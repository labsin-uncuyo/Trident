#!/usr/bin/env bash
set -euo pipefail

# Quick connectivity test to the compromised host from the host machine.
SSH_HOST=${SSH_HOST:-127.0.0.1}
SSH_PORT=${SSH_PORT:-2223}
SSH_USER=${SSH_USER:-labuser}
SSH_PASSWORD=${SSH_PASSWORD:-adminadmin}

echo "[test_aracne_ssh] Testing SSH to ${SSH_USER}@${SSH_HOST}:${SSH_PORT}"
sshpass -p "$SSH_PASSWORD" ssh \
  -o BatchMode=yes \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=3 \
  -p "$SSH_PORT" \
  "${SSH_USER}@${SSH_HOST}" \
  "echo '[test_aracne_ssh] SSH OK'" && exit 0

echo "[test_aracne_ssh] SSH failed"
exit 1
