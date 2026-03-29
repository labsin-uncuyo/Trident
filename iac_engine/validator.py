from __future__ import annotations

import argparse
import ipaddress
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import LabConfig, FirewallRule
from .builder import load_config


def _run_exec(container: str, command: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", container] + command,
        check=False,
        capture_output=True,
        text=True,
    )


def _pick_node_by_cidr(nodes: Dict[str, Dict[str, str]], cidr: ipaddress.IPv4Network) -> Optional[Tuple[str, str]]:
    for name, ips in nodes.items():
        for ip in ips.values():
            if ipaddress.ip_address(ip) in cidr:
                return name, ip
    return None


def _rule_checks(nodes: Dict[str, Dict[str, str]], rule: FirewallRule) -> List[Tuple[str, str, str, int, bool]]:
    if rule.proto not in {"tcp", "udp", "icmp"}:
        return []
    if rule.src is None or rule.dst is None:
        return []
    src_pick = _pick_node_by_cidr(nodes, rule.src)
    dst_pick = _pick_node_by_cidr(nodes, rule.dst)
    if not src_pick or not dst_pick:
        return []
    src_name, _ = src_pick
    _, dst_ip = dst_pick
    if rule.proto in {"tcp", "udp"} and rule.dport:
        return [(src_name, dst_ip, rule.proto, rule.dport, rule.action == "ACCEPT")]
    if rule.proto == "icmp":
        return [(src_name, dst_ip, "icmp", 0, rule.action == "ACCEPT")]
    return []


def validate_lab(config: LabConfig) -> bool:
    nodes = {node.name: {net.name: str(net.ipv4) for net in node.networks} for node in config.nodes}
    ok = True

    for rule in config.router.firewall.rules:
        checks = _rule_checks(nodes, rule)
        for src, dst_ip, proto, dport, should_succeed in checks:
            if proto == "icmp":
                result = _run_exec(src, ["ping", "-c", "1", "-W", "1", dst_ip])
            else:
                result = _run_exec(src, ["nc", "-zvw", "2", dst_ip, str(dport)])
            passed = result.returncode == 0
            if passed != should_succeed:
                ok = False
                expectation = "ACCEPT" if should_succeed else "DROP"
                print(f"FAILED: {src} -> {dst_ip} {proto}/{dport} expected {expectation}")

    for net in config.networks:
        members = [n for n, ips in nodes.items() if net.name in ips]
        if len(members) < 2:
            continue
        source = members[0]
        for target in members[1:]:
            ip = nodes[target][net.name]
            result = _run_exec(source, ["ping", "-c", "1", "-W", "1", ip])
            if result.returncode != 0:
                ok = False
                print(f"FAILED: ping sweep {source} -> {ip} on {net.name}")

    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-deployment validation for lab topology.")
    parser.add_argument("--config", required=True, type=Path, help="Path to lab_config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    success = validate_lab(config)
    if not success:
        raise SystemExit(1)
    print("Validation passed")


if __name__ == "__main__":
    main()
