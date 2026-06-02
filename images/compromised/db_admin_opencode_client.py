#!/usr/bin/env python3
"""
DB Admin Benign Agent – OpenCode Server API version

Connects to the OpenCode HTTP server already running on the compromised
machine and starts a ``db_admin`` session via the REST API.

Replaces the previous ``docker exec`` + ``opencode run`` approach with
direct HTTP calls to the OpenCode server (port 4096 by default).

Now uses the shared OpenCodeAgent base class for common functionality.
"""

import argparse
import os
import sys
import time
from typing import Dict, List, Optional
from uuid import uuid4

import requests

# Add path to import shared base class
# Try multiple possible locations for the shared module
_shared_paths = [
    "/opt",  # Inside Docker container (shared is at /opt/shared/)
    os.path.join(os.path.dirname(__file__), "..", "..", "images", "shared"),  # Local development
    os.path.join(os.path.dirname(__file__), "..", "..", "images"),  # Alternative local dev
]
for path in _shared_paths:
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

try:
    from shared.opencode_client import OpenCodeAgent
    from shared.opencode_utils import RETRY_DELAYS, ModelAvailabilityError, check_for_model_error
except ImportError:
    # Fallback if shared module not available
    OpenCodeAgent = None
    RETRY_DELAYS = [1, 5, 10]
    ModelAvailabilityError = Exception
    def check_for_model_error(messages): pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OPENCODE_SERVER_PORT = int(os.getenv("OPENCODE_SERVER_PORT", "4096"))
OPENCODE_SERVER_HOST = "127.0.0.1"
DEFAULT_AGENT = "db_admin"
STATUS_POLL_INTERVAL = float(os.getenv("OPENCODE_STATUS_POLL_INTERVAL", "3"))

# Default goal for the db_admin agent when none is provided
DEFAULT_GOAL = """Start your workday. Connect to the database server via the jump host and begin your daily tasks.

WEB RESEARCH (use curl frequently, always pipe through grep): Research these URLs throughout your session:
curl -s https://www.postgresql.org/docs/current/ | sed 's/<[^>]>//g' | grep -i "keyword" | head -20
curl -s https://wiki.postgresql.org/wiki/Main_Page | sed 's/<[^>]>//g' | grep -iv "edit|login|search" | head -20
curl -s https://www.postgresqltutorial.com/ | sed 's/<[^>]>//g' | head -20
curl -s https://planet.postgresql.org/ | sed 's/<[^>]>//g' | head -20


TIMING: sleep 60-130 between tasks to simulate coffee breaks, go to the bathroom, and natural work pacing.

DATABASE TASKS: Check table structure, INSERT new employees, UPDATE salaries, DELETE obsolete records, run monitoring queries. After each web research session, execute at least one database operation.

LOOP: This workday has no defined end. After completing a full cycle of research + DB operations, start a new cycle with different keywords and different data modifications. Repeat indefinitely.
To conect use: PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb"""
_MIN_REMAINING_SECONDS = 30  # Don't start a new session with less time left


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
        "--host", default=OPENCODE_SERVER_HOST,
        help=f"OpenCode server host (default: {OPENCODE_SERVER_HOST}).",
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
    args = parse_args()
    goal_text = " ".join(args.goal).strip()
    if not goal_text:
        goal_text = DEFAULT_GOAL

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

    # Expose log context so signal handler can flush on exit
    agent._signal_log_ctx = {
        "output_dir": output_dir,
        "timeline_path": timeline_path,
        "execution_id": execution_id,
        "session_count": 0,
    }

    print(f"[db_admin] OpenCode Server API mode")
    print(f"[db_admin] Logs  : {output_dir}")
    print(f"[db_admin] Target: http://{agent.host}:{agent.port}")
    print(f"[db_admin] Agent : {agent.agent}")
    print(f"[db_admin] Goal  : {goal_text!r}")
    if args.time_limit is not None:
        print(f"[db_admin] Time limit: {args.time_limit}s")
    else:
        print(f"[db_admin] Time limit: None (indefinite execution)")

    agent._write_timeline_entry(timeline_path, "INIT",
                         "db_admin execution started", data={
                             "goal": goal_text,
                             "host": agent.host,
                             "agent": agent.agent,
                             "exec": execution_id[:8],
                             "mode": "opencode_server_api",
                             "time_limit": args.time_limit,
                         })

    # ── 1. Wait for OpenCode server ──────────────────────────────────
    print("[db_admin] Waiting for OpenCode server...")
    if not agent.wait_for_server(timeout=120):
        msg = (f"OpenCode server not available at "
               f"{agent.host}:{agent.port}")
        print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
        agent._write_timeline_entry(timeline_path, "ERROR", msg,
                             data={"exec": execution_id[:8]})
        return 1
    print("[db_admin] ✓ OpenCode server healthy")

    # ── 2. Session loop – keep launching sessions until time limit ───
    execution_start = time.time()
    all_session_messages: List[Dict] = []
    session_count = 0
    prev_session_id: Optional[str] = None
    time_limit = args.time_limit

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
            remaining = float('inf')

        session_count += 1
        is_forked = False

        # ── Create session (fork previous for continuity, or new) ────
        if prev_session_id is not None:
            print(f"[db_admin] Session {session_count}: forking from "
                  f"{prev_session_id[:12]}...")
            session_id = agent.fork_session(prev_session_id)
            if session_id:
                is_forked = True
            else:
                print("[db_admin] Fork failed, creating fresh session "
                      "with context...")
                session_id = agent.create_session(
                    title=f"db_admin {execution_id[:8]} s{session_count}")
        else:
            session_id = agent.create_session(
                title=f"db_admin {execution_id[:8]}")

        if not session_id:
            msg = f"Failed to create session {session_count}"
            print(f"[db_admin] ERROR: {msg}", file=sys.stderr)
            agent._write_timeline_entry(timeline_path, "ERROR", msg,
                                 data={"exec": execution_id[:8],
                                        "session_num": session_count})
            return 1

        agent._active_session_id = session_id
        agent._signal_log_ctx["session_count"] = session_count

        print(f"[db_admin] ✓ Session {session_count} created: "
              f"{session_id[:12]} ({'forked' if is_forked else 'new'})")
        agent._write_timeline_entry(
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
                    prev_ctx = agent.extract_context_from_messages(last_msgs)
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
                turn_remaining = float('inf')

            # Send prompt
            turn_label = f"s{session_count}t{turn}"
            print(f"[db_admin] [{turn_label}] Sending prompt...")
            if not agent.send_message_async(session_id, prompt):
                print(f"[db_admin] [{turn_label}] Failed to send prompt",
                      file=sys.stderr)
                break
            print(f"[db_admin] [{turn_label}] Prompt sent, waiting...")

            # ── Start background thread to save logs every 2 seconds for real-time dashboard ──
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
                        pass  # Silently fail if session isn't ready yet
                    _stop_live_logging.wait(2.0)  # Save every 2 seconds
            _live_log_thread = threading.Thread(target=_live_log_saver, daemon=True)
            _live_log_thread.start()

            # Wait for this turn to finish
            if time_limit is not None:
                turn_timeout = max(int(turn_remaining), 60)
            else:
                turn_timeout = 3600  # 1 hour per turn when no limit
            completed = agent.wait_for_session_complete(
                session_id, timeout=turn_timeout)

            # ── Stop live logging ──
            _stop_live_logging.set()
            _live_log_thread.join(timeout=1)

            turn_duration = time.time() - session_start

            if not completed:
                print(f"[db_admin] [{turn_label}] Timed out")
                break

            # ── Check for context window overflow ────────────────────
            # Summarize the session in-place so it can keep running;
            # only abandon to a fresh session if summarization fails.
            if agent._last_wait_error and agent.is_context_overflow(agent._last_wait_error):
                print(f"[db_admin] [{turn_label}] Context window overflow "
                      f"– summarizing session {session_id[:12]}...",
                      file=sys.stderr)
                if agent.summarize_session(session_id):
                    print(f"[db_admin] [{turn_label}] Session summarized, "
                          f"retrying prompt...")
                    agent._last_wait_error = None
                    continue  # retry same prompt in the now-compact session
                # Summarization failed – fall back to a fresh session
                print(f"[db_admin] [{turn_label}] Summarization failed, "
                      f"will start a fresh session", file=sys.stderr)
                context_overflow = True
                prev_session_id = None  # prevent fork in outer loop
                break  # end inner turn loop → outer loop starts fresh session

            # Fetch messages and inspect the agent's last response
            messages = agent.get_session_messages(session_id)

            # Check for model availability errors
            model_error = check_for_model_error(messages)
            if model_error:
                print(f"[db_admin] [{turn_label}] Model availability error: {model_error[:100]}",
                      file=sys.stderr)
                # Model errors are not recoverable in the continuous loop
                # Fall back to starting a new session in the outer loop
                context_overflow = True
                prev_session_id = None
                break

            last_text = agent.get_last_assistant_text(messages)
            snippet = last_text[:200].replace("\n", " ")
            print(f"[db_admin] [{turn_label}] Agent responded "
                  f"({turn_duration:.0f}s): {snippet}...")

            # Check if the agent considers itself done
            if agent.agent_says_done(messages):
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
        log_result = agent.save_session_logs(
            session_id,
            output_dir,
            timeline_path,
            execution_id,
            session_count,
        )
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

        agent._write_timeline_entry(
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

    agent._write_timeline_entry(timeline_path, "DONE",
                         "db_admin execution finished", data={
                             "total_sessions": session_count,
                             "total_duration_seconds":
                                 round(total_duration, 2),
                             "exec": execution_id[:8],
                         })

    agent._active_session_id = None
    print(f"[db_admin] Done. {session_count} session(s), "
          f"{total_duration:.1f}s total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
