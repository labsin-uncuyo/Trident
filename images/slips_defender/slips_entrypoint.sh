#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"
: "${DEFENDER_PORT:=8000}"

SLIPS_DATASET_DIR="/StratosphereLinuxIPS/dataset"
SLIPS_OUTPUT_DIR="/StratosphereLinuxIPS/output"
DEFENDER_URL="http://127.0.0.1:${DEFENDER_PORT}/alerts"

mkdir -p "/outputs/${RUN_ID}/pcaps" "/outputs/${RUN_ID}/slips"
mkdir -p "${SLIPS_DATASET_DIR}" "${SLIPS_OUTPUT_DIR}"
mkdir -p "/StratosphereLinuxIPS/slips_files/ports_info"

# Clear stale pcaps so the watcher processes fresh captures promptly
find "${SLIPS_DATASET_DIR}" -maxdepth 1 -type f -name "*.pcap*" \
  ! -name "router.pcap" ! -name "router_stream.pcap" ! -name "switch_stream.pcap" ! -name "server.pcap" \
  -delete || true

if ! pip3 install --no-cache-dir fastapi==0.110.0 uvicorn==0.27.1 requests==2.31.0 >/tmp/slips_pip.log 2>&1; then
    cat /tmp/slips_pip.log
    exit 1
fi

export RUN_ID
export DEFENDER_PORT
export SLIPS_DATASET_DIR
export SLIPS_OUTPUT_DIR
export DEFENDER_URL

cd /opt/lab

# Ensure SSH keys are generated and authorized on target hosts
if ! /opt/lab/setup_ssh_keys.sh; then
    echo "⚠️ SSH key setup encountered issues; continuing startup. Check logs above."
fi

python3 -m uvicorn defender_api:app --host 0.0.0.0 --port "${DEFENDER_PORT}" --log-level info &
RECEIVER_PID=$!

# Planner API disabled due to missing dependencies
# python3 -m uvicorn defender.app.main:app --host 127.0.0.1 --port "${PLANNER_PORT:-1654}" --log-level info &
# PLANNER_PID=$!
PLANNER_PID=""

python3 /opt/lab/forward_alerts.py &
TAIL_PID=$!

python3 /opt/lab/watch_pcaps.py &
WATCH_PID=$!

python3 /opt/lab/defender/auto_responder.py &
AUTO_PID=$!

cleanup() {
    # Only kill processes that have PIDs (planner is disabled)
    [ -n "${RECEIVER_PID}" ] && kill "${RECEIVER_PID}" >/dev/null 2>&1 || true
    [ -n "${PLANNER_PID}" ] && kill "${PLANNER_PID}" >/dev/null 2>&1 || true
    [ -n "${TAIL_PID}" ] && kill "${TAIL_PID}" >/dev/null 2>&1 || true
    [ -n "${WATCH_PID}" ] && kill "${WATCH_PID}" >/dev/null 2>&1 || true
    [ -n "${AUTO_PID}" ] && kill "${AUTO_PID}" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

# Only wait for processes that are running (planner is disabled)
PIDS_TO_WAIT=()
[ -n "${RECEIVER_PID}" ] && PIDS_TO_WAIT+=("${RECEIVER_PID}")
[ -n "${TAIL_PID}" ] && PIDS_TO_WAIT+=("${TAIL_PID}")
[ -n "${WATCH_PID}" ] && PIDS_TO_WAIT+=("${WATCH_PID}")
[ -n "${AUTO_PID}" ] && PIDS_TO_WAIT+=("${AUTO_PID}")

if [ ${#PIDS_TO_WAIT[@]} -gt 0 ]; then
    wait -n "${PIDS_TO_WAIT[@]}"
fi
EXIT_CODE=$?
cleanup
wait || true
exit "${EXIT_CODE}"
