#!/bin/bash

# Simple test script that works with existing make up infrastructure
# Performs: 1) Network discovery, 2) SSH port discovery, 3) Brute force attack

set -e

EXPERIMENT_ID=${1:-"test_$(date +%Y%m%d_%H%M%S)"}
echo "Starting experiment: $EXPERIMENT_ID"

# Check if containers are running
if ! docker ps | grep -q "lab_router"; then
    echo "ERROR: Lab infrastructure not running. Please run 'make up' first."
    exit 1
fi

echo "✓ Infrastructure is running"

# Create output directory
OUTPUT_DIR="/home/shared/Trident/outputs/experiment_$EXPERIMENT_ID"
mkdir -p "$OUTPUT_DIR"

# Copy and execute attack script
echo "Executing attack on compromised container..."
docker cp /home/shared/Trident/scripts/defender_experiments/attack_script.sh lab_compromised:/tmp/attack_script.sh
docker exec lab_compromised chmod +x /tmp/attack_script.sh
docker exec lab_compromised /tmp/attack_script.sh

# Wait for attack to complete
sleep 5

# Copy PCAP files for analysis
echo "Copying PCAP files for analysis..."
PCAP_DIR="$OUTPUT_DIR/pcaps"
mkdir -p "$PCAP_DIR"
docker cp lab_router:/pcaps/. "$PCAP_DIR/" 2>/dev/null || true

# Run PCAP analysis
echo "Running PCAP analysis..."
if [[ -f "/home/shared/Trident/scripts/defender_experiments/analyze_pcaps.py" ]]; then
    python3 /home/shared/Trident/scripts/defender_experiments/analyze_pcaps.py "$PCAP_DIR" --output "$OUTPUT_DIR/pcap_analysis.json"
fi

# Copy SLIPS logs
echo "Copying SLIPS logs..."
SLIPS_DIR="$OUTPUT_DIR/slips_logs"
mkdir -p "$SLIPS_DIR"
docker cp lab_slips_defender:/logs/. "$SLIPS_DIR/" 2>/dev/null || true

echo "✓ Experiment completed: $EXPERIMENT_ID"
echo "Results saved to: $OUTPUT_DIR"
echo "PCAP Analysis: $OUTPUT_DIR/pcap_analysis.json"