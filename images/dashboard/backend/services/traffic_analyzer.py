"""Lightweight PCAP traffic analyzer using raw struct parsing (no tshark needed).

Computes per-IP-pair byte totals across all pcap files in the current run,
then maps them onto topology edge IDs. Results are cached for 30 s.
"""

from __future__ import annotations

import logging
import struct
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("dashboard.traffic")

# ── IP → topology node mapping ──────────────────────────────────────
_IP_TO_NODE: dict[str, str] = {
    "172.30.0.10": "compromised",
    "172.30.0.1":  "router",
    "172.31.0.1":  "router",
    "172.31.0.10": "server",
}

# ── Edge → set of (node_a, node_b) pairs it covers ─────────────────
_EDGE_PAIRS: dict[str, set[frozenset[str]]] = {
    "e-comp-router": {frozenset({"compromised", "router"})},
    "e-router-server": {frozenset({"router", "server"})},
}

# ── Simple TTL cache ────────────────────────────────────────────────
_CACHE: dict[str, Any] = {}          # {"result": ..., "ts": float, "run": str}
_CACHE_TTL = 30.0                    # seconds


# ── Raw pcap parser (no external deps) ─────────────────────────────

_PCAP_GLOBAL_HDR = 24
_PCAP_PKT_HDR = 16
_ETH_HDR = 14


def _parse_pcap(path: Path) -> dict[tuple[str, str], int]:
    """Parse one pcap file; return {(src_ip, dst_ip): total_bytes}."""
    flows: dict[tuple[str, str], int] = {}
    try:
        with open(path, "rb") as fh:
            gh = fh.read(_PCAP_GLOBAL_HDR)
            if len(gh) < _PCAP_GLOBAL_HDR:
                return flows
            magic = struct.unpack_from("<I", gh, 0)[0]
            if magic not in (0xA1B2C3D4, 0xD4C3B2A1):
                return flows                    # not a valid libpcap file
            endian = ">" if magic == 0xD4C3B2A1 else "<"

            while True:
                ph = fh.read(_PCAP_PKT_HDR)
                if len(ph) < _PCAP_PKT_HDR:
                    break
                _, _, incl_len, orig_len = struct.unpack_from(f"{endian}IIII", ph, 0)
                data = fh.read(incl_len)
                if len(data) < incl_len:
                    break

                # Ethernet → IPv4 only
                if len(data) < _ETH_HDR + 20:
                    continue
                eth_type = struct.unpack_from(">H", data, 12)[0]
                if eth_type != 0x0800:          # not IPv4
                    continue

                ip = _ETH_HDR
                src = f"{data[ip+12]}.{data[ip+13]}.{data[ip+14]}.{data[ip+15]}"
                dst = f"{data[ip+16]}.{data[ip+17]}.{data[ip+18]}.{data[ip+19]}"
                flows[(src, dst)] = flows.get((src, dst), 0) + orig_len
    except Exception as exc:
        logger.debug("pcap parse error %s: %s", path.name, exc)
    return flows


def _aggregate_to_edges(
    pair_bytes: dict[tuple[str, str], int]
) -> dict[str, dict[str, Any]]:
    """Map per-IP-pair byte totals onto topology edge IDs."""
    edge_bytes: dict[str, int] = {eid: 0 for eid in _EDGE_PAIRS}

    for (src, dst), nbytes in pair_bytes.items():
        src_node = _IP_TO_NODE.get(src)
        dst_node = _IP_TO_NODE.get(dst)
        if not src_node or not dst_node or src_node == dst_node:
            continue
        pair = frozenset({src_node, dst_node})
        for eid, covered in _EDGE_PAIRS.items():
            if pair in covered:
                edge_bytes[eid] += nbytes

    return {
        eid: {
            "bytes": b,
            "mb": round(b / 1_048_576, 2),
            "label": _mb_label(b),
        }
        for eid, b in edge_bytes.items()
    }


def _mb_label(b: int) -> str:
    if b == 0:
        return "0 B"
    if b < 1024:
        return f"{b} B"
    if b < 1_048_576:
        return f"{b/1024:.1f} KB"
    return f"{b/1_048_576:.1f} MB"


def compute_traffic(outputs_dir: Path, run_id: str) -> dict[str, Any]:
    """Return traffic stats for *run_id*, using a 30 s cache."""
    now = time.monotonic()
    cached = _CACHE.get("result")
    if cached and _CACHE.get("run") == run_id and (now - _CACHE.get("ts", 0)) < _CACHE_TTL:
        return cached

    pcap_dir = outputs_dir / run_id / "pcaps"
    pair_bytes: dict[tuple[str, str], int] = {}

    if pcap_dir.is_dir():
        for pcap in sorted(pcap_dir.glob("*.pcap")):
            for (src, dst), nb in _parse_pcap(pcap).items():
                pair_bytes[(src, dst)] = pair_bytes.get((src, dst), 0) + nb

    # Build per-pair MB list (filter only known-node IPs)
    flows = []
    for (src, dst), nb in sorted(pair_bytes.items(), key=lambda x: -x[1])[:50]:
        if _IP_TO_NODE.get(src) or _IP_TO_NODE.get(dst):
            flows.append({
                "src": src,
                "dst": dst,
                "src_node": _IP_TO_NODE.get(src, "unknown"),
                "dst_node": _IP_TO_NODE.get(dst, "unknown"),
                "bytes": nb,
                "mb": round(nb / 1_048_576, 2),
            })

    result = {
        "run_id": run_id,
        "flows": flows,
        "edges": _aggregate_to_edges(pair_bytes),
    }
    _CACHE["result"] = result
    _CACHE["ts"] = now
    _CACHE["run"] = run_id
    return result
