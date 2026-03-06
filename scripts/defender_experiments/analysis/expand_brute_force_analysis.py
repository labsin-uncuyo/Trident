#!/usr/bin/env python3
"""
Expand Run Analysis Script for Brute Force Experiments
Reads auto_responder_timeline.jsonl files for specific runs and uses LLM to expand
on initial observations from expand.md or notable_actions_analysis.md

Usage:
    python3 expand_brute_force_analysis.py
"""

import os
import json
import re
import requests
from pathlib import Path

# Configuration
EXPERIMENT_DIR = "/home/diego/Trident/creative_monitored"
OUTPUT_DIR = os.path.join(EXPERIMENT_DIR, "analysis")
EXPAND_FILE = os.path.join(OUTPUT_DIR, "expand.md")
LLM_API_URL = "https://llm.ai.e-infra.cz/v1"
LLM_MODEL = "gpt-oss-120b"

# Load .env file to get API key
def load_env():
    trident_env = os.path.join("/home/diego/Trident", ".env")

    if os.path.exists(trident_env):
        with open(trident_env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
        print(f"Loaded environment from {trident_env}")
        return True
    return False

load_env()


def parse_expand_md():
    """Parse expand.md to extract runs and their initial observations"""
    if not os.path.exists(EXPAND_FILE):
        print(f"Error: {EXPAND_FILE} not found")
        return {}

    runs = {}
    current_run = None
    current_observation = []

    with open(EXPAND_FILE, 'r') as f:
        for line in f:
            # Match run headers like: ## flask_brute_1771977919_run_2
            header_match = re.match(r'^##\s+(flask_brute_\d+_run_\d+)', line)
            if header_match:
                # Save previous run if exists
                if current_run:
                    runs[current_run] = '\n'.join(current_observation).strip()

                # Start new run
                current_run = header_match.group(1)
                current_observation = []
            elif current_run:
                # Collect observation lines
                # Skip empty lines and merge bullet points
                if line.strip():
                    # Remove bullet numbers like "1. " or "2. "
                    cleaned = re.sub(r'^\d+\.\s+', '', line.strip())
                    current_observation.append(cleaned)

    # Save last run
    if current_run:
        runs[current_run] = '\n'.join(current_observation).strip()

    return runs


# Runs to analyze with their initial observations
# Keys can be either run numbers (int) or full paths (str)
# This will be automatically populated from expand.md
RUNS_TO_ANALYZE = {}

def extract_timeline_commands(run_path):
    """Extract relevant commands from auto_responder_timeline.jsonl up to first EXEC DONE"""
    # run_path can be either a full path or just a run directory name
    if not os.path.isabs(run_path):
        run_dir = Path(EXPERIMENT_DIR) / run_path
    else:
        run_dir = Path(run_path)

    if not run_dir.exists():
        print(f"  Warning: Directory not found for run {run_path}")
        return None

    timeline_file = run_dir / "auto_responder_timeline.jsonl"

    if not timeline_file.exists():
        print(f"  Warning: Timeline file not found for run {run_path}")
        return None

    commands = []
    exec_done_found = False
    last_opencode_found = False

    with open(timeline_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)

                # Check for EXEC DONE
                if entry.get('level') == 'DONE' and 'EXEC' in entry.get('msg', ''):
                    exec_done_found = True
                    break

                # Track OPENCODE entries
                if entry.get('level') == 'OPENCODE':
                    last_opencode_found = True

                # Extract bash commands
                if entry.get('level') == 'OPENCODE' and entry.get('msg') == 'tool_use':
                    entry_data = entry.get('data', {})
                    part = entry_data.get('part', {})

                    if isinstance(part, dict) and part.get('type') == 'tool':
                        tool = part.get('tool')
                        state = part.get('state', {})

                        if tool == 'bash':
                            cmd = state.get('input', {}).get('command', '')
                            desc = state.get('input', {}).get('description', '')
                            exit_code = state.get('metadata', {}).get('exit', None)
                            output = state.get('output', '')

                            # Truncate long outputs
                            if len(output) > 500:
                                output = output[:500] + "... [truncated]"

                            commands.append({
                                'command': cmd,
                                'description': desc,
                                'exit_code': exit_code,
                                'output': output
                            })

            except json.JSONDecodeError:
                continue

    if not exec_done_found and not last_opencode_found:
        print(f"  Warning: No EXEC DONE or OPENCODE found for run {run_path}")

    return commands


def format_commands_for_llm(commands):
    """Format commands for LLM prompt"""
    formatted = []

    for i, cmd in enumerate(commands, 1):
        status = "✓ SUCCESS" if cmd['exit_code'] == 0 else f"✗ FAILED (exit {cmd['exit_code']})" if cmd['exit_code'] is not None else "? UNKNOWN"

        formatted.append(f"\n### Command {i}: {cmd['description']}")
        formatted.append(f"**Status:** {status}")
        formatted.append(f"**Command:**")
        formatted.append(f"```bash")
        formatted.append(cmd['command'])
        formatted.append(f"```")

        if cmd['output'] and cmd['output'].strip():
            formatted.append(f"**Output:**")
            formatted.append(f"```")
            formatted.append(cmd['output'][:800])  # Limit output to keep prompt size reasonable
            formatted.append(f"```")

    return "\n".join(formatted)


def call_llm_for_expansion(run_path, initial_observation, commands_text):
    """Call LLM to expand on the initial observation"""
    api_key = os.environ.get('OPENCODE_API_KEY')
    if not api_key:
        print("  Error: OPENCODE_API_KEY not set")
        return None

    prompt = f"""You are analyzing an automated incident response to a brute force password guessing attack on a Flask login page. The attacker made repeated login attempts, which was detected as a port scan followed by HTTP POST requests to /login.

## Initial Observation ({run_path}):
{initial_observation}

## Complete Command Timeline:
{commands_text}

## CRITICAL VERIFICATION INSTRUCTIONS:
**Before writing your analysis, you MUST verify whether the actions described in the initial observation actually executed successfully.**

Check the command timeline carefully:
- Look at exit codes (✓ SUCCESS vs ✗ FAILED indicators)
- Read command outputs to confirm services actually started
- Verify file creations succeeded
- Check if background processes are actually running
- Identify any errors, failures, or partial executions

**Important distinctions to make:**
- Did the honeypot/deception service actually start and bind to the port successfully?
- Were files actually created, or did write operations fail?
- Did iptables/NAT rules get applied, or were there permission errors?
- Were background processes actually launched, or did they fail to start?

**Your analysis MUST clearly state:**
1. What was ATTEMPTED (what the responder tried to do)
2. What actually WORKED (commands that succeeded)
3. What FAILED (commands that failed or had errors)
4. Whether the described action was FULLY, PARTIALLY, or NOT successfully implemented

## Your Task:
Expand on the initial observation with a detailed analysis (2-4 paragraphs):

1. **Verification and Execution Status**: First and foremost - verify whether the described action actually worked. Did the commands succeed? Did the service start? Were the rules applied? Be explicit about what worked and what didn't.

2. **Context and Setup**: Briefly describe what led to this interesting action - what commands came before it, what the responder was trying to accomplish.

3. **Detailed Breakdown**: Explain exactly HOW this action works technically. What specific commands or techniques were used? What do they do at a system level?

4. **Impact Assessment**: What are the implications of this approach? What are the benefits and risks? How does it compare to standard incident response procedures?

5. **Effectiveness and Edge Cases**: Would this action actually work as intended? Are there any potential issues, unintended consequences, or situations where it might fail or backfire?

Focus on technical accuracy and practical incident response considerations. Be specific and cite actual commands from the timeline."""

    try:
        print(f"  Calling LLM for run {run_path}...")
        response = requests.post(
            f"{LLM_API_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 100000,
                "temperature": 0
            },
            timeout=300
        )

        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                return result['choices'][0]['message']['content'].strip()
            else:
                print(f"  Error: No valid response from LLM")
                return None
        else:
            print(f"  Error: HTTP {response.status_code} - {response.text}")
            return None

    except Exception as e:
        print(f"  Error calling LLM: {str(e)}")
        return None


def main():
    """Main execution"""
    print("=" * 80)
    print("Expanded Brute Force Run Analysis Generator")
    print("=" * 80)
    print()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Parse runs from expand.md
    global RUNS_TO_ANALYZE
    RUNS_TO_ANALYZE = parse_expand_md()

    print(f"Parsed {len(RUNS_TO_ANALYZE)} runs from {EXPAND_FILE}")

    # Output file
    output_file = os.path.join(OUTPUT_DIR, "expanded_run_analysis.md")

    output_lines = [
        "# Expanded Brute Force Incident Response Analysis",
        "",
        "This report provides detailed analysis of notable automated incident responses from the brute force experiments.",
        "",
        "Each run showcases an interesting or unexpected defensive action that goes beyond standard 'block-and-kill' responses.",
        "",
        "---",
        ""
    ]

    # Process each run
    total_runs = len(RUNS_TO_ANALYZE)
    if total_runs == 0:
        print("No runs to analyze. Please add runs to expand.md")
        print("\nTo use this script:")
        print("1. First run generate_brute_force_analysis.py --with-llm")
        print("2. Read the notable_actions_analysis.md file")
        print("3. Add interesting runs to expand.md")
        print("4. Run this script again to generate expanded analysis")
        return

    for idx, (run_key, initial_obs) in enumerate(sorted(RUNS_TO_ANALYZE.items()), 1):
        # Convert run_key to string (handles both int run numbers and string paths)
        run_path = str(run_key)
        print(f"\n[{idx}/{total_runs}] Processing {run_path}...")

        # Extract commands from timeline
        commands = extract_timeline_commands(run_path)

        if not commands:
            output_lines.append(f"## {run_path}")
            output_lines.append(f"**Initial Observation:** {initial_obs}")
            output_lines.append("")
            output_lines.append("*Timeline data not available for detailed analysis.*")
            output_lines.append("")
            output_lines.append("---")
            output_lines.append("")
            continue

        print(f"  Extracted {len(commands)} commands from timeline")

        # Format commands for LLM
        commands_text = format_commands_for_llm(commands)

        # Call LLM for expansion
        expanded_analysis = call_llm_for_expansion(run_path, initial_obs, commands_text)

        # Write to output
        output_lines.append(f"## {run_path}")
        output_lines.append("")
        output_lines.append(f"**Initial Observation:**")
        output_lines.append(f"> {initial_obs}")
        output_lines.append("")

        if expanded_analysis:
            output_lines.append(f"**Detailed Analysis:**")
            output_lines.append("")
            output_lines.append(expanded_analysis)
            print(f"  ✓ Successfully expanded analysis")
        else:
            output_lines.append("*LLM analysis unavailable.*")
            print(f"  ✗ Failed to get LLM analysis")

        output_lines.append("")
        output_lines.append("---")
        output_lines.append("")

        # Write incrementally so we don't lose progress
        with open(output_file, 'w') as f:
            f.write("\n".join(output_lines))

    print()
    print("=" * 80)
    print(f"✓ Analysis complete!")
    print(f"  Output saved to: {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
