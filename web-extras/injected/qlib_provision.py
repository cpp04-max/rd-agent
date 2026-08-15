def _ensure_qlib_cn_data() -> None:
    """Download qlib CN market data once (persisted on the /data volume via symlink)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    try:
        target = Path(os.path.expanduser("~/.qlib/qlib_data/cn_data"))
        if target.exists() and any(target.iterdir()):
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            home_qlib = Path(os.path.expanduser("~/.qlib"))
            if home_qlib.is_symlink():  # dangling symlink (no volume mounted)
                home_qlib.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
        from filelock import FileLock

        with FileLock(str(target.parent / ".cn_data.lock")):
            if target.exists() and any(target.iterdir()):
                return
            print(f"[qlib-data] downloading qlib cn_data to {target} ...", flush=True)
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "qlib.cli.data",
                    "qlib_data",
                    "--name",
                    "qlib_data",
                    "--target_dir",
                    str(target),
                    "--interval",
                    "1d",
                    "--region",
                    "cn",
                    "--exists_skip",
                ]
            )
            print("[qlib-data] cn_data ready.", flush=True)
    except Exception as e:
        print(f"[qlib-data] provisioning failed: {e}", flush=True)
