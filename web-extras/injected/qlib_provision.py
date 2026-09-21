# Approximate size of the qlib CN 1d bundle; used only to render a rough ETA.
QLIB_CN_EXPECTED_MB = 400


def _dir_mb(path):
    import os

    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1e6


def _run_logged(cmd, target, label):
    """Run a subprocess, streaming its output live and printing a size/rate/ETA heartbeat."""
    import subprocess
    import threading
    import time

    start = time.time()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    stop = threading.Event()

    def _heartbeat():
        while not stop.wait(10):
            el = time.time() - start
            mb = _dir_mb(target)
            rate = mb / el if el > 0 else 0.0
            eta = ""
            if rate > 0.01:
                rem = max(0.0, QLIB_CN_EXPECTED_MB - mb) / rate
                eta = f", est. remaining ~{int(rem)}s"
            print(
                f"[qlib-data] {label}: elapsed {int(el)}s, ~{mb:.0f} MB on disk, "
                f"~{rate:.1f} MB/s{eta}",
                flush=True,
            )

    thr = threading.Thread(target=_heartbeat, daemon=True)
    thr.start()
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            print(f"[qlib-data]   {line}", flush=True)
    proc.wait()
    stop.set()
    thr.join(timeout=2)
    el = time.time() - start
    print(
        f"[qlib-data] {label} finished in {int(el)}s, ~{_dir_mb(target):.0f} MB on disk, "
        f"exit={proc.returncode}",
        flush=True,
    )
    return proc.returncode


def _ensure_qlib_cn_data() -> None:
    """Download qlib CN market data once (persisted on the /data volume via symlink)."""
    import os
    import sys
    from pathlib import Path

    target = Path(os.path.expanduser("~/.qlib/qlib_data/cn_data"))
    if target.exists() and any(target.iterdir()):
        n = sum(1 for p in target.rglob("*") if p.is_file())
        print(
            f"[qlib-data] cn_data already present (~{_dir_mb(target):.0f} MB, {n} files) - "
            "skipping download.",
            flush=True,
        )
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
            print("[qlib-data] cn_data already present - skipping download.", flush=True)
            return
        print(
            f"[qlib-data] downloading qlib cn_data to {target} (one-time ~"
            f"{QLIB_CN_EXPECTED_MB} MB download; live progress below) ...",
            flush=True,
        )
        rc = _run_logged(
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
            ],
            target,
            "downloading cn_data",
        )
        if rc != 0:
            raise RuntimeError(f"qlib cn_data download exited with code {rc}")
        print(f"[qlib-data] cn_data ready (~{_dir_mb(target):.0f} MB).", flush=True)
