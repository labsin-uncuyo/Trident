#!/bin/bash

# Host-side SSH Key Setup Script for Auto Responder
# Mirrors the in-container setup when you prefer to run it from the host.

set -euo pipefail

SERVER_IP="${SERVER_IP:-172.31.0.10}"
COMPROMISED_IP="${COMPROMISED_IP:-172.30.0.10}"
SSH_PORT="${SSH_PORT:-22}"
LAB_PASSWORD="${LAB_PASSWORD:-}"
SERVER_ROOT_PASSWORD="${SERVER_ROOT_PASSWORD:-admin123}"

log() {
    echo "[$(date -Is)] $*"
}

wait_for_container() {
    local name=$1
    local attempts=0
    local max_attempts=30
    while [ ${attempts} -lt ${max_attempts} ]; do
        if docker exec "${name}" true >/dev/null 2>&1; then
            log "${name} is reachable"
            return 0
        fi
        attempts=$((attempts + 1))
        log "Waiting for ${name} (${attempts}/${max_attempts})..."
        sleep 2
    done
    log "Timeout waiting for ${name}"
    return 1
}

add_key_to_container() {
    local container=$1
    local pub_key=$2
    docker exec "${container}" bash -c "\
        mkdir -p /root/.ssh && chmod 700 /root/.ssh && \
        touch /root/.ssh/authorized_keys && \
        grep -qxF '${pub_key}' /root/.ssh/authorized_keys || echo '${pub_key}' >> /root/.ssh/authorized_keys && \
        chmod 600 /root/.ssh/authorized_keys"
}

main() {
    log "Setting up SSH key access for auto_responder from host"

    # Fetch the pub key from the persistent volume
    pub_key=$(docker run --rm -v lab_auto_responder_ssh_keys:/data alpine sh -c 'cat /data/id_rsa_auto_responder.pub 2>/dev/null' || true)
    if [ -z "${pub_key}" ]; then
        log "Could not read id_rsa_auto_responder.pub from auto_responder_ssh_keys volume"
        exit 1
    fi
    log "Public key loaded from volume"

    wait_for_container lab_server || true
    wait_for_container lab_compromised || true

    add_key_to_container lab_server "${pub_key}" || log "Failed to add key to lab_server"
    add_key_to_container lab_compromised "${pub_key}" || log "Failed to add key to lab_compromised"

    log "Host-side SSH key setup complete"
}

main "$@"
