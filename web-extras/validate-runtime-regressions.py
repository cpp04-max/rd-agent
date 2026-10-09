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
