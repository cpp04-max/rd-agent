# Injected into rdagent/log/server/app.py by patch-rdagent.py.
# Provides safe, non-destructive continuation / branching of Finance Whole Pipeline traces.

def _resume_trace_dir(trace_id: str):
    normalized = str(trace_id or "").strip().strip("/")
    if not normalized:
        return None
    candidate = (log_folder_path / normalized).resolve()
    root = log_folder_path.resolve()
    try:
        if os.path.commonpath([str(candidate), str(root)]) != str(root):
            return None
    except ValueError:
        return None
    parts = candidate.relative_to(root).parts
    if len(parts) != 2 or parts[0] != "Finance Whole Pipeline":
        return None
    return candidate


def _resume_checkpoint_records(trace_dir: Path):
    records = []
    session_dir = trace_dir / "__session__"
    if not session_dir.exists():
        return records

    for file in session_dir.glob("*/*_*"):
        if not file.is_file():
            continue
        try:
            loop_index = int(file.parent.name)
            step_index_text, step_name = file.name.split("_", 1)
            step_index = int(step_index_text)
        except (ValueError, TypeError):
            continue
        records.append(
            {
                "key": f"{loop_index}/{file.name}",
                "loop_index": loop_index,
                "loop_number": loop_index + 1,
                "step_index": step_index,
                "step_name": step_name,
                "label": f"Loop {loop_index + 1} · after {step_name}",
                "path": str(file),
            }
        )
    records.sort(key=lambda x: (x["loop_index"], x["step_index"]))
    return records


@app.route("/resume/options", methods=["GET"])
def resume_options():
    source_id = request.args.get("id", "")
    source_dir = _resume_trace_dir(source_id)
    if source_dir is None:
        return jsonify({"error": "Invalid Finance Whole Pipeline trace ID"}), 400
    if not source_dir.exists():
        return jsonify({"error": "Trace not found"}), 404

    records = _resume_checkpoint_records(source_dir)
    if not records:
        return jsonify(
            {
                "source_id": source_id,
                "resumable": False,
                "checkpoints": [],
                "message": (
                    "No durable session checkpoints were found. This trace was likely "
                    "created before resume support was deployed."
                ),
            }
        ), 200

    latest = records[-1]
    return jsonify(
        {
            "source_id": source_id,
            "resumable": True,
            "latest": latest,
            "checkpoints": records,
        }
    ), 200


@app.route("/resume", methods=["POST"])
def resume_trace():
    import json as _json
    import shutil as _shutil

    payload = request.get_json(silent=True) or {}
    source_id = str(payload.get("source_id") or "").strip()
    checkpoint_key = str(payload.get("checkpoint") or "latest").strip()
    instruction = str(payload.get("instruction") or "").strip()

    try:
        additional_loops = int(payload.get("additional_loops", 3))
    except (TypeError, ValueError):
        return jsonify({"error": "additional_loops must be an integer"}), 400
    if additional_loops < 1 or additional_loops > 100:
        return jsonify({"error": "additional_loops must be between 1 and 100"}), 400

    try:
        duration_hours = float(payload.get("all_duration", 6))
    except (TypeError, ValueError):
        return jsonify({"error": "all_duration must be a number of hours"}), 400
    if duration_hours <= 0 or duration_hours > 72:
        return jsonify({"error": "all_duration must be > 0 and <= 72 hours"}), 400

    source_dir = _resume_trace_dir(source_id)
    if source_dir is None:
        return jsonify({"error": "Invalid Finance Whole Pipeline source trace"}), 400
    if not source_dir.exists():
        return jsonify({"error": "Source trace not found"}), 404

    source_task = rdagent_processes.get(str(source_dir))
    if source_task is not None and source_task.is_alive():
        return jsonify({"error": "Source run is still active; wait for it to finish before branching."}), 409

    records = _resume_checkpoint_records(source_dir)
    if not records:
        return jsonify(
            {
                "error": (
                    "This trace has no durable __session__ checkpoints. Only runs created "
                    "after resume support is deployed can be resumed safely."
                )
            }
        ), 409

    if checkpoint_key == "latest":
        selected = records[-1]
    else:
        selected = next((r for r in records if r["key"] == checkpoint_key), None)
        if selected is None:
            return jsonify({"error": "Requested checkpoint was not found"}), 404

    source_name = source_dir.name
    suffix = randomname.get_name()
    if checkpoint_key == "latest":
        branch_name = f"{source_name}-cont-{suffix}"
        resume_mode = "continue"
    else:
        branch_name = f"{source_name}-L{selected['loop_number']}-{suffix}"
        resume_mode = "branch"

    dest_dir = source_dir.parent / branch_name
    while dest_dir.exists():
        suffix = randomname.get_name()
        branch_name = f"{source_name}-resume-{suffix}"
        dest_dir = source_dir.parent / branch_name

    # Copy the source trace first. QuantRDLoop.load(..., checkout=True) will then
    # truncate this *copy* to the selected checkpoint, leaving the original untouched.
    _shutil.copytree(source_dir, dest_dir)

    checkpoint_path = dest_dir / "__session__" / str(selected["loop_index"]) / (
        f"{selected['step_index']}_{selected['step_name']}"
    )
    if not checkpoint_path.exists():
        _shutil.rmtree(dest_dir, ignore_errors=True)
        return jsonify({"error": "Copied checkpoint is missing"}), 500

    meta = {
        "source_id": source_id,
        "mode": resume_mode,
        "checkpoint": selected,
        "additional_loops": additional_loops,
        "all_duration_hours": duration_hours,
        "instruction_override": instruction or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (dest_dir / "_resume_meta.json").write_text(_json.dumps(meta, indent=2), encoding="utf-8")

    stdout_path = dest_dir.parent / f"{branch_name}.log"
    kwargs = {
        "path": str(checkpoint_path),
        "checkout": True,
        "additional_loops": additional_loops,
        "all_duration": f"{duration_hours}h",
        "resume_instruction": instruction or None,
        "base_features_path": None,
    }

    task = RDAgentTask(
        target_name="fin_quant",
        kwargs=kwargs,
        stdout_path=str(stdout_path),
        log_trace_path=str(dest_dir),
        scenario="Finance Whole Pipeline",
        trace_name=branch_name,
        ui_server_port=app.config["UI_SERVER_PORT"],
    )
    rdagent_processes[str(dest_dir)] = task
    task.start()

    app.logger.warning(
        "Resumed trace %s -> %s from %s with %d additional loops and %.2fh",
        source_id,
        f"Finance Whole Pipeline/{branch_name}",
        selected["key"],
        additional_loops,
        duration_hours,
    )

    return jsonify(
        {
            "id": f"Finance Whole Pipeline/{branch_name}",
            "source_id": source_id,
            "mode": resume_mode,
            "checkpoint": selected,
            "additional_loops": additional_loops,
            "all_duration": duration_hours,
        }
    ), 200
