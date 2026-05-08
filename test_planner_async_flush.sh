#!/bin/bash
# Test async flush - run this after the defender container is running

echo "=== Testing Planner Async Flush ==="
echo ""

# Set up environment
export LANGFUSE_PUBLIC_KEY="pk-lf-trident-defender"
export LANGFUSE_SECRET_KEY="sk-lf-trident-defender"
export LANGFUSE_HOST="http://host.docker.internal:3000"
export OPENAI_API_KEY="sk-test"
export OPENAI_BASE_URL="http://10.0.0.49:8080/p/diego/v1"
export LLM_MODEL="gemma4"
export LANGFUSE_ENABLED="true"
export LANGFUSE_ASYNC_FLUSH="true"

# Test 1: With async flush enabled (default)
echo "Test 1: ASYNC flush enabled"
echo "----------------------------"
curl -s -X POST http://localhost:1654/plan \
  -H "Content-Type: application/json" \
  -d '{
    "alert": "2026-05-08T17:14:16+00:00 8.8.8.8 DNS TXT high entropy test.com",
    "temperature": 0.2,
    "max_tokens": 500
  }' | jq -r '"Has executor_ip: \(.executor_host_ip // "null"), Plan length: \(.plan | length // 0)"'

echo ""
echo ""

# Test 2: With sync flush (for comparison)
echo "Test 2: SYNC flush (for comparison)"
echo "------------------------------------"
curl -s -X POST http://localhost:1654/plan \
  -H "Content-Type: application/json" \
  -d '{
    "alert": "2026-05-08T17:14:16+00:00 8.8.8.8 DNS TXT high entropy test.com",
    "temperature": 0.2,
    "max_tokens": 500
  }' | jq -r '"Has executor_ip: \(.executor_host_ip // "null"), Plan length: \(.plan | length // 0)"'

echo ""
echo ""
echo "=== Check planner logs for timing ==="
echo "The timing traces will show 'langfuse_flush' duration"
echo "With async flush, it should return immediately (~1ms)"
echo "With sync flush, it will show the full flush time (~6s)"
