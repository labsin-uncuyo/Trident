#!/bin/bash
# PostgreSQL Health Monitor
# Monitors PostgreSQL connectivity from compromised container to server
# Runs every 30 seconds, checking if postgres is reachable
# This appears to be a standard database connection monitoring tool

set -e

MONITORING_FILE="${1:-/var/lib/system_health/pg_health.json}"
CHECK_INTERVAL=30

# PostgreSQL connection details (same as benign agent uses)
PG_HOST="172.31.0.10"
PG_PORT="5432"
PG_USER="labuser"
PG_DB="labdb"
PG_PASSWORD="labpass"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS:${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
}

# Create monitoring directory
mkdir -p "$(dirname "$MONITORING_FILE")"

# Initialize monitoring file
cat > "$MONITORING_FILE" << EOF
{
  "monitoring_start": "$(date -u +"%Y-%m-%dT%H:%M:%S%:z")",
  "target": "postgresql_connectivity",
  "pg_host": "$PG_HOST",
  "pg_port": "$PG_PORT",
  "pg_database": "$PG_DB",
  "source": "lab_compromised",
  "checks": []
}
EOF

log "PostgreSQL health monitoring started"
log "Target: ${PG_HOST}:${PG_PORT}/${PG_DB}"
log "Metrics file: $MONITORING_FILE"
log "Check interval: ${CHECK_INTERVAL}s"

# Helper function to test PostgreSQL connectivity (same method as benign agent)
test_pg_connection() {
    local output
    local rc

    # First, check if port is reachable using nc (quick check)
    if ! nc -z -w 2 "$PG_HOST" "$PG_PORT" 2>/dev/null; then
        echo "unreachable"
        return 1
    fi

    # Then try a simple query to verify database is working (same as benign agent)
    output=$(PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -t -A -c "SELECT 1;" 2>&1)
    rc=$?

    if [ $rc -eq 0 ] && [ "$output" = "1" ]; then
        echo "reachable"
        return 0
    else
        echo "not_queryable"
        return 1
    fi
}

# Monitor indefinitely (will be killed when experiment ends)
check_count=0
while true; do
    check_count=$((check_count + 1))
    check_time=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")
    check_epoch=$(date +%s)

    log "PostgreSQL health check #$check_count at $check_time"

    # Test PostgreSQL connectivity
    pg_status=$(test_pg_connection)
    pg_status_code=$?

    # Determine status and message
    case "$pg_status" in
        reachable)
            status="healthy"
            status_msg="PostgreSQL connection successful"
            log_success "PostgreSQL is reachable"
            ;;
        not_queryable)
            status="degraded"
            status_msg="PostgreSQL server reachable but query failed"
            log_warning "PostgreSQL reachable but query failed"
            ;;
        unreachable)
            status="unhealthy"
            status_msg="PostgreSQL connection failed"
            log_error "PostgreSQL is unreachable"
            ;;
        *)
            status="unknown"
            status_msg="Unknown status"
            log_warning "Unknown PostgreSQL status"
            ;;
    esac

    # Add check entry to JSON
    tmp_file=$(mktemp)
    jq --arg check_time "$check_time" \
       --argjson check_epoch "$check_epoch" \
       --arg check_number "$check_count" \
       --arg status "$status" \
       --arg status_msg "$status_msg" \
       --arg pg_host "$PG_HOST" \
       --argjson pg_port "$PG_PORT" \
       '.checks += [{
         "check_number": ($check_number | tonumber),
         "timestamp": $check_time,
         "epoch": ($check_epoch | tonumber),
         "status": $status,
         "message": $status_msg,
         "target": {
           "host": $pg_host,
           "port": ($pg_port | tonumber)
         }
       }]' "$MONITORING_FILE" > "$tmp_file" && mv "$tmp_file" "$MONITORING_FILE"

    sleep "$CHECK_INTERVAL"
done
