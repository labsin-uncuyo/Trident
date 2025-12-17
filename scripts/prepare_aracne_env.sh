#!/usr/bin/env bash
set -euo pipefail

# Populate configs/aracne_lab/.env with sane lab defaults (or honor existing one with keys).
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARACNE_ENV="${ROOT_DIR}/configs/aracne_lab/.env"

if [ -f "$ARACNE_ENV" ]; then
  echo "[prepare_aracne_env] Found existing ${ARACNE_ENV}; leaving it unchanged."
  exit 0
fi

mkdir -p "$(dirname "$ARACNE_ENV")"

cat >"$ARACNE_ENV" <<EOF
OPENAI_API_KEY=${OPENAI_API_KEY:-}
OPENAI_BASE_URL=${OPENAI_BASE_URL:-}
CESNET_API_KEY=${CESNET_API_KEY:-}
CESNET_BASE_URL=${CESNET_BASE_URL:-}

PLANNER_SOURCE=${PLANNER_SOURCE:-cesnet}
PLANNER_MODEL=${PLANNER_MODEL:-gpt-oss-120b}
SUMMARIZER_SOURCE=${SUMMARIZER_SOURCE:-cesnet}
SUMMARIZER_MODEL=${SUMMARIZER_MODEL:-deepseek-r1}
INTERPRETER_SOURCE=${INTERPRETER_SOURCE:-cesnet}
INTERPRETER_MODEL=${INTERPRETER_MODEL:-qwen3-coder}
ACTION_LIMIT=${ACTION_LIMIT:-50}

SSH_HOST=${SSH_HOST:-127.0.0.1}
SSH_PORT=${SSH_PORT:-2223}
SSH_USER=${SSH_USER:-labuser}
SSH_KEY_PATH=${SSH_KEY_PATH:-}
SSH_PASSWORD=${SSH_PASSWORD:-adminadmin}

OLLAMA_HOST=${OLLAMA_HOST:-}
OLLAMA_PORT=${OLLAMA_PORT:-}
EOF

echo "[prepare_aracne_env] Wrote ${ARACNE_ENV}"
