"""Tests for GET /api/topology."""

from __future__ import annotations

import pytest

EXPECTED_NODE_IDS = {"compromised", "router", "server", "defender", "aracne"}
EXPECTED_EDGE_IDS = {"e-comp-router", "e-router-server", "e-aracne-server", "e-defender-router"}


class TestTopologyEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/topology")
        assert r.status_code == 200

    def test_response_has_nodes_and_edges(self, client):
        data = client.get("/api/topology").json()
        assert "nodes" in data
        assert "edges" in data

    def test_all_expected_nodes_present(self, client):
        data = client.get("/api/topology").json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert EXPECTED_NODE_IDS == node_ids

    def test_all_expected_edges_present(self, client):
        data = client.get("/api/topology").json()
        edge_ids = {e["id"] for e in data["edges"]}
        assert EXPECTED_EDGE_IDS == edge_ids

    def test_node_has_required_fields(self, client):
        data = client.get("/api/topology").json()
        required = {"id", "label", "type", "ips", "networks", "services", "container", "state", "position"}
        for node in data["nodes"]:
            missing = required - node.keys()
            assert not missing, f"Node {node['id']} missing fields: {missing}"

    def test_edge_has_required_fields(self, client):
        data = client.get("/api/topology").json()
        for edge in data["edges"]:
            assert "id" in edge
            assert "source" in edge
            assert "target" in edge

    def test_router_has_two_networks(self, client):
        data = client.get("/api/topology").json()
        router = next(n for n in data["nodes"] if n["id"] == "router")
        assert "lab_net_a" in router["networks"]
        assert "lab_net_b" in router["networks"]

    def test_compromised_ip_correct(self, client):
        data = client.get("/api/topology").json()
        comp = next(n for n in data["nodes"] if n["id"] == "compromised")
        assert "172.30.0.10" in comp["ips"]

    def test_server_ip_correct(self, client):
        data = client.get("/api/topology").json()
        server = next(n for n in data["nodes"] if n["id"] == "server")
        assert "172.31.0.10" in server["ips"]

    def test_node_types_valid(self, client):
        valid_types = {"router", "server", "host", "attacker", "defender", "dashboard"}
        data = client.get("/api/topology").json()
        for node in data["nodes"]:
            assert node["type"] in valid_types, f"Invalid type {node['type']} for {node['id']}"

    def test_node_state_field_present(self, client):
        """State comes from Docker — may be 'running' (mocked) or 'unknown'."""
        data = client.get("/api/topology").json()
        valid_states = {"running", "stopped", "restarting", "paused", "exited", "dead", "unknown"}
        for node in data["nodes"]:
            assert node["state"] in valid_states

    def test_animated_edges(self, client):
        """Main network edges should be animated."""
        data = client.get("/api/topology").json()
        edges_by_id = {e["id"]: e for e in data["edges"]}
        assert edges_by_id["e-comp-router"]["animated"] is True
        assert edges_by_id["e-router-server"]["animated"] is True

    def test_positions_present(self, client):
        data = client.get("/api/topology").json()
        for node in data["nodes"]:
            assert "x" in node["position"]
            assert "y" in node["position"]
