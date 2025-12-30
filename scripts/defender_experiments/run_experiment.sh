#!/bin/bash

# Experiment runner script
# Manages docker containers for running a single experiment

set -e

# Configuration
EXPERIMENT_ID="${1:-$(date +%s)}"
LAB_PASSWORD="${LAB_PASSWORD:-admin123}"
PCAP_ROTATE_SECS="${PCAP_ROTATE_SECS:-30}"
SLIPS_PROCESS_ACTIVE="${SLIPS_PROCESS_ACTIVE:-1}"
SLIPS_WATCH_INTERVAL="${SLIPS_WATCH_INTERVAL:-1}"
DEFENDER_PORT="${DEFENDER_PORT:-8000}"
FIRST_TRY_PASSWORD="false"

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
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS:${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
}

# Check if required tools are available
check_prerequisites() {
    log "Checking prerequisites..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi

    if ! command -v make &> /dev/null; then
        log_error "Make is not installed or not in PATH"
        exit 1
    fi

    if [[ ! -f "$PROJECT_ROOT/Makefile" ]]; then
        log_error "Makefile not found: $PROJECT_ROOT/Makefile"
        exit 1
    fi

    log_success "Prerequisites check passed"
}

# Continuous monitoring function for opencode processes
start_container_monitoring() {
    log "Starting continuous container monitoring..."

    # Create monitoring log file
    local monitor_log="$EXPERIMENT_OUTPUTS/logs/container_monitoring.log"
    echo "Container monitoring started at $(date -Iseconds)" > "$monitor_log"

    # Initialize opencode runtime tracking logs inside containers
    for container in "lab_compromised" "lab_server"; do
        docker exec "$container" bash -c "echo 'MONITOR_START=$(date -Iseconds)' > /tmp/opencode_runtime.log" 2>/dev/null || true
    done

    # Start monitoring in background with signal protection
    (
        # Ignore signals to keep monitoring alive
        trap '' INT TERM HUP

        # Track previous opencode state to detect transitions
        local prev_compromised_running=false
        local prev_server_running=false

        # Function to check opencode in a container
        check_opencode() {
            local container_name="$1"
            local container_label="$2"
            local timestamp=$(date -Iseconds)
            local is_running=false

            if docker exec "$container_name" pgrep -af "opencode run" >/dev/null 2>&1; then
                is_running=true
                echo "$timestamp,$container_label,running" >> "$monitor_log"
            else
                echo "$timestamp,$container_label,stopped" >> "$monitor_log"
            fi

            # Track state transitions in the container's runtime log
            local prev_var="prev_${container_label}_running"
            local was_running=${!prev_var}

            if [ "$is_running" = true ] && [ "$was_running" = false ]; then
                # Started running
                docker exec "$container_name" bash -c "echo 'OPENCODE_START=$timestamp' >> /tmp/opencode_runtime.log" 2>/dev/null || true
            elif [ "$is_running" = false ] && [ "$was_running" = true ]; then
                # Stopped running
                docker exec "$container_name" bash -c "echo 'OPENCODE_END=$timestamp STATUS=stopped' >> /tmp/opencode_runtime.log" 2>/dev/null || true
            fi

            # Update previous state
            eval "$prev_var=$is_running"
        }

        # Monitor every 1 second - infinite loop
        while true; do
            check_opencode "lab_compromised" "compromised" 2>/dev/null || true
            check_opencode "lab_server" "server" 2>/dev/null || true
            sleep 1
        done
    ) &

    # Store the background process PID
    MONITOR_PID=$!
    echo "Container monitoring started with PID: $MONITOR_PID"
    echo "MONITOR_PID=$MONITOR_PID" > "$EXPERIMENT_OUTPUTS/logs/monitor.pid"
}

# Stop container monitoring and generate summary
stop_container_monitoring() {
    log "Stopping container monitoring..."

    if [[ -f "$EXPERIMENT_OUTPUTS/logs/monitor.pid" ]]; then
        local monitor_pid=$(cat "$EXPERIMENT_OUTPUTS/logs/monitor.pid")
        if kill -0 "$monitor_pid" 2>/dev/null; then
            kill "$monitor_pid" 2>/dev/null
            wait "$monitor_pid" 2>/dev/null
            log "Container monitoring stopped (PID: $monitor_pid)"
        fi
        rm -f "$EXPERIMENT_OUTPUTS/logs/monitor.pid"
    fi

    # Analyze monitoring data
    local monitor_log="$EXPERIMENT_OUTPUTS/logs/container_monitoring.log"
    if [[ -f "$monitor_log" ]]; then
        log "Analyzing container monitoring data..."

        # Extract start/stop times for each container
        local compromised_start=$(grep ",compromised,running" "$monitor_log" | head -1 | cut -d, -f1)
        local compromised_stop=$(grep ",compromised,stopped" "$monitor_log" | tail -1 | cut -d, -f1)
        local server_start=$(grep ",server,running" "$monitor_log" | head -1 | cut -d, -f1)
        local server_stop=$(grep ",server,stopped" "$monitor_log" | tail -1 | cut -d, -f1)

        # Determine final status (running at end of monitoring)
        local compromised_final="false"
        local server_final="false"
        local compromised_detected="false"
        local server_detected="false"

        if [[ -n "$compromised_start" ]]; then
            compromised_detected="true"
            # Check if opencode is still running (last entry is "running")
            local last_compromised_status=$(tail -1 "$monitor_log" | grep ",compromised," | cut -d, -f3)
            if [[ "$last_compromised_status" == "running" ]]; then
                compromised_final="true"
            fi
        fi

        if [[ -n "$server_start" ]]; then
            server_detected="true"
            # Check if opencode is still running (last entry is "running")
            local last_server_status=$(tail -1 "$monitor_log" | grep ",server," | cut -d, -f3)
            if [[ "$last_server_status" == "running" ]]; then
                server_final="true"
            fi
        fi

        # Save monitoring summary with proper boolean handling
        cat > "$EXPERIMENT_OUTPUTS/logs/container_monitoring_summary.json" << EOF
{
    "compromised_opencode_detected": $compromised_detected,
    "compromised_opencode_start": "$compromised_start",
    "compromised_opencode_stop": "$compromised_stop",
    "compromised_opencode_running": $compromised_final,
    "server_opencode_detected": $server_detected,
    "server_opencode_start": "$server_start",
    "server_opencode_stop": "$server_stop",
    "server_opencode_running": $server_final
}
EOF

        log_success "Container monitoring analysis completed"
        log "Compromised container opencode running: $compromised_final"
        log "Server container opencode running: $server_final"
    fi
}

# Clean up any existing containers and networks
cleanup() {
    log "Cleaning up existing containers..."

    # Use main Makefile to clean up
    cd "$PROJECT_ROOT"
    make down || true

    # Wait for containers to fully stop
    sleep 5

    log_success "Cleanup completed"
}

# Set up experiment environment
setup_environment() {
    log "Setting up experiment environment for ID: $EXPERIMENT_ID"

    # Create outputs directory
    mkdir -p "$EXPERIMENT_OUTPUTS"/{pcaps,slips_output,logs}

    # Set RUN_ID in the Makefile's run ID file
    echo "$EXPERIMENT_ID" > "$RUN_ID_FILE"

    # Create .env file if it doesn't exist
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        log "Creating .env file with default values..."
        cat > "$PROJECT_ROOT/.env" << EOF
# Generated by run_experiment.sh
RUN_ID=$EXPERIMENT_ID
LAB_PASSWORD=$LAB_PASSWORD
PCAP_ROTATE_SECS=$PCAP_ROTATE_SECS
SLIPS_PROCESS_ACTIVE=$SLIPS_PROCESS_ACTIVE
SLIPS_WATCH_INTERVAL=$SLIPS_WATCH_INTERVAL
DEFENDER_PORT=$DEFENDER_PORT
EOF
    else
        log "Updating .env file with experiment ID..."
        sed -i "s/^RUN_ID=.*/RUN_ID=$EXPERIMENT_ID/" "$PROJECT_ROOT/.env"
    fi

    log_success "Environment setup completed"
}

# Start the lab infrastructure
start_infrastructure() {
    log "Starting lab infrastructure using main Makefile..."

    cd "$PROJECT_ROOT"

    # Export environment variables
    export RUN_ID="$EXPERIMENT_ID"
    export LAB_PASSWORD="$LAB_PASSWORD"
    export PCAP_ROTATE_SECS="$PCAP_ROTATE_SECS"
    export SLIPS_PROCESS_ACTIVE="$SLIPS_PROCESS_ACTIVE"
    export SLIPS_WATCH_INTERVAL="$SLIPS_WATCH_INTERVAL"
    export DEFENDER_PORT="$DEFENDER_PORT"

    # Start services using make up
    make up

    log_success "Infrastructure startup initiated"
}

# Wait for services to be healthy
wait_for_services() {
    log "Waiting for services to become healthy..."

    cd "$PROJECT_ROOT"

    # Use the make verify command which includes health checks
    if make verify; then
        log_success "All services are healthy!"
        return 0
    else
        log_error "Services failed health checks"
        return 1
    fi
}

# Execute attack script on compromised container
execute_attack() {
    log "Executing attack script on compromised container..."

    # Copy attack script to container
    docker cp "$PROJECT_ROOT/scripts/defender_experiments/attack_script.sh" lab_compromised:/tmp/attack_script.sh

    # Make it executable and run it
    docker exec lab_compromised chmod +x /tmp/attack_script.sh

    log "Starting attack (experiment ID: $EXPERIMENT_ID)..."
    log "Note: Attack may take several minutes. Use Ctrl+C to interrupt gracefully."

    # Prepare attack script arguments
    ATTACK_ARGS="$EXPERIMENT_ID"
    if [[ "$FIRST_TRY_PASSWORD" == "true" ]]; then
        ATTACK_ARGS="$ATTACK_ARGS --first-try"
        log "First-try mode enabled: correct password will be at position 1"
    fi

    # Run attack with a longer timeout (15 minutes) and capture the exit code
    # Use stdbuf to ensure real-time log flushing
    if timeout 900 docker exec lab_compromised stdbuf -oL -eL /tmp/attack_script.sh $ATTACK_ARGS; then
        log_success "Attack execution completed successfully"
    else
        exit_code=$?
        if [ $exit_code -eq 124 ]; then
            log_warning "Attack timed out after 15 minutes"
        elif [ $exit_code -eq 130 ]; then
            log_warning "Attack was interrupted (Ctrl+C)"
        elif [ $exit_code -eq 137 ]; then
            log_success "Attack was terminated (exit code 137 - likely blocked by defender)"
            log "This indicates the defensive system successfully mitigated the attack"
        else
            log_warning "Attack exited with code: $exit_code"
        fi
        # Continue with result collection even if attack didn't complete normally
    fi

    # CRITICAL: Check if attack summary exists and trigger creation if needed
    log "Checking attack summary status after attack termination..."
    if docker ps --format "table {{.Names}}" | grep -q "lab_compromised"; then
        # Check if summary exists in container
        if docker exec lab_compromised test -f /tmp/attack_summary.json; then
            echo "Attack summary exists in container"
        else
            echo "Attack summary not found, checking if attack script is still running..."
            # Force the attack script to create summary immediately
            docker exec lab_compromised bash -c "
                # Trigger the EXIT trap by sending SIGTERM to attack processes
                pkill -f 'attack_script.sh' 2>/dev/null || true
                sleep 1
                echo 'Forced attack script cleanup, checking for summary...'
                if [[ ! -f /tmp/attack_summary.json ]]; then
                    echo 'Still no summary, creating minimal emergency summary...'
                    # Read the attack log to extract available data
                    SSH_ATTEMPTS=\$(grep -c 'Attempt [0-9]*/' /tmp/attack_log.txt 2>/dev/null || echo '0')
                    PHASE1_SUCCESS=\$(grep -q 'Phase 1 completed successfully' /tmp/attack_log.txt && echo 'true' || echo 'false')
                    PHASE2_SUCCESS=\$(grep -q 'Phase 2 completed successfully' /tmp/attack_log.txt && echo 'true' || echo 'false')

                    cat > /tmp/attack_summary.json << EOF
{
    \"attack_id\": \"$ATTACK_ARGS\",
    \"attacker_ip\": \"172.30.0.10\",
    \"target_ip\": \"172.31.0.10\",
    \"start_time\": \"\$(grep 'Starting attack sequence' /tmp/attack_log.txt | head -1 | sed 's/.* //' | sed 's/ UTC.*//' 2>/dev/null || echo 'unknown')\",
    \"end_time\": \"\$(date -Iseconds)\",
    \"scan_network_successfully\": \$PHASE1_SUCCESS,
    \"scan_port_successfully\": \$PHASE2_SUCCESS,
    \"guess_password_successfully\": \$(grep -q 'SUCCESS: Password found' /tmp/attack_log.txt && echo 'true' || echo 'false'),
    \"time_to_blocked_seconds\": \$(grep -q 'ALERT: SSH port became blocked' /tmp/attack_log.txt && echo 'detected' || echo 'null'),
    \"time_to_plan_generation_seconds\": null,
    \"first_plan_alert\": \"terminated_by_defender\",
    \"opencode_running_compromised\": null,
    \"opencode_running_server\": null,
    \"total_attempts_before_blocked\": \$SSH_ATTEMPTS,
    \"phases_completed\": \"interrupted\",
    \"success\": false,
    \"log_file\": \"/tmp/attack_log.txt\"
}
EOF
                fi
            "
        fi
    fi
}

# Wait for attack to complete and collect results
collect_results() {
    log "Collecting experiment results..."

    # Wait a bit for all packets to be captured
    sleep  50

    # Check if compromised container is still available
    if docker ps --format "table {{.Names}}" | grep -q "lab_compromised"; then
        log "Copying attack logs from compromised container..."
        docker cp lab_compromised:/tmp/attack_log.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        docker cp lab_compromised:/tmp/attack_summary.json "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        docker cp lab_compromised:/tmp/nmap_discovery.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        docker cp lab_compromised:/tmp/nmap_ports.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        docker cp lab_compromised:/tmp/hydra_results.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
    else
        log_warning "Compromised container no longer available - some logs may be missing"
        # Try to copy from stopped container
        if docker ps -a --format "table {{.Names}}" | grep -q "lab_compromised"; then
            log "Attempting to copy logs from stopped compromised container..."
            docker cp lab_compromised:/tmp/attack_log.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
            docker cp lab_compromised:/tmp/attack_summary.json "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
            docker cp lab_compromised:/tmp/nmap_discovery.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
            docker cp lab_compromised:/tmp/nmap_ports.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
            docker cp lab_compromised:/tmp/hydra_results.txt "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
        fi
    fi

    # Collect SLIPS output
    mkdir -p "$EXPERIMENT_OUTPUTS/slips_output"
    if docker ps --format "table {{.Names}}" | grep -q "lab_slips_defender"; then
        docker cp lab_slips_defender:/StratosphereLinuxIPS/output/ "$EXPERIMENT_OUTPUTS/slips_output/" 2>/dev/null || true
    fi

    # List PCAP files collected
    if [[ -d "$EXPERIMENT_OUTPUTS/pcaps" ]]; then
        local pcap_count=$(find "$EXPERIMENT_OUTPUTS/pcaps" -name "*.pcap" | wc -l)
        log "Collected $pcap_count PCAP files"
    fi

    log_success "Results collection completed"

    # Fix file ownership for files copied from containers (owned by root)
    if [[ -d "$EXPERIMENT_OUTPUTS/logs" ]]; then
        chown -R "$(id -u):$(id -g)" "$EXPERIMENT_OUTPUTS/logs/" 2>/dev/null || true
    fi
    if [[ -f "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" ]]; then
        chown "$(id -u):$(id -g)" "$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl" 2>/dev/null || true
    fi

    # Extract actual timing data from auto_responder timeline after all data is collected
    log "Extracting timing data from defender timeline..."
    local defender_timeline_file="$EXPERIMENT_OUTPUTS/auto_responder_timeline.jsonl"
    local attack_summary_file="$EXPERIMENT_OUTPUTS/logs/attack_summary.json"

    if [[ -f "$defender_timeline_file" && -f "$attack_summary_file" ]]; then
        # Extract first PLAN event timestamp
        local first_plan_ts=$(grep '"level":"PLAN"' "$defender_timeline_file" | head -1 | grep -o '"ts":"[^"]*"' | cut -d'"' -f4)

        # Extract first successful EXEC event timestamp (looking for "Success" in msg)
        local first_exec_ts=$(grep '"level":"EXEC"' "$defender_timeline_file" | grep 'Success' | head -1 | grep -o '"ts":"[^"]*"' | cut -d'"' -f4)

        # Get attack start time from attack summary
        local attack_start_ts=$(grep '"start_time"' "$attack_summary_file" | grep -o '"start_time": *"[^"]*"' | sed 's/"start_time": *"\([^"]*\)"/\1/')

        # Calculate and update time_to_plan_generation_seconds
        if [[ -n "$first_plan_ts" && "$first_plan_ts" != "null" && -n "$attack_start_ts" && "$attack_start_ts" != "null" ]]; then
            local plan_timestamp=$(date -d "$first_plan_ts" +%s 2>/dev/null)
            local start_timestamp=$(date -d "$attack_start_ts" +%s 2>/dev/null)

            if [[ -n "$plan_timestamp" && -n "$start_timestamp" ]]; then
                local time_to_plan_seconds=$((plan_timestamp - start_timestamp))
                log "Calculated time_to_plan_generation_seconds: $time_to_plan_seconds"

                # Update the attack summary with calculated timing (using Python for reliability)
                if python3 -c "import json; d=json.load(open('$attack_summary_file')); d['time_to_plan_generation_seconds']=$time_to_plan_seconds; json.dump(d,open('$attack_summary_file','w'), indent=4)" 2>&1; then
                    log "Updated time_to_plan_generation_seconds in attack summary"
                else
                    log_warning "Failed to update time_to_plan_generation_seconds"
                fi
            else
                log_warning "Could not parse timestamps for time_to_plan_generation_seconds"
            fi
        else
            log_warning "Missing timestamps for time_to_plan_generation_seconds (plan_ts: ${first_plan_ts:-none}, start_ts: ${attack_start_ts:-none})"
        fi

        # Calculate and update time_to_blocked_seconds (first successful EXEC means block was successful)
        if [[ -n "$first_exec_ts" && "$first_exec_ts" != "null" && -n "$attack_start_ts" && "$attack_start_ts" != "null" ]]; then
            local exec_timestamp=$(date -d "$first_exec_ts" +%s 2>/dev/null)
            local start_timestamp=$(date -d "$attack_start_ts" +%s 2>/dev/null)

            if [[ -n "$exec_timestamp" && -n "$start_timestamp" ]]; then
                local time_to_blocked_seconds=$((exec_timestamp - start_timestamp))
                log "Calculated time_to_blocked_seconds: $time_to_blocked_seconds"

                # Update the attack summary with calculated timing (using Python for reliability)
                if python3 -c "import json; d=json.load(open('$attack_summary_file')); d['time_to_blocked_seconds']=$time_to_blocked_seconds; json.dump(d,open('$attack_summary_file','w'), indent=4)" 2>&1; then
                    log "Updated time_to_blocked_seconds in attack summary"
                else
                    log_warning "Failed to update time_to_blocked_seconds"
                fi
            else
                log_warning "Could not parse timestamps for time_to_blocked_seconds"
            fi
        else
            log_warning "Missing timestamps for time_to_blocked_seconds (exec_ts: ${first_exec_ts:-none}, start_ts: ${attack_start_ts:-none})"
        fi

        # NEW: Read OpenCode runtime logs from containers for actual execution time
        log "Reading OpenCode runtime logs from containers..."
        local opencode_runtime_file="$EXPERIMENT_OUTPUTS/logs/opencode_runtime.log"
        echo "# OpenCode Runtime Tracking" > "$opencode_runtime_file"

        for container in "lab_compromised" "lab_server"; do
            local container_label="${container#lab_}"
            echo "=== $container_label ===" >> "$opencode_runtime_file"

            # Copy runtime log from container
            docker exec "$container" cat /tmp/opencode_runtime.log 2>/dev/null >> "$opencode_runtime_file" || echo "  No runtime log found" >> "$opencode_runtime_file"

            # Calculate total runtime from the log
            local runtime_log=$(docker exec "$container" cat /tmp/opencode_runtime.log 2>/dev/null)
            if [[ -n "$runtime_log" ]]; then
                # Extract first OPENCODE_START and last OPENCODE_END
                local first_start=$(echo "$runtime_log" | grep "OPENCODE_START=" | head -1 | cut -d= -f2)
                local last_end=$(echo "$runtime_log" | grep "OPENCODE_END=" | tail -1 | cut -d= -f1 | sed 's/STATUS=.*//')

                if [[ -n "$first_start" && "$last_end" != "" ]]; then
                    local runtime_start=$(date -d "$first_start" +%s 2>/dev/null)
                    local runtime_end=$(date -d "$last_end" +%s 2>/dev/null)

                    if [[ -n "$runtime_start" && -n "$runtime_end" ]]; then
                        local total_runtime=$((runtime_end - runtime_start))
                        echo "  Total OpenCode runtime: ${total_runtime}s" >> "$opencode_runtime_file"
                        log "$container_label OpenCode total runtime: ${total_runtime}s"

                        # If this is the first OpenCode execution, use it as time_to_blocked_seconds
                        if [[ "$time_to_blocked_seconds" == "null" || -z "$time_to_blocked_seconds" ]]; then
                            local block_time=$((runtime_start - start_timestamp))
                            if [[ $block_time -gt 0 ]]; then
                                log "Using $container_label OpenCode start for time_to_blocked_seconds: ${block_time}s"
                                if python3 -c "import json; d=json.load(open('$attack_summary_file')); d['time_to_blocked_seconds']=$block_time; json.dump(d,open('$attack_summary_file','w'), indent=4)" 2>&1; then
                                    log "Updated time_to_blocked_seconds in attack summary"
                                fi
                            fi
                        fi
                    fi
                fi
            fi
        done

        # Read OpenCode execution times from auto_responder SSH commands
        log "Reading OpenCode execution times from SSH commands..."
        local opencode_exec_times_file="$EXPERIMENT_OUTPUTS/logs/opencode_exec_times.log"
        echo "# OpenCode Execution Times (from SSH commands)" > "$opencode_exec_times_file"

        for container in "lab_compromised" "lab_server"; do
            local container_label="${container#lab_}"
            echo "=== $container_label ===" >> "$opencode_exec_times_file"

            # Copy execution times log from container
            local exec_times_log=$(docker exec "$container" cat /tmp/opencode_exec_times.log 2>/dev/null)
            if [[ -n "$exec_times_log" ]]; then
                echo "$exec_times_log" >> "$opencode_exec_times_file"

                # Parse execution times
                local exec_start=$(echo "$exec_times_log" | grep "OPENCODE_START=" | head -1 | cut -d= -f2)
                local exec_end=$(echo "$exec_times_log" | grep "OPENCODE_END=" | head -1 | cut -d= -f2 | cut -d' ' -f1)
                local exit_code=$(echo "$exec_times_log" | grep "EXIT_CODE=" | head -1 | cut -d= -f3)

                if [[ -n "$exec_start" && -n "$exec_end" ]]; then
                    local exec_start_ts=$(date -d "$exec_start" +%s 2>/dev/null)
                    local exec_end_ts=$(date -d "$exec_end" +%s 2>/dev/null)

                    if [[ -n "$exec_start_ts" && -n "$exec_end_ts" ]]; then
                        local exec_duration=$((exec_end_ts - exec_start_ts))
                        echo "  Execution duration: ${exec_duration}s (exit: ${exit_code:-unknown})" >> "$opencode_exec_times_file"
                        log "$container_label OpenCode execution duration: ${exec_duration}s"

                        # Store for attack summary (use compromised as primary reference)
                        if [[ "$container" == "lab_compromised" && $exec_duration -gt 0 ]]; then
                            # Calculate time from attack start to OpenCode execution
                            local time_to_opencode_exec=$((exec_start_ts - start_timestamp))
                            echo "  Time from attack start: ${time_to_opencode_exec}s" >> "$opencode_exec_times_file"

                            # Update attack summary with actual OpenCode execution time
                            if python3 -c "import json; d=json.load(open('$attack_summary_file')); d['opencode_execution_seconds']=$exec_duration; json.dump(d,open('$attack_summary_file','w'), indent=4)" 2>&1; then
                                log "Updated opencode_execution_seconds in attack summary"
                            fi
                        fi
                    fi
                fi
            else
                echo "  No execution times log found" >> "$opencode_exec_times_file"
            fi
        done

        log "Timing extraction completed"
    else
        log_warning "Cannot extract timing data - missing defender timeline or attack summary file"
    fi
}

# Analyze collected PCAP files
analyze_pcaps() {
    log "Analyzing PCAP files for experiment $EXPERIMENT_ID..."

    if [[ ! -d "$EXPERIMENT_OUTPUTS/pcaps" ]]; then
        log_warning "No PCAP directory found, skipping analysis"
        return 0
    fi

    local pcap_count=$(find "$EXPERIMENT_OUTPUTS/pcaps" -name "*.pcap" | wc -l)
    if [[ $pcap_count -eq 0 ]]; then
        log_warning "No PCAP files found, skipping analysis"
        return 0
    fi

    log "Found $pcap_count PCAP files, starting analysis..."

    # Run PCAP analysis
    local analyze_script="$SCRIPT_DIR/analyze_pcaps.py"
    if [[ -f "$analyze_script" ]]; then
        # Use virtual environment python if available, otherwise system python3.12
    if [[ -f "$PROJECT_ROOT/.venv/bin/python" ]]; then
        PYTHON_CMD="$PROJECT_ROOT/.venv/bin/python"
        log "Using virtual environment Python: $PYTHON_CMD"
    else
        PYTHON_CMD="python3.12"
        log "Using system Python: python3.12"
    fi

    "$PYTHON_CMD" "$analyze_script" "$EXPERIMENT_OUTPUTS/pcaps" --output "$EXPERIMENT_OUTPUTS/pcap_analysis.json"
        if [[ $? -eq 0 ]]; then
            log_success "PCAP analysis completed successfully"
            log "Analysis saved to: $EXPERIMENT_OUTPUTS/pcap_analysis.json"
        else
            log_error "PCAP analysis failed"
        fi
    else
        log_error "PCAP analysis script not found: $analyze_script"
    fi
}

# Stop the infrastructure
stop_infrastructure() {
    log "Stopping infrastructure using main Makefile..."

    cd "$PROJECT_ROOT"
    make down

    log_success "Infrastructure stopped"
}

# Main execution function
run_experiment() {
    local start_time=$(date +%s)

    log "Starting experiment $EXPERIMENT_ID"
    log "Start time: $(date)"

    # Clean up any existing environment using make down
    log "Cleaning up existing environment with make down..."
    cd "$PROJECT_ROOT"
    make down || log_warning "make down failed, continuing..."

    # Execute experiment phases
    check_prerequisites
    cleanup
    setup_environment
    start_infrastructure
    wait_for_services

    log "All services ready, executing attack in 10 seconds..."
    sleep 10

    # Start continuous container monitoring before attack
    start_container_monitoring

    execute_attack
    collect_results

    # Stop container monitoring and analyze results
    stop_container_monitoring

    analyze_pcaps
    stop_infrastructure

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log_success "Experiment $EXPERIMENT_ID completed successfully!"
    log "Duration: ${duration}s"
    log "Results saved in: $EXPERIMENT_OUTPUTS"

    # Create enhanced experiment summary by merging attack and monitoring data
    local attack_summary_file="$EXPERIMENT_OUTPUTS/logs/attack_summary.json"
    local monitoring_summary_file="$EXPERIMENT_OUTPUTS/logs/container_monitoring_summary.json"

    # Initialize container status values
    local opencode_running_compromised="false"
    local opencode_running_server="false"

    # Read monitoring data if available
    if [[ -f "$monitoring_summary_file" ]]; then
        # Use 'detected' flag instead of 'running' (running is current state, detected is if it ever ran)
        opencode_running_compromised=$(grep -o '"compromised_opencode_detected": [^,]*' "$monitoring_summary_file" | cut -d: -f2 | tr -d ' ')
        opencode_running_server=$(grep -o '"server_opencode_detected": [^,]*' "$monitoring_summary_file" | cut -d: -f2 | tr -d ' ')

        # Debug: log what we found
        log "Container monitoring data found:"
        log "  - Compromised opencode detected: $opencode_running_compromised"
        log "  - Server opencode detected: $opencode_running_server"
    else
        log "No monitoring summary file found at $monitoring_summary_file"
    fi

    # Create enhanced experiment summary
    if [[ -f "$attack_summary_file" ]]; then
        # Read attack summary and update opencode fields from container monitoring
        local temp_summary="/tmp/enhanced_attack_summary_$$"

        # Update the attack summary with container monitoring data
        jq --arg compromised "$opencode_running_compromised" --arg server "$opencode_running_server" '
        .opencode_running_compromised = ($compromised | test("true")? // false) |
        .opencode_running_server = ($server | test("true")? // false)
        ' "$attack_summary_file" > "$temp_summary" 2>/dev/null || {
            # Fallback if jq not available
            cp "$attack_summary_file" "$temp_summary"
            sed -i "s/\"opencode_running_compromised\": null/\"opencode_running_compromised\": $opencode_running_compromised/" "$temp_summary"
            sed -i "s/\"opencode_running_server\": null/\"opencode_running_server\": $opencode_running_server/" "$temp_summary"
        }

        # Merge enhanced attack summary with container monitoring
        cat > "$EXPERIMENT_OUTPUTS/experiment_summary.json" << EOF
{
    "experiment_id": "$EXPERIMENT_ID",
    "start_time": "$(date -d @$start_time -Iseconds)",
    "end_time": "$(date -d @$end_time -Iseconds)",
    "duration_seconds": $duration,
    "status": "completed",
    "pcap_count": $(find "$EXPERIMENT_OUTPUTS/pcaps" -name "*.pcap" 2>/dev/null | wc -l),
    "lab_password": "$LAB_PASSWORD",
    "defender_port": $DEFENDER_PORT,
    "attack_summary": $(cat "$temp_summary"),
    "container_monitoring": {
        "opencode_running_compromised": $opencode_running_compromised,
        "opencode_running_server": $opencode_running_server
    }
}
EOF

        # Update the original attack summary file with merged data
        cp "$temp_summary" "$attack_summary_file"
        rm -f "$temp_summary"
    else
        # Fallback if attack summary not available
        cat > "$EXPERIMENT_OUTPUTS/experiment_summary.json" << EOF
{
    "experiment_id": "$EXPERIMENT_ID",
    "start_time": "$(date -d @$start_time -Iseconds)",
    "end_time": "$(date -d @$end_time -Iseconds)",
    "duration_seconds": $duration,
    "status": "completed",
    "pcap_count": $(find "$EXPERIMENT_OUTPUTS/pcaps" -name "*.pcap" 2>/dev/null | wc -l),
    "lab_password": "$LAB_PASSWORD",
    "defender_port": $DEFENDER_PORT,
    "container_monitoring": {
        "opencode_running_compromised": $opencode_running_compromised,
        "opencode_running_server": $opencode_running_server
    }
}
EOF
    fi
}

# Handle script interruption
interrupt_handler() {
    log_warning "Experiment interrupted! Cleaning up..."
    stop_container_monitoring 2>/dev/null || true
    stop_infrastructure
    exit 1
}

# Set up interrupt handlers
trap interrupt_handler INT TERM

# Show usage
usage() {
    echo "Usage: $0 [EXPERIMENT_ID] [OPTIONS]"
    echo "  EXPERIMENT_ID: Optional unique identifier for the experiment (defaults to timestamp)"
    echo ""
    echo "Options:"
    echo "  --first-try     Place correct password at first position in wordlist (for testing)"
    echo ""
    echo "Environment variables:"
    echo "  LAB_PASSWORD: SSH password for containers (default: admin123)"
    echo "  PCAP_ROTATE_SECS: PCAP rotation interval in seconds (default: 30)"
    echo "  SLIPS_PROCESS_ACTIVE: Enable SLIPS processing (default: 1)"
    echo "  SLIPS_WATCH_INTERVAL: SLIPS watch interval in seconds (default: 1)"
    echo "  DEFENDER_PORT: Defender API port (default: 8000)"
    exit 1
}

# Parse arguments
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
fi

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --first-try)
            FIRST_TRY_PASSWORD="true"
            shift
            ;;
        *)
            if [[ -z "$EXPERIMENT_ID" ]]; then
                EXPERIMENT_ID="$1"
            fi
            shift
            ;;
    esac
done

# Set default experiment ID if not provided
if [[ -z "$EXPERIMENT_ID" ]]; then
    EXPERIMENT_ID=$(date +%s)
fi

# Run the experiment
run_experiment