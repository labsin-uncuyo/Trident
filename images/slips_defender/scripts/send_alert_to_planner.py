#!/usr/bin/env python3
"""
Send a Slips alert to the Planner API for incident response planning.

Usage:
    python send_alert_to_planner.py --alert "ALERT_TEXT"
    python send_alert_to_planner.py --file alerts.log
    python send_alert_to_planner.py --latest-alert
    python send_alert_to_planner.py --interactive
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional
import requests
from datetime import datetime


# Configuration
PLANNER_API_URL = os.getenv("PLANNER_API_URL", "http://localhost:8000")
PLAN_ENDPOINT = f"{PLANNER_API_URL}/plan"
DEFAULT_ALERTS_DIR = Path("/outputs")


def send_alert_to_planner(alert: str) -> dict:
    """
    Send an alert to the planner API and return the response.

    Args:
        alert: The alert text to send

    Returns:
        dict: The JSON response from the planner API
    """
    payload = {"alert": alert}

    try:
        response = requests.post(
            PLAN_ENDPOINT,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Error sending alert to planner: {e}", file=sys.stderr)
        sys.exit(1)


def find_latest_alerts_file(run_id: Optional[str] = None) -> Optional[Path]:
    """
    Find the latest alerts.log file.

    Args:
        run_id: Specific run ID to look for (optional)

    Returns:
        Path to the latest alerts.log file, or None if not found
    """
    if run_id:
        search_dir = DEFAULT_ALERTS_DIR / run_id
    else:
        search_dir = DEFAULT_ALERTS_DIR

    if not search_dir.exists():
        return None

    # Find all alerts.log files
    alerts_files = list(search_dir.rglob("alerts.log"))

    if not alerts_files:
        return None

    # Sort by modification time, newest first
    alerts_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return alerts_files[0]


def get_latest_alert_from_file(alerts_file: Path) -> Optional[str]:
    """
    Extract the latest alert from an alerts.log file.

    Args:
        alerts_file: Path to the alerts.log file

    Returns:
        The latest alert text, or None if no alerts found
    """
    try:
        with open(alerts_file, 'r') as f:
            lines = f.readlines()

        # Filter out heartbeat lines and empty lines
        alerts = []
        for line in lines:
            line = line.strip()
            if line and '"note":"heartbeat"' not in line:
                # Skip JSON heartbeat lines
                try:
                    json.loads(line)
                    continue  # Skip JSON lines
                except json.JSONDecodeError:
                    pass  # Not JSON, keep it

                if "Detected" in line or "threat level:" in line:
                    alerts.append(line)

        if not alerts:
            return None

        # Return the most recent alert (last in file)
        return alerts[-1]

    except Exception as e:
        print(f"Error reading alerts file: {e}", file=sys.stderr)
        return None


def print_planner_response(response: dict):
    """Pretty print the planner API response."""
    print("\n" + "=" * 80)
    print("PLANNER API RESPONSE")
    print("=" * 80)
    print()

    if "plans" in response and response["plans"]:
        plan = response["plans"][0]

        print(f"Model: {response.get('model', 'N/A')}")
        print(f"Request ID: {response.get('request_id', 'N/A')}")
        print(f"Created: {response.get('created', 'N/A')}")
        print()
        print("=" * 80)
        print(f"EXECUTOR HOST IP: {plan.get('executor_host_ip', 'N/A')}")
        print("=" * 80)
        print()
        print(plan.get('plan', 'No plan generated'))
        print()
    else:
        print("No plans in response")
        print(json.dumps(response, indent=2))

    print("=" * 80)


def interactive_mode():
    """Run in interactive mode to compose an alert."""
    print("=" * 80)
    print("INTERACTIVE ALERT COMPOSER")
    print("=" * 80)
    print()
    print("Enter your alert text (press Ctrl+D or type 'END' on a new line to finish):")
    print()

    lines = []
    try:
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
    except EOFError:
        pass

    alert = "\n".join(lines).strip()

    if not alert:
        print("No alert text provided.", file=sys.stderr)
        sys.exit(1)

    print()
    print("=" * 80)
    print("ALERT TO SEND:")
    print("=" * 80)
    print(alert)
    print("=" * 80)
    print()

    confirm = input("Send this alert to planner? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        sys.exit(0)

    return alert


def main():
    parser = argparse.ArgumentParser(
        description="Send Slips alerts to the Planner API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send a custom alert
  python send_alert_to_planner.py --alert "Src IP 192.168.1.1. Detected port scan"

  # Use the latest alert from alerts.log
  python send_alert_to_planner.py --latest-alert

  # Use alerts from a specific file
  python send_alert_to_planner.py --file /path/to/alerts.log

  # Interactive mode
  python send_alert_to_planner.py --interactive

  # Use latest alert from specific run
  python send_alert_to_planner.py --latest-alert --run-id logs_20260120_230023
        """
    )

    parser.add_argument(
        "--alert", "-a",
        help="Alert text to send"
    )

    parser.add_argument(
        "--file", "-f",
        type=Path,
        help="Path to alerts.log file (uses latest alert from file)"
    )

    parser.add_argument(
        "--latest-alert", "-l",
        action="store_true",
        help="Get the latest alert from the most recent alerts.log file"
    )

    parser.add_argument(
        "--run-id", "-r",
        help="Specific run ID to use (for --latest-alert)"
    )

    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Interactive mode to compose alert"
    )

    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only print the plan, not the metadata"
    )

    args = parser.parse_args()

    # Determine the alert to send
    alert = None

    if args.interactive:
        alert = interactive_mode()

    elif args.file:
        alert = get_latest_alert_from_file(args.file)
        if not alert:
            print(f"No alerts found in {args.file}", file=sys.stderr)
            sys.exit(1)

    elif args.latest_alert:
        alerts_file = find_latest_alerts_file(args.run_id)
        if not alerts_file:
            print("No alerts.log files found", file=sys.stderr)
            sys.exit(1)

        print(f"Using alerts from: {alerts_file}", file=sys.stderr)
        alert = get_latest_alert_from_file(alerts_file)
        if not alert:
            print(f"No alerts found in {alerts_file}", file=sys.stderr)
            sys.exit(1)

    elif args.alert:
        alert = args.alert

    else:
        parser.print_help()
        sys.exit(1)

    # Send alert to planner
    print(f"Sending alert to planner at {PLAN_ENDPOINT}...", file=sys.stderr)
    response = send_alert_to_planner(alert)

    # Print response
    if args.quiet:
        if "plans" in response and response["plans"]:
            print(response["plans"][0].get('plan', ''))
    else:
        print_planner_response(response)


if __name__ == "__main__":
    main()
