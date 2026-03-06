#!/usr/bin/env python3
"""
Test script to verify the new format with all parts (step-start, text, tool, step-finish)
"""

import os
import sys
import json
import requests
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import from the main script
import importlib.util
spec = importlib.util.spec_from_file_location("generate_brute_force_analysis",
    "/home/diego/Trident/scripts/defender_experiments/analysis/generate_brute_force_analysis.py")
gfa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gfa)

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
    print(f"Testing Full Format: {TEST_RUN}")
    print("=" * 80)
    print()

    # Initialize analyzer
    analyzer = gfa.BruteForceAnalyzer(TEST_RUN)

    # Parse the single run
    run_num = analyzer._extract_run_number(TEST_RUN)
    summary_file = os.path.join(TEST_RUN, "flask_brute_experiment_summary.json")

    print("Parsing run data...")
    run_data = analyzer._parse_run(summary_file, None, TEST_RUN, run_num)

    if not run_data:
        print("Error: Failed to parse run")
        return

    print(f"✓ Run parsed successfully")
    print(f"  Run directory: {run_data['run_dir']}")
    print(f"  Login attempts: {run_data['login_attempts']}")
    print(f"  Server parts: {len(run_data['server_parts'])}")
    print(f"  Compromised parts: {len(run_data['compromised_parts'])}")
    print()

    # Count part types
    from collections import Counter
    server_types = Counter(p['type'] for p in run_data['server_parts'])
    compromised_types = Counter(p['type'] for p in run_data['compromised_parts'])

    print("Server part types:", dict(server_types))
    print("Compromised part types:", dict(compromised_types))
    print()

    # Format for LLM
    print("=" * 80)
    print("SAMPLE OUTPUT THAT WILL BE SENT TO LLM (first 100 lines):")
    print("=" * 80)

    formatted = analyzer._format_parts_for_llm(run_data['server_parts'][:3], run_data['compromised_parts'][:3])
    lines = formatted.split('\n')
    for i, line in enumerate(lines[:100], 1):
        print(f"{i:3}: {line}")

    if len(lines) > 100:
        print(f"\n... ({len(lines) - 100} more lines)")

    print()
    print("=" * 80)
    print("✓ Test completed successfully!")
    print()

    # Check if we have all part types
    has_all_types = all(t in server_types + compromised_types for t in ['step-start', 'text', 'tool', 'step-finish'])
    print(f"Has all part types: {'YES' if has_all_types else 'NO'}")

    # Check for full outputs (no truncation)
    has_full_outputs = any(p['type'] == 'tool' and len(p.get('output', '')) > 800 for p in run_data['server_parts'] + run_data['compromised_parts'])
    print(f"Has full outputs (>800 chars): {'YES' if has_full_outputs else 'NO'}")


if __name__ == "__main__":
    main()
