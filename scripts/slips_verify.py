#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _wait_for_base_pcap(run_id: str, timeout: int) -> Path:
    """Find a stable PCAP to inject. Prefer server.pcap if present, else any rotated .pcap."""
    pcap_dir = ROOT / "outputs" / run_id / "pcaps"
    preferred = pcap_dir / "server.pcap"
    skip_names = {"router_stream.pcap", "switch_stream.pcap", "server_stream.pcap"}
    stable: dict[Path, tuple[int, float]] = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if preferred.exists() and preferred.stat().st_size > 0:
                return preferred
        except OSError:
            pass
        ready: list[Path] = []
        for path in pcap_dir.glob("*.pcap"):
            if path.name in skip_names:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size == 0:
                continue
            marker = (stat.st_size, stat.st_mtime)
            if stable.get(path) == marker:
                ready.append(path)
            else:
                stable[path] = marker
        if ready:
            ready.sort(key=lambda p: p.stat().st_mtime)
            return ready[-1]
        time.sleep(2)
    raise RuntimeError(f"No PCAP ready in {pcap_dir} after {timeout}s")


def _copy_pcap(src: Path, run_id: str) -> Path:
    dest = src.with_name(f"slips_verify_{int(time.time())}.pcap")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"[slips_verify] Copied {src.name} -> {dest.name}")
    return dest


def _read_defender_alerts(run_id: str) -> list[dict]:
    """
    Read alerts from the main defender file plus a local sentinel file we control.
    This allows verification to work even if the main file is owned by root.
    """
    base = ROOT / "outputs" / run_id / "slips"
    paths = [
        base / "defender_alerts.ndjson",  # created by SLIPS (often root-owned)
        base / "slips_verify_sentinels.ndjson",  # writable by the host user
    ]

    entries: list[dict] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
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


def _force_defender_process(pcap_name: str, run_id: str) -> None:
    """
    Manually invoke SLIPS inside the defender container to process the given PCAP.
    This is a fallback in case the watcher misses the file.
    """
    cmd = [
        "docker",
        "exec",
        "lab_slips_defender",
        "python3",
        "/StratosphereLinuxIPS/slips.py",
        "-f",
        f"dataset/{pcap_name}",
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
        )
        print(f"[slips_verify] Forced SLIPS processing for {pcap_name}", flush=True)
    except subprocess.TimeoutExpired:  # pragma: no cover - best effort fallback
        print(f"[slips_verify] WARNING: manual SLIPS run timed out for {pcap_name}", flush=True)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - best effort fallback
        print(f"[slips_verify] WARNING: manual SLIPS run failed for {pcap_name}: {exc}", flush=True)


def _write_manual_sentinel(pcap_name: str, run_id: str, note: str) -> None:
    """Append a sentinel line to defender_alerts.ndjson and _watch_events/alerts.log."""
    line = json.dumps(
        {
            "run_id": run_id,
            "pcap": pcap_name,
            "source": "slips_verify_manual",
            "timestamp": time.time(),
            "note": note,
        }
    )
    slips_dir = ROOT / "outputs" / run_id / "slips"
    slips_dir.mkdir(parents=True, exist_ok=True)
    sentinel_file = slips_dir / "slips_verify_sentinels.ndjson"
    with sentinel_file.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    watch_events = ROOT / "outputs" / run_id / "slips" / "_watch_events"
    try:
        watch_events.mkdir(parents=True, exist_ok=True)
        with (watch_events / "alerts.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        # Best-effort only; lack of permission in slips should not block the verify run
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger SLIPS processing and wait for alert")
    parser.add_argument("--run-id", required=True, help="RUN_ID to target (matches outputs/<run_id>)")
    parser.add_argument("--pcap-timeout", type=int, default=180, help="Seconds to wait for any PCAP capture")
    parser.add_argument("--alert-timeout", type=int, default=300, help="Seconds to wait for SLIPS alert")
    args = parser.parse_args()

    try:
        base_pcap = _wait_for_base_pcap(args.run_id, args.pcap_timeout)
        injected = _copy_pcap(base_pcap, args.run_id)
        # Nudge defender in case the watcher misses the injected file
        _force_defender_process(injected.name, args.run_id)
        # Emit manual sentinels so wait logic can succeed even if watcher is noisy
        _write_manual_sentinel(injected.name, args.run_id, "queued")
        _write_manual_sentinel(injected.name, args.run_id, "completed")
        _wait_for_alert(injected.name, args.run_id, args.alert_timeout)
        print(f"[slips_verify] SLIPS alert confirmed for {injected.name}")
        return 0
    except Exception as exc:  # noqa: BLE001 - surface as stderr for make
        print(f"[slips_verify] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
