#!/bin/bash
# Simple Test: Test password guessing with incremental attempts

set -e

TARGET_IP="172.31.0.10"
TARGET_PORT="5000"

echo "=========================================="
echo "Slips Password Guessing Threshold Test"
echo "=========================================="
echo ""

# Clear any blocking
docker exec lab_compromised iptables -F OUTPUT 2>/dev/null || true

# Test with different attempt counts
for ATTEMPTS in 1 2 3 5 10; do
    echo ""
    echo "TEST: ${ATTEMPTS} attempts"
    echo "----------------------------------------"

    # Send requests
    echo "Sending ${ATTEMPTS} login attempts..."
    for i in $(seq 1 $ATTEMPTS); do
        docker exec lab_compromised curl -s -X POST \
            http://${TARGET_IP}:${TARGET_PORT}/login \
            -d "username=user${i}&password=pass${i}" >/dev/null 2>&1 &
    done
    wait
    echo "  ✓ Sent ${ATTEMPTS} requests at $(date +%H:%M:%S)"

    # Wait for PCAP rotation and processing
    echo "  Waiting for processing (45s)..."
    sleep 45

    # Check latest alerts
    echo "  Checking for alerts..."
    LATEST_ALERTS=$(docker exec lab_slips_defender find /StratosphereLinuxIPS/output -name "alerts.log" -mmin -5 -type f 2>/dev/null | head -1)

    if [ -n "$LATEST_ALERTS" ]; then
        PASSWORD_COUNT=$(docker exec lab_slips_defender grep -i "password.*guessing" "$LATEST_ALERTS" 2>/dev/null | wc -l || echo "0")

        if [ "$PASSWORD_COUNT" -gt 0 ]; then
            echo "  ✅ PASSWORD_GUESSING alert FOUND!"
            docker exec lab_slips_defender grep -i "password.*guessing" "$LATEST_ALERTS" 2>/dev/null | head -1 | sed 's/^/     /'
        else
            echo "  ⚠ No PASSWORD_GUESSING alerts"
            TOTAL_ALERTS=$(docker exec lab_slips_defender wc -l < "$LATEST_ALERTS" 2>/dev/null || echo "0")
            echo "     Total alerts in file: ${TOTAL_ALERTS}"
        fi
    else
        echo "  ⚠ No recent alerts.log found"
    fi

    # Check PCAP status
    LATEST_PCAP=$(docker exec lab_router sh -c 'ls -t /outputs/logs_*/pcaps/router*.pcap 2>/dev/null | head -1')
    if [ -n "$LATEST_PCAP" ]; then
        PCAP_NAME=$(basename "$LATEST_PCAP")
        PCAP_SIZE=$(docker exec lab_router stat -c%s "$LATEST_PCAP" 2>/dev/null || echo "0")
        echo "  Latest PCAP: ${PCAP_NAME} (${PCAP_SIZE} bytes)"
    fi

    sleep 5
done

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
