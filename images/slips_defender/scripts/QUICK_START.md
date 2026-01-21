# Quick Start: send_alert_to_planner.py

## Basic Usage

### 1. Send a Custom Alert
```bash
python3 send_alert_to_planner.py --alert "YOUR_ALERT_TEXT"
```

### 2. Use Latest Alert from Logs
```bash
python3 send_alert_to_planner.py --latest-alert
```

### 3. Interactive Mode
```bash
python3 send_alert_to_planner.py --interactive
```

### 4. Quiet Mode (Just the Plan)
```bash
python3 send_alert_to_planner.py --alert "ALERT" --quiet
```

## Common Examples

### Example 1: SSH Brute Force
```bash
python3 send_alert_to_planner.py --alert "Src IP 192.168.1.100. Detected SSH password guessing. 50 failed attempts. Threat level: high. Confidence: 0.9."
```

### Example 2: DNS Tunneling
```bash
python3 send_alert_to_planner.py --alert "Src IP 10.0.0.5. Detected high entropy DNS queries. Possible data exfiltration. Threat level: high. Confidence: 0.85."
```

### Example 3: Port Scan
```bash
python3 send_alert_to_planner.py --alert "Src IP 172.16.0.10. Detected horizontal port scan. 100 ports scanned. Threat level: medium. Confidence: 0.7."
```

### Example 4: Malware Download
```bash
python3 send_alert_to_planner.py --alert "Src IP 192.168.1.50. Detected executable file download from suspicious domain. Threat level: high. Confidence: 0.95."
```

### Example 5: Your Custom Emergency DNS Alert
```bash
python3 send_alert_to_planner.py --alert "2026-01-20T23:20:16+00:00 (TW 1): Src IP 172.30.0.10. Detected A DNS TXT answer with high entropy. query: analisisconsumidoresargentina.lat answer: \"EMERGENCY SERVER ALERT...\" entropy: 5.9 Confidence 0.8. threat level: high."
```

## Integration with Slips

### Manual Workflow
1. Trigger an attack in your lab
2. Wait for Slips to generate an alert
3. Copy the alert from `alerts.log`
4. Send to planner:
   ```bash
   python3 send_alert_to_planner.py --alert "PASTED_ALERT"
   ```

### Automated Workflow
```bash
# Create a monitoring script
watch -n 10 'python3 /scripts/send_alert_to_planner.py --latest-alert'
```

### Cron Job
```cron
# Check every 5 minutes for new alerts
*/5 * * * * cd /scripts && python3 send_alert_to_planner.py --latest-alert >> /var/log/planner_requests.log 2>&1
```

## Tips

1. **Alert Format**: Include "Src IP", "Detected", "threat level" for best results
2. **Quiet Mode**: Use `--quiet` to just get the plan without metadata
3. **File Input**: Use `--file` to process alerts from a file
4. **Interactive**: Use `--interactive` for complex alerts
5. **Debugging**: Check planner API logs if request fails

## Output Fields

- **Model**: LLM used (e.g., gpt-oss-120b)
- **Request ID**: Unique tracker for your request
- **Executor Host IP**: Target host for remediation
- **Plan**: Full incident response plan with:
  - Threat Analysis
  - Immediate Actions
  - Investigation Steps
  - Remediation Actions
  - Validation Steps

## Troubleshooting

### "No alerts found"
```bash
# Specify exact file path
python3 send_alert_to_planner.py --file /home/diego/Trident/outputs/logs_20260120_230023/slips/_watch_events/alerts.log
```

### "Connection refused"
```bash
# Check if planner is running
docker ps | grep slips_defender
curl http://localhost:8000/health
```

### "Empty plan"
- Ensure alert has proper format
- Check LLM API key configuration
- Verify alert contains "Detected" and threat level

## Environment Variables

```bash
# Set custom planner URL
export PLANNER_API_URL="http://localhost:8000"

# Set default alerts directory
export DEFAULT_ALERTS_DIR="/outputs"
```
