# IaC Engine

This engine converts a JSON topology blueprint into a runnable Docker lab with deterministic networking, router firewall rules, and packet capture.

## Quickstart
1. Generate the compose and scripts:
```bash
python -m iac_engine.builder --config topologies/lab_config.json --output-dir outputs/iac_engine
```

2. Start the lab:
```bash
docker compose -f outputs/iac_engine/docker-compose.yml up -d
```

3. Validate routing and firewall rules:
```bash
python -m iac_engine.validator --config topologies/lab_config.json
```

## What gets generated
- `outputs/iac_engine/docker-compose.yml`
- `outputs/iac_engine/router_setup.sh` (router iptables + tcpdump)
- `outputs/iac_engine/start_<node>.sh` (routes + services for non-router nodes that need them)

## JSON structure (high level)
- `networks`: name, subnet CIDR, optional gateway, internal
- `nodes`: name, image, networks (with static IPs and optional MAC), services, dual_homed toggle
- `router`: router node name, firewall policy, explicit rules, logging toggle

## Notes
- Containers that need routing or service startup get `NET_ADMIN`.
- The router always gets `NET_ADMIN` and `NET_RAW` for iptables and tcpdump.
- Validation uses `ping` and `nc` inside containers. Ensure your images include these tools.
