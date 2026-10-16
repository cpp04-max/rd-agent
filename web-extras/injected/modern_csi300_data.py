from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from filelock import FileLock

DATA_ROOT = Path(os.environ.get("RDAGENT_MARKET_DATA_ROOT", "/data/market/csi300"))
MODERN_QLIB_ROOT = Path(os.environ.get("RDAGENT_MODERN_QLIB_DIR", "/data/qlib/csi300_modern"))
INDEX_CODE = os.environ.get("RDAGENT_CSI300_INDEX_CODE", "000300.SH")
INDEX_CODE_FALLBACK = "399300.SZ"

REQUIRED_FAMILIES = ("price_volume", "csi300_membership")
DEFAULT_OPTIONAL_FAMILIES = ("daily_basic", "trading_status", "industry", "market_context")
DEFAULT_FAMILIES = list(REQUIRED_FAMILIES + DEFAULT_OPTIONAL_FAMILIES)

MODERN_SPLIT = {
    "train_start": "2008-01-01",
    "train_end": "2021-12-31",
    "valid_start": "2022-01-01",
    "valid_end": "2023-12-31",
    "test_start": "2024-01-01",
    "test_end": None,
}

FAMILY_CATALOG: dict[str, dict[str, Any]] = {
    "price_volume": {
        "label": "Daily price / volume",
        "description": "Adjusted OHLCV, amount and adjustment factor for historical CSI300 members.",
        "source": "Tushare daily + adj_factor",
        "required": True,
        "required_points": 2000,
        "fields": ["$open", "$close", "$high", "$low", "$volume", "$factor", "$amount"],
        "model_features": {},
    },
    "csi300_membership": {
        "label": "Point-in-time CSI300 membership",
        "description": "Historical monthly constituent membership and weights; prevents current-universe survivorship bias.",
        "source": "Tushare index_weight",
        "required": True,
        "required_points": 2000,
        "fields": ["$csi300_weight"],
        "model_features": {"CSI300_WEIGHT": "$csi300_weight"},
    },
    "daily_basic": {
        "label": "Daily valuation & liquidity",
        "description": "Turnover, volume ratio, valuation, shares and market-cap variables.",
        "source": "Tushare daily_basic",
        "required": False,
        "required_points": 2000,
        "fields": [
            "$db_turnover_rate", "$db_turnover_rate_f", "$db_volume_ratio",
            "$db_pe_ttm", "$db_pb", "$db_ps_ttm", "$db_dv_ttm",
            "$db_total_mv", "$db_circ_mv", "$db_free_share",
        ],
        "model_features": {
            "DB_TURNOVER": "$db_turnover_rate",
            "DB_FREE_TURNOVER": "$db_turnover_rate_f",
            "DB_VOLUME_RATIO": "$db_volume_ratio",
            "DB_PE_TTM": "$db_pe_ttm",
            "DB_PB": "$db_pb",
            "DB_PS_TTM": "$db_ps_ttm",
            "DB_DIV_YIELD_TTM": "$db_dv_ttm",
            "DB_LOG_TOTAL_MV": "Log($db_total_mv+1)",
            "DB_LOG_CIRC_MV": "Log($db_circ_mv+1)",
        },
    },
    "trading_status": {
        "label": "Trading / suspension status",
        "description": "Daily suspension flag from the official stop/resume record; useful for tradability and missing-price interpretation.",
        "source": "Tushare suspend_d",
        "required": False,
        "required_points": 2000,
        "fields": ["$is_suspended"],
        "model_features": {"IS_SUSPENDED": "$is_suspended"},
    },
    "intraday_market": {
        "label": "CSI300 intraday market context",
        "description": "Daily features derived from CSI300 5-minute bars: realized volatility, intraday range, last-30-minute return and last-hour volume share.",
        "source": "Tushare idx_mins (5min)",
        "required": False,
        "required_points": None,
        "permission": "separate historical index-minute permission",
        "fields": ["$idx5m_rv", "$idx5m_range", "$idx5m_last30", "$idx5m_last_hour_vol_share"],
        "model_features": {
            "IDX5M_RV": "$idx5m_rv",
            "IDX5M_RANGE": "$idx5m_range",
            "IDX5M_LAST30": "$idx5m_last30",
            "IDX5M_LAST_HOUR_VOL_SHARE": "$idx5m_last_hour_vol_share",
        },
    },
    "industry": {
        "label": "Point-in-time industry context",
        "description": "Historical Shenwan L1 membership plus industry return and stock-vs-industry relative return.",
        "source": "Tushare index_member_all",
        "required": False,
        "required_points": 2000,
        "fields": ["$industry_l1_id", "$industry_return_1d", "$industry_rel_return_1d"],
        "model_features": {
            "INDUSTRY_RETURN_1D": "$industry_return_1d",
            "INDUSTRY_REL_RETURN_1D": "$industry_rel_return_1d",
        },
    },
    "market_context": {
        "label": "CSI300 market context",
        "description": "Index level, daily return, 20-day momentum and realized volatility broadcast to each constituent.",
        "source": "Tushare index_daily",
        "required": False,
        "required_points": 2000,
        "fields": ["$mkt_return_1d", "$mkt_mom20", "$mkt_vol20", "$mkt_amount_log"],
        "model_features": {
            "MKT_RETURN_1D": "$mkt_return_1d",
            "MKT_MOM20": "$mkt_mom20",
            "MKT_VOL20": "$mkt_vol20",
            "MKT_AMOUNT_LOG": "$mkt_amount_log",
        },
    },
    "if_futures": {
        "label": "CSI300 IF futures",
        "description": "Main-contract IF return, basis, volume and open-interest context.",
        "source": "Tushare fut_mapping + fut_daily",
        "required": False,
        "required_points": 2000,
        "fields": ["$if_return_1d", "$if_basis", "$if_vol_log", "$if_oi_log"],
        "model_features": {
            "IF_RETURN_1D": "$if_return_1d",
            "IF_BASIS": "$if_basis",
            "IF_VOL_LOG": "$if_vol_log",
            "IF_OI_LOG": "$if_oi_log",
        },
    },
    "fundamentals": {
        "label": "Point-in-time fundamentals",
        "description": "Financial indicators joined only from their announcement date to avoid look-ahead.",
        "source": "Tushare fina_indicator",
        "required": False,
        "required_points": 2000,
        "fields": [
            "$fi_eps", "$fi_roe", "$fi_roa", "$fi_grossprofit_margin",
            "$fi_debt_to_assets", "$fi_current_ratio", "$fi_netprofit_yoy",
            "$fi_q_sales_yoy", "$fi_q_profit_yoy",
        ],
        "model_features": {
            "FI_EPS": "$fi_eps",
            "FI_ROE": "$fi_roe",
            "FI_ROA": "$fi_roa",
            "FI_GROSS_MARGIN": "$fi_grossprofit_margin",
            "FI_DEBT_TO_ASSETS": "$fi_debt_to_assets",
            "FI_CURRENT_RATIO": "$fi_current_ratio",
            "FI_NETPROFIT_YOY": "$fi_netprofit_yoy",
            "FI_Q_SALES_YOY": "$fi_q_sales_yoy",
            "FI_Q_PROFIT_YOY": "$fi_q_profit_yoy",
        },
    },
    "money_flow": {
        "label": "Stock money flow",
        "description": "Small/large/extra-large active-order flow ratios and net money-flow ratio (available from 2010).",
        "source": "Tushare moneyflow",
        "required": False,
        "required_points": 2000,
        "fields": ["$mf_net_ratio", "$mf_large_net_ratio", "$mf_small_net_ratio"],
        "model_features": {
            "MF_NET_RATIO": "$mf_net_ratio",
            "MF_LARGE_NET_RATIO": "$mf_large_net_ratio",
            "MF_SMALL_NET_RATIO": "$mf_small_net_ratio",
        },
    },
    "margin": {
        "label": "Margin financing / securities lending",
        "description": "Daily financing balance, securities-lending balance and financing-buy intensity.",
        "source": "Tushare margin_detail",
        "required": False,
        "required_points": 2000,
        "fields": ["$margin_rzrqye_log", "$margin_rqye_log", "$margin_rzmre_log"],
        "model_features": {
            "MARGIN_BALANCE_LOG": "$margin_rzrqye_log",
            "MARGIN_SHORT_BAL_LOG": "$margin_rqye_log",
            "MARGIN_BUY_LOG": "$margin_rzmre_log",
        },
    },
    "northbound": {
        "label": "Northbound holdings",
        "description": "Historical Stock Connect holding ratio / holding volume when available from the Tushare account.",
        "source": "Tushare hk_hold",
        "required": False,
        "required_points": 3000,
        "permission": "legacy holding endpoint when available; modern Stock Connect list fallback from 2025-08",
        "fields": ["$north_eligible", "$north_hold_ratio", "$north_hold_logvol"],
        "model_features": {
            "NORTH_ELIGIBLE": "$north_eligible",
            "NORTH_HOLD_RATIO": "$north_hold_ratio",
            "NORTH_HOLD_LOGVOL": "$north_hold_logvol",
        },
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yyyymmdd(value: str | pd.Timestamp | None) -> str:
    if value is None:
        return pd.Timestamp.utcnow().strftime("%Y%m%d")
    return pd.Timestamp(value).strftime("%Y%m%d")


def _dash_date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _to_qlib_symbol(ts_code: str) -> str:
    raw = str(ts_code or "").strip().upper()
    if "." not in raw:
        return raw
    code, exch = raw.split(".", 1)
    if exch in {"SH", "SSE"}:
        return f"SH{code}"
    if exch in {"SZ", "SZSE"}:
        return f"SZ{code}"
    if exch in {"BJ", "BSE"}:
        return f"BJ{code}"
    return f"{exch}{code}"


def _safe_symbol(ts_code: str) -> str:
    return str(ts_code).replace(".", "_").replace("/", "_")


def _family_set(config: dict[str, Any]) -> list[str]:
    requested = [str(x) for x in config.get("families", [])]
    unknown = sorted(set(requested) - set(FAMILY_CATALOG))
    if unknown:
        raise ValueError(f"Unknown dataset families: {unknown}")
    selected = []
    for name in REQUIRED_FAMILIES:
        if name not in selected:
            selected.append(name)
    for name in requested:
        if name not in selected:
            selected.append(name)
    return selected


def normalize_dataset_config(raw: Any = None) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    if not isinstance(raw, dict):
        raise ValueError("dataset_config must be a JSON object")

    mode = str(raw.get("mode") or "legacy").strip().lower()
    if mode not in {"legacy", "modern"}:
        raise ValueError("dataset mode must be 'legacy' or 'modern'")

    if mode == "legacy":
        return {
            "mode": "legacy",
            "families": [],
            "split": {
                "train_start": "2008-01-01",
                "train_end": "2014-12-31",
                "valid_start": "2015-01-01",
                "valid_end": "2016-12-31",
                "test_start": "2017-01-01",
                "test_end": "2020-08-01",
            },
            "provider_uri": str(Path("~/.qlib/qlib_data/cn_data").expanduser()),
        }

    families = _family_set({
        "families": raw.get("families") or DEFAULT_FAMILIES,
    })
    split = dict(MODERN_SPLIT)
    if isinstance(raw.get("split"), dict):
        for key in split:
            value = raw["split"].get(key)
            if value:
                split[key] = _dash_date(value)

    return {
        "mode": "modern",
        "families": families,
        "split": split,
        "start_date": _dash_date(raw.get("start_date") or split["train_start"]),
        "as_of_date": _dash_date(raw.get("as_of_date") or pd.Timestamp.utcnow().date()),
        "provider_uri": raw.get("provider_uri"),
        "resolved_end": raw.get("resolved_end"),
        "manifest_path": raw.get("manifest_path"),
        "source": "tushare",
    }


def dataset_catalog() -> dict[str, Any]:
    manifest = None
    latest = DATA_ROOT / "latest_manifest.json"
    if latest.exists():
        try:
            manifest = json.loads(latest.read_text(encoding="utf-8"))
        except Exception:
            manifest = None

    families = []
    for key, value in FAMILY_CATALOG.items():
        item = dict(value)
        item["id"] = key
        item["default"] = key in DEFAULT_FAMILIES
        families.append(item)

    return {
        "token_configured": bool(os.environ.get("TUSHARE_TOKEN", "").strip()),
        "families": families,
        "default_families": list(DEFAULT_FAMILIES),
        "required_families": list(REQUIRED_FAMILIES),
        "modern_split": dict(MODERN_SPLIT),
        "legacy_split": {
            "train_start": "2008-01-01",
            "train_end": "2014-12-31",
            "valid_start": "2015-01-01",
            "valid_end": "2016-12-31",
            "test_start": "2017-01-01",
            "test_end": "2020-08-01",
        },
        "latest_manifest": manifest,
        "data_root": str(DATA_ROOT),
        "modern_qlib_root": str(MODERN_QLIB_ROOT),
    }



_PREVIEW_TTL_SECONDS = int(os.environ.get("RDAGENT_DATA_PREVIEW_TTL_SECONDS", "900"))
_PREVIEW_ROWS = max(1, min(20, int(os.environ.get("RDAGENT_DATA_PREVIEW_ROWS", "5"))))

_PREVIEW_PIT_NOTES = {
    "price_volume": "Daily bar information is intended for prediction after that trading day's close. Adjustment factors are merged by trade_date.",
    "csi300_membership": "Uses historical CSI300 snapshots instead of today's members, preventing current-universe survivorship leakage.",
    "daily_basic": "Daily valuation/liquidity snapshot. Use day-t values only for predictions made after the day-t close.",
    "trading_status": "Official suspension/resumption records. Suspended dates remain explicit and prices are not forward-filled.",
    "intraday_market": "Aggregated from same-day CSI300 5-minute bars. These features are only valid after the source bars have occurred.",
    "industry": "Industry membership is bounded by in_date/out_date rather than backfilling today's classification through history.",
    "market_context": "CSI300 market context is calculated from contemporaneous index history and is suitable for next-session targets when lagged by the experiment design.",
    "if_futures": "Main-contract IF context is aligned by trade_date; the preview reports contract and derived market-context fields where available.",
    "fundamentals": "Financial indicators enter the model from ann_date, never from the fiscal period end date.",
    "money_flow": "Daily active-order flow aggregates are post-trade information for that session.",
    "margin": "Daily financing/securities-lending values are aligned by trade_date.",
    "northbound": "Holding data are used when the legacy endpoint is available; newer Stock Connect eligibility is kept distinct from holding size.",
}

_PREVIEW_COLUMNS = {
    "price_volume": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "adj_factor"],
    "csi300_membership": ["index_code", "con_code", "trade_date", "weight"],
    "daily_basic": [
        "ts_code", "trade_date", "turnover_rate", "turnover_rate_f", "volume_ratio",
        "pe_ttm", "pb", "ps_ttm", "dv_ttm", "total_mv", "circ_mv",
    ],
    "trading_status": ["ts_code", "trade_date", "suspend_timing", "suspend_type"],
    "intraday_market": ["datetime", "$idx5m_rv", "$idx5m_range", "$idx5m_last30", "$idx5m_last_hour_vol_share"],
    "industry": ["ts_code", "name", "l1_code", "l1_name", "in_date", "out_date", "is_new"],
    "market_context": ["datetime", "$mkt_return_1d", "$mkt_mom20", "$mkt_vol20", "$mkt_amount_log"],
    "if_futures": [
        "trade_date", "mapping_ts_code", "close", "vol", "oi",
        "$if_return_1d", "$if_basis", "$if_vol_log", "$if_oi_log",
    ],
    "fundamentals": [
        "ts_code", "ann_date", "end_date", "eps", "roe", "roa", "grossprofit_margin",
        "debt_to_assets", "current_ratio", "netprofit_yoy", "q_sales_yoy", "q_profit_yoy",
    ],
    "money_flow": [
        "ts_code", "trade_date", "buy_sm_amount", "sell_sm_amount",
        "buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount",
        "net_mf_amount",
    ],
    "margin": ["ts_code", "trade_date", "rzrqye", "rqye", "rzmre", "rqmcl"],
    "northbound": ["ts_code", "trade_date", "name", "eligible", "ratio", "vol", "type", "type_name"],
}


def _preview_json_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _preview_sort_column(df: pd.DataFrame) -> str | None:
    for column in (
        "trade_time", "datetime", "trade_date", "ann_date",
        "end_date", "in_date", "out_date",
    ):
        if column in df.columns and df[column].notna().any():
            return column
    return None


def _preview_frame_payload(
    family: str,
    frame: pd.DataFrame,
    *,
    row_count: int = _PREVIEW_ROWS,
) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"columns": [], "rows": [], "as_of": None}

    data = frame.copy()
    sort_col = _preview_sort_column(data)
    if sort_col is not None:
        sort_values = pd.to_datetime(data[sort_col].astype(str), errors="coerce")
        data = data.assign(__preview_sort=sort_values).sort_values(
            "__preview_sort", ascending=False, na_position="last"
        ).drop(columns=["__preview_sort"])

    preferred = [
        column for column in _PREVIEW_COLUMNS.get(family, [])
        if column in data.columns
    ]
    if preferred:
        data = data[preferred]
    else:
        data = data.iloc[:, : min(14, len(data.columns))]

    data = data.head(row_count)
    rows = [
        {str(column): _preview_json_value(value) for column, value in row.items()}
        for row in data.to_dict(orient="records")
    ]

    as_of = None
    if sort_col is not None and sort_col in frame.columns:
        parsed = pd.to_datetime(frame[sort_col].astype(str), errors="coerce").dropna()
        if not parsed.empty:
            as_of = parsed.max().isoformat()

    return {
        "columns": [str(column) for column in data.columns],
        "rows": rows,
        "as_of": as_of,
    }


def _preview_raw_root(family: str) -> Path:
    return DATA_ROOT / "raw" / family


def _cached_family_preview(family: str) -> dict[str, Any]:
    root = _preview_raw_root(family)
    if not root.exists():
        return {
            "cached_files": 0,
            "sample": {"columns": [], "rows": [], "as_of": None},
            "representative_symbol": None,
        }

    paths = list(root.glob("*.parquet"))
    if family == "price_volume":
        daily = [path for path in paths if path.name.endswith("_daily.parquet")]
        if daily:
            paths = daily
    paths = sorted(
        paths,
        key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
        reverse=True,
    )

    frames = []
    representative_symbol = None
    for path in paths[:4]:
        frame = _load_parquet(path)
        if frame.empty:
            continue
        frames.append(frame)
        if representative_symbol is None and "ts_code" in frame.columns:
            symbols = frame["ts_code"].dropna().astype(str)
            if not symbols.empty:
                representative_symbol = symbols.iloc[0]
        if sum(len(item) for item in frames) >= 50:
            break

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if family == "market_context" and not combined.empty:
        try:
            combined = _build_index_context(combined)
        except Exception:
            pass
    elif family == "intraday_market" and not combined.empty:
        try:
            combined = _build_intraday_market_context(combined)
        except Exception:
            pass

    return {
        "cached_files": len(paths),
        "sample": _preview_frame_payload(family, combined),
        "representative_symbol": representative_symbol,
    }


def _preview_cache_file(family: str) -> Path:
    path = DATA_ROOT / "preview"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{family}.json"


def _read_preview_cache(family: str) -> dict[str, Any] | None:
    path = _preview_cache_file(family)
    if not path.exists():
        return None
    try:
        if (time.time() - path.stat().st_mtime) > _PREVIEW_TTL_SECONDS:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _write_preview_cache(family: str, payload: dict[str, Any]) -> None:
    path = _preview_cache_file(family)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def _preview_trade_days(pro, lookback_days: int = 60) -> list[pd.Timestamp]:
    end = pd.Timestamp.utcnow().tz_localize(None).normalize()
    start = end - pd.Timedelta(days=max(lookback_days, 20))
    frame = _request(
        pro,
        "trade_cal",
        exchange="SSE",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        is_open="1",
        fields="exchange,cal_date,is_open,pretrade_date",
    )
    if frame.empty:
        return []
    dates = pd.to_datetime(frame["cal_date"].astype(str), errors="coerce").dropna()
    return sorted(pd.Timestamp(value).normalize() for value in dates.unique())


def _preview_membership_snapshot(pro, end_date: str) -> pd.DataFrame:
    end = pd.Timestamp(end_date)
    frame = pd.DataFrame()
    for days in (45, 120):
        start = (end - pd.Timedelta(days=days)).strftime("%Y%m%d")
        frame = _request(
            pro,
            "index_weight",
            index_code=INDEX_CODE,
            start_date=start,
            end_date=end.strftime("%Y%m%d"),
            fields="index_code,con_code,trade_date,weight",
        )
        if frame.empty and INDEX_CODE != INDEX_CODE_FALLBACK:
            frame = _request(
                pro,
                "index_weight",
                index_code=INDEX_CODE_FALLBACK,
                start_date=start,
                end_date=end.strftime("%Y%m%d"),
                fields="index_code,con_code,trade_date,weight",
            )
        if not frame.empty:
            break
    if frame.empty:
        return frame
    latest = str(frame["trade_date"].astype(str).max())
    current = frame.loc[frame["trade_date"].astype(str) == latest].copy()
    current["weight"] = pd.to_numeric(current.get("weight"), errors="coerce")
    return current.sort_values(["weight", "con_code"], ascending=[False, True])


def _preview_representative_symbol(pro, end_date: str) -> tuple[str | None, pd.DataFrame]:
    membership = _preview_membership_snapshot(pro, end_date)
    if membership.empty:
        return None, membership
    symbols = membership["con_code"].dropna().astype(str)
    return (symbols.iloc[0] if not symbols.empty else None), membership


def _live_family_preview(family: str) -> dict[str, Any]:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured.")

    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError("The tushare Python package is not installed.") from exc

    pro = ts.pro_api(token)
    # A preview must not require an unrelated privileged endpoint merely to discover
    # "today's" trading date. Query the selected family over a recent calendar window;
    # Tushare naturally returns only dates for which that endpoint has observations.
    latest = pd.Timestamp.utcnow().tz_localize(None).normalize()
    end_date = latest.strftime("%Y%m%d")
    start_45 = (latest - pd.Timedelta(days=45)).strftime("%Y%m%d")
    start_90 = (latest - pd.Timedelta(days=90)).strftime("%Y%m%d")
    representative_symbol = os.environ.get(
        "RDAGENT_DATA_PREVIEW_SYMBOL", "600519.SH"
    ).strip() or "600519.SH"
    note = None

    if family == "csi300_membership":
        frame = _preview_membership_snapshot(pro, end_date)

    elif family == "market_context":
        frame = _request(
            pro,
            "index_daily",
            ts_code=INDEX_CODE,
            start_date=start_90,
            end_date=end_date,
            fields="ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount",
        )
        if frame.empty and INDEX_CODE != INDEX_CODE_FALLBACK:
            frame = _request(
                pro,
                "index_daily",
                ts_code=INDEX_CODE_FALLBACK,
                start_date=start_90,
                end_date=end_date,
                fields="ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount",
            )
        frame = _build_index_context(frame) if not frame.empty else frame

    elif family == "intraday_market":
        frame = pd.DataFrame()
        last_error = None
        recent_calendar_days = [
            latest - pd.Timedelta(days=offset)
            for offset in range(0, 10)
        ]
        for day in recent_calendar_days:
            kwargs = {
                "ts_code": INDEX_CODE,
                "freq": "5min",
                "start_date": f"{day:%Y-%m-%d} 09:00:00",
                "end_date": f"{day:%Y-%m-%d} 16:00:00",
                "fields": "ts_code,trade_time,open,close,high,low,vol,amount",
            }
            try:
                bars = _request(pro, "idx_mins", **kwargs)
                if bars.empty and INDEX_CODE != INDEX_CODE_FALLBACK:
                    kwargs["ts_code"] = INDEX_CODE_FALLBACK
                    bars = _request(pro, "idx_mins", **kwargs)
                if not bars.empty:
                    frame = _build_intraday_market_context(bars)
                    break
            except Exception as exc:
                last_error = exc
                break
        if frame.empty and last_error is not None:
            raise RuntimeError(
                "Historical CSI300 minute preview is unavailable for this account: "
                f"{last_error}"
            ) from last_error

    elif family == "if_futures":
        mapping = _request(
            pro,
            "fut_mapping",
            ts_code="IF.CFX",
            start_date=start_45,
            end_date=end_date,
            fields="ts_code,trade_date,mapping_ts_code",
        )
        if mapping.empty:
            frame = mapping
        else:
            mapping = mapping.sort_values("trade_date")
            contracts = list(
                mapping["mapping_ts_code"].dropna().astype(str).unique()
            )[-2:]
            fut_frames = []
            for contract in contracts:
                part = _request(
                    pro,
                    "fut_daily",
                    ts_code=contract,
                    start_date=start_45,
                    end_date=end_date,
                    fields="ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,vol,amount,oi,oi_chg",
                )
                if not part.empty:
                    fut_frames.append(part)
            fut = pd.concat(fut_frames, ignore_index=True) if fut_frames else pd.DataFrame()
            merged = (
                mapping.merge(
                    fut,
                    left_on=["trade_date", "mapping_ts_code"],
                    right_on=["trade_date", "ts_code"],
                    how="left",
                    suffixes=("", "_contract"),
                )
                if not fut.empty else mapping
            )
            index_df = _request(
                pro,
                "index_daily",
                ts_code=INDEX_CODE,
                start_date=start_45,
                end_date=end_date,
                fields="ts_code,trade_date,close,amount",
            )
            if not fut.empty and not index_df.empty:
                context = _build_futures_context(merged, index_df)
                frame = merged.merge(
                    context,
                    left_on=pd.to_datetime(merged["trade_date"].astype(str)),
                    right_on="datetime",
                    how="left",
                ).drop(columns=["key_0"], errors="ignore")
            else:
                frame = merged

    else:
        if family == "price_volume":
            daily = _request(
                pro,
                "daily",
                ts_code=representative_symbol,
                start_date=start_45,
                end_date=end_date,
                fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            )
            adj = pd.DataFrame()
            adj_error = None
            try:
                adj = _request(
                    pro,
                    "adj_factor",
                    ts_code=representative_symbol,
                    start_date=start_45,
                    end_date=end_date,
                    fields="ts_code,trade_date,adj_factor",
                )
            except RuntimeError as exc:
                adj_error = str(exc)
            frame = daily.merge(
                adj[["trade_date", "adj_factor"]] if not adj.empty
                else pd.DataFrame(columns=["trade_date", "adj_factor"]),
                on="trade_date",
                how="left",
            ) if not daily.empty else daily
            if adj_error:
                note = (
                    "Raw daily prices are accessible, but the adjustment-factor endpoint "
                    "is not available for this account. Full Modern CSI300 price_volume "
                    f"still requires adj_factor access. {adj_error}"
                )

        elif family == "daily_basic":
            frame = _request(
                pro,
                "daily_basic",
                ts_code=representative_symbol,
                start_date=start_45,
                end_date=end_date,
                fields=(
                    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
                    "pe_ttm,pb,ps_ttm,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv"
                ),
            )

        elif family == "trading_status":
            try:
                frame = _request(
                    pro,
                    "suspend_d",
                    start_date=(latest - pd.Timedelta(days=180)).strftime("%Y%m%d"),
                    end_date=end_date,
                    fields="ts_code,trade_date,suspend_timing,suspend_type",
                )
            except Exception:
                frame = _request(
                    pro,
                    "suspend_d",
                    ts_code=representative_symbol,
                    start_date=(latest - pd.Timedelta(days=365)).strftime("%Y%m%d"),
                    end_date=end_date,
                    fields="ts_code,trade_date,suspend_timing,suspend_type",
                )
            if frame.empty:
                note = "No suspension events were returned in the recent preview window."

        elif family == "industry":
            frames = []
            for is_new in ("Y", "N"):
                part = _request(
                    pro,
                    "index_member_all",
                    ts_code=representative_symbol,
                    is_new=is_new,
                    fields="l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new",
                )
                if not part.empty:
                    frames.append(part)
            frame = (
                pd.concat(frames, ignore_index=True).drop_duplicates()
                if frames else pd.DataFrame()
            )

        elif family == "fundamentals":
            frame = _request(
                pro,
                "fina_indicator",
                ts_code=representative_symbol,
                start_date=(latest - pd.Timedelta(days=800)).strftime("%Y%m%d"),
                end_date=end_date,
                fields=(
                    "ts_code,ann_date,end_date,eps,roe,roa,grossprofit_margin,"
                    "debt_to_assets,current_ratio,netprofit_yoy,q_sales_yoy,q_profit_yoy,update_flag"
                ),
            )

        elif family == "money_flow":
            frame = _request(
                pro,
                "moneyflow",
                ts_code=representative_symbol,
                start_date=start_90,
                end_date=end_date,
                fields=(
                    "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,"
                    "buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount"
                ),
            )

        elif family == "margin":
            frame = _request(
                pro,
                "margin_detail",
                ts_code=representative_symbol,
                start_date=start_90,
                end_date=end_date,
                fields="trade_date,ts_code,rzye,rqye,rzmre,rqyl,rzche,rqchl,rqmcl,rzrqye",
            )

        elif family == "northbound":
            frame = pd.DataFrame()
            try:
                frame = _request(
                    pro,
                    "hk_hold",
                    ts_code=representative_symbol,
                    start_date=(latest - pd.Timedelta(days=180)).strftime("%Y%m%d"),
                    end_date=end_date,
                    fields="code,trade_date,ts_code,name,vol,ratio,exchange",
                )
                if not frame.empty:
                    frame["eligible"] = 1.0
            except Exception:
                frame = pd.DataFrame()
            if frame.empty:
                fallback_start = max(
                    pd.Timestamp("2025-08-12"),
                    latest - pd.Timedelta(days=180),
                ).strftime("%Y%m%d")
                frames = []
                for connect_type in ("HK_SH", "HK_SZ"):
                    try:
                        part = _request(
                            pro,
                            "stock_hsgt",
                            ts_code=representative_symbol,
                            type=connect_type,
                            start_date=fallback_start,
                            end_date=end_date,
                            fields="ts_code,trade_date,type,name,type_name",
                        )
                    except Exception:
                        part = pd.DataFrame()
                    if not part.empty:
                        frames.append(part)
                frame = (
                    pd.concat(frames, ignore_index=True).drop_duplicates(
                        ["trade_date", "ts_code"], keep="last"
                    )
                    if frames else pd.DataFrame()
                )
                if not frame.empty:
                    frame["eligible"] = 1.0
                    frame["ratio"] = np.nan
                    frame["vol"] = np.nan
                    note = "Showing modern Stock Connect eligibility; holding size is unavailable from this fallback endpoint."

        else:
            raise ValueError(f"Unsupported dataset preview family: {family}")

    sample = _preview_frame_payload(family, frame)
    return {
        "sample": sample,
        "representative_symbol": representative_symbol,
        "note": note,
        "fetched_at": _now_iso(),
    }


def dataset_family_preview(family: str, *, force: bool = False) -> dict[str, Any]:
    family = str(family or "").strip()
    if family not in FAMILY_CATALOG:
        raise ValueError(f"Unknown dataset family: {family or '<empty>'}")

    metadata = dict(FAMILY_CATALOG[family])
    cached = _cached_family_preview(family)
    latest_manifest = None
    latest_manifest_path = DATA_ROOT / "latest_manifest.json"
    if latest_manifest_path.exists():
        try:
            latest_manifest = json.loads(
                latest_manifest_path.read_text(encoding="utf-8")
            )
        except Exception:
            latest_manifest = None

    build_info = {
        "included_in_latest_build": bool(
            isinstance(latest_manifest, dict)
            and family in latest_manifest.get("families", [])
        ),
        "latest_build_through": (
            latest_manifest.get("resolved_end")
            if isinstance(latest_manifest, dict) else None
        ),
        "latest_build_stock_count": (
            latest_manifest.get("stock_count")
            if isinstance(latest_manifest, dict) else None
        ),
    }

    preview_error = None
    live = None if force else _read_preview_cache(family)
    if live is None and os.environ.get("TUSHARE_TOKEN", "").strip():
        lock = FileLock(str(_preview_cache_file(family)) + ".lock")
        with lock:
            live = None if force else _read_preview_cache(family)
            if live is None:
                try:
                    live = _live_family_preview(family)
                    _write_preview_cache(family, live)
                except Exception as exc:
                    preview_error = str(exc)
                    lowered = preview_error.lower()
                    if (
                        "访问权限" in preview_error
                        or "permission denied" in lowered
                        or "access denied" in lowered
                    ):
                        requirement = metadata.get("permission")
                        if not requirement and metadata.get("required_points"):
                            requirement = f"{metadata['required_points']}+ Tushare points"
                        preview_error = (
                            f"{metadata.get('label') or family} is not enabled for the "
                            f"current Tushare account"
                            + (f" (requires {requirement})" if requirement else "")
                            + f". {preview_error}"
                        )

    if live and live.get("sample", {}).get("rows"):
        sample = live["sample"]
        sample_source = "Tushare live preview"
        representative_symbol = live.get("representative_symbol")
        sample_note = live.get("note")
        fetched_at = live.get("fetched_at")
    elif cached["sample"].get("rows"):
        sample = cached["sample"]
        sample_source = "persistent raw-data cache"
        representative_symbol = cached.get("representative_symbol")
        sample_note = (
            "Live preview was unavailable; showing the newest locally cached rows."
            if preview_error else
            "Showing the newest locally cached rows."
        )
        fetched_at = None
    else:
        sample = {"columns": [], "rows": [], "as_of": None}
        sample_source = None
        representative_symbol = None
        sample_note = None
        fetched_at = None
        if preview_error is None and not os.environ.get("TUSHARE_TOKEN", "").strip():
            preview_error = (
                "No cached sample is available and TUSHARE_TOKEN is not configured."
            )

    return {
        "family": family,
        "label": metadata.get("label"),
        "description": metadata.get("description"),
        "source": metadata.get("source"),
        "required": bool(metadata.get("required")),
        "required_points": metadata.get("required_points"),
        "permission": metadata.get("permission"),
        "qlib_fields": list(metadata.get("fields", [])),
        "model_features": dict(metadata.get("model_features", {})),
        "point_in_time_note": _PREVIEW_PIT_NOTES.get(family),
        "token_configured": bool(os.environ.get("TUSHARE_TOKEN", "").strip()),
        "cache": {
            "raw_files": cached.get("cached_files", 0),
            **build_info,
        },
        "sample": sample,
        "sample_source": sample_source,
        "sample_as_of": sample.get("as_of"),
        "representative_symbol": representative_symbol,
        "sample_note": sample_note,
        "fetched_at": fetched_at,
        "preview_error": preview_error,
    }


def qlib_fields_for_config(config: dict[str, Any]) -> list[str]:
    if config.get("mode") != "modern":
        return ["$open", "$close", "$high", "$low", "$volume", "$factor"]
    fields: list[str] = []
    for family in _family_set(config):
        for field in FAMILY_CATALOG[family].get("fields", []):
            if field not in fields:
                fields.append(field)
    return fields


def model_features_for_config(config: dict[str, Any]) -> dict[str, str]:
    features: dict[str, str] = {}
    if config.get("mode") != "modern":
        return features
    for family in _family_set(config):
        features.update(FAMILY_CATALOG[family].get("model_features", {}))
    return features


def _raw_path(family: str, key: str) -> Path:
    path = DATA_ROOT / "raw" / family
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{key}.parquet"


def _load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def _request(pro, endpoint: str, *, fields: str | None = None, **kwargs) -> pd.DataFrame:
    interval = float(os.environ.get("TUSHARE_REQUEST_INTERVAL_SECONDS", "0.14"))
    retries = int(os.environ.get("TUSHARE_REQUEST_RETRIES", "4"))
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            fn = getattr(pro, endpoint, None)
            if fn is None:
                call_kwargs = dict(kwargs)
                if fields:
                    call_kwargs["fields"] = fields
                result = pro.query(endpoint, **call_kwargs)
            else:
                if fields:
                    kwargs = {**kwargs, "fields": fields}
                result = fn(**kwargs)
            time.sleep(max(0.0, interval))
            if result is None:
                return pd.DataFrame()
            return result
        except Exception as exc:
            last_exc = exc
            message = str(exc)
            permission_markers = (
                "没有接口",
                "访问权限",
                "权限",
                "permission",
                "access denied",
                "AccessDenied",
            )
            if any(marker.lower() in message.lower() for marker in permission_markers):
                raise RuntimeError(
                    f"Tushare endpoint '{endpoint}' permission denied: {message}"
                ) from exc
            if attempt >= retries:
                break
            delay = min(8.0, 0.8 * (2 ** (attempt - 1)))
            print(
                f"[modern-data] {endpoint} attempt {attempt}/{retries} failed: {exc}; retrying in {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"Tushare endpoint '{endpoint}' failed after {retries} attempts: {last_exc}"
    ) from last_exc


def _cache_full_history(
    pro,
    family: str,
    key: str,
    endpoint: str,
    *,
    start_date: str,
    end_date: str,
    fields: str | None = None,
    refresh_current: bool = False,
    **kwargs,
) -> pd.DataFrame:
    path = _raw_path(family, key)
    cached = _load_parquet(path)
    if not cached.empty and not refresh_current:
        date_col = "trade_date" if "trade_date" in cached.columns else None
        if date_col is not None:
            max_date = str(cached[date_col].dropna().astype(str).max() or "")
            if max_date >= end_date:
                return cached
        else:
            return cached

    print(f"[modern-data] downloading {family}/{key} ...", flush=True)
    df = _request(
        pro,
        endpoint,
        fields=fields,
        start_date=start_date,
        end_date=end_date,
        **kwargs,
    )
    if not df.empty:
        _save_parquet(df, path)
    elif not cached.empty:
        return cached
    return df


def _fetch_calendar(pro, start_date: str, end_date: str) -> list[pd.Timestamp]:
    path = _raw_path("calendar", f"{start_date}_{end_date}")
    cached = _load_parquet(path)
    if cached.empty:
        df = pd.DataFrame()
        trade_cal_error = None
        try:
            df = _request(
                pro,
                "trade_cal",
                exchange="SSE",
                start_date=start_date,
                end_date=end_date,
                is_open="1",
                fields="exchange,cal_date,is_open,pretrade_date",
            )
        except RuntimeError as exc:
            trade_cal_error = exc
            print(
                "[modern-data] trade_cal unavailable; deriving the trading calendar "
                f"from CSI300 index_daily instead: {exc}",
                flush=True,
            )

        if not df.empty:
            cached = df
        else:
            try:
                index_df = _fetch_index_daily(pro, start_date, end_date)
            except Exception as index_exc:
                detail = (
                    f"trade_cal error: {trade_cal_error}; " if trade_cal_error else ""
                )
                raise RuntimeError(
                    "Could not resolve the China trading calendar. "
                    f"{detail}index_daily fallback error: {index_exc}"
                ) from index_exc
            dates = pd.to_datetime(
                index_df["trade_date"].astype(str), errors="coerce"
            ).dropna()
            if dates.empty:
                raise RuntimeError(
                    "CSI300 index_daily fallback returned no usable trading dates."
                )
            cached = pd.DataFrame(
                {
                    "exchange": "SSE",
                    "cal_date": dates.dt.strftime("%Y%m%d"),
                    "is_open": "1",
                    "pretrade_date": None,
                    "calendar_source": "index_daily",
                }
            ).drop_duplicates("cal_date", keep="last")
        _save_parquet(cached, path)

    if "cal_date" not in cached.columns:
        raise RuntimeError("Cached trading calendar is missing cal_date.")
    if "is_open" in cached.columns:
        open_mask = cached["is_open"].astype(str) == "1"
    else:
        open_mask = pd.Series(True, index=cached.index)
    days = pd.to_datetime(
        cached.loc[open_mask, "cal_date"].astype(str), errors="coerce"
    ).dropna()
    return sorted(pd.Timestamp(x).normalize() for x in days.unique())


def _month_ranges(start_date: str, end_date: str):
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    for period in pd.period_range(start=start, end=end, freq="M"):
        a = max(start, period.start_time)
        b = min(end, period.end_time)
        yield period.strftime("%Y%m"), a.strftime("%Y%m%d"), b.strftime("%Y%m%d")


def _fetch_membership(pro, start_date: str, end_date: str) -> pd.DataFrame:
    frames = []
    current_month = pd.Timestamp(end_date).strftime("%Y%m")
    for month, a, b in _month_ranges(start_date, end_date):
        path = _raw_path("csi300_membership", month)
        cached = _load_parquet(path)
        if cached.empty or month == current_month:
            df = _request(
                pro,
                "index_weight",
                index_code=INDEX_CODE,
                start_date=a,
                end_date=b,
                fields="index_code,con_code,trade_date,weight",
            )
            if df.empty and INDEX_CODE != INDEX_CODE_FALLBACK:
                df = _request(
                    pro,
                    "index_weight",
                    index_code=INDEX_CODE_FALLBACK,
                    start_date=a,
                    end_date=b,
                    fields="index_code,con_code,trade_date,weight",
                )
            if not df.empty:
                _save_parquet(df, path)
                cached = df
        if not cached.empty:
            frames.append(cached)
    if not frames:
        raise RuntimeError(
            "No CSI300 membership data was returned. The Tushare account needs index_weight access."
        )
    result = pd.concat(frames, ignore_index=True)
    result["trade_date"] = result["trade_date"].astype(str)
    result = result.drop_duplicates(["trade_date", "con_code"], keep="last")
    return result.sort_values(["trade_date", "con_code"])


def _membership_intervals(
    membership: pd.DataFrame,
    calendar: list[pd.Timestamp],
) -> tuple[list[tuple[str, str, str]], dict[str, pd.DataFrame]]:
    if membership.empty:
        return [], {}
    snapshots = sorted(membership["trade_date"].astype(str).unique())
    cal = pd.DatetimeIndex(calendar)
    intervals: list[tuple[str, str, str]] = []
    weights_by_symbol: dict[str, list[pd.DataFrame]] = {}
    open_since: dict[str, pd.Timestamp] = {}

    for i, snap in enumerate(snapshots):
        snap_dt = pd.Timestamp(snap)
        members = membership.loc[membership["trade_date"].astype(str) == snap]
        current = set(members["con_code"].astype(str))
        previous = set(open_since)

        for code in current - previous:
            open_since[code] = snap_dt

        for code in previous - current:
            before = cal[cal < snap_dt]
            end_dt = before[-1] if len(before) else snap_dt
            intervals.append(
                (_to_qlib_symbol(code), open_since.pop(code).strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            )

        next_snap = pd.Timestamp(snapshots[i + 1]) if i + 1 < len(snapshots) else None
        if next_snap is None:
            end_dt = cal[-1]
        else:
            before = cal[cal < next_snap]
            end_dt = before[-1] if len(before) else snap_dt

        for _, row in members.iterrows():
            code = str(row["con_code"])
            frame = pd.DataFrame(
                {
                    "datetime": cal[(cal >= snap_dt) & (cal <= end_dt)],
                    "$csi300_weight": float(row.get("weight", np.nan)),
                }
            )
            if not frame.empty:
                weights_by_symbol.setdefault(code, []).append(frame)

    end_dt = cal[-1]
    for code, begin in list(open_since.items()):
        intervals.append(
            (_to_qlib_symbol(code), begin.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
        )

    weight_frames = {
        code: pd.concat(frames, ignore_index=True).drop_duplicates("datetime", keep="last")
        for code, frames in weights_by_symbol.items()
    }
    return intervals, weight_frames


def _fetch_symbol_family(pro, family: str, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    key = _safe_symbol(ts_code)
    if family == "price_volume":
        daily = _cache_full_history(
            pro, family, key + "_daily", "daily",
            ts_code=ts_code, start_date=start_date, end_date=end_date,
        )
        adj = _cache_full_history(
            pro, family, key + "_adj", "adj_factor",
            ts_code=ts_code, start_date=start_date, end_date=end_date,
        )
        if daily.empty:
            return daily
        result = daily.merge(
            adj[["trade_date", "adj_factor"]] if not adj.empty else pd.DataFrame(columns=["trade_date", "adj_factor"]),
            on="trade_date",
            how="left",
        )
        result["adj_factor"] = pd.to_numeric(result.get("adj_factor"), errors="coerce")
        if result["adj_factor"].notna().any():
            first = result.sort_values("trade_date")["adj_factor"].dropna().iloc[0]
            result["factor_norm"] = result["adj_factor"] / float(first or 1.0)
        else:
            result["factor_norm"] = 1.0
        return result

    if family == "daily_basic":
        return _cache_full_history(
            pro, family, key, "daily_basic",
            ts_code=ts_code, start_date=start_date, end_date=end_date,
        )

    if family == "money_flow":
        return _cache_full_history(
            pro, family, key, "moneyflow",
            ts_code=ts_code, start_date=max(start_date, "20100101"), end_date=end_date,
        )

    if family == "margin":
        return _cache_full_history(
            pro, family, key, "margin_detail",
            ts_code=ts_code, start_date=start_date, end_date=end_date,
        )

    if family == "trading_status":
        return _cache_full_history(
            pro, family, key, "suspend_d",
            ts_code=ts_code, start_date=start_date, end_date=end_date,
            fields="ts_code,trade_date,suspend_timing,suspend_type",
        )

    if family == "fundamentals":
        path = _raw_path(family, key)
        cached = _load_parquet(path)
        if not cached.empty and path.stat().st_mtime >= (time.time() - 18 * 3600):
            return cached
        print(f"[modern-data] downloading {family}/{key} ...", flush=True)
        df = _request(
            pro,
            "fina_indicator",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields=(
                "ts_code,ann_date,end_date,eps,roe,roa,grossprofit_margin,"
                "debt_to_assets,current_ratio,netprofit_yoy,q_sales_yoy,q_profit_yoy,update_flag"
            ),
        )
        if not df.empty:
            _save_parquet(df, path)
            return df
        return cached

    if family == "industry":
        path = _raw_path(family, key)
        cached = _load_parquet(path)
        if not cached.empty:
            return cached
        frames = []
        for is_new in ("Y", "N"):
            df = _request(
                pro,
                "index_member_all",
                ts_code=ts_code,
                is_new=is_new,
                fields="l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new",
            )
            if not df.empty:
                frames.append(df)
        result = pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()
        if not result.empty:
            _save_parquet(result, path)
        return result

    if family == "northbound":
        path = _raw_path(family, key)
        cached = _load_parquet(path)
        if not cached.empty:
            max_date = str(cached.get("trade_date", pd.Series(dtype=str)).astype(str).max() or "")
            if max_date >= end_date:
                return cached

        print(f"[modern-data] downloading {family}/{key} ...", flush=True)
        holdings = pd.DataFrame()
        try:
            holdings = _request(
                pro,
                "hk_hold",
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                fields="code,trade_date,ts_code,name,vol,ratio,exchange",
            )
        except RuntimeError as exc:
            print(
                "[modern-data] legacy hk_hold unavailable; using modern Stock Connect "
                f"eligibility fallback for {ts_code}: {exc}",
                flush=True,
            )

        if not holdings.empty:
            holdings["eligible"] = 1.0
            _save_parquet(holdings, path)
            return holdings

        # Current Tushare exposes stock_hsgt from 2025-08-12. It is an eligibility
        # signal, not a historical holding-size replacement, so ratio/vol remain NaN.
        eligibility_frames = []
        fallback_start = max(start_date, "20250812")
        if fallback_start <= end_date:
            for connect_type in ("HK_SH", "HK_SZ"):
                try:
                    frame = _request(
                        pro,
                        "stock_hsgt",
                        ts_code=ts_code,
                        type=connect_type,
                        start_date=fallback_start,
                        end_date=end_date,
                        fields="ts_code,trade_date,type,name,type_name",
                    )
                except RuntimeError:
                    frame = pd.DataFrame()
                if not frame.empty:
                    eligibility_frames.append(frame)

        result = (
            pd.concat(eligibility_frames, ignore_index=True)
            .drop_duplicates(["trade_date", "ts_code"], keep="last")
            if eligibility_frames else pd.DataFrame()
        )
        if not result.empty:
            result["eligible"] = 1.0
            result["ratio"] = np.nan
            result["vol"] = np.nan
            _save_parquet(result, path)
            return result
        return cached

    raise ValueError(f"Unsupported symbol family: {family}")


def _fetch_index_daily(pro, start_date: str, end_date: str) -> pd.DataFrame:
    path = _raw_path("market_context", f"csi300_{start_date}_{end_date}")
    cached = _load_parquet(path)
    if not cached.empty and str(cached["trade_date"].astype(str).max()) >= end_date:
        return cached
    result = _request(
        pro,
        "index_daily",
        ts_code=INDEX_CODE,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount",
    )
    if result.empty and INDEX_CODE != INDEX_CODE_FALLBACK:
        result = _request(
            pro,
            "index_daily",
            ts_code=INDEX_CODE_FALLBACK,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount",
        )
    if result.empty:
        raise RuntimeError("CSI300 index_daily returned no rows.")
    _save_parquet(result, path)
    return result


def _fetch_if_futures(pro, start_date: str, end_date: str) -> pd.DataFrame:
    mapping_frames = []
    for year in range(pd.Timestamp(start_date).year, pd.Timestamp(end_date).year + 1):
        a = max(pd.Timestamp(start_date), pd.Timestamp(f"{year}-01-01")).strftime("%Y%m%d")
        b = min(pd.Timestamp(end_date), pd.Timestamp(f"{year}-12-31")).strftime("%Y%m%d")
        path = _raw_path("if_futures_mapping", str(year))
        cached = _load_parquet(path)
        if cached.empty:
            cached = _request(
                pro,
                "fut_mapping",
                ts_code="IF.CFX",
                start_date=a,
                end_date=b,
                fields="ts_code,trade_date,mapping_ts_code",
            )
            if not cached.empty:
                _save_parquet(cached, path)
        if not cached.empty:
            mapping_frames.append(cached)

    if not mapping_frames:
        raise RuntimeError("Tushare fut_mapping returned no IF main-contract mapping.")

    mapping = pd.concat(mapping_frames, ignore_index=True)
    mapping = mapping.drop_duplicates("trade_date", keep="last")
    contract_frames = []
    for contract in sorted(mapping["mapping_ts_code"].dropna().astype(str).unique()):
        used = mapping.loc[mapping["mapping_ts_code"].astype(str) == contract, "trade_date"].astype(str)
        a, b = used.min(), used.max()
        path = _raw_path("if_futures", _safe_symbol(contract))
        cached = _load_parquet(path)
        if cached.empty:
            cached = _request(
                pro,
                "fut_daily",
                ts_code=contract,
                start_date=a,
                end_date=b,
                fields="ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,vol,amount,oi,oi_chg",
            )
            if not cached.empty:
                _save_parquet(cached, path)
        if not cached.empty:
            contract_frames.append(cached)

    if not contract_frames:
        raise RuntimeError("Tushare fut_daily returned no IF contract data.")

    fut = pd.concat(contract_frames, ignore_index=True)
    merged = mapping.merge(
        fut,
        left_on=["trade_date", "mapping_ts_code"],
        right_on=["trade_date", "ts_code"],
        how="left",
        suffixes=("", "_contract"),
    )
    return merged.sort_values("trade_date")


def _fetch_index_intraday(pro, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch CSI300 5-minute history in bounded chunks and cache the raw bars."""
    frames = []
    start = max(pd.Timestamp(start_date), pd.Timestamp("2014-01-01"))
    end = pd.Timestamp(end_date)
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + pd.Timedelta(days=120), end)
        key = f"{cursor:%Y%m%d}_{chunk_end:%Y%m%d}"
        path = _raw_path("intraday_market", key)
        cached = _load_parquet(path)
        if cached.empty:
            kwargs = {
                "ts_code": INDEX_CODE,
                "freq": "5min",
                "start_date": f"{cursor:%Y-%m-%d} 09:00:00",
                "end_date": f"{chunk_end:%Y-%m-%d} 16:00:00",
                "fields": "ts_code,trade_time,open,close,high,low,vol,amount",
            }
            try:
                cached = _request(pro, "idx_mins", **kwargs)
            except RuntimeError:
                kwargs["ts_code"] = INDEX_CODE_FALLBACK
                cached = _request(pro, "idx_mins", **kwargs)
            if not cached.empty:
                _save_parquet(cached, path)
        if not cached.empty:
            frames.append(cached)
        cursor = chunk_end + pd.Timedelta(days=1)

    if not frames:
        raise RuntimeError(
            "CSI300 intraday_market was selected but idx_mins returned no data. "
            "Historical index-minute permission may not be enabled."
        )
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        ["trade_time", "ts_code"], keep="last"
    )


def _build_intraday_market_context(bars: pd.DataFrame) -> pd.DataFrame:
    df = bars.copy()
    df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
    df = df.loc[df["trade_time"].notna()].sort_values("trade_time")
    df["datetime"] = df["trade_time"].dt.normalize()
    rows = []
    for dt, day in df.groupby("datetime", sort=True):
        day = day.sort_values("trade_time")
        close = pd.to_numeric(day["close"], errors="coerce")
        high = pd.to_numeric(day["high"], errors="coerce")
        low = pd.to_numeric(day["low"], errors="coerce")
        open_px = pd.to_numeric(day["open"], errors="coerce")
        vol = pd.to_numeric(day.get("vol"), errors="coerce").fillna(0.0)
        log_ret = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)
        valid_close = close.dropna()
        if valid_close.empty:
            continue
        first_open = open_px.dropna().iloc[0] if open_px.notna().any() else valid_close.iloc[0]
        last30 = (
            valid_close.iloc[-1] / valid_close.iloc[-7] - 1.0
            if len(valid_close) >= 7 else np.nan
        )
        total_vol = float(vol.sum())
        rows.append(
            {
                "datetime": pd.Timestamp(dt),
                "$idx5m_rv": float(np.sqrt(np.nansum(np.square(log_ret.to_numpy(dtype=float))))),
                "$idx5m_range": (
                    float(high.max() - low.min()) / float(first_open)
                    if pd.notna(first_open) and float(first_open) != 0.0 else np.nan
                ),
                "$idx5m_last30": float(last30) if pd.notna(last30) else np.nan,
                "$idx5m_last_hour_vol_share": (
                    float(vol.tail(12).sum()) / total_vol if total_vol > 0 else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _stock_panel(
    ts_code: str,
    selected: list[str],
    raw: dict[str, dict[str, pd.DataFrame]],
    weight_frame: pd.DataFrame | None,
    index_context: pd.DataFrame | None,
    futures_context: pd.DataFrame | None,
    intraday_context: pd.DataFrame | None,
) -> pd.DataFrame:
    price = raw["price_volume"].get(ts_code, pd.DataFrame()).copy()
    if price.empty:
        return pd.DataFrame()

    price["datetime"] = pd.to_datetime(price["trade_date"].astype(str))
    price = price.sort_values("datetime").drop_duplicates("datetime", keep="last")
    factor = pd.to_numeric(price.get("factor_norm", 1.0), errors="coerce").fillna(1.0)

    out = pd.DataFrame({"datetime": price["datetime"]})
    for src, dst in (("open", "$open"), ("close", "$close"), ("high", "$high"), ("low", "$low")):
        out[dst] = pd.to_numeric(price.get(src), errors="coerce") * factor
    out["$volume"] = pd.to_numeric(price.get("vol"), errors="coerce") / factor.replace(0, np.nan)
    out["$factor"] = factor
    out["$amount"] = pd.to_numeric(price.get("amount"), errors="coerce")

    if weight_frame is not None and not weight_frame.empty:
        out = out.merge(weight_frame, on="datetime", how="left")

    if "daily_basic" in selected:
        db = raw["daily_basic"].get(ts_code, pd.DataFrame()).copy()
        if not db.empty:
            db["datetime"] = pd.to_datetime(db["trade_date"].astype(str))
            mapping = {
                "turnover_rate": "$db_turnover_rate",
                "turnover_rate_f": "$db_turnover_rate_f",
                "volume_ratio": "$db_volume_ratio",
                "pe_ttm": "$db_pe_ttm",
                "pb": "$db_pb",
                "ps_ttm": "$db_ps_ttm",
                "dv_ttm": "$db_dv_ttm",
                "total_mv": "$db_total_mv",
                "circ_mv": "$db_circ_mv",
                "free_share": "$db_free_share",
            }
            cols = ["datetime"]
            for src, dst in mapping.items():
                if src in db.columns:
                    db[dst] = pd.to_numeric(db[src], errors="coerce")
                    cols.append(dst)
            out = out.merge(db[cols].drop_duplicates("datetime", keep="last"), on="datetime", how="left")

    if "trading_status" in selected:
        status = raw["trading_status"].get(ts_code, pd.DataFrame()).copy()
        out["$is_suspended"] = 0.0
        if not status.empty:
            status["datetime"] = pd.to_datetime(status["trade_date"].astype(str))
            suspended_dates = set(
                status.loc[
                    status["suspend_type"].astype(str).str.upper().eq("S"),
                    "datetime",
                ].dt.normalize()
            )
            # Daily price has no rows while a stock is suspended. Add those dates
            # explicitly so the Qlib binary contains NaN prices but an observable
            # $is_suspended=1 rather than silently dropping the status information.
            missing_status_dates = sorted(
                suspended_dates - set(out["datetime"].dt.normalize())
            )
            if missing_status_dates:
                out = pd.concat(
                    [
                        out,
                        pd.DataFrame({"datetime": missing_status_dates}),
                    ],
                    ignore_index=True,
                    sort=False,
                ).sort_values("datetime")
            out["$is_suspended"] = (
                out["datetime"].dt.normalize().isin(suspended_dates).astype(float)
            )

    if "money_flow" in selected:
        mf = raw["money_flow"].get(ts_code, pd.DataFrame()).copy()
        if not mf.empty:
            mf["datetime"] = pd.to_datetime(mf["trade_date"].astype(str))
            num = lambda name: pd.to_numeric(mf.get(name, 0.0), errors="coerce").fillna(0.0)
            buy_all = num("buy_sm_amount") + num("buy_md_amount") + num("buy_lg_amount") + num("buy_elg_amount")
            sell_all = num("sell_sm_amount") + num("sell_md_amount") + num("sell_lg_amount") + num("sell_elg_amount")
            denom = (buy_all + sell_all).abs() + 1e-9
            mf["$mf_net_ratio"] = num("net_mf_amount") / denom
            mf["$mf_large_net_ratio"] = (
                num("buy_lg_amount") + num("buy_elg_amount") - num("sell_lg_amount") - num("sell_elg_amount")
            ) / denom
            mf["$mf_small_net_ratio"] = (num("buy_sm_amount") - num("sell_sm_amount")) / denom
            out = out.merge(
                mf[["datetime", "$mf_net_ratio", "$mf_large_net_ratio", "$mf_small_net_ratio"]]
                .drop_duplicates("datetime", keep="last"),
                on="datetime",
                how="left",
            )

    if "margin" in selected:
        mg = raw["margin"].get(ts_code, pd.DataFrame()).copy()
        if not mg.empty:
            mg["datetime"] = pd.to_datetime(mg["trade_date"].astype(str))
            for src, dst in (
                ("rzrqye", "$margin_rzrqye_log"),
                ("rqye", "$margin_rqye_log"),
                ("rzmre", "$margin_rzmre_log"),
            ):
                mg[dst] = np.log1p(pd.to_numeric(mg.get(src), errors="coerce").clip(lower=0))
            out = out.merge(
                mg[["datetime", "$margin_rzrqye_log", "$margin_rqye_log", "$margin_rzmre_log"]]
                .drop_duplicates("datetime", keep="last"),
                on="datetime",
                how="left",
            )

    if "northbound" in selected:
        nb = raw["northbound"].get(ts_code, pd.DataFrame()).copy()
        if not nb.empty and "trade_date" in nb.columns:
            nb["datetime"] = pd.to_datetime(nb["trade_date"].astype(str))
            nb["$north_eligible"] = pd.to_numeric(nb.get("eligible", 1.0), errors="coerce").fillna(1.0)
            nb["$north_hold_ratio"] = pd.to_numeric(nb.get("ratio"), errors="coerce")
            nb["$north_hold_logvol"] = np.log1p(pd.to_numeric(nb.get("vol"), errors="coerce").clip(lower=0))
            out = out.merge(
                nb[["datetime", "$north_eligible", "$north_hold_ratio", "$north_hold_logvol"]]
                .drop_duplicates("datetime", keep="last"),
                on="datetime",
                how="left",
            )

    if "fundamentals" in selected:
        fi = raw["fundamentals"].get(ts_code, pd.DataFrame()).copy()
        if not fi.empty:
            fi = fi.loc[fi["ann_date"].notna()].copy()
            if not fi.empty:
                fi["datetime"] = pd.to_datetime(fi["ann_date"].astype(str))
                fi["end_sort"] = pd.to_datetime(fi.get("end_date").astype(str), errors="coerce")
                fi = fi.sort_values(["datetime", "end_sort"]).drop_duplicates("datetime", keep="last")
                fmap = {
                    "eps": "$fi_eps",
                    "roe": "$fi_roe",
                    "roa": "$fi_roa",
                    "grossprofit_margin": "$fi_grossprofit_margin",
                    "debt_to_assets": "$fi_debt_to_assets",
                    "current_ratio": "$fi_current_ratio",
                    "netprofit_yoy": "$fi_netprofit_yoy",
                    "q_sales_yoy": "$fi_q_sales_yoy",
                    "q_profit_yoy": "$fi_q_profit_yoy",
                }
                cols = ["datetime"]
                for src, dst in fmap.items():
                    fi[dst] = pd.to_numeric(fi.get(src), errors="coerce")
                    cols.append(dst)
                out = pd.merge_asof(
                    out.sort_values("datetime"),
                    fi[cols].sort_values("datetime"),
                    on="datetime",
                    direction="backward",
                    allow_exact_matches=True,
                )

    if "industry" in selected:
        ind = raw["industry"].get(ts_code, pd.DataFrame()).copy()
        out["$industry_l1_id"] = np.nan
        if not ind.empty:
            for _, row in ind.iterrows():
                code = str(row.get("l1_code") or "")
                if not code:
                    continue
                begin = pd.to_datetime(str(row.get("in_date") or ""), errors="coerce")
                finish = pd.to_datetime(str(row.get("out_date") or ""), errors="coerce")
                if pd.isna(begin):
                    continue
                if pd.isna(finish):
                    finish = out["datetime"].max()
                numeric_id = int(hashlib.sha1(code.encode("utf-8")).hexdigest()[:8], 16) % 100000
                mask = (out["datetime"] >= begin) & (out["datetime"] <= finish)
                out.loc[mask, "$industry_l1_id"] = float(numeric_id)

    if index_context is not None and not index_context.empty:
        out = out.merge(index_context, on="datetime", how="left")

    if futures_context is not None and not futures_context.empty:
        out = out.merge(futures_context, on="datetime", how="left")

    if intraday_context is not None and not intraday_context.empty:
        out = out.merge(intraday_context, on="datetime", how="left")

    out["instrument"] = _to_qlib_symbol(ts_code)
    return out.sort_values("datetime")


def _build_index_context(index_df: pd.DataFrame) -> pd.DataFrame:
    df = index_df.copy()
    df["datetime"] = pd.to_datetime(df["trade_date"].astype(str))
    df = df.sort_values("datetime").drop_duplicates("datetime", keep="last")
    close = pd.to_numeric(df["close"], errors="coerce")
    ret = close.pct_change()
    return pd.DataFrame(
        {
            "datetime": df["datetime"],
            "$mkt_return_1d": ret,
            "$mkt_mom20": close.pct_change(20),
            "$mkt_vol20": ret.rolling(20, min_periods=10).std() * math.sqrt(252),
            "$mkt_amount_log": np.log1p(pd.to_numeric(df.get("amount"), errors="coerce").clip(lower=0)),
        }
    )


def _build_futures_context(fut: pd.DataFrame, index_df: pd.DataFrame) -> pd.DataFrame:
    df = fut.copy()
    df["datetime"] = pd.to_datetime(df["trade_date"].astype(str))
    df = df.sort_values("datetime").drop_duplicates("datetime", keep="last")
    close = pd.to_numeric(df.get("close"), errors="coerce")
    idx = index_df[["trade_date", "close"]].copy()
    idx["datetime"] = pd.to_datetime(idx["trade_date"].astype(str))
    idx["index_close"] = pd.to_numeric(idx["close"], errors="coerce")
    df = df.merge(idx[["datetime", "index_close"]], on="datetime", how="left")
    return pd.DataFrame(
        {
            "datetime": df["datetime"],
            "$if_return_1d": close.pct_change(),
            "$if_basis": close / df["index_close"] - 1.0,
            "$if_vol_log": np.log1p(pd.to_numeric(df.get("vol"), errors="coerce").clip(lower=0)),
            "$if_oi_log": np.log1p(pd.to_numeric(df.get("oi"), errors="coerce").clip(lower=0)),
        }
    )


def _add_industry_returns(panel: pd.DataFrame) -> pd.DataFrame:
    if "$industry_l1_id" not in panel.columns:
        return panel
    result = panel.copy()
    result["__stock_ret"] = result.groupby("instrument", sort=False)["$close"].pct_change(fill_method=None)
    industry_ret = (
        result.groupby(["datetime", "$industry_l1_id"], dropna=True)["__stock_ret"]
        .mean()
        .rename("$industry_return_1d")
        .reset_index()
    )
    result = result.merge(industry_ret, on=["datetime", "$industry_l1_id"], how="left")
    result["$industry_rel_return_1d"] = result["__stock_ret"] - result["$industry_return_1d"]
    return result.drop(columns=["__stock_ret"])


def _write_bin_provider(
    provider_dir: Path,
    calendar: list[pd.Timestamp],
    panel: pd.DataFrame,
    membership_intervals: list[tuple[str, str, str]],
    index_df: pd.DataFrame,
    fields: list[str],
) -> None:
    provider_dir.mkdir(parents=True, exist_ok=True)
    calendars_dir = provider_dir / "calendars"
    instruments_dir = provider_dir / "instruments"
    features_root = provider_dir / "features"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)
    features_root.mkdir(parents=True, exist_ok=True)

    calendar_index = pd.DatetimeIndex(calendar)
    (calendars_dir / "day.txt").write_text(
        "\n".join(x.strftime("%Y-%m-%d") for x in calendar_index) + "\n",
        encoding="utf-8",
    )

    available = set(panel["instrument"].astype(str).unique())
    clean_intervals = [row for row in membership_intervals if row[0] in available]
    (instruments_dir / "csi300.txt").write_text(
        "\n".join("\t".join(row) for row in clean_intervals) + "\n",
        encoding="utf-8",
    )

    all_lines = []
    for symbol, group in panel.groupby("instrument", sort=True):
        g = group.sort_values("datetime")
        begin, end = g["datetime"].min(), g["datetime"].max()
        all_lines.append(f"{symbol}\t{begin:%Y-%m-%d}\t{end:%Y-%m-%d}")
        _write_symbol_bins(features_root, symbol, g, calendar_index, fields)

    benchmark = index_df.copy()
    benchmark["datetime"] = pd.to_datetime(benchmark["trade_date"].astype(str))
    benchmark = benchmark.sort_values("datetime").drop_duplicates("datetime", keep="last")
    benchmark_panel = pd.DataFrame({"datetime": benchmark["datetime"]})
    for src, dst in (("open", "$open"), ("close", "$close"), ("high", "$high"), ("low", "$low")):
        benchmark_panel[dst] = pd.to_numeric(benchmark.get(src), errors="coerce")
    benchmark_panel["$volume"] = pd.to_numeric(benchmark.get("vol"), errors="coerce")
    benchmark_panel["$amount"] = pd.to_numeric(benchmark.get("amount"), errors="coerce")
    benchmark_panel["$factor"] = 1.0
    benchmark_panel["instrument"] = "SH000300"
    if not benchmark_panel.empty:
        all_lines.append(
            f"SH000300\t{benchmark_panel['datetime'].min():%Y-%m-%d}\t{benchmark_panel['datetime'].max():%Y-%m-%d}"
        )
        _write_symbol_bins(
            features_root,
            "SH000300",
            benchmark_panel,
            calendar_index,
            ["$open", "$close", "$high", "$low", "$volume", "$factor", "$amount"],
        )

    (instruments_dir / "all.txt").write_text("\n".join(all_lines) + "\n", encoding="utf-8")


def _write_symbol_bins(
    features_root: Path,
    symbol: str,
    frame: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    fields: list[str],
) -> None:
    frame = frame.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame = frame.sort_values("datetime").drop_duplicates("datetime", keep="last")
    if frame.empty:
        return
    start = frame["datetime"].min()
    end = frame["datetime"].max()
    subset_calendar = calendar[(calendar >= start) & (calendar <= end)]
    if len(subset_calendar) == 0:
        return
    start_index = int(calendar.get_indexer([subset_calendar[0]])[0])
    aligned = frame.set_index("datetime").reindex(subset_calendar)
    out_dir = features_root / symbol.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    for qfield in fields:
        field = qfield[1:] if qfield.startswith("$") else qfield
        values = (
            pd.to_numeric(aligned[qfield], errors="coerce").to_numpy(dtype=np.float32)
            if qfield in aligned.columns
            else np.full(len(aligned), np.nan, dtype=np.float32)
        )
        payload = np.hstack([np.float32(start_index), values]).astype("<f4")
        payload.tofile(out_dir / f"{field.lower()}.day.bin")


def _manifest_key(families: list[str]) -> str:
    return hashlib.sha1(",".join(sorted(families)).encode("utf-8")).hexdigest()[:12]


def configure_runtime(config: dict[str, Any]) -> dict[str, Any]:
    resolved = normalize_dataset_config(config)
    if resolved["mode"] == "legacy":
        os.environ["RDAGENT_QLIB_PROVIDER_URI"] = resolved["provider_uri"]
        os.environ.pop("RDAGENT_DATASET_FAMILIES", None)
        os.environ.pop("RDAGENT_DATASET_BASE_FEATURES", None)
    else:
        provider = resolved.get("provider_uri")
        if not provider:
            raise RuntimeError("Modern dataset configuration has no resolved provider_uri.")
        os.environ["RDAGENT_QLIB_PROVIDER_URI"] = str(provider)
        os.environ["RDAGENT_DATASET_FAMILIES"] = json.dumps(resolved["families"])
        os.environ["RDAGENT_DATASET_BASE_FEATURES"] = json.dumps(model_features_for_config(resolved))

    # Factor CoSTEER normally keeps one process-global daily_pv.h5 directory. That
    # is unsafe once experiments can select different providers/families: a later run
    # could reuse an HDF created by a different dataset. Give every frozen dataset
    # configuration its own persistent factor-source cache.
    _cache_identity = json.dumps(
        {
            "mode": resolved["mode"],
            "provider_uri": resolved.get("provider_uri"),
            "families": resolved.get("families", []),
        },
        sort_keys=True,
    )
    _cache_key = hashlib.sha1(_cache_identity.encode("utf-8")).hexdigest()[:16]
    _factor_cache_root = DATA_ROOT / "factor_source" / _cache_key
    os.environ["FACTOR_COSTEER_DATA_FOLDER"] = str(_factor_cache_root / "full")
    os.environ["FACTOR_COSTEER_DATA_FOLDER_DEBUG"] = str(_factor_cache_root / "debug")
    resolved["factor_source_cache"] = str(_factor_cache_root)

    split = resolved["split"]
    for prefix in ("QLIB_FACTOR_", "QLIB_MODEL_", "QLIB_QUANT_"):
        for key, value in split.items():
            env_name = prefix + key.upper()
            if value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = str(value)
    return resolved


def prepare_for_run(config: dict[str, Any], trace_dir: str | Path | None = None) -> dict[str, Any]:
    cfg = normalize_dataset_config(config)
    trace_path = Path(trace_dir) if trace_dir else None

    if cfg["mode"] == "legacy":
        if trace_path is not None:
            (trace_path / "_dataset_config.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )
        return configure_runtime(cfg)

    existing_provider = cfg.get("provider_uri")
    if existing_provider and Path(existing_provider).exists():
        print(f"[modern-data] reusing frozen provider {existing_provider}", flush=True)
        return configure_runtime(cfg)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Modern CSI300 data was selected but TUSHARE_TOKEN is not configured. "
            "Set it as a Fly secret, then retry the experiment."
        )

    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError("Modern CSI300 data requires the 'tushare' Python package.") from exc

    selected = _family_set(cfg)
    start_date = _yyyymmdd(cfg["start_date"])
    requested_end = _yyyymmdd(cfg["as_of_date"])
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    MODERN_QLIB_ROOT.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(DATA_ROOT / ".prepare.lock"))
    with lock:
        pro = ts.pro_api(token)
        calendar = _fetch_calendar(pro, start_date, requested_end)
        if not calendar:
            raise RuntimeError("No trading calendar available for modern dataset.")
        resolved_end = calendar[-1].strftime("%Y%m%d")
        print(
            f"[modern-data] preparing CSI300 {start_date} -> {resolved_end}; families={selected}",
            flush=True,
        )

        membership = _fetch_membership(pro, start_date, resolved_end)
        membership_intervals, weights = _membership_intervals(membership, calendar)
        symbols = sorted(set(membership["con_code"].dropna().astype(str)))
        print(f"[modern-data] historical CSI300 union: {len(symbols)} stocks", flush=True)

        index_df = _fetch_index_daily(pro, start_date, resolved_end)
        index_context = _build_index_context(index_df) if "market_context" in selected else None
        futures_context = None
        if "if_futures" in selected:
            futures_context = _build_futures_context(
                _fetch_if_futures(pro, max(start_date, "20100416"), resolved_end),
                index_df,
            )

        intraday_context = None
        if "intraday_market" in selected:
            intraday_context = _build_intraday_market_context(
                _fetch_index_intraday(pro, start_date, resolved_end)
            )

        symbol_families = [
            f for f in selected
            if f in {"price_volume", "daily_basic", "trading_status", "industry", "fundamentals", "money_flow", "margin", "northbound"}
        ]
        raw: dict[str, dict[str, pd.DataFrame]] = {family: {} for family in symbol_families}

        for idx, ts_code in enumerate(symbols, start=1):
            if idx == 1 or idx % 25 == 0 or idx == len(symbols):
                print(f"[modern-data] stock {idx}/{len(symbols)}: {ts_code}", flush=True)
            for family in symbol_families:
                try:
                    raw[family][ts_code] = _fetch_symbol_family(
                        pro, family, ts_code, start_date, resolved_end
                    )
                except Exception as exc:
                    if FAMILY_CATALOG[family]["required"] or family in selected:
                        raise RuntimeError(
                            f"Selected dataset family '{family}' failed for {ts_code}: {exc}"
                        ) from exc

        panels = []
        for ts_code in symbols:
            panel = _stock_panel(
                ts_code,
                selected,
                raw,
                weights.get(ts_code),
                index_context,
                futures_context,
                intraday_context,
            )
            if not panel.empty:
                panels.append(panel)
        if not panels:
            raise RuntimeError("Modern CSI300 build produced no stock panel.")

        panel = pd.concat(panels, ignore_index=True)
        if "industry" in selected:
            panel = _add_industry_returns(panel)

        all_fields = qlib_fields_for_config(cfg)
        for field in all_fields:
            if field not in panel.columns:
                panel[field] = np.nan

        family_key = _manifest_key(selected)
        provider_dir = MODERN_QLIB_ROOT / family_key / resolved_end
        manifest_path = provider_dir / "manifest.json"
        if not manifest_path.exists():
            print(f"[modern-data] writing Qlib provider {provider_dir}", flush=True)
            _write_bin_provider(
                provider_dir,
                calendar,
                panel,
                membership_intervals,
                index_df,
                all_fields,
            )
        provider_dir.mkdir(parents=True, exist_ok=True)

        resolved = dict(cfg)
        resolved["provider_uri"] = str(provider_dir)
        resolved["resolved_end"] = _dash_date(resolved_end)
        resolved["split"] = dict(resolved["split"])
        resolved["split"]["test_end"] = _dash_date(resolved_end)
        resolved["model_features"] = model_features_for_config(resolved)
        resolved["qlib_fields"] = all_fields
        resolved["built_at"] = _now_iso()
        resolved["manifest_path"] = str(manifest_path)

        manifest = {
            **resolved,
            "stock_count": int(panel["instrument"].nunique()),
            "row_count": int(len(panel)),
            "calendar_days": int(len(calendar)),
            "raw_root": str(DATA_ROOT / "raw"),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (DATA_ROOT / "latest_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        if trace_path is not None:
            trace_path.mkdir(parents=True, exist_ok=True)
            (trace_path / "_dataset_config.json").write_text(
                json.dumps(resolved, indent=2), encoding="utf-8"
            )

        print(
            f"[modern-data] ready: provider={provider_dir} stocks={manifest['stock_count']} "
            f"rows={manifest['row_count']} test_end={resolved['split']['test_end']}",
            flush=True,
        )
        return configure_runtime(resolved)
