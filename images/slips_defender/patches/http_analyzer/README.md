# HTTP Password Guessing Detection for Slips

This enhancement adds PASSWORD_GUESSING detection to the HTTP analyzer module in Slips, specifically targeting brute force attacks on login endpoints over ports 80 and 443.

## Overview

The modified HTTP analyzer now includes:
1. **Password guessing detection** - Tracks repeated POST requests to login endpoints
2. **Configurable threshold** - Default: 10 login attempts within 5 minutes
3. **Automatic alerting** - Generates high-confidence alerts when threshold is exceeded

## Implementation Details

### Modified Files

1. **set_evidence.py** - Added `password_guessing()` method
2. **http_analyzer.py** - Added password guessing tracking and detection logic

### Key Features

#### Detection Logic (`http_analyzer.py`)

The `check_password_guessing()` method:
- Monitors **POST requests** to login endpoints
- Tracks attempts per **source IP address**
- Uses a **sliding time window** of 5 minutes
- Removes stale attempts older than 5 minutes
- Triggers alert when threshold is exceeded

#### Monitored Endpoints

Common login paths (case-insensitive):
```
/login, /signin, /auth, /authenticate, /user/login
/account/login, /admin/login, /api/login, /api/auth
/auth/login, /sessions, /session, /logon, /sign-in
/wp-login.php, /user, /login.php, /auth.php
```

#### Alert Details

When password guessing is detected:
- **Evidence Type**: `EvidenceType.PASSWORD_GUESSING`
- **Threat Level**: `ThreatLevel.HIGH`
- **Confidence**: 0.9
- **Description**: Includes source IP, destination, port, number of attempts, and endpoint

## Configuration

### Threshold Configuration

The password guessing threshold can be adjusted in `http_analyzer.py`:

```python
# In the init() method
self.password_guessing_threshold = 10  # Default: 10 attempts
```

### Adding Custom Login Paths

To monitor additional login paths, modify the `login_paths` set:

```python
self.login_paths = {
    "/login",
    "/custom-login",  # Add your custom paths here
    # ... more paths
}
```

## Installation

### Option 1: Docker Build with Patches

1. Build the Docker image with the patched files:
```bash
cd images/slips_defender
docker build -t lab/slips_defender:latest .
```

2. Update the Dockerfile to copy the patched files:
```dockerfile
# Copy the patched HTTP analyzer files
COPY patches/http_analyzer/set_evidence.py /StratosphereLinuxIPS/modules/http_analyzer/
COPY patches/http_analyzer/http_analyzer.py /StratosphereLinuxIPS/modules/http_analyzer/
```

### Option 2: Runtime Patching

Use the provided `install_patches.sh` script to patch a running container:
```bash
cd images/slips_defender/patches
./install_patches.sh
```

## Testing

### Manual Testing

1. Simulate a brute force attack:
```bash
for i in {1..15}; do
  curl -X POST http://target-server:443/login \
    -d "username=user$i&password=pass$i"
  sleep 1
done
```

2. Check Slips logs for alerts:
```bash
docker logs slips_defender | grep -i "password_guessing"
```

### Automated Testing

Run the Flask brute force experiment:
```bash
cd scripts/defender_experiments
./flask_brute_attack.sh
```

Expected results:
- Alert should be generated within the first 10-15 login attempts
- Alert type should be `PASSWORD_GUESSING` (not just `HORIZONTAL_PORT_SCAN`)
- Threat level should be `HIGH`

## Verification

### Check if the Patch is Applied

```bash
docker exec slips_defender grep -n "check_password_guessing" /StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py
```

Expected output:
```
119:    def check_password_guessing(self, twid: str, flow) -> bool:
```

### Monitor Detection in Real-Time

```bash
# View alerts as they are generated
docker exec slips_defender tail -f /StratosphereLinuxIPS/output/*/alerts.log | grep -i password
```

## Technical Details

### Evidence Structure

```python
Evidence(
    evidence_type=EvidenceType.PASSWORD_GUESSING,
    attacker=Attacker(
        direction=Direction.SRC,
        ioc_type=IoCType.IP,
        value=flow.saddr,
    ),
    victim=Victim(
        direction=Direction.DST,
        ioc_type=IoCType.IP,
        value=flow.daddr,
    ),
    threat_level=ThreatLevel.HIGH,
    confidence=0.9,
    # Additional context included in description
)
```

### Performance Considerations

- **Memory**: Login attempts are stored per IP for 5 minutes maximum
- **CPU**: Minimal overhead - only checks POST requests to login paths
- **Storage**: No additional storage requirements

### Limitations

1. **HTTP only** - Does not detect HTTPS brute force (encrypted traffic)
2. **Path-based** - Requires known login paths (configurable)
3. **POST method** - Only detects POST-based login attempts
4. **Time window** - Uses 5-minute sliding window (adjustable)

## Troubleshooting

### Issue: No alerts generated

**Possible causes:**
1. Threshold not reached (default: 10 attempts)
2. Login path not in `login_paths` set
3. Requests not using POST method
4. Time window expired (>5 minutes between attempts)

**Solution:**
```bash
# Enable debug logging
docker exec slips_defender python3 -c "
from modules.http_analyzer.http_analyzer import HTTPAnalyzer
print('Password guessing threshold:', HTTPAnalyzer().password_guessing_threshold)
print('Login paths:', HTTPAnalyzer().login_paths)
"
```

### Issue: Too many false positives

**Solution:**
1. Increase the threshold:
```python
self.password_guessing_threshold = 20  # Increase to 20 attempts
```

2. Reduce the time window by modifying the cleanup logic:
```python
cutoff_time = current_time - 180  # 3 minutes instead of 5
```

## Future Enhancements

Potential improvements:
1. **Rate-based detection** - Detect attempts per second/minute
2. **Failed login detection** - Monitor HTTP 401/403 status codes
3. **User-agent correlation** - Detect tools like Hydra, Medusa, etc.
4. **Machine learning** - Train on known brute force patterns
5. **SSL/TLS inspection** - Detect HTTPS brute force with SSL inspection

## References

- Original implementation based on SSH password guessing in `/StratosphereLinuxIPS/modules/flowalerts/set_evidence.py`
- Slips documentation: https://stratospherelinuxips.readthedocs.io/
- Evidence types: `/StratosphereLinuxIPS/slips_files/core/structures/evidence.py`

## Authors

- Enhanced by: Trident Security Team
- Based on: Original Slips HTTP Analyzer by Alya Gomaa
