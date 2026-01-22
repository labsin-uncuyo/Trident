# Research Cyber Lab Phase 1

This phase-1 lab now focuses on a tiny, fully routed environment that still exposes enough moving pieces to exercise IDS/IPS workflows. A privileged router stitches together two /24 networks, and a combined SLIPS + FastAPI defender ingests PCAPs from disk and writes alerts under `outputs/<RUN_ID>/slips/`.

## Pre-reqs
- Docker 23+
- docker-compose v2 (compose-spec 3.8 support)
- Python 3.10
- GNU Make

## Quick start
```bash
cp .env.example .env
# optionally tweak RUN_ID / DEFENDER_PORT / LAB_PASSWORD / OPENCODE_API_KEY
python3 -m pip install -r requirements.txt
make build
make up          # core only (router, server, compromised)
make defend      # start defender components (slips_defender)
# start other roles when needed
# make ghosts_psql   # benign workload
# make aracne_attack # attacker
# wait for core/defender containers to become healthy (~30s)
make verify
# inspect artifacts
ls outputs/${RUN_ID}/
# tear down
make down
```

Use `make COMPOSE=docker-compose up` if you rely on the legacy binary. Point `PYTHON` at a venv interpreter to run tests inside one, e.g. `make verify PYTHON=.venv/bin/python`.

## Topology & addressing
- **Networks** – `lab_net_a` (172.30.0.0/24) and `lab_net_b` (172.31.0.0/24) are defined in `docker-compose.yml` with static IPAM so no extra scripts are required.
- **router (lab_router)** – privileged, bound to 172.30.0.1/172.31.0.1, enables IP forwarding, captures routed traffic to `/outputs/<RUN_ID>/pcaps/router_*.pcap`, and exposes `/management.sh` for `block_ip`, `unblock_ip`, and `rotate_pcaps`. Router also forwards DNS so lookups appear in PCAPs.
- **slips_defender (lab_slips_defender)** – now runs the official `stratosphereips/slips:latest` container in host-network mode. Helper scripts under `images/slips_defender/` keep our FastAPI endpoint (127.0.0.1:${DEFENDER_PORT}) alive, watch `/outputs/<RUN_ID>/pcaps` for rotated captures, invoke `slips.py -f dataset/<file>.pcap`, and forward the resulting alerts to FastAPI so they land in `/outputs/<RUN_ID>/defender_alerts.ndjson`.
- **compromised (lab_compromised)** – 172.30.0.10 with SSH reachable via router port-forwarding, includes enhanced tooling, GHOSTS framework, OpenCode, and routes all traffic (including default) via the router. DNS is configured to use the router so lookups are visible in router PCAPs.
- **server (lab_server)** – 172.31.0.10 with nginx and PostgreSQL reachable via router port-forwarding. Postgres boots with a demo `labdb` + `events` table. **OpenCode v1.0.77** is installed and configured with e-INFRA CZ Chat API for AI-assisted operations. Default routing and DNS are via the router so north-south traffic is captured.
  - **Web login test app** – nginx proxies `/login` to a Flask service on port 5000 inside the server container (code in `images/server/flask_app/`). Default credentials are `admin/admin`; override via `.env` (`LOGIN_USER`/`LOGIN_PASSWORD`) and recreate the server container. Logs land in `/var/log/flask-login.log` plus nginx access logs.
  - **PostgreSQL auth** – remote access requires password auth (`md5`). Default DB creds are `labuser/labpass`, configurable via `.env` (`DB_USER`/`DB_PASSWORD`). SSL stays disabled to keep traffic visible in PCAPs.
 - **ghosts_driver (lab_ghosts_driver)** – benign workload generator; only starts when invoked via `make ghosts_psql`. Default image is built for `linux-arm64`; on amd64 hosts you must rebuild the client (e.g., `dotnet publish -c Release -r linux-x64 --self-contained true -o /opt/ghosts/bin`) or use a multi-arch build to avoid `exec format error`.
- **aracne_attacker (lab_aracne_attacker)** – attacker container on `lab_net_b` that routes through the router to reach `lab_compromised`; only starts when invoked via `make aracne_attack`.

Traffic path: `compromised ↔ router ↔ server`, with default routes pointed at the router so north-south flows traverse it. The authoritative artifacts are the PCAP files under `outputs/<RUN_ID>/pcaps/`, which SLIPS ingests directly.

## Shared components

The lab uses reusable Dockerfile snippets for common functionality:

- **`images/shared/base-packages.dockerfile`** - Common packages, timezone setup, and development tools
- **`images/shared/opencode-install.dockerfile`** - Standardized OpenCode installation

Both `server` and `compromised` containers reference these shared components, ensuring consistent environments and simplified maintenance.

## Artifacts & operations
- Every container mounts `./outputs` to `/outputs`, and everything is scoped under `/outputs/<RUN_ID>/`. See `outputs/README.md` for the current map.
- PCAPs: `router_*.pcap` accumulates under `outputs/<RUN_ID>/pcaps/`. Router and defender images ship logrotate configs plus `/management.sh rotate_pcaps` for forced rotations.
- Alerts: `lab_slips_defender` appends JSON lines to `outputs/<RUN_ID>/slips/defender_alerts.ndjson` and writes per-PCAP `alerts.log`/`alerts.json` under `outputs/<RUN_ID>/slips/<pcap>_<timestamp>/`. Drop a new PCAP into `outputs/${RUN_ID}/pcaps/` to trigger processing.
- ARACNE attacker: logs to `outputs/<RUN_ID>/aracne/agent.log` (remote shell transcript) and `context.log` (LLM traces). Each session is snapshotted under `aracne/experiments/<timestamp_goal>/` for reproducibility.
- Viewing SLIPS logs: every time SLIPS processes a PCAP it writes into `outputs/${RUN_ID}/slips/<timestamp>/alerts.log`. Tail them on the host (`tail -f outputs/${RUN_ID}/slips/*/alerts.log`) or inside the container (`docker exec lab_slips_defender tail -f /StratosphereLinuxIPS/output/*/alerts.log`). Those same alert lines are forwarded to FastAPI and mirrored in `outputs/${RUN_ID}/slips/defender_alerts.ndjson`.

- Router ACL helpers:

  ```bash
  docker exec lab_router /management.sh block_ip 172.30.0.10
  docker exec lab_router /management.sh unblock_ip 172.30.0.10
  docker exec lab_router /management.sh rotate_pcaps
  ```

## Running the ARACNE attacker
- The attacker container is not started by `make up`; it only runs when invoked.
- To launch an attack: set a goal and run `make aracne_attack`, e.g.:
  ```bash
  export GOAL="Run a noisy nmap scan against 172.31.0.10 and save output"
  make aracne_attack
  ```
- ARACNE logs land in `outputs/<RUN_ID>/aracne/` (`agent.log`, `context.log`, per-session snapshots under `experiments/`). SLIPS artifacts continue to flow into `outputs/<RUN_ID>/slips/`.
- SSH auth for the attacker uses password access (`adminadmin`) to the compromised host; no SSH key is required. If you need to test connectivity from the host, use `scripts/test_aracne_ssh.sh`.
- Bringing it back down: `make down` (same as the rest of the stack). When not running an attack, the attacker container stays idle.
- The compromised host ships with common tools preinstalled (nmap, hydra, sshpass, netcat-openbsd, socat, curl, git, ripgrep, unzip, PostgreSQL client, Python3/pip, etc.) and includes a small bundled wordlist at `/usr/share/wordlists/rockyou.txt` for quick SSH brute-force experiments. `labuser` is configured for passwordless sudo to enable privileged actions when needed.

## SLIPS mode (official image, PCAP ingestion)
1. **Router capture** – `lab_router` runs tcpdump and logrotate inside the container, writing rolling PCAPs to `outputs/<RUN_ID>/pcaps/` on the host. Use `/management.sh rotate_pcaps` whenever you want a fresh on-disk artifact.
2. **Shared dataset** – The defender service mounts `./outputs/${RUN_ID}/pcaps` as `/StratosphereLinuxIPS/dataset` and `./outputs/${RUN_ID}/slips` as `/StratosphereLinuxIPS/output`. `make up` pre-creates both directories (or create them manually if you change `RUN_ID`).
3. **Official SLIPS** – `lab_slips_defender` uses `stratosphereips/slips:latest` with host networking and NET_ADMIN. A lightweight watcher (`watch_pcaps.py`) polls the dataset directory, skips active capture files, and calls `python3 /StratosphereLinuxIPS/slips.py -f dataset/<file>.pcap` for each rotated file it discovers.
4. **Alert fan-out** – SLIPS writes its logs (including `alerts.log`) under `/StratosphereLinuxIPS/output/<timestamp>/`. `forward_alerts.py` tails every discovered `alerts.log` and POSTs the JSON lines to the built-in FastAPI endpoint at `http://127.0.0.1:${DEFENDER_PORT}/alerts`.
5. **FastAPI persistence** – `defender_api.py` is the same FastAPI/uvicorn app as before; it responds to `/health` and appends alert JSON to `outputs/<RUN_ID>/slips/defender_alerts.ndjson` when `/alerts` receives a POST. Tests watch both the SLIPS output tree and this NDJSON file to confirm end-to-end delivery.

To enable SLIPS active blocking later, tweak `/opt/lab/watch_pcaps.py` (or override via an env var) to call `python3 /StratosphereLinuxIPS/slips.py -f dataset/<file>.pcap -p`; the container already runs with `NET_ADMIN`, so the capability is in place.

## Access checklist
- Host access now goes through the router IPs (no direct port mappings).
- Compromised host: `ssh labuser@172.30.0.1` (password from `.env`).
- Server services: `http://172.31.0.1:80/` and `PGPASSWORD=labpass psql -h 172.31.0.1 -p 5432 -U labuser labdb`.
- DB auth smoke test (from host via compromised): `docker exec lab_compromised bash -lc 'PGPASSWORD=labpass psql -h 172.31.0.10 -U labuser -d labdb -c "SELECT current_user;"'`
- Defender health: `docker exec lab_slips_defender curl -fsS http://127.0.0.1:${DEFENDER_PORT}/health`.
- OpenCode AI: Use the helper script `./opencode.sh "your prompt"` or directly `docker exec lab_server opencode run "your prompt"`.

When finished, `make down` removes the stack and frees both custom networks.

## OpenCode AI Integration

The server container includes **OpenCode v1.0.77** with e-INFRA CZ Chat API integration for AI-assisted operations.

### Configuration

OpenCode is pre-configured with:
- **Provider**: e-INFRA CZ Chat API (`https://chat.ai.e-infra.cz/api/v1`)
- **Model**: Qwen3 Coder (32K context, 8K output)
- **API Key**: Loaded from `OPENCODE_API_KEY` in `.env` file
- **Data Persistence**: OpenCode session data persists in Docker volume `opencode_data`

### Usage

**Option 1: Using the helper script (recommended)**
```bash
./opencode.sh "list all files here"
./opencode.sh "analyze the nginx logs"
./opencode.sh "check database tables"
```

**Option 2: Direct docker exec**
```bash
# In server container
docker exec lab_server opencode run "list all files here"
docker exec lab_server opencode run "explain the index.html file"

# In compromised container
docker exec lab_compromised opencode run "list files here"

# Use a custom system prompt with the soc_god agent
sudo docker exec lab_server opencode run --agent soc_god "your prompt"
```

**Option 3: Interactive mode**
```bash
docker exec -it lab_server opencode
# or
docker exec -it lab_compromised opencode
# Then interact with OpenCode TUI
```

### OpenCode Commands

Available commands inside the container:
```bash
opencode run [message]     # Run with a message (non-interactive)
opencode [project]         # Start interactive TUI
opencode models            # List available models
opencode auth              # Manage credentials
opencode stats             # Show token usage
opencode --help            # Full command list
```

### Configuration Files

- **OpenCode config**: `/root/.config/opencode/opencode.json`
- **Authentication**: `/root/.local/share/opencode/auth.json` (auto-generated from env)
- **Data directory**: `/root/.opencode/` (persisted via Docker volume)

### Verification

Test the installation:
```bash
# Quick test (server)
./opencode.sh "say hello"

# Quick test (compromised)
docker exec lab_compromised opencode run "list files here"

# List files in web directory
docker exec lab_server bash -c 'cd /var/www/html && opencode run "list all files here"'

# Check OpenCode version
docker exec lab_server opencode --help

# Create a file with OpenCode
./opencode.sh "create a file called test.txt with the text 'Hello from OpenCode'"

# Read the file back
docker exec lab_server cat test.txt
```

**Complete Test Example:**
```bash
# Have OpenCode create and describe a file
./opencode.sh "create a file called ufw_description.txt with a short one-sentence description of what ufw is"
docker exec lab_server cat ufw_description.txt
# Output: UFW (Uncomplicated Firewall) is a user-friendly interface for managing iptables firewall rules on Linux systems.

# Have OpenCode read and explain the file
./opencode.sh "read the ufw_description.txt file and tell me what it says in your own words"
# OpenCode will read the file and provide a paraphrased explanation
```

### Troubleshooting

**Check API connection:**
```bash
docker exec lab_server bash -c 'curl -H "Authorization: Bearer $OPENCODE_API_KEY" https://chat.ai.e-infra.cz/api/v1/models | head -50'
```

**View configuration:**
```bash
docker exec lab_server cat /root/.config/opencode/opencode.json
docker exec lab_server cat /root/.local/share/opencode/auth.json
```

**Check logs:**
```bash
docker exec lab_server ls -la /root/.local/share/opencode/
docker logs lab_server
```

### Security Notes

- API key is injected from environment variables (never committed to code)
- Authentication file is generated at container startup
- OpenCode data persists across container restarts via named volume
- All OpenCode operations run as root inside the container (isolated from host)
