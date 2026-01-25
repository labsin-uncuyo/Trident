# Scripts

Utility scripts for manual alert submission to the Planner API.

## send_alert_to_planner.py

Send alerts to the Planner API for remediation plan generation.

### Usage

```bash
# Send custom alert
python3 send_alert_to_planner.py --alert "Src IP 192.168.1.1. Detected port scan"

# Use latest alert from logs
python3 send_alert_to_planner.py --latest-alert

# Interactive mode
python3 send_alert_to_planner.py --interactive

# Quiet mode (plan only)
python3 send_alert_to_planner.py --alert "ALERT_TEXT" --quiet
```

### Environment

```bash
export PLANNER_API_URL="http://localhost:8000"
export DEFAULT_ALERTS_DIR="/outputs"
```

### Output

- **Model**: LLM model used
- **Request ID**: Unique identifier
- **Executor Host IP**: Target for remediation
- **Incident Response Plan**: Analysis and actions

## send_alert.sh

Bash wrapper for `send_alert_to_planner.py`. Accepts same arguments.

## Docker Usage

```bash
docker exec lab_slips_defender python3 /scripts/send_alert_to_planner.py --latest-alert
```

## Alert Format

Best results include:
- Source IP address
- "Detected" keyword with threat description
- Threat level and confidence

Example:
```
Src IP 172.30.0.10. Detected SSH password guessing. 50 failed attempts.
Threat level: high. Confidence: 0.9.
```
