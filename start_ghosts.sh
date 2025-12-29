#!/bin/bash

# Start GHOSTS driver container with proper profile dependencies
# This script ensures all required services are running before starting ghosts_driver

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==========================================="
echo "Starting GHOSTS Driver"
echo "==========================================="

# Check if core infrastructure is running
if ! docker ps | grep -q "lab_compromised"; then
    echo "❌ Error: Core infrastructure not running!"
    echo "   Please run 'make up' first to start the lab infrastructure"
    exit 1
fi

# Check if GHOSTS infrastructure (Shadows API) is needed
if [ "$GHOSTS_MODE" = "shadows" ]; then
    echo ""
    echo "Checking GHOSTS infrastructure (Shadows API)..."
    
    if ! docker ps | grep -q "ghosts-shadows"; then
        echo "⚠ Shadows API not running. Starting GHOSTS infrastructure..."
        cd images/ghosts_driver
        ./start_ghosts_api.sh
        cd "$SCRIPT_DIR"
    else
        echo "✓ Shadows API already running"
    fi
fi

# Set defaults if not provided
export RUN_ID="${RUN_ID:-run_$(date +%Y%m%d_%H%M%S)}"
export GHOSTS_MODE="${GHOSTS_MODE:-shadows}"

echo ""
echo "Configuration:"
echo "  RUN_ID: $RUN_ID"
echo "  GHOSTS_MODE: $GHOSTS_MODE"
echo ""

# Start ghosts_driver with both core and benign profiles
echo "Starting ghosts_driver container..."
docker compose --profile core --profile benign up -d ghosts_driver

echo ""
echo "==========================================="
echo "GHOSTS Driver Started"
echo "==========================================="
echo ""
echo "Monitor logs with:"
echo "  docker compose logs -f ghosts_driver"
echo ""
echo "Stop with:"
echo "  docker compose stop ghosts_driver"
echo ""
