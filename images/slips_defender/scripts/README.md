# Slips Defender Scripts

This directory contains utility scripts for interacting with the Slips defender and Planner API.

## send_alert_to_planner.py

Send Slips alerts to the Planner API for automated incident response planning.

### Installation

```bash
pip install requests
```

### Usage

```bash
# Send a custom alert
python3 send_alert_to_planner.py --alert "Src IP 192.168.1.1. Detected port scan"

# Use the latest alert from alerts.log
python3 send_alert_to_planner.py --latest-alert

# Use alerts from a specific file
python3 send_alert_to_planner.py --file /path/to/alerts.log

# Interactive mode (compose alert manually)
python3 send_alert_to_planner.py --interactive

# Use latest alert from specific run ID
python3 send_alert_to_planner.py --latest-alert --run-id logs_20260120_230023

# Quiet mode (only print the plan)
python3 send_alert_to_planner.py --alert "ALERT_TEXT" --quiet
```

### Examples

#### Example 1: Send Custom Alert

```bash
./send_alert_to_planner.py --alert "2026-01-20T23:20:16+00:00 (TW 1): Src IP 172.30.0.10. Detected A DNS TXT answer with high entropy."
```

#### Example 2: Use Latest Alert from Logs

```bash
./send_alert_to_planner.py --latest-alert
```

#### Example 3: Interactive Mode

```bash
./send_alert_to_planner.py --interactive
```

Then type your alert:
```
Src IP 192.168.1.100. Detected multiple failed SSH login attempts.
Threat level: high. Confidence: 0.9.
END
```

### Output

The script sends the alert to the Planner API and displays:

- **Model**: LLM model used
- **Request ID**: Unique identifier for tracking
- **Executor Host IP**: Target host for remediation
- **Incident Response Plan**: Detailed analysis and actions

### Configuration

Set environment variables:

```bash
export PLANNER_API_URL="http://localhost:8000"
export DEFAULT_ALERTS_DIR="/outputs"
```

### Exit Codes

- `0`: Success
- `1`: Error (network, file not found, etc.)

## send_alert.sh

Bash wrapper for `send_alert_to_planner.py`.

### Usage

```bash
# Same arguments as Python script
./send_alert.sh --alert "ALERT_TEXT"
./send_alert.sh --latest-alert
./send_alert.sh --interactive
```

## Docker Usage

To run from within the defender container:

```bash
docker exec lab_slips_defender python3 /scripts/send_alert_to_planner.py --latest-alert
```

Or add to docker-compose for persistent access:

```yaml
services:
  slips_defender:
    volumes:
      - ./images/slips_defender/scripts:/scripts:ro
```

## Integration with Slips

### Automatic Alert Forwarding

To automatically send all HIGH severity alerts to the planner:

```python
# Add to your Slips monitoring script
import subprocess

def on_high_severity_alert(alert):
    subprocess.run([
        "python3", "/scripts/send_alert_to_planner.py",
        "--alert", alert
    ])
```

### Cron Job

Schedule periodic checking for new alerts:

```cron
# Check for new alerts every 5 minutes
*/5 * * * * cd /scripts && python3 send_alert_to_planner.py --latest-alert
```

## Troubleshooting

### "No alerts found"

- Check that `DEFAULT_ALERTS_DIR` is correct
- Verify alerts.log file exists and has content
- Use `--file` to specify exact path

### "Connection refused"

- Ensure Planner API is running: `docker ps | grep planner`
- Check `PLANNER_API_URL` environment variable
- Verify port 8000 is accessible

### "Empty plan returned"

- Check alert format (must include "Detected" and "threat level")
- Verify LLM API key is configured
- Check Planner logs for errors
