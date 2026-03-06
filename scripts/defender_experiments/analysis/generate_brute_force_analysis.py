#!/usr/bin/env python3
"""
OpenCode AutoResponder Analysis Script for Brute Force Experiments
Generates comprehensive reports from flask_brute_force experiment runs

Usage:
    python3 generate_brute_force_analysis.py              # Run without LLM analysis
    python3 generate_brute_force_analysis.py --with-llm   # Run with LLM analysis
"""

import os
import sys
import json
import glob
import re
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import seaborn as sns
import numpy as np
from datetime import datetime
import subprocess
import requests

# Configuration
EXPERIMENT_DIR = "/home/diego/Trident/creative_monitored"
OUTPUT_DIR = os.path.join(EXPERIMENT_DIR, "analysis")
LLM_API_URL = "https://llm.ai.e-infra.cz/v1"
LLM_MODEL = "gpt-oss-120b"
WITH_LLM = False  # Default: no LLM analysis

# Parse command line args
if '--with-llm' in sys.argv:
    WITH_LLM = True
    print("LLM analysis ENABLED")
else:
    print("LLM analysis DISABLED (use --with-llm to enable)")

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

# Create output directory
os.makedirs(OUTPUT_DIR, exist_ok=True)


class BruteForceAnalyzer:
    def __init__(self, experiment_dir):
        self.experiment_dir = experiment_dir
        self.runs_data = []

    def load_all_runs(self):
        """Load all run directories and parse summary files"""
        pattern = os.path.join(self.experiment_dir, "flask_brute_*_run_*")
        run_dirs = sorted(glob.glob(pattern))

        for run_dir in run_dirs:
            run_num = self._extract_run_number(run_dir)
            summary_file = os.path.join(run_dir, "flask_brute_experiment_summary.json")
            timeline_file = os.path.join(run_dir, "auto_responder_timeline.jsonl")

            if not os.path.exists(summary_file):
                continue

            run_data = self._parse_run(summary_file, timeline_file, run_dir, run_num)
            if run_data:
                self.runs_data.append(run_data)

        print(f"Loaded {len(self.runs_data)} runs")

    def _extract_run_number(self, run_dir):
        """Extract run number from directory name"""
        match = re.search(r'run_(\d+)$', run_dir)
        return int(match.group(1)) if match else None

    def _parse_timeline_with_source(self, timeline_file, source):
        """Parse timeline file and track which source (server/compromised) commands came from"""
        commands = []
        if not os.path.exists(timeline_file):
            return commands

        try:
            exec_done_found = False
            with open(timeline_file) as f:
                for line in f:
                    try:
                        entry = json.loads(line)

                        # Stop after first execution completes
                        if entry.get('level') == 'DONE' and 'EXEC' in entry.get('msg', ''):
                            exec_done_found = True
                            break

                        # Collect commands from timeline
                        if entry.get('level') == 'OPENCODE' and entry.get('msg') == 'tool_use':
                            entry_data = entry.get('data', {})
                            part = entry_data.get('part', {})

                            if isinstance(part, dict) and part.get('type') == 'tool':
                                tool = part.get('tool')
                                state = part.get('state', {})

                                if tool == 'bash':
                                    cmd = state.get('input', {}).get('command', 'N/A')
                                    desc = state.get('input', {}).get('description', 'N/A')
                                    exit_code = state.get('metadata', {}).get('exit', None)

                                    commands.append({
                                        'command': cmd,
                                        'description': desc,
                                        'exit_code': exit_code,
                                        'source': source
                                    })

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            print(f"Error parsing timeline {timeline_file}: {e}")

        return commands

    def _parse_opencode_api_messages(self, api_messages_file, source):
        """Parse opencode_api_messages.json to extract all parts: step-start, text, tool, step-finish"""
        all_parts = []
        if not os.path.exists(api_messages_file):
            return all_parts

        try:
            with open(api_messages_file) as f:
                messages = json.load(f)

            # Extract all parts from all messages
            for message in messages:
                message_parts = message.get('parts', [])
                message_info = message.get('info', {})

                for part in message_parts:
                    part_type = part.get('type', 'unknown')

                    # Build part record with all available data
                    part_record = {
                        'type': part_type,
                        'source': source,
                        'message_role': message_info.get('role', 'unknown'),
                        'timestamp': message_info.get('time', {}).get('created', None)
                    }

                    # Add type-specific data
                    if part_type == 'tool':
                        tool = part.get('tool')
                        state = part.get('state', {})

                        part_record.update({
                            'tool': tool,
                            'input': state.get('input', {}),
                            'output': state.get('output', ''),
                            'status': state.get('status', 'unknown'),
                            'exit_code': state.get('metadata', {}).get('exit', None),
                            'call_id': part.get('callID', None)
                        })

                    elif part_type == 'text':
                        part_record.update({
                            'text': part.get('text', ''),
                            'time_start': part.get('time', {}).get('start', None),
                            'time_end': part.get('time', {}).get('end', None)
                        })

                    elif part_type == 'step-start':
                        part_record.update({
                            'part_id': part.get('id', None)
                        })

                    elif part_type == 'step-finish':
                        part_record.update({
                            'reason': part.get('reason', None),
                            'cost': part.get('cost', 0),
                            'tokens': part.get('tokens', {})
                        })

                    all_parts.append(part_record)

        except Exception as e:
            print(f"Error parsing API messages {api_messages_file}: {e}")

        return all_parts

    def _format_parts_for_llm(self, server_parts, compromised_parts):
        """Format all parts (step-start, text, tool, step-finish) for LLM prompt"""
        text_parts = []
        text_parts.append("### SERVER (172.31.0.10 - Defender System)\n")

        # Format server parts
        for part in server_parts:
            part_type = part['type']

            if part_type == 'step-start':
                text_parts.append("[STEP START]")

            elif part_type == 'text' and part.get('text'):
                text_parts.append(f"[THOUGHT]: {part['text']}")

            elif part_type == 'tool':
                tool = part['tool']
                text_parts.append(f"[TOOL: {tool}]")

                # Add input based on tool type
                if tool == 'bash':
                    cmd = part['input'].get('command', 'N/A')
                    desc = part['input'].get('description', '')
                    status = part.get('status', 'unknown')
                    exit_code = part.get('exit_code', None)

                    text_parts.append(f"  Command: {cmd}")
                    if desc:
                        text_parts.append(f"  Description: {desc}")
                    if exit_code is not None:
                        text_parts.append(f"  Exit: {exit_code} ({'SUCCESS' if exit_code == 0 else 'FAILED'})")

                    # Add full output (no truncation)
                    if part.get('output'):
                        output = part['output']
                        text_parts.append(f"  Output:\n{output}")

                else:
                    # Other tools - show input as JSON
                    text_parts.append(f"  Input: {json.dumps(part['input'], indent=2)}")

                    if part.get('output'):
                        text_parts.append(f"  Output: {part['output']}")

            elif part_type == 'step-finish':
                reason = part.get('reason', 'unknown')
                tokens = part.get('tokens', {})
                text_parts.append(f"[STEP FINISH: {reason}] (Tokens: {tokens.get('total', 0)})")

            text_parts.append("")  # Blank line between parts

        # Format compromised parts
        text_parts.append("\n### COMPROMISED (172.30.0.10 - Attacker Target System)\n")

        for part in compromised_parts:
            part_type = part['type']

            if part_type == 'step-start':
                text_parts.append("[STEP START]")

            elif part_type == 'text' and part.get('text'):
                text_parts.append(f"[THOUGHT]: {part['text']}")

            elif part_type == 'tool':
                tool = part['tool']
                text_parts.append(f"[TOOL: {tool}]")

                # Add input based on tool type
                if tool == 'bash':
                    cmd = part['input'].get('command', 'N/A')
                    desc = part['input'].get('description', '')
                    status = part.get('status', 'unknown')
                    exit_code = part.get('exit_code', None)

                    text_parts.append(f"  Command: {cmd}")
                    if desc:
                        text_parts.append(f"  Description: {desc}")
                    if exit_code is not None:
                        text_parts.append(f"  Exit: {exit_code} ({'SUCCESS' if exit_code == 0 else 'FAILED'})")

                    # Add full output (no truncation)
                    if part.get('output'):
                        output = part['output']
                        text_parts.append(f"  Output:\n{output}")

                else:
                    # Other tools - show input as JSON
                    text_parts.append(f"  Input: {json.dumps(part['input'], indent=2)}")

                    if part.get('output'):
                        text_parts.append(f"  Output: {part['output']}")

            elif part_type == 'step-finish':
                reason = part.get('reason', 'unknown')
                tokens = part.get('tokens', {})
                text_parts.append(f"[STEP FINISH: {reason}] (Tokens: {tokens.get('total', 0)})")

            text_parts.append("")  # Blank line between parts

        return "\n".join(text_parts)

    def _parse_run(self, summary_file, timeline_file, run_dir, run_num):
        """Parse summary and API messages files"""
        data = {
            'run_num': run_num,
            'run_dir': os.path.basename(run_dir),
            'login_attempts': 0,
            'successful_attempts': 0,
            'password_found': False,
            'timings': {},
            'parts': [],
            'tools': Counter(),
            'actions': defaultdict(list),
            'server_parts': [],
            'compromised_parts': []
        }

        # Parse summary file
        try:
            with open(summary_file) as f:
                summary = json.load(f)

                # Get metrics (it's a dict, not a list!)
                if 'metrics' in summary and isinstance(summary['metrics'], dict):
                    metrics = summary['metrics']

                    # Get login attempt metrics
                    if 'flask_login_attempts' in metrics:
                        data['login_attempts'] = metrics['flask_login_attempts']

                    if 'flask_successful_attempts' in metrics:
                        data['successful_attempts'] = metrics['flask_successful_attempts']

                    if 'password_found' in metrics:
                        data['password_found'] = metrics['password_found']

                    # Get timing fields
                    timing_fields = [
                        'time_to_high_confidence_alert_seconds',
                        'time_to_plan_generation_seconds',
                        'time_to_opencode_execution_seconds',
                        'time_to_port_blocked_seconds',
                        'total_duration_seconds'
                    ]

                    for field in timing_fields:
                        if field in metrics:
                            data['timings'][field] = metrics[field]

                # Get total duration if available at top level
                if 'total_duration_seconds' in summary:
                    data['timings']['total_duration_seconds'] = summary['total_duration_seconds']

        except Exception as e:
            print(f"Error parsing summary {summary_file}: {e}")
            return None

        # Parse API messages for all parts from both server and compromised (ONLY - no fallback)
        server_api_file = os.path.join(run_dir, "defender", "server", "opencode_api_messages.json")
        compromised_api_file = os.path.join(run_dir, "defender", "compromised", "opencode_api_messages.json")

        # Track file availability
        data['server_api_file_exists'] = os.path.exists(server_api_file)
        data['compromised_api_file_exists'] = os.path.exists(compromised_api_file)

        server_parts = self._parse_opencode_api_messages(server_api_file, 'server')
        compromised_parts = self._parse_opencode_api_messages(compromised_api_file, 'compromised')

        data['server_parts'] = server_parts
        data['compromised_parts'] = compromised_parts

        # Log missing files for debugging
        if not data['server_api_file_exists'] and not data['compromised_api_file_exists']:
            print(f"  Warning: {run_dir} - no opencode_api_messages.json files found")
        elif not data['server_api_file_exists']:
            print(f"  Warning: {run_dir} - server opencode_api_messages.json missing")
        elif not data['compromised_api_file_exists']:
            print(f"  Warning: {run_dir} - compromised opencode_api_messages.json missing")

        # Combine all parts for analysis
        all_parts = server_parts + compromised_parts
        data['parts'] = all_parts

        # Count tools and categorize actions from tool parts
        for part in all_parts:
            if part['type'] == 'tool':
                tool_name = part['tool']
                data['tools'][tool_name] += 1

                # For bash tools, categorize the action
                if tool_name == 'bash':
                    cmd = part['input'].get('command', 'N/A')
                    desc = part['input'].get('description', 'N/A')
                    action_type = self._categorize_action(cmd, desc)
                    data['actions'][action_type].append(cmd)

        return data

    def _categorize_action(self, command, description):
        """Categorize a command into an action type"""
        cmd_lower = command.lower()

        # Network containment
        if 'iptables' in cmd_lower and ('drop' in cmd_lower or 'reject' in cmd_lower):
            return 'Block traffic'
        elif 'iptables' in cmd_lower:
            return 'Firewall rule modification'
        elif any(word in cmd_lower for word in ['netstat', 'ss ', 'lsof -i']):
            return 'Check network connections'
        elif 'iptables' in cmd_lower and ('-l' in cmd_lower or '--list' in cmd_lower):
            return 'Verify firewall rules'

        # Process containment
        elif 'kill' in cmd_lower or 'pkill' in cmd_lower:
            return 'Kill process'
        elif 'ps aux' in cmd_lower:
            return 'List processes'
        elif 'systemctl' in cmd_lower or 'service' in cmd_lower:
            if 'stop' in cmd_lower:
                return 'Stop service'
            elif 'status' in cmd_lower:
                return 'Check service status'
            else:
                return 'Service management'

        # Forensic collection
        elif 'find' in cmd_lower and ('/var/log' in cmd_lower or '*.log' in cmd_lower):
            return 'Search logs'
        elif 'grep' in cmd_lower and ('172.30' in cmd_lower or '172.31' in cmd_lower or '/var/log' in cmd_lower):
            return 'Search logs for IOCs'
        elif 'cp ' in cmd_lower and ('.log' in cmd_lower or '.bak' in cmd_lower):
            return 'Preserve logs'
        elif 'journalctl' in cmd_lower:
            return 'Check system logs'
        elif 'lastlog' in cmd_lower or '/etc/passwd' in cmd_lower:
            return 'Check user accounts'

        # File operations
        elif 'find' in cmd_lower and 'tmp' in cmd_lower:
            return 'Search temp files'
        elif 'rm ' in cmd_lower or '-delete' in cmd_lower:
            return 'Delete file'
        elif 'crontab' in cmd_lower:
            return 'Check scheduled tasks'

        # Backup
        elif 'iptables-save' in cmd_lower or 'backup' in cmd_lower:
            return 'Backup configuration'

        # Network capture
        elif 'tcpdump' in cmd_lower:
            return 'Network capture'

        # Verification
        elif 'grep' in cmd_lower:
            return 'Search/Verify'
        elif 'cat' in cmd_lower:
            return 'Read file'
        elif 'ls' in cmd_lower or 'find' in cmd_lower:
            return 'List files'

        else:
            return 'Other'

    def generate_action_frequency_table(self):
        """Generate action frequency table"""
        print("Generating action frequency table...")

        action_counts = defaultdict(int)

        for run in self.runs_data:
            for action_type in run['actions'].keys():
                action_counts[action_type] += 1

        # Sort by frequency
        sorted_actions = sorted(action_counts.items(), key=lambda x: x[1], reverse=True)

        # Create markdown table
        output = []
        output.append("# Action Frequency Table")
        output.append("")
        output.append("| Action | Frequency | Percentage |")
        output.append("|--------|-----------|------------|")

        total_runs = len(self.runs_data)
        for action, count in sorted_actions:
            pct = (count / total_runs) * 100
            output.append(f"| {action} | {count}/{total_runs} | {pct:.1f}% |")

        table = "\n".join(output)

        # Save to file
        output_file = os.path.join(OUTPUT_DIR, "action_frequency_table.md")
        with open(output_file, 'w') as f:
            f.write(table)

        print(f"Saved action frequency table to {output_file}")
        return table

    def generate_tool_usage_table(self):
        """Generate tool usage table"""
        print("Generating tool usage table...")

        tool_counts = Counter()

        for run in self.runs_data:
            tool_counts.update(run['tools'])

        # Sort by frequency
        sorted_tools = tool_counts.most_common()

        # Create markdown table
        output = []
        output.append("# Tool Usage Table")
        output.append("")
        output.append("| Tool | Frequency | Purpose |")
        output.append("|------|-----------|---------|")

        tool_purposes = {
            'bash': 'Command execution',
            'browser_open': 'Open URLs in browser',
            'chat_completion': 'LLM interaction',
            'file_read': 'Read file contents',
            'file_write': 'Write to files',
            'grep': 'Search patterns in files',
            'editor': 'Edit files',
            'read': 'Read file contents',
            'edit': 'Edit file contents',
        }

        for tool, count in sorted_tools:
            purpose = tool_purposes.get(tool, 'Unknown')
            output.append(f"| {tool} | {count} | {purpose} |")

        table = "\n".join(output)

        # Save to file
        output_file = os.path.join(OUTPUT_DIR, "tool_usage_table.md")
        with open(output_file, 'w') as f:
            f.write(table)

        print(f"Saved tool usage table to {output_file}")
        return table

    def create_login_attempts_boxplot(self):
        """Create box plot of login attempts"""
        print("Creating login attempts box plot...")

        attempts = [run['login_attempts'] for run in self.runs_data if run['login_attempts'] > 0]

        print(f"  Found {len(attempts)} runs with login attempt data")
        if attempts:
            print(f"  Min: {min(attempts)}, Max: {max(attempts)}, Median: {np.median(attempts):.1f}")

        if not attempts:
            print("No login attempt data found")
            return

        plt.figure(figsize=(10, 6))
        bp = plt.boxplot([attempts], vert=True, patch_artist=True)

        # Color the box
        bp['boxes'][0].set_facecolor('#FF6B6B')
        bp['boxes'][0].set_alpha(0.7)

        plt.ylabel('Login Attempts', fontsize=12)
        plt.title('Brute Force Login Attempts Distribution', fontsize=14, fontweight='bold')
        plt.grid(True, alpha=0.3, axis='y')

        # Add statistics text
        stats_text = f"Min: {min(attempts)}\nMax: {max(attempts)}\nMedian: {np.median(attempts):.1f}\nMean: {np.mean(attempts):.1f}"
        plt.text(1.1, np.median(attempts), stats_text, fontsize=10, verticalalignment='center',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        plt.tight_layout()

        output_file = os.path.join(OUTPUT_DIR, "login_attempts_boxplot.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"Saved login attempts box plot to {output_file}")

    def create_timing_boxplots(self):
        """Create combined box plots of all timing metrics from summary files"""
        print("Creating timing box plots...")

        # Extract all timing data
        timing_data = {}
        timing_labels = {
            'time_to_high_confidence_alert_seconds': 'Time to Alert (s)',
            'time_to_plan_generation_seconds': 'Time to Plan (s)',
            'time_to_opencode_execution_seconds': 'Time to Execute (s)',
            'time_to_port_blocked_seconds': 'Time to Block Port (s)',
            'total_duration_seconds': 'Total Duration (s)',
        }

        for run in self.runs_data:
            for key, value in run['timings'].items():
                if key in timing_labels and value is not None and value > 0:
                    if key not in timing_data:
                        timing_data[key] = []
                    timing_data[key].append(value)

        print(f"  Found timing data for {len(timing_data)} metrics:")
        for key, data in timing_data.items():
            print(f"    {timing_labels.get(key, key)}: {len(data)} values (median: {np.median(data):.1f}s)")

        # Create single plot with all boxes
        num_metrics = len(timing_data)
        if num_metrics == 0:
            print("No timing data found")
            return

        # Sort metrics by median value
        sorted_metrics = sorted(timing_data.items(), key=lambda x: np.median(x[1]))

        fig, ax = plt.subplots(figsize=(14, 7))

        # Prepare data for boxplot
        data_to_plot = [data for key, data in sorted_metrics]
        labels_to_plot = [timing_labels[key] for key, data in sorted_metrics]

        # Create boxplot
        bp = ax.boxplot(data_to_plot, vert=True, patch_artist=True, showmeans=True)

        # Color each box
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#F7DC6F']
        for idx, box in enumerate(bp['boxes']):
            box.set_facecolor(colors[idx % len(colors)])
            box.set_alpha(0.7)

        # Set labels
        ax.set_xticks(range(1, len(labels_to_plot) + 1))
        ax.set_xticklabels(labels_to_plot, rotation=45, ha='right', fontsize=11)
        ax.set_ylabel('Time (seconds)', fontsize=12)
        ax.set_title('Brute Force Response Timing Metrics', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y', linestyle='--')

        # Calculate appropriate y-axis limit
        # Use 95th percentile of all data to avoid extreme outliers
        all_values = [val for data in timing_data.values() for val in data]
        p95 = np.percentile(all_values, 95)
        max_non_outlier = max([max(data) for data in timing_data.values()])

        # Set y-axis to show most data clearly, but indicate outliers exist
        # If max is > 2x p95, cap at p95 * 1.5 to show majority clearly
        if max_non_outlier > p95 * 2:
            y_max = p95 * 1.5
            ax.set_ylim(bottom=0, top=y_max)
            # Add note about outliers
            ax.text(0.02, 0.02, f'Note: {sum(1 for v in all_values if v > y_max)} outliers > {y_max:.0f}s not shown',
                   transform=ax.transAxes, fontsize=8, style='italic',
                   bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.7))
        else:
            ax.set_ylim(bottom=0)

        # Add statistics text box - position outside plot area to avoid blocking data
        stats_text = "Statistics (median):\n"
        for key, data in sorted_metrics:
            label = timing_labels[key].replace(' (s)', '')
            median_val = np.median(data)
            stats_text += f"{label}: {median_val:.0f}s\n"

        # Place legend in upper left outside the main data area
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
               fontsize=9, verticalalignment='top', horizontalalignment='left',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        plt.tight_layout()

        output_file = os.path.join(OUTPUT_DIR, "timing_metrics_boxplots.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"Saved timing box plots to {output_file}")

    def analyze_notable_actions(self):
        """Use LLM to analyze notable actions from each run"""
        if not WITH_LLM:
            print("Skipping LLM analysis (disabled)")
            return

        print("Analyzing notable actions with LLM...")

        output = []
        output.append("# Notable Actions Analysis")
        output.append("")
        output.append("*Generated by GPT-oss-120b analysis of each run's execution*")
        output.append("")

        # Get API key from environment (already loaded by load_env())
        api_key = os.environ.get('OPENCODE_API_KEY')
        if not api_key:
            print("Warning: OPENCODE_API_KEY not set, skipping LLM analysis")
            output.append("> LLM analysis skipped: OPENCODE_API_KEY not configured")
            output.append("")
            return "\n".join(output)

        for run in self.runs_data:
            run_num = run['run_num']
            run_path = run['run_dir']
            output.append(f"## {run_path}")

            # Check if we have execution data
            server_parts = run['server_parts']
            compromised_parts = run['compromised_parts']

            if not server_parts and not compromised_parts:
                # No execution data available
                output.append("**Execution data not available:** opencode_api_messages.json files are missing or empty.")
                output.append("This run cannot be analyzed - the OpenCode execution logs were not saved.")
                output.append("")
                print(f"  Run {run_num}: No execution data available (skipped)")
                continue

            # Check for empty execution (files exist but no commands)
            total_tools = sum(1 for p in server_parts + compromised_parts if p['type'] == 'tool')
            if total_tools == 0:
                output.append("**No commands executed:** opencode_api_messages.json files exist but contain no tool executions.")
                output.append("The plan may have been generated but not executed, or execution data was not captured.")
                output.append("")
                print(f"  Run {run_num}: No tool executions found (skipped)")
                continue

            # Format all parts for the LLM
            execution_text = self._format_parts_for_llm(server_parts, compromised_parts)

            prompt = f"""Analyze this incident response and identify the most interesting or unusual action taken.

Context: This is an automated response to a brute force password guessing attack on a Flask login page. Run: {run_path}. The attacker made {run['login_attempts']} login attempts. The attack was detected as a port scan followed by repeated HTTP POST requests to /login.

The responder can execute commands on TWO systems:
- SERVER (172.31.0.10): The defender system where detection/response logic runs
- COMPROMISED (172.30.0.10): The target system being attacked (where Flask app runs)

Complete execution trace with all steps, text reasoning, tool uses, and outputs:
{execution_text}

A "usual" response would include: blocking the source IP with iptables, checking logs for login attempts, and verifying network connections.

Answer in 2-3 sentences:
1. What was the most INTERESTING or UNEXPECTED action taken - something beyond the standard response that stands out as unusual, creative, over-aggressive, or surprisingly effective/problematic?
2. Which system (SERVER or COMPROMISED) was this action executed on?

**IMPORTANT:** Only describe actions that are explicitly shown in the execution trace above. Do NOT invent or speculate about actions that are not documented. If the execution trace is incomplete or shows only basic containment, state that explicitly."""

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
                        output.append(f"{analysis}")
                        output.append("")
                        print(f"  Run {run_num}: Analyzed successfully ({total_tools} tools)")
                    else:
                        output.append(f"> LLM analysis failed: No valid response structure")
                        output.append("")
                        print(f"  Run {run_num}: LLM returned invalid response")
                else:
                    output.append(f"> LLM analysis failed: HTTP {response.status_code} - {response.text[:200]}")
                    output.append("")
                    print(f"  Run {run_num}: HTTP error {response.status_code}")

            except Exception as e:
                output.append(f"> LLM analysis failed: {str(e)}")
                output.append("")
                print(f"  Run {run_num}: Exception - {str(e)}")

        # Save to file
        analysis = "\n".join(output)
        output_file = os.path.join(OUTPUT_DIR, "notable_actions_analysis.md")
        with open(output_file, 'w') as f:
            f.write(analysis)

        print(f"Saved notable actions analysis to {output_file}")
        return analysis

    def generate_summary_report(self):
        """Generate overall summary report"""
        print("Generating summary report...")

        output = []
        output.append("# Brute Force Experiment Analysis Report")
        output.append("")
        output.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append(f"**Experiment Directory:** {self.experiment_dir}")
        output.append(f"**Runs Analyzed:** {len(self.runs_data)}")
        output.append("")

        # Summary statistics
        output.append("## Summary Statistics")
        output.append("")

        attempts = [run['login_attempts'] for run in self.runs_data if run['login_attempts'] > 0]
        if attempts:
            output.append(f"- **Total login attempts:** {sum(attempts)} across {len(attempts)} runs")
            output.append(f"- **Average attempts per run:** {np.mean(attempts):.1f}")
            output.append(f"- **Median attempts:** {np.median(attempts):.1f}")
            output.append(f"- **Min attempts:** {min(attempts)}")
            output.append(f"- **Max attempts:** {max(attempts)}")
            output.append("")

        # Success rate
        successful_runs = sum(1 for run in self.runs_data if run['password_found'])
        if len(self.runs_data) > 0:
            output.append(f"- **Runs where password was found:** {successful_runs}/{len(self.runs_data)} ({100*successful_runs/len(self.runs_data):.1f}%)")
            output.append("")

        # Timing stats
        if self.runs_data:
            for timing_key in ['time_to_high_confidence_alert_seconds', 'time_to_plan_generation_seconds',
                              'time_to_opencode_execution_seconds', 'time_to_port_blocked_seconds']:
                values = [r['timings'].get(timing_key, 0) for r in self.runs_data
                         if r['timings'].get(timing_key) is not None and r['timings'].get(timing_key, 0) > 0]
                if values:
                    label = timing_key.replace('_', ' ').title()
                    output.append(f"- **Average {label}:** {np.mean(values):.1f} seconds")
            output.append("")

        # List all runs
        output.append("## Runs Analyzed")
        output.append("")
        output.append("| Run | Login Attempts | Successful | Commands | Tools |")
        output.append("|-----|----------------|------------|----------|-------|")

        for run in sorted(self.runs_data, key=lambda x: x['run_num']):
            success = "✓" if run['password_found'] else "✗"
            output.append(f"| {run['run_num']} | {run['login_attempts']} | {success} | {len(run['parts'])} | {len(run['tools'])} |")

        output.append("")

        # Save summary
        summary = "\n".join(output)
        output_file = os.path.join(OUTPUT_DIR, "SUMMARY.md")
        with open(output_file, 'w') as f:
            f.write(summary)

        print(f"Saved summary report to {output_file}")
        return summary


def main():
    print("=" * 80)
    print("Brute Force Experiment Analysis")
    print("=" * 80)
    print()

    # Initialize analyzer
    analyzer = BruteForceAnalyzer(EXPERIMENT_DIR)

    # Load all runs
    analyzer.load_all_runs()
    print()

    if not analyzer.runs_data:
        print("No runs found to analyze!")
        return

    # Generate all reports
    print("Generating reports...")
    print("-" * 80)

    analyzer.generate_summary_report()
    analyzer.generate_action_frequency_table()
    analyzer.generate_tool_usage_table()
    analyzer.create_login_attempts_boxplot()
    analyzer.create_timing_boxplots()
    analyzer.analyze_notable_actions()

    print("-" * 80)
    print()
    print(f"Analysis complete! Results saved to: {OUTPUT_DIR}")
    print()
    print("Generated files:")
    print("  - SUMMARY.md")
    print("  - action_frequency_table.md")
    print("  - tool_usage_table.md")
    print("  - notable_actions_analysis.md")
    print("  - login_attempts_boxplot.png")
    print("  - timing_metrics_boxplots.png")


if __name__ == "__main__":
    main()
