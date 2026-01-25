# SLIPS Defender

Automated network intrusion detection and response system using SLIPS IDS with AI-driven remediation.

## Architecture

```
┌─────────────────┐      ┌──────────────┐      ┌──────────────┐
│  Network Traffic │ ──> │   SLIPS IDS  │ ──> │  Alert API   │
│  (PCAP files)   │      │  (Zeek + ML) │      │  (/alerts)   │
└─────────────────┘      └──────────────┘      └──────┬───────┘
                                                       │
                                                       ▼
                                              ┌──────────────┐
                                              │   Alert DB   │
                                              │   (.ndjson)  │
                                              └──────┬───────┘
                                                     │
                       ┌─────────────────────────────┼───────────────────┐
                       │                             │                   │
                       ▼                             ▼                   ▼
              ┌──────────────┐            ┌──────────────┐    ┌──────────────┐
              │    Watcher   │            │   Forwarder  │    │AutoResponder │
              │ (PCAP monitor)│            │ (SLIPS log)  │    │ (LLM planner)│
              └──────────────┘            └──────────────┘    └──────┬───────┘
                  │                                                              │
                  ▼                                                              ▼
           ┌──────────────┐                                            ┌──────────────┐
           │  SLIPS       │                                            │  SSH/OpenCode│
           │  Processing  │                                            │  Execution   │
           └──────────────┘                                            └──────────────┘
```

## Components

### Core Services

**SLIPS IDS** (`stratosphereips/slips:latest`)
- Network traffic analysis using Zeek logs
- Machine learning-based threat detection
- Evidence generation and scoring

**Defender API** (`defender_api.py:8000`)
- `/alerts` - Receives alerts from SLIPS
- `/plan` - Generates remediation plans via LLM
- `/health` - Health check endpoint

**AutoResponder** (`auto_responder.py`)
- Monitors alert stream for high/critical threats
- Deduplicates alerts (source → target → attack type)
- Calls LLM planner for each new threat
- Executes remediation via SSH/OpenCode

### Supporting Services

**Watcher** (`watch_pcaps.py`)
- Monitors `/StratosphereLinuxIPS/dataset/` for new PCAP files
- Orchestrates SLIPS processing
- Manages file lifecycle and timeouts

**Forwarder** (`forward_alerts.py`)
- Tails SLIPS `alerts.log` files
- Normalizes and forwards to Defender API

## Data Flow

1. **Ingest**: Network traffic captured as PCAP files
2. **Detect**: SLIPS analyzes traffic, generates alerts
3. **Collect**: Forwarder and Watcher aggregate alerts
4. **Filter**: AutoResponder processes only HIGH/CRITICAL threats
5. **Plan**: LLM generates host-specific remediation plans
6. **Execute**: OpenCode executes plans on target hosts via SSH

## Configuration

Environment variables (see `.env` or `docker-compose.yml`):

```bash
RUN_ID=<experiment_id>          # Experiment identifier
DEFENDER_PORT=8000              # Defender API port
LLM_BASE_URL=<api_url>          # LLM API endpoint
OPENCODE_API_KEY=<key>          # LLM API key
SLIPS_ALERT_INTERVAL=2          # Seconds between alert polls
AUTO_RESPONDER_INTERVAL=5       # Seconds between alert checks
OPENCODE_TIMEOUT=600            # Max execution time (seconds)
```

## SSH Connectivity

The defender establishes SSH key-based authentication to target hosts:

- Server: `172.31.0.10` (victim/protected)
- Compromised: `172.30.0.10` (attacker/investigated)

Keys are generated during container startup via `setup_ssh_keys.sh`.

## Custom SLIPS Modules

Custom detection modules are applied as patches in `patches/`. See individual patch directories for details.

## Output Files

All outputs written to `/outputs/{RUN_ID}/`:

```
outputs/
├── slips/
│   └── defender_alerts.ndjson      # All incoming alerts
├── auto_responder_detailed.log     # AutoResponder activity
├── auto_responder_timeline.jsonl   # Structured event timeline
├── executions.jsonl                # OpenCode execution results
└── processed_alerts.json           # Duplicate detection state
```

## Testing

See `defender/README.md` for manual attack simulation commands.

Common attacks to test detection:
- Port scanning (nmap)
- SSH brute force (hydra)
- HTTP password guessing (curl)
- DoS attacks (hping3)

Monitor response in real-time:
```bash
tail -f /outputs/{RUN_ID}/auto_responder_detailed.log
```

## References

- [SLIPS Documentation](https://stratospherelinuxips.readthedocs.io/)
- [OpenCode](https://github.com/sisl/OpenCode)
- Trident Lab Architecture: See project root README
