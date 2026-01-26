# Trident Agents

Agents are optional. The lab can run without any agent for pure traffic capture.

## IPs used in the lab
- `lab_compromised`: 172.30.0.10 (lab_net_a)
- `lab_server`: 172.31.0.10 (lab_net_b)
- `lab_router`: 172.30.0.1 / 172.31.0.1

## Defender (SLIPS + Auto‑Responder)
- **Purpose**: Detects malicious activity from router PCAPs and can execute remediation plans.
- **Where it runs**: `lab_slips_defender` container on host network (no container IP). It runs SLIPS + planner and sends a prompt to OpenCode on `lab_server` for execution.
- **Inputs**: `outputs/<RUN_ID>/pcaps/` mounted as the SLIPS dataset.
- **Outputs**: `outputs/<RUN_ID>/slips/` (alerts, logs, NDJSON).

Start:
```bash
make defend
```

## Attacker (ARACNE)
- **Purpose**: Goal‑driven offensive agent for repeatable attack workflows.
- **Where it runs**: `lab_aracne_attacker` container (on `lab_net_a`) and connects via SSH to `lab_compromised`.
- **Inputs**: Goal text passed via `GOAL=...`.
- **Outputs**: `outputs/<RUN_ID>/aracne/` (agent logs + snapshots).

Start:
```bash
GOAL="Scan 172.31.0.0/24" make aracne_attack
```

## Attacker (coder56)
- **Purpose**: Simple attacker runner that uses OpenCode prompts for offensive tasks.
- **Where it runs**: Host-side runner that executes OpenCode inside `lab_compromised`.
- **Inputs**: Goal text passed to `make coder56`.
- **Outputs**: `outputs/<RUN_ID>/coder56/`.

Start:
```bash
make coder56 "Run an SSH brute-force attempt against 172.30.0.10"
```

## Benign (db_admin)
- **Purpose**: Generates safe, routine activity to mimic normal operations.
- **Where it runs**: Host-side runner that executes OpenCode inside `lab_compromised`.
- **Outputs**: `outputs/<RUN_ID>/benign_agent/`.

Start:
```bash
make benign "Perform morning database checks"
```

## Notes
- Agents are independent; you can run only what you need.
- All agent artifacts are grouped by `RUN_ID` for reproducibility.
