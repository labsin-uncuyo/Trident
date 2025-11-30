#!/bin/bash
set -euo pipefail

usage() {
    cat <<USAGE
Usage: $0 <command> [args]
Commands:
  block_ip <IP>    Block traffic from the source IP
  unblock_ip <IP>  Remove block rule for the IP
  rotate_pcaps     Force logrotate for pcaps
USAGE
}

command=${1:-}
case "$command" in
    block_ip)
        ip=${2:-}
        [ -n "$ip" ] || { echo "IP required" >&2; exit 1; }
        if ! iptables -C FORWARD -s "$ip" -j DROP 2>/dev/null; then
            iptables -I FORWARD -s "$ip" -j DROP
        fi
        ;;
    unblock_ip)
        ip=${2:-}
        [ -n "$ip" ] || { echo "IP required" >&2; exit 1; }
        while iptables -C FORWARD -s "$ip" -j DROP 2>/dev/null; do
            iptables -D FORWARD -s "$ip" -j DROP
        done
        ;;
    rotate_pcaps)
        logrotate -f /etc/logrotate.d/pcap
        ;;
    *)
        usage
        exit 1
        ;;
esac
