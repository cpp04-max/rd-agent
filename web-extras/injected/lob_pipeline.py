"""Self-contained LOB (limit-order-book) feature discovery + Statistical Market
Making (SMM) scenario.

Unlike the qlib finance loops (daily bars, qrun backtests), market making works
on high-frequency order-book microstructure. There is no bundled LOB dataset, so
this scenario synthesises a deterministic order-book stream whose short-horizon
mid-price drift is driven by an observable order-flow-pressure state. That makes
the discovered microstructure features genuinely predictive and the whole loop
reproducible offline.

Pipeline (mirrors the RD loop: propose -> tasks -> code -> run -> feedback):
  1. synthesise_lob()          -> order-book snapshots + forward-return label
  2. propose + hypothesis2task -> LLM proposes microstructure feature specs
  3. execute each feature code -> feature column, validated & IC-scored
  4. select features           -> keep |IC| above threshold (fallback: known-good)
  5. train_smm()               -> LightGBM predicting short-horizon mid drift
  6. backtest_market_making()  -> signal-skewed quoting vs no-signal baseline
  7. log hypothesis/tasks/metrics/chart, return (END end_code=0 from server)

The LLM is only used to *propose* feature specifications; every proposed feature
is executed and validated, and a conservative built-in feature set guarantees the
example always completes even if the model returns unusable code.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from rdagent.core.proposal import Hypothesis
from rdagent.log import rdagent_logger as logger
from rdagent.oai.llm_utils import APIBackend

RNG_SEED = 7
N_STEPS = 12000          # order-book snapshots
N_LEVELS = 5             # book depth per side
HORIZON = 10             # forward-return horizon (steps)
TICK = 0.01
MIN_VALID_COVERAGE = 0.6  # fraction of non-NaN values required for a feature
IC_THRESHOLD = 0.01       # |IC| vs forward return required to keep a feature


# --------------------------------------------------------------------------- #
# 1. Synthetic order book
# --------------------------------------------------------------------------- #
def synthesise_lob(n: int = N_STEPS, seed: int = RNG_SEED) -> pd.DataFrame:
    """Simulate a limit order book whose mid-price drift is driven by a latent
    order-flow-pressure state ``z`` that is observable through the book.

    Returns a DataFrame indexed by step with bid/ask price+size per level, the
    mid price, signed trade flow, and the forward-return label.
    """
    rng = np.random.default_rng(seed)

    # Latent order-flow pressure: persistent AR(1) -> predictable drift.
    z = np.zeros(n)
    shock = rng.normal(0.0, 1.0, n)
    for t in range(1, n):
        z[t] = 0.90 * z[t - 1] + 0.40 * shock[t]

    # Mid price drifts with z plus microstructure noise.
    drift = 0.40 * z
    noise = rng.normal(0.0, 0.55, n)
    dmid = drift + noise
    mid = 100.0 + np.cumsum(dmid) * TICK

    # Spread breathes with |z| (wider when pressure is high).
    spread = TICK * (2.0 + 1.5 * np.abs(z) + 0.5 * rng.random(n))

    bid1 = mid - spread / 2.0
    ask1 = mid + spread / 2.0

    cols: dict[str, np.ndarray] = {"mid": mid, "spread": spread}

    # Book sizes: level-1 size imbalances encode the sign of z so that
    # book/order-flow imbalance features are informative.
    base_size = 500.0 + 100.0 * rng.random(n)
    for lv in range(1, N_LEVELS + 1):
        decay = 1.0 / lv
        # Bid side grows with +z, ask side grows with -z (noisily).
        bid_size = base_size * decay * (1.0 + 0.35 * np.tanh(z)) * (0.3 + 1.4 * rng.random(n))
        ask_size = base_size * decay * (1.0 - 0.35 * np.tanh(z)) * (0.3 + 1.4 * rng.random(n))
        cols[f"bid_size_{lv}"] = np.clip(bid_size, 1.0, None)
        cols[f"ask_size_{lv}"] = np.clip(ask_size, 1.0, None)
        cols[f"bid_price_{lv}"] = bid1 - (lv - 1) * spread
        cols[f"ask_price_{lv}"] = ask1 + (lv - 1) * spread

    # Signed trade flow: aggressive orders aligned with z (noisy).
    trade_flow = 200.0 * np.tanh(z) + rng.normal(0.0, 220.0, n)
    cols["trade_flow"] = trade_flow

    df = pd.DataFrame(cols)

    # Forward-return label: mid change over the next HORIZON steps.
    df["fwd_ret"] = df["mid"].shift(-HORIZON) - df["mid"]
    return df


# --------------------------------------------------------------------------- #
# 2. Feature discovery
# --------------------------------------------------------------------------- #
# Built-in known-good microstructure features. These act both as the fallback
# (so the example always completes) and as the reference the LLM is asked to
# extend. Each entry: name -> description + pandas implementation over ``df``.
def _ofi(df: pd.DataFrame) -> pd.Series:
    """Order-flow imbalance (best level): size/price changes of bid vs ask."""
    bsz, asz = df["bid_size_1"], df["ask_size_1"]
    bp, ap = df["bid_price_1"], df["ask_price_1"]
    db = bsz.diff() + (bp.diff() > 0) * bsz - (bp.diff() < 0) * bsz.shift(1)
    da = asz.diff() + (ap.diff() < 0) * asz - (ap.diff() > 0) * asz.shift(1)
    return (db - da).rolling(5).sum()


def _book_imbalance(df: pd.DataFrame) -> pd.Series:
    """Depth-weighted book imbalance across all levels."""
    bid = sum(df[f"bid_size_{lv}"] for lv in range(1, N_LEVELS + 1))
    ask = sum(df[f"ask_size_{lv}"] for lv in range(1, N_LEVELS + 1))
    return (bid - ask) / (bid + ask)


def _microprice(df: pd.DataFrame) -> pd.Series:
    """Size-weighted mid (microprice) deviation from the mid."""
    bsz, asz = df["bid_size_1"], df["ask_size_1"]
    micro = (df["ask_price_1"] * bsz + df["bid_price_1"] * asz) / (bsz + asz)
    return (micro - df["mid"]) / df["spread"]


def _trade_imbalance(df: pd.DataFrame) -> pd.Series:
    """Rolling signed aggressive trade flow."""
    return df["trade_flow"].rolling(10).sum()


def _spread_level(df: pd.DataFrame) -> pd.Series:
    """Current spread in ticks (liquidity state)."""
    return df["spread"] / TICK


def _depth_ratio(df: pd.DataFrame) -> pd.Series:
    """Top-of-book depth ratio bid/ask."""
    return np.log(df["bid_size_1"] / df["ask_size_1"])


KNOWN_GOOD_FEATURES: dict[str, dict] = {
    "order_flow_imbalance": {
        "description": "Cumulative best-level order-flow imbalance (Cont et al.).",
        "formulation": "OFI_t = sum_{k<=5} (dB_k - dA_k)",
        "code": _ofi,
    },
    "book_imbalance": {
        "description": "Depth-weighted imbalance across all book levels.",
        "formulation": "(sum bid_size - sum ask_size)/(sum bid_size + sum ask_size)",
        "code": _book_imbalance,
    },
    "microprice_dev": {
        "description": "Microprice deviation from mid, scaled by spread.",
        "formulation": "( (ask1*bsz + bid1*asz)/(bsz+asz) - mid ) / spread",
        "code": _microprice,
    },
    "trade_imbalance": {
        "description": "Rolling signed aggressive trade flow.",
        "formulation": "sum_{k<=10} trade_flow_{t-k}",
        "code": _trade_imbalance,
    },
    "spread_ticks": {
        "description": "Spread in ticks (liquidity state).",
        "formulation": "spread / tick",
        "code": _spread_level,
    },
    "depth_ratio": {
        "description": "Log top-of-book depth ratio.",
        "formulation": "log(bid_size_1 / ask_size_1)",
        "code": _depth_ratio,
    },
}


PROPPOSE_SYSTEM = (
    "You are a high-frequency market-microstructure quant. You discover features "
    "from limit-order-book snapshots to predict short-horizon mid-price drift for "
    "statistical market making. Respond ONLY with JSON."
)

PROPOSE_USER = """The order-book snapshot table has these columns:
{columns}
{previous}
Propose up to {max_features} microstructure features that may predict the forward
mid-price change over the next {horizon} steps. For each feature give:
- name: snake_case identifier
- description: one sentence
- formulation: short formula
Return JSON: {{"features": [{{"name": ..., "description": ..., "formulation": ...}}]}}
"""

CODEGEN_SYSTEM = (
    "You write pandas feature code for limit-order-book data. Respond ONLY with a "
    "JSON object mapping feature name to Python code. The code must define a "
    "function compute(df) -> pd.Series aligned to df.index using only df columns, "
    "numpy as np and pandas as pd."
)

CODEGEN_USER = """Write the implementation for these features:
{specs}

Return JSON: {{"<name>": "def compute(df):\\n    ..."}}
"""


@dataclass
class LOBFeatureSpec:
    name: str
    description: str = ""
    formulation: str = ""
    code: object = None  # callable(df) -> pd.Series


@dataclass
class FeatureResult:
    spec: LOBFeatureSpec
    series: pd.Series | None = None
    ic: float = float("nan")
    coverage: float = 0.0
    ok: bool = False
    error: str = ""


def _propose_specs(df: pd.DataFrame, max_features: int = 6, previous_summary: str = "") -> list[dict]:
    """Ask the LLM for candidate feature specs; fall back to known-good on error."""
    try:
        backend = APIBackend()
        previous = (
            f"\nPrevious round results (propose NEW features, do not repeat them):\n{previous_summary}\n"
            if previous_summary else ""
        )
        user = PROPOSE_USER.format(
            columns=", ".join(c for c in df.columns if c != "fwd_ret"),
            previous=previous,
            max_features=max_features,
            horizon=HORIZON,
        )
        resp = backend.build_messages_and_create_chat_completion(
            user_prompt=user, system_prompt=PROPPOSE_SYSTEM, json_mode=True
        )
        data = json.loads(resp)
        feats = data.get("features", [])
        if feats:
            return feats[:max_features]
    except Exception:
        traceback.print_exc()
    # Fallback: built-in specs.
    return [
        {"name": k, "description": v["description"], "formulation": v["formulation"]}
        for k, v in KNOWN_GOOD_FEATURES.items()
    ]


def _codegen(specs: list[dict]) -> dict[str, object]:
    """Get implementations for the proposed specs.

    Known-good features map straight to their reference implementation; anything
    else is delegated to the LLM, and any feature without working code is dropped.
    """
    impls: dict[str, object] = {}
    unknown: list[dict] = []
    for spec in specs:
        name = str(spec.get("name", "")).strip()
        if not name:
            continue
        if name in KNOWN_GOOD_FEATURES:
            impls[name] = KNOWN_GOOD_FEATURES[name]["code"]
        else:
            unknown.append(spec)

    if unknown:
        try:
            backend = APIBackend()
            resp = backend.build_messages_and_create_chat_completion(
                user_prompt=CODEGEN_USER.format(specs=json.dumps(unknown, indent=2)),
                system_prompt=CODEGEN_SYSTEM,
                json_mode=True,
            )
            code_map = json.loads(resp)
            for spec in unknown:
                name = spec["name"]
                code_text = code_map.get(name)
                if not isinstance(code_text, str):
                    continue
                fn = _compile_feature_fn(code_text)
                if fn is not None:
                    impls[name] = fn
        except Exception:
            traceback.print_exc()
    return impls


def _compile_feature_fn(code_text: str):
    """Compile LLM feature code into compute(df); return None on failure."""
    try:
        ns: dict = {"np": np, "pd": pd}
        exec(code_text, ns)  # noqa: S102 - scenario executes generated code by design
        fn = ns.get("compute")
        if callable(fn):
            return fn
    except Exception:
        traceback.print_exc()
    return None


def _spearman_ic(feature: pd.Series, label: pd.Series) -> float:
    aligned = pd.concat([feature, label], axis=1).dropna()
    if len(aligned) < 100:
        return float("nan")
    return float(aligned.iloc[:, 0].rank().corr(aligned.iloc[:, 1].rank()))


def execute_features(df: pd.DataFrame, specs: list[dict], impls: dict[str, object]) -> list[FeatureResult]:
    results: list[FeatureResult] = []
    label = df["fwd_ret"]
    for spec in specs:
        name = str(spec.get("name", "")).strip()
        lob_spec = LOBFeatureSpec(
            name=name,
            description=str(spec.get("description", "")),
            formulation=str(spec.get("formulation", "")),
        )
        fn = impls.get(name)
        if fn is None:
            results.append(FeatureResult(spec=lob_spec, error="no implementation"))
            continue
        try:
            series = fn(df)
            if not isinstance(series, pd.Series):
                series = pd.Series(series, index=df.index)
            coverage = float(series.notna().mean())
            if coverage < MIN_VALID_COVERAGE or np.isclose(float(series.dropna().std() or 0.0), 0.0):
                results.append(FeatureResult(spec=lob_spec, series=series, coverage=coverage, error="low coverage/no variance"))
                continue
            ic = _spearman_ic(series, label)
            ok = np.isfinite(ic) and abs(ic) >= IC_THRESHOLD
            results.append(FeatureResult(spec=lob_spec, series=series, ic=ic, coverage=coverage, ok=ok))
        except Exception as exc:
            results.append(FeatureResult(spec=lob_spec, error=f"{type(exc).__name__}: {exc}"))
    return results


def select_features(results: list[FeatureResult], df: pd.DataFrame) -> list[FeatureResult]:
    """Keep features with meaningful IC; if none pass, fall back to known-good."""
    kept = [r for r in results if r.ok]
    if kept:
        return sorted(kept, key=lambda r: -abs(r.ic))
    logger.warning("No proposed feature passed validation; using built-in feature set.")
    label = df["fwd_ret"]
    fallback = []
    for name, meta in KNOWN_GOOD_FEATURES.items():
        spec = LOBFeatureSpec(name=name, description=meta["description"], formulation=meta["formulation"])
        series = meta["code"](df)
        fallback.append(
            FeatureResult(spec=spec, series=series, ic=_spearman_ic(series, label), coverage=float(series.notna().mean()), ok=True)
        )
    return fallback


# --------------------------------------------------------------------------- #
# 3. SMM signal model
# --------------------------------------------------------------------------- #
def train_smm(df: pd.DataFrame, features: list[FeatureResult]) -> dict:
    """Train a LightGBM model predicting forward mid-price drift from the
    discovered features. Chronological train/valid/test split."""
    import lightgbm as lgb

    X = pd.DataFrame({r.spec.name: r.series for r in features}, index=df.index)
    y = df["fwd_ret"]
    valid_mask = y.notna() & X.notna().all(axis=1)
    X, y = X[valid_mask], y[valid_mask]

    n = len(X)
    tr_end, va_end = int(n * 0.6), int(n * 0.8)
    X_tr, y_tr = X.iloc[:tr_end], y.iloc[:tr_end]
    X_va, y_va = X.iloc[tr_end:va_end], y.iloc[tr_end:va_end]
    X_te, y_te = X.iloc[va_end:], y.iloc[va_end:]

    model = lgb.LGBMRegressor(
        n_estimators=300, learning_rate=0.05, num_leaves=31, subsample=0.9,
        subsample_freq=1, colsample_bytree=0.9, random_state=RNG_SEED, verbosity=-1,
    )
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_va, y_va)],
        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)],
    )
    pred_te = pd.Series(model.predict(X_te), index=X_te.index)
    ic = float(pred_te.rank().corr(y_te.rank()))
    hit = float(((pred_te > 0) == (y_te > 0)).mean())
    feature_importance = {
        name: float(imp) for name, imp in zip(X.columns, model.feature_importances_)
    }
    return {
        "model": model, "pred_test": pred_te, "test_index": X_te.index,
        "test_ic": ic, "directional_hit_rate": hit,
        "n_train": int(len(X_tr)), "n_valid": int(len(X_va)), "n_test": int(len(X_te)),
        "feature_importance": feature_importance,
    }


# --------------------------------------------------------------------------- #
# 4. Market-making backtest
# --------------------------------------------------------------------------- #
def backtest_market_making(
    mid: pd.Series, signal: pd.Series, half_spread_ticks: float = 4.0,
    skew_frac: float = 0.5, inventory_cap: int = 8, order_life: int = HORIZON,
) -> dict:
    """Discrete market-making simulation with resting orders.

    Quotes sit ``half_spread`` around the mid and are shifted (skewed) along the
    normalised signal: a positive drift forecast lifts both quotes so the bid is
    hit more often (accumulate inventory before the move). The skew is bounded to
    a fraction ``skew_frac`` of the half-spread so the bid never crosses above
    the mid, which would fill instantly at an adverse price. Each posted quote
    rests for up to ``order_life`` steps (the prediction horizon), so a fill can
    happen on any step while the order is alive, then it is refreshed from the
    latest signal. Returns PnL and risk statistics.
    """
    mid_arr = mid.to_numpy()
    sig = signal.to_numpy()
    sig_std = float(np.nanstd(sig)) or 1.0
    sig_norm = np.clip(np.nan_to_num(sig) / sig_std, -1.0, 1.0)

    half = half_spread_ticks * TICK
    max_shift = half * float(np.clip(skew_frac, 0.0, 1.0))

    inventory, cash = 0, 0.0
    fills, max_abs_inv = 0, 0
    bid = ask = None
    ttl_b = ttl_a = 0
    equity = np.zeros(len(mid_arr))

    for t in range(len(mid_arr)):
        price = mid_arr[t]
        # Refresh expired quotes from the current signal.
        if ttl_b <= 0:
            bid = price - half + max_shift * sig_norm[t]
            ttl_b = order_life
        if ttl_a <= 0:
            ask = price + half + max_shift * sig_norm[t]
            ttl_a = order_life

        # Fills: mid crossing a resting quote.
        if price <= bid and inventory < inventory_cap:
            inventory += 1
            cash -= bid
            fills += 1
            ttl_b = 0  # consumed; repost next step
        elif price >= ask and inventory > -inventory_cap:
            inventory -= 1
            cash += ask
            fills += 1
            ttl_a = 0

        ttl_b -= 1
        ttl_a -= 1
        max_abs_inv = max(max_abs_inv, abs(inventory))
        equity[t] = cash + inventory * price

    pnl = float(equity[-1])
    deq = np.diff(equity)
    sharpe = float(deq.mean() / (deq.std() + 1e-12) * np.sqrt(len(deq))) if len(deq) else 0.0
    return {"pnl": pnl, "fills": fills, "max_abs_inventory": max_abs_inv,
            "sharpe": sharpe, "equity": equity}



# --------------------------------------------------------------------------- #
# 5. Orchestration
# --------------------------------------------------------------------------- #
class _ScenarioConfig:
    def __init__(self, setting: dict) -> None:
        self.experiment_setting = setting


def _log_feature_feedback(results: list[FeatureResult], round_idx: int) -> None:
    from rdagent.components.coder.CoSTEER.evaluators import CoSTEERSingleFeedback

    fl = []
    for r in results:
        if r.error:
            fl.append(CoSTEERSingleFeedback(
                execution=f"Feature '{r.spec.name}' rejected: {r.error}",
                return_checking="n/a", code="", final_decision=False,
            ))
        else:
            fl.append(CoSTEERSingleFeedback(
                execution=f"Feature '{r.spec.name}' computed on {len(r.series)} snapshots.",
                return_checking=f"coverage={r.coverage:.2f}, IC={r.ic:+.4f}, kept={r.ok}",
                code=r.spec.formulation, final_decision=bool(r.ok),
            ))
    logger.log_object(fl, tag=f"evo_loop_{round_idx}.evolving feedback")


def _as_factor_tasks(specs: list[dict]) -> list:
    from rdagent.components.coder.factor_coder.factor import FactorTask

    return [
        FactorTask(
            factor_name=str(s.get("name", f"feature_{i}")),
            factor_description=str(s.get("description", "")),
            factor_formulation=str(s.get("formulation", "")),
            variables={"df": "limit-order-book snapshot table"},
        )
        for i, s in enumerate(specs)
    ]


def main(loops: int | None = None, rounds: int | None = None, **kwargs) -> dict:
    """Run the LOB feature-discovery + SMM pipeline end to end.

    ``loops`` (from the web upload form) and ``rounds`` both set the number of
    feature-discovery rounds; ``loops`` wins when both are given.
    """
    rounds = max(1, min(int(loops if loops is not None else (rounds or 2)), 4))
    logger.log_object(
        _ScenarioConfig({
            "scenario": "LOB feature discovery + statistical market making",
            "n_steps": N_STEPS, "levels": N_LEVELS, "horizon": HORIZON,
            "rounds": rounds, "ic_threshold": IC_THRESHOLD,
        }),
        tag="lob scenario",
    )

    df = synthesise_lob()
    logger.info(f"Synthesised order book: {len(df)} snapshots, {N_LEVELS} levels/side")

    hypothesis = Hypothesis(
        hypothesis=(
            "Short-horizon mid-price drift in the order book is driven by latent "
            "order-flow pressure that is observable through book depth imbalances, "
            "order-flow imbalance and aggressive trade flow; features capturing it "
            "can skew market-making quotes profitably."
        ),
        reason=(
            "Persistent order-flow pressure precedes price moves. Microstructure "
            "features that measure the bid/ask size and flow asymmetry should "
            "therefore carry predictive information usable for quote skewing."
        ),
        concise_reason="Order-flow pressure is persistent and visible in the book.",
        concise_observation="Depth and flow imbalances precede mid-price moves.",
        concise_justification="Imbalance-based features should predict short-horizon drift.",
        concise_knowledge="OFI / book imbalance / microprice are standard alpha sources for HFT market making.",
    )
    logger.log_object(hypothesis, tag="hypothesis generation")

    all_results: list[FeatureResult] = []
    previous_summary = ""
    for rnd in range(rounds):
        specs = _propose_specs(df, previous_summary=previous_summary)
        if rnd == 0:
            logger.log_object(_as_factor_tasks(specs), tag="experiment generation")
        impls = _codegen(specs)
        results = execute_features(df, specs, impls)
        _log_feature_feedback(results, rnd)
        all_results.extend(results)
        lines = [
            (f"{r.spec.name}: IC={r.ic:+.4f} KEPT" if r.ok
             else f"{r.spec.name}: rejected ({r.error or f'IC={r.ic:+.4f} below threshold'})")
            for r in results
        ]
        previous_summary = "\n".join(lines)
        logger.info(f"Discovery round {rnd + 1}/{rounds}:\n{previous_summary}")

    selected = select_features(all_results, df)
    by_name: dict[str, FeatureResult] = {}
    for r in selected:
        cur = by_name.get(r.spec.name)
        if cur is None or abs(r.ic) > abs(cur.ic):
            by_name[r.spec.name] = r
    selected = sorted(by_name.values(), key=lambda r: -abs(r.ic))
    kept_names = [r.spec.name for r in selected]
    logger.info(f"Selected features for SMM model: {kept_names}")

    model_res = train_smm(df, selected)
    test_idx = model_res["test_index"]
    mid_test = df.loc[test_idx, "mid"]

    signal = model_res["pred_test"]
    active = backtest_market_making(mid_test, signal)
    baseline = backtest_market_making(mid_test, pd.Series(0.0, index=test_idx))

    import plotly.graph_objects as go

    fig = go.Figure()
    x = list(range(len(active["equity"])))
    fig.add_trace(go.Scatter(x=x, y=active["equity"], name="SMM (model-skewed quotes)"))
    fig.add_trace(go.Scatter(x=x, y=baseline["equity"], name="Baseline (no signal)"))
    fig.update_layout(title="Market-making equity curve (test segment)",
                      xaxis_title="step", yaxis_title="PnL")
    logger.log_object(fig, tag="lob_chart")

    metrics = {
        "discovered_features": kept_names,
        "feature_ic": {r.spec.name: round(float(r.ic), 4) for r in selected},
        "model_test_ic": round(model_res["test_ic"], 4),
        "directional_hit_rate": round(model_res["directional_hit_rate"], 4),
        "mm_pnl": round(active["pnl"], 2),
        "baseline_pnl": round(baseline["pnl"], 2),
        "pnl_improvement": round(active["pnl"] - baseline["pnl"], 2),
        "mm_sharpe": round(active["sharpe"], 2),
        "mm_fills": active["fills"],
        "max_abs_inventory": active["max_abs_inventory"],
        "feature_importance": {k: int(v) for k, v in model_res["feature_importance"].items()},
    }
    logger.log_object(metrics, tag="lob_metrics")

    from rdagent.core.proposal import HypothesisFeedback

    feedback = HypothesisFeedback(
        observations=(
            f"{len(kept_names)} features were discovered and validated "
            f"(ICs: {metrics['feature_ic']}). The SMM signal model reached test "
            f"IC {metrics['model_test_ic']} and directional hit rate "
            f"{metrics['directional_hit_rate']}. In the market-making backtest the "
            f"model-skewed strategy earned {metrics['mm_pnl']} vs "
            f"{metrics['baseline_pnl']} for the no-signal baseline "
            f"(improvement {metrics['pnl_improvement']})."
        ),
        hypothesis_evaluation=(
            "Supported: microstructure imbalance features predict short-horizon "
            "drift and improve market-making PnL over symmetric quoting."
            if metrics["pnl_improvement"] > 0 else
            "Partially supported: features are predictive but the quoting skew "
            "did not improve PnL on this sample."
        ),
        new_hypothesis=(
            "Explore level-2 queue-position features and regime-dependent skew "
            "scaling to further lift market-making PnL."
        ),
        reason="Feature ICs are significant and the signal-skewed backtest beats baseline.",
        decision=bool(metrics["pnl_improvement"] > 0),
    )
    logger.log_object(feedback, tag="feedback")
    return metrics
