#!/bin/bash
# Script to generate GHOSTS timeline using LLM
# This script will be run inside the container to create the timeline dynamically

set -e

echo "[INFO] Starting LLM Timeline Generator for John Scott"

# Set environment variables from Docker if available
export OPENAI_API_KEY="${OPENAI_API_KEY:-YOUR_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://chat.ai.e-infra.cz/api/v1}"
export LLM_MODEL="${LLM_MODEL:-qwen3-coder}"
export LLM_TEMPERATURE="${LLM_TEMPERATURE:-0.7}"

echo "[INFO] LLM Configuration:"
echo "  - Base URL: $OPENAI_BASE_URL"
echo "  - Model: $LLM_MODEL"
echo "  - Temperature: $LLM_TEMPERATURE"

# Directory where timeline will be generated
TIMELINE_DIR="/opt/john_scott_llm"
TIMELINE_FILE="$TIMELINE_DIR/timeline_john_scott_llm.json"

# Create directory if it doesn't exist
mkdir -p "$TIMELINE_DIR"

# Copy the generator script if not already there
if [ ! -f "$TIMELINE_DIR/generate_timeline_llm.py" ]; then
    echo "[INFO] Copying LLM timeline generator script..."
    cp /opt/john_scott_llm/generate_timeline_llm.py "$TIMELINE_DIR/"
fi

cd "$TIMELINE_DIR"

# Generate the timeline
echo "[INFO] Generating timeline with LLM..."
python3 generate_timeline_llm.py

if [ -f "$TIMELINE_FILE" ]; then
    echo "[SUCCESS] Timeline generated successfully: $TIMELINE_FILE"
    
    # Show summary
    QUERY_COUNT=$(grep -c "Command" "$TIMELINE_FILE" || echo "0")
    echo "[INFO] Generated timeline with $QUERY_COUNT commands"
    
    # Copy to config location for GHOSTS
    mkdir -p /app/config
    cp "$TIMELINE_FILE" /app/config/timeline.json
    echo "[INFO] Timeline copied to /app/config/timeline.json"
    
    exit 0
else
    echo "[ERROR] Failed to generate timeline"
    exit 1
fi
