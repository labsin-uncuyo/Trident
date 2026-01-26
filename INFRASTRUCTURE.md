# Trident Infrastructure

This document describes the lab topology, services, routing, and outputs in detail.

## Topology
- `lab_net_a`: 172.30.0.0/24 (client/compromised side)
- `lab_net_b`: 172.31.0.0/24 (server side)
- `lab_router`: 172.30.0.1 (net A) and 172.31.0.1 (net B)

All north–south traffic is routed through `lab_router` and captured as PCAPs.

```
lab_compromised (172.30.0.10) ↔ lab_router ↔ lab_server (172.31.0.10)
```

## Services
- **lab_router** (privileged)
  - Enables IP forwarding
  - Captures traffic to `outputs/<RUN_ID>/pcaps/router_*.pcap`
  - Exposes management helpers (e.g., block/unblock/rotate pcaps)

- **lab_compromised** (net A)
  - SSH target for agents
  - Routes default traffic via the router so flows are captured

- **lab_server** (net B)
  - nginx on port 80
  - PostgreSQL on port 5432
  - Routes default traffic via the router

## Artifact policy
- Router PCAPs are always generated under `outputs/<RUN_ID>/pcaps/`.
- Agent logs are created only for the agents you actually run.
- New agents must define their own log destinations under `outputs/<RUN_ID>/`.

## Access points (via router)
- SSH to compromised: `172.30.0.1:22` → `lab_compromised:22`
- HTTP to server: `172.31.0.1:80` → `lab_server:80`
- PostgreSQL to server: `172.31.0.1:5432` → `lab_server:5432`

## Outputs
All artifacts are scoped under `outputs/<RUN_ID>/`:
- `pcaps/` — router captures (`router_*.pcap`)
- `slips/` — IDS output (if defender is running)
- `aracne/` — attacker logs (when ARACNE is used)
- `coder56/` — attacker logs (when coder56 is used)
- `benign_agent/` — benign agent logs (when benign agent is used)

## Compose profiles
- `core`: router, server, compromised
- `defender`: adds `slips_defender`
- `attackers`: adds `aracne_attacker`
