#!/usr/bin/env python3
"""
Simplified Auto Responder with One-line SSH Execution
"""

import json
import os
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
PLANNER_URL = os.getenv("PLANNER_URL", "http://127.0.0.1:8001/plan")
OPENCODE_TIMEOUT = int(os.getenv("OPENCODE_TIMEOUT", "300"))
POLL_INTERVAL = float(os.getenv("AUTO_RESPONDER_INTERVAL", "5"))
MAX_EXECUTION_RETRIES = int(os.getenv("MAX_EXECUTION_RETRIES", "3"))

class AutoResponder:
    def __init__(self):
        self.processed_alerts: Set[str] = set()
        self.lock = threading.Lock()
        self.setup_logging()
        self.load_processed_alerts()
        self.log("SYSTEM", "AutoResponder initialized")

    def setup_logging(self):
        """Setup logging"""
        log_file = Path("/outputs") / RUN_ID / "auto_responder_detailed.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("auto_responder")
        self.logger.setLevel(logging.INFO)

        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def log(self, level: str, message: str, alert_hash: str = None, execution_id: str = None):
        """Log with context"""
        context_parts = []
        if alert_hash:
            context_parts.append(f"alert:{alert_hash[:8]}")
        if execution_id:
            context_parts.append(f"exec:{execution_id[:8]}")

        context = f"[{', '.join(context_parts)}]" if context_parts else ""
        log_message = f"{message} {context}"

        if level.upper() == "ERROR":
            self.logger.error(log_message)
        elif level.upper() == "WARNING":
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)

    def load_processed_alerts(self):
        """Load processed alerts"""
        try:
            # Initialize empty processed alerts set for repeat detection
            self.processed_alerts = set()
        except Exception as e:
            self.processed_alerts = set()

    def save_processed_alerts(self):
        """Save processed alerts"""
        # No longer saving to file since we use in-memory tracking
        pass

    def should_respond_to_alert(self, alert: Dict) -> bool:
        """Check if alert should trigger automated response"""
        # Respond to medium, high, and critical threat alerts
        threat_level = alert.get('threat_level', '').lower()
        if threat_level not in ['medium', 'high', 'critical']:
            return False

        # Don't respond to heartbeat messages
        note = alert.get('note', '').lower()
        if 'heartbeat' in note:
            return False

        return True

    def is_repeat_alert(self, alert: Dict) -> bool:
        """Check if this is a repeat alert from same source to same target"""
        source_ip = alert.get('sourceip', '')
        dest_ip = alert.get('destip', '')
        attack_id = alert.get('attackid', '')

        # Create key for this alert combination
        repeat_key = f"{source_ip}->{dest_ip}->{attack_id}"

        # Check if we've seen this combination recently
        if repeat_key in self.processed_alerts:
            return False

        # Mark this combination as seen
        self.processed_alerts.add(repeat_key)

        # Clean up old entries (keep only last 100)
        if len(self.processed_alerts) > 100:
            # Convert to list, sort by recency (using timestamp), keep latest 100
            all_entries = sorted(self.processed_alerts, reverse=True)[:100]
            self.processed_alerts = set(all_entries)

        return False

    def get_alert_hash(self, alert: Dict) -> str:
        """Generate hash for alert deduplication"""
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
        """Get unprocessed alerts"""
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
                        alert_hash = self.get_alert_hash(alert)

                        if alert_hash not in self.processed_alerts:
                            new_alerts.append(alert)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            pass

        return new_alerts

    def format_alert_for_planner(self, alert: Dict) -> str:
        """Format alert for planner"""
        timestamp = alert.get("timestamp", datetime.now().isoformat())
        source_ip = alert.get("sourceip", "unknown")
        dest_ip = alert.get("destip", "unknown")
        attack_id = alert.get("attackid", "unknown")
        proto = alert.get("proto", "unknown")

        description = alert.get("description", "") or alert.get("threat_level", "")

        formatted = f"{timestamp} {source_ip} {attack_id} ({proto}) targeting {dest_ip}"
        if description:
            formatted += f" - {description}"

        return formatted

    def call_planner(self, alert_text: str) -> Optional[Dict]:
        """Call planner service"""
        try:
            payload = {"alert": alert_text}
            response = requests.post(PLANNER_URL, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return None

    def execute_plan_with_opencode(self, plan: str, executor_ip: str, alert: Dict, alert_hash: str = None, execution_id: str = None) -> bool:
        """Execute plan with one-line SSH"""
        # Simple IP to container mapping
        if executor_ip in ["172.31.0.10", "127.0.0.1"] or executor_ip.startswith("172.31."):
            target_container = "lab_server"
            target_ip = "172.31.0.10"
        else:
            target_container = "lab_compromised"
            target_ip = "172.30.0.10"

        self.log("EXECUTION", f"🎯 Target: {target_container} ({target_ip})", alert_hash, execution_id)

        # Simple context for OpenCode
        context = f"Execute security plan: {plan} | Alert: {alert.get('attackid', 'unknown')} from {alert.get('sourceip', 'unknown')}"

        try:
            start_time = time.time()
            self.log("EXECUTION", f"🚀 Running OpenCode via SSH", alert_hash, execution_id)

            # One-line SSH command
            cmd = f'ssh -i /root/.ssh/id_rsa_auto -o StrictHostKeyChecking=no root@{target_ip} "opencode run --agent soc_god \\"{context}\\""'

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)

            duration = time.time() - start_time

            if result.returncode == 0:
                self.log("SUCCESS", f"✅ Execution successful ({duration:.1f}s)", alert_hash, execution_id)
                self.log("OUTPUT", f"📋 {result.stdout[:200]}...", alert_hash, execution_id)

                # Log execution
                execution_log = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "execution_id": execution_id,
                    "alert_hash": alert_hash,
                    "target_container": target_container,
                    "target_ip": target_ip,
                    "duration": duration,
                    "success": True,
                    "output": result.stdout,
                    "plan": plan,
                    "alert": alert
                }

                log_file = Path("/outputs") / RUN_ID / "executions.jsonl"
                log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file, "a") as f:
                    f.write(json.dumps(execution_log) + "\n")

                return True
            else:
                self.log("ERROR", f"❌ Execution failed: {result.stderr[:100]}", alert_hash, execution_id)
                return False

        except Exception as e:
            self.log("ERROR", f"💥 SSH execution error: {e}", alert_hash, execution_id)
            return False

    def process_alert(self, alert: Dict) -> bool:
        """Process single alert"""
        alert_hash = self.get_alert_hash(alert)
        execution_id = hashlib.md5(f"{alert_hash}{time.time()}".encode()).hexdigest()[:16]

        # Check if this alert should trigger automated response
        if not self.should_respond_to_alert(alert):
            # Skip low-threat and heartbeat alerts silently
            return True

        # Check for repeated alerts from same source to same target
        if self.is_repeat_alert(alert):
            self.log("INFO", f"⏭ Skipping repeat alert - {alert.get('attackid', 'unknown')} from {alert.get('sourceip', 'unknown')} -> {alert.get('destip', 'unknown')} (threat: {alert.get('threat_level', 'unknown')})", alert_hash, execution_id)
            return True

        self.log("ALERT", f"🚨 HIGH-THREAT ALERT - {alert.get('attackid', 'unknown')} from {alert.get('sourceip', 'unknown')} -> {alert.get('destip', 'unknown')} (threat: {alert.get('threat_level', 'unknown')})", alert_hash, execution_id)

        try:
            # Generate plan
            self.log("PLANNER", "📝 Generating plan...", alert_hash, execution_id)
            alert_text = self.format_alert_for_planner(alert)
            plan_response = self.call_planner(alert_text)

            if not plan_response:
                self.log("ERROR", "❌ Plan generation failed", alert_hash, execution_id)
                return False

            plan = plan_response.get("plan", "")
            executor_ip = plan_response.get("executor_host_ip", "127.0.0.1")

            if not plan:
                self.log("ERROR", "❌ Empty plan generated", alert_hash, execution_id)
                return False

            self.log("PLANNER", f"✅ Plan generated for {executor_ip}", alert_hash, execution_id)

            # Execute plan
            success = self.execute_plan_with_opencode(plan, executor_ip, alert, alert_hash, execution_id)

            if success:
                self.log("SUCCESS", f"🎉 High-threat alert processed successfully", alert_hash, execution_id)
            else:
                self.log("ERROR", f"❌ Plan execution failed", alert_hash, execution_id)

            return success

        except Exception as e:
            self.log("ERROR", f"💥 Processing error: {e}", alert_hash, execution_id)
            return False

    def run_once(self):
        """Single run of alert processing"""
        try:
            new_alerts = self.get_new_alerts()

            if not new_alerts:
                return

            self.log("INFO", f"📡 Processing {len(new_alerts)} new alerts")

            for alert in new_alerts:
                alert_hash = self.get_alert_hash(alert)
                try:
                    success = self.process_alert(alert)
                    if success:
                        with self.lock:
                            self.processed_alerts.add(alert_hash)
                except Exception as e:
                    self.log("ERROR", f"⚠️ Alert processing error: {e}")

            if len(new_alerts) > 0:
                self.save_processed_alerts()

        except Exception as e:
            self.log("ERROR", f"💥 Run error: {e}")

    def run(self):
        """Main monitoring loop"""
        self.log("SYSTEM", "🚀 Starting automated response service")
        self.log("SYSTEM", f"📡 Monitoring: {ALERT_FILE}")
        self.log("SYSTEM", f"🧠 Planner URL: {PLANNER_URL}")
        self.log("SYSTEM", f"⏱️ Poll interval: {POLL_INTERVAL}s")

        while True:
            try:
                self.run_once()
                time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                self.log("SYSTEM", "🛑 Shutting down...")
                break
            except Exception as e:
                self.log("ERROR", f"💥 Loop error: {e}")
                time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    import subprocess
    responder = AutoResponder()
    responder.run()