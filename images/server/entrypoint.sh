#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"

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

mkdir -p "/outputs/${RUN_ID}" /var/log/nginx

pg_version="$(ls /etc/postgresql | head -n1)"
pg_conf="/etc/postgresql/${pg_version}/main/postgresql.conf"
pg_hba="/etc/postgresql/${pg_version}/main/pg_hba.conf"
pg_log="/var/log/postgresql/postgresql-${pg_version}-main.log"

sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/g" "${pg_conf}"
if ! grep -q "0.0.0.0/0" "${pg_hba}"; then
    echo "host all all 0.0.0.0/0 trust" >> "${pg_hba}"
fi

systemctl start postgresql
systemctl start ssh

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='labdb';" | grep -q 1; then
    runuser -u postgres -- createdb labdb
fi
runuser -u postgres -- psql -d labdb -c "CREATE TABLE IF NOT EXISTS events (id serial PRIMARY KEY, msg text);" >/dev/null

# Load employee database if not already loaded
if ! runuser -u postgres -- psql -d labdb -tAc "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='employee';" | grep -q 1; then
    echo "Loading employee database (this may take a few minutes)..."
    runuser -u postgres -- psql -d labdb -f /opt/database/employees_data_modified.sql >/dev/null 2>&1
    echo "Employee database loaded successfully."
fi

# Load roles and users if not already created
if ! runuser -u postgres -- psql -d labdb -tAc "SELECT 1 FROM pg_roles WHERE rolname='john_scott';" | grep -q 1; then
    echo "Creating database roles and users..."
    runuser -u postgres -- psql -d labdb -f /opt/database/roles_users.sql >/dev/null 2>&1
    echo "Roles and users created successfully."
fi

systemctl start nginx

# Ensure hosts on net_a are reachable through router
ip route replace 172.30.0.0/24 via 172.31.0.1 || true

capture_log=/var/log/server-capture.log
touch /var/log/nginx/access.log /var/log/nginx/error.log "${pg_log}" "${capture_log}"

# Capture all traffic seen by the server so SLIPS can analyze client<->server flows
tcpdump -U -s 0 -i eth0 -w "${pcap_dir}/server.pcap" >>"${capture_log}" 2>&1 &
TCPDUMP_PID=$!

trap 'kill "${TCPDUMP_PID}" >/dev/null 2>&1 || true' EXIT

tail -n0 -F /var/log/nginx/access.log /var/log/nginx/error.log "${pg_log}" "${capture_log}"
