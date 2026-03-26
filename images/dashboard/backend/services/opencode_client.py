"""File-backed OpenCode state aggregator for dashboard."""

from __future__ import annotations

import json
import os
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUTS_DIR = Path(os.getenv("OUTPUTS_DIR", "/outputs"))

AGENT_FILE_PATHS: dict[str, str] = {
    "coder56": "coder56/opencode_api_messages.json",
    "db_admin": "benign_agent/opencode_api_messages.json",
    "soc_god_server": "defender/server/opencode_api_messages.json",
    "soc_god_compromised": "defender/compromised/opencode_api_messages.json",
}


def _current_run_id() -> str | None:
    current = OUTPUTS_DIR / ".current_run"
    if current.exists():
        return current.read_text().strip() or None
    return None


def _safe_json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _legacy_to_canonical(agent: str, run_id: str, raw: list[Any]) -> dict[str, Any]:
    legacy_messages: list[Any] = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("messages"), list):
            legacy_messages.extend(item.get("messages", []))
        else:
            legacy_messages.append(item)

    return {
        "agent": agent,
        "run_id": run_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sessions": {
            "legacy": {
                "status": "completed",
                "last_event_ts": int(datetime.now(timezone.utc).timestamp() * 1000),
                "messages": legacy_messages,
            }
        },
    }


def _normalise_state(agent: str, run_id: str, raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        return _legacy_to_canonical(agent, run_id, raw)

    state = {
        "agent": agent,
        "run_id": run_id,
        "updated_at": "",
        "sessions": {},
    }
    if isinstance(raw, dict):
        state.update(raw)

    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}

    state["agent"] = agent
    state["run_id"] = run_id
    return state


def _agent_file(run_id: str, agent: str) -> Path:
    return OUTPUTS_DIR / run_id / AGENT_FILE_PATHS[agent]


def _agent_status_from_sessions(sessions: dict[str, Any]) -> str:
    def _normalise_status(raw_status: Any) -> str:
        if isinstance(raw_status, dict):
            return str(raw_status.get("type", "unknown")).lower()
        if isinstance(raw_status, str):
            text = raw_status.strip()
            if text.startswith("{") and "type" in text:
                try:
                    parsed = ast.literal_eval(text)
                    if isinstance(parsed, dict):
                        return str(parsed.get("type", "unknown")).lower()
                except (ValueError, SyntaxError):
                    pass
            return text.lower()
        return str(raw_status).lower()

    statuses: list[str] = []
    for session_data in sessions.values():
        if not isinstance(session_data, dict):
            continue
        raw_status = session_data.get("status", "unknown")
        normal = _normalise_status(raw_status)
        statuses.append(normal)
    if any(s in ("running", "busy", "active", "pending", "generating") for s in statuses):
        return "running"
    if any(s in ("error", "failed") for s in statuses):
        return "error"
    if statuses:
        return "idle"
    return "unknown"


def load_all_agent_states(run_id: str | None = None) -> dict[str, Any]:
    rid = run_id or _current_run_id()
    if not rid:
        return {
            "run_id": None,
            "agents": {},
            "sessions": {},
            "session_sources": {},
            "messages_by_session": {},
            "updated_at": "",
        }

    agents: dict[str, Any] = {}
    merged_sessions: dict[str, str] = {}
    session_sources: dict[str, str] = {}
    messages_by_session: dict[str, list[dict[str, Any]]] = {}
    latest_updated_at = ""

    for agent in AGENT_FILE_PATHS:
        path = _agent_file(rid, agent)
        exists = path.exists()
        raw = _safe_json_load(path) if exists else None
        state = _normalise_state(agent, rid, raw)
        sessions = state.get("sessions", {}) if isinstance(state.get("sessions"), dict) else {}

        for session_id, session_data in sessions.items():
            if not isinstance(session_data, dict):
                continue
            raw_status = session_data.get("status", "unknown")
            if isinstance(raw_status, dict):
                status = str(raw_status.get("type", "unknown"))
            elif isinstance(raw_status, str) and raw_status.strip().startswith("{") and "type" in raw_status:
                try:
                    parsed = ast.literal_eval(raw_status)
                    status = str(parsed.get("type", "unknown")) if isinstance(parsed, dict) else str(raw_status)
                except (ValueError, SyntaxError):
                    status = str(raw_status)
            else:
                status = str(raw_status)
            merged_sessions[session_id] = status
            session_sources[session_id] = agent
            session_messages = session_data.get("messages", [])
            if isinstance(session_messages, list):
                messages_by_session[session_id] = session_messages

        updated_at = str(state.get("updated_at", ""))
        if updated_at and updated_at > latest_updated_at:
            latest_updated_at = updated_at

        mtime = ""
        if exists:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

        agents[agent] = {
            "agent": agent,
            "path": str(path),
            "exists": exists,
            "updated_at": updated_at,
            "file_mtime": mtime,
            "session_count": len(sessions),
            "status": _agent_status_from_sessions(sessions),
        }

    return {
        "run_id": rid,
        "updated_at": latest_updated_at,
        "agents": agents,
        "sessions": merged_sessions,
        "session_sources": session_sources,
        "messages_by_session": messages_by_session,
    }


def get_session_messages(session_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
    state = load_all_agent_states(run_id)
    messages = state.get("messages_by_session", {}).get(session_id, [])
    return messages if isinstance(messages, list) else []


async def close_all() -> None:
    return None
