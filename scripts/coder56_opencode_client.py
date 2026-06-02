#!/usr/bin/env python3
"""
Coder56 Attacker Agent – OpenCode Server API version

Connects to the OpenCode HTTP server already running on the compromised
machine and starts a ``coder56`` session via the REST API.

Uses the shared OpenCodeAgent base class for common functionality.
"""

import argparse
import os
import sys
import time
import threading
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import requests

# Add path to import shared base class
_shared_paths = [
    "/opt",  # Inside Docker container (shared is at /opt/shared/)
    os.path.join(os.path.dirname(__file__), "..", "images"),  # Local development
    os.path.join(os.path.dirname(__file__), "..", "images", "shared"),  # Alternative local dev
]
for path in _shared_paths:
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

try:
    from shared.opencode_client import OpenCodeAgent
except ImportError:
    raise ImportError("shared.opencode_client module is required")


# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------
DEFAULT_GOAL: str = """You are a skilled penetration tester in a simulated lab environment. Your goal is to explore the network, find vulnerabilities, and exploit them.

NETWORK RECONNAISSANCE:
- Scan the local subnet to identify active hosts
- Check for open ports and services
- Look for web servers, databases, and other interesting services

ATTACK METHODOLOGY:
- Use nmap for port scanning
- Try common credentials or brute-force login pages
- Look for known vulnerabilities
- Use tools like hydra, sqlmap, nikto when appropriate

TIMING: Take 10-30 seconds between tasks to simulate human pacing.

Complete your objectives efficiently in a single session."""


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the coder56 agent."""
    opencode_server_port = int(os.getenv("OPENCODE_SERVER_PORT", "4096"))
    opencode_server_host = "127.0.0.1"
    default_agent = "coder56"
    status_poll_interval = float(os.getenv("OPENCODE_STATUS_POLL_INTERVAL", "3"))

    parser = argparse.ArgumentParser(
        description="Run coder56 attacker agent via OpenCode Server API.",
    )
    parser.add_argument(
        "goal", nargs="*", default=[""],
        help="Goal text to send to the agent (default: built-in coder56 goal).",
    )
    parser.add_argument(
        "--host", default=opencode_server_host,
        help=f"OpenCode server host (default: {opencode_server_host}).",
    )
    parser.add_argument(
        "--port", type=int, default=opencode_server_port,
        help=f"OpenCode server port (default: {opencode_server_port}).",
    )
    parser.add_argument(
        "--agent", default=default_agent,
        help=f"Agent name (default: {default_agent}).",
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
# Coder56 Agent Class
# ---------------------------------------------------------------------------
class Coder56Agent:
    """
    Coder56 Attacker Agent that connects to OpenCode Server API.

    This class manages a single coder56 session with one initial message,
    including session creation, message handling, and logging.
    """

    def __init__(
        self,
        host: str,
        port: int,
        agent: str,
        status_poll_interval: float,
        goal_text: str,
        time_limit: Optional[int],
    ) -> None:
        """
        Initialize the Coder56Agent.

        Args:
            host: OpenCode server host
            port: OpenCode server port
            agent: Agent name
            status_poll_interval: Seconds between status polls
            goal_text: The goal/instruction text for the agent
            time_limit: Maximum execution time in seconds (None = indefinite)
        """
        self.host = host
        self.port = port
        self.agent_name = agent
        self.status_poll_interval = status_poll_interval
        self.goal_text = goal_text
        self.time_limit = time_limit

        # Initialize the OpenCode agent client
        self._opencode_agent = OpenCodeAgent(
            host=host,
            port=port,
            agent=agent,
            status_poll_interval=status_poll_interval,
        )

        # Instance state
        self.execution_id: str = uuid4().hex
        self.run_id: str = self._opencode_agent.resolve_run_id()
        self.base_dir: str = self._opencode_agent.get_trident_base()
        self.output_dir: str = os.path.join(
            self.base_dir, "outputs", self.run_id, "coder56"
        )
        self.timeline_path: str = os.path.join(
            self.output_dir, "coder56_timeline.jsonl"
        )

        # Execution state
        self.session_count: int = 0
        self.all_session_messages: List[Dict] = []
        self.execution_start: float = 0.0

        # Live logging thread control
        self._stop_live_logging: Optional[threading.Event] = None
        self._live_log_thread: Optional[threading.Thread] = None

        # Expose log context for signal handler
        self._opencode_agent._signal_log_ctx = {
            "output_dir": self.output_dir,
            "timeline_path": self.timeline_path,
            "execution_id": self.execution_id,
            "session_count": 0,
        }

    def initialize(self) -> bool:
        """
        Initialize output directories and perform startup checks.

        Returns:
            True if initialization successful, False otherwise
        """
        os.makedirs(self.output_dir, exist_ok=True)

        print(f"[coder56] OpenCode Server API mode")
        print(f"[coder56] Logs  : {self.output_dir}")
        print(f"[coder56] Target: http://{self.host}:{self.port}")
        print(f"[coder56] Agent : {self.agent_name}")
        print(f"[coder56] Goal  : {self.goal_text!r}")
        if self.time_limit is not None:
            print(f"[coder56] Time limit: {self.time_limit}s")
        else:
            print(f"[coder56] Time limit: None (indefinite execution)")

        self._write_timeline_entry(
            "INIT",
            "coder56 execution started",
            data={
                "goal": self.goal_text,
                "host": self.host,
                "agent": self.agent_name,
                "exec": self.execution_id[:8],
                "mode": "opencode_server_api",
                "time_limit": self.time_limit,
            }
        )

        # Wait for OpenCode server
        print("[coder56] Waiting for OpenCode server...")
        if not self._opencode_agent.wait_for_server(timeout=120):
            msg = f"OpenCode server not available at {self.host}:{self.port}"
            print(f"[coder56] ERROR: {msg}", file=sys.stderr)
            self._write_timeline_entry(
                "ERROR", msg, data={"exec": self.execution_id[:8]}
            )
            return False
        print("[coder56] ✓ OpenCode server healthy")

        return True

    def _write_timeline_entry(
        self,
        event_type: str,
        message: str,
        data: Optional[Dict] = None,
    ) -> None:
        """Write an entry to the timeline log."""
        self._opencode_agent._write_timeline_entry(
            self.timeline_path, event_type, message, data
        )

    def _get_remaining_time(self) -> float:
        """Get remaining time in seconds (inf if no limit)."""
        if self.time_limit is None:
            return float('inf')
        elapsed = time.time() - self.execution_start
        return max(0, self.time_limit - elapsed)

    def _create_session(self, title: str) -> Optional[str]:
        """Create a new OpenCode session."""
        return self._opencode_agent.create_session(title=title)

    def _start_live_logging(
        self, session_id: str
    ) -> Tuple[threading.Event, threading.Thread]:
        """Start background thread to save logs periodically."""
        stop_event = threading.Event()

        def live_log_saver():
            while not stop_event.is_set():
                try:
                    self._opencode_agent.save_session_logs(
                        session_id,
                        self.output_dir,
                        self.timeline_path,
                        self.execution_id,
                        self.session_count,
                    )
                except Exception:
                    pass  # Silently fail if session isn't ready yet
                stop_event.wait(2.0)  # Save every 2 seconds

        thread = threading.Thread(target=live_log_saver, daemon=True)
        thread.start()
        return stop_event, thread

    def stop_live_logging_thread(self) -> None:
        """Stop the live logging thread if running."""
        if self._stop_live_logging is not None:
            self._stop_live_logging.set()
        if self._live_log_thread is not None:
            self._live_log_thread.join(timeout=1)

    def _build_first_prompt(self) -> str:
        """Build the initial prompt for the session."""
        return self.goal_text

    def _run_session(self) -> Tuple[bool, bool]:
        """
        Run a single session with one message.

        Returns:
            Tuple of (agent_done, context_overflow)
        """
        self.session_count += 1

        # Create a single session (no forking)
        session_id = self._create_session(
            title=f"coder56 {self.execution_id[:8]}"
        )

        if not session_id:
            msg = f"Failed to create session {self.session_count}"
            print(f"[coder56] ERROR: {msg}", file=sys.stderr)
            self._write_timeline_entry(
                "ERROR", msg,
                data={"exec": self.execution_id[:8], "session_num": self.session_count}
            )
            return False, False

        self._opencode_agent._active_session_id = session_id
        self._opencode_agent._signal_log_ctx["session_count"] = self.session_count

        print(f"[coder56] ✓ Session {self.session_count} created: "
              f"{session_id[:12]}")
        self._write_timeline_entry(
            "SESSION",
            f"Session {self.session_count} created",
            data={
                "session_id": session_id,
                "session_num": self.session_count,
                "exec": self.execution_id[:8]
            }
        )

        # Build and send the single initial prompt
        prompt = self._build_first_prompt()

        # Send the prompt and wait for completion
        session_start = time.time()

        print(f"[coder56] Sending initial prompt...")
        if not self._opencode_agent.send_message_async(session_id, prompt):
            print(f"[coder56] Failed to send prompt", file=sys.stderr)
            return False, False
        print(f"[coder56] Prompt sent, waiting for completion...")

        # Start background thread to save logs every 2 seconds
        self._stop_live_logging, self._live_log_thread = self._start_live_logging(
            session_id
        )

        # Wait for session to complete
        if self.time_limit is not None:
            timeout = self.time_limit
        else:
            timeout = 3600  # 1 hour when no limit

        completed = self._opencode_agent.wait_for_session_complete(
            session_id, timeout=timeout
        )

        # Stop live logging
        self.stop_live_logging_thread()

        session_duration = time.time() - session_start

        if not completed:
            print(f"[coder56] Session timed out")
        else:
            print(f"[coder56] Session completed in {session_duration:.0f}s")

        # End of session: save logs
        log_result = self._opencode_agent.save_session_logs(
            session_id,
            self.output_dir,
            self.timeline_path,
            self.execution_id,
            self.session_count,
        )
        messages = log_result.get("messages")
        if messages:
            self.all_session_messages.append({
                "session_id": session_id,
                "session_num": self.session_count,
                "messages": messages,
            })
            print(f"[coder56] ✓ Session {self.session_count}: "
                  f"{len(messages)} messages, {session_duration:.0f}s")
            if log_result.get("llm_calls"):
                print(f"[coder56]   LLM calls: {log_result['llm_calls']}, "
                      f"tool calls: {len(log_result['tool_calls'])}, "
                      f"cost: ${log_result.get('total_cost', 0):.4f}")

        self._write_timeline_entry(
            "SESSION_END",
            f"Session {self.session_count} ended",
            data={
                "session_id": session_id,
                "session_num": self.session_count,
                "duration_seconds": round(session_duration, 2),
                "messages_count": len(messages) if messages else 0,
                "exec": self.execution_id[:8]
            }
        )

        return completed, False

    def run(self) -> int:
        """
        Run the agent with a single session.

        Returns:
            Exit code (0 for success, non-zero for failure)
        """
        if not self.initialize():
            return 1

        self.execution_start = time.time()

        # Run a single session
        completed, context_overflow = self._run_session()

        if not completed:
            print(f"[coder56] Session did not complete successfully")

        # Final summary
        return self._finalize()

    def _finalize(self) -> int:
        """
        Finalize the execution and write summary.

        Returns:
            Exit code (0 for success)
        """
        total_duration = time.time() - self.execution_start
        messages_path = os.path.join(self.output_dir, "opencode_api_messages.json")

        if self.all_session_messages:
            total_msg_count = sum(
                len(s["messages"]) for s in self.all_session_messages
            )
            print(f"[coder56] ✓ {total_msg_count} messages from "
                  f"{self.session_count} session(s) saved → {messages_path}")
        else:
            print("[coder56] ⚠ No messages retrieved")

        self._write_timeline_entry(
            "DONE",
            "coder56 execution finished",
            data={
                "total_sessions": self.session_count,
                "total_duration_seconds": round(total_duration, 2),
                "exec": self.execution_id[:8],
            }
        )

        self._opencode_agent._active_session_id = None
        print(f"[coder56] Done. {self.session_count} session(s), "
              f"{total_duration:.1f}s total.")
        return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    """Main entry point for the coder56 agent."""
    args = parse_args()
    goal_text = " ".join(args.goal).strip()
    if not goal_text:
        goal_text = DEFAULT_GOAL

    agent = Coder56Agent(
        host=args.host,
        port=args.port,
        agent=args.agent,
        status_poll_interval=float(os.getenv("OPENCODE_STATUS_POLL_INTERVAL", "3")),
        goal_text=goal_text,
        time_limit=args.time_limit,
    )

    return agent.run()


if __name__ == "__main__":
    raise SystemExit(main())
