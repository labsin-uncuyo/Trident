#!/bin/bash
# System Health Monitoring Script
# Monitors system metrics and network events
# Standard system administration monitoring tool

set -e

MONITORING_FILE="${1:-/var/lib/system_health/metrics.json}"
CHECK_INTERVAL=5

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

# Initialize monitoring file
cat > "$MONITORING_FILE" << EOF
{
  "monitoring_start": "$(date -u +"%Y-%m-%dT%H:%M:%S%:z")",
  "target": "network_events",
  "events_detected": false,
  "first_event_time": null,
  "event_count": 0,
  "checks": []
}
EOF

log "System health monitoring started"
log "Monitoring target: network events"
log "Metrics file: $MONITORING_FILE"
log "Check interval: ${CHECK_INTERVAL}s"

# Monitor indefinitely (will be killed when experiment ends)
check_count=0
while true; do
    check_count=$((check_count + 1))
    check_time=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")

    log "Health check #$check_count at $check_time"

    # Check for network events in system logs
    # This monitors for various network-related events

    # Look for network events in common locations
    events_found=false

    # Check if system has generated any network-related events
    if [[ -d "/home/diego/Trident/outputs/.current_run" ]]; then
        current_run=$(cat /home/diego/Trident/outputs/.current_run 2>/dev/null || echo "")
        if [[ -n "$current_run" ]]; then
            system_output="/home/diego/Trident/outputs/$current_run/slips_output"

            if [[ -d "$system_output" ]]; then
                # Check for network events in system output
                network_events=$(grep -r "analisisconsumidoresargentina.lat" "$system_output" 2>/dev/null || true)
                if [[ -n "$network_events" ]]; then
                    events_found=true
                fi
            fi
        fi
    fi

    # Update monitoring state
    if [[ "$events_found" == "true" ]]; then
        if [[ "$(jq -r '.events_detected' "$MONITORING_FILE")" == "false" ]]; then
            log_success "Network events detected!"

            tmp_file=$(mktemp)
            jq --arg event_time "$check_time" \
               '.events_detected = true | .first_event_time = $event_time' \
               "$MONITORING_FILE" > "$tmp_file" && mv "$tmp_file" "$MONITORING_FILE"
        fi

        # Increment event count
        current_count=$(jq -r '.event_count' "$MONITORING_FILE")
        tmp_file=$(mktemp)
        jq --argjson count "$((current_count + 1))" \
           '.event_count = $count' \
           "$MONITORING_FILE" > "$tmp_file" && mv "$tmp_file" "$MONITORING_FILE"
    fi

    # Add check entry
    tmp_file=$(mktemp)
    jq --arg check_time "$check_time" \
       --arg events_found "$events_found" \
       '.checks += [{
         "check_number": '"$check_count"',
         "timestamp": $check_time,
         "events_detected": $events_found
       }]' "$MONITORING_FILE" > "$tmp_file" && mv "$tmp_file" "$MONITORING_FILE"

    sleep "$CHECK_INTERVAL"
done
