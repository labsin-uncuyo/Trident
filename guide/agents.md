# Agents

Agents are optional. The lab can run without any agent for pure traffic capture.

## IPs used in the lab
- `lab_compromised`: 172.30.0.10 (lab_net_a)
- `lab_server`: 172.31.0.10 (lab_net_b)
- `lab_router`: 172.30.0.1 / 172.31.0.1

## Defender (SLIPS + Auto‑Responder)
- **Purpose**: Detects malicious activity from router PCAPs and can execute remediation plans.
- **Where it runs**: `lab_slips_defender` container on **host network** (no container IP).
- **Inputs**: `outputs/<RUN_ID>/pcaps/` mounted as the SLIPS dataset.
- **Outputs**: `outputs/<RUN_ID>/slips/` (alerts, logs, NDJSON).
- **Access**: SSH key-based access to `lab_compromised` and `lab_server` is configured by the defender on startup.

Start:
```bash
make defend
```

## Attacker (ARACNE)
- **Purpose**: Goal‑driven offensive workflows against the lab.
- **Where it runs**: `lab_aracne_attacker` container (on `lab_net_b`) and connects via SSH to `lab_compromised`.
- **Inputs**: Goal text passed via `make aracne "<goal>"`.
- **Outputs**: `outputs/<RUN_ID>/aracne/` (agent logs + snapshots).

Start:
```bash
make aracne "Scan 172.31.0.0/24"
```

## Attacker (coder56)
- **Purpose**: Host-side runner that executes OpenCode inside `lab_compromised`.
- **Where it runs**: On the host, via `docker exec`.
- **Inputs**: Goal text passed to `make coder56`.
- **Outputs**: `outputs/<RUN_ID>/coder56/`.

Start:
```bash
make coder56 "Run an SSH brute-force attempt against 172.31.0.10"
```

## Benign (db_admin)
- **Purpose**: Generates safe, routine activity to mimic normal operations.
- **Where it runs**: Host-side runner that executes OpenCode inside `lab_compromised`.
- **Outputs**: `outputs/<RUN_ID>/benign_agent/`.

Start:
```bash
make benign "Perform morning database checks"
```

## Sample scenario
```bash
# 1) Bring up infra
make up

# 2) Start defender (optional but useful for alerts)
make defend

# 3) Generate benign traffic
make benign "Verify the web app is reachable and query the database"

# 4) Run an attacker goal
make coder56 "Run a nmap scan against 172.31.0.10"
```

## Notes
- Agents are independent; you can run only what you need.
- All agent artifacts are grouped by `RUN_ID` for reproducibility.
- For ARACNE settings (providers, models, SSH auth), see `configs/aracne_lab/README.md`.
