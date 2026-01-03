# Defender Experiments

This directory contains scripts for running automated experiments to test defender performance against various attack scenarios including SSH brute force and data exfiltration.

## 📋 Table of Contents

- [SSH Brute Force Experiments](#ssh-brute-force-experiments)
- [Data Exfiltration Experiments](#data-exfiltration-experiments)
- [Analysis and Reporting Tools](#analysis-and-reporting-tools)
- [Utility Scripts](#utility-scripts)
- [Configuration](#configuration)

---

## SSH Brute Force Experiments

### 1. `attack_script.sh`
Performs a three-phase attack from the compromised container:
- **Phase 1**: Network discovery using nmap to locate the server
- **Phase 2**: Port scanning to identify SSH service on the server
- **Phase 3**: SSH brute force attack with a 250-password wordlist (including the correct password `admin123`)

### 2. `run_experiment.sh`
Manages the complete lifecycle of a single SSH brute force experiment:
- Sets up environment and creates output directories
- Starts all Docker containers (router, server, compromised, defender)
- Waits for services to become healthy
- Executes the attack script
- Collects PCAP files and logs
- Stops infrastructure and generates experiment summary

### 3. `run_multiple_experiments_forced.sh`
Orchestrates multiple SSH brute force experiments sequentially:
- Runs specified number of experiments
- Analyzes PCAPs for each experiment
- Generates comprehensive JSON report with statistics
- Provides defender performance recommendations

### 4. `analyze_pcaps.py`
Analyzes PCAP files to evaluate defender performance:
- Tracks attack progression through network traffic
- Identifies milestones (server discovery, SSH port found, handshake, auth attempts)
- Determines final defender status and performance rating
- Generates detailed timing analysis

---

## Data Exfiltration Experiments

### 1. `exfiltration_experiment.sh`
**Primary script for data exfiltration attack simulation.**

Tests defender response to database exfiltration through PostgreSQL:
- Simulates attacker dumping database via `pg_dump` piped to netcat
- Monitors timeline from attack start to defender response
- Tracks metrics:
  - Time until SLIPS generates high-confidence alert
  - Time to plan generation
  - Time until OpenCode execution finishes
  - Time until last byte exfiltrated
- Auto-terminates when:
  - Defender successfully executes and no bytes received for 30s, OR
  - 15 minutes elapsed since exfil command

**Usage:**
```bash
./exfiltration_experiment.sh [experiment_id]
```

### 2. `run_50_experiments.py`
Python script to run multiple exfiltration experiments sequentially:
- Configurable number of experiments (default: 19, adjustable in script)
- Moves results to organized output directory
- Generates success/failure statistics
- Includes wait time between experiments (30s default)

**Usage:**
```bash
python3 run_50_experiments.py
```

### 3. `exfiltration_monitor.sh`
Monitoring script for exfiltration experiments (used by `exfiltration_experiment.sh`):
- Monitors network traffic during exfiltration
- Detects when data transfer stops
- Signals completion to main experiment script

### 4. `enlarge_database_with_integrity.py`
Utility to create larger test databases while maintaining referential integrity:
- Duplicates employees and all related records (salary, title, department_employee)
- Preserves foreign key constraints
- Useful for testing defender performance with larger data volumes

**Usage:**
```bash
python3 enlarge_database_with_integrity.py <input.sql> <output.sql> <multiplier>
```

---

## Analysis and Reporting Tools

### 1. `generate_opencode_analysis.py`
**Comprehensive analysis and visualization of exfiltration experiment results.**

Generates detailed reports including:
- Summary statistics (success rates, timing metrics)
- Box plots for key metrics (plan generation, execution time, blocking time)
- Command frequency analysis
- Tool usage breakdown
- Action categorization

**Usage:**
```bash
# Basic analysis (no LLM)
python3 generate_opencode_analysis.py

# With LLM analysis of patterns
python3 generate_opencode_analysis.py --with-llm
```

### 2. `expand_run_analysis.py`
Uses LLM to analyze specific experiment runs in depth:
- Reads `auto_responder_timeline.jsonl` files
- Expands on initial observations with AI-powered analysis
- Generates detailed reports for specific runs

**Usage:**
```bash
python3 expand_run_analysis.py
```

### 3. `plot_experiment_results.py`
Creates box plots from SSH brute force experiment results:
- Visualizes key metrics across multiple runs
- Compares time_to_plan_generation, opencode_execution_seconds, time_to_blocked_seconds

**Usage:**
```bash
python3 plot_experiment_results.py <experiment_output_dir>
```

---

## Utility Scripts

### 1. `diagnose_pcap.py`
Diagnostic tool for analyzing PCAP files:
- Packet statistics and classification
- SSH traffic detection verification
- Helps debug why detection might not be working

**Usage:**
```bash
python3 diagnose_pcap.py <pcap_folder_path>
```

---

## Configuration

### Environment Variables (SSH Brute Force)
- `LAB_PASSWORD`: SSH password for containers (default: `admin123`)
- `PCAP_ROTATE_SECS`: PCAP rotation interval in seconds (default: 5)
- `SLIPS_PROCESS_ACTIVE`: Enable SLIPS processing (default: 1)
- `SLIPS_WATCH_INTERVAL`: SLIPS watch interval in seconds (default: 1)
- `DEFENDER_PORT`: Defender API port (default: 8000)

### Environment Variables (Exfiltration)
- `RUN_ID`: Experiment run ID (auto-generated if not provided)
- `PCAP_ROTATE_SECS`: PCAP rotation interval (default: 30)
- `MAX_EXPERIMENT_TIME`: Maximum experiment duration in seconds (default: 900)

### Network Configuration
- Compromised IP: `172.30.0.10`
- Server IP: `172.31.0.10`
- Router manages traffic between networks

---

## Usage Examples

### SSH Brute Force - Single Experiment
```bash
# Run one experiment with default settings
./run_experiment.sh

# Run with custom experiment ID
./run_experiment.sh my_test_001

# Set custom password (default: admin123)
LAB_PASSWORD=admin123 ./run_experiment.sh

# Custom PCAP rotation interval
PCAP_ROTATE_SECS=10 ./run_experiment.sh
```

### SSH Brute Force - Multiple Experiments
```bash
# Run multiple experiments using the shell script
./run_multiple_experiments_forced.sh 5

# Or use the Python variant (if available)
python3 run_multiple_experiments_forced.sh 5 --output my_results.json
```

### Data Exfiltration - Single Experiment
```bash
# Run with auto-generated experiment ID
./exfiltration_experiment.sh

# Run with custom experiment ID
./exfiltration_experiment.sh exfil_test_001
```

### Data Exfiltration - Multiple Experiments
```bash
# Run sequential experiments (edit script to change NUM_EXPERIMENTS)
python3 run_50_experiments.py
```

### Manual Smoke Tests

**Web Login Brute Force:**
```bash
docker exec lab_compromised bash -lc 'for i in $(seq 1 50); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    -d "username=admin&password=wrongpass" http://172.31.0.10/login
done'
```

**PostgreSQL Brute Force:**
```bash
docker exec lab_compromised bash -lc 'for i in $(seq 1 50); do
  PGPASSWORD="wrongpass" psql -h 172.31.0.10 -U labuser -d labdb -c "SELECT 1;" >/dev/null 2>&1 \
    && echo "hit" && break
  echo "try $i"
done'
```

### Analysis

**PCAP Analysis (SSH Experiments):**
```bash
python3 analyze_pcaps.py /path/to/pcaps/folder
python3 analyze_pcaps.py /path/to/pcaps --output custom_analysis.json
python3 analyze_pcaps.py /path/to/pcaps --quiet
```

**OpenCode Analysis (Exfiltration Experiments):**
```bash
# Basic analysis
python3 generate_opencode_analysis.py

# With LLM-powered pattern analysis
python3 generate_opencode_analysis.py --with-llm
```

**Deep Dive Analysis with LLM:**
```bash
python3 expand_run_analysis.py
```

**Visualization:**
```bash
python3 plot_experiment_results.py <experiment_output_dir>
```

**PCAP Diagnostics:**
```bash
python3 diagnose_pcap.py <pcap_folder_path>
```

---

## Expected Timelines

### SSH Brute Force Attack
1. **Network Discovery** (~10-30 seconds)
2. **Port Scanning** (~5-15 seconds)
3. **Brute Force Attack** (~1-5 minutes depending on password position)

### Data Exfiltration Attack
1. **Attack Initiation** (immediate)
2. **SLIPS Detection** (~5-30 seconds for high-confidence alert)
3. **Plan Generation** (~2-5 seconds)
4. **OpenCode Execution** (~5-15 seconds)
5. **Remediation Complete** (~15-60 seconds total)

---

## Performance Analysis Categories

The analysis scripts categorize defender performance as:

### SSH Brute Force
- **FAILURE - Attack Successful**: SSH brute force completes successfully
- **Critical - Brute Force Detected**: SSH authentication attempts observed
- **Warning - Connection Established**: SSH handshake completed
- **Alert - Port Scanned**: SSH port discovered
- **Passive - Server Discovered**: Server responds to discovery
- **No Attack**: No malicious activity detected

### Data Exfiltration
- **Blocked**: Exfiltration stopped before completion (>0 bytes but < total)
- **Partial**: Some data exfiltrated before defender response
- **Failure**: Full database exfiltrated (defender did not respond in time)
- **No Attack**: No malicious activity detected

---

## Output Files

### SSH Brute Force Experiments
- `outputs/{experiment_id}/experiment_summary.json`: Basic experiment metadata
- `outputs/{experiment_id}/pcaps/`: Network traffic captures
- `outputs/{experiment_id}/logs/`: Attack logs and system outputs
- `outputs/{experiment_id}/slips_output/`: Defender logs and alerts
- `multi_experiment_results.json`: Comprehensive multi-experiment report

### Data Exfiltration Experiments
- `outputs/{experiment_id}/exfil_experiment_summary.json`: Experiment metadata and timing
- `outputs/{experiment_id}/auto_responder_timeline.jsonl`: Detailed execution timeline
- `outputs/{experiment_id}/executions.jsonl`: OpenCode execution details
- `outputs/{experiment_id}/pcaps/`: Network traffic captures
- `exfil_experiment_output_*/report/`: Analysis reports and visualizations

---

## Dependencies

### System Requirements
- Docker and Docker Compose
- Python 3.8+
- Make (for using `make up` / `make down` commands)

### Python Packages
```bash
pip install scapy matplotlib seaborn numpy requests
```

### Container Tools (auto-installed)
- nmap (network scanning)
- hydra (SSH brute force)
- PostgreSQL client tools
- netcat (network utilities)
- hping3 (DoS testing)

---

## Troubleshooting

### Common Issues

1. **Container startup failures**
   ```bash
   docker logs lab_slips_defender
   docker logs lab_server
   docker logs lab_compromised
   ```

2. **PCAP analysis failures**
   - Ensure scapy is installed: `pip install scapy`
   - Verify PCAP files exist in output directory
   - Check file permissions

3. **Attack failures**
   - Verify network connectivity: `docker exec lab_compromised ping 172.31.0.10`
   - Check password configuration in `.env` file
   - Ensure containers are healthy: `docker ps`

4. **Permission errors**
   - Ensure scripts are executable: `chmod +x *.sh`
   - Verify Docker access: `docker ps`
   - Check output directory permissions

### Logs and Debugging

**Experiment logs:**
- SSH experiments: `outputs/{experiment_id}/logs/attack_log.txt`
- Exfiltration experiments: `outputs/{experiment_id}/logs/experiment.log`

**Defender logs:**
- `outputs/{RUN_ID}/auto_responder_detailed.log` - Detailed responder activity
- `outputs/{RUN_ID}/auto_responder_timeline.jsonl` - Structured timeline
- `outputs/{RUN_ID}/executions.jsonl` - OpenCode execution details
- `outputs/{RUN_ID}/slips/defender_alerts.ndjson` - SLIPS alerts

**Container logs:**
```bash
docker logs lab_slips_defender
docker logs lab_server
docker logs lab_compromised
docker logs lab_router
```

---

## Security Note

These scripts are designed for **authorized security testing and educational purposes only**. They simulate attack patterns to test and evaluate defensive systems in controlled environments.

**Use only on:**
- Systems you own or have explicit permission to test
- Isolated lab environments (e.g., the Trident lab infrastructure)
- Educational and research settings with proper authorization

---

## Additional Resources

- **Trident Project Documentation**: See main project README
- **SLIPS Documentation**: https://stratospherelinuxips.readthedocs.io/
- **Defender Manual**: `/home/diego/Trident/images/slips_defender/defender/README.md`