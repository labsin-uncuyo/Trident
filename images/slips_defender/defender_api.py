from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

RUN_ID = os.getenv("RUN_ID", "run_local")
DEFENDER_PORT = int(os.getenv("DEFENDER_PORT", "8000"))
ALERT_FILE = Path("/outputs") / RUN_ID / "defender_alerts.ndjson"
_LOCK = threading.Lock()

app = FastAPI()


class PlanRequest(BaseModel):
    alert: str = Field(..., description="Plaintext IDS alert or SIEM signal")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=10, le=8192)


class PlanResponse(BaseModel):
    executor_host_ip: str
    plan: str
    model: str
    request_id: str
    created: str


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "run_id": RUN_ID, "timestamp": str(time.time())}


@app.post("/alerts")
async def alerts(alert: Dict[str, object]) -> Dict[str, object]:
    enriched = dict(alert)
    enriched.setdefault("run_id", RUN_ID)
    enriched.setdefault("timestamp", time.time())
    line = json.dumps(enriched)
    try:
        with _LOCK:
            ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with ALERT_FILE.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="failed to persist alert") from exc
    return {"status": "stored", "run_id": RUN_ID}


def generate_fallback_plan(alert_text: str) -> Dict[str, Any]:
    """
    Fallback plan generator that creates basic remediation plans
    without requiring LLM services
    """
    alert_lower = alert_text.lower()

    # Extract IPs from alert text
    ip_matches = re.findall(r'(\d+\.\d+\.\d+\.\d+)', alert_text)
    source_ip = ip_matches[0] if len(ip_matches) > 0 else "unknown"
    target_ip = ip_matches[1] if len(ip_matches) > 1 else (ip_matches[0] if len(ip_matches) > 0 else "unknown")

    # Determine attack type and appropriate response
    if "vertical port scan" in alert_lower or "horizontal port scan" in alert_lower:
        executor_ip = target_ip  # Block on target machine
        plan = f"""PORT SCAN REMEDIATION:
1. Block source IP {source_ip} at firewall:
   - iptables -A INPUT -s {source_ip} -j DROP
   - iptables -A FORWARD -s {source_ip} -j DROP

2. Monitor for continued scanning from {source_ip}:
   - Set up monitoring rules for {source_ip}
   - Log any further connection attempts

3. Check target machine {target_ip} for compromise:
   - Review system logs for unusual activity
   - Check for any successful intrusions
   - Verify no services were compromised

4. Consider implementing rate limiting:
   - iptables -A INPUT -s {source_ip} -m limit --limit 10/min -j ACCEPT
   - iptables -A INPUT -s {source_ip} -j DROP

5. Report incident:
   - Document the port scan attempt
   - Escalate if part of larger attack pattern"""

    elif "ddos" in alert_lower or "denial of service" in alert_lower:
        executor_ip = target_ip
        plan = f"""DDOS REMEDIATION:
1. Implement immediate rate limiting:
   - iptables -A INPUT -s {source_ip} -m limit --limit 1/min -j ACCEPT
   - iptables -A INPUT -s {source_ip} -j DROP

2. Enable SYN cookies if not already enabled:
   - echo 1 > /proc/sys/net/ipv4/tcp_syncookies

3. Increase connection tracking limits:
   - echo 65536 > /proc/sys/net/netfilter/nf_conntrack_max

4. Block at network edge:
   - Configure upstream firewall/router to block {source_ip}
   - Consider BGP blackhole for severe attacks

5. Monitor system resources:
   - Watch CPU, memory, and network utilization
   - Be prepared to restart critical services

6. Prepare for failover if service degradation continues"""

    elif "brute force" in alert_lower or "password guessing" in alert_lower:
        executor_ip = target_ip
        plan = f"""BRUTE FORCE REMEDIATION:
1. Immediately block source IP:
   - iptables -A INPUT -s {source_ip} -j DROP

2. Check for successful intrusions:
   - Review authentication logs on {target_ip}
   - Look for successful logins from {source_ip}
   - Check for newly created user accounts

3. Strengthen authentication:
   - Force password changes for any compromised accounts
   - Enable account lockout after failed attempts
   - Consider two-factor authentication

4. Monitor for continued attempts:
   - Set up alerts for failed login attempts
   - Monitor for attempts from other IPs

5. Security audit:
   - Review all user account activity
   - Check for privilege escalation attempts
   - Audit system changes"""

    else:
        # Generic security response
        executor_ip = target_ip
        plan = f"""SECURITY INCIDENT RESPONSE:
1. Investigate the alert:
   - Analyze the traffic from {source_ip} to {target_ip}
   - Review system logs for related activity
   - Determine if this is part of a larger attack

2. Immediate containment:
   - Block source IP {source_ip} if malicious activity confirmed
   - Isolate target system {target_ip} if compromise suspected
   - Preserve evidence for forensic analysis

3. Monitor and analyze:
   - Set up additional monitoring for {target_ip}
   - Watch for lateral movement attempts
   - Log all related network activity

4. Remediation:
   - Patch any vulnerabilities exploited
   - Update security configurations
   - Review and update firewall rules

5. Documentation:
   - Document the incident timeline
   - Record all response actions taken
   - Update incident response procedures"""

    return {
        "executor_host_ip": executor_ip,
        "plan": plan,
        "model": "fallback_rules_v1.0",
        "request_id": str(uuid.uuid4()),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime())
    }


@app.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest) -> Any:
    """Generate remediation plan for security alert"""
    if not req.alert or not req.alert.strip():
        raise HTTPException(status_code=400, detail="alert must be non-empty")

    # Use fallback plan generator
    try:
        plan_result = generate_fallback_plan(req.alert.strip())
        return PlanResponse(**plan_result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate plan: {str(e)}")