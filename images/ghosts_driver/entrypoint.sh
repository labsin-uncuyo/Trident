#!/bin/bash
set -e

echo "=== GHOSTS Driver Starting ==="

# Check for parameters
GHOSTS_REPEATS=${GHOSTS_REPEATS:-1}
GHOSTS_DELAY=${GHOSTS_DELAY:-5}
echo "Parameters:"
echo "  - Workflow repeats: $GHOSTS_REPEATS"
echo "  - Delay between commands: $GHOSTS_DELAY seconds"
echo ""

# Verify SSH key exists
if [ ! -f /root/.ssh/id_rsa ]; then
    echo "✗ SSH private key not found at /root/.ssh/id_rsa"
    exit 1
fi
echo "✓ SSH private key configured"

# Wait for compromised machine to be ready
echo "Waiting for compromised machine (172.30.0.10) to be ready..."
for i in {1..30}; do
    if ping -c 1 -W 1 172.30.0.10 > /dev/null 2>&1; then
        echo "✓ Compromised machine is reachable"
        break
    fi
    echo "  Attempt $i/30..."
    sleep 2
done

# Test SSH connectivity
echo "Testing SSH connection to compromised machine..."
if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -i /root/.ssh/id_rsa labuser@172.30.0.10 "echo 'SSH connection successful'"; then
    echo "✓ SSH connection test passed"
else
    echo "✗ SSH connection test failed"
    echo "  Please verify:"
    echo "  - SSH public key is installed on compromised machine"
    echo "  - labuser exists on compromised machine"
    echo "  - SSH service is running on compromised machine"
fi

# Adjust timeline based on parameters
echo "Adjusting timeline with delay settings..."
TIMELINE_FILE="/opt/ghosts/bin/config/timeline.json"
if [ -f "$TIMELINE_FILE" ]; then
    DELAY_MS=$((GHOSTS_DELAY * 1000))
    # Backup original
    cp "$TIMELINE_FILE" "${TIMELINE_FILE}.original"
    
    # Adjust delays
    sed -i "s/\"DelayBefore\": [0-9]*/\"DelayBefore\": $DELAY_MS/g" "$TIMELINE_FILE"
    sed -i "s/\"DelayAfter\": [0-9]*/\"DelayAfter\": $DELAY_MS/g" "$TIMELINE_FILE"
    
    # Adjust Loop setting based on REPEATS
    if [ "$GHOSTS_REPEATS" -eq 1 ]; then
        echo "  - Setting Loop to false (single execution)"
        sed -i 's/"Loop": true/"Loop": false/g' "$TIMELINE_FILE"
    else
        echo "  - Keeping Loop enabled (will run continuously)"
    fi
    
    echo "✓ Timeline delays adjusted to $DELAY_MS ms"
else
    echo "⚠ Timeline file not found at $TIMELINE_FILE"
fi
echo ""

# Calculate execution time for controlled termination
NUM_COMMANDS=$(grep -c '"Command":' "$TIMELINE_FILE" 2>/dev/null || echo 6)
CYCLE_TIME=$((NUM_COMMANDS * GHOSTS_DELAY * 2))
TOTAL_TIME=$((GHOSTS_REPEATS * CYCLE_TIME))
echo "Execution plan:"
echo "  - Commands per cycle: $NUM_COMMANDS"
echo "  - Time per cycle: ~$CYCLE_TIME seconds"
echo "  - Total planned time: ~$TOTAL_TIME seconds"
echo ""

# Start GHOSTS client with timeout if Loop is enabled
echo "Starting GHOSTS client..."
cd /opt/ghosts/bin

copy_logs() {
    echo "Copying GHOSTS logs to outputs..."
    if [ -n "$RUN_ID" ] && [ -d "/opt/ghosts/bin/logs" ]; then
        LOGS_DEST="/outputs/${RUN_ID}/ghosts"
        mkdir -p "$LOGS_DEST"
        cp -r /opt/ghosts/bin/logs/* "$LOGS_DEST/" 2>/dev/null || true
        echo "✓ Logs copied to $LOGS_DEST"
        ls -lh "$LOGS_DEST"
        # Basic sanity check: ensure we wrote at least one log file
        if find "$LOGS_DEST" -type f | grep -q .; then
            echo "✓ Log presence check passed"
        else
            echo "✗ No log files found in $LOGS_DEST (check GHOSTS run)"
        fi
    else
        echo "⚠ RUN_ID not set or logs directory not found, skipping log copy"
    fi
}

runner_pid=""

cleanup() {
    if [ -n "$runner_pid" ] && kill -0 "$runner_pid" 2>/dev/null; then
        kill "$runner_pid" 2>/dev/null || true
        wait "$runner_pid" 2>/dev/null || true
    fi
    copy_logs
}

trap cleanup EXIT
trap cleanup TERM INT

if [ "$GHOSTS_REPEATS" -gt 1 ]; then
    # Run with timeout to stop after N cycles
    TIMEOUT_SECS=$((TOTAL_TIME + 60))
    echo "  (Will terminate after $TIMEOUT_SECS seconds)"
    timeout $TIMEOUT_SECS ./Ghosts.Client.Universal &
    runner_pid=$!
else
    # Run normally (Loop is false, will exit on its own)
    ./Ghosts.Client.Universal &
    runner_pid=$!
fi

wait "$runner_pid" 2>/dev/null || true

echo "=== GHOSTS Driver Stopped ==="
