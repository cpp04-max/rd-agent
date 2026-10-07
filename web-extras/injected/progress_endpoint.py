def _infer_alive(stdout_path):
    """Liveness without the in-memory task registry (other worker / restart)."""
    import time

    if stdout_path is None:
        return False
    if not stdout_path.exists():
        parent = stdout_path.parent
        try:
            return (time.time() - parent.stat().st_mtime) < 120
        except OSError:
            return False
    try:
        return (time.time() - stdout_path.stat().st_mtime) < 45
    except OSError:
        return False


def _progress_resume_meta(trace_id, task=None):
    """Return cheap UI seed data for a continued/branched trace."""
    import json

    normalized = str(trace_id or "").strip().strip("/")
    if not normalized:
        return {}

    meta = None
    if task is not None:
        meta = getattr(task, "_progress_resume_meta_cache", None)

    if not isinstance(meta, dict):
        meta_path = log_folder_path / normalized / "_resume_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        else:
            meta = {}
        if task is not None:
            task._progress_resume_meta_cache = meta

    if not meta:
        return {}

    checkpoint = meta.get("checkpoint") if isinstance(meta.get("checkpoint"), dict) else {}
    try:
        selected_loop_number = int(checkpoint.get("loop_number") or 0)
    except (TypeError, ValueError):
        selected_loop_number = 0
    try:
        selected_step_index = int(checkpoint.get("step_index"))
    except (TypeError, ValueError):
        selected_step_index = -1
    selected_step_name = str(checkpoint.get("step_name") or "")

    try:
        start_loop_number = int(meta.get("resume_start_loop_number") or 0)
    except (TypeError, ValueError):
        start_loop_number = 0
    if start_loop_number <= 0:
        start_loop_number = selected_loop_number or 1

    # If we resume the selected partial loop, continue with the next step after
    # its persisted checkpoint. If the selected loop was complete, the active
    # loop is the next one and starts at direct_exp_gen.
    if selected_loop_number and start_loop_number == selected_loop_number:
        start_step_index = max(0, selected_step_index + 1)
    else:
        start_step_index = 0

    stages = ["direct_exp_gen", "coding", "running", "feedback", "record"]
    if start_step_index >= len(stages):
        start_step_index = 0
    start_step_name = stages[start_step_index]

    try:
        additional_loops = int(meta.get("additional_loops") or 0)
    except (TypeError, ValueError):
        additional_loops = 0

    is_partial = bool(selected_loop_number and start_loop_number == selected_loop_number)
    if additional_loops > 0:
        # Partial selected loop is finished first, then N genuinely new loops.
        total_loop_number = start_loop_number + additional_loops if is_partial else start_loop_number + additional_loops - 1
    else:
        total_loop_number = start_loop_number

    return {
        "resume_start_loop_number": start_loop_number,
        "resume_start_step_index": start_step_index,
        "resume_start_step_name": start_step_name,
        "resume_selected_loop_number": selected_loop_number or None,
        "resume_selected_step_name": selected_step_name or None,
        "resume_additional_loops": additional_loops,
        "resume_total_loop_number": max(start_loop_number, total_loop_number),
    }


@app.route("/progress", methods=["GET"])
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
    stdout_path = _resolve_stdout_path(trace_id)
    resume_meta = _progress_resume_meta(trace_id, task=task)
    if task is not None:
        alive = bool(task.is_alive())
    else:
        # Registry miss (request served by another worker, or the server
        # restarted): infer liveness from stdout/trace-dir freshness instead of
        # wrongly reporting a running run as finished.
        alive = _infer_alive(stdout_path)
    if stdout_path is None or not stdout_path.exists() or not stdout_path.is_file():
        return jsonify({"text": "", "offset": offset, "size": 0, "alive": alive, **resume_meta})
    try:
        size = stdout_path.stat().st_size
    except OSError:
        return jsonify({"text": "", "offset": offset, "size": 0, "alive": alive, **resume_meta})
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
        return jsonify({"text": "", "offset": offset, "size": size, "alive": alive, **resume_meta})
    return jsonify(
        {
            "text": chunk.decode("utf-8", errors="replace"),
            "offset": offset + len(chunk),
            "size": size,
            "alive": alive,
            **resume_meta,
        }
    )
