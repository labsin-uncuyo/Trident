#!/bin/bash
# Network Connectivity Check Script
# Performs periodic DNS resolution checks to verify network connectivity
# This is a standard system administration task

set -e

EXPERIMENT_ID="${1:-dns_injection_$(date +%Y%m%d_%H%M%S)}"
OUTPUT_DIR="/var/lib/network_metrics"
MONITORING_FILE="$OUTPUT_DIR/connectivity_status.json"
TARGET_DOMAIN="analisisconsumidoresargentina.lat"
# Use explicit external resolver so DNS traffic traverses lab_router and is captured in PCAPs.
DNS_RESOLVER="${DNS_RESOLVER:-8.8.8.8}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging functions
log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS:${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
}

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Initialize monitoring JSON using Python (no jq dependency)
python3 << EOF
import json
from datetime import datetime

data = {
    "experiment_id": "$EXPERIMENT_ID",
    "attack_type": "dns_injection",
    "target_domain": "$TARGET_DOMAIN",
    "dns_resolver": "$DNS_RESOLVER",
    "start_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    "num_resolutions": 5,
    "checks": [],
    "final_status": "running"
}

with open("$MONITORING_FILE", "w") as f:
    json.dump(data, f, indent=2)
EOF

log "Starting DNS Injection Attack: $EXPERIMENT_ID"
log "Target domain: $TARGET_DOMAIN (TXT records)"
log "DNS resolver: $DNS_RESOLVER"
log "Number of resolutions: 5"

# Perform 5 DNS TXT resolution checks
for i in {1..5}; do
    log "DNS resolution $i/5..."

    # Perform DNS TXT lookup using nslookup (TXT records have high entropy for detection)
    check_start=$(date +%s.%N)
    dns_result=$(nslookup -type=TXT "$TARGET_DOMAIN" "$DNS_RESOLVER" 2>&1 || true)
    check_end=$(date +%s.%N)
    # Use python3 for floating point arithmetic
    check_duration=$(python3 -c "print($check_end - $check_start)")

    # Check if TXT record was found (look for "text =" in output)
    txt_found=$(echo "$dns_result" | grep -c "text =" || echo "0")

    if [[ $txt_found -gt 0 ]]; then
        log_success "DNS TXT resolution $i succeeded (${check_duration}s)"
        check_status="success"
    else
        log_error "DNS TXT resolution $i failed"
        check_status="failed"
    fi

    # Update monitoring JSON using Python (no jq dependency)
    python3 << EOF
import json
from datetime import datetime

with open("$MONITORING_FILE", "r") as f:
    data = json.load(f)

data["checks"].append({
    "check_number": $i,
    "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    "status": "$check_status",
    "response_time_seconds": float("$check_duration")
})

with open("$MONITORING_FILE", "w") as f:
    json.dump(data, f, indent=2)
EOF

    # Wait 2 seconds between resolutions
    if [[ $i -lt 5 ]]; then
        sleep 2
    fi
done

# Update final status using Python
python3 << EOF
import json
from datetime import datetime

with open("$MONITORING_FILE", "r") as f:
    data = json.load(f)

data["final_status"] = "completed"
data["end_time"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")

with open("$MONITORING_FILE", "w") as f:
    json.dump(data, f, indent=2)
EOF

log_success "DNS Injection Attack completed"
log "Results saved to: $MONITORING_FILE"

# Also save a summary using Python
python3 << EOF
import json
from datetime import datetime

with open("$MONITORING_FILE", "r") as f:
    data = json.load(f)

summary = {
    "experiment_id": data["experiment_id"],
    "attack_type": data["attack_type"],
    "target_domain": data["target_domain"],
    "total_resolutions": len(data["checks"]),
    "start_time": data["start_time"],
    "end_time": data.get("end_time", ""),
    "final_status": data["final_status"],
    "num_successful": len([c for c in data["checks"] if c["status"] == "success"])
}

with open("$OUTPUT_DIR/dns_attack_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
EOF

log "Summary saved to: $OUTPUT_DIR/dns_attack_summary.json"

exit 0
