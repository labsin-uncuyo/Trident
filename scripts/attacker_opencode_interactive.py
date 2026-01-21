#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OpenCode for coder56 in lab_compromised and log outputs."
    )
    parser.add_argument("goal", nargs="+", help="Goal text to send into the TUI.")
    parser.add_argument(
        "--container",
        default=os.environ.get("ATTACKER_CONTAINER", "lab_compromised"),
        help="Target container name (default: lab_compromised).",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("ATTACKER_USER", "labuser"),
        help="User to run OpenCode as inside the container (default: labuser).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("OPENCODE_TIMEOUT", "600")),
        help="Seconds to wait for OpenCode run (default: 600 or OPENCODE_TIMEOUT).",
    )
    return parser.parse_args()


def resolve_run_id() -> str:
    run_id = os.environ.get("RUN_ID", "").strip()
    if run_id:
        return run_id
    current_run = os.path.join("outputs", ".current_run")
    try:
        with open(current_run, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return "manual"


def write_timeline_entry(path: str, level: str, message: str, data: Optional[dict] = None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "msg": message,
    }
    if data:
        entry["data"] = data
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")


def append_opencode_events(timeline_path: str, execution_id: str, stdout_text: str) -> dict:
    tool_calls = []
    llm_calls = 0
    final_output = None
    errors = []
    text_outputs = []

    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            if final_output is None:
                final_output = line[:500]
            continue

        event_type = event.get("type", "")
        if event_type == "step_start":
            llm_calls += 1
        elif event_type == "tool_use":
            part = event.get("part", {})
            tool_calls.append(part.get("tool", "unknown"))
        elif event_type == "text":
            part = event.get("part", {})
            text_content = part.get("text", "")
            if text_content:
                text_outputs.append(text_content)
        elif event_type.lower() == "error":
            errors.append(str(event))

        timeline_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "OPENCODE",
            "msg": event_type,
            "exec": execution_id[:8],
            "data": event,
        }
        with open(timeline_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(timeline_entry, separators=(",", ":")) + "\n")

    if not final_output and text_outputs:
        final_output = " ".join(text_outputs)[-500:]

    return {
        "final_output": final_output,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "errors": errors,
    }


def main() -> int:
    args = parse_args()
    goal_text = " ".join(args.goal).strip()
    if not goal_text:
        print("Error: goal is required.", file=sys.stderr)
        return 2

    cmd = [
        "docker",
        "exec",
        "-i",
        "--user",
        args.user,
        args.container,
        "opencode",
        "run",
        "--agent",
        "coder56",
        "--",
        goal_text,
    ]
    display_cmd = "docker exec -it lab_compromised opencode --agent coder56"
    print(f"[coder56_tui] Starting: {display_cmd}")
    execution_id = uuid4().hex
    try:
        print("[coder56_tui] TUI ready, sending goal...")

        run_id = resolve_run_id()
        output_dir = os.path.join("outputs", run_id, "coder56")
        os.makedirs(output_dir, exist_ok=True)
        timeline_path = os.path.join(output_dir, "auto_responder_timeline.jsonl")

        write_timeline_entry(timeline_path, "INIT", "coder56 execution started", data={
            "goal": goal_text,
            "container": args.container,
            "exec": execution_id[:8],
        })
        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        duration = time.time() - start_time

        stdout_path = os.path.join(output_dir, "opencode_stdout.jsonl")
        stderr_path = os.path.join(output_dir, "opencode_stderr.log")
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write(result.stdout or "")
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(result.stderr or "")

        metrics = append_opencode_events(timeline_path, execution_id, result.stdout or "")
        write_timeline_entry(timeline_path, "EXEC", "coder56 execution completed", data={
            "exit_code": result.returncode,
            "duration_seconds": round(duration, 2),
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "output": metrics.get("final_output"),
            "llm_calls": metrics.get("llm_calls"),
            "tool_calls": metrics.get("tool_calls"),
            "unique_tools": len(set(metrics.get("tool_calls", []))),
            "errors": metrics.get("errors") or None,
            "exec": execution_id[:8],
        })

        if result.returncode != 0:
            write_timeline_entry(timeline_path, "ERROR", "coder56 execution failed", data={
                "exit_code": result.returncode,
                "exec": execution_id[:8],
            })

        print("[coder56_tui] Completed.")
        return 0
    except subprocess.TimeoutExpired as exc:
        run_id = resolve_run_id()
        output_dir = os.path.join("outputs", run_id, "coder56")
        os.makedirs(output_dir, exist_ok=True)
        timeline_path = os.path.join(output_dir, "auto_responder_timeline.jsonl")
        stdout_path = os.path.join(output_dir, "opencode_stdout.jsonl")
        stderr_path = os.path.join(output_dir, "opencode_stderr.log")
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write(exc.stdout or "")
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(exc.stderr or "")
        append_opencode_events(timeline_path, execution_id, exc.stdout or "")
        write_timeline_entry(timeline_path, "ERROR", "coder56 execution timed out", data={
            "timeout_seconds": args.timeout,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "exec": execution_id[:8],
        })
        print("[coder56_tui] Completed.")
        return 0
    except Exception as exc:
        run_id = resolve_run_id()
        output_dir = os.path.join("outputs", run_id, "coder56")
        os.makedirs(output_dir, exist_ok=True)
        timeline_path = os.path.join(output_dir, "auto_responder_timeline.jsonl")
        write_timeline_entry(timeline_path, "ERROR", "coder56 execution exception", data={
            "error": str(exc),
            "exec": execution_id[:8],
        })
        print("[coder56_tui] Completed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
