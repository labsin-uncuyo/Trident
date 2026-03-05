"""Shared fixtures for Trident Dashboard unit/integration tests.

Run these tests with:
    cd /home/diego/Trident
    .venv/bin/pytest tests/dashboard/ -v

No Docker stack required — all external deps are mocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

# ── Make 'backend' importable ──────────────────────────────────────
_DASHBOARD = Path(__file__).resolve().parents[2] / "images" / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))


# ── Override parent conftest autouse fixtures ──────────────────────
# tests/conftest.py (parent) has stack_ready(autouse=True) which boots
# the full Docker lab. We override it here so dashboard tests stay fast
# and offline.

@pytest.fixture(scope="session")
def lab_env():
    """No-op override — dashboard tests don't need the lab env."""
    return {}


@pytest.fixture(scope="session", autouse=True)
def stack_ready(lab_env):  # type: ignore[override]
    """No-op override — dashboard tests don't start Docker containers."""
    yield


# ── Docker mock ────────────────────────────────────────────────────

def _make_fake_container(name: str, status: str = "running") -> MagicMock:
    c = MagicMock()
    c.name = name
    c.short_id = name[:12]
    c.status = status
    c.image.tags = [f"lab/{name}:latest"]
    c.attrs = {
        "State": {"Status": status},
        "NetworkSettings": {
            "Networks": {
                "lab_net_a": {"IPAddress": "172.30.0.10"},
            }
        },
    }
    return c


@pytest.fixture()
def mock_docker():
    """Patch docker.from_env() to return a fake client with sample containers."""
    fake_containers = [
        _make_fake_container("lab_router", "running"),
        _make_fake_container("lab_compromised", "running"),
        _make_fake_container("lab_server", "running"),
        _make_fake_container("lab_slips_defender", "exited"),
    ]
    fake_client = MagicMock()
    fake_client.containers.list.return_value = fake_containers

    with patch("docker.from_env", return_value=fake_client):
        yield fake_client


# ── Outputs directory fixture ──────────────────────────────────────

RUN_ID = "test_run_20260304_120000"


@pytest.fixture()
def outputs_dir(tmp_path: Path) -> Path:
    """Create a minimal outputs/ directory tree for a single run."""
    (tmp_path / ".current_run").write_text(RUN_ID)
    run = tmp_path / RUN_ID
    (run / "slips").mkdir(parents=True)
    (run / "pcaps").mkdir(parents=True)
    (run / "coder56").mkdir(parents=True)
    (run / "benign_agent").mkdir(parents=True)
    (run / "defender" / "compromised").mkdir(parents=True)
    (run / "defender" / "server").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def outputs_with_data(outputs_dir: Path) -> Path:
    """outputs_dir pre-loaded with sample alerts, pcaps, and timeline data."""
    run = outputs_dir / RUN_ID

    # Sample alert
    alert = {
        "timestamp": "2026-03-04T12:00:00",
        "run_id": RUN_ID,
        "data": {"type": "dns_high_entropy", "ip": "172.30.0.10", "score": 0.8},
    }
    (run / "slips" / "defender_alerts.ndjson").write_text(
        json.dumps(alert) + "\n"
    )

    # Sample PCAP file
    (run / "pcaps" / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

    # Sample timeline
    timeline_entry = {"ts": "2026-03-04T12:00:01", "level": "INFO", "msg": "Session started"}
    (run / "coder56" / "auto_responder_timeline.jsonl").write_text(
        json.dumps(timeline_entry) + "\n"
    )
    # db_admin timeline
    (run / "benign_agent" / "db_admin_timeline.jsonl").write_text(
        json.dumps({"ts": "2026-03-04T12:00:02", "level": "INFO", "msg": "db connect"}) + "\n"
    )

    return outputs_dir


# ── FastAPI TestClient ─────────────────────────────────────────────

@pytest.fixture()
def client(mock_docker) -> Generator[TestClient, None, None]:
    """TestClient for the FastAPI app with Docker mocked."""
    from backend.app import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
