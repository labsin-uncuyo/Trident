# ARACNE attacker (lab wrapper)

This repository tracks ARACNE as a submodule (`external/aracne`) without our lab-specific settings. Use this wrapper to run the attacker inside the Trident lab.

## Layout
- `configs/aracne_lab/.env` — lab defaults (SSH target, CESNET/OpenAI placeholders, Ollama host/port). Fill in API keys at runtime; do not commit secrets.
- `configs/aracne_lab/config/AttackConfig_lab.yaml` — lab attack config, references env vars for the compromised host and LLM providers.
- `configs/aracne_lab/start_lab.sh` — launcher used by the `aracne_attacker` container (password SSH, env expansion, calls `aracne.py`).

## How to run
```bash
# bring up core + defender
make up

# run an attack with a goal
GOAL="Run a noisy nmap scan against 172.31.0.10" make aracne_attack
```

## Auth
- SSH uses password auth to the compromised host (`adminadmin` by default). No SSH key is mounted into the attacker.

## Logs
- ARACNE logs live under `outputs/<RUN_ID>/aracne/` (`agent.log`, `context.log`, `experiments/...`).
- SLIPS logs live under `outputs/<RUN_ID>/slips/` (per-PCAP `alerts.log/json` and `slips/defender_alerts.ndjson`).

## Notes
- Keep `external/aracne` as a clean submodule; do not commit lab-specific config or keys into it.
- If you need different models/providers, edit `configs/aracne_lab/config/AttackConfig_lab.yaml` or override via env vars.***
