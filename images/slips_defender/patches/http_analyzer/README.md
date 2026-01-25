# HTTP Password Guessing Detection

SLIPS enhancement to detect brute force attacks on HTTP login endpoints.

## Overview

Extends the SLIPS HTTP analyzer module to identify password guessing attacks by monitoring repeated POST requests to authentication endpoints.

## Detection Logic

- **Monitors**: POST requests to common login paths
- **Tracks**: Attempts per source IP address
- **Window**: Sliding 5-minute time window
- **Threshold**: Configurable (default: 10 attempts)

**Monitored Paths**: `/login`, `/signin`, `/auth`, `/authenticate`, `/user/login`, `/admin/login`, `/api/login`, `/wp-login.php`, and more (case-insensitive)

## Alert Details

When password guessing is detected:

- **Evidence Type**: `EvidenceType.PASSWORD_GUESSING`
- **Threat Level**: `ThreatLevel.HIGH`
- **Confidence**: 0.9
- **Description**: Includes source IP, destination, port, attempt count, and endpoint

## Modified Files

```
patches/http_analyzer/
├── http_analyzer.py    # Main detection logic
└── set_evidence.py     # Evidence type definitions
```

Applied during container build to:
- `/StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py`
- `/StratosphereLinuxIPS/modules/http_analyzer/set_evidence.py`

## Configuration

Adjust threshold in `http_analyzer.py`:

```python
self.password_guessing_threshold = 10  # Default: 10 attempts
```

Add custom login paths:

```python
self.login_paths = {
    "/login",
    "/custom-path",  # Add here
    # ...
}
```

## Verification

Check if patch is applied:

```bash
docker exec lab_slips_defender grep -n "check_password_guessing" \
  /StratosphereLinuxIPS/modules/http_analyzer/http_analyzer.py
```

Expected output includes line number of the detection method.

## Testing

Simulate a brute force attack:

```bash
for i in {1..15}; do
  curl -X POST http://target:443/login \
    -d "username=user$i&password=pass$i"
  sleep 1
done
```

Expected result: Alert generated within first 10-15 attempts.

## Limitations

- HTTP only (does not detect HTTPS encrypted traffic)
- Path-based (requires known login paths)
- POST method only (does not detect GET-based logins)
- Time window limited to 5 minutes (configurable)
