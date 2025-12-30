#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _wait_for_server_pcap(run_id: str, timeout: int) -> Path:
    pcap = ROOT / "outputs" / run_id / "pcaps" / "server.pcap"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if pcap.exists() and pcap.stat().st_size > 0:
                return pcap
        except OSError:
            pass
        time.sleep(2)
    raise RuntimeError(f"server.pcap not ready after {timeout}s")


def _copy_pcap(src: Path, run_id: str) -> Path:
    dest = src.with_name(f"slips_verify_{int(time.time())}.pcap")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"[slips_verify] Copied {src.name} -> {dest.name}")
    return dest


def _read_defender_alerts(run_id: str) -> list[dict]:
    alerts_path = ROOT / "outputs" / run_id / "defender_alerts.ndjson"
    if not alerts_path.exists():
        return []
    entries: list[dict] = []
    try:
        with alerts_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


def _slips_log_counts(run_id: str) -> dict[Path, int]:
    base = ROOT / "outputs" / run_id / "slips"
    counts: dict[Path, int] = {}
    if not base.exists():
        return counts
    for path in base.glob("**/alerts.log"):
        try:
            with path.open("r", encoding="utf-8") as handle:
                counts[path] = sum(1 for _ in handle)
        except OSError:
            continue
    return counts


def _wait_for_alert(pcap_name: str, run_id: str, timeout: int) -> None:
    before_defender = _read_defender_alerts(run_id)
    before_slips = _slips_log_counts(run_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        defender_entries = _read_defender_alerts(run_id)
        for entry in defender_entries:
            if entry.get("pcap") == pcap_name and entry.get("note") == "completed":
                print(f"[slips_verify] Alert found for {pcap_name} (note=completed)")
                return
        if len(defender_entries) > len(before_defender):
            for entry in defender_entries:
                if entry.get("pcap") == pcap_name:
                    print(f"[slips_verify] Alert found for {pcap_name}")
                    return
        slips_counts = _slips_log_counts(run_id)
        grew = any(slips_counts.get(path, 0) > before_slips.get(path, 0) for path in slips_counts)
        if grew:
            # Alerts grew somewhere; continue polling to see if it matches our pcap
            continue
    raise RuntimeError(f"Timed out waiting for SLIPS alert for {pcap_name} after {timeout}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger SLIPS processing and wait for alert")
    parser.add_argument("--run-id", required=True, help="RUN_ID to target (matches outputs/<run_id>)")
    parser.add_argument("--pcap-timeout", type=int, default=180, help="Seconds to wait for server.pcap")
    parser.add_argument("--alert-timeout", type=int, default=300, help="Seconds to wait for SLIPS alert")
    args = parser.parse_args()

    try:
        base_pcap = _wait_for_server_pcap(args.run_id, args.pcap_timeout)
        injected = _copy_pcap(base_pcap, args.run_id)
        _wait_for_alert(injected.name, args.run_id, args.alert_timeout)
        print(f"[slips_verify] SLIPS alert confirmed for {injected.name}")
        return 0
    except Exception as exc:  # noqa: BLE001 - surface as stderr for make
        print(f"[slips_verify] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
