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

SCENARIO - LOB feature auto-discovery + statistical market making (P15, P16)
      P15  scenarios/lob_smm/*         install new package (install_file) and wire the
                                       web dispatch / upload mapping / no-interaction set
      P16  log/ui/storage.py           render lob_chart (equity curve) + lob_metrics dict

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


def install_file(rel: str, src: str, note: str):
    """Create a brand-new file in the tree from an injected source file.

    Unlike patch() (string-replace on an existing file), this copies a whole
    file so the patcher can add modules that upstream does not ship. Empty
    files (e.g. __init__.py) skip the syntax check.
    """
    dst = ROOT / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = (INJECTED / src).read_text()
    if src.endswith(".py") and text.strip():
        ast.parse(text)
    dst.write_text(text)
    print(f"installed {rel} ({note})", flush=True)


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
for tgt in ("fin_factor", "fin_factor_report", "fin_model", "fin_quant"):
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
    "        _candidate = _trace_dir.parent / (_trace_dir.name + \".log\")\n"
    "        if _candidate.exists():\n"
    "            stdout_path = _candidate\n"
    "    if stdout_path is None:\n"
    "        return None\n"
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
# The CoSTEER model coder (General Model Implementation, and the model step of
# fin_model/fin_quant) executes generated code via MODEL_COSTEER env selection.
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
# typical sandboxes ship conda, so the interactive finance loops (fin_factor,
# fin_quant) re-ask the user for features forever. Fall back to a LocalEnv
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
# LOB feature auto-discovery + statistical market making (SMM). This scenario
# is self-contained (synthetic order-book data, no qlib / Kaggle), so upstream
# does not ship it: the patcher CREATES the package via install_file, then
# wires it into the web server dispatch, the upload-form scenario mapping and
# the no-user-interaction target set.
install_file("rdagent/scenarios/lob_smm/__init__.py", "empty_init.py", "P15 lob_smm package")
install_file("rdagent/scenarios/lob_smm/pipeline.py", "lob_pipeline.py", "P15 lob_smm pipeline")
patch(
    "rdagent/log/server/app.py",
    '_TARGETS_WITHOUT_USER_INTERACTION = {"general_model", "fin_factor_report"}',
    '_TARGETS_WITHOUT_USER_INTERACTION = {"general_model", "fin_factor_report", "lob_smm"}',
    "P15 lob_smm no user interaction",
)
patch(
    "rdagent/log/server/app.py",
    "                    else:\n"
    '                        raise ValueError(f"Unknown target: {self.target_name}")',
    '                    elif self.target_name == "lob_smm":\n'
    "                        from rdagent.scenarios.lob_smm.pipeline import main as lob_smm\n"
    "\n"
    "                        lob_smm(**self.kwargs)\n"
    "                    else:\n"
    '                        raise ValueError(f"Unknown target: {self.target_name}")',
    "P15 lob_smm dispatch branch",
)
patch(
    "rdagent/log/server/app.py",
    '    if scenario == "Data Science":\n'
    '        target_name = "data_science"\n'
    '        kwargs = {"competition": competition, "loop_n": loop_n_val, "timeout": all_duration_val}\n'
    "\n"
    "    if target_name is None:",
    '    if scenario == "Data Science":\n'
    '        target_name = "data_science"\n'
    '        kwargs = {"competition": competition, "loop_n": loop_n_val, "timeout": all_duration_val}\n'
    '    if scenario == "LOB Market Making":\n'
    '        target_name = "lob_smm"\n'
    '        kwargs = {"loops": loop_n_val}\n'
    "\n"
    "    if target_name is None:",
    "P15 lob_smm upload mapping",
)

# ---------------------------------------------------------------- P16
# Render the LOB artifacts in the dashboard: the equity-curve chart and the
# metrics dict logged by the pipeline. Inserted ahead of the generic "running"
# branch so the dedicated tags win.
patch(
    "rdagent/log/ui/storage.py",
    '        elif "running" in tag:\n'
    "            from rdagent.core.experiment import Experiment",
    '        elif "lob_chart" in tag:\n'
    "            import plotly\n"
    "\n"
    "            data = {\n"
    '                "id": id,\n'
    '                "msg": {\n'
    '                    "tag": "feedback.return_chart",\n'
    '                    "timestamp": timestamp,\n'
    '                    "loop_id": li,\n'
    '                    "content": {"chart_html": plotly.io.to_html(obj)},\n'
    "                },\n"
    "            }\n"
    '        elif "lob_metrics" in tag:\n'
    "            import json\n"
    "\n"
    "            data = {\n"
    '                "id": id,\n'
    '                "msg": {\n'
    '                    "tag": "feedback.metric",\n'
    '                    "old_tag": tag,\n'
    '                    "timestamp": timestamp,\n'
    '                    "loop_id": li,\n'
    '                    "content": {"result": json.dumps(obj)},\n'
    "                },\n"
    "            }\n"
    '        elif "running" in tag:\n'
    "            from rdagent.core.experiment import Experiment",
    "P16 lob chart + metrics storage",
)

print("All rdagent patches applied.", flush=True)
