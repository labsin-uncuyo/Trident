#!/bin/bash
set -e

echo "=== GHOSTS Driver Starting ==="

# Check for parameters
GHOSTS_MODE=${GHOSTS_MODE:-dummy}
GHOSTS_REPEATS=${GHOSTS_REPEATS:-1}
GHOSTS_DELAY=${GHOSTS_DELAY:-5}
GHOSTS_NUM_QUERIES=${GHOSTS_NUM_QUERIES:-5}
GHOSTS_SCENARIO=${GHOSTS_SCENARIO:-developer_routine}
GHOSTS_ROLE=${GHOSTS_ROLE:-senior_developer_role}

# SSH credentials (like ARACNE)
SSH_HOST=${SSH_HOST:-172.30.0.10}
SSH_PORT=${SSH_PORT:-22}
SSH_USER=${SSH_USER:-labuser}
SSH_PASSWORD=${SSH_PASSWORD:-${LAB_PASSWORD:-adminadmin}}

echo "Parameters:"
echo "  - Mode: $GHOSTS_MODE"
if [ "$GHOSTS_MODE" = "llm" ]; then
    echo "  - Number of queries: $GHOSTS_NUM_QUERIES"
    echo "  - Scenario: $GHOSTS_SCENARIO"
    echo "  - Database Role: $GHOSTS_ROLE"
    echo "  - Delay between commands: $GHOSTS_DELAY seconds"
else
    echo "  - Workflow repeats: $GHOSTS_REPEATS"
    echo "  - Delay between commands: $GHOSTS_DELAY seconds"
fi
echo "  - SSH Target: $SSH_USER@$SSH_HOST:$SSH_PORT"
echo ""

# Verify sshpass is available
if ! command -v sshpass >/dev/null 2>&1; then
    echo "✗ sshpass not found - required for password authentication"
    exit 1
fi
echo "✓ sshpass available for password authentication"

# Wait for compromised machine to be ready
echo "Waiting for compromised machine ($SSH_HOST) to be ready..."
for i in {1..30}; do
    if ping -c 1 -W 1 "$SSH_HOST" > /dev/null 2>&1; then
        echo "✓ Compromised machine is reachable"
        break
    fi
    echo "  Attempt $i/30..."
    sleep 2
done

# Test SSH connectivity (like ARACNE)
echo "Testing SSH connection to compromised machine..."
if sshpass -p "$SSH_PASSWORD" ssh \
    -o PreferredAuthentications=password \
    -o PubkeyAuthentication=no \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=5 \
    -p "$SSH_PORT" \
    "${SSH_USER}@${SSH_HOST}" "echo 'SSH connection successful'"; then
    echo "✓ SSH connection test passed"
else
    echo "✗ SSH connection test failed"
    echo "  Please verify:"
    echo "  - SSH public key is installed on compromised machine"
    echo "  - labuser exists on compromised machine"
    echo "  - SSH service is running on compromised machine"
fi

# Generate or adjust timeline based on mode
TIMELINE_FILE="/opt/ghosts/bin/config/timeline.json"

if [ "$GHOSTS_MODE" = "llm" ]; then
    echo "=== LLM Mode: Dynamic Query Generation ==="
    echo "Timestamp: $(date -Iseconds)"
    
    # Configuration paths
    LLM_SCRIPT_DIR="/opt/ghosts/john_scott_llm"
    LLM_CONFIG="/opt/ghosts/john_scott_llm/application_llm.json"
    
    # Copy LLM-enhanced application config if available
    if [ -f "$LLM_CONFIG" ]; then
        echo "✓ Copying LLM-enhanced application config..."
        cp "$LLM_CONFIG" /opt/ghosts/bin/config/application.json
        
        # Replace environment variables in config
        if [ -n "$OPENAI_API_KEY" ]; then
            sed -i "s|\${OPENAI_API_KEY}|$OPENAI_API_KEY|g" /opt/ghosts/bin/config/application.json
            echo "✓ OPENAI_API_KEY configured (${#OPENAI_API_KEY} chars)"
        fi
        if [ -n "$OPENAI_BASE_URL" ]; then
            sed -i "s|\${OPENAI_BASE_URL}|$OPENAI_BASE_URL|g" /opt/ghosts/bin/config/application.json
            echo "✓ OPENAI_BASE_URL: $OPENAI_BASE_URL"
        fi
        if [ -n "$LLM_MODEL" ]; then
            sed -i "s|\${LLM_MODEL}|$LLM_MODEL|g" /opt/ghosts/bin/config/application.json
            echo "✓ LLM_MODEL: $LLM_MODEL"
        fi
    fi
    
    # Generate timeline dynamically using LLM
    GENERATE_SCRIPT="$LLM_SCRIPT_DIR/generate_timeline_llm.sh"
    if [ -f "$GENERATE_SCRIPT" ] && [ -n "$OPENAI_API_KEY" ] && [ -n "$OPENAI_BASE_URL" ]; then
        echo ""
        echo "=== Generating Timeline with LLM ==="
        chmod +x "$GENERATE_SCRIPT"
        chmod +x "$LLM_SCRIPT_DIR/generate_queries_llm.sh" 2>/dev/null
        
        # Export variables for the LLM scripts
        export NUM_QUERIES="$GHOSTS_NUM_QUERIES"
        export SCENARIO="$GHOSTS_SCENARIO"
        export ROLE="$GHOSTS_ROLE"
        export DELAY_BEFORE=$((GHOSTS_DELAY * 1000))
        export DELAY_AFTER=$((GHOSTS_DELAY * 2000))
        export OUTPUT_FILE="$TIMELINE_FILE"
        
        echo "LLM Generation Parameters:"
        echo "  - NUM_QUERIES: $NUM_QUERIES"
        echo "  - SCENARIO: $SCENARIO"
        echo "  - ROLE: $ROLE"
        echo "  - DELAY_BEFORE: ${DELAY_BEFORE}ms"
        echo ""
        
        # Run the LLM timeline generator
        if "$GENERATE_SCRIPT"; then
            echo "✓ LLM-generated timeline created successfully"
            
            # Verify the generated timeline
            if [ -f "$TIMELINE_FILE" ]; then
                NUM_COMMANDS=$(grep -c '"Command":' "$TIMELINE_FILE" 2>/dev/null || echo 0)
                echo "✓ Timeline contains $NUM_COMMANDS LLM-generated commands"
                
                # Show first few queries for debugging
                echo ""
                echo "=== Generated SQL Queries Preview ==="
                grep '"Command":' "$TIMELINE_FILE" | head -3 | while read line; do
                    echo "  $line" | cut -c1-100
                done
                echo "  ..."
            fi
        else
            echo "⚠ LLM generation failed, using static fallback timeline"
            if [ -f "$LLM_SCRIPT_DIR/timeline_john_scott_llm.json" ]; then
                cp "$LLM_SCRIPT_DIR/timeline_john_scott_llm.json" "$TIMELINE_FILE"
            else
                cp /opt/ghosts/john_scott_dummy/timeline_john_scott.json "$TIMELINE_FILE"
            fi
        fi
    else
        echo "⚠ LLM generator not available or credentials missing"
        echo "  - Script exists: $([ -f \"$GENERATE_SCRIPT\" ] && echo 'yes' || echo 'no')"
        echo "  - API Key set: $([ -n \"$OPENAI_API_KEY\" ] && echo 'yes' || echo 'no')"
        echo "  - Base URL set: $([ -n \"$OPENAI_BASE_URL\" ] && echo 'yes' || echo 'no')"
        
        # Use static fallback
        if [ -f "$LLM_SCRIPT_DIR/timeline_john_scott_llm.json" ]; then
            echo "Using static LLM timeline as fallback..."
            cp "$LLM_SCRIPT_DIR/timeline_john_scott_llm.json" "$TIMELINE_FILE"
        else
            cp /opt/ghosts/john_scott_dummy/timeline_john_scott.json "$TIMELINE_FILE"
        fi
    fi
    
    # Adjust delays based on GHOSTS_DELAY parameter
    if [ -f "$TIMELINE_FILE" ]; then
        DELAY_MS=$((GHOSTS_DELAY * 1000))
        sed -i "s/\"DelayBefore\": [0-9]*/\"DelayBefore\": $DELAY_MS/g" "$TIMELINE_FILE"
        sed -i "s/\"DelayAfter\": [0-9]*/\"DelayAfter\": $((DELAY_MS * 2))/g" "$TIMELINE_FILE"
        echo ""
        echo "✓ Delays adjusted: ${DELAY_MS}ms before / $((DELAY_MS * 2))ms after"
    fi
    
    NUM_COMMANDS=$(grep -c '"Command":' "$TIMELINE_FILE" 2>/dev/null || echo 0)
    echo ""
    echo "=== LLM Mode Ready ==="
    echo "✓ Timeline ready with $NUM_COMMANDS commands"
    
else
    # Original dummy/hardcoded mode
    echo "Adjusting timeline with delay settings..."
    if [ -f "$TIMELINE_FILE" ]; then
        DELAY_MS=$((GHOSTS_DELAY * 1000))
        # Backup original
        cp "$TIMELINE_FILE" "${TIMELINE_FILE}.original"
        
        # Expand environment variables first (like ARACNE does)
        envsubst < "${TIMELINE_FILE}.original" > "$TIMELINE_FILE"
        
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
        echo "✓ Environment variables expanded (SSH credentials)"
    else
        echo "⚠ Timeline file not found at $TIMELINE_FILE"
    fi
fi
echo ""

# Calculate execution time for controlled termination
NUM_COMMANDS=$(grep -c '"Command":' "$TIMELINE_FILE" 2>/dev/null || echo 6)
if [ "$GHOSTS_MODE" = "llm" ]; then
    CYCLE_TIME=$((NUM_COMMANDS * GHOSTS_DELAY * 2))
    TOTAL_TIME=$((CYCLE_TIME + 60))
else
    CYCLE_TIME=$((NUM_COMMANDS * GHOSTS_DELAY * 2))
    TOTAL_TIME=$((GHOSTS_REPEATS * CYCLE_TIME))
fi
echo "Execution plan:"
echo "  - Commands per cycle: $NUM_COMMANDS"
echo "  - Time per cycle: ~$CYCLE_TIME seconds"
echo "  - Total planned time: ~$TOTAL_TIME seconds"
echo ""

# Start GHOSTS client with timeout if Loop is enabled
echo "Starting GHOSTS client..."
cd /opt/ghosts/bin

# Determine RUN_ID from environment or .current_run file
if [ -z "$RUN_ID" ]; then
    if [ -f "/outputs/.current_run" ]; then
        RUN_ID=$(cat /outputs/.current_run)
        echo "✓ RUN_ID loaded from .current_run: $RUN_ID"
    else
        RUN_ID="ghosts_$(date +%Y%m%d_%H%M%S)"
        echo "⚠ No RUN_ID found, using generated: $RUN_ID"
    fi
else
    echo "✓ RUN_ID from environment: $RUN_ID"
fi

# Setup logs directory
LOGS_DEST="/outputs/${RUN_ID}/ghosts"
mkdir -p "$LOGS_DEST"
echo "✓ Logs destination: $LOGS_DEST"

# Configure GHOSTS to write logs directly to output directory via symlink
GHOSTS_LOGS_DIR="/opt/ghosts/bin/logs"
if [ -d "$GHOSTS_LOGS_DIR" ]; then
    # Backup existing logs if any
    mv "$GHOSTS_LOGS_DIR" "${GHOSTS_LOGS_DIR}.bak" 2>/dev/null || true
fi
# Create symlink so GHOSTS writes directly to outputs
ln -sf "$LOGS_DEST" "$GHOSTS_LOGS_DIR"
echo "✓ GHOSTS logs symlinked to $LOGS_DEST"

copy_logs() {
    echo "Finalizing GHOSTS logs..."
    if [ -n "$RUN_ID" ]; then
        # If symlink exists, logs are already in place
        if [ -L "$GHOSTS_LOGS_DIR" ]; then
            echo "✓ Logs already in $LOGS_DEST (via symlink)"
        elif [ -d "$GHOSTS_LOGS_DIR" ]; then
            # Fallback: copy if symlink failed
            cp -r "$GHOSTS_LOGS_DIR"/* "$LOGS_DEST/" 2>/dev/null || true
            echo "✓ Logs copied to $LOGS_DEST"
        fi
        
        # List log files
        if [ -d "$LOGS_DEST" ]; then
            echo "Log files:"
            ls -lh "$LOGS_DEST" 2>/dev/null || echo "  (empty)"
            
            # Count log entries
            LOG_LINES=$(wc -l "$LOGS_DEST"/*.log 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
            echo "Total log lines: $LOG_LINES"
        fi
    else
        echo "⚠ RUN_ID not set, logs not saved to outputs"
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
