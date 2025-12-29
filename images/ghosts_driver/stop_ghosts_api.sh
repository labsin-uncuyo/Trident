#!/bin/bash
# Stop GHOSTS API + Shadows infrastructure

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "Stopping GHOSTS API + Shadows"
echo "========================================="
echo ""

if ! docker compose version &> /dev/null; then
    echo "ERROR: docker compose not available"
    exit 1
fi

# Source .env file from main Trident directory if available
ENV_FILE="$SCRIPT_DIR/../../.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Stop the services
docker compose --env-file "$ENV_FILE" -f docker-compose-ghosts-api.yml down

echo ""
echo "✓ All services stopped"
echo ""
echo "To remove all data (including database):"
echo "  docker compose --env-file ../../.env -f docker-compose-ghosts-api.yml down -v"
echo ""
