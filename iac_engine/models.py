from __future__ import annotations

from typing import Dict, List, Optional, Set
import ipaddress
import re

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

MAC_REGEX = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")


class Network(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    subnet: ipaddress.IPv4Network
    gateway: Optional[ipaddress.IPv4Address] = None
    internal: bool = False

    @field_validator("gateway")
    @classmethod
    def gateway_in_subnet(cls, value: Optional[ipaddress.IPv4Address], info):
        if value is None:
            return value
        subnet = info.data.get("subnet")
        if subnet and value not in subnet:
            raise ValueError("gateway must be within subnet")
        return value


class NodeNetwork(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    ipv4: ipaddress.IPv4Address
    mac_address: Optional[str] = Field(default=None, pattern=MAC_REGEX.pattern)


class DependsOn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str = Field(
        default="service_started",
        pattern=r"^(service_started|service_healthy|service_completed_successfully)$",
    )


class HealthCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test: List[str]
    interval: str = "30s"
    timeout: str = "10s"
    retries: int = 3
    start_period: Optional[str] = None


class NodeComposeConfig(BaseModel):
    """Compose-level properties that don't affect network topology."""

    model_config = ConfigDict(extra="forbid")

    build: Optional[str] = None
    profile: Optional[str] = None
    environment: Dict[str, str] = Field(default_factory=dict)
    volumes: List[str] = Field(default_factory=list)
    ports: List[str] = Field(default_factory=list)
    privileged: bool = False
    init: bool = False
    restart: Optional[str] = None
    cap_add: List[str] = Field(default_factory=list)
    depends_on: Dict[str, DependsOn] = Field(default_factory=dict)
    healthcheck: Optional[HealthCheck] = None
    dns: List[str] = Field(default_factory=list)
    command: Optional[List[str]] = None
    entrypoint: Optional[List[str]] = None


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    image: str = Field(..., min_length=1)
    networks: List[NodeNetwork] = Field(..., min_length=1)
    services: List[str] = Field(default_factory=list)
    dual_homed: bool = False
    compose: NodeComposeConfig = Field(default_factory=NodeComposeConfig)


class FirewallRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    chain: str = Field(default="FORWARD")
    action: str = Field(..., pattern=r"^(ACCEPT|DROP)$")
    src: Optional[ipaddress.IPv4Network] = None
    dst: Optional[ipaddress.IPv4Network] = None
    in_iface: Optional[str] = None
    out_iface: Optional[str] = None
    proto: Optional[str] = Field(default=None, pattern=r"^(tcp|udp|icmp)$")
    sport: Optional[int] = Field(default=None, ge=1, le=65535)
    dport: Optional[int] = Field(default=None, ge=1, le=65535)
    state: Optional[str] = None

    @field_validator("chain")
    @classmethod
    def only_forward(cls, value: str):
        if value != "FORWARD":
            raise ValueError("only FORWARD chain is supported in this engine")
        return value

    @model_validator(mode="after")
    def ports_require_proto(self):
        if (self.sport or self.dport) and self.proto not in {"tcp", "udp"}:
            raise ValueError("sport/dport require proto tcp or udp")
        return self


class FirewallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_forward_policy: str = Field(..., pattern=r"^(ACCEPT|DROP)$")
    logging: bool = False
    rules: List[FirewallRule] = Field(default_factory=list)


class RouterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    firewall: FirewallConfig


class LabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    networks: List[Network] = Field(..., min_length=1)
    nodes: List[Node] = Field(..., min_length=1)
    router: RouterConfig
    named_volumes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_topology(self):
        network_names: Set[str] = set()
        for net in self.networks:
            if net.name in network_names:
                raise ValueError(f"duplicate network name: {net.name}")
            network_names.add(net.name)

        node_names: Set[str] = set()
        for node in self.nodes:
            if node.name in node_names:
                raise ValueError(f"duplicate node name: {node.name}")
            node_names.add(node.name)

        if self.router.name not in node_names:
            raise ValueError("router.name must reference an existing node")

        networks_by_name = {net.name: net for net in self.networks}
        ip_seen: Set[str] = set()

        router_node = next(node for node in self.nodes if node.name == self.router.name)
        if len(router_node.networks) < 2:
            raise ValueError("router must attach to at least two networks")
        router_networks = {net.name for net in router_node.networks}

        for node in self.nodes:
            if not node.dual_homed and len(node.networks) > 1 and node.name != self.router.name:
                raise ValueError(f"node {node.name} has multiple networks but dual_homed is false")

            for net in node.networks:
                if net.name not in networks_by_name:
                    raise ValueError(f"node {node.name} references unknown network {net.name}")
                if node.name != self.router.name and net.name not in router_networks:
                    raise ValueError(f"router is not attached to network {net.name}")
                subnet = networks_by_name[net.name].subnet
                if net.ipv4 not in subnet:
                    raise ValueError(f"node {node.name} ip {net.ipv4} not in subnet {subnet}")
                ip_key = f"{net.name}:{net.ipv4}"
                if ip_key in ip_seen:
                    raise ValueError(f"duplicate ip {net.ipv4} on network {net.name}")
                ip_seen.add(ip_key)

        return self
