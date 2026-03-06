#!/usr/bin/env python3
"""
Analyze Flask login attempt logs from brute force experiments.
This script processes flask_login_attempts.jsonl files from brute force experiment outputs.

Usage:
    python3 analyze_brute_force_logs.py <path_to_flask_login_attempts.jsonl>
    python3 analyze_brute_force_logs.py --all  # Analyze all experiments in /home/diego/Trident/outputs
"""

import json
import sys
import os
import glob
from pathlib import Path
from datetime import datetime
from collections import Counter

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
        return None

    total = len(attempts)
    successful = sum(1 for a in attempts if a.get('success', False))
    failed = total - successful

    result = {
        'log_file': str(log_file),
        'total_attempts': total,
        'successful_attempts': successful,
        'failed_attempts': failed
    }

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

                # Calculate attempts per second
                if duration > 0:
                    attempts_per_sec = total / duration
                    print(f"Rate: {attempts_per_sec:.2f} attempts/second")
            except Exception as e:
                print(f"Error calculating duration: {e}")

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

    # Password length distribution
    password_lengths = Counter(a.get('password_len', 0) for a in attempts)
    print()
    print("Password length distribution:")
    for length, count in sorted(password_lengths.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  - Length {length}: {count} attempts")

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

    return result


def analyze_all_experiments():
    """Analyze all brute force experiments in the outputs directory"""
    outputs_dir = "/home/diego/Trident/creative_monitored"
    pattern = os.path.join(outputs_dir, "flask_brute_*_run_*")

    run_dirs = sorted(glob.glob(pattern))

    if not run_dirs:
        print(f"No brute force experiment directories found in {outputs_dir}")
        return

    print(f"Found {len(run_dirs)} brute force experiment directories")
    print()

    all_results = []

    for run_dir in run_dirs:
        run_name = os.path.basename(run_dir)
        login_log = os.path.join(run_dir, "logs", "flask_login_attempts.jsonl")

        if not os.path.exists(login_log):
            login_log = os.path.join(run_dir, "flask_login_attempts.jsonl")

        if os.path.exists(login_log):
            print(f"\nAnalyzing {run_name}...")
            result = analyze_flask_logs(login_log)
            if result:
                result['run_name'] = run_name
                all_results.append(result)
        else:
            print(f"Warning: No login attempts log found for {run_name}")

    # Generate summary
    if all_results:
        print("\n" + "=" * 80)
        print("SUMMARY ACROSS ALL RUNS")
        print("=" * 80)

        total_attempts = sum(r['total_attempts'] for r in all_results)
        total_successful = sum(r['successful_attempts'] for r in all_results)

        print(f"Total runs analyzed: {len(all_results)}")
        print(f"Total login attempts across all runs: {total_attempts}")
        print(f"Total successful attempts: {total_successful}")
        print(f"Success rate: {(100 * total_successful / total_attempts) if total_attempts > 0 else 0:.2f}%")

        print("\nPer-run breakdown:")
        print(f"{'Run':<40} {'Attempts':>12} {'Successful':>12}")
        print("-" * 66)
        for result in all_results:
            print(f"{result['run_name']:<40} {result['total_attempts']:>12} {result['successful_attempts']:>12}")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 analyze_brute_force_logs.py <path_to_flask_login_attempts.jsonl>")
        print("  python3 analyze_brute_force_logs.py --all")
        sys.exit(1)

    if sys.argv[1] == '--all':
        analyze_all_experiments()
    else:
        log_file = Path(sys.argv[1])
        if not log_file.exists():
            print(f"Error: Log file not found: {log_file}")
            sys.exit(1)

        analyze_flask_logs(log_file)


if __name__ == "__main__":
    main()
