from __future__ import annotations

import json
import os
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
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            payload = {"raw": line, "run_id": RUN_ID}
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
