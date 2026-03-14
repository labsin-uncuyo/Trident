#!/usr/bin/env python3
"""
DB Admin Benign Agent – OpenCode Server API version

Connects to the OpenCode HTTP server already running on the compromised
machine and starts a ``db_admin`` session via the REST API.

Replaces the previous ``docker exec`` + ``opencode run`` approach with
direct HTTP calls to the OpenCode server (port 4096 by default).
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

import requests


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OPENCODE_SERVER_PORT = int(os.getenv("OPENCODE_SERVER_PORT", "4096"))
COMPROMISED_IP = os.getenv("COMPROMISED_IP", "172.30.0.10")
DEFAULT_AGENT = "db_admin"
STATUS_POLL_INTERVAL = float(os.getenv("OPENCODE_STATUS_POLL_INTERVAL", "3"))

# Default goal for the db_admin agent when none is provided
DEFAULT_GOAL = """Start your workday. Connect to the database server via the jump host and begin your daily tasks.

These are the credentials to connect to the server's database: PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb

WEB RESEARCH (use curl frequently, always pipe through grep): Research these URLs throughout your session:
curl -s https://www.postgresql.org/docs/current/ | sed 's/<[^>]>//g' | grep -i "keyword" | head -20
curl -s https://wiki.postgresql.org/wiki/Main_Page | sed 's/<[^>]>//g' | grep -iv "edit|login|search" | head -20
curl -s https://www.postgresqltutorial.com/ | sed 's/<[^>]>//g' | head -20
curl -s https://planet.postgresql.org/ | sed 's/<[^>]>//g' | head -20

TIMING: sleep 60-130 between tasks to simulate coffee breaks, go to the bathroom, and natural work pacing.

DATABASE TASKS: Check table structure, INSERT new employees, UPDATE salaries, DELETE obsolete records, run monitoring queries. After each web research session, execute at least one database operation.

LOOP: This workday has no defined end. After completing a full cycle of research + DB operations, start a new cycle with different keywords and different data modifications. Repeat indefinitely."""
_MIN_REMAINING_SECONDS = 30  # Don't start a new session with less time left

# Phrases that indicate the agent considers its work done for this session.
# Checked case-insensitively against the assistant's last text response.
_DONE_PHRASES = (
    "all tasks completed",
    "all tasks are completed",
    "all tasks have been completed",
    "completed all tasks",
    "workday is complete",
    "workday is done",
    "workday complete",
    "finished all tasks",
    "completed my workday",
    "nothing left to do",
    "no more tasks",
    "signing off",
    "end of workday",
    "logging off",
    "work is done",
    "that concludes",
    "that's all for today",
    "all done for today",
    "wrapping up for the day",
)

# Active session reference for cleanup on SIGTERM/SIGINT
_active_host: Optional[str] = None
_active_session_id: Optional[str] = None
# Shared state so the signal handler can flush logs on exit.
_signal_log_ctx: Optional[Dict] = None


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------
def _signal_handler(signum, frame):
    """Abort the running session (if any), flush logs, and exit."""
    if _active_host and _active_session_id:
        # Best-effort save of the current session's logs before aborting.
        ctx = _signal_log_ctx
        if ctx:
            try:
                save_session_logs(
                    _active_host, _active_session_id,
                    ctx["output_dir"], ctx["timeline_path"],
                    ctx["execution_id"], ctx["session_count"])
            except Exception:
                pass  # best-effort
            # Write a DONE entry so the timeline is always terminated.
            try:
                write_timeline_entry(
                    ctx["timeline_path"], "INTERRUPTED",
                    "Execution interrupted by signal",
                    data={"exec": ctx["execution_id"][:8],
                          "signal": signum})
            except Exception:
                pass
        abort_session(_active_host, _active_session_id)
    sys.exit(1)


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# ---------------------------------------------------------------------------
# OpenCode Server API helpers
# ---------------------------------------------------------------------------
def get_opencode_base_url(host: str = COMPROMISED_IP,
                          port: int = OPENCODE_SERVER_PORT) -> str:
    """Build the OpenCode server base URL."""
    return f"http://{host}:{port}"


def check_opencode_health(host: str = COMPROMISED_IP) -> bool:
    """Return True if the OpenCode server is alive."""
    base_url = get_opencode_base_url(host)
    try:
        resp = requests.get(f"{base_url}/global/health", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("healthy", False)
    except Exception:
        pass
    return False


def wait_for_opencode_server(host: str = COMPROMISED_IP,
                             timeout: int = 120) -> bool:
    """Block until the OpenCode server is healthy or *timeout* elapses."""
    start = time.time()
    while time.time() - start < timeout:
        if check_opencode_health(host):
            return True
        time.sleep(2)
    return False


def create_session(host: str = COMPROMISED_IP,
                   title: Optional[str] = None) -> Optional[str]:
    """Create a new session. Returns the session ID or None."""
    base_url = get_opencode_base_url(host)
    try:
        body: dict = {}
        if title:
            body["title"] = title
        resp = requests.post(f"{base_url}/session", json=body, timeout=60)
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as exc:
        print(f"[db_admin] Failed to create session: {exc}", file=sys.stderr)
        return None


def send_message_async(host: str, session_id: str, message: str,
                       agent: str = DEFAULT_AGENT) -> bool:
    """Fire-and-forget: POST prompt and return immediately."""
    base_url = get_opencode_base_url(host)
    try:
        body = {
            "parts": [{"type": "text", "text": message}],
            "agent": agent,
        }
        resp = requests.post(
            f"{base_url}/session/{session_id}/prompt_async",
            json=body,
            timeout=30,
        )
        return resp.status_code in (200, 204)
    except Exception as exc:
        print(f"[db_admin] Failed to send async message: {exc}",
              file=sys.stderr)
        return False


def send_message_sync(host: str, session_id: str, message: str,
                      agent: str = DEFAULT_AGENT,
                      timeout: int = 600) -> Optional[Dict]:
    """Blocking: POST prompt and wait for the full response."""
    base_url = get_opencode_base_url(host)
    try:
        body = {
            "parts": [{"type": "text", "text": message}],
            "agent": agent,
        }
        resp = requests.post(
            f"{base_url}/session/{session_id}/message",
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[db_admin] Failed to send sync message: {exc}",
              file=sys.stderr)
        return None


def get_session_status(host: str,
                       session_id: Optional[str] = None) -> Optional[Dict]:
    """Query execution status.  If *session_id* given, return only that."""
    base_url = get_opencode_base_url(host)
    try:
        resp = requests.get(f"{base_url}/session/status", timeout=10)
        resp.raise_for_status()
        all_statuses = resp.json()
        if session_id:
            return all_statuses.get(session_id)
        return all_statuses
    except Exception as exc:
        print(f"[db_admin] Failed to get session status: {exc}",
              file=sys.stderr)
        return None


_BUSY_STATES = ("busy", "pending", "running", "active", "generating")
_IDLE_STATES = ("completed", "idle", "ready", "done")
# Grace period (seconds) to wait for the server to transition to "busy"
# after an async prompt before we start treating "idle" as "completed".
_GRACE_PERIOD = 15

# Phrases that indicate the session failed due to context window overflow.
# Checked case-insensitively against the error status string.
_CONTEXT_OVERFLOW_PHRASES = (
    "requested token count exceeds",
    "context length of",
    "exceeds the model's maximum context",
    "maximum context length",
    "input messages or the completion to fit within the limit",
)

# Tracks the last error seen by wait_for_session_complete so callers can
# inspect the reason for completion without changing the bool return type.
_last_wait_error: Optional[str] = None


def _is_context_overflow(status_str: str) -> bool:
    """Return True if *status_str* indicates a context-window overflow."""
    s = status_str.lower()
    return any(phrase in s for phrase in _CONTEXT_OVERFLOW_PHRASES)


def wait_for_session_complete(host: str, session_id: str,
                              timeout: int = 600) -> bool:
    """Poll session status until it completes, fails, or times out.

    The function waits through an initial *grace period* during which
    "idle" / "ready" statuses are **not** treated as completion.  This
    avoids the race where polling starts before the server picks up the
    async prompt.
    """
    global _last_wait_error
    _last_wait_error = None
    start = time.time()
    saw_busy = False          # True once we've seen a busy state
    _last_logged_status = None  # avoid spamming the same status

    while True:
        elapsed = time.time() - start
        if elapsed >= timeout:
            break

        status = get_session_status(host, session_id)

        # ── session disappeared from status map ──────────────────────
        if status is None:
            if _last_logged_status != "__none__":
                print(f"[db_admin]   status: None (saw_busy={saw_busy}, "
                      f"elapsed={elapsed:.0f}s)")
                _last_logged_status = "__none__"
            # Early in the run the session may not yet appear
            if saw_busy or elapsed > _GRACE_PERIOD:
                print(f"[db_admin] Session {session_id[:12]} completed "
                      f"({elapsed:.0f}s)")
                return True
            time.sleep(STATUS_POLL_INTERVAL)
            continue

        status_str = str(status).lower()
        if status_str != _last_logged_status:
            print(f"[db_admin]   status: {status_str[:80]} "
                  f"(saw_busy={saw_busy}, elapsed={elapsed:.0f}s)")
            _last_logged_status = status_str

        # ── track whether we ever saw the session actively working ───
        if any(s in status_str for s in _BUSY_STATES):
            saw_busy = True

        # ── hard errors are always final ─────────────────────────────
        if "error" in status_str or "failed" in status_str:
            _last_wait_error = status_str
            print(f"[db_admin] Session {session_id[:12]} errored: "
                  f"{status_str}", file=sys.stderr)
            return True

        # ── idle / completed states ──────────────────────────────────
        if any(s in status_str for s in _IDLE_STATES):
            if saw_busy:
                # Was busy before → genuinely finished
                return True
            if elapsed > _GRACE_PERIOD:
                # Never saw busy, but grace period exhausted
                print(f"[db_admin] Session {session_id[:12]}: still "
                      f"idle after grace period ({elapsed:.0f}s), "
                      f"treating as completed")
                return True
            # Still within grace period – keep waiting for busy

        time.sleep(STATUS_POLL_INTERVAL)

    print(f"[db_admin] Session {session_id[:12]} timed out after "
          f"{timeout}s", file=sys.stderr)
    return False


def get_session_messages(host: str, session_id: str) -> Optional[List]:
    """Fetch all messages / results from a session (with retries)."""
    base_url = get_opencode_base_url(host)
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{base_url}/session/{session_id}/message", timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[db_admin] Attempt {attempt + 1}/3 get messages "
                  f"failed: {exc}", file=sys.stderr)
            time.sleep(2)
    return None


def abort_session(host: str, session_id: str) -> bool:
    """Abort a running session."""
    base_url = get_opencode_base_url(host)
    try:
        resp = requests.post(
            f"{base_url}/session/{session_id}/abort", timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def summarize_session(host: str, session_id: str,
                      provider_id: str = "e-infra-chat",
                      model_id: str = "qwen3-coder") -> bool:
    """Ask the OpenCode server to compress this session's history in-place.

    Uses ``POST /session/:id/summarize``.  After a successful call the
    session's token count drops significantly, allowing further prompts
    without hitting the context-window limit.
    Returns True on success.
    """
    base_url = get_opencode_base_url(host)
    try:
        body = {"providerID": provider_id, "modelID": model_id}
        resp = requests.post(
            f"{base_url}/session/{session_id}/summarize",
            json=body,
            timeout=120,  # summarisation can take a moment
        )
        if resp.status_code == 200:
            result = resp.json()
            # The endpoint returns a boolean
            return bool(result) if not isinstance(result, bool) else result
        print(f"[db_admin] summarize_session HTTP {resp.status_code}: "
              f"{resp.text[:200]}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[db_admin] Failed to summarize session: {exc}",
              file=sys.stderr)
        return False


def fork_session(host: str, session_id: str,
                 message_id: Optional[str] = None) -> Optional[str]:
    """Fork an existing session to continue with full context.

    Returns the new session ID or *None* on failure.
    """
    base_url = get_opencode_base_url(host)
    try:
        body: dict = {}
        if message_id:
            body["messageID"] = message_id
        resp = requests.post(f"{base_url}/session/{session_id}/fork",
                             json=body, timeout=60)
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as exc:
        print(f"[db_admin] Failed to fork session: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Log conversion: API messages → legacy JSONL format
# (Adapted from auto_responder.py)
# ---------------------------------------------------------------------------
def convert_api_messages_to_legacy_jsonl(messages: List[Dict]) -> List[str]:
    """Convert OpenCode Server API message format to legacy JSONL format.

    Legacy format has one JSON event per line with top-level fields:
      {"type": "step_start|tool_use|text|step_finish",
       "timestamp": <ms_epoch>, "sessionID": ..., "part": {...}}

    API message format has messages containing parts:
      [{"info": {...}, "parts": [{"type": "step-start|tool|text|step-finish", ...}]}]
    """
    legacy_lines: List[str] = []

    for msg in messages:
        info = msg.get("info", {})
        parts = msg.get("parts", [])
        session_id = info.get("sessionID", "")

        for part in parts:
            part_type = part.get("type", "")

            # Map API part types to legacy event types
            type_map = {
                "step-start": "step_start",
                "step-finish": "step_finish",
                "tool": "tool_use",
                "text": "text",
            }
            legacy_type = type_map.get(part_type)
            if legacy_type is None:
                continue

            # Determine timestamp
            timestamp_ms = 0
            part_time = part.get("time", {})
            if part_time:
                timestamp_ms = (
                    part_time.get("start", 0) or part_time.get("end", 0)
                )
            if not timestamp_ms:
                msg_time = info.get("time", {})
                timestamp_ms = (
                    msg_time.get("created", 0)
                    or msg_time.get("completed", 0)
                )

            legacy_event: Dict = {
                "type": legacy_type,
                "timestamp": timestamp_ms,
                "sessionID": session_id,
                "part": part,
            }

            # For step_finish, add reason/cost/tokens from message info
            if legacy_type == "step_finish":
                if "reason" not in part and info.get("finish"):
                    legacy_event["part"]["reason"] = info["finish"]
                if "cost" not in part and info.get("cost") is not None:
                    legacy_event["part"]["cost"] = info["cost"]
                if "tokens" not in part and info.get("tokens"):
                    legacy_event["part"]["tokens"] = info["tokens"]

            legacy_lines.append(
                json.dumps(legacy_event, separators=(",", ":"))
            )

    return legacy_lines


def save_session_logs(host: str, session_id: str, output_dir: str,
                      timeline_path: str, execution_id: str,
                      session_num: int) -> Dict:
    """Fetch session messages and save in both API and legacy JSONL formats.

    Saves (per session, appending to execution-level files):
      - opencode_api_messages.json  : Full API response (JSON array)
      - opencode_stdout.jsonl       : Legacy JSONL format (one event per line)

    Also writes each OpenCode event to the timeline.
    Returns dict with parsed metrics.
    """
    api_path = os.path.join(output_dir, "opencode_api_messages.json")
    legacy_path = os.path.join(output_dir, "opencode_stdout.jsonl")

    messages = get_session_messages(host, session_id)
    if messages is None:
        print(f"[db_admin] No messages retrieved for session "
              f"{session_id[:12]}", file=sys.stderr)
        return {"final_output": None, "llm_calls": 0,
                "tool_calls": [], "errors": [],
                "messages": None}

    if not messages:
        print(f"[db_admin] Empty message list for session "
              f"{session_id[:12]}")
        return {"final_output": None, "llm_calls": 0,
                "tool_calls": [], "errors": [],
                "messages": messages}

    # ── Save API format (load existing, append, rewrite) ──
    existing: List = []
    if os.path.exists(api_path):
        try:
            with open(api_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append({
        "session_id": session_id,
        "session_num": session_num,
        "exec": execution_id[:8],
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "messages": messages,
    })
    with open(api_path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
    print(f"[db_admin] Saved API messages → {api_path}")

    # ── Convert and save legacy JSONL format (append) ──
    legacy_lines = convert_api_messages_to_legacy_jsonl(messages)
    with open(legacy_path, "a", encoding="utf-8") as fh:
        for line in legacy_lines:
            fh.write(line + "\n")
    print(f"[db_admin] Saved legacy JSONL ({len(legacy_lines)} events) → "
          f"{legacy_path}")

    # ── Write each OpenCode event to the timeline ──
    for line in legacy_lines:
        try:
            event = json.loads(line)
            event_type = event.get("type", "")
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "OPENCODE",
                "msg": event_type,
                "exec": execution_id[:8],
                "data": event,
            }
            with open(timeline_path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(entry, separators=(",", ":")) + "\n"
                )
        except (json.JSONDecodeError, ValueError):
            continue

    # ── Parse metrics ──
    llm_calls = 0
    tool_calls: List[str] = []
    text_outputs: List[str] = []
    errors: List[str] = []
    total_tokens = {"input": 0, "output": 0, "reasoning": 0}
    total_cost = 0.0

    for msg in messages:
        info = msg.get("info", {})
        parts = msg.get("parts", [])

        if info.get("role") == "assistant":
            msg_tokens = info.get("tokens", {})
            total_tokens["input"] += msg_tokens.get("input", 0)
            total_tokens["output"] += msg_tokens.get("output", 0)
            total_tokens["reasoning"] += msg_tokens.get("reasoning", 0)
            total_cost += info.get("cost", 0) or 0

        for part in parts:
            part_type = part.get("type", "")
            if part_type == "step-start":
                llm_calls += 1
            elif part_type == "tool":
                tool_calls.append(part.get("tool", "unknown"))
            elif part_type == "text":
                text = part.get("text", "")
                if text:
                    text_outputs.append(text)

    final_output = None
    if text_outputs:
        final_output = " ".join(text_outputs)[-500:]

    return {
        "final_output": final_output,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "errors": errors,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "api_messages": len(messages),
        "messages": messages,
    }


def _extract_context_from_messages(messages: Optional[List],
                                   max_chars: int = 2000) -> str:
    """Best-effort extraction of readable context from session messages."""
    if not messages:
        return ""
    context_parts: List[str] = []
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", msg.get("type", "unknown"))
        content = msg.get("content", msg.get("text", ""))
        if isinstance(content, list):
            content = " ".join(
                p.get("text", str(p)) if isinstance(p, dict) else str(p)
                for p in content
            )
        elif not isinstance(content, str):
            content = str(content)
        if content.strip():
            context_parts.append(f"[{role}]: {content[:500]}")
        if sum(len(p) for p in context_parts) >= max_chars:
            break
    context_parts.reverse()
    return "\n".join(context_parts)


def _get_last_assistant_text(messages: Optional[List]) -> str:
    """Return the text of the last assistant message, or empty string."""
    if not messages:
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", msg.get("type", ""))
        if role not in ("assistant", "model"):
            continue
        content = msg.get("content", msg.get("text", ""))
        if isinstance(content, list):
            content = " ".join(
                p.get("text", str(p)) if isinstance(p, dict) else str(p)
                for p in content
            )
        elif not isinstance(content, str):
            content = str(content)
        return content.strip()
    return ""


def _agent_says_done(messages: Optional[List]) -> bool:
    """Heuristic: check if the agent's last response signals task completion."""
    text = _get_last_assistant_text(messages).lower()
    if not text:
        return False
    return any(phrase in text for phrase in _DONE_PHRASES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_trident_base() -> str:
    """Get Trident base directory (Docker: /home/shared/Trident, Host: workspace root)."""
    # Check environment variable first (Docker containers set this)
    trident_home = os.environ.get("TRIDENT_HOME", "").strip()
    if trident_home and os.path.isdir(trident_home):
        return trident_home
    
    # Fall back to workspace root (for host execution)
    # Navigate up from script location to find Trident root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    current = script_dir
    for _ in range(5):  # Search up to 5 levels
        if os.path.exists(os.path.join(current, "README.md")) and \
           os.path.exists(os.path.join(current, "docker-compose.yml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:  # Reached root
            break
        current = parent
    
    # Last resort: use current working directory
    return os.getcwd()


def resolve_run_id() -> str:
    run_id = os.environ.get("RUN_ID", "").strip()
    if run_id:
        return run_id
    base_dir = get_trident_base()
    current_run = os.path.join(base_dir, "outputs", ".current_run")
    try:
        with open(current_run, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return "manual"


def write_timeline_entry(path: str, level: str, message: str,
                         data: Optional[dict] = None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "msg": message,
    }
    if data:
        entry["data"] = data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        fh.flush()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run db_admin benign agent via OpenCode Server API.",
    )
    parser.add_argument(
        "goal", nargs="*", default=[""],
        help="Goal text to send to the agent (default: built-in db_admin goal).",
    )
    parser.add_argument(
        "--host", default=COMPROMISED_IP,
        help=f"OpenCode server host (default: {COMPROMISED_IP}).",
    )
    parser.add_argument(
        "--port", type=int, default=OPENCODE_SERVER_PORT,
        help=f"OpenCode server port (default: {OPENCODE_SERVER_PORT}).",
    )
    parser.add_argument(
        "--agent", default=DEFAULT_AGENT,
        help=f"Agent name (default: {DEFAULT_AGENT}).",
    )
    parser.add_argument(
        "--time-limit", type=int, default=None,
        help="Maximum execution time in seconds (default: None = run indefinitely).",
    )
    # Kept for backward-compatibility with callers that still pass these.
    parser.add_argument("--container", default=None,
                        help=argparse.SUPPRESS)
    parser.add_argument("--user", default=None,
                        help=argparse.SUPPRESS)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    global _active_host, _active_session_id, OPENCODE_SERVER_PORT, _last_wait_error

    args = parse_args()
    goal_text = " ".join(args.goal).strip()
    if not goal_text:
        goal_text = DEFAULT_GOAL
    host = args.host
    agent = args.agent
    time_limit = args.time_limit
    OPENCODE_SERVER_PORT = args.port

    execution_id = uuid4().hex
    run_id = resolve_run_id()
    base_dir = get_trident_base()
    output_dir = os.path.join(base_dir, "outputs", run_id, "benign_agent")
    os.makedirs(output_dir, exist_ok=True)
    timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")

    # Expose log context so the signal handler can flush on Ctrl+C.
    global _signal_log_ctx
    _signal_log_ctx = {
        "output_dir": output_dir,
        "timeline_path": timeline_path,
        "execution_id": execution_id,
        "session_count": 0,
    }

    print(f"[db_admin] OpenCode Server API mode")
    print(f"[db_admin] Logs  : {output_dir}")
    print(f"[db_admin] Target: http://{host}:{OPENCODE_SERVER_PORT}")
    print(f"[db_admin] Agent : {agent}")
    print(f"[db_admin] Goal  : {goal_text!r}")
    if time_limit is not None:
        print(f"[db_admin] Time limit: {time_limit}s")
    else:
        print(f"[db_admin] Time limit: None (indefinite execution)")

    write_timeline_entry(timeline_path, "INIT",
                         "db_admin execution started", data={
                             "goal": goal_text,
                             "host": host,
                             "agent": agent,
                             "exec": execution_id[:8],
                             "mode": "opencode_server_api",
                             "time_limit": time_limit,
                         })

    # ── 1. Wait for OpenCode server ──────────────────────────────────
    print("[db_admin] Waiting for OpenCode server...")
    if not wait_for_opencode_server(host, timeout=120):
        msg = (f"OpenCode server not available at "
               f"{host}:{OPENCODE_SERVER_PORT}")
        print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
        write_timeline_entry(timeline_path, "ERROR", msg,
                             data={"exec": execution_id[:8]})
        return 1
    print("[db_admin] ✓ OpenCode server healthy")

    # ── 2. Session loop – keep launching sessions until time limit ───
    execution_start = time.time()
    all_session_messages: List[Dict] = []
    session_count = 0
    prev_session_id: Optional[str] = None

    while True:
        # Check if we've exceeded time limit (if set)
        if time_limit is not None:
            elapsed = time.time() - execution_start
            remaining = time_limit - elapsed

            if remaining < _MIN_REMAINING_SECONDS:
                print(f"[db_admin] Time limit reached "
                      f"({elapsed:.0f}s/{time_limit}s)")
                break
        else:
            remaining = float('inf')  # Infinite time remaining

        session_count += 1
        is_forked = False

        # ── Create session (fork previous for continuity, or new) ────
        if prev_session_id is not None:
            print(f"[db_admin] Session {session_count}: forking from "
                  f"{prev_session_id[:12]}...")
            session_id = fork_session(host, prev_session_id)
            if session_id:
                is_forked = True
            else:
                print("[db_admin] Fork failed, creating fresh session "
                      "with context...")
                session_id = create_session(
                    host,
                    title=f"db_admin {execution_id[:8]} s{session_count}")
        else:
            session_id = create_session(
                host, title=f"db_admin {execution_id[:8]}")

        if not session_id:
            msg = f"Failed to create session {session_count}"
            print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
            write_timeline_entry(timeline_path, "ERROR", msg,
                                 data={"exec": execution_id[:8],
                                        "session_num": session_count})
            return 1

        _active_host = host
        _active_session_id = session_id
        _signal_log_ctx["session_count"] = session_count

        print(f"[db_admin] ✓ Session {session_count} created: "
              f"{session_id[:12]} ({'forked' if is_forked else 'new'})")
        write_timeline_entry(
            timeline_path, "SESSION",
            f"Session {session_count} created",
            data={"session_id": session_id,
                  "session_num": session_count,
                  "forked_from": prev_session_id if is_forked else None,
                  "exec": execution_id[:8]})

        # ── Build first prompt for this session ──────────────────────
        if session_count == 1:
            prompt = goal_text
        else:
            if time_limit is not None:
                remaining_min = remaining / 60
                time_phrase = f"You still have approximately {remaining_min:.0f} minutes remaining in your workday."
            else:
                time_phrase = "Continue your workday."
            
            if is_forked:
                prompt = (
                    f"{time_phrase} Here is your "
                    f"task again:\n\n{goal_text}\n\n"
                    f"IMPORTANT: Do NOT just describe what you would do. "
                    f"Actually execute the commands right now. Start "
                    f"immediately by running a command."
                )
            else:
                prev_ctx = ""
                if all_session_messages:
                    last_msgs = all_session_messages[-1].get("messages")
                    prev_ctx = _extract_context_from_messages(last_msgs)
                context_block = ""
                if prev_ctx:
                    context_block = (
                        f"\n\nHere is context from your previous "
                        f"session:\n{prev_ctx}"
                    )
                prompt = (
                    f"{time_phrase} Here is your task:\n\n"
                    f"{goal_text}{context_block}\n\n"
                    f"IMPORTANT: Do NOT just describe what you would do. "
                    f"Actually execute the commands right now. Start "
                    f"immediately by running a command."
                )

        # ── Inner turn loop: keep the session alive ──────────────────
        # The agent processes one prompt and goes idle. We send follow-up
        # "continue" messages within the SAME session until:
        #   • the agent signals it has finished all tasks, OR
        #   • the overall time limit is reached.
        session_start = time.time()
        turn = 0
        agent_done = False
        context_overflow = False  # set when context window limit is hit

        while True:
            turn += 1
            # Check time limit if set
            if time_limit is not None:
                turn_remaining = time_limit - (time.time() - execution_start)
                if turn_remaining < _MIN_REMAINING_SECONDS:
                    print(f"[db_admin] Time limit approaching, ending session "
                          f"{session_count}")
                    break
            else:
                turn_remaining = float('inf')  # No time limit

            # Send prompt
            turn_label = f"s{session_count}t{turn}"
            print(f"[db_admin] [{turn_label}] Sending prompt...")
            if not send_message_async(host, session_id, prompt,
                                       agent=agent):
                print(f"[db_admin] [{turn_label}] Failed to send prompt",
                      file=sys.stderr)
                break
            print(f"[db_admin] [{turn_label}] Prompt sent, waiting...")

            # Wait for this turn to finish
            if time_limit is not None:
                turn_timeout = max(int(turn_remaining), 60)
            else:
                turn_timeout = 3600  # 1 hour per turn when no limit
            completed = wait_for_session_complete(
                host, session_id, timeout=turn_timeout)
            turn_duration = time.time() - session_start

            if not completed:
                print(f"[db_admin] [{turn_label}] Timed out")
                break

            # ── Check for context window overflow ────────────────────
            # Summarize the session in-place so it can keep running;
            # only abandon to a fresh session if summarization fails.
            if _last_wait_error and _is_context_overflow(_last_wait_error):
                print(f"[db_admin] [{turn_label}] Context window overflow "
                      f"– summarizing session {session_id[:12]}...",
                      file=sys.stderr)
                if summarize_session(host, session_id):
                    print(f"[db_admin] [{turn_label}] Session summarized, "
                          f"retrying prompt...")
                    _last_wait_error = None
                    continue  # retry same prompt in the now-compact session
                # Summarization failed – fall back to a fresh session
                print(f"[db_admin] [{turn_label}] Summarization failed, "
                      f"will start a fresh session", file=sys.stderr)
                context_overflow = True
                prev_session_id = None  # prevent fork in outer loop
                break  # end inner turn loop → outer loop starts fresh session

            # Fetch messages and inspect the agent's last response
            messages = get_session_messages(host, session_id)
            last_text = _get_last_assistant_text(messages)
            snippet = last_text[:200].replace("\n", " ")
            print(f"[db_admin] [{turn_label}] Agent responded "
                  f"({turn_duration:.0f}s): {snippet}...")

            # Check if the agent considers itself done
            if _agent_says_done(messages):
                print(f"[db_admin] [{turn_label}] Agent signaled "
                      f"task completion")
                agent_done = True
                break

            # Build follow-up prompt for next turn
            if time_limit is not None:
                remaining_min = (time_limit - (time.time() - execution_start)) / 60
                time_phrase = f"You have approximately {remaining_min:.0f} minutes left in your workday."
            else:
                time_phrase = "Continue your workday."
            
            prompt = (
                f"Good, keep going. {time_phrase} "
                f"Continue with the next cycle of tasks. "
                f"Execute the next command now."
            )

        # ── End of session: save logs incrementally ──────────────────
        session_duration = time.time() - session_start
        log_result = save_session_logs(
            host, session_id, output_dir, timeline_path,
            execution_id, session_count)
        messages = log_result.get("messages")
        if messages:
            all_session_messages.append({
                "session_id": session_id,
                "session_num": session_count,
                "forked_from": prev_session_id if is_forked else None,
                "turns": turn,
                "messages": messages,
            })
            print(f"[db_admin] ✓ Session {session_count}: {turn} turns, "
                  f"{len(messages)} messages, {session_duration:.0f}s")
            if log_result.get("llm_calls"):
                print(f"[db_admin]   LLM calls: {log_result['llm_calls']}, "
                      f"tool calls: {len(log_result['tool_calls'])}, "
                      f"cost: ${log_result.get('total_cost', 0):.4f}")

        write_timeline_entry(
            timeline_path, "SESSION_END",
            f"Session {session_count} ended",
            data={"session_id": session_id,
                  "session_num": session_count,
                  "turns": turn,
                  "duration_seconds": round(session_duration, 2),
                  "agent_done": agent_done,
                  "context_overflow": context_overflow,
                  "messages_count": len(messages) if messages else 0,
                  "exec": execution_id[:8]})

        # If context overflowed: prev_session_id is already None (set inside
        # the inner loop); skip the assignment below and continue to the
        # next iteration which will create a fresh session.
        if not context_overflow:
            prev_session_id = session_id

        if context_overflow:
            # Fresh session will be created at the top of the outer loop
            print(f"[db_admin] Starting fresh session after context overflow...")
            continue

        # Session ended (either agent said done, or the session completed
        # naturally via tool calls without an explicit done phrase, or the
        # inner turn-limit was hit).  In all cases: start a new session if
        # time remains, otherwise exit cleanly.
        if time_limit is not None:
            remaining_now = time_limit - (time.time() - execution_start)
            if remaining_now < _MIN_REMAINING_SECONDS:
                print(f"[db_admin] Time limit reached after session {session_count}")
                break
            reason = "agent finished" if agent_done else "session completed"
            print(f"[db_admin] Session {session_count} done ({reason}), "
                  f"{remaining_now:.0f}s remain — starting new session...")
        else:
            reason = "agent finished" if agent_done else "session completed"
            print(f"[db_admin] Session {session_count} done ({reason}), "
                  f"starting new session...")

    # ── 3. Final summary ─────────────────────────────────────────────
    # Session logs were already incrementally saved by save_session_logs().
    # Write a final summary to the timeline and print stats.
    total_duration = time.time() - execution_start
    messages_path = os.path.join(output_dir, "opencode_api_messages.json")
    if all_session_messages:
        total_msg_count = sum(
            len(s["messages"]) for s in all_session_messages)
        print(f"[db_admin] ✓ {total_msg_count} messages from "
              f"{session_count} session(s) saved → {messages_path}")
    else:
        print("[db_admin] ⚠ No messages retrieved")

    write_timeline_entry(timeline_path, "DONE",
                         "db_admin execution finished", data={
                             "total_sessions": session_count,
                             "total_duration_seconds":
                                 round(total_duration, 2),
                             "exec": execution_id[:8],
                         })

    _active_session_id = None
    print(f"[db_admin] Done. {session_count} session(s), "
          f"{total_duration:.1f}s total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
