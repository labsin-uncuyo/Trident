#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"
: "${PCAP_ROTATE_SECS:=30}"

pcap_dir="/outputs/${RUN_ID}/pcaps"
mkdir -p "${pcap_dir}"
ln -sfn "${pcap_dir}" /pcaps

sysctl -w net.ipv4.ip_forward=1 >/dev/null

# Ensure the router is the default gateway for lab traffic.
lan_a_ip="172.30.0.1"
lan_b_ip="172.31.0.1"
host_a_ip="172.30.0.254"
host_b_ip="172.31.0.254"
compromised_ip="172.30.0.10"
server_ip="172.31.0.10"

# Start DNS forwarder on the router so client queries traverse it.
dnsmasq --no-daemon \
  --listen-address="${lan_a_ip}","${lan_b_ip}" \
  --bind-interfaces \
  --no-hosts \
  --no-resolv \
  --server=1.1.1.1 \
  --server=8.8.8.8 \
  >/var/log/dnsmasq.log 2>&1 &
wait_for_iface() {
    local ip="$1"
    local tries=20
    while [ "${tries}" -gt 0 ]; do
        iface="$(ip -o -4 addr show | awk -v ip="${ip}" '$4 ~ ip {print $2; exit}')"
        if [ -n "${iface}" ]; then
            echo "${iface}"
            return 0
        fi
        sleep 0.5
        tries=$((tries - 1))
    done
    return 1
}

lan_a_if="$(wait_for_iface "${lan_a_ip}" || true)"
lan_b_if="$(wait_for_iface "${lan_b_ip}" || true)"

if [ -n "${lan_a_if}" ] && [ -n "${lan_b_if}" ]; then
    if ! iptables-legacy -C FORWARD -i "${lan_b_if}" -o "${lan_a_if}" -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_b_if}" -o "${lan_a_if}" -j ACCEPT
    fi
    if ! iptables-legacy -C FORWARD -i "${lan_a_if}" -o "${lan_b_if}" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_a_if}" -o "${lan_b_if}" -m state --state RELATED,ESTABLISHED -j ACCEPT
    fi
    # Allow same-interface forwarding for host->router port forwards.
    if ! iptables-legacy -C FORWARD -i "${lan_a_if}" -o "${lan_a_if}" -p tcp -d "${compromised_ip}" --dport 22 -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_a_if}" -o "${lan_a_if}" -p tcp -d "${compromised_ip}" --dport 22 -j ACCEPT
    fi
    if ! iptables-legacy -C FORWARD -i "${lan_a_if}" -o "${lan_a_if}" -p tcp -s "${compromised_ip}" --sport 22 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_a_if}" -o "${lan_a_if}" -p tcp -s "${compromised_ip}" --sport 22 -m state --state RELATED,ESTABLISHED -j ACCEPT
    fi
    if ! iptables-legacy -C FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -d "${server_ip}" --dport 80 -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -d "${server_ip}" --dport 80 -j ACCEPT
    fi
    if ! iptables-legacy -C FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -s "${server_ip}" --sport 80 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -s "${server_ip}" --sport 80 -m state --state RELATED,ESTABLISHED -j ACCEPT
    fi
    if ! iptables-legacy -C FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -d "${server_ip}" --dport 5432 -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -d "${server_ip}" --dport 5432 -j ACCEPT
    fi
    if ! iptables-legacy -C FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -s "${server_ip}" --sport 5432 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
        iptables-legacy -A FORWARD -i "${lan_b_if}" -o "${lan_b_if}" -p tcp -s "${server_ip}" --sport 5432 -m state --state RELATED,ESTABLISHED -j ACCEPT
    fi
    if ! iptables-legacy -t nat -C POSTROUTING -s 172.31.0.0/24 ! -d 172.30.0.0/24 -o "${lan_a_if}" -j MASQUERADE 2>/dev/null; then
        iptables-legacy -t nat -A POSTROUTING -s 172.31.0.0/24 ! -d 172.30.0.0/24 -o "${lan_a_if}" -j MASQUERADE
    fi
    # Host access through router IPs (DNAT + SNAT to keep replies routed).
    if ! iptables-legacy -t nat -C PREROUTING -i "${lan_a_if}" -d "${lan_a_ip}" -p tcp --dport 22 -j DNAT --to-destination "${compromised_ip}:22" 2>/dev/null; then
        iptables-legacy -t nat -A PREROUTING -i "${lan_a_if}" -d "${lan_a_ip}" -p tcp --dport 22 -j DNAT --to-destination "${compromised_ip}:22"
    fi
    if ! iptables-legacy -t nat -C POSTROUTING -s "${host_a_ip}" -d "${compromised_ip}" -p tcp --dport 22 -j SNAT --to-source "${lan_a_ip}" 2>/dev/null; then
        iptables-legacy -t nat -A POSTROUTING -s "${host_a_ip}" -d "${compromised_ip}" -p tcp --dport 22 -j SNAT --to-source "${lan_a_ip}"
    fi
    if ! iptables-legacy -t nat -C PREROUTING -i "${lan_b_if}" -d "${lan_b_ip}" -p tcp --dport 80 -j DNAT --to-destination "${server_ip}:80" 2>/dev/null; then
        iptables-legacy -t nat -A PREROUTING -i "${lan_b_if}" -d "${lan_b_ip}" -p tcp --dport 80 -j DNAT --to-destination "${server_ip}:80"
    fi
    if ! iptables-legacy -t nat -C PREROUTING -i "${lan_b_if}" -d "${lan_b_ip}" -p tcp --dport 5432 -j DNAT --to-destination "${server_ip}:5432" 2>/dev/null; then
        iptables-legacy -t nat -A PREROUTING -i "${lan_b_if}" -d "${lan_b_ip}" -p tcp --dport 5432 -j DNAT --to-destination "${server_ip}:5432"
    fi
    if ! iptables-legacy -t nat -C POSTROUTING -s "${host_b_ip}" -d "${server_ip}" -p tcp --dport 80 -j SNAT --to-source "${lan_b_ip}" 2>/dev/null; then
        iptables-legacy -t nat -A POSTROUTING -s "${host_b_ip}" -d "${server_ip}" -p tcp --dport 80 -j SNAT --to-source "${lan_b_ip}"
    fi
    if ! iptables-legacy -t nat -C POSTROUTING -s "${host_b_ip}" -d "${server_ip}" -p tcp --dport 5432 -j SNAT --to-source "${lan_b_ip}" 2>/dev/null; then
        iptables-legacy -t nat -A POSTROUTING -s "${host_b_ip}" -d "${server_ip}" -p tcp --dport 5432 -j SNAT --to-source "${lan_b_ip}"
    fi
else
    echo "router: interfaces not ready; skipping forward/NAT rules" >&2
fi

# Setup DNAT rule for simulated data exfiltration to fake public IP
# Redirects traffic destined for 137.184.126.86:443 to router itself (172.31.0.1:443)
# This allows realistic PCAP captures showing exfiltration to a "public" IP
# while actually capturing the data locally
iptables-legacy -t nat -A PREROUTING -d 137.184.126.86 -p tcp --dport 443 -j DNAT --to-destination 172.31.0.1:443 2>/dev/null || true

# Start netcat listener to receive exfiltrated data on port 443
# Data will be saved to /tmp/exfil/labdb_dump.sql
mkdir -p /tmp/exfil
nc -lvnp 443 -k > /tmp/exfil/labdb_dump.sql 2>/tmp/exfil/nc.log &
echo "✓ Data exfiltration listener started on port 443 (fake IP: 137.184.126.86)"

file_log=/var/log/router-capture.log
touch "${file_log}"

# Rotate captures to keep SLIPS runs small and fast
# Capture on eth1 (client/compromised side) with proper Ethernet headers for Zeek
tcpdump -U -s 0 -i eth1 \
  -G "${PCAP_ROTATE_SECS}" \
  -w "${pcap_dir}/router_%Y-%m-%d_%H-%M-%S.pcap" \
  -Z root \
  >>"${file_log}" 2>&1 &

trap 'pkill tcpdump || true' EXIT

tail -n0 -F "${file_log}"
