"""Tests for GET /api/timeline/agents and GET /api/timeline/{agent}."""

from __future__ import annotations

import json

import pytest

RUN_ID = "test_run_20260304_120000"

KNOWN_AGENTS = ["coder56", "db_admin", "soc_god_server", "soc_god_compromised"]


class TestTimelineAgentsEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/timeline/agents")
        assert r.status_code == 200

    def test_returns_agents_list(self, client):
        data = client.get("/api/timeline/agents").json()
        assert "agents" in data
        assert isinstance(data["agents"], list)

    def test_all_expected_agents_present(self, client):
        data = client.get("/api/timeline/agents").json()
        for agent in KNOWN_AGENTS:
            assert agent in data["agents"], f"Missing agent: {agent}"


class TestTimelineAgentEndpoint:
    def test_returns_200_no_file(self, client, outputs_dir, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_dir)
        r = client.get("/api/timeline/coder56")
        assert r.status_code == 200

    def test_empty_when_no_timeline_file(self, client, outputs_dir, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_dir)
        data = client.get("/api/timeline/coder56").json()
        assert data["count"] == 0
        assert data["entries"] == []

    def test_agent_field_in_response(self, client, outputs_dir, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_dir)
        data = client.get("/api/timeline/coder56").json()
        assert data["agent"] == "coder56"

    def test_reads_coder56_timeline(self, client, outputs_with_data, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/timeline/coder56").json()
        assert data["count"] == 1
        assert data["entries"][0]["msg"] == "Session started"

    def test_reads_db_admin_timeline(self, client, outputs_with_data, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/timeline/db_admin").json()
        assert data["count"] == 1
        assert data["entries"][0]["msg"] == "db connect"

    def test_unknown_agent_returns_empty(self, client, outputs_dir, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_dir)
        data = client.get("/api/timeline/nonexistent_agent").json()
        assert data["count"] == 0
        assert data["entries"] == []

    def test_multi_entry_timeline(self, client, outputs_dir, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_dir)
        tl_file = outputs_dir / RUN_ID / "coder56" / "auto_responder_timeline.jsonl"
        entries = [
            {"ts": f"2026-03-04T12:00:0{i}", "level": "INFO", "msg": f"event {i}"}
            for i in range(3)
        ]
        tl_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        data = client.get("/api/timeline/coder56").json()
        assert data["count"] == 3

    def test_skips_invalid_json_lines(self, client, outputs_dir, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_dir)
        tl_file = outputs_dir / RUN_ID / "coder56" / "auto_responder_timeline.jsonl"
        tl_file.write_text(
            "NOT JSON\n"
            + json.dumps({"ts": "2026-03-04T12:00:00", "level": "INFO", "msg": "ok"}) + "\n"
        )
        data = client.get("/api/timeline/coder56").json()
        assert data["count"] == 1

    def test_no_current_run_returns_empty(self, client, tmp_path, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", tmp_path)
        data = client.get("/api/timeline/coder56").json()
        assert data["count"] == 0

    def test_limit_parameter(self, client, outputs_dir, monkeypatch):
        import backend.routers.timeline as timeline_module
        monkeypatch.setattr(timeline_module, "OUTPUTS_DIR", outputs_dir)
        tl_file = outputs_dir / RUN_ID / "coder56" / "auto_responder_timeline.jsonl"
        entries = [json.dumps({"ts": "t", "level": "INFO", "msg": f"e{i}"}) for i in range(20)]
        tl_file.write_text("\n".join(entries) + "\n")
        data = client.get("/api/timeline/coder56?limit=5").json()
        assert data["count"] <= 5
