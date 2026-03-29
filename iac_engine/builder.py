from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .iptables import render_firewall_rules
from .models import LabConfig, Node

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _dump_yaml(obj, indent: int = 0) -> str:
    sp = "  " * indent
    if isinstance(obj, dict):
        lines: List[str] = []
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{sp}{key}:")
                lines.append(_dump_yaml(value, indent + 1))
            else:
                lines.append(f"{sp}{key}: {_yaml_scalar(value)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        lines = []
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.append(f"{sp}-")
                lines.append(_dump_yaml(item, indent + 1))
            else:
                lines.append(f"{sp}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{sp}{_yaml_scalar(obj)}"


def _render_template(template_name: str, mapping: Dict[str, str]) -> str:
    template_path = TEMPLATE_DIR / template_name
    content = template_path.read_text()
    for key, value in mapping.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def load_config(config_path: Path) -> LabConfig:
    data = json.loads(config_path.read_text())
    return LabConfig.model_validate(data)


def _services_to_shell(commands: List[str]) -> str:
    if not commands:
        return "true"
    return "\n".join(f"{cmd} &" for cmd in commands)


def _router_tcpdump_cmd() -> str:
    return (
        "tcpdump -i any -n -U -G 300 -W 20 "
        "-w /pcaps/router_%Y-%m-%d_%H-%M-%S.pcap "
        ">/pcaps/tcpdump.log 2>&1 &"
    )


def _node_routes(
    node: Node, router_by_network: Dict[str, str], all_subnets: Dict[str, str]
) -> List[Tuple[str, str]]:
    attached = {net.name for net in node.networks}
    if not attached:
        return []
    primary_network = node.networks[0].name
    via = router_by_network.get(primary_network)
    if not via:
        return []
    routes = []
    for net_name, subnet in all_subnets.items():
        if net_name not in attached:
            routes.append((subnet, via))
    return routes


def _write_script(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _env_var_prefix(node_name: str) -> str:
    """Convert node name to env var prefix, stripping the lab_ prefix."""
    name = node_name.upper()
    if name.startswith("LAB_"):
        name = name[4:]
    return name


def _compute_injected_env(config: LabConfig) -> Dict[str, Dict[str, str]]:
    """Compute auto-injected topology env vars for each node.

    Every container receives:
      LAB_<NODE>_IP          - primary (first-network) IP of each node
      LAB_<NODE>_<NET>_IP    - per-network IP for multi-homed nodes
      ROUTER_IP              - router IP on this node's primary network
      GATEWAY_IP             - Docker bridge gateway on primary network
      <NET>_SUBNET           - CIDR for each network
      <NET>_GATEWAY          - gateway IP for each network (when defined)
    """
    net_gateways: Dict[str, Optional[str]] = {
        net.name: (str(net.gateway) if net.gateway else None)
        for net in config.networks
    }
    net_subnets: Dict[str, str] = {net.name: str(net.subnet) for net in config.networks}

    router_node = next(n for n in config.nodes if n.name == config.router.name)
    router_ips: Dict[str, str] = {nn.name: str(nn.ipv4) for nn in router_node.networks}

    # Build shared node IP vars (same block injected into every service)
    shared_node_vars: Dict[str, str] = {}
    for node in config.nodes:
        prefix = _env_var_prefix(node.name)
        shared_node_vars[f"LAB_{prefix}_IP"] = str(node.networks[0].ipv4)
        if len(node.networks) > 1:
            for nn in node.networks:
                net_upper = nn.name.upper()
                shared_node_vars[f"LAB_{prefix}_{net_upper}_IP"] = str(nn.ipv4)

    result: Dict[str, Dict[str, str]] = {}
    for node in config.nodes:
        env: Dict[str, str] = {}
        env.update(shared_node_vars)

        primary_net = node.networks[0].name
        if primary_net in router_ips:
            env["ROUTER_IP"] = router_ips[primary_net]

        gw = net_gateways.get(primary_net)
        if gw:
            env["GATEWAY_IP"] = gw

        for net in config.networks:
            net_upper = net.name.upper()
            env[f"{net_upper}_SUBNET"] = net_subnets[net.name]
            if net.gateway:
                env[f"{net_upper}_GATEWAY"] = str(net.gateway)

        result[node.name] = env

    return result


def generate_router_setup(config: LabConfig, output_dir: Path) -> Path:
    router_node = next(node for node in config.nodes if node.name == config.router.name)
    iptables_lines = render_firewall_rules(config.router.firewall)
    iptables_block = "\n".join(iptables_lines)
    services_block = _services_to_shell(router_node.services)
    content = _render_template(
        "router_setup.sh.tmpl",
        {
            "IPTABLES_RULES": iptables_block,
            "TCPDUMP_CMD": _router_tcpdump_cmd(),
            "SERVICES": services_block,
        },
    )
    path = output_dir / "router_setup.sh"
    _write_script(path, content)
    return path


def generate_node_start(
    node: Node, routes: List[Tuple[str, str]], output_dir: Path
) -> Optional[Path]:
    if not routes and not node.services:
        return None
    route_lines = []
    for subnet, via in routes:
        route_lines.append(f"ip route add {subnet} via {via} || true")
    routes_block = "\n".join(route_lines) if route_lines else "true"
    services_block = _services_to_shell(node.services)
    content = _render_template(
        "node_start.sh.tmpl",
        {
            "ROUTES": routes_block,
            "SERVICES": services_block,
        },
    )
    path = output_dir / f"start_{node.name}.sh"
    _write_script(path, content)
    return path


def build_compose(config: LabConfig, injected_env: Dict[str, Dict[str, str]]) -> Dict:
    networks = {}
    for net in config.networks:
        net_entry: Dict = {
            "name": net.name,
            "driver": "bridge",
            "ipam": {"config": [{"subnet": str(net.subnet)}]},
        }
        if net.gateway:
            net_entry["ipam"]["config"][0]["gateway"] = str(net.gateway)
        if net.internal:
            net_entry["internal"] = True
        networks[net.name] = net_entry

    services = {}
    for node in config.nodes:
        cc = node.compose
        svc: Dict = {}

        if cc.build:
            svc["build"] = cc.build
        svc["image"] = node.image
        svc["container_name"] = node.name

        if cc.profile:
            svc["profiles"] = [cc.profile]
        if cc.init:
            svc["init"] = True
        if cc.privileged:
            svc["privileged"] = True

        svc["networks"] = {}
        for nn in node.networks:
            net_cfg: Dict = {"ipv4_address": str(nn.ipv4)}
            if nn.mac_address:
                net_cfg["mac_address"] = nn.mac_address
            svc["networks"][nn.name] = net_cfg

        # Auto-injected topology vars merged with explicit env (explicit wins)
        env: Dict[str, str] = {}
        env.update(injected_env.get(node.name, {}))
        env.update(cc.environment)
        if env:
            svc["environment"] = env

        # DNS: explicit config > auto (router on primary network)
        if cc.dns:
            svc["dns"] = cc.dns
        elif "ROUTER_IP" in injected_env.get(node.name, {}):
            svc["dns"] = [injected_env[node.name]["ROUTER_IP"]]

        if cc.volumes:
            svc["volumes"] = cc.volumes
        if cc.ports:
            svc["ports"] = cc.ports
        if cc.cap_add:
            svc["cap_add"] = cc.cap_add
        if cc.restart:
            svc["restart"] = cc.restart

        if cc.depends_on:
            svc["depends_on"] = {
                name: {"condition": dep.condition}
                for name, dep in cc.depends_on.items()
            }

        if cc.healthcheck:
            hc: Dict = {"test": cc.healthcheck.test}
            hc["interval"] = cc.healthcheck.interval
            hc["timeout"] = cc.healthcheck.timeout
            hc["retries"] = cc.healthcheck.retries
            if cc.healthcheck.start_period:
                hc["start_period"] = cc.healthcheck.start_period
            svc["healthcheck"] = hc

        if cc.command:
            svc["command"] = cc.command
        if cc.entrypoint:
            svc["entrypoint"] = cc.entrypoint

        services[node.name] = svc

    volumes_section: Dict = {}
    for vol in config.named_volumes:
        volumes_section[vol] = {}

    compose: Dict = {
        "version": "3.8",
        "services": services,
        "networks": networks,
    }
    if volumes_section:
        compose["volumes"] = volumes_section

    return compose


def build(config_path: Path, output_path: Path) -> Path:
    """Generate docker-compose.yml from topology config."""
    config = load_config(config_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    injected_env = _compute_injected_env(config)
    compose = build_compose(config, injected_env)
    compose_text = _dump_yaml(compose)
    output_path.write_text(compose_text)

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate docker-compose.yml from lab topology JSON."
    )
    parser.add_argument("--config", required=True, type=Path, help="Path to lab_config.json")
    parser.add_argument(
        "--output",
        default=Path("docker-compose.yml"),
        type=Path,
        help="Output path for docker-compose.yml (default: ./docker-compose.yml)",
    )
    args = parser.parse_args()

    compose_path = build(args.config, args.output)
    print(f"Generated {compose_path}")


if __name__ == "__main__":
    main()
