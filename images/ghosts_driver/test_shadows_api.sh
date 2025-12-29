#!/bin/bash
# Test Shadows API integration

set -e

SHADOWS_API_URL=${SHADOWS_API_URL:-http://localhost:5900}

echo "========================================="
echo "Testing Shadows API"
echo "========================================="
echo ""

# Test health endpoint
echo "1. Health Check"
echo "   GET $SHADOWS_API_URL/health"
if HEALTH=$(curl -sf "$SHADOWS_API_URL/health" 2>&1); then
    echo "   ✓ Status: OK"
    echo "$HEALTH" | jq . 2>/dev/null || echo "$HEALTH"
else
    echo "   ✗ Failed to connect to Shadows API"
    exit 1
fi

echo ""
echo "2. Test Chat Endpoint"
echo "   POST $SHADOWS_API_URL/chat"
CHAT_RESPONSE=$(curl -sf -X POST "$SHADOWS_API_URL/chat" \
    -H "Content-Type: application/json" \
    -d '{"query": "Hello, I am John Scott, a senior developer. How are you?"}' 2>&1)

if [ $? -eq 0 ]; then
    echo "   ✓ Response received:"
    echo "$CHAT_RESPONSE" | jq -r '.' 2>/dev/null || echo "$CHAT_RESPONSE"
else
    echo "   ✗ Chat endpoint failed"
fi

echo ""
echo "3. Test Activity Endpoint (SQL Query Generation)"
echo "   POST $SHADOWS_API_URL/activity"

ACTIVITY_QUERY="You are John Scott, a Senior Developer analyzing an employee database. Generate a realistic SQL query to find the top 10 highest paid employees. Use tables: employee (id, first_name, last_name) and salary (employee_id, amount, to_date). Current records have to_date='9999-01-01'. Return only the SQL query, no explanations."

ACTIVITY_RESPONSE=$(curl -sf -X POST "$SHADOWS_API_URL/activity" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$ACTIVITY_QUERY\"}" 2>&1)

if [ $? -eq 0 ]; then
    echo "   ✓ Response received:"
    echo "$ACTIVITY_RESPONSE" | jq -r '.' 2>/dev/null || echo "$ACTIVITY_RESPONSE"
else
    echo "   ✗ Activity endpoint failed"
fi

echo ""
echo "========================================="
echo "Shadows API Tests Complete"
echo "========================================="
echo ""
echo "If all tests passed, Shadows is ready for use with ghosts_driver"
echo ""
