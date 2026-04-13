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
COMPROMISED_IP = "172.30.0.10"  # fixed lab IP, not configurable via env
DEFAULT_AGENT = "db_admin"
STATUS_POLL_INTERVAL = float(os.getenv("OPENCODE_STATUS_POLL_INTERVAL", "3"))

# Active session reference for cleanup on SIGTERM/SIGINT
_active_host: Optional[str] = None
_active_session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------
def _signal_handler(signum, frame):
    """Abort the running session (if any) and exit."""
    if _active_host and _active_session_id:
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
        resp = requests.post(f"{base_url}/session", json=body, timeout=10)
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


def wait_for_session_complete(host: str, session_id: str,
                              timeout: int = 600) -> bool:
    """Poll session status until it completes, fails, or times out."""
    start = time.time()
    while time.time() - start < timeout:
        status = get_session_status(host, session_id)
        elapsed = time.time() - start

        # None → session no longer listed → completed
        if status is None:
            if elapsed > 5:
                print(f"[db_admin] Session {session_id[:8]} completed "
                      f"({elapsed:.0f}s)")
                return True
            time.sleep(STATUS_POLL_INTERVAL)
            continue

        status_str = str(status).lower()

        if any(s in status_str
               for s in ("completed", "idle", "ready", "done")):
            return True
        if "error" in status_str or "failed" in status_str:
            print(f"[db_admin] Session {session_id[:8]} errored: "
                  f"{status_str}", file=sys.stderr)
            return True

        # If status is not recognisably busy, double-check once
        if not any(s in status_str
                   for s in ("busy", "pending", "running",
                             "active", "generating")):
            time.sleep(STATUS_POLL_INTERVAL)
            status2 = get_session_status(host, session_id)
            if status2 is None or not any(
                s in str(status2).lower()
                for s in ("busy", "pending", "running",
                          "active", "generating")
            ):
                return True

        time.sleep(STATUS_POLL_INTERVAL)

    print(f"[db_admin] Session {session_id[:8]} timed out after {timeout}s",
          file=sys.stderr)
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
        help="Goal text to send to the agent (default: empty string).",
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
        "--timeout", type=int,
        default=int(os.environ.get("OPENCODE_TIMEOUT", "1200")),
        help="Max seconds to wait for execution (default: 1200).",
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
    global _active_host, _active_session_id, OPENCODE_SERVER_PORT

    args = parse_args()
    goal_text = " ".join(args.goal).strip()
    host = args.host
    agent = args.agent
    timeout = args.timeout
    OPENCODE_SERVER_PORT = args.port

    execution_id = uuid4().hex
    run_id = resolve_run_id()
    base_dir = get_trident_base()
    output_dir = os.path.join(base_dir, "outputs", run_id, "benign_agent")
    os.makedirs(output_dir, exist_ok=True)
    timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")

    print(f"[db_admin] OpenCode Server API mode")
    print(f"[db_admin] Target: http://{host}:{OPENCODE_SERVER_PORT}")
    print(f"[db_admin] Agent : {agent}")
    print(f"[db_admin] Goal  : {goal_text!r}")

    write_timeline_entry(timeline_path, "INIT",
                         "db_admin execution started", data={
                             "goal": goal_text,
                             "host": host,
                             "agent": agent,
                             "exec": execution_id[:8],
                             "mode": "opencode_server_api",
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

    # ── 2. Create session ────────────────────────────────────────────
    session_id = create_session(host,
                                title=f"db_admin {execution_id[:8]}")
    if not session_id:
        msg = "Failed to create OpenCode session"
        print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
        write_timeline_entry(timeline_path, "ERROR", msg,
                             data={"exec": execution_id[:8]})
        return 1

    _active_host = host
    _active_session_id = session_id

    print(f"[db_admin] ✓ Session created: {session_id[:8]}")
    write_timeline_entry(timeline_path, "SESSION", "Session created",
                         data={"session_id": session_id,
                               "exec": execution_id[:8]})

    # ── 3. Send goal (prompt) ────────────────────────────────────────
    start_time = time.time()
    print("[db_admin] Sending prompt (async)...")
    if not send_message_async(host, session_id, goal_text, agent=agent):
        msg = "Failed to send prompt to session"
        print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
        write_timeline_entry(timeline_path, "ERROR", msg,
                             data={"session_id": session_id,
                                   "exec": execution_id[:8]})
        return 1
    print("[db_admin] ✓ Prompt sent")

    # ── 4. Wait for completion ───────────────────────────────────────
    print(f"[db_admin] Waiting for session to complete "
          f"(timeout: {timeout}s)...")
    completed = wait_for_session_complete(host, session_id,
                                         timeout=timeout)
    duration = time.time() - start_time

    if completed:
        print(f"[db_admin] ✓ Session completed in {duration:.1f}s")
    else:
        print("[db_admin] ⚠ Session did not complete within timeout")

    # ── 5. Fetch results ─────────────────────────────────────────────
    messages = get_session_messages(host, session_id)
    messages_path = os.path.join(output_dir,
                                 "opencode_api_messages.json")
    if messages:
        with open(messages_path, "w", encoding="utf-8") as fh:
            json.dump(messages, fh, indent=2)
        print(f"[db_admin] ✓ Saved {len(messages)} messages to "
              f"{messages_path}")
    else:
        print("[db_admin] ⚠ No messages retrieved")

    write_timeline_entry(timeline_path, "DONE",
                         "db_admin execution finished", data={
                             "session_id": session_id,
                             "duration_seconds": round(duration, 2),
                             "completed": completed,
                             "messages_count": (len(messages)
                                                if messages else 0),
                             "exec": execution_id[:8],
                         })

    _active_session_id = None
    print("[db_admin] Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
