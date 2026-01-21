# Flask Brute Force Experiment - Summary

## Overview
The Flask brute force experiment tests the defender's response to a web application login brute force attack targeting a Flask login page.

## Changes Made

### 1. Flask App Modifications (`/home/diego/Trident/images/server/flask_app/app.py`)
- **Added logging**: All login attempts are now logged to `/tmp/flask_login_attempts.jsonl`
- **Log format**: JSONL (one JSON object per line) with fields:
  - `timestamp`: ISO format timestamp
  - `username`: Attempted username
  - `password_len`: Length of attempted password
  - `remote_addr`: Source IP address
  - `success`: Boolean indicating if login was successful

### 2. Experiment Scripts Created/Modified

#### `run_experiment.sh` (Main experiment runner)
- Modified to match `exfiltration_experiment.sh` structure
- Phases: Infrastructure → Defender → Monitoring → Attack → Results → Summary
- **Collects Flask logs** from server at end of experiment
- **Parses Flask logs** to extract:
  - Total login attempts
  - Successful attempts
  - First/last attempt timestamps
  - First successful attempt timestamp
- Generates JSON summary with all Flask login metrics

#### `flask_brute_attack.sh` (Attack script)
- Performs 2 nmap scans (network discovery + port scan)
- Flask login brute force with **1000-word password list**
- Correct password "admin" (from LOGIN_PASSWORD env var, default "admin")
- Random position in wordlist
- Real-time monitoring to detect blocking

#### `flask_bruteforce_monitor.sh` (Monitoring script)
- Runs in compromised container
- Pings Flask port (5000) every second
- Detects when port becomes blocked (3 consecutive failures)
- Outputs monitoring.json with block status

#### `run_flask_brute_experiments.py` (Multiple experiment runner)
- Python-based sequential experiment runner
- Replaces old bash version
- Outputs to `flask_brute_experiment_output/`
- 30-second wait between experiments

#### `analyze_flask_logs.py` (Utility script)
- Standalone script to analyze Flask login logs
- Shows total attempts, success rate, time range, unique IPs, usernames
- Usage: `python3 analyze_flask_logs.py <path_to_flask_login_attempts.jsonl>`

## Experiment Flow

1. **Infrastructure starts**: Docker containers, network, Flask app
2. **Defender starts**: SLIPS + auto-responder (unless SKIP_DEFENDER=true)
3. **Monitoring starts**: Flask port monitoring begins in background
4. **Attack executes**:
   - Nmap network scan
   - Nmap port scan
   - Flask brute force (1000 passwords)
5. **Monitoring loop**:
   - Tracks Flask port status
   - Tracks defender events (alert, plan, execution)
   - Terminates when Flask port blocked OR 15 min timeout
6. **Results collected**:
   - Defender timeline
   - Flask login logs (from server)
   - Attack logs (from attacker)
   - Monitoring data
7. **Summary generated**:
   - Timing metrics
   - Flask login statistics (from server logs - more accurate than attacker logs)

## Key Metrics Captured

### Timing Metrics
- `time_to_high_confidence_alert_seconds`: Time to first high-confidence SLIPS alert
- `time_to_plan_generation_seconds`: Time to first defender plan
- `time_to_opencode_execution_seconds`: Time to first successful OpenCode execution
- `time_to_port_blocked_seconds`: Time until Flask port became blocked

### Flask Login Metrics (from server logs)
- `flask_login_attempts`: Total number of login attempts received by Flask
- `flask_successful_attempts`: Number of successful logins
- `flask_first_attempt_time`: Timestamp of first attempt
- `flask_last_attempt_time`: Timestamp of last attempt
- `flask_successful_attempt_time`: Timestamp of first successful attempt (if any)
- `password_found`: Boolean - was the correct password found?

## Output Files

Each experiment generates:
- `flask_brute_experiment_summary.json`: Main summary with all metrics
- `logs/flask_login_attempts.jsonl`: Raw Flask login logs from server
- `logs/flask_attack_summary.json`: Attack-side summary
- `logs/flask_attack_log.txt`: Detailed attack log
- `logs/monitoring.json`: Port monitoring data
- `logs/auto_responder_timeline.jsonl`: Defender event timeline
- `logs/nmap_discovery.txt`: Network scan results
- `logs/nmap_ports.txt`: Port scan results

## Usage

### Single Experiment
```bash
./scripts/defender_experiments/run_experiment.sh [experiment_id]
```

### Multiple Experiments
```bash
python3 scripts/defender_experiments/run_flask_brute_experiments.py
```

### Analyze Flask Logs
```bash
python3 scripts/defender_experiments/analyze_flask_logs.py /path/to/flask_login_attempts.jsonl
```

## Environment Variables

- `LOGIN_USER`: Flask username (default: "admin")
- `LOGIN_PASSWORD`: Flask password (default: "admin")
- `SKIP_DEFENDER`: Set to "true" to run baseline (no defender)
- `PCAP_ROTATE_SECS`: PCAP rotation interval (default: 30)

## Password List

The attack uses a 1000-word list with the correct password ("admin") at a random position. Common passwords include:
- Standard passwords (123456, password, qwerty, etc.)
- Admin variations (admin123, administrator, etc.)
- Dictionary words
- Random variations

## Termination Conditions

Experiment ends when:
1. Flask port is blocked (3 consecutive connection failures detected)
2. 15 minutes elapsed since attack start (timeout)
