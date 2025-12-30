#!/usr/bin/env python3
"""
Generate box plots from defender experiment results.

This script aggregates data from multiple experiment runs in
experiment_output/ and creates box plots for key metrics:
- time_to_plan_generation_seconds
- opencode_execution_seconds
- time_to_blocked_seconds
"""

import json
import os
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np


def collect_experiment_data(experiment_output_dir: str) -> Dict[str, List[float]]:
    """
    Collect data from all experiment directories.

    Args:
        experiment_output_dir: Path to experiment_output directory

    Returns:
        Dictionary with metric names as keys and lists of values as values
    """
    metrics = {
        "time_to_plan_generation_seconds": [],
        "opencode_execution_seconds": [],
        "time_to_blocked_seconds": [],
    }

    exp_path = Path(experiment_output_dir)
    if not exp_path.exists():
        raise FileNotFoundError(f"Experiment output directory not found: {experiment_output_dir}")

    # Iterate through all experiment directories
    for exp_dir in sorted(exp_path.iterdir()):
        if not exp_dir.is_dir():
            continue

        attack_summary_path = exp_dir / "logs" / "attack_summary.json"
        if not attack_summary_path.exists():
            print(f"Warning: attack_summary.json not found in {exp_dir}")
            continue

        try:
            with open(attack_summary_path, "r") as f:
                data = json.load(f)

            # Collect each metric if it exists
            for metric in metrics:
                value = data.get(metric)
                if value is not None:
                    metrics[metric].append(float(value))

        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse {attack_summary_path}: {e}")
        except Exception as e:
            print(f"Warning: Error reading {attack_summary_path}: {e}")

    return metrics


def print_statistics(metrics: Dict[str, List[float]]) -> None:
    """Print statistical summary for each metric."""
    print("\n" + "=" * 60)
    print("EXPERIMENT RESULTS STATISTICS")
    print("=" * 60)

    for metric_name, values in metrics.items():
        if not values:
            print(f"\n{metric_name}: No data")
            continue

        print(f"\n{metric_name}:")
        print(f"  Count:    {len(values)}")
        print(f"  Mean:     {np.mean(values):.2f}s")
        print(f"  Median:   {np.median(values):.2f}s")
        print(f"  Std Dev:  {np.std(values):.2f}s")
        print(f"  Min:      {np.min(values):.2f}s")
        print(f"  Max:      {np.max(values):.2f}s")
        print(f"  Q1:       {np.percentile(values, 25):.2f}s")
        print(f"  Q3:       {np.percentile(values, 75):.2f}s")

    print("\n" + "=" * 60)


def create_box_plots(metrics: Dict[str, List[float]], output_dir: str) -> None:
    """
    Create separate box plots for each metric.

    Args:
        metrics: Dictionary with metric names and values
        output_dir: Directory to save plots
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Define plot styling
    plot_config = {
        "time_to_plan_generation_seconds": {
            "title": "Time to Plan Generation",
            "ylabel": "Time (seconds)",
            "color": "#3498db",
        },
        "opencode_execution_seconds": {
            "title": "OpenCode Execution Time",
            "ylabel": "Time (seconds)",
            "color": "#e74c3c",
        },
        "time_to_blocked_seconds": {
            "title": "Time to Blocked",
            "ylabel": "Time (seconds)",
            "color": "#2ecc71",
        },
    }

    for metric_name, values in metrics.items():
        if not values:
            print(f"Skipping {metric_name}: No data available")
            continue

        config = plot_config[metric_name]

        # Create figure
        fig, ax = plt.subplots(figsize=(8, 6))

        # Create box plot
        bp = ax.boxplot(
            [values],
            vert=True,
            patch_artist=True,
            widths=0.5,
            showmeans=True,
            meanline=True,
        )

        # Style the box
        box = bp["boxes"][0]
        box.set_facecolor(config["color"])
        box.set_alpha(0.7)

        # Style elements
        for element in ["whiskers", "fliers", "means", "medians", "caps"]:
            plt.setp(bp[element], color="black", linewidth=1.5)

        # Add grid
        ax.yaxis.grid(True, linestyle="--", alpha=0.7)

        # Labels and title
        ax.set_ylabel(config["ylabel"], fontsize=12, fontweight="bold")
        ax.set_title(
            f"{config['title']}\n(n={len(values)})",
            fontsize=14,
            fontweight="bold",
        )

        # Remove x-axis ticks (not needed for single box)
        ax.set_xticks([])

        # Add statistics text box
        stats_text = (
            f"Mean: {np.mean(values):.2f}s\n"
            f"Median: {np.median(values):.2f}s\n"
            f"Std: {np.std(values):.2f}s"
        )
        ax.text(
            0.98,
            0.97,
            stats_text,
            transform=ax.transAxes,
            fontsize=10,
            verticalalignment="top",
            horizontalalignment="right",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
        )

        plt.tight_layout()

        # Save plot
        safe_name = metric_name.replace("_", "-")
        output_file = output_path / f"{safe_name}.png"
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        print(f"Saved: {output_file}")

        plt.close()


def create_combined_plot(metrics: Dict[str, List[float]], output_dir: str) -> None:
    """
    Create a combined plot with all three metrics side by side.

    Args:
        metrics: Dictionary with metric names and values
        output_dir: Directory to save plots
    """
    output_path = Path(output_dir)

    # Filter out metrics with no data
    valid_metrics = {
        k: v for k, v in metrics.items() if v
    }

    if not valid_metrics:
        print("No data available for combined plot")
        return

    fig, axes = plt.subplots(1, len(valid_metrics), figsize=(6 * len(valid_metrics), 5))

    # If only one metric has data, axes won't be an array
    if len(valid_metrics) == 1:
        axes = [axes]

    colors = ["#3498db", "#e74c3c", "#2ecc71"]
    titles = {
        "time_to_plan_generation_seconds": "Time to Plan Generation",
        "opencode_execution_seconds": "OpenCode Execution Time",
        "time_to_blocked_seconds": "Time to Blocked",
    }

    for idx, (metric_name, values) in enumerate(valid_metrics.items()):
        ax = axes[idx]

        bp = ax.boxplot(
            [values],
            vert=True,
            patch_artist=True,
            widths=0.5,
            showmeans=True,
            meanline=True,
        )

        box = bp["boxes"][0]
        box.set_facecolor(colors[idx])
        box.set_alpha(0.7)

        for element in ["whiskers", "fliers", "means", "medians", "caps"]:
            plt.setp(bp[element], color="black", linewidth=1.5)

        ax.yaxis.grid(True, linestyle="--", alpha=0.7)
        ax.set_ylabel("Time (seconds)", fontsize=11, fontweight="bold")
        ax.set_title(
            f"{titles[metric_name]}\n(n={len(values)})",
            fontsize=12,
            fontweight="bold",
        )
        ax.set_xticks([])

    plt.tight_layout()

    output_file = output_path / "combined_metrics.png"
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    print(f"Saved: {output_file}")

    plt.close()


def main():
    """Main entry point."""
    # Paths
    script_dir = Path(__file__).parent
    trident_dir = script_dir.parent.parent
    experiment_output_dir = trident_dir / "experiment_output"
    plots_output_dir = trident_dir / "experiment_output" / "plots"

    print(f"Reading experiments from: {experiment_output_dir}")
    print(f"Saving plots to: {plots_output_dir}")

    # Collect data
    metrics = collect_experiment_data(str(experiment_output_dir))

    # Print statistics
    print_statistics(metrics)

    # Create plots
    create_box_plots(metrics, str(plots_output_dir))
    create_combined_plot(metrics, str(plots_output_dir))

    print(f"\nDone! Plots saved to: {plots_output_dir}")


if __name__ == "__main__":
    main()
