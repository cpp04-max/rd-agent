"""Build-time backend patches: make upstream RD-Agent run inside this container.

Upstream RD-Agent executes generated code in conda envs / Docker containers and
its dashboard has no live log streaming. This container is plain CPython + Flask,
so without these patches the scenarios crash ("No hypothesis generated ...") or
the UI cannot show progress. Grouped by concern:

ENV  - run generated code in the container's own Python (P1-P4, P11)
    Each patched env-selection keeps conda/docker when actually available and
    otherwise falls back to a LocalEnv whose bin_path carries the container
    PATH. (LocalEnv otherwise builds the subprocess PATH from conf.bin_path
    plus /bin:/usr/bin only; in python:3.10-slim the python/qrun binaries live
    in /usr/local/bin, so without bin_path every spawned `python ...` fails
    with "No such file or directory".)

      P1  factor_coder/config.py          get_factor_env()
      P2  model_coder/conf.py             get_model_env()
      P3  qlib/experiment/workspace.py    QlibFBWorkspace.execute()
      P4  qlib/experiment/utils.py        generate_data_folder_from_qlib()
      P11 model_coder/model.py            ModelCoder.execute()

DATA - qlib market-data provisioning and dataset-build fixes (P5, P5b, P6)
      P5   factor_data_template/generate.py  cap universe via RDAGENT_QLIB_UNIVERSE
      P5b  factor_data_template/generate.py  intersect the debug block with it
      P6   log/server/app.py                 download cn_data once before fin_* runs
                                             (body lives in injected/qlib_provision.py)

STREAM - live "thinking flow" for the dashboard (P8-P10)
      P8   log/server/app.py  /progress stdout-tail endpoint
                              (body lives in injected/progress_endpoint.py)
      P9   log/server/app.py  stdout path fallback for traces reloaded after restart
      P10  log/server/app.py  line-buffered run stdout

ROBUSTNESS
      P7   shared/get_runtime_info.py  tolerate a runtime probe without JSON output
      P12  log/server/app.py           re-raise scenario crashes (real end_code, no fake success)
      P13  log/ui/storage.py           skip research.tasks rendering when no tasks were extracted
      P14  utils/qlib.py               validate_qlib_features without conda

SCOPE - this deployment reproduces ONLY RD-Agent(Q) (arXiv:2505.15155): the joint
        factor + model co-optimization loop exposed as the "Finance Whole Pipeline"
        scenario (fin_quant). Every other upstream scenario is disabled at /upload.
      P15  log/server/app.py           reject any /upload that is not the RD-Agent(Q) pipeline
      P16  log/server/app.py           startup banner so the live thinking-flow shows immediately
      P17  components/workflow/rd_loop.py  bound base-factor qlib validation (was a silent ~1h block)

All patches are strict-match: the build fails loudly if upstream drifts. Large
injected blocks live as real, lintable Python files in web-extras/injected/;
the patcher splices them in at the anchors below.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

LOCAL_CONF = 'LocalConf(default_entry="python main.py", bin_path=os.environ.get("PATH", ""))'


def patch(rel: str, old: str, new: str, note: str):
    p = ROOT / rel
    s = p.read_text()
    if old not in s:
        print(f"PATCH FAILED [{note}]: pattern not found in {rel}", flush=True)
        sys.exit(1)
    if s.count(old) > 1:
        print(f"PATCH FAILED [{note}]: pattern not unique in {rel}", flush=True)
        sys.exit(1)
    p.write_text(s.replace(old, new))
    print(f"patched {rel} ({note})", flush=True)


INJECTED = Path(__file__).resolve().parent / "injected"


def snippet(name: str) -> str:
    """Load an injected code block (kept as a real .py file so it stays lintable)."""
    text = (INJECTED / name).read_text().rstrip("\n")
    ast.parse(text + "\n")
    return text


# ---------------------------------------------------------------- P1
patch(
    "rdagent/components/coder/factor_coder/config.py",
    "import os\nfrom typing import Optional",
    "import os\nimport shutil\nfrom typing import Optional",
    "P1 import shutil",
)
patch(
    "rdagent/components/coder/factor_coder/config.py",
    "from rdagent.utils.env import CondaConf, Env, LocalEnv",
    "from rdagent.utils.env import CondaConf, Env, LocalConf, LocalEnv",
    "P1 import LocalConf",
)
patch(
    "rdagent/components/coder/factor_coder/config.py",
    "    conf = FactorCoSTEERSettings()\n"
    "    if hasattr(conf, \"python_bin\"):\n"
    "        env = LocalEnv(conf=(CondaConf(conda_env_name=os.environ.get(\"CONDA_DEFAULT_ENV\"))))",
    "    conf = FactorCoSTEERSettings()\n"
    "    _conda_env_name = os.environ.get(\"CONDA_DEFAULT_ENV\")\n"
    "    if _conda_env_name and shutil.which(\"conda\"):\n"
    "        env = LocalEnv(conf=(CondaConf(conda_env_name=_conda_env_name)))\n"
    "    else:\n"
    f"        env = LocalEnv(conf={LOCAL_CONF})",
    "P1 get_factor_env local fallback",
)

# ---------------------------------------------------------------- P2
patch(
    "rdagent/components/coder/model_coder/conf.py",
    "from typing import Optional\n",
    "import os\nimport shutil\nfrom typing import Optional\n",
    "P2 imports",
)
patch(
    "rdagent/components/coder/model_coder/conf.py",
    "from rdagent.utils.env import Env, QlibCondaConf, QlibCondaEnv, QTDockerEnv",
    "from rdagent.utils.env import Env, LocalConf, LocalEnv, QlibCondaConf, QlibCondaEnv, QTDockerEnv",
    "P2 import LocalEnv",
)
patch(
    "rdagent/components/coder/model_coder/conf.py",
    "    elif conf.env_type == \"conda\":\n"
    "        env = QlibCondaEnv(conf=QlibCondaConf())",
    "    elif conf.env_type == \"conda\":\n"
    "        if shutil.which(\"conda\"):\n"
    "            env = QlibCondaEnv(conf=QlibCondaConf())\n"
    "        else:\n"
    f"            env = LocalEnv(conf={LOCAL_CONF})",
    "P2 get_model_env local fallback",
)

# ---------------------------------------------------------------- P3
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    "import re\nfrom pathlib import Path",
    "import os\nimport re\nimport shutil\nfrom pathlib import Path",
    "P3 imports",
)
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    "        elif MODEL_COSTEER_SETTINGS.env_type == \"conda\":\n"
    "            qtde = QlibCondaEnv(conf=QlibCondaConf())",
    "        elif MODEL_COSTEER_SETTINGS.env_type == \"conda\":\n"
    "            if shutil.which(\"conda\"):\n"
    "                qtde = QlibCondaEnv(conf=QlibCondaConf())\n"
    "            else:\n"
    "                from rdagent.utils.env import LocalConf, LocalEnv\n"
    "\n"
    f"                qtde = LocalEnv(conf={LOCAL_CONF})",
    "P3 QlibFBWorkspace local fallback",
)

# ---------------------------------------------------------------- P4
patch(
    "rdagent/scenarios/qlib/experiment/utils.py",
    "import random\nimport re\nimport shutil",
    "import os\nimport random\nimport re\nimport shutil",
    "P4 import os",
)
patch(
    "rdagent/scenarios/qlib/experiment/utils.py",
    "def generate_data_folder_from_qlib():\n"
    "    template_path = Path(__file__).parent / \"factor_data_template\"\n"
    "    qtde = QTDockerEnv()\n"
    "    qtde.prepare()",
    "def generate_data_folder_from_qlib():\n"
    "    template_path = Path(__file__).parent / \"factor_data_template\"\n"
    "    if os.environ.get(\"RDAGENT_QLIB_DATA_GEN_DOCKER\") == \"1\":\n"
    "        qtde = QTDockerEnv()\n"
    "        qtde.prepare()\n"
    "    else:\n"
    "        from rdagent.utils.env import LocalConf, LocalEnv\n"
    "\n"
    f"        qtde = LocalEnv(conf={LOCAL_CONF})",
    "P4 data folder gen local env",
)

# ---------------------------------------------------------------- P5
patch(
    "rdagent/scenarios/qlib/experiment/factor_data_template/generate.py",
    "instruments = D.instruments()",
    "import os\n\ninstruments = D.instruments(market=os.environ.get(\"RDAGENT_QLIB_UNIVERSE\", \"csi300\"))",
    "P5 limit universe",
)

# ---------------------------------------------------------------- P5b
old = (
    "data = (\n"
    "    (\n"
    '        D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")\n'
    "        .swaplevel()\n"
    "        .sort_index()\n"
    "    )\n"
    "    .swaplevel()\n"
    '    .loc[data.reset_index()["instrument"].unique()[:100]]\n'
    "    .swaplevel()\n"
    "    .sort_index()\n"
    ")"
)
new = (
    "_debug = (\n"
    '    D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")\n'
    "    .swaplevel()\n"
    "    .sort_index()\n"
    ")\n"
    "_debug = _debug.swaplevel()\n"
    '_present = set(_debug.reset_index()["instrument"].unique())\n'
    '_pick = [i for i in data.reset_index()["instrument"].unique() if i in _present][:100]\n'
    "data = _debug.loc[_pick].swaplevel().sort_index()"
)
patch(
    "rdagent/scenarios/qlib/experiment/factor_data_template/generate.py",
    old,
    new,
    "P5b debug-block intersection",
)

# ---------------------------------------------------------------- P6
patch(
    "rdagent/log/server/app.py",
    '_TARGETS_WITHOUT_USER_INTERACTION = {"general_model", "fin_factor_report"}',
    '_TARGETS_WITHOUT_USER_INTERACTION = {"general_model", "fin_factor_report"}\n\n\n'
    + snippet("qlib_provision.py"),
    "P6 provision qlib data helper",
)
for tgt in ("fin_quant",):  # only the RD-Agent(Q) joint pipeline is served
    patch(
        "rdagent/log/server/app.py",
        f"                        {tgt}(**self.kwargs)",
        f"                        _ensure_qlib_cn_data()\n                        {tgt}(**self.kwargs)",
        f"P6 provision before {tgt}",
    )

# ---------------------------------------------------------------- P7
patch(
    "rdagent/scenarios/shared/get_runtime_info.py",
    "    json_match = re.search(r\"\\{.*\\}\", stdout, re.DOTALL)\n"
    "    return json.dumps(json.loads(json_match.group()), indent=2)",
    "    json_match = re.search(r\"\\{.*\\}\", stdout, re.DOTALL)\n"
    "    if json_match is None:\n"
    "        return \"{}\"\n"
    "    return json.dumps(json.loads(json_match.group()), indent=2)",
    "P7 tolerant runtime probe",
)


# ---------------------------------------------------------------- P8
patch(
    "rdagent/log/server/app.py",
    '@app.route("/traces", methods=["GET"])',
    snippet("progress_endpoint.py")
    + '\n\n\n@app.route("/traces", methods=["GET"])',
    "P8 /progress stdout tail endpoint",
)


# ---------------------------------------------------------------- P9
# After a server restart, traces are reloaded from disk without a live task,
# so `task.stdout_path` is empty and /progress + /stdout would return nothing.
# Fall back to the on-disk layout used by /upload: <trace_folder>/<scenario>/<trace_name>.log
patch(
    "rdagent/log/server/app.py",
    "    task = rdagent_processes.get(str(log_folder_path / normalized_trace_id))\n"
    "    if task is None or not task.stdout_path:\n"
    "        return None\n"
    "\n"
    "    stdout_path = Path(task.stdout_path).resolve()",
    "    task = rdagent_processes.get(str(log_folder_path / normalized_trace_id))\n"
    "    stdout_path = None\n"
    "    if task is not None and task.stdout_path:\n"
    "        stdout_path = Path(task.stdout_path)\n"
    "    else:\n"
    "        # Traces reloaded from disk after a restart have no live task;\n"
    "        # /upload persists stdout at <trace_folder>/<scenario>/<trace_name>.log.\n"
    "        _trace_dir = log_folder_path / normalized_trace_id\n"
    "        # Always return the deterministic path (even before the child\n"
    "        # creates it) so /progress can infer liveness from trace-dir mtime.\n"
    "        stdout_path = _trace_dir.parent / (_trace_dir.name + \".log\")\n"
    "\n"
    "    stdout_path = stdout_path.resolve()",
    "P9 stdout path fallback for traces reloaded from disk",
)


# ---------------------------------------------------------------- P10
# Line-buffer the redirected stdout so the live activity panel sees output
# immediately instead of waiting for an 8KB buffer to fill.
patch(
    "rdagent/log/server/app.py",
    '        with open(self.stdout_path, "w") as log_file:',
    '        with open(self.stdout_path, "w", buffering=1) as log_file:',
    "P10 line-buffered run stdout",
)


# ---------------------------------------------------------------- P11
# The CoSTEER model coder (the model step of the fin_quant pipeline) executes
# generated code via MODEL_COSTEER env selection.
# get_model_env() in conf.py already gets a conda->LocalEnv fallback from P2,
# but ModelCoder.execute() in model.py picks its env independently and dies when
# conda/docker are absent (prod logs: conda exit 127, then a PATH without
# /usr/local/bin -> 'python' not found). Add the same LocalEnv fallback.
patch(
    "rdagent/components/coder/model_coder/model.py",
    "import pickle\nimport site\nimport traceback\n",
    "import os\nimport pickle\nimport shutil\nimport site\nimport traceback\n",
    "P11b model.py imports",
)
patch(
    "rdagent/components/coder/model_coder/model.py",
    "                if MODEL_COSTEER_SETTINGS.env_type == \"docker\":\n"
    "                    qtde = QTDockerEnv()\n"
    "                elif MODEL_COSTEER_SETTINGS.env_type == \"conda\":\n"
    "                    qtde = QlibCondaEnv(conf=QlibCondaConf())\n"
    "                else:\n"
    "                    raise ValueError(f\"Unknown env_type: {MODEL_COSTEER_SETTINGS.env_type}\")",
    "                if MODEL_COSTEER_SETTINGS.env_type == \"docker\" and shutil.which(\"docker\"):\n"
    "                    qtde = QTDockerEnv()\n"
    "                elif MODEL_COSTEER_SETTINGS.env_type == \"conda\" and shutil.which(\"conda\"):\n"
    "                    qtde = QlibCondaEnv(conf=QlibCondaConf())\n"
    "                else:\n"
    "                    from rdagent.utils.env import LocalConf, LocalEnv\n"
    "\n"
    f"                    qtde = LocalEnv(conf={LOCAL_CONF})",
    "P11b model execute local fallback",
)

patch(
    "rdagent/log/server/app.py",
    "                except Exception:\n                    traceback.print_exc()",
    "                except Exception:\n                    traceback.print_exc()\n                    raise",
    "P12 re-raise scenario crashes",
)
patch(
    "rdagent/log/ui/storage.py",
    "            else:\n"
    "                tasks: list[FactorTask | ModelTask] = obj\n"
    "            if isinstance(tasks[0], FactorTask):",
    "            else:\n"
    "                tasks: list[FactorTask | ModelTask] = obj\n"
    "            if not tasks:\n"
    "                return {}\n"
    "            if isinstance(tasks[0], FactorTask):",
    "P13 guard empty task list",
)
# ---------------------------------------------------------------- P14
# validate_qlib_features() probes user-supplied base features by running
# test_fea.py inside a conda env (rdagent4qlib). Neither this container nor
# typical sandboxes ship conda, so the interactive fin_quant loop re-asks the
# user for features forever. Fall back to a LocalEnv
# using the current interpreter (qlib is installed in it) when conda is absent.
patch(
    "rdagent/utils/qlib.py",
    "from rdagent.core.experiment import FBWorkspace\n"
    "from rdagent.utils.env import QlibCondaConf, QlibCondaEnv",
    "import os\n"
    "import shutil\n"
    "\n"
    "from rdagent.core.experiment import FBWorkspace\n"
    "from rdagent.utils.env import QlibCondaConf, QlibCondaEnv",
    "P14 qlib.py imports",
)
patch(
    "rdagent/utils/qlib.py",
    "    qlib_env = QlibCondaEnv(conf=QlibCondaConf())\n"
    "    qlib_env.prepare()\n",
    "    if shutil.which(\"conda\"):\n"
    "        qlib_env = QlibCondaEnv(conf=QlibCondaConf())\n"
    "        qlib_env.prepare()\n"
    "    else:\n"
    "        from rdagent.utils.env import LocalConf, LocalEnv\n"
    "\n"
    "        qlib_env = LocalEnv(\n"
    "            conf=LocalConf(default_entry=\"python test_fea.py\", bin_path=os.environ.get(\"PATH\", \"\"))\n"
    "        )\n",
    "P14 validate without conda",
)

# ---------------------------------------------------------------- P15
# Scope lock: this deployment reproduces ONLY RD-Agent(Q) (arXiv:2505.15155) —
# the joint factor + model co-optimization loop served as the "Finance Whole
# Pipeline" scenario (fin_quant). Reject every other scenario at the /upload
# entry point so the app stays single-purpose even though upstream ships more.
patch(
    "rdagent/log/server/app.py",
    '    scenario = request.form.get("scenario")\n'
    '    files = request.files.getlist("files")',
    '    scenario = request.form.get("scenario")\n'
    '    if scenario != "Finance Whole Pipeline":\n'
    '        return jsonify({"error": "This deployment reproduces RD-Agent(Q) '
    '(arXiv:2505.15155) only, via the Finance Whole Pipeline scenario."}), 400\n'
    '    files = request.files.getlist("files")',
    "P15 restrict /upload to the RD-Agent(Q) pipeline",
)

# ---------------------------------------------------------------- P16
# Emit an immediate stdout line when a task process starts so the dashboard's
# live "thinking flow" (which tails the run stdout via /progress) shows activity
# from t=0 instead of a blank panel while slow startup work runs.
patch(
    "rdagent/log/server/app.py",
    "                rdagent_logger.rebind_console_to_current_streams()\n"
    "                try:",
    "                rdagent_logger.rebind_console_to_current_streams()\n"
    "                print(\n"
    '                    f"[rd-agent] task process started: target={self.target_name} "\n'
    '                    f"kwargs={sorted(self.kwargs)}",\n'
    "                    flush=True,\n"
    "                )\n"
    "                try:",
    "P16 startup banner to run stdout",
)

# ---------------------------------------------------------------- P17
# Base-factor validation could block the whole run for up to an hour in silence.
# _init_base_features() runs BEFORE the interactor and before the RDLoop starts;
# validate_qlib_features() shells out to `timeout --kill-after=10 3600 python
# test_fea.py`, so an uploaded base_factors.json that is slow (or hangs) left the
# UI spinning with no trace messages and no thinking-flow output. Log progress and
# bound the probe to ~180s on a daemon thread; on timeout/failure fall back to the
# default base features with a clear message.
patch(
    "rdagent/components/workflow/rd_loop.py",
    "        if base_features_path is not None:\n"
    "            try:",
    "        if base_features_path is not None:\n"
    '            print(f"[rd-agent] loading base factors from {base_features_path} ...", flush=True)\n'
    "            try:",
    "P17 log base-factor loading",
)
patch(
    "rdagent/components/workflow/rd_loop.py",
    "                    if validate_qlib_features(list(features.values())):",
    "                    import threading\n"
    "\n"
    "                    _val: dict = {}\n"
    "\n"
    "                    def _validate_base_features() -> None:\n"
    '                        _val["ok"] = validate_qlib_features(list(features.values()))\n'
    "\n"
    "                    print(\n"
    '                        f"[rd-agent] validating {len(features)} base-factor expressions via qlib "\n'
    '                        "(bounded to 180s) ...",\n'
    "                        flush=True,\n"
    "                    )\n"
    "                    _thr = threading.Thread(target=_validate_base_features, daemon=True)\n"
    "                    _thr.start()\n"
    "                    _thr.join(timeout=180)\n"
    "                    if _thr.is_alive():\n"
    "                        print(\n"
    '                            "[rd-agent] base-factor validation timed out; using default base features.",\n'
    "                            flush=True,\n"
    "                        )\n"
    "                    _base_ok = (not _thr.is_alive()) and bool(_val.get(\"ok\", False))\n"
    "                    if _base_ok:",
    "P17 bound base-factor validation",
)

# ---------------------------------------------------------------- P18
# Capture a task-process crash into the run's own stdout file. Previously a crash
# before/around the stdout redirect left the run log empty, so /progress reported
# "no captured output" and the real traceback was invisible.
patch(
    "rdagent/log/server/app.py",
    "    def _run(self) -> None:",
    "    def _run_safe(self) -> None:\n"
    '        """Wrap _run so a crash before/around the stdout redirect is captured."""\n'
    "        try:\n"
    "            self._run()\n"
    "        except BaseException:\n"
    "            import traceback as _tb\n"
    "\n"
    "            try:\n"
    '                with open(self.stdout_path, "a", buffering=1) as _f:\n'
    '                    _f.write("\\n[rd-agent] task process crashed:\\n")\n'
    "                    _tb.print_exc(file=_f)\n"
    "            except OSError:\n"
    "                pass\n"
    "            raise\n"
    "\n"
    "    def _run(self) -> None:",
    "P18 crash-capturing run wrapper",
)
patch(
    "rdagent/log/server/app.py",
    "                target=self._run,",
    "                target=self._run_safe,",
    "P18 use crash-capturing wrapper as process target",
)

# ---------------------------------------------------------------- P19
# Make the initial-parameter interaction incapable of silent infinite blocking.
# Previously a lost/mismatched answer parked the run forever on a blocking
# queue get() at "Waiting for user interaction on initial parameters...". Now
# every request is (re)sent with a bounded wait; on timeout it logs a warning and
# re-requests (which also re-surfaces the dialog in the UI via a new trace
# message). Also fixes the inverted feature_codes condition and logs payload keys.
# RDAGENT_ASK_TIMEOUT (seconds, default 600) bounds each wait.
_RD_LOOP_OLD = '    def _interact_init_params(self) -> None:\n        if not (hasattr(self, "user_request_q") and hasattr(self, "user_response_q")):\n            return\n\n        logger.info("Waiting for user interaction on initial parameters...")\n        try:\n            self.user_request_q.put(\n                {\n                    "user_instruction": None,\n                }\n            )\n            res_dict = self.user_response_q.get()\n            logger.info("Received user instruction response.")\n            self.plan.update(res_dict)\n\n            if "feature_codes" not in self.plan:\n                self.plan[\n                    "user_instruction"\n                ] += f"\\n\\n{str(list(self.plan[\'feature_codes\'].keys()))} has been configured as the base factor; do not generate duplicate factors."\n            fea_valid_msg = ""\n            while True:\n                logger.info("Requesting base feature configuration from user.")\n                self.user_request_q.put(\n                    {\n                        "features": self.plan["features"],\n                        "feature_validation_msg": fea_valid_msg,\n                    }\n                )\n                self.plan["features"] = self.user_response_q.get()\n                logger.info("Received base feature configuration response.")\n                if validate_qlib_features(list(self.plan["features"].values())):\n                    logger.info(f"Base feature validation passed. {len(self.plan[\'features\'])} features selected.")\n                    break\n                else:\n                    logger.info("Base feature validation failed. Asking user to revise.")\n                    fea_valid_msg = "Some features are invalid, please revise."\n\n        except (EOFError, OSError):\n            logger.info("User interaction failed, using default initial parameters.")\n            return\n        logger.info("Received user interaction on initial parameters.")'
_RD_LOOP_NEW = '    def _interact_init_params(self) -> None:\n        if not (hasattr(self, "user_request_q") and hasattr(self, "user_response_q")):\n            return\n\n        import os\n        import queue as _queue\n\n        _ask_timeout = int(os.environ.get("RDAGENT_ASK_TIMEOUT", "600"))\n        _ask_attempts = int(os.environ.get("RDAGENT_ASK_ATTEMPTS", "3"))\n        _default_instruction = (\n            "Reproduce RD-Agent(Q) (arXiv:2505.15155): jointly optimize alpha factors and the "\n            "return-forecasting model on the CSI300 universe. Each round, form a hypothesis from "\n            "quant domain priors, implement factor and model code with Co-STEER, run a qlib "\n            "backtest, and use the feedback (IC/RankIC, annualized excess return, information "\n            "ratio, max drawdown) to choose the next research direction."\n        )\n\n        def _ask(payload, what, default=None):\n            for _attempt in range(1, max(1, _ask_attempts) + 1):\n                self.user_request_q.put(payload)\n                logger.info(\n                    f"Sent {what} request (attempt {_attempt}/{_ask_attempts}); "\n                    f"waiting up to {_ask_timeout}s for a response..."\n                )\n                try:\n                    res = self.user_response_q.get(timeout=_ask_timeout)\n                except _queue.Empty:\n                    logger.warning(f"No {what} response within {_ask_timeout}s (attempt {_attempt}).")\n                    continue\n                logger.info(\n                    f"Received {what} response with keys="\n                    f"{sorted(res) if isinstance(res, dict) else type(res).__name__}."\n                )\n                return res\n            logger.warning(\n                f"No {what} response after {_ask_attempts} attempt(s); proceeding with defaults "\n                "so the run can continue unattended."\n            )\n            return default\n\n        logger.info("Waiting for user interaction on initial parameters...")\n        try:\n            res_dict = _ask(\n                {"user_instruction": None},\n                "user-instruction",\n                {"user_instruction": _default_instruction},\n            )\n            if not isinstance(res_dict, dict) or "user_instruction" not in res_dict:\n                logger.warning("Unexpected initial-parameter payload; re-requesting user instruction.")\n                res_dict = _ask(\n                    {"user_instruction": None},\n                    "user-instruction",\n                    {"user_instruction": _default_instruction},\n                )\n            if isinstance(res_dict, dict):\n                self.plan.update(res_dict)\n            if self.plan.get("feature_codes"):\n                self.plan["user_instruction"] = str(self.plan.get("user_instruction", "")) + (\n                    f"\\n\\n{str(list(self.plan[\'feature_codes\'].keys()))} has been configured as the base factor; do not generate duplicate factors."\n                )\n            fea_valid_msg = ""\n            while True:\n                got = _ask(\n                    {"features": self.plan["features"], "feature_validation_msg": fea_valid_msg},\n                    "base-feature-configuration",\n                    None,\n                )\n                _exhausted = got is None\n                if _exhausted:\n                    got = dict(self.plan.get("features") or {})\n                self.plan["features"] = got\n                if validate_qlib_features(list(self.plan["features"].values())):\n                    logger.info(f"Base feature validation passed. {len(self.plan[\'features\'])} features selected.")\n                    break\n                if _exhausted:\n                    logger.warning("Base features invalid but no user available; proceeding anyway.")\n                    break\n                logger.info("Base feature validation failed. Asking user to revise.")\n                fea_valid_msg = "Some features are invalid, please revise."\n\n        except (EOFError, OSError):\n            logger.info("User interaction failed, using default initial parameters.")\n            return\n        logger.info("Received user interaction on initial parameters.")'
patch(
    "rdagent/components/workflow/rd_loop.py",
    _RD_LOOP_OLD,
    _RD_LOOP_NEW,
    "P19 bounded re-asking initial-parameter interaction with defaults fallback",
)

# ---------------------------------------------------------------- P20
# Never fabricate a decoy task when submitting a user response: enqueuing into a
# fresh queue nobody reads silently drops the answer and hangs the run at its
# next blocking get(), while the frontend (got 200) advances to the next dialog.
patch(
    "rdagent/log/server/app.py",
    "    trace_id = str(log_folder_path / trace_id)\n"
    "    task = _get_or_create_task(trace_id)",
    "    trace_id = str(log_folder_path / trace_id)\n"
    "    task = rdagent_processes.get(trace_id)\n"
    "    if task is None:\n"
    "        return jsonify(\n"
    '            {"error": "No running task for this trace; the run may have ended."}\n'
    "        ), 404",
    "P20 reject user-response submit for unknown trace",
)

# ---------------------------------------------------------------- P21
# Bound the remaining blocking interactions (hypothesis + feedback confirmation)
# with the same RDAGENT_ASK_TIMEOUT / RDAGENT_ASK_TIMEOUT-attempts scheme: on no
# response, continue with the unmodified hypothesis/feedback so an unattended run
# can reach the end instead of parking on a bare queue get().
_HYPO_OLD = '    def _interact_hypo(self, hypo: Hypothesis) -> Hypothesis:\n        if not (hasattr(self, "user_request_q") and hasattr(self, "user_response_q")):\n            return hypo\n\n        logger.info("Waiting for user interaction on hypothesis...")\n        try:\n            self.user_request_q.put(hypo.__dict__)\n            res_dict = self.user_response_q.get()\n            modified_hypo = type(hypo)(**res_dict)\n        except (EOFError, OSError, TypeError):\n            logger.info("User interaction failed, using original hypothesis.")\n            return hypo\n        logger.info("Received user interaction on hypothesis.")\n        return modified_hypo'
_HYPO_NEW = '    def _interact_hypo(self, hypo: Hypothesis) -> Hypothesis:\n        if not (hasattr(self, "user_request_q") and hasattr(self, "user_response_q")):\n            return hypo\n\n        import os\n        import queue as _queue\n\n        _timeout = int(os.environ.get("RDAGENT_ASK_TIMEOUT", "600"))\n        _attempts = int(os.environ.get("RDAGENT_ASK_ATTEMPTS", "3"))\n        logger.info("Waiting for user interaction on hypothesis...")\n        for _attempt in range(1, max(1, _attempts) + 1):\n            try:\n                self.user_request_q.put(hypo.__dict__)\n                logger.info(\n                    f"Sent hypothesis request (attempt {_attempt}/{_attempts}); "\n                    f"waiting up to {_timeout}s for a response..."\n                )\n                res_dict = self.user_response_q.get(timeout=_timeout)\n                modified_hypo = type(hypo)(**res_dict)\n                logger.info("Received user interaction on hypothesis.")\n                return modified_hypo\n            except _queue.Empty:\n                logger.warning(f"No hypothesis response within {_timeout}s (attempt {_attempt}).")\n            except (EOFError, OSError, TypeError):\n                logger.info("User interaction failed, using original hypothesis.")\n                return hypo\n        logger.warning("No hypothesis response; continuing with the unmodified hypothesis.")\n        return hypo'
patch(
    "rdagent/components/workflow/rd_loop.py",
    _HYPO_OLD,
    _HYPO_NEW,
    "P21 bounded hypothesis interaction",
)
_FB_OLD = '    def _interact_feedback(self, feedback: HypothesisFeedback) -> HypothesisFeedback:\n        if not (hasattr(self, "user_request_q") and hasattr(self, "user_response_q")):\n            return feedback\n\n        logger.info("Waiting for user interaction on feedback...")\n        try:\n            self.user_request_q.put(feedback.__dict__)\n            res_dict = self.user_response_q.get()\n            modified_feedback = HypothesisFeedback(**res_dict)\n        except (EOFError, OSError, TypeError):\n            logger.info("User interaction failed, using original feedback.")\n            return feedback\n        logger.info("Received user interaction on feedback.")\n        return modified_feedback'
_FB_NEW = '    def _interact_feedback(self, feedback: HypothesisFeedback) -> HypothesisFeedback:\n        if not (hasattr(self, "user_request_q") and hasattr(self, "user_response_q")):\n            return feedback\n\n        import os\n        import queue as _queue\n\n        _timeout = int(os.environ.get("RDAGENT_ASK_TIMEOUT", "600"))\n        _attempts = int(os.environ.get("RDAGENT_ASK_ATTEMPTS", "3"))\n        logger.info("Waiting for user interaction on feedback...")\n        for _attempt in range(1, max(1, _attempts) + 1):\n            try:\n                self.user_request_q.put(feedback.__dict__)\n                logger.info(\n                    f"Sent feedback request (attempt {_attempt}/{_attempts}); "\n                    f"waiting up to {_timeout}s for a response..."\n                )\n                res_dict = self.user_response_q.get(timeout=_timeout)\n                modified_feedback = type(feedback)(**res_dict)\n                logger.info("Received user interaction on feedback.")\n                return modified_feedback\n            except _queue.Empty:\n                logger.warning(f"No feedback response within {_timeout}s (attempt {_attempt}).")\n            except (EOFError, OSError, TypeError):\n                logger.info("User interaction failed, using original feedback.")\n                return feedback\n        logger.warning("No feedback response; continuing with the unmodified feedback.")\n        return feedback'
patch(
    "rdagent/components/workflow/rd_loop.py",
    _FB_OLD,
    _FB_NEW,
    "P21 bounded feedback interaction",
)

# ---------------------------------------------------------------- P22
# Fail fast on LLM auth OR quota/billing errors. A rejected key or an exhausted
# free-tier quota used to burn all 10 retries and surface as a generic
# "Failed to create chat completion after 10 retries", hiding the real cause.
# Detect both and raise immediately with an actionable stdout line the live
# panel shows at once.
_AUTH_OLD = '            except Exception as e:  # noqa: BLE001\n'
_AUTH_NEW = '            except Exception as e:  # noqa: BLE001\n                _err_text = str(e)\n                _is_auth = (\n                    "AuthenticationError" in _err_text\n                    or "Incorrect API key" in _err_text\n                    or "invalid api key" in _err_text.lower()\n                )\n                _is_quota = (\n                    "Free quota exhausted" in _err_text\n                    or "add funds" in _err_text.lower()\n                    or "insufficient balance" in _err_text.lower()\n                    or "arrearage" in _err_text.lower()\n                )\n                if _is_auth or _is_quota:\n                    if _is_quota:\n                        print(\n                            "[rd-agent] LLM QUOTA EXHAUSTED: the DashScope free-tier quota for this "\n                            "key is used up. Add funds or disable \'use free tier only\' in the Model "\n                            "Studio console (or switch key), then re-run. Not retrying.",\n                            flush=True,\n                        )\n                    else:\n                        print(\n                            "[rd-agent] LLM AUTHENTICATION FAILED: the provider rejected the configured "\n                            "API key. Fix the OPENAI_API_KEY / OPENAI_API_BASE secrets and redeploy; "\n                            "not retrying.",\n                            flush=True,\n                        )\n                    logger.error("LLM request rejected (auth or quota) - check key/quota in the console.")\n                    raise\n'
patch(
    "rdagent/oai/backend/base.py",
    _AUTH_OLD,
    _AUTH_NEW,
    "P22 fail fast on LLM auth/quota errors",
)

# ---------------------------------------------------------------- P23
# Tolerate malformed boolean env vars (a crossed Fly secret once put an API key into
# REASONING_THINK_RM, crashing the app at import in a boot loop). Warn + ignore instead.
_LLMCONF_OLD = 'LLM_SETTINGS = LLMSettings()\n'
_LLMCONF_NEW = 'import os as _os\n\n# Defensive: a crossed/mistyped Fly secret (e.g. an API key pasted into a boolean\n# setting) made pydantic raise at import and crash-loop the whole machine. Ignore\n# non-boolean values for boolean settings (with a loud warning) instead of dying.\nfor _fname, _ffield in LLMSettings.model_fields.items():\n    if _ffield.annotation is bool:\n        for _variant in (_fname, _fname.upper(), _fname.lower()):\n            _raw = _os.environ.get(_variant)\n            if _raw is not None and _raw.strip().lower() not in {\n                "true", "false", "1", "0", "yes", "no", "on", "off", ""\n            }:\n                print(\n                    f"[rd-agent] WARNING: env {_variant} for boolean setting \'{_fname}\' is not "\n                    "a boolean (looks like a secret or wrong value); ignoring it and using the "\n                    "default. Fix the Fly secret to \'true\' or \'false\'.",\n                    flush=True,\n                )\n                _os.environ.pop(_variant, None)\n\nLLM_SETTINGS = LLMSettings()\n'
patch(
    "rdagent/oai/llm_conf.py",
    _LLMCONF_OLD,
    _LLMCONF_NEW,
    "P23 ignore non-boolean values for boolean LLM settings",
)

# ---------------------------------------------------------------- P24
# Kill ANSI escape spam in logs ('[96m[0m' runs): LogColors codes are only
# emitted when stdout is a TTY; in log files/aggregators they are empty strings.
_LOGCOLORS_OLD = 'class LogColors:\n    """\n    ANSI color codes for use in console output.\n    """\n\n    RED = "\\033[91m"\n    GREEN = "\\033[92m"\n    YELLOW = "\\033[93m"\n    BLUE = "\\033[94m"\n    MAGENTA = "\\033[95m"\n    CYAN = "\\033[96m"\n    WHITE = "\\033[97m"\n    GRAY = "\\033[90m"\n    BLACK = "\\033[30m"\n\n    BOLD = "\\033[1m"\n    ITALIC = "\\033[3m"\n\n    END = "\\033[0m"\n'
_LOGCOLORS_NEW = 'import sys as _sys\n\n# Colors are only meaningful on a real terminal. In log files / log\n# aggregators they show up as useless escape spam (e.g. long runs of\n# \'[96m[0m\' for empty colored segments), so disable them off-TTY.\n_TTY = bool(getattr(_sys.stdout, "isatty", lambda: False)())\n\n\nclass LogColors:\n    """\n    ANSI color codes for use in console output (empty when not a TTY).\n    """\n\n    RED = "\\033[91m" if _TTY else ""\n    GREEN = "\\033[92m" if _TTY else ""\n    YELLOW = "\\033[93m" if _TTY else ""\n    BLUE = "\\033[94m" if _TTY else ""\n    MAGENTA = "\\033[95m" if _TTY else ""\n    CYAN = "\\033[96m" if _TTY else ""\n    WHITE = "\\033[97m" if _TTY else ""\n    GRAY = "\\033[90m" if _TTY else ""\n    BLACK = "\\033[30m" if _TTY else ""\n\n    BOLD = "\\033[1m" if _TTY else ""\n    ITALIC = "\\033[3m" if _TTY else ""\n\n    END = "\\033[0m" if _TTY else ""\n'
patch(
    "rdagent/log/utils/__init__.py",
    _LOGCOLORS_OLD,
    _LOGCOLORS_NEW,
    "P24 disable ANSI log colors off-TTY",
)

# ---------------------------------------------------------------- P25
# The qlib workflow templates hardcode n_jobs: 20, which makes qlib spawn 20
# DataLoader workers on a 2-vCPU machine (torch warns it may run slow or freeze).
# Cap to 2 to match the VM; training becomes stable and usually faster.
for _yaml in (
    "rdagent/scenarios/qlib/experiment/factor_template/conf_combined_factors_sota_model.yaml",
    "rdagent/scenarios/qlib/experiment/model_template/conf_sota_factors_model.yaml",
    "rdagent/scenarios/qlib/experiment/model_template/conf_baseline_factors_model.yaml",
):
    patch(_yaml, "            n_jobs: 20", "            n_jobs: 2", f"P25 cap n_jobs in {_yaml.split('/')[-1]}")

# ---------------------------------------------------------------- P26
# LLM-proposed training hyperparameters default to n_epochs=100; at ~minutes per
# CPU epoch a single model can eat the whole 6h loop timer. Clamp with the
# RDAGENT_MAX_EPOCHS env var (default 100 = unchanged) so ops can bound run cost.
patch(
    "rdagent/scenarios/qlib/developer/model_runner.py",
    "import pandas as pd",
    "import os\n\nimport pandas as pd",
    "P26 import os in model_runner",
)
patch(
    "rdagent/scenarios/qlib/developer/model_runner.py",
    '                    "n_epochs": str(training_hyperparameters.get("n_epochs", "100")),',
    '                    "n_epochs": str(\n'
    '                        min(\n'
    '                            int(training_hyperparameters.get("n_epochs", "100")),\n'
    '                            int(os.environ.get("RDAGENT_MAX_EPOCHS", "100")),\n'
    "                        )\n"
    "                    ),",
    "P26 clamp n_epochs in model_runner",
)
patch(
    "rdagent/scenarios/qlib/developer/factor_runner.py",
    "from pathlib import Path",
    "import os\nfrom pathlib import Path",
    "P26 import os in factor_runner",
)
patch(
    "rdagent/scenarios/qlib/developer/factor_runner.py",
    '                    "n_epochs": str(sota_training_hyperparameters.get("n_epochs", "100")),',
    '                    "n_epochs": str(\n'
    '                        min(\n'
    '                            int(sota_training_hyperparameters.get("n_epochs", "100")),\n'
    '                            int(os.environ.get("RDAGENT_MAX_EPOCHS", "100")),\n'
    "                        )\n"
    "                    ),",
    "P26 clamp n_epochs in factor_runner",
)

# ---------------------------------------------------------------- P27
# Avoid starting expensive work when the remaining timer is clearly insufficient.
# P49 makes this action-aware: factor loops default to 1800s, model loops to 3600s.
# This prevents the old blanket 3600s threshold from aborting a fast factor loop after
# its hypothesis was already generated. Tunable via RDAGENT_MIN_FACTOR_LOOP_SECONDS,
# RDAGENT_MIN_MODEL_LOOP_SECONDS, and RDAGENT_MIN_LOOP_SECONDS.
_LOOPGUARD_OLD = '            else:\n                logger.info(f"Timer remaining time: {self.timer.remain_time()}")\n'
_LOOPGUARD_NEW = '            else:\n                logger.info(f"Timer remaining time: {self.timer.remain_time()}")\n                # P49: use an action-aware minimum after direct_exp_gen instead of a\n                # blanket 3600s requirement. Factor loops are materially faster than\n                # model loops in fin_quant, so the old fixed threshold could stop a\n                # perfectly runnable factor loop after its hypothesis had already been\n                # generated (creating a fake-looking loop with no feedback/result).\n                if loop_id is not None and step_id == 0 and loop_id > 0:\n                    _default_min_s = int(os.environ.get("RDAGENT_MIN_LOOP_SECONDS", "3600"))\n                    _factor_min_s = int(os.environ.get("RDAGENT_MIN_FACTOR_LOOP_SECONDS", "1800"))\n                    _model_min_s = int(os.environ.get("RDAGENT_MIN_MODEL_LOOP_SECONDS", "3600"))\n                    _action = None\n                    try:\n                        _direct = self.loop_prev_out[loop_id].get("direct_exp_gen") or {}\n                        _proposal = _direct.get("propose") if isinstance(_direct, dict) else None\n                        _action = getattr(_proposal, "action", None)\n                    except Exception:\n                        _action = None\n                    _min_loop_s = (\n                        _factor_min_s if _action == "factor"\n                        else _model_min_s if _action == "model"\n                        else _default_min_s\n                    )\n                    _remaining_s = self.timer.remain_time().total_seconds()\n                    logger.info(\n                        f"Time-budget guard: action={_action or \'unknown\'}; "\n                        f"remaining={_remaining_s:.0f}s; required={_min_loop_s}s"\n                    )\n                    if _remaining_s < _min_loop_s:\n                        logger.warning(\n                            f"Only {self.timer.remain_time()} left (< {_min_loop_s}s for "\n                            f"{_action or \'this\'} loop); stopping before coding/running."\n                        )\n                        raise self.LoopTerminationError(\n                            f"Insufficient time for {_action or \'next\'} loop"\n                        )\n'
patch(
    "rdagent/utils/workflow/loop.py",
    _LOOPGUARD_OLD,
    _LOOPGUARD_NEW,
    "P27 skip loops that cannot finish in the remaining timer",
)

# ---------------------------------------------------------------- P28
# DashScope rejects embedding batches larger than 10 ("batch size is invalid, it
# should not be larger than 10"). CoSTEER's knowledge-base queries embed whole
# string lists at once, which crashes once the knowledge base grows. Chunk to 10
# and merge in order.
patch(
    "rdagent/oai/backend/litellm.py",
    "        response = embedding(\n"
    "            model=model_name,\n"
    "            input=input_content_list,\n"
    "        )\n"
    '        response_list = [data["embedding"] for data in response.data]\n'
    "        return response_list",
    "        _BATCH = 10\n"
    "        response_list: list[list[float]] = []\n"
    "        for _i in range(0, len(input_content_list), _BATCH):\n"
    "            _chunk = input_content_list[_i : _i + _BATCH]\n"
    "            response = embedding(\n"
    "                model=model_name,\n"
    "                input=_chunk,\n"
    "            )\n"
    '            response_list.extend(data["embedding"] for data in response.data)\n'
    "        return response_list",
    "P28 chunk embedding batches to <=10",
)

# ---------------------------------------------------------------- P29
# A 400 BadRequest (e.g. DashScope embedding batch > 10) can never succeed; retrying
# it 10 times wastes minutes then crashes opaquely. Fail fast with a loud message.
_BADREQ_OLD1 = '                if _is_auth or _is_quota:\n'
_BADREQ_NEW1 = '                _is_badreq = (\n                    "BadRequestError" in _err_text\n                    or "InvalidParameter" in _err_text\n                    or "Error code: 400" in _err_text\n                )\n                if _is_auth or _is_quota or _is_badreq:\n'
patch(
    "rdagent/oai/backend/base.py",
    _BADREQ_OLD1,
    _BADREQ_NEW1,
    "P29 detect bad-request in retry handler",
)
_BADREQ_OLD2 = '                    logger.error("LLM request rejected (auth or quota) - check key/quota in the console.")\n                    raise'
_BADREQ_NEW2 = '                    if _is_badreq and not _is_auth and not _is_quota:\n                        print(\n                            "[rd-agent] LLM BAD REQUEST (400): the provider rejected the "\n                            "request (e.g. embedding batch too large). Not retrying.",\n                            flush=True,\n                        )\n                    logger.error(\n                        "LLM request rejected (auth/quota/bad-request) - see message above."\n                    )\n                    raise'
patch(
    "rdagent/oai/backend/base.py",
    _BADREQ_OLD2,
    _BADREQ_NEW2,
    "P29 loud message for bad-request",
)

# ---------------------------------------------------------------- P30
# Print an explicit completion marker to the run stdout. Previously a successful run
# ended silently in fly logs (END exists only in trace storage), making it impossible
# to tell 'completed but results on another machine' from 'died at teardown'.
_DONE_OLD = '                    else:\n                        raise ValueError(f"Unknown target: {self.target_name}")\n'
_DONE_NEW = '                    else:\n                        raise ValueError(f"Unknown target: {self.target_name}")\n                    print(\n                        f"[rd-agent] scenario {self.target_name} returned successfully; "\n                        "run complete - results are in the trace storage.",\n                        flush=True,\n                    )\n'
patch(
    "rdagent/log/server/app.py",
    _DONE_OLD,
    _DONE_NEW,
    "P30 print run-completion marker to stdout",
)

# ---------------------------------------------------------------- P31
# Force the task child to exit immediately after a successful run (stdio flushed
# first). Without this a teardown hang keeps the child alive, no END is ever
# synthesized, and the dashboard shows the finished run as result-less.
_EXIT_OLD = '                    print(\n                        f"[rd-agent] scenario {self.target_name} returned successfully; "\n                        "run complete - results are in the trace storage.",\n                        flush=True,\n                    )\n'
_EXIT_NEW = '                    print(\n                        f"[rd-agent] scenario {self.target_name} returned successfully; "\n                        "run complete - results are in the trace storage.",\n                        flush=True,\n                    )\n                    # Guarantee prompt exit: a teardown hang (queue-feeder flush,\n                    # mlflow atexit) would otherwise keep the child alive forever,\n                    # so the server never synthesizes END and the dashboard shows\n                    # an in-progress run with no result.\n                    import sys as _sys\n\n                    _sys.stdout.flush()\n                    _sys.stderr.flush()\n                    os._exit(0)\n'
patch(
    "rdagent/log/server/app.py",
    _EXIT_OLD,
    _EXIT_NEW,
    "P31 force child exit after successful run",
)

# ---------------------------------------------------------------- P32
# Server-side auto-skip for ALL user interactions. The frontend 'auto skip'
# switch only auto-submits feedback/hypothesis payloads (init params always show
# a dialog) and only while that browser tab is open, so runs could never be
# unattended. With RDAGENT_AUTO_SKIP_INTERACTION=true the loop answers every
# interaction itself: default instruction, current base features, and the
# unmodified hypothesis/feedback.
patch(
    "rdagent/components/workflow/rd_loop.py",
    '        logger.info("Waiting for user interaction on initial parameters...")\n',
    '        if os.environ.get("RDAGENT_AUTO_SKIP_INTERACTION", "").strip().lower() in {\n            "1",\n            "true",\n            "yes",\n            "on",\n        }:\n            logger.info(\n                "Auto-skip interaction: using default initial parameters without asking."\n            )\n            if not self.plan.get("user_instruction"):\n                self.plan["user_instruction"] = (\n                    "Reproduce RD-Agent(Q) (arXiv:2505.15155): jointly optimize alpha "\n                    "factors and the return-forecasting model on the CSI300 universe; use "\n                    "qlib backtest feedback (IC/RankIC, annualized excess return, "\n                    "information ratio, max drawdown) to pick the next direction."\n                )\n            return\n        logger.info("Waiting for user interaction on initial parameters...")\n',
    "P32 auto-skip initial parameters",
)
patch(
    "rdagent/components/workflow/rd_loop.py",
    '        logger.info("Waiting for user interaction on hypothesis...")\n',
    '        if os.environ.get("RDAGENT_AUTO_SKIP_INTERACTION", "").strip().lower() in {\n            "1",\n            "true",\n            "yes",\n            "on",\n        }:\n            logger.info("Auto-skip interaction: keeping the generated hypothesis unchanged.")\n            return hypo\n        logger.info("Waiting for user interaction on hypothesis...")\n',
    "P32 auto-skip hypothesis confirmation",
)
patch(
    "rdagent/components/workflow/rd_loop.py",
    '        logger.info("Waiting for user interaction on feedback...")\n',
    '        if os.environ.get("RDAGENT_AUTO_SKIP_INTERACTION", "").strip().lower() in {\n            "1",\n            "true",\n            "yes",\n            "on",\n        }:\n            logger.info("Auto-skip interaction: keeping the generated feedback unchanged.")\n            return feedback\n        logger.info("Waiting for user interaction on feedback...")\n',
    "P32 auto-skip feedback confirmation",
)

# ---------------------------------------------------------------- P33
# Allow chat and embedding calls to use different endpoints/keys WITHOUT breaking
# provider-native routing: the override kwargs are added ONLY when the
# CHAT_OPENAI_*/EMBEDDING_OPENAI_* settings are non-empty (passing an explicit None
# would make litellm skip its env resolution, e.g. LITELLM_PROXY_API_BASE for
# litellm_proxy/* models or OPENAI_API_BASE for openai/* models).
_CHATROUTE_OLD = '        response = completion(\n            messages=messages,\n            stream=LITELLM_SETTINGS.chat_stream,\n            max_retries=0,\n            **complete_kwargs,\n            **kwargs,\n        )\n'
_CHATROUTE_NEW = '        # Only pass api_base/api_key when explicitly configured; an explicit\n        # None makes litellm skip its per-provider env resolution.\n        _route_kwargs = {}\n        if LITELLM_SETTINGS.chat_openai_base_url:\n            _route_kwargs["api_base"] = LITELLM_SETTINGS.chat_openai_base_url\n        if LITELLM_SETTINGS.chat_openai_api_key:\n            _route_kwargs["api_key"] = LITELLM_SETTINGS.chat_openai_api_key\n        response = completion(\n            messages=messages,\n            stream=LITELLM_SETTINGS.chat_stream,\n            max_retries=0,\n            **_route_kwargs,\n            **complete_kwargs,\n            **kwargs,\n        )\n'
patch(
    "rdagent/oai/backend/litellm.py",
    _CHATROUTE_OLD,
    _CHATROUTE_NEW,
    "P33 optional chat endpoint override",
)
_EMBROUTE_OLD = '            response = embedding(\n                model=model_name,\n                input=_chunk,\n            )\n'
_EMBROUTE_NEW = '            _emb_route_kwargs = {}\n            if LITELLM_SETTINGS.embedding_openai_base_url:\n                _emb_route_kwargs["api_base"] = LITELLM_SETTINGS.embedding_openai_base_url\n            if LITELLM_SETTINGS.embedding_openai_api_key:\n                _emb_route_kwargs["api_key"] = LITELLM_SETTINGS.embedding_openai_api_key\n            response = embedding(\n                model=model_name,\n                input=_chunk,\n                **_emb_route_kwargs,\n            )\n'
patch(
    "rdagent/oai/backend/litellm.py",
    _EMBROUTE_OLD,
    _EMBROUTE_NEW,
    "P33 optional embedding endpoint override",
)

# ---------------------------------------------------------------- P34
# Log the effective endpoint + masked key ONCE per process tree (env-flag dedupe,
# so subprocesses don't repeat it) for chat and embeddings. A misrouted config
# (e.g. chat still on the general DashScope endpoint instead of the Token Plan
# URL) then shows up as one obvious line instead of a confusing 403 mid-run.
_ROUTE_IMP_OLD = 'from litellm import (\n'
_ROUTE_IMP_NEW = 'from os import environ as _os_environ\n\nfrom litellm import (\n'
patch(
    "rdagent/oai/backend/litellm.py",
    _ROUTE_IMP_OLD,
    _ROUTE_IMP_NEW,
    "P34 import os in litellm backend",
)
_ROUTE_CHAT_OLD = '        model = LITELLM_SETTINGS.chat_model\n'
_ROUTE_CHAT_NEW = '        model = LITELLM_SETTINGS.chat_model\n        if not _os_environ.get("_RD_ROUTE_LOG_CHAT"):\n            _os_environ["_RD_ROUTE_LOG_CHAT"] = "1"\n            _base = LITELLM_SETTINGS.chat_openai_base_url or _os_environ.get("OPENAI_API_BASE", "")\n            _key = LITELLM_SETTINGS.chat_openai_api_key or _os_environ.get("OPENAI_API_KEY", "")\n            print(\n                f"[rd-agent] LLM route: chat model={model} base={_base} "\n                f"key={(_key[:6] + \'…\' + _key[-4:]) if _key else \'<unset>\'}",\n                flush=True,\n            )\n'
patch(
    "rdagent/oai/backend/litellm.py",
    _ROUTE_CHAT_OLD,
    _ROUTE_CHAT_NEW,
    "P34 log effective chat route (once)",
)
_ROUTE_EMB_OLD = '        model_name = LITELLM_SETTINGS.embedding_model\n'
_ROUTE_EMB_NEW = '        model_name = LITELLM_SETTINGS.embedding_model\n        if not _os_environ.get("_RD_ROUTE_LOG_EMB"):\n            _os_environ["_RD_ROUTE_LOG_EMB"] = "1"\n            if LITELLM_SETTINGS.embedding_openai_base_url:\n                _base = LITELLM_SETTINGS.embedding_openai_base_url\n            elif model_name.startswith("litellm_proxy/"):\n                _base = _os_environ.get("LITELLM_PROXY_API_BASE", "")\n            else:\n                _base = _os_environ.get("OPENAI_API_BASE", "")\n            _key = LITELLM_SETTINGS.embedding_openai_api_key or (\n                _os_environ.get("LITELLM_PROXY_API_KEY", "")\n                if model_name.startswith("litellm_proxy/")\n                else _os_environ.get("OPENAI_API_KEY", "")\n            )\n            print(\n                f"[rd-agent] LLM route: embedding model={model_name} base={_base} "\n                f"key={(_key[:6] + \'…\' + _key[-4:]) if _key else \'<unset>\'}",\n                flush=True,\n            )\n'
patch(
    "rdagent/oai/backend/litellm.py",
    _ROUTE_EMB_OLD,
    _ROUTE_EMB_NEW,
    "P34 log effective embedding route (once)",
)


# ---------------------------------------------------------------- P37 robust historical trace reload
# A historical RESULT page can be empty even when the run succeeded if one persisted
# trace object cannot be converted for the web UI: read_trace() previously aborted the
# entire replay on that single conversion error. Skip only the malformed event. Also,
# if a history trace exists on disk but has no in-memory messages (e.g. startup load
# raced/failed), /trace reloads it on demand instead of returning an empty array.
_READ_TRACE_OLD = '''    for msg in fs.iter_msg():
        data = ws._obj_to_json(obj=msg.content, tag=msg.tag, id=id, timestamp=msg.timestamp.isoformat())
        if data:
'''
_READ_TRACE_NEW = '''    for msg in fs.iter_msg():
        try:
            data = ws._obj_to_json(obj=msg.content, tag=msg.tag, id=id, timestamp=msg.timestamp.isoformat())
        except Exception:
            app.logger.exception(
                "Skipping malformed trace event while replaying %s (tag=%s)",
                log_path,
                getattr(msg, "tag", "<unknown>"),
            )
            continue
        if data:
'''
patch(
    "rdagent/log/server/app.py",
    _READ_TRACE_OLD,
    _READ_TRACE_NEW,
    "P37 skip malformed persisted trace events",
)

_TRACE_RELOAD_OLD = '''    task = _get_or_create_task(trace_id)

    # Make sure any pending user-interaction requests are visible to the frontend.
'''
_TRACE_RELOAD_NEW = '''    task = _get_or_create_task(trace_id)

    # History traces normally load at server startup. If that replay failed or the
    # task was created lazily, recover directly from the persisted trace directory.
    if task.process is None and not task.messages:
        _trace_dir = Path(trace_id)
        if _trace_dir.exists() and _trace_dir.is_dir():
            try:
                read_trace(_trace_dir, id=trace_id)
                task = _get_or_create_task(trace_id)
                app.logger.info(
                    "Reloaded historical trace on demand: %s (%d UI messages)",
                    trace_id,
                    len(task.messages),
                )
            except Exception:
                app.logger.exception("Failed to reload historical trace on demand: %s", trace_id)

    # Make sure any pending user-interaction requests are visible to the frontend.
'''
patch(
    "rdagent/log/server/app.py",
    _TRACE_RELOAD_OLD,
    _TRACE_RELOAD_NEW,
    "P37 on-demand persisted trace reload",
)


# ---------------------------------------------------------------- P38 resilient FileStorage replay
# FileStorage.iter_msg() used to pickle.load EVERY .pkl into an in-memory list before
# yielding the first message. One historical pickle that references a generated/
# unavailable class therefore aborted the entire trace replay and left the UI with
# zero structured events even though later hypothesis/metric/feedback pickles were
# perfectly valid. Skip only the unreadable pickle and continue replaying the rest.
_FILE_REPLAY_OLD = '''        for file in self.path.glob(pkl_files):
            if file.name == "debug_llm.pkl":
                continue
            pkl_log_tag = ".".join(file.relative_to(self.path).as_posix().replace("/", ".").split(".")[:-3])
            pid = file.parent.name

            with file.open("rb") as f:
                content = pickle.load(f)

            timestamp = datetime.strptime(file.stem, "%Y-%m-%d_%H-%M-%S-%f").replace(tzinfo=timezone.utc)

            m = Message(tag=pkl_log_tag, level="INFO", timestamp=timestamp, caller="", pid_trace=pid, content=content)

            msg_l.append(m)
'''
_FILE_REPLAY_NEW = '''        for file in self.path.glob(pkl_files):
            if file.name == "debug_llm.pkl":
                continue
            pkl_log_tag = ".".join(file.relative_to(self.path).as_posix().replace("/", ".").split(".")[:-3])
            pid = file.parent.name

            try:
                with file.open("rb") as f:
                    content = pickle.load(f)

                timestamp = datetime.strptime(file.stem, "%Y-%m-%d_%H-%M-%S-%f").replace(tzinfo=timezone.utc)
            except Exception as e:
                print(
                    f"[rd-agent] WARNING: skipping unreadable trace pickle {file}: "
                    f"{type(e).__name__}: {e}",
                    flush=True,
                )
                continue

            m = Message(tag=pkl_log_tag, level="INFO", timestamp=timestamp, caller="", pid_trace=pid, content=content)

            msg_l.append(m)
'''
patch(
    "rdagent/log/storage.py",
    _FILE_REPLAY_OLD,
    _FILE_REPLAY_NEW,
    "P38 skip unreadable historical trace pickles",
)


# ---------------------------------------------------------------- P40 robust structured RESULT replay
# Historical traces may have been written by an earlier image whose concrete Python
# classes no longer compare equal to the classes imported by the current image.
# The pickle still contains the result data, but WebStorage._obj_to_json() can return
# {} because of isinstance(...) gates. Recover the three core RESULT events by tag
# and attributes instead: hypothesis generation, runner result, and feedback.
_TRACE_FALLBACK_HELPER_ANCHOR = '''def read_trace(log_path: Path, id: str = "") -> None:
'''
_TRACE_FALLBACK_HELPER = '''def _recover_result_event_from_trace_obj(msg, id: str):
    """Best-effort compatibility replay for persisted finance RESULT objects.

    This intentionally uses tag + attributes instead of concrete class identity so
    traces created by older deployments remain viewable after redeploys.
    """
    import json as _json

    tag = str(getattr(msg, "tag", "") or "")
    obj = getattr(msg, "content", None)
    timestamp = msg.timestamp.isoformat()
    try:
        from rdagent.log.utils import extract_loopid_func_name
        loop_id, _ = extract_loopid_func_name(tag)
    except Exception:
        loop_id = None

    if "hypothesis generation" in tag:
        hypothesis = getattr(obj, "hypothesis", None)
        if hypothesis is None and isinstance(obj, dict):
            hypothesis = obj.get("hypothesis")
        if hypothesis is not None:
            def _ga(name, default=""):
                if isinstance(obj, dict):
                    return obj.get(name, default)
                return getattr(obj, name, default)
            return {
                "id": id,
                "msg": {
                    "tag": "research.hypothesis",
                    "old_tag": tag,
                    "timestamp": timestamp,
                    "loop_id": loop_id,
                    "content": {
                        "hypothesis": str(hypothesis),
                        "reason": str(_ga("reason", "") or ""),
                        "component": str(_ga("component", "") or ""),
                        "concise_reason": str(_ga("concise_reason", "") or ""),
                        "concise_justification": str(_ga("concise_justification", "") or ""),
                        "concise_observation": str(_ga("concise_observation", "") or ""),
                        "concise_knowledge": str(_ga("concise_knowledge", "") or ""),
                    },
                },
            }

    # Restrict metric recovery to the actual runner-result object; do not treat
    # arbitrary debug/template objects below Loop_*/running as metrics.
    if tag.endswith(".running.runner result") or "running.runner result" in tag:
        result = getattr(obj, "result", None)
        if result is None and isinstance(obj, dict):
            result = obj.get("result")
        if result is not None:
            try:
                if hasattr(result, "to_json"):
                    result_json = result.to_json()
                elif isinstance(result, str):
                    # Preserve already-serialized JSON when valid.
                    _json.loads(result)
                    result_json = result
                else:
                    result_json = _json.dumps(result, default=str)
                return {
                    "id": id,
                    "msg": {
                        "tag": "feedback.metric",
                        "old_tag": tag,
                        "timestamp": timestamp,
                        "loop_id": loop_id,
                        "content": {"result": result_json},
                    },
                }
            except Exception:
                pass

    # Exact persisted tag is Loop_N.feedback.feedback. Avoid debug_llm/token_cost/etc.
    if tag.endswith(".feedback.feedback") or tag == "feedback":
        def _gf(name, default=None):
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)

        decision = _gf("decision", None)
        observations = _gf("observations", None)
        reason = _gf("reason", None)
        hypothesis_evaluation = _gf("hypothesis_evaluation", None)
        new_hypothesis = _gf("new_hypothesis", None)
        exception = _gf("exception", None)

        # Require at least one feedback-shaped field so unrelated objects aren't
        # synthesized into fake RESULT rows.
        if any(
            value is not None
            for value in (
                decision,
                observations,
                reason,
                hypothesis_evaluation,
                new_hypothesis,
                exception,
            )
        ):
            return {
                "id": id,
                "msg": {
                    "tag": "feedback.hypothesis_feedback",
                    "old_tag": tag,
                    "timestamp": timestamp,
                    "loop_id": loop_id,
                    "content": {
                        "observations": "" if observations is None else str(observations),
                        "hypothesis_evaluation": (
                            "" if hypothesis_evaluation is None else str(hypothesis_evaluation)
                        ),
                        "new_hypothesis": "" if new_hypothesis is None else str(new_hypothesis),
                        "decision": bool(decision) if decision is not None else False,
                        "reason": "" if reason is None else str(reason),
                        "exception": "" if exception is None else str(exception),
                    },
                },
            }

    return {}


def read_trace(log_path: Path, id: str = "") -> None:
'''
patch(
    "rdagent/log/server/app.py",
    _TRACE_FALLBACK_HELPER_ANCHOR,
    _TRACE_FALLBACK_HELPER,
    "P40 add backward-compatible RESULT event recovery",
)

# P37 already guards converter failures. Extend it so an empty/unsupported converter
# result falls back to the compatibility decoder above, and log a replay summary.
_P40_READ_OLD = '''    task.messages = []
    last_timestamp = None
    for msg in fs.iter_msg():
        try:
            data = ws._obj_to_json(obj=msg.content, tag=msg.tag, id=id, timestamp=msg.timestamp.isoformat())
        except Exception:
            app.logger.exception(
                "Skipping malformed trace event while replaying %s (tag=%s)",
                log_path,
                getattr(msg, "tag", "<unknown>"),
            )
            continue
        if data:
'''
_P40_READ_NEW = '''    task.messages = []
    last_timestamp = None
    _replay_counts = {
        "research.hypothesis": 0,
        "feedback.metric": 0,
        "feedback.hypothesis_feedback": 0,
        "feedback.return_chart": 0,
    }
    for msg in fs.iter_msg():
        try:
            data = ws._obj_to_json(obj=msg.content, tag=msg.tag, id=id, timestamp=msg.timestamp.isoformat())
        except Exception:
            app.logger.exception(
                "Standard trace conversion failed for %s (tag=%s); trying compatibility replay",
                log_path,
                getattr(msg, "tag", "<unknown>"),
            )
            data = {}
        if not data:
            data = _recover_result_event_from_trace_obj(msg, id)
        if data:
'''
patch(
    "rdagent/log/server/app.py",
    _P40_READ_OLD,
    _P40_READ_NEW,
    "P40 fallback to duck-typed RESULT conversion",
)

_P40_APPEND_OLD = '''            if isinstance(data, list):
                for d in data:
                    task.messages.append(d["msg"])
                    last_timestamp = msg.timestamp
            else:
                task.messages.append(data["msg"])
                last_timestamp = msg.timestamp

    now = datetime.now(timezone.utc)
'''
_P40_APPEND_NEW = '''            if isinstance(data, list):
                for d in data:
                    _ui_msg = d["msg"]
                    task.messages.append(_ui_msg)
                    if _ui_msg.get("tag") in _replay_counts:
                        _replay_counts[_ui_msg["tag"]] += 1
                    last_timestamp = msg.timestamp
            else:
                _ui_msg = data["msg"]
                task.messages.append(_ui_msg)
                if _ui_msg.get("tag") in _replay_counts:
                    _replay_counts[_ui_msg["tag"]] += 1
                last_timestamp = msg.timestamp

    app.logger.info(
        "Trace replay summary for %s: total_ui=%d hypothesis=%d metric=%d feedback=%d chart=%d",
        log_path,
        len(task.messages),
        _replay_counts["research.hypothesis"],
        _replay_counts["feedback.metric"],
        _replay_counts["feedback.hypothesis_feedback"],
        _replay_counts["feedback.return_chart"],
    )

    now = datetime.now(timezone.utc)
'''
patch(
    "rdagent/log/server/app.py",
    _P40_APPEND_OLD,
    _P40_APPEND_NEW,
    "P40 log historical RESULT replay counts",
)


# ---------------------------------------------------------------- P41 reconcile completed live runs from persisted trace
# RESULT must not depend on best-effort live /receive delivery. Once a child process
# has exited, rebuild its UI messages from the durable .pkl trace before returning
# END. This makes a freshly completed run converge to the same state as history
# replay and lets P40 recover hypothesis/metric/feedback deterministically.
_P41_RECONCILE_OLD = '''    # Make sure any pending user-interaction requests are visible to the frontend.
    _drain_user_requests_into_messages(task)

    if task.process is not None and not task.is_alive():
'''
_P41_RECONCILE_NEW = '''    # A live run may have missed one or more best-effort WebStorage /receive
    # messages even though FileStorage persisted the corresponding .pkl objects.
    # Once the process is complete, make persisted storage authoritative and rebuild
    # the UI message stream exactly once before synthesizing END.
    if (
        task.process is not None
        and not task.is_alive()
        and not getattr(task, "_result_reconciled_from_disk", False)
    ):
        _completed_trace_dir = Path(trace_id)
        if _completed_trace_dir.exists() and _completed_trace_dir.is_dir():
            try:
                read_trace(_completed_trace_dir, id=trace_id)
                task = _get_or_create_task(trace_id)
                # The client may already have advanced a pointer through an incomplete
                # live message stream. Replay the authoritative rebuilt stream from 0.
                task.pointers.clear()
                task._result_reconciled_from_disk = True
                app.logger.info(
                    "Reconciled completed trace from disk: %s (%d UI messages)",
                    trace_id,
                    len(task.messages),
                )
            except Exception:
                app.logger.exception(
                    "Failed to reconcile completed trace from disk: %s",
                    trace_id,
                )

    # Make sure any pending user-interaction requests are visible to the frontend.
    _drain_user_requests_into_messages(task)

    if task.process is not None and not task.is_alive():
'''
patch(
    "rdagent/log/server/app.py",
    _P41_RECONCILE_OLD,
    _P41_RECONCILE_NEW,
    "P41 rebuild completed live RESULT from persisted trace",
)


# ---------------------------------------------------------------- P42 durable continuation / branching
# 1) Put LoopBase.__session__ under each trace on /data so checkpoints survive deploys.
# 2) Extend fin_quant main with "additional loops", instruction override, and a fresh
#    timer when resuming.
# 3) Add /resume/options and /resume routes. Resume is non-destructive: the source
#    trace is copied, then the copy is checked out/truncated to the chosen checkpoint.
_DURABLE_SESSION_OLD = '''        from rdagent.log.conf import LOG_SETTINGS

        LOG_SETTINGS.set_ui_server_port(self.ui_server_port)
'''
_DURABLE_SESSION_NEW = '''        from rdagent.log.conf import LOG_SETTINGS

        # Keep workflow session snapshots beside this trace's durable FileStorage.
        # Without this, LoopBase.__session__ uses the process-start log directory
        # under /app and disappears on redeploy.
        LOG_SETTINGS.trace_path = self.log_trace_path
        LOG_SETTINGS.set_ui_server_port(self.ui_server_port)
'''
patch(
    "rdagent/log/server/app.py",
    _DURABLE_SESSION_OLD,
    _DURABLE_SESSION_NEW,
    "P42 persist __session__ under each trace",
)

_QUANT_SIG_OLD = '''    checkout: bool = True,
    base_features_path: str | None = None,
    **kwargs,
):
'''
_QUANT_SIG_NEW = '''    checkout: bool | str = True,
    base_features_path: str | None = None,
    additional_loops: int | None = None,
    resume_instruction: str | None = None,
    resume_loop_index: int | None = None,
    reset_timer_on_resume: bool = True,
    **kwargs,
):
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _QUANT_SIG_OLD,
    _QUANT_SIG_NEW,
    "P42 fin_quant resume arguments",
)

_QUANT_LOAD_OLD = '''    if path is None:
        quant_loop = QuantRDLoop(QUANT_PROP_SETTING)
    else:
        quant_loop = QuantRDLoop.load(path, checkout=checkout)
    quant_loop._init_base_features(base_features_path)
'''
_QUANT_LOAD_NEW = '''    if path is None:
        quant_loop = QuantRDLoop(QUANT_PROP_SETTING)
        _resume_incomplete_loop = False
    else:
        # A continuation gets a new budget rather than inheriting an expired timer.
        quant_loop = QuantRDLoop.load(
            path,
            checkout=checkout,
            replace_timer=not reset_timer_on_resume,
        )

        # P50: start the workflow at the selected checkpoint's loop instead of
        # rescanning internal loop 0,1,... on every resume. If the selected loop is
        # already complete (record checkpoint), start at the next loop. If it is
        # partial (e.g. after direct_exp_gen/coding), resume that exact loop.
        if resume_loop_index is None:
            _selected_loop_idx = max(quant_loop.step_idx.keys(), default=-1)
        else:
            _selected_loop_idx = int(resume_loop_index)

        _selected_step_idx = int(quant_loop.step_idx.get(_selected_loop_idx, 0))
        _resume_incomplete_loop = _selected_step_idx < len(quant_loop.steps)
        _resume_start_loop_idx = (
            _selected_loop_idx if _resume_incomplete_loop else _selected_loop_idx + 1
        )
        quant_loop._resume_start_loop_idx = _resume_start_loop_idx
        logger.info(
            f"Resume checkpoint resolved: selected_loop={_selected_loop_idx + 1}, "
            f"selected_step_idx={_selected_step_idx}, "
            f"resume_start_loop={_resume_start_loop_idx + 1}, "
            f"incomplete_selected_loop={_resume_incomplete_loop}"
        )

    if resume_instruction:
        quant_loop.plan["user_instruction"] = str(resume_instruction)

    if additional_loops is not None:
        # "Additional loops" means loops after the selected checkpoint. If the
        # selected checkpoint is partial, first finish that selected loop and then
        # run N genuinely new loops. If it is complete, run N new loops directly.
        loop_n = int(additional_loops) + (
            1 if path is not None and _resume_incomplete_loop else 0
        )
        logger.info(
            f"Resume requested: start_loop="
            f"{getattr(quant_loop, '_resume_start_loop_idx', 0) + 1}, "
            f"finish_selected_partial={bool(path is not None and _resume_incomplete_loop)}, "
            f"additional_loops={additional_loops}, effective loop_n={loop_n}"
        )

    quant_loop._init_base_features(base_features_path)

    if path is not None:
        _active_loop_idx = int(getattr(quant_loop, "_resume_start_loop_idx", 0) or 0)
        _active_step_idx = int(quant_loop.step_idx.get(_active_loop_idx, 0))
        _active_step_name = (
            quant_loop.steps[_active_step_idx]
            if 0 <= _active_step_idx < len(quant_loop.steps)
            else "complete"
        )
        print(
            f"[rd-agent] RESUME_ACTIVE ui_loop={_active_loop_idx + 1} "
            f"internal_loop={_active_loop_idx} next_step={_active_step_name} "
            f"step_index={_active_step_idx}",
            flush=True,
        )
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _QUANT_LOAD_OLD,
    _QUANT_LOAD_NEW,
    "P42 fresh timer + additional-loop semantics + instruction override",
)

patch(
    "rdagent/log/server/app.py",
    '@app.route("/upload", methods=["POST"])',
    snippet("resume_routes.py") + '\n\n\n@app.route("/upload", methods=["POST"])',
    "P42 resume/branch API routes",
)


# ---------------------------------------------------------------- P46
# Treat qlib/runtime failures as execution failures rather than failed research.
# The previous behavior converted a killed qrun into FactorEmptyError/ModelEmptyError,
# recorded decision=False with an empty reason, then immediately generated another
# hypothesis. That caused every later loop to inherit the same broken execution state.
#
# P46 does four things:
#   1) preserve qrun exit code (including SIGKILL/OOM-style 137) in the error text;
#   2) populate a useful feedback reason instead of leaving reason="";
#   3) stop BEFORE the next hypothesis after an execution failure, while keeping the
#      failed loop's feedback/record checkpoint durable;
#   4) make bandit metric extraction null-safe for older failed traces.

_WORKSPACE_QRUN_OLD = '''        execute_qlib_log = qtde.check_output(
            local_path=str(self.workspace_path),
            entry=f"qrun {qlib_config_name}",
            env=run_env,
        )
        logger.log_object(execute_qlib_log, tag="Qlib_execute_log")

        execute_log = qtde.check_output(
'''
_WORKSPACE_QRUN_NEW = '''        _qlib_run = qtde.run(
            local_path=str(self.workspace_path),
            entry=f"qrun {qlib_config_name}",
            env=run_env,
        )
        execute_qlib_log = _qlib_run.stdout
        if _qlib_run.exit_code != 0:
            _status = (
                f"[RD-Agent execution status] qrun_exit_code={_qlib_run.exit_code} "
                f"running_time={_qlib_run.running_time:.1f}s"
            )
            if _qlib_run.exit_code in (137, -9):
                _status += (
                    " | process was killed (SIGKILL/137); on Fly this commonly "
                    "indicates memory pressure/OOM"
                )
            elif _qlib_run.exit_code == 124:
                _status += " | qrun timed out"
            execute_qlib_log = f"{execute_qlib_log}\\n{_status}"
            logger.error(_status)
            logger.log_object(execute_qlib_log, tag="Qlib_execute_log")
            return None, execute_qlib_log

        logger.log_object(execute_qlib_log, tag="Qlib_execute_log")

        execute_log = qtde.check_output(
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _WORKSPACE_QRUN_OLD,
    _WORKSPACE_QRUN_NEW,
    "P46 preserve qrun exit status and fail before result parsing",
)

_QUANT_CLASS_OLD = '''class QuantRDLoop(RDLoop):
'''
_QUANT_CLASS_NEW = '''def _is_execution_failure(exc: Exception | str | None) -> bool:
    """Return True for runtime/infrastructure failures, not research rejection."""
    text = str(exc or "")
    lower = text.lower()
    return (
        "failed to run this experiment" in lower
        or ("failed to run " in lower and " model, because " in lower)
        or "qrun_exit_code=" in lower
        or "no result file found" in lower
        or "\\nkilled" in lower
        or "process was killed" in lower
        or "running time exceeds" in lower
        or "qrun timed out" in lower
    )


def _execution_failure_reason(exc: Exception | str | None) -> str:
    text = str(exc or "")
    lower = text.lower()
    if "qrun_exit_code=137" in lower or "qrun_exit_code=-9" in lower or "\\nkilled" in lower:
        return (
            "Execution failed: the Qlib process was killed before producing a complete "
            "backtest result. This is an infrastructure/resource failure (commonly "
            "memory pressure/OOM), not evidence that the research hypothesis is bad."
        )
    if "qrun_exit_code=124" in lower or "timed out" in lower or "running time exceeds" in lower:
        return (
            "Execution failed: the Qlib run timed out before producing a complete "
            "backtest result. Retry/repair the execution before evaluating the hypothesis."
        )
    return (
        "Execution failed: Qlib did not produce a valid backtest result. "
        "Retry/repair the execution before generating a new research hypothesis."
    )


class QuantRDLoop(RDLoop):
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _QUANT_CLASS_OLD,
    _QUANT_CLASS_NEW,
    "P46 classify quant execution failures",
)

_QUANT_DIRECT_OLD = '''    async def direct_exp_gen(self, prev_out: dict[str, Any]):
'''
_QUANT_DIRECT_NEW = '''    def _check_exit_conditions_on_step(
        self,
        loop_id: int | None = None,
        step_id: int | None = None,
    ) -> None:
        # Stop only AFTER the failed loop's record step has completed and its durable
        # checkpoint has been written. LoopBase calls this hook *after* each step.
        #
        # P46 incorrectly checked step_id == 0, which meant the next loop's
        # direct_exp_gen was allowed to run first and was then terminated immediately.
        # That produced an empty-looking red Loop 01 in the UI. The record-step guard
        # below prevents the next hypothesis from being started at all.
        _record_step_id = self.steps.index("record") if "record" in self.steps else len(self.steps) - 1
        if (
            step_id == _record_step_id
            and getattr(self, "_execution_failure_pending", None)
        ):
            logger.error(
                "Execution failure recorded; stopping after the failed loop record "
                "checkpoint and before any next hypothesis. Retry this experiment "
                "from its coding checkpoint after fixing the runtime/resource issue."
            )
            raise self.LoopTerminationError("Execution failure requires retry/repair")
        return super()._check_exit_conditions_on_step(loop_id=loop_id, step_id=step_id)

    async def direct_exp_gen(self, prev_out: dict[str, Any]):
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _QUANT_DIRECT_OLD,
    _QUANT_DIRECT_NEW,
    "P46 stop hypothesis cascade after execution failure",
)

_QUANT_FEEDBACK_OLD = '''        if e is not None:
            feedback = HypothesisFeedback(
                observations=str(e),
                hypothesis_evaluation="",
                new_hypothesis="",
                reason="",
                decision=False,
            )
        else:
'''
_QUANT_FEEDBACK_NEW = '''        if e is not None:
            if _is_execution_failure(e):
                _reason = _execution_failure_reason(e)
                self._execution_failure_pending = _reason
                feedback = HypothesisFeedback(
                    observations=str(e),
                    hypothesis_evaluation=(
                        "The experiment was not scientifically evaluated because the "
                        "execution/backtest did not complete."
                    ),
                    new_hypothesis="",
                    reason=_reason,
                    decision=False,
                    exception=e,
                )
            else:
                # A normal implementation/research failure should still explain why it
                # failed instead of leaving ResultPage with an empty reason.
                feedback = HypothesisFeedback(
                    observations=str(e),
                    hypothesis_evaluation="",
                    new_hypothesis="",
                    reason=str(e),
                    decision=False,
                    exception=e,
                )
        else:
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _QUANT_FEEDBACK_OLD,
    _QUANT_FEEDBACK_NEW,
    "P46 keep actual exception reason in quant feedback",
)

_BANDIT_NULL_OLD = '''    try:
        result = experiment.result
        ic = result.get("IC", 0.0)
'''
_BANDIT_NULL_NEW = '''    try:
        result = getattr(experiment, "result", None)
        if result is None:
            # Failed/incomplete experiments have no scientific metric. Returning a
            # neutral vector is intentional; P46 stops new-hypothesis generation
            # after a fresh execution failure, while this also keeps old traces safe.
            return Metrics()
        ic = result.get("IC", 0.0)
'''
patch(
    "rdagent/scenarios/qlib/proposal/bandit.py",
    _BANDIT_NULL_OLD,
    _BANDIT_NULL_NEW,
    "P46 null-safe bandit metric extraction",
)

patch(
    "rdagent/scenarios/qlib/proposal/bandit.py",
    '        arr = result.get("1day.excess_return_with_cost.annualized_return ", 0.0)',
    '        arr = result.get(\n'
    '            "1day.excess_return_with_cost.annualized_return",\n'
    '            result.get("1day.excess_return_with_cost.annualized_return ", 0.0),\n'
    '        )',
    "P46 accept canonical with-cost annualized-return key",
)



# ---------------------------------------------------------------- P48 live RESULT snapshot
# RESULT should be inspectable while a multi-loop run is still active. Build a
# pointer-independent snapshot from both in-memory UI messages and durable FileStorage
# so completed loop metrics/feedback show up immediately without waiting for END.
_LIVE_RESULT_ROUTE_OLD = '''@app.route("/stdout", methods=["GET"])
def download_stdout_file():
'''
_LIVE_RESULT_ROUTE_NEW = '''def _live_result_snapshot_from_messages(messages):
    import json as _json

    loops = {}
    latest_timestamp = None

    for ui_msg in messages or []:
        if not isinstance(ui_msg, dict):
            continue
        tag = str(ui_msg.get("tag") or "")
        if tag not in {
            "research.hypothesis",
            "feedback.metric",
            "feedback.hypothesis_feedback",
        }:
            continue

        loop_id = ui_msg.get("loop_id")
        try:
            loop_id = int(loop_id)
        except (TypeError, ValueError):
            continue
        if loop_id < 0:
            continue

        row = loops.setdefault(
            loop_id,
            {
                "loop_id": loop_id,
                "researchHypothesis": None,
                "feedbackMetric": None,
                "feedbackHypothesis": None,
                "updated_at": None,
            },
        )

        timestamp = ui_msg.get("timestamp")
        if timestamp:
            row["updated_at"] = timestamp
            latest_timestamp = timestamp

        content = ui_msg.get("content")
        if tag == "research.hypothesis":
            if isinstance(content, dict):
                row["researchHypothesis"] = content
        elif tag == "feedback.metric":
            metric_payload = content.get("result") if isinstance(content, dict) else None
            if isinstance(metric_payload, str):
                try:
                    metric_payload = _json.loads(metric_payload)
                except Exception:
                    metric_payload = None
            if isinstance(metric_payload, dict):
                row["feedbackMetric"] = metric_payload
        elif tag == "feedback.hypothesis_feedback":
            if isinstance(content, dict):
                row["feedbackHypothesis"] = content

    ordered = [loops[key] for key in sorted(loops)]
    for row in ordered:
        row["complete"] = bool(row.get("feedbackHypothesis"))
        row["has_metrics"] = bool(row.get("feedbackMetric"))
    return ordered, latest_timestamp


def _collect_live_result_messages(trace_dir: Path, trace_id: str):
    """Read only RESULT-relevant events without mutating /trace pointers/messages."""
    fs = FileStorage(trace_dir)
    ws = WebStorage(port=1, path=trace_dir)
    recovered = []

    for msg in fs.iter_msg():
        try:
            data = ws._obj_to_json(
                obj=msg.content,
                tag=msg.tag,
                id=trace_id,
                timestamp=msg.timestamp.isoformat(),
            )
        except Exception:
            data = {}

        if not data:
            data = _recover_result_event_from_trace_obj(msg, trace_id)
        if not data:
            continue

        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ui_msg = entry.get("msg")
            if not isinstance(ui_msg, dict):
                continue
            if ui_msg.get("tag") in {
                "research.hypothesis",
                "feedback.metric",
                "feedback.hypothesis_feedback",
            }:
                recovered.append(ui_msg)
    return recovered


@app.route("/result/live", methods=["GET"])
def live_result_snapshot():
    import time as _time

    trace_id = str(request.args.get("id") or "").strip().strip("/")
    if not trace_id:
        return jsonify({"error": "Trace ID is required"}), 400

    trace_dir = (log_folder_path / trace_id).resolve()
    root = log_folder_path.resolve()
    try:
        if os.path.commonpath([str(trace_dir), str(root)]) != str(root):
            return jsonify({"error": "Invalid trace ID"}), 400
    except ValueError:
        return jsonify({"error": "Invalid trace ID"}), 400

    if not trace_dir.exists() or not trace_dir.is_dir():
        return jsonify({"error": "Trace not found"}), 404

    task = rdagent_processes.get(str(trace_dir))
    alive = bool(task is not None and task.is_alive())

    # Primary source: durable trace. Cache briefly to avoid repeatedly unpickling a
    # large trace when the frontend polls every few seconds.
    disk_messages = []
    now = _time.monotonic()
    cache = getattr(task, "_live_result_cache", None) if task is not None else None
    if (
        isinstance(cache, dict)
        and now - float(cache.get("time", 0.0)) < 2.5
        and isinstance(cache.get("messages"), list)
    ):
        disk_messages = cache["messages"]
    else:
        try:
            disk_messages = _collect_live_result_messages(trace_dir, str(trace_dir))
        except Exception:
            app.logger.exception("Failed to build live RESULT snapshot for %s", trace_dir)
            disk_messages = []
        if task is not None:
            task._live_result_cache = {"time": now, "messages": disk_messages}

    # Append current in-memory messages after durable messages so the newest live
    # payload wins when both sources contain the same loop/event.
    combined = list(disk_messages)
    if task is not None and isinstance(task.messages, list):
        combined.extend(task.messages)

    loops, updated_at = _live_result_snapshot_from_messages(combined)
    return jsonify(
        {
            "id": trace_id,
            "alive": alive,
            "loops": loops,
            "loop_count": len(loops),
            "updated_at": updated_at,
        }
    ), 200


@app.route("/stdout", methods=["GET"])
def download_stdout_file():
'''
patch(
    "rdagent/log/server/app.py",
    _LIVE_RESULT_ROUTE_OLD,
    _LIVE_RESULT_ROUTE_NEW,
    "P48 live RESULT snapshot endpoint",
)



# ---------------------------------------------------------------- P50 true checkpoint resume start
# Upstream LoopBase.run() always resets loop_idx=0. P42 compensated by inflating
# loop_n and rescanning completed loops, which made a Loop 3 continuation look like
# it restarted at Loop 1. Honor the explicit resume start index instead.
_LOOP_RUN_RESET_OLD = '''        self.loop_idx = (
            0  # if we rerun the loop, we should revert the loop index to 0 to make sure every loop is correctly kicked
        )
'''
_LOOP_RUN_RESET_NEW = '''        self.loop_idx = int(getattr(self, "_resume_start_loop_idx", 0) or 0)
        if self.loop_idx:
            logger.info(
                f"Resume workflow kickoff directly from internal loop index {self.loop_idx} "
                f"(UI Loop {self.loop_idx + 1})"
            )
'''
patch(
    "rdagent/utils/workflow/loop.py",
    _LOOP_RUN_RESET_OLD,
    _LOOP_RUN_RESET_NEW,
    "P50 start resumed workflow at selected loop",
)

_LOOP_RESUME_RESET_OLD = '''            except self.LoopResumeError as e:
                logger.warning(f"Stop all the routines and resume loop: {e}")
                self.loop_idx = 0
'''
_LOOP_RESUME_RESET_NEW = '''            except self.LoopResumeError as e:
                logger.warning(f"Stop all the routines and resume loop: {e}")
                self.loop_idx = int(getattr(self, "_resume_start_loop_idx", 0) or 0)
'''
patch(
    "rdagent/utils/workflow/loop.py",
    _LOOP_RESUME_RESET_OLD,
    _LOOP_RESUME_RESET_NEW,
    "P50 preserve selected resume start across internal resume",
)



# ---------------------------------------------------------------- P51 history replay/list correctness
# Historical traces are durable files, so the server is authoritative for whether an
# experiment exists. Also make replayed traces immediately terminal when no live
# process owns them; the old 30-minute heuristic could make a completed historical
# run look "still running" after a deploy.
_HISTORY_END_OLD = '''    now = datetime.now(timezone.utc)
    if last_timestamp and (now - last_timestamp).total_seconds() > 1800:
        task.messages.append(
            {
                "tag": "END",
                "timestamp": now.isoformat(),
                "content": {"error_msg": "Trace session has ended.", "end_code": 0},
            }
        )
'''
_HISTORY_END_NEW = '''    now = datetime.now(timezone.utc)
    # A replayed trace with no live process is historical/completed regardless of
    # how recent its last pickle timestamp is. The old 30-minute age heuristic left
    # recently completed traces looking active after a server restart/deploy.
    _historical_or_finished = task.process is None or not task.is_alive()
    if (
        last_timestamp
        and _historical_or_finished
        and (not task.messages or task.messages[-1].get("tag") != "END")
    ):
        task.messages.append(
            {
                "tag": "END",
                "timestamp": now.isoformat(),
                "content": {"error_msg": "Trace session has ended.", "end_code": 0},
            }
        )
'''
patch(
    "rdagent/log/server/app.py",
    _HISTORY_END_OLD,
    _HISTORY_END_NEW,
    "P51 mark replayed historical traces completed immediately",
)

_HISTORY_LIST_OLD = '''def _collect_existing_trace_ids(trace_root: Path) -> list[str]:
    """Return trace ids that should be visible in the UI history panel."""

    if not trace_root.exists():
        return []

    trace_ids: list[str] = []
    for trace_dir in sorted(trace_root.glob("*/*"), key=lambda p: str(p)):
        if not trace_dir.is_dir():
            continue
        if "uploads" in trace_dir.relative_to(trace_root).parts:
            continue
        if not any(trace_dir.rglob("*.pkl")):
            continue

        trace_ids.append(trace_dir.relative_to(trace_root).as_posix())

    return trace_ids
'''
_HISTORY_LIST_NEW = '''def _collect_existing_trace_ids(trace_root: Path) -> list[str]:
    """Return durable trace ids in oldest -> newest activity order."""

    if not trace_root.exists():
        return []

    trace_records = []
    for trace_dir in trace_root.glob("*/*"):
        if not trace_dir.is_dir():
            continue
        if "uploads" in trace_dir.relative_to(trace_root).parts:
            continue

        pickle_files = list(trace_dir.rglob("*.pkl"))
        if not pickle_files:
            continue

        try:
            latest_mtime = max(file.stat().st_mtime for file in pickle_files)
        except OSError:
            latest_mtime = trace_dir.stat().st_mtime

        trace_records.append(
            (latest_mtime, trace_dir.relative_to(trace_root).as_posix())
        )

    # Frontend selects the last entry as the default, so return oldest -> newest.
    trace_records.sort(key=lambda item: (item[0], item[1]))
    return [trace_id for _, trace_id in trace_records]
'''
patch(
    "rdagent/log/server/app.py",
    _HISTORY_LIST_OLD,
    _HISTORY_LIST_NEW,
    "P51 make durable history list authoritative and chronological",
)



# ---------------------------------------------------------------- P52 fast history listing
# P51 made history authoritative but sorted each trace by recursively materializing and
# stat'ing every *.pkl. That turns a simple "open history" click into O(total trace
# files) filesystem work. Use a cheap existence probe plus the sibling stdout log /
# trace directory mtimes for activity ordering.
_HISTORY_LIST_P51_OLD = '''def _collect_existing_trace_ids(trace_root: Path) -> list[str]:
    """Return durable trace ids in oldest -> newest activity order."""

    if not trace_root.exists():
        return []

    trace_records = []
    for trace_dir in trace_root.glob("*/*"):
        if not trace_dir.is_dir():
            continue
        if "uploads" in trace_dir.relative_to(trace_root).parts:
            continue

        pickle_files = list(trace_dir.rglob("*.pkl"))
        if not pickle_files:
            continue

        try:
            latest_mtime = max(file.stat().st_mtime for file in pickle_files)
        except OSError:
            latest_mtime = trace_dir.stat().st_mtime

        trace_records.append(
            (latest_mtime, trace_dir.relative_to(trace_root).as_posix())
        )

    # Frontend selects the last entry as the default, so return oldest -> newest.
    trace_records.sort(key=lambda item: (item[0], item[1]))
    return [trace_id for _, trace_id in trace_records]
'''
_HISTORY_LIST_P52_NEW = '''def _collect_existing_trace_ids(trace_root: Path) -> list[str]:
    """Return durable trace ids in oldest -> newest activity order, cheaply."""

    if not trace_root.exists():
        return []

    trace_records = []
    for trace_dir in trace_root.glob("*/*"):
        if not trace_dir.is_dir():
            continue
        if "uploads" in trace_dir.relative_to(trace_root).parts:
            continue

        # Existence only: stop at the first persisted event instead of recursively
        # collecting/stat'ing every pickle in every experiment.
        try:
            if next(trace_dir.rglob("*.pkl"), None) is None:
                continue
        except OSError:
            continue

        activity_mtime = 0.0
        try:
            activity_mtime = trace_dir.stat().st_mtime
        except OSError:
            pass

        # Each run has a sibling stdout log (<trace-name>.log). Its mtime tracks
        # active work without walking the trace tree and is the best cheap ordering
        # signal for both live and completed experiments.
        stdout_path = trace_dir.parent / f"{trace_dir.name}.log"
        if stdout_path.exists():
            try:
                activity_mtime = max(activity_mtime, stdout_path.stat().st_mtime)
            except OSError:
                pass

        # Durable session directory is another cheap signal for resume-enabled runs.
        session_dir = trace_dir / "__session__"
        if session_dir.exists():
            try:
                activity_mtime = max(activity_mtime, session_dir.stat().st_mtime)
            except OSError:
                pass

        trace_records.append(
            (activity_mtime, trace_dir.relative_to(trace_root).as_posix())
        )

    trace_records.sort(key=lambda item: (item[0], item[1]))
    return [trace_id for _, trace_id in trace_records]
'''
patch(
    "rdagent/log/server/app.py",
    _HISTORY_LIST_P51_OLD,
    _HISTORY_LIST_P52_NEW,
    "P52 avoid full recursive pickle scan when listing history",
)



# ---------------------------------------------------------------- P55 CoderError + factor-data robustness
# A factor implementation can legitimately end with a CoderError after CoSTEER
# exhausts its repair attempts. P46 preserved the raw exception on HypothesisFeedback
# (useful for durable state), but upstream WebStorage copied that Python object directly
# into requests.post(json=...), which crashes JSON serialization. Also, the factor
# workspace silently creates an empty source-data directory after a fresh Fly deploy
# instead of regenerating daily_pv.h5. Fix both failure paths.

_WEBSTORAGE_CLASS_OLD = '''class WebStorage(Storage):
    """
    The storage for web app.
    It is used to provide the data for the web app.
    """
'''
_WEBSTORAGE_CLASS_NEW = '''class WebStorage(Storage):
    """
    The storage for web app.
    It is used to provide the data for the web app.
    """

    @staticmethod
    def _json_safe(value):
        """Recursively convert UI payloads to strict JSON-safe values.

        Durable FileStorage may keep rich Python objects such as exceptions, but
        the web transport must never crash the research loop merely because a
        feedback object contains a CoderError (or another non-JSON-native type).
        """
        import math

        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, BaseException):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): WebStorage._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [WebStorage._json_safe(v) for v in value]

        # numpy/pandas scalar types commonly expose item().
        item = getattr(value, "item", None)
        if callable(item):
            try:
                return WebStorage._json_safe(item())
            except Exception:
                pass
        return str(value)
'''
patch(
    "rdagent/log/ui/storage.py",
    _WEBSTORAGE_CLASS_OLD,
    _WEBSTORAGE_CLASS_NEW,
    "P55 add strict JSON-safe UI payload conversion",
)

_WEBSTORAGE_POST_OLD = '''            if not data:
                return "Normal log, skipped"
            if isinstance(data, list):
'''
_WEBSTORAGE_POST_NEW = '''            if not data:
                return "Normal log, skipped"
            data = self._json_safe(data)
            if isinstance(data, list):
'''
patch(
    "rdagent/log/ui/storage.py",
    _WEBSTORAGE_POST_OLD,
    _WEBSTORAGE_POST_NEW,
    "P55 sanitize UI payload before requests.post(json=...)",
)

_FACTOR_DATA_OLD = '''            source_data_path.mkdir(exist_ok=True, parents=True)
            code_path = self.workspace_path / f"factor.py"
'''
_FACTOR_DATA_NEW = '''            # On Fly the application root is replaced on deploy. The default
            # factor source-data folders live under git_ignore_folder, so a fresh
            # image can have no daily_pv.h5. The old code silently mkdir'ed an empty
            # folder and then every generated factor failed with FileNotFoundError.
            if self.target_task.version == 1 and not (source_data_path / "daily_pv.h5").exists():
                _prepare_lock_path = source_data_path.parent / ".factor_data_prepare.lock"
                _prepare_lock_path.parent.mkdir(exist_ok=True, parents=True)
                with FileLock(_prepare_lock_path):
                    if not (source_data_path / "daily_pv.h5").exists():
                        from rdagent.scenarios.qlib.experiment.utils import generate_data_folder_from_qlib

                        generate_data_folder_from_qlib()

            source_data_path.mkdir(exist_ok=True, parents=True)
            if self.target_task.version == 1 and not (source_data_path / "daily_pv.h5").exists():
                raise FileNotFoundError(
                    f"RD-Agent factor source data is missing after preparation: "
                    f"{source_data_path / 'daily_pv.h5'}"
                )

            code_path = self.workspace_path / f"factor.py"
'''
patch(
    "rdagent/components/coder/factor_coder/factor.py",
    _FACTOR_DATA_OLD,
    _FACTOR_DATA_NEW,
    "P55 regenerate/verify daily_pv.h5 before factor execution",
)

_P46_EXEC_HELPERS_OLD = '''def _is_execution_failure(exc: Exception | str | None) -> bool:
    """Return True for runtime/infrastructure failures, not research rejection."""
    text = str(exc or "")
    lower = text.lower()
    return (
        "failed to run this experiment" in lower
        or ("failed to run " in lower and " model, because " in lower)
        or "qrun_exit_code=" in lower
        or "no result file found" in lower
        or "\\nkilled" in lower
        or "process was killed" in lower
        or "running time exceeds" in lower
        or "qrun timed out" in lower
    )


def _execution_failure_reason(exc: Exception | str | None) -> str:
    text = str(exc or "")
    lower = text.lower()
    if "qrun_exit_code=137" in lower or "qrun_exit_code=-9" in lower or "\\nkilled" in lower:
        return (
            "Execution failed: the Qlib process was killed before producing a complete "
            "backtest result. This is an infrastructure/resource failure (commonly "
            "memory pressure/OOM), not evidence that the research hypothesis is bad."
        )
    if "qrun_exit_code=124" in lower or "timed out" in lower or "running time exceeds" in lower:
        return (
            "Execution failed: the Qlib run timed out before producing a complete "
            "backtest result. Retry/repair the execution before evaluating the hypothesis."
        )
    return (
        "Execution failed: Qlib did not produce a valid backtest result. "
        "Retry/repair the execution before generating a new research hypothesis."
    )


class QuantRDLoop(RDLoop):
'''
_P46_EXEC_HELPERS_NEW = '''def _is_execution_failure(exc: Exception | str | None) -> bool:
    """Return True when the experiment never produced a valid runnable result.

    Scientific rejection is handled later by the evaluator with no exception.
    CoderError/FactorEmptyError/ModelEmptyError therefore represent implementation
    or execution failure, not evidence against the research hypothesis.
    """
    text = str(exc or "")
    lower = text.lower()
    return (
        isinstance(exc, (FactorEmptyError, ModelEmptyError))
        or "all tasks are failed" in lower
        or "expected output file not found" in lower
        or "filenotfounderror" in lower
        or "failed to run this experiment" in lower
        or ("failed to run " in lower and " model, because " in lower)
        or "qrun_exit_code=" in lower
        or "no result file found" in lower
        or "\\nkilled" in lower
        or "process was killed" in lower
        or "running time exceeds" in lower
        or "qrun timed out" in lower
    )


def _execution_failure_reason(exc: Exception | str | None) -> str:
    text = str(exc or "")
    lower = text.lower()
    if "qrun_exit_code=137" in lower or "qrun_exit_code=-9" in lower or "\\nkilled" in lower:
        return (
            "Execution failed: the Qlib process was killed before producing a complete "
            "backtest result. This is an infrastructure/resource failure (commonly "
            "memory pressure/OOM), not evidence that the research hypothesis is bad."
        )
    if "qrun_exit_code=124" in lower or "timed out" in lower or "running time exceeds" in lower:
        return (
            "Execution failed: the Qlib run timed out before producing a complete "
            "backtest result. Retry/repair the execution before evaluating the hypothesis."
        )
    if (
        isinstance(exc, (FactorEmptyError, ModelEmptyError))
        or "all tasks are failed" in lower
        or "expected output file not found" in lower
        or "filenotfounderror" in lower
    ):
        return (
            "Execution failed: the generated factor/model implementation did not produce "
            "a valid runnable output. This is an implementation/execution failure, not "
            "scientific evidence against the hypothesis. Retry this loop from coding "
            "after repairing the implementation/runtime data dependency."
        )
    return (
        "Execution failed: Qlib did not produce a valid backtest result. "
        "Retry/repair the execution before generating a new research hypothesis."
    )


class QuantRDLoop(RDLoop):
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _P46_EXEC_HELPERS_OLD,
    _P46_EXEC_HELPERS_NEW,
    "P55 classify CoderError/no-output as execution failure",
)



# P55b remember which durable checkpoint should be used for an execution retry.
_P46_FAILURE_STAGE_OLD = '''            if _is_execution_failure(e):
                _reason = _execution_failure_reason(e)
                self._execution_failure_pending = _reason
                feedback = HypothesisFeedback(
'''
_P46_FAILURE_STAGE_NEW = '''            if _is_execution_failure(e):
                _reason = _execution_failure_reason(e)
                self._execution_failure_pending = _reason
                # If coding itself failed, the "after coding" checkpoint contains
                # coding=None and would immediately jump to feedback. Resume from
                # direct_exp_gen so the SAME hypothesis/experiment reruns coding.
                # If running failed, the coding output is valid and should be reused.
                self._execution_failure_retry_from = (
                    "direct_exp_gen"
                    if prev_out.get("coding") is None
                    else "coding"
                )
                feedback = HypothesisFeedback(
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _P46_FAILURE_STAGE_OLD,
    _P46_FAILURE_STAGE_NEW,
    "P55 remember coding-vs-running retry checkpoint",
)



# ---------------------------------------------------------------- P58 resume workspace repair + terminal failure hardening
# Durable loop checkpoints survive Fly redeploys under /data, while generated Qlib
# workspaces live in the image filesystem. Rehydrate every file-backed workspace from
# its persisted file_dict immediately before qrun so a continued checkpoint never
# points at an empty/recreated workspace directory.
_P58_WORKSPACE_REHYDRATE_OLD = '''        _qlib_run = qtde.run(
            local_path=str(self.workspace_path),
            entry=f"qrun {qlib_config_name}",
            env=run_env,
        )
'''
_P58_WORKSPACE_REHYDRATE_NEW = '''        # P58: a durable checkpoint can outlive its ephemeral workspace after a
        # Fly redeploy. file_dict is pickled with the checkpoint, so replay it before
        # qrun instead of assuming workspace_path still contains the template files.
        self.prepare()
        self.inject_files(**self.file_dict)
        _config_path = self.workspace_path / qlib_config_name
        if not _config_path.exists():
            _status = (
                "[RD-Agent execution status] missing_qrun_config="
                f"{qlib_config_name} workspace={self.workspace_path}"
            )
            logger.error(_status)
            logger.log_object(_status, tag="Qlib_execute_log")
            return None, _status

        _qlib_run = qtde.run(
            local_path=str(self.workspace_path),
            entry=f"qrun {qlib_config_name}",
            env=run_env,
        )
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _P58_WORKSPACE_REHYDRATE_OLD,
    _P58_WORKSPACE_REHYDRATE_NEW,
    "P58 rehydrate durable Qlib workspace before qrun",
)

# The workflow kickoff coroutine can race one loop ahead of the worker coroutine.
# A post-record termination check alone can therefore allow the next direct_exp_gen
# to start even after feedback already classified the prior loop as an execution
# failure. Guard the generator itself so no speculative LLM work starts.
_P58_DIRECT_GUARD_OLD = '''    async def direct_exp_gen(self, prev_out: dict[str, Any]):
        while True:
'''
_P58_DIRECT_GUARD_NEW = '''    async def direct_exp_gen(self, prev_out: dict[str, Any]):
        if getattr(self, "_execution_failure_pending", None):
            raise self.LoopTerminationError("Execution failure requires retry/repair")
        while True:
            if getattr(self, "_execution_failure_pending", None):
                raise self.LoopTerminationError("Execution failure requires retry/repair")
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _P58_DIRECT_GUARD_OLD,
    _P58_DIRECT_GUARD_NEW,
    "P58 block speculative next hypothesis after execution failure",
)

# RESULT must still explain a terminal execution failure if WebStorage never persisted
# the structured feedback event. Derive a small, secret-free failure summary from the
# run stdout and expose it alongside /result/live's structured loop rows.
_P58_LIVE_FAILURE_ROUTE_OLD = '''@app.route("/result/live", methods=["GET"])
def live_result_snapshot():
'''
_P58_LIVE_FAILURE_ROUTE_NEW = '''def _live_result_execution_failure(trace_dir: Path):
    stdout_path = trace_dir.parent / f"{trace_dir.name}.log"
    if not stdout_path.exists():
        return None
    try:
        with stdout_path.open("rb") as _fh:
            _fh.seek(0, 2)
            _size = _fh.tell()
            _fh.seek(max(0, _size - 131072))
            _tail = _fh.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    _lower = _tail.lower()
    _failed = (
        "execution failure requires retry/repair" in _lower
        or "execution failure recorded" in _lower
        or "qrun_exit_code=" in _lower
        or "missing_qrun_config=" in _lower
        or "failed to run this experiment" in _lower
    )
    if not _failed:
        return None

    if (
        "filenotfounderror" in _lower
        and "conf_combined_factors_sota_model.yaml" in _lower
    ):
        _reason = (
            "Required Qlib configuration file was missing from the resumed workspace: "
            "conf_combined_factors_sota_model.yaml. The backtest did not run."
        )
    elif "missing_qrun_config=" in _lower:
        _reason = (
            "Required Qlib configuration was missing from the experiment workspace. "
            "The backtest did not run."
        )
    elif "qrun_exit_code=137" in _lower or "qrun_exit_code=-9" in _lower:
        _reason = (
            "The Qlib process was killed before producing a complete backtest result, "
            "commonly because of memory/resource pressure."
        )
    elif "qrun_exit_code=124" in _lower or "qrun timed out" in _lower:
        _reason = "The Qlib backtest timed out before producing a complete result."
    else:
        _reason = (
            "The experiment hit an execution/runtime failure before a valid Qlib "
            "backtest result was produced."
        )

    return {
        "status": "execution_failed",
        "stage": "Qlib backtest / running",
        "reason": _reason,
        "scientific_result": "Not evaluated",
        "metrics_available": False,
        "retry": "Retry this experiment from its last valid coding checkpoint.",
    }


@app.route("/result/live", methods=["GET"])
def live_result_snapshot():
'''
patch(
    "rdagent/log/server/app.py",
    _P58_LIVE_FAILURE_ROUTE_OLD,
    _P58_LIVE_FAILURE_ROUTE_NEW,
    "P58 derive terminal RESULT failure summary from stdout",
)

_P58_LIVE_JSON_OLD = '''    loops, updated_at = _live_result_snapshot_from_messages(combined)
    return jsonify(
        {
            "id": trace_id,
            "alive": alive,
            "loops": loops,
            "loop_count": len(loops),
            "updated_at": updated_at,
        }
    ), 200
'''
_P58_LIVE_JSON_NEW = '''    loops, updated_at = _live_result_snapshot_from_messages(combined)
    execution_failure = _live_result_execution_failure(trace_dir)
    return jsonify(
        {
            "id": trace_id,
            "alive": alive,
            "loops": loops,
            "loop_count": len(loops),
            "updated_at": updated_at,
            "execution_failure": execution_failure,
        }
    ), 200
'''
patch(
    "rdagent/log/server/app.py",
    _P58_LIVE_JSON_OLD,
    _P58_LIVE_JSON_NEW,
    "P58 include terminal failure in live RESULT snapshot",
)

# Never print provider credentials in stdout. The previous first-backend diagnostic
# logged the complete settings object, including openai_api_key.
_P58_LLM_LOG_OLD = '''        if not self.__class__._has_logged_settings:
            logger.info(f"{LITELLM_SETTINGS}")
            logger.log_object(LITELLM_SETTINGS.model_dump(), tag="LITELLM_SETTINGS")
            self.__class__._has_logged_settings = True
'''
_P58_LLM_LOG_NEW = '''        if not self.__class__._has_logged_settings:
            _raw_settings = LITELLM_SETTINGS.model_dump()
            _safe_settings = {}
            for _name, _value in _raw_settings.items():
                _lower_name = str(_name).lower()
                _secret_field = (
                    "api_key" in _lower_name
                    or _lower_name.endswith("_key")
                    or "password" in _lower_name
                    or "secret" in _lower_name
                    or "credential" in _lower_name
                )
                _safe_settings[_name] = (
                    "[REDACTED]" if _secret_field and _value else _value
                )
            logger.info(f"LiteLLM settings: {_safe_settings}")
            logger.log_object(_safe_settings, tag="LITELLM_SETTINGS")
            self.__class__._has_logged_settings = True
'''
patch(
    "rdagent/oai/backend/litellm.py",
    _P58_LLM_LOG_OLD,
    _P58_LLM_LOG_NEW,
    "P58 redact provider credentials from LiteLLM settings logs",
)


# ---------------------------------------------------------------- P59 continuation-aware RESULT inheritance
# A resumed task starts with an empty in-memory task.messages list. The durable trace
# directory is copied, but RESULT must not wait for the new loop to finish before it
# can show the successful loops from the source experiment. Merge source RESULT events
# up to the selected checkpoint into /result/live, while excluding any source loops
# that occur after the branch point.
_P59_PARENT_HELPER_ANCHOR = '''def _live_result_execution_failure(trace_dir: Path):
'''
_P59_PARENT_HELPER_NEW = '''def _resume_parent_result_messages(trace_dir: Path):
    import json as _json

    meta_path = trace_dir / "_resume_meta.json"
    if not meta_path.exists():
        return [], None

    try:
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return [], None

    source_id = str(meta.get("source_id") or "").strip().strip("/")
    checkpoint = meta.get("checkpoint") if isinstance(meta.get("checkpoint"), dict) else {}
    if not source_id or not checkpoint:
        return [], None

    source_dir = (log_folder_path / source_id).resolve()
    root = log_folder_path.resolve()
    try:
        if os.path.commonpath([str(source_dir), str(root)]) != str(root):
            return [], None
    except ValueError:
        return [], None
    if not source_dir.exists() or not source_dir.is_dir():
        return [], {
            "source_id": source_id,
            "available": False,
            "reason": "source trace is no longer available",
        }

    try:
        selected_loop = int(checkpoint.get("loop_index"))
    except (TypeError, ValueError):
        return [], None

    selected_step = str(checkpoint.get("step_name") or "").strip()
    # A checkpoint is written after its named step. running/feedback/record can
    # therefore contribute RESULT data for the selected loop; direct_exp_gen/coding
    # cannot and must not inherit the later failed/stale result from the source trace.
    include_selected_loop = selected_step in {"running", "feedback", "record"}
    max_result_loop = selected_loop if include_selected_loop else selected_loop - 1

    if max_result_loop < 0:
        return [], {
            "source_id": source_id,
            "available": True,
            "max_result_loop": max_result_loop,
            "selected_loop": selected_loop,
            "selected_step": selected_step,
        }

    parent_messages = []
    try:
        parent_messages = _collect_live_result_messages(source_dir, str(source_dir))
    except Exception:
        app.logger.exception(
            "Failed to replay source RESULT while continuing %s from %s",
            trace_dir,
            source_dir,
        )
        parent_messages = []

    # If disk compatibility replay yields nothing, use the already-loaded source task
    # as a second path. This protects older traces whose persisted Python objects are
    # only readable through the server's existing replayed UI messages.
    if not parent_messages:
        source_task = rdagent_processes.get(str(source_dir))
        if source_task is not None and isinstance(source_task.messages, list):
            parent_messages = [
                msg
                for msg in source_task.messages
                if isinstance(msg, dict)
                and msg.get("tag")
                in {
                    "research.hypothesis",
                    "feedback.metric",
                    "feedback.hypothesis_feedback",
                }
            ]

    filtered = []
    for msg in parent_messages:
        if not isinstance(msg, dict):
            continue
        try:
            loop_id = int(msg.get("loop_id"))
        except (TypeError, ValueError):
            continue
        if 0 <= loop_id <= max_result_loop:
            filtered.append(msg)

    return filtered, {
        "source_id": source_id,
        "available": True,
        "max_result_loop": max_result_loop,
        "selected_loop": selected_loop,
        "selected_step": selected_step,
    }


def _live_result_execution_failure(trace_dir: Path):
'''
patch(
    "rdagent/log/server/app.py",
    _P59_PARENT_HELPER_ANCHOR,
    _P59_PARENT_HELPER_NEW,
    "P59 inherit source RESULT up to continuation checkpoint",
)

_P59_COMBINE_OLD = '''    # Append current in-memory messages after durable messages so the newest live
    # payload wins when both sources contain the same loop/event.
    combined = list(disk_messages)
    if task is not None and isinstance(task.messages, list):
        combined.extend(task.messages)

    loops, updated_at = _live_result_snapshot_from_messages(combined)
    execution_failure = _live_result_execution_failure(trace_dir)
'''
_P59_COMBINE_NEW = '''    # A continuation/branch must show its already-completed source loops immediately.
    # Parent rows are added first; the copied/truncated destination trace and then live
    # in-memory events override them for the same loop as the continuation progresses.
    parent_messages, continuation_source = _resume_parent_result_messages(trace_dir)
    parent_loops, _ = _live_result_snapshot_from_messages(parent_messages)

    combined = list(parent_messages)
    combined.extend(disk_messages)
    if task is not None and isinstance(task.messages, list):
        combined.extend(task.messages)

    loops, updated_at = _live_result_snapshot_from_messages(combined)
    execution_failure = _live_result_execution_failure(trace_dir)
    terminal = bool(
        task is None
        or task.process is None
        or task.process.exitcode is not None
    )
'''
patch(
    "rdagent/log/server/app.py",
    _P59_COMBINE_OLD,
    _P59_COMBINE_NEW,
    "P59 merge inherited + destination + live RESULT streams",
)

_P59_RESPONSE_OLD = '''            "execution_failure": execution_failure,
        }
    ), 200
'''
_P59_RESPONSE_NEW = '''            "execution_failure": execution_failure,
            "terminal": terminal,
            "continuation_source": continuation_source,
            "inherited_loop_count": len(parent_loops),
        }
    ), 200
'''
patch(
    "rdagent/log/server/app.py",
    _P59_RESPONSE_OLD,
    _P59_RESPONSE_NEW,
    "P59 expose continuation RESULT inheritance state",
)


# ---------------------------------------------------------------- P60 prevent stale copied future loops during branch startup
# copytree() necessarily copies the source's full durable trace before the child calls
# LoopBase.load(checkout=True) and truncates it to the selected checkpoint. During that
# short window /result/live must not expose source events after the branch point.
_P60_INFO_MAX_OLD = '''            "selected_step": selected_step,
        }

    parent_messages = []
'''
_P60_INFO_MAX_NEW = '''            "selected_step": selected_step,
            "created_at": meta.get("created_at"),
        }

    parent_messages = []
'''
patch(
    "rdagent/log/server/app.py",
    _P60_INFO_MAX_OLD,
    _P60_INFO_MAX_NEW,
    "P60 include continuation creation time for empty parent range",
)

_P60_INFO_FINAL_OLD = '''        "selected_step": selected_step,
    }


def _live_result_execution_failure(trace_dir: Path):
'''
_P60_INFO_FINAL_NEW = '''        "selected_step": selected_step,
        "created_at": meta.get("created_at"),
    }


def _filter_continuation_destination_messages(messages, continuation_source):
    """Drop copied source events past the selected branch checkpoint.

    Events produced after _resume_meta.created_at belong to the new continuation and
    are retained even when they reuse the selected loop id.
    """
    if not isinstance(continuation_source, dict):
        return list(messages or [])

    try:
        max_result_loop = int(continuation_source.get("max_result_loop"))
    except (TypeError, ValueError):
        return list(messages or [])

    created_at_raw = str(continuation_source.get("created_at") or "").strip()
    if not created_at_raw:
        return list(messages or [])

    try:
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
    except Exception:
        return list(messages or [])

    filtered = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue

        try:
            loop_id = int(msg.get("loop_id"))
        except (TypeError, ValueError):
            loop_id = None

        timestamp_raw = str(msg.get("timestamp") or "").strip()
        is_new_continuation_event = False
        if timestamp_raw:
            try:
                timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                is_new_continuation_event = timestamp >= created_at
            except Exception:
                is_new_continuation_event = False

        if (
            loop_id is None
            or loop_id <= max_result_loop
            or is_new_continuation_event
        ):
            filtered.append(msg)

    return filtered


def _live_result_execution_failure(trace_dir: Path):
'''
patch(
    "rdagent/log/server/app.py",
    _P60_INFO_FINAL_OLD,
    _P60_INFO_FINAL_NEW,
    "P60 filter copied destination RESULT past branch checkpoint",
)

_P60_COMBINE_OLD = '''    parent_messages, continuation_source = _resume_parent_result_messages(trace_dir)
    parent_loops, _ = _live_result_snapshot_from_messages(parent_messages)

    combined = list(parent_messages)
    combined.extend(disk_messages)
'''
_P60_COMBINE_NEW = '''    parent_messages, continuation_source = _resume_parent_result_messages(trace_dir)
    parent_loops, _ = _live_result_snapshot_from_messages(parent_messages)
    disk_messages = _filter_continuation_destination_messages(
        disk_messages,
        continuation_source,
    )

    combined = list(parent_messages)
    combined.extend(disk_messages)
'''
patch(
    "rdagent/log/server/app.py",
    _P60_COMBINE_OLD,
    _P60_COMBINE_NEW,
    "P60 suppress stale copied future-loop RESULT events",
)


# ---------------------------------------------------------------- P61 fresh Qlib execution; no stale backtest cache
# P3 falls back from QlibCondaEnv (whose cache is disabled upstream) to LocalEnv.
# LocalConf defaults enable_cache=True, and Env.cached_run hashes only .py/.csv/.yaml
# workspace files. Qlib's actual combined factor matrix is parquet and run_env is not
# included in that cache key, so distinct experiments can silently reuse an older qrun
# result. Disable LocalEnv execution caching specifically for Qlib workspaces.
_P61_QLIB_LOCAL_CACHE_OLD = '''                qtde = LocalEnv(conf=LocalConf(default_entry="python main.py", bin_path=os.environ.get("PATH", "")))
'''
_P61_QLIB_LOCAL_CACHE_NEW = '''                qtde = LocalEnv(
                    conf=LocalConf(
                        default_entry="python main.py",
                        bin_path=os.environ.get("PATH", ""),
                        enable_cache=False,
                    )
                )
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _P61_QLIB_LOCAL_CACHE_OLD,
    _P61_QLIB_LOCAL_CACHE_NEW,
    "P61 disable stale LocalEnv cache for Qlib backtests",
)

# Runner-level pickle caching is also unsafe for research execution because its
# upstream key is based on task descriptions, not generated implementation code,
# market-data revisions, or runtime configuration. Keep lower-level code caches, but
# always execute the aggregate Qlib factor/model experiment.
_P61_RUNNER_CACHE_DECORATOR = '''    @cache_with_pickle(CachedRunner.get_cache_key, CachedRunner.assign_cached_result)
'''
for _runner_path in (
    "rdagent/scenarios/qlib/developer/factor_runner.py",
    "rdagent/scenarios/qlib/developer/model_runner.py",
):
    patch(
        _runner_path,
        _P61_RUNNER_CACHE_DECORATOR,
        "",
        f"P61 disable stale aggregate runner cache in {_runner_path.split('/')[-1]}",
    )

# Future logs must prove that qrun was really launched rather than silently replayed.
_P61_FRESH_QRUN_OLD = '''        _qlib_run = qtde.run(
            local_path=str(self.workspace_path),
            entry=f"qrun {qlib_config_name}",
            env=run_env,
        )
'''
_P61_FRESH_QRUN_NEW = '''        logger.info(
            f"[rd-agent] FRESH_QRUN config={qlib_config_name} "
            f"env_cache={getattr(qtde.conf, 'enable_cache', None)} "
            f"workspace={self.workspace_path}"
        )
        _qlib_run = qtde.run(
            local_path=str(self.workspace_path),
            entry=f"qrun {qlib_config_name}",
            env=run_env,
        )
        logger.info(
            f"[rd-agent] FRESH_QRUN_DONE config={qlib_config_name} "
            f"exit_code={_qlib_run.exit_code} running_time={_qlib_run.running_time:.1f}s"
        )
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _P61_FRESH_QRUN_OLD,
    _P61_FRESH_QRUN_NEW,
    "P61 log fresh qrun start/end",
)


# ---------------------------------------------------------------- P62 time-budget guard before expensive hypothesis generation
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    "import asyncio\nfrom typing import Any",
    "import asyncio\nimport os\nfrom typing import Any",
    "P62 import os for pre-hypothesis time guard",
)

_P62_DIRECT_OLD = '''    async def direct_exp_gen(self, prev_out: dict[str, Any]):
        if getattr(self, "_execution_failure_pending", None):
            raise self.LoopTerminationError("Execution failure requires retry/repair")
        while True:
'''
_P62_DIRECT_NEW = '''    async def direct_exp_gen(self, prev_out: dict[str, Any]):
        if getattr(self, "_execution_failure_pending", None):
            raise self.LoopTerminationError("Execution failure requires retry/repair")

        _min_hypothesis_start_s = int(
            os.environ.get("RDAGENT_MIN_HYPOTHESIS_START_SECONDS", "3600")
        )
        _remaining_before_hypothesis_s = self.timer.remain_time().total_seconds()
        if _remaining_before_hypothesis_s < _min_hypothesis_start_s:
            logger.warning(
                f"Only {self.timer.remain_time()} left (< "
                f"{_min_hypothesis_start_s}s); stopping before generating another "
                "hypothesis that cannot be executed."
            )
            raise self.LoopTerminationError(
                "Insufficient time to start another research loop"
            )

        while True:
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _P62_DIRECT_OLD,
    _P62_DIRECT_NEW,
    "P62 stop before expensive hypothesis generation when budget is too small",
)

patch(
    "rdagent/utils/workflow/loop.py",
    '_factor_min_s = int(os.environ.get("RDAGENT_MIN_FACTOR_LOOP_SECONDS", "1800"))',
    '_factor_min_s = int(os.environ.get("RDAGENT_MIN_FACTOR_LOOP_SECONDS", "5400"))',
    "P62 require a realistic 90-minute default budget for factor loops",
)


# ---------------------------------------------------------------- P63 factor-value cache follows source-data revisions
_P63_FACTOR_HASH_OLD = '''    def hash_func(self, data_type: str = "Debug") -> str:
        return (
            md5_hash(data_type + self.file_dict["factor.py"])
            if ("factor.py" in self.file_dict and not self.raise_exception)
            else None
        )
'''
_P63_FACTOR_HASH_NEW = '''    def hash_func(self, data_type: str = "Debug") -> str:
        if "factor.py" not in self.file_dict or self.raise_exception:
            return None

        _data_fingerprint = ""
        if self.target_task.version == 1:
            _source_data_path = Path(
                FACTOR_COSTEER_SETTINGS.data_folder_debug
                if data_type == "Debug"
                else FACTOR_COSTEER_SETTINGS.data_folder
            )
            _fingerprint_parts = []
            for _name in ("daily_pv.h5", "README.md"):
                _path = _source_data_path / _name
                if _path.exists():
                    _stat = _path.stat()
                    _fingerprint_parts.append(
                        f"{_name}:{_stat.st_size}:{_stat.st_mtime_ns}"
                    )
                else:
                    _fingerprint_parts.append(f"{_name}:missing")
            _data_fingerprint = "|".join(_fingerprint_parts)

        return md5_hash(
            data_type + self.file_dict["factor.py"] + _data_fingerprint
        )
'''
patch(
    "rdagent/components/coder/factor_coder/factor.py",
    _P63_FACTOR_HASH_OLD,
    _P63_FACTOR_HASH_NEW,
    "P63 include qlib source-data fingerprint in factor execution cache",
)


# ---------------------------------------------------------------- P65 resumed Qlib workspace lifecycle
# A resumed checkpoint can reference a workspace directory from a pre-deploy image.
# P58 repaired that directory inside execute(), but factor/model runners write parquet
# BEFORE execute() is called. Materialize the workspace at runner entry, then keep the
# P58 pre-qrun repair as a second safety net.
_P65_WS_INIT_OLD = '''    def __init__(self, template_folder_path: Path, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.inject_code_from_folder(template_folder_path)

    def execute(self, qlib_config_name: str = "conf.yaml", run_env: dict = {}, *args, **kwargs) -> str:
'''
_P65_WS_INIT_NEW = '''    def __init__(self, template_folder_path: Path, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.inject_code_from_folder(template_folder_path)

    def ensure_materialized(self) -> None:
        """Recreate an ephemeral workspace from the durable in-memory file_dict."""
        self.prepare()
        if self.file_dict:
            self.inject_files(**dict(self.file_dict))

    def execute(self, qlib_config_name: str = "conf.yaml", run_env: dict = {}, *args, **kwargs) -> str:
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _P65_WS_INIT_OLD,
    _P65_WS_INIT_NEW,
    "P65 add Qlib workspace materialization lifecycle",
)

_P65_P58_REHYDRATE_OLD = '''        self.prepare()
        self.inject_files(**self.file_dict)
        _config_path = self.workspace_path / qlib_config_name
'''
_P65_P58_REHYDRATE_NEW = '''        self.ensure_materialized()
        _config_path = self.workspace_path / qlib_config_name
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _P65_P58_REHYDRATE_OLD,
    _P65_P58_REHYDRATE_NEW,
    "P65 use shared materialization before qrun",
)

_P65_FACTOR_DEVELOP_OLD = '''        if exp.based_experiments and exp.based_experiments[-1].result is None:
            logger.info(f"Baseline experiment execution ...")
'''
_P65_FACTOR_DEVELOP_NEW = '''        # P65: resume checkpoints outlive the image filesystem. The factor runner
        # writes combined_factors_df.parquet before QlibFBWorkspace.execute(), so
        # restore the experiment workspace before any processing/writes.
        exp.experiment_workspace.ensure_materialized()

        if exp.based_experiments and exp.based_experiments[-1].result is None:
            logger.info(f"Baseline experiment execution ...")
'''
patch(
    "rdagent/scenarios/qlib/developer/factor_runner.py",
    _P65_FACTOR_DEVELOP_OLD,
    _P65_FACTOR_DEVELOP_NEW,
    "P65 materialize factor experiment workspace before parquet writes",
)

_P65_MODEL_DEVELOP_OLD = '''        if exp.based_experiments and exp.based_experiments[-1].result is None:
            exp.based_experiments[-1] = self.develop(exp.based_experiments[-1])
'''
_P65_MODEL_DEVELOP_NEW = '''        # P65: restore the ephemeral experiment workspace before SOTA factor
        # parquet/model files are written during a resumed run.
        exp.experiment_workspace.ensure_materialized()

        if exp.based_experiments and exp.based_experiments[-1].result is None:
            exp.based_experiments[-1] = self.develop(exp.based_experiments[-1])
'''
patch(
    "rdagent/scenarios/qlib/developer/model_runner.py",
    _P65_MODEL_DEVELOP_OLD,
    _P65_MODEL_DEVELOP_NEW,
    "P65 materialize model experiment workspace before parquet writes",
)


# ---------------------------------------------------------------- P66 defensive runner writes + reliable time-budget action
# Keep every parquet write independently safe even if a future runner refactor bypasses
# the runner-entry materialization call.
_P66_FACTOR_TARGET_OLD = '''            target_path = exp.experiment_workspace.workspace_path / "combined_factors_df.parquet"

            # Save the combined factors to the workspace
            combined_factors.to_parquet(target_path, engine="pyarrow")
'''
_P66_FACTOR_TARGET_NEW = '''            target_path = exp.experiment_workspace.workspace_path / "combined_factors_df.parquet"
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Save the combined factors to the workspace
            combined_factors.to_parquet(target_path, engine="pyarrow")
'''
patch(
    "rdagent/scenarios/qlib/developer/factor_runner.py",
    _P66_FACTOR_TARGET_OLD,
    _P66_FACTOR_TARGET_NEW,
    "P66 ensure factor combined parquet parent exists",
)

_P66_FACTOR_BASE_TARGET_OLD = '''                target_path = exp.experiment_workspace.workspace_path / "combined_factors_df.parquet"
                # Save the combined factors to the workspace
                factors.to_parquet(target_path, engine="pyarrow")
'''
_P66_FACTOR_BASE_TARGET_NEW = '''                target_path = exp.experiment_workspace.workspace_path / "combined_factors_df.parquet"
                target_path.parent.mkdir(parents=True, exist_ok=True)
                # Save the combined factors to the workspace
                factors.to_parquet(target_path, engine="pyarrow")
'''
patch(
    "rdagent/scenarios/qlib/developer/factor_runner.py",
    _P66_FACTOR_BASE_TARGET_OLD,
    _P66_FACTOR_BASE_TARGET_NEW,
    "P66 ensure base-factor parquet parent exists",
)

_P66_MODEL_TARGET_OLD = '''                target_path = exp.experiment_workspace.workspace_path / "combined_factors_df.parquet"

                # Save the combined factors to the workspace
                combined_factors.to_parquet(target_path, engine="pyarrow")
'''
_P66_MODEL_TARGET_NEW = '''                target_path = exp.experiment_workspace.workspace_path / "combined_factors_df.parquet"
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # Save the combined factors to the workspace
                combined_factors.to_parquet(target_path, engine="pyarrow")
'''
patch(
    "rdagent/scenarios/qlib/developer/model_runner.py",
    _P66_MODEL_TARGET_OLD,
    _P66_MODEL_TARGET_NEW,
    "P66 ensure model combined parquet parent exists",
)

_P66_ACTION_OLD = '''                    _action = None
                    try:
                        _direct = self.loop_prev_out[loop_id].get("direct_exp_gen") or {}
                        _proposal = _direct.get("propose") if isinstance(_direct, dict) else None
                        _action = getattr(_proposal, "action", None)
                    except Exception:
                        _action = None
'''
_P66_ACTION_NEW = '''                    _action = None
                    try:
                        _loop_state = self.loop_prev_out.get(loop_id, {})
                        _direct = (
                            _loop_state.get("direct_exp_gen")
                            if isinstance(_loop_state, dict)
                            else None
                        ) or {}
                        _proposal = _direct.get("propose") if isinstance(_direct, dict) else None
                        _action = getattr(_proposal, "action", None)
                        if _action is None and isinstance(_proposal, dict):
                            _action = _proposal.get("action")

                        # With parallel kickoff/resume the current loop state can briefly
                        # be incomplete at this hook. Fall back to the generated/coded
                        # experiment class instead of weakening the budget to "unknown".
                        if _action not in {"factor", "model"} and isinstance(_loop_state, dict):
                            _candidate = (
                                _loop_state.get("coding")
                                or (_direct.get("exp_gen") if isinstance(_direct, dict) else None)
                            )
                            _candidate_name = type(_candidate).__name__.lower()
                            if "factor" in _candidate_name:
                                _action = "factor"
                            elif "model" in _candidate_name:
                                _action = "model"
                    except Exception:
                        _action = None
'''
patch(
    "rdagent/utils/workflow/loop.py",
    _P66_ACTION_OLD,
    _P66_ACTION_NEW,
    "P66 resolve factor/model action reliably in time-budget guard",
)


# ---------------------------------------------------------------- P67 workspace-loss fallback + legacy failure visibility
# P65/P66 should make a missing experiment workspace impossible. If a future refactor
# reintroduces it, convert only this specific infrastructure OSError into the normal
# execution-failure path instead of crashing the entire task.
_P67_RUNNING_OLD = '''    def running(self, prev_out: dict[str, Any]):
        if prev_out["direct_exp_gen"]["propose"].action == "factor":
            exp = self.factor_runner.develop(prev_out["coding"])
            if exp is None:
                logger.error(f"Factor extraction failed.")
                raise FactorEmptyError("Factor extraction failed.")
        elif prev_out["direct_exp_gen"]["propose"].action == "model":
            exp = self.model_runner.develop(prev_out["coding"])
        logger.log_object(exp, tag="runner result")
        return exp
'''
_P67_RUNNING_NEW = '''    def running(self, prev_out: dict[str, Any]):
        _action = prev_out["direct_exp_gen"]["propose"].action
        try:
            if _action == "factor":
                exp = self.factor_runner.develop(prev_out["coding"])
                if exp is None:
                    logger.error(f"Factor extraction failed.")
                    raise FactorEmptyError("Factor extraction failed.")
            elif _action == "model":
                exp = self.model_runner.develop(prev_out["coding"])
        except OSError as exc:
            _text = str(exc)
            _lower = _text.lower()
            if (
                "rd-agent_workspace" in _lower
                and (
                    "non-existent directory" in _lower
                    or "no such file or directory" in _lower
                )
            ):
                _message = (
                    "Execution failed: resumed Qlib workspace disappeared before "
                    f"{_action} runner output could be written: {_text}"
                )
                if _action == "model":
                    raise ModelEmptyError(_message) from exc
                raise FactorEmptyError(_message) from exc
            raise
        logger.log_object(exp, tag="runner result")
        return exp
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _P67_RUNNING_OLD,
    _P67_RUNNING_NEW,
    "P67 route missing resumed workspace through execution-failure handling",
)

_P67_EXEC_MARKER_OLD = '''        or "qrun timed out" in lower
    )
'''
_P67_EXEC_MARKER_NEW = '''        or "qrun timed out" in lower
        or "resumed qlib workspace disappeared" in lower
        or "cannot save file into a non-existent directory" in lower
    )
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _P67_EXEC_MARKER_OLD,
    _P67_EXEC_MARKER_NEW,
    "P67 classify missing workspace as infrastructure execution failure",
)

_P67_REASON_OLD = '''    if "qrun_exit_code=124" in lower or "timed out" in lower or "running time exceeds" in lower:
        return (
            "Execution failed: the Qlib run timed out before producing a complete "
            "backtest result. Retry/repair the execution before evaluating the hypothesis."
        )
    if (
        isinstance(exc, (FactorEmptyError, ModelEmptyError))
'''
_P67_REASON_NEW = '''    if "qrun_exit_code=124" in lower or "timed out" in lower or "running time exceeds" in lower:
        return (
            "Execution failed: the Qlib run timed out before producing a complete "
            "backtest result. Retry/repair the execution before evaluating the hypothesis."
        )
    if (
        "resumed qlib workspace disappeared" in lower
        or "cannot save file into a non-existent directory" in lower
    ):
        return (
            "Execution failed: the resumed Qlib workspace was missing before runner "
            "output could be written. Retry from the coding checkpoint; the workspace "
            "will be re-materialized before the runner writes any files."
        )
    if (
        isinstance(exc, (FactorEmptyError, ModelEmptyError))
'''
patch(
    "rdagent/app/qlib_rd_loop/quant.py",
    _P67_REASON_OLD,
    _P67_REASON_NEW,
    "P67 explain missing workspace execution failure",
)

_P67_LIVE_FAILED_OLD = '''        or "failed to run this experiment" in _lower
    )
'''
_P67_LIVE_FAILED_NEW = '''        or "failed to run this experiment" in _lower
        or "cannot save file into a non-existent directory" in _lower
        or "resumed qlib workspace disappeared" in _lower
    )
'''
patch(
    "rdagent/log/server/app.py",
    _P67_LIVE_FAILED_OLD,
    _P67_LIVE_FAILED_NEW,
    "P67 expose missing-workspace crash in RESULT",
)

_P67_LIVE_REASON_OLD = '''    elif "qrun_exit_code=124" in _lower or "qrun timed out" in _lower:
        _reason = "The Qlib backtest timed out before producing a complete result."
    else:
'''
_P67_LIVE_REASON_NEW = '''    elif "qrun_exit_code=124" in _lower or "qrun timed out" in _lower:
        _reason = "The Qlib backtest timed out before producing a complete result."
    elif (
        "cannot save file into a non-existent directory" in _lower
        or "resumed qlib workspace disappeared" in _lower
    ):
        _reason = (
            "The resumed Qlib workspace directory disappeared before factor/model "
            "runner output could be written. Retry from the coding checkpoint; the "
            "workspace will be restored before the write."
        )
    else:
'''
patch(
    "rdagent/log/server/app.py",
    _P67_LIVE_REASON_OLD,
    _P67_LIVE_REASON_NEW,
    "P67 render actionable missing-workspace failure reason",
)


# ---------------------------------------------------------------- P69 recursive continuation RESULT inheritance
# P59 inherited RESULT events from only the immediate source trace. After several
# Continue/Retry/Branch generations, the immediate parent may itself rely on inherited
# RESULT rows that are not physically present in its local FileStorage. Resolve the
# ancestry recursively, while applying every checkpoint boundary and guarding cycles.
patch(
    "rdagent/log/server/app.py",
    "def _resume_parent_result_messages(trace_dir: Path):\n    import json as _json\n",
    "def _resume_parent_result_messages(\\n"
    "    trace_dir: Path,\\n"
    "    _visited: set[str] | None = None,\\n"
    "    _depth: int = 0,\\n"
    "):\\n"
    "    import json as _json\\n\\n"
    "    if _visited is None:\\n"
    "        _visited = set()\\n"
    "    if _depth >= 32:\\n"
    "        return [], {\\n"
    '            "available": False,\\n'
    '            "reason": "continuation ancestry exceeds 32 levels",\\n'
    '            "ancestry_depth": _depth,\\n'
    "        }\\n"
    "    _trace_key = str(trace_dir.resolve())\\n"
    "    if _trace_key in _visited:\\n"
    "        return [], {\\n"
    '            "available": False,\\n'
    '            "reason": "continuation ancestry cycle detected",\\n'
    '            "ancestry_depth": _depth,\\n'
    "        }\\n"
    "    _visited.add(_trace_key)\\n",
    "P69 add bounded recursive RESULT ancestry state",
)

_P69_PARENT_DIRECT_OLD = '''    parent_messages = []
    try:
        parent_messages = _collect_live_result_messages(source_dir, str(source_dir))
    except Exception:
        app.logger.exception(
            "Failed to replay source RESULT while continuing %s from %s",
            trace_dir,
            source_dir,
        )
        parent_messages = []

    # If disk compatibility replay yields nothing, use the already-loaded source task
    # as a second path. This protects older traces whose persisted Python objects are
    # only readable through the server's existing replayed UI messages.
    if not parent_messages:
        source_task = rdagent_processes.get(str(source_dir))
        if source_task is not None and isinstance(source_task.messages, list):
            parent_messages = [
                msg
                for msg in source_task.messages
                if isinstance(msg, dict)
                and msg.get("tag")
                in {
                    "research.hypothesis",
                    "feedback.metric",
                    "feedback.hypothesis_feedback",
                }
            ]

    filtered = []
'''
_P69_PARENT_DIRECT_NEW = '''    # First resolve the source trace's own inherited ancestry. Then append the
    # source trace's direct durable/live RESULT events so the nearest generation wins
    # if the same loop exists in multiple generations.
    ancestor_messages = []
    try:
        ancestor_messages, _ = _resume_parent_result_messages(
            source_dir,
            _visited,
            _depth + 1,
        )
    except Exception:
        app.logger.exception(
            "Failed to resolve RESULT ancestry for %s while continuing %s",
            source_dir,
            trace_dir,
        )
        ancestor_messages = []

    source_direct_messages = []
    try:
        source_direct_messages = _collect_live_result_messages(
            source_dir,
            str(source_dir),
        )
    except Exception:
        app.logger.exception(
            "Failed to replay source RESULT while continuing %s from %s",
            trace_dir,
            source_dir,
        )
        source_direct_messages = []

    # If disk compatibility replay yields nothing, use the already-loaded source task
    # as a second path. This protects older traces whose persisted Python objects are
    # only readable through the server's existing replayed UI messages.
    if not source_direct_messages:
        source_task = rdagent_processes.get(str(source_dir))
        if source_task is not None and isinstance(source_task.messages, list):
            source_direct_messages = [
                msg
                for msg in source_task.messages
                if isinstance(msg, dict)
                and msg.get("tag")
                in {
                    "research.hypothesis",
                    "feedback.metric",
                    "feedback.hypothesis_feedback",
                }
            ]

    parent_messages = list(ancestor_messages)
    parent_messages.extend(source_direct_messages)

    filtered = []
'''
patch(
    "rdagent/log/server/app.py",
    _P69_PARENT_DIRECT_OLD,
    _P69_PARENT_DIRECT_NEW,
    "P69 recursively merge ancestor RESULT events",
)

_P69_INFO_OLD = '''        "created_at": meta.get("created_at"),
    }


def _filter_continuation_destination_messages(messages, continuation_source):
'''
_P69_INFO_NEW = '''        "created_at": meta.get("created_at"),
        "ancestry_depth": _depth + 1,
    }


def _filter_continuation_destination_messages(messages, continuation_source):
'''
patch(
    "rdagent/log/server/app.py",
    _P69_INFO_OLD,
    _P69_INFO_NEW,
    "P69 expose RESULT ancestry depth",
)


# ---------------------------------------------------------------- P70 configurable fresh-qrun timeout
# The CPU Qlib run in the current trace reached epoch 26/30 exactly when LocalEnv's
# default 3600s timeout killed it. Keep timeouts/failure handling, but give a fresh
# scientific backtest a realistic default two-hour window. This is isolated to the
# Qlib experiment LocalEnv; factor code-generation helpers keep their existing limits.
_P70_QRUN_ENV_OLD = '''                qtde = LocalEnv(
                    conf=LocalConf(
                        default_entry="python main.py",
                        bin_path=os.environ.get("PATH", ""),
                        enable_cache=False,
                    )
                )
'''
_P70_QRUN_ENV_NEW = '''                _qrun_timeout_raw = os.environ.get(
                    "RDAGENT_QRUN_TIMEOUT_SECONDS",
                    "7200",
                ).strip()
                _qrun_timeout = (
                    None
                    if _qrun_timeout_raw.lower() in {"", "0", "none"}
                    else max(60, int(_qrun_timeout_raw))
                )
                qtde = LocalEnv(
                    conf=LocalConf(
                        default_entry="python main.py",
                        bin_path=os.environ.get("PATH", ""),
                        running_timeout_period=_qrun_timeout,
                        enable_cache=False,
                    )
                )
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _P70_QRUN_ENV_OLD,
    _P70_QRUN_ENV_NEW,
    "P70 use configurable two-hour Qlib qrun timeout",
)

_P70_FRESH_LOG_OLD = '''            f"[rd-agent] FRESH_QRUN config={qlib_config_name} "
            f"env_cache={getattr(qtde.conf, 'enable_cache', None)} "
            f"workspace={self.workspace_path}"
'''
_P70_FRESH_LOG_NEW = '''            f"[rd-agent] FRESH_QRUN config={qlib_config_name} "
            f"env_cache={getattr(qtde.conf, 'enable_cache', None)} "
            f"timeout={getattr(qtde.conf, 'running_timeout_period', None)}s "
            f"workspace={self.workspace_path}"
'''
patch(
    "rdagent/scenarios/qlib/experiment/workspace.py",
    _P70_FRESH_LOG_OLD,
    _P70_FRESH_LOG_NEW,
    "P70 log effective Qlib qrun timeout",
)

print("All rdagent patches applied.", flush=True)
