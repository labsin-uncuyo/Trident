#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"
: "${PCAP_ROTATE_SECS:=60}"

pcap_dir="/outputs/${RUN_ID}/pcaps"
mkdir -p "${pcap_dir}"
ln -sfn "${pcap_dir}" /pcaps
# Keep router captures clear of the mirror channel to the switch (port 7000).
capture_filter='not (host 172.30.0.2 and port 7000)'

sysctl -w net.ipv4.ip_forward=1 >/dev/null

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
