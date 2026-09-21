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
# Harden the initial-parameter interaction (the step that was hanging at
# "Waiting for user interaction on initial parameters..."): log each request /
# response with payload keys, refuse to consume a mismatched payload as the
# instruction answer (re-ask instead), and fix the inverted feature_codes
# condition that could KeyError / mis-append the base-factor note.
patch(
    "rdagent/components/workflow/rd_loop.py",
    "            self.user_request_q.put(\n"
    "                {\n"
    '                    "user_instruction": None,\n'
    "                }\n"
    "            )\n"
    "            res_dict = self.user_response_q.get()",
    "            self.user_request_q.put(\n"
    "                {\n"
    '                    "user_instruction": None,\n'
    "                }\n"
    "            )\n"
    '            logger.info("Sent user-instruction request; blocking on the response queue...")\n'
    "            res_dict = self.user_response_q.get()",
    "P19 log instruction request",
)
patch(
    "rdagent/components/workflow/rd_loop.py",
    '            logger.info("Received user instruction response.")\n'
    "            self.plan.update(res_dict)\n"
    "\n"
    '            if "feature_codes" not in self.plan:\n'
    "                self.plan[\n"
    '                    "user_instruction"\n'
    "                ] += f\"\\n\\n{str(list(self.plan['feature_codes'].keys()))} has been configured as the base factor; do not generate duplicate factors.\"",
    "            logger.info(\n"
    '                "Received user instruction response with keys="\n'
    "                f\"{sorted(res_dict) if isinstance(res_dict, dict) else type(res_dict).__name__}.\"\n"
    "            )\n"
    '            if not isinstance(res_dict, dict) or "user_instruction" not in res_dict:\n'
    "                logger.warning(\n"
    '                    "Unexpected initial-parameter payload; re-requesting user instruction."\n'
    "                )\n"
    '                self.user_request_q.put({"user_instruction": None})\n'
    "                res_dict = self.user_response_q.get()\n"
    "            if isinstance(res_dict, dict):\n"
    "                self.plan.update(res_dict)\n"
    "            if self.plan.get(\"feature_codes\"):\n"
    '                self.plan["user_instruction"] = str(\n'
    '                    self.plan.get("user_instruction", "")\n'
    "                ) + f\"\\n\\n{str(list(self.plan['feature_codes'].keys()))} has been configured as the base factor; do not generate duplicate factors.\"",
    "P19 robust instruction response handling",
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

print("All rdagent patches applied.", flush=True)
