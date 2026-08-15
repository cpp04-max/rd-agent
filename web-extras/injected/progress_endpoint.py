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
