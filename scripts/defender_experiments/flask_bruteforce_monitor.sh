#!/bin/bash
# Monitoring script to track Flask brute force progress
# Run this inside the compromised container to monitor when Flask port becomes blocked
# This script starts AT THE SAME TIME as the attack script
# It waits for /tmp/flask_bruteforce_started file before actually starting pings

# Don't exit on error - we want to keep monitoring
set +e

OUTPUT_FILE="${1:-/tmp/flask_bruteforce/monitoring.json}"
FLASK_URL="http://172.31.0.10:5000/login"
SAMPLE_INTERVAL=1  # Check every second
START_SIGNAL_FILE="/tmp/flask_bruteforce_started"

# Initialize monitoring - record that we started at the same time as attack
MONITOR_START_TIME=$(date -Iseconds)
echo "{\"monitor_start_time\":\"$MONITOR_START_TIME\",\"status\":\"waiting_for_bruteforce_start\"}" > "$OUTPUT_FILE"

last_success=false
success_count=0
failure_count=0
blocked_count=0
max_blocked_count=3  # 3 consecutive failures = blocked

log() {
    local key="$1"
    local value="$2"
    local timestamp=$(date -Iseconds)
    echo "{\"timestamp\":\"$timestamp\",\"$key\":\"$value\"}" >> "$OUTPUT_FILE"
}

echo "Monitoring Flask brute force to: $FLASK_URL"
echo "Output file: $OUTPUT_FILE"
echo "Checking every ${SAMPLE_INTERVAL}s"
echo "Will declare blocked after ${max_blocked_count} consecutive failures"
echo "Monitor start time: $MONITOR_START_TIME"
echo ""
echo "WAITING for brute force to start (waiting for $START_SIGNAL_FILE)..."

# Wait for the signal file to appear
while [ ! -f "$START_SIGNAL_FILE" ]; do
    sleep 0.1
done

echo "START SIGNAL RECEIVED - beginning port monitoring"
log "bruteforce_start_detected" "true"

while true; do
    # Try to connect to Flask port with timeout
    response=$(timeout 2 curl -s -X POST "$FLASK_URL" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=admin&password=test123" 2>&1)
    curl_exit=$?

    timestamp=$(date -Iseconds)

    if [[ $curl_exit -eq 0 && -n "$response" ]]; then
        # Connection successful
        if echo "$response" | grep -q "Invalid credentials"; then
            # Port is open and responding
            echo "[$timestamp] Flask port OPEN: Authentication failed (expected)"
            log "port_open" "true"
            log "auth_success" "false"

            failure_count=$((failure_count + 1))
            blocked_count=0  # Reset blocked counter
            success_count=0
        elif echo "$response" | grep -q "OK"; then
            # Successful login (shouldn't happen with test password)
            echo "[$timestamp] Flask port OPEN: Authentication succeeded (unexpected!)"
            log "port_open" "true"
            log "auth_success" "true"

            success_count=$((success_count + 1))
            blocked_count=0
            failure_count=0
        else
            # Unknown response
            echo "[$timestamp] Flask port OPEN: Unknown response"
            log "port_open" "true"
            log "response" "unknown"

            blocked_count=0
        fi
    else
        # Connection failed - port might be blocked
        blocked_count=$((blocked_count + 1))
        echo "[$timestamp] Flask port BLOCKED (consecutive: $blocked_count/$max_blocked_count)"
        log "port_blocked" "true"
        log "blocked_count" "$blocked_count"

        if [[ $blocked_count -ge $max_blocked_count ]]; then
            echo "Flask port confirmed BLOCKED after ${blocked_count} consecutive failures"
            log "block_confirmed" "true"
            log "end_time" "$(date -Iseconds)"
            log "final_status" "blocked"
            break
        fi
    fi

    sleep $SAMPLE_INTERVAL
done

# Write final summary
echo ""
echo "=== Flask Brute Force Monitoring Summary ==="
echo "Total successful connections: ${success_count}"
echo "Total failed auth attempts: ${failure_count}"
echo "Status: Blocked"

exit 0
