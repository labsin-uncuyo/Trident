from __future__ import annotations

from typing import List

from .models import FirewallConfig, FirewallRule


def _rule_match_parts(rule: FirewallRule) -> List[str]:
    parts: List[str] = []
    if rule.in_iface:
        parts += ["-i", rule.in_iface]
    if rule.out_iface:
        parts += ["-o", rule.out_iface]
    if rule.src:
        parts += ["-s", str(rule.src)]
    if rule.dst:
        parts += ["-d", str(rule.dst)]
    if rule.proto:
        parts += ["-p", rule.proto]
    if rule.state:
        parts += ["-m", "state", "--state", rule.state]
    if rule.sport:
        parts += ["--sport", str(rule.sport)]
    if rule.dport:
        parts += ["--dport", str(rule.dport)]
    return parts


def _log_prefix(rule: FirewallRule) -> str:
    if rule.name:
        return f"FW {rule.name}: "
    return f"FW {rule.action}: "


def render_firewall_rules(firewall: FirewallConfig) -> List[str]:
    lines: List[str] = []
    lines.append(f"iptables -P FORWARD {firewall.default_forward_policy}")
    for rule in firewall.rules:
        match = _rule_match_parts(rule)
        if firewall.logging:
            prefix = _log_prefix(rule)
            log_parts = ["iptables", "-A", rule.chain] + match + [
                "-j",
                "LOG",
                "--log-prefix",
                f"\"{prefix}\"",
                "--log-level",
                "4",
            ]
            lines.append(" ".join(log_parts))
        action_parts = ["iptables", "-A", rule.chain] + match + ["-j", rule.action]
        lines.append(" ".join(action_parts))
    return lines
