"""Topology data endpoint — static Trident network definition enriched with live
container state, agent activity, and traffic flow."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter

from backend.models import (
    ContainerState,
    NodeType,
    TopologyData,
    TopologyEdge,
    TopologyNode,
)
from backend.services.docker_client import list_containers
from backend.services.file_tailer import read_ndjson_file
from backend.services.traffic_analyzer import compute_traffic

OUTPUTS_DIR = Path(os.getenv("OUTPUTS_DIR", "/outputs"))

router = APIRouter(prefix="/api/topology", tags=["topology"])

# ── Static topology definition (mirrors docker-compose.yml) ────────

_NODES: list[dict] = [
    {
        "id": "compromised",
        "label": "Compromised Host",
        "type": NodeType.host,
        "ips": ["172.30.0.10"],
        "networks": ["lab_net_a"],
        "services": ["SSH:22", "OpenCode:4096"],
        "container": "lab_compromised",
        "position": {"x": 100, "y": 300},
    },
    {
        "id": "router",
        "label": "Router / Gateway",
        "type": NodeType.router,
        "ips": ["172.30.0.1", "172.31.0.1"],
        "networks": ["lab_net_a", "lab_net_b"],
        "services": ["DNS", "NAT", "PCAP Capture"],
        "container": "lab_router",
        "position": {"x": 400, "y": 300},
    },
    {
        "id": "server",
        "label": "Server",
        "type": NodeType.server,
        "ips": ["172.31.0.10"],
        "networks": ["lab_net_b"],
        "services": ["HTTP:80", "PostgreSQL:5432", "SSH:22", "OpenCode:4096"],
        "container": "lab_server",
        "position": {"x": 700, "y": 300},
    },
    {
        "id": "defender",
        "label": "SLIPS Defender",
        "type": NodeType.defender,
        "ips": ["host"],
        "networks": ["host"],
        "services": ["SLIPS IDS", "Defender API:8000", "Planner:1654"],
        "container": "lab_slips_defender",
        "position": {"x": 400, "y": 100},
    },
]


_EDGES: list[dict] = [
    {
        "id": "e-comp-router",
        "source": "compromised",
        "target": "router",
        "label": "lab_net_a · 172.30.0.0/24",
        "animated": True,
    },
    {
        "id": "e-router-server",
        "source": "router",
        "target": "server",
        "label": "lab_net_b · 172.31.0.0/24",
        "animated": True,
    },
    {
        "id": "e-defender-router",
        "source": "defender",
        "target": "router",
        "label": "host network (PCAP analysis)",
        "animated": False,
    },
]

# ── Agent → node mapping ────────────────────────────────────────────
_AGENT_NODES: dict[str, str] = {
    "coder56": "compromised",
    "db_admin": "server",
    "soc_god_server": "server",
    "soc_god_compromised": "compromised",
}

_TIMELINE_PATHS: dict[str, str] = {
    "coder56": "coder56/auto_responder_timeline.jsonl",
    "db_admin": "benign_agent/db_admin_timeline.jsonl",
    "soc_god_server": "defender/server/auto_responder_timeline.jsonl",
    "soc_god_compromised": "defender/compromised/auto_responder_timeline.jsonl",
}


def _current_run_id() -> str | None:
    p = OUTPUTS_DIR / ".current_run"
    return p.read_text().strip() if p.exists() else None


@router.get("", response_model=TopologyData)
async def get_topology():
    """Return the network topology with live container state."""
    containers = {c.name: c for c in list_containers()}

    nodes: list[TopologyNode] = []
    for n in _NODES:
        cinfo = containers.get(n["container"])
        state = cinfo.state if cinfo else ContainerState.unknown
        nodes.append(TopologyNode(**n, state=state))

    edges = [TopologyEdge(**e) for e in _EDGES]
    return TopologyData(nodes=nodes, edges=edges)


@router.get("/agents")
async def get_topology_agents():
    """Return active agents per topology node.

    An agent is 'active' if its timeline has an entry within the last 30 min.
    """
    run_id = _current_run_id()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    node_agents: dict[str, list[str]] = {}

    for agent, rel_path in _TIMELINE_PATHS.items():
        node = _AGENT_NODES.get(agent)
        if not node:
            continue
        if run_id:
            path = OUTPUTS_DIR / run_id / rel_path
            entries = read_ndjson_file(path, max_lines=5000)
        else:
            entries = []

        if entries:
            last_ts_str = entries[-1].get("ts", "")
            try:
                last_ts = datetime.fromisoformat(last_ts_str)
                active = last_ts >= cutoff
            except ValueError:
                active = False
        else:
            active = False

        if active:
            node_agents.setdefault(node, []).append(agent)

    return {"agents": node_agents}


@router.get("/traffic")
async def get_topology_traffic():
    """Return traffic flow totals (bytes, MB) per topology edge."""
    run_id = _current_run_id()
    if not run_id:
        return {"run_id": None, "flows": [], "edges": {}}
    return compute_traffic(OUTPUTS_DIR, run_id)
