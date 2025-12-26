#!/bin/bash
# Generate GHOSTS timeline using LLM queries
# This script is called by the docker entrypoint or can be run standalone

set -e

# Parameters with defaults
NUM_QUERIES=${NUM_QUERIES:-5}
SCENARIO=${SCENARIO:-developer_routine}
ROLE=${ROLE:-senior_developer_role}
DELAY_BEFORE=${DELAY_BEFORE:-5000}
DELAY_AFTER=${DELAY_AFTER:-10000}
LOOP=${LOOP:-false}
OUTPUT_FILE=${OUTPUT_FILE:-/opt/ghosts/bin/config/timeline.json}

echo "=== Generating GHOSTS Timeline with LLM ==="
echo "Parameters:"
echo "  - Number of queries: $NUM_QUERIES"
echo "  - Scenario: $SCENARIO"
echo "  - Database Role: $ROLE"
echo "  - Delay before: ${DELAY_BEFORE}ms"
echo "  - Delay after: ${DELAY_AFTER}ms"
echo "  - Loop: $LOOP"
echo "  - Output: $OUTPUT_FILE"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check Python availability
if ! command -v python3 &> /dev/null; then
    echo "✗ Error: python3 not found"
    exit 1
fi

# Install requirements if needed
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "Installing Python requirements..."
    pip3 install -q -r "$SCRIPT_DIR/requirements.txt" || true
fi

# Generate timeline
echo "Calling LLM to generate SQL queries..."
LOOP_FLAG=""
if [ "$LOOP" = "true" ]; then
    LOOP_FLAG="--loop"
fi

python3 "$SCRIPT_DIR/generate_timeline_llm.py" \
    --num-queries "$NUM_QUERIES" \
    --scenario "$SCENARIO" \
    --role "$ROLE" \
    --delay-before "$DELAY_BEFORE" \
    --delay-after "$DELAY_AFTER" \
    $LOOP_FLAG \
    --output "$OUTPUT_FILE" 2>&1 | grep -E "^(✓|⚠|✗|Generating|Creating)" || true

if [ ! -f "$OUTPUT_FILE" ]; then
    echo "✗ Error: Timeline file not created at $OUTPUT_FILE"
    exit 1
fi

echo ""
echo "✓ Timeline generation complete"
echo "  Location: $OUTPUT_FILE"
echo "  Size: $(du -h "$OUTPUT_FILE" | cut -f1)"

# Validate JSON
if command -v jq &> /dev/null; then
    if jq empty "$OUTPUT_FILE" 2>/dev/null; then
        EVENT_COUNT=$(jq '.TimeLineHandlers[0].TimeLineEvents | length' "$OUTPUT_FILE")
        echo "  Events: $EVENT_COUNT"
        echo "✓ Timeline JSON is valid"
    else
        echo "✗ Warning: Timeline JSON validation failed"
    fi
fi
