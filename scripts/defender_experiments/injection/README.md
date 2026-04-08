# DNS Injection Experiment

## Overview

This experiment tests the defender's response to DNS resolution attacks targeting `analisisconsumidoresargentina.lat`. The attack performs 5 consecutive DNS resolutions to generate DNS alerts and trigger the automated defense system.

**IMPORTANT**: All scripts that execute inside Docker containers use benign names to appear as normal Ubuntu system services.

## Benign Process Names

Scripts copied to containers are renamed to look like legitimate Ubuntu services:

| Script File | Container Path | Process Name | Purpose |
|-------------|---------------|--------------|---------|
| `dns_injection_attack.sh` | `/usr/local/bin/network_check.sh` | `network_check` | Appears to be a network connectivity verification tool |
| `dns_injection_monitor.sh` | `/usr/local/bin/health_monitor.sh` | `health_monitor` | Appears to be a system health monitoring daemon |
| Monitoring output | `/var/lib/system_health/metrics.json` | - | System health metrics directory |
| Attack output | `/var/lib/network_metrics/connectivity_status.json` | - | Network metrics directory |

These names mimic standard Ubuntu system administration tools that would be expected in a normal environment.

## Experiment Structure

Based on the `brute_force` experiment structure, this includes:

### Scripts

1. **dns_injection_attack.sh** - The attack script that performs 5 DNS resolutions to the target domain
   - Performs 5 consecutive DNS lookups using `nslookup`
   - Records timing and results for each resolution
   - Outputs monitoring data to `/var/lib/network_metrics/connectivity_status.json`
   - **When copied to container**: `/usr/local/bin/network_check.sh`

2. **dns_injection_monitor.sh** - Monitoring script that tracks DNS alerts
   - Monitors for DNS-related alerts in SLIPS output
   - Tracks alert detection and timing
   - Runs continuously until experiment completes
   - **When copied to container**: `/usr/local/bin/health_monitor.sh`

3. **run_injection_experiment.sh** - Main experiment runner
   - Starts infrastructure with `make up`
   - Optionally starts defender with `make defend`
   - Executes the DNS attack
   - Monitors for experiment completion conditions
   - Collects results and generates summary
   - Cleans up with `make down`

4. **run_injection_experiments.py** - Python runner for N experiments
   - Runs multiple experiments sequentially
   - Handles cleanup between experiments
   - Aggregates results in output directory

## Usage

### Run a Single Experiment

```bash
cd /home/diego/Trident
./scripts/defender_experiments/injection/run_injection_experiment.sh [experiment_id]
```

### Run N Experiments

Edit `NUM_EXPERIMENTS` in `run_injection_experiments.py` (default: 3), then:

```bash
cd /home/diego/Trident
python3 ./scripts/defender_experiments/injection/run_injection_experiments.py
```

## Experiment Flow

1. **Phase 1: Infrastructure Setup**
   - Run `make down` to ensure clean state
   - Run `make up` to start core services (server, compromised, router)
   - Wait for all containers to be healthy
   - Verify network connectivity

2. **Phase 2: Defender Start** (unless SKIP_DEFENDER=true)
   - Run `make defend` to start defender services
   - Wait for defender to be ready

3. **Phase 3: Attack Execution**
   - Copy attack and monitoring scripts to compromised container with benign names:
     - `dns_injection_attack.sh` → `/usr/local/bin/network_check.sh`
     - `dns_injection_monitor.sh` → `/usr/local/bin/health_monitor.sh`
   - Start monitoring in background (`health_monitor.sh`)
   - Execute 5 DNS resolutions to `analisisconsumidoresargentina.lat` via `network_check.sh`

4. **Phase 4: Monitoring**
   - Track DNS alerts detection
   - Track plan generation
   - Track OpenCode execution start and completion
   - Monitor experiment end conditions

5. **Phase 5: Results Collection**
   - Copy defender timeline logs
   - Copy OpenCode API messages
   - Copy DNS attack monitoring data
   - Copy SLIPS output

6. **Phase 6: Summary Generation**
   - Calculate timing metrics
   - Generate JSON summary
   - Print experiment results

7. **Cleanup**
   - Run `make down` to stop all containers
   - Remove PCAP files to save disk space

## Termination Conditions

The experiment ends when:

1. **Success**: OpenCode execution complete on both servers + attack finished + no new alerts for 30s
2. **Timeout**: 20 minutes (1200 seconds) have passed since attack started
3. **Interrupt**: User sends SIGINT/SIGTERM

## Output Format

Results are saved to: `/home/diego/Trident/outputs/<experiment_id>/`

### Directory Structure

```
<experiment_id>/
├── logs/
│   ├── experiment.log                    # Main experiment log
│   ├── network_check.log                 # DNS attack output (renamed)
│   ├── monitoring.json                   # Network check monitoring data
│   ├── dns_attack_summary.json           # Network check summary
│   ├── auto_responder_timeline.jsonl     # Combined defender timeline
│   ├── auto_responder_timeline_server.jsonl
│   ├── auto_responder_timeline_compromised.jsonl
│   ├── opencode_api_messages_server.json
│   ├── opencode_api_messages_compromised.json
│   └── slips/                            # SLIPS output
├── defender/
│   ├── server/
│   │   ├── auto_responder_timeline.jsonl
│   │   ├── opencode_api_messages.json
│   │   └── opencode_sse_events.jsonl
│   └── compromised/
│       ├── auto_responder_timeline.jsonl
│       ├── opencode_api_messages.json
│       └── opencode_sse_events.jsonl
└── dns_injection_experiment_summary.json # Experiment summary
```

**Note**: Inside the container, files are stored at benign paths:
- Monitoring data: `/var/lib/system_health/metrics.json`
- Attack output: `/var/lib/network_metrics/connectivity_status.json` and `connectivity_summary.json`
- Logs: `/var/log/health_monitor.log`

### Summary JSON Format

```json
{
  "experiment_id": "dns_injection_20240329_120000",
  "attack_type": "dns_injection",
  "target_domain": "analisisconsumidoresargentina.lat",
  "attack_start_time": "2024-03-29T12:00:00+00:00",
  "experiment_end_time": "2024-03-29T12:05:00+00:00",
  "total_duration_seconds": 300,
  "end_reason": "opencode_complete_attack_done_no_new_alerts",
  "num_plans_generated": 2,
  "metrics": {
    "time_to_high_confidence_alert_seconds": 15,
    "high_confidence_alert_time": "2024-03-29T12:00:15+00:00",
    "time_to_plan_generation_seconds": 30,
    "plan_generation_time": "2024-03-29T12:00:30+00:00",
    "time_to_opencode_execution_seconds": 60,
    "opencode_execution_time": "2024-03-29T12:01:00+00:00",
    "opencode_execution_end_time": "2024-03-29T12:04:00+00:00",
    "dns_resolutions_total": 5,
    "dns_resolutions_successful": 5,
    "dns_first_resolution_time": "2024-03-29T12:00:00+00:00",
    "dns_last_resolution_time": "2024-03-29T12:00:10+00:00",
    "per_ip_metrics": {
      "172.31.0.10": {
        "plan_time": "2024-03-29T12:00:30+00:00",
        "time_to_plan_seconds": 30,
        "exec_start_time": "2024-03-29T12:01:00+00:00",
        "time_to_exec_seconds": 60,
        "exec_end_time": "2024-03-29T12:03:00+00:00"
      },
      "172.30.0.10": {
        "plan_time": "2024-03-29T12:00:30+00:00",
        "time_to_plan_seconds": 30,
        "exec_start_time": "2024-03-29T12:01:00+00:00",
        "time_to_exec_seconds": 60,
        "exec_end_time": "2024-03-29T12:04:00+00:00"
      }
    }
  }
}
```

## Configuration

Edit variables in `run_injection_experiment.sh`:

- `MAX_EXPERIMENT_TIME=1200` - Maximum experiment duration (20 minutes)
- `TARGET_DOMAIN="analisisconsumidoresargentina.lat"` - Target domain for DNS resolutions
- `NUM_DNS_RESOLUTIONS=5` - Number of DNS resolutions to perform

Edit variables in `run_injection_experiments.py`:

- `NUM_EXPERIMENTS = 3` - Number of experiments to run
- `timeout=2700` - Timeout per experiment (45 minutes)

## Differences from brute_force Experiment

1. **Attack Type**: DNS resolutions instead of HTTP login attempts
2. **Target**: Domain name instead of IP:port
3. **Monitoring**: DNS-specific monitoring instead of Flask port blocking
4. **Termination**: Based on OpenCode completion instead of port blocking
5. **Duration**: 20 minutes max instead of 60 minutes

## Notes

- All scripts use **benign filenames when copied to containers** to appear as legitimate Ubuntu services:
  - `dns_injection_attack.sh` → `/usr/local/bin/network_check.sh` (appears as network connectivity tool)
  - `dns_injection_monitor.sh` → `/usr/local/bin/health_monitor.sh` (appears as system health daemon)
  - Output stored in `/var/lib/network_metrics/` and `/var/lib/system_health/` (standard system directories)
- DNS resolutions are performed using `nslookup` for simplicity
- Monitoring tracks DNS alerts from SLIPS
- Both OpenCode servers (172.31.0.10 and 172.30.0.10) are monitored for execution
- PCAP files are deleted after each experiment to save disk space

### Process Naming Strategy

The experiment uses the following benign naming strategy to avoid detection:

| Component | Actual Purpose | Benign Name | Rationale |
|-----------|---------------|-------------|-----------|
| Attack script | Performs DNS resolutions | `network_check.sh` | Standard network connectivity verification tool |
| Monitor script | Tracks DNS alerts | `health_monitor.sh` | Common system health monitoring daemon |
| Attack output dir | Stores attack results | `/var/lib/network_metrics/` | Standard metrics storage location |
| Monitor output dir | Stores monitoring data | `/var/lib/system_health/` | System health data directory |
| Attack log | Attack execution log | `network_check.log` | Network diagnostic log file |

These names are chosen because:
1. **Network check tools** are common in Ubuntu for diagnosing connectivity issues
2. **Health monitoring daemons** are standard system administration tools
3. **/var/lib/*** is the standard location for system state data in Linux
4. **Logs in /var/log/*** are expected system administration files

This naming convention makes the activities appear as routine system maintenance rather than malicious behavior.
