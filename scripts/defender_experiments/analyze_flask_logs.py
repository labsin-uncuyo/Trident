#!/usr/bin/env python3
"""
Analyze Flask login attempt logs from experiments.
Usage: python3 analyze_flask_logs.py <path_to_flask_login_attempts.jsonl>
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def analyze_flask_logs(log_file):
    """Analyze Flask login attempt logs"""
    attempts = []

    with open(log_file, 'r') as f:
        for line in f:
            try:
                attempts.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

    if not attempts:
        print("No valid login attempts found in log file")
        return

    total = len(attempts)
    successful = sum(1 for a in attempts if a.get('success', False))
    failed = total - successful

    print("=" * 60)
    print("FLASK LOGIN ATTEMPTS ANALYSIS")
    print("=" * 60)
    print(f"Log file: {log_file}")
    print(f"Total attempts: {total}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print()

    # Time range
    if total > 0:
        first_time = attempts[0].get('timestamp', 'unknown')
        last_time = attempts[-1].get('timestamp', 'unknown')
        print(f"First attempt: {first_time}")
        print(f"Last attempt: {last_time}")

        if first_time != 'unknown' and last_time != 'unknown':
            try:
                first_dt = datetime.fromisoformat(first_time.replace('Z', '+00:00'))
                last_dt = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
                duration = (last_dt - first_dt).total_seconds()
                print(f"Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
            except:
                pass

    print()

    # Unique IP addresses
    ips = set(a.get('remote_addr') for a in attempts if a.get('remote_addr') != 'unknown')
    print(f"Unique source IPs: {len(ips)}")
    for ip in sorted(ips):
        ip_count = sum(1 for a in attempts if a.get('remote_addr') == ip)
        print(f"  - {ip}: {ip_count} attempts")

    print()

    # Usernames tried
    usernames = {}
    for a in attempts:
        username = a.get('username', 'unknown')
        usernames[username] = usernames.get(username, 0) + 1

    print(f"Unique usernames: {len(usernames)}")
    for username, count in sorted(usernames.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {username}: {count} attempts")

    print()

    # Successful attempts
    if successful > 0:
        print("SUCCESSFUL ATTEMPTS:")
        for i, a in enumerate(attempts, 1):
            if a.get('success', False):
                print(f"  {i}. {a.get('timestamp')} - {a.get('username')} from {a.get('remote_addr')}")
    else:
        print("No successful attempts detected")

    print()
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_flask_logs.py <path_to_flask_login_attempts.jsonl>")
        sys.exit(1)

    log_file = Path(sys.argv[1])
    if not log_file.exists():
        print(f"Error: Log file not found: {log_file}")
        sys.exit(1)

    analyze_flask_logs(log_file)
