#!/usr/bin/env python3
"""
Expand Run Analysis Script
Reads auto_responder_timeline.jsonl files for specific runs and uses LLM to expand
on initial observations from diegoquestions.md

Usage:
    python3 expand_run_analysis.py
"""

import os
import json
import re
import requests
from pathlib import Path

# Configuration
EXPERIMENT_DIR = "/home/diego/Trident/exfil_experiment_output_50_python"
OUTPUT_DIR = os.path.join(EXPERIMENT_DIR, "report")
LLM_API_URL = "https://chat.ai.e-infra.cz/api/v1"
LLM_MODEL = "gpt-oss-120b"

# Load .env file to get API key
def load_env():
    env_file = os.path.join(os.path.dirname(os.path.dirname(EXPERIMENT_DIR)), ".env")
    trident_env = os.path.join("/home/diego/Trident", ".env")
    
    for env_path in [env_file, trident_env]:
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip()
            print(f"Loaded environment from {env_path}")
            return True
    return False

load_env()

# Runs to analyze with their initial observations
RUNS_TO_ANALYZE = {
    14: """The response went beyond the usual block‑and‑kill steps by swapping the real pg_dump binary for a custom wrapper script that logs every dump invocation (including the exact SQL query and user) and then aborts the operation, turning the attacker's own tool into a tripwire. This "binary‑hijack" technique is far more creative and proactive than a simple iptables block.""",
    
    15: """The most unexpected step was the explicit deletion of the two temporary log files (`/tmp/opencode_exec_times.log` and `/tmp/opencode_runtime.log`). Those files aren't related to PostgreSQL or the netcat dump, so removing them looks like an attempt to erase unrelated evidence rather than a standard containment action.""",
    
    25: """The most unexpected step was the blunt "kill ‑9 6555 6560 6568" – terminating three processes outright without first confirming they were the pg_dump/netcat jobs, which is far more aggressive than the typical "identify then stop" approach.""",
    
    24: """The most unexpected step was the targeted deletion of the suspicious shared‑object file `/tmp/.d88ffedfa7fd6d96-00000000.so` (step 16), which goes beyond generic blocking/killing and shows the responders actually identified and removed a specific malicious payload left on the host.""",
    
    27: """The only "extra" step was that the responder **never tried to stop the pg_dump/netcat processes – they just listed the top CPU‑hungry tasks with `ps aux …` instead of killing the malicious ones**. In a typical IR playbook you'd see a `kill`/`pkill` (or a `kill -9`) right after blocking the IP, so merely inspecting the process list without taking action is the most unexpected move.""",
    
    29: """The most unexpected step was the cascade of failed rkhunter install attempts followed by a manual `dpkg --configure -a` to repair the package system before retrying the install – a troubleshooting move you rarely see in a quick "block‑and‑kill" response.""",
    
    40: """The most unexpected step was the forensic‑style backup of credential files – copying **/etc/passwd** and especially **/etc/shadow** to /root.""",
    
    41: """The most unexpected step was pulling a root‑kit scanner onto the server during the containment – the automated run of `apt‑get update && apt‑get install -y chkrootkit` followed by `chkrootkit -q` (and the repeated, failed attempts to install rkhunter). Installing and executing a malware‑detection tool on a live production host goes well beyond the usual IP‑blocking, process‑killing, and service‑stopping actions.""",
    
    42: """The most unexpected step was that the responders didn't just block the IP and kill the dump process—they spun up a decoy PostgreSQL instance and configured a fake pg_dump that returned fabricated tables, effectively feeding the attacker bogus data instead of simply stopping the exfiltration. This misinformation‑as‑defense move goes well beyond the usual "block‑and‑kill" response.""",
    
    43: """The response went beyond the usual block‑and‑kill steps by swapping the real pg_dump binary for a custom wrapper script that logs every dump invocation (including the exact SQL query and user) and then aborts the operation, turning the attacker's own tool into a tripwire. This "binary‑hijack" technique is far more creative and proactive than a simple iptables block.""",
    
    76: """The most unexpected step was the forensic‑oriented action of locating a captured packet file ( `find / -type f -name "*.pcap"` ) and then copying the server's pcap (`/outputs/…/pcaps/server.pcap`) into `/root/server.pcap.bak`. Preserving the raw traffic dump goes beyond a typical "block‑and‑kill" response and shows a deliberate effort to retain evidence for later analysis.""",
    
    85: """The most unexpected step was stopping the unrelated nginx service (command 20), a web server that isn't part of the PostgreSQL dump chain, which is an over‑aggressive move that could disrupt legitimate production traffic.""",
    
    97: """The most unexpected step was digging into the system's scheduled jobs—listing `/etc/crontab`, the contents of `/etc/cron.d/`, and especially opening the suspicious `/etc/cron.d/e2scrub_all` file—showing the responder was hunting for a persistence mechanism rather than just blocking the IP and killing the dump processes."""
}


def extract_timeline_commands(run_num):
    """Extract relevant commands from auto_responder_timeline.jsonl up to first EXEC DONE"""
    run_pattern = f"exfil_py_run_{run_num}_exfil_py_*_run_{run_num}"
    run_dirs = list(Path(EXPERIMENT_DIR).glob(run_pattern))
    
    if not run_dirs:
        print(f"  Warning: No directory found for run {run_num}")
        return None
    
    timeline_file = run_dirs[0] / "auto_responder_timeline.jsonl"
    
    if not timeline_file.exists():
        print(f"  Warning: Timeline file not found for run {run_num}")
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
        print(f"  Warning: No EXEC DONE or OPENCODE found for run {run_num}")
    
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


def call_llm_for_expansion(run_num, initial_observation, commands_text):
    """Call LLM to expand on the initial observation"""
    api_key = os.environ.get('OPENCODE_API_KEY')
    if not api_key:
        print("  Error: OPENCODE_API_KEY not set")
        return None
    
    prompt = f"""You are analyzing an automated incident response to a data exfiltration attack. The attacker used PostgreSQL dump (pg_dump) piped to netcat to exfiltrate a database to IP 137.184.126.86 on port 443.

## Initial Observation (Run {run_num}):
{initial_observation}

## Complete Command Timeline:
{commands_text}

## Your Task:
Expand on the initial observation with a detailed analysis (2-4 paragraphs):

1. **Context and Setup**: Briefly describe what led to this interesting action - what commands came before it, what the responder was trying to accomplish.

2. **Detailed Breakdown**: Explain exactly HOW this action works technically. What specific commands or techniques were used? What do they do at a system level?

3. **Impact Assessment**: What are the implications of this approach? What are the benefits and risks? How does it compare to standard incident response procedures?

4. **Effectiveness and Edge Cases**: Would this action actually work as intended? Are there any potential issues, unintended consequences, or situations where it might fail or backfire?

Focus on technical accuracy and practical incident response considerations. Be specific and cite actual commands from the timeline."""

    try:
        print(f"  Calling LLM for run {run_num}...")
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
    print("Expanded Run Analysis Generator")
    print("=" * 80)
    print()
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Output file
    output_file = os.path.join(OUTPUT_DIR, "expanded_run_analysis.md")
    
    output_lines = [
        "# Expanded Incident Response Analysis",
        "",
        "This report provides detailed analysis of notable automated incident responses from the exfiltration experiments.",
        "",
        "Each run showcases an interesting or unexpected defensive action that goes beyond standard 'block-and-kill' responses.",
        "",
        "---",
        ""
    ]
    
    # Process each run
    total_runs = len(RUNS_TO_ANALYZE)
    for idx, (run_num, initial_obs) in enumerate(sorted(RUNS_TO_ANALYZE.items()), 1):
        print(f"\n[{idx}/{total_runs}] Processing Run {run_num}...")
        
        # Extract commands from timeline
        commands = extract_timeline_commands(run_num)
        
        if not commands:
            output_lines.append(f"## Run {run_num}")
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
        expanded_analysis = call_llm_for_expansion(run_num, initial_obs, commands_text)
        
        # Write to output
        output_lines.append(f"## Run {run_num}")
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
