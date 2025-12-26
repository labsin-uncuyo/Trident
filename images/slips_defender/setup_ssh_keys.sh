#!/bin/bash

# SSH Key Setup Script for Auto Responder
# - Ensures persistent keypair under /root/.ssh (backed by Docker volume)
# - Waits for lab_server and lab_compromised to accept SSH
# - Injects the public key into each container's authorized_keys (idempotent)

set -euo pipefail

SERVER_IP="${SERVER_IP:-172.31.0.10}"
COMPROMISED_IP="${COMPROMISED_IP:-172.30.0.10}"
SSH_KEY_PATH="${SSH_KEY_PATH:-/root/.ssh/id_rsa_auto_responder}"
SSH_PORT="${SSH_PORT:-22}"
SERVER_ROOT_PASSWORD="${SERVER_ROOT_PASSWORD:-admin123}"
COMPROMISED_USER="${COMPROMISED_USER:-labuser}"
COMPROMISED_PASSWORD="${COMPROMISED_PASSWORD:-${LAB_PASSWORD:-}}"
MAX_ATTEMPTS=40
SLEEP_SECONDS=3

log() {
    echo "[$(date -Is)] $*"
}

ensure_ssh_key() {
    if [ ! -f "${SSH_KEY_PATH}" ]; then
        log "🔐 Generating SSH key at ${SSH_KEY_PATH} (ed25519)"
        ssh-keygen -t ed25519 -f "${SSH_KEY_PATH}" -N "" -C "auto_responder@slips" >/dev/null
    fi
    chmod 700 "$(dirname "${SSH_KEY_PATH}")"
    chmod 600 "${SSH_KEY_PATH}"
    if [ -f "${SSH_KEY_PATH}.pub" ]; then
        chmod 644 "${SSH_KEY_PATH}.pub"
    fi
}

wait_for_ssh() {
    local ip=$1
    local name=$2
    local attempt=1

    log "⏳ Waiting for SSH on ${name} (${ip}:${SSH_PORT})..."
    while [ ${attempt} -le ${MAX_ATTEMPTS} ]; do
        if nc -z "${ip}" "${SSH_PORT}" >/dev/null 2>&1; then
            log "✅ SSH port open on ${name}"
            return 0
        fi
        log "⏳ Attempt ${attempt}/${MAX_ATTEMPTS}..."
        attempt=$((attempt + 1))
        sleep ${SLEEP_SECONDS}
    done

    log "❌ Timeout waiting for SSH on ${name}"
    return 1
}

add_key_via_password_ssh() {
    local user=$1
    local ip=$2
    local password=$3
    local target_label=$4

    if [ -z "${password}" ]; then
        log "❌ Missing password for ${target_label}; cannot inject key"
        return 1
    fi

    local pub_key
    pub_key=$(cat "${SSH_KEY_PATH}.pub" 2>/dev/null || true)
    if [ -z "${pub_key}" ]; then
        log "❌ Public key not found at ${SSH_KEY_PATH}.pub"
        return 1
    fi

    log "🔑 Installing public key on ${target_label} (${ip}) as ${user}"
    sshpass -p "${password}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -p "${SSH_PORT}" "${user}@${ip}" \
        "sudo mkdir -p /root/.ssh && sudo chmod 700 /root/.ssh && \
         sudo touch /root/.ssh/authorized_keys && \
         sudo grep -qxF '${pub_key}' /root/.ssh/authorized_keys || echo '${pub_key}' | sudo tee -a /root/.ssh/authorized_keys >/dev/null && \
         sudo chmod 600 /root/.ssh/authorized_keys"
}

add_key_to_admin_user() {
    local pub_key
    pub_key=$(cat "${SSH_KEY_PATH}.pub" 2>/dev/null || true)
    if [ -z "${pub_key}" ]; then
        log "❌ Public key not found at ${SSH_KEY_PATH}.pub"
        return 1
    fi

    log "🔑 Installing public key on server admin user (${SERVER_IP}) as admin"
    sshpass -p "${SERVER_ROOT_PASSWORD}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -p "${SSH_PORT}" "admin@${SERVER_IP}" \
        "mkdir -p /home/admin/.ssh && chmod 700 /home/admin/.ssh && \
         touch /home/admin/.ssh/authorized_keys && \
         grep -qxF '${pub_key}' /home/admin/.ssh/authorized_keys || echo '${pub_key}' >> /home/admin/.ssh/authorized_keys && \
         chmod 600 /home/admin/.ssh/authorized_keys"
}

test_key_login() {
    local ip=$1
    local label=$2
    if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 \
        -i "${SSH_KEY_PATH}" -p "${SSH_PORT}" root@"${ip}" "echo SSH_OK" >/dev/null 2>&1; then
        log "✅ SSH key login working for ${label} (${ip})"
        return 0
    else
        log "❌ SSH key login failed for ${label} (${ip})"
        return 1
    fi
}

main() {
    log "🔧 Setting up persistent SSH key access for auto_responder"
    ensure_ssh_key

    wait_for_ssh "${SERVER_IP}" "lab_server" || true
    wait_for_ssh "${COMPROMISED_IP}" "lab_compromised" || true

    add_key_via_password_ssh "root" "${SERVER_IP}" "${SERVER_ROOT_PASSWORD}" "lab_server" || true
    add_key_to_admin_user || true
    add_key_via_password_ssh "${COMPROMISED_USER}" "${COMPROMISED_IP}" "${COMPROMISED_PASSWORD}" "lab_compromised (sudo)" || true

    test_key_login "${SERVER_IP}" "lab_server" || true
    test_key_login "${COMPROMISED_IP}" "lab_compromised" || true

    log "🎉 SSH key setup completed (idempotent)"
}

main "$@"
