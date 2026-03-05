"""Unit tests for backend service layer."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure 'backend' is importable (conftest does this too, but be safe)
_DASHBOARD = Path(__file__).resolve().parents[2] / "images" / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))


# ═══════════════════════════════════════════════════════════════════
# file_tailer
# ═══════════════════════════════════════════════════════════════════

class TestReadNdjsonFile:
    """Tests for backend.services.file_tailer.read_ndjson_file."""

    def test_returns_empty_for_nonexistent_file(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        result = read_ndjson_file(tmp_path / "does_not_exist.jsonl")
        assert result == []

    def test_reads_single_line(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        f = tmp_path / "test.jsonl"
        f.write_text(json.dumps({"key": "value"}) + "\n")
        result = read_ndjson_file(f)
        assert result == [{"key": "value"}]

    def test_reads_multiple_lines(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        f = tmp_path / "test.jsonl"
        lines = [json.dumps({"i": i}) for i in range(5)]
        f.write_text("\n".join(lines) + "\n")
        result = read_ndjson_file(f)
        assert len(result) == 5
        assert result[2] == {"i": 2}

    def test_skips_invalid_json_lines(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        f = tmp_path / "test.jsonl"
        f.write_text(
            "NOT JSON\n"
            + json.dumps({"valid": True}) + "\n"
            + "also bad\n"
        )
        result = read_ndjson_file(f)
        assert result == [{"valid": True}]

    def test_skips_blank_lines(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        f = tmp_path / "test.jsonl"
        f.write_text(
            "\n"
            + json.dumps({"val": 1}) + "\n"
            + "\n"
            + json.dumps({"val": 2}) + "\n"
        )
        result = read_ndjson_file(f)
        assert len(result) == 2

    def test_respects_max_lines(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        f = tmp_path / "test.jsonl"
        lines = [json.dumps({"i": i}) for i in range(100)]
        f.write_text("\n".join(lines) + "\n")
        result = read_ndjson_file(f, max_lines=10)
        assert len(result) == 10

    def test_handles_unicode(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        f = tmp_path / "test.jsonl"
        f.write_text(json.dumps({"msg": "héllo wörld 🎯"}) + "\n", encoding="utf-8")
        result = read_ndjson_file(f)
        assert result[0]["msg"] == "héllo wörld 🎯"

    def test_handles_empty_file(self, tmp_path):
        from backend.services.file_tailer import read_ndjson_file
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        result = read_ndjson_file(f)
        assert result == []


class TestTailNdjson:
    """Tests for backend.services.file_tailer.tail_ndjson (async generator)."""

    async def test_yields_existing_lines_from_beginning(self, tmp_path):
        from backend.services.file_tailer import tail_ndjson

        f = tmp_path / "test.jsonl"
        f.write_text(json.dumps({"i": 0}) + "\n" + json.dumps({"i": 1}) + "\n")

        results = []
        async for entry in tail_ndjson(f, from_beginning=True, poll_interval=0.05):
            results.append(entry)
            if len(results) >= 2:
                break

        assert len(results) == 2
        assert results[0] == {"i": 0}

    async def test_waits_for_file_to_exist(self, tmp_path):
        from backend.services.file_tailer import tail_ndjson

        f = tmp_path / "future.jsonl"
        results = []

        async def writer():
            await asyncio.sleep(0.1)
            f.write_text(json.dumps({"created": True}) + "\n")

        async def reader():
            async for entry in tail_ndjson(f, from_beginning=True, poll_interval=0.05):
                results.append(entry)
                break

        await asyncio.gather(writer(), reader())
        assert results == [{"created": True}]

    async def test_picks_up_appended_lines(self, tmp_path):
        """tail_ndjson from offset=0 should pick up new lines appended after start."""
        from backend.services.file_tailer import tail_ndjson

        f = tmp_path / "growing.jsonl"
        f.write_text("")  # start empty

        results = []

        async def writer():
            await asyncio.sleep(0.1)
            with open(f, "a") as fh:
                fh.write(json.dumps({"appended": True}) + "\n")

        async def reader():
            async for entry in tail_ndjson(f, from_beginning=False, poll_interval=0.05):
                results.append(entry)
                break

        await asyncio.gather(writer(), reader())
        assert results == [{"appended": True}]


# ═══════════════════════════════════════════════════════════════════
# docker_client
# ═══════════════════════════════════════════════════════════════════

class TestMapState:
    def test_known_states(self):
        from backend.services.docker_client import _map_state
        from backend.models import ContainerState
        assert _map_state("running") == ContainerState.running
        assert _map_state("exited") == ContainerState.exited
        assert _map_state("paused") == ContainerState.paused
        assert _map_state("dead") == ContainerState.dead

    def test_unknown_maps_to_unknown(self):
        from backend.services.docker_client import _map_state
        from backend.models import ContainerState
        assert _map_state("garbage") == ContainerState.unknown

    def test_case_insensitive(self):
        from backend.services.docker_client import _map_state
        from backend.models import ContainerState
        assert _map_state("RUNNING") == ContainerState.running
        assert _map_state("Exited") == ContainerState.exited


class TestListContainers:
    def test_returns_empty_when_docker_unavailable(self):
        """DockerException must be caught gracefully."""
        from backend.services.docker_client import list_containers
        import docker.errors
        with patch("docker.from_env", side_effect=docker.errors.DockerException("no socket")):
            result = list_containers()
        assert result == []

    def test_filters_non_lab_containers(self):
        from backend.services.docker_client import list_containers

        def make_c(name):
            c = MagicMock()
            c.name = name
            c.short_id = name[:12]
            c.status = "running"
            c.image.tags = []
            c.attrs = {"State": {"Status": "running"}, "NetworkSettings": {"Networks": {}}}
            return c

        fake_client = MagicMock()
        fake_client.containers.list.return_value = [
            make_c("lab_router"),
            make_c("system_container"),  # should be filtered out
        ]

        with patch("docker.from_env", return_value=fake_client):
            result = list_containers()

        names = [c.name for c in result]
        assert "lab_router" in names
        assert "system_container" not in names

    def test_returns_container_info_objects(self, mock_docker):
        from backend.services.docker_client import list_containers
        from backend.models import ContainerInfo
        result = list_containers()
        assert all(isinstance(c, ContainerInfo) for c in result)

    def test_ip_addresses_extracted(self):
        from backend.services.docker_client import list_containers

        c = MagicMock()
        c.name = "lab_server"
        c.short_id = "lab_server"
        c.status = "running"
        c.image.tags = ["lab/server:latest"]
        c.attrs = {
            "State": {"Status": "running"},
            "NetworkSettings": {
                "Networks": {
                    "lab_net_b": {"IPAddress": "172.31.0.10"},
                }
            },
        }
        fake_client = MagicMock()
        fake_client.containers.list.return_value = [c]

        with patch("docker.from_env", return_value=fake_client):
            result = list_containers()

        assert result[0].ip_addresses == {"lab_net_b": "172.31.0.10"}


# ═══════════════════════════════════════════════════════════════════
# opencode_client
# ═══════════════════════════════════════════════════════════════════

class TestOpenCodeClientGetClient:
    def test_known_host_returns_client(self):
        from backend.services.opencode_client import get_client, HOSTS
        client = get_client("compromised")
        assert client is not None
        assert client.base_url == HOSTS["compromised"]

    def test_unknown_host_raises_value_error(self):
        from backend.services.opencode_client import get_client
        with pytest.raises(ValueError, match="Unknown host"):
            get_client("nonexistent_host")

    def test_same_client_returned_each_call(self):
        from backend.services.opencode_client import get_client
        c1 = get_client("server")
        c2 = get_client("server")
        assert c1 is c2


class TestOpenCodeClientMethods:
    """Test OpenCodeClient HTTP methods with mocked httpx responses."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy_on_200(self):
        from backend.services.opencode_client import OpenCodeClient
        import httpx

        client = OpenCodeClient("http://fake:4096")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"healthy": True}

        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http
            result = await client.health()

        assert result["healthy"] is True

    @pytest.mark.asyncio
    async def test_health_returns_error_on_exception(self):
        from backend.services.opencode_client import OpenCodeClient
        import httpx

        client = OpenCodeClient("http://dead:4096")
        with patch.object(client, "_get_client", side_effect=Exception("conn refused")):
            result = await client.health()

        assert result["healthy"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_list_sessions_returns_empty_on_error(self):
        from backend.services.opencode_client import OpenCodeClient

        client = OpenCodeClient("http://dead:4096")
        with patch.object(client, "_get_client", side_effect=Exception("unreachable")):
            result = await client.list_sessions()

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_messages_returns_empty_on_error(self):
        from backend.services.opencode_client import OpenCodeClient

        client = OpenCodeClient("http://dead:4096")
        with patch.object(client, "_get_client", side_effect=Exception("unreachable")):
            result = await client.get_messages("some_session_id")

        assert result == []

    @pytest.mark.asyncio
    async def test_list_sessions_parses_json(self):
        from backend.services.opencode_client import OpenCodeClient

        client = OpenCodeClient("http://fake:4096")
        fake_sessions = {"s1": "idle", "s2": "running"}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = fake_sessions

        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http
            result = await client.list_sessions()

        assert result == fake_sessions

    @pytest.mark.asyncio
    async def test_get_messages_parses_json(self):
        from backend.services.opencode_client import OpenCodeClient

        client = OpenCodeClient("http://fake:4096")
        fake_messages = [{"role": "user", "parts": []}, {"role": "assistant", "parts": []}]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = fake_messages

        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http
            result = await client.get_messages("session_abc")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_close_is_safe_when_client_not_created(self):
        from backend.services.opencode_client import OpenCodeClient

        client = OpenCodeClient("http://fake:4096")
        # Should not raise
        await client.close()
