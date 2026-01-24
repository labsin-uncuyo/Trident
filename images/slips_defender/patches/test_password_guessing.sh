#!/bin/bash
# Test script for HTTP password guessing detection
# This script simulates a brute force attack to verify the detection is working

set -e

echo "=========================================="
echo "HTTP Password Guessing Detection Test"
echo "=========================================="
echo

# Configuration
TARGET_HOST="${1:-172.31.0.10}"  # Default Flask server in Trident
TARGET_PORT="${2:-443}"
ATTEMPTS="${3:-15}"  # More than the threshold of 10
LOGIN_PATH="${4:-/login}"

echo "Test Configuration:"
echo "  Target: $TARGET_HOST:$TARGET_PORT"
echo "  Login path: $LOGIN_PATH"
echo "  Attempts: $ATTEMPTS"
echo "  Threshold: 10 (default)"
echo

echo "Starting brute force simulation..."
echo

# Simulate brute force attack
for i in $(seq 1 $ATTEMPTS); do
    USERNAME="user$i"
    PASSWORD="pass$(shuf -i 1000-9999 -n 1)"

    echo "[$i/$ATTEMPTS] Attempting login with username: $USERNAME"

    # Send POST request
    response=$(curl -s -w "\n%{http_code}" -X POST \
        "http://$TARGET_HOST:$TARGET_PORT$LOGIN_PATH" \
        -d "username=$USERNAME&password=$PASSWORD" \
        --connect-timeout 5 \
        --max-time 10 2>/dev/null || echo "000")

    # Extract status code
    status_code=$(echo "$response" | tail -n1)

    if [ "$status_code" = "000" ]; then
        echo "  ✗ Connection failed"
    elif [ "$status_code" = "401" ] || [ "$status_code" = "403" ]; then
        echo "  ✓ Login failed (expected) - HTTP $status_code"
    elif [ "$status_code" = "200" ]; then
        echo "  ⚠ Login succeeded (unexpected!) - HTTP $status_code"
    else
        echo "  Response: HTTP $status_code"
    fi

    # Small delay between attempts (more realistic)
    sleep 0.5
done

echo
echo "=========================================="
echo "Test completed!"
echo "=========================================="
echo
echo "Now check Slips for PASSWORD_GUESSING alerts:"
echo
echo "1. Check alerts log:"
echo "   docker exec slips_defender tail -50 /StratosphereLinuxIPS/output/*/alerts.log | grep -i password"
echo
echo "2. Check alerts JSON:"
echo "   docker exec slips_defender find /StratosphereLinuxIPS/output -name 'alerts.json' -exec cat {} \; | jq '.[] | select(.evidence_type == \"PASSWORD_GUESSING\")'"
echo
echo "3. Monitor in real-time:"
echo "   docker logs -f slips_defender | grep -i 'password.*guessing'"
echo
echo "Expected behavior:"
echo "  - Alert should be generated after ~10 attempts"
echo "  - Evidence type: PASSWORD_GUESSING"
echo "  - Threat level: HIGH"
echo "  - Description includes number of attempts and target endpoint"
echo
