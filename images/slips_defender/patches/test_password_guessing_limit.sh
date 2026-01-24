#!/bin/bash
# Test Script: Find Slips PCAP Processing Limit
# This script tests increasing numbers of login attempts to find where Slips fails

set -e

TARGET_IP="172.31.0.10"
TARGET_PORT="5000"
RUN_ID="logs_$(date +%Y%m%d_%H%M%S)"

echo "=========================================="
echo "Slips Password Guessing Limit Test"
echo "=========================================="
echo "Run ID: $RUN_ID"
echo "Target: ${TARGET_IP}:${TARGET_PORT}"
echo ""

# Test configurations: attempts per test
TESTS=(1 2 3 5 7 10 15 20)

# Clear any existing blocking
echo "[SETUP] Clearing iptables rules..."
docker exec lab_compromised iptables -F OUTPUT 2>/dev/null || true

for ATTEMPTS in "${TESTS[@]}"; do
    echo ""
    echo "=========================================="
    echo "TEST: ${ATTEMPTS} login attempts"
    echo "=========================================="

    # Clear previous PCAP processing state
    echo "[1/4] Waiting for previous PCAP processing to complete..."
    sleep 5

    # Send login attempts
    echo "[2/4] Sending ${ATTEMPTS} login attempts..."
    for i in $(seq 1 $ATTEMPTS); do
        docker exec lab_compromised curl -s -X POST \
            "http://${TARGET_IP}:${TARGET_PORT}/login" \
            -d "username=user${i}&password=pass${i}" >/dev/null 2>&1 &
    done
    wait
    echo "  ✓ Sent ${ATTEMPTS} requests"

    # Wait for PCAP rotation
    echo "[3/4] Waiting for PCAP rotation (35s)..."
    sleep 35

    # Get latest PCAP info
    echo "[4/4] Checking PCAP processing..."

    # Find the actual PCAP path in router
    PCAP_PATH=$(docker exec lab_router sh -c 'ls -t /outputs/logs_*/pcaps/router*.pcap 2>/dev/null | head -1')

    if [ -z "$PCAP_PATH" ]; then
        echo "  ⚠ No PCAP found in router!"
        continue
    fi

    LATEST_PCAP=$(basename "$PCAP_PATH")

    # Check PCAP size
    PCAP_SIZE=$(docker exec lab_router stat -c%s "$PCAP_PATH" 2>/dev/null || echo "0")

    echo "  PCAP: ${LATEST_PCAP}"
    echo "  Size: ${PCAP_SIZE} bytes"

    # Count port 5000 packets
    PKT_COUNT=$(docker exec lab_slips_defender python3 -c "
import scapy.all as scapy
try:
    packets = scapy.rdpcap('${PCAP_PATH}')
    tcp_5000 = [p for p in packets if p.haslayer(scapy.TCP) and (p[scapy.TCP].dport == 5000 or p[scapy.TCP].sport == 5000)]
    print(f'{len(tcp_5000)}')
except:
    print('0')
" 2>/dev/null || echo "0")

    echo "  Port 5000 packets: ${PKT_COUNT}"

    # Check if PCAP was processed
    OUTPUT_DIR=$(docker exec lab_slips_defender find /StratosphereLinuxIPS/output -name "*${LATEST_PCAP%.pcap}*" -type d | grep -v "to_" | head -1)

    if [ -n "$OUTPUT_DIR" ]; then
        # Check for alerts.log
        ALERT_LOG=$(docker exec lab_slips_defender find "${OUTPUT_DIR}" -name "alerts.log" 2>/dev/null | head -1)

        if [ -n "$ALERT_LOG" ]; then
            # Check for PASSWORD_GUESSING
            PASSWORD_ALERTS=$(docker exec lab_slips_defender grep -i "password" "${ALERT_LOG}" 2>/dev/null | wc -l || echo "0")

            if [ "$PASSWORD_ALERTS" -gt 0 ]; then
                echo "  ✅ SUCCESS: PASSWORD_GUESSING alert generated!"
                echo "  Alerts found: ${PASSWORD_ALERTS}"
                docker exec lab_slips_defender grep -i "password" "${ALERT_LOG}" | head -1 | sed 's/^/    /'
            else
                echo "  ⚠ WARNING: No PASSWORD_GUESSING alerts"
                echo "  Other alerts present: $(docker exec lab_slips_defender wc -l < "${ALERT_LOG}")"
            fi
        else
            # Check for errors
            ERROR_LOG=$(docker exec lab_slips_defender find "${OUTPUT_DIR}" -name "errors.log" 2>/dev/null | head -1)
            if [ -n "$ERROR_LOG" ] && [ -s "$ERROR_LOG" ]; then
                echo "  ❌ ERROR: Processing failed (see errors.log)"
                docker exec lab_slips_defender cat "${ERROR_LOG}" | head -10 | sed 's/^/    /'
            else
                echo "  ⚠ WARNING: No alerts.log found (processing incomplete?)"
            fi
        fi
    else
        echo "  ❌ ERROR: No output directory created (processing failed)"
    fi

    # Check defender status
    DEFENDER_STATUS=$(docker exec lab_slips_defender tail -20 /StratosphereLinuxIPS/output/defender_alerts.ndjson 2>/dev/null | grep "${LATEST_PCAP}" | tail -1)
    if echo "$DEFENDER_STATUS" | grep -q "failed"; then
        echo "  ❌ Defender marked as FAILED"
    elif echo "$DEFENDER_STATUS" | grep -q "completed"; then
        echo "  ✅ Defender marked as completed"
    else
        echo "  ⏳ Defender still processing..."
    fi

    # Wait before next test
    echo ""
    echo "Waiting 10s before next test..."
    sleep 10
done

echo ""
echo "=========================================="
echo "TEST SUMMARY"
echo "=========================================="
echo "Test completed. Review results above."
echo ""
echo "Recommendations:"
echo "1. Identify the highest attempt count that succeeded"
echo "2. Set password_guessing_threshold below this limit"
echo "3. Consider testing in production environment for accurate limits"
