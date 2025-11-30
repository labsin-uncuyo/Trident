# Lab Topology and Functional Specification

## Overview
Phase 1 now delivers a five-container “tiny routed lab” that mirrors Stratosphere Linux IPS (SLIPS) deployment practices. Two Docker bridges (`lab_net_a`, `lab_net_b`) are routed through a privileged router. Every container shares `./outputs`, which becomes the rendezvous point for PCAP captures, SLIPS datasets, and defender alerts. Automated tests rely on static IP assignments and the official SLIPS container ingesting rotated PCAPs captured on the **server** (host-based monitoring of client↔server traffic).

## Network Topology
- **lab_net_a (172.30.0.0/24)** – houses the compromised client (172.30.0.10), optional switch/collector (172.30.0.2), and the SLIPS defender (uses host networking but still mounts the same outputs).
- **lab_net_b (172.31.0.0/24)** – contains the “server” workload at 172.31.0.10 (nginx + PostgreSQL).
- **Router** – `lab_router` binds to 172.30.0.1/24 and 172.31.0.1/24, enables IPv4 forwarding, captures via tcpdump, and mirrors traffic. All east-west flows traverse it, ensuring consistent PCAP generation.

### Address Plan
| Service        | Container        | Network   | IP Address     |
|----------------|------------------|-----------|----------------|
| Router         | lab_router       | net_a     | 172.30.0.1     |
|                |                  | net_b     | 172.31.0.1     |
| Switch (opt)   | lab_switch       | net_a     | 172.30.0.2     |
| Compromised    | lab_compromised  | net_a     | 172.30.0.10    |
| SLIPS Defender | lab_slips_defender (host net) | — | host network |
| Server         | lab_server       | net_b     | 172.31.0.10    |

> NOTE: `lab_slips_defender` uses `network_mode: host` to follow upstream SLIPS docs. It still mounts `./outputs/${RUN_ID}/pcaps` and `./outputs/${RUN_ID}/slips_output` for dataset and output paths.

## Service Matrix
| Container          | Base stack                                   | Key responsibilities |
|--------------------|----------------------------------------------|----------------------|
| **lab_router**     | Ubuntu 22.04, privileged                     | Enables forwarding, exposes `/management.sh` (`block_ip`, `unblock_ip`, `rotate_pcaps`). |
| **lab_switch**     | Ubuntu 22.04 (optional)                      | Listens on TCP/7000, writes `/outputs/<RUN_ID>/pcaps/switch_stream.pcap`, forwards stream to SLIPS TCP/9000 (not required for PCAP ingestion but kept for experiments). |
| **lab_slips_defender** | `stratosphereips/slips:latest` (amd64) + helper scripts | Runs official SLIPS with host networking, watches `/StratosphereLinuxIPS/dataset/` for new PCAPs, executes `slips.py -f dataset/<file>.pcap`, tails `/StratosphereLinuxIPS/output/**/alerts.log`, and forwards alerts to the embedded FastAPI (`127.0.0.1:${DEFENDER_PORT}`) which appends to `/outputs/<RUN_ID>/defender_alerts.ndjson`. |
| **lab_compromised**| Ubuntu 22.04                                 | Acts as the lone “client/attacker” host, SSH on 2223, ships curl/nmap/OpenCode, and routes 172.31.0.0/24 via 172.30.0.1. |
| **lab_server**     | Ubuntu 22.04 + nginx + PostgreSQL            | Exposes HTTP (8080 → 80) and Postgres (5432) to host, initializes `labdb.events`, keeps services alive for restart tests, **captures all server traffic to `/outputs/<RUN_ID>/pcaps/server.pcap` for SLIPS**. |

## Alert Flow
1. `lab_server` captures PCAPs into `outputs/<RUN_ID>/pcaps/` as `server.pcap`.
2. `lab_slips_defender` mounts that directory as `/StratosphereLinuxIPS/dataset`. `watch_pcaps.py` skips live files (`server.pcap`, router/switch streams) and triggers SLIPS runs for rotated copies or injected fixtures (e.g., `server.pcap.1`, `pytest_injected_*.pcap`).
3. SLIPS writes alerts under `/StratosphereLinuxIPS/output/<timestamp>/alerts.log`, which is bind-mounted to `outputs/<RUN_ID>/slips_output/`.
4. `forward_alerts.py` tails every `alerts.log` file and POSTs JSON payloads to `http://127.0.0.1:${DEFENDER_PORT}/alerts`.
5. `defender_api.py` handles `/health` and `/alerts`, appending alerts to `/outputs/<RUN_ID>/defender_alerts.ndjson`. Tests read both the SLIPS log and the NDJSON to verify the pipeline.

## SLIPS Logs & Debugging
- Host path: `outputs/<RUN_ID>/slips_output/<timestamp>/alerts.log`. Use `tail -f outputs/run_local/slips_output/*/alerts.log`.
- Container path: `/StratosphereLinuxIPS/output/<timestamp>/alerts.log`. Use `docker exec -it lab_slips_defender tail -f /StratosphereLinuxIPS/output/*/alerts.log`.
- FastAPI persists every POST to `outputs/<RUN_ID>/defender_alerts.ndjson`, making it easy to correlate alerts with PCAPs.

## Testing & Automation
- `pytest` suite (run via `make verify`) spins the stack, waits for all services to report healthy, and validates:
  - SSH reachability to `lab_compromised`.
  - HTTP reachability from `lab_compromised` to `lab_server`.
  - SLIPS ingestion: copies an existing PCAP, waits for new entries in `slips_output/**/alerts.log`, and asserts defender NDJSON grows.
  - Log rotation: writes a test PCAP inside the router and calls `/management.sh rotate_pcaps`.
  - Server restart policy and post-test cleanup (`make down`).

## Operational Notes
- `make build` now pulls the official SLIPS image in addition to building local ones.
- `make up` wipes any lingering `lab_` containers/networks and pre-creates `outputs/${RUN_ID}/{pcaps,slips_output}` to satisfy volume mounts.
- Because `stratosphereips/slips:latest` is amd64-only, ARM hosts must enable binfmt (`docker run --privileged --rm tonistiigi/binfmt --install amd64`) before `make up`.
- Router management commands (`block_ip`, `unblock_ip`, `rotate_pcaps`) remain unchanged; SLIPS consumes the rotated artifacts automatically.
