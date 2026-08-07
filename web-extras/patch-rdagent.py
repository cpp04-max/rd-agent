"""Build-time patches so the finance (qlib) scenarios run inside this web container.

Upstream RD-Agent assumes it runs inside a conda environment (and Docker for the
factor source-data generation). This container is plain CPython, so without these
patches every finance scenario crashes during scenario construction -- the dashboard
then shows: "No hypothesis generated due to some errors happened in previous steps."

Patches (all strict-match; build fails loudly if upstream drifts):
  P1 factor_coder/config.py        get_factor_env: conda -> local fallback
  P2 model_coder/conf.py           get_model_env:  conda -> local fallback
  P3 qlib/experiment/workspace.py  QlibFBWorkspace.execute: conda -> local fallback
  P4 qlib/experiment/utils.py      generate_data_folder_from_qlib: docker -> local env
  P5 factor_data_template/generate.py: limit universe (memory) via RDAGENT_QLIB_UNIVERSE
  P6 log/server/app.py             provision qlib cn_data once before fin_* scenarios run
  P7 shared/get_runtime_info.py    do not crash when the env probe returns no JSON

LocalConf note: LocalEnv builds the subprocess PATH from conf.bin_path plus
/bin:/usr/bin only. In python:3.10-slim the python/qrun binaries live in
/usr/local/bin, so bin_path must carry the container PATH or every spawned
`python ...` fails with "No such file or directory".
"""
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
    '_TARGETS_WITHOUT_USER_INTERACTION = {"general_model", "fin_factor_report"}\n'
    "\n"
    "\n"
    "def _ensure_qlib_cn_data() -> None:\n"
    '    """Download qlib CN market data once (persisted on the /data volume via symlink)."""\n'
    "    import os\n"
    "    import subprocess\n"
    "    import sys\n"
    "    from pathlib import Path\n"
    "\n"
    "    try:\n"
    "        target = Path(os.path.expanduser(\"~/.qlib/qlib_data/cn_data\"))\n"
    "        if target.exists() and any(target.iterdir()):\n"
    "            return\n"
    "        try:\n"
    "            target.parent.mkdir(parents=True, exist_ok=True)\n"
    "        except OSError:\n"
    "            home_qlib = Path(os.path.expanduser(\"~/.qlib\"))\n"
    "            if home_qlib.is_symlink():  # dangling symlink (no volume mounted)\n"
    "                home_qlib.unlink()\n"
    "            target.parent.mkdir(parents=True, exist_ok=True)\n"
    "        from filelock import FileLock\n"
    "\n"
    "        with FileLock(str(target.parent / \".cn_data.lock\")):\n"
    "            if target.exists() and any(target.iterdir()):\n"
    "                return\n"
    "            print(f\"[qlib-data] downloading qlib cn_data to {target} ...\", flush=True)\n"
    "            subprocess.check_call(\n"
    "                [\n"
    "                    sys.executable,\n"
    "                    \"-m\",\n"
    "                    \"qlib.cli.data\",\n"
    "                    \"qlib_data\",\n"
    "                    \"--name\",\n"
    "                    \"qlib_data\",\n"
    "                    \"--target_dir\",\n"
    "                    str(target),\n"
    "                    \"--interval\",\n"
    "                    \"1d\",\n"
    "                    \"--region\",\n"
    "                    \"cn\",\n"
    "                    \"--exists_skip\",\n"
    "                ]\n"
    "            )\n"
    "            print(\"[qlib-data] cn_data ready.\", flush=True)\n"
    "    except Exception as e:\n"
    "        print(f\"[qlib-data] provisioning failed: {e}\", flush=True)",
    "P6 helper",
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
    '''@app.route("/progress", methods=["GET"])
def progress_tail():
    """Live stdout tail powering the dashboard's 'thinking flow' panel."""
    trace_id = request.args.get("id", "")
    try:
        offset = max(0, int(request.args.get("offset", "0")))
    except ValueError:
        offset = 0
    normalized_trace_id = str(trace_id or "").strip()
    task = (
        rdagent_processes.get(str(log_folder_path / normalized_trace_id))
        if normalized_trace_id
        else None
    )
    alive = bool(task is not None and task.is_alive())
    stdout_path = _resolve_stdout_path(trace_id)
    if stdout_path is None or not stdout_path.exists() or not stdout_path.is_file():
        return jsonify({"text": "", "offset": offset, "size": 0, "alive": alive})
    try:
        size = stdout_path.stat().st_size
    except OSError:
        return jsonify({"text": "", "offset": offset, "size": 0, "alive": alive})
    if offset > size:
        offset = 0
    max_bytes = 200_000
    if size - offset > max_bytes:
        offset = size - max_bytes
    try:
        with open(stdout_path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return jsonify({"text": "", "offset": offset, "size": size, "alive": alive})
    return jsonify(
        {
            "text": chunk.decode("utf-8", errors="replace"),
            "offset": offset + len(chunk),
            "size": size,
            "alive": alive,
        }
    )


@app.route("/traces", methods=["GET"])''',
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

print("All rdagent patches applied.", flush=True)
