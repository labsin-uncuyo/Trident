#!/usr/bin/env bash
set -euo pipefail

MAX_RETRIES=60
SLEEP=5
DEFENDER_PORT_VALUE="${DEFENDER_PORT:-}"

if [ -z "$DEFENDER_PORT_VALUE" ]; then
    for env_file in ".env" ".env.example"; do
        if [ -f "$env_file" ]; then
            val=$(grep -E '^DEFENDER_PORT=' "$env_file" | tail -n1 | cut -d'=' -f2)
            if [ -n "$val" ]; then
                DEFENDER_PORT_VALUE="$val"
                break
            fi
        fi
    done
fi

DEFENDER_PORT_VALUE="${DEFENDER_PORT_VALUE:-8000}"

echo "[wait] Checking lab readiness..."

for i in $(seq 1 "$MAX_RETRIES"); do
    echo "[wait] Attempt $i/$MAX_RETRIES"

    if ! docker inspect -f '{{.State.Health.Status}}' lab_server 2>/dev/null | grep -q healthy; then
        echo "[wait] lab_server not healthy yet"
        sleep "$SLEEP"
        continue
    fi

    HTTP_CODE=$(docker exec lab_compromised bash -lc "curl -s -o /dev/null -w '%{http_code}' http://172.31.0.10:80" || echo "000")
    if [ "$HTTP_CODE" != "200" ]; then
        echo "[wait] HTTP 200 not ready (got $HTTP_CODE)"
        sleep "$SLEEP"
        continue
    fi

    if ! curl -sf "http://localhost:${DEFENDER_PORT_VALUE}/health" >/dev/null; then
        echo "[wait] SLIPS API not healthy yet"
        sleep "$SLEEP"
        continue
    fi

    echo "[wait] LAB IS READY ✔"
    exit 0
done

echo "[wait] Lab did NOT become ready in time ❌"
exit 1
