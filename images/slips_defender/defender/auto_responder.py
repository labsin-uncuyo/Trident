#!/usr/bin/env python3
"""
Automated Response Orchestrator

This component bridges SLIPS alerts with OpenCode execution:
1. Monitors defender_alerts.ndjson for new alerts
2. Calls the planner service to generate remediation plans
3. Executes plans using OpenCode on target machines
4. Tracks processed alerts to avoid duplicates
"""

import json
import os
import subprocess
import time
import threading
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import requests
import logging

try:
    import pexpect
    HAS_PEXPECT = True
except ImportError:
    HAS_PEXPECT = False
    print("[auto_responder] WARNING: pexpect not available. Multi-alert mode disabled.")

# Configuration
RUN_ID = os.getenv("RUN_ID", "run_local")
ALERT_FILE = Path("/outputs") / RUN_ID / "slips" / "defender_alerts.ndjson"
PROCESSED_FILE = Path("/outputs") / RUN_ID / "processed_alerts.json"
PLANNER_URL = os.getenv("PLANNER_URL", "http://127.0.0.1:1654/plan")
OPENCODE_TIMEOUT = int(os.getenv("OPENCODE_TIMEOUT", "600"))  # 10 minutes
POLL_INTERVAL = float(os.getenv("AUTO_RESPONDER_INTERVAL", "5"))
MAX_EXECUTION_RETRIES = int(os.getenv("MAX_EXECUTION_RETRIES", "3"))
DUPLICATE_DETECTION_WINDOW = int(os.getenv("DUPLICATE_DETECTION_WINDOW", "300"))  # 5 minutes

# Multi-alert configuration
ENABLE_MULTI_ALERT = os.getenv("ENABLE_MULTI_ALERT", "true").lower() == "true"
ALERT_POOL_WINDOW = int(os.getenv("ALERT_POOL_WINDOW", "10"))  # Pool alerts within 10s window
MULTI_ALERT_DELAY = float(os.getenv("MULTI_ALERT_DELAY", "0.5"))  # Delay between commands (0.5s)
MULTI_ALERT_SESSION_TIMEOUT = int(os.getenv("MULTI_ALERT_SESSION_TIMEOUT", "300"))  # 5 minutes

# SSH configuration
SERVER_IP = "172.31.0.10"     # Server container IP
COMPROMISED_IP = "172.30.0.10" # Compromised container IP
SSH_USER = "root"
SSH_PORT = 22
SSH_KEY_PATH = "/root/.ssh/id_rsa_auto_responder"  # SSH private key path
SSH_KNOWN_HOSTS = "/dev/null"  # Skip host key verification (for lab environment)

# Docker container names (kept for reference)
SERVER_CONTAINER = "lab_server"
COMPROMISED_CONTAINER = "lab_compromised"

class AutoResponder:
    def __init__(self):
        self.processed_alerts: Set[str] = set()
        self.threat_history: Dict[str, datetime] = {}  # threat_hash -> first_seen
        self.lock = threading.Lock()
        self.setup_logging()
        self.load_processed_alerts()
        self._ssh_verified = False  # Track if SSH was verified once
        self.log("INIT", "AutoResponder started", extra_data={
            "config": {
                "alert_file": str(ALERT_FILE),
                "planner_url": PLANNER_URL,
                "poll_interval": POLL_INTERVAL,
                "opencode_timeout": OPENCODE_TIMEOUT,
                "server_ip": SERVER_IP,
                "compromised_ip": COMPROMISED_IP,
                "duplicate_window": DUPLICATE_DETECTION_WINDOW,
                "multi_alert_enabled": ENABLE_MULTI_ALERT,
                "multi_alert_pexpect_available": HAS_PEXPECT,
                "multi_alert_mode": "enabled" if (ENABLE_MULTI_ALERT and HAS_PEXPECT) else "disabled"
            }
        })

        # Log multi-alert mode status
        if ENABLE_MULTI_ALERT:
            if HAS_PEXPECT:
                print(f"[auto_responder] ✓ Multi-alert mode ENABLED (pexpect available)")
                print(f"[auto_responder]   - Alert pool window: {ALERT_POOL_WINDOW}s")
                print(f"[auto_responder]   - Delay between commands: {MULTI_ALERT_DELAY}s")
                print(f"[auto_responder]   - Session timeout: {MULTI_ALERT_SESSION_TIMEOUT}s")
            else:
                print(f"[auto_responder] ⚠ Multi-alert mode requested but pexpect NOT available")
                print(f"[auto_responder]   Falling back to single-alert mode")
        else:
            print(f"[auto_responder] Multi-alert mode DISABLED (ENABLE_MULTI_ALERT={ENABLE_MULTI_ALERT})")

    def setup_logging(self):
        """Setup detailed logging with timestamps"""
        log_file = Path("/outputs") / RUN_ID / "auto_responder_detailed.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Create custom logger
        self.logger = logging.getLogger("auto_responder")
        self.logger.setLevel(logging.INFO)

        # Clear existing handlers
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        # File handler with detailed formatting
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Detailed formatter with timestamps
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def log(self, level: str, message: str, alert_hash: str = None, execution_id: str = None, extra_data: Dict = None):
        """
        Clean, compact logging with structured timeline output.
        
        Timeline log levels (in auto_responder_timeline.jsonl):
        - INIT: System startup with config
        - ALERT: New alert received (includes full alert data)
        - PLAN: Plan generation (includes full plan)
        - SSH: SSH connection attempt (includes full command)
        - EXEC: OpenCode execution result (includes output)
        - ERROR: Any error with details
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Add context if provided (short format for console)
        context_parts = []
        if alert_hash:
            context_parts.append(f"#{alert_hash[:8]}")
        if execution_id:
            context_parts.append(f"@{execution_id[:8]}")

        context = f" {' '.join(context_parts)}" if context_parts else ""

        log_message = f"{message}{context}"

        # Log to both file and console using logger
        if level.upper() == "ERROR":
            self.logger.error(log_message)
        elif level.upper() == "WARNING":
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)

        # Write to structured timeline log (JSONL format for easy parsing)
        structured_log_file = Path("/outputs") / RUN_ID / "auto_responder_timeline.jsonl"
        with open(structured_log_file, "a") as f:
            entry = {
                "ts": timestamp,
                "level": level.upper(),
                "msg": message
            }
            if alert_hash:
                entry["alert"] = alert_hash[:8]
            if execution_id:
                entry["exec"] = execution_id[:8]
            if extra_data:
                entry["data"] = extra_data
            f.write(json.dumps(entry, separators=(',', ':')) + "\n")

    def load_processed_alerts(self) -> None:
        """Load set of already processed alert hashes"""
        try:
            if PROCESSED_FILE.exists():
                with PROCESSED_FILE.open("r") as f:
                    data = json.load(f)
                    self.processed_alerts = set(data.get("processed_hashes", []))
                    # Load threat history with timestamps
                    threat_history_data = data.get("threat_history", {})
                    now = datetime.now(timezone.utc)
                    # Only load threats within the duplicate window
                    for threat_hash, timestamp_str in threat_history_data.items():
                        try:
                            threat_time = datetime.fromisoformat(timestamp_str)
                            # Keep only recent threats (within duplicate window)
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
        """Save set of processed alert hashes and threat history"""
        try:
            PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Clean up old threats from history before saving
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
        """Generate hash for alert deduplication (includes timestamp)"""
        # Use key fields that define uniqueness of an alert
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
        """Generate hash for threat deduplication (excludes timestamp)"""
        # Extract IPs from raw alert if not in structured fields
        source_ip = alert.get("sourceip", "")
        dest_ip = alert.get("destip", "")
        raw_alert = alert.get("raw", "")

        if not source_ip or not dest_ip:
            import re
            ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
            if len(ip_match) >= 2:
                source_ip, dest_ip = ip_match[0], ip_match[1]
            elif len(ip_match) == 1:
                source_ip = ip_match[0]

        # Extract attack type from raw alert
        attack_type = "unknown"
        if "horizontal port scan" in raw_alert.lower():
            attack_type = "horizontal_port_scan"
        elif "vertical port scan" in raw_alert.lower():
            attack_type = "vertical_port_scan"
        elif "brute force" in raw_alert.lower():
            attack_type = "brute_force"
        elif "denial of service" in raw_alert.lower() or "ddos" in raw_alert.lower():
            attack_type = "dos"
        elif alert.get("attackid"):
            attack_type = alert.get("attackid", "unknown")

        # Create hash based on threat characteristics (not timestamp)
        threat_fields = {
            "source_ip": source_ip,
            "dest_ip": dest_ip,
            "attack_type": attack_type,
            "proto": alert.get("proto", "")
        }
        threat_str = json.dumps(threat_fields, sort_keys=True)
        return hashlib.md5(threat_str.encode()).hexdigest()

    def is_duplicate_threat(self, alert: Dict, alert_hash: str) -> bool:
        """Check if this alert is a duplicate threat (same type+IPs within window)"""
        threat_hash = self.get_threat_hash(alert)
        now = datetime.now(timezone.utc)

        with self.lock:
            if threat_hash in self.threat_history:
                first_seen = self.threat_history[threat_hash]
                time_since_first = (now - first_seen).total_seconds()

                if time_since_first < DUPLICATE_DETECTION_WINDOW:
                    # This is a duplicate - update the processed set with this exact alert hash
                    # so we don't process it again
                    self.processed_alerts.add(alert_hash)
                    return True
                else:
                    # Window expired, start fresh
                    self.threat_history[threat_hash] = now
                    return False
            else:
                # New threat, record it
                self.threat_history[threat_hash] = now
                return False

    def get_new_alerts(self) -> List[Dict]:
        """Read alerts file and return unprocessed alerts with high confidence"""
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

                        # Filter: Only process high-confidence security alerts
                        # Skip system messages (heartbeat, queued, completed, etc.)
                        if not self._is_high_confidence_alert(alert):
                            continue

                        alert_hash = self.get_alert_hash(alert)

                        # Skip if already processed
                        if alert_hash in self.processed_alerts:
                            continue

                        # Skip if this is a duplicate threat (same type+IPs within 5 min)
                        if self.is_duplicate_threat(alert, alert_hash):
                            print(f"[auto_responder] Skipping duplicate threat: {self.get_threat_hash(alert)[:8]}")
                            continue

                        new_alerts.append(alert)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[auto_responder] Error reading alerts file: {e}")

        return new_alerts

    def _is_high_confidence_alert(self, alert: Dict) -> bool:
        """Check if alert is a high-confidence security alert worth responding to"""
        # Skip system messages
        note = alert.get("note", "").lower()
        if note in ["heartbeat", "queued", "completed"]:
            return False

        # Skip alerts with note field only (system messages)
        if len(alert.keys()) <= 3 and "note" in alert:
            return False

        # Check ALL fields for high-confidence indicators, especially the raw field
        # High confidence data is in the 'raw' field for SLIPS alerts
        raw_alert = alert.get("raw", "").lower()
        description = alert.get("description", "").lower()
        threat_level = alert.get("threat_level", "").lower()

        # Combine all alert text for searching
        alert_text = f"{raw_alert} {description} {threat_level}"

        # High confidence patterns
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
        """Format alert into plaintext for planner consumption"""
        timestamp = alert.get("timestamp", datetime.now().isoformat())

        # Try to extract from structured fields first
        source_ip = alert.get("sourceip", "unknown")
        dest_ip = alert.get("destip", "unknown")
        attack_id = alert.get("attackid", "unknown")
        proto = alert.get("proto", "unknown")
        description = alert.get("description", "") or alert.get("threat_level", "")

        # If no structured data, parse from raw SLIPS alert
        raw_alert = alert.get("raw", "")
        if raw_alert and (source_ip == "unknown" or dest_ip == "unknown"):
            # Extract IPs from raw alert: "Src IP 172.30.0.10 ... to IP 172.31.0.10"
            import re
            ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
            if len(ip_match) >= 2:
                source_ip, dest_ip = ip_match[0], ip_match[1]

            # Extract timestamp from raw alert
            time_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', raw_alert)
            if time_match:
                timestamp = time_match.group(1) + '+00:00'

            # Attack type is the description in raw alert
            attack_id = "vertical_port_scan" if "vertical port scan" in raw_alert.lower() else "unknown"
            proto = "TCP" if "TCP" in raw_alert else "unknown"

            # Use the raw alert as description since it contains all details
            description = raw_alert

        formatted = f"{timestamp} {source_ip} {attack_id} ({proto}) targeting {dest_ip}"
        if description:
            formatted += f" - {description}"

        return formatted

    def call_planner(self, alert_text: str) -> Optional[Dict]:
        """Call planner service to generate remediation plan"""
        try:
            payload = {"alert": alert_text}
            response = requests.post(PLANNER_URL, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[auto_responder] Planner request failed: {e}")
            return None

    def determine_target_ssh_info(self, executor_ip: str) -> Optional[tuple]:
        """Determine SSH target information based on executor IP"""
        # Map IPs to SSH targets based on network topology
        if executor_ip.startswith("172.31.0."):
            # Server network (172.31.0.0/24)
            return SERVER_IP, "server"
        elif executor_ip.startswith("172.30.0."):
            # Compromised network (172.30.0.0/24)
            return COMPROMISED_IP, "compromised"
        else:
            # Default to server for unknown IPs
            return SERVER_IP, "server"

    def ensure_ssh_key(self) -> bool:
        """Ensure SSH key exists and has proper permissions (silent after first check)"""
        try:
            # Check if ssh command is available
            ssh_check = subprocess.run(["which", "ssh"], capture_output=True, text=True)
            if ssh_check.returncode != 0:
                self.log("ERROR", "SSH client not installed")
                return False

            # Check if ssh-keygen is available
            ssh_keygen_check = subprocess.run(["which", "ssh-keygen"], capture_output=True, text=True)
            if ssh_keygen_check.returncode != 0:
                self.log("ERROR", "ssh-keygen not installed")
                return False

            # Generate SSH key if it doesn't exist
            if not Path(SSH_KEY_PATH).exists():
                self.log("SSH", f"Generating SSH key at {SSH_KEY_PATH}")
                result = subprocess.run([
                    "ssh-keygen", "-t", "ed25519", "-f", SSH_KEY_PATH,
                    "-N", "", "-C", "auto_responder@slips"
                ], capture_output=True, text=True)

                if result.returncode != 0:
                    self.log("ERROR", f"Failed to generate SSH key: {result.stderr}")
                    return False

            # Set proper permissions
            os.chmod(SSH_KEY_PATH, 0o600)
            if Path(f"{SSH_KEY_PATH}.pub").exists():
                os.chmod(f"{SSH_KEY_PATH}.pub", 0o644)

            return True
        except Exception as e:
            self.log("ERROR", f"SSH key setup failed: {e}")
            return False

    def setup_ssh_access(self) -> bool:
        """Setup SSH access to target containers using setup script"""
        try:
            setup_script_path = "/opt/lab/defender/setup_ssh.sh"
            print(f"[auto_responder] Setting up SSH access using {setup_script_path}")

            # Run SSH setup script
            result = subprocess.run([
                "bash", setup_script_path
            ], capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"[auto_responder] SSH setup script failed: {result.stderr}")
                return False

            print(f"[auto_responder] SSH access setup completed")
            print(f"[auto_responder] Setup output: {result.stdout[-500:]}...")  # Last 500 chars

            return True

        except Exception as e:
            print(f"[auto_responder] Error setting up SSH access: {e}")
            return False

    def execute_multiple_plans_parallel(self, plans_list: List[Dict], alert: Dict, alert_hash: str = None, base_execution_id: str = None) -> bool:
        """
        Execute multiple plans in parallel, one per IP.

        Each plan gets its own execution thread and they run simultaneously.
        Returns True only if ALL executions succeed.
        """
        import concurrent.futures

        results = {}
        threads = []

        def execute_single_plan(plan_data: Dict, ip_index: int):
            """Execute a single plan in a thread"""
            executor_ip = plan_data.get("executor_host_ip", "")
            plan = plan_data.get("plan", "")

            # Create unique execution ID for this IP (include IP for clarity)
            ip_safe = executor_ip.replace('.', '_')
            ip_execution_id = f"{base_execution_id}_{ip_safe}"

            self.log("EXEC", f"Starting execution for {executor_ip}", alert_hash, ip_execution_id, extra_data={
                "executor_ip": executor_ip,
                "ip_index": ip_index,
                "total_plans": len(plans_list)
            })

            success = self.execute_plan_with_opencode(plan, executor_ip, alert, alert_hash, ip_execution_id)
            results[executor_ip] = success
            return success

        # Execute all plans in parallel using thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(plans_list)) as executor:
            futures = {
                executor.submit(execute_single_plan, plan_data, i): plan_data.get("executor_host_ip", "")
                for i, plan_data in enumerate(plans_list)
            }

            # Wait for all to complete
            concurrent.futures.wait(futures)

        # Check if all executions succeeded
        all_success = all(results.values())

        self.log("EXEC", f"Parallel execution complete: {sum(results.values())}/{len(results)} succeeded", alert_hash, base_execution_id, extra_data={
            "results": results,
            "all_success": all_success
        })

        return all_success

    def execute_plan_with_opencode(self, plan: str, executor_ip: str, alert: Dict, alert_hash: str = None, execution_id: str = None) -> bool:
        """Execute remediation plan using OpenCode via SSH on target machine"""
        target_info = self.determine_target_ssh_info(executor_ip)
        if not target_info:
            self.log("ERROR", f"Unknown target IP: {executor_ip}", alert_hash, execution_id)
            return False

        target_ip, target_name = target_info

        # Ensure SSH key exists
        if not self.ensure_ssh_key():
            self.log("ERROR", f"SSH key setup failed", alert_hash, execution_id)
            return False

        # Create execution context message for OpenCode
        context = f"""Execute this security remediation plan immediately:

PLAN: {plan}

CONTEXT:
- Alert Source IP: {alert.get('sourceip', 'unknown')}
- Alert Target IP: {alert.get('destip', 'unknown')}
- Attack Type: {alert.get('attackid', 'unknown')}
- Target Machine: {target_name} ({target_ip})
- Target IP: {executor_ip}

Execute all containment and remediation steps immediately. Be decisive and thorough."""

        # Use base64 encoding to safely pass context with special characters
        import base64
        context_b64 = base64.b64encode(context.encode('utf-8')).decode('utf-8')

        # Build the full SSH command
        # Use environment variables for API key and base URL
        opencode_api_key = os.environ.get("OPENCODE_API_KEY")
        if not opencode_api_key:
            raise ValueError("OPENCODE_API_KEY environment variable is not set")

        # Get OPENAI_BASE_URL (needed for OpenCode to authenticate)
        openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://chat.ai.e-infra.cz/api/")

        for attempt in range(MAX_EXECUTION_RETRIES):
            try:
                # Log the SSH execution attempt with full command
                self.log("SSH", f"→ {target_name}@{target_ip} (attempt {attempt + 1}/{MAX_EXECUTION_RETRIES})", alert_hash, execution_id, extra_data={
                    "target": target_name,
                    "target_ip": target_ip,
                    "attempt": attempt + 1,
                    "command": f"ssh ... 'echo <base64> | base64 -d | opencode run --agent soc_god'",
                    "context": context,
                    "timeout": OPENCODE_TIMEOUT
                })

                # Use SSH to connect to target machine and run OpenCode
                # Use base64 encoding to safely pass the context without shell escaping issues
                # Log timing data directly on the target machine before/after OpenCode
                # Capture OpenCode JSON output for full reasoning trace
                ssh_command = f'''export OPENCODE_API_KEY={opencode_api_key}
export OPENAI_BASE_URL={openai_base_url}
echo "OPENCODE_START=$(date -Iseconds)" >> /tmp/opencode_exec_times.log
(opencode run --agent soc_god --format json --log-level DEBUG -- "$(echo '{context_b64}' | base64 -d)" 2>&1; echo "OPENCODE_END=$(date -Iseconds) EXIT_CODE=$?" >> /tmp/opencode_exec_times.log) || echo "OPENCODE_ERROR=$(date -Iseconds)" >> /tmp/opencode_exec_times.log
'''

                ssh_cmd = [
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", f"UserKnownHostsFile={SSH_KNOWN_HOSTS}",
                    "-i", SSH_KEY_PATH,
                    "-p", str(SSH_PORT),
                    f"{SSH_USER}@{target_ip}",
                    ssh_command
                ]

                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    timeout=OPENCODE_TIMEOUT,
                    check=True
                )

                # Parse and log OpenCode JSON events to timeline
                # Each event gets its own timeline entry for full traceability
                tool_calls = []
                llm_calls = 0
                final_output = None
                errors = []
                text_outputs = []

                structured_log_file = Path("/outputs") / RUN_ID / "auto_responder_timeline.jsonl"

                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)

                        # Extract metrics based on actual OpenCode event types
                        event_type = event.get("type", "")

                        if event_type == "step_start":
                            # Each reasoning step involves LLM processing
                            llm_calls += 1
                        elif event_type == "tool_use":
                            # Extract tool name from tool_use events
                            part = event.get("part", {})
                            tool_name = part.get("tool", "unknown")
                            tool_calls.append(tool_name)
                        elif event_type == "text":
                            # Collect text output
                            part = event.get("part", {})
                            text_content = part.get("text", "")
                            if text_content:
                                text_outputs.append(text_content)
                        elif event_type == "Error":
                            errors.append(str(event))

                        # Log each OpenCode event to timeline with OPENCODE level
                        timestamp = datetime.now(timezone.utc).isoformat()
                        timeline_entry = {
                            "ts": timestamp,
                            "level": "OPENCODE",
                            "msg": event_type,
                            "exec": execution_id[:8],
                            "data": event
                        }
                        with open(structured_log_file, "a") as f:
                            f.write(json.dumps(timeline_entry, separators=(',', ':')) + "\n")

                    except (json.JSONDecodeError, ValueError):
                        # Non-JSON output - save as final output if we haven't captured one yet
                        if final_output is None and line:
                            final_output = line[:500]

                # Use collected text outputs as final output
                if not final_output and text_outputs:
                    final_output = " ".join(text_outputs)[-500:]

                # Final EXEC entry with summary
                self.log("EXEC", f"✓ Success on {target_name}", alert_hash, execution_id, extra_data={
                    "status": "success",
                    "target": target_name,
                    "output": final_output[:500] if final_output else None,
                    "llm_calls": llm_calls,
                    "tool_calls": tool_calls,
                    "unique_tools": len(set(tool_calls)),
                    "errors": errors if errors else None,
                    "stderr": result.stderr[:500] if result.stderr else None
                })
                return True

            except subprocess.TimeoutExpired:
                self.log("ERROR", f"Timeout on {target_name} ({OPENCODE_TIMEOUT}s)", alert_hash, execution_id, extra_data={
                    "status": "timeout",
                    "target": target_name,
                    "timeout": OPENCODE_TIMEOUT
                })

            except subprocess.CalledProcessError as e:
                # Determine if SSH worked but OpenCode failed (exit code from remote)
                ssh_failed = "connection refused" in (e.stderr or "").lower() or \
                             "no route to host" in (e.stderr or "").lower() or \
                             "permission denied" in (e.stderr or "").lower()

                # Parse any partial OpenCode output even on failure
                partial_events = []
                if e.stdout:
                    structured_log_file = Path("/outputs") / RUN_ID / "auto_responder_timeline.jsonl"
                    for line in e.stdout.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            partial_events.append(event)
                            timestamp = datetime.now(timezone.utc).isoformat()
                            timeline_entry = {
                                "ts": timestamp,
                                "level": "OPENCODE",
                                "msg": event.get("type", ""),
                                "exec": execution_id[:8],
                                "data": event
                            }
                            with open(structured_log_file, "a") as f:
                                f.write(json.dumps(timeline_entry, separators=(',', ':')) + "\n")
                        except (json.JSONDecodeError, ValueError):
                            pass

                self.log("ERROR", f"{'SSH failed' if ssh_failed else 'OpenCode failed'} on {target_name} (exit {e.returncode})", alert_hash, execution_id, extra_data={
                    "status": "ssh_error" if ssh_failed else "exec_error",
                    "target": target_name,
                    "exit_code": e.returncode,
                    "stdout": e.stdout[:1000] if e.stdout else None,
                    "stderr": e.stderr[:1000] if e.stderr else None,
                    "partial_opencode_events": len(partial_events)
                })

            except Exception as e:
                self.log("ERROR", f"Unexpected error on {target_name}: {e}", alert_hash, execution_id, extra_data={
                    "status": "exception",
                    "target": target_name,
                    "error": str(e)
                })

            if attempt < MAX_EXECUTION_RETRIES - 1:
                wait_time = 10 * (attempt + 1)  # Exponential backoff: 10s, 20s, 30s
                time.sleep(wait_time)

        self.log("ERROR", f"All {MAX_EXECUTION_RETRIES} attempts failed for {target_name}", alert_hash, execution_id)
        return False

    def execute_multiple_alerts_with_opencode_interactive(
        self,
        alerts_with_plans: List[Tuple[Dict, str, str]],  # List of (alert, plan, executor_ip)
        target_container: str,
        execution_id: str = None
    ) -> bool:
        """
        Execute multiple alerts in a single OpenCode interactive session.

        Args:
            alerts_with_plans: List of tuples (alert, plan, executor_ip)
            target_container: Docker container name (e.g., 'lab_server')
            execution_id: Execution ID for logging

        Returns:
            bool: True if all alerts executed successfully
        """
        if not HAS_PEXPECT:
            self.log("ERROR", "pexpect not available, cannot use multi-alert mode", execution_id=execution_id)
            return False

        if not alerts_with_plans:
            return True

        target_info = self.determine_target_ssh_info(alerts_with_plans[0][2])  # Use first alert's executor IP
        if not target_info:
            self.log("ERROR", f"Unknown target for alerts", execution_id=execution_id)
            return False

        target_ip, target_name = target_info

        # Build combined prompts for all alerts
        prompts = []
        for alert, plan, executor_ip in alerts_with_plans:
            context = f"""Execute this security remediation plan:

PLAN: {plan}

CONTEXT:
- Alert Source IP: {alert.get('sourceip', 'unknown')}
- Alert Target IP: {alert.get('destip', 'unknown')}
- Attack Type: {alert.get('attackid', 'unknown')}
- Target Machine: {target_name} ({target_ip})
- Target IP: {executor_ip}

Execute all containment and remediation steps immediately."""
            prompts.append(context)

        self.log("SSH", f"→ {target_name} (multi-alert: {len(prompts)} alerts)", execution_id=execution_id, extra_data={
            "target": target_name,
            "target_ip": target_ip,
            "alert_count": len(prompts),
            "mode": "interactive_multi_alert"
        })

        try:
            # Start OpenCode in interactive mode via docker exec
            # Use bash -c to ensure proper PTY allocation
            cmd = f"docker exec -it {target_container} /root/.opencode/bin/opencode"

            child = pexpect.spawn(cmd, encoding='utf-8', timeout=MULTI_ALERT_SESSION_TIMEOUT)

            # Wait for OpenCode TUI to initialize (look for "Ask anything")
            self.log("SSH", f"Waiting for OpenCode to initialize...", execution_id=execution_id)
            child.expect('Ask anything', timeout=30)
            self.log("SSH", f"OpenCode ready, sending {len(prompts)} alerts...", execution_id=execution_id)

            # Send first prompt
            child.sendline(prompts[0])

            # Send subsequent prompts with 0.5s delay (while first is processing)
            for i, prompt in enumerate(prompts[1:], start=2):
                time.sleep(MULTI_ALERT_DELAY)
                child.sendline(prompt)
                self.log("SSH", f"Sent alert {i}/{len(prompts)}", execution_id=execution_id)

            # Wait for all commands to complete
            self.log("SSH", f"Waiting for completion (timeout: {MULTI_ALERT_SESSION_TIMEOUT}s)...", execution_id=execution_id)
            time.sleep(MULTI_ALERT_SESSION_TIMEOUT)

            # Try to gracefully exit
            if child.isalive():
                child.sendline('/exit')
                time.sleep(2)

            # Force close if still alive
            if child.isalive():
                child.terminate(force=True)

            self.log("EXEC", f"✓ Multi-alert execution completed on {target_name}", execution_id=execution_id, extra_data={
                "status": "success",
                "target": target_name,
                "alert_count": len(prompts)
            })
            return True

        except pexpect.exceptions.TIMEOUT as e:
            self.log("ERROR", f"Timeout on {target_name} ({MULTI_ALERT_SESSION_TIMEOUT}s)", execution_id=execution_id, extra_data={
                "status": "timeout",
                "target": target_name,
                "timeout": MULTI_ALERT_SESSION_TIMEOUT
            })
            # Try to clean up
            try:
                if child.isalive():
                    child.terminate(force=True)
            except:
                pass
            return False

        except Exception as e:
            self.log("ERROR", f"Multi-alert execution failed on {target_name}: {e}", execution_id=execution_id, extra_data={
                "status": "exception",
                "target": target_name,
                "error": str(e)
            })
            try:
                if child.isalive():
                    child.terminate(force=True)
            except:
                pass
            return False

    def diagnose_ssh_connectivity(self, target_ip: str, alert_hash: str = None, execution_id: str = None) -> bool:
        """Quick SSH connectivity check - returns True if SSH works"""
        try:
            # Quick ping test
            ping_result = subprocess.run(["ping", "-c", "1", "-W", "2", target_ip], 
                                         capture_output=True, text=True, timeout=5)
            ping_ok = ping_result.returncode == 0

            # Quick SSH test
            ssh_test = subprocess.run([
                "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
                "-i", SSH_KEY_PATH, "-p", str(SSH_PORT), f"{SSH_USER}@{target_ip}",
                "echo", "OK"
            ], capture_output=True, text=True, timeout=10)
            ssh_ok = ssh_test.returncode == 0

            if not ssh_ok:
                self.log("SSH", f"Connectivity check: ping={'OK' if ping_ok else 'FAIL'}, ssh=FAIL to {target_ip}", 
                        alert_hash, execution_id, extra_data={
                            "target_ip": target_ip,
                            "ping": ping_ok,
                            "ssh": False,
                            "ssh_error": ssh_test.stderr.strip() if ssh_test.stderr else None
                        })
            return ssh_ok

        except Exception as e:
            self.log("ERROR", f"SSH connectivity check failed: {e}", alert_hash, execution_id)
            return False

    def process_alert(self, alert: Dict) -> bool:
        """Process single alert through plan generation and execution - supports multiple plans per IP"""
        alert_hash = self.get_alert_hash(alert)
        base_execution_id = hashlib.md5(f"{alert_hash}{time.time()}".encode()).hexdigest()[:16]
        start_time = time.time()

        # Extract alert info for logging
        source_ip = alert.get('sourceip', 'unknown')
        dest_ip = alert.get('destip', 'unknown')
        raw_alert = alert.get('raw', '')

        # Try to extract IPs from raw if not in structured fields
        if source_ip == 'unknown' or dest_ip == 'unknown':
            import re
            ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', raw_alert)
            if len(ip_match) >= 2:
                source_ip, dest_ip = ip_match[0], ip_match[1]
            elif len(ip_match) == 1:
                source_ip = ip_match[0]

        self.log("ALERT", f"New: {source_ip} → {dest_ip}", alert_hash, base_execution_id, extra_data={
            "source_ip": source_ip,
            "dest_ip": dest_ip,
            "attack_type": alert.get('attackid', 'unknown'),
            "raw": raw_alert,
            "full_alert": alert
        })

        try:
            # Step 1: Format and generate plans (may return multiple plans)
            alert_text = self.format_alert_for_planner(alert)
            plan_start = time.time()
            plan_response = self.call_planner(alert_text)
            plan_duration = time.time() - plan_start

            if not plan_response:
                self.log("ERROR", f"Plan generation failed ({plan_duration:.2f}s)", alert_hash, base_execution_id)
                return False

            # Handle both old format (single plan) and new format (multiple plans)
            plans_list = []
            if "plans" in plan_response:
                # New format: multiple plans
                plans_list = plan_response.get("plans", [])
            else:
                # Old format: single plan - convert to list for backward compatibility
                plan = plan_response.get("plan", "")
                executor_ip = plan_response.get("executor_host_ip", "")
                if plan and executor_ip:
                    plans_list = [{"executor_host_ip": executor_ip, "plan": plan}]

            if not plans_list:
                self.log("ERROR", "No valid plans in response", alert_hash, base_execution_id, extra_data={"plan_response": plan_response})
                return False

            self.log("PLAN", f"Generated {len(plans_list)} plan(s) ({plan_duration:.2f}s)", alert_hash, base_execution_id, extra_data={
                "num_plans": len(plans_list),
                "plans": plans_list,
                "model": plan_response.get("model", "unknown"),
                "formatted_alert": alert_text
            })

            # Step 2: Execute all plans in parallel (one thread per IP)
            exec_start = time.time()
            success = self.execute_multiple_plans_parallel(plans_list, alert, alert_hash, base_execution_id)
            exec_duration = time.time() - exec_start
            total_duration = time.time() - start_time

            if success:
                self.log("DONE", f"Completed in {total_duration:.1f}s (plan: {plan_duration:.1f}s, exec: {exec_duration:.1f}s)", alert_hash, base_execution_id, extra_data={
                    "total_duration": total_duration,
                    "plan_duration": plan_duration,
                    "exec_duration": exec_duration,
                    "status": "success"
                })
            else:
                self.log("ERROR", f"Execution failed after {exec_duration:.1f}s", alert_hash, base_execution_id, extra_data={
                    "total_duration": total_duration,
                    "status": "failed"
                })

            return success

        except Exception as e:
            self.log("ERROR", f"Exception: {e}", alert_hash, base_execution_id, extra_data={
                "exception": str(e),
                "alert": alert
            })
            return False

    def run_once(self) -> None:
        """Single run of the alert processing loop with multi-alert batching"""
        try:
            new_alerts = self.get_new_alerts()

            if not new_alerts:
                return

            print(f"[auto_responder] Found {len(new_alerts)} new alerts")

            # Check if multi-alert mode is enabled
            if ENABLE_MULTI_ALERT and HAS_PEXPECT and len(new_alerts) > 1:
                processed_count = self.run_multi_alert_mode(new_alerts)
            else:
                # Fall back to single-alert mode
                if ENABLE_MULTI_ALERT and not HAS_PEXPECT:
                    print("[auto_responder] Multi-alert mode requested but pexpect not available, using single-alert mode")
                processed_count = self.run_single_alert_mode(new_alerts)

            if processed_count > 0:
                self.save_processed_alerts()
                print(f"[auto_responder] Successfully processed {processed_count} alerts")

        except Exception as e:
            print(f"[auto_responder] Error in run_once: {e}")

    def run_single_alert_mode(self, alerts: List[Dict]) -> int:
        """Process alerts one at a time (legacy mode)"""
        processed_count = 0
        for alert in alerts:
            alert_hash = self.get_alert_hash(alert)

            try:
                success = self.process_alert(alert)
                if success:
                    with self.lock:
                        self.processed_alerts.add(alert_hash)
                    processed_count += 1
                else:
                    print(f"[auto_responder] Failed to process alert, will retry later")

            except Exception as e:
                print(f"[auto_responder] Error processing alert: {e}")

        return processed_count

    def run_multi_alert_mode(self, alerts: List[Dict]) -> int:
        """
        Process alerts in batches by target machine using multi-alert mode.

        This method:
        1. Groups alerts by target container
        2. Generates plans for all alerts
        3. Executes each batch in a single OpenCode session
        """
        processed_count = 0

        # Step 1: Group alerts by target container and generate plans
        alerts_by_container = {}  # container_name -> [(alert, plan, executor_ip)]
        failed_plans = []  # Alerts that failed plan generation

        for alert in alerts:
            alert_hash = self.get_alert_hash(alert)
            execution_id = hashlib.md5(f"{alert_hash}{time.time()}".encode()).hexdigest()[:16]

            try:
                # Generate plan for this alert
                alert_text = self.format_alert_for_planner(alert)
                plan_response = self.call_planner(alert_text)

                if not plan_response:
                    print(f"[auto_responder] Plan generation failed for alert {alert_hash[:8]}")
                    failed_plans.append(alert)
                    continue

                plan = plan_response.get("plan", "")
                executor_ip = plan_response.get("executor_host_ip", "")

                if not plan or not executor_ip:
                    print(f"[auto_responder] Invalid plan response for alert {alert_hash[:8]}")
                    failed_plans.append(alert)
                    continue

                # Determine target container
                target_info = self.determine_target_ssh_info(executor_ip)
                if not target_info:
                    print(f"[auto_responder] Unknown target IP: {executor_ip}")
                    failed_plans.append(alert)
                    continue

                target_ip, target_name = target_info

                # Map target name to container name
                if target_name == "server":
                    container_name = SERVER_CONTAINER
                elif target_name == "compromised":
                    container_name = COMPROMISED_CONTAINER
                else:
                    print(f"[auto_responder] Unknown target name: {target_name}")
                    failed_plans.append(alert)
                    continue

                # Add to batch
                if container_name not in alerts_by_container:
                    alerts_by_container[container_name] = []
                alerts_by_container[container_name].append((alert, plan, executor_ip))

                self.log("PLAN", f"Generated for {executor_ip} (batching)", alert_hash, execution_id, extra_data={
                    "executor_ip": executor_ip,
                    "plan": plan,
                    "container": container_name
                })

            except Exception as e:
                print(f"[auto_responder] Error processing alert {alert_hash[:8]}: {e}")
                failed_plans.append(alert)

        # Step 2: Execute each batch
        for container_name, alerts_batch in alerts_by_container.items():
            execution_id = hashlib.md5(f"batch_{container_name}_{time.time()}".encode()).hexdigest()[:16]

            try:
                print(f"[auto_responder] Executing {len(alerts_batch)} alerts on {container_name} in single session")

                success = self.execute_multiple_alerts_with_opencode_interactive(
                    alerts_batch,
                    container_name,
                    execution_id
                )

                if success:
                    # Mark all alerts in batch as processed
                    for alert, _, _ in alerts_batch:
                        alert_hash = self.get_alert_hash(alert)
                        with self.lock:
                            self.processed_alerts.add(alert_hash)
                        processed_count += 1
                else:
                    print(f"[auto_responder] Batch execution failed for {container_name}")

            except Exception as e:
                print(f"[auto_responder] Error executing batch on {container_name}: {e}")

        # Step 3: Process any alerts that failed plan generation using single-alert mode
        if failed_plans:
            print(f"[auto_responder] Processing {len(failed_plans)} failed plans in single-alert mode")
            processed_count += self.run_single_alert_mode(failed_plans)

        return processed_count

    def run(self) -> None:
        """Main monitoring loop"""
        print(f"[auto_responder] Monitoring {ALERT_FILE} (poll: {POLL_INTERVAL}s)")

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
