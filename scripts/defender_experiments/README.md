# Defender Experiments

This directory contains scripts for running automated experiments to test defender performance against scripted attacks.

## Scripts Overview

### 1. `attack_script.sh`
Performs a three-phase attack from the compromised container:
- **Phase 1**: Network discovery using nmap to locate the server
- **Phase 2**: Port scanning to identify SSH service on the server
- **Phase 3**: SSH brute force attack with a 250-password wordlist (including the correct password `admin123`)

### 2. `run_experiment.sh`
Manages the complete lifecycle of a single experiment:
- Sets up environment and creates output directories
- Starts all Docker containers (router, server, compromised, defender)
- Waits for services to become healthy
- Executes the attack script
- Collects PCAP files and logs
- Stops infrastructure and generates experiment summary

### 3. `analyze_pcaps.py`
Analyzes PCAP files to evaluate defender performance:
- Tracks attack progression through network traffic
- Identifies milestones (server discovery, SSH port found, handshake, auth attempts)
- Determines final defender status and performance rating
- Generates detailed timing analysis

### 4. `run_multi_experiment.py`
Orchestrates multiple experiments and aggregates results:
- Runs specified number of experiments sequentially
- Analyzes PCAPs for each experiment
- Generates comprehensive JSON report with statistics
- Provides defender performance recommendations

## Usage

### Single Experiment
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

### Web Login Smoke Test (manual)
Run from inside the compromised container:
```bash
for i in $(seq 1 50); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    -d "username=admin&password=wrongpass" http://172.31.0.10/login
done
```

### Multiple Experiments
```bash
# Run 5 experiments and generate comprehensive report
python3 run_multi_experiment.py 5

# Custom output file
python3 run_multi_experiment.py 10 --output my_results.json

# Custom configuration
python3 run_multi_experiment.py 5 --pcap-rotate-secs 3 --lab-password admin123

# Quiet mode (less verbose output)
python3 run_multi_experiment.py 3 --quiet
```

### PCAP Analysis
```bash
# Analyze PCAP files from an experiment
python3 analyze_pcaps.py /path/to/pcaps/folder

# Custom output file
python3 analyze_pcaps.py /path/to/pcaps --output custom_analysis.json

# Quiet mode
python3 analyze_pcaps.py /path/to/pcaps --quiet
```

## Configuration

### Environment Variables
- `LAB_PASSWORD`: SSH password for containers (default: `admin123`)
- `PCAP_ROTATE_SECS`: PCAP rotation interval in seconds (default: 5)
- `SLIPS_PROCESS_ACTIVE`: Enable SLIPS processing (default: 1)
- `SLIPS_WATCH_INTERVAL`: SLIPS watch interval in seconds (default: 1)
- `DEFENDER_PORT`: Defender API port (default: 8000)

### Network Configuration
- Compromised IP: `172.30.0.10`
- Server IP: `172.31.0.10`
- Router manages traffic between networks

## Expected Attack Timeline

1. **Network Discovery** (~10-30 seconds)
2. **Port Scanning** (~5-15 seconds)
3. **Brute Force Attack** (~1-5 minutes depending on password position)

## Defender Performance Analysis

The analysis script categorizes defender performance as:
- **FAILURE - Attack Successful**: SSH brute force completes successfully
- **Critical - Brute Force Detected**: SSH authentication attempts observed
- **Warning - Connection Established**: SSH handshake completed
- **Alert - Port Scanned**: SSH port discovered
- **Passive - Server Discovered**: Server responds to discovery
- **No Attack**: No malicious activity detected

## Output Files

### Single Experiment
- `outputs/{experiment_id}/experiment_summary.json`: Basic experiment metadata
- `outputs/{experiment_id}/pcaps/`: Network traffic captures
- `outputs/{experiment_id}/logs/`: Attack logs and system outputs
- `outputs/{experiment_id}/slips/`: Defender logs and alerts

### Multi-Experiment
- `multi_experiment_results.json`: Comprehensive report with all experiments
- Individual experiment analyses stored in respective experiment folders

## Dependencies

- Docker and Docker Compose
- Python 3 with scapy package
- nmap and hydra (installed in compromised container)
- SLIPS defender system

## Troubleshooting

### Common Issues
1. **Container startup failures**: Check Docker logs with `docker logs lab_<service>`
2. **PCAP analysis failures**: Ensure scapy is installed and PCAP files exist
3. **Attack failures**: Verify network connectivity and password configuration
4. **Permission errors**: Ensure scripts are executable and Docker access

### Logs and Debugging
- Experiment logs: `outputs/{experiment_id}/logs/attack_log.txt`
- Container logs: `docker logs lab_router`, `docker logs lab_server`, etc.
- Defender logs: `outputs/{experiment_id}/slips/`

## Security Note

These scripts are designed for authorized security testing and educational purposes only. They simulate attack patterns to test and evaluate defensive systems in controlled environments.
