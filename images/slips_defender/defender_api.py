from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx

RUN_ID = os.getenv("RUN_ID", "run_local")
DEFENDER_PORT = int(os.getenv("DEFENDER_PORT", "8000"))
ALERT_FILE = Path("/outputs") / RUN_ID / "slips" / "defender_alerts.ndjson"
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


@app.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest) -> Any:
    """Generate remediation plan for security alert"""
    if not req.alert or not req.alert.strip():
        raise HTTPException(status_code=400, detail="alert must be non-empty")

    alert_text = req.alert.strip()

    # Extract IPs from alert text for determining executor
    import re
    ip_matches = re.findall(r'(\d+\.\d+\.\d+\.\d+)', alert_text)

    # Default to server IP for LLM-based planning (which will determine the actual target)
    executor_ip = "172.31.0.10"  # Default to server

    # Check if alert contains compromised IP (172.30.0.x) - then target compromised
    if len(ip_matches) >= 2:
        source_ip, target_ip = ip_matches[0], ip_matches[1]
        if target_ip.startswith("172.30.0.") or target_ip.startswith("10.0.2."):
            executor_ip = target_ip  # Target is on compromised network
        elif source_ip.startswith("172.30.0.") or source_ip.startswith("10.0.2."):
            executor_ip = target_ip  # Response should run on target system

    # Generate a test plan for demonstration
    plan = f"""SECURITY INCIDENT RESPONSE PLAN (LLM-Generated):

Alert Analysis:
- Alert: "{alert_text}"
- Detected source IPs: {ip_matches if ip_matches else 'None detected'}
- Recommended executor: {executor_ip}

Response Actions:
1. **Immediate Containment**
   - Analyze the alert pattern and traffic characteristics
   - Identify potential attack vectors and affected systems
   - Isolate if necessary to prevent lateral movement

2. **Investigation & Analysis**
   - Review system logs for related activity
   - Check for successful intrusions or privilege escalation
   - Collect forensic evidence for further analysis

3. **Remediation Steps**
   - Block malicious source IPs if confirmed
   - Patch identified vulnerabilities
   - Implement additional monitoring
   - Update security configurations

4. **Monitoring & Validation**
   - Continuously monitor for recurring threats
   - Validate that containment measures are effective
   - Update detection rules based on attack patterns

Note: This is a test LLM-generated plan. Production implementation should use
the external planner service with proper environment configuration."""

    return PlanResponse(
        executor_host_ip=executor_ip,
        plan=plan,
        model="test-llm-planner",
        request_id=str(uuid.uuid4()),
        created=time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime())
    )



