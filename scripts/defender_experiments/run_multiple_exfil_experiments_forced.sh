#!/bin/bash

# FORCED Multiple exfiltration experiment runner script
# This script WILL run all experiments no matter what happens

# NO set -e - we want to continue on ALL errors
# NO traps that exit - we want to ignore interrupts

# Configuration
NUM_EXPERIMENTS=30
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPERIMENT_SCRIPT="$SCRIPT_DIR/exfiltration_experiment.sh"
EXPERIMENT_OUTPUT_ROOT="$PROJECT_ROOT/experiment_output"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] EXFIL FORCED RUNNER:${NC} $1" | tee -a /tmp/exfil_forced_runner.log
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] EXFIL FORCED RUNNER SUCCESS:${NC} $1" | tee -a /tmp/exfil_forced_runner.log
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] EXFIL FORCED RUNNER ERROR:${NC} $1" | tee -a /tmp/exfil_forced_runner.log
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] EXFIL FORCED RUNNER WARNING:${NC} $1" | tee -a /tmp/exfil_forced_runner.log
}

# IGNORE ALL SIGNALS - THIS SCRIPT CANNOT BE STOPPED
trap '' INT TERM QUIT HUP

# Force create the experiment output directory
mkdir -p "$EXPERIMENT_OUTPUT_ROOT"

# Main execution - FORCED to complete
run_forced_exfil_experiments() {
    local start_time=$(date +%s)
    local completed_experiments=0

    log "FORCED: Starting $NUM_EXPERIMENTS exfiltration experiments - WILL COMPLETE ALL"
    log "FORCED: Start time: $(date)"
    echo "EXFIL FORCED RUN STARTED: $(date)" > /tmp/exfil_forced_runner_status.log

    # Force the loop to run all experiments
    for ((i=1; i<=NUM_EXPERIMENTS; i++)); do
        log ""
        log "${GREEN}===================================${NC}"
        log "${GREEN}FORCED: Starting exfil experiment $i of $NUM_EXPERIMENTS${NC}"
        log "${GREEN}FORCED: Progress - WILL NOT STOP UNTIL ALL DONE${NC}"
        log "${GREEN}===================================${NC}"
        log ""

        # Generate a unique experiment ID
        local experiment_id="exfil_forced_$(date +%s)_run_$i"

        # Create experiment directory
        local experiment_dir="$EXPERIMENT_OUTPUT_ROOT/exfil_forced_run_${i}_$experiment_id"
        mkdir -p "$experiment_dir/logs"

        # ALWAYS run the experiment, ignore all errors
        log "FORCED: Running exfiltration experiment $i with ID: $experiment_id"

        # Use timeout to prevent hanging, but continue on any failure
        # Increased timeout to 30 minutes (exfil can take up to 15 min max + setup time)
        timeout 1800 "$EXPERIMENT_SCRIPT" "$experiment_id" > "$experiment_dir/logs/experiment_output.log" 2>&1 || {
            local exit_code=$?
            log_error "Exfil experiment $i failed with code $exit_code - CONTINUING ANYWAY"
            echo "Exfil experiment $i failed with exit code $exit_code at $(date)" >> "$experiment_dir/logs/forced_status.log"

            # Log additional context for debugging
            if [[ $exit_code -eq 137 ]]; then
                log_error "Exfil experiment $i was terminated (likely blocked by defender or timeout)"
                echo "Possible defender action detected - experiment terminated" >> "$experiment_dir/logs/forced_status.log"
            elif [[ $exit_code -eq 124 ]]; then
                log_error "Exfil experiment $i timed out after 30 minutes"
                echo "Experiment timeout" >> "$experiment_dir/logs/forced_status.log"
            fi
        }

        # ALWAYS copy results if they exist
        local source_dir="$PROJECT_ROOT/outputs/$experiment_id"
        if [[ -d "$source_dir" ]]; then
            log "FORCED: Copying results for exfil experiment $i"
            cp -r "$source_dir"/* "$experiment_dir/" 2>/dev/null || log_warning "Failed to copy some results for exfil experiment $i"
            ((completed_experiments++))
            log_success "Exfil experiment $i results copied"
        else
            log_warning "No results directory found for exfil experiment $i"
        fi

        # Always log progress
        log "FORCED: Exfil experiment $i processing complete. $i/$NUM_EXPERIMENTS processed."
        echo "Exfil experiment $i processed at $(date)" >> /tmp/exfil_forced_runner_status.log

        # Clean up original outputs if exists
        if [[ -d "$source_dir" ]]; then
            rm -rf "$source_dir" 2>/dev/null || true
        fi

        # Wait between experiments
        if [[ $i -lt $NUM_EXPERIMENTS ]]; then
            log "FORCED: Waiting 30 seconds before next experiment..."
            sleep 30
        fi
    done

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log ""
    log "${GREEN}===================================${NC}"
    log "${GREEN}FORCED: ALL $NUM_EXPERIMENTS EXFIL EXPERIMENTS COMPLETED!${NC}"
    log "${GREEN}===================================${NC}"
    log "FORCED: Total experiments processed: $NUM_EXPERIMENTS"
    log "FORCED: Successfully completed: $completed_experiments"
    log "FORCED: Total duration: ${duration}s ($((duration / 60)) minutes)"
    log "FORCED: All results saved in: $EXPERIMENT_OUTPUT_ROOT"

    echo "EXFIL FORCED RUN COMPLETED: $(date), Total: $NUM_EXPERIMENTS, Successful: $completed_experiments" >> /tmp/exfil_forced_runner_status.log
}

# Start the forced run
log "EXFIL FORCED RUNNER INITIALIZED - CANNOT BE STOPPED"
run_forced_exfil_experiments
log "EXFIL FORCED RUNNER FINISHED - ALL EXPERIMENTS COMPLETED"
