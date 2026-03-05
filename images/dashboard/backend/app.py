"""Trident Dashboard — FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.models import HealthResponse, ServiceHealth
from backend.routers import alerts, containers, opencode, pcaps, runs, timeline, topology
from backend.services.opencode_client import HOSTS, close_all, get_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("dashboard")

OUTPUTS_DIR = Path(os.getenv("OUTPUTS_DIR", "/outputs"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Trident Dashboard starting up")
    yield
    logger.info("Trident Dashboard shutting down")
    await close_all()


app = FastAPI(
    title="Trident Dashboard",
    description="Real-time monitoring dashboard for the Trident cyber range",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server and any local origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ─────────────────────────────────────────────────
app.include_router(topology.router)
app.include_router(containers.router)
app.include_router(opencode.router)
app.include_router(alerts.router)
app.include_router(runs.router)
app.include_router(pcaps.router)
app.include_router(timeline.router)


# ── Health endpoint ──────────────────────────────────────────────────

def _current_run_id() -> str | None:
    p = OUTPUTS_DIR / ".current_run"
    if p.exists():
        return p.read_text().strip()
    return None


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Dashboard health, including connectivity to OpenCode servers."""
    services: list[ServiceHealth] = []

    for name in HOSTS:
        client = get_client(name)
        h = await client.health()
        services.append(
            ServiceHealth(
                name=f"opencode_{name}",
                healthy=h.get("healthy", False),
                detail=h.get("error", "ok"),
            )
        )

    return HealthResponse(
        status="ok",
        run_id=_current_run_id(),
        timestamp=datetime.utcnow().isoformat(),
        services=services,
    )


# ── Serve React static build (production) ────────────────────────────
# Mount after all API routes so /api/* takes priority
_static_dir = Path(__file__).parent.parent / "frontend" / "dist"
if _static_dir.is_dir():
    # Serve static assets (JS, CSS, images, etc.)
    app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="static-assets")

    # SPA catch-all: serve index.html for any non-API, non-asset path
    _index_html = _static_dir / "index.html"

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        """Serve the React SPA index.html for all non-API routes."""
        # Check if a static file exists at the requested path
        static_file = _static_dir / full_path
        if full_path and static_file.is_file():
            return FileResponse(str(static_file))
        return FileResponse(str(_index_html))
