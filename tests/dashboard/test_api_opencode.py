"""Tests for /api/opencode/* endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestOpenCodeHostsEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/opencode/hosts")
        assert r.status_code == 200

    def test_lists_configured_hosts(self, client):
        data = client.get("/api/opencode/hosts").json()
        assert "compromised" in data
        assert "server" in data

    def test_host_entry_has_url_and_healthy(self, client):
        data = client.get("/api/opencode/hosts").json()
        for host_data in data.values():
            assert "url" in host_data
            assert "healthy" in host_data

    def test_hosts_unreachable_healthy_false(self, client):
        """When both OpenCode servers are forced unreachable, healthy=False."""
        from unittest.mock import AsyncMock, patch
        with patch(
            "backend.services.opencode_client.OpenCodeClient.health",
            new=AsyncMock(return_value={"healthy": False, "error": "conn refused"}),
        ):
            data = client.get("/api/opencode/hosts").json()
            for host_data in data.values():
                assert host_data["healthy"] is False

    def test_base_urls_correct(self, client):
        data = client.get("/api/opencode/hosts").json()
        assert "172.30.0.10:4096" in data["compromised"]["url"]
        assert "172.31.0.10:4096" in data["server"]["url"]


class TestOpenCodeHostHealthEndpoint:
    def test_known_host_returns_200(self, client):
        r = client.get("/api/opencode/compromised/health")
        assert r.status_code == 200

    def test_unknown_host_returns_404(self, client):
        r = client.get("/api/opencode/unknown_host/health")
        assert r.status_code == 404

    def test_health_response_has_healthy_key(self, client):
        data = client.get("/api/opencode/compromised/health").json()
        assert "healthy" in data

    def test_server_host_also_works(self, client):
        r = client.get("/api/opencode/server/health")
        assert r.status_code == 200


class TestOpenCodeSessionsEndpoint:
    def test_unknown_host_returns_404(self, client):
        r = client.get("/api/opencode/badhost/sessions")
        assert r.status_code == 404

    def test_known_host_returns_200(self, client):
        r = client.get("/api/opencode/compromised/sessions")
        assert r.status_code == 200

    def test_returns_dict(self, client):
        data = client.get("/api/opencode/compromised/sessions").json()
        assert isinstance(data, dict)

    def test_empty_when_server_unavailable(self, client):
        """Graceful degradation: no sessions when OpenCode is down."""
        data = client.get("/api/opencode/compromised/sessions").json()
        assert data == {}

    def test_mocked_sessions(self, client):
        """With sessions mocked, list_sessions returns expected data."""
        mock_sessions = {"abc123": "idle", "def456": "running"}
        with patch(
            "backend.services.opencode_client.OpenCodeClient.list_sessions",
            new=AsyncMock(return_value=mock_sessions),
        ):
            data = client.get("/api/opencode/compromised/sessions").json()
            assert data == mock_sessions


class TestOpenCodeMessagesEndpoint:
    def test_unknown_host_returns_404(self, client):
        r = client.get("/api/opencode/badhost/sessions/abc/messages")
        assert r.status_code == 404

    def test_known_host_returns_200(self, client):
        r = client.get("/api/opencode/compromised/sessions/abc123/messages")
        assert r.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/api/opencode/compromised/sessions/abc123/messages").json()
        assert isinstance(data, list)

    def test_empty_when_server_unavailable(self, client):
        data = client.get("/api/opencode/compromised/sessions/abc123/messages").json()
        assert data == []

    def test_mocked_messages(self, client):
        fake_msgs = [
            {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "parts": [{"type": "text", "text": "hello"}]},
        ]
        with patch(
            "backend.services.opencode_client.OpenCodeClient.get_messages",
            new=AsyncMock(return_value=fake_msgs),
        ):
            data = client.get("/api/opencode/server/sessions/xyz/messages").json()
            assert len(data) == 2
            assert data[0]["role"] == "user"
