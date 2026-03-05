"""Tests for GET /api/runs and GET /api/runs/current."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

RUN_ID = "test_run_20260304_120000"


class TestRunsCurrentEndpoint:
    def test_returns_200(self, client, outputs_dir, monkeypatch):
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", outputs_dir)
        r = client.get("/api/runs/current")
        assert r.status_code == 200

    def test_returns_run_id(self, client, outputs_dir, monkeypatch):
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", outputs_dir)
        data = client.get("/api/runs/current").json()
        assert data["run_id"] == RUN_ID

    def test_no_current_run_returns_none(self, client, tmp_path, monkeypatch):
        """When .current_run is missing, run_id should be None."""
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        data = client.get("/api/runs/current").json()
        assert data["run_id"] is None


class TestRunsListEndpoint:
    def test_returns_200_empty(self, client, tmp_path, monkeypatch):
        """Empty outputs dir returns empty list."""
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        r = client.get("/api/runs")
        assert r.status_code == 200
        assert r.json() == []

    def test_run_dirs_must_start_with_logs_(self, client, tmp_path, monkeypatch):
        """Only directories starting with 'logs_' are listed as runs."""
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        (tmp_path / "not_a_run").mkdir()
        (tmp_path / "logs_20260304_120000").mkdir()
        data = client.get("/api/runs").json()
        assert len(data) == 1
        assert data[0]["run_id"] == "logs_20260304_120000"

    def test_is_current_flag(self, client, tmp_path, monkeypatch):
        """The run ID in .current_run should have is_current=True."""
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        run_dir = tmp_path / "logs_20260304_120000"
        run_dir.mkdir()
        (tmp_path / ".current_run").write_text("logs_20260304_120000")
        data = client.get("/api/runs").json()
        assert data[0]["is_current"] is True

    def test_has_pcaps_flag(self, client, tmp_path, monkeypatch):
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        run_dir = tmp_path / "logs_20260304_120000"
        pcaps = run_dir / "pcaps"
        pcaps.mkdir(parents=True)
        (pcaps / "capture.pcap").write_bytes(b"\x00" * 20)
        data = client.get("/api/runs").json()
        assert data[0]["has_pcaps"] is True

    def test_has_alerts_flag(self, client, tmp_path, monkeypatch):
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        run_dir = tmp_path / "logs_20260304_120000"
        slips = run_dir / "slips"
        slips.mkdir(parents=True)
        (slips / "defender_alerts.ndjson").write_text(
            '{"type":"alert"}\n'
        )
        data = client.get("/api/runs").json()
        assert data[0]["has_alerts"] is True

    def test_run_entry_fields(self, client, tmp_path, monkeypatch):
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        (tmp_path / "logs_20260304_120000").mkdir()
        data = client.get("/api/runs").json()
        entry = data[0]
        assert "run_id" in entry
        assert "path" in entry
        assert "is_current" in entry
        assert "created" in entry
        assert "has_pcaps" in entry
        assert "has_alerts" in entry

    def test_multiple_runs_sorted_newest_first(self, client, tmp_path, monkeypatch):
        import backend.routers.runs as runs_module
        monkeypatch.setattr(runs_module, "OUTPUTS_DIR", tmp_path)
        (tmp_path / "logs_20260301_080000").mkdir()
        (tmp_path / "logs_20260304_120000").mkdir()
        data = client.get("/api/runs").json()
        assert len(data) == 2
        # Newest first (sorted in reverse)
        assert data[0]["run_id"] == "logs_20260304_120000"
