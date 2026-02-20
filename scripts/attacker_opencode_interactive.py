#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from uuid import uuid4
import re
import hashlib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OpenCode for coder56 in lab_compromised and log outputs."
    )
    parser.add_argument("goal", nargs="+", help="Goal text to send into the agent.")
    parser.add_argument(
        "--container",
        default=os.environ.get("ATTACKER_CONTAINER", "lab_compromised"),
        help="Target container name (default: lab_compromised).",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("ATTACKER_USER", "normal_user"),
        help="User to run OpenCode as inside the container (default: labuser).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("OPENCODE_TIMEOUT", "600")),
        help="Seconds to wait for execution (default: 600 or OPENCODE_TIMEOUT).",
    )
    parser.add_argument(
        "--server-url",
        default=os.environ.get("ATTACKER_OPENCODE_URL", "").strip(),
        help="OpenCode server base URL, e.g. http://172.30.0.10:4096 (default: derive from container IP).",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=int(os.environ.get("OPENCODE_SERVER_PORT", "4096")),
        help="OpenCode server port when deriving URL from container IP (default: 4096).",
    )
    parser.add_argument(
        "--status-poll-interval",
        type=float,
        default=float(os.environ.get("OPENCODE_STATUS_POLL_INTERVAL", "2")),
        help="Polling interval in seconds for server mode (default: 2).",
    )
    parser.add_argument(
        "--stall-timeout",
        type=int,
        default=int(os.environ.get("OPENCODE_STALL_TIMEOUT", "0")),
        help="Abort server-mode wait if the session 'updated' timestamp stops changing for N seconds (0 disables; default: 0).",
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
    tool_calls: List[str] = []
    llm_calls = 0
    final_output = None
    errors: List[str] = []
    text_outputs: List[str] = []

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


def _safe_fetch_messages(base_url: str, session_id: Optional[str]) -> List[dict]:
    if not session_id:
        return []
    try:
        fetched = _http_json("GET", f"{base_url}/session/{session_id}/message", timeout=30)
        return fetched if isinstance(fetched, list) else []
    except Exception:
        return []


def _persist_messages(output_dir: str, execution_id: str, messages: List[dict]) -> dict:
    if not messages:
        return {
            "tool_commands_path": None,
            "tool_commands_count": 0,
            "export_path": None,
        }
    commands = _collect_tool_commands_from_messages(messages, execution_id)
    tool_commands_path = None
    if commands:
        tool_commands_path = _write_tool_commands(output_dir, execution_id, commands)

    api_path = os.path.join(output_dir, f"opencode_api_messages_{execution_id[:8]}.json")
    with open(api_path, "w", encoding="utf-8") as handle:
        json.dump(messages, handle, ensure_ascii=True, indent=2)
    shutil.copyfile(api_path, os.path.join(output_dir, "opencode_api_messages.json"))

    return {
        "tool_commands_path": tool_commands_path,
        "tool_commands_count": len(commands),
        "export_path": api_path,
    }


def _persist_stdout_from_messages(output_dir: str, execution_id: str, messages: List[dict], stdout_path: str) -> dict:
    if not messages:
        return {}
    events = _messages_to_stdout_events(messages)
    with open(stdout_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    return append_opencode_events(
        timeline_path=os.path.join(output_dir, "auto_responder_timeline.jsonl"),
        execution_id=execution_id,
        stdout_text="\n".join(json.dumps(e, separators=(",", ":")) for e in events),
    )


def _http_json(method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Any:
    payload = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    req = Request(url=url, data=payload, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
        return json.loads(text) if text else None


_RE_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_RE_SK = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
_RE_PGPASSWORD = re.compile(r"\bPGPASSWORD=([^\\s]+)")


def _redact_command(cmd: str) -> str:
    """
    Redact sensitive tokens and lab IPs/credentials from live logs.
    This keeps observability without turning logs into a copy-pastable attack recipe.
    """
    if not isinstance(cmd, str):
        return ""
    s = cmd
    s = _RE_PGPASSWORD.sub("PGPASSWORD=<REDACTED>", s)
    s = _RE_SK.sub("sk-<REDACTED>", s)
    s = _RE_IPV4.sub("<IP>", s)
    # Common password patterns
    s = s.replace("normalpass", "<REDACTED>")
    return s


def _hash_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:16]


def _container_ip(container: str) -> str:
    cmd = [
        "docker",
        "inspect",
        "-f",
        "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        container,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    ip = (result.stdout or "").strip()
    if not ip:
        raise RuntimeError(f"Could not determine IP for container '{container}'")
    return ip


def _derive_server_url(args: argparse.Namespace) -> str:
    if args.server_url:
        return args.server_url.rstrip("/")
    ip = _container_ip(args.container)
    return f"http://{ip}:{args.server_port}"


def _write_compat_logs(output_dir: str, stdout_path: str, stderr_path: str) -> None:
    if not os.path.exists(stdout_path):
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write("")
    if not os.path.exists(stderr_path):
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write("")
    shutil.copyfile(stdout_path, os.path.join(output_dir, "opencode_stdout.jsonl"))
    shutil.copyfile(stderr_path, os.path.join(output_dir, "opencode_stderr.log"))


def _extract_tool_command(part: Dict[str, Any], execution_id: str) -> Optional[Dict[str, Any]]:
    if not isinstance(part, dict):
        return None
    if part.get("type") != "tool":
        return None
    st = part.get("state") or {}
    inp = st.get("input") or {}
    cmd = inp.get("command") if isinstance(inp, dict) else None
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    md = st.get("metadata") or {}
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "exec": execution_id[:8],
        "tool": part.get("tool"),
        "status": st.get("status"),
        "title": inp.get("title") or inp.get("description"),
        "command": cmd,
        "working_dir": inp.get("working_dir") or inp.get("cwd"),
        "exit": md.get("exit") if isinstance(md, dict) else None,
        "source": "message",
    }


def _collect_tool_commands_from_messages(messages: List[Dict[str, Any]], execution_id: str) -> List[Dict[str, Any]]:
    commands: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        for part in (msg.get("parts") or []):
            if not isinstance(part, dict):
                continue
            cmd = _extract_tool_command(part, execution_id)
            if cmd:
                commands.append(cmd)
    return commands


def _collect_tool_commands_from_stdout(stdout_text: str, execution_id: str) -> List[Dict[str, Any]]:
    commands: List[Dict[str, Any]] = []
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        # Normalize into the same schema as message parts.
        if part.get("type") != "tool":
            part = dict(part)
            part["type"] = "tool"
        cmd = _extract_tool_command(part, execution_id)
        if cmd:
            cmd["source"] = "stdout"
            commands.append(cmd)
    return commands


def _write_tool_commands(output_dir: str, execution_id: str, commands: List[Dict[str, Any]]) -> str:
    path = os.path.join(output_dir, f"opencode_tool_commands_{execution_id[:8]}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for cmd in commands:
            handle.write(json.dumps(cmd, ensure_ascii=True, separators=(",", ":")) + "\n")
    shutil.copyfile(path, os.path.join(output_dir, "opencode_tool_commands.jsonl"))
    return path


def _messages_to_stdout_events(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for msg in messages:
        info = msg.get("info", {}) if isinstance(msg, dict) else {}
        if isinstance(info, dict) and info.get("error"):
            events.append({"type": "error", "error": info.get("error")})

        for part in (msg.get("parts") or []):
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "step-start":
                events.append({"type": "step_start", "part": part})
            elif ptype == "step-finish":
                events.append({"type": "step_finish", "part": part})
            elif ptype == "tool":
                events.append({"type": "tool_use", "part": part})
            elif ptype == "text":
                events.append({"type": "text", "part": part})
    return events


def _run_server_mode(
    args: argparse.Namespace,
    goal_text: str,
    execution_id: str,
    output_dir: str,
    timeline_path: str,
    stdout_path: str,
    stderr_path: str,
) -> Dict[str, Any]:
    start = time.time()
    base_url = _derive_server_url(args)
    errors: List[str] = []
    session_id = None

    write_timeline_entry(timeline_path, "API", "coder56 server mode starting", {
        "base_url": base_url,
        "exec": execution_id[:8],
    })

    try:
        health = _http_json("GET", f"{base_url}/global/health", timeout=8)
        healthy = isinstance(health, dict) and bool(health.get("healthy", False))
        if not healthy:
            raise RuntimeError(f"OpenCode server unhealthy at {base_url}")

        session = _http_json("POST", f"{base_url}/session", {"title": f"coder56 {execution_id[:8]}"}, timeout=10)
        session_id = (session or {}).get("id")
        if not session_id:
            raise RuntimeError("OpenCode server did not return session id")
        write_timeline_entry(timeline_path, "API", "opencode session created", {
            "session_id": session_id,
            "exec": execution_id[:8],
        })

        body = {
            "parts": [{"type": "text", "text": goal_text}],
            "agent": "coder56",
        }
        _http_json("POST", f"{base_url}/session/{session_id}/prompt_async", body, timeout=30)
        write_timeline_entry(timeline_path, "API", "prompt_async submitted", {
            "session_id": session_id,
            "exec": execution_id[:8],
        })

        deadline = time.time() + args.timeout
        last_status: Any = None
        seen_session_status = False
        messages: List[Dict[str, Any]] = []

        # Progress/health logging while we wait so long runs don't look "stuck".
        last_progress_log = 0.0
        last_meta_fetch = 0.0
        last_activity_fetch = 0.0
        last_updated_ms: Optional[int] = None
        last_updated_change = time.time()
        last_seen_message_id: Optional[str] = None
        last_activity_summary: Dict[str, Any] = {}

        def _fetch_session_updated_ms() -> Optional[int]:
            try:
                sess_list = _http_json("GET", f"{base_url}/session", timeout=10)
                if isinstance(sess_list, list):
                    for s in sess_list:
                        if isinstance(s, dict) and s.get("id") == session_id:
                            t = s.get("time") or {}
                            upd = t.get("updated")
                            return int(upd) if upd is not None else None
            except Exception:
                return None
            return None

        def _summarize_recent_activity(limit: int = 25) -> Dict[str, Any]:
            """
            Best-effort extraction of "what is it doing" from the latest message parts.
            This is intentionally heuristic because /session/status is coarse (often just busy/idle).
            """
            summary: Dict[str, Any] = {
                "last_role": None,
                "last_finish": None,
                "last_message_id": None,
                "last_tool": None,
                "last_tool_status": None,
                "last_tool_title": None,
                "last_tool_cmd_redacted": None,
                "last_tool_cmd_hash": None,
                "last_tool_exit": None,
                "last_tool_output_len": None,
                "last_text": None,
                "error": None,
            }
            try:
                recent = _http_json("GET", f"{base_url}/session/{session_id}/message?limit={limit}", timeout=30)
                if not isinstance(recent, list) or not recent:
                    return summary
                last = recent[-1]
                info = last.get("info", {}) if isinstance(last, dict) else {}
                summary["last_role"] = info.get("role")
                summary["last_finish"] = info.get("finish")
                summary["last_message_id"] = info.get("id")

                # Walk backwards across recent messages to find a tool or text.
                for msg in reversed(recent):
                    if not isinstance(msg, dict):
                        continue
                    for part in reversed(msg.get("parts") or []):
                        if not isinstance(part, dict):
                            continue
                        ptype = part.get("type")
                        if ptype == "tool":
                            st = part.get("state") or {}
                            inp = st.get("input") or {}
                            out = st.get("output") or ""
                            md = st.get("metadata") or {}
                            summary["last_tool"] = part.get("tool")
                            summary["last_tool_status"] = st.get("status")
                            summary["last_tool_title"] = inp.get("title") or inp.get("description")
                            cmd = inp.get("command") if isinstance(inp, dict) else None
                            if isinstance(cmd, str):
                                summary["last_tool_cmd_redacted"] = (_redact_command(cmd)[:220] + "...") if len(cmd) > 220 else _redact_command(cmd)
                                summary["last_tool_cmd_hash"] = _hash_text(cmd)
                            if isinstance(md, dict):
                                summary["last_tool_exit"] = md.get("exit")
                            if isinstance(out, str):
                                summary["last_tool_output_len"] = len(out)
                            break
                        if ptype == "text":
                            txt = part.get("text")
                            if isinstance(txt, str) and txt.strip():
                                txt = " ".join(txt.split())
                                summary["last_text"] = (txt[:180] + "...") if len(txt) > 180 else txt
                                break
                    if summary.get("last_tool") or summary.get("last_text"):
                        break

                if isinstance(info, dict) and isinstance(info.get("error"), dict):
                    err = info.get("error") or {}
                    summary["error"] = err.get("name") or str(err)
            except Exception as exc:
                summary["error"] = f"activity_fetch_failed: {exc}"
            return summary

        while time.time() < deadline:
            statuses = _http_json("GET", f"{base_url}/session/status", timeout=10)
            status = statuses.get(session_id) if isinstance(statuses, dict) else None
            last_status = status
            status_s = str(status).lower() if status is not None else "none"

            now = time.time()
            if (now - last_meta_fetch) >= 5:
                last_meta_fetch = now
                updated = _fetch_session_updated_ms()
                if updated is not None and updated != last_updated_ms:
                    last_updated_ms = updated
                    last_updated_change = now

            # Fetch recent activity when we log progress, or when the session updated timestamp changes.
            if (now - last_activity_fetch) >= 10 or (last_updated_ms is not None and (now - last_updated_change) < 2):
                last_activity_fetch = now
                last_activity_summary = _summarize_recent_activity(limit=25)
                msg_id = last_activity_summary.get("last_message_id")
                if isinstance(msg_id, str) and msg_id != last_seen_message_id:
                    last_seen_message_id = msg_id

            if (now - last_progress_log) >= 10:
                last_progress_log = now
                # Keep console output terse; timeline gets structured data.
                activity_bits: List[str] = []
                if last_activity_summary.get("last_tool"):
                    activity_bits.append(f"tool={last_activity_summary.get('last_tool')}:{last_activity_summary.get('last_tool_status')}")
                    if last_activity_summary.get("last_tool_title"):
                        activity_bits.append(f"title={last_activity_summary.get('last_tool_title')}")
                    if last_activity_summary.get("last_tool_exit") is not None:
                        activity_bits.append(f"exit={last_activity_summary.get('last_tool_exit')}")
                    if last_activity_summary.get("last_tool_output_len") is not None:
                        activity_bits.append(f"out_len={last_activity_summary.get('last_tool_output_len')}")
                    if last_activity_summary.get("last_tool_cmd_hash"):
                        activity_bits.append(f"cmd_hash={last_activity_summary.get('last_tool_cmd_hash')}")
                elif last_activity_summary.get("last_text"):
                    activity_bits.append("text=1")
                if last_activity_summary.get("error"):
                    activity_bits.append(f"msg_error={last_activity_summary.get('error')}")
                activity_s = " ".join(activity_bits) if activity_bits else "activity=unknown"
                print(f"[coder56_server] status={status_s} elapsed={int(now - start)}s updated_ms={last_updated_ms} {activity_s}")
                write_timeline_entry(timeline_path, "POLL", "opencode session polling", {
                    "session_id": session_id,
                    "status": status,
                    "elapsed_seconds": int(now - start),
                    "updated_ms": last_updated_ms,
                    "seconds_since_update": int(now - last_updated_change),
                    "activity": last_activity_summary,
                    "exec": execution_id[:8],
                })

                if args.stall_timeout and int(now - last_updated_change) >= args.stall_timeout:
                    raise TimeoutError(
                        f"Session stalled: no updates for {args.stall_timeout}s (session_id={session_id})"
                    )

            if status is None:
                # Some server builds remove session status entries after completion.
                # If we previously observed the session and messages exist, treat it as finished.
                if seen_session_status:
                    fetched = _http_json("GET", f"{base_url}/session/{session_id}/message", timeout=30)
                    if isinstance(fetched, list) and fetched:
                        messages = fetched
                        break
                time.sleep(args.status_poll_interval)
                continue
            seen_session_status = True
            if any(k in status_s for k in ["completed", "idle", "ready", "done", "error", "failed"]):
                break
            time.sleep(args.status_poll_interval)
        else:
            raise TimeoutError(f"Timed out waiting for OpenCode session completion ({args.timeout}s)")

        if not seen_session_status:
            errors.append("session status not observed in /session/status response")

        if not messages:
            for _ in range(5):
                fetched = _http_json("GET", f"{base_url}/session/{session_id}/message", timeout=30)
                if isinstance(fetched, list) and fetched:
                    messages = fetched
                    break
                time.sleep(1)
            if not messages:
                fetched = _http_json("GET", f"{base_url}/session/{session_id}/message", timeout=30)
                if isinstance(fetched, list):
                    messages = fetched
        if not messages:
            errors.append("empty message payload from OpenCode server")

        commands = _collect_tool_commands_from_messages(messages, execution_id)
        tool_commands_path = None
        if commands:
            tool_commands_path = _write_tool_commands(output_dir, execution_id, commands)

        api_path = os.path.join(output_dir, f"opencode_api_messages_{execution_id[:8]}.json")
        with open(api_path, "w", encoding="utf-8") as handle:
            json.dump(messages, handle, ensure_ascii=True, indent=2)
        shutil.copyfile(api_path, os.path.join(output_dir, "opencode_api_messages.json"))

        events = _messages_to_stdout_events(messages)
        with open(stdout_path, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write("")

        metrics = append_opencode_events(
            timeline_path=timeline_path,
            execution_id=execution_id,
            stdout_text="\n".join(json.dumps(e, separators=(",", ":")) for e in events),
        )
        metrics["session_id"] = session_id
        metrics["export_path"] = api_path
        metrics["tool_commands_path"] = tool_commands_path
        metrics["tool_commands_count"] = len(commands)

        if last_status is not None and any(k in str(last_status).lower() for k in ["error", "failed"]):
            errors.append(f"session status: {last_status}")

        return {
            "exit_code": 0 if not errors else 1,
            "duration": time.time() - start,
            "metrics": metrics,
            "errors": errors,
        }

    except Exception as exc:
        err_text = str(exc)
        errors.append(err_text)
        # Best-effort persistence of any partial messages/tool calls.
        messages = _safe_fetch_messages(base_url, session_id)
        persisted = _persist_messages(output_dir, execution_id, messages)
        metrics = _persist_stdout_from_messages(output_dir, execution_id, messages, stdout_path)
        if not messages:
            with open(stdout_path, "w", encoding="utf-8") as handle:
                handle.write("")
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(err_text + "\n")

        if session_id:
            try:
                _http_json("POST", f"{base_url}/session/{session_id}/abort", timeout=10)
            except Exception:
                pass

        return {
            "exit_code": 124 if isinstance(exc, TimeoutError) else 1,
            "duration": time.time() - start,
            "metrics": {
                "final_output": None,
                "llm_calls": 0,
                "tool_calls": metrics.get("tool_calls", []),
                "tool_commands_path": persisted.get("tool_commands_path"),
                "tool_commands_count": persisted.get("tool_commands_count", 0),
                "errors": errors,
                "session_id": session_id,
                "export_path": persisted.get("export_path"),
            },
            "errors": errors,
        }


def main() -> int:
    args = parse_args()
    goal_text = " ".join(args.goal).strip()
    if not goal_text:
        print("Error: goal is required.", file=sys.stderr)
        return 2

    display_cmd = f"OpenCode HTTP API on {_derive_server_url(args)} using agent coder56"

    print(f"[coder56_server] Starting: {display_cmd}")
    execution_id = uuid4().hex

    run_id = resolve_run_id()
    output_dir = os.path.join("outputs", run_id, "coder56")
    os.makedirs(output_dir, exist_ok=True)
    timeline_path = os.path.join(output_dir, "auto_responder_timeline.jsonl")

    write_timeline_entry(timeline_path, "INIT", "coder56 execution started", data={
        "goal": goal_text,
        "container": args.container,
        "exec": execution_id[:8],
        "mode": "server",
    })
    stdout_path = os.path.join(output_dir, f"opencode_stdout_{execution_id[:8]}.jsonl")
    stderr_path = os.path.join(output_dir, f"opencode_stderr_{execution_id[:8]}.log")

    try:
        print("[coder56_server] Starting execution...")
        exit_code = 0

        server_result = _run_server_mode(
            args=args,
            goal_text=goal_text,
            execution_id=execution_id,
            output_dir=output_dir,
            timeline_path=timeline_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        exit_code = int(server_result["exit_code"])
        duration = float(server_result["duration"])
        metrics = dict(server_result["metrics"])

        _write_compat_logs(output_dir, stdout_path, stderr_path)

        write_timeline_entry(timeline_path, "EXEC", "coder56 execution completed", data={
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "output": metrics.get("final_output"),
            "llm_calls": metrics.get("llm_calls"),
            "tool_calls": metrics.get("tool_calls"),
            "unique_tools": len(set(metrics.get("tool_calls", []))),
            "tool_commands_count": metrics.get("tool_commands_count"),
            "tool_commands_path": metrics.get("tool_commands_path"),
            "errors": metrics.get("errors") or None,
            "session_id": metrics.get("session_id"),
            "export_path": metrics.get("export_path"),
            "exec": execution_id[:8],
        })

        if exit_code != 0:
            write_timeline_entry(timeline_path, "ERROR", "coder56 execution failed", data={
                "exit_code": exit_code,
                "exec": execution_id[:8],
            })

        print("[coder56_server] Completed.")
        return exit_code

    except subprocess.TimeoutExpired as exc:
        def _coerce_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode(errors="replace")
            return str(value)

        # Best-effort persistence of any partial messages/tool calls.
        messages = _safe_fetch_messages(_derive_server_url(args), session_id)
        persisted = _persist_messages(output_dir, execution_id, messages)
        metrics = _persist_stdout_from_messages(output_dir, execution_id, messages, stdout_path)
        if not messages:
            with open(stdout_path, "w", encoding="utf-8") as handle:
                handle.write(_coerce_text(exc.stdout))
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(_coerce_text(exc.stderr))
        if not messages:
            append_opencode_events(timeline_path, execution_id, _coerce_text(exc.stdout))
        _write_compat_logs(output_dir, stdout_path, stderr_path)
        write_timeline_entry(timeline_path, "ERROR", "coder56 execution timed out", data={
            "timeout_seconds": args.timeout,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "exec": execution_id[:8],
            "tool_commands_path": persisted.get("tool_commands_path"),
            "export_path": persisted.get("export_path"),
        })
        print("[coder56_server] Completed.")
        return 124

    except Exception as exc:
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(str(exc) + "\n")
        _write_compat_logs(output_dir, stdout_path, stderr_path)
        write_timeline_entry(timeline_path, "ERROR", "coder56 execution exception", data={
            "error": str(exc),
            "exec": execution_id[:8],
        })
        print("[coder56_server] Completed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
