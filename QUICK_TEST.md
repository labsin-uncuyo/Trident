# Quick Test Commands

## Current Setup
- Infrastructure: ✅ Running (lab_router, lab_server, lab_compromised)
- RUN_ID: `logs_20251215_222402`
- API Key: Configured in `/home/shared/Trident/.env`

## Test the LLM Workflow

### Option 1: Quick Test (3 queries, developer scenario)
```bash
make ghosts_psql_llm NUM_QUERIES=3 SCENARIO=developer_routine DELAY=2
```

### Option 2: Full Test (5 queries, HR audit scenario)
```bash
make ghosts_psql_llm NUM_QUERIES=5 SCENARIO=hr_audit ROLE=senior_developer_role DELAY=3
```

### Option 3: Exploratory Test (8 queries)
```bash
make ghosts_psql_llm NUM_QUERIES=8 SCENARIO=exploratory DELAY=2
```

## Verify Logs After Test

```bash
# Set RUN_ID variable for convenience
RUN_ID=$(cat ./outputs/.current_run)

# 1. Check all log files exist
ls -lh ./outputs/$RUN_ID/ghosts/

# 2. View the generated timeline (LLM created this)
cat ./outputs/$RUN_ID/ghosts/timeline_generated.json | jq '.TimeLineHandlers[0].TimeLineEvents | length'

# 3. View GHOSTS framework log (shows execution)
tail -50 ./outputs/$RUN_ID/ghosts/app.log

# 4. View detailed command log
tail -100 ./outputs/$RUN_ID/ghosts/clientupdates.log

# 5. Count how many SQL queries were executed
grep "SELECT" ./outputs/$RUN_ID/ghosts/app.log | wc -l

# 6. See actual queries that ran
grep "SELECT" ./outputs/$RUN_ID/ghosts/app.log | head -10

# 7. Check timeline events (should match NUM_QUERIES + 2 for intro/outro messages)
grep "TIMELINE|" ./outputs/$RUN_ID/ghosts/clientupdates.log | wc -l
```

## Compare Hardcoded vs LLM

```bash
# Test hardcoded version
make ghosts_psql REPEATS=1 DELAY=2

# Then check logs
RUN_ID=$(cat ./outputs/.current_run)
echo "Logs saved to: ./outputs/$RUN_ID/ghosts/"
ls -lh ./outputs/$RUN_ID/ghosts/
```

## Watch Execution in Real-Time

```bash
# Terminal 1: Follow container logs
docker logs -f lab_ghosts_driver

# Terminal 2: Monitor log files
watch -n 3 "ls -lh ./outputs/\$(cat ./outputs/.current_run)/ghosts/"
```

## Expected Results

### Log Files Created:
- ✅ `app.log` - GHOSTS framework logs (~5-30 KB)
- ✅ `clientupdates.log` - Detailed command execution (~10-200 KB)
- ✅ `timeline_generated.json` - LLM-generated timeline (LLM mode only)

### Log Content Verification:
```bash
RUN_ID=$(cat ./outputs/.current_run)

# Should see GHOSTS startup
head -20 ./outputs/$RUN_ID/ghosts/app.log

# Should see SQL queries being executed
grep "psql" ./outputs/$RUN_ID/ghosts/app.log | head -5

# Should see timeline events (one per query + intro/outro)
grep -c "TIMELINE|" ./outputs/$RUN_ID/ghosts/clientupdates.log
```

## Troubleshooting Quick Checks

### If no logs appear:
```bash
# Check container ran
docker ps -a --filter "name=lab_ghosts_driver"

# Check container logs
docker logs lab_ghosts_driver | tail -30

# Verify RUN_ID exists
cat ./outputs/.current_run
```

### If LLM fails:
```bash
# Check OpenCode (may not be installed, will use fallback)
docker exec lab_ghosts_driver which opencode || echo "OpenCode not found - using fallback queries"

# Check API key
grep OPENCODE_API_KEY /home/shared/Trident/.env
```

### If queries don't execute:
```bash
# Test SSH connection
docker exec lab_ghosts_driver ssh -o StrictHostKeyChecking=no -i /root/.ssh/id_rsa labuser@172.30.0.10 "echo 'SSH works'"

# Test database connection
docker exec lab_compromised bash -c 'PGPASSWORD="john_scott" psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb -c "SELECT 1;"'
```

## Success Indicators

✅ **Makefile output shows:**
- "✓ Container started: lab_ghosts_driver"
- "✓ Container stopped"
- "✓ Logs copied to ./outputs/logs_YYYYMMDD_HHMMSS/ghosts/"
- "✓ Generated timeline copied to ..." (LLM mode only)
- "📊 Statistics: Timeline events logged: X"

✅ **Log directory contains:**
- 2-3 files (3 for LLM mode with timeline_generated.json)
- File sizes > 0 bytes
- Readable JSON in timeline_generated.json (if LLM mode)

✅ **Logs contain:**
- "Ghosts.Client.Universal startup" in app.log
- "SSH" and "psql" commands in app.log
- Multiple "TIMELINE|" entries in clientupdates.log
- SQL queries (SELECT statements) in logs
