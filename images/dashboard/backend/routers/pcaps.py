"""PCAP listing + future traffic analysis stubs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.models import PcapFile, PcapSummary

router = APIRouter(prefix="/api/pcaps", tags=["pcaps"])

OUTPUTS_DIR = Path("/outputs")


def _current_run_id() -> str | None:
    p = OUTPUTS_DIR / ".current_run"
    if p.exists():
        return p.read_text().strip()
    return None


def _pcaps_dir(run_id: str | None = None) -> Path:
    rid = run_id or _current_run_id()
    if not rid:
        return OUTPUTS_DIR / "__nonexistent__"
    return OUTPUTS_DIR / rid / "pcaps"


@router.get("", response_model=list[PcapFile])
async def list_pcaps(run_id: str | None = None):
    """List PCAP files for the current (or specified) run."""
    pcap_dir = _pcaps_dir(run_id)
    if not pcap_dir.exists():
        return []

    results: list[PcapFile] = []
    for f in sorted(pcap_dir.iterdir()):
        if not f.name.endswith(".pcap"):
            continue
        stat = f.stat()
        results.append(
            PcapFile(
                filename=f.name,
                path=str(f),
                size_bytes=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            )
        )
    return results


@router.get("/{filename}/summary", response_model=PcapSummary)
async def get_pcap_summary(filename: str, run_id: str | None = None):
    """Parse a PCAP and return protocol summary.

    Phase 2 — currently returns 501 Not Implemented.
    """
    raise HTTPException(
        status_code=501,
        detail="PCAP analysis not yet implemented. Coming in Phase 2.",
    )
