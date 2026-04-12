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
Three Docker bridge networks are created:
- `lab_net_a` -- 172.30.0.0/24 (gateway 172.30.0.254)
- `lab_net_b` -- 172.31.0.0/24 (gateway 172.31.0.254)
- `lab_egress` -- 172.32.0.0/24 (gateway 172.32.0.254)

Note: Docker assigns the `.254` gateway to the bridge network itself. The lab containers then **override their default routes** to point at the router (`.1`) so all traffic is forced through `lab_router` and captured.

Static IPs:
- `lab_router`: 172.30.0.1 + 172.31.0.1 + 172.32.0.1
- `lab_compromised`: 172.30.0.10
- `lab_server`: 172.31.0.10

Default routes:
- `lab_compromised` forces default via `172.30.0.1` and adds a route to `172.31.0.0/24` through the router. `images/compromised/entrypoint.sh`
- `lab_server` forces default via `172.31.0.1` and routes `172.30.0.0/24` through the router. `images/server/entrypoint.sh`

`lab_egress` provides internet connectivity through the host. Only `lab_router` and `lab_slips_defender` are attached to it. Lab hosts (`lab_compromised`, `lab_server`) have no attachment to `lab_egress` and no routes into that subnet — they cannot reach the internet directly. The router's iptables rules additionally block forwarding from the lab subnets into the egress interface, so even traffic routed through the router cannot reach the internet unless explicitly permitted.

## Traffic routing

`lab_compromised` and `lab_server` override their default routes on startup to point at `lab_router` (172.30.0.1 and 172.31.0.1 respectively). As a result, every packet between the two subnets crosses the router, where `tcpdump` captures it. There is no path between the hosts that bypasses the router.

The router enables `net.ipv4.ip_forward=1` and installs iptables rules to allow forwarding between the two lab networks.

### DNAT port forwards

Host-accessible DNAT rules on the router let you reach lab services without entering the lab networks directly:

| Host connects to | Reaches |
|---|---|
| 172.30.0.1:22 | lab_compromised:22 (SSH) |
| 172.31.0.1:80 | lab_server:80 (HTTP) |
| 172.31.0.1:5432 | lab_server:5432 (PostgreSQL) |

Each DNAT rule has a corresponding SNAT rule so that reply packets are routed back through the router rather than directly to the Docker bridge gateway.

### Exfiltration simulation

The router also installs a DNAT rule that redirects traffic destined for `137.184.126.86:443` to itself (`172.31.0.1:443`), where a `netcat` listener captures incoming data to `/tmp/exfil/labdb_dump.sql`. This supports simulated data exfiltration scenarios without requiring real external infrastructure -- PCAPs will show connections to a seemingly public IP while the data is captured locally on the router.

## PCAP capture

Two capture modes run simultaneously:

- **Router (rotated):** `tcpdump` on the LAN-A interface (`lan_a_if`), rotating every 30 seconds into `outputs/<RUN_ID>/pcaps/router_YYYY-MM-DD_HH-MM-SS.pcap`. Captures all cross-subnet traffic and DNS queries. The interface is used instead of `any` to produce standard Ethernet-linktype PCAPs compatible with Zeek and SLIPS. Rotation interval is controlled by `PCAP_ROTATE_SECS` in `images/router/entrypoint.sh` (default 30, not wired to `.env`).

- **Server (continuous):** `tcpdump` on `eth0` into `outputs/<RUN_ID>/pcaps/server.pcap`. Captures client-server flows from the server's perspective. Grows for the entire run duration.

## DNS

The router runs `dnsmasq`, listening on both 172.30.0.1 and 172.31.0.1. Lab containers have their DNS set to the router's address on their respective subnet (via `dns:` in `docker-compose.yml`), so all DNS queries pass through the router and appear in the PCAPs. Queries are forwarded to public resolvers (1.1.1.1, 8.8.8.8).

## RUN_ID and outputs directory creation
`make up` sets `RUN_ID` (or generates `logs_YYYYMMDD_HHMMSS`), writes it to `outputs/.current_run`, and creates the output tree:
```
outputs/<RUN_ID>/
├── pcaps/
├── slips/
├── coder56/
└── benign_agent/
```
Makefile: `Makefile`

## Agents and how they plug in
Agents are optional and can run after infra is up.

- **Defender (SLIPS + auto-responder)**
  - Runs in `lab_slips_defender` on `lab_net_a`, `lab_net_b`, and `lab_egress`.
  - Reads PCAPs from `outputs/<RUN_ID>/pcaps` and writes IDS outputs to `outputs/<RUN_ID>/slips`.
  - Starts via `make defend`.
  - Compose + entrypoint: `docker-compose.yml`, `images/slips_defender/slips_entrypoint.sh`.

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
- `lab_slips_defender` runs with `NET_ADMIN` on dedicated network interfaces.
- No explicit egress firewalling is configured; DNS forwarding in the router points to public resolvers (1.1.1.1, 8.8.8.8).

Note: **privileged** containers run with effectively all Linux capabilities (kernel-level networking, iptables, sysctl, raw sockets). Trident uses this so the router/server can forward traffic and capture PCAPs, but it also means these containers have elevated access on the host.

## Known rough edges / failure modes
- `make verify` assumes the defender is running; for infra-only, use the README's manual verification steps instead.
- `lab_net_a` / `lab_net_b` subnets can conflict with existing Docker networks; resolve by removing or changing overlapping networks.
- Containers require privileged/capabilities; rootless Docker or locked-down environments may fail to start.
- `lab_slips_defender` uses host networking; port `DEFENDER_PORT` must be free on the host.
