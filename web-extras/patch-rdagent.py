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
# Never start a loop the remaining timer cannot finish. Previously a new loop began
# with e.g. 41 min left, ran past the budget and died mid-step, so the run ended with
# an incomplete final loop and the dashboard showed no usable result for it. Now the
# loop terminates cleanly at the boundary (results of completed loops are kept and the
# server logs END). Tunable via RDAGENT_MIN_LOOP_SECONDS (default 3600).
_LOOPGUARD_OLD = '            else:\n                logger.info(f"Timer remaining time: {self.timer.remain_time()}")\n'
_LOOPGUARD_NEW = '            else:\n                logger.info(f"Timer remaining time: {self.timer.remain_time()}")\n                # Don\'t start a loop we cannot finish: beginning a new loop with\n                # less than RDAGENT_MIN_LOOP_SECONDS left guarantees a doomed loop\n                # whose partial work is discarded and which ends mid-step, leaving the\n                # dashboard with an incomplete run and no usable result.\n                _min_loop_s = int(os.environ.get("RDAGENT_MIN_LOOP_SECONDS", "3600"))\n                if (\n                    loop_id is not None\n                    and step_id == 0\n                    and loop_id > 0\n                    and self.timer.remain_time().total_seconds() < _min_loop_s\n                ):\n                    logger.warning(\n                        f"Only {self.timer.remain_time()} left (< {_min_loop_s}s); not "\n                        "starting another loop - finishing with the completed loops."\n                    )\n                    raise self.LoopTerminationError("Insufficient time for another loop")\n'
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

print("All rdagent patches applied.", flush=True)
