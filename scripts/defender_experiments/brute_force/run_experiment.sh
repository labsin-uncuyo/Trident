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
MAX_EXPERIMENT_TIME=1530  # 25.5 minutes (increased by 70%)
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

# Wait for containers to be fully started
log "Waiting for containers to stabilize (20s)..."
sleep 20

# Verify core services are healthy using docker health checks
log "Checking core services health..."
max_wait=60
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    # Check if all core containers are healthy
    if docker ps --format "{{.Names}}:{{.Status}}" | grep -q "lab_compromised.*healthy" && \
       docker ps --format "{{.Names}}:{{.Status}}" | grep -q "lab_server.*healthy" && \
       docker ps --format "{{.Names}}:{{.Status}}" | grep -q "lab_router.*healthy"; then
        log_success "Core services are healthy!"
        break
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    if [ $((elapsed % 15)) -eq 0 ]; then
        log "Still waiting for core services... (${elapsed}s elapsed)"
    fi
done

if [ $elapsed -ge $max_wait ]; then
    log_error "Core services failed to become healthy within ${max_wait}s"
    docker ps --format "table {{.Names}}\t{{.Status}}"
    exit 1
fi

# Verify network connectivity
log "Verifying network connectivity..."
if ! docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:80; then
    log_error "Server not reachable from compromised"
    exit 1
fi
log_success "Network connectivity verified!"

# Wait for Flask app to be ready
log "Waiting for Flask app to be ready..."
max_wait=60  # 1 minute max
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    if docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:443/login 2>/dev/null; then
        log_success "Flask app is ready!"
        break
    fi
    sleep 3
    elapsed=$((elapsed + 3))
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

    # Wait for defender containers to be healthy
    log "Waiting for defender containers to stabilize..."
    sleep 15

    log "Waiting for defender to be ready..."
    max_wait=90
    elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        # Check if defender container is healthy
        if docker ps --format "{{.Names}}:{{.Status}}" | grep -q "lab_slips_defender.*healthy"; then
            # Also verify defender API is responding
            if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
                log_success "Defender is ready!"
                break
            fi
        fi
        sleep 5
        elapsed=$((elapsed + 5))
        if [ $((elapsed % 15)) -eq 0 ]; then
            log "Still waiting for defender... (${elapsed}s elapsed)"
        fi
    done

    if [ $elapsed -ge $max_wait ]; then
        log_error "Defender failed to become ready within ${max_wait}s"
        docker ps --format "table {{.Names}}\t{{.Status}}"
        exit 1
    fi
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
first_plan_count=0
first_successful_exec_time=""
opencode_complete_time=""
flask_blocked_time=""
experiment_end_reason=""

# Per-IP tracking
declare -A ip_plan_time
declare -A ip_exec_start_time
declare -A ip_exec_end_time
declare -A ip_exec_duration
declare -A ip_plan_content

log "Monitoring experiment progress (max ${MAX_EXPERIMENT_TIME}s)..."
log "Will terminate when:"
log "  1. BOTH: Flask port is blocked AND OpenCode execution complete"
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

        # Check for plan generation
        if [[ -z "$first_plan_time" ]]; then
            first_plan=$(grep '"level":"PLAN"' "$defender_timeline" | head -1 || true)

            if [[ -n "$first_plan" ]]; then
                first_plan_time=$(echo "$first_plan" | grep -o '"ts":"[^"]*"' | cut -d'"' -f4)

                # Extract number of plans
                first_plan_count=$(echo "$first_plan" | jq -r '.data.num_plans // 1' 2>/dev/null || echo "1")

                # Extract per-IP plan information
                # Parse the plans array to get executor_host_ip for each plan
                num_plans=$first_plan_count
                for ((i=0; i<num_plans; i++)); do
                    # Extract executor IP for this plan
                    plan_json=$(echo "$first_plan" | jq -c ".data.plans[$i]" 2>/dev/null || echo "{}")
                    if [[ "$plan_json" != "{}" ]] && [[ "$plan_json" != "null" ]]; then
                        plan_ip=$(echo "$plan_json" | jq -r '.executor_host_ip // empty' 2>/dev/null)
                        plan_plan=$(echo "$plan_json" | jq -r '.plan // empty' 2>/dev/null)

                        if [[ -n "$plan_ip" ]]; then
                            ip_plan_time["$plan_ip"]="$first_plan_time"
                            ip_plan_content["$plan_ip"]="$plan_plan"
                            log "Plan generated for IP $plan_ip at: $first_plan_time"
                        fi
                    fi
                done

                log "Plan generated at: $first_plan_time (total plans: $num_plans)"
            fi
        fi

        # Check for OpenCode execution (per-IP)
        # Look for EXEC entries with executor_ip data
        exec_entries=$(grep '"level":"EXEC".*"executor_ip"' "$defender_timeline" 2>/dev/null || true)

        if [[ -n "$exec_entries" ]]; then
            # Track per-IP execution start times
            while IFS= read -r exec_entry; do
                exec_ip=$(echo "$exec_entry" | jq -r '.data.executor_ip // empty' 2>/dev/null)
                exec_ts=$(echo "$exec_entry" | jq -r '.ts // empty' 2>/dev/null)

                if [[ -n "$exec_ip" ]] && [[ -n "$exec_ts" ]]; then
                    # Only record first execution start per IP
                    if [[ -z "${ip_exec_start_time[$exec_ip]:-}" ]]; then
                        ip_exec_start_time["$exec_ip"]="$exec_ts"
                        log "OpenCode execution started for IP $exec_ip at: $exec_ts"

                        # Set overall first execution time if not set
                        if [[ -z "$first_successful_exec_time" ]]; then
                            first_successful_exec_time="$exec_ts"
                        fi
                    fi
                fi
            done <<< "$exec_entries"
        fi

        # Check for overall first execution time from container logs (fallback)
        if [[ -z "$first_successful_exec_time" ]]; then
            opencodetime_from_container=$(docker exec lab_compromised cat /tmp/opencode_exec_times.log 2>/dev/null | grep '^OPENCODE_START=' | cut -d= -f2 | head -1 || true)
            if [[ -n "$opencodetime_from_container" ]]; then
                first_successful_exec_time="$opencodetime_from_container"
                log "OpenCode execution start time from container: $first_successful_exec_time"
            fi
        fi

        # Check for OpenCode completion per-IP (DONE or EXEC with status=success)
        done_entries=$(grep '"level":"DONE".*"status":"success"' "$defender_timeline" 2>/dev/null || true)
        if [[ -n "$done_entries" ]]; then
            while IFS= read -r done_entry; do
                # Extract IP from the exec field (format: base_exec_id_IP)
                exec_id=$(echo "$done_entry" | jq -r '.exec // empty' 2>/dev/null)
                done_ts=$(echo "$done_entry" | jq -r '.ts // empty' 2>/dev/null)

                if [[ -n "$exec_id" ]] && [[ -n "$done_ts" ]]; then
                    # Extract IP from exec_id (format: hash_172_31_0_10 or hash_172_30_0_10)
                    ip_part=$(echo "$exec_id" | grep -oE '[0-9]+_[0-9]+_[0-9]+_[0-9]+$' | head -1 || true)
                    if [[ -n "$ip_part" ]]; then
                        # Convert underscores back to dots
                        ip=$(echo "$ip_part" | tr '_' '.')
                        ip_exec_end_time["$ip"]="$done_ts"
                        log "OpenCode execution completed for IP $ip at: $done_ts"
                    fi
                fi
            done <<< "$done_entries"
        fi

        # Also check opencodetime logs from containers for completion
        for container in lab_server lab_compromised; do
            if docker exec "$container" test -f /tmp/opencode_exec_times.log 2>/dev/null; then
                opencodetime_end=$(docker exec "$container" cat /tmp/opencode_exec_times.log 2>/dev/null | grep '^OPENCODE_END=' | cut -d= -f2 | cut -d' ' -f1 | head -1 || true)
                if [[ -n "$opencodetime_end" ]]; then
                    # Determine which IP this container represents
                    if [[ "$container" == "lab_server" ]]; then
                        ip="172.31.0.10"
                    else
                        ip="172.30.0.10"
                    fi

                    if [[ -z "${ip_exec_end_time[$ip]:-}" ]]; then
                        ip_exec_end_time["$ip"]="$opencodetime_end"
                        log "OpenCode execution completed for IP $ip from container log: $opencodetime_end"
                    fi

                    # Set overall completion time if not set
                    if [[ -z "$opencode_complete_time" ]]; then
                        opencode_complete_time="$opencodetime_end"
                    fi
                fi
            fi
        done

        # Check if Flask is already blocked and OpenCode complete
        if [[ -n "$opencode_complete_time" ]]; then
            if [[ "$flask_status" == "blocked" ]]; then
                log "✓ Flask already blocked, both conditions met"
                experiment_end_reason="both_complete"
                break
            fi
        fi
    fi

    # Check Flask monitoring for block status
    if [[ "$flask_status" == "blocked" && -z "$flask_blocked_time" ]]; then
        flask_blocked_time=$(docker exec lab_compromised cat /tmp/flask_bruteforce/monitoring.json 2>/dev/null | grep '"end_time"' | grep -o '"end_time":"[^"]*"' | cut -d'"' -f4 | tail -1)
        log "✓ Flask port blocked at: ${flask_blocked_time:-unknown}"

        # Check if we already have OpenCode execution complete
        if [[ -n "$opencode_complete_time" ]]; then
            log "✓ OpenCode execution already completed at: $opencode_complete_time"
            log "Termination condition met: BOTH Flask blocked AND OpenCode execution complete"
            experiment_end_reason="both_complete"
            break
        else
            log "Waiting for OpenCode execution to complete..."
        fi
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
            log "  ⏳ Waiting for: OpenCode execution start"
        else
            log "  ✓ OpenCode started: $first_successful_exec_time"
        fi

        if [[ -z "$opencode_complete_time" ]]; then
            log "  ⏳ Waiting for: OpenCode execution complete"
        else
            log "  ✓ OpenCode completed: $opencode_complete_time"
        fi

        if [[ "$flask_status" != "blocked" ]]; then
            log "  ⏳ Waiting for: Flask port to be blocked"
        else
            log "  ✓ Flask port blocked"
        fi

        # NEW: Check if attack succeeded but defender didn't respond (early termination)
        if [[ $elapsed -ge 300 ]]; then  # After 5 minutes
            # Check if password was found in the attack
            if [[ -f "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" ]]; then
                if grep -q "SUCCESS: Password found" "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" 2>/dev/null; then
                    log "⚠️  Attack succeeded (password found) but defender didn't respond after ${elapsed}s"
                    log "⚠️  Ending experiment early - defender unresponsive"
                    experiment_end_reason="attack_success_no_defender"
                    break
                fi
            fi
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

# Copy OpenCode execution time log from compromised container
docker cp lab_compromised:/tmp/opencode_exec_times.log "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true

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

# Try to get OpenCode execution time from the copied log file if not already set
if [[ -z "$first_successful_exec_time" ]] && [[ -f "$EXPERIMENT_OUTPUTS/logs/opencode_exec_times.log" ]]; then
    first_successful_exec_time=$(grep '^OPENCODE_START=' "$EXPERIMENT_OUTPUTS/logs/opencode_exec_times.log" 2>/dev/null | cut -d= -f2 | head -1 || true)
    if [[ -n "$first_successful_exec_time" ]]; then
        log "Found OpenCode execution start time in copied log: $first_successful_exec_time"
    fi
fi

# Get OpenCode completion time from the copied log file if not already set
if [[ -z "$opencode_complete_time" ]] && [[ -f "$EXPERIMENT_OUTPUTS/logs/opencode_exec_times.log" ]]; then
    opencode_complete_time=$(grep '^OPENCODE_END=' "$EXPERIMENT_OUTPUTS/logs/opencode_exec_times.log" 2>/dev/null | cut -d= -f2 | cut -d' ' -f1 | head -1 || true)
    if [[ -n "$opencode_complete_time" ]]; then
        log "Found OpenCode completion time in copied log: $opencode_complete_time"
    fi
fi

# Calculate OpenCode execution duration per-IP
for ip in "${!ip_exec_start_time[@]}"; do
    start_time="${ip_exec_start_time[$ip]}"
    end_time="${ip_exec_end_time[$ip]:-}"

    if [[ -n "$start_time" ]] && [[ -n "$end_time" ]]; then
        start_epoch=$(to_epoch "$start_time")
        end_epoch=$(to_epoch "$end_time")
        if [[ $start_epoch -gt 0 ]] && [[ $end_epoch -gt 0 ]]; then
            duration=$((end_epoch - start_epoch))
            ip_exec_duration["$ip"]=$duration
            log "OpenCode execution duration for IP $ip: ${duration}s"
        fi
    fi
done

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

# First check Flask attack log for password found (more reliable)
if [[ -f "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" ]]; then
    # Check if password was found in attack log
    if grep -q "SUCCESS: Password found" "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" 2>/dev/null; then
        password_found="true"
        # Extract the successful attempt timestamp
        flask_successful_attempt_time=$(grep "SUCCESS: Password found" "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" | head -1 | grep -o '\[.*\]' | tr -d '[]' | date -Iseconds -f- 2>/dev/null || echo "null")
        log "Password found in Flask attack log at: $flask_successful_attempt_time"
    fi
fi

# Then parse Flask login attempt logs from server
if [[ -f "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" ]]; then
    flask_login_attempts=$(wc -l < "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | tr -d ' ' || echo "0")
    flask_successful_attempts=$(grep -c '"success":true' "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | tr -d ' ' || echo "0")

    # Get first and last attempt timestamps
    flask_first_attempt_time=$(head -1 "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | grep -o '"timestamp": "[^"]*"' | cut -d'"' -f4 | head -1 || echo "null")
    flask_last_attempt_time=$(tail -1 "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | grep -o '"timestamp": "[^"]*"' | cut -d'"' -f4 | head -1 || echo "null")

    # Get successful attempt timestamp if any
    if [[ "$flask_successful_attempts" -gt 0 ]]; then
        flask_successful_attempt_time=$(grep '"success":true' "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | head -1 | grep -o '"timestamp": "[^"]*"' | cut -d'"' -f4 | head -1 || echo "null")
        password_found="true"
    fi

    log "Flask login logs: $flask_login_attempts attempts, $flask_successful_attempts successful"
else
    # Fallback to attack summary if Flask logs not available
    if [[ -f "$EXPERIMENT_OUTPUTS/logs/flask_attack_summary.json" ]]; then
        flask_login_attempts=$(grep -o '"total_attempts_before_blocked": [0-9]*' "$EXPERIMENT_OUTPUTS/logs/flask_attack_summary.json" | cut -d: -f2 | tr -d ' ' || echo "0")
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

# Helper function to output null or quoted string
json_string() {
    if [[ "$1" == "null" ]] || [[ -z "$1" ]]; then
        echo "null"
    else
        echo "\"$1\""
    fi
}

# Convert values to proper JSON format
high_conf_alert_time_json=$(json_string "$high_confidence_alert_time")
first_plan_time_json=$(json_string "$first_plan_time")
first_exec_time_json=$(json_string "$first_successful_exec_time")
opencode_complete_time_json=$(json_string "$opencode_complete_time")
flask_blocked_time_json=$(json_string "$flask_blocked_time")
first_attempt_json=$(json_string "$flask_first_attempt_time")
last_attempt_json=$(json_string "$flask_last_attempt_time")
successful_attempt_json=$(json_string "$flask_successful_attempt_time")

# Build per-IP metrics JSON
per_ip_metrics="{"
first_ip=true
for ip in "${!ip_plan_time[@]}"; do
    if [[ "$first_ip" == "true" ]]; then
        first_ip=false
    else
        per_ip_metrics+=","
    fi

    plan_time="${ip_plan_time[$ip]:-null}"
    exec_start="${ip_exec_start_time[$ip]:-null}"
    exec_end="${ip_exec_end_time[$ip]:-null}"
    duration="${ip_exec_duration[$ip]:-null}"

    # Calculate time deltas
    plan_epoch=$(to_epoch "$plan_time")
    exec_epoch=$(to_epoch "$exec_start")

    time_to_plan="null"
    if [[ $plan_epoch -gt 0 ]]; then
        time_to_plan=$((plan_epoch - ATTACK_START_TIME))
    fi

    time_to_exec="null"
    if [[ $exec_epoch -gt 0 ]]; then
        time_to_exec=$((exec_epoch - ATTACK_START_TIME))
    fi

    per_ip_metrics+="\"$ip\":{"
    per_ip_metrics+="\"plan_time\":$(json_string "$plan_time"),"
    per_ip_metrics+="\"time_to_plan_seconds\":${time_to_plan},"
    per_ip_metrics+="\"exec_start_time\":$(json_string "$exec_start"),"
    per_ip_metrics+="\"time_to_exec_seconds\":${time_to_exec},"
    per_ip_metrics+="\"exec_end_time\":$(json_string "$exec_end"),"
    per_ip_metrics+="\"exec_duration_seconds\":${duration}"
    per_ip_metrics+="}"
done
per_ip_metrics+="}"

# Generate JSON with error checking
if ! cat > "$EXPERIMENT_OUTPUTS/flask_brute_experiment_summary.json" << EOF
{
    "experiment_id": "$EXPERIMENT_ID",
    "attack_type": "flask_brute_force",
    "attack_start_time": "$attack_start_iso",
    "experiment_end_time": "$(date -Iseconds)",
    "total_duration_seconds": $TOTAL_DURATION,
    "end_reason": "$experiment_end_reason",
    "num_plans_generated": ${first_plan_count:-1},
    "metrics": {
        "time_to_high_confidence_alert_seconds": ${time_to_high_conf},
        "high_confidence_alert_time": ${high_conf_alert_time_json},
        "high_confidence_alert_details": ${high_conf_alert_details},
        "time_to_plan_generation_seconds": ${time_to_plan},
        "plan_generation_time": ${first_plan_time_json},
        "time_to_opencode_execution_seconds": ${time_to_exec},
        "opencode_execution_time": ${first_exec_time_json},
        "opencode_execution_end_time": ${opencode_complete_time_json:-null},
        "time_to_port_blocked_seconds": ${time_to_blocked},
        "port_blocked_time": ${flask_blocked_time_json},
        "flask_login_attempts": ${flask_login_attempts},
        "flask_successful_attempts": ${flask_successful_attempts},
        "flask_first_attempt_time": ${first_attempt_json},
        "flask_last_attempt_time": ${last_attempt_json},
        "flask_successful_attempt_time": ${successful_attempt_json},
        "password_found": ${password_found},
        "per_ip_metrics": ${per_ip_metrics}
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
log "Plans Generated: ${first_plan_count:-1}"
log ""
log "Timing Metrics:"
log "  - Time to high confidence alert: ${time_to_high_conf:-N/A}s"
log "  - Time to plan generation: ${time_to_plan:-N/A}s"
log "  - Time to OpenCode execution: ${time_to_exec:-N/A}s"
log "  - Time to port blocked: ${time_to_blocked:-N/A}s"
log ""

# Print per-IP metrics
if [[ ${#ip_plan_time[@]} -gt 0 ]]; then
    log "Per-IP Execution Details:"
    for ip in "${!ip_plan_time[@]}"; do
        log ""
        log "  IP: $ip"
        log "    - Plan generated at: ${ip_plan_time[$ip]:-N/A}"

        plan_epoch=$(to_epoch "${ip_plan_time[$ip]:-}")
        if [[ $plan_epoch -gt 0 ]]; then
            time_delta=$((plan_epoch - ATTACK_START_TIME))
            log "    - Time to plan: ${time_delta}s"
        fi

        log "    - Execution started: ${ip_exec_start_time[$ip]:-N/A}"

        exec_epoch=$(to_epoch "${ip_exec_start_time[$ip]:-}")
        if [[ $exec_epoch -gt 0 ]]; then
            time_delta=$((exec_epoch - ATTACK_START_TIME))
            log "    - Time to execution: ${time_delta}s"
        fi

        log "    - Execution ended: ${ip_exec_end_time[$ip]:-N/A}"
        log "    - Execution duration: ${ip_exec_duration[$ip]:-N/A}s"
    done
    log ""
fi

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
