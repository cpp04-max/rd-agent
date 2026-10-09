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
    "workspace_rehydration": "self.inject_files(**self.file_dict)" in workspace,
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
