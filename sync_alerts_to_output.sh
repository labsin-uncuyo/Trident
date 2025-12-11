#!/bin/bash

# Script to sync Slips alerts from container to Trident/output/{id}/ directory
# Usage: ./sync_alerts_to_output.sh

set -euo pipefail

# Export Docker host for colima
export DOCKER_HOST="unix:///Users/diegoforni/.colima/default/docker.sock"

CONTAINER_NAME="lab_slips_defender"
TRIDENT_OUTPUT_DIR="./outputs"

# Get current RUN_ID from the .current_run file
if [[ -f "${TRIDENT_OUTPUT_DIR}/.current_run" ]]; then
    RUN_ID=$(cat "${TRIDENT_OUTPUT_DIR}/.current_run" | head -1 | tr -d '\n')
else
    echo "❌ Could not find RUN_ID in ${TRIDENT_OUTPUT_DIR}/.current_run"
    exit 1
fi

TARGET_DIR="${TRIDENT_OUTPUT_DIR}/${RUN_ID}/slips"

echo "🔄 Syncing alerts from ${CONTAINER_NAME} to ${TARGET_DIR}"

# Check if container is running
if ! docker ps --format "table {{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    echo "❌ Container ${CONTAINER_NAME} is not running"
    exit 1
fi

# Create target directory if it doesn't exist
mkdir -p "${TARGET_DIR}"

# Copy all alert files from container to host
echo "📋 Copying alert files..."
docker cp "${CONTAINER_NAME}:/outputs/" "${TRIDENT_OUTPUT_DIR}/temp_sync_" 2>/dev/null || {
    echo "❌ Failed to copy from container"
    exit 1
}

# Move alert files to the correct location
echo "📁 Moving files to ${TARGET_DIR}..."
if [[ -d "${TRIDENT_OUTPUT_DIR}/temp_sync_/outputs" ]]; then
    # Find and copy all alert files
    find "${TRIDENT_OUTPUT_DIR}/temp_sync_/outputs" -name "alerts.log" -type f | while read -r alert_file; do
        rel_path="${alert_file#${TRIDENT_OUTPUT_DIR}/temp_sync_/outputs/}"
        target_file="${TARGET_DIR}/${rel_path}"
        mkdir -p "$(dirname "$target_file")"
        cp "$alert_file" "$target_file"
        echo "✅ Copied ${rel_path}"
    done

    find "${TRIDENT_OUTPUT_DIR}/temp_sync_/outputs" -name "alerts.json" -type f | while read -r alert_file; do
        rel_path="${alert_file#${TRIDENT_OUTPUT_DIR}/temp_sync_/outputs/}"
        target_file="${TARGET_DIR}/${rel_path}"
        mkdir -p "$(dirname "$target_file")"
        cp "$alert_file" "$target_file"
        echo "✅ Copied ${rel_path}"
    done
else
    echo "⚠️ No alert files found in container"
fi

# Cleanup temp directory
rm -rf "${TRIDENT_OUTPUT_DIR}/temp_sync_"

echo "✅ Alert sync completed!"
echo "📊 Alerts available in: ${TARGET_DIR}"

# Show summary
if [[ -f "${TARGET_DIR}/alerts.log" ]]; then
    alert_count=$(wc -l < "${TARGET_DIR}/alerts.log" 2>/dev/null || echo "0")
    echo "📈 Total alerts in alerts.log: ${alert_count}"
fi

if [[ -f "${TARGET_DIR}/alerts.json" ]]; then
    json_size=$(du -h "${TARGET_DIR}/alerts.json" | cut -f1 2>/dev/null || echo "0B")
    echo "📊 alerts.json size: ${json_size}"
fi