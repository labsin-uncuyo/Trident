"""Tests for Pydantic models in backend/models.py."""

from __future__ import annotations

import pytest

from backend.models import (
    AlertEntry,
    Connection,
    ContainerInfo,
    ContainerState,
    HealthResponse,
    MessagePart,
    NodeType,
    PcapFile,
    PcapSummary,
    RunInfo,
    ServiceHealth,
    SessionDetail,
    SessionMessage,
    TimelineEntry,
    TopologyData,
    TopologyEdge,
    TopologyNode,
)


# ── ContainerState ─────────────────────────────────────────────────

class TestContainerState:
    def test_all_values(self):
        for v in ("running", "stopped", "restarting", "paused", "exited", "dead", "unknown"):
            assert ContainerState(v) == v

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            ContainerState("nonexistent")


# ── NodeType ───────────────────────────────────────────────────────

class TestNodeType:
    def test_all_values(self):
        for v in ("router", "server", "host", "attacker", "defender", "dashboard"):
            assert NodeType(v) == v


# ── ContainerInfo ──────────────────────────────────────────────────

class TestContainerInfo:
    def test_defaults(self):
        c = ContainerInfo(
            id="abc123",
            name="lab_router",
            image="lab/router:latest",
            state=ContainerState.running,
            status="Up 5 minutes",
        )
        assert c.networks == []
        assert c.ip_addresses == {}
        assert c.health is None

    def test_with_networks(self):
        c = ContainerInfo(
            id="x",
            name="lab_server",
            image="lab/server:latest",
            state=ContainerState.exited,
            status="Exited (0) 1 hour ago",
            networks=["lab_net_a", "lab_net_b"],
            ip_addresses={"lab_net_a": "172.30.0.10"},
            health="healthy",
        )
        assert "lab_net_a" in c.networks
        assert c.ip_addresses["lab_net_a"] == "172.30.0.10"
        assert c.health == "healthy"

    def test_serialise_roundtrip(self):
        c = ContainerInfo(
            id="z",
            name="lab_x",
            image="img",
            state=ContainerState.running,
            status="running",
        )
        d = c.model_dump()
        c2 = ContainerInfo(**d)
        assert c == c2


# ── TopologyNode ───────────────────────────────────────────────────

class TestTopologyNode:
    def test_defaults(self):
        n = TopologyNode(
            id="router",
            label="Router",
            type=NodeType.router,
            container="lab_router",
        )
        assert n.ips == []
        assert n.networks == []
        assert n.services == []
        assert n.state == ContainerState.unknown
        assert n.position == {}

    def test_with_all_fields(self):
        n = TopologyNode(
            id="compromised",
            label="Compromised Host",
            type=NodeType.host,
            ips=["172.30.0.10"],
            networks=["lab_net_a"],
            services=["SSH:22", "OpenCode:4096"],
            container="lab_compromised",
            state=ContainerState.running,
            position={"x": 100.0, "y": 300.0},
        )
        assert n.state == ContainerState.running
        assert "SSH:22" in n.services


class TestTopologyEdge:
    def test_defaults(self):
        e = TopologyEdge(id="e1", source="a", target="b")
        assert e.label == ""
        assert e.animated is False

    def test_animated(self):
        e = TopologyEdge(id="e2", source="a", target="b", animated=True, label="net_a")
        assert e.animated is True
        assert e.label == "net_a"


class TestTopologyData:
    def test_empty(self):
        td = TopologyData(nodes=[], edges=[])
        assert td.nodes == []
        assert td.edges == []


# ── MessagePart ────────────────────────────────────────────────────

class TestMessagePart:
    def test_text_part(self):
        p = MessagePart(type="text", text="hello world")
        assert p.type == "text"
        assert p.text == "hello world"
        assert p.tool is None

    def test_tool_part(self):
        p = MessagePart(type="tool", tool="bash")
        assert p.tool == "bash"

    def test_extra_fields_allowed(self):
        p = MessagePart(type="step-start", extra_data={"foo": "bar"})  # type: ignore[call-arg]
        assert p.type == "step-start"


# ── AlertEntry ─────────────────────────────────────────────────────

class TestAlertEntry:
    def test_defaults(self):
        a = AlertEntry()
        assert a.timestamp == ""
        assert a.run_id == ""
        assert a.data == {}

    def test_with_data(self):
        a = AlertEntry(
            timestamp="2026-03-04T12:00:00",
            run_id="test_run",
            data={"type": "scan", "ip": "1.2.3.4"},
        )
        assert a.data["type"] == "scan"


# ── PcapFile ───────────────────────────────────────────────────────

class TestPcapFile:
    def test_basic(self):
        p = PcapFile(
            filename="capture.pcap",
            path="/outputs/run/pcaps/capture.pcap",
            size_bytes=1024,
            modified="2026-03-04T12:00:00",
        )
        assert p.size_bytes == 1024


# ── RunInfo ────────────────────────────────────────────────────────

class TestRunInfo:
    def test_defaults(self):
        r = RunInfo(run_id="logs_20260304_120000", path="/outputs/logs_20260304_120000")
        assert r.is_current is False
        assert r.has_pcaps is False
        assert r.has_alerts is False

    def test_current(self):
        r = RunInfo(run_id="x", path="/x", is_current=True, has_pcaps=True, has_alerts=True)
        assert r.is_current is True


# ── TimelineEntry ──────────────────────────────────────────────────

class TestTimelineEntry:
    def test_defaults(self):
        t = TimelineEntry()
        assert t.ts == ""
        assert t.level == ""
        assert t.msg == ""
        assert t.exec is None

    def test_with_data(self):
        t = TimelineEntry(ts="2026-03-04T12:00:00", level="INFO", msg="hello", exec="bash")
        assert t.exec == "bash"


# ── HealthResponse ─────────────────────────────────────────────────

class TestHealthResponse:
    def test_defaults(self):
        h = HealthResponse()
        assert h.status == "ok"
        assert h.services == []
        assert h.run_id is None

    def test_with_services(self):
        s = ServiceHealth(name="opencode_compromised", healthy=True, detail="ok")
        h = HealthResponse(status="ok", timestamp="2026-03-04T12:00:00", services=[s])
        assert len(h.services) == 1
        assert h.services[0].healthy is True


# ── PcapSummary / Connection (Phase 2 stubs) ───────────────────────

class TestPhase2Stubs:
    def test_pcap_summary_defaults(self):
        p = PcapSummary(filename="test.pcap")
        assert p.total_packets == 0
        assert p.protocols == {}

    def test_connection_defaults(self):
        c = Connection(
            src_ip="1.2.3.4",
            dst_ip="5.6.7.8",
            src_port=12345,
            dst_port=80,
            protocol="TCP",
        )
        assert c.packets == 0
        assert c.bytes == 0
