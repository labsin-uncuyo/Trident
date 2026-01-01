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
import httpx
import logging

logger = logging.getLogger(__name__)

# Configuration
RUN_ID = os.getenv("RUN_ID", "run_local")
DEFENDER_PORT = int(os.getenv("DEFENDER_PORT", "8000"))
ALERT_FILE = Path("/outputs") / RUN_ID / "slips" / "defender_alerts.ndjson"
_LOCK = threading.Lock()

# LLM Configuration
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://chat.ai.e-infra.cz/api/v1")
LLM_API_KEY = os.getenv("OPENCODE_API_KEY", "")
PLANNER_MODEL = "gpt-oss-120b"  # Hardcoded for /plan endpoint only
# Note: LLM_MODEL env var is used by OpenCode execution (should remain qwen3-coder)
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

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


async def call_llm_for_plan(alert_text: str, executor_ip_hint: str) -> tuple[str, str]:
    """
    Call LLM API to generate incident response plan.
    Returns (executor_ip, plan).
    """
    # Build the system prompt for security incident response
    system_prompt = """You are an expert Security Operations Center (SOC) analyst and incident responder specializing in Linux system security, network forensics, and containment operations.

# Environment
You are operating in a cybersecurity lab environment with Linux systems. Your SSH agent can execute commands on any host in the network.

# Your Task
Given a security alert, generate a high-level incident response plan that:
1. Analyzes the threat and determines its severity
2. Identifies which host to execute remediation on based on the alert context
3. Provides strategic, high-level containment and investigation actions

# Choosing the Executor Host
Decide where to execute based on the alert:
- If the threat targets a system (e.g., scanning, attacks against a server), execute on the TARGET system to defend it
- If the threat originates from a compromised host (e.g., data exfiltration, malicious outbound traffic), execute on the SOURCE host to investigate and clean it
- Consider network topology and where remediation will be most effective

# CRITICAL - RESPONSE FORMAT
You must respond with valid JSON only. No markdown, no code blocks, no explanation outside the JSON.

Format:
{
  "executor_ip": "<IP_ADDRESS>",
  "threat_analysis": "<detailed threat analysis>",
  "immediate_actions": "<high-level containment steps - NO specific commands>",
  "investigation_steps": "<high-level forensic approach - NO specific commands>",
  "remediation_actions": "<high-level remediation strategy - NO specific commands>",
  "validation_steps": "<high-level verification approach - NO specific commands>"
}

# Important Guidelines
- DO NOT include specific bash commands, shell syntax, or code
- Describe WHAT to do, not HOW to do it (e.g., "Block network traffic from source IP" not "iptables -A INPUT -s 1.2.3.4 -j DROP")
- Focus on strategic objectives and priorities
- An execution agent will translate your plan into actual commands
- Think like a SOC lead planning the response, not a technician executing it

# Important Notes
- You are a DEFENDER. Protect systems, contain threats, preserve evidence.
- Preserve logs for forensics - don't destroy evidence.
- Prioritize containment when threat is active.
- Consider both immediate containment and longer-term remediation."""

    user_message = f"""# Security Alert

{alert_text}

Generate an incident response plan in JSON format. Choose the appropriate executor IP based on the alert context. Provide high-level strategic guidance without specific commands."""

    if not LLM_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="LLM API key not configured. Set OPENCODE_API_KEY environment variable."
        )

    # Make API call to LLM
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": PLANNER_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4096
                }
            )
            response.raise_for_status()
            result = response.json()

            # Extract the generated plan
            plan_content = result["choices"][0]["message"]["content"]

            # Try to parse as JSON
            try:
                # Strip markdown code blocks if present
                plan_content = plan_content.strip()
                if plan_content.startswith("```"):
                    plan_content = plan_content.split("```")[1]
                    if plan_content.startswith("json"):
                        plan_content = plan_content[4:]
                plan_content = plan_content.strip()

                plan_json = json.loads(plan_content)
                executor_ip = plan_json.get("executor_ip", executor_ip_hint)

                # Build formatted plan from JSON
                plan = f"""## Threat Analysis
{plan_json.get('threat_analysis', 'No analysis provided.')}

## Immediate Actions
{plan_json.get('immediate_actions', 'No immediate actions provided.')}

## Investigation Steps
{plan_json.get('investigation_steps', 'No investigation steps provided.')}

## Remediation Actions
{plan_json.get('remediation_actions', 'No remediation actions provided.')}

## Validation Steps
{plan_json.get('validation_steps', 'No validation steps provided.')}"""

                return executor_ip, plan

            except (json.JSONDecodeError, KeyError) as e:
                # Fallback if JSON parsing fails
                logger.warning(f"Failed to parse LLM response as JSON: {e}")
                logger.warning(f"Response was: {plan_content[:500]}")
                logger.warning(f"Using hint: {executor_ip_hint}")
                return executor_ip_hint, plan_content

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"LLM API error: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate plan: {str(e)}")


@app.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest) -> Any:
    """Generate remediation plan for security alert using LLM"""
    if not req.alert or not req.alert.strip():
        raise HTTPException(status_code=400, detail="alert must be non-empty")

    alert_text = req.alert.strip()

    # Extract IPs from alert text for hinting the executor
    ip_matches = re.findall(r'(\d+\.\d+\.\d+\.\d+)', alert_text)

    # Determine hint for executor IP based on alert IPs
    executor_ip_hint = "172.31.0.10"  # Default to server

    if len(ip_matches) >= 2:
        source_ip, target_ip = ip_matches[0], ip_matches[1]
        # If target is on compromised network, execute there
        if target_ip.startswith("172.30.0.") or target_ip.startswith("10.0.2."):
            executor_ip_hint = target_ip
        # If source is from compromised network, target the server
        elif source_ip.startswith("172.30.0."):
            executor_ip_hint = target_ip if target_ip.startswith("172.31.0.") else "172.31.0.10"

    # Call LLM to generate the actual plan
    executor_ip, llm_plan = await call_llm_for_plan(alert_text, executor_ip_hint)

    return PlanResponse(
        executor_host_ip=executor_ip,
        plan=llm_plan,
        model=PLANNER_MODEL,
        request_id=str(uuid.uuid4()),
        created=time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime())
    )



