"""Pydantic models for the Trident Dashboard API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Container / Docker ──────────────────────────────────────────────

class ContainerState(str, Enum):
    running = "running"
    stopped = "stopped"
    restarting = "restarting"
    paused = "paused"
    exited = "exited"
    dead = "dead"
    unknown = "unknown"


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    state: ContainerState
    status: str  # human-readable e.g. "Up 5 minutes (healthy)"
    health: str | None = None
    networks: list[str] = Field(default_factory=list)
    ip_addresses: dict[str, str] = Field(default_factory=dict)


# ── Topology ────────────────────────────────────────────────────────

class NodeType(str, Enum):
    router = "router"
    server = "server"
    host = "host"
    attacker = "attacker"
    defender = "defender"
    dashboard = "dashboard"


class TopologyNode(BaseModel):
    id: str
    label: str
    type: NodeType
    ips: list[str] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    container: str  # Docker container name
    state: ContainerState = ContainerState.unknown
    position: dict[str, float] = Field(default_factory=dict)  # {x, y} hint


class TopologyEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str = ""
    animated: bool = False


class TopologyData(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


# ── OpenCode ────────────────────────────────────────────────────────

class OpenCodeSessionStatus(BaseModel):
    session_id: str
    status: str


class MessagePart(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str  # step-start, text, tool, step-finish, etc.
    text: str | None = None
    tool: str | None = None
    time: dict[str, Any] | None = None
    # Catch-all for extra fields
    extra: dict[str, Any] = Field(default_factory=dict)


class SessionMessage(BaseModel):
    role: str = ""
    session_id: str = ""
    created: int | None = None  # epoch ms
    completed: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    parts: list[MessagePart] = Field(default_factory=list)


class SessionDetail(BaseModel):
    session_id: str
    host: str
    messages: list[SessionMessage] = Field(default_factory=list)


# ── Alerts ──────────────────────────────────────────────────────────

class AlertEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    timestamp: str = ""
    run_id: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ── PCAPs ───────────────────────────────────────────────────────────

class PcapFile(BaseModel):
    filename: str
    path: str
    size_bytes: int
    modified: str  # ISO-8601


# ── Runs ────────────────────────────────────────────────────────────

class RunInfo(BaseModel):
    run_id: str
    path: str
    is_current: bool = False
    created: str = ""  # ISO-8601
    has_pcaps: bool = False
    has_alerts: bool = False


# ── Timeline ────────────────────────────────────────────────────────

class TimelineEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: str = ""
    level: str = ""
    msg: str = ""
    exec: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# ── Health ──────────────────────────────────────────────────────────

class ServiceHealth(BaseModel):
    name: str
    healthy: bool
    detail: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    run_id: str | None = None
    timestamp: str = ""
    services: list[ServiceHealth] = Field(default_factory=list)


# ── Traffic (Phase 2 stubs) ─────────────────────────────────────────

class PcapSummary(BaseModel):
    """Stub for future PCAP analysis."""
    filename: str
    total_packets: int = 0
    duration_seconds: float = 0.0
    protocols: dict[str, int] = Field(default_factory=dict)
    top_talkers: list[dict[str, Any]] = Field(default_factory=list)


class Connection(BaseModel):
    """Stub for future connection tracking."""
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: str
    packets: int = 0
    bytes: int = 0
    start_time: str = ""
    end_time: str = ""
