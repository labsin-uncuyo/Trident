#!/usr/bin/env python3
"""
DB Admin Benign Agent – Natural Completion version

Like db_admin_opencode_client.py, this connects to the OpenCode HTTP server
already running on the compromised machine and starts a ``db_admin`` session
via the REST API.

The key difference: **no time limit and no "keep going" nudges**. The agent
runs a single session and is allowed to finish naturally when it considers
its work done. The script exits as soon as the agent signals completion (via
done-phrases like "workday is complete", "all tasks completed", etc.) or when
the session goes idle after the agent has executed at least one tool.

A ``--max-wait`` option (default: 3600s = 1 hour) acts as a safety backstop
so the script cannot hang forever if the model loops without finishing. This
is NOT a time limit on the agent's work — it is a dead-man's switch.

Usage:
    python3 db_admin_natural.py
    python3 db_admin_natural.py --max-wait 1800
    python3 db_admin_natural.py "Custom goal text"
"""

import argparse
import os
import sys
import time
from typing import Dict, List, Optional
from uuid import uuid4

import requests

# Add path to import shared base class
_shared_paths = [
    "/opt",
    os.path.join(os.path.dirname(__file__), "..", "..", "images", "shared"),
    os.path.join(os.path.dirname(__file__), "..", "..", "images"),
]
for path in _shared_paths:
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

try:
    from shared.opencode_client import OpenCodeAgent
    from shared.opencode_utils import (
        RETRY_DELAYS,
        ModelAvailabilityError,
        check_for_model_error,
    )
except ImportError:
    OpenCodeAgent = None
    RETRY_DELAYS = [1, 5, 10]
    ModelAvailabilityError = Exception

    def check_for_model_error(messages):  # type: ignore
        pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OPENCODE_SERVER_PORT = int(os.getenv("OPENCODE_SERVER_PORT", "4096"))
OPENCODE_SERVER_HOST = "127.0.0.1"
DEFAULT_AGENT = "db_admin"
STATUS_POLL_INTERVAL = float(os.getenv("OPENCODE_STATUS_POLL_INTERVAL", "3"))

DEFAULT_MAX_WAIT = 3600  # Safety backstop: 1 hour

DEFAULT_GOAL = """Start your workday. Connect to the database server via the jump host and begin your daily tasks.

WEB RESEARCH (use curl frequently, always pipe through grep): Research these URLs throughout your session:
curl -s https://www.postgresql.org/docs/current/ | sed 's/<[^>]>//g' | grep -i "keyword" | head -20
curl -s https://wiki.postgresql.org/wiki/Main_Page | sed 's/<[^>]>//g' | grep -iv "edit|login|search" | head -20
curl -s https://www.postgresqltutorial.com/ | sed 's/<[^>]>//g' | head -20
curl -s https://planet.postgresql.org/ | sed 's/<[^>]>//g' | head -20


TIMING: sleep 60-130 between tasks to simulate coffee breaks, go to the bathroom, and natural work pacing.

DATABASE TASKS: Check table structure, INSERT new employees, UPDATE salaries, DELETE obsolete records, run monitoring queries. After each web research session, execute at least one database operation.

LOOP: This workday has no defined end. After completing a full cycle of research + DB operations, start a new cycle with different keywords and different data modifications. Repeat indefinitely.

To use postgres, connect via PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb


Examples:
  # List all databases
  PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb -c "\l"
  # List all tables
  PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb -c "\dt"
  # List all schemas
  PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb -c "\dn"
  # Count rows in employee table
  PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb -c "SELECT COUNT(*) FROM employee;"
  # List all columns in employee table
  PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'employee';
  """


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run db_admin benign agent via OpenCode Server API with "
            "natural completion (no time limit, no forced nudges)."
        ),
    )
    parser.add_argument(
        "goal",
        nargs="*",
        default=[""],
        help="Goal text to send to the agent (default: built-in db_admin goal).",
    )
    parser.add_argument(
        "--host",
        default=OPENCODE_SERVER_HOST,
        help=f"OpenCode server host (default: {OPENCODE_SERVER_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=OPENCODE_SERVER_PORT,
        help=f"OpenCode server port (default: {OPENCODE_SERVER_PORT}).",
    )
    parser.add_argument(
        "--agent",
        default=DEFAULT_AGENT,
        help=f"Agent name (default: {DEFAULT_AGENT}).",
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=DEFAULT_MAX_WAIT,
        help=(
            "Safety backstop: maximum wall-clock seconds to wait for the "
            "agent to finish naturally (default: 3600 = 1 hour). This is "
            "NOT a time limit on the agent's work — it prevents the script "
            "from hanging forever if the model loops."
        ),
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=5,
        help=(
            "Maximum number of sessions to start (default: 5). Each new "
            "session is forked from the previous one for context continuity. "
            "If the agent exhausts all sessions without finishing, the "
            "script exits."
        ),
    )
    # Kept for backward-compatibility with callers that still pass these.
    parser.add_argument("--container", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--user", default=None, help=argparse.SUPPRESS)
    # Accept --time-limit silently (ignored — this script has no time limit).
    parser.add_argument(
        "--time-limit",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helper: count tool calls in messages
# ---------------------------------------------------------------------------
def _count_tool_parts(messages: Optional[List]) -> int:
    """Count the number of tool-use parts in a list of OpenCode messages."""
    if not messages:
        return 0
    count = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        parts = msg.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "tool":
                count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    goal_text = " ".join(args.goal).strip()
    if not goal_text:
        goal_text = DEFAULT_GOAL

    max_wait = args.max_wait

    if OpenCodeAgent is None:
        print(
            "[db_admin] ERROR: shared.opencode_client not available",
            file=sys.stderr,
        )
        return 1

    # Initialize the OpenCode agent
    agent = OpenCodeAgent(
        host=args.host,
        port=args.port,
        agent=args.agent,
        status_poll_interval=STATUS_POLL_INTERVAL,
    )

    execution_id = uuid4().hex
    run_id = agent.resolve_run_id()
    base_dir = agent.get_trident_base()
    output_dir = os.path.join(base_dir, "outputs", run_id, "benign_agent")
    os.makedirs(output_dir, exist_ok=True)
    timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")

    agent._signal_log_ctx = {
        "output_dir": output_dir,
        "timeline_path": timeline_path,
        "execution_id": execution_id,
        "session_count": 0,
    }

    print("[db_admin] OpenCode Server API mode (natural completion)")
    print(f"[db_admin] Logs  : {output_dir}")
    print(f"[db_admin] Target: http://{agent.host}:{agent.port}")
    print(f"[db_admin] Agent : {agent.agent}")
    print(f"[db_admin] Goal  : {goal_text!r}")
    print(f"[db_admin] Max wait: {max_wait}s (safety backstop, not a time limit)")
    print(f"[db_admin] Max sessions: {args.max_sessions}")

    agent._write_timeline_entry(
        timeline_path,
        "INIT",
        "db_admin execution started (natural completion)",
        data={
            "goal": goal_text,
            "host": agent.host,
            "agent": agent.agent,
            "exec": execution_id[:8],
            "mode": "opencode_server_api_natural",
            "max_wait": max_wait,
            "max_sessions": args.max_sessions,
        },
    )

    # ── 1. Wait for OpenCode server ──────────────────────────────────
    print("[db_admin] Waiting for OpenCode server...")
    if not agent.wait_for_server(timeout=120):
        msg = f"OpenCode server not available at {agent.host}:{agent.port}"
        print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
        agent._write_timeline_entry(timeline_path, "ERROR", msg, data={"exec": execution_id[:8]})
        return 1
    print("[db_admin] ✓ OpenCode server healthy")

    # ── 2. Session loop — let the agent finish naturally ─────────────
    execution_start = time.time()
    all_session_messages: List[Dict] = []
    session_count = 0
    prev_session_id: Optional[str] = None
    agent_finished = False

    while session_count < args.max_sessions:
        # Safety backstop: if we've been waiting too long, stop.
        elapsed = time.time() - execution_start
        if elapsed >= max_wait:
            print(
                f"[db_admin] Safety backstop reached ({elapsed:.0f}s/{max_wait}s) "
                f"— stopping. The agent did not signal completion within the "
                f"backstop window."
            )
            break

        session_count += 1
        is_forked = False

        # ── Create session (fork previous for continuity, or new) ────
        if prev_session_id is not None:
            print(
                f"[db_admin] Session {session_count}: forking from "
                f"{prev_session_id[:12]}..."
            )
            session_id = agent.fork_session(prev_session_id)
            if session_id:
                is_forked = True
            else:
                print("[db_admin] Fork failed, creating fresh session...")
                session_id = agent.create_session(
                    title=f"db_admin {execution_id[:8]} s{session_count}"
                )
        else:
            session_id = agent.create_session(
                title=f"db_admin {execution_id[:8]}"
            )

        if not session_id:
            msg = f"Failed to create session {session_count}"
            print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
            agent._write_timeline_entry(
                timeline_path,
                "ERROR",
                msg,
                data={"exec": execution_id[:8], "session_num": session_count},
            )
            return 1

        agent._active_session_id = session_id
        agent._signal_log_ctx["session_count"] = session_count

        print(
            f"[db_admin] ✓ Session {session_count} created: "
            f"{session_id[:12]} ({'forked' if is_forked else 'new'})"
        )
        agent._write_timeline_entry(
            timeline_path,
            "SESSION",
            f"Session {session_count} created",
            data={
                "session_id": session_id,
                "session_num": session_count,
                "forked_from": prev_session_id if is_forked else None,
                "exec": execution_id[:8],
            },
        )

        # ── Build prompt for this session ────────────────────────────
        if session_count == 1:
            prompt = goal_text
        else:
            # Context continuity: remind the agent of its task and let it
            # continue / finish as it sees fit. No "keep going" pressure.
            if is_forked:
                prompt = (
                    f"Continue your workday from where you left off. "
                    f"Here is your task:\n\n{goal_text}\n\n"
                    f"If you have already completed your tasks, say so."
                )
            else:
                prev_ctx = ""
                if all_session_messages:
                    last_msgs = all_session_messages[-1].get("messages")
                    prev_ctx = agent.extract_context_from_messages(last_msgs)
                context_block = ""
                if prev_ctx:
                    context_block = f"\n\nHere is context from your previous session:\n{prev_ctx}"
                prompt = (
                    f"Continue your workday. Here is your task:\n\n"
                    f"{goal_text}{context_block}\n\n"
                    f"If you have already completed your tasks, say so."
                )

        # ── Send the prompt and wait for the session to complete ─────
        # Unlike the time-limited version, we send ONE prompt per session
        # and wait for the agent to finish on its own. No "keep going"
        # nudges are sent. The agent decides when it's done.
        session_start = time.time()
        turn_label = f"s{session_count}t1"
        print(f"[db_admin] [{turn_label}] Sending prompt...")
        if not agent.send_message_async(session_id, prompt):
            print(f"[db_admin] [{turn_label}] Failed to send prompt", file=sys.stderr)
            break
        print(f"[db_admin] [{turn_label}] Prompt sent, waiting for agent to finish...")

        # Live logging thread for real-time dashboard updates
        import threading

        _stop_live_logging = threading.Event()

        def _live_log_saver():
            while not _stop_live_logging.is_set():
                try:
                    agent.save_session_logs(
                        session_id,
                        output_dir,
                        timeline_path,
                        execution_id,
                        session_count,
                    )
                except Exception:
                    pass
                _stop_live_logging.wait(2.0)

        _live_log_thread = threading.Thread(target=_live_log_saver, daemon=True)
        _live_log_thread.start()

        # Wait for the session to complete. Use a generous per-session
        # timeout derived from the remaining backstop budget.
        remaining_backstop = max_wait - (time.time() - execution_start)
        session_timeout = int(max(remaining_backstop, 120))
        completed = agent.wait_for_session_complete(
            session_id, timeout=session_timeout
        )

        _stop_live_logging.set()
        _live_log_thread.join(timeout=1)

        session_duration = time.time() - session_start

        if not completed:
            print(f"[db_admin] [{turn_label}] Session timed out")
        else:
            print(
                f"[db_admin] [{turn_label}] Session completed naturally "
                f"({session_duration:.0f}s)"
            )

        # ── Check for context window overflow ────────────────────────
        context_overflow = False
        if agent._last_wait_error and agent.is_context_overflow(agent._last_wait_error):
            print(
                f"[db_admin] [{turn_label}] Context window overflow "
                f"— summarizing session {session_id[:12]}...",
                file=sys.stderr,
            )
            if agent.summarize_session(session_id):
                print(f"[db_admin] [{turn_label}] Session summarized")
                agent._last_wait_error = None
                # Don't count this as a finished session — continue to next
                context_overflow = True
            else:
                print(
                    f"[db_admin] [{turn_label}] Summarization failed, "
                    f"will start a fresh session",
                    file=sys.stderr,
                )
                context_overflow = True

        # ── Fetch messages and check if the agent is done ────────────
        messages = agent.get_session_messages(session_id)

        # Check for model availability errors
        model_error = check_for_model_error(messages)
        if model_error:
            print(
                f"[db_admin] [{turn_label}] Model availability error: "
                f"{model_error[:100]}",
                file=sys.stderr,
            )
            agent._write_timeline_entry(
                timeline_path,
                "ERROR",
                f"Model error: {model_error[:200]}",
                data={"exec": execution_id[:8], "session_num": session_count},
            )
            break

        # Save session logs
        log_result = agent.save_session_logs(
            session_id,
            output_dir,
            timeline_path,
            execution_id,
            session_count,
        )
        if messages:
            all_session_messages.append({
                "session_id": session_id,
                "session_num": session_count,
                "forked_from": prev_session_id if is_forked else None,
                "messages": messages,
            })

        tool_count = _count_tool_parts(messages)
        llm_calls = log_result.get("llm_calls", 0) if log_result else 0
        tool_calls = len(log_result.get("tool_calls", [])) if log_result else 0

        print(
            f"[db_admin] ✓ Session {session_count}: "
            f"{len(messages) if messages else 0} messages, "
            f"{tool_count} tool parts, {session_duration:.0f}s"
        )
        if log_result and log_result.get("llm_calls"):
            print(
                f"[db_admin]   LLM calls: {llm_calls}, "
                f"tool calls: {tool_calls}, "
                f"cost: ${log_result.get('total_cost', 0):.4f}"
            )

        # ── Check if the agent signaled completion ───────────────────
        last_text = agent.get_last_assistant_text(messages)
        snippet = last_text[:200].replace("\n", " ") if last_text else "(no text)"
        print(f"[db_admin]   Last response: {snippet}...")

        agent_done = agent.agent_says_done(messages)
        if agent_done:
            print(
                f"[db_admin] ✓ Agent signaled task completion — "
                f"stopping naturally."
            )
            agent_finished = True

        agent._write_timeline_entry(
            timeline_path,
            "SESSION_END",
            f"Session {session_count} ended",
            data={
                "session_id": session_id,
                "session_num": session_count,
                "duration_seconds": round(session_duration, 2),
                "agent_done": agent_done,
                "context_overflow": context_overflow,
                "messages_count": len(messages) if messages else 0,
                "tool_parts": tool_count,
                "exec": execution_id[:8],
            },
        )

        if agent_finished:
            break

        if context_overflow:
            prev_session_id = None
            print("[db_admin] Starting fresh session after context overflow...")
            continue

        # The session completed without an explicit done-phrase. Check if
        # the agent actually did work (tool calls) — if so, it may have
        # finished naturally without saying a done-phrase. If it did
        # nothing (0 tools), start a new session to give it another chance.
        if tool_count == 0 and not last_text:
            print(
                "[db_admin] Session produced no output — "
                "starting a new session..."
            )
            prev_session_id = session_id
        else:
            # The agent did some work but didn't say an explicit done-phrase.
            # Fork the session and let it continue with a fresh prompt.
            prev_session_id = session_id
            print(
                "[db_admin] Session completed without explicit done-phrase. "
                "Forking to continue..."
            )

    # ── 3. Final summary ─────────────────────────────────────────────
    total_duration = time.time() - execution_start
    messages_path = os.path.join(output_dir, "opencode_api_messages.json")
    if all_session_messages:
        total_msg_count = sum(len(s["messages"]) for s in all_session_messages)
        print(
            f"[db_admin] ✓ {total_msg_count} messages from "
            f"{session_count} session(s) saved → {messages_path}"
        )
    else:
        print("[db_admin] ⚠ No messages retrieved")

    agent._write_timeline_entry(
        timeline_path,
        "DONE",
        "db_admin execution finished",
        data={
            "total_sessions": session_count,
            "total_duration_seconds": round(total_duration, 2),
            "agent_finished": agent_finished,
            "exec": execution_id[:8],
        },
    )

    agent._active_session_id = None
    status = "finished naturally" if agent_finished else "stopped (backstop/limit)"
    print(
        f"[db_admin] Done. {session_count} session(s), "
        f"{total_duration:.1f}s total. Agent {status}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
