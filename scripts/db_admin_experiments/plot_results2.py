#!/usr/bin/env python3
"""
Supplementary plots for db_admin experiments.

Plots generated:
  1. SQL command length distribution (histogram with %-labels, averaged across runs)
  2. SQL command execution time by command type (bar chart, averaged across runs)
  3. Exit-code failure rate over time (all tool calls, averaged across runs)

Usage:
    python3 plot_results2.py [--raw-runs-dir DIR]
"""

import argparse
import re
import sys
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ── Defaults ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_RAW_RUNS = PROJECT_ROOT / "experiments_db_admin" / "raw_runs"
DEFAULT_OUT = DEFAULT_RAW_RUNS / "figures2"

# ── Style ─────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#fafafa",
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "--",
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "axes.labelsize": 11,
    "figure.dpi": 150,
})

PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
]

# SQL keywords to detect SQL commands
SQL_KEYWORDS_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|GRANT|REVOKE|TRUNCATE|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)

SQL_TYPE_ORDER = [
    "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP",
    "ALTER", "GRANT", "REVOKE", "TRUNCATE", "BEGIN", "COMMIT", "ROLLBACK",
]


def extract_sql_query(cmd: str) -> str:
    """Extract the SQL string from a psql -c '...' command."""
    # Try -c "..." or -c '...'
    for pattern in [
        r'-c\s+"((?:[^"\\]|\\.)*)"',
        r"-c\s+'((?:[^'\\]|\\.)*)'",
    ]:
        m = re.search(pattern, cmd, re.DOTALL)
        if m:
            return m.group(1).strip()
    return cmd.strip()


def classify_sql_type(sql: str) -> str:
    """Return the primary SQL keyword (verb) of a query."""
    m = SQL_KEYWORDS_RE.search(sql)
    if m:
        return m.group(1).upper()
    return "OTHER"


def is_sql_command(row) -> bool:
    """True if the bash command contains a SQL keyword (psql -c ...)."""
    if row.get("tool") != "bash":
        return False
    cmd = str(row.get("command", ""))
    return bool(SQL_KEYWORDS_RE.search(cmd))


# ─────────────────────────────────────────────────────────────────────────────
# Plot 1 – SQL command length distribution (box plot per SQL type)
# ─────────────────────────────────────────────────────────────────────────────

def plot_sql_length_distribution(df: pd.DataFrame, out_dir: Path) -> None:
    """
    Box plot showing the character-length distribution of SQL queries,
    with one box per SQL command type (SELECT, INSERT, UPDATE, …).
    All individual observations across all runs are pooled per type.
    Each box is annotated with count (n) and share of total (%).
    """
    mask = df.apply(is_sql_command, axis=1)
    sql_df = df[mask].copy()
    sql_df["sql_query"] = sql_df["command"].apply(extract_sql_query)
    sql_df["sql_len"]   = sql_df["sql_query"].str.len()
    sql_df["sql_type"]  = sql_df["sql_query"].apply(classify_sql_type)

    # Order: canonical SQL_TYPE_ORDER first, then any extras alphabetically
    present       = set(sql_df["sql_type"].unique())
    ordered_types = [t for t in SQL_TYPE_ORDER if t in present] + \
                    sorted(t for t in present if t not in SQL_TYPE_ORDER)

    data_per_type = [
        sql_df.loc[sql_df["sql_type"] == t, "sql_len"].dropna().values
        for t in ordered_types
    ]

    total = sum(len(d) for d in data_per_type)
    pcts  = [len(d) / total * 100 for d in data_per_type]

    n_types = len(ordered_types)

    # Cap y-axis at the 99th percentile of all SQL lengths so boxes fill the
    # plot; extreme outliers beyond this cap are still drawn but clipped.
    all_lengths = np.concatenate([d for d in data_per_type if len(d) > 0])
    y_cap = float(np.percentile(all_lengths, 99)) * 1.15  # 15 % headroom
    y_cap = max(y_cap, 200)  # never collapse to nothing

    fig, ax = plt.subplots(figsize=(max(10, n_types * 1.6), 8))

    bp = ax.boxplot(
        data_per_type,
        patch_artist=True,
        notch=False,
        vert=True,
        widths=0.65,
        medianprops=dict(color="white", linewidth=2.5),
        whiskerprops=dict(linewidth=1.3, linestyle="--", color="#555555"),
        capprops=dict(linewidth=1.8, color="#555555"),
        flierprops=dict(marker="o", markersize=3.5, alpha=0.35,
                        linestyle="none", markeredgewidth=0),
    )

    colors = [PALETTE[i % len(PALETTE)] for i in range(n_types)]
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.82)
    for flier, color in zip(bp["fliers"], colors):
        flier.set_markerfacecolor(color)
        flier.set_markeredgecolor(color)

    # Apply y-axis cap AFTER drawing so boxplot internals are unaffected
    ax.set_ylim(0, y_cap)

    # Annotate each box: n, % and median value, placed just above the Q3 box
    label_offset = y_cap * 0.02
    for i, (lengths, pct) in enumerate(zip(data_per_type, pcts), start=1):
        if len(lengths) == 0:
            continue
        q3  = float(np.percentile(lengths, 75))
        med = float(np.median(lengths))
        y_label = min(q3 + label_offset, y_cap * 0.97)
        ax.text(
            i, y_label,
            f"n={len(lengths)}\n({pct:.1f}%)\nmed={med:.0f}",
            ha="center", va="bottom", fontsize=8.5, color="#111111",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.6,
                      edgecolor="none"),
        )

    # Count outliers clipped by y_cap
    n_clipped = int(np.sum(all_lengths > y_cap))

    ax.set_xticks(range(1, n_types + 1))
    ax.set_xticklabels(ordered_types, rotation=20, ha="right", fontsize=11)
    ax.set_xlabel("SQL Command Type", labelpad=8)
    ax.set_ylabel("SQL Query Length (characters)")
    ax.set_title("SQL Command Length Distribution by Type\n"
                 "(all observations pooled across all runs)")

    n_runs = sql_df["run_id"].nunique()
    clip_note = f"  |  {n_clipped} outlier(s) above y-cap not shown" if n_clipped else ""
    ax.text(
        0.98, 0.97,
        f"Total SQL cmds: {total} across {n_runs} runs\n"
        f"Box: Q1–Q3 | Centre line: median | Whiskers: 1.5×IQR{clip_note}",
        transform=ax.transAxes, ha="right", va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.75),
    )

    fig.tight_layout()
    out_path = out_dir / "plot1_sql_length_distribution.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"[1] Saved: {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Plot 2 – SQL command execution time by command type (box plot)
# ─────────────────────────────────────────────────────────────────────────────

def plot_sql_execution_time_by_type(df: pd.DataFrame, out_dir: Path) -> None:
    """
    Box plot of execution time (ms) per SQL command type, using all individual
    observations pooled across runs.  Log y-scale keeps fast and slow commands
    both visible; y-axis is capped at the 99th percentile to prevent extreme
    outliers from squashing the boxes.
    """
    mask = df.apply(is_sql_command, axis=1)
    sql_df = df[mask].copy()
    sql_df["sql_query"]   = sql_df["command"].apply(extract_sql_query)
    sql_df["sql_type"]    = sql_df["sql_query"].apply(classify_sql_type)
    sql_df["duration_ms"] = pd.to_numeric(sql_df["duration_ms"], errors="coerce")
    sql_df = sql_df.dropna(subset=["duration_ms"])
    sql_df = sql_df[sql_df["duration_ms"] > 0]

    present       = set(sql_df["sql_type"].unique())
    ordered_types = [t for t in SQL_TYPE_ORDER if t in present] + \
                    sorted(t for t in present if t not in SQL_TYPE_ORDER)

    data_per_type = [
        sql_df.loc[sql_df["sql_type"] == t, "duration_ms"].values
        for t in ordered_types
    ]

    total = sum(len(d) for d in data_per_type)
    pcts  = [len(d) / total * 100 for d in data_per_type]

    # Cap y-axis at 99th percentile with headroom so boxes fill the plot
    all_vals = np.concatenate([d for d in data_per_type if len(d) > 0])
    y_cap = float(np.percentile(all_vals, 99)) * 1.3
    y_floor = max(float(np.percentile(all_vals, 1)) * 0.7, 1)

    n_types = len(ordered_types)
    fig, ax = plt.subplots(figsize=(max(10, n_types * 1.6), 8))

    bp = ax.boxplot(
        data_per_type,
        patch_artist=True,
        notch=False,
        vert=True,
        widths=0.65,
        medianprops=dict(color="white", linewidth=2.5),
        whiskerprops=dict(linewidth=1.3, linestyle="--", color="#555555"),
        capprops=dict(linewidth=1.8, color="#555555"),
        flierprops=dict(marker="o", markersize=3.5, alpha=0.35,
                        linestyle="none", markeredgewidth=0),
    )

    colors = [PALETTE[i % len(PALETTE)] for i in range(n_types)]
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.82)
    for flier, color in zip(bp["fliers"], colors):
        flier.set_markerfacecolor(color)
        flier.set_markeredgecolor(color)

    # Log scale – apply limits after drawing
    ax.set_yscale("log")
    ax.set_ylim(y_floor, y_cap)

    # Annotate: n, %, median inside/above the Q3 line
    for i, (lengths, pct) in enumerate(zip(data_per_type, pcts), start=1):
        if len(lengths) == 0:
            continue
        med = float(np.median(lengths))
        q3  = float(np.percentile(lengths, 75))
        label_y = min(q3 * 1.25, y_cap * 0.92)
        med_str = f"{med/1000:.2f}s" if med >= 1000 else f"{med:.0f}ms"
        ax.text(
            i, label_y,
            f"n={len(lengths)}\n({pct:.1f}%)\nmed={med_str}",
            ha="center", va="bottom", fontsize=8.5, color="#111111",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                      alpha=0.65, edgecolor="none"),
        )

    def fmt_ms(v, _):
        if v >= 1000:
            return f"{v/1000:.0f}s"
        return f"{v:.0f}ms"

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_ms))
    ax.set_xticks(range(1, n_types + 1))
    ax.set_xticklabels(ordered_types, rotation=20, ha="right", fontsize=11)
    ax.set_xlabel("SQL Command Type", labelpad=8)
    ax.set_ylabel("Execution Time (log scale)")
    ax.set_title("SQL Command Execution Time by Type\n"
                 "(all observations pooled across all runs — log scale)")

    n_runs = sql_df["run_id"].nunique()
    n_clipped = int(np.sum(all_vals > y_cap))
    clip_note = f"  |  {n_clipped} outlier(s) above y-cap not shown" if n_clipped else ""
    ax.text(
        0.98, 0.97,
        f"Total SQL cmds: {total} across {n_runs} runs\n"
        f"Box: Q1–Q3 | Centre line: median | Whiskers: 1.5×IQR{clip_note}",
        transform=ax.transAxes, ha="right", va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.75),
    )

    fig.tight_layout()
    out_path = out_dir / "plot2_sql_execution_time_by_type.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"[2] Saved: {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Plot 3 – Exit-code failure rate over time
# ─────────────────────────────────────────────────────────────────────────────

def plot_exit_code_failure_rate_over_time(df: pd.DataFrame, out_dir: Path) -> None:
    """
    Frequency polygon of the failure rate (exit code ≠ 0) per minute of run.
    Each run lasted 45 minutes; elapsed time is derived from start_ts relative
    to the first call in that run.  Failure rates per minute are averaged across
    all runs and shown as a line with a 95 % CI shaded band.
    """
    bash_df = df[df["tool"] == "bash"].copy()
    bash_df["exit_code"] = pd.to_numeric(bash_df["exit_code"], errors="coerce")
    bash_df["failed"] = (bash_df["exit_code"] != 0).astype(float)

    # Parse timestamps and compute elapsed minutes from first call in each run
    bash_df["start_ts"] = pd.to_datetime(bash_df["start_ts"], utc=True, errors="coerce")

    def add_elapsed(group):
        group = group.copy()
        t0 = group["start_ts"].min()
        group["elapsed_min"] = (group["start_ts"] - t0).dt.total_seconds() / 60.0
        return group

    bash_df = bash_df.groupby("run_id", group_keys=False).apply(add_elapsed)

    RUN_DURATION_MIN = 45
    bash_df = bash_df.dropna(subset=["elapsed_min"])
    bash_df["minute_bin"] = bash_df["elapsed_min"].clip(0, RUN_DURATION_MIN - 1).astype(int)

    runs = bash_df["run_id"].unique()
    run_rates = np.full((len(runs), RUN_DURATION_MIN), np.nan)
    for i, run in enumerate(runs):
        run_sub = bash_df[bash_df["run_id"] == run]
        for m in range(RUN_DURATION_MIN):
            bin_sub = run_sub[run_sub["minute_bin"] == m]
            if len(bin_sub) > 0:
                run_rates[i, m] = bin_sub["failed"].mean()

    avg_rate = np.nanmean(run_rates, axis=0) * 100   # percent
    std_rate = np.nanstd(run_rates, axis=0) * 100
    n_valid  = np.sum(~np.isnan(run_rates), axis=0)
    ci95     = 1.96 * std_rate / np.sqrt(np.maximum(n_valid, 1))

    minutes = np.arange(RUN_DURATION_MIN)

    fig, ax = plt.subplots(figsize=(14, 6))

    # 95 % CI shaded band
    ax.fill_between(minutes,
                    np.clip(avg_rate - ci95, 0, None),
                    avg_rate + ci95,
                    color=PALETTE[3], alpha=0.18, label="95% CI")

    # Frequency polygon (line only, no bars)
    ax.plot(minutes, avg_rate,
            color=PALETTE[3], linewidth=2.2, marker="o",
            markersize=4, markerfacecolor="white", markeredgewidth=1.5,
            label="Avg failure rate", zorder=5)

    ax.set_xlabel("Elapsed Time (minutes into run)")
    ax.set_ylabel("Failure Rate (%)")
    ax.set_title("Exit-Code Failure Rate Over Time\n(average across all runs, 95% CI band)")
    ax.set_xlim(-0.5, RUN_DURATION_MIN - 0.5)
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(5))
    ax.xaxis.set_minor_locator(mticker.MultipleLocator(1))

    n_runs = len(runs)
    total_calls = len(bash_df)
    ax.text(
        0.98, 0.97,
        f"Total bash calls: {total_calls}\nRuns: {n_runs}\nShaded band: 95% CI",
        transform=ax.transAxes, ha="right", va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7),
    )

    ax.legend(fontsize=10)
    fig.tight_layout()
    out_path = out_dir / "plot3_failure_rate_over_time.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"[3] Saved: {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-runs-dir", type=Path, default=DEFAULT_RAW_RUNS,
                        help="Directory containing the experiment CSVs")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT,
                        help="Directory to save the output figures")
    args = parser.parse_args()

    raw_runs_dir: Path = args.raw_runs_dir
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    tool_calls_csv = raw_runs_dir / "db_admin_tool_calls_detail.csv"

    if not tool_calls_csv.exists():
        print(f"ERROR: {tool_calls_csv} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {tool_calls_csv} …")
    df = pd.read_csv(tool_calls_csv)
    df["call_idx"] = pd.to_numeric(df["call_idx"], errors="coerce")
    df["duration_ms"] = pd.to_numeric(df["duration_ms"], errors="coerce")
    df["exit_code"] = pd.to_numeric(df["exit_code"], errors="coerce")

    print(f"Loaded {len(df)} tool-call rows from {df['run_id'].nunique()} runs.\n")

    plot_sql_length_distribution(df, out_dir)
    plot_sql_execution_time_by_type(df, out_dir)
    plot_exit_code_failure_rate_over_time(df, out_dir)

    print(f"\nAll plots saved to: {out_dir}")


if __name__ == "__main__":
    main()
