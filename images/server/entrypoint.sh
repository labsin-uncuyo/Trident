#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"
: "${LOGIN_USER:=admin}"
: "${LOGIN_PASSWORD:=admin}"
: "${DB_USER:=labuser}"
: "${DB_PASSWORD:=labpass}"

export LOGIN_USER
export LOGIN_PASSWORD
export DB_USER
export DB_PASSWORD

if ! id -u "${LOGIN_USER}" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "${LOGIN_USER}"
fi
printf '%s:%s\n' "${LOGIN_USER}" "${LOGIN_PASSWORD}" | chpasswd

pcap_dir="/outputs/${RUN_ID}/pcaps"
mkdir -p "${pcap_dir}"

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
    # Also add to admin user's authorized_keys for compatibility
    mkdir -p /home/admin/.ssh
    chmod 700 /home/admin/.ssh
    if ! grep -qxF "${pub_key}" /home/admin/.ssh/authorized_keys 2>/dev/null; then
        echo "${pub_key}" >> /home/admin/.ssh/authorized_keys
        chown -R admin:admin /home/admin/.ssh
        echo "✓ Auto-responder SSH key installed for admin"
    fi
fi

mkdir -p "/outputs/${RUN_ID}" /var/log/nginx

pg_version="$(ls /etc/postgresql | head -n1)"
pg_conf="/etc/postgresql/${pg_version}/main/postgresql.conf"
pg_hba="/etc/postgresql/${pg_version}/main/pg_hba.conf"
pg_log="/var/log/postgresql/postgresql-${pg_version}-main.log"

sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/g" "${pg_conf}"
# Force plaintext connections so router captures show queries without SSL wrapping
sed -i "s/^#\\?ssl = .*/ssl = off/" "${pg_conf}"
sed -i '/0.0.0.0\/0.*trust/d' "${pg_hba}"
if ! grep -q "0.0.0.0/0.*md5" "${pg_hba}"; then
    echo "host all all 0.0.0.0/0 md5" >> "${pg_hba}"
fi

systemctl start postgresql
systemctl start ssh

runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}';" | grep -q 1 \
    || runuser -u postgres -- psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" >/dev/null
runuser -u postgres -- psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" >/dev/null
runuser -u postgres -- psql -c "GRANT pg_execute_server_program TO ${DB_USER};" >/dev/null

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='labdb';" | grep -q 1; then
    runuser -u postgres -- createdb labdb
fi
runuser -u postgres -- psql -d labdb -c "CREATE TABLE IF NOT EXISTS events (id serial PRIMARY KEY, msg text);" >/dev/null

# Start nginx early so healthcheck passes during database loading
systemctl start nginx

# Ensure hosts on net_a are reachable through router (do this BEFORE database loading)
ip route replace 172.30.0.0/24 via 172.31.0.1 || true
ip route replace default via 172.31.0.1 dev eth0 || true

# Add route for simulated exfiltration IP (for data exfiltration simulation)
# Traffic to 137.184.126.86 will be routed through the router for DNAT
ip route add 137.184.126.86 via 172.31.0.1 dev eth0 2>/dev/null || true

# Load employee database if not already loaded (check if employee table has data)
employee_count=$(runuser -u postgres -- psql -d labdb -tAc "SELECT COUNT(*) FROM employee;" 2>/dev/null || echo "0")
if [ "$employee_count" -eq 0 ]; then
    echo "Loading employee database (this may take a few minutes)..."
    runuser -u postgres -- psql -d labdb -f /opt/database/employees_data_modified.sql
    echo "Employee database loaded successfully."
fi

# Load roles and users if not already created
if ! runuser -u postgres -- psql -d labdb -tAc "SELECT 1 FROM pg_roles WHERE rolname='john_scott';" | grep -q 1; then
    echo "Creating database roles and users..."
    runuser -u postgres -- psql -d labdb -f /opt/database/roles_users.sql >/dev/null 2>&1
    echo "Roles and users created successfully."
fi

# Start the lab login app behind nginx.
login_log=/var/log/flask-login.log
touch "${login_log}"
python3 /opt/flask_app/app.py >>"${login_log}" 2>&1 &

capture_log=/var/log/server-capture.log
touch /var/log/nginx/access.log /var/log/nginx/error.log "${pg_log}" "${capture_log}"

# Capture all traffic seen by the server so SLIPS can analyze client<->server flows
tcpdump -U -s 0 -i eth0 -w "${pcap_dir}/server.pcap" >>"${capture_log}" 2>&1 &
TCPDUMP_PID=$!

trap 'kill "${TCPDUMP_PID}" >/dev/null 2>&1 || true' EXIT

# Re-assert default route in case container networking reset it.
ip route replace default via 172.31.0.1 dev eth0 || true

tail -n0 -F /var/log/nginx/access.log /var/log/nginx/error.log "${pg_log}" "${capture_log}" "${login_log}"
