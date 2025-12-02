#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARACNE_ROOT="${LAB_ROOT}/../aracne"
ENV_SOURCE="${ARACNE_ROOT}/env_EXAMPLE"
ENV_TARGET="${ARACNE_ROOT}/agent/.env"

if [ ! -d "${ARACNE_ROOT}" ]; then
    echo "❌ ARACNE repository not found at ${ARACNE_ROOT}. Clone it as a sibling to Trident."
    exit 1
fi

if [ ! -f "${ENV_SOURCE}" ]; then
    echo "❌ env_EXAMPLE missing at ${ENV_SOURCE}. Please restore it."
    exit 1
fi

if [ -f "${ENV_TARGET}" ]; then
    echo "✅ ARACNE .env already present at ${ENV_TARGET}"
else
    cp "${ENV_SOURCE}" "${ENV_TARGET}"
    echo "✨ Created ${ENV_TARGET} from env_EXAMPLE."
    echo "👉 Update SSH/LLM values inside ${ENV_TARGET} as needed (API keys are still required)."
fi
