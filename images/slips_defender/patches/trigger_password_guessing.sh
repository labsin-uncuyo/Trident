#!/bin/bash
# Script to definitively trigger PASSWORD_GUESSING detection in Slips
# This script ensures 15+ POST requests to /login are sent rapidly

set -e

echo "=========================================="
echo "PASSWORD_GUESSING Detection Trigger"
echo "=========================================="
echo

TARGET_IP="172.31.0.10"
TARGET_PORT="5000"
LOGIN_PATH="/login"
ATTEMPTS=15

echo "Target: ${TARGET_IP}:${TARGET_PORT}${LOGIN_PATH}"
echo "Attempts: ${ATTEMPTS}"
echo "Threshold: 10 (will trigger after 10th attempt)"
echo

# Function to send a single login attempt
send_login() {
    local attempt_num=$1
    local username="user${attempt_num}"
    local password="pass${attempt_num}"

    curl -s -X POST \
        "http://${TARGET_IP}:${TARGET_PORT}${LOGIN_PATH}" \
        -d "username=${username}&password=${password}" \
        --connect-timeout 5 \
        --max-time 10 \
        > /dev/null 2>&1

    if [ $? -eq 0 ]; then
        echo "[$attempt_num/${ATTEMPTS}] ✓ Sent"
    else
        echo "[$attempt_num/${ATTEMPTS}] ✗ Failed"
    fi
}

echo "Sending ${ATTEMPTS} login attempts..."
echo

# Send all attempts in parallel for maximum speed
for i in $(seq 1 $ATTEMPTS); do
    send_login $i &
done

# Wait for all background jobs to complete
wait

echo
echo "=========================================="
echo "All ${ATTEMPTS} attempts sent!"
echo "=========================================="
echo

# Wait a moment for traffic to be captured
sleep 2

echo "Next steps:"
echo "1. Wait for PCAP rotation (~30 seconds)"
echo "2. Wait for Slips to process the PCAP"
echo "3. Check for PASSWORD_GUESSING alerts:"
echo
echo "   docker exec lab_slips_defender find /StratosphereLinuxIPS/output -name 'alerts.log' -mmin -5 -exec grep -l 'PASSWORD_GUESSING' {} \\;"
echo
echo "Or monitor in real-time:"
echo "   docker exec lab_slips_defender tail -f /StratosphereLinuxIPS/output/*/alerts.log | grep -i password"
echo
