#!/usr/bin/env bash
set -euo pipefail

SSH_HOST=${SSH_HOST:-127.0.0.1}
SSH_PORT=${SSH_PORT:-2223}
SSH_USER=${SSH_USER:-labuser}
SSH_PASSWORD=${SSH_PASSWORD:-adminadmin}
GOAL=${GOAL:-"Create the file /home/labuser/aracne_was_here.txt containing 'aracne ok' and then read it back to confirm."}
CONFIG_SRC="/agent/config/AttackConfig_lab.yaml"
CONFIG_DST="/tmp/AttackConfig_lab_resolved.yaml"

until sshpass -p "$SSH_PASSWORD" ssh \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o ConnectTimeout=2 \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -p "$SSH_PORT" \
  "${SSH_USER}@${SSH_HOST}" "echo ready" >/dev/null 2>&1; do
  echo "Waiting for SSH target ${SSH_HOST}:${SSH_PORT}..."
  sleep 2
done

# Render config with environment variable expansion
python3 - "$CONFIG_SRC" "$CONFIG_DST" <<'PY'
import os, sys, yaml
from pathlib import Path

def expand(obj):
    if isinstance(obj, dict):
        return {k: expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand(v) for v in obj]
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    return obj

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
data = yaml.safe_load(src.read_text())
data = expand(data)
dst.write_text(yaml.safe_dump(data))
PY

# Start netcat listener in background to receive database dumps
nc -lvnp 443 > /tmp/labdb_dump.sql 2>/tmp/nc_listener.log &
echo "Netcat listener started on port 443"

exec python3 aracne.py \
  -e /agent/.env \
  -c "$CONFIG_DST" \
  -g "$GOAL"
