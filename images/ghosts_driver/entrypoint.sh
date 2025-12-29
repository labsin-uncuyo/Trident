#!/bin/bash
set -e

echo "=== GHOSTS Driver Starting ==="

# Check for parameters
GHOSTS_MODE=${GHOSTS_MODE:-shadows}
GHOSTS_REPEATS=${GHOSTS_REPEATS:-1}
GHOSTS_DELAY=${GHOSTS_DELAY:-5}
GHOSTS_NUM_QUERIES=${GHOSTS_NUM_QUERIES:-5}
GHOSTS_SCENARIO=${GHOSTS_SCENARIO:-developer_routine}
GHOSTS_ROLE=${GHOSTS_ROLE:-senior_developer_role}

# Shadows API Configuration
SHADOWS_API_URL=${SHADOWS_API_URL:-http://ghosts-shadows:5900}

# SSH credentials
SSH_HOST=${SSH_HOST:-172.30.0.10}
SSH_PORT=${SSH_PORT:-22}
SSH_USER=${SSH_USER:-labuser}
SSH_PASSWORD=${SSH_PASSWORD:-${LAB_PASSWORD:-adminadmin}}

echo "Parameters:"
echo "  - Mode: $GHOSTS_MODE (shadows only)"
echo "  - Number of queries: $GHOSTS_NUM_QUERIES"
echo "  - Scenario: $GHOSTS_SCENARIO"
echo "  - Database Role: $GHOSTS_ROLE"
echo "  - Delay between commands: $GHOSTS_DELAY seconds"
echo "  - Shadows API: $SHADOWS_API_URL"
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

if [ "$GHOSTS_MODE" = "shadows" ]; then
    echo "=== SHADOWS Mode: GHOSTS Native LLM Integration ==="
    echo "Timestamp: $(date -Iseconds)"
    
    # Configuration paths
    LLM_SCRIPT_DIR="/opt/ghosts/john_scott_llm"
    SHADOWS_CONFIG="/opt/ghosts/john_scott_llm/application_shadows.json"
    
    # Copy Shadows-enhanced application config if available
    if [ -f "$SHADOWS_CONFIG" ]; then
        echo "✓ Copying Shadows-enhanced application config..."
        cp "$SHADOWS_CONFIG" /opt/ghosts/bin/config/application.json
    fi
    
    # Wait for Shadows API to be available
    echo "Checking Shadows API availability..."
    SHADOWS_READY=false
    for i in {1..30}; do
        if curl -sf "${SHADOWS_API_URL}/health" > /dev/null 2>&1; then
            SHADOWS_READY=true
            echo "✓ Shadows API is available at $SHADOWS_API_URL"
            break
        fi
        echo "  Attempt $i/30..."
        sleep 2
    done
    
    if [ "$SHADOWS_READY" = "false" ]; then
        echo "⚠ Shadows API not available, using static timeline as fallback"
        echo "Using static timeline..."
        cp "$LLM_SCRIPT_DIR/timeline_john_scott_llm.json" "$TIMELINE_FILE"
    else
        # Generate timeline dynamically using Shadows API
        GENERATE_SCRIPT="$LLM_SCRIPT_DIR/generate_timeline_shadows.sh"
        
        # Create timeline generator for Shadows if it doesn't exist
        if [ ! -f "$GENERATE_SCRIPT" ]; then
            echo "Creating Shadows timeline generator..."
            cat > "$GENERATE_SCRIPT" << 'SHADOWSGEN'
#!/bin/bash
# Timeline generator using Shadows API
set -e

SHADOWS_API_URL=${SHADOWS_API_URL:-http://ghosts-shadows:5900}
NUM_QUERIES=${NUM_QUERIES:-5}
OUTPUT_FILE=${OUTPUT_FILE:-/opt/ghosts/bin/config/timeline.json}

# Generate queries using Shadows
QUERY_SCRIPT="/opt/ghosts/john_scott_llm/generate_queries_shadows.sh"
chmod +x "$QUERY_SCRIPT"

QUERIES=$("$QUERY_SCRIPT")
export QUERIES

# Convert to timeline format
python3 << 'PYEOF'
import json
import os
import sys

queries = os.environ.get('QUERIES', '').strip().split('\n')
queries = [q.strip() for q in queries if q.strip()]

timeline = {
    "Status": "Run",
    "TimeLineHandlers": [
        {
            "HandlerType": "Bash",
            "Initial": "",
            "UtcTimeOn": "00:00:00",
            "UtcTimeOff": "24:00:00",
            "Loop": False,
            "TimeLineEvents": []
        }
    ]
}

for i, query in enumerate(queries):
    event = {
        "Command": f"sshpass -p \"${{SSH_PASSWORD}}\" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${{SSH_PORT}} ${{SSH_USER}}@${{SSH_HOST}} \"psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb -c '{query}'\"",
        "CommandArgs": [],
        "DelayBefore": int(os.environ.get('DELAY_BEFORE', '5000')),
        "DelayAfter": int(os.environ.get('DELAY_AFTER', '10000'))
    }
    timeline["TimeLineHandlers"][0]["TimeLineEvents"].append(event)

output_file = os.environ.get('OUTPUT_FILE', '/opt/ghosts/bin/config/timeline.json')
with open(output_file, 'w') as f:
    json.dump(timeline, f, indent=2)

print(f"Timeline generated with {len(queries)} commands")
PYEOF
SHADOWSGEN
            chmod +x "$GENERATE_SCRIPT"
        fi
        
        if [ -f "$GENERATE_SCRIPT" ]; then
            echo ""
            echo "=== Generating Timeline with Shadows API ==="
            
            # Remove old timeline to force regeneration
            rm -f "$TIMELINE_FILE"
            
            # Export variables for the Shadows scripts
            export NUM_QUERIES="$GHOSTS_NUM_QUERIES"
            export SCENARIO="$GHOSTS_SCENARIO"
            export ROLE="$GHOSTS_ROLE"
            export DELAY_BEFORE=$((GHOSTS_DELAY * 1000))
            export DELAY_AFTER=$((GHOSTS_DELAY * 2000))
            export OUTPUT_FILE="$TIMELINE_FILE"
            export SHADOWS_API_URL="$SHADOWS_API_URL"
            
            echo "Shadows Generation Parameters:"
            echo "  - NUM_QUERIES: $NUM_QUERIES"
            echo "  - SCENARIO: $SCENARIO"
            echo "  - ROLE: $ROLE"
            echo "  - Shadows API: $SHADOWS_API_URL"
            echo ""
            
            # Run the Shadows timeline generator
            if "$GENERATE_SCRIPT"; then
                echo "✓ Shadows-generated timeline created successfully"
                
                # Verify the generated timeline
                if [ -f "$TIMELINE_FILE" ]; then
                    NUM_COMMANDS=$(grep -c '"Command":' "$TIMELINE_FILE" 2>/dev/null || echo 0)
                    echo "✓ Timeline contains $NUM_COMMANDS Shadows-generated commands"
                    
                    # Show first few queries for debugging
                    echo ""
                    echo "=== Generated SQL Queries Preview (Shadows) ==="
                    grep '"Command":' "$TIMELINE_FILE" | head -3 | while read line; do
                        echo "  $line" | cut -c1-100
                    done
                    echo "  ..."
                fi
            else
                echo "⚠ Shadows generation failed, using static fallback timeline"
                cp "$LLM_SCRIPT_DIR/timeline_john_scott_llm.json" "$TIMELINE_FILE"
            fi
        else
            echo "⚠ Shadows generator creation failed, using static fallback"
            cp "$LLM_SCRIPT_DIR/timeline_john_scott_llm.json" "$TIMELINE_FILE"
        fi
    fi
    
    # Expand environment variables in the generated timeline
    if [ -f "$TIMELINE_FILE" ]; then
        echo ""
        echo "Expanding environment variables in timeline..."
        cp "$TIMELINE_FILE" "${TIMELINE_FILE}.original"
        # Only substitute SSH_* variables to avoid breaking SQL dollar-quoted strings ($$)
        envsubst '$SSH_PASSWORD $SSH_PORT $SSH_USER $SSH_HOST' < "${TIMELINE_FILE}.original" > "$TIMELINE_FILE"
        echo "✓ Environment variables expanded (SSH credentials)"
    fi
    
    NUM_COMMANDS=$(grep -c '"Command":' "$TIMELINE_FILE" 2>/dev/null || echo 0)
    echo ""
    echo "=== SHADOWS Mode Ready ==="
    echo "✓ Timeline ready with $NUM_COMMANDS commands"
    
else
    echo "⚠ Invalid GHOSTS_MODE: $GHOSTS_MODE"
    echo "Only 'shadows' mode is supported."
    echo "Using static timeline as fallback..."
    cp "/opt/ghosts/john_scott_llm/timeline_john_scott_llm.json" "$TIMELINE_FILE"
    
    # Expand environment variables
    if [ -f "$TIMELINE_FILE" ]; then
        cp "$TIMELINE_FILE" "${TIMELINE_FILE}.original"
        envsubst '$SSH_PASSWORD $SSH_PORT $SSH_USER $SSH_HOST' < "${TIMELINE_FILE}.original" > "$TIMELINE_FILE"
        echo "✓ Environment variables expanded (SSH credentials)"
    fi
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
