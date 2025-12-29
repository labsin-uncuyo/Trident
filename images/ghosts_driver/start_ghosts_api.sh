#!/bin/bash
# Start GHOSTS API + Shadows infrastructure
# This script launches the GHOSTS API server and Shadows component

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "GHOSTS API + Shadows Startup"
echo "========================================="
echo ""

# Source .env file from main Trident directory
ENV_FILE="$SCRIPT_DIR/../../.env"
if [ -f "$ENV_FILE" ]; then
    echo "Loading configuration from .env file..."
    set -a  # Export all variables
    source "$ENV_FILE"
    set +a
fi

# Check for required environment variables
if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY not set"
    echo "Please set it in your .env file at: $(realpath $SCRIPT_DIR/../../.env)"
    echo "Or export it manually:"
    echo "  export OPENAI_API_KEY=your_api_key_here"
    exit 1
fi

echo "✓ OPENAI_API_KEY configured (${#OPENAI_API_KEY} chars)"

# Optional: set default values
export OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.openai.com/v1}
export LLM_MODEL=${LLM_MODEL:-gpt-4o-mini}

echo "✓ Base URL: $OPENAI_BASE_URL"
echo "✓ Model: $LLM_MODEL"
echo ""

# Check if docker compose is available
if ! docker compose version &> /dev/null; then
    echo "ERROR: docker compose not available"
    echo "Please install Docker Compose plugin"
    exit 1
fi

echo "Starting GHOSTS API + Shadows services..."
echo ""

# Start the services with .env file
docker compose --env-file "$ENV_FILE" -f docker-compose-ghosts-api.yml up -d

echo ""
echo "Waiting for services to be ready..."
sleep 5

# Check service health
echo ""
echo "Checking service status..."
docker compose --env-file "$ENV_FILE" -f docker-compose-ghosts-api.yml ps

echo ""
echo "========================================="
echo "Services Status"
echo "========================================="

# Check GHOSTS API
if curl -sf http://localhost:5000 > /dev/null 2>&1; then
    echo "✓ GHOSTS API: http://localhost:5000 (Ready)"
else
    echo "⚠ GHOSTS API: http://localhost:5000 (Not responding)"
fi

# Check GHOSTS UI
if curl -sf http://localhost:8081 > /dev/null 2>&1; then
    echo "✓ GHOSTS UI: http://localhost:8081 (Ready)"
else
    echo "⚠ GHOSTS UI: http://localhost:8081 (Not responding)"
fi

# Check Shadows API
if curl -sf http://localhost:5900/health > /dev/null 2>&1; then
    echo "✓ Shadows API: http://localhost:5900 (Ready)"
    SHADOWS_INFO=$(curl -s http://localhost:5900/health | jq -r '"\(.llm_provider) - \(.model)"' 2>/dev/null || echo "unknown")
    echo "  Provider: $SHADOWS_INFO"
else
    echo "⚠ Shadows API: http://localhost:5900 (Not responding)"
fi

# Check Shadows UI
if curl -sf http://localhost:7860 > /dev/null 2>&1; then
    echo "✓ Shadows UI: http://localhost:7860 (Ready)"
else
    echo "⚠ Shadows UI: http://localhost:7860 (Not responding)"
fi

# Check Grafana
if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    echo "✓ Grafana: http://localhost:3000 (Ready)"
else
    echo "⚠ Grafana: http://localhost:3000 (Not responding)"
fi

echo ""
echo "========================================="
echo "Next Steps"
echo "========================================="
echo ""
echo "1. Access GHOSTS UI at: http://localhost:8081"
echo "2. Test Shadows API at: http://localhost:7860"
echo "3. View logs with: docker compose -f docker-compose-ghosts-api.yml logs -f"
echo ""
echo "To start ghosts_driver with Shadows integration:"
echo "  docker-compose --profile benign up -d ghosts_driver"
echo "  or set GHOSTS_MODE=shadows in your environment"
echo ""
echo "To stop all services:"
echo "  ./stop_ghosts_api.sh"
echo ""
