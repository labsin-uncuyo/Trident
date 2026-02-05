# Trident Architecture

This page is derived from the actual configs and entrypoints in this repo. It explains how the lab boots, routes traffic, and produces artifacts.

## Start/stop commands
- **Infra-only bring-up**: `make up` (uses `docker-compose.yml` with the `core` profile).
- **Tear down**: `make down` (removes containers + volumes).

Makefile: `Makefile`

## Containers created in infra-only mode
`make up` starts the `core` profile only:
- `lab_router` (privileged): routes between subnets and captures PCAPs.
- `lab_server` (privileged): nginx + PostgreSQL + SSH + login app.
- `lab_compromised`: SSH-accessible client host.

Compose: `docker-compose.yml`

## Networks and routing
Two Docker bridge networks are created:
- `lab_net_a` — 172.30.0.0/24 (gateway 172.30.0.254)
- `lab_net_b` — 172.31.0.0/24 (gateway 172.31.0.254)

Note: Docker assigns the `.254` gateway to the bridge network itself. The lab containers then **override their default routes** to point at the router (`.1`) so all traffic is forced through `lab_router` and captured.

Static IPs:
- `lab_router`: 172.30.0.1 + 172.31.0.1
- `lab_compromised`: 172.30.0.10
- `lab_server`: 172.31.0.10

Default routes:
- `lab_compromised` forces default via `172.30.0.1` and adds routes to `172.31.0.0/24` and `172.32.0.0/24` through the router. `images/compromised/entrypoint.sh`

Note: `172.32.0.0/24` is not used by the current topology, but a route is pre-installed so a future third subnet can be added without 
changing the compromised host setup.

- `lab_server` forces default via `172.31.0.1` and routes `172.30.0.0/24` through the router. `images/server/entrypoint.sh`

Router forwarding and NAT:
- Enables `net.ipv4.ip_forward=1`.
- Installs iptables rules to allow forward between the two networks and to support host access via router IPs (DNAT/SNAT).
- Adds a DNAT rule that maps `137.184.126.86:443` to `172.31.0.1:443` for simulated exfiltration capture.

Router entrypoint: `images/router/entrypoint.sh`

Host access points (via router DNAT rules):
- SSH to compromised: `172.30.0.1:22` → `172.30.0.10:22`
- HTTP to server: `172.31.0.1:80` → `172.31.0.10:80`
- PostgreSQL to server: `172.31.0.1:5432` → `172.31.0.10:5432`

## Traffic capture (PCAPs)
- **Router PCAPs (rotated)**: `tcpdump -G` rotates files every 30 seconds into `outputs/<RUN_ID>/pcaps/router_%Y-%m-%d_%H-%M-%S.pcap`.
- **Server PCAP (continuous)**: `lab_server` runs `tcpdump` on `eth0` to `outputs/<RUN_ID>/pcaps/server.pcap`.

Router and server entrypoints:
- `images/router/entrypoint.sh`
- `images/server/entrypoint.sh`

## RUN_ID and outputs directory creation
`make up` sets `RUN_ID` (or generates `logs_YYYYMMDD_HHMMSS`), writes it to `outputs/.current_run`, and creates the output tree:
```
outputs/<RUN_ID>/
├── pcaps/
├── slips/
├── aracne/
└── benign_agent/
```
Makefile: `Makefile`

## Agents and how they plug in
Agents are optional and can run after infra is up.

- **Defender (SLIPS + auto-responder)**
  - Runs in `lab_slips_defender` on **host network**.
  - Reads PCAPs from `outputs/<RUN_ID>/pcaps` and writes IDS outputs to `outputs/<RUN_ID>/slips`.
  - Starts via `make defend`.
  - Compose + entrypoint: `docker-compose.yml`, `images/slips_defender/slips_entrypoint.sh`.

- **Attacker (ARACNE)**
  - Runs in `lab_aracne_attacker` on `lab_net_b` and SSHs to `lab_compromised`.
  - Goal text passed via `GOAL=...` (used by `make aracne "..."`).
  - Writes logs to `outputs/<RUN_ID>/aracne/`.
  - Compose + config: `docker-compose.yml`, `configs/aracne_lab/`.

- **Attacker (coder56)**
  - Host-side runner that execs OpenCode inside `lab_compromised`.
  - Logs to `outputs/<RUN_ID>/coder56/`.
  - Runner: `scripts/attacker_opencode_interactive.py`.

- **Benign (db_admin)**
  - Host-side runner that execs OpenCode inside `lab_compromised`.
  - Logs to `outputs/<RUN_ID>/benign_agent/`.
  - Runner: `images/compromised/db_admin_logger.py`.

## Alerts and logs
- SLIPS outputs under `outputs/<RUN_ID>/slips/`.
- Defender writes `defender_alerts.ndjson` and watcher events under the same directory. `images/slips_defender/watch_pcaps.py`

## Environment variables that control behavior
From `.env.example` and compose:
- Core: `RUN_ID`, `LAB_PASSWORD`, `COMPOSE_PROJECT_NAME`
- Defender: `DEFENDER_PORT`, `PLANNER_PORT`, `PLANNER_URL`, `OPENCODE_TIMEOUT`
- LLM/OpenAI: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`
- OpenCode: `OPENCODE_API_KEY`
- Server app: `LOGIN_USER`, `LOGIN_PASSWORD`
- PostgreSQL: `DB_USER`, `DB_PASSWORD`

Notes:
- Router capture rotation is hardcoded to 30s via `PCAP_ROTATE_SECS` default in `images/router/entrypoint.sh`; it is not currently wired to compose/env.

## Safety and privileges
- `lab_router` is **privileged** and uses iptables.
- `lab_server` is **privileged** and uses `NET_ADMIN` + `NET_RAW`.
- `lab_compromised` has `NET_ADMIN` and passwordless sudo for `labuser`.
- `lab_slips_defender` runs with `network_mode: host` and `NET_ADMIN`.
- No explicit egress firewalling is configured; DNS forwarding in the router points to public resolvers (1.1.1.1, 8.8.8.8).

Note: **privileged** containers run with effectively all Linux capabilities (kernel‑level networking, iptables, sysctl, raw sockets). Trident uses this so the router/server can forward traffic and capture PCAPs, but it also means these containers have elevated access on the host.

## Known rough edges / failure modes
- `make verify` assumes the defender is running; for infra-only, use the README’s manual verification steps instead.
- `lab_net_a` / `lab_net_b` subnets can conflict with existing Docker networks; resolve by removing or changing overlapping networks.
- Containers require privileged/capabilities; rootless Docker or locked-down environments may fail to start.
- `lab_slips_defender` uses host networking; port `DEFENDER_PORT` must be free on the host.
