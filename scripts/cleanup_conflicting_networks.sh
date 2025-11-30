#!/usr/bin/env bash
set -euo pipefail

TARGET_SUBNETS=("172.30.0.0/24" "172.31.0.0/24")
KEEP=("lab_net_a" "lab_net_b")

in_keep() {
    local name=$1
    for keep in "${KEEP[@]}"; do
        if [[ "$keep" == "$name" ]]; then
            return 0
        fi
    done
    return 1
}

uses_target_subnet() {
    local net=$1
    local inspect_output
    inspect_output=$(docker network inspect "$net" --format '{{range .IPAM.Config}}{{println .Subnet}}{{end}}' 2>/dev/null || true)
    if [[ -z "$inspect_output" ]]; then
        return 1
    fi
    while IFS= read -r subnet; do
        for target in "${TARGET_SUBNETS[@]}"; do
            if [[ "$subnet" == "$target" ]]; then
                return 0
            fi
        done
    done <<< "$inspect_output"
    return 1
}

main() {
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        if in_keep "$name"; then
            continue
        fi
        if uses_target_subnet "$name"; then
            docker network rm "$name" >/dev/null 2>&1 && echo "Removed conflicting network: $name" || true
        fi
    done < <(docker network ls --format '{{.Name}}')
}

main "$@"
