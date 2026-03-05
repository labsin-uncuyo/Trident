"""Tests for GET /api/containers and ws /api/containers/ws."""

from __future__ import annotations


class TestContainersEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/containers")
        assert r.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/api/containers").json()
        assert isinstance(data, list)

    def test_containers_have_required_fields(self, client):
        data = client.get("/api/containers").json()
        required = {"id", "name", "image", "state", "status"}
        for c in data:
            missing = required - c.keys()
            assert not missing, f"Container missing fields: {missing}"

    def test_only_lab_containers_returned(self, client):
        """Only containers whose names start with 'lab_' should be returned."""
        data = client.get("/api/containers").json()
        for c in data:
            assert c["name"].startswith("lab_"), f"Non-lab container: {c['name']}"

    def test_mocked_containers_present(self, client):
        data = client.get("/api/containers").json()
        names = {c["name"] for c in data}
        assert "lab_router" in names
        assert "lab_compromised" in names
        assert "lab_server" in names

    def test_container_state_valid(self, client):
        valid = {"running", "stopped", "restarting", "paused", "exited", "dead", "unknown"}
        data = client.get("/api/containers").json()
        for c in data:
            assert c["state"] in valid, f"Invalid state: {c['state']}"

    def test_running_containers_detected(self, client):
        data = client.get("/api/containers").json()
        running = [c for c in data if c["state"] == "running"]
        assert len(running) >= 3  # router, compromised, server are all "running" in mock


class TestContainersWebSocket:
    def test_ws_connects_and_receives_message(self, client):
        """Container WS should emit an initial containers snapshot."""
        with client.websocket_connect("/api/containers/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "containers"
            assert isinstance(msg["data"], list)

    def test_ws_data_has_container_fields(self, client):
        with client.websocket_connect("/api/containers/ws") as ws:
            msg = ws.receive_json()
            for c in msg["data"]:
                assert "name" in c
                assert "state" in c
