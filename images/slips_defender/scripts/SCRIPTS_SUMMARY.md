# Slips Defender Scripts - Summary

## Created Scripts

### 1. `send_alert_to_planner.py`
**Main Python script for sending alerts to the Planner API**

**Features:**
- Send custom alerts via `--alert`
- Extract latest alert from logs via `--latest-alert`
- Read alerts from file via `--file`
- Interactive mode via `--interactive`
- Quiet mode via `--quiet` (just the plan)
- Automatic alert parsing from Slips logs

**Location:** `images/slips_defender/scripts/send_alert_to_planner.py`

**Dependencies:** `requests` (Python library)

### 2. `send_alert.sh`
**Bash wrapper for the Python script**

**Features:**
- Simple command-line interface
- Passes all arguments to Python script
- Checks for Python and script dependencies

**Location:** `images/slips_defender/scripts/send_alert.sh`

### 3. `README.md`
**Comprehensive documentation**

**Contents:**
- Installation instructions
- Usage examples
- Configuration options
- Troubleshooting guide
- Docker integration
- Cron job examples

**Location:** `images/slips_defender/scripts/README.md`

### 4. `QUICK_START.md`
**Quick reference guide**

**Contents:**
- Basic usage patterns
- Common alert examples
- Integration workflows
- Tips and tricks
- Output field descriptions

**Location:** `images/slips_defender/scripts/QUICK_START.md`

## Usage Examples

### Send Your Custom DNS TXT Alert
```bash
cd /home/diego/Trident
python3 images/slips_defender/scripts/send_alert_to_planner.py \
  --alert "2026-01-20T23:20:16+00:00 (TW 1): Src IP 172.30.0.10. Detected A DNS TXT answer with high entropy..."
```

### Interactive Alert Creation
```bash
python3 images/slips_defender/scripts/send_alert_to_planner.py --interactive
```

### Get Just the Plan (Quiet Mode)
```bash
python3 images/slips_defender/scripts/send_alert_to_planner.py \
  --alert "SSH brute force detected" \
  --quiet > plan.txt
```

## Integration with Trident

### Make Defend
```bash
make defend
```

### Send Alert to Planner
```bash
python3 images/slips_defender/scripts/send_alert_to_planner.py --latest-alert
```

### Clean Up
```bash
make clean
```

## What the Script Does

1. **Accepts Alert**: Takes alert text from command line, file, or interactive input
2. **Sends to API**: POSTs to `http://localhost:8000/plan`
3. **Receives Plan**: Gets incident response plan from LLM
4. **Displays Results**: Shows executor IP, threat analysis, and remediation steps

## Alert Format for Best Results

```
[TIMESTAMP] (TW N): Src IP [IP_ADDRESS]. Detected [DESCRIPTION] threat level: [LEVEL]. Confidence: [CONF].
```

Example:
```
2026-01-20T23:20:16+00:00 (TW 1): Src IP 172.30.0.10. Detected A DNS TXT answer with high entropy. query: example.com answer: "payload" entropy: 5.9 Confidence 0.8. threat level: high.
```

## Testing Your Setup

```bash
# Test with a simple alert
python3 images/slips_defender/scripts/send_alert_to_planner.py \
  --alert "Test alert. Src IP 192.168.1.1. Detected port scan. Threat level: medium."

# Test with your DNS alert
python3 images/slips_defender/scripts/send_alert_to_planner.py \
  --file /tmp/test_alert.txt

# Test quiet mode
python3 images/slips_defender/scripts/send_alert_to_planner.py \
  --alert "SSH attack detected" \
  --quiet
```

## Files Created

```
images/slips_defender/scripts/
├── send_alert_to_planner.py    # Main Python script
├── send_alert.sh                # Bash wrapper
├── README.md                    # Full documentation
├── QUICK_START.md               # Quick reference
└── SCRIPTS_SUMMARY.md           # This file
```

All scripts are executable and ready to use!
