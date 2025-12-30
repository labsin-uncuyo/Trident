#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"
: "${PCAP_ROTATE_SECS:=30}"

pcap_dir="/outputs/${RUN_ID}/pcaps"
mkdir -p "${pcap_dir}"
ln -sfn "${pcap_dir}" /pcaps
# Keep router captures clear of the mirror channel to the switch (port 7000).
capture_filter='not (host 172.30.0.2 and port 7000)'

sysctl -w net.ipv4.ip_forward=1 >/dev/null

# Setup DNAT rule for simulated data exfiltration to fake public IP
# Redirects traffic destined for 137.184.126.86:443 to router itself (172.31.0.1:443)
# This allows realistic PCAP captures showing exfiltration to a "public" IP
# while actually capturing the data locally
iptables-legacy -t nat -A PREROUTING -d 137.184.126.86 -p tcp --dport 443 -j DNAT --to-destination 172.31.0.1:443 2>/dev/null || true

# Start netcat listener to receive exfiltrated data on port 443
# Data will be saved to /tmp/exfil/labdb_dump.sql
mkdir -p /tmp/exfil
nc -lvnp 443 > /tmp/exfil/labdb_dump.sql 2>/tmp/exfil/nc.log &
echo "✓ Data exfiltration listener started on port 443 (fake IP: 137.184.126.86)"

file_log=/var/log/router-capture.log
stream_log=/var/log/router-stream.log
touch "${file_log}" "${stream_log}"

# Rotate captures to keep SLIPS runs small and fast
tcpdump -U -s 0 -i any \
  -G "${PCAP_ROTATE_SECS}" \
  -w "${pcap_dir}/router_%Y-%m-%d_%H-%M-%S.pcap" \
  -Z root \
  "${capture_filter}" >>"${file_log}" 2>&1 &

stream_packets() {
    while true; do
        tcpdump -U -s 0 -i any -w - "${capture_filter}" 2>>"${stream_log}" \
            | tee "${pcap_dir}/router_stream.pcap" \
            | nc -q0 172.30.0.2 7000 || true
        echo "router: restarting mirror pipeline" >>"${stream_log}"
        sleep 2
    done
}

stream_packets &

trap 'pkill tcpdump || true' EXIT

tail -n0 -F "${file_log}" "${stream_log}"
