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


def _resume_failure_state(checkpoint_path: Path):
    """Load the persisted loop and extract failure text + best retry checkpoint."""
    try:
        import pickle as _pickle

        with checkpoint_path.open("rb") as _fh:
            state = _pickle.load(_fh)

        pending = getattr(state, "_execution_failure_pending", None)
        explicit_retry = getattr(state, "_execution_failure_retry_from", None)

        step_idx = getattr(state, "step_idx", {}) or {}
        loop_index = max(step_idx.keys(), default=-1)
        prev_out_all = getattr(state, "loop_prev_out", {}) or {}
        prev_out = prev_out_all.get(loop_index, {}) if loop_index >= 0 else {}
        exception_key = getattr(state, "EXCEPTION_KEY", "_EXCEPTION")
        step_exception = prev_out.get(exception_key) if isinstance(prev_out, dict) else None

        pieces = []
        if pending:
            pieces.append(pending)
        if step_exception:
            pieces.append(step_exception)

        trace = getattr(state, "trace", None)
        hist = getattr(trace, "hist", None) or []
        if hist:
            feedback = hist[-1][1]
            pieces.extend(
                [
                    getattr(feedback, "reason", None),
                    getattr(feedback, "observations", None),
                    getattr(feedback, "exception", None),
                ]
            )

        text = "\n".join(str(item) for item in pieces if item)
        lower = text.lower()

        retry_step = explicit_retry if explicit_retry in {"direct_exp_gen", "coding"} else None
        if retry_step is None and step_exception and isinstance(prev_out, dict):
            # coding=None means the coder itself failed and must be rerun from the
            # durable direct_exp_gen checkpoint. If coding exists but running did
            # not complete, reuse the code and rerun from the coding checkpoint.
            if "coding" in prev_out and prev_out.get("coding") is None:
                retry_step = "direct_exp_gen"
            elif "coding" in prev_out:
                retry_step = "coding"

        return state, text, lower, retry_step
    except Exception:
        return None, "", "", None


def _resume_execution_failure_reason(checkpoint_path: Path):
    """Best-effort classification of completed OR partial execution failures."""
    _state, text, lower, _retry_step = _resume_failure_state(checkpoint_path)
    if not text:
        return None

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
    if not (
        any(marker in lower for marker in markers)
        or ("failed to run " in lower and " model, because " in lower)
    ):
        return None

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
            "Execution failed: the generated implementation produced no valid output; "
            "retry the same loop from the last valid pre-failure checkpoint."
        )
    return "Execution failed: retry this loop from the coding checkpoint."


def _resume_execution_failure_retry_step(checkpoint_path: Path):
    """Return the durable step after which the failed work should be retried."""
    _state, _text, _lower, retry_step = _resume_failure_state(checkpoint_path)
    return retry_step or "coding"


def _resume_terminal_workspace_crash_state(trace_dir: Path):
    """Recover the failed running loop from a terminal missing-workspace traceback."""
    import re as _re

    stdout_path = trace_dir.parent / f"{trace_dir.name}.log"
    if not stdout_path.exists():
        return None
    try:
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    lower = text.lower()
    crash_marker = "[rd-agent] task process crashed:"
    crash_pos = lower.rfind(crash_marker)
    if crash_pos < 0:
        return None

    crash_tail = lower[crash_pos:]
    if not (
        "cannot save file into a non-existent directory" in crash_tail
        and "rd-agent_workspace" in crash_tail
    ):
        return None

    prefix = text[:crash_pos]
    running_matches = list(
        _re.finditer(r"Start Loop (\d+), Step 2: running", prefix)
    )
    if not running_matches:
        return None

    failed_loop = int(running_matches[-1].group(1))
    return {
        "loop_index": failed_loop,
        "loop_number": failed_loop + 1,
        "reason": (
            "Execution crashed because the resumed Qlib workspace directory was "
            "missing before parquet output could be written. Retry this loop from "
            "its coding checkpoint."
        ),
    }


def _resume_legacy_stale_qrun_state(trace_dir: Path):
    """Detect old loops whose Qlib execution was silently served from LocalEnv cache.

    P61 adds FRESH_QRUN markers and disables the cache. For traces created before P61,
    the tell-tale pattern is a running step that logs "Experiment execution ..." and
    reaches feedback without any actual qrun LocalEnv execution in between.
    """
    import re as _re

    stdout_path = trace_dir.parent / f"{trace_dir.name}.log"
    if not stdout_path.exists():
        return None

    try:
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    start_re = _re.compile(r"Start Loop (\d+), Step 2: running")
    starts = list(start_re.finditer(text))
    if not starts:
        return None

    suspicious = []
    for index, match in enumerate(starts):
        loop_index = int(match.group(1))
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        segment = text[match.start():end]

        feedback_marker = f"Start Loop {loop_index}, Step 3: feedback"
        feedback_pos = segment.find(feedback_marker)
        if feedback_pos < 0:
            continue
        segment = segment[:feedback_pos]

        if "Experiment execution ..." not in segment:
            continue

        normalized = " ".join(segment.split())
        fresh_marker = "[rd-agent] FRESH_QRUN " in segment
        local_qrun = (
            "LocalEnv Logs Begin" in segment
            and (
                " qrun " in normalized
                or " qrun conf_" in normalized
                or "qrun conf_" in normalized
            )
        )
        qrun_failure = (
            "qrun_exit_code=" in segment
            or "missing_qrun_config=" in segment
            or "Failed to run this experiment" in segment
        )

        # Explicit execution failures are handled by the existing retry logic.
        # This detector is only for silent stale-cache success.
        if not fresh_marker and not local_qrun and not qrun_failure:
            suspicious.append(loop_index)

    if not suspicious:
        return None

    first_loop = min(suspicious)
    return {
        "loop_index": first_loop,
        "loop_number": first_loop + 1,
        "reason": (
            "Legacy stale Qlib cache detected: this loop reached feedback after "
            "'Experiment execution' without launching qrun. Results from this loop "
            "and later loops are not scientifically valid and must be recomputed."
        ),
        "suspicious_loops": sorted(set(suspicious)),
    }


def _history_experiment_records():
    """Return Finance Whole Pipeline experiments newest-first with activity timestamps."""
    scenario_dir = log_folder_path / "Finance Whole Pipeline"
    if not scenario_dir.exists():
        return []

    records = []
    for trace_dir in scenario_dir.iterdir():
        if not trace_dir.is_dir():
            continue
        if trace_dir.name == "uploads":
            continue

        try:
            if next(trace_dir.rglob("*.pkl"), None) is None:
                continue
        except OSError:
            continue

        activity_mtime = 0.0
        try:
            activity_mtime = trace_dir.stat().st_mtime
        except OSError:
            pass

        stdout_path = trace_dir.parent / f"{trace_dir.name}.log"
        for activity_path in (stdout_path, trace_dir / "__session__", trace_dir / "_resume_meta.json"):
            if not activity_path.exists():
                continue
            try:
                activity_mtime = max(activity_mtime, activity_path.stat().st_mtime)
            except OSError:
                pass

        trace_id = trace_dir.relative_to(log_folder_path).as_posix()
        task = rdagent_processes.get(str(trace_dir))
        active = bool(task is not None and task.is_alive())
        updated_at = (
            datetime.fromtimestamp(activity_mtime, tz=timezone.utc).isoformat()
            if activity_mtime > 0
            else None
        )
        records.append(
            {
                "id": trace_id,
                "scenario": "Finance Whole Pipeline",
                "name": trace_dir.name,
                "timestamp": updated_at,
                "updated_at": updated_at,
                "timestamp_ms": int(activity_mtime * 1000) if activity_mtime > 0 else 0,
                "active": active,
            }
        )

    records.sort(
        key=lambda item: (item.get("timestamp_ms", 0), item.get("id", "")),
        reverse=True,
    )
    return records


@app.route("/history/experiments", methods=["GET"])
def history_experiments():
    """Structured history metadata for the Previous Experiments UI."""
    return jsonify(_history_experiment_records()), 200


@app.route("/history/experiment", methods=["DELETE"])
def delete_history_experiment():
    """Permanently delete one completed experiment's durable trace and stdout log."""
    import shutil as _shutil

    payload = request.get_json(silent=True) or {}
    trace_id = str(payload.get("id") or request.args.get("id") or "").strip()
    trace_dir = _resume_trace_dir(trace_id)
    if trace_dir is None:
        return jsonify({"error": "Invalid Finance Whole Pipeline trace ID"}), 400
    if not trace_dir.exists():
        return jsonify({"error": "Experiment not found"}), 404

    task = rdagent_processes.get(str(trace_dir))
    if task is not None and task.is_alive():
        return jsonify(
            {
                "error": (
                    "This experiment is still running. Stop or wait for it to finish "
                    "before deleting it."
                )
            }
        ), 409

    stdout_path = trace_dir.parent / f"{trace_dir.name}.log"
    removed = []
    errors = []

    try:
        _shutil.rmtree(trace_dir)
        removed.append(str(trace_dir))
    except Exception as exc:
        errors.append(f"trace directory: {exc}")

    if stdout_path.exists():
        try:
            stdout_path.unlink()
            removed.append(str(stdout_path))
        except Exception as exc:
            errors.append(f"stdout log: {exc}")

    # Drop any stale in-memory task entry after the durable files are gone.
    rdagent_processes.pop(str(trace_dir), None)

    if errors:
        return jsonify(
            {
                "error": "Experiment deletion was only partially completed.",
                "id": trace_id,
                "removed": removed,
                "details": errors,
            }
        ), 500

    return jsonify(
        {
            "deleted": True,
            "id": trace_id,
            "removed": removed,
        }
    ), 200


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
    legacy_stale_qrun = _resume_legacy_stale_qrun_state(source_dir)
    terminal_workspace_crash = _resume_terminal_workspace_crash_state(source_dir)

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
        # Detect failures from either a completed record checkpoint or the
        # latest partial checkpoint. This also recovers traces that crashed while
        # logging feedback before a record checkpoint could be written.
        failure_probe = completed or candidates[-1]
        execution_failure_reason = _resume_execution_failure_reason(
            Path(failure_probe["path"])
        )
        retry_checkpoint = None
        if execution_failure_reason:
            retry_step = _resume_execution_failure_retry_step(
                Path(failure_probe["path"])
            )
            retry_checkpoint = next(
                (
                    item
                    for item in reversed(candidates)
                    if item["step_name"] == retry_step
                ),
                None,
            )

        selected = retry_checkpoint or completed or candidates[-1]

        terminal_workspace_failed = bool(
            terminal_workspace_crash
            and loop_index == int(terminal_workspace_crash["loop_index"])
        )
        if terminal_workspace_failed:
            crash_retry = next(
                (
                    item
                    for item in reversed(candidates)
                    if item["step_name"] == "coding"
                ),
                None,
            )
            if crash_retry is not None:
                selected = crash_retry
                execution_failure_reason = terminal_workspace_crash["reason"]

        legacy_invalid = bool(
            legacy_stale_qrun
            and loop_index >= int(legacy_stale_qrun["loop_index"])
        )
        if (
            legacy_stale_qrun
            and loop_index == int(legacy_stale_qrun["loop_index"])
        ):
            legacy_retry = next(
                (
                    item
                    for item in reversed(candidates)
                    if item["step_name"] == "coding"
                ),
                None,
            )
            if legacy_retry is not None:
                selected = legacy_retry

        loop_checkpoints.append(
            {
                **selected,
                "complete": completed is not None,
                "execution_failed": bool(execution_failure_reason),
                "failure_reason": execution_failure_reason,
                "legacy_stale_qrun": legacy_invalid,
                "scientifically_valid": not legacy_invalid,
                "label": (
                    f"Loop {selected['loop_number']} · stale cached backtest · retry run"
                    if legacy_invalid
                    and loop_index == int(legacy_stale_qrun["loop_index"])
                    else (
                        f"Loop {selected['loop_number']} · invalid after stale cached backtest"
                        if legacy_invalid
                        else (
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
            "legacy_stale_qrun": legacy_stale_qrun,
            "terminal_workspace_crash": terminal_workspace_crash,
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
    auto_retry_legacy_cache = False
    auto_retry_workspace_crash = False
    legacy_stale_qrun = _resume_legacy_stale_qrun_state(source_dir)
    terminal_workspace_crash = _resume_terminal_workspace_crash_state(source_dir)

    if checkpoint_key == "latest":
        selected = records[-1]

        # P68: an unhandled running-step crash can coexist with a later speculative
        # direct_exp_gen checkpoint. Retry the actual failed loop, never that future
        # hypothesis checkpoint.
        if terminal_workspace_crash:
            failed_loop = int(terminal_workspace_crash["loop_index"])
            retry_checkpoint = next(
                (
                    item
                    for item in reversed(records)
                    if item["loop_index"] == failed_loop
                    and item["step_name"] == "coding"
                ),
                None,
            )
            if retry_checkpoint is not None:
                selected = retry_checkpoint
                auto_retry_execution = True
                auto_retry_workspace_crash = True

        # P64: traces produced before P61 can contain scientifically invalid loops
        # whose qrun was silently served from LocalEnv cache. Rewind automatically
        # to the first affected loop's coding checkpoint.
        if legacy_stale_qrun and not auto_retry_workspace_crash:
            first_bad_loop = int(legacy_stale_qrun["loop_index"])
            retry_checkpoint = next(
                (
                    item
                    for item in reversed(records)
                    if item["loop_index"] == first_bad_loop
                    and item["step_name"] == "coding"
                ),
                None,
            )
            if retry_checkpoint is not None:
                selected = retry_checkpoint
                auto_retry_execution = True
                auto_retry_legacy_cache = True

        if (
            not auto_retry_legacy_cache
            and not auto_retry_workspace_crash
            and selected["step_name"] == "record"
        ):
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

        if legacy_stale_qrun:
            first_bad_loop = int(legacy_stale_qrun["loop_index"])
            invalid_selection = (
                selected["loop_index"] > first_bad_loop
                or (
                    selected["loop_index"] == first_bad_loop
                    and selected["step_name"] not in {"direct_exp_gen", "coding"}
                )
            )
            if invalid_selection:
                return jsonify(
                    {
                        "error": (
                            f"Loop {first_bad_loop + 1} and later results were created "
                            "with the legacy stale Qlib cache and are scientifically "
                            "invalid. Resume from that loop's coding checkpoint instead."
                        ),
                        "legacy_stale_qrun": legacy_stale_qrun,
                    }
                ), 409

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
        "legacy_stale_qrun_repair": legacy_stale_qrun if auto_retry_legacy_cache else None,
        "terminal_workspace_crash_repair": (
            terminal_workspace_crash if auto_retry_workspace_crash else None
        ),
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

    # P57: do not report a successful continuation if the child process dies
    # immediately during startup. A normal fin_quant run cannot legitimately
    # finish within this short grace period.
    import time as _time
    _time.sleep(0.25)
    if task.process is not None and task.process.exitcode is not None:
        _exit_code = task.process.exitcode
        _tail = ""
        try:
            if stdout_path.exists():
                _tail = stdout_path.read_text(
                    encoding="utf-8", errors="replace"
                )[-6000:]
        except Exception:
            _tail = ""
        app.logger.error(
            "Continuation process %s exited immediately with code %s. Tail: %s",
            f"Finance Whole Pipeline/{branch_name}",
            _exit_code,
            _tail[-1500:],
        )
        return jsonify(
            {
                "error": (
                    f"Continuation process exited immediately with code {_exit_code}. "
                    "The new trace was kept for diagnosis."
                ),
                "id": f"Finance Whole Pipeline/{branch_name}",
                "exit_code": _exit_code,
                "log_tail": _tail,
            }
        ), 500

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
            "legacy_stale_qrun_repair": (
                legacy_stale_qrun if auto_retry_legacy_cache else None
            ),
            "terminal_workspace_crash_repair": (
                terminal_workspace_crash if auto_retry_workspace_crash else None
            ),
        }
    ), 200
