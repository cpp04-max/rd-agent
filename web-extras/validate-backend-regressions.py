from __future__ import annotations
import ast
import sys
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
print("[backend-regression] all checks passed")
