"""Run management endpoints."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from backend.models import RunInfo

router = APIRouter(prefix="/api/runs", tags=["runs"])

OUTPUTS_DIR = Path("/outputs")


def _current_run_id() -> str | None:
    p = OUTPUTS_DIR / ".current_run"
    if p.exists():
        return p.read_text().strip()
    return None


@router.get("/current")
async def get_current_run():
    """Return the current active run ID."""
    rid = _current_run_id()
    return {"run_id": rid}


@router.get("", response_model=list[RunInfo])
async def list_runs():
    """List all run directories."""
    current = _current_run_id()
    runs: list[RunInfo] = []

    if not OUTPUTS_DIR.exists():
        return runs

    for entry in sorted(OUTPUTS_DIR.iterdir(), reverse=True):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        # Skip non-run dirs (heuristic: run dirs start with "logs_")
        if not entry.name.startswith("logs_"):
            continue

        has_pcaps = (entry / "pcaps").is_dir() and any((entry / "pcaps").iterdir()) if (entry / "pcaps").is_dir() else False
        has_alerts = (entry / "slips" / "defender_alerts.ndjson").exists()

        # Parse creation time from dir name
        created = ""
        try:
            # logs_YYYYMMDD_HHMMSS
            ts_part = entry.name.replace("logs_", "")
            dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
            created = dt.isoformat()
        except ValueError:
            stat = entry.stat()
            created = datetime.fromtimestamp(stat.st_ctime).isoformat()

        runs.append(
            RunInfo(
                run_id=entry.name,
                path=str(entry),
                is_current=(entry.name == current),
                created=created,
                has_pcaps=has_pcaps,
                has_alerts=has_alerts,
            )
        )
    return runs
