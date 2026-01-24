#!/bin/bash
# Script to run from compromised container to trigger PASSWORD_GUESSING
# This ensures traffic routes through the router and gets captured

TARGET_IP="172.31.0.10"
TARGET_PORT="5000"
ATTEMPTS=20

echo "Sending ${ATTEMPTS} login attempts from compromised container..."
echo "Target: ${TARGET_IP}:${TARGET_PORT}/login"
echo

# Use a simple loop with subshells for parallel execution
for i in $(seq 1 $ATTEMPTS); do
    (curl -s -X POST "http://${TARGET_IP}:${TARGET_PORT}/login" \
        -d "username=user${i}&password=pass${i}" \
        --connect-timeout 5 \
        --max-time 10 > /dev/null 2>&1 && echo "[$i] ✓") &
done

wait
echo
echo "All ${ATTEMPTS} attempts completed!"
