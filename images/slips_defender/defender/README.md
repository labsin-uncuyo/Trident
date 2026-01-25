# AutoResponder

AI-driven automated incident response orchestrator. Translates SLIPS IDS alerts into executed remediation actions.

## Architecture

```
┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│ defender_alerts  │────▶│  LLM Planner │────▶│  SSH/OpenCode│
│    .ndjson       │     │    (/plan)   │     │   Execution  │
└──────────────────┘     └──────────────┘     └──────────────┘
        ▲                                            │
        │                                            ▼
┌──────────────────┐                         ┌──────────────┐
│   Deduplication  │                         │   Target     │
│   (memory)       │                         │   Hosts      │
└──────────────────┘                         └──────────────┘
```

## Processing Flow

1. **Monitor**: Polls `defender_alerts.ndjson` for new alerts
2. **Filter**: Processes only HIGH/CRITICAL threat levels
3. **Deduplicate**: Tracks `{source_ip}→{dest_ip}→{attack_id}` combinations
4. **Plan**: Requests LLM-generated remediation plan for target IP
5. **Execute**: Runs plan via SSH using OpenCode
6. **Track**: Logs all actions to timeline and execution files

## Configuration

Environment variables:

```bash
PLANNER_URL=http://127.0.0.1:8000/plan      # Planner endpoint
OPENCODE_TIMEOUT=600                         # Max execution (seconds)
AUTO_RESPONDER_INTERVAL=5                    # Poll interval (seconds)
DUPLICATE_DETECTION_WINDOW=300               # Dedup window (seconds)
MAX_EXECUTION_RETRIES=3                      # Retry attempts
```

SSH targets:
- **Server**: `172.31.0.10` (victim/protected systems)
- **Compromised**: `172.30.0.10` (attacker/investigated systems)

Key authentication via `/root/.ssh/id_rsa_auto_responder`

## Alert Filtering

**Processed**:
- Threat level: `high` or `critical`
- Not recently seen (within deduplication window)

**Skipped**:
- Low/medium threat levels
- Heartbeat and system messages
- Duplicate alert combinations

## Multi-Alert Mode

When `pexpect` is available, the AutoResponder can:
- Pool alerts within a time window (default: 10s)
- Execute multiple remediation actions in a single SSH session
- Reduce connection overhead for rapid attacks

Configuration:
```bash
ENABLE_MULTI_ALERT=true
ALERT_POOL_WINDOW=10
MULTI_ALERT_DELAY=0.5
```

## Output Files

Written to `/outputs/{RUN_ID}/`:

- **auto_responder_detailed.log** - Timestamped activity log
- **auto_responder_timeline.jsonl** - Structured event timeline
- **executions.jsonl** - OpenCode execution results with I/O
- **processed_alerts.json** - Duplicate detection state

## Testing

### Manual Attack Simulation

From the compromised container (`172.30.0.1`), run attacks against the server (`172.31.0.10`):

**Port Scan**:
```bash
nmap -sS -p 22,80,443 172.31.0.10
```

**SSH Brute Force**:
```bash
hydra -l root -P /usr/share/wordlists/rockyou.txt ssh://172.31.0.10
```

**HTTP Flood**:
```bash
for i in {1..50}; do curl -s http://172.31.0.10/ & done; wait
```

### Monitor Response

```bash
# Watch alerts being processed
tail -f /outputs/{RUN_ID}/slips/defender_alerts.ndjson

# Watch AutoResponder activity
tail -f /outputs/{RUN_ID}/auto_responder_detailed.log

# Watch executions
tail -f /outputs/{RUN_ID}/executions.jsonl
```

## Dependencies

Python requirements in `requirements.txt`:
- `requests` - HTTP client for planner API
- `pexpect` - Multi-alert SSH session support (optional)

## Failure Handling

- **SSH failures**: Logged, retry up to `MAX_EXECUTION_RETRIES`
- **Planner timeouts**: Returns HTTP 504, alert remains in queue
- **Execution failures**: Logged to `executions.jsonl` with error details
- **Duplicate alerts**: Silently skipped to prevent redundant actions
