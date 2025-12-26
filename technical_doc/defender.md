# Trident Auto-Responder System

The Auto-Responder is the core autonomous defense component of Trident. It bridges SLIPS IDS alerts with AI-powered remediation through OpenCode execution on target machines.

## Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    NETWORK      │    │     SLIPS       │    │  DEFENDER API   │
│    TRAFFIC      │───▶│     IDS         │───▶│   (port 8000)   │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └────────┬────────┘
                                                       │
                                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AUTO-RESPONDER                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │ Alert       │───▶│ Planner     │───▶│ SSH + OpenCode      │  │
│  │ Parser      │    │ (LLM/Rule)  │    │ Executor            │  │
│  └─────────────┘    └─────────────┘    └──────────┬──────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                                    │
                          ┌─────────────────────────┼─────────────────────────┐
                          ▼                         ▼                         ▼
                   ┌─────────────┐           ┌─────────────┐           ┌─────────────┐
                   │   SERVER    │           │ COMPROMISED │           │   OTHER     │
                   │ 172.31.0.10 │           │ 172.30.0.10 │           │   TARGETS   │
                   │  OpenCode   │           │  OpenCode   │           │             │
                   └─────────────┘           └─────────────┘           └─────────────┘
```

## Data Flow

### 1. Alert Generation (SLIPS → Defender API)

**Source:** SLIPS IDS running on `lab_slips_defender` container

**Process:**
1. SLIPS monitors network interfaces for all container traffic
2. Detects threats based on Stratosphere threat intelligence
3. Writes alerts to `/StratosphereLinuxIPS/output/<run>/alerts.log`
4. `forward_alerts.py` tails this file and POSTs to Defender API

**Alert Format (SLIPS raw):**
```
2024-01-15T10:30:45.123456+0000 (TW 1): Src IP 172.30.0.10. 
Detected Horizontal port scan to port SSH 22/TCP. 
From 172.30.0.10 to 5 unique destination IPs. 
Total packets sent: 25. Confidence: 0.8. threat level: high.
```

**Defender API Storage (`slips/defender_alerts.ndjson`):**
```json
{"raw":"2024-01-15T10:30:45... threat level: high.","run_id":"diego","timestamp":1705312245.123}
```

### 2. Alert Filtering (Auto-Responder)

**File:** `auto_responder.py` → `_is_high_confidence_alert()`

Only processes alerts matching these patterns:
- `confidence: 0.8` or higher
- `threat level: high`
- `vertical port scan` / `horizontal port scan`
- `denial of service` / `ddos`
- `brute force` / `password guessing`

Skips system messages: `heartbeat`, `queued`, `completed`

### 3. Plan Generation

**Built-in Planner (Defender API)**
**File:** `defender_api.py` → `/plan` endpoint on port 8000

The planner is integrated into the Defender API service. When called, it:
- Parses the alert to extract source/destination IPs
- Determines which target machine should execute the remediation
- Generates a structured response plan
- Returns JSON: `{"executor_host_ip": "...", "plan": "..."}`


### 4. SSH Execution

**File:** `auto_responder.py` → `execute_plan_with_opencode()`

**Target Selection:**
- `172.31.0.x` → server (172.31.0.10)
- `172.30.0.x` → compromised (172.30.0.10)

**SSH Command:**
```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /root/.ssh/id_rsa_auto_responder -p 22 \
    root@<target_ip> \
    'export OPENCODE_API_KEY=***
echo "<base64_context>" | base64 -d | opencode run --agent soc_god --'
```

The context is base64-encoded to avoid shell escaping issues with special characters. The `export` ensures the API key is available to the `opencode` child process.

**Retry Logic:**
- 3 attempts max
- Exponential backoff: 10s, 20s, 30s
- 600s timeout per attempt (10 minutes)

### 5. OpenCode Execution

**Config:** `images/server/opencode.json`

**Agent:** `soc_god`
```json
{
  "agent": {
    "soc_god": {
      "model": "e-infra-chat/qwen3-coder",
      "bash": true,
      "edit": true,
      "write": true,
      "permission": {"bash": "allow"},
      "prompt": "SYSTEM_CONTEXT: ISOLATED_CYBER_RANGE..."
    }
  }
}
```

**System Prompt Highlights:**
- Non-conversational, autonomous execution
- Full root access assumed
- Direct command execution (no explanations)
- Error recovery with automatic retries

---

## Timeline Log Format

**File:** `outputs/<run_id>/auto_responder_timeline.jsonl`

Each line is a JSON object with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `ts` | ISO 8601 | Timestamp with timezone |
| `level` | string | Log level (see below) |
| `msg` | string | Human-readable message |
| `alert` | string | First 8 chars of alert hash (optional) |
| `exec` | string | First 8 chars of execution ID (optional) |
| `data` | object | Structured data (optional) |

### Log Levels

| Level | Meaning | Data Fields |
|-------|---------|-------------|
| `INIT` | System startup | `config{}` with settings |
| `ALERT` | New alert detected | `source_ip`, `dest_ip`, `raw`, `full_alert{}` |
| `PLAN` | Plan generated | `executor_ip`, `plan`, `model`, `formatted_alert` |
| `SSH` | SSH execution attempt | `target`, `target_ip`, `command`, `context`, `timeout` |
| `EXEC` | OpenCode result | `status`, `output`, `stderr` |
| `DONE` | Alert completed | `total_duration`, `plan_duration`, `exec_duration`, `status` |
| `ERROR` | Any failure | varies by error type |

### Example Timeline

```jsonl
{"ts":"2025-11-27T15:47:28Z","level":"INIT","msg":"AutoResponder started","data":{"config":{"alert_file":"/outputs/diego/slips/defender_alerts.ndjson","planner_url":"http://127.0.0.1:8000/plan"}}}
{"ts":"2025-11-27T15:48:39Z","level":"ALERT","msg":"New: 172.30.0.10 → 172.31.0.10","alert":"a130b248","exec":"891e75f5","data":{"source_ip":"172.30.0.10","dest_ip":"172.31.0.10","raw":"...threat level: high."}}
{"ts":"2025-11-27T15:48:39Z","level":"PLAN","msg":"Generated for 172.31.0.10 (0.01s)","alert":"a130b248","exec":"891e75f5","data":{"executor_ip":"172.31.0.10","plan":"SECURITY INCIDENT RESPONSE:..."}}
{"ts":"2025-11-27T15:48:40Z","level":"SSH","msg":"→ server@172.31.0.10 (attempt 1/3)","alert":"a130b248","exec":"891e75f5","data":{"target":"server","command":"ssh ... 'echo <base64> | base64 -d | opencode run --agent soc_god'"}}
{"ts":"2025-11-27T15:51:31Z","level":"EXEC","msg":"✓ Success on server","alert":"a130b248","exec":"891e75f5","data":{"status":"success","output":"Security incident response completed..."}}
{"ts":"2025-11-27T15:51:31Z","level":"DONE","msg":"Completed in 172.4s (plan: 0.0s, exec: 171.1s)","alert":"a130b248","exec":"891e75f5","data":{"total_duration":172.41,"status":"success"}}
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUN_ID` | `run_local` | Output directory name |
| `PLANNER_URL` | `http://127.0.0.1:8000/plan` | Plan generation endpoint |
| `OPENCODE_TIMEOUT` | `600` | Seconds before SSH timeout (10 minutes) |
| `AUTO_RESPONDER_INTERVAL` | `5` | Alert poll interval (seconds) |
| `MAX_EXECUTION_RETRIES` | `3` | SSH retry attempts |
| `OPENCODE_API_KEY` | - | API key for OpenCode LLM |

### SLIPS capture and processing cadence

- Router rotation is fixed at 30s (`images/router/entrypoint.sh`), producing `router_*.pcap` into `outputs/<run>/pcaps`.
- The watcher polls every 5s and processes only completed rotated PCAPs (stream snapshots are disabled).
- Per-PCAP processing timeout is fixed at 60s in `watch_pcaps.py`; if exceeded, the run is marked timed out and the watcher moves on.
- Zeek preprocessing (`images/slips_defender/slips.yaml`):
  - `pcapfilter` drops mDNS/DHCP (`not port 5353 and not port 67 and not port 68`) while keeping ICMP/ARP; avoids multicast/broadcast keywords that break on SLL captures.
  - `tcp_inactivity_timeout` is set to 1 minute to finish small rotations faster.

### SLIPS modules (enabled vs disabled)

- Disabled (to keep runs fast/stable): `rnn_cc_detection`, `flowmldetection`, `threat_intelligence`, `update_manager`, `virustotal`, `timeline`, `blocking`, plus the default `template`.
- Enabled (all others): core flow/ARP/HTTP/scan modules such as `arp`, `flow_alerts`, `http_analyzer`, `ip_info`, `network_discovery`, `riskiq`, and supporting processes (input/profiler/evidence handler).

### Network Topology

| Container | IP | Network |
|-----------|-----|---------|
| slips_defender | 172.30.0.254, 172.31.0.254 | Both |
| server | 172.31.0.10 | net_b |
| compromised | 172.30.0.10 | net_a |
| router | 172.30.0.1, 172.31.0.1 | Both |

---

## Files Reference

```
images/slips_defender/
├── defender/
│   ├── auto_responder.py      # Main orchestrator
│   └── setup_ssh_keys.sh      # SSH key setup script
├── defender_api.py           # Defender API (alerts storage + /plan endpoint)
├── forward_alerts.py         # SLIPS → Defender API forwarder
└── watch_pcaps.py            # PCAP watcher + SLIPS executor

outputs/<run_id>/
├── slips/defender_alerts.ndjson    # Raw alerts from SLIPS
├── processed_alerts.json     # Deduplication state
├── auto_responder_timeline.jsonl  # Structured execution log
└── auto_responder_detailed.log    # Human-readable log
```

---

## Debugging

### View Timeline (compact)
```bash
cat outputs/diego/auto_responder_timeline.jsonl | jq -c 'select(.level != "SSH") | {ts: .ts[11:19], level, msg, alert}'
```

### Watch Live Alerts
```bash
tail -f outputs/diego/slips/defender_alerts.ndjson | jq .
```

### Filter Errors Only
```bash
cat outputs/diego/auto_responder_timeline.jsonl | jq 'select(.level == "ERROR")'
```

### View Full SSH Commands
```bash
cat outputs/diego/auto_responder_timeline.jsonl | jq 'select(.level == "SSH") | .data.command'
```

### Check OpenCode Output
```bash
cat outputs/diego/auto_responder_timeline.jsonl | jq 'select(.level == "EXEC") | .data.output'
```

---

## Known Issues

### 1. Self-Isolation Bug
OpenCode may block SSH access from the defender when "isolating" a target system. The remediation plan says to block all traffic, but this includes the defender's SSH connection.

**Workaround:** Add defender IP to plan context or modify prompts to exclude management IPs.

### 2. Exit Code 255 False Positives
SSH returns 255 for both connection failures AND when the remote command exits non-zero. Check `data.stderr` to distinguish:
- Contains `connection refused` → SSH failed
- Contains OpenCode output → SSH worked, OpenCode had error

### 3. Long Execution Times
OpenCode execution can take 60-180 seconds depending on plan complexity. The 600s timeout (10 minutes) is intentional to allow complex remediation tasks to complete.

---

## Example: Full Alert Lifecycle

```
T+0s    SLIPS detects port scan from 172.30.0.10 to 172.31.0.10
T+2s    forward_alerts.py POSTs to /alerts
T+5s    auto_responder picks up alert
T+5s    Calls /plan endpoint → LLM plan generated
T+5s    SSH to server@172.31.0.10
T+6s    OpenCode starts with soc_god agent
T+30s   OpenCode runs: iptables -A INPUT -s 172.30.0.10 -j DROP
T+45s   OpenCode runs: fail2ban-client status
T+60s   OpenCode completes, SSH returns
T+60s   DONE logged, alert marked processed
```
