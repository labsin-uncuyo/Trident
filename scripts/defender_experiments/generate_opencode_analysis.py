#!/usr/bin/env python3
"""
OpenCode AutoResponder Analysis Script
Generates comprehensive reports from exfiltration experiment runs

Usage:
    python3 generate_opencode_analysis.py              # Run without LLM analysis
    python3 generate_opencode_analysis.py --with-llm   # Run with LLM analysis
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
EXPERIMENT_DIR = "/home/diego/Trident/exfil_experiment_output_50_python"
OUTPUT_DIR = os.path.join(EXPERIMENT_DIR, "report")
LLM_API_URL = "https://chat.ai.e-infra.cz/api/v1"
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
    env_file = os.path.join(os.path.dirname(EXPERIMENT_DIR), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

load_env()

# Create output directory
os.makedirs(OUTPUT_DIR, exist_ok=True)


class OpenCodeAnalyzer:
    def __init__(self, experiment_dir):
        self.experiment_dir = experiment_dir
        self.runs_data = []

    def load_all_runs(self):
        """Load all run directories and parse summary files"""
        pattern = os.path.join(self.experiment_dir, "exfil_py_run_*")
        run_dirs = sorted(glob.glob(pattern))

        for run_dir in run_dirs:
            run_num = self._extract_run_number(run_dir)
            summary_file = os.path.join(run_dir, "exfil_experiment_summary.json")
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

    def _parse_run(self, summary_file, timeline_file, run_dir, run_num):
        """Parse summary and timeline files"""
        data = {
            'run_num': run_num,
            'run_dir': os.path.basename(run_dir),
            'exfil_size_mb': 0,
            'timings': {},
            'commands': [],
            'tools': Counter(),
            'actions': defaultdict(list)
        }

        # Parse summary file
        try:
            with open(summary_file) as f:
                summary = json.load(f)

                # Get exfil size and timings from metrics (it's a dict, not a list!)
                if 'metrics' in summary and isinstance(summary['metrics'], dict):
                    metrics = summary['metrics']

                    # Get exfil size
                    if 'exfil_file_size_bytes' in metrics:
                        data['exfil_size_mb'] = metrics['exfil_file_size_bytes'] / (1024 * 1024)

                    # Get timing fields
                    timing_fields = [
                        'time_to_high_confidence_alert_seconds',
                        'time_to_plan_generation_seconds',
                        'time_to_opencode_execution_seconds',
                        'time_from_opencode_start_to_block_seconds',
                        'block_time_seconds',
                        'total_duration_seconds'
                    ]

                    for field in timing_fields:
                        if field in metrics:
                            data['timings'][field] = metrics[field]

                    # Also get block time from blocking_analysis
                    if 'blocking_analysis' in metrics and isinstance(metrics['blocking_analysis'], dict):
                        blocking = metrics['blocking_analysis']
                        if 'block_time_seconds' in blocking:
                            data['timings']['block_time_seconds'] = blocking['block_time_seconds']
                        if 'time_from_opencode_start_to_block_seconds' in blocking:
                            data['timings']['time_from_opencode_start_to_block_seconds'] = blocking['time_from_opencode_start_to_block_seconds']

                # Get total duration if available at top level
                if 'total_duration_seconds' in summary:
                    data['timings']['total_duration_seconds'] = summary['total_duration_seconds']

        except Exception as e:
            print(f"Error parsing summary {summary_file}: {e}")
            return None

        # Parse timeline for commands
        if os.path.exists(timeline_file):
            try:
                success_found = False
                with open(timeline_file) as f:
                    for line in f:
                        try:
                            entry = json.loads(line)

                            # Stop after first successful execution
                            if entry.get('level') == 'DONE':
                                if success_found:
                                    break
                                success_found = True

                            # Collect commands from first successful execution
                            if entry.get('level') == 'OPENCODE' and entry.get('msg') == 'tool_use':
                                entry_data = entry.get('data', {})
                                part = entry_data.get('part', {})

                                if isinstance(part, dict) and part.get('type') == 'tool':
                                    tool = part.get('tool')
                                    state = part.get('state', {})

                                    # Count tool usage
                                    if tool:
                                        data['tools'][tool] += 1

                                    if tool == 'bash':
                                        cmd = state.get('input', {}).get('command', 'N/A')
                                        desc = state.get('input', {}).get('description', 'N/A')
                                        exit_code = state.get('metadata', {}).get('exit', None)

                                        # Only collect commands until first DONE
                                        if not success_found:
                                            data['commands'].append({
                                                'command': cmd,
                                                'description': desc,
                                                'exit_code': exit_code
                                            })

                                            # Categorize actions
                                            action_type = self._categorize_action(cmd, desc)
                                            data['actions'][action_type].append(cmd)

                        except json.JSONDecodeError:
                            continue

            except Exception as e:
                print(f"Error parsing timeline {timeline_file}: {e}")

        return data

    def _categorize_action(self, command, description):
        """Categorize a command into an action type"""
        cmd_lower = command.lower()

        # Network containment
        if 'iptables' in cmd_lower and '-a output' in cmd_lower:
            return 'Block outbound traffic'
        elif 'iptables' in cmd_lower and '-a input' in cmd_lower:
            return 'Block inbound traffic'
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
        elif 'grep' in cmd_lower and ('137.184.126.86' in cmd_lower or '/var/log' in cmd_lower):
            return 'Search logs for IOCs'
        elif 'cp -r' in cmd_lower and '/var/log' in cmd_lower:
            return 'Preserve logs'
        elif 'journalctl' in cmd_lower:
            return 'Check system logs'
        elif 'lastlog' in cmd_lower or '/etc/passwd' in cmd_lower:
            return 'Check user accounts'

        # File operations
        elif 'find' in cmd_lower and ('dump' in cmd_lower or 'pg' in cmd_lower):
            return 'Search for dump files'
        elif 'rm ' in cmd_lower or '-delete' in cmd_lower:
            return 'Delete file'
        elif 'crontab' in cmd_lower:
            return 'Check scheduled tasks'

        # Backup
        elif 'iptables-save' in cmd_lower or 'backup' in cmd_lower:
            return 'Backup configuration'

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

    def create_exfil_size_boxplot(self):
        """Create box plot of exfiltrated data sizes"""
        print("Creating exfil size box plot...")

        sizes = [run['exfil_size_mb'] for run in self.runs_data if run['exfil_size_mb'] > 0]

        print(f"  Found {len(sizes)} runs with exfil size data")
        if sizes:
            print(f"  Min: {min(sizes):.1f} MB, Max: {max(sizes):.1f} MB, Median: {np.median(sizes):.1f} MB")

        if not sizes:
            print("No exfil size data found")
            return

        plt.figure(figsize=(10, 6))
        bp = plt.boxplot([sizes], vert=True, patch_artist=True)

        # Color the box
        bp['boxes'][0].set_facecolor('lightblue')

        plt.ylabel('Exfiltrated Data (MB)')
        plt.title('Data Exfiltration Size Distribution')
        plt.grid(True, alpha=0.3)

        # Add statistics text
        stats_text = f"Min: {min(sizes):.1f} MB\nMax: {max(sizes):.1f} MB\nMedian: {np.median(sizes):.1f} MB\nMean: {np.mean(sizes):.1f} MB"
        plt.text(1.1, np.median(sizes), stats_text, fontsize=10, verticalalignment='center')

        plt.tight_layout()

        output_file = os.path.join(OUTPUT_DIR, "exfil_size_boxplot.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"Saved exfil size box plot to {output_file}")

    def create_timing_boxplots(self):
        """Create combined box plots of all timing metrics from summary files"""
        print("Creating timing box plots...")

        # Extract all timing data
        timing_data = {}
        timing_labels = {
            'time_to_high_confidence_alert_seconds': 'Time to Alert (s)',
            'time_to_plan_generation_seconds': 'Time to Plan (s)',
            'time_to_opencode_execution_seconds': 'Time to Execute (s)',
            'time_from_opencode_start_to_block_seconds': 'OpenCode Start to Block (s)',
            'block_time_seconds': 'Block Time (s)',
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

        # Sort metrics by median value, but keep 'OpenCode Start to Block' last
        opencode_start_key = 'time_from_opencode_start_to_block_seconds'

        # Separate OpenCode Start to Block from other metrics
        other_metrics = [(k, v) for k, v in timing_data.items() if k != opencode_start_key]
        opencode_metric = [(k, v) for k, v in timing_data.items() if k == opencode_start_key]

        # Sort other metrics by median value
        sorted_other = sorted(other_metrics, key=lambda x: np.median(x[1]))

        # Combine: sorted other metrics first, then OpenCode Start to Block last
        sorted_metrics = sorted_other + opencode_metric

        fig, ax = plt.subplots(figsize=(12, 6))

        # Prepare data for boxplot
        data_to_plot = [data for key, data in sorted_metrics]
        labels_to_plot = [timing_labels[key] for key, data in sorted_metrics]

        # Create boxplot
        bp = ax.boxplot(data_to_plot, vert=True, patch_artist=True)

        # Color each box
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8']
        for idx, box in enumerate(bp['boxes']):
            box.set_facecolor(colors[idx % len(colors)])

        # Set labels
        ax.set_xticks(range(1, len(labels_to_plot) + 1))
        ax.set_xticklabels(labels_to_plot, rotation=45, ha='right')
        ax.set_ylabel('Time (seconds)')
        ax.set_title('OpenCode Response Timing Metrics (from Experiment Summaries)', fontsize=14)
        ax.grid(True, alpha=0.3, axis='y')
        ax.set_yscale('log')

        # Set 10 evenly spaced y-axis ticks on log scale
        import math
        min_val = 10
        max_val = 600
        # Create evenly spaced ticks on log scale
        log_min = math.log10(min_val)
        log_max = math.log10(max_val)
        log_ticks = np.linspace(log_min, log_max, 10)
        custom_ticks = [10**x for x in log_ticks]
        # Round to 2 significant figures
        custom_ticks = [round(x, 1) if x < 100 else round(x) for x in custom_ticks]
        ax.set_yticks(custom_ticks)
        ax.set_yticklabels([int(x) if x >= 100 else f"{x:.1f}" for x in custom_ticks])

        plt.tight_layout()

        output_file = os.path.join(OUTPUT_DIR, "timing_metrics_boxplots.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"Saved timing box plots to {output_file}")

    def analyze_notable_actions(self):
        """Use LLM to analyze notable actions from each run"""
        if not WITH_LLM:
            print("Skipping LLM analysis (disabled)")
            # Don't overwrite existing file
            return

        print("Analyzing notable actions with LLM...")

        output = []
        output.append("# Notable Actions Analysis")
        output.append("")
        output.append("*Generated by GPT-oss-120b analysis of each run's first successful execution*")
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

            # Create summary of commands
            commands_text = ""
            for i, cmd in enumerate(run['commands'][:20], 1):
                status = "✓" if cmd['exit_code'] == 0 else "✗"
                commands_text += f"{i}. [{status}] {cmd['command']}\n"

            prompt = f"""Analyze this incident response and identify the most interesting or unusual action taken.

Context: This is an automated response to a data exfiltration alert where the attacker used PostgreSQL dump (pg_dump) piped to netcat to exfiltrate a database to IP 137.184.126.86 on port 443.

Commands executed in order:
{commands_text}

A "usual" response would include: blocking the IP with iptables, killing processes, and checking network connections.

Answer in 1-2 sentences: What was the most INTERESTING or UNEXPECTED action taken - something beyond the standard response that stands out as unusual, creative, over-aggressive, or surprisingly effective/problematic?"""

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

                        output.append(f"## Run {run_num}")
                        output.append(f"{analysis}")
                        output.append("")
                    else:
                        output.append(f"## Run {run_num}")
                        output.append(f"> LLM analysis failed: No valid response")
                        output.append("")
                else:
                    output.append(f"## Run {run_num}")
                    output.append(f"> LLM analysis failed: HTTP {response.status_code}")
                    output.append("")

            except Exception as e:
                output.append(f"## Run {run_num}")
                output.append(f"> LLM analysis failed: {str(e)}")
                output.append("")

            print(f"  Analyzed run {run_num}")

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
        output.append("# OpenCode AutoResponder Analysis Report")
        output.append("")
        output.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append(f"**Experiment Directory:** {self.experiment_dir}")
        output.append(f"**Runs Analyzed:** {len(self.runs_data)}")
        output.append("")

        # Summary statistics
        output.append("## Summary Statistics")
        output.append("")

        sizes = [run['exfil_size_mb'] for run in self.runs_data if run['exfil_size_mb'] > 0]
        if sizes:
            output.append(f"- **Total data exfiltrated:** {sum(sizes):.1f} MB across {len(sizes)} runs")
            output.append(f"- **Average exfil size:** {np.mean(sizes):.1f} MB")
            output.append(f"- **Median exfil size:** {np.median(sizes):.1f} MB")
            output.append(f"- **Min exfil size:** {min(sizes):.1f} MB")
            output.append(f"- **Max exfil size:** {max(sizes):.1f} MB")
            output.append("")

        # Timing stats
        if self.runs_data:
            for timing_key in ['time_to_high_confidence_alert_seconds', 'time_to_plan_generation_seconds',
                              'time_to_opencode_execution_seconds', 'time_from_opencode_start_to_block_seconds']:
                values = [r['timings'].get(timing_key, 0) for r in self.runs_data
                         if r['timings'].get(timing_key) is not None and r['timings'].get(timing_key, 0) > 0]
                if values:
                    label = timing_key.replace('_', ' ').title()
                    output.append(f"- **Average {label}:** {np.mean(values):.1f} seconds")
            output.append("")

        # List all runs
        output.append("## Runs Analyzed")
        output.append("")
        output.append("| Run | Exfil Size (MB) | Commands | Tools |")
        output.append("|-----|----------------|----------|-------|")

        for run in sorted(self.runs_data, key=lambda x: x['run_num']):
            output.append(f"| {run['run_num']} | {run['exfil_size_mb']:.1f} | {len(run['commands'])} | {len(run['tools'])} |")

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
    print("OpenCode AutoResponder Analysis")
    print("=" * 80)
    print()

    # Initialize analyzer
    analyzer = OpenCodeAnalyzer(EXPERIMENT_DIR)

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
    analyzer.create_exfil_size_boxplot()
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
    print("  - exfil_size_boxplot.png")
    print("  - timing_metrics_boxplots.png")


if __name__ == "__main__":
    main()
