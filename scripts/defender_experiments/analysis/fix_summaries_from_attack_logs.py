#!/usr/bin/env python3
"""
Fix Flask brute force experiment summaries by parsing actual attack logs.
This script corrects login attempt counts and password_found status by reading
the actual flask_attack.log files and updating the summary JSON files.

Usage:
    python3 fix_summaries_from_attack_logs.py
"""

import os
import json
import re
import glob
from pathlib import Path

# Configuration
EXPERIMENT_DIR = "/home/diego/Trident/brute_force_outputs"


def parse_attack_log(log_file):
    """Parse flask_attack.log to get actual attempt count and password found status"""
    if not os.path.exists(log_file):
        return None, None

    attempts = 0
    password_found = False

    try:
        with open(log_file, 'r') as f:
            content = f.read()

            # Count attempts - look for "Attempt N/3000:" pattern
            attempt_matches = re.findall(r'Attempt \d+/3000:', content)
            attempts = len(attempt_matches)

            # Check if password was found
            password_found = 'Password found' in content or 'SUCCESS: Password found' in content

    except Exception as e:
        print(f"  Error parsing {log_file}: {e}")
        return None, None

    return attempts, password_found


def update_summary(summary_file, actual_attempts, password_found):
    """Update summary file with corrected data"""
    try:
        with open(summary_file, 'r') as f:
            summary = json.load(f)

        # Update metrics
        if 'metrics' not in summary:
            summary['metrics'] = {}

        old_attempts = summary['metrics'].get('flask_login_attempts', 0)
        old_password_found = summary['metrics'].get('password_found', False)
        old_successful = summary['metrics'].get('flask_successful_attempts', 0)

        # Update with actual values
        summary['metrics']['flask_login_attempts'] = actual_attempts
        summary['metrics']['password_found'] = password_found

        # Update successful attempts based on password_found
        if password_found:
            summary['metrics']['flask_successful_attempts'] = 1
        else:
            summary['metrics']['flask_successful_attempts'] = 0

        # Write back
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=4)

        return old_attempts, old_password_found, old_successful

    except Exception as e:
        print(f"  Error updating {summary_file}: {e}")
        return None, None, None


def main():
    print("=" * 80)
    print("Fixing Flask Brute Force Summaries from Attack Logs")
    print("=" * 80)
    print()

    # Find all run directories
    pattern = os.path.join(EXPERIMENT_DIR, "flask_brute_*_run_*")
    run_dirs = sorted(glob.glob(pattern))

    print(f"Found {len(run_dirs)} run directories")
    print()

    stats = {
        'total_processed': 0,
        'log_not_found': 0,
        'summary_not_found': 0,
        'attempts_corrected': 0,
        'password_status_corrected': 0,
        'both_corrected': 0,
        'no_change_needed': 0
    }

    for run_dir in run_dirs:
        run_name = os.path.basename(run_dir)
        print(f"Processing {run_name}...")

        # Paths
        attack_log = os.path.join(run_dir, "logs", "flask_attack.log")
        summary_file = os.path.join(run_dir, "flask_brute_experiment_summary.json")

        # Check if files exist
        if not os.path.exists(attack_log):
            print(f"  ⚠ Attack log not found: {attack_log}")
            stats['log_not_found'] += 1
            continue

        if not os.path.exists(summary_file):
            print(f"  ⚠ Summary file not found: {summary_file}")
            stats['summary_not_found'] += 1
            continue

        # Parse attack log
        actual_attempts, password_found = parse_attack_log(attack_log)

        if actual_attempts is None:
            print(f"  ✗ Failed to parse attack log")
            continue

        print(f"  Actual attempts: {actual_attempts}, Password found: {password_found}")

        # Read current summary to compare
        with open(summary_file, 'r') as f:
            summary = json.load(f)

        current_attempts = summary['metrics'].get('flask_login_attempts', 0)
        current_password_found = summary['metrics'].get('password_found', False)

        # Check if update is needed
        attempts_changed = current_attempts != actual_attempts
        password_changed = current_password_found != password_found

        if not attempts_changed and not password_changed:
            print(f"  ✓ Already correct (attempts={current_attempts}, password_found={current_password_found})")
            stats['no_change_needed'] += 1
            stats['total_processed'] += 1
            continue

        # Update summary
        old_attempts, old_password_found, old_successful = update_summary(
            summary_file, actual_attempts, password_found
        )

        # Track changes
        if attempts_changed and password_changed:
            print(f"  ✓ UPDATED: attempts {old_attempts} → {actual_attempts}, password_found {old_password_found} → {password_found}")
            stats['both_corrected'] += 1
        elif attempts_changed:
            print(f"  ✓ UPDATED: attempts {old_attempts} → {actual_attempts}")
            stats['attempts_corrected'] += 1
        elif password_changed:
            print(f"  ✓ UPDATED: password_found {old_password_found} → {password_found}")
            stats['password_status_corrected'] += 1

        stats['total_processed'] += 1
        print()

    # Print summary
    print("=" * 80)
    print("Summary of Changes")
    print("=" * 80)
    print(f"Total runs processed: {stats['total_processed']}")
    print(f"Runs with no changes needed: {stats['no_change_needed']}")
    print(f"Runs with attempt counts corrected: {stats['attempts_corrected']}")
    print(f"Runs with password status corrected: {stats['password_status_corrected']}")
    print(f"Runs with both corrected: {stats['both_corrected']}")
    print(f"Runs with missing attack log: {stats['log_not_found']}")
    print(f"Runs with missing summary: {stats['summary_not_found']}")
    print()


if __name__ == "__main__":
    main()
