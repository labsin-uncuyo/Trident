#!/usr/bin/env python3
"""
Deep Dive Analysis of Failed Defenses in Brute Force Experiments
Analyzes runs where the defender failed to block the attack or where password was found

Usage:
    python3 analyze_brute_force_failures.py              # Basic analysis
    python3 analyze_brute_force_failures.py --with-llm  # With LLM root cause analysis
"""

import os
import sys
import json
import glob
import re
from pathlib import Path
from collections import defaultdict, Counter
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import seaborn as sns
import numpy as np
from datetime import datetime
import requests

# Configuration
EXPERIMENT_DIR = "/home/diego/Trident/creative_monitored"
OUTPUT_DIR = os.path.join(EXPERIMENT_DIR, "analysis")
LLM_API_URL = "https://llm.ai.e-infra.cz/v1"
LLM_MODEL = "gpt-oss-120b"
WITH_LLM = '--with-llm' in sys.argv

if WITH_LLM:
    print("LLM root cause analysis ENABLED")
else:
    print("LLM root cause analysis DISABLED (use --with-llm to enable)")

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
        return True
    return False

load_env()
os.makedirs(OUTPUT_DIR, exist_ok=True)


class FailureAnalyzer:
    def __init__(self, experiment_dir):
        self.experiment_dir = experiment_dir
        self.failed_runs = []
        self.successful_runs = []

    def load_all_runs(self):
        """Load all runs and categorize by success/failure"""
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
                # Categorize as failure if password was found OR no commands were executed
                if run_data['password_found'] or run_data['command_count'] == 0:
                    self.failed_runs.append(run_data)
                else:
                    self.successful_runs.append(run_data)

        print(f"Loaded {len(self.failed_runs)} failed runs and {len(self.successful_runs)} successful runs")

    def _extract_run_number(self, run_dir):
        """Extract run number from directory name"""
        match = re.search(r'run_(\d+)$', run_dir)
        return int(match.group(1)) if match else None

    def _parse_run(self, summary_file, timeline_file, run_dir, run_num):
        """Parse summary and timeline files"""
        data = {
            'run_num': run_num,
            'run_dir': os.path.basename(run_dir),
            'run_path': run_dir,
            'password_found': False,
            'login_attempts': 0,
            'port_blocked': False,
            'command_count': 0,
            'opencode_executed': False,
            'timeline_entries': [],
            'commands': [],
            'errors': [],
            'timings': {}
        }

        # Parse summary file
        try:
            with open(summary_file) as f:
                summary = json.load(f)

                if 'metrics' in summary and isinstance(summary['metrics'], dict):
                    metrics = summary['metrics']

                    data['login_attempts'] = metrics.get('flask_login_attempts', 0)
                    data['password_found'] = metrics.get('password_found', False)
                    data['port_blocked'] = 'time_to_port_blocked_seconds' in metrics

                    # Timing data
                    for key in ['time_to_high_confidence_alert_seconds',
                               'time_to_plan_generation_seconds',
                               'time_to_opencode_execution_seconds',
                               'time_to_port_blocked_seconds']:
                        if key in metrics:
                            data['timings'][key] = metrics[key]

        except Exception as e:
            data['errors'].append(f"Summary parse error: {e}")

        # Parse timeline
        if os.path.exists(timeline_file):
            try:
                with open(timeline_file) as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            data['timeline_entries'].append(entry)

                            # Check for OpenCode execution
                            if entry.get('level') == 'OPENCODE':
                                data['opencode_executed'] = True

                            # Extract commands
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

                                        data['commands'].append({
                                            'command': cmd,
                                            'description': desc,
                                            'exit_code': exit_code,
                                            'output': output[:500] if output else ''
                                        })
                                        data['command_count'] += 1

                                    # Check for errors in output
                                    if 'error' in str(state.get('output', '')).lower():
                                        data['errors'].append(f"Tool error: {tool}")

                        except json.JSONDecodeError:
                            continue

            except Exception as e:
                data['errors'].append(f"Timeline parse error: {e}")

        return data

    def analyze_failure_patterns(self):
        """Analyze common patterns in failures"""
        print("\nAnalyzing failure patterns...")

        failure_types = defaultdict(int)
        failure_reasons = []

        for run in self.failed_runs:
            if run['password_found']:
                failure_types['Password found (defense failed)'] += 1
                failure_reasons.append('password_found')
            elif run['command_count'] == 0:
                failure_types['No commands executed'] += 1
                failure_reasons.append('no_commands')
            elif not run['port_blocked']:
                failure_types['Port not blocked'] += 1
                failure_reasons.append('no_block')
            elif run['errors']:
                failure_types['Execution errors'] += 1
                failure_reasons.append('errors')

        return failure_types, failure_reasons

    def compare_with_successful(self):
        """Compare failed vs successful runs"""
        print("\nComparing failed vs successful runs...")

        comparison = {
            'failed_avg_attempts': np.mean([r['login_attempts'] for r in self.failed_runs]),
            'successful_avg_attempts': np.mean([r['login_attempts'] for r in self.successful_runs]),
            'failed_avg_commands': np.mean([r['command_count'] for r in self.failed_runs]),
            'successful_avg_commands': np.mean([r['command_count'] for r in self.successful_runs]),
            'failed_blocked': sum(1 for r in self.failed_runs if r['port_blocked']),
            'successful_blocked': sum(1 for r in self.successful_runs if r['port_blocked']),
        }

        return comparison

    def generate_failure_report(self):
        """Generate detailed failure report"""
        print("\nGenerating failure report...")

        output = []
        output.append("# Brute Force Defense Failure Analysis")
        output.append("")
        output.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append(f"**Total Runs Analyzed:** {len(self.failed_runs) + len(self.successful_runs)}")
        output.append(f"**Failed Runs:** {len(self.failed_runs)} ({100*len(self.failed_runs)/(len(self.failed_runs)+len(self.successful_runs)):.1f}%)")
        output.append(f"**Successful Runs:** {len(self.successful_runs)}")
        output.append("")

        # Failure types
        failure_types, _ = self.analyze_failure_patterns()
        output.append("## Failure Types")
        output.append("")
        output.append("| Failure Type | Count | Percentage |")
        output.append("|--------------|-------|------------|")
        total_failed = len(self.failed_runs)
        for ftype, count in sorted(failure_types.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total_failed) * 100
            output.append(f"| {ftype} | {count} | {pct:.1f}% |")
        output.append("")

        # Comparison
        comparison = self.compare_with_successful()
        output.append("## Failed vs Successful Runs Comparison")
        output.append("")
        output.append(f"| Metric | Failed Runs | Successful Runs |")
        output.append(f"|--------|-------------|-----------------|")
        output.append(f"| Avg login attempts | {comparison['failed_avg_attempts']:.0f} | {comparison['successful_avg_attempts']:.0f} |")
        output.append(f"| Avg commands executed | {comparison['failed_avg_commands']:.1f} | {comparison['successful_avg_commands']:.1f} |")
        output.append(f"| Port blocked | {comparison['failed_blocked']}/{len(self.failed_runs)} | {comparison['successful_blocked']}/{len(self.successful_runs)} |")
        output.append("")

        # Detailed failure breakdown
        output.append("## Detailed Failure Breakdown")
        output.append("")

        for run in sorted(self.failed_runs, key=lambda x: x['login_attempts'], reverse=True):
            output.append(f"### Run {run['run_num']}: {run['run_dir']}")
            output.append("")
            output.append(f"- **Login Attempts:** {run['login_attempts']}")
            output.append(f"- **Password Found:** {'✓ YES' if run['password_found'] else '✗ No'}")
            output.append(f"- **Commands Executed:** {run['command_count']}")
            output.append(f"- **Port Blocked:** {'✓ Yes' if run['port_blocked'] else '✗ No'}")
            output.append(f"- **OpenCode Executed:** {'✓ Yes' if run['opencode_executed'] else '✗ No'}")

            if run['timings']:
                output.append("- **Timings:**")
                for key, value in run['timings'].items():
                    if value:
                        label = key.replace('_', ' ').replace(' seconds', '').title()
                        output.append(f"  - {label}: {value:.1f}s")

            if run['errors']:
                output.append(f"- **Errors:** {len(run['errors'])}")
                for error in run['errors'][:3]:
                    output.append(f"  - {error}")

            # Show first few commands if any
            if run['commands']:
                output.append("- **Sample Commands:**")
                for cmd in run['commands'][:5]:
                    status = "✓" if cmd['exit_code'] == 0 else "✗"
                    output.append(f"  - [{status}] `{cmd['command'][:80]}...`")

            output.append("")

        report = "\n".join(output)

        # Save report
        report_file = os.path.join(OUTPUT_DIR, "failure_analysis.md")
        with open(report_file, 'w') as f:
            f.write(report)

        print(f"Saved failure report to {report_file}")
        return report

    def create_failure_visualizations(self):
        """Create visualizations of failure patterns"""
        print("\nCreating failure visualizations...")

        # 1. Failure types pie chart
        failure_types, _ = self.analyze_failure_patterns()

        if failure_types:
            fig, ax = plt.subplots(figsize=(10, 6))
            labels = list(failure_types.keys())
            sizes = list(failure_types.values())
            colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A']

            wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%',
                                              colors=colors[:len(labels)], startangle=90)
            ax.set_title('Defense Failure Types', fontsize=14, fontweight='bold')

            # Make percentage text bold
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')

            plt.tight_layout()
            output_file = os.path.join(OUTPUT_DIR, "failure_types_piechart.png")
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            plt.close()
            print(f"Saved failure types pie chart to {output_file}")

        # 2. Login attempts comparison
        failed_attempts = [r['login_attempts'] for r in self.failed_runs]
        successful_attempts = [r['login_attempts'] for r in self.successful_runs]

        fig, ax = plt.subplots(figsize=(12, 6))
        bp = ax.boxplot([failed_attempts, successful_attempts],
                       labels=['Failed Runs', 'Successful Runs'],
                       patch_artist=True)

        bp['boxes'][0].set_facecolor('#FF6B6B')
        bp['boxes'][1].set_facecolor('#4ECDC4')

        ax.set_ylabel('Login Attempts')
        ax.set_title('Login Attempts: Failed vs Successful Defenses', fontsize=14)
        ax.grid(True, alpha=0.3, axis='y')

        # Add statistics
        stats_text = f"Failed: median={np.median(failed_attempts):.0f}\n"
        stats_text += f"Successful: median={np.median(successful_attempts):.0f}"
        ax.text(0.98, 0.97, stats_text, transform=ax.transAxes,
               fontsize=10, verticalalignment='top', horizontalalignment='right',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        plt.tight_layout()
        output_file = os.path.join(OUTPUT_DIR, "failure_comparison_boxplot.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"Saved comparison box plot to {output_file}")

    def analyze_root_causes_with_llm(self):
        """Use LLM to analyze root causes of failures"""
        if not WITH_LLM:
            print("\nSkipping LLM root cause analysis (disabled)")
            return

        print("\nAnalyzing root causes with LLM...")

        api_key = os.environ.get('OPENCODE_API_KEY')
        if not api_key:
            print("Warning: OPENCODE_API_KEY not set, skipping LLM analysis")
            return

        output = []
        output.append("# Root Cause Analysis (LLM)")
        output.append("")
        output.append("*Detailed analysis of why defenses failed*")
        output.append("")

        # Analyze a sample of failed runs
        sample_size = min(10, len(self.failed_runs))
        sample_runs = sorted(self.failed_runs, key=lambda x: x['login_attempts'], reverse=True)[:sample_size]

        for idx, run in enumerate(sample_runs, 1):
            run_num = run['run_num']
            print(f"  Analyzing run {run_num} ({idx}/{len(sample_runs)})...")

            # Build context for LLM
            commands_text = ""
            for i, cmd in enumerate(run['commands'][:15], 1):
                status = "✓" if cmd['exit_code'] == 0 else "✗"
                commands_text += f"{i}. [{status}] {cmd['command']}\n"

            if not commands_text:
                commands_text = "No commands were executed."

            prompt = f"""Analyze this FAILED defensive response to a brute force password guessing attack.

**Context:**
- Attack: {run['login_attempts']} login attempts
- Password Found: {'YES - Defense FAILED' if run['password_found'] else 'No'}
- Commands Executed: {run['command_count']}
- Port Blocked: {'Yes' if run['port_blocked'] else 'No'}

**Commands Executed:**
{commands_text}

**Timeline Events Summary:**
{len(run['timeline_entries'])} timeline events logged

**Your Task:**
Analyze WHY this defense failed. Be specific and technical:

1. **Primary Failure Point**: What was the main reason this defense failed? (e.g., no commands executed, port not blocked, blocked too late, wrong blocking method)

2. **Technical Root Cause**: What specifically went wrong at a technical level? Was it a timing issue, incomplete execution, wrong approach, or missing step?

3. **What Would Have Worked**: What specific action or sequence of actions would have likely prevented the password from being found?

4. **Systemic Issue**: Does this reveal a pattern or weakness in the automated response approach?

Keep your analysis to 2-3 concise paragraphs. Be technical and specific."""

            try:
                response = requests.post(
                    f"{LLM_API_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 3000,
                        "temperature": 0
                    },
                    timeout=120
                )

                if response.status_code == 200:
                    result = response.json()
                    if 'choices' in result and len(result['choices']) > 0:
                        analysis = result['choices'][0]['message']['content'].strip()
                        output.append(f"## Run {run_num}")
                        output.append("")
                        output.append(analysis)
                        output.append("")
                        print(f"    ✓ Analyzed")
                    else:
                        output.append(f"## Run {run_num}")
                        output.append("> LLM analysis failed: No valid response")
                        output.append("")
                else:
                    output.append(f"## Run {run_num}")
                    output.append(f"> LLM analysis failed: HTTP {response.status_code}")
                    output.append("")

            except Exception as e:
                output.append(f"## Run {run_num}")
                output.append(f"> LLM analysis failed: {str(e)}")
                output.append("")

        # Save analysis
        analysis = "\n".join(output)
        output_file = os.path.join(OUTPUT_DIR, "root_cause_analysis.md")
        with open(output_file, 'w') as f:
            f.write(analysis)

        print(f"\nSaved root cause analysis to {output_file}")
        return analysis


def main():
    print("=" * 80)
    print("Brute Force Defense Failure Analysis")
    print("=" * 80)
    print()

    analyzer = FailureAnalyzer(EXPERIMENT_DIR)
    analyzer.load_all_runs()
    print()

    if not analyzer.failed_runs:
        print("No failed runs found! All defenses were successful.")
        return

    # Generate all reports
    print("Generating reports...")
    print("-" * 80)

    analyzer.generate_failure_report()
    analyzer.create_failure_visualizations()
    analyzer.analyze_root_causes_with_llm()

    print("-" * 80)
    print()
    print(f"Analysis complete! Results saved to: {OUTPUT_DIR}")
    print()
    print("Generated files:")
    print("  - failure_analysis.md")
    print("  - root_cause_analysis.md (if --with-llm)")
    print("  - failure_types_piechart.png")
    print("  - failure_comparison_boxplot.png")


if __name__ == "__main__":
    main()
