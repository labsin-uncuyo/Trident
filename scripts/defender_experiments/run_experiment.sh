#!/bin/bash
# Flask Brute Force Experiment Script
# Tests defender response to Flask login brute force attack
#
# Logs:
# - Time until SLIPS generates high confidence alert
# - Time to plan generation
# - Time until OpenCode execution finishes
# - Time until Flask port is blocked
#
# Termination conditions:
# 1. Flask port is blocked (10 consecutive connection failures)
# 2. 15 minutes have passed since brute force command was executed

set -e

# Configuration
EXPERIMENT_ID="${1:-flask_brute_$(date +%Y%m%d_%H%M%S)}"
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

log "Starting Flask Brute Force Experiment: $EXPERIMENT_ID"
log "Output directory: $EXPERIMENT_OUTPUTS"

# Phase 1: Start infrastructure
log "=== Phase 1: Starting Infrastructure ==="
cd "$PROJECT_ROOT"

# Set RUN_ID environment variable to match experiment ID
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

# Wait for Flask app to be ready
log "Waiting for Flask app to be ready..."
max_wait=120  # 2 minutes max
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    if docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:5000/login 2>/dev/null; then
        log_success "Flask app is ready!"
        break
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    if [ $((elapsed % 15)) -eq 0 ]; then
        log "Still waiting for Flask app... (${elapsed}s elapsed)"
    fi
done

if [ $elapsed -ge $max_wait ]; then
    log_error "Flask app failed to start within ${max_wait}s"
    exit 1
fi

# Phase 2: Start defender (skip if SKIP_DEFENDER is set)
if [[ "$SKIP_DEFENDER" == "true" ]]; then
    log "=== Phase 2: SKIPPING Defender (baseline mode) ==="

    log "Setting RUN_ID to match experiment ID: $EXPERIMENT_ID"
    echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"

    log "Defender disabled - running in baseline mode (no automated response)"
    log_success "Baseline mode configured!"
else
    log "=== Phase 2: Starting Defender ==="

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

# Phase 3: Start Flask brute force attack and monitoring
log "=== Phase 3: Starting Flask Brute Force Attack ==="

# Record attack start time BEFORE starting anything
ATTACK_START_TIME=$(date +%s)
log "Attack start time: $(date -Iseconds)"

# Copy Flask attack script to compromised container
docker cp "$SCRIPT_DIR/flask_brute_attack.sh" lab_compromised:/tmp/flask_brute_attack.sh
docker exec lab_compromised chmod +x /tmp/flask_brute_attack.sh

# Create monitoring directory in compromised container
docker exec lab_compromised mkdir -p /tmp/flask_bruteforce

# Copy monitoring script to compromised container
docker cp "$SCRIPT_DIR/flask_bruteforce_monitor.sh" lab_compromised:/tmp/flask_bruteforce_monitor.sh
docker exec lab_compromised chmod +x /tmp/flask_bruteforce_monitor.sh

# Start monitoring in background using nohup inside the container
# This starts at the SAME TIME as the attack
docker exec lab_compromised bash -c "nohup /tmp/flask_bruteforce_monitor.sh /tmp/flask_bruteforce/monitoring.json > /tmp/flask_bruteforce_monitor_stdout.log 2>&1 &"
log "Flask brute force monitoring started (synchronized with attack)"

# Execute brute force attack in background
log "Executing Flask brute force attack..."
docker exec lab_compromised /tmp/flask_brute_attack.sh "$EXPERIMENT_ID" > "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" 2>&1 &
ATTACK_PID=$!

log "Flask brute force attack started (container PID: $ATTACK_PID)"

# Phase 5: Monitor for experiment end conditions
log "=== Phase 5: Monitoring Experiment Progress ==="

# Variables to track experiment state
high_confidence_alert_time=""
first_plan_time=""
first_successful_exec_time=""
flask_blocked_time=""
experiment_end_reason=""

log "Monitoring experiment progress (max ${MAX_EXPERIMENT_TIME}s)..."
log "Will terminate when:"
log "  1. Flask port is blocked (3 consecutive connection failures)"
log "  2. OR ${MAX_EXPERIMENT_TIME}s have passed since brute force started"

# Monitoring loop
while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - ATTACK_START_TIME))

    # Check timeout
    if [[ $elapsed -ge $MAX_EXPERIMENT_TIME ]]; then
        log_warning "Experiment timeout (${MAX_EXPERIMENT_TIME}s elapsed)"
        experiment_end_reason="timeout"
        break
    fi

    # Check Flask monitoring status
    flask_status=$(docker exec lab_compromised cat /tmp/flask_bruteforce/monitoring.json 2>/dev/null | grep -o '"final_status":"[^"]*"' | cut -d'"' -f4 | tail -1)

    # Parse defender timeline for key events
    defender_timeline="$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl"

    if [[ -f "$defender_timeline" ]]; then
        # Check for high confidence alert
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
            fi
        fi
    fi

    # Check Flask monitoring for block status
    if [[ "$flask_status" == "blocked" && -z "$flask_blocked_time" ]]; then
        flask_blocked_time=$(docker exec lab_compromised cat /tmp/flask_bruteforce/monitoring.json 2>/dev/null | grep '"end_time"' | grep -o '"end_time":"[^"]*"' | cut -d'"' -f4 | tail -1)
        log "✓ Flask port blocked at: ${flask_blocked_time:-unknown}"
        experiment_end_reason="flask_blocked"
        break
    fi

    # Progress update every 30 seconds
    if [[ $((elapsed % 30)) -eq 0 && $elapsed -gt 0 ]]; then
        log "Progress: ${elapsed}s elapsed"

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

        if [[ "$flask_status" != "blocked" ]]; then
            log "  ⏳ Waiting for: Flask port to be blocked"
        else
            log "  ✓ Flask port blocked"
        fi
    fi

    sleep 5
done

# Phase 6: Collect results
log "=== Phase 6: Collecting Results ==="

EXPERIMENT_END_TIME=$(date +%s)
TOTAL_DURATION=$((EXPERIMENT_END_TIME - ATTACK_START_TIME))

log "Experiment ended: $(date -Iseconds)"
log "Total duration: ${TOTAL_DURATION}s"
log "End reason: $experiment_end_reason"

# Wait for all logs to be written
sleep 10

# Copy defender timeline and detailed logs
if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" ]]; then
    cp "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" "$EXPERIMENT_OUTPUTS/logs/"
    log "Defender timeline copied"
fi
if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_detailed.log" ]]; then
    cp "$EXPERIMENT_OUTPUTS/auto_responder_detailed.log" "$EXPERIMENT_OUTPUTS/logs/"
    log "Defender detailed log copied"
fi

# Copy SLIPS output
if [[ -d "$EXPERIMENT_OUTPUTS/slips" ]]; then
    cp -r "$EXPERIMENT_OUTPUTS/slips" "$EXPERIMENT_OUTPUTS/logs/"
    log "SLIPS output copied"
fi

# Copy Flask brute force monitoring results
docker cp lab_compromised:/tmp/flask_bruteforce/monitoring.json "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
docker cp lab_compromised:/tmp/flask_attack_summary.json "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
docker cp lab_compromised:/tmp/flask_attack_log.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
docker cp lab_compromised:/tmp/nmap_discovery.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
docker cp lab_compromised:/tmp/nmap_ports.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
docker cp lab_compromised:/tmp/flask_hydra_results.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true

# Copy Flask login attempt logs from server
docker cp lab_server:/tmp/flask_login_attempts.jsonl "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
log "Flask login attempts log copied from server"

log "Flask brute force results copied"

# Collect PCAPs
log "PCAPs saved in: $EXPERIMENT_OUTPUTS/pcaps"

# Phase 7: Generate summary
log "=== Phase 7: Generating Summary ==="

# Calculate timestamps in seconds since epoch
if [[ -n "$ATTACK_START_TIME" ]]; then
    attack_start_iso=$(date -d @$ATTACK_START_TIME -Iseconds 2>/dev/null || echo "$EXPERIMENT_START_TIME")
else
    attack_start_iso=$(date -Iseconds)
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
blocked_epoch=$(to_epoch "$flask_blocked_time")

# Calculate deltas
time_to_high_conf=""
time_to_plan=""
time_to_exec=""
time_to_blocked=""

if [[ $high_conf_epoch -gt 0 ]]; then
    time_to_high_conf=$((high_conf_epoch - ATTACK_START_TIME))
fi

if [[ $plan_epoch -gt 0 ]]; then
    time_to_plan=$((plan_epoch - ATTACK_START_TIME))
fi

if [[ $exec_epoch -gt 0 ]]; then
    time_to_exec=$((exec_epoch - ATTACK_START_TIME))
fi

if [[ $blocked_epoch -gt 0 ]]; then
    time_to_blocked=$((blocked_epoch - ATTACK_START_TIME))
fi

# Get attack summary data
attack_attempts="0"
password_found="false"

# Parse Flask login attempt logs from server (more accurate than attacker logs)
flask_login_attempts="0"
flask_successful_attempts="0"
flask_first_attempt_time=""
flask_last_attempt_time=""
flask_successful_attempt_time=""

if [[ -f "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" ]]; then
    flask_login_attempts=$(wc -l < "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null || echo "0")
    flask_successful_attempts=$(grep -c '"success":true' "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null || echo "0")

    # Get first and last attempt timestamps
    flask_first_attempt_time=$(head -1 "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | grep -o '"timestamp":"[^"]*"' | cut -d'"' -f4 || echo "null")
    flask_last_attempt_time=$(tail -1 "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | grep -o '"timestamp":"[^"]*"' | cut -d'"' -f4 || echo "null")

    # Get successful attempt timestamp if any
    if [[ $flask_successful_attempts -gt 0 ]]; then
        flask_successful_attempt_time=$(grep '"success":true' "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | head -1 | grep -o '"timestamp":"[^"]*"' | cut -d'"' -f4 || echo "null")
        password_found="true"
    fi

    log "Flask login logs: $flask_login_attempts attempts, $flask_successful_attempts successful"
else
    # Fallback to attack summary if Flask logs not available
    if [[ -f "$EXPERIMENT_OUTPUTS/logs/flask_attack_summary.json" ]]; then
        attack_attempts=$(grep -o '"total_attempts_before_blocked": [0-9]*' "$EXPERIMENT_OUTPUTS/logs/flask_attack_summary.json" | cut -d: -f2 | tr -d ' ' || echo "0")
        password_found=$(grep -o '"guess_password_successfully": [^,]*' "$EXPERIMENT_OUTPUTS/logs/flask_attack_summary.json" | cut -d: -f2 | tr -d ' ' || echo "false")
    fi
fi

# Get high confidence alert details
high_conf_alert_details=""
if [[ -f "$EXPERIMENT_OUTPUTS/logs/auto_responder_timeline.jsonl" ]]; then
    high_conf_alert_details=$(grep -i '"level":"ALERT"' "$EXPERIMENT_OUTPUTS/logs/auto_responder_timeline.jsonl" | \
        grep -i 'threat level: high' | head -1 | jq -c '.data.full_alert // .msg' 2>/dev/null || echo "null")
fi

# Create JSON summary
: "${experiment_end_reason:=unknown}"
: "${time_to_high_conf:=null}"
: "${high_confidence_alert_time:=null}"
: "${high_conf_alert_details:=null}"
: "${time_to_plan:=null}"
: "${first_plan_time:=null}"
: "${time_to_exec:=null}"
: "${first_successful_exec_time:=null}"
: "${time_to_blocked:=null}"
: "${flask_blocked_time:=null}"
: "${flask_login_attempts:=0}"
: "${flask_successful_attempts:=0}"
: "${flask_first_attempt_time:=null}"
: "${flask_last_attempt_time:=null}"
: "${flask_successful_attempt_time:=null}"
: "${password_found:=false}"

# Generate JSON with error checking
if ! cat > "$EXPERIMENT_OUTPUTS/flask_brute_experiment_summary.json" << EOF
{
    "experiment_id": "$EXPERIMENT_ID",
    "attack_type": "flask_brute_force",
    "attack_start_time": "$attack_start_iso",
    "experiment_end_time": "$(date -Iseconds)",
    "total_duration_seconds": $TOTAL_DURATION,
    "end_reason": "$experiment_end_reason",
    "metrics": {
        "time_to_high_confidence_alert_seconds": ${time_to_high_conf},
        "high_confidence_alert_time": "${high_confidence_alert_time}",
        "high_confidence_alert_details": ${high_conf_alert_details},
        "time_to_plan_generation_seconds": ${time_to_plan},
        "plan_generation_time": "${first_plan_time}",
        "time_to_opencode_execution_seconds": ${time_to_exec},
        "opencode_execution_time": "${first_successful_exec_time}",
        "time_to_port_blocked_seconds": ${time_to_blocked},
        "port_blocked_time": "${flask_blocked_time}",
        "flask_login_attempts": $flask_login_attempts,
        "flask_successful_attempts": $flask_successful_attempts,
        "flask_first_attempt_time": "${flask_first_attempt_time}",
        "flask_last_attempt_time": "${flask_last_attempt_time}",
        "flask_successful_attempt_time": "${flask_successful_attempt_time}",
        "password_found": ${password_found}
    }
}
EOF
then
    log_error "Failed to generate summary JSON - saving minimal summary"
    echo "{\"experiment_id\": \"$EXPERIMENT_ID\", \"error\": \"summary_generation_failed\"}" > "$EXPERIMENT_OUTPUTS/flask_brute_experiment_summary.json"
fi

# Print summary
log ""
log "=== Experiment Summary ==="
log "Experiment ID: $EXPERIMENT_ID"
log "Attack Type: Flask Brute Force"
log "End Reason: $experiment_end_reason"
log "Total Duration: ${TOTAL_DURATION}s"
log ""
log "Timing Metrics:"
log "  - Time to high confidence alert: ${time_to_high_conf:-N/A}s"
log "  - Time to plan generation: ${time_to_plan:-N/A}s"
log "  - Time to OpenCode execution: ${time_to_exec:-N/A}s"
log "  - Time to port blocked: ${time_to_blocked:-N/A}s"
log ""
log "Flask Login Data (from server logs):"
log "  - Total login attempts: $flask_login_attempts"
log "  - Successful attempts: $flask_successful_attempts"
log "  - First attempt: ${flask_first_attempt_time:-N/A}"
log "  - Last attempt: ${flask_last_attempt_time:-N/A}"
log "  - First successful: ${flask_successful_attempt_time:-N/A}"
log "  - Password found: $password_found"
log ""
log "Results saved in: $EXPERIMENT_OUTPUTS"
log "Summary saved in: $EXPERIMENT_OUTPUTS/flask_brute_experiment_summary.json"

log_success "Experiment complete!"

# Delete PCAPs to save disk space
log "Deleting PCAPs to save disk space..."
rm -rf "$EXPERIMENT_OUTPUTS/pcaps" 2>/dev/null || true
rm -rf "/home/diego/Trident/outputs/$EXPERIMENT_ID/pcaps" 2>/dev/null || true
log "PCAPs deleted"

exit 0
