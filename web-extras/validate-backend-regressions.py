from __future__ import annotations
import ast
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/app/RD-Agent")

def read(rel):
    path = root / rel
    if not path.exists():
        raise AssertionError("missing expected file: " + rel)
    value = path.read_text()
    if rel.endswith(".py"):
        ast.parse(value)
    return value

workspace = read("rdagent/scenarios/qlib/experiment/workspace.py")
factor_runner = read("rdagent/scenarios/qlib/developer/factor_runner.py")
model_runner = read("rdagent/scenarios/qlib/developer/model_runner.py")
factor_code = read("rdagent/components/coder/factor_coder/factor.py")
quant = read("rdagent/app/qlib_rd_loop/quant.py")
loop = read("rdagent/utils/workflow/loop.py")
server = read("rdagent/log/server/app.py")
litellm = read("rdagent/oai/backend/litellm.py")

checks = {
    "qlib_local_cache_disabled": "enable_cache=False" in workspace,
    "workspace_rehydration": (
        "def ensure_materialized(self)" in workspace
        and "self.prepare()" in workspace
        and "self.inject_files(**dict(self.file_dict))" in workspace
        and "self.ensure_materialized()" in workspace
    ),
    "fresh_qrun_start_marker": "[rd-agent] FRESH_QRUN config=" in workspace,
    "fresh_qrun_done_marker": "[rd-agent] FRESH_QRUN_DONE config=" in workspace,
    "qrun_exit_status": "qrun_exit_code=" in workspace,
    "factor_runner_result_cache_disabled":
        "@cache_with_pickle(CachedRunner.get_cache_key" not in factor_runner,
    "model_runner_result_cache_disabled":
        "@cache_with_pickle(CachedRunner.get_cache_key" not in model_runner,
    "factor_cache_tracks_data":
        "daily_pv.h5" in factor_code and "_data_fingerprint" in factor_code,
    "execution_failure_guard": "_execution_failure_pending" in quant,
    "pre_hypothesis_budget_guard":
        "RDAGENT_MIN_HYPOTHESIS_START_SECONDS" in quant,
    "factor_budget_guard_90m":
        'RDAGENT_MIN_FACTOR_LOOP_SECONDS", "5400"' in loop,
    "resume_selected_loop": "_resume_start_loop_idx" in loop,
    "live_result_endpoint": '@app.route("/result/live"' in server,
    "continuation_result_inheritance": "continuation_source" in server,
    "terminal_failure_summary": "execution_failure" in server,
    "secret_redaction":
        "[REDACTED]" in litellm
        and 'logger.info(f"{LITELLM_SETTINGS}")' not in litellm,
    "legacy_stale_qrun_migration":
        "_resume_legacy_stale_qrun_state" in server
        and "legacy_stale_qrun_repair" in server,
    "workspace_materialization_method":
        "def ensure_materialized(self)" in workspace,
    "factor_runner_materializes_before_write":
        "exp.experiment_workspace.ensure_materialized()" in factor_runner
        and factor_runner.find("ensure_materialized()") < factor_runner.find("to_parquet("),
    "model_runner_materializes_before_write":
        "exp.experiment_workspace.ensure_materialized()" in model_runner
        and model_runner.find("ensure_materialized()") < model_runner.find("to_parquet("),
    "all_factor_parquet_writes_guarded":
        factor_runner.count('target_path.parent.mkdir(parents=True, exist_ok=True)')
        >= factor_runner.count("to_parquet(target_path"),
    "all_model_parquet_writes_guarded":
        model_runner.count('target_path.parent.mkdir(parents=True, exist_ok=True)')
        >= model_runner.count("to_parquet(target_path"),
    "budget_action_fallback":
        '_candidate_name = type(_candidate).__name__.lower()' in loop,
    "workspace_loss_fallback":
        "resumed Qlib workspace disappeared" in quant
        and "cannot save file into a non-existent directory" in server,
    "workspace_crash_resume_rewind":
        "_resume_terminal_workspace_crash_state" in server
        and "terminal_workspace_crash_repair" in server,
    "recursive_result_inheritance":
        "_resume_parent_result_messages(" in server
        and "_visited: set[str] | None = None" in server
        and "_depth + 1" in server
        and "continuation ancestry cycle detected" in server,
    "qrun_timeout_configurable":
        "RDAGENT_QRUN_TIMEOUT_SECONDS" in workspace
        and 'running_timeout_period=_qrun_timeout' in workspace
        and 'timeout={getattr(qtde.conf, \'running_timeout_period\', None)}s' in workspace,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print("[backend-regression] " + name + ": " + ("OK" if ok else "FAIL"))
if failed:
    raise SystemExit("backend regression checks failed: " + ", ".join(failed))

section = workspace[workspace.find("class QlibFBWorkspace"):]
if "LocalEnv(" not in section or "enable_cache=False" not in section:
    raise SystemExit("Qlib LocalEnv fallback is not explicitly cache-disabled")
# Execute the actual patched RESULT inheritance helper without importing Flask/RD-Agent.
# This catches recursive-ancestry logic errors in patch-smoke, independently of Docker Hub.
_server_tree = ast.parse(server)
_wanted = {"_resume_parent_result_messages", "_live_result_snapshot_from_messages"}
_nodes = [
    node for node in _server_tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _wanted
]
if {node.name for node in _nodes} != _wanted:
    raise SystemExit("could not extract patched RESULT helper functions for runtime regression")

class _DummyLogger:
    def exception(self, *args, **kwargs):
        pass

class _DummyApp:
    logger = _DummyLogger()

_ns = {
    "Path": Path,
    "os": os,
    "rdagent_processes": {},
    "app": _DummyApp(),
}
exec(compile(ast.Module(body=_nodes, type_ignores=[]), "<result-regression>", "exec"), _ns)

def _metric(loop_id, value):
    return {
        "tag": "feedback.metric",
        "loop_id": loop_id,
        "timestamp": "2026-10-09T00:00:00+00:00",
        "content": {"result": {"IC": value}},
    }

with tempfile.TemporaryDirectory() as _tmp:
    _trace_root = Path(_tmp)
    _scenario = _trace_root / "Finance Whole Pipeline"
    _base = _scenario / "base"
    _middle = _scenario / "middle"
    _leaf = _scenario / "leaf"
    for _path in (_base, _middle, _leaf):
        _path.mkdir(parents=True, exist_ok=True)

    (_middle / "_resume_meta.json").write_text(json.dumps({
        "source_id": "Finance Whole Pipeline/base",
        "checkpoint": {"loop_index": 1, "step_name": "record", "step_index": 4},
        "created_at": "2026-10-09T00:10:00+00:00",
    }))
    (_leaf / "_resume_meta.json").write_text(json.dumps({
        "source_id": "Finance Whole Pipeline/middle",
        "checkpoint": {"loop_index": 2, "step_name": "coding", "step_index": 1},
        "created_at": "2026-10-09T00:20:00+00:00",
    }))

    _direct = {
        str(_base.resolve()): [_metric(0, 0.01), _metric(1, 0.02), _metric(2, 0.99)],
        str(_middle.resolve()): [],
        str(_leaf.resolve()): [],
    }
    def _fake_collect(trace_dir, trace_id):
        return list(_direct.get(str(Path(trace_dir).resolve()), []))

    _ns["log_folder_path"] = _trace_root
    _ns["_collect_live_result_messages"] = _fake_collect
    _inherit = _ns["_resume_parent_result_messages"]
    _snapshot = _ns["_live_result_snapshot_from_messages"]

    _messages, _info = _inherit(_leaf)
    _rows, _ = _snapshot(_messages)
    if [row["loop_id"] for row in _rows] != [0, 1]:
        raise SystemExit(
            "recursive RESULT inheritance failed: expected ancestor loops [0, 1], got "
            + repr([row["loop_id"] for row in _rows])
        )
    if any(row["loop_id"] == 2 for row in _rows):
        raise SystemExit("checkpoint filtering resurrected a post-branch RESULT loop")

    # Create an ancestry cycle and verify it terminates without adding invalid rows.
    (_base / "_resume_meta.json").write_text(json.dumps({
        "source_id": "Finance Whole Pipeline/leaf",
        "checkpoint": {"loop_index": 1, "step_name": "record", "step_index": 4},
        "created_at": "2026-10-09T00:00:00+00:00",
    }))
    _cycle_messages, _ = _inherit(_leaf)
    _cycle_rows, _ = _snapshot(_cycle_messages)
    if [row["loop_id"] for row in _cycle_rows] != [0, 1]:
        raise SystemExit("RESULT ancestry cycle guard failed or duplicated invalid loops")

print("[backend-regression] recursive continuation RESULT runtime: OK")
print("[backend-regression] all checks passed")
