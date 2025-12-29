#!/bin/bash
# Query generator using GHOSTS Shadows API instead of direct OpenAI calls
# This integrates with GHOSTS native LLM framework

set -e

# Parameters
NUM_QUERIES=${NUM_QUERIES:-5}
SCENARIO=${SCENARIO:-developer_routine}
ROLE=${ROLE:-senior_developer_role}

# Shadows API Configuration
SHADOWS_API_URL=${SHADOWS_API_URL:-http://ghosts-shadows:5900}
SHADOWS_ENDPOINT="${SHADOWS_API_URL}/activity"

# Validate Shadows API availability
echo "Checking Shadows API availability at $SHADOWS_API_URL..."
if ! curl -sf "${SHADOWS_API_URL}/health" > /dev/null 2>&1; then
    echo "WARNING: Shadows API not available at $SHADOWS_API_URL" >&2
    echo "Falling back to legacy LLM method..." >&2
    exec /opt/ghosts/john_scott_llm/generate_queries_john_scott.sh
    exit $?
fi

echo "✓ Shadows API is available"

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
- User john_scott has full SELECT access'

# Build persona-driven prompt for Shadows
QUERY_PROMPT="You are John Scott, a Senior Developer with 8 years experience. You're exploring the employee database during a typical work session.

CRITICAL BEHAVIORAL RULES - You MUST follow these:

1. INTENT PHASES (follow in order):
   - Warm-up (queries 1-2): Basic checks, current_user, simple counts
   - Exploration (next 30%): Department joins, aggregations
   - Focus (middle 40%): Salary analysis, title searches, specific lookups
   - Validation (next 20%): Repeat or refine earlier queries
   - Wrap-up (last 10%): Summary query or final count

2. IMPERFECTION - You are NOT perfect:
   - 15% of queries should have minor errors (wrong column name, missing alias, impossible WHERE)
   - Follow errors with corrected versions later
   - Use inconsistent formatting (mixed case, uneven spacing)
   - Occasionally redundant logic

3. REPETITION & MUTATION:
   - 20% of queries should repeat or slightly modify previous ones
   - Mutations: change LIMIT, swap ORDER BY, add/remove WHERE clause
   - Some queries should be nearly identical

4. HUMAN BEHAVIOR:
   - Start simple, get more complex, then simplify again
   - Mix SELECT styles (explicit columns vs *)
   - Vary query sophistication
   - Don't always use perfect JOINs

Database Schema:
$SCHEMA_CONTEXT

Generate EXACTLY $NUM_QUERIES SQL queries following the rules above.

Requirements:
- One query per line
- Each must end with semicolon
- Follow intent phases
- Include mistakes and corrections
- Repeat/mutate some queries
- Use realistic imperfect SQL
- Valid PostgreSQL syntax (except intentional errors)

Output format (one per line):
SELECT ...;
SELECT ...;
..."

# Call Shadows API for activity generation
RESPONSE=$(curl -s -X POST "${SHADOWS_ENDPOINT}" \
    -H "Content-Type: application/json" \
    -d "$(jq -n \
        --arg query "$QUERY_PROMPT" \
        '{query: $query}'
    )" 2>&1)

# Check for errors
if [ -z "$RESPONSE" ]; then
    echo "ERROR: No response from Shadows API" >&2
    exit 1
fi

# Check if response is JSON error
if echo "$RESPONSE" | jq -e '.error' > /dev/null 2>&1; then
    echo "ERROR: Shadows API returned error:" >&2
    echo "$RESPONSE" | jq -r '.error' >&2
    exit 1
fi

# Extract content from JSON response
CONTENT=$(echo "$RESPONSE" | jq -r '. // empty' 2>/dev/null)

if [ -z "$CONTENT" ]; then
    echo "ERROR: No content in Shadows API response" >&2
    exit 1
fi

# Parse and clean queries
QUERIES=$(echo "$CONTENT" | grep -iE "^SELECT" | head -n "$NUM_QUERIES")

# Count queries
QUERY_COUNT=$(echo "$QUERIES" | grep -c "SELECT" || echo "0")

# Output queries
if [ "$QUERY_COUNT" -gt 0 ]; then
    echo "$QUERIES"
else
    # Fallback with human-like qualities
    cat << 'EOF'
SELECT current_database(), current_user, version();
SELECT COUNT(*) FROM employee;
SELECT COUNT(*) as total FROM employee;
SELECT d.dept_name, COUNT(*) FROM department d JOIN department_employee de ON d.id = de.department_id GROUP BY d.dept_name;
SELECT e.first_name, e.last_name, s.amount FROM employee e JOIN salary s ON e.id = s.employee_id WHERE s.to_date = '9999-01-01' ORDER BY s.amount DESC LIMIT 20;
EOF
fi
