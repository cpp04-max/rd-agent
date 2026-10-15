from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/app/RD-Agent")

from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace


def exercise(template_rel: str, required_config: str) -> None:
    template = root / template_rel
    ws = QlibFBWorkspace(template_folder_path=template)
    try:
        assert ws.workspace_path.exists(), "workspace should exist after initialization"
        assert required_config in ws.file_dict, f"{required_config} not persisted in file_dict"

        # Simulate exactly what a Fly redeploy does to an old checkpoint: the Python
        # object/file_dict survives in the durable checkpoint but its old /app workspace
        # directory has disappeared.
        shutil.rmtree(ws.workspace_path)
        assert not ws.workspace_path.exists(), "failed to simulate missing workspace"

        ws.ensure_materialized()
        assert ws.workspace_path.exists(), "ensure_materialized did not recreate workspace"
        assert (ws.workspace_path / required_config).exists(), "template config was not restored"

        # Reproduce the failing line from factor/model runner before qrun.
        parquet = ws.workspace_path / "combined_factors_df.parquet"
        pd.DataFrame({"x": [1.0, 2.0]}).to_parquet(parquet, engine="pyarrow")
        assert parquet.exists() and parquet.stat().st_size > 0, "parquet write failed after rehydration"

        # A second call must be idempotent and must not destroy generated parquet data.
        ws.ensure_materialized()
        assert parquet.exists(), "materialization unexpectedly removed generated parquet"
        assert (ws.workspace_path / required_config).exists(), "config missing after second materialization"
    finally:
        shutil.rmtree(ws.workspace_path, ignore_errors=True)


exercise(
    "rdagent/scenarios/qlib/experiment/factor_template",
    "conf_combined_factors_sota_model.yaml",
)
exercise(
    "rdagent/scenarios/qlib/experiment/model_template",
    "conf_sota_factors_model.yaml",
)

print("[runtime-regression] resumed Qlib workspace rehydration + parquet writes: OK")


# P69: reproduce a deep continuation chain where the immediate parent has no direct
# RESULT events but its ancestor does. This is the live-training blank RESULT bug.
import importlib
import json
import tempfile

server_mod = importlib.import_module("rdagent.log.server.app")
_original_root = server_mod.log_folder_path
_original_collect = server_mod._collect_live_result_messages
_original_processes = server_mod.rdagent_processes

def _metric(loop_id: int, value: float):
    return {
        "tag": "feedback.metric",
        "loop_id": loop_id,
        "timestamp": f"2026-10-09T00:00:0{loop_id}+00:00",
        "content": {"result": {"IC": value}},
    }

with tempfile.TemporaryDirectory() as tmp:
    trace_root = Path(tmp)
    scenario = trace_root / "Finance Whole Pipeline"
    base = scenario / "base"
    middle = scenario / "middle"
    leaf = scenario / "leaf"
    for path in (base, middle, leaf):
        path.mkdir(parents=True, exist_ok=True)

    # middle continues base through loop 1; leaf continues middle from loop 2 coding.
    (middle / "_resume_meta.json").write_text(
        json.dumps(
            {
                "source_id": "Finance Whole Pipeline/base",
                "checkpoint": {
                    "loop_index": 1,
                    "step_name": "record",
                    "step_index": 4,
                },
                "created_at": "2026-10-09T00:10:00+00:00",
            }
        )
    )
    (leaf / "_resume_meta.json").write_text(
        json.dumps(
            {
                "source_id": "Finance Whole Pipeline/middle",
                "checkpoint": {
                    "loop_index": 2,
                    "step_name": "coding",
                    "step_index": 1,
                },
                "created_at": "2026-10-09T00:20:00+00:00",
            }
        )
    )

    direct = {
        str(base.resolve()): [_metric(0, 0.01), _metric(1, 0.02)],
        # Immediate parent intentionally has no direct RESULT rows.
        str(middle.resolve()): [],
        str(leaf.resolve()): [],
    }

    def _fake_collect(trace_dir, trace_id):
        return list(direct.get(str(Path(trace_dir).resolve()), []))

    try:
        server_mod.log_folder_path = trace_root
        server_mod._collect_live_result_messages = _fake_collect
        server_mod.rdagent_processes = {}

        inherited, info = server_mod._resume_parent_result_messages(leaf)
        rows, _ = server_mod._live_result_snapshot_from_messages(inherited)
        assert [row["loop_id"] for row in rows] == [0, 1], (
            "deep continuation did not inherit grandparent RESULT rows"
        )
        assert int(info.get("ancestry_depth", 0)) >= 1

        # Add a cycle and prove bounded recursion does not hang or invent rows.
        (base / "_resume_meta.json").write_text(
            json.dumps(
                {
                    "source_id": "Finance Whole Pipeline/leaf",
                    "checkpoint": {
                        "loop_index": 1,
                        "step_name": "record",
                        "step_index": 4,
                    },
                    "created_at": "2026-10-09T00:00:00+00:00",
                }
            )
        )
        inherited_cycle, _ = server_mod._resume_parent_result_messages(leaf)
        cycle_rows, _ = server_mod._live_result_snapshot_from_messages(inherited_cycle)
        assert len(cycle_rows) <= 2, "cycle guard duplicated/invented RESULT rows"
    finally:
        server_mod.log_folder_path = _original_root
        server_mod._collect_live_result_messages = _original_collect
        server_mod.rdagent_processes = _original_processes

print("[runtime-regression] recursive continuation RESULT inheritance: OK")


# P75: build a tiny modern Qlib provider using the exact custom binary writer and
# read the selected custom field back through qlib. This catches incorrect calendar
# offsets, binary layout, instrument files, or field naming without any network call.
import numpy as np
import qlib
from qlib.data import D
from rdagent.scenarios.qlib.experiment import modern_csi300_data as modern_data

with tempfile.TemporaryDirectory() as tmp:
    provider = Path(tmp) / "provider"
    calendar = [
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
        pd.Timestamp("2024-01-04"),
    ]
    panel = pd.DataFrame(
        {
            "datetime": calendar,
            "instrument": ["SH600000"] * 3,
            "$open": [10.0, 10.5, 10.8],
            "$close": [10.2, 10.7, 11.0],
            "$high": [10.4, 10.9, 11.2],
            "$low": [9.9, 10.3, 10.6],
            "$volume": [1000.0, 1100.0, 1200.0],
            "$factor": [1.0, 1.0, 1.0],
            "$amount": [10000.0, 11800.0, 13200.0],
            "$db_pb": [1.1, 1.2, 1.3],
            "$csi300_weight": [0.4, 0.4, 0.4],
        }
    )
    membership = [("SH600000", "2024-01-02", "2024-01-04")]
    index_df = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103", "20240104"],
            "open": [3500.0, 3510.0, 3520.0],
            "close": [3505.0, 3515.0, 3530.0],
            "high": [3510.0, 3520.0, 3540.0],
            "low": [3490.0, 3500.0, 3510.0],
            "vol": [1e6, 1.1e6, 1.2e6],
            "amount": [2e8, 2.1e8, 2.2e8],
        }
    )
    modern_data._write_bin_provider(
        provider,
        calendar,
        panel,
        membership,
        index_df,
        [
            "$open", "$close", "$high", "$low", "$volume", "$factor",
            "$amount", "$db_pb", "$csi300_weight",
        ],
    )

    raw = np.fromfile(
        provider / "features" / "sh600000" / "db_pb.day.bin",
        dtype="<f4",
    )
    assert raw.shape == (4,), f"unexpected Qlib binary length: {raw.shape}"
    assert raw[0] == 0.0, f"unexpected Qlib calendar offset: {raw[0]}"
    assert np.allclose(raw[1:], [1.1, 1.2, 1.3], atol=1e-6)

    qlib.init(provider_uri=str(provider), region="cn")
    values = D.features(
        ["SH600000"],
        ["$close", "$db_pb", "$csi300_weight"],
        start_time="2024-01-02",
        end_time="2024-01-04",
        freq="day",
    )
    assert len(values) == 3, f"Qlib did not read all synthetic modern rows: {len(values)}"
    assert np.allclose(values["$db_pb"].to_numpy(), [1.1, 1.2, 1.3], atol=1e-6)
    assert np.allclose(values["$csi300_weight"].to_numpy(), [0.4, 0.4, 0.4], atol=1e-6)

    cfg = modern_data.normalize_dataset_config(
        {"mode": "modern", "families": ["daily_basic"]}
    )
    assert "price_volume" in cfg["families"] and "csi300_membership" in cfg["families"]
    assert "daily_basic" in cfg["families"]
    assert cfg["split"]["test_start"] == "2024-01-01"

print("[runtime-regression] modern CSI300 Qlib provider + custom field readback: OK")
