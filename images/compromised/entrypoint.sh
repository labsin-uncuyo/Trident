#!/bin/bash
set -euo pipefail

: "${LAB_PASSWORD:?LAB_PASSWORD must be set}"
: "${RUN_ID:=run_local}"

printf 'labuser:%s\n' "${LAB_PASSWORD}" | chpasswd

mkdir -p /etc/sudoers.d
echo "labuser ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/labuser
chmod 440 /etc/sudoers.d/labuser

# Create OpenCode auth.json with API key from environment
mkdir -p /root/.local/share/opencode
cat >/root/.local/share/opencode/auth.json <<EOF
{
    "e-infra-chat": {
        "type": "api",
        "key": "${OPENCODE_API_KEY:-}"
    }
}
EOF

# Copy OpenCode configuration (already has {env:OPENCODE_API_KEY} placeholder)
if [ -f /root/.config/opencode/opencode.json.template ]; then
    cp /root/.config/opencode/opencode.json.template /root/.config/opencode/opencode.json
fi

# Setup SSH authorized keys for GHOSTS driver
install -m 700 -o labuser -g labuser -d /home/labuser/.ssh

# First, install the key from the secrets volume if it exists
if [ -f /secrets/authorized_keys ]; then
    install -m 600 -o labuser -g labuser /secrets/authorized_keys /home/labuser/.ssh/authorized_keys
    echo "✓ SSH authorized_keys installed from /secrets/authorized_keys"
fi

# Also install the key from the temporary location (from Dockerfile COPY)
if [ -f /tmp/ghosts_authorized_keys ]; then
    cat /tmp/ghosts_authorized_keys >> /home/labuser/.ssh/authorized_keys
    chown labuser:labuser /home/labuser/.ssh/authorized_keys
    chmod 600 /home/labuser/.ssh/authorized_keys
    rm /tmp/ghosts_authorized_keys
    echo "✓ GHOSTS driver SSH key installed"
fi

mkdir -p "/outputs/${RUN_ID}"
mkdir -p "/outputs/${RUN_ID}/ghosts_logs/john_scott"
mkdir -p "/outputs/backups/john_scott"

# Fix permissions for labuser to write logs
chown -R labuser:labuser "/outputs/${RUN_ID}/ghosts_logs"
chown -R labuser:labuser "/outputs/backups/john_scott"
chmod -R 755 "/outputs/${RUN_ID}/ghosts_logs"
chmod -R 755 "/outputs/backups/john_scott"

# Ensure the compromised host routes net_b traffic through the router
ip route replace 172.31.0.0/24 via 172.30.0.1 || true

# Start SSH server in background
/usr/sbin/sshd

# Note: GHOSTS client is now running in the ghosts_driver container
# using the Puppeteer architecture. It connects to this machine via SSH.
# No need to build or run GHOSTS here.

# Wait for database server to be ready
echo "Waiting for database server to be ready..."
max_attempts=30
attempt=0
until PGPASSWORD="john_scott" psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb -c "SELECT 1" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ $attempt -ge $max_attempts ]; then
        echo "WARNING: Database not available after ${max_attempts} attempts"
        echo "Continuing anyway..."
        break
    fi
    echo "Attempt ${attempt}/${max_attempts}: Database not ready, waiting..."
    sleep 5
done

echo "Database is ready!"
echo "SSH server is running on port 22"
echo "Ready for GHOSTS driver connections"

# Keep container running
exec tail -f /dev/null
