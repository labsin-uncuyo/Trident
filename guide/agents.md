# Agents

Agents are optional components that generate, detect, or monitor network
activity inside the lab. The core infrastructure (`make up`) works on its own
for pure traffic capture — you only start agents when you need automated
attack simulation, defense, or benign background noise.

The typical experiment runs three agent types simultaneously:

- **Attacker** (coder56) — executes commands on the compromised host to probe and exploit the server.
- **Defender** (SLIPS + auto-responder) — reads router PCAPs in near-real-time, detects threats, and SSHes into lab hosts to apply remediation.
- **Benign** (db_admin) — generates realistic background traffic (SQL queries, web requests, sleep cycles) to give the IDS a mixed-signal environment and test for false positives.

Running all three together is the design intent: the interesting research questions are about how the defender distinguishes attack from benign traffic, whether the attacker can detect and evade active defenses, and what emergent interactions arise when both agents reason about the same network simultaneously.

## IPs used in the lab

| Host | IP | Network |
|---|---|---|
| `lab_compromised` | 172.30.0.10 | lab_net_a |
| `lab_router` | 172.30.0.1 / 172.31.0.1 | lab_net_a + lab_net_b |
| `lab_server` | 172.31.0.10 | lab_net_b |
| `lab_slips_defender` | 172.30.0.30 / 172.31.0.30 | lab_net_a + lab_net_b |
| `lab_dashboard` | (dashboard_net) | lab_dashboard_net |

---

## Defender (SLIPS + Auto-Responder)

IDS that reads rotating PCAPs from the router and generates alerts. The
companion auto-responder can SSH into lab hosts to execute remediation plans.

### Where it runs

`lab_slips_defender` container on `lab_net_a` (172.30.0.30) and `lab_net_b`
(172.31.0.30), plus `lab_egress` for outbound connectivity.

### Start / stop

```bash
make defend          # build (if needed), start defender, provision SSH keys
make not_defend      # stop defender container (does not remove it)
```

`make defend` automatically runs `scripts/setup_ssh_keys_host.sh` to inject
the auto-responder SSH public key into `lab_server` and `lab_compromised`.
You can re-run key provisioning independently with `make ssh_keys`.

### Output files (`outputs/<RUN_ID>/slips/`)

| File / folder | Content |
|---|---|
| `alerts.json` | SLIPS JSON alert summary |
| `alerts.log` | Human-readable SLIPS alert output |
| `defender_alerts.ndjson` | Each line: one SLIPS alert as processed by auto-responder |
| `watcher_events/` | Records which PCAP files triggered auto-responder invocations |

### Prerequisites / env vars

| Variable | Default | Notes |
|---|---|---|
| `DEFENDER_PORT` | 8000 | Host port the defender health endpoint binds to; must be free |
| `PLANNER_PORT` | 1654 | Internal planner gRPC port |
| `OPENAI_API_KEY` | -- | Required for the LLM planner |
| `OPENCODE_API_KEY` | -- | Required for auto-responder remediation |
| `LLM_MODEL` | gpt-4o-mini | Model used by the incident planner |
| `LAB_PASSWORD` | -- | SSH password for lab hosts |

### Gotchas

- `DEFENDER_PORT` (default 8000) must be free on the host before starting.
- The defender depends on the router being healthy. If the router is not
  running, `make defend` will start it automatically.
- SLIPS reads PCAPs from `outputs/<RUN_ID>/pcaps/`. If no PCAPs exist yet
  (e.g., no traffic has flowed), SLIPS will wait until files appear.

---

## coder56 (OpenCode attacker)

Host-side script that launches OpenCode inside `lab_compromised` as the
`labuser` user with the `coder56` agent persona. The agent receives a goal
and autonomously executes commands to achieve it.

### Where it runs

On the host, via `docker exec` into the `lab_compromised` container.

### Start / stop

```bash
make coder56 "Run an nmap scan against 172.31.0.10"
```

The process runs in the background (`nohup`). The PID is printed to stdout.
To stop it, kill the PID or the underlying `docker exec` process.

### Output files (`outputs/<RUN_ID>/coder56/`)

| File | Content |
|---|---|
| `auto_responder_timeline.jsonl` | Structured JSONL timeline: init, OpenCode events, completion or errors |
| `opencode_stdout_<exec_id>.jsonl` | Raw JSON event stream from `opencode run` |
| `opencode_stderr_<exec_id>.log` | Stderr from the OpenCode process |
| `opencode_api_messages.json` | Structured API-style message export for dashboard consumption |

### Prerequisites / env vars

| Variable | Default | Notes |
|---|---|---|
| `OPENCODE_API_KEY` | -- | Required; passed into `lab_compromised` |
| `OPENAI_API_KEY` | -- | Required; used by the LLM backend |
| `OPENCODE_TIMEOUT` | 600 | Seconds before the run is forcibly terminated |
| `OPENCODE_MODE` | run | `run` (headless JSON) or `tui` (interactive, requires pexpect) |

### Gotchas

- coder56 runs in the background via `nohup`. Check the printed PID to
  monitor or kill it.
- Default timeout is 600 seconds (`OPENCODE_TIMEOUT`). The `.env.example`
  ships with 450; the defender compose service defaults to 1200. Set the
  value appropriate to your goal complexity.
- Start benign traffic before coder56 to avoid OpenCode session race
  conditions on the compromised host.

---

## Benign (db_admin)

Generates realistic, non-malicious database administration traffic. The agent
connects to `lab_server` via `lab_compromised`, runs SQL queries, does web
research, and sleeps between tasks to simulate a human operator.

### Where it runs

A temporary container (using the `lab/dashboard` image) on `lab_net_a`. It
calls the OpenCode HTTP API on `lab_compromised` to start a `db_admin` session.

### Start / stop

```bash
# Default goal (indefinite workday simulation), no time limit
make benign

# Custom goal with a 15-minute time limit
make benign GOAL="Check replication status and vacuum the analytics table" TIME_LIMIT=900
```

The benign agent runs in the **foreground**. Press Ctrl-C to stop it.

### Output files (`outputs/<RUN_ID>/benign_agent/`)

Output structure depends on the OpenCode session. Typical files include
session logs and API message exports written by the db_admin client.

### Prerequisites / env vars

| Variable | Default | Notes |
|---|---|---|
| `OPENCODE_API_KEY` | -- | Required; used by the OpenCode server on `lab_compromised` |
| `GOAL` | (built-in default) | Optional custom goal text |
| `TIME_LIMIT` | (none) | Optional; seconds before the agent stops gracefully |

### Gotchas

- Runs in the foreground. Use a separate terminal or `tmux` session.
- Start benign before coder56 to avoid OpenCode session race conditions.
- If no `GOAL` is provided, the agent runs an indefinite workday loop with
  randomized sleep intervals (60-130 seconds between tasks).

---

## Dashboard

Web UI for monitoring runs, viewing alerts, browsing PCAPs, inspecting
container state, and replaying agent timelines.

### Where it runs

`lab_dashboard` container on `lab_dashboard_net`. Exposed on host port 8888,
serving at `http://localhost:8888`.

### Start / stop

```bash
make dashboard       # build and start (or recreate) the dashboard
```

Stop it with `make down` (stops everything) or
`docker stop lab_dashboard`.

### Output files

The dashboard does not produce output files. It reads from `outputs/` and
the Docker socket.

### Prerequisites / env vars

No agent-specific env vars are required. The dashboard mounts:

- `./outputs` (read-only) -- to display run artifacts
- `/var/run/docker.sock` (read-only) -- to list and inspect containers

### Gotchas

- The compose file maps container port 8080 to host port **8888**
  (`"8888:8080"`). Access the dashboard at `http://localhost:8888`.
- The Docker socket mount is read-only; the dashboard cannot modify
  containers.
- The dashboard depends on all three core containers (router, server,
  compromised) being healthy before it starts.

---

## Compromised host tooling

The `lab_compromised` container comes pre-installed with common penetration
testing and administration tools:

- **Network**: nmap, netcat-openbsd, socat, curl
- **Brute-force**: hydra, sshpass
- **Development**: git, Python 3 with pip
- **Database**: PostgreSQL client (psql)
- **Wordlists**: `/usr/share/wordlists/rockyou.txt`

---

## Sample scenario

```bash
# 1) Bring up core infrastructure
make up

# 2) Start the dashboard (optional, for live monitoring)
make dashboard

# 3) Start the defender (optional, for IDS alerts)
make defend

# 4) Generate benign background traffic (foreground -- use a separate terminal)
make benign

# 5) In another terminal, launch an attacker
make coder56 "Enumerate services on 172.31.0.10 and attempt credential stuffing"
```

All agent artifacts are grouped under `outputs/<RUN_ID>/` for reproducibility
and post-experiment analysis.
