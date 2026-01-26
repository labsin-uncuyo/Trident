# Trident Lab

Trident is a compact, fully routed Docker lab for testing cyber agents and IDS/IPS workflows in a reproducible network. The lab emulates a small enterprise segment with a router, a compromised host, and a server. All traffic crosses the router so you always get clean PCAPs for detection, response, and evaluation.

At a high level, Trident lets you:
- Spin up a fixed‑IP lab where traffic is routed and captured by design.
- Run optional agents (defender, attacker, benign) against the same environment.
- Collect artifacts in one place (`outputs/<RUN_ID>/`) for repeatable experiments.

## What agents are supported
Trident supports three optional agent roles. These are the agents designed by this project so you can test the infrastructure with real workflows, but they are not the only agents you can run in the lab. The core infrastructure runs without any agent.

- **Defender**: SLIPS IDS + Auto‑Responder. Ingests router PCAPs and can execute OpenCode remediation.
- **Attacker (ARACNE)**: Goal‑driven offensive workflows against the lab.
- **Attacker (coder56)**: Lightweight attacker runner that uses OpenCode prompts for offensive tasks.
- **Benign**: db_admin agent that runs safe maintenance‑style actions to generate normal activity.

Details are in `./AGENTS.md`.

## Requirements
- Docker 23+
- docker-compose v2 (compose-spec 3.8 support)
- Python 3.10
- GNU Make

## Setup (infrastructure only)
```bash
cp .env.example .env
# Required for infrastructure:
# - LAB_PASSWORD
# - RUN_ID
# - DEFENDER_PORT

python3 -m pip install -r requirements.txt
make build
make up
```

Tear down:
```bash
make down
```

## Default credentials
- **Compromised host (SSH)**: `labuser` / `LAB_PASSWORD` (default `adminadmin` in `.env.example`)
- **Server (SSH)**: `root` / `admin123`
- **Web login app**: `admin` / `admin` (`LOGIN_USER` / `LOGIN_PASSWORD`)
- **PostgreSQL**: `labuser` / `labpass` (`DB_USER` / `DB_PASSWORD`)

## Infrastructure overview (big picture)
- Two Docker networks with static subnets:
  - `lab_net_a` (172.30.0.0/24) for the compromised side
  - `lab_net_b` (172.31.0.0/24) for the server side
- A privileged **router** connects both networks and captures traffic to `outputs/<RUN_ID>/pcaps/`.
- **lab_compromised** (172.30.0.10) is the client/compromised host.
- **lab_server** (172.31.0.10) runs nginx + PostgreSQL.

Traffic path is always:
`lab_compromised ↔ lab_router ↔ lab_server`

This guarantees all north–south flows are observable in the router PCAPs. Router PCAPs are the only always‑on artifact. Agent logs are created only for the agents you run; new agents must define their own log outputs.

## Where to read next
- **Infrastructure details**: `./INFRASTRUCTURE.md`
- **Agents and workflows**: `./AGENTS.md`
