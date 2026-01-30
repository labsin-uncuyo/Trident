#!/usr/bin/env python3
"""
Script to generate boxplots from benign experiment results.
Creates boxplots for key metrics and saves them as PNG files.
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import sys
from pathlib import Path

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['font.size'] = 10

def load_data(csv_path):
    """Load experiment data from CSV file."""
    df = pd.read_csv(csv_path)
    return df

def create_boxplot(data, column, title, ylabel, output_path, exclude_timeouts=False):
    """Create and save a boxplot for a specific metric."""
    plot_data = data.copy()
    
    # Optionally exclude timeout runs
    if exclude_timeouts:
        plot_data = plot_data[plot_data['status'] == 'completed']
        title += " (excluding timeouts)"
    
    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Create boxplot
    bp = ax.boxplot([plot_data[column].dropna()], 
                     labels=['All Runs'],
                     patch_artist=True,
                     showmeans=True,
                     meanprops=dict(marker='D', markerfacecolor='red', markersize=8))
    
    # Customize colors
    for patch in bp['boxes']:
        patch.set_facecolor('lightblue')
    
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_ylabel(ylabel, fontsize=12)
    ax.grid(True, alpha=0.3)
    
    # Add statistics text
    stats_text = f"n = {len(plot_data[column].dropna())}\n"
    stats_text += f"Mean: {plot_data[column].mean():.2f}\n"
    stats_text += f"Median: {plot_data[column].median():.2f}\n"
    stats_text += f"Std: {plot_data[column].std():.2f}"
    
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
            fontsize=9)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")

def create_status_comparison_boxplot(data, column, title, ylabel, output_path):
    """Create boxplot comparing completed vs timeout runs."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Separate data by status
    completed = data[data['status'] == 'completed'][column].dropna()
    timeout = data[data['status'] == 'timeout'][column].dropna()
    
    # Create boxplot
    bp = ax.boxplot([completed, timeout],
                     labels=['Completed', 'Timeout'],
                     patch_artist=True,
                     showmeans=True,
                     meanprops=dict(marker='D', markerfacecolor='red', markersize=8))
    
    # Customize colors
    colors = ['lightgreen', 'lightcoral']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
    
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_ylabel(ylabel, fontsize=12)
    ax.grid(True, alpha=0.3)
    
    # Add statistics
    stats_text = f"Completed: n={len(completed)}, mean={completed.mean():.2f}\n"
    stats_text += f"Timeout: n={len(timeout)}, mean={timeout.mean():.2f}"
    
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
            fontsize=9)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")

def create_multiple_metrics_boxplot(data, columns, title, output_path, exclude_timeouts=False):
    """Create boxplot with multiple metrics side by side."""
    plot_data = data.copy()
    
    if exclude_timeouts:
        plot_data = plot_data[plot_data['status'] == 'completed']
        title += " (excluding timeouts)"
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Prepare data for plotting
    plot_values = [plot_data[col].dropna() for col in columns]
    
    bp = ax.boxplot(plot_values,
                     labels=[col.replace('_', ' ').title() for col in columns],
                     patch_artist=True,
                     showmeans=True,
                     meanprops=dict(marker='D', markerfacecolor='red', markersize=8))
    
    # Customize colors
    colors = plt.cm.Set3(range(len(columns)))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
    
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_ylabel('Count', fontsize=12)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45, ha='right')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")

def main():
    # Check if CSV path is provided
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = Path('/home/shared/Trident/outputs/experiments_benign/experiment_benign_20260127_161016.csv')
    
    # Output directory
    if len(sys.argv) > 2:
        output_dir = Path(sys.argv[2])
    else:
        output_dir = Path('/home/shared/Trident/outputs/experiments_benign/1/graphics')
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading data from: {csv_path}")
    df = load_data(csv_path)
    
    print(f"\nDataset summary:")
    print(f"Total runs: {len(df)}")
    print(f"Completed: {len(df[df['status'] == 'completed'])}")
    print(f"Timeout: {len(df[df['status'] == 'timeout'])}")
    print(f"\nGenerating boxplots...\n")
    
    # 1. Duration boxplots
    create_boxplot(df, 'duration_seconds', 
                   'Experiment Duration Distribution',
                   'Duration (seconds)',
                   output_dir / 'duration_all.png')
    
    create_boxplot(df, 'duration_seconds',
                   'Experiment Duration Distribution',
                   'Duration (seconds)',
                   output_dir / 'duration_completed.png',
                   exclude_timeouts=True)
    
    create_status_comparison_boxplot(df, 'duration_seconds',
                                     'Duration Comparison by Status',
                                     'Duration (seconds)',
                                     output_dir / 'duration_by_status.png')
    
    # 2. Bash commands boxplot
    create_boxplot(df, 'bash_commands',
                   'Bash Commands Distribution',
                   'Number of Commands',
                   output_dir / 'bash_commands_all.png')
    
    create_boxplot(df, 'bash_commands',
                   'Bash Commands Distribution',
                   'Number of Commands',
                   output_dir / 'bash_commands_completed.png',
                   exclude_timeouts=True)
    
    create_status_comparison_boxplot(df, 'bash_commands',
                                     'Bash Commands by Status',
                                     'Number of Commands',
                                     output_dir / 'bash_commands_by_status.png')
    
    # 3. Text outputs boxplot
    create_boxplot(df, 'text_outputs',
                   'Text Outputs Distribution',
                   'Number of Text Outputs',
                   output_dir / 'text_outputs_all.png')
    
    create_boxplot(df, 'text_outputs',
                   'Text Outputs Distribution',
                   'Number of Text Outputs',
                   output_dir / 'text_outputs_completed.png',
                   exclude_timeouts=True)
    
    # 4. Final output length boxplot
    create_boxplot(df, 'final_output_length',
                   'Final Output Length Distribution',
                   'Length (characters)',
                   output_dir / 'output_length_all.png')
    
    create_boxplot(df, 'final_output_length',
                   'Final Output Length Distribution',
                   'Length (characters)',
                   output_dir / 'output_length_completed.png',
                   exclude_timeouts=True)
    
    # 5. Multiple metrics comparison (completed only)
    metrics = ['bash_commands', 'text_outputs', 'errors_count']
    create_multiple_metrics_boxplot(df, metrics,
                                    'Activity Metrics Comparison',
                                    output_dir / 'metrics_comparison_completed.png',
                                    exclude_timeouts=True)
    
    # 6. Multiple metrics comparison (all runs)
    create_multiple_metrics_boxplot(df, metrics,
                                    'Activity Metrics Comparison',
                                    output_dir / 'metrics_comparison_all.png',
                                    exclude_timeouts=False)
    
    print(f"\nAll plots saved to: {output_dir}")
    print(f"\nSummary statistics:")
    print(f"\nDuration (seconds):")
    print(df['duration_seconds'].describe())
    print(f"\nBash commands:")
    print(df['bash_commands'].describe())
    print(f"\nText outputs:")
    print(df['text_outputs'].describe())

if __name__ == '__main__':
    main()
