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

HAS_PEXPECT = False
try:
    import pexpect
    HAS_PEXPECT = True
except Exception:
    HAS_PEXPECT = False


def ensure_pexpect() -> bool:
    global HAS_PEXPECT, pexpect
    if HAS_PEXPECT:
        return True
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pexpect"])
        import pexpect  # type: ignore
        HAS_PEXPECT = True
        return True
    except Exception:
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OpenCode for coder56 in lab_compromised and log outputs."
    )
    parser.add_argument("goal", nargs="+", help="Goal text to send into the TUI.")
    parser.add_argument(
        "--mode",
        choices=["run", "tui"],
        default=os.environ.get("OPENCODE_MODE", "run"),
        help="Execution mode: 'run' uses opencode run with stdin; 'tui' uses interactive TUI (default: run or OPENCODE_MODE).",
    )
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
    parser.add_argument(
        "--tui-ready-regex",
        default=os.environ.get("OPENCODE_TUI_READY_REGEX", "Ask anything"),
        help="Regex to detect TUI readiness (default: 'Ask anything').",
    )
    parser.add_argument(
        "--tui-idle-timeout",
        type=int,
        default=int(os.environ.get("OPENCODE_TUI_IDLE_TIMEOUT", "10")),
        help="Seconds of idle output before assuming completion in TUI mode (default: 10).",
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

    if args.mode == "tui":
        display_cmd = f"docker exec -it --user {args.user} {args.container} opencode --agent coder56"
    else:
        display_cmd = (
            f"docker exec -i --user {args.user} {args.container} "
            "opencode run --agent coder56 --format json"
        )
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
        stdout_path = os.path.join(output_dir, "opencode_stdout.jsonl")
        stderr_path = os.path.join(output_dir, "opencode_stderr.log")
        start_time = time.time()

        exit_code = 0
        if args.mode == "tui":
            if not ensure_pexpect():
                print("[coder56_tui] ERROR: pexpect not available; install it or use --mode run.", file=sys.stderr)
                return 1
            cmd = f"docker exec -it --user {args.user} {args.container} opencode --agent coder56"
            child = pexpect.spawn(cmd, encoding="utf-8", timeout=args.timeout)
            try:
                with open(stdout_path, "w", encoding="utf-8") as out_handle, \
                    open(stderr_path, "w", encoding="utf-8") as err_handle:
                    child.logfile_read = out_handle
                    # Wait for initial prompt
                    child.expect(args.tui_ready_regex, timeout=30)
                    child.sendline(goal_text)
                    # Read output until prompt returns, idle timeout, or overall timeout.
                    overall_start = time.time()
                    while (time.time() - overall_start) < args.timeout:
                        try:
                            child.expect(args.tui_ready_regex, timeout=args.tui_idle_timeout)
                            break
                        except pexpect.exceptions.TIMEOUT:
                            break
                    if child.isalive():
                        child.sendline("/exit")
                        time.sleep(2)
                    if child.isalive():
                        child.terminate(force=True)
                duration = time.time() - start_time
                metrics = {
                    "final_output": None,
                    "llm_calls": 0,
                    "tool_calls": [],
                    "errors": None,
                }
            except pexpect.exceptions.TIMEOUT:
                if child.isalive():
                    child.terminate(force=True)
                duration = time.time() - start_time
                with open(stderr_path, "a", encoding="utf-8") as err_handle:
                    err_handle.write("TUI mode timeout waiting for prompt.\n")
                metrics = {
                    "final_output": None,
                    "llm_calls": 0,
                    "tool_calls": [],
                    "errors": ["tui_timeout"],
                }
                exit_code = 124
        else:
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
                "--format",
                "json",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                input=goal_text + "\n",
                timeout=args.timeout,
            )
            duration = time.time() - start_time
            exit_code = result.returncode
            with open(stdout_path, "w", encoding="utf-8") as handle:
                handle.write(result.stdout or "")
            with open(stderr_path, "w", encoding="utf-8") as handle:
                handle.write(result.stderr or "")
            metrics = append_opencode_events(timeline_path, execution_id, result.stdout or "")
        write_timeline_entry(timeline_path, "EXEC", "coder56 execution completed", data={
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "output": metrics.get("final_output"),
            "llm_calls": metrics.get("llm_calls"),
            "tool_calls": metrics.get("tool_calls"),
            "unique_tools": len(set(metrics.get("tool_calls", []))),
            "errors": metrics.get("errors") or None,
            "session_id": metrics.get("session_id"),
            "export_path": metrics.get("export_path"),
            "exec": execution_id[:8],
        })

        if args.mode == "run" and result.returncode != 0:
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
