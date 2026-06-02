from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict

import requests

# Dynamic SLIPS path detection to handle different versions
def _find_slips_base() -> Path:
    """Find the SLIPS installation directory across different versions."""
    candidates = [
        Path("/StratosphereLinuxIPS"),
        Path("/opt/slips"),
        Path("/usr/local/slips"),
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "slips.py").exists():
            return candidate
    # Default to original path if none found
    return Path("/StratosphereLinuxIPS")

SLIPS_BASE = _find_slips_base()
RUN_ID = os.getenv("RUN_ID", "run_local")
OUTPUT_ROOT = Path(os.getenv("SLIPS_OUTPUT_DIR", str(SLIPS_BASE / "output")))
DEFENDER_URL = os.getenv("DEFENDER_URL", "http://127.0.0.1:8000/alerts")
POLL_INTERVAL = float(os.getenv("SLIPS_ALERT_INTERVAL", "2"))

# Regex to detect the start of a new SLIPS alert (lines with ISO timestamp)
# Matches patterns like: 2026-05-11T23:42:21.263763+00:00
_SLIPS_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _log_files() -> list[Path]:
    if not OUTPUT_ROOT.exists():
        return []
    return sorted(OUTPUT_ROOT.glob("**/alerts.log"))


def _post_alert(payload: Dict[str, object]) -> bool:
    try:
        requests.post(DEFENDER_URL, json=payload, timeout=5).raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"[slips-forward] failed to POST alert: {exc}", flush=True)
        return False


def _aggregate_alerts(lines: list[str]) -> list[str]:
    """
    Aggregate multi-line SLIPS alerts into single complete alerts.

    SLIPS alerts can span multiple lines. A new alert starts with a line
    beginning with an ISO timestamp. Lines without timestamps are continuations
    of the previous alert. Blank lines are preserved as part of the alert content.

    Args:
        lines: Raw lines from the alerts.log file

    Returns:
        List of complete alerts (each alert is a joined string)
    """
    complete_alerts = []
    current_alert_parts: list[str] = []

    for line in lines:
        original_line = line.rstrip("\n\r")
        stripped = original_line.strip()

        # Check if this line starts a new alert (has ISO timestamp at start)
        if _SLIPS_TIMESTAMP_RE.match(stripped):
            # Save previous alert if exists
            if current_alert_parts:
                complete_alerts.append(" ".join(current_alert_parts))
            # Start new alert - preserve original spacing
            current_alert_parts = [stripped]
        else:
            # Continuation of current alert - preserve the content
            # Empty lines become spaces, non-empty lines are added
            current_alert_parts.append(stripped)

    # Don't forget the last alert
    if current_alert_parts:
        complete_alerts.append(" ".join(current_alert_parts))

    return complete_alerts


def main() -> None:
    positions: Dict[Path, int] = {}
    while True:
        for log_path in _log_files():
            try:
                current_size = log_path.stat().st_size
            except FileNotFoundError:
                continue
            previous = positions.get(log_path, 0)
            if current_size < previous:
                previous = 0
            if current_size == previous:
                continue
            start_pos = previous
            try:
                with log_path.open("r", encoding="utf-8") as handle:
                    handle.seek(previous)
                    success = True

                    # Read all new lines and aggregate multi-line alerts
                    new_lines = handle.readlines()
                    if not new_lines:
                        positions[log_path] = handle.tell()
                        continue

                    complete_alerts = _aggregate_alerts(new_lines)

                    for alert in complete_alerts:
                        alert = alert.strip()
                        if not alert:
                            continue
                        try:
                            payload = json.loads(alert)
                        except json.JSONDecodeError:
                            payload = {"raw": alert, "run_id": RUN_ID}
                        if not _post_alert(payload):
                            success = False
                            break

                    if success:
                        positions[log_path] = handle.tell()
                    else:
                        positions[log_path] = start_pos
            except FileNotFoundError:
                continue
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
