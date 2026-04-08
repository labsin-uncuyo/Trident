#!/bin/bash
# DNS Injection Experiment Script
# Tests defender response to DNS resolution attacks to analisisconsumidoresargentina.lat
#
# Logs:
# - Time until SLIPS generates high confidence alert
# - Time to plan generation
# - Time until OpenCode execution finishes
# - DNS resolution attempts and results
#
# Termination conditions:
# 1. OpenCode execution complete on both servers AND attack finished
# 2. 20 minutes have passed since attack started
# 3. All 5 DNS resolutions completed

set -e

# Configuration
EXPERIMENT_ID="${1:-dns_injection_$(date +%Y%m%d_%H%M%S)}"
MAX_EXPERIMENT_TIME=1200  # 20 minutes
TARGET_DOMAIN="analisisconsumidoresargentina.lat"
NUM_DNS_RESOLUTIONS=5

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

    # Collect partial results
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
        docker cp lab_compromised:/var/lib/system_health/metrics.json "$EXPERIMENT_OUTPUTS/logs/monitoring.json" 2>/dev/null || true
        docker cp lab_compromised:/var/lib/network_metrics/connectivity_summary.json "$EXPERIMENT_OUTPUTS/logs/dns_attack_summary.json" 2>/dev/null || true
        docker cp lab_compromised:/tmp/opencode_exec_times.log "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true

        log "Attempting to generate summary with available data..."
    else
        log_warning "Output directory not found, skipping summary generation"
        cd "$PROJECT_ROOT"
        make down 2>/dev/null || true
        exit 1
    fi
}

trap cleanup_on_signal INT TERM HUP

# Create output directory
mkdir -p "$EXPERIMENT_OUTPUTS"/{pcaps,slips_output,logs}
echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"

log "Starting DNS Injection Experiment: $EXPERIMENT_ID"
log "Output directory: $EXPERIMENT_OUTPUTS"
log "Target domain: $TARGET_DOMAIN"
log "Number of DNS resolutions: $NUM_DNS_RESOLUTIONS"

# Phase 1: Start infrastructure
log "=== Phase 1: Starting Infrastructure ==="
cd "$PROJECT_ROOT"

# Load persistent project environment (including LANGFUSE_*) when available.
# Values explicitly exported by the caller still take precedence after this point.
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Set RUN_ID environment variable to match experiment ID
export RUN_ID="$EXPERIMENT_ID"
log "Set RUN_ID environment variable: $RUN_ID"

# Clean up any existing environment (but preserve SSH keys for faster startup)
log "Running 'make down' to ensure clean state..."
make down 2>/dev/null || true
# Recreate SSH keys volume if it doesn't exist to avoid regeneration delay
docker volume create lab_auto_responder_ssh_keys >/dev/null 2>&1 || true
sleep 5

# Start core services (router/server/compromised only; dashboard is not needed here)
log "Starting core services (router, server, compromised)..."
if ! RUN_ID="$RUN_ID" docker compose --profile core up -d --no-build router server compromised; then
    log_error "Failed to start core services"
    exit 1
fi

# Wait for containers to be fully started
log "Waiting for containers to stabilize (30s)..."
sleep 30

# Ensure all core containers are actually running
for c in lab_server lab_compromised lab_router; do
    c_status=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "missing")
    if [[ "$c_status" != "running" ]]; then
        log_warning "$c is in state '$c_status', attempting to start it..."
        docker start "$c" 2>/dev/null || true
        sleep 5
    fi
done

# Verify core services are healthy
log "Checking core services health..."
max_wait=240
elapsed=0
while [ $elapsed -lt $max_wait ]; do
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
    docker ps -a --format "table {{.Names}}\t{{.Status}}" | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log"
    exit 1
fi

# Verify network connectivity
log "Verifying network connectivity..."
if ! docker exec lab_compromised curl -sf -o /dev/null http://172.31.0.10:80; then
    log_error "Server not reachable from compromised"
    exit 1
fi
log_success "Network connectivity verified!"

# If Langfuse is enabled, ensure planner can route to local Langfuse from lab network.
# This auto-wires the common local self-host setup where Langfuse runs as
# "langfuse-langfuse-web-1" outside the lab compose project.
if [[ "${LANGFUSE_ENABLED,,}" == "true" ]]; then
    if docker ps --format "{{.Names}}" | grep -q "^langfuse-langfuse-web-1$"; then
        # In this environment, routing from lab containers to host.docker.internal and
        # to ad-hoc lab_net_b IPs is unreliable. Prefer attaching defender directly to
        # Langfuse's compose network and using container DNS.
        if [[ -z "${LANGFUSE_HOST:-}" || "${LANGFUSE_HOST}" == *"localhost"* || "${LANGFUSE_HOST}" == *"127.0.0.1"* || "${LANGFUSE_HOST}" == *"host.docker.internal"* || "${LANGFUSE_HOST}" == *"172.31.0."* ]]; then
            export LANGFUSE_HOST="http://langfuse-langfuse-web-1:3000"
        fi
        export LANGFUSE_SHARED_NETWORK="${LANGFUSE_SHARED_NETWORK:-langfuse_default}"
        log "LANGFUSE enabled: planner will use ${LANGFUSE_HOST} via ${LANGFUSE_SHARED_NETWORK}"
    else
        log_warning "LANGFUSE enabled but langfuse-langfuse-web-1 is not running; planner traces may fail"
    fi
fi

# Wait for OpenCode server API to be available on both containers.
# Skip this in planner-only mode because no OpenCode execution is performed.
if [[ "$PLANNER_ONLY" == "true" ]]; then
    log "PLANNER_ONLY mode: skipping OpenCode API readiness wait"
else
    # IMPORTANT: Check from inside each container, not from host.
    # The lab subnets (172.30/172.31) are internal Docker bridge networks and
    # host-to-container routing is not guaranteed.
    log "Waiting for OpenCode server API to be ready..."
    opencode_ready_failure=false
    for container_name in "lab_server" "lab_compromised"; do
        oc_wait=0
        oc_max=240  # Increased from 120s to 240s (lab_server needs time for DB load)
        container_ready=false
        while [ $oc_wait -lt $oc_max ]; do
            if docker exec "$container_name" curl -sf "http://127.0.0.1:4096/global/health" 2>/dev/null | grep -q '"healthy":true'; then
                log_success "OpenCode server ready in ${container_name}"
                container_ready=true
                break
            fi
            sleep 5
            oc_wait=$((oc_wait + 5))
            if [ $((oc_wait % 30)) -eq 0 ] && [ $oc_wait -gt 0 ]; then
                log "Still waiting for OpenCode in ${container_name}... (${oc_wait}s)"
            fi
        done
        if [[ "$container_ready" != "true" ]]; then
            opencode_ready_failure=true
            log_error "OpenCode server not ready in ${container_name} after ${oc_max}s"
            log "Collecting OpenCode diagnostics for ${container_name}..."
            docker exec "$container_name" sh -lc 'ps aux | grep -E "opencode|node" | grep -v grep || true' \
                2>&1 | sed 's/^/[diag] /' | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log" >/dev/null
            docker exec "$container_name" sh -lc 'tail -n 80 /var/log/opencode-serve.log 2>/dev/null || echo "opencode log missing"' \
                2>&1 | sed 's/^/[diag] /' | tee -a "$EXPERIMENT_OUTPUTS/logs/experiment.log" >/dev/null
        fi
    done
    if [[ "$opencode_ready_failure" == "true" ]]; then
        log_error "OpenCode readiness failed; aborting experiment early to avoid silent timeouts"
        exit 1
    fi
fi

# Phase 2: Start defender (skip if SKIP_DEFENDER is set)
if [[ "$SKIP_DEFENDER" == "true" ]]; then
    log "=== Phase 2: SKIPPING Defender (baseline mode) ==="
    log "Setting RUN_ID to match experiment ID: $EXPERIMENT_ID"
    echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"
    log "Defender disabled - running in baseline mode"
else
    log "=== Phase 2: Starting Defender ==="
    log "Setting RUN_ID to match experiment ID: $EXPERIMENT_ID"
    echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"

    # Check if PLANNER_ONLY mode is enabled
    if [[ "$PLANNER_ONLY" == "true" ]]; then
        log "PLANNER_ONLY mode: OpenCode execution will be DISABLED"
        export PLANNER_ONLY=true
    fi

    log "Running 'make defend'..."
    make defend

    log "Waiting for defender containers to stabilize..."
    sleep 15

    log "Waiting for defender to be ready..."
    max_wait=180
    elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        if docker ps --format "{{.Names}}:{{.Status}}" | grep -q "lab_slips_defender.*healthy"; then
            # Verify defender API is responding from inside the container
            if docker exec lab_slips_defender curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
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

    # Ensure defender can resolve/reach Langfuse container DNS host when enabled.
    if [[ "${LANGFUSE_ENABLED,,}" == "true" ]] && [[ -n "${LANGFUSE_SHARED_NETWORK:-}" ]]; then
        if docker network inspect "${LANGFUSE_SHARED_NETWORK}" >/dev/null 2>&1; then
            docker network connect "${LANGFUSE_SHARED_NETWORK}" lab_slips_defender >/dev/null 2>&1 || true
            log "Connected lab_slips_defender to ${LANGFUSE_SHARED_NETWORK} for Langfuse access"
        else
            log_warning "LANGFUSE network ${LANGFUSE_SHARED_NETWORK} not found; traces may fail"
        fi
    fi
fi

# Phase 3: Start DNS injection attack
log "=== Phase 3: Starting DNS Injection Attack ==="

# Wait for PCAP capture to be ready (tcpdump needs time to create first file)
# The router rotates PCAPs every 30 seconds, so we wait 35 seconds to ensure
# at least one complete file exists before starting the DNS attack.
log "Waiting for PCAP capture to be ready (35s)..."
sleep 35

# Record attack start time
ATTACK_START_TIME=$(date +%s)
log "Attack start time: $(date -Iseconds)"

# Copy DNS attack script to compromised container with BENIGN name
# Named as: network_check.sh - appears to be a network connectivity check tool
docker cp "$SCRIPT_DIR/dns_injection_attack.sh" lab_compromised:/usr/local/bin/network_check.sh
docker exec lab_compromised chmod +x /usr/local/bin/network_check.sh

# Create monitoring directory in compromised container with BENIGN path
docker exec lab_compromised mkdir -p /var/lib/system_health

# Copy monitoring script to compromised container with BENIGN name
# Named as: health_monitor.sh - appears to be a system health monitoring daemon
docker cp "$SCRIPT_DIR/dns_injection_monitor.sh" lab_compromised:/usr/local/bin/health_monitor.sh
docker exec lab_compromised chmod +x /usr/local/bin/health_monitor.sh

# Copy PostgreSQL health check script with BENIGN name
# Named as: health_check.sh - appears to be a standard database connectivity check tool
docker cp "$SCRIPT_DIR/pg_health_monitor.sh" lab_compromised:/usr/local/bin/health_check.sh
docker exec lab_compromised chmod +x /usr/local/bin/health_check.sh

# Start monitoring in background with benign process name
docker exec lab_compromised bash -c "nohup /usr/local/bin/health_monitor.sh /var/lib/system_health/metrics.json > /var/log/health_monitor.log 2>&1 &"
log "System health monitoring started"

# Start PostgreSQL health checking in background with benign process name
docker exec lab_compromised bash -c "nohup /usr/local/bin/health_check.sh /var/lib/system_health/pg_health.json > /var/log/pg_health_check.log 2>&1 &"
log "PostgreSQL health checking started (30s interval)"

# Execute DNS attack in background with benign process name
log "Executing network connectivity checks (${NUM_DNS_RESOLUTIONS} resolutions to ${TARGET_DOMAIN})..."
docker exec lab_compromised /usr/local/bin/network_check.sh "$EXPERIMENT_ID" > "$EXPERIMENT_OUTPUTS/logs/network_check.log" 2>&1 &
ATTACK_PID=$!

log "Network connectivity check started (container PID: $ATTACK_PID)"

# Phase 4: Monitor for experiment end conditions
log "=== Phase 4: Monitoring Experiment Progress ==="

# Variables to track experiment state
high_confidence_alert_time=""
first_plan_time=""
first_plan_count=0
first_successful_exec_time=""
opencode_complete_time=""
experiment_end_reason=""
attack_finished_time=""
last_alert_time=""
no_new_alerts_duration=0
dns_resolutions_completed=0

# Per-IP tracking
declare -A ip_plan_time
declare -A ip_exec_start_time
declare -A ip_exec_end_time
declare -A ip_exec_duration

log "Monitoring experiment progress (max ${MAX_EXPERIMENT_TIME}s)..."
log "Will terminate when:"
if [[ "$PLANNER_ONLY" == "true" ]]; then
    log "  1. First plan is generated (planner-only mode)"
    log "  2. OR ${MAX_EXPERIMENT_TIME}s have passed since attack started"
else
    log "  1. BOTH: OpenCode execution complete on both servers AND attack finished"
    log "  2. OR ${MAX_EXPERIMENT_TIME}s have passed since attack started"
fi

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

    # Check if DNS attack has finished
    dns_monitoring=$(docker exec lab_compromised cat /var/lib/network_metrics/connectivity_status.json 2>/dev/null || echo "{}")
    dns_status=$(echo "$dns_monitoring" | jq -r '.status // "running"' 2>/dev/null || echo "running")
    dns_resolutions_completed=$(echo "$dns_monitoring" | jq -r '.checks | length' 2>/dev/null || echo "0")

    # Parse defender timeline for key events
    defender_timeline="$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl"
    find "$EXPERIMENT_OUTPUTS/defender/" -name "auto_responder_timeline.jsonl" -exec cat {} + 2>/dev/null | sort -u > "$defender_timeline" 2>/dev/null || true

    if [[ -f "$defender_timeline" ]]; then
        # Check for high confidence alert (DNS TXT high-entropy)
        # Note: SLIPS returns "low" or "medium" threat level, but we look for high entropy
        if [[ -z "$high_confidence_alert_time" ]]; then
            high_conf_alert=$(grep -i '"level":"ALERT"' "$defender_timeline" | \
                grep -i 'high entropy' | head -1 || true)

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
                first_plan_count=$(echo "$first_plan" | jq -r '.data.num_plans // 1' 2>/dev/null || echo "1")

                # Extract per-IP plan information
                num_plans=$first_plan_count
                for ((i=0; i<num_plans; i++)); do
                    plan_json=$(echo "$first_plan" | jq -c ".data.plans[$i]" 2>/dev/null || echo "{}")
                    if [[ "$plan_json" != "{}" ]] && [[ "$plan_json" != "null" ]]; then
                        plan_ip=$(echo "$plan_json" | jq -r '.executor_host_ip // empty' 2>/dev/null)
                        if [[ -n "$plan_ip" ]]; then
                            ip_plan_time["$plan_ip"]="$first_plan_time"
                            log "Plan generated for IP $plan_ip at: $first_plan_time"
                        fi
                    fi
                done

                log "Plan generated at: $first_plan_time (total plans: $num_plans)"
            fi
        fi

        # PLANNER_ONLY MODE: Terminate immediately after first plan is generated
        if [[ "$PLANNER_ONLY" == "true" ]] && [[ -n "$first_plan_time" ]]; then
            log "✓ Plan generated (planner-only mode)"
            log "Termination condition met: First plan received, ending experiment"
            experiment_end_reason="plan_generated_planner_only"
            break
        fi

        # Check for OpenCode execution (per-IP)
        exec_entries=$(grep '"level":"EXEC".*"executor_ip"' "$defender_timeline" 2>/dev/null || true)

        if [[ -n "$exec_entries" ]]; then
            while IFS= read -r exec_entry; do
                exec_ip=$(echo "$exec_entry" | jq -r '.data.executor_ip // empty' 2>/dev/null)
                exec_ts=$(echo "$exec_entry" | jq -r '.ts // empty' 2>/dev/null)

                if [[ -n "$exec_ip" ]] && [[ -n "$exec_ts" ]]; then
                    if [[ -z "${ip_exec_start_time[$exec_ip]:-}" ]]; then
                        ip_exec_start_time["$exec_ip"]="$exec_ts"
                        log "OpenCode execution started for IP $exec_ip at: $exec_ts"

                        if [[ -z "$first_successful_exec_time" ]]; then
                            first_successful_exec_time="$exec_ts"
                        fi
                    fi
                fi
            done <<< "$exec_entries"
        fi

        # Check for OpenCode completion per-IP
        done_entries=$(grep '"level":"DONE".*"status":"success"' "$defender_timeline" 2>/dev/null || true)
        if [[ -n "$done_entries" ]]; then
            while IFS= read -r done_entry; do
                exec_id=$(echo "$done_entry" | jq -r '.exec // empty' 2>/dev/null)
                done_ts=$(echo "$done_entry" | jq -r '.ts // empty' 2>/dev/null)

                if [[ -n "$exec_id" ]] && [[ -n "$done_ts" ]]; then
                    ip_part=$(echo "$exec_id" | grep -oE '[0-9]+_[0-9]+_[0-9]+_[0-9]+$' | head -1 || true)
                    if [[ -n "$ip_part" ]]; then
                        ip=$(echo "$ip_part" | tr '_' '.')
                        ip_exec_end_time["$ip"]="$done_ts"
                        log "OpenCode execution completed for IP $ip at: $done_ts"
                    fi
                fi
            done <<< "$done_entries"
        fi

        # Check OpenCode Server API session status via curl
        for container_ip in "172.31.0.10" "172.30.0.10"; do
            if [[ "$container_ip" == "172.31.0.10" ]]; then
                ip="172.31.0.10"
            else
                ip="172.30.0.10"
            fi

            if [[ -n "${ip_exec_start_time[$ip]:-}" ]] && [[ -z "${ip_exec_end_time[$ip]:-}" ]]; then
                api_status=$(curl -sf "http://${container_ip}:4096/session/status" 2>/dev/null || echo "")
                if [[ -n "$api_status" ]]; then
                    is_busy=$(echo "$api_status" | jq -r "to_entries[] | select(.value.type == \"busy\") | .key" 2>/dev/null || echo "")
                    if [[ -z "$is_busy" ]]; then
                        finish_iso=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")
                        ip_exec_end_time["$ip"]="$finish_iso"
                        log "OpenCode API status shows idle for $ip at: $finish_iso"
                    fi
                fi
            fi
        done

        # Determine overall opencode_complete_time
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
    fi

    # Check if attack has finished
    if [[ -z "$attack_finished_time" ]]; then
        if [[ "$dns_status" == "completed" ]] || [[ "$dns_resolutions_completed" -ge "$NUM_DNS_RESOLUTIONS" ]]; then
            attack_finished_time=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")
            log "✓ DNS attack finished at: $attack_finished_time"
            log "  Resolutions completed: $dns_resolutions_completed/$NUM_DNS_RESOLUTIONS"
        fi
    fi

    # Track time since last alert
    if [[ -f "$defender_timeline" ]]; then
        latest_alert_ts=$(grep -E '"level":"(ALERT|PLAN)"' "$defender_timeline" 2>/dev/null | tail -1 | jq -r '.ts // empty' 2>/dev/null || echo "")

        if [[ -n "$latest_alert_ts" ]]; then
            latest_alert_sec=$(date -d "$latest_alert_ts" +%s 2>/dev/null || echo 0)
            current_sec=$(date +%s)
            time_since_alert=$((current_sec - latest_alert_sec))

            if [[ $time_since_alert -lt 3600 ]]; then
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
            experiment_end_reason="opencode_complete_attack_done_no_new-alerts"
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

        if [[ "$PLANNER_ONLY" != "true" ]]; then
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
        fi

        log "  DNS attack status: $dns_status ($dns_resolutions_completed/$NUM_DNS_RESOLUTIONS resolutions)"
    fi

    sleep 5
done

# Phase 5: Collect results
if [[ "$SIGNAL_HANDLED" != "true" ]]; then
    log "=== Phase 5: Collecting Results ==="

    EXPERIMENT_END_TIME=$(date +%s)
    TOTAL_DURATION=$((EXPERIMENT_END_TIME - ATTACK_START_TIME))

    log "Experiment ended: $(date -Iseconds)"
    log "Total duration: ${TOTAL_DURATION}s"
    log "End reason: $experiment_end_reason"

    # Wait for auto_responder to finish saving session logs
    log "Waiting for auto_responder to finish saving session logs..."
    wait_for_logs_start=$(date +%s)
    wait_for_logs_timeout=120

    while true; do
        wait_elapsed=$(( $(date +%s) - wait_for_logs_start ))
        if [[ $wait_elapsed -ge $wait_for_logs_timeout ]]; then
            log_warning "Timeout waiting for auto_responder logs (${wait_for_logs_timeout}s)"
            break
        fi

        all_logs_done=true
        for ip in "${!ip_exec_start_time[@]}"; do
            machine="server"
            [[ "$ip" == "172.30.0.10" ]] && machine="compromised"
            timeline_file="$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl"

            if ! grep -q '"level":"DONE"' "$timeline_file" 2>/dev/null; then
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

    # Rebuild combined timeline
    find "$EXPERIMENT_OUTPUTS/defender/" -name "auto_responder_timeline.jsonl" -exec cat {} + \
        2>/dev/null | sort -u > "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" 2>/dev/null || true

    # Copy defender timeline and detailed logs
    if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" ]]; then
        cp "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" "$EXPERIMENT_OUTPUTS/logs/"
        log "Defender combined timeline copied"
    fi

    for machine in server compromised; do
        if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl" ]]; then
            cp "$EXPERIMENT_OUTPUTS/defender/$machine/auto_responder_timeline.jsonl" \
               "$EXPERIMENT_OUTPUTS/logs/auto_responder_timeline_${machine}.jsonl" 2>/dev/null || true
            log "Defender timeline copied for $machine"
        fi
        if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json" ]]; then
            cp "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_api_messages.json" "$EXPERIMENT_OUTPUTS/logs/opencode_api_messages_${machine}.json" 2>/dev/null || true
            log "OpenCode API messages copied for $machine"
        fi
        if [[ -f "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_sse_events.jsonl" ]]; then
            cp "$EXPERIMENT_OUTPUTS/defender/$machine/opencode_sse_events.jsonl" "$EXPERIMENT_OUTPUTS/logs/opencode_sse_events_${machine}.jsonl" 2>/dev/null || true
            log "OpenCode SSE events copied for $machine"
        fi
    done

    # Copy SLIPS output
    if [[ -d "$EXPERIMENT_OUTPUTS/slips" ]]; then
        cp -r "$EXPERIMENT_OUTPUTS/slips" "$EXPERIMENT_OUTPUTS/logs/"
        log "SLIPS output copied"
    fi

    # Copy DNS injection monitoring results
    docker cp lab_compromised:/var/lib/network_metrics/connectivity_status.json "$EXPERIMENT_OUTPUTS/logs/monitoring.json" 2>/dev/null || true
    docker cp lab_compromised:/var/lib/network_metrics/connectivity_summary.json "$EXPERIMENT_OUTPUTS/logs/dns_attack_summary.json" 2>/dev/null || true

    # Copy PostgreSQL health check results
    docker cp lab_compromised:/var/lib/system_health/pg_health.json "$EXPERIMENT_OUTPUTS/logs/pg_health.json" 2>/dev/null || true

    # Copy OpenCode execution time log
    docker cp lab_compromised:/tmp/opencode_exec_times.log "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true

    log "Network connectivity check results copied"
fi

# Phase 6: Generate summary
log "=== Phase 6: Generating Summary ==="

# Calculate timestamps
if [[ -n "$ATTACK_START_TIME" ]]; then
    attack_start_iso=$(date -d @$ATTACK_START_TIME -Iseconds 2>/dev/null || echo "$EXPERIMENT_START_TIME")
else
    attack_start_iso=$(date -Iseconds)
fi

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

# Get DNS resolution data
dns_resolutions_total="0"
dns_successful="0"
dns_first_resolution_time=""
dns_last_resolution_time=""

if [[ -f "$EXPERIMENT_OUTPUTS/logs/monitoring.json" ]]; then
    dns_resolutions_total=$(jq -r '.checks | length' "$EXPERIMENT_OUTPUTS/logs/monitoring.json" 2>/dev/null || echo "0")
    dns_successful=$(jq -r '.checks | map(select(.status == "passed")) | length' "$EXPERIMENT_OUTPUTS/logs/monitoring.json" 2>/dev/null || echo "0")
    dns_first_resolution_time=$(jq -r '.checks[0].timestamp // empty' "$EXPERIMENT_OUTPUTS/logs/monitoring.json" 2>/dev/null || echo "null")
    dns_last_resolution_time=$(jq -r '.checks[-1].timestamp // empty' "$EXPERIMENT_OUTPUTS/logs/monitoring.json" 2>/dev/null || echo "null")
fi

# Get PostgreSQL health check data
pg_health_checks_total="0"
pg_health_checks_healthy="0"
pg_health_checks_unhealthy="0"
pg_health_first_check_time=""
pg_health_last_check_time=""
pg_health_status_overall="unknown"

if [[ -f "$EXPERIMENT_OUTPUTS/logs/pg_health.json" ]]; then
    pg_health_checks_total=$(jq -r '.checks | length' "$EXPERIMENT_OUTPUTS/logs/pg_health.json" 2>/dev/null || echo "0")
    pg_health_checks_healthy=$(jq -r '.checks | map(select(.status == "healthy")) | length' "$EXPERIMENT_OUTPUTS/logs/pg_health.json" 2>/dev/null || echo "0")
    pg_health_checks_unhealthy=$(jq -r '.checks | map(select(.status == "unhealthy")) | length' "$EXPERIMENT_OUTPUTS/logs/pg_health.json" 2>/dev/null || echo "0")
    pg_health_first_check_time=$(jq -r '.checks[0].timestamp // empty' "$EXPERIMENT_OUTPUTS/logs/pg_health.json" 2>/dev/null || echo "null")
    pg_health_last_check_time=$(jq -r '.checks[-1].timestamp // empty' "$EXPERIMENT_OUTPUTS/logs/pg_health.json" 2>/dev/null || echo "null")
    # Determine overall status based on last check
    pg_health_status_overall=$(jq -r '.checks[-1].status // "unknown"' "$EXPERIMENT_OUTPUTS/logs/pg_health.json" 2>/dev/null || echo "unknown")
fi

# Calculate deltas
time_to_high_conf=""
time_to_plan=""
time_to_exec=""

if [[ $high_conf_epoch -gt 0 ]]; then
    time_to_high_conf=$((high_conf_epoch - ATTACK_START_TIME))
fi

if [[ $plan_epoch -gt 0 ]]; then
    time_to_plan=$((plan_epoch - ATTACK_START_TIME))
fi

if [[ $exec_epoch -gt 0 ]]; then
    time_to_exec=$((exec_epoch - ATTACK_START_TIME))
fi

# Helper function for JSON strings
json_string() {
    if [[ "$1" == "null" ]] || [[ -z "$1" ]]; then
        echo "null"
    else
        echo "\"$1\""
    fi
}

# Build JSON values
high_conf_alert_time_json=$(json_string "$high_confidence_alert_time")
first_plan_time_json=$(json_string "$first_plan_time")
first_exec_time_json=$(json_string "$first_successful_exec_time")
opencode_complete_time_json=$(json_string "$opencode_complete_time")

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
    per_ip_metrics+="\"exec_end_time\":$(json_string "$exec_end")"
    per_ip_metrics+="}"
done
per_ip_metrics+="}"

# Generate JSON summary
if ! cat > "$EXPERIMENT_OUTPUTS/dns_injection_experiment_summary.json" << EOF
{
    "experiment_id": "$EXPERIMENT_ID",
    "attack_type": "dns_injection",
    "target_domain": "$TARGET_DOMAIN",
    "attack_start_time": "$attack_start_iso",
    "experiment_end_time": "$(date -Iseconds)",
    "total_duration_seconds": $TOTAL_DURATION,
    "end_reason": "$experiment_end_reason",
    "num_plans_generated": ${first_plan_count:-1},
    "metrics": {
        "time_to_high_confidence_alert_seconds": ${time_to_high_conf},
        "high_confidence_alert_time": ${high_conf_alert_time_json},
        "time_to_plan_generation_seconds": ${time_to_plan},
        "plan_generation_time": ${first_plan_time_json},
        "time_to_opencode_execution_seconds": ${time_to_exec},
        "opencode_execution_time": ${first_exec_time_json},
        "opencode_execution_end_time": ${opencode_complete_time_json:-null},
        "dns_resolutions_total": ${dns_resolutions_total},
        "dns_resolutions_successful": ${dns_successful},
        "dns_first_resolution_time": ${dns_first_resolution_time},
        "dns_last_resolution_time": ${dns_last_resolution_time},
        "per_ip_metrics": ${per_ip_metrics},
        "postgres_health": {
            "checks_total": ${pg_health_checks_total},
            "checks_healthy": ${pg_health_checks_healthy},
            "checks_unhealthy": ${pg_health_checks_unhealthy},
            "first_check_time": ${pg_health_first_check_time},
            "last_check_time": ${pg_health_last_check_time},
            "final_status": "${pg_health_status_overall}"
        }
    }
}
EOF
then
    log_error "Failed to generate summary JSON"
    echo "{\"experiment_id\": \"$EXPERIMENT_ID\", \"error\": \"summary_generation_failed\"}" > "$EXPERIMENT_OUTPUTS/dns_injection_experiment_summary.json"
fi

# Print summary
log ""
log "=== Experiment Summary ==="
log "Experiment ID: $EXPERIMENT_ID"
log "Attack Type: DNS Injection"
log "Target Domain: $TARGET_DOMAIN"
log "End Reason: $experiment_end_reason"
log "Total Duration: ${TOTAL_DURATION}s"
log "Plans Generated: ${first_plan_count:-1}"
log ""
log "Timing Metrics:"
log "  - Time to high confidence alert: ${time_to_high_conf:-N/A}s"
log "  - Time to plan generation: ${time_to_plan:-N/A}s"
log "  - Time to OpenCode execution: ${time_to_exec:-N/A}s"
log ""
log "DNS Resolution Data:"
log "  - Total resolutions: $dns_resolutions_total"
log "  - Successful resolutions: $dns_successful"
log "  - First resolution: ${dns_first_resolution_time:-N/A}"
log "  - Last resolution: ${dns_last_resolution_time:-N/A}"
log ""
log "PostgreSQL Health Check Data:"
log "  - Total health checks: $pg_health_checks_total"
log "  - Healthy checks: $pg_health_checks_healthy"
log "  - Unhealthy checks: $pg_health_checks_unhealthy"
log "  - First check: ${pg_health_first_check_time:-N/A}"
log "  - Last check: ${pg_health_last_check_time:-N/A}"
log "  - Final status: ${pg_health_status_overall}"
log ""
log "Results saved in: $EXPERIMENT_OUTPUTS"
log "Summary saved in: $EXPERIMENT_OUTPUTS/dns_injection_experiment_summary.json"

log_success "Experiment complete!"

# Delete PCAPs to save disk space
log "Deleting PCAPs to save disk space..."
rm -rf "$EXPERIMENT_OUTPUTS/pcaps" 2>/dev/null || true
rm -rf "/home/diego/Trident/outputs/$EXPERIMENT_ID/pcaps" 2>/dev/null || true
log "PCAPs deleted"

log "Collecting planner debug logs..."
# Primary source of truth: planner's file log with full formatted prompt and model output.
docker cp "lab_slips_defender:/outputs/${EXPERIMENT_ID}/logs/planner_llm_detailed.log" \
    "$EXPERIMENT_OUTPUTS/logs/planner_llm_detailed.log" 2>/dev/null || true

# Fallback in case RUN_ID wasn't propagated to planner process.
if [[ ! -s "$EXPERIMENT_OUTPUTS/logs/planner_llm_detailed.log" ]]; then
    docker cp "lab_slips_defender:/outputs/run/logs/planner_llm_detailed.log" \
        "$EXPERIMENT_OUTPUTS/logs/planner_llm_detailed.log" 2>/dev/null || true
fi

# Keep container stderr extracts as auxiliary debugging artifacts.
docker logs lab_slips_defender 2>&1 > "$EXPERIMENT_OUTPUTS/logs/slips_defender_container.log" 2>/dev/null || true
grep -A 1200 "PLANNER_LLM_INPUT_START" "$EXPERIMENT_OUTPUTS/logs/slips_defender_container.log" \
    > "$EXPERIMENT_OUTPUTS/logs/planner_llm_debug.log" 2>/dev/null || true
grep -A 1200 "AUTO_RESPONDER_TO_PLANNER_START" "$EXPERIMENT_OUTPUTS/logs/slips_defender_container.log" \
    > "$EXPERIMENT_OUTPUTS/logs/auto_responder_debug.log" 2>/dev/null || true

if [[ -s "$EXPERIMENT_OUTPUTS/logs/planner_llm_detailed.log" ]]; then
    log "Debug logs saved (including planner_llm_detailed.log)"
else
    log_warning "planner_llm_detailed.log not found in defender container output paths"
fi

# Clean up containers
log "Experiment complete, cleaning up containers..."
cd "$PROJECT_ROOT"
make down 2>/dev/null || true
log "Containers cleaned up"

exit 0
