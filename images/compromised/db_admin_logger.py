#!/usr/bin/env python3
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


# Global variables for cleanup
_cleanup_container = None
_cleanup_agent = None
_opencode_pid = None


def cleanup_opencode_process():
    """Kill any running opencode process for this agent inside the container."""
    if not _cleanup_container:
        return
    
    try:
        # First try to kill by specific PID if we have it (most precise method)
        if _opencode_pid:
            subprocess.run(
                ["docker", "exec", _cleanup_container, "kill", "-9", str(_opencode_pid)],
                capture_output=True,
                timeout=5,
            )
        # Fallback: use more specific pattern including format to avoid killing other agents
        elif _cleanup_agent:
            # Pattern: "opencode run --agent db_admin --format json"
            # This is more specific than just the agent name to avoid collisions
            subprocess.run(
                ["docker", "exec", _cleanup_container, "pkill", "-9", "-f", f"opencode run --agent {_cleanup_agent} --format json"],
                capture_output=True,
                timeout=5,
            )
    except Exception:
        pass


def signal_handler(signum, frame):
    """Handle termination signals by cleaning up opencode processes."""
    cleanup_opencode_process()
    sys.exit(1)


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


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
        default=int(os.environ.get("OPENCODE_TIMEOUT", "86400")),
        help="Seconds to wait for OpenCode run (default: 86400 or OPENCODE_TIMEOUT).",
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
        handle.flush()  # Ensure real-time writing


def _calculate_metrics(stdout_text: str) -> dict:
    """Calculate metrics from stdout without writing to timeline (used for summary)."""
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
        except (json.JSONDecodeError, ValueError):
            if "|  Bash " in line:
                bash_commands.append(line_stripped)
                tool_calls.append("bash")
            elif final_output is None and line_stripped:
                final_output = line_stripped[:500]

    if llm_calls == 0 and bash_commands:
        llm_calls = max(1, len(bash_commands) // 2)

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
    global _cleanup_container, _cleanup_agent, _opencode_pid
    
    args = parse_args()
    _cleanup_container = args.container
    _cleanup_agent = "db_admin"
    
    goal_text = " ".join(args.goal).strip()
    if not goal_text:
        print("Error: goal is required.", file=sys.stderr)
        return 2

    display_cmd = f"docker exec -i lab_compromised opencode run --agent db_admin --format json"
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
        stdout_path = os.path.join(output_dir, "opencode_stdout.jsonl")
        stderr_path = os.path.join(output_dir, "opencode_stderr.log")
        start_time = time.time()
        
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
            "db_admin",
            "--format",
            "json",
        ]
        
        # Start the process
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered for real-time output
        )
        
        # Try to capture the PID of the opencode process inside the container
        # This is best-effort; if it fails we fall back to pkill
        try:
            pid_result = subprocess.run(
                ["docker", "exec", args.container, "pgrep", "-f", f"opencode run --agent db_admin --format json"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if pid_result.returncode == 0 and pid_result.stdout.strip():
                _opencode_pid = pid_result.stdout.strip().split()[0]  # Get first PID
        except Exception:
            pass
        
        # Send goal to stdin and close it
        proc.stdin.write(goal_text + "\n")
        proc.stdin.flush()
        proc.stdin.close()
        
        # Read stdout line by line in real-time and write to files immediately
        stdout_lines = []
        deadline = time.time() + args.timeout
        
        try:
            with open(stdout_path, "w", encoding="utf-8") as stdout_handle:
                while True:
                    if time.time() > deadline:
                        proc.kill()
                        raise subprocess.TimeoutExpired(cmd, args.timeout, output="\n".join(stdout_lines), stderr="")
                    
                    line = proc.stdout.readline()
                    if not line:
                        # Check if process has ended
                        if proc.poll() is not None:
                            break
                        continue
                    
                    stdout_lines.append(line.rstrip('\n'))
                    # Write to file immediately with flush for real-time logging
                    stdout_handle.write(line)
                    stdout_handle.flush()
                    
                    # Also process and write timeline entry in real-time
                    line_stripped = line.strip()
                    if line_stripped:
                        try:
                            event = json.loads(line_stripped)
                            event_type = event.get("type", "")
                            timeline_entry = {
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "level": "OPENCODE",
                                "msg": event_type,
                                "exec": execution_id[:8],
                                "data": event,
                            }
                        except (json.JSONDecodeError, ValueError):
                            timeline_entry = {
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "level": "OUTPUT",
                                "msg": "text_line",
                                "exec": execution_id[:8],
                                "data": {"text": line_stripped[:200]},
                            }
                        
                        with open(timeline_path, "a", encoding="utf-8") as tl_handle:
                            tl_handle.write(json.dumps(timeline_entry, separators=(",", ":")) + "\n")
            
            # Wait for process to complete and get stderr
            proc.wait()
            stderr = proc.stderr.read() if proc.stderr else ""
            stdout = "\n".join(stdout_lines)
            
            result = subprocess.CompletedProcess(
                args=cmd,
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            stderr = proc.stderr.read() if proc.stderr else ""
            raise subprocess.TimeoutExpired(cmd, args.timeout, output="\n".join(stdout_lines), stderr=stderr)
        duration = time.time() - start_time
        
        # Write stderr (stdout was already written in real-time)
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(result.stderr or "")

        # Calculate metrics from the already-processed stdout (no need to re-process timeline)
        metrics = _calculate_metrics(result.stdout or "")
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
        # Kill the opencode process inside the container to prevent zombie processes
        cleanup_opencode_process()
        
        run_id = resolve_run_id()
        output_dir = os.path.join("/home/shared/Trident/outputs", run_id, "benign_agent")
        os.makedirs(output_dir, exist_ok=True)
        timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")
        stdout_path = os.path.join(output_dir, "opencode_stdout.jsonl")
        stderr_path = os.path.join(output_dir, "opencode_stderr.log")
        
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write(exc.stdout or "")
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(exc.stderr or "")
        append_opencode_events(timeline_path, execution_id, exc.stdout or "")
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
