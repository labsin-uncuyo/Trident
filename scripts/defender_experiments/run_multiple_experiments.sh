#!/bin/bash

# Multiple experiment runner script
# Runs the experiment script 5 times and copies all results to experiment_output

set -e

# Configuration
NUM_EXPERIMENTS=5
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPERIMENT_SCRIPT="$SCRIPT_DIR/run_experiment.sh"
EXPERIMENT_OUTPUT_ROOT="$PROJECT_ROOT/experiment_output"

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

# Check if the experiment script exists
check_prerequisites() {
    log "Checking prerequisites..."

    if [[ ! -f "$EXPERIMENT_SCRIPT" ]]; then
        log_error "Experiment script not found: $EXPERIMENT_SCRIPT"
        exit 1
    fi

    if [[ ! -x "$EXPERIMENT_SCRIPT" ]]; then
        log_error "Experiment script is not executable: $EXPERIMENT_SCRIPT"
        chmod +x "$EXPERIMENT_SCRIPT"
    fi

    log_success "Prerequisites check passed"
}

# Copy all results from an experiment to the experiment_output folder
copy_results() {
    local experiment_id="$1"
    local run_number="$2"
    local source_dir="$PROJECT_ROOT/outputs/$experiment_id"
    local target_dir="$EXPERIMENT_OUTPUT_ROOT/run_${run_number}_$experiment_id"

    log "Copying results for experiment $experiment_id to $target_dir"

    if [[ ! -d "$source_dir" ]]; then
        log_error "Source directory not found: $source_dir"
        return 1
    fi

    # Create the target directory
    mkdir -p "$target_dir"

    # Copy all contents recursively
    cp -r "$source_dir"/* "$target_dir/"

    # Also copy any logs from the script directory
    if [[ -d "$SCRIPT_DIR/logs" ]]; then
        mkdir -p "$target_dir/script_logs"
        cp -r "$SCRIPT_DIR/logs"/* "$target_dir/script_logs/" 2>/dev/null || true
    fi

    # The experiment console output is already in the logs directory
    # since we created it before running the experiment

    log_success "Results copied to: $target_dir"
}

# Main execution function
run_multiple_experiments() {
    local start_time=$(date +%s)
    local completed_experiments=0

    log "Starting $NUM_EXPERIMENTS experiments"
    log "Start time: $(date)"

    # Create the main experiment_output directory
    mkdir -p "$EXPERIMENT_OUTPUT_ROOT"

    # Run experiments
    for ((i=1; i<=NUM_EXPERIMENTS; i++)); do
        log ""
        log "${GREEN}===================================${NC}"
        log "${GREEN}Starting experiment $i of $NUM_EXPERIMENTS${NC}"
        log "${GREEN}===================================${NC}"
        log ""

        # Generate a unique experiment ID for this run
        local experiment_id="exp_$(date +%s)_run_$i"

        # Create a logs directory for this experiment run
        local experiment_log_dir="$EXPERIMENT_OUTPUT_ROOT/run_${i}_$experiment_id/logs"
        mkdir -p "$experiment_log_dir"

        # Run the experiment script and capture output
        log "Running experiment $i with ID: $experiment_id"
        log "Console output will be saved to: $experiment_log_dir/experiment_output.log"

        local experiment_log_file="$experiment_log_dir/experiment_output.log"
        local experiment_error_file="$experiment_log_dir/experiment_error.log"

        # Run the experiment script with output captured
        if "$EXPERIMENT_SCRIPT" "$experiment_id" > "$experiment_log_file" 2>&1; then
            log_success "Experiment $i completed successfully"

            # Also copy stdout and stderr separately if available
            echo "Experiment $i completed successfully at $(date)" >> "$experiment_log_dir/completion_status.log"

            # Copy results to experiment_output
            if copy_results "$experiment_id" "$i"; then
                log_success "Results for experiment $i copied successfully"
                ((completed_experiments++))
            else
                log_error "Failed to copy results for experiment $i"
            fi

            # Clean up the original outputs directory to save space
            if [[ -d "$PROJECT_ROOT/outputs/$experiment_id" ]]; then
                log "Cleaning up original outputs directory..."
                rm -rf "$PROJECT_ROOT/outputs/$experiment_id"
            fi
        else
            log_error "Experiment $i failed"
            echo "Experiment $i failed at $(date)" >> "$experiment_log_dir/completion_status.log"

            # Even if failed, still try to copy any partial results
            if [[ -d "$PROJECT_ROOT/outputs/$experiment_id" ]]; then
                log "Copying partial results for failed experiment $i..."
                copy_results "$experiment_id" "$i" || true
            fi
        fi

        # Wait a bit between experiments
        if [[ $i -lt $NUM_EXPERIMENTS ]]; then
            log "Waiting 30 seconds before next experiment..."
            sleep 30
        fi
    done

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log ""
    log "${GREEN}===================================${NC}"
    log "${GREEN}All experiments completed!${NC}"
    log "${GREEN}===================================${NC}"
    log "Total experiments run: $NUM_EXPERIMENTS"
    log "Successfully completed: $completed_experiments"
    log "Failed: $((NUM_EXPERIMENTS - completed_experiments))"
    log "Total duration: ${duration}s ($((duration / 60)) minutes)"
    log "All results saved in: $EXPERIMENT_OUTPUT_ROOT"
    log "Console output for each experiment is saved in the respective logs subdirectory"

    # Create a summary of all experiments
    local summary_file="$EXPERIMENT_OUTPUT_ROOT/experiment_summary.json"
    cat > "$summary_file" << EOF
{
    "total_experiments": $NUM_EXPERIMENTS,
    "completed_experiments": $completed_experiments,
    "failed_experiments": $((NUM_EXPERIMENTS - completed_experiments)),
    "start_time": "$(date -d @$start_time -Iseconds)",
    "end_time": "$(date -d @$end_time -Iseconds)",
    "duration_seconds": $duration,
    "results_directory": "$EXPERIMENT_OUTPUT_ROOT",
    "experiment_runs": [
EOF

    # Add info about each experiment run
    for ((i=1; i<=NUM_EXPERIMENTS; i++)); do
        if [[ $i -gt 1 ]]; then
            echo "," >> "$summary_file"
        fi
        local run_dir_pattern="$EXPERIMENT_OUTPUT_ROOT/run_${i}_*"
        local run_dir=$(ls -d $run_dir_pattern 2>/dev/null | head -n 1)
        local status="failed"
        local log_path=""

        if [[ -d "$run_dir" ]]; then
            status="completed"
            log_path="$run_dir/logs/experiment_output.log"
        fi

        echo "        {\"run_number\": $i, \"status\": \"$status\", \"console_log\": \"$log_path\"}" >> "$summary_file"
    done

    echo "    ]" >> "$summary_file"
    echo "}" >> "$summary_file"

    log "Summary created: $summary_file"
}

# Show usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -n, --num-experiments NUM    Number of experiments to run (default: 5)"
    echo "  -h, --help                  Show this help message"
    echo ""
    echo "This script runs the experiment script multiple times and copies all results"
    echo "to the experiment_output directory after each run."
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--num-experiments)
            NUM_EXPERIMENTS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate number of experiments
if ! [[ "$NUM_EXPERIMENTS" =~ ^[0-9]+$ ]] || [[ "$NUM_EXPERIMENTS" -lt 1 ]]; then
    log_error "Number of experiments must be a positive integer"
    exit 1
fi

# Handle script interruption
interrupt_handler() {
    log_warning "Script interrupted! Cleaning up..."
    exit 1
}

# Set up interrupt handlers
trap interrupt_handler INT TERM

# Run the experiments
check_prerequisites
run_multiple_experiments