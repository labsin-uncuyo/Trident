import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from iac_engine.iptables import render_firewall_rules
from iac_engine.models import FirewallConfig, FirewallRule


def test_firewall_rule_with_logging():
    firewall = FirewallConfig(
        default_forward_policy="DROP",
        logging=True,
        rules=[
            FirewallRule(
                name="web",
                action="ACCEPT",
                src="172.30.0.0/24",
                dst="172.31.0.10/32",
                proto="tcp",
                dport=80,
            )
        ],
    )
    lines = render_firewall_rules(firewall)
    assert lines[0] == "iptables -P FORWARD DROP"
    assert "LOG" in lines[1]
    assert "--dport 80" in lines[1]
    assert lines[2].endswith("-j ACCEPT")


def test_firewall_rule_with_state():
    firewall = FirewallConfig(
        default_forward_policy="ACCEPT",
        logging=False,
        rules=[
            FirewallRule(
                action="DROP",
                src="172.31.0.0/24",
                dst="172.30.0.0/24",
                proto="tcp",
                dport=22,
                state="NEW",
            )
        ],
    )
    lines = render_firewall_rules(firewall)
    assert lines[0] == "iptables -P FORWARD ACCEPT"
    assert "-m state --state NEW" in lines[1]
    assert lines[1].endswith("-j DROP")
