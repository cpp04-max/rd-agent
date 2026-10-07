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


def _resume_execution_failure_reason(checkpoint_path: Path):
    """Best-effort classification of a persisted loop as an execution failure.

    New P46 checkpoints carry _execution_failure_pending. Older P42/P43 record
    checkpoints can still be classified from their latest feedback text.
    """
    try:
        import pickle as _pickle

        with checkpoint_path.open("rb") as _fh:
            state = _pickle.load(_fh)

        pending = getattr(state, "_execution_failure_pending", None)
        if pending:
            return str(pending)

        trace = getattr(state, "trace", None)
        hist = getattr(trace, "hist", None) or []
        if not hist:
            return None
        feedback = hist[-1][1]
        pieces = [
            getattr(feedback, "reason", None),
            getattr(feedback, "observations", None),
            getattr(feedback, "exception", None),
        ]
        text = "\n".join(str(item) for item in pieces if item)
        lower = text.lower()
        markers = (
            "failed to run this experiment",
            "qrun_exit_code=",
            "no result file found",
            "expected output file not found",
            "all tasks are failed",
            "filenotfounderror",
            "process was killed",
            "\nkilled",
            "qrun timed out",
            "running time exceeds",
        )
        if any(marker in lower for marker in markers) or (
            "failed to run " in lower and " model, because " in lower
        ):
            if "killed" in lower or "qrun_exit_code=137" in lower or "qrun_exit_code=-9" in lower:
                return (
                    "Execution failed: Qlib was killed before producing a complete "
                    "backtest result; retry from the coding checkpoint after checking memory."
                )
            if (
                "all tasks are failed" in lower
                or "expected output file not found" in lower
                or "filenotfounderror" in lower
            ):
                return (
                    "Execution failed: the generated implementation produced no valid "
                    "output; retry this loop from the coding checkpoint."
                )
            return "Execution failed: retry this loop from the coding checkpoint."
    except Exception:
        return None
    return None


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

    # Present one intuitive checkpoint per loop for the normal UI. Prefer the
    # completed "record" checkpoint; if the loop is partial, use its latest
    # successfully persisted step and label it clearly.
    loop_map = {}
    for record in records:
        loop_map.setdefault(record["loop_index"], []).append(record)

    loop_checkpoints = []
    for loop_index in sorted(loop_map):
        candidates = loop_map[loop_index]
        completed = next(
            (item for item in candidates if item["step_name"] == "record"),
            None,
        )
        execution_failure_reason = (
            _resume_execution_failure_reason(Path(completed["path"]))
            if completed is not None
            else None
        )
        retry_checkpoint = None
        if execution_failure_reason:
            # "after coding" means the generated hypothesis/code is durable but
            # running has not yet succeeded. Resuming here reruns the SAME experiment
            # instead of asking the LLM for another hypothesis.
            retry_checkpoint = next(
                (item for item in reversed(candidates) if item["step_name"] == "coding"),
                None,
            )

        selected = retry_checkpoint or completed or candidates[-1]
        loop_checkpoints.append(
            {
                **selected,
                "complete": completed is not None,
                "execution_failed": bool(execution_failure_reason),
                "failure_reason": execution_failure_reason,
                "label": (
                    f"Loop {selected['loop_number']} · execution failed · retry run"
                    if execution_failure_reason and retry_checkpoint is not None
                    else (
                        f"Loop {selected['loop_number']} · execution failed"
                        if execution_failure_reason
                        else (
                            f"Loop {selected['loop_number']} · completed"
                            if completed is not None
                            else (
                                f"Loop {selected['loop_number']} · partial "
                                f"(after {selected['step_name']})"
                            )
                        )
                    )
                ),
            }
        )

    resume_meta = None
    meta_path = source_dir / "_resume_meta.json"
    if meta_path.exists():
        try:
            import json as _json

            resume_meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            resume_meta = None

    return jsonify(
        {
            "source_id": source_id,
            "resumable": True,
            "latest": latest,
            "loop_checkpoints": loop_checkpoints,
            "checkpoints": records,
            "resume_meta": resume_meta,
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

    auto_retry_execution = False
    if checkpoint_key == "latest":
        selected = records[-1]
        if selected["step_name"] == "record":
            execution_failure_reason = _resume_execution_failure_reason(Path(selected["path"]))
            if execution_failure_reason:
                retry_checkpoint = next(
                    (
                        item
                        for item in reversed(records)
                        if item["loop_index"] == selected["loop_index"]
                        and item["step_name"] == "coding"
                    ),
                    None,
                )
                if retry_checkpoint is not None:
                    selected = retry_checkpoint
                    auto_retry_execution = True
    else:
        selected = next((r for r in records if r["key"] == checkpoint_key), None)
        if selected is None:
            return jsonify({"error": "Requested checkpoint was not found"}), 404

    source_name = source_dir.name
    suffix = randomname.get_name()
    if checkpoint_key == "latest":
        if auto_retry_execution:
            branch_name = f"{source_name}-retry-{suffix}"
            resume_mode = "retry_execution"
        else:
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

    resume_start_loop_number = int(selected["loop_number"]) + (
        1 if selected["step_name"] == "record" else 0
    )

    meta = {
        "source_id": source_id,
        "mode": resume_mode,
        "checkpoint": selected,
        "resume_start_loop_number": resume_start_loop_number,
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
        "resume_loop_index": int(selected["loop_index"]),
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
    app.logger.warning(
        "Continuation active start: UI Loop %d (selected checkpoint %s)",
        resume_start_loop_number,
        selected["key"],
    )

    return jsonify(
        {
            "id": f"Finance Whole Pipeline/{branch_name}",
            "source_id": source_id,
            "mode": resume_mode,
            "checkpoint": selected,
            "resume_start_loop_number": resume_start_loop_number,
            "additional_loops": additional_loops,
            "all_duration": duration_hours,
        }
    ), 200
