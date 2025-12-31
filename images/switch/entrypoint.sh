#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"

pcap_dir="/outputs/${RUN_ID}/pcaps"
mkdir -p "${pcap_dir}"

log_file=/var/log/switch-collector.log
touch "${log_file}"

collector_loop() {
    while true; do
        echo "switch: awaiting stream on port 7000" >>"${log_file}"
        nc -l -p 7000 \
            | tee "${pcap_dir}/switch_stream.pcap" \
            | nc -q0 172.30.0.200 9000 || true
        echo "switch: stream closed, restarting listener" >>"${log_file}"
        sleep 1
    done
}

collector_loop &

tail -n0 -F "${log_file}"
