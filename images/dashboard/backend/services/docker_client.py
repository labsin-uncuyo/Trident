"""Docker socket client for container introspection."""

from __future__ import annotations

import logging
from typing import Any

import docker
from docker.errors import DockerException

from backend.models import ContainerInfo, ContainerState

logger = logging.getLogger("dashboard.docker")

_CONTAINER_PREFIX = "lab_"


def _map_state(raw: str) -> ContainerState:
    try:
        return ContainerState(raw.lower())
    except ValueError:
        return ContainerState.unknown


def list_containers() -> list[ContainerInfo]:
    """List all lab_* containers with their status."""
    try:
        client = docker.from_env()
    except DockerException as exc:
        logger.error("Cannot connect to Docker daemon: %s", exc)
        return []

    results: list[ContainerInfo] = []
    for c in client.containers.list(all=True):
        if not c.name.startswith(_CONTAINER_PREFIX):
            continue

        # Network info
        net_settings = c.attrs.get("NetworkSettings", {})
        networks_raw = net_settings.get("Networks", {})
        net_names = list(networks_raw.keys())
        ip_map = {}
        for net_name, net_data in networks_raw.items():
            ip = net_data.get("IPAddress", "")
            if ip:
                ip_map[net_name] = ip

        # Health
        health = None
        health_data = c.attrs.get("State", {}).get("Health")
        if health_data:
            health = health_data.get("Status", "unknown")

        results.append(
            ContainerInfo(
                id=c.short_id,
                name=c.name,
                image=",".join(c.image.tags) if c.image.tags else str(c.image.id)[:19],
                state=_map_state(c.status),
                status=c.attrs.get("State", {}).get("Status", c.status),
                health=health,
                networks=net_names,
                ip_addresses=ip_map,
            )
        )
    return results


def get_container(name: str) -> ContainerInfo | None:
    """Get info for a single container by name."""
    for c in list_containers():
        if c.name == name:
            return c
    return None
