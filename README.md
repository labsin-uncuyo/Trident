# Trident Lab

## What it is
Trident is a compact, fully routed Docker lab for evaluating network telemetry, IDS/IPS pipelines, and agent behavior in a reproducible environment. It models a small enterprise segment (client → router → server) and makes traffic capture a first‑class output.

## Why it exists / use cases
- Validate detection rules against realistic routed traffic.
- Compare agent behaviors with consistent network baselines.
- Generate repeatable PCAP datasets for IDS evaluation.
- Teach or demo network monitoring in a contained lab.

## Key features
- Deterministic IPs and routes so traffic always crosses the router.
- Automated PCAP capture (router + server) into `outputs/<RUN_ID>/`.
- Optional agents (defender/attacker/benign) that plug in after infra is up.
- Single-command infra spin‑up and teardown.

## Quickstart
### Prerequisites
- Docker 23+
- Docker Compose v2
- GNU Make

### Commands
```bash
cp .env.example .env
# Edit .env and set at least:
# LAB_PASSWORD=...  (required)

make up
```

### Verify it worked
1) **Containers are running**:
```bash
docker ps --filter "name=lab_" --format "table {{.Names}}\t{{.Status}}"
```
Expected containers: `lab_router`, `lab_server`, `lab_compromised`.

2) **Connectivity across subnets** (from compromised → server):
```bash
docker exec lab_compromised ping -c 1 172.31.0.10
docker exec lab_compromised curl -sf http://172.31.0.10:80 >/dev/null && echo "HTTP OK"
```

3) **PCAPs are being written**:
```bash
RUN_ID=$(cat outputs/.current_run)
ls -1 outputs/$RUN_ID/pcaps | head
```
Expected: `router_YYYY-MM-DD_HH-MM-SS.pcap` files and `server.pcap`.

Tear down:
```bash
make down
```

## Where outputs go
`make up` creates a run-scoped output tree:
```
outputs/
└── <RUN_ID>/
    ├── pcaps/
    ├── slips/
    ├── aracne/
    ├── coder56/
    └── benign_agent/
```

## Safety model
- **Lab‑only**: This repo is intended for isolated, local experimentation.
- **Privileged containers**: `lab_router` and `lab_server` run privileged and use `NET_ADMIN`.
- **Host‑network defender**: the defender container uses `network_mode: host` (port configurable via `DEFENDER_PORT`).
- **No production targets**: do not point agents at real systems or networks.
- **Credentials are defaults**: see `guide/credentials.md` and override via `.env`.

## Docs
Start here: `guide/index.md`
- Architecture: `guide/architecture.md`
- Agents: `guide/agents.md`
- Topologies: `guide/topologies.md`
- Credentials: `guide/credentials.md`

## License
See `LICENSE`.
