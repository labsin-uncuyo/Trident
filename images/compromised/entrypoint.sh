#!/bin/bash
set -euo pipefail

: "${SSH_COMPROMISED_PASS:?SSH_COMPROMISED_PASS must be set}"
: "${SSH_COMPROMISED_USER:=labuser}"
: "${RUN_ID:=run_local}"

# ── LLM provider configuration ────────────────────────────────────
# Backward compat: accept OPENCODE_API_KEY if LLM_API_KEY is unset
: "${LLM_API_KEY:=${OPENCODE_API_KEY:-}}"

# Validate required vars
if [ -z "${LLM_API_KEY:-}" ]; then
    echo "ERROR: LLM_API_KEY is not set. Export it in your .env file." >&2
    exit 1
fi
if [ -z "${LLM_BASE_URL:-}" ]; then
    echo "ERROR: LLM_BASE_URL is not set. Export it in your .env file." >&2
    exit 1
fi

# Defaults
: "${PROVIDER_NAME:=openai}"
: "${LLM_MODEL:=gpt-4o}"
: "${CODER56_MODEL:=${LLM_MODEL}}"
: "${DB_ADMIN_MODEL:=${LLM_MODEL}}"
: "${SOC_GOD_MODEL:=${LLM_MODEL}}"

printf '%s:%s\n' "${SSH_COMPROMISED_USER}" "${SSH_COMPROMISED_PASS}" | chpasswd

mkdir -p /etc/sudoers.d
echo "labuser ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/labuser
chmod 440 /etc/sudoers.d/labuser
echo 'Defaults env_keep += "LLM_API_KEY OPENCODE_API_KEY"' >/etc/sudoers.d/opencode_env
chmod 440 /etc/sudoers.d/opencode_env

# ── Generate OpenCode auth.json from env ───────────────────────────
# The provider key in auth.json MUST match the provider key in opencode.json.
_auth_json() {
    if [ "${OLLAMA_ENABLED:-false}" = "true" ]; then
        cat <<EOF
{
    "${PROVIDER_NAME}": {
        "type": "api",
        "key": "${LLM_API_KEY}"
    },
    "ollama": {
        "type": "api",
        "key": "${OLLAMA_API_KEY:-ollama}"
    }
}
EOF
    else
        cat <<EOF
{
    "${PROVIDER_NAME}": {
        "type": "api",
        "key": "${LLM_API_KEY}"
    }
}
EOF
    fi
}

mkdir -p /root/.local/share/opencode
_auth_json >/root/.local/share/opencode/auth.json

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

# Ensure LLM_API_KEY is available in SSH login shells
if [ -n "${LLM_API_KEY}" ]; then
    cat >/etc/profile.d/opencode_env.sh <<EOF
export LLM_API_KEY='${LLM_API_KEY}'
export OPENCODE_API_KEY='${LLM_API_KEY}'
EOF
    chmod 644 /etc/profile.d/opencode_env.sh
fi

# Mirror OpenCode auth/config for labuser SSH sessions
install -d -m 700 -o labuser -g labuser /home/labuser/.config/opencode /home/labuser/.local /home/labuser/.local/share /home/labuser/.local/share/opencode
install -d -m 700 -o labuser -g labuser /home/labuser/.local/state
chown -R labuser:labuser /home/labuser/.local
_auth_json >/home/labuser/.local/share/opencode/auth.json
chown labuser:labuser /home/labuser/.local/share/opencode/auth.json

# ── Generate opencode.json from template ───────────────────────────
# The template uses ${VAR} placeholders. envsubst replaces them with
# the current environment values at container start.
if [ -f /root/.config/opencode/opencode.json.template ]; then
    export PROVIDER_NAME LLM_BASE_URL LLM_API_KEY LLM_MODEL CODER56_MODEL DB_ADMIN_MODEL SOC_GOD_MODEL

    # Only substitute our specific variables to avoid touching literal $ in JSON
    envsubst '${PROVIDER_NAME} ${LLM_BASE_URL} ${LLM_API_KEY} ${LLM_MODEL} ${CODER56_MODEL} ${DB_ADMIN_MODEL} ${SOC_GOD_MODEL}' \
        </root/.config/opencode/opencode.json.template \
        >/root/.config/opencode/opencode.json

    # Optionally route the benign agent through the built-in Ollama provider.
    # OpenCode auto-configures a built-in "ollama" provider from OLLAMA_BASE_URL
    # / OLLAMA_API_KEY. We simply point db_admin at it.
    #
    # Tool calling notes:
    #   * mistral-nemo needs a large num_ctx or Ollama truncates the system
    #     prompt to 4096 tokens and the agent stops following instructions.
    #     The mistral-nemo model is pre-configured with num_ctx=32768 on the
    #     host Ollama instance (see AGENTS.md).
    #   * The built-in ollama provider sends opencode's tool definitions
    #     (including bash) to Ollama's native /api/chat endpoint, so the model
    #     can call bash directly.
    if [ "${OLLAMA_ENABLED:-false}" = "true" ]; then
        python3 - <<PY
import json
import os

config_path = "/root/.config/opencode/opencode.json"
with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

ollama_model = os.getenv("OLLAMA_MODEL", "mistral-nemo")

# Route the benign db_admin agent through the built-in ollama provider.
if os.getenv("BENIGN_USE_OLLAMA", "false").lower() == "true":
    agents = cfg.setdefault("agent", {})
    db_admin = agents.setdefault("db_admin", {})
    db_admin["model"] = f"ollama/{ollama_model}"

# Override the built-in ollama provider to route through the local
# ollama_proxy.py (127.0.0.1:11435). The proxy injects bash/edit/write
# tool definitions (which @ai-sdk/openai-compatible does not send to a
# custom baseURL by default) and sets num_ctx=32768 so Ollama does not
# truncate the ~6k-token db_admin system prompt to the 4096 default.
providers = cfg.setdefault("provider", {})
ollama_provider = providers.setdefault("ollama", {})
# Force the OpenAI-compatible adapter (chat/completions) instead of the
# built-in @ai-sdk/ollama native adapter (api/chat). This lets us route
# through ollama_proxy.py which injects bash/edit/write tool definitions.
ollama_provider["npm"] = "@ai-sdk/openai-compatible"
ollama_provider["name"] = "Ollama Local"
_proxy_port = os.getenv("OLLAMA_PROXY_PORT", "11434")
ollama_provider.setdefault("options", {}).setdefault(
    "baseURL", f"http://127.0.0.1:{_proxy_port}/v1"
)
ollama_provider.setdefault("options", {}).setdefault(
    "apiKey", os.getenv("OLLAMA_API_KEY", "ollama")
)
ollama_models = ollama_provider.setdefault("models", {})
model_cfg = ollama_models.setdefault(ollama_model, {})
model_cfg.setdefault("name", ollama_model)
model_cfg.setdefault("limit", {}).setdefault("context", 128000)
model_cfg["limit"].setdefault("output", 16384)

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
PY
    fi

    install -m 600 -o labuser -g labuser /root/.config/opencode/opencode.json /home/labuser/.config/opencode/opencode.json
fi

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

# Ensure the compromised host routes traffic through the router
ip route replace blackhole 172.30.0.254/32 || true
ip route replace blackhole 172.31.0.254/32 || true
ip route replace 172.31.0.0/24 via 172.30.0.1 || true
ip route replace default via 172.30.0.1 dev eth0 || true

# Enable bash history for labuser to track commands
echo 'HISTFILE=/home/labuser/.bash_history' >> /home/labuser/.bashrc
echo 'HISTSIZE=10000' >> /home/labuser/.bashrc
echo 'HISTFILESIZE=10000' >> /home/labuser/.bashrc
echo 'shopt -s histappend' >> /home/labuser/.bashrc
echo 'PROMPT_COMMAND="history -a"' >> /home/labuser/.bashrc
touch /home/labuser/.bash_history
chown labuser:labuser /home/labuser/.bash_history
chmod 600 /home/labuser/.bash_history

# Reduce synthetic SSH friction for autonomous experiments.
cat >/home/labuser/.ssh/config <<'EOF'
Host *
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
EOF
chown labuser:labuser /home/labuser/.ssh/config
chmod 600 /home/labuser/.ssh/config

# Start SSH server in background
/usr/sbin/sshd

# Re-assert default route in case container networking reset it.
ip route replace default via 172.30.0.1 dev eth0 || true

# ── Start Ollama native-API proxy (when enabled) ───────────────────
# ollama_proxy.py listens on 127.0.0.1:11435 and translates OpenCode's
# OpenAI-compatible /v1/chat/completions requests into Ollama's native
# /api/chat format. It injects bash/edit/write tool definitions (which
# @ai-sdk/openai-compatible does not send to a custom baseURL by default)
# and sets num_ctx=32768 so Ollama does not truncate the system prompt.
if [ "${OLLAMA_ENABLED:-false}" = "true" ]; then
    # Parse OLLAMA_BASE_URL (e.g. http://host.docker.internal:11434/v1)
    # into host/port for the proxy's native target. Resolve the hostname
    # to an IP NOW, before we repoint host.docker.internal at 127.0.0.1
    # (otherwise the proxy would connect to itself).
    _obu="${OLLAMA_BASE_URL:-http://host.docker.internal:11434/v1}"
    _obu="${_obu#http://}"; _obu="${_obu#https://}"
    _obu="${_obu%%/*}"            # strip path -> host[:port]
    _proxy_host="${_obu%%:*}"
    _proxy_port="${_obu##*:}"
    [ "${_proxy_host}" = "${_proxy_port}" ] && _proxy_port="11434"
    [ -z "${_proxy_port}" ] && _proxy_port="11434"
    # Resolve to IP so the proxy isn't affected by the /etc/hosts change
    _resolved_ip=$(getent hosts "${_proxy_host}" | awk '{print $1}' | head -1)
    [ -n "${_resolved_ip}" ] && _proxy_host="${_resolved_ip}"

    export OLLAMA_PROXY_TARGET_HOST="${_proxy_host}"
    export OLLAMA_PROXY_TARGET_PORT="${_proxy_port}"
    # Run the proxy on Ollama's standard port (11434) so OpenCode's
    # built-in ollama provider (which connects to host.docker.internal:11434)
    # hits the proxy. The proxy forwards to the real Ollama.
    export OLLAMA_PROXY_PORT="11434"
    export OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-32768}"

    proxy_log="/var/log/ollama_proxy.log"
    touch "${proxy_log}"
    echo "Starting Ollama proxy on 127.0.0.1:${OLLAMA_PROXY_PORT} -> ${_proxy_host}:${_proxy_port}..."
    python3 /opt/ollama_proxy.py >>"${proxy_log}" 2>&1 &
    PROXY_PID=$!

    _waits=0
    until curl -sf "http://127.0.0.1:${OLLAMA_PROXY_PORT}/health" >/dev/null 2>&1; do
        _waits=$((_waits + 1))
        if [ "${_waits}" -gt 30 ]; then
            echo "⚠ Ollama proxy did not become healthy in 30s; continuing anyway" >&2
            break
        fi
        sleep 1
    done
    if [ "${_waits}" -le 30 ]; then
        echo "✅ Ollama proxy ready (PID ${PROXY_PID})"
    fi

    # Transparent intercept: repoint host.docker.internal at 127.0.0.1 so
    # OpenCode's built-in ollama provider (which hardcodes
    # host.docker.internal:11434 and ignores OLLAMA_BASE_URL / config
    # baseURL overrides) connects to the proxy. The proxy forwards to the
    # real Ollama via OLLAMA_PROXY_TARGET_HOST/PORT (the original IP).
    # Use Python (truncate+write) because `sed -i` cannot rename the
    # Docker bind-mounted /etc/hosts.
    _real_ip="${_proxy_host}"
    python3 - <<'PYEOF' || true
hosts = open("/etc/hosts").readlines()
out = []
for line in hosts:
    if "host.docker.internal" in line:
        out.append("127.0.0.1 host.docker.internal\n")
    elif "host-internal" in line:
        out.append("127.0.0.1 host-internal\n")
    else:
        out.append(line)
open("/etc/hosts", "w").write("".join(out))
PYEOF
    echo "  Repointed host.docker.internal -> 127.0.0.1 (real Ollama at ${_real_ip}:${_proxy_port})"
    export OLLAMA_BASE_URL="http://127.0.0.1:${OLLAMA_PROXY_PORT}/v1"
    export OLLAMA_HOST="http://127.0.0.1:${OLLAMA_PROXY_PORT}"
fi

# Start OpenCode HTTP server for remote API access (used by auto_responder)
opencode_log="/var/log/opencode-serve.log"
touch "${opencode_log}"
echo "Starting OpenCode HTTP server on 0.0.0.0:4096..."
echo "  Provider: ${PROVIDER_NAME}"
echo "  Base URL: ${LLM_BASE_URL}"
echo "  Default model: ${LLM_MODEL}"
echo "  coder56 model: ${CODER56_MODEL}"
echo "  db_admin model: ${DB_ADMIN_MODEL}"
echo "  soc_god model: ${SOC_GOD_MODEL}"
if [ "${OLLAMA_ENABLED:-false}" = "true" ]; then
    echo "  Ollama enabled: model=${OLLAMA_MODEL:-mistral-nemo} benign_use_ollama=${BENIGN_USE_OLLAMA:-false} num_ctx=${OLLAMA_NUM_CTX:-32768}"
fi
cd /tmp && opencode serve --hostname 0.0.0.0 --port 4096 >>"${opencode_log}" 2>&1 &
OPENCODE_PID=$!
echo "✅ OpenCode serve started (PID ${OPENCODE_PID})"

# Keep container running
exec tail -f /dev/null
