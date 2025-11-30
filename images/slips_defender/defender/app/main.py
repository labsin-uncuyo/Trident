from __future__ import annotations

import os
from typing import Optional, Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .planner import IncidentPlanner, PlannerConfig


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


def _build_planner() -> IncidentPlanner:
    cfg = PlannerConfig()
    # Ensure compatibility env vars are present before instantiation
    if cfg.openai_base_url:
        os.environ.setdefault("OPENAI_BASE_URL", cfg.openai_base_url)
    if cfg.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", cfg.openai_api_key)
    return IncidentPlanner(cfg)


app = FastAPI(title="LLM Defender Planner", version="0.1.0")
planner = _build_planner()


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"status": "ok", "model": planner.config.model}


@app.post("/plan", response_model=PlanResponse)
def plan(req: PlanRequest) -> Any:
    if not req.alert or not req.alert.strip():
        raise HTTPException(status_code=400, detail="alert must be non-empty")
    out = planner.plan(req.alert.strip(), temperature=req.temperature, max_tokens=req.max_tokens)
    return PlanResponse(**out)
