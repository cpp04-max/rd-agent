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

print("All rdagent patches applied.", flush=True)
