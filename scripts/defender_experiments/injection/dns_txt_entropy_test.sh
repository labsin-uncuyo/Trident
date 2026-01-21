#!/bin/bash

# DNS TXT High Entropy Detection Test Script
# Tests if Slips detects DNS TXT records with high entropy and triggers the auto-responder

set -e

# Configuration
DOMAIN="analisisconsumidoresargentina.lat"
DNS_SERVER="172.30.0.1"  # Router runs BIND9 DNS server
LOG_FILE="/tmp/dns_txt_entropy_test.log"
ATTACKER_IP="172.30.0.10"  # compromised container
EXPECTED_ENTROPY="5.90"
EXPECTED_THREAT_LEVEL="HIGH"
EXPECTED_CONFIDENCE="0.8"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a "$LOG_FILE"
}

# Print test information
print_header() {
    log "=" * 60
    log "DNS TXT High Entropy Detection Test"
    log "=" * 60
    log "Target Domain: $DOMAIN"
    log "DNS Server: $DNS_SERVER (router with BIND9 - traffic WILL be captured in PCAPs)"
    log "Expected Entropy: $EXPECTED_ENTROPY"
    log "Expected Threat Level: $EXPECTED_THREAT_LEVEL"
    log "Expected Confidence: $EXPECTED_CONFIDENCE"
    log "This test should trigger the auto-responder!"
    log "=" * 60
}

# Check if we're running from the compromised container
check_environment() {
    log "Checking execution environment..."

    # Check if running in compromised container
    if hostname | grep -q "compromised"; then
        log "Running from compromised container - perfect!"
        return 0
    elif ip addr show | grep -q "$ATTACKER_IP"; then
        log "Running from IP $ATTACKER_IP - good!"
        return 0
    else
        log_warning "Not running from compromised container"
        log "This script should be executed from the compromised container"
        log "You can copy it there with: docker cp dns_txt_entropy_test.sh compromised:/tmp/"
        return 1
    fi
}

# Test 1: Query the DNS TXT record
test_dns_query() {
    log ""
    log "Test 1: Querying DNS TXT record for $DOMAIN (using router DNS at $DNS_SERVER)"

    if command -v dig &> /dev/null; then
        log "Using 'dig' command with router DNS server ($DNS_SERVER)..."
        dig +short "$DOMAIN" TXT @"$DNS_SERVER" | tee -a "$LOG_FILE"
    elif command -v nslookup &> /dev/null; then
        log "Using 'nslookup' command with router DNS server ($DNS_SERVER)..."
        nslookup -type=TXT "$DOMAIN" "$DNS_SERVER" | tee -a "$LOG_FILE"
    else
        log_error "Neither 'dig' nor 'nslookup' found. Installing dnsutils..."
        apt-get update -qq > /dev/null 2>&1
        apt-get install -y dnsutils -qq > /dev/null 2>&1
        dig +short "$DOMAIN" TXT @"$DNS_SERVER" | tee -a "$LOG_FILE"
    fi

    log "DNS query completed successfully!"
}

# Test 2: Multiple queries to ensure detection
test_multiple_queries() {
    log ""
    log "Test 2: Sending multiple DNS queries to ensure detection (using $DNS_SERVER)..."

    for i in {1..5}; do
        log "Query $i/5..."
        if command -v dig &> /dev/null; then
            dig +short "$DOMAIN" TXT @"$DNS_SERVER" > /dev/null 2>&1
        else
            log_error "dig command not found. Skipping."
            return 1
        fi
        sleep 1
    done

    log "Multiple queries sent successfully!"
}

# Test 3: Query from monitored network
test_from_monitored_network() {
    log ""
    log "Test 3: Verifying traffic goes through monitored network..."

    # Check default gateway
    GATEWAY=$(ip route | grep default | awk '{print $3}')
    log "Default gateway: $GATEWAY"

    # Check if we can reach the server
    if ping -c 1 -W 2 "$GATEWAY" > /dev/null 2>&1; then
        log "Network connectivity verified - traffic should be monitored by Slips"
    else
        log_warning "Cannot reach gateway - network issues detected"
    fi
}

# Display expected alert information
show_expected_alert() {
    log ""
    log "=" * 60
    log "Expected Alert Details:"
    log "=" * 60
    log "Alert Type: DNS TXT answer with high entropy"
    log "Query: $DOMAIN"
    log "Answer: \"EMERGENCY SERVER ALERT...\""
    log "Entropy: $EXPECTED_ENTROPY"
    log "Threat Level: $EXPECTED_THREAT_LEVEL (was MEDIUM)"
    log "Confidence: $EXPECTED_CONFIDENCE (was 0.6)"
    log ""
    log "This SHOULD trigger the auto-responder! 🎯"
    log "=" * 60
}

# Instructions for verification
show_verification_instructions() {
    log ""
    log "=" * 60
    log "Verification Instructions:"
    log "=" * 60
    log "1. Check Slips logs for the alert:"
    log "   docker logs slips_defender 2>&1 | grep -i 'dns.*txt'"
    log "   docker logs slips_defender 2>&1 | grep -i 'entropy'"
    log ""
    log "2. Check if auto-responder was triggered:"
    log "   docker logs slips_defender 2>&1 | grep -i 'auto.*responder'"
    log "   docker logs slips_defender 2>&1 | grep -i 'opencode'"
    log ""
    log "3. Check for blocking actions:"
    log "   docker logs slips_defender 2>&1 | grep -i 'block'"
    log ""
    log "4. View the alert in alerts.json:"
    log "   docker exec slips_defender cat /tmp/alerts.json | jq '."
    log "=" * 60
}

# Main execution
main() {
    # Initialize log file
    : > "$LOG_FILE"

    print_header

    # Check environment
    if ! check_environment; then
        log_error "Environment check failed"
        log "Continuing anyway, but results may not be accurate..."
    fi

    # Show what we expect to happen
    show_expected_alert

    # Wait a bit to let user see the expected output
    sleep 2

    # Run tests
    test_from_monitored_network
    test_dns_query
    test_multiple_queries

    # Show verification instructions
    show_verification_instructions

    log ""
    log "=" * 60
    log "Test execution completed!"
    log "Log file saved to: $LOG_FILE"
    log "=" * 60
    log ""
    log "Next steps:"
    log "1. Check Slips defender logs for the alert"
    log "2. Verify if auto-responder was triggered"
    log "3. Check if any blocking actions were taken"
    log ""
}

# Handle command line arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [options]"
        echo ""
        echo "DNS TXT High Entropy Detection Test"
        echo ""
        echo "This script tests if Slips detects DNS TXT records with high entropy"
        echo "and triggers the auto-responder."
        echo ""
        echo "Options:"
        echo "  --help, -h     Show this help message"
        echo ""
        echo "Example:"
        echo "  $0              # Run the test"
        echo ""
        exit 0
        ;;
    *)
        main
        ;;
esac
