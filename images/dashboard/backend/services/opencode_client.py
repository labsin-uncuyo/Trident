"""Async HTTP client for OpenCode server API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger("dashboard.opencode")

# Known OpenCode hosts
HOSTS: dict[str, str] = {
    "compromised": "http://172.30.0.10:4096",
    "server": "http://172.31.0.10:4096",
}

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class OpenCodeClient:
    """Thin async wrapper around the OpenCode HTTP server API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=_TIMEOUT
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Health ──────────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        try:
            c = await self._get_client()
            r = await c.get("/global/health")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.debug("health check failed for %s: %s", self.base_url, exc)
            return {"healthy": False, "error": str(exc)}

    # ── Sessions ────────────────────────────────────────────────────

    async def list_sessions(self) -> dict[str, str]:
        """Return {session_id: status} mapping.

        The upstream API may return statuses as plain strings OR as
        objects like ``{"type": "busy"}``.  This method normalises
        both forms into simple string values.
        """
        try:
            c = await self._get_client()
            r = await c.get("/session/status")
            r.raise_for_status()
            raw = r.json()
            # Normalise: {sid: "idle"} or {sid: {"type": "idle"}} → {sid: "idle"}
            normalised: dict[str, str] = {}
            for sid, val in raw.items():
                if isinstance(val, dict):
                    normalised[sid] = val.get("type", "unknown")
                elif isinstance(val, str):
                    normalised[sid] = val
                else:
                    normalised[sid] = str(val)
            return normalised
        except Exception as exc:
            logger.warning("list_sessions failed on %s: %s", self.base_url, exc)
            return {}

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Fetch all messages for a session."""
        try:
            c = await self._get_client()
            r = await c.get(f"/session/{session_id}/message")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning(
                "get_messages(%s) failed on %s: %s",
                session_id, self.base_url, exc,
            )
            return []

    async def create_session(self, title: str = "dashboard") -> str | None:
        """Create a new session, return session ID."""
        try:
            c = await self._get_client()
            r = await c.post("/session", json={"title": title})
            r.raise_for_status()
            return r.json().get("id")
        except Exception as exc:
            logger.warning("create_session failed on %s: %s", self.base_url, exc)
            return None

    async def abort_session(self, session_id: str) -> bool:
        try:
            c = await self._get_client()
            r = await c.post(f"/session/{session_id}/abort")
            return r.is_success
        except Exception:
            return False


# ── Global client pool ──────────────────────────────────────────────

_clients: dict[str, OpenCodeClient] = {}


def get_client(host: str) -> OpenCodeClient:
    """Get or create a client for a known host name."""
    if host not in HOSTS:
        raise ValueError(f"Unknown host '{host}'. Valid: {list(HOSTS)}")
    if host not in _clients:
        _clients[host] = OpenCodeClient(HOSTS[host])
    return _clients[host]


async def close_all() -> None:
    for c in _clients.values():
        await c.close()
    _clients.clear()
