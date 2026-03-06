#!/usr/bin/env python3
"""
Test script to analyze a single run with the new API message parsing
"""

import os
import sys
import json
import re
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from generate_brute_force_analysis import BruteForceAnalyzer

# Configuration
TEST_RUN = "/home/diego/Trident/brute_force_outputs/flask_brute_1771529218_run_12"
LLM_API_URL = "https://llm.ai.e-infra.cz/v1"
LLM_MODEL = "gpt-oss-120b"

# Load .env file
def load_env():
    trident_env = os.path.join("/home/diego/Trident", ".env")
    if os.path.exists(trident_env):
        with open(trident_env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

load_env()

def main():
    print("=" * 80)
    print(f"Testing Single Run Analysis: {TEST_RUN}")
    print("=" * 80)
    print()

    # Initialize analyzer
    analyzer = BruteForceAnalyzer(TEST_RUN)

    # Parse the single run
    run_num = analyzer._extract_run_number(TEST_RUN)
    summary_file = os.path.join(TEST_RUN, "flask_brute_experiment_summary.json")

    if not os.path.exists(summary_file):
        print(f"Error: Summary file not found: {summary_file}")
        return

    print("Parsing run data...")
    run_data = analyzer._parse_run(summary_file, None, TEST_RUN, run_num)

    if not run_data:
        print("Error: Failed to parse run")
        return

    print(f"✓ Run parsed successfully")
    print(f"  Run directory: {run_data['run_dir']}")
    print(f"  Login attempts: {run_data['login_attempts']}")
    print(f"  Server commands: {len(run_data['server_commands'])}")
    print(f"  Compromised commands: {len(run_data['compromised_commands'])}")
    print()

    # Show sample commands with outputs
    print("Sample server commands (first 3):")
    for i, cmd in enumerate(run_data['server_commands'][:3], 1):
        print(f"\n{i}. {cmd['command']}")
        if 'description' in cmd:
            print(f"   Description: {cmd['description']}")
        if 'output' in cmd and cmd['output']:
            output_preview = cmd['output'][:150] + "..." if len(cmd['output']) > 150 else cmd['output']
            print(f"   Output: {output_preview}")

    print("\n" + "=" * 80)
    print("Sample compromised commands (first 3):")
    for i, cmd in enumerate(run_data['compromised_commands'][:3], 1):
        print(f"\n{i}. {cmd['command']}")
        if 'description' in cmd:
            print(f"   Description: {cmd['description']}")
        if 'output' in cmd and cmd['output']:
            output_preview = cmd['output'][:150] + "..." if len(cmd['output']) > 150 else cmd['output']
            print(f"   Output: {output_preview}")

    print("\n" + "=" * 80)
    print("✓ Test completed successfully!")
    print()

    # Check if outputs are present
    has_outputs = any('output' in cmd and cmd['output'] for cmd in run_data['server_commands'] + run_data['compromised_commands'])
    print(f"Commands with outputs: {'YES' if has_outputs else 'NO'}")


if __name__ == "__main__":
    main()
