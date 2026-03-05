"""Generic async NDJSON / JSONL file tailer using watchfiles."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger("dashboard.tailer")


async def tail_ndjson(
    path: str | Path,
    *,
    from_beginning: bool = False,
    poll_interval: float = 1.0,
) -> AsyncIterator[dict[str, Any]]:
    """Yield new JSON lines appended to *path*.

    If *from_beginning* is True, read all existing lines first.
    Then watch for new data via polling (works across Docker volumes).
    """
    path = Path(path)

    # Wait for file to exist
    while not path.exists():
        await asyncio.sleep(poll_interval)

    offset = 0 if from_beginning else path.stat().st_size

    while True:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            await asyncio.sleep(poll_interval)
            continue

        if size > offset:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("skipping non-JSON line: %.80s", line)
                offset = fh.tell()
        elif size < offset:
            # File was truncated / rotated
            offset = 0
            continue

        await asyncio.sleep(poll_interval)


def read_ndjson_file(path: str | Path, max_lines: int = 10_000) -> list[dict[str, Any]]:
    """Read an NDJSON file synchronously, return list of parsed dicts."""
    path = Path(path)
    if not path.exists():
        return []
    results: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results
