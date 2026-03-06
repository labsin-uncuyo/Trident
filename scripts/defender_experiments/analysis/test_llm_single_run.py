#!/usr/bin/env python3
"""
Test LLM analysis with a single run to verify the prompt format
"""

import os
import sys
import json
import requests
from pathlib import Path

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

def parse_opencode_api_messages(api_messages_file, source):
    """Parse opencode_api_messages.json to extract tool uses with input and output"""
    commands = []
    if not os.path.exists(api_messages_file):
        return commands

    try:
        with open(api_messages_file) as f:
            messages = json.load(f)

        # Extract tool uses from messages
        for message in messages:
            parts = message.get('parts', [])

            for part in parts:
                # Only look at tool parts
                if part.get('type') == 'tool':
                    tool = part.get('tool')
                    state = part.get('state', {})

                    if tool == 'bash':
                        cmd = state.get('input', {}).get('command', 'N/A')
                        desc = state.get('input', {}).get('description', 'N/A')
                        output = state.get('output', '')
                        exit_code = state.get('metadata', {}).get('exit', None)
                        status = state.get('status', 'unknown')

                        # Truncate long outputs to keep prompt size reasonable
                        if len(output) > 800:
                            output = output[:800] + "\n... [output truncated]"

                        commands.append({
                            'command': cmd,
                            'description': desc,
                            'output': output,
                            'exit_code': exit_code,
                            'status': status,
                            'source': source
                        })

    except Exception as e:
        print(f"Error parsing API messages {api_messages_file}: {e}")

    return commands

def main():
    print("=" * 80)
    print(f"Testing LLM Analysis with Single Run: {TEST_RUN}")
    print("=" * 80)
    print()

    # Parse summary
    summary_file = os.path.join(TEST_RUN, "flask_brute_experiment_summary.json")
    with open(summary_file) as f:
        summary = json.load(f)

    login_attempts = summary['metrics']['flask_login_attempts']
    run_name = os.path.basename(TEST_RUN)

    # Parse API messages
    server_api_file = os.path.join(TEST_RUN, "defender", "server", "opencode_api_messages.json")
    compromised_api_file = os.path.join(TEST_RUN, "defender", "compromised", "opencode_api_messages.json")

    server_cmds = parse_opencode_api_messages(server_api_file, 'server')
    compromised_cmds = parse_opencode_api_messages(compromised_api_file, 'compromised')

    print(f"Parsed {len(server_cmds)} server commands and {len(compromised_cmds)} compromised commands")
    print()

    # Build commands text for prompt
    commands_text = ""

    # Server commands (first 5 for testing)
    commands_text += "### SERVER (172.31.0.10 - Defender System)\n"
    for i, cmd in enumerate(server_cmds[:5], 1):
        status = "✓" if cmd.get('exit_code') == 0 else "✗"
        commands_text += f"{i}. [{status}] {cmd['command']}\n"

        # Add description if available
        if 'description' in cmd and cmd['description'] != 'N/A':
            commands_text += f"   Description: {cmd['description']}\n"

        # Add output if available (from API messages)
        if 'output' in cmd and cmd['output']:
            commands_text += f"   Output: {cmd['output'][:200]}\n"
        commands_text += "\n"

    # Compromised commands (first 5 for testing)
    commands_text += "### COMPROMISED (172.30.0.10 - Attacker Target System)\n"
    for i, cmd in enumerate(compromised_cmds[:5], 1):
        status = "✓" if cmd.get('exit_code') == 0 else "✗"
        commands_text += f"{i}. [{status}] {cmd['command']}\n"

        # Add description if available
        if 'description' in cmd and cmd['description'] != 'N/A':
            commands_text += f"   Description: {cmd['description']}\n"

        # Add output if available (from API messages)
        if 'output' in cmd and cmd['output']:
            commands_text += f"   Output: {cmd['output'][:200]}\n"
        commands_text += "\n"

    # Build prompt
    prompt = f"""Analyze this incident response and identify the most interesting or unusual action taken.

Context: This is an automated response to a brute force password guessing attack on a Flask login page. Run: {run_name}. The attacker made {login_attempts} login attempts. The attack was detected as a port scan followed by repeated HTTP POST requests to /login.

The responder can execute commands on TWO systems:
- SERVER (172.31.0.10): The defender system where detection/response logic runs
- COMPROMISED (172.30.0.10): The target system being attacked (where Flask app runs)

Commands executed with their outputs:
{commands_text}

A "usual" response would include: blocking the source IP with iptables, checking logs for login attempts, and verifying network connections.

Answer in 2-3 sentences:
1. What was the most INTERESTING or UNEXPECTED action taken - something beyond the standard response that stands out as unusual, creative, over-aggressive, or surprisingly effective/problematic?
2. Which system (SERVER or COMPROMISED) was this action executed on?"""

    print("=" * 80)
    print("PROMPT THAT WILL BE SENT TO LLM:")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print()

    # Get API key
    api_key = os.environ.get('OPENCODE_API_KEY')
    if not api_key:
        print("Error: OPENCODE_API_KEY not set")
        return

    print("Sending prompt to LLM...")
    print()

    try:
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
                "max_tokens": 20000,
                "temperature": 0.3
            },
            timeout=300
        )

        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                analysis = result['choices'][0]['message']['content'].strip()

                print("=" * 80)
                print("LLM RESPONSE:")
                print("=" * 80)
                print(analysis)
                print("=" * 80)
                print()
                print("✓ Test completed successfully!")
            else:
                print("Error: No valid response from LLM")
        else:
            print(f"Error: HTTP {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"Error calling LLM: {str(e)}")


if __name__ == "__main__":
    main()
