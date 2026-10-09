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
