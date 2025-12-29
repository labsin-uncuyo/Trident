#!/bin/bash
# Generate SQL queries using LLM API
# This script calls the OpenAI-compatible API to generate realistic SQL queries

set -e

# Parameters
NUM_QUERIES=${NUM_QUERIES:-5}
SCENARIO=${SCENARIO:-developer_routine}
ROLE=${ROLE:-senior_developer_role}
OUTPUT_FILE=${OUTPUT_FILE:-/tmp/generated_queries.json}

# API Configuration
API_KEY="${OPENAI_API_KEY}"
API_BASE="${OPENAI_BASE_URL}"
MODEL="${LLM_MODEL}"

# Validate API key
if [ -z "$API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY not set" >&2
    exit 1
fi

# Database schema context
SCHEMA_CONTEXT='PostgreSQL Database: labdb
Connection: SSH to labuser@172.30.0.10, then psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb

Tables:
- employee (id, birth_date, first_name, last_name, gender, hire_date)
- department (id, dept_name)  
- department_employee (employee_id, department_id, from_date, to_date)
- department_manager (employee_id, department_id, from_date, to_date)
- salary (employee_id, amount, from_date, to_date)
- title (employee_id, title, from_date, to_date)
- events (id, msg)

Notes:
- Current records use to_date = 9999-01-01
- Use explicit columns, JOINs, WHERE, ORDER BY, LIMIT
- User john_scott has full SELECT access'

# Scenario descriptions
case "$SCENARIO" in
    developer_routine)
        SCENARIO_DESC="Senior Developer daily routine: checking team members, reviewing hires, analyzing salaries, tracking promotions"
        ;;
    hr_audit)
        SCENARIO_DESC="HR audit: employee counts by department, salary ranges, tenure analysis, manager assignments"
        ;;
    performance_review)
        SCENARIO_DESC="Performance review prep: direct reports, salary history, time in position, career progression"
        ;;
    exploratory)
        SCENARIO_DESC="Database exploration: analytical queries, statistics, complex joins, data quality checks"
        ;;
    *)
        SCENARIO_DESC="General database analysis and queries"
        ;;
esac

# Build the prompt
PROMPT="You are John Scott, a Senior Developer. Generate exactly $NUM_QUERIES different PostgreSQL SELECT queries for the following scenario:

Scenario: $SCENARIO_DESC

Database Schema:
$SCHEMA_CONTEXT

Requirements:
1. Generate EXACTLY $NUM_QUERIES unique SQL SELECT statements
2. Each query must be a single line, valid PostgreSQL
3. Use realistic analytical queries a senior developer would run
4. Include JOINs, aggregations, WHERE clauses as appropriate
5. Always use LIMIT for queries that return many rows
6. Output ONLY the SQL queries, one per line, no explanations
7. Each query must end with a semicolon

Output format (one query per line):
SELECT ...;
SELECT ...;
..."

# Call the API
echo "Calling LLM API to generate $NUM_QUERIES queries..." >&2
echo "  API: $API_BASE" >&2
echo "  Model: $MODEL" >&2
echo "  Scenario: $SCENARIO" >&2

RESPONSE=$(curl -s "${API_BASE}chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $API_KEY" \
    -d "$(jq -n \
        --arg model "$MODEL" \
        --arg prompt "$PROMPT" \
        '{
            model: $model,
            messages: [
                {role: "system", content: "You are an expert PostgreSQL developer. Generate only SQL queries, no explanations."},
                {role: "user", content: $prompt}
            ],
            temperature: 0.7,
            max_tokens: 2000
        }'
    )" 2>&1)

# Check for errors
if echo "$RESPONSE" | jq -e '.error' > /dev/null 2>&1; then
    echo "ERROR: API returned error:" >&2
    echo "$RESPONSE" | jq -r '.error.message // .error' >&2
    exit 1
fi

# Extract queries from response
CONTENT=$(echo "$RESPONSE" | jq -r '.choices[0].message.content // empty')

if [ -z "$CONTENT" ]; then
    echo "ERROR: No content in API response" >&2
    echo "Response: $RESPONSE" >&2
    exit 1
fi

# Parse and clean queries
echo "Parsing generated queries..." >&2
QUERIES=$(echo "$CONTENT" | grep -iE "^SELECT" | head -n "$NUM_QUERIES")

# Count queries
QUERY_COUNT=$(echo "$QUERIES" | grep -c "SELECT" || echo "0")
echo "Generated $QUERY_COUNT queries" >&2

# Output queries
if [ "$QUERY_COUNT" -gt 0 ]; then
    echo "$QUERIES"
else
    echo "WARNING: No valid queries extracted, using fallback" >&2
    # Fallback queries
    cat << 'EOF'
SELECT current_database(), current_user, version();
SELECT COUNT(*) as total_employees FROM employee;
SELECT d.dept_name, COUNT(*) as emp_count FROM department d JOIN department_employee de ON d.id = de.department_id GROUP BY d.dept_name ORDER BY emp_count DESC;
SELECT e.first_name, e.last_name, t.title FROM employee e JOIN title t ON e.id = t.employee_id WHERE t.to_date = '9999-01-01' LIMIT 10;
SELECT AVG(s.amount)::numeric(10,2) as avg_salary FROM salary s WHERE s.to_date = '9999-01-01';
EOF
fi
