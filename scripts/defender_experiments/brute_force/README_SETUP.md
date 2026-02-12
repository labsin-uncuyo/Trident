# Flask Brute Force Experiment - Setup and Configuration

## Overview

This experiment tests SLIPS defender's ability to detect HTTP password guessing attacks against a Flask login application. The attacker (compromised host) performs a brute force attack against the Flask application on the server.

## How It Works

### Attack Flow
1. **Attacker** (`lab_compromised` - 172.30.0.10) sends HTTP POST requests to `/login` on **Server** (`lab_server` - 172.31.0.10:443)
2. **Router** captures all traffic on eth1 interface (compromised network side) to PCAP files
3. **SLIPS Defender** analyzes PCAP files using Zeek and http_analyzer module
4. **Detection**: When 10+ login attempts are detected within 5 minutes, a high-severity alert is generated
5. **Auto_responder** receives alert and executes remediation plan via SSH

### Network Topology
```
lab_net_a (172.30.0.0/24)          lab_net_b (172.31.0.0/24)
┌─────────────────────┐         ┌─────────────────────┐
│  lab_compromised    │         │   lab_server         │
│  172.30.0.10        │────────▶│  172.31.0.10        │
│  (Attacker)          │ eth1/eth0│  (Flask App)        │
└─────────────────────┘         └─────────────────────┘
         ▲                                 │
         │                                 │
    ┌────┴─────────────────────────────────┴────┐
    │         lab_router                     │
    │         172.30.0.1 / 172.31.0.1          │
    │         - Captures PCAPs on eth1       │
    └──────────────────────────────────────────┘
```

## Configuration

### Attack Configuration (`flask_brute_attack.sh`)

**Current Optimal Settings:**
```bash
# Number of password attempts
ATTEMPTS=40

# Delay between attempts (seconds)
SLEEP_TIME=0.1

# Target
TARGET="http://172.31.0.10:443/login"

# Total duration: ~6 seconds (well within 30s PCAP window)
```

**Why These Settings Work:**
- **40 attempts** provides sufficient attempts to exceed the 10-attempt threshold
- **0.1s delay** ensures rapid execution while allowing network processing
- **Total ~6 seconds** fits comfortably within the 30-second PCAP rotation window
- **Detection threshold**: 10 attempts within 5 minutes (configured in http_analyzer.py)

### SLIPS Configuration

**Password Guessing Detection** (`http_analyzer.py`):
```python
# Line 72: Detection threshold
password_guessing_threshold = 10

# Line 73-79: Login paths to monitor
login_paths = [
    "/login",
    "/login/",
    "/signin",
    "/signin/",
    "/auth",
    "/auth/",
    "/auth/login",
    "/auth/login/",
]

# Line 165-171: Time window for counting attempts (5 minutes)
cutoff_time = current_time - 300  # 300 seconds = 5 minutes
```

**Key Detection Logic** (lines 119-184):
1. Monitors only POST requests to login endpoints
2. Tracks attempts per source IP (`self.login_attempts[src_ip]`)
3. Counts attempts within last 5 minutes
4. When threshold (10) is exceeded, triggers alert and clears counter

## Critical Fixes Applied

### 1. PCAP Capture Interface (CRITICAL)

**Problem**: Using `-i any` created "Linux cooked v2" link-layer headers that Zeek couldn't parse correctly, resulting in empty http.log files.

**Solution** (`images/router/entrypoint.sh:117`):
```bash
# OLD (broken):
tcpdump -U -s 0 -i any ...

# NEW (working):
tcpdump -U -s 0 -i eth1 ...
```

**Why eth1?**
- eth1 connects to network A where compromised host lives
- Captures traffic from 172.30.0.10 with correct source IP
- Produces PCAPs Zeek can parse (though still shows as "cooked v2" in `file` command)

### 2. SSH Key Setup for Auto_responder

**Problem**: SSH keys weren't mounted in containers, causing "Permission denied (publickey,password)" errors.

**Solution** (`docker-compose.yml`):
```yaml
services:
  compromised:
    volumes:
      - auto_responder_ssh_keys:/root/.ssh_auto_responder:ro  # ADDED

  server:
    volumes:
      - auto_responder_ssh_keys:/root/.ssh_auto_responder:ro  # ADDED

  slips_defender:
    volumes:
      - auto_responder_ssh_keys:/root/.ssh  # Already existed
```

**Server Entrypoint Fix** (`images/server/entrypoint.sh:54-62`):
```bash
# OLD (broken - hardcoded user):
chown -R admin:admin /home/admin/.ssh

# NEW (working - uses $LOGIN_USER):
if id -u "${LOGIN_USER}" >/dev/null 2>&1; then
    admin_home=$(getent passwd "${LOGIN_USER}" | cut -d: -f6)
    mkdir -p "${admin_home}/.ssh"
    # ... install key ...
    chown -R "${LOGIN_USER}:${LOGIN_USER}" "${admin_home}/.ssh"
fi
```

### 3. HTTP Analyzer Compatibility Issues

**Problem**: AttributeError when http_analyzer tried to call non-existent DBManager methods.

**Solution**: Commented out problematic functions (`images/slips_defender/patches/http_analyzer/http_analyzer.py`):
```python
# Lines 421-436: Disabled get_user_agent_info()
# DISABLED: get_user_agent_info causes AttributeError
# if not cached_ua or (
#     isinstance(cached_ua, dict)
#     and cached_ua.get("user_agent", "") != flow.user_agent
#     and "server-bag" not in flow.user_agent
# ):
#     self.get_user_agent_info(flow.user_agent, profileid)
```

Added try/except blocks around other problematic functions (lines 393-421).

## Verification

### Check Detection Works

```bash
# 1. Start infrastructure
make up
make defend

# 2. Run attack
docker cp scripts/defender_experiments/brute_force/flask_brute_attack.sh \
  lab_compromised:/tmp/flask_brute_attack.sh
docker exec lab_compromised chmod +x /tmp/flask_brute_attack.sh
docker exec lab_compromised /tmp/flask_brute_attack.sh test_run

# 3. Wait for SLIPS processing (90 seconds)
sleep 90

# 4. Check for password guessing alert
cat outputs/logs_<RUN_ID>/slips/defender_alerts.ndjson | \
  jq -r '.raw' | grep -i "password.*guessing"

# Expected output:
# "Detected HTTP password guessing detected. Src IP 172.30.0.10
# made 10 login attempts to 172.31.0.10:443/login on port unknown.
# Detected by Slips. threat level: high."
```

### Check Zeek Parsed HTTP Traffic

```bash
# Find POST requests in Zeek logs
find outputs/logs_<RUN_ID> -name "http.log" -path "*/zeek_files/*" | \
  xargs grep '"method":"POST"' | wc -l

# Should show 40+ POST requests (one per password attempt)
```

### Check Auto_responder Worked

```bash
# Check timeline for successful SSH execution
cat outputs/logs_<RUN_ID>/auto_responder_timeline.jsonl | \
  grep -E "✓ Success|EXEC.*complete.*succeeded"

# Expected output:
# 2026-01-31T19:42:54.888827+00:00 EXEC ✓ Success on compromised
# 2026-01-31T19:42:54.889724+00:00 EXEC Parallel execution complete: 1/1 succeeded
```

## Troubleshooting

### No HTTP Traffic in Zeek Logs

**Symptoms**: http.log is empty or has 0 POST requests

**Causes**:
1. **Wrong PCAP interface**: Router using `-i any` instead of `-i eth1`
   - Check: `docker exec lab_router ps aux | grep tcpdump`
   - Fix: Rebuild router image: `docker compose build --no-cache router`

2. **PCAP not capturing traffic**: tcpdump not running
   - Check: `docker exec lab_router ps aux | grep tcpdump`
   - Verify: Should show `tcpdump -U -s 0 -i eth1`

3. **Attack didn't run**: Check attack logs
   - Check: `docker exec lab_compromised cat /tmp/flask_attack_summary.json`

### SSH Permission Denied

**Symptoms**: "Permission denied (publickey,password)" when auto_responder tries SSH

**Causes**:
1. **Keys not mounted**: Volume mount missing
   - Check: `docker exec lab_compromised ls -la /root/.ssh_auto_responder/`
   - Fix: Add volume mount in docker-compose.yml

2. **Key not in authorized_keys**:
   - Check: `docker exec lab_compromised cat /root/.ssh/authorized_keys`
   - Fix: Restart containers to trigger entrypoint key installation

3. **Wrong key path in code**: Using `id_rsa_auto` instead of `id_rsa_auto_responder`
   - Check: Already fixed in `auto_responder.py` line 52

### No Password Guessing Alert

**Symptoms**: No alert despite POST requests in http.log

**Causes**:
1. **http_analyzer module crashed**: Check errors.log
   - Fix: Disable problematic functions (get_user_agent_info)

2. **Threshold not reached**: Need more attempts
   - Fix: Increase ATTEMPTS in flask_brute_attack.sh

3. **Path mismatch**: Login URI not in login_paths
   - Check: Zeek http.log for actual URI path
   - Fix: Add path to login_paths list in http_analyzer.py

## Performance Characteristics

### SLIPS Processing Speed
- **PCAP rotation**: 30 seconds
- **Zeek analysis**: ~30-45 seconds per PCAP
- **Total detection time**: 60-90 seconds after attack completes

### Attack Throughput
- **Minimum attempts**: 10 (detection threshold)
- **Recommended**: 40 attempts (provides margin)
- **Maximum tested**: Not yet established (testing in progress)

### Time Window Constraints
- **PCAP window**: 30 seconds
- **Detection window**: 5 minutes (300 seconds) for counting attempts
- **Attack duration**: 40 attempts × 0.1s = ~6 seconds (well within limits)

## Experiment Parameters

### Variables to Adjust

**In `flask_brute_attack.sh`:**
- `ATTEMPTS`: Number of password guesses (default: 40)
- `SLEEP_TIME`: Delay between attempts (default: 0.1)

**In `http_analyzer.py`:**
- `password_guessing_threshold`: Attempts to trigger alert (default: 10)
- `login_paths`: List of login endpoint paths
- Time window: 300 seconds (hardcoded in check_password_guessing())

### What to Measure

1. **Detection Rate**: % of attacks that trigger password guessing alert
2. **Detection Latency**: Time from last attempt to alert generation
3. **False Positive Rate**: Alerts on legitimate login attempts
4. **Auto_responder Success Rate**: % of alerts where SSH remediation succeeds
5. **Performance**: Maximum attempts/second SLIPS can handle without missing detections

## Files Modified

### Configuration Files
- `images/router/entrypoint.sh` - PCAP capture interface
- `images/server/entrypoint.sh` - SSH key chown fix
- `docker-compose.yml` - SSH key volume mounts
- `scripts/defender_experiments/brute_force/flask_brute_attack.sh` - Attack parameters

### Code Patches
- `images/slips_defender/patches/http_analyzer/http_analyzer.py` - Detection logic and error handling

## Next Steps

### Stress Testing
To find maximum throughput:
1. Increase ATTEMPTS significantly (100, 200, 500+)
2. Monitor SLIPS processing time
3. Check for PCAP corruption or Zeek failures
4. Measure detection latency with high traffic volumes
5. Test auto_responder stability under load

### Additional Scenarios
- Test with different sleep times (0s, 0.05s, 0.2s, etc.)
- Test with distributed attacks from multiple IPs
- Test with other login endpoints (/signin, /auth, etc.)
- Test with HTTP vs HTTPS

---

**Last Updated**: 2026-01-31
**Status**: ✅ Working - Detection and auto_responder both functional
**Tested Configuration**: 40 attempts, 0.1s delay, 10-attempt threshold
