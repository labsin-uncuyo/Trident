from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

DATASET_DIR = Path("/StratosphereLinuxIPS/dataset")
OUTPUT_DIR = Path("/StratosphereLinuxIPS/output")
RUN_ID = "run_local"
# Fixed cadence and behavior: no active stream snapshots, 5s poll, 60s per-PCAP timeout.
POLL_INTERVAL = 5.0
PROCESS_ACTIVE = False
PROCESS_TIMEOUT = 60.0
SKIP_ACTIVE = {"router.pcap", "router_stream.pcap", "switch_stream.pcap"}
SKIP_ACTIVE.add("server.pcap")
SKIP_PREFIXES = ("router_stream", "switch_stream", "server_stream")


def _write_sentinel(path: Path, note: str) -> None:
    assurance_dir = OUTPUT_DIR / "_watch_events"
    assurance_dir.mkdir(parents=True, exist_ok=True)
    sentinel = {
        "run_id": RUN_ID,
        "pcap": path.name,
        "source": "watch_pcaps",
        "timestamp": time.time(),
        "note": note,
    }
    line = json.dumps(sentinel)
    with (assurance_dir / "alerts.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    defender_file = Path("/outputs") / RUN_ID / "slips" / "defender_alerts.ndjson"
    defender_file.parent.mkdir(parents=True, exist_ok=True)
    with defender_file.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(f"[slips-watch] wrote sentinel alert for {path.name}: {note}", flush=True)


def _eligible(path: Path) -> tuple[bool, str]:
    if path.name in SKIP_ACTIVE and not PROCESS_ACTIVE:
        return False, "skip_active"
    if path.name.startswith(SKIP_PREFIXES):
        return False, "skip_prefix"
    if not path.is_file():
        return False, "not_file"
    if path.suffix == ".gz":
        return False, "gzip"
    try:
        stat = path.stat()
        if stat.st_size == 0:
            return False, "empty"
    except FileNotFoundError:
        return False, "missing"
    return True, ""


def _process(path: Path) -> None:
    print(f"[slips-watch] processing {path.name}", flush=True)
    _write_sentinel(path, "queued")
    subprocess.run(
        ["python3", "/StratosphereLinuxIPS/slips.py", "-f", f"dataset/{path.name}"],
        cwd="/StratosphereLinuxIPS",
        timeout=PROCESS_TIMEOUT,
        check=True,
    )
    _write_sentinel(path, "completed")


def _pcap_bounds(path: Path) -> tuple[datetime, datetime] | None:
    """Return (first_ts, last_ts) in UTC from a libpcap file."""
    # libpcap global header: magic (4), version_major (2), version_minor (2),
    # thiszone (4), sigfigs (4), snaplen (4), network (4)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(data) < 24:
        return None
    magic = int.from_bytes(data[0:4], "little")
    if magic == 0xA1B2C3D4:
        endian = "little"
    elif magic == 0xD4C3B2A1:
        endian = "big"
    else:
        return None
    offset = 24
    first = last = None
    while offset + 16 <= len(data):
        ts_sec = int.from_bytes(data[offset : offset + 4], endian)
        ts_usec = int.from_bytes(data[offset + 4 : offset + 8], endian)
        incl_len = int.from_bytes(data[offset + 8 : offset + 12], endian)
        # orig_len not needed for bounds
        ts = datetime.fromtimestamp(ts_sec + ts_usec / 1_000_000, tz=timezone.utc)
        if first is None:
            first = ts
        last = ts
        offset += 16 + incl_len
        if offset > len(data):
            break
    if first is None or last is None:
        return None
    return first, last


def _rename_output_dir(pcap_path: Path) -> None:
    bounds = _pcap_bounds(pcap_path)
    if not bounds:
        return
    start_ts, end_ts = bounds
    start_str = start_ts.strftime("%Y-%m-%d_%H-%M-%S")
    end_str = end_ts.strftime("%Y-%m-%d_%H-%M-%S")
    prefix = f"{pcap_path.name}_"
    candidates = [p for p in OUTPUT_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    if not candidates:
        return
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    new_name = f"{pcap_path.stem}_{start_str}_to_{end_str}"
    dest = OUTPUT_DIR / new_name
    if dest.exists():
        return
    try:
        latest.rename(dest)
    except OSError:
        return


def main() -> None:
    processed: set[str] = set()
    last_snapshot: dict[str, float] = {}
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[slips-watch] starting; watching {DATASET_DIR}", flush=True)
    last_heartbeat = 0.0
    while True:
        paths = []
        for path in DATASET_DIR.glob("*.pcap*"):
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            paths.append((mtime, path))
        for _, path in sorted(paths, key=lambda t: t[0]):
            print(f"[slips-watch] candidate discovered: {path.name}", flush=True)
            ok, reason = _eligible(path)
            if not ok:
                print(f"[slips-watch] skip {path.name}: {reason}", flush=True)
                continue
            try:
                marker = f"{path.name}:{int(path.stat().st_mtime)}:{path.stat().st_size}"
            except FileNotFoundError:
                continue

            target_path = path
            if PROCESS_ACTIVE and path.name in SKIP_ACTIVE:
                now = time.time()
                last = last_snapshot.get(path.name, 0.0)
                if now - last < ACTIVE_SNAPSHOT_COOLDOWN:
                    print(f"[slips-watch] skip {path.name}: snapshot_cooldown", flush=True)
                    continue
                snapshot = path.with_name(f"{path.stem}_{int(now)}{path.suffix}")
                try:
                    shutil.copy2(path, snapshot)
                except FileNotFoundError:
                    continue
                target_path = snapshot
                last_snapshot[path.name] = now
                try:
                    marker = f"{target_path.name}:{int(target_path.stat().st_mtime)}:{target_path.stat().st_size}"
                except FileNotFoundError:
                    continue

            if marker in processed:
                print(f"[slips-watch] already processed {path.name} ({marker})", flush=True)
                continue
            try:
                _process(target_path)
                _rename_output_dir(target_path)
                processed.add(marker)
            except subprocess.TimeoutExpired:
                print(f"[slips-watch] SLIPS timed out for {path.name} after {PROCESS_TIMEOUT}s", flush=True)
                _write_sentinel(path, "timeout")
                processed.add(marker)
            except subprocess.CalledProcessError as exc:
                print(f"[slips-watch] SLIPS failed for {path.name}: {exc}", flush=True)
                _write_sentinel(path, "failed")
                processed.add(marker)
        now = time.time()
        if now - last_heartbeat >= 10:
            _write_sentinel(Path("heartbeat.pcap"), "heartbeat")
            last_heartbeat = now
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
