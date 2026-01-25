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
        description="Run OpenCode for db_admin benign agent and log outputs."
    )
    parser.add_argument("goal", nargs="+", help="Goal text to send to the agent.")
    parser.add_argument(
        "--container",
        default=os.environ.get("BENIGN_CONTAINER", "lab_compromised"),
        help="Target container name (default: lab_compromised).",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("BENIGN_USER", "labuser"),
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
    current_run = os.path.join("/home/shared/Trident/outputs", ".current_run")
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
    bash_commands = []

    for line in stdout_text.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        # Try to parse as JSON first (for --format json output)
        try:
            event = json.loads(line_stripped)
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
        except (json.JSONDecodeError, ValueError):
            # Not JSON, handle as formatted output
            # Detect tool usage patterns in formatted output
            if "|  Bash " in line:
                bash_commands.append(line_stripped)
                tool_calls.append("bash")
            elif final_output is None and line_stripped:
                # Capture first significant non-JSON line as output
                final_output = line_stripped[:500]
            
            # Still log non-JSON lines to timeline
            timeline_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "OUTPUT",
                "msg": "text_line",
                "exec": execution_id[:8],
                "data": {"text": line_stripped[:200]},  # Limit line length
            }
            with open(timeline_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(timeline_entry, separators=(",", ":")) + "\n")

    # Estimate LLM calls from bash commands if not captured from JSON
    if llm_calls == 0 and bash_commands:
        llm_calls = max(1, len(bash_commands) // 2)  # Rough estimate

    if not final_output and text_outputs:
        final_output = " ".join(text_outputs)[-500:]
    elif not final_output and stdout_text:
        final_output = stdout_text[:500]

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
        "--user",
        args.user,
        args.container,
        "opencode",
        "run",
        "--agent",
        "db_admin",
        "--",
        goal_text,
    ]
    display_cmd = f"docker exec -it {args.container} opencode --agent db_admin"
    print(f"[db_admin] Starting: {display_cmd}")
    execution_id = uuid4().hex
    try:
        print("[db_admin] Agent ready, sending goal...")

        run_id = resolve_run_id()
        output_dir = os.path.join("/home/shared/Trident/outputs", run_id, "benign_agent")
        os.makedirs(output_dir, exist_ok=True)
        timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")

        write_timeline_entry(timeline_path, "INIT", "db_admin execution started", data={
            "goal": goal_text,
            "container": args.container,
            "exec": execution_id[:8],
        })
        start_time = time.time()
        result = subprocess.run(
            cmd,
            input="",  # Provide empty stdin to prevent hanging
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        duration = time.time() - start_time

        # Raw output capture
        stdout_path = os.path.join(output_dir, "opencode_stdout.jsonl")
        stderr_path = os.path.join(output_dir, "opencode_stderr.log")
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write(result.stdout or "")
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(result.stderr or "")

        # Event processing and timeline logging
        metrics = append_opencode_events(timeline_path, execution_id, result.stdout or "")
        write_timeline_entry(timeline_path, "EXEC", "db_admin execution completed", data={
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
            write_timeline_entry(timeline_path, "ERROR", "db_admin execution failed", data={
                "exit_code": result.returncode,
                "exec": execution_id[:8],
            })

        print("[db_admin] Completed.")
        return 0
    except subprocess.TimeoutExpired as exc:
        run_id = resolve_run_id()
        output_dir = os.path.join("/home/shared/Trident/outputs", run_id, "benign_agent")
        os.makedirs(output_dir, exist_ok=True)
        timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")
        stdout_path = os.path.join(output_dir, "opencode_stdout.jsonl")
        stderr_path = os.path.join(output_dir, "opencode_stderr.log")
        
        # Handle both str and bytes output
        stdout_text = exc.stdout.decode("utf-8") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr_text = exc.stderr.decode("utf-8") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write(stdout_text)
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(stderr_text)
        append_opencode_events(timeline_path, execution_id, stdout_text)
        write_timeline_entry(timeline_path, "ERROR", "db_admin execution timed out", data={
            "timeout_seconds": args.timeout,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "exec": execution_id[:8],
        })
        print("[db_admin] Completed.")
        return 0
    except Exception as exc:
        run_id = resolve_run_id()
        output_dir = os.path.join("/home/shared/Trident/outputs", run_id, "benign_agent")
        os.makedirs(output_dir, exist_ok=True)
        timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")
        write_timeline_entry(timeline_path, "ERROR", "db_admin execution exception", data={
            "error": str(exc),
            "exec": execution_id[:8],
        })
        print("[db_admin] Completed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
