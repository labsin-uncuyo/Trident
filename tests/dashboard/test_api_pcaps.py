"""Tests for GET /api/pcaps and GET /api/pcaps/{filename}/summary."""

from __future__ import annotations

from pathlib import Path

import pytest

RUN_ID = "test_run_20260304_120000"


class TestPcapsListEndpoint:
    def test_returns_200_empty(self, client, outputs_dir, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_dir)
        r = client.get("/api/pcaps")
        assert r.status_code == 200

    def test_empty_when_no_pcaps(self, client, outputs_dir, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_dir)
        data = client.get("/api/pcaps").json()
        assert data == []

    def test_returns_pcap_files(self, client, outputs_with_data, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/pcaps").json()
        assert len(data) == 1
        assert data[0]["filename"] == "capture.pcap"

    def test_pcap_entry_fields(self, client, outputs_with_data, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/pcaps").json()
        entry = data[0]
        assert "filename" in entry
        assert "path" in entry
        assert "size_bytes" in entry
        assert "modified" in entry

    def test_only_pcap_extension_listed(self, client, outputs_dir, monkeypatch):
        """Non-.pcap files in the pcaps directory must be ignored."""
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_dir)
        pcap_dir = outputs_dir / RUN_ID / "pcaps"
        (pcap_dir / "capture.pcap").write_bytes(b"\x00" * 24)
        (pcap_dir / "README.txt").write_text("ignore me")
        data = client.get("/api/pcaps").json()
        filenames = [e["filename"] for e in data]
        assert "capture.pcap" in filenames
        assert "README.txt" not in filenames

    def test_size_bytes_correct(self, client, outputs_dir, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_dir)
        pcap_dir = outputs_dir / RUN_ID / "pcaps"
        payload = b"\xd4\xc3\xb2\xa1" + b"\x00" * 20
        (pcap_dir / "test.pcap").write_bytes(payload)
        data = client.get("/api/pcaps").json()
        assert data[0]["size_bytes"] == len(payload)

    def test_query_specific_run_id(self, client, tmp_path, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", tmp_path)
        alt_run = "logs_20260101_000000"
        pcap_dir = tmp_path / alt_run / "pcaps"
        pcap_dir.mkdir(parents=True)
        (pcap_dir / "other.pcap").write_bytes(b"\x00" * 10)
        data = client.get(f"/api/pcaps?run_id={alt_run}").json()
        assert len(data) == 1
        assert data[0]["filename"] == "other.pcap"

    def test_missing_outputs_returns_empty(self, client, tmp_path, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", tmp_path)
        # No .current_run → no run dir found → empty list
        data = client.get("/api/pcaps").json()
        assert data == []


class TestPcapSummaryEndpoint:
    def test_returns_501_not_implemented(self, client, outputs_with_data, monkeypatch):
        """Phase 2 stub — must return 501 until implemented."""
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_with_data)
        r = client.get("/api/pcaps/capture.pcap/summary")
        assert r.status_code == 501

    def test_501_detail_message(self, client, outputs_with_data, monkeypatch):
        import backend.routers.pcaps as pcaps_module
        monkeypatch.setattr(pcaps_module, "OUTPUTS_DIR", outputs_with_data)
        data = client.get("/api/pcaps/capture.pcap/summary").json()
        assert "detail" in data
        assert "501" in data["detail"] or "not" in data["detail"].lower()
