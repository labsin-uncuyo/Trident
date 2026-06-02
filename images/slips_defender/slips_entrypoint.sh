#!/bin/bash
set -euo pipefail

: "${RUN_ID:=run_local}"
: "${DEFENDER_PORT:=8000}"
: "${SLIPS_PROCESS_TIMEOUT:=240}"

# Dynamic SLIPS base detection
SLIPS_BASE="/StratosphereLinuxIPS"
if [ ! -f "$SLIPS_BASE/slips.py" ]; then
    if [ -f "/opt/slips/slips.py" ]; then
        SLIPS_BASE="/opt/slips"
    elif [ -f "/usr/local/slips/slips.py" ]; then
        SLIPS_BASE="/usr/local/slips"
    fi
fi

SLIPS_DATASET_DIR="$SLIPS_BASE/dataset"
SLIPS_OUTPUT_DIR="$SLIPS_BASE/output"
DEFENDER_URL="http://127.0.0.1:${DEFENDER_PORT}/alerts"

mkdir -p "/outputs/${RUN_ID}/pcaps" "/outputs/${RUN_ID}/slips"
mkdir -p "${SLIPS_DATASET_DIR}" "${SLIPS_OUTPUT_DIR}"

# Sync local ports_info overrides into the Slips runtime path (if directory exists)
if [ -d "$SLIPS_BASE/slips_files/ports_info" ]; then
    cp -f /opt/lab/slips_files/ports_info/services.csv "$SLIPS_BASE/slips_files/ports_info/services.csv" || true
fi

# Run compatibility diagnostic if available
if [ -f "/opt/lab/diagnose_slips_compat.sh" ]; then
    echo "🔧 Running SLIPS compatibility diagnostic..."
    bash /opt/lab/diagnose_slips_compat.sh || echo "⚠️ Diagnostic completed with warnings"
fi

# Clear stale pcaps so the watcher processes fresh captures promptly
find "${SLIPS_DATASET_DIR}" -maxdepth 1 -type f -name "*.pcap*" \
  ! -name "router.pcap" ! -name "router_stream.pcap" ! -name "switch_stream.pcap" ! -name "server.pcap" \
  -delete || true

# Note: fastapi, uvicorn, requests are now installed at build time in Dockerfile
# No need for runtime pip install (which fails due to no network access in container)

export RUN_ID
export DEFENDER_PORT
export SLIPS_PROCESS_TIMEOUT
export SLIPS_DATASET_DIR
export SLIPS_OUTPUT_DIR
export DEFENDER_URL

cd /opt/lab

if [[ "${DNS_ONLY_DEFENSE:-}" =~ ^(true|1|yes|on)$ ]]; then
    echo "✅ DNS_ONLY_DEFENSE enabled: tuning SLIPS for DNS-only analysis"
    python3 - <<'PY'
import re
from pathlib import Path

path = Path("/StratosphereLinuxIPS/config/slips.yaml")
text = path.read_text(encoding="utf-8")

replacements = {
    r"^(\s*time_window_width:)\s*.*$": "\\1 60",
    r"^(\s*analysis_direction:)\s*.*$": "\\1 out",
    r"^(\s*pcapfilter:)\s*.*$": "\\1 'port 53'",
    r"^(\s*disable:)\s*.*$": "\\1 [template, rnn_cc_detection, flowmldetection, threat_intelligence, update_manager, virustotal, timeline, blocking, networkdiscovery]",
}

for pattern, replacement in replacements.items():
    text = re.sub(pattern, replacement, text, flags=re.MULTILINE)

path.write_text(text, encoding="utf-8")
PY
fi

# Ensure SSH keys are generated and authorized on target hosts
if ! bash /opt/lab/setup_ssh_keys.sh; then
    echo "⚠️ SSH key setup encountered issues; continuing startup. Check logs above."
fi

# Clear stale SSH known_hosts to avoid "host key changed" errors
rm -f /root/.ssh/known_hosts
echo "✅ Cleared stale SSH known_hosts"

# Apply HTTP analyzer password guessing detection patches
echo "🔧 Applying HTTP analyzer patches..."
# Handle different SLIPS versions with varying module paths
HTTP_ANALYZER_DIR=""
if [ -d "/StratosphereLinuxIPS/modules/http_analyzer" ]; then
    HTTP_ANALYZER_DIR="/StratosphereLinuxIPS/modules/http_analyzer"
elif [ -d "/StratosphereLinuxIPS/slips_modules/http_analyzer" ]; then
    HTTP_ANALYZER_DIR="/StratosphereLinuxIPS/slips_modules/http_analyzer"
elif [ -d "/opt/slips/modules/http_analyzer" ]; then
    HTTP_ANALYZER_DIR="/opt/slips/modules/http_analyzer"
fi

if [ -n "$HTTP_ANALYZER_DIR" ]; then
    if [ -f "/opt/lab/patches/http_analyzer/http_analyzer.py" ]; then
        cp /opt/lab/patches/http_analyzer/http_analyzer.py "$HTTP_ANALYZER_DIR/http_analyzer.py"
        echo "✅ Applied http_analyzer.py patch to $HTTP_ANALYZER_DIR"
    else
        echo "⚠️ http_analyzer.py patch not found, skipping"
    fi

    if [ -f "/opt/lab/patches/http_analyzer/set_evidence.py" ]; then
        cp /opt/lab/patches/http_analyzer/set_evidence.py "$HTTP_ANALYZER_DIR/set_evidence.py"
        echo "✅ Applied set_evidence.py patch to $HTTP_ANALYZER_DIR"
    else
        echo "⚠️ set_evidence.py patch not found, skipping"
    fi
else
    echo "⚠️ Could not find http_analyzer module directory - patches not applied"
fi

# Ensure HTTP protocol is enabled in Zeek
echo "🔧 Ensuring HTTP protocol analysis is enabled..."
# Handle different SLIPS versions with varying Zeek script locations
ZEEK_LOAD_FILE=""
if [ -f "/StratosphereLinuxIPS/zeek-scripts/__load__.zeek" ]; then
    ZEEK_LOAD_FILE="/StratosphereLinuxIPS/zeek-scripts/__load__.zeek"
elif [ -f "/StratosphereLinuxIPS/zeek/__load__.zeek" ]; then
    ZEEK_LOAD_FILE="/StratosphereLinuxIPS/zeek/__load__.zeek"
elif [ -f "/usr/local/zeek/share/zeek/__load__.zeek" ]; then
    ZEEK_LOAD_FILE="/usr/local/zeek/share/zeek/__load__.zeek"
fi

if [ -n "$ZEEK_LOAD_FILE" ]; then
    if ! grep -q "@load base/protocols/http/main" "$ZEEK_LOAD_FILE"; then
        # Add HTTP loading at the beginning of the file, after the existing loads
        sed -i '/^@load \.\/slips-conf\.zeek/a @load base/protocols/http/main' "$ZEEK_LOAD_FILE"
        echo "✅ Enabled HTTP protocol analysis in Zeek ($ZEEK_LOAD_FILE)"
    else
        echo "✅ HTTP protocol analysis already enabled"
    fi
else
    echo "⚠️ Could not find Zeek __load__.zeek file - HTTP analysis may not be enabled"
fi

python3 -m uvicorn defender_api:app --host 0.0.0.0 --port "${DEFENDER_PORT}" --log-level info &
RECEIVER_PID=$!

# Planner API
python3 -m uvicorn defender.app.main:app --host 127.0.0.1 --port "${PLANNER_PORT:-1654}" --log-level info &
PLANNER_PID=$!

python3 /opt/lab/forward_alerts.py &
TAIL_PID=$!

python3 /opt/lab/watch_pcaps.py &
WATCH_PID=$!

python3 /opt/lab/defender/auto_responder.py &
AUTO_PID=$!

cleanup() {
    # Kill all processes
    [ -n "${RECEIVER_PID}" ] && kill "${RECEIVER_PID}" >/dev/null 2>&1 || true
    [ -n "${PLANNER_PID}" ] && kill "${PLANNER_PID}" >/dev/null 2>&1 || true
    [ -n "${TAIL_PID}" ] && kill "${TAIL_PID}" >/dev/null 2>&1 || true
    [ -n "${WATCH_PID}" ] && kill "${WATCH_PID}" >/dev/null 2>&1 || true
    [ -n "${AUTO_PID}" ] && kill "${AUTO_PID}" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

# Wait for all processes
PIDS_TO_WAIT=()
[ -n "${RECEIVER_PID}" ] && PIDS_TO_WAIT+=("${RECEIVER_PID}")
[ -n "${PLANNER_PID}" ] && PIDS_TO_WAIT+=("${PLANNER_PID}")
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
