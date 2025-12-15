#!/bin/bash
# Test script for LLM-driven John Scott timeline generation
# Run this locally to test before deploying to container

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "=========================================="
echo "Testing LLM Query Generator"
echo "=========================================="
echo ""

# Test 1: Generate queries with default scenario
echo "Test 1: Generate 3 queries with developer_routine scenario"
echo "Command: python3 llm_query_generator.py --num-queries 3 --scenario developer_routine"
echo ""
python3 "$SCRIPT_DIR/llm_query_generator.py" --num-queries 3 --scenario developer_routine --output /tmp/test_queries_1.txt || {
    echo "✗ Test 1 failed"
    exit 1
}
echo ""
echo "✓ Test 1 passed"
echo "Generated queries saved to: /tmp/test_queries_1.txt"
echo ""

# Test 2: Generate queries with hr_audit scenario
echo "=========================================="
echo "Test 2: Generate 2 queries with hr_audit scenario"
echo "Command: python3 llm_query_generator.py --num-queries 2 --scenario hr_audit"
echo ""
python3 "$SCRIPT_DIR/llm_query_generator.py" --num-queries 2 --scenario hr_audit --output /tmp/test_queries_2.txt || {
    echo "✗ Test 2 failed"
    exit 1
}
echo ""
echo "✓ Test 2 passed"
echo "Generated queries saved to: /tmp/test_queries_2.txt"
echo ""

# Test 3: Generate complete timeline
echo "=========================================="
echo "Test 3: Generate complete GHOSTS timeline"
echo "Command: python3 generate_timeline_llm.py --num-queries 4 --scenario exploratory"
echo ""
python3 "$SCRIPT_DIR/generate_timeline_llm.py" \
    --num-queries 4 \
    --scenario exploratory \
    --delay-before 3000 \
    --delay-after 5000 \
    --output /tmp/test_timeline.json > /dev/null || {
    echo "✗ Test 3 failed"
    exit 1
}
echo ""
echo "✓ Test 3 passed"
echo "Timeline saved to: /tmp/test_timeline.json"
echo ""

# Test 4: Validate timeline JSON structure
echo "=========================================="
echo "Test 4: Validate timeline JSON structure"
echo ""
if command -v jq &> /dev/null; then
    echo "Checking JSON validity..."
    if jq empty /tmp/test_timeline.json 2>/dev/null; then
        echo "✓ JSON is valid"
    else
        echo "✗ JSON validation failed"
        exit 1
    fi
    
    echo ""
    echo "Timeline structure:"
    echo "  - Status: $(jq -r '.Status' /tmp/test_timeline.json)"
    echo "  - Handler Type: $(jq -r '.TimeLineHandlers[0].HandlerType' /tmp/test_timeline.json)"
    echo "  - Loop: $(jq -r '.TimeLineHandlers[0].Loop' /tmp/test_timeline.json)"
    echo "  - Total Events: $(jq '.TimeLineHandlers[0].TimeLineEvents | length' /tmp/test_timeline.json)"
    echo ""
    
    # Check first event structure
    echo "First event sample:"
    jq '.TimeLineHandlers[0].TimeLineEvents[0] | {Command: .Command[:80], DelayBefore, DelayAfter}' /tmp/test_timeline.json
    echo ""
    
    echo "✓ Test 4 passed"
else
    echo "⚠ jq not installed, skipping JSON validation"
fi
echo ""

# Test 5: Test bash wrapper script
echo "=========================================="
echo "Test 5: Test generate_timeline.sh wrapper"
echo ""
NUM_QUERIES=3 SCENARIO=performance_review OUTPUT_FILE=/tmp/test_timeline_wrapper.json \
    bash "$SCRIPT_DIR/generate_timeline.sh" || {
    echo "✗ Test 5 failed"
    exit 1
}
echo ""
echo "✓ Test 5 passed"
echo ""

# Summary
echo "=========================================="
echo "✓ All tests passed successfully!"
echo "=========================================="
echo ""
echo "Generated test files:"
echo "  - /tmp/test_queries_1.txt (developer_routine queries)"
echo "  - /tmp/test_queries_2.txt (hr_audit queries)"
echo "  - /tmp/test_timeline.json (exploratory timeline)"
echo "  - /tmp/test_timeline_wrapper.json (performance_review timeline)"
echo ""
echo "You can inspect these files to verify the output quality."
echo ""
echo "Next steps:"
echo "  1. Review the generated timelines for quality"
echo "  2. Test in docker container with: make ghosts_psql_llm NUM_QUERIES=5 SCENARIO=developer_routine"
echo "  3. Monitor execution with: docker logs -f lab_ghosts_driver"
