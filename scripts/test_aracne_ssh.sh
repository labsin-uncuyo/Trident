#!/usr/bin/env bash
set -euo pipefail

# Quick connectivity test to the compromised host from the host machine.
SSH_HOST=${SSH_HOST:-127.0.0.1}
SSH_PORT=${SSH_PORT:-2223}
SSH_USER=${SSH_USER:-labuser}
SSH_KEY_PATH=${SSH_KEY_PATH:-./images/ghosts_driver/john_scott_dummy/id_rsa}

if [ ! -f "$SSH_KEY_PATH" ]; then
  echo "[test_aracne_ssh] SSH key not found at $SSH_KEY_PATH"
  exit 1
fi

echo "[test_aracne_ssh] Testing SSH to ${SSH_USER}@${SSH_HOST}:${SSH_PORT}"
ssh -i "$SSH_KEY_PATH" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=3 \
  -p "$SSH_PORT" \
  "${SSH_USER}@${SSH_HOST}" \
  "echo '[test_aracne_ssh] SSH OK'" && exit 0

echo "[test_aracne_ssh] SSH failed"
exit 1
