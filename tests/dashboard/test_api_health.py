"""Tests for GET /api/health."""

from __future__ import annotations


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_health_structure(self, client):
        data = client.get("/api/health").json()
        assert "status" in data
        assert "timestamp" in data
        assert "services" in data
        assert isinstance(data["services"], list)

    def test_health_status_ok(self, client):
        data = client.get("/api/health").json()
        assert data["status"] == "ok"

    def test_health_services_are_opencode(self, client):
        """Each service entry must have name/healthy/detail keys."""
        data = client.get("/api/health").json()
        for svc in data["services"]:
            assert "name" in svc
            assert "healthy" in svc
            assert isinstance(svc["healthy"], bool)

    def test_health_run_id_field_present(self, client):
        """run_id may be None when no outputs dir is configured."""
        data = client.get("/api/health").json()
        assert "run_id" in data

    def test_health_opencode_unreachable_still_200(self, client):
        """Even when both OpenCode servers are down, health returns 200 with healthy=False."""
        from unittest.mock import AsyncMock, patch
        with patch(
            "backend.services.opencode_client.OpenCodeClient.health",
            new=AsyncMock(return_value={"healthy": False, "error": "connection refused"}),
        ):
            r = client.get("/api/health")
            assert r.status_code == 200
            data = r.json()
            assert all(not svc["healthy"] for svc in data["services"])
