from __future__ import annotations

import os
import sys
import time
from typing import Optional, Any, Dict

from fastapi import FastAPI, HTTPException, Request
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
    base_url = cfg.openai_base_url
    if base_url:
        os.environ.setdefault("LLM_URL", base_url)
    if cfg.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", cfg.openai_api_key)
    return IncidentPlanner(cfg)


app = FastAPI(title="LLM Defender Planner", version="0.1.0")
planner = _build_planner()


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"status": "ok", "model": planner.config.model}


@app.post("/plan", response_model=PlanResponse)
def plan(req: PlanRequest, http_request: Request) -> Any:
    request_start = time.time()

    # Log incoming request details
    print(f"\n{'='*60}", flush=True)
    print(f"[PLAN_ENDPOINT] Received request at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"[PLAN_ENDPOINT] Alert length: {len(req.alert) if req.alert else 0}", flush=True)
    print(f"[PLAN_ENDPOINT] Temperature: {req.temperature}", flush=True)
    print(f"[PLAN_ENDPOINT] Max tokens: {req.max_tokens}", flush=True)
    print(f"[PLAN_ENDPOINT] Client: {http_request.client.host if http_request.client else 'unknown'}", flush=True)

    if not req.alert or not req.alert.strip():
        print(f"[PLAN_ENDPOINT] ERROR: Empty alert received", flush=True)
        raise HTTPException(status_code=400, detail="alert must be non-empty")

    try:
        print(f"[PLAN_ENDPOINT] Calling planner.plan()...", flush=True)
        out = planner.plan(req.alert.strip(), temperature=req.temperature, max_tokens=req.max_tokens)

        # Log output details
        duration = time.time() - request_start
        print(f"[PLAN_ENDPOINT] Planner returned in {duration:.2f}s", flush=True)
        print(f"[PLAN_ENDPOINT] Output keys: {list(out.keys())}", flush=True)
        print(f"[PLAN_ENDPOINT] executor_host_ip: '{out.get('executor_host_ip', '')}'", flush=True)
        print(f"[PLAN_ENDPOINT] plan length: {len(out.get('plan', ''))}", flush=True)
        print(f"[PLAN_ENDPOINT] plan preview: {out.get('plan', '')[:200]}", flush=True)
        print(f"[PLAN_ENDPOINT] request_id: {out.get('request_id', '')}", flush=True)

        # Check for debug info indicating parsing issues
        if "_debug" in out:
            print(f"[PLAN_ENDPOINT] WARNING: Debug info present in response", flush=True)
            print(f"[PLAN_ENDPOINT] _debug: {out['_debug']}", flush=True)

        response = PlanResponse(**out)
        print(f"[PLAN_ENDPOINT] Returning PlanResponse", flush=True)
        print(f"{'='*60}\n", flush=True)
        return response

    except Exception as e:
        duration = time.time() - request_start
        print(f"[PLAN_ENDPOINT] EXCEPTION after {duration:.2f}s: {type(e).__name__}: {e}", flush=True)
        import traceback
        print(f"[PLAN_ENDPOINT] Traceback:\n{traceback.format_exc()}", flush=True)
        print(f"{'='*60}\n", flush=True)
        raise


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests."""
    start_time = time.time()

    # Log request
    print(f"\n[HTTP_REQUEST] {request.method} {request.url.path}", flush=True)

    response = await call_next(request)

    # Log response
    duration = time.time() - start_time
    print(f"[HTTP_RESPONSE] {request.method} {request.url.path} -> {response.status_code} ({duration:.3f}s)\n", flush=True)

    return response
