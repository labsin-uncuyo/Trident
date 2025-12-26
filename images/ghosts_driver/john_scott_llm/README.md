# GHOSTS John Scott - LLM-Driven Version

LLM-powered behavior simulation for John Scott (Senior Developer) using the GHOSTS framework to generate realistic database queries dynamically.

## Overview

This implementation uses an LLM (via OpenCode) to generate realistic SQL queries that John Scott would execute as part of his daily work. Instead of using hardcoded timelines, the queries are generated on-demand based on different scenarios, making the simulation more dynamic and realistic.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Makefile (ghosts_psql_llm target)                          │
│  - Accepts: NUM_QUERIES, SCENARIO, DELAY, API_KEY           │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  generate_timeline.sh                                        │
│  - Calls generate_timeline_llm.py                            │
│  - Copies generated timeline to GHOSTS config                │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  generate_timeline_llm.py                                    │
│  - Uses llm_query_generator.py to get SQL queries           │
│  - Wraps queries in SSH commands                             │
│  - Generates GHOSTS timeline.json                            │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  llm_query_generator.py                                      │
│  - Calls OpenCode LLM with database schema context           │
│  - Parses and validates SQL queries                          │
│  - Fallback to reasonable defaults if LLM unavailable        │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  GHOSTS Driver Container                                     │
│  - Reads generated timeline                                  │
│  - Executes SSH commands to compromised machine              │
│  - Compromised machine runs psql commands                    │
└─────────────────────────────────────────────────────────────┘
```

## Files

- **`llm_query_generator.py`**: Core LLM integration, generates SQL queries based on scenario
- **`generate_timeline_llm.py`**: Converts SQL queries into GHOSTS timeline format
- **`generate_timeline.sh`**: Wrapper script that orchestrates timeline generation
- **`test_john_scott_llm.sh`**: Test script for local development
- **`requirements.txt`**: Python dependencies

## Usage

### Prerequisites

1. Ensure `OPENCODE_API_KEY` is set in `/home/shared/Trident/.env` file:
   ```bash
   OPENCODE_API_KEY=sk-your-api-key-here
   ```
   The API key is **automatically** loaded from `.env` - you never need to pass it as a parameter.

2. Initialize the infrastructure:
   ```bash
   make up
   ```

### From Makefile (Recommended)

```bash
# Generate 10 queries with developer_routine scenario using default role
make ghosts_psql_llm NUM_QUERIES=10 SCENARIO=developer_routine

# Generate 5 queries with hr_audit scenario, custom role, and delay
make ghosts_psql_llm NUM_QUERIES=5 SCENARIO=hr_audit ROLE=senior_developer_role DELAY=3

# Exploratory scenario with 8 queries
make ghosts_psql_llm NUM_QUERIES=8 SCENARIO=exploratory ROLE=senior_developer_role
```

### Parameters

- **`NUM_QUERIES`** (default: 5): Number of SQL queries to generate via LLM
- **`SCENARIO`** (default: `developer_routine`): Type of work scenario
  - `developer_routine`: Daily dev tasks (team checks, salaries, hires)
  - `hr_audit`: HR-focused queries (headcounts, ranges, tenure)
  - `performance_review`: Review preparation (reports, progression, comparisons)
  - `exploratory`: Random analytical queries (statistics, joins, edge cases)
- **`ROLE`** (default: `senior_developer_role`): Database role name from `/home/shared/Trident/images/server/roles_users.sql`
  - Determines user permissions and access patterns
  - LLM generates queries appropriate for the role's privileges
  - Currently supported: `senior_developer_role` (john_scott user)
- **`DELAY`** (default: 5): Base delay in seconds between commands (varies slightly for realism)

**Note:** Unlike the hardcoded version, `REPEATS` is not a parameter since the LLM generates unique queries each time.

### Direct Script Usage

```bash
# Generate queries only with specific role
python3 llm_query_generator.py --num-queries 10 --scenario hr_audit --role senior_developer_role

# Generate complete timeline with role
python3 generate_timeline_llm.py --num-queries 8 --scenario developer_routine \
    --role senior_developer_role --delay-before 5000 --delay-after 10000 --output timeline.json

# Generate timeline with looping enabled
python3 generate_timeline_llm.py --num-queries 5 --scenario exploratory \
    --role senior_developer_role --loop
```

## Database Roles and Permissions

The LLM generates queries based on the specified database role, which determines:
- Available tables and columns
- Permission levels (SELECT, INSERT, UPDATE, DELETE, DDL)
- Typical work patterns and access needs

### Available Roles

#### `senior_developer_role` (john_scott user)
- **Credentials**: `john_scott` / `john_scott`
- **Connection**: Two-step process
  1. SSH to labuser@172.30.0.10
  2. `psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb`
  
- **Permissions**:
  - DML: SELECT, INSERT, UPDATE, DELETE on all tables
  - DDL: CREATE on schema public
  - Full access to: employee, department, department_employee, department_manager, salary, title, events
  
- **Typical Activities**:
  - Query employee records and department data
  - Analyze salary ranges for budget planning
  - Review team composition and hiring patterns
  - Create test data or temporary tables
  - Run analytics queries and reports
  - Monitor system events and logs

### Role-Based Query Generation

The LLM considers the role's permissions when generating queries:
- **READ-only roles**: Only SELECT statements
- **Developer roles**: SELECT + occasional INSERT/UPDATE for testing
- **Admin roles**: Full DDL/DML including CREATE, DROP, ALTER

This ensures realistic behavior - a developer won't try to execute queries they don't have permission for.

## Scenarios

### developer_routine
John Scott performs typical development work:
- Checking team members in Development department
- Reviewing recent hires and backgrounds
- Planning budgets with salary information
- Tracking title progressions and promotions
- Analyzing department statistics

### hr_audit
John Scott conducts HR audit activities:
- Employee counts by department
- Salary ranges and averages
- Identifying long-tenured employees
- Reviewing organizational changes
- Checking manager assignments

### performance_review
John Scott prepares for performance reviews:
- Listing direct reports and titles
- Analyzing salary history and adjustments
- Calculating time in current positions
- Making cross-department comparisons
- Identifying career progression patterns

### exploratory
John Scott explores the database:
- Running random analytical queries
- Performing data quality checks
- Computing statistical aggregations
- Testing complex joins and subqueries
- Investigating edge cases

## How It Works

1. **Role Context Loading**: System reads the database role from `roles_users.sql` to understand permissions and access patterns
2. **LLM Query Generation**: `llm_query_generator.py` sends the database schema, role permissions, and scenario context to OpenCode LLM
3. **Query Validation**: Generated queries are validated for syntax and role-appropriate permissions
4. **Timeline Creation**: `generate_timeline_llm.py` wraps each SQL query in proper SSH and psql command syntax
5. **Two-Step Connection**: Each command follows the security pattern:
   - Step 1: SSH from ghosts_driver (172.30.0.20) to compromised (172.30.0.10)
   - Step 2: From compromised, connect to PostgreSQL on server (172.31.0.10:5432)
6. **GHOSTS Execution**: The timeline is loaded by GHOSTS framework, which executes each command with specified delays

## Example Generated Timeline

```json
{
  "Status": "Run",
  "TimeLineHandlers": [{
    "HandlerType": "Bash",
    "Loop": false,
    "TimeLineEvents": [
      {
        "Command": "ssh ... labuser@172.30.0.10 'PGPASSWORD=\"john_scott\" psql -h 172.31.0.10 -U john_scott -d labdb -c \"SELECT ...\"'",
        "DelayBefore": 5000,
        "DelayAfter": 10000
      },
      ...
    ]
  }]
}
```

## Requirements

- OpenCode CLI installed in ghosts_driver container
- Access to e-INFRA CZ Chat API (or compatible OpenAI API)
- **`OPENCODE_API_KEY`** configured in `/home/shared/Trident/.env` file (automatically loaded)
- Python 3.8+
- SSH access from ghosts_driver to compromised machine
- PostgreSQL database credentials for john_scott user

## Environment Variables

All configuration is loaded from `/home/shared/Trident/.env`:

```bash
# Required
OPENCODE_API_KEY=sk-your-api-key-here

# Optional (with defaults shown)
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api/
LLM_MODEL=qwen3-coder
```

## Troubleshooting

**LLM queries not generating:**
- Check if OpenCode is installed: `opencode --version`
- Verify API key is set: `echo $OPENCODE_API_KEY`
- Check network connectivity to API endpoint
- Review fallback queries are being used

**SSH connection failures:**
- Ensure SSH keys are properly set up (see `setup_ssh_keys_host.sh`)
- Verify compromised container is running
- Check network connectivity between containers

**PostgreSQL connection issues:**
- Verify server container is running
- Check john_scott user credentials
- Ensure database is initialized

## Differences from Hardcoded Version

| Aspect | Hardcoded (`john_scott_dummy`) | LLM-Driven (`john_scott_llm`) |
|--------|-------------------------------|------------------------------|
| Queries | Fixed 6 queries | Dynamic, LLM-generated |
| Parameters | REPEATS, DELAY | NUM_QUERIES, SCENARIO, DELAY |
| Variety | Same queries each run | Different queries each run |
| Realism | Predetermined patterns | Contextually appropriate |
| Flexibility | Limited scenarios | Multiple scenario types |
| Fallback | N/A | Graceful degradation |

## Future Enhancements

- [ ] Add conversation memory for multi-session continuity
- [ ] Implement time-of-day aware scenario selection
- [ ] Add anomaly injection (e.g., suspicious queries)
- [ ] Support for multiple personas with different access levels
- [ ] Integration with SLIPS for correlation analysis
- [ ] Real-time query adaptation based on previous results
