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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
import requests
import logging

# Configuration
RUN_ID = os.getenv("RUN_ID", "run_local")
ALERT_FILE = Path("/outputs") / RUN_ID / "defender_alerts.ndjson"
PROCESSED_FILE = Path("/outputs") / RUN_ID / "processed_alerts.json"
PLANNER_URL = os.getenv("PLANNER_URL", "http://127.0.0.1:1654/plan")
OPENCODE_TIMEOUT = int(os.getenv("OPENCODE_TIMEOUT", "300"))  # 5 minutes
POLL_INTERVAL = float(os.getenv("AUTO_RESPONDER_INTERVAL", "5"))
MAX_EXECUTION_RETRIES = int(os.getenv("MAX_EXECUTION_RETRIES", "3"))

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
                "compromised_ip": COMPROMISED_IP
            }
        })

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
                print(f"[auto_responder] Loaded {len(self.processed_alerts)} processed alerts")
        except Exception as e:
            print(f"[auto_responder] Failed to load processed alerts: {e}")
            self.processed_alerts = set()

    def save_processed_alerts(self) -> None:
        """Save set of processed alert hashes"""
        try:
            PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
            with PROCESSED_FILE.open("w") as f:
                json.dump({
                    "processed_hashes": list(self.processed_alerts),
                    "last_updated": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"[auto_responder] Failed to save processed alerts: {e}")

    def get_alert_hash(self, alert: Dict) -> str:
        """Generate hash for alert deduplication"""
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

                        if alert_hash not in self.processed_alerts:
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

        # Escape the context properly for shell command
        escaped_context = context.replace('"', '\\"').replace('\n', '\\n')
        
        # Build the full SSH command
        opencode_api_key = os.environ.get("OPENCODE_API_KEY", "")
        ssh_base = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile={SSH_KNOWN_HOSTS} -i {SSH_KEY_PATH} -p {SSH_PORT} {SSH_USER}@{target_ip}"
        full_ssh_cmd = f"{ssh_base} 'OPENCODE_API_KEY={opencode_api_key} opencode run --agent soc_god \"{escaped_context}\"'"

        for attempt in range(MAX_EXECUTION_RETRIES):
            try:
                # Log the SSH execution attempt with full command
                self.log("SSH", f"→ {target_name}@{target_ip} (attempt {attempt + 1}/{MAX_EXECUTION_RETRIES})", alert_hash, execution_id, extra_data={
                    "target": target_name,
                    "target_ip": target_ip,
                    "attempt": attempt + 1,
                    "command": f"{ssh_base} 'OPENCODE_API_KEY=*** opencode run --agent soc_god \"...\"'",
                    "context": context,
                    "timeout": OPENCODE_TIMEOUT
                })

                # Use SSH to connect to target machine and run OpenCode
                ssh_cmd = [
                    "bash", "-c", f"""
                    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile={SSH_KNOWN_HOSTS} \\
                        -i {SSH_KEY_PATH} \\
                        -p {SSH_PORT} \\
                        {SSH_USER}@{target_ip} \\
                        'OPENCODE_API_KEY={opencode_api_key} opencode run --agent soc_god "{escaped_context}"'
                    """
                ]

                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    timeout=OPENCODE_TIMEOUT,
                    check=True
                )

                self.log("EXEC", f"✓ Success on {target_name}", alert_hash, execution_id, extra_data={
                    "status": "success",
                    "target": target_name,
                    "output": result.stdout,
                    "stderr": result.stderr if result.stderr else None
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
                
                self.log("ERROR", f"{'SSH failed' if ssh_failed else 'OpenCode failed'} on {target_name} (exit {e.returncode})", alert_hash, execution_id, extra_data={
                    "status": "ssh_error" if ssh_failed else "exec_error",
                    "target": target_name,
                    "exit_code": e.returncode,
                    "stdout": e.stdout,
                    "stderr": e.stderr
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
        """Process single alert through plan generation and execution"""
        alert_hash = self.get_alert_hash(alert)
        execution_id = hashlib.md5(f"{alert_hash}{time.time()}".encode()).hexdigest()[:16]
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

        self.log("ALERT", f"New: {source_ip} → {dest_ip}", alert_hash, execution_id, extra_data={
            "source_ip": source_ip,
            "dest_ip": dest_ip,
            "attack_type": alert.get('attackid', 'unknown'),
            "raw": raw_alert,
            "full_alert": alert
        })

        try:
            # Step 1: Format and generate plan
            alert_text = self.format_alert_for_planner(alert)
            plan_start = time.time()
            plan_response = self.call_planner(alert_text)
            plan_duration = time.time() - plan_start

            if not plan_response:
                self.log("ERROR", f"Plan generation failed ({plan_duration:.2f}s)", alert_hash, execution_id)
                return False

            plan = plan_response.get("plan", "")
            executor_ip = plan_response.get("executor_host_ip", "")

            if not plan or not executor_ip:
                self.log("ERROR", "Invalid plan response", alert_hash, execution_id, extra_data={"plan_response": plan_response})
                return False

            self.log("PLAN", f"Generated for {executor_ip} ({plan_duration:.2f}s)", alert_hash, execution_id, extra_data={
                "executor_ip": executor_ip,
                "plan": plan,
                "model": plan_response.get("model", "unknown"),
                "formatted_alert": alert_text
            })

            # Step 2: Execute plan
            exec_start = time.time()
            success = self.execute_plan_with_opencode(plan, executor_ip, alert, alert_hash, execution_id)
            exec_duration = time.time() - exec_start
            total_duration = time.time() - start_time

            if success:
                self.log("DONE", f"Completed in {total_duration:.1f}s (plan: {plan_duration:.1f}s, exec: {exec_duration:.1f}s)", alert_hash, execution_id, extra_data={
                    "total_duration": total_duration,
                    "plan_duration": plan_duration,
                    "exec_duration": exec_duration,
                    "status": "success"
                })
            else:
                self.log("ERROR", f"Execution failed after {exec_duration:.1f}s", alert_hash, execution_id, extra_data={
                    "total_duration": total_duration,
                    "status": "failed"
                })

            return success

        except Exception as e:
            self.log("ERROR", f"Exception: {e}", alert_hash, execution_id, extra_data={
                "exception": str(e),
                "alert": alert
            })
            return False

    def run_once(self) -> None:
        """Single run of the alert processing loop"""
        try:
            new_alerts = self.get_new_alerts()

            if not new_alerts:
                return

            print(f"[auto_responder] Found {len(new_alerts)} new alerts")

            processed_count = 0
            for alert in new_alerts:
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

            if processed_count > 0:
                self.save_processed_alerts()
                print(f"[auto_responder] Successfully processed {processed_count} alerts")

        except Exception as e:
            print(f"[auto_responder] Error in run_once: {e}")

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