"""Tests for GET /api/alerts and ws /api/alerts/ws."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RUN_ID = "test_run_20260304_120000"


class TestAlertsEndpoint:
    def test_returns_200_no_outputs(self, client, tmp_path, monkeypatch):
        """Should return empty list gracefully when no outputs dir."""
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", tmp_path)
        r = client.get("/api/alerts")
        assert r.status_code == 200

    def test_empty_when_no_file(self, client, outputs_dir, monkeypatch):
        """No alerts file → count=0, alerts=[]."""
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", outputs_dir)
        data = client.get("/api/alerts").json()
        assert data["count"] == 0
        assert data["alerts"] == []

    def test_returns_alerts_from_file(self, client, outputs_with_data, monkeypatch):
        """Alert file with one entry → count=1."""
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/alerts").json()
        assert data["count"] == 1
        assert len(data["alerts"]) == 1

    def test_alert_fields(self, client, outputs_with_data, monkeypatch):
        """Each alert entry should have expected keys."""
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/alerts").json()
        entry = data["alerts"][0]
        assert "timestamp" in entry
        assert "run_id" in entry
        assert "data" in entry

    def test_run_id_in_response(self, client, outputs_with_data, monkeypatch):
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/alerts").json()
        assert data["run_id"] == RUN_ID

    def test_limit_parameter(self, client, outputs_dir, monkeypatch):
        """Create 10 alerts and verify limit=5 returns only 5."""
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", outputs_dir)
        alerts_file = outputs_dir / RUN_ID / "slips" / "defender_alerts.ndjson"
        entries = [json.dumps({"timestamp": f"2026-03-04T12:00:0{i}", "run_id": RUN_ID, "data": {}}) for i in range(10)]
        alerts_file.write_text("\n".join(entries) + "\n")
        data = client.get("/api/alerts?limit=5").json()
        assert data["count"] <= 5

    def test_query_specific_run_id(self, client, tmp_path, monkeypatch):
        """?run_id=... overrides the current run."""
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", tmp_path)
        # Create alerts for a different run
        alt_run = "logs_20260101_000000"
        (tmp_path / alt_run / "slips").mkdir(parents=True)
        (tmp_path / alt_run / "slips" / "defender_alerts.ndjson").write_text(
            json.dumps({"timestamp": "2026-01-01T00:00:00", "run_id": alt_run, "data": {}}) + "\n"
        )
        data = client.get(f"/api/alerts?run_id={alt_run}").json()
        assert data["count"] == 1
        assert data["run_id"] == alt_run

    def test_skips_invalid_json_lines(self, client, outputs_dir, monkeypatch):
        """Non-JSON lines in the alerts file should be silently skipped."""
        import backend.routers.alerts as alerts_module
        monkeypatch.setattr(alerts_module, "OUTPUTS_DIR", outputs_dir)
        alerts_file = outputs_dir / RUN_ID / "slips" / "defender_alerts.ndjson"
        alerts_file.write_text(
            "NOT VALID JSON\n"
            + json.dumps({"timestamp": "2026-03-04T12:00:00", "run_id": RUN_ID, "data": {}}) + "\n"
        )
        data = client.get("/api/alerts").json()
        assert data["count"] == 1  # only the valid line
