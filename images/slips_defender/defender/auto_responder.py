#!/usr/bin/env python3
"""
Automated Response Orchestrator (OpenCode Server API version)

This component bridges SLIPS alerts with OpenCode execution:
1. Monitors defender_alerts.ndjson for new alerts
2. Calls the planner service to generate remediation plans
3. Executes plans using OpenCode HTTP Server API on target machines
4. Tracks processed alerts to avoid duplicates

Uses the OpenCode server HTTP API (https://opencode.ai/docs/server/)
instead of SSH+pexpect for remote execution.
"""

import json
import os
import time
import threading
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import requests
import logging

# Configuration
RUN_ID = os.getenv("RUN_ID", "run_local")
ALERT_FILE = Path("/outputs") / RUN_ID / "slips" / "defender_alerts.ndjson"
PROCESSED_FILE = Path("/outputs") / RUN_ID / "processed_alerts.json"
PLANNER_URL = os.getenv("PLANNER_URL", "http://127.0.0.1:1654/plan")
OPENCODE_TIMEOUT = int(os.getenv("OPENCODE_TIMEOUT", "600"))  # 10 minutes
POLL_INTERVAL = float(os.getenv("AUTO_RESPONDER_INTERVAL", "5"))
MAX_EXECUTION_RETRIES = int(os.getenv("MAX_EXECUTION_RETRIES", "3"))
DUPLICATE_DETECTION_WINDOW = int(os.getenv("DUPLICATE_DETECTION_WINDOW", "300"))  # 5 minutes

# OpenCode Server API configuration
OPENCODE_SERVER_PORT = int(os.getenv("OPENCODE_SERVER_PORT", "4096"))

# Network topology
SERVER_IP = "172.31.0.10"
COMPROMISED_IP = "172.30.0.10"

# OpenCode status polling
OPENCODE_STATUS_POLL_INTERVAL = float(os.getenv("OPENCODE_STATUS_POLL_INTERVAL", "3"))


class AutoResponder:
    def __init__(self):
        self.processed_alerts: Set[str] = set()
        self.threat_history: Dict[str, datetime] = {}
        self.lock = threading.Lock()
        self.setup_logging()
        self.load_processed_alerts()

        # target_ip -> session_id: track one active session per host so
        # follow-up alerts reuse the same OpenCode session instead of
        # creating a brand-new one.
        self.active_sessions: Dict[str, str] = {}

        self.log("INIT", "AutoResponder started (OpenCode Server API mode)", extra_data={
            "config": {
                "alert_file": str(ALERT_FILE),
                "planner_url": PLANNER_URL,
                "poll_interval": POLL_INTERVAL,
                "opencode_timeout": OPENCODE_TIMEOUT,
                "server_ip": SERVER_IP,
                "compromised_ip": COMPROMISED_IP,
                "opencode_server_port": OPENCODE_SERVER_PORT,
                "duplicate_window": DUPLICATE_DETECTION_WINDOW,
                "mode": "opencode_server_api"
            }
        })

        print(f"[auto_responder] ✓ OpenCode Server API mode ENABLED")
        print(f"[auto_responder]   - Server: http://{SERVER_IP}:{OPENCODE_SERVER_PORT}")
        print(f"[auto_responder]   - Compromised: http://{COMPROMISED_IP}:{OPENCODE_SERVER_PORT}")

    def get_opencode_base_url(self, target_ip: str) -> str:
        """Get the OpenCode server API base URL for a target IP."""
        return f"http://{target_ip}:{OPENCODE_SERVER_PORT}"

    def write_timeline_entry(self, machine_name: str, level: str, message: str, execution_id: str = None, data: dict = None) -> None:
        """Write a timeline entry to the machine-specific timeline file."""
        timeline_path = self.get_machine_timeline_path(machine_name)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level.upper(),
            "msg": message,
        }
        if execution_id:
            entry["exec"] = execution_id[:8]
        if data:
            entry["data"] = data
        with open(timeline_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def get_machine_output_dir(self, machine_name: str) -> Path:
        output_dir = Path("/outputs") / RUN_ID / "defender" / machine_name
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_machine_timeline_path(self, machine_name: str) -> Path:
        return self.get_machine_output_dir(machine_name) / "auto_responder_timeline.jsonl"

    def setup_logging(self):
        main_output_dir = Path("/outputs") / RUN_ID / "defender"
        main_output_dir.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, message: str, machine_name: str = None, alert_hash: str = None, execution_id: str = None, extra_data: Dict = None):
        context_parts = []
        if alert_hash:
            context_parts.append(f"#{alert_hash[:8]}")
        if execution_id:
            context_parts.append(f"@{execution_id[:8]}")

        context = f" {' '.join(context_parts)}" if context_parts else ""
        log_message = f"{message}{context}"

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp} | {level.upper():8} | {log_message}")

        if machine_name:
            self.write_timeline_entry(machine_name, level, message, execution_id, extra_data)
        else:
            for machine in ["server", "compromised"]:
                self.write_timeline_entry(machine, level, message, execution_id, extra_data)

    def load_processed_alerts(self) -> None:
        try:
            if PROCESSED_FILE.exists():
                with PROCESSED_FILE.open("r") as f:
                    data = json.load(f)
                    self.processed_alerts = set(data.get("processed_hashes", []))
                    threat_history_data = data.get("threat_history", {})
                    now = datetime.now(timezone.utc)
                    for threat_hash, timestamp_str in threat_history_data.items():
                        try:
                            threat_time = datetime.fromisoformat(timestamp_str)
                            if (now - threat_time).total_seconds() < DUPLICATE_DETECTION_WINDOW:
                                self.threat_history[threat_hash] = threat_time
                        except (ValueError, TypeError):
                            continue
                print(f"[auto_responder] Loaded {len(self.processed_alerts)} processed alerts, {len(self.threat_history)} recent threats")
        except Exception as e:
            print(f"[auto_responder] Failed to load processed alerts: {e}")
            self.processed_alerts = set()
            self.threat_history = {}

    def save_processed_alerts(self) -> None:
        try:
            PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc)
            active_threats = {
                threat_hash: threat_time.isoformat()
                for threat_hash, threat_time in self.threat_history.items()
                if (now - threat_time).total_seconds() < DUPLICATE_DETECTION_WINDOW
            }
            with PROCESSED_FILE.open("w") as f:
                json.dump({
                    "processed_hashes": list(self.processed_alerts),
                    "threat_history": active_threats,
                    "last_updated": datetime.now(timezone.utc).isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"[auto_responder] Failed to save processed alerts: {e}")

    def get_alert_hash(self, alert: Dict) -> str:
        key_fields = {
            "sourceip": alert.get("sourceip", ""),
            "destip": alert.get("destip", ""),
            "attackid": alert.get("attackid", ""),
            "proto": alert.get("proto", ""),
            "timestamp": alert.get("timestamp", "")
        }
        alert_str = json.dumps(key_fields, sort_keys=True)
        return hashlib.md5(alert_str.encode()).hexdigest()

    def get_threat_hash(self, alert: Dict) -> str:
        import re
        source_ip = alert.get("sourceip", "")
        dest_ip = alert.get("destip", "")
        raw_alert = alert.get("raw", "")

        if not source_ip or not dest_ip:
            src_match = re.search(r'Src IP\s+(\d+\.\d+\.\d+\.\d+)', raw_alert)
            to_ip_match = re.search(r'to IP\s+(\d+\.\d+\.\d+\.\d+)', raw_alert)
            to_match = re.search(r'to\s+(\d+\.\d+\.\d+\.\d+):\d+', raw_alert)

            if src_match:
                source_ip = src_match.group(1)
            elif not source_ip:
                ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
                if len(ip_match) >= 1:
                    source_ip = ip_match[0]

            if to_ip_match:
                dest_ip = to_ip_match.group(1)
            elif to_match:
                dest_ip = to_match.group(1)
            elif not dest_ip:
                ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
                if len(ip_match) >= 2:
                    dest_ip = ip_match[-1] if ip_match[-1] != source_ip else ip_match[1]

        # Extract the Slips detection type from the raw alert text.
        # Slips alerts follow the pattern "Detected <description>." — we
        # normalise that phrase into a stable attack_type so that different
        # detections (e.g. "Horizontal port scan" vs "HTTP password guessing")
        # always produce distinct threat hashes, even for the same src/dst.
        attack_type = "unknown"
        raw_lower = raw_alert.lower()

        # 1. Try to extract the canonical "Detected <phrase>" from Slips
        detected_match = re.search(r'detected\s+(.+?)(?:\.|threat level|$)', raw_lower)
        if detected_match:
            phrase = detected_match.group(1).strip()
            # Normalise: collapse whitespace, strip IPs/numbers so
            # "ICMP scan on 10 hosts" and "ICMP scan on 25 hosts" hash alike
            phrase = re.sub(r'\d+\.\d+\.\d+\.\d+', '_IP_', phrase)
            phrase = re.sub(r'\b\d+\b', '_N_', phrase)
            phrase = re.sub(r'\s+', ' ', phrase).strip()
            attack_type = phrase

        # 2. Fallback keyword mapping for alerts that lack "Detected ..."
        if attack_type == "unknown":
            kw_map = [
                ("horizontal port scan", "horizontal_port_scan"),
                ("vertical port scan",   "vertical_port_scan"),
                ("password guessing",    "password_guessing"),
                ("brute force",          "brute_force"),
                ("denial of service",    "dos"),
                ("ddos",                 "dos"),
                ("icmp.*scan",           "icmp_scan"),
                ("port scan",            "port_scan"),
                ("ssh",                  "ssh_attack"),
            ]
            for pattern, label in kw_map:
                if re.search(pattern, raw_lower):
                    attack_type = label
                    break
            else:
                if alert.get("attackid"):
                    attack_type = alert.get("attackid", "unknown")

        threat_fields = {
            "source_ip": source_ip,
            "dest_ip": dest_ip,
            "attack_type": attack_type,
        }
        threat_str = json.dumps(threat_fields, sort_keys=True)
        return hashlib.md5(threat_str.encode()).hexdigest()

    def is_duplicate_threat(self, alert: Dict, alert_hash: str) -> bool:
        """Pure read-only check: is this threat already being handled?
        Does NOT mutate state — call record_threat() after successful processing."""
        threat_hash = self.get_threat_hash(alert)
        now = datetime.now(timezone.utc)

        with self.lock:
            if threat_hash in self.threat_history:
                first_seen = self.threat_history[threat_hash]
                time_since_first = (now - first_seen).total_seconds()
                if time_since_first < DUPLICATE_DETECTION_WINDOW:
                    return True
                # Window expired — allow re-processing
                return False
            return False

    def record_threat(self, alert: Dict) -> None:
        """Record a threat as actively being handled (call after successful process_alert)."""
        threat_hash = self.get_threat_hash(alert)
        now = datetime.now(timezone.utc)
        with self.lock:
            self.threat_history[threat_hash] = now

    def get_new_alerts(self) -> List[Dict]:
        if not ALERT_FILE.exists():
            return []

        new_alerts = []
        try:
            with ALERT_FILE.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        alert = json.loads(line)
                        if not self._is_high_confidence_alert(alert):
                            continue
                        alert_hash = self.get_alert_hash(alert)
                        if alert_hash in self.processed_alerts:
                            continue
                        new_alerts.append(alert)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[auto_responder] Error reading alerts file: {e}")

        return new_alerts

    def _is_high_confidence_alert(self, alert: Dict) -> bool:
        note = alert.get("note", "").lower()
        if note in ["heartbeat", "queued", "completed"]:
            return False
        if len(alert.keys()) <= 3 and "note" in alert:
            return False

        raw_alert = alert.get("raw", "").lower()
        description = alert.get("description", "").lower()
        threat_level = alert.get("threat_level", "").lower()
        alert_text = f"{raw_alert} {description} {threat_level}"

        high_confidence_patterns = [
            "confidence: 1",
            "confidence: 0.9",
            "confidence: 0.8",
            "confidence: 1.0",
            "threat level: high",
            "threat_level: high",
            "vertical port scan",
            "horizontal port scan",
            "denial of service",
            "ddos",
            "brute force",
            "password guessing"
        ]

        for pattern in high_confidence_patterns:
            if pattern in alert_text:
                return True
        return False

    def format_alert_for_planner(self, alert: Dict) -> str:
        import re
        timestamp = alert.get("timestamp", datetime.now().isoformat())
        source_ip = alert.get("sourceip", "unknown")
        dest_ip = alert.get("destip", "unknown")
        attack_id = alert.get("attackid", "unknown")
        proto = alert.get("proto", "unknown")
        description = alert.get("description", "") or alert.get("threat_level", "")

        raw_alert = alert.get("raw", "")
        if raw_alert and (source_ip == "unknown" or dest_ip == "unknown"):
            ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
            if len(ip_match) >= 2:
                source_ip, dest_ip = ip_match[0], ip_match[1]
            time_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', raw_alert)
            if time_match:
                timestamp = time_match.group(1) + '+00:00'
            attack_id = "vertical_port_scan" if "vertical port scan" in raw_alert.lower() else "unknown"
            proto = "TCP" if "TCP" in raw_alert else "unknown"
            description = raw_alert

        formatted = f"{timestamp} {source_ip} {attack_id} ({proto}) targeting {dest_ip}"
        if description:
            formatted += f" - {description}"
        return formatted

    def call_planner(self, alert_text: str) -> Optional[Dict]:
        try:
            payload = {"alert": alert_text}
            response = requests.post(PLANNER_URL, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[auto_responder] Planner request failed: {e}")
            return None

    def determine_target_info(self, executor_ip: str) -> Optional[tuple]:
        if executor_ip.startswith("172.31.0."):
            return SERVER_IP, "server"
        elif executor_ip.startswith("172.30.0."):
            return COMPROMISED_IP, "compromised"
        else:
            return SERVER_IP, "server"

    # ──────────────────────────────────────────────────────────────────
    # OpenCode Server API methods
    # ──────────────────────────────────────────────────────────────────

    def check_opencode_health(self, target_ip: str) -> bool:
        """Check if OpenCode server is healthy on target."""
        base_url = self.get_opencode_base_url(target_ip)
        try:
            resp = requests.get(f"{base_url}/global/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("healthy", False)
        except Exception:
            pass
        return False

    def wait_for_opencode_server(self, target_ip: str, timeout: int = 60) -> bool:
        """Wait for OpenCode server to become available."""
        start = time.time()
        while time.time() - start < timeout:
            if self.check_opencode_health(target_ip):
                return True
            time.sleep(2)
        return False

    def create_session(self, target_ip: str, title: str = None) -> Optional[str]:
        """Create a new OpenCode session. Returns session ID or None."""
        base_url = self.get_opencode_base_url(target_ip)
        try:
            body = {}
            if title:
                body["title"] = title
            resp = requests.post(f"{base_url}/session", json=body, timeout=10)
            resp.raise_for_status()
            session = resp.json()
            session_id = session.get("id")
            return session_id
        except Exception as e:
            print(f"[auto_responder] Failed to create session on {target_ip}: {e}")
            return None

    def send_message_async(self, target_ip: str, session_id: str, message: str, agent: str = "soc_god") -> bool:
        """Send a message asynchronously using POST /session/:id/prompt_async."""
        base_url = self.get_opencode_base_url(target_ip)
        try:
            body = {
                "parts": [{"type": "text", "text": message}],
                "agent": agent,
            }
            resp = requests.post(
                f"{base_url}/session/{session_id}/prompt_async",
                json=body,
                timeout=30
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            print(f"[auto_responder] Failed to send async message to {target_ip} session {session_id}: {e}")
            return False

    def send_message_sync(self, target_ip: str, session_id: str, message: str, agent: str = "soc_god") -> Optional[Dict]:
        """Send a message synchronously using POST /session/:id/message."""
        base_url = self.get_opencode_base_url(target_ip)
        try:
            body = {
                "parts": [{"type": "text", "text": message}],
                "agent": agent,
            }
            resp = requests.post(
                f"{base_url}/session/{session_id}/message",
                json=body,
                timeout=OPENCODE_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[auto_responder] Failed to send sync message to {target_ip} session {session_id}: {e}")
            return None

    def get_session_status(self, target_ip: str, session_id: str = None) -> Optional[Dict]:
        """Get session status using GET /session/status."""
        base_url = self.get_opencode_base_url(target_ip)
        try:
            resp = requests.get(f"{base_url}/session/status", timeout=10)
            resp.raise_for_status()
            all_statuses = resp.json()
            if session_id:
                return all_statuses.get(session_id)
            return all_statuses
        except Exception as e:
            print(f"[auto_responder] Failed to get session status from {target_ip}: {e}")
            return None

    def get_session_messages(self, target_ip: str, session_id: str) -> Optional[List]:
        """Get messages from a session using GET /session/:id/message.
        Retries a few times in case the server is temporarily busy."""
        base_url = self.get_opencode_base_url(target_ip)
        last_error = None
        for attempt in range(3):
            try:
                resp = requests.get(f"{base_url}/session/{session_id}/message", timeout=30)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_error = e
                print(f"[auto_responder] Attempt {attempt+1}/3 failed to get messages from {target_ip} session {session_id}: {e}")
                time.sleep(2)
        print(f"[auto_responder] All attempts failed to get messages from {target_ip} session {session_id}: {last_error}")
        return None

    def wait_for_session_complete(self, target_ip: str, session_id: str, timeout: int = None) -> bool:
        """Poll session status until it is no longer busy/active."""
        if timeout is None:
            timeout = OPENCODE_TIMEOUT
        start = time.time()
        machine_name = "server" if target_ip == SERVER_IP else "compromised"

        while time.time() - start < timeout:
            status = self.get_session_status(target_ip, session_id)
            elapsed = time.time() - start

            # If status is None, the session is no longer listed in /session/status
            # This means it has completed (OpenCode removes finished sessions from the busy list)
            if status is None:
                # Only treat as completed if we've been polling for at least a few seconds
                # (to avoid false positives from race conditions at startup)
                if elapsed > 5:
                    self.log("POLL", f"Session {session_id[:8]} no longer in status response → completed ({elapsed:.0f}s)", machine_name)
                    return True
                time.sleep(OPENCODE_STATUS_POLL_INTERVAL)
                continue

            if isinstance(status, str):
                status_str = status.lower()
            elif isinstance(status, dict):
                status_str = str(status).lower()
            else:
                status_str = str(status).lower()

            self.log("POLL", f"Session {session_id[:8]} status: {status_str} ({elapsed:.0f}s)", machine_name)

            if any(ind in status_str for ind in ["completed", "idle", "ready", "done"]):
                return True
            if "error" in status_str or "failed" in status_str:
                self.log("ERROR", f"Session {session_id[:8]} reported error: {status_str}", machine_name)
                return True

            if not any(ind in status_str for ind in ["busy", "pending", "running", "active", "generating"]):
                time.sleep(OPENCODE_STATUS_POLL_INTERVAL)
                status2 = self.get_session_status(target_ip, session_id)
                if status2 is not None:
                    status2_str = str(status2).lower()
                    if not any(ind in status2_str for ind in ["busy", "pending", "running", "active", "generating"]):
                        self.log("POLL", f"Session {session_id[:8]} appears idle (confirmed)", machine_name)
                        return True

            time.sleep(OPENCODE_STATUS_POLL_INTERVAL)

        self.log("TIMEOUT", f"Session {session_id[:8]} timed out after {timeout}s", machine_name)
        return False

    def abort_session(self, target_ip: str, session_id: str) -> bool:
        base_url = self.get_opencode_base_url(target_ip)
        try:
            resp = requests.post(f"{base_url}/session/{session_id}/abort", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────
    # Log conversion: API messages → legacy JSONL format
    # ──────────────────────────────────────────────────────────────────

    def convert_api_messages_to_legacy_jsonl(self, messages: List[Dict]) -> List[str]:
        """Convert OpenCode Server API message format to legacy opencode_stdout.jsonl format.

        Legacy format has one JSON event per line with top-level fields:
          {"type": "step_start|tool_use|text|step_finish", "timestamp": <ms_epoch>, "sessionID": ..., "part": {...}}

        API message format has messages containing parts:
          [{"info": {...}, "parts": [{"type": "step-start|tool|text|step-finish", ...}]}]
        """
        legacy_lines = []

        for msg in messages:
            info = msg.get("info", {})
            parts = msg.get("parts", [])
            session_id = info.get("sessionID", "")

            for part in parts:
                part_type = part.get("type", "")

                # Map API part types to legacy event types
                if part_type == "step-start":
                    legacy_type = "step_start"
                elif part_type == "step-finish":
                    legacy_type = "step_finish"
                elif part_type == "tool":
                    legacy_type = "tool_use"
                elif part_type == "text":
                    legacy_type = "text"
                else:
                    # Skip unknown types
                    continue

                # Determine timestamp: use part time if available, else message time
                timestamp_ms = 0
                part_time = part.get("time", {})
                if part_time:
                    timestamp_ms = part_time.get("start", 0) or part_time.get("end", 0)
                if not timestamp_ms:
                    msg_time = info.get("time", {})
                    timestamp_ms = msg_time.get("created", 0) or msg_time.get("completed", 0)

                # Build legacy event
                legacy_event = {
                    "type": legacy_type,
                    "timestamp": timestamp_ms,
                    "sessionID": session_id,
                    "part": part,
                }

                # For step_finish, add reason/cost/tokens from the part or message info
                if legacy_type == "step_finish":
                    if "reason" not in part and info.get("finish"):
                        legacy_event["part"]["reason"] = info["finish"]
                    if "cost" not in part and info.get("cost") is not None:
                        legacy_event["part"]["cost"] = info["cost"]
                    if "tokens" not in part and info.get("tokens"):
                        legacy_event["part"]["tokens"] = info["tokens"]

                legacy_lines.append(json.dumps(legacy_event, separators=(",", ":")))

        return legacy_lines

    def save_session_logs(self, target_ip: str, session_id: str, machine_name: str,
                          execution_id: str = None, alert_hash: str = None) -> Dict:
        """Fetch session messages and save in both API and legacy formats.

        Saves:
          - opencode_api_messages.json  : Full API response (JSON array)
          - opencode_stdout.jsonl       : Legacy JSONL format (one event per line)

        Returns dict with parsed metrics (llm_calls, tool_calls, etc.).
        """
        machine_output_dir = self.get_machine_output_dir(machine_name)
        api_path = machine_output_dir / "opencode_api_messages.json"
        legacy_path = machine_output_dir / "opencode_stdout.jsonl"

        messages = self.get_session_messages(target_ip, session_id)
        if messages is None:
            self.log("WARN", f"No messages retrieved for session {session_id[:8]}",
                     machine_name, alert_hash, execution_id)
            return {"final_output": None, "llm_calls": 0, "tool_calls": [], "errors": []}

        if not messages:
            # Empty list — session had no messages (possibly early completion)
            self.log("WARN", f"Empty message list for session {session_id[:8]} — saving empty log",
                     machine_name, alert_hash, execution_id)
            with open(api_path, "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=2)
            return {"final_output": None, "llm_calls": 0, "tool_calls": [], "errors": []}

        # ── Save API format ──
        with open(api_path, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2)
        self.log("LOG", f"Saved API messages to {api_path}",
                 machine_name, alert_hash, execution_id)

        # ── Convert and save legacy JSONL format ──
        legacy_lines = self.convert_api_messages_to_legacy_jsonl(messages)
        with open(legacy_path, "w", encoding="utf-8") as f:
            for line in legacy_lines:
                f.write(line + "\n")
        self.log("LOG", f"Saved legacy JSONL ({len(legacy_lines)} events) to {legacy_path}",
                 machine_name, alert_hash, execution_id)

        # ── Also write each event to the timeline ──
        timeline_path = self.get_machine_timeline_path(machine_name)
        for line in legacy_lines:
            try:
                event = json.loads(line)
                event_type = event.get("type", "")
                timeline_entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "level": "OPENCODE",
                    "msg": event_type,
                }
                if execution_id:
                    timeline_entry["exec"] = execution_id[:8]
                timeline_entry["data"] = event
                with open(timeline_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(timeline_entry, separators=(",", ":")) + "\n")
            except (json.JSONDecodeError, ValueError):
                continue

        # ── Parse metrics from messages ──
        llm_calls = 0
        tool_calls = []
        text_outputs = []
        errors = []
        total_tokens = {"input": 0, "output": 0, "reasoning": 0}
        total_cost = 0.0

        for msg in messages:
            info = msg.get("info", {})
            parts = msg.get("parts", [])

            # Accumulate token counts from assistant messages
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
                    tool_name = part.get("tool", "unknown")
                    tool_calls.append(tool_name)
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
        }

    # ──────────────────────────────────────────────────────────────────
    # Execution via OpenCode Server API
    # ──────────────────────────────────────────────────────────────────

    def execute_plan_via_server_api(self, plan: str, target_name: str, target_ip: str,
                                    alert: Dict, alert_hash: str = None,
                                    execution_id: str = None) -> bool:
        """Execute remediation plan using OpenCode Server HTTP API."""
        if not execution_id:
            execution_id = hashlib.md5(f"{time.time()}".encode()).hexdigest()[:16]

        self.log("API", f"Checking OpenCode server health on {target_name} ({target_ip})", target_name, alert_hash, execution_id)
        if not self.check_opencode_health(target_ip):
            self.log("API", f"Waiting for OpenCode server on {target_name}...", target_name, alert_hash, execution_id)
            if not self.wait_for_opencode_server(target_ip, timeout=60):
                self.log("ERROR", f"OpenCode server not available on {target_name} ({target_ip})", target_name, alert_hash, execution_id)
                return False

        self.log("API", f"✓ OpenCode server healthy on {target_name}", target_name, alert_hash, execution_id)

        context = f"""Execute this security remediation plan immediately:

PLAN: {plan}

CONTEXT:
- Alert Source IP: {alert.get('sourceip', 'unknown')}
- Alert Target IP: {alert.get('destip', 'unknown')}
- Attack Type: {alert.get('attackid', 'unknown')}
- Target Machine: {target_name} ({target_ip})
- Target IP: {target_ip}

**ABSOLUTE PROHIBITIONS - DO NOT VIOLATE:**
- **NEVER STOP OR RESTART SSH SERVICE**
- **NEVER STOP OR RESTART HTTP/HTTPS SERVICES**
- **NEVER KILL THE OPENCODE PROCESS** - Do NOT run: kill, pkill, or killall against the 'opencode' process. It is the agent controlling you.
- **NEVER BLOCK PORT 4096/tcp** - This is the OpenCode server API port. Blocking it will terminate your own execution.
- **NEVER BLOCK TRAFFIC TO/FROM YOUR OWN IP ADDRESS**

**CRITICAL FIREWALL RULES - FOLLOW EXACTLY:**
- **Maintain SSH, HTTPS, and OpenCode (port 4096) connectivity above all else**
- **INPUT chain:** Use to block traffic FROM specific source IPs - SAFE
- **OUTPUT chain:** Use to block traffic TO specific destination IPs - SAFE if NOT your own IP
- **NEVER use 0.0.0.0/0 as destination**
- **FORBIDDEN:** iptables -A INPUT -p tcp --dport 4096 -j DROP (blocks OpenCode API - kills your agent)

Execute all containment and remediation steps immediately. Be decisive and thorough."""

        machine_output_dir = self.get_machine_output_dir(target_name)
        stdout_path = machine_output_dir / "opencode_stdout.jsonl"  # legacy JSONL
        api_path = machine_output_dir / "opencode_api_messages.json"  # full API messages
        stderr_path = machine_output_dir / "opencode_stderr.log"

        start_time = time.time()

        try:
            # ── Reuse an existing session for this target if one is active ──
            session_id = None
            reused = False
            with self.lock:
                existing_id = self.active_sessions.get(target_ip)
            if existing_id:
                # Check whether the previous session is still listed (busy)
                status = self.get_session_status(target_ip, existing_id)
                if status is not None:
                    # Session is busy — abort the current task so we can send the new plan immediately.
                    # Abort stops the running LLM execution but keeps the session and its
                    # message history alive, so the next prompt continues with full context.
                    self.log("API", f"Aborting running task in session {existing_id[:8]} on {target_name} to send new plan",
                             target_name, alert_hash, execution_id)
                    aborted = self.abort_session(target_ip, existing_id)
                    if aborted:
                        self.log("API", f"Successfully aborted session {existing_id[:8]}",
                                 target_name, alert_hash, execution_id)
                    else:
                        self.log("WARN", f"Abort returned false for session {existing_id[:8]}, will try to send anyway",
                                 target_name, alert_hash, execution_id)
                    # Brief pause to let the abort settle before sending the next prompt
                    time.sleep(2)
                # Session exists (now idle after abort, or was already idle) — reuse it
                session_id = existing_id
                reused = True
                self.log("API", f"Reusing session {session_id[:8]} on {target_name}",
                         target_name, alert_hash, execution_id, extra_data={"session_id": session_id})

            if session_id is None:
                session_title = f"Defender response {alert_hash[:8] if alert_hash else 'unknown'}"
                session_id = self.create_session(target_ip, title=session_title)
                if not session_id:
                    self.log("ERROR", f"Failed to create session on {target_name}", target_name, alert_hash, execution_id)
                    return False
                self.log("API", f"Created session {session_id[:8]} on {target_name}", target_name, alert_hash, execution_id, extra_data={
                    "session_id": session_id
                })

            # Track this session as the active one for the target
            with self.lock:
                self.active_sessions[target_ip] = session_id

            self.log("API", f"Sending plan to session {session_id[:8]} (async, fire-and-continue)", target_name, alert_hash, execution_id)
            success = self.send_message_async(target_ip, session_id, context, agent="soc_god")
            if not success:
                self.log("ERROR", f"Failed to send message to session {session_id[:8]}", target_name, alert_hash, execution_id)
                return False

            duration = time.time() - start_time
            self.log("API", f"✓ Plan dispatched to session {session_id[:8]} in {duration:.1f}s — not waiting for completion",
                     target_name, alert_hash, execution_id, extra_data={
                         "session_id": session_id,
                         "mode": "opencode_server_api",
                         "reused_session": reused,
                         "executor_ip": target_ip,
                         "dispatch_seconds": round(duration, 2),
                     })
            return True

        except Exception as exc:
            duration = time.time() - start_time
            with open(stderr_path, "a", encoding="utf-8") as handle:
                handle.write(f"Exception: {str(exc)}\n")
            self.log("ERROR", f"OpenCode execution exception on {target_name}: {exc}", target_name, alert_hash, execution_id, extra_data={
                "error": str(exc),
                "duration_seconds": round(duration, 2),
                "exec": execution_id[:8],
            })
            return False

    def execute_multiple_plans_async(self, plans_list: List[Dict], alert: Dict, alert_hash: str = None, base_execution_id: str = None) -> None:
        """Execute multiple plans in background threads (truly non-blocking)."""
        import concurrent.futures

        def execute_single_plan(plan_data: Dict, ip_index: int):
            executor_ip = plan_data.get("executor_host_ip", "")
            plan = plan_data.get("plan", "")

            target_info = self.determine_target_info(executor_ip)
            target_name = target_info[1] if target_info else "unknown"
            target_ip = target_info[0] if target_info else "unknown"

            ip_safe = executor_ip.replace('.', '_')
            ip_execution_id = f"{base_execution_id}_{ip_safe}"

            self.log("EXEC", f"Starting execution for {executor_ip}", target_name, alert_hash, ip_execution_id, extra_data={
                "executor_ip": executor_ip,
                "ip_index": ip_index,
                "total_plans": len(plans_list)
            })

            self.execute_plan_via_server_api(plan, target_name, target_ip, alert, alert_hash, ip_execution_id)

        # Do NOT use 'with' — that blocks until all futures complete.
        # Fire-and-forget: create executor, submit tasks, let threads run in background.
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(plans_list))
        futures = []
        for i, plan_data in enumerate(plans_list):
            futures.append(pool.submit(execute_single_plan, plan_data, i))
        # Keep references alive so threads aren't garbage-collected;
        # prune completed pools to avoid memory leak.
        if not hasattr(self, '_background_pools'):
            self._background_pools = []
        self._background_pools = [
            (p, futs) for p, futs in self._background_pools
            if not all(fut.done() for fut in futs)
        ]
        self._background_pools.append((pool, futures))
        pool.shutdown(wait=False)

    def process_alert(self, alert: Dict) -> bool:
        """Process single alert through plan generation and execution."""
        import re

        alert_hash = self.get_alert_hash(alert)
        base_execution_id = hashlib.md5(f"{alert_hash}{time.time()}".encode()).hexdigest()[:16]
        start_time = time.time()

        source_ip = alert.get('sourceip', 'unknown')
        dest_ip = alert.get('destip', 'unknown')
        raw_alert = alert.get('raw', '')

        if source_ip == 'unknown' or dest_ip == 'unknown':
            src_match = re.search(r'Src IP\s+(\d+\.\d+\.\d+\.\d+)', raw_alert)
            to_ip_match = re.search(r'to IP\s+(\d+\.\d+\.\d+\.\d+)', raw_alert)
            to_match = re.search(r'to\s+(\d+\.\d+\.\d+\.\d+):\d+', raw_alert)

            if src_match:
                source_ip = src_match.group(1)
            elif source_ip == 'unknown':
                ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
                if len(ip_match) >= 1:
                    source_ip = ip_match[0]

            if to_ip_match:
                dest_ip = to_ip_match.group(1)
            elif to_match:
                dest_ip = to_match.group(1)
            elif dest_ip == 'unknown':
                ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
                if len(ip_match) >= 2:
                    dest_ip = ip_match[-1] if ip_match[-1] != source_ip else list(dict.fromkeys(ip_match))[1]

        self.log("ALERT", f"New: {source_ip} → {dest_ip}", machine_name=None, alert_hash=alert_hash, execution_id=base_execution_id, extra_data={
            "source_ip": source_ip,
            "dest_ip": dest_ip,
            "attack_type": alert.get('attackid', 'unknown'),
            "raw": raw_alert,
            "full_alert": alert
        })

        try:
            alert_text = self.format_alert_for_planner(alert)
            plan_start = time.time()
            plan_response = self.call_planner(alert_text)
            plan_duration = time.time() - plan_start

            if not plan_response:
                self.log("ERROR", f"Plan generation failed ({plan_duration:.2f}s)", machine_name=None, alert_hash=alert_hash, execution_id=base_execution_id)
                return False

            plans_list = []
            if "plans" in plan_response:
                plans_list = plan_response.get("plans", [])
            else:
                plan = plan_response.get("plan", "")
                executor_ip = plan_response.get("executor_host_ip", "")
                if plan and executor_ip:
                    plans_list = [{"executor_host_ip": executor_ip, "plan": plan}]

            if not plans_list:
                self.log("ERROR", "No valid plans in response", machine_name=None, alert_hash=alert_hash, execution_id=base_execution_id, extra_data={"plan_response": plan_response})
                return False

            self.log("PLAN", f"Generated {len(plans_list)} plan(s) ({plan_duration:.2f}s)", machine_name=None, alert_hash=alert_hash, execution_id=base_execution_id, extra_data={
                "num_plans": len(plans_list),
                "plans": plans_list,
                "model": plan_response.get("model", "unknown"),
                "formatted_alert": alert_text
            })

            exec_start = time.time()
            self.execute_multiple_plans_async(plans_list, alert, alert_hash, base_execution_id)
            total_duration = time.time() - start_time

            self.log("DONE", f"Started execution in {total_duration:.1f}s (plan: {plan_duration:.1f}s)", machine_name=None, alert_hash=alert_hash, execution_id=base_execution_id, extra_data={
                "total_duration": total_duration,
                "plan_duration": plan_duration,
                "status": "started_in_background"
            })

            return True

        except Exception as e:
            self.log("ERROR", f"Exception: {e}", machine_name=None, alert_hash=alert_hash, execution_id=base_execution_id, extra_data={
                "exception": str(e),
                "alert": alert
            })
            return False

    def run_once(self) -> None:
        """Single run of the alert processing loop."""
        try:
            new_alerts = self.get_new_alerts()
            if not new_alerts:
                return

            print(f"[auto_responder] Found {len(new_alerts)} new alerts")

            processed_count = 0
            for alert in new_alerts:
                alert_hash = self.get_alert_hash(alert)
                # Re-check threat dedup here (not in get_new_alerts) so that
                # record_threat() from the previous iteration is visible.
                if self.is_duplicate_threat(alert, alert_hash):
                    print(f"[auto_responder] Skipping duplicate threat: {self.get_threat_hash(alert)[:8]}")
                    continue
                try:
                    success = self.process_alert(alert)
                    if success:
                        with self.lock:
                            self.processed_alerts.add(alert_hash)
                        self.record_threat(alert)
                        processed_count += 1
                    else:
                        print(f"[auto_responder] Failed to process alert, will retry later")
                except Exception as e:
                    print(f"[auto_responder] Error processing alert: {e}")

            if processed_count > 0:
                self.save_processed_alerts()
                print(f"[auto_responder] Successfully processed {processed_count} alerts")

        except Exception as e:
            print(f"[auto_responder] Error in run_once: {e}")

    def run(self) -> None:
        """Main monitoring loop"""
        print(f"[auto_responder] Monitoring {ALERT_FILE} (poll: {POLL_INTERVAL}s)")
        print(f"[auto_responder] Using OpenCode Server API mode")

        while True:
            try:
                self.run_once()
                time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                print(f"[auto_responder] Shutting down...")
                break
            except Exception as e:
                print(f"[auto_responder] Error: {e}")
                time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    responder = AutoResponder()
    responder.run()
