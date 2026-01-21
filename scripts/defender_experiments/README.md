# Defender Experiments

This directory contains scripts for running automated experiments to test defender performance against various attack scenarios including web brute force, data exfiltration, and DNS-based attacks.

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Experiment Categories](#experiment-categories)
- [Analysis Tools](#analysis-tools)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Output Files](#output-files)
- [Dependencies](#dependencies)

---

## Quick Start

```bash
# Run a single Flask brute force experiment
./brute_force/run_experiment.sh

# Run a single data exfiltration experiment
./exfiltration/exfiltration_experiment.sh

# Run multiple experiments
python3 brute_force/run_flask_brute_experiments.py
python3 exfiltration/run_exfil_experiments.py

# Analyze results
python3 analysis/analyze_flask_logs.py <path_to_flask_log>
python3 analysis/generate_opencode_analysis.py
```

---

## Experiment Categories

### Web Brute Force Experiments

**Location:** `brute_force/`

Tests defender response to web application login brute force attacks targeting a Flask login page.

#### Files

- **`run_experiment.sh`** - Main experiment runner that orchestrates the complete experiment lifecycle
- **`flask_brute_attack.sh`** - Attack script that performs network discovery and brute force attack
- **`flask_bruteforce_monitor.sh`** - Monitoring script that detects when the Flask port becomes blocked
- **`run_flask_brute_experiments.py`** - Sequential experiment runner for multiple tests
- **`FLASK_BRUTE_FORCE_README.md`** - Detailed documentation specific to Flask brute force experiments

**See also:** `brute_force/FLASK_BRUTE_FORCE_README.md` for detailed documentation.

---

### Data Exfiltration Experiments

**Location:** `exfiltration/`

Tests defender response to database exfiltration through PostgreSQL.

#### Files

- **`exfiltration_experiment.sh`** - Primary experiment script that simulates database dumping via netcat
- **`exfiltration_monitor.sh`** - Monitoring script that tracks data transfer and detects completion
- **`run_exfil_experiments.py`** - Sequential experiment runner for multiple tests

---

### DNS/Injection Experiments

**Location:** `injection/`

Tests DNS-based detection and auto-responder triggering.

#### Files

- **`dns_txt_entropy_test.sh`** - Tests if SLIPS detects DNS TXT records with high entropy and triggers auto-responder

---

## Analysis Tools

**Location:** `analysis/`

### Files

- **`analyze_flask_logs.py`** - Analyzes Flask login attempt logs from server (attempts, success rates, IPs, usernames)
- **`generate_opencode_analysis.py`** - Comprehensive analysis and visualization of exfiltration experiment results
- **`expand_run_analysis.py`** - LLM-powered deep analysis of specific experiment runs
- **`plot_exfiltration_results.py`** - Creates box plots from exfiltration experiment results

---

## Output Files

### Flask Brute Force Experiments

Each experiment generates:
- `flask_brute_experiment_summary.json` - Main summary with all metrics
- `logs/flask_login_attempts.jsonl` - Raw Flask login logs from server
- `logs/flask_attack_summary.json` - Attack-side summary
- `logs/flask_attack_log.txt` - Detailed attack log
- `logs/monitoring.json` - Port monitoring data
- `logs/auto_responder_timeline.jsonl` - Defender event 

### Data Exfiltration Experiments

Each experiment generates:
- `exfil_experiment_summary.json` - Experiment metadata and timing
- `auto_responder_timeline.jsonl` - Detailed execution timeline
- `executions.jsonl` - OpenCode execution details
- `logs/monitoring.json` - Exfiltration monitoring data

### Multi-Experiment Outputs

- Flask: `flask_brute_experiment_output/`
- Exfiltration: `exfil_experiment_output_*/`

---

