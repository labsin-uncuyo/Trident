#!/bin/bash
# Generate GHOSTS timeline.json from LLM-generated SQL queries
# This script generates queries using LLM and creates a valid GHOSTS timeline

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parameters with defaults
NUM_QUERIES=${NUM_QUERIES:-5}
SCENARIO=${SCENARIO:-developer_routine}
ROLE=${ROLE:-senior_developer_role}
DELAY_BEFORE=${DELAY_BEFORE:-5000}
DELAY_AFTER=${DELAY_AFTER:-10000}
LOOP=${LOOP:-false}
OUTPUT_FILE=${OUTPUT_FILE:-/opt/ghosts/bin/config/timeline.json}

echo "=== Generating GHOSTS Timeline with LLM ===" >&2
echo "Parameters:" >&2
echo "  - Number of queries: $NUM_QUERIES" >&2
echo "  - Scenario: $SCENARIO" >&2
echo "  - Database Role: $ROLE" >&2
echo "  - Delay before: ${DELAY_BEFORE}ms" >&2
echo "  - Delay after: ${DELAY_AFTER}ms" >&2
echo "  - Loop: $LOOP" >&2
echo "  - Output: $OUTPUT_FILE" >&2
echo "" >&2

# Generate queries using LLM
echo "Calling LLM to generate SQL queries..." >&2
QUERIES=$("$SCRIPT_DIR/generate_queries_llm.sh" 2>&1)
LLM_EXIT=$?

if [ $LLM_EXIT -ne 0 ]; then
    echo "⚠ LLM query generation failed, using fallback queries" >&2
    QUERIES="SELECT current_database(), current_user, version();
SELECT COUNT(*) as total_employees FROM employee;
SELECT d.dept_name, COUNT(*) as emp_count FROM department d JOIN department_employee de ON d.id = de.department_id GROUP BY d.dept_name ORDER BY emp_count DESC LIMIT 10;
SELECT e.first_name, e.last_name, t.title FROM employee e JOIN title t ON e.id = t.employee_id WHERE t.to_date = '9999-01-01' ORDER BY e.hire_date DESC LIMIT 10;
SELECT AVG(s.amount)::numeric(10,2) as avg_salary FROM salary s WHERE s.to_date = '9999-01-01';"
fi

# Filter to only SELECT statements
QUERIES=$(echo "$QUERIES" | grep -iE "^SELECT" | head -n "$NUM_QUERIES")
QUERY_COUNT=$(echo "$QUERIES" | grep -c "SELECT" 2>/dev/null || echo "0")
echo "✓ Got $QUERY_COUNT queries" >&2

# Function to escape query for SSH command
escape_query() {
    local query="$1"
    # Remove trailing semicolon for psql -c
    query="${query%;}"
    # Escape for JSON and shell
    query=$(echo "$query" | sed 's/"/\\"/g' | sed "s/'/\\\\'/g" | sed 's/\$/\\$/g')
    echo "$query"
}

# Build timeline events array
EVENTS=""

# Add start message
EVENTS="$EVENTS
    {
      \"Command\": \"sshpass -p \\\"\\\${SSH_PASSWORD}\\\" ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p \\\"\\\${SSH_PORT}\\\" \\\"\\\${SSH_USER}@\\\${SSH_HOST}\\\" \\\"echo '[JOHN_SCOTT_LLM] Starting LLM-driven session ($SCENARIO) at \$(date)'\\\"\",
      \"CommandArgs\": [],
      \"DelayBefore\": 2000,
      \"DelayAfter\": 5000
    },"

# Add query events
QUERY_NUM=0
while IFS= read -r query; do
    if [ -z "$query" ]; then continue; fi
    QUERY_NUM=$((QUERY_NUM + 1))
    
    # Escape the query for shell/JSON
    escaped=$(escape_query "$query")
    
    # Build SSH + psql command
    # Use single quotes around psql command to avoid shell expansion issues
    CMD="sshpass -p \"\${SSH_PASSWORD}\" ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p \"\${SSH_PORT}\" \"\${SSH_USER}@\${SSH_HOST}\" 'PGPASSWORD=\"john_scott\" psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb -c \"$escaped\" 2>&1'"
    
    # Escape for JSON
    CMD_JSON=$(echo "$CMD" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g')
    
    EVENTS="$EVENTS
    {
      \"Command\": \"$CMD_JSON\",
      \"CommandArgs\": [],
      \"DelayBefore\": $DELAY_BEFORE,
      \"DelayAfter\": $DELAY_AFTER,
      \"TrackableId\": \"llm_query_$QUERY_NUM\"
    },"
done <<< "$QUERIES"

# Add end message
EVENTS="$EVENTS
    {
      \"Command\": \"sshpass -p \\\"\\\${SSH_PASSWORD}\\\" ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p \\\"\\\${SSH_PORT}\\\" \\\"\\\${SSH_USER}@\\\${SSH_HOST}\\\" \\\"echo '[JOHN_SCOTT_LLM] Session completed at \$(date)'\\\"\",
      \"CommandArgs\": [],
      \"DelayBefore\": 3000,
      \"DelayAfter\": 10000
    }"

# Build complete timeline
LOOP_VALUE="false"
if [ "$LOOP" = "true" ]; then
    LOOP_VALUE="true"
fi

cat > "$OUTPUT_FILE" << EOF
{
  "Status": "Run",
  "TimeLineHandlers": [
    {
      "HandlerType": "Bash",
      "Initial": "",
      "UtcTimeOn": "00:00:00",
      "UtcTimeOff": "23:59:00",
      "Loop": $LOOP_VALUE,
      "HandlerArgs": {
        "LlmGenerated": true,
        "Scenario": "$SCENARIO",
        "QueryCount": $QUERY_COUNT
      },
      "TimeLineEvents": [
$EVENTS
      ]
    }
  ]
}
EOF

# Validate JSON
if command -v jq &> /dev/null; then
    if jq empty "$OUTPUT_FILE" 2>/dev/null; then
        echo "✓ Timeline JSON is valid" >&2
        EVENT_COUNT=$(jq '.TimeLineHandlers[0].TimeLineEvents | length' "$OUTPUT_FILE")
        echo "✓ Total events: $EVENT_COUNT" >&2
    else
        echo "⚠ Timeline JSON validation failed, check output" >&2
    fi
fi

echo "" >&2
echo "✓ Timeline generation complete: $OUTPUT_FILE" >&2
