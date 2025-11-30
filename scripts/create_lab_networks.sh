#!/usr/bin/env bash
set -euo pipefail

create_network() {
    local name=$1
    local subnet=$2
    local gateway=$3
    docker network create --subnet="$subnet" --gateway="$gateway" "$name" >/dev/null 2>&1 || true
}

main() {
    create_network lab_net_a 172.30.0.0/24 172.30.0.254
    create_network lab_net_b 172.31.0.0/24 172.31.0.254
}

main "$@"
