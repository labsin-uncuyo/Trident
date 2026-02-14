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
MAX_EXPERIMENT_TIME=3600  # 60 minutes - allow time for OpenCode to complete
PCAP_ROTATE_SECS="${PCAP_ROTATE_SECS:-30}"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../../../ && pwd)"
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

# Flag to track if we've handled a signal
SIGNAL_HANDLED=false

# Trap for cleanup on interrupt
# We do NOT trap EXIT to allow Phase 6/7 to complete on normal exit
cleanup_on_signal() {
    if [[ "$SIGNAL_HANDLED" == "true" ]]; then
        return
    fi
    SIGNAL_HANDLED=true

    log ""
    log_warning "Experiment interrupted by signal!"

    # Set end time
    EXPERIMENT_END_TIME=$(date +%s)
    if [[ -n "$ATTACK_START_TIME" ]]; then
        TOTAL_DURATION=$((EXPERIMENT_END_TIME - ATTACK_START_TIME))
    fi
    : "${experiment_end_reason:=interrupted}"

    log "End reason: $experiment_end_reason"
    log "Will attempt to collect available data and generate summary..."

    # Collect partial results and then continue to Phase 7 (summary generation)
    # Phase 6: Collect available results (may be partial)
    if [[ -d "$EXPERIMENT_OUTPUTS" ]]; then
        log "Collecting available results..."

        # Combine timeline files
        find "$EXPERIMENT_OUTPUTS/defender/" -name "auto_responder_timeline.jsonl" -exec cat {} + \
            2>/dev/null | sort -u > "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" 2>/dev/null || true

        # Copy to logs directory
        if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" ]]; then
            cp "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        fi

        for machine in server compromised; do
            if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl" ]]; then
                cp "$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl" \
                   "$EXPERIMENT_OUTPUTS/logs/auto_responder_timeline_${machine}.jsonl" 2>/dev/null || true
            fi
            if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json" ]]; then
                cp "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json" \
                   "$EXPERIMENT_OUTPUTS/logs/opencode_api_messages_${machine}.json" 2>/dev/null || true
            fi
            if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_sse_events.jsonl" ]]; then
                cp "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_sse_events.jsonl" \
                   "$EXPERIMENT_OUTPUTS/logs/opencode_sse_events_${machine}.jsonl" 2>/dev/null || true
            fi
        done

        # Try to copy logs from containers while they're still running
        docker cp lab_compromised:/tmp/flask_bruteforce/monitoring.json "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        docker cp lab_compromised:/tmp/flask_attack_summary.json "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        docker cp lab_compromised:/tmp/opencode_exec_times.log "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true

        log "Attempting to generate summary with available data..."
        # Fall through to Phase 7 (summary generation) below
    else
        log_warning "Output directory not found, skipping summary generation"
        # Clean up and exit
        cd "$PROJECT_ROOT"
        make down 2>/dev/null || true
        exit 1
    fi
}

# Only trap signals, NOT EXIT - this allows normal completion to run Phase 6/7
trap cleanup_on_signal INT TERM HUP

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
log "Waiting for containers to stabilize (30s)..."
sleep 30

# Ensure all core containers are actually running (not just Created)
for c in lab_server lab_compromised lab_router; do
    c_status=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "missing")
    if [[ "$c_status" != "running" ]]; then
        log_warning "$c is in state '$c_status', attempting to start it..."
        docker start "$c" 2>/dev/null || true
        sleep 5
    fi
done

# Verify core services are healthy using docker health checks
log "Checking core services health..."
max_wait=240
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
    log "Container statuses:"
    docker ps -a --format "table {{.Names}}\t{{.Status}}" | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log"
    # Try to show logs for non-healthy containers
    for c in lab_server lab_compromised lab_router; do
        if ! docker ps --format "{{.Names}}:{{.Status}}" | grep -q "${c}.*healthy"; then
            log_error "$c is not healthy. Last 20 lines of logs:"
            docker logs "$c" --tail 20 2>&1 | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log"
        fi
    done
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
max_wait=300  # 5 minutes max - allow time for database initialization on fresh volumes
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    if docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:80/login 2>/dev/null; then
        log_success "Flask app is ready!"
        break
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    if [ $((elapsed % 30)) -eq 0 ] && [ $elapsed -gt 0 ]; then
        log "Still waiting for Flask app... (${elapsed}s elapsed)"
    fi
done

if [ $elapsed -ge $max_wait ]; then
    log_error "Flask app failed to start within ${max_wait}s"
    docker ps --format "table {{.Names}}\t{{.Status}}"
    docker logs lab_server --tail 50
    exit 1
fi

# Wait for OpenCode server API to be available on both containers
log "Waiting for OpenCode server API to be ready..."
for container_ip in "172.31.0.10" "172.30.0.10"; do
    oc_wait=0
    oc_max=120
    while [ $oc_wait -lt $oc_max ]; do
        if curl -sf "http://${container_ip}:4096/global/health" 2>/dev/null | grep -q '"healthy":true'; then
            log_success "OpenCode server ready on ${container_ip}"
            break
        fi
        sleep 5
        oc_wait=$((oc_wait + 5))
        if [ $((oc_wait % 30)) -eq 0 ] && [ $oc_wait -gt 0 ]; then
            log "Still waiting for OpenCode on ${container_ip}... (${oc_wait}s)"
        fi
    done
    if [ $oc_wait -ge $oc_max ]; then
        log_warning "OpenCode server not ready on ${container_ip} after ${oc_max}s (may start later)"
    fi
done

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

# Copy Flask attack script to compromised container with BENIGN name
# Inside container: test_script_1.sh (looks like a test script)
docker cp "$SCRIPT_DIR/flask_brute_attack.sh" lab_compromised:/tmp/test_script_1.sh
docker exec lab_compromised chmod +x /tmp/test_script_1.sh

# Create monitoring directory in compromised container
docker exec lab_compromised mkdir -p /tmp/flask_bruteforce

# Copy monitoring script to compromised container with BENIGN name
# Inside container: system_monitor.sh (looks like a system monitoring tool)
docker cp "$SCRIPT_DIR/flask_bruteforce_monitor.sh" lab_compromised:/tmp/system_monitor.sh
docker exec lab_compromised chmod +x /tmp/system_monitor.sh

# Start monitoring in background using nohup inside the container
# This starts at the SAME TIME as the attack
docker exec lab_compromised bash -c "nohup /tmp/system_monitor.sh /tmp/flask_bruteforce/monitoring.json > /tmp/flask_bruteforce_monitor_stdout.log 2>&1 &"
log "Flask brute force monitoring started (synchronized with attack)"

# Execute brute force attack in background
log "Executing Flask brute force attack..."
docker exec lab_compromised /tmp/test_script_1.sh "$EXPERIMENT_ID" > "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" 2>&1 &
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
attack_finished_time=""
last_alert_time=""
no_new_alerts_duration=0

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
    # The auto_responder writes per-machine timelines under defender/<machine>/
    # ALERT and PLAN entries are written to BOTH server/ and compromised/ timelines
    # We also include any other subdirectories in case of fallback
    defender_timeline_server="$EXPERIMENT_OUTPUTS/defender/server/auto_responder_timeline.jsonl"
    defender_timeline_compromised="$EXPERIMENT_OUTPUTS/defender/compromised/auto_responder_timeline.jsonl"
    # Also keep the legacy combined path for Phase 6 copy
    defender_timeline="$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl"

    # Combine ALL timeline files from defender/ subdirectories (includes server, compromised, and any hash-named dirs)
    find "$EXPERIMENT_OUTPUTS/defender/" -name "auto_responder_timeline.jsonl" -exec cat {} + 2>/dev/null | sort -u > "$defender_timeline" 2>/dev/null || true

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
                fi
            fi
        done

        # Check OpenCode Server API session status via curl (primary completion detection)
        # GET /session/status returns {} when all sessions are idle/completed
        for container_ip in "172.31.0.10" "172.30.0.10"; do
            if [[ "$container_ip" == "172.31.0.10" ]]; then
                ip="172.31.0.10"
            else
                ip="172.30.0.10"
            fi

            # Only check if we know execution started but don't have end time yet
            if [[ -n "${ip_exec_start_time[$ip]:-}" ]] && [[ -z "${ip_exec_end_time[$ip]:-}" ]]; then
                api_status=$(curl -sf "http://${container_ip}:4096/session/status" 2>/dev/null || echo "")
                if [[ -n "$api_status" ]]; then
                    # If status is empty {} or session is not listed as busy, it's done
                    is_busy=$(echo "$api_status" | jq -r "to_entries[] | select(.value.type == \"busy\") | .key" 2>/dev/null || echo "")
                    if [[ -z "$is_busy" ]]; then
                        finish_iso=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")
                        ip_exec_end_time["$ip"]="$finish_iso"
                        log "OpenCode API status shows idle for $ip at: $finish_iso"
                    fi
                fi
            fi
        done

        # Determine overall opencode_complete_time: only set when ALL IPs with
        # active executions have completed (not just the first one)
        if [[ -z "$opencode_complete_time" ]]; then
            all_done=true
            any_started=false
            for ip in "${!ip_exec_start_time[@]}"; do
                any_started=true
                if [[ -z "${ip_exec_end_time[$ip]:-}" ]]; then
                    all_done=false
                    break
                fi
            done
            if [[ "$any_started" == "true" ]] && [[ "$all_done" == "true" ]]; then
                # Use the latest end time as the overall completion time
                latest_end=""
                for ip in "${!ip_exec_end_time[@]}"; do
                    end_val="${ip_exec_end_time[$ip]}"
                    if [[ -z "$latest_end" ]] || [[ "$end_val" > "$latest_end" ]]; then
                        latest_end="$end_val"
                    fi
                done
                opencode_complete_time="$latest_end"
                log "✓ All OpenCode executions completed at: $opencode_complete_time"
            fi
        fi

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

    # Check if attack has finished and track time since last alert
    if [[ -z "$attack_finished_time" ]]; then
        # Check if attack process is still running
        if ! kill -0 "$ATTACK_PID" 2>/dev/null; then
            attack_finished_time=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")
            log "Attack finished at: $attack_finished_time"
        fi
    fi

    # Track time since last new alert
    if [[ -f "$defender_timeline" ]]; then
        # Get the timestamp of the most recent ALERT or PLAN entry
        latest_alert_ts=$(grep -E '"level":"(ALERT|PLAN)"' "$defender_timeline" 2>/dev/null | tail -1 | jq -r '.ts // empty' 2>/dev/null || echo "")

        if [[ -n "$latest_alert_ts" ]]; then
            # Convert to seconds since epoch
            latest_alert_sec=$(date -d "$latest_alert_ts" +%s 2>/dev/null || echo 0)
            current_sec=$(date +%s)

            # Calculate how long since last alert
            time_since_alert=$((current_sec - latest_alert_sec))

            # Update tracking if we have a newer alert
            if [[ $time_since_alert -lt 3600 ]]; then  # Sanity check: alerts within last hour
                if [[ -z "$last_alert_time" ]] || [[ "$latest_alert_sec" -gt "$(date -d "$last_alert_time" +%s 2>/dev/null || echo 0)" ]]; then
                    last_alert_time="$latest_alert_ts"
                    no_new_alerts_duration=0
                else
                    no_new_alerts_duration=$time_since_alert
                fi
            fi
        fi
    fi

    # Check termination condition: OpenCode finished + attack finished + no new alerts for 30s
    if [[ -n "$opencode_complete_time" ]] && [[ -n "$attack_finished_time" ]]; then
        if [[ $no_new_alerts_duration -ge 30 ]]; then
            log "✓ OpenCode complete at: $opencode_complete_time"
            log "✓ Attack finished at: $attack_finished_time"
            log "✓ No new alerts for ${no_new_alerts_duration}s (threshold: 30s)"
            log "Termination condition met: OpenCode finished, attack finished, and no new alerts for 30s"
            experiment_end_reason="opencode_complete_attack_done_no_new_alerts"
            break
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

        # Check if attack succeeded but defender didn't respond (early termination)
        # Only trigger if NO OpenCode execution has started at all
        if [[ $elapsed -ge 600 ]]; then  # After 10 minutes
            # Check if password was found in the attack
            if [[ -f "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" ]]; then
                if grep -q "SUCCESS: Password found" "$EXPERIMENT_OUTPUTS/logs/flask_attack.log" 2>/dev/null; then
                    # Only terminate early if OpenCode never started executing
                    if [[ -z "$first_successful_exec_time" ]]; then
                        log "⚠️  Attack succeeded (password found) and no defender execution started after ${elapsed}s"
                        log "⚠️  Ending experiment early - defender truly unresponsive"
                        experiment_end_reason="attack_success_no_defender"
                        break
                    else
                        # OpenCode is running - don't terminate, just log status
                        if [[ $((elapsed % 300)) -eq 0 ]]; then
                            log "⏳ Attack succeeded but OpenCode is still executing defense (${elapsed}s elapsed)"
                        fi
                    fi
                fi
            fi
        fi
    fi

    sleep 5
done

# Check if we were interrupted by a signal
# If so, skip Phase 6 (already done by signal handler) and go to Phase 7
if [[ "$SIGNAL_HANDLED" == "true" ]]; then
    log "=== Signal was handled, skipping to Phase 7 ==="
    # Phase 6 was partially done by the signal handler
    # Fall through to Phase 7 below
else
    # Phase 6: Collect results (normal completion path)
    log "=== Phase 6: Collecting Results ==="

EXPERIMENT_END_TIME=$(date +%s)
TOTAL_DURATION=$((EXPERIMENT_END_TIME - ATTACK_START_TIME))

log "Experiment ended: $(date -Iseconds)"
log "Total duration: ${TOTAL_DURATION}s"
log "End reason: $experiment_end_reason"

# Wait for all logs to be written
# The auto_responder may still be finishing its execution (saving session logs,
# writing DONE entries). Wait until we see DONE or EXEC completion entries for
# all IPs that had executions, or until a timeout.
log "Waiting for auto_responder to finish saving session logs..."
wait_for_logs_start=$(date +%s)
wait_for_logs_timeout=120  # Wait up to 2 minutes for logs

while true; do
    wait_elapsed=$(( $(date +%s) - wait_for_logs_start ))
    if [[ $wait_elapsed -ge $wait_for_logs_timeout ]]; then
        log_warning "Timeout waiting for auto_responder logs (${wait_for_logs_timeout}s)"
        break
    fi

    # Check if all IPs with executions have DONE or EXEC completion entries
    all_logs_done=true
    for ip in "${!ip_exec_start_time[@]}"; do
        machine="server"
        [[ "$ip" == "172.30.0.10" ]] && machine="compromised"
        timeline_file="$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl"

        # Check for DONE or EXEC with status=success
        if ! grep -q '"level":"DONE"' "$timeline_file" 2>/dev/null; then
            # Also check for opencode_api_messages.json as evidence of completion
            if [[ ! -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json" ]]; then
                all_logs_done=false
                break
            fi
        fi
    done

    if [[ "$all_logs_done" == "true" ]]; then
        log "✓ All auto_responder logs saved successfully"
        break
    fi

    sleep 5
done

# Rebuild combined timeline from ALL defender subdirectories (authoritative source)
find "$EXPERIMENT_OUTPUTS/defender/" -name "auto_responder_timeline.jsonl" -exec cat {} + \
    2>/dev/null | sort -u > "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" 2>/dev/null || true

# Copy defender timeline and detailed logs
if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" ]]; then
    cp "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" "$EXPERIMENT_OUTPUTS/logs/"
    log "Defender combined timeline copied"
fi
# Also copy per-machine timelines
for machine in server compromised; do
    if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl" ]]; then
        cp "$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl" \
           "$EXPERIMENT_OUTPUTS/logs/auto_responder_timeline_${machine}.jsonl" 2>/dev/null || true
        log "Defender timeline copied for $machine"
    fi
done
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

# Copy OpenCode API messages (new format) alongside legacy JSONL
for machine in server compromised; do
    if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json" ]]; then
        cp "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json" "$EXPERIMENT_OUTPUTS/logs/opencode_api_messages_${machine}.json" 2>/dev/null || true
        log "OpenCode API messages copied for $machine"
    fi
    if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_stdout.jsonl" ]]; then
        cp "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_stdout.jsonl" "$EXPERIMENT_OUTPUTS/logs/opencode_stdout_${machine}.jsonl" 2>/dev/null || true
        log "OpenCode legacy JSONL copied for $machine"
    fi
    if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_sse_events.jsonl" ]]; then
        cp "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_sse_events.jsonl" "$EXPERIMENT_OUTPUTS/logs/opencode_sse_events_${machine}.jsonl" 2>/dev/null || true
        log "OpenCode SSE events copied for $machine"
    fi
done

# Copy Flask login attempt logs from server
docker cp lab_server:/tmp/flask_login_attempts.jsonl "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
log "Flask login attempts log copied from server"

log "Flask brute force results copied"

# Collect PCAPs
log "PCAPs saved in: $EXPERIMENT_OUTPUTS/pcaps"

fi  # End of else block (normal Phase 6 completion)

# Phase 7: Generate summary
# This runs in all cases: normal completion, interrupt, timeout
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
    flask_successful_attempts=$(grep -c '"success": *true' "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | tr -d ' ' || echo "0")

    # Get first and last attempt timestamps
    flask_first_attempt_time=$(head -1 "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | grep -o '"timestamp": "[^"]*"' | cut -d'"' -f4 | head -1 || echo "null")
    flask_last_attempt_time=$(tail -1 "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | grep -o '"timestamp": "[^"]*"' | cut -d'"' -f4 | head -1 || echo "null")

    # Get successful attempt timestamp if any
    if [[ "$flask_successful_attempts" -gt 0 ]]; then
        flask_successful_attempt_time=$(grep '"success": *true' "$EXPERIMENT_OUTPUTS/logs/flask_login_attempts.jsonl" 2>/dev/null | head -1 | grep -o '"timestamp": "[^"]*"' | cut -d'"' -f4 | head -1 || echo "null")
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

# Extract OpenCode execution details from API messages (primary format)
opencode_details=$(python3 -c "
import json, sys, os
result = {}
for machine in ['server', 'compromised']:
    api_file = os.path.join('$EXPERIMENT_OUTPUTS', 'defender', machine, 'opencode_api_messages.json')
    if not os.path.exists(api_file):
        continue
    try:
        with open(api_file) as f:
            messages = json.load(f)
    except Exception:
        continue

    llm_calls = 0
    tool_calls = []
    tool_details = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0
    total_cost = 0.0
    completed_with_stop = False
    session_id = ''

    for msg in messages:
        info = msg.get('info', {})
        parts = msg.get('parts', [])
        if not session_id:
            session_id = info.get('sessionID', '')
        if info.get('role') == 'assistant':
            tokens = info.get('tokens', {})
            total_input_tokens += tokens.get('input', 0)
            total_output_tokens += tokens.get('output', 0)
            total_reasoning_tokens += tokens.get('reasoning', 0)
            total_cost += info.get('cost', 0) or 0
            if info.get('finish') == 'stop':
                completed_with_stop = True
        for part in parts:
            pt = part.get('type', '')
            if pt == 'step-start':
                llm_calls += 1
            elif pt == 'tool':
                tool_name = part.get('tool', 'unknown')
                tool_calls.append(tool_name)
                state = part.get('state', {})
                meta = state.get('metadata', {})
                tool_details.append({
                    'tool': tool_name,
                    'status': state.get('status', ''),
                    'exit_code': meta.get('exit'),
                    'command': state.get('input', {}).get('command', '')[:200] if tool_name == 'bash' else None,
                    'output_preview': str(state.get('output', ''))[:200],
                })

    result[machine] = {
        'session_id': session_id,
        'llm_calls': llm_calls,
        'tool_calls': tool_calls,
        'tool_details': tool_details,
        'completed_with_stop': completed_with_stop,
        'total_input_tokens': total_input_tokens,
        'total_output_tokens': total_output_tokens,
        'total_reasoning_tokens': total_reasoning_tokens,
        'total_cost': total_cost,
    }
print(json.dumps(result))
" 2>/dev/null || echo '{}')

# Validate it's valid JSON, fallback to empty
echo "$opencode_details" | jq . >/dev/null 2>&1 || opencode_details='{}'

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
        "per_ip_metrics": ${per_ip_metrics},
        "opencode_execution_details": ${opencode_details}
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

# Print OpenCode execution details (parsed from API messages)
log "OpenCode Execution Details:"
for machine in server compromised; do
    api_file="$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json"
    if [[ -f "$api_file" ]]; then
        m_data=$(echo "$opencode_details" | jq -r ".${machine} // empty" 2>/dev/null)
        if [[ -n "$m_data" ]] && [[ "$m_data" != "null" ]]; then
            m_llm=$(echo "$m_data" | jq -r '.llm_calls // 0')
            m_tools=$(echo "$m_data" | jq -r '.tool_calls | length')
            m_tool_list=$(echo "$m_data" | jq -r '.tool_calls | group_by(.) | map("\(.[0])(\(length))") | join(", ")' 2>/dev/null || echo "none")
            m_stop=$(echo "$m_data" | jq -r '.completed_with_stop')
            m_in_tok=$(echo "$m_data" | jq -r '.total_input_tokens')
            m_out_tok=$(echo "$m_data" | jq -r '.total_output_tokens')
            m_sid=$(echo "$m_data" | jq -r '.session_id // "unknown"' | head -c 20)
            log "  $machine (session: ${m_sid}...):"
            log "    - LLM calls: $m_llm"
            log "    - Tool calls: $m_tools ($m_tool_list)"
            log "    - Completed (stop): $m_stop"
            log "    - Tokens: input=$m_in_tok output=$m_out_tok"
        else
            log "  $machine: API messages file exists but no parsed data"
        fi
    else
        log "  $machine: no execution data"
    fi
done
log ""
log "Results saved in: $EXPERIMENT_OUTPUTS"
log "Summary saved in: $EXPERIMENT_OUTPUTS/flask_brute_experiment_summary.json"

log_success "Experiment complete!"

# Delete PCAPs to save disk space
log "Deleting PCAPs to save disk space..."
rm -rf "$EXPERIMENT_OUTPUTS/pcaps" 2>/dev/null || true
rm -rf "/home/diego/Trident/outputs/$EXPERIMENT_ID/pcaps" 2>/dev/null || true
log "PCAPs deleted"

# Clean up containers AFTER summary is generated
log "Experiment complete, cleaning up containers..."
cd "$PROJECT_ROOT"
make down 2>/dev/null || true
log "Containers cleaned up"

exit 0
