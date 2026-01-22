# Lab Topology and Functional Specification

## Overview
Phase 1 now delivers a modular “tiny routed lab” that mirrors Stratosphere Linux IPS (SLIPS) deployment practices. Two Docker bridges (`lab_net_a`, `lab_net_b`) are routed through a privileged router. Every container shares `./outputs`, which becomes the rendezvous point for PCAP captures, SLIPS datasets, and defender alerts. Automated tests rely on static IP assignments and the official SLIPS container ingesting rotated PCAPs captured on the **router** (routed observation of client↔server traffic). Services are grouped by profiles: `core` (router/server/compromised), `defender` (slips_defender), `benign` (ghosts_driver), and `attackers` (aracne_attacker).

## Network Topology
- **lab_net_a (172.30.0.0/24)** – houses the compromised client (172.30.0.10).
- **lab_net_b (172.31.0.0/24)** – contains the “server” workload at 172.31.0.10 (nginx + PostgreSQL) and the attacker container at 172.31.0.50.
- **Router** – `lab_router` binds to 172.30.0.1/24 and 172.31.0.1/24, enables IPv4 forwarding, captures via tcpdump, and mirrors traffic. All east-west flows traverse it, ensuring consistent PCAP generation.

### Address Plan
| Service        | Container        | Network   | IP Address     |
|----------------|------------------|-----------|----------------|
| Router         | lab_router       | net_a     | 172.30.0.1     |
|                |                  | net_b     | 172.31.0.1     |
| Compromised    | lab_compromised  | net_a     | 172.30.0.10    |
| Aracne Attacker| lab_aracne_attacker | net_b  | 172.31.0.50    |
| SLIPS Defender | lab_slips_defender (host net) | — | host network |
| Server         | lab_server       | net_b     | 172.31.0.10    |

> NOTE: `lab_slips_defender` uses `network_mode: host` to follow upstream SLIPS docs. It still mounts `./outputs/${RUN_ID}/pcaps` and `./outputs/${RUN_ID}/slips` for dataset and output paths.

## Service Matrix
| Container          | Base stack                                   | Key responsibilities |
|--------------------|----------------------------------------------|----------------------|
| **lab_router**     | Ubuntu 22.04, privileged                     | Enables forwarding, exposes `/management.sh` (`block_ip`, `unblock_ip`, `rotate_pcaps`). |
| **lab_slips_defender** | `stratosphereips/slips:latest` (amd64) + helper scripts | Runs official SLIPS with host networking, watches `/StratosphereLinuxIPS/dataset/` for new PCAPs, executes `slips.py -f dataset/<file>.pcap`, tails `/StratosphereLinuxIPS/output/**/alerts.log`, and forwards alerts to the embedded FastAPI (`127.0.0.1:${DEFENDER_PORT}`) which appends to `/outputs/<RUN_ID>/slips/defender_alerts.ndjson`. |
| **lab_compromised**| Ubuntu 22.04                                 | Acts as the lone “client/attacker” host, SSH reachable via router port-forwarding, ships curl/nmap/OpenCode, and routes all traffic (including default) via 172.30.0.1. |
| **lab_server**     | Ubuntu 22.04 + nginx + PostgreSQL            | Exposes HTTP/Postgres via router port-forwarding, initializes `labdb.events`, keeps services alive for restart tests, defaults to 172.31.0.1 for north-south routing, captures optional host-side traffic to `/outputs/<RUN_ID>/pcaps/server.pcap` for local inspection. |

## Alert Flow
1. `lab_router` captures routed traffic into `outputs/<RUN_ID>/pcaps/` as `router_*.pcap`.
2. `lab_slips_defender` mounts that directory as `/StratosphereLinuxIPS/dataset`. `watch_pcaps.py` skips active captures (`router.pcap`) and triggers SLIPS runs for rotated PCAPs (for example, `router_0000.pcap`).
3. SLIPS writes alerts under `/StratosphereLinuxIPS/output/<timestamp>/alerts.log`, which is bind-mounted to `outputs/<RUN_ID>/slips/`.
4. `forward_alerts.py` tails every `alerts.log` file and POSTs JSON payloads to `http://127.0.0.1:${DEFENDER_PORT}/alerts`.
5. `defender_api.py` handles `/health` and `/alerts`, appending alerts to `/outputs/<RUN_ID>/slips/defender_alerts.ndjson`. Tests read both the SLIPS log and the NDJSON to verify the pipeline.

## SLIPS Logs & Debugging
- Host path: `outputs/<RUN_ID>/slips/<timestamp>/alerts.log`. Use `tail -f outputs/<RUN_ID>/slips/*/alerts.log`.
- Container path: `/StratosphereLinuxIPS/output/<timestamp>/alerts.log`. Use `docker exec -it lab_slips_defender tail -f /StratosphereLinuxIPS/output/*/alerts.log`.
- FastAPI persists every POST to `outputs/<RUN_ID>/slips/defender_alerts.ndjson`, making it easy to correlate alerts with PCAPs.

## Testing & Automation
- `pytest` suite (run via `make verify`) spins the stack, waits for all services to report healthy, and validates:
  - SSH reachability to `lab_compromised`.
  - HTTP reachability from `lab_compromised` to `lab_server`.
- SLIPS ingestion: copies an existing PCAP, waits for new entries in `slips/**/alerts.log`, and asserts defender NDJSON grows.
- Log rotation: writes a test PCAP inside the router and calls `/management.sh rotate_pcaps`.
  - Server restart policy and post-test cleanup (`make down`).

## Operational Notes
- `make build` builds all profiles (core/defender/benign/attackers) via compose.
- `make up` wipes any lingering `lab_` containers/networks and pre-creates `outputs/${RUN_ID}/{pcaps,slips}` to satisfy volume mounts; it starts only the `core` profile.
- `make defend` / `make not_defend` toggle the defender profile; `make ghosts_psql` runs the benign profile; `make aracne_attack` runs the attackers profile after `make up`.
- Because `stratosphereips/slips:latest` is amd64-only, ARM hosts must enable binfmt (`docker run --privileged --rm tonistiigi/binfmt --install amd64`) before `make up`.
- Router management commands (`block_ip`, `unblock_ip`, `rotate_pcaps`) remain unchanged; SLIPS consumes the rotated artifacts automatically when the defender profile is active.
