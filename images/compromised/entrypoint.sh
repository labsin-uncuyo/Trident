#!/bin/bash
set -euo pipefail

: "${LAB_PASSWORD:?LAB_PASSWORD must be set}"
: "${RUN_ID:=run_local}"

printf 'labuser:%s\n' "${LAB_PASSWORD}" | chpasswd

mkdir -p /etc/sudoers.d
echo "labuser ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/labuser
chmod 440 /etc/sudoers.d/labuser
echo 'Defaults env_keep += "OPENCODE_API_KEY"' >/etc/sudoers.d/opencode_env
chmod 440 /etc/sudoers.d/opencode_env

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

# Ensure OpenCode is on PATH for all users/shells (copy binary out of /root)
if [ -x /root/.opencode/bin/opencode ]; then
    rm -f /usr/local/bin/opencode /usr/bin/opencode
    install -m 755 /root/.opencode/bin/opencode /usr/local/bin/opencode
    ln -sf /usr/local/bin/opencode /usr/bin/opencode
fi
cat >/etc/profile.d/opencode.sh <<'EOF'
export PATH="/usr/local/bin:/usr/bin:${PATH}"
EOF
chmod 644 /etc/profile.d/opencode.sh

# Ensure OPENCODE_API_KEY is available in SSH login shells
if [ -n "${OPENCODE_API_KEY:-}" ]; then
    cat >/etc/profile.d/opencode_env.sh <<EOF
export OPENCODE_API_KEY='${OPENCODE_API_KEY}'
EOF
    chmod 644 /etc/profile.d/opencode_env.sh
fi

# Mirror OpenCode auth/config for labuser SSH sessions
install -d -m 700 -o labuser -g labuser /home/labuser/.config/opencode /home/labuser/.local/share/opencode
install -d -m 700 -o labuser -g labuser /home/labuser/.local/state
cat >/home/labuser/.local/share/opencode/auth.json <<EOF
{
    "e-infra-chat": {
        "type": "api",
        "key": "${OPENCODE_API_KEY:-}"
    }
}
EOF
chown labuser:labuser /home/labuser/.local/share/opencode/auth.json

# Copy OpenCode configuration (already has {env:OPENCODE_API_KEY} placeholder)
if [ -f /root/.config/opencode/opencode.json.template ]; then
    cp /root/.config/opencode/opencode.json.template /root/.config/opencode/opencode.json
    install -m 600 -o labuser -g labuser /root/.config/opencode/opencode.json.template /home/labuser/.config/opencode/opencode.json
fi

# Setup SSH authorized keys for GHOSTS driver
install -m 700 -o labuser -g labuser -d /home/labuser/.ssh

# First, install the key from the secrets volume if it exists
if [ -f /secrets/authorized_keys ]; then
    install -m 600 -o labuser -g labuser /secrets/authorized_keys /home/labuser/.ssh/authorized_keys
    echo "✓ SSH authorized_keys installed from /secrets/authorized_keys"
fi

# Setup SSH authorized_keys for auto_responder from shared volume
# The auto_responder_ssh_keys volume contains the public key that defender will use
mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# Copy the auto_responder public key to root's authorized_keys
if [ -f /root/.ssh_auto_responder/id_rsa_auto_responder.pub ]; then
    pub_key=$(cat /root/.ssh_auto_responder/id_rsa_auto_responder.pub)
    # Add key if not already present
    if ! grep -qxF "${pub_key}" /root/.ssh/authorized_keys 2>/dev/null; then
        echo "${pub_key}" >> /root/.ssh/authorized_keys
        echo "✓ Auto-responder SSH key installed for root"
    fi
fi

# Fix permissions for labuser to write logs
chown -R labuser:labuser "/outputs/${RUN_ID}/ghosts_logs"
chown -R labuser:labuser "/outputs/backups/john_scott"
chmod -R 755 "/outputs/${RUN_ID}/ghosts_logs"
chmod -R 755 "/outputs/backups/john_scott"

# Ensure the compromised host routes traffic through the router
ip route replace 172.31.0.0/24 via 172.30.0.1 || true
ip route replace 172.32.0.0/24 via 172.30.0.1 || true

# Configure DNS to use our router (172.30.0.1) which runs BIND9
# This ensures DNS traffic goes through the router and is captured in PCAPs
rm -f /etc/resolv.conf
cat > /etc/resolv.conf <<EOF
nameserver 172.30.0.1
search lab.local
options timeout:2 attempts:3
EOF
echo "✓ DNS configured to use router DNS server (172.30.0.1)"

# Start SSH server in background
/usr/sbin/sshd

# Keep container running
exec tail -f /dev/null
