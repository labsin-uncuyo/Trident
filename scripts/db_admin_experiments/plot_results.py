#!/usr/bin/env python3
"""
Generate plots from db_admin experiment CSVs.

All plots use aggregated/average data across runs — no per-run individual charts.

Usage:
    python3 plot_results.py [--raw-runs-dir DIR]
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── Defaults ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_RAW_RUNS = PROJECT_ROOT / "experiments_db_admin" / "raw_runs"

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
    "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF", "#AEC7E8",
]


# ── Command categoriser ──────────────────────────────────────────────────────

def categorize_command(cmd: str) -> str:
    c = cmd.lower().strip()
    if c.startswith("sleep "):
        return "sleep"
    if "curl " in c:
        return "curl / web"
    if "psql" in c:
        if "insert" in c:
            return "SQL INSERT"
        if "update" in c:
            return "SQL UPDATE"
        if "delete" in c:
            return "SQL DELETE"
        if "select" in c:
            return "SQL SELECT"
        if any(x in c for x in ["\\dt", "\\d ", "\\l", "pg_dump", "pg_restore"]):
            return "SQL admin"
        return "SQL other"
    if "ssh " in c:
        return "SSH"
    if any(x in c for x in ["env ", "whoami", "hostname", "uname", "cat /etc", "id "]):
        return "system info"
    if any(x in c for x in ["ls ", "find ", "cat ", "head ", "tail ", "grep "]):
        return "file ops"
    if any(x in c for x in ["apt", "pip", "install"]):
        return "install"
    if "pg_isready" in c:
        return "pg_isready"
    if any(x in c for x in ["which ", "command -v"]):
        return "check tool"
    return "other"


def get_category(t: dict) -> str:
    if t["tool"] == "bash":
        return categorize_command(t["command"])
    if t["tool"] == "webfetch":
        return "other"
    return t["tool"]


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_top10(tools: list[dict]) -> list[str]:
    """Return the 10 most frequent action category names."""
    cats = Counter(get_category(t) for t in tools)
    return [name for name, _ in cats.most_common(10)]


def per_run_counts(tools: list[dict], top10: list[str]) -> dict[str, list[int]]:
    """Build {category: [count_run1, count_run2, ...]} for the top-10 actions."""
    run_cats = defaultdict(Counter)
    for t in tools:
        run_cats[t["run_id"]][get_category(t)] += 1
    run_ids = sorted(run_cats.keys())
    return {cat: [run_cats[r].get(cat, 0) for r in run_ids] for cat in top10}


# ── Plot functions (all command-count focused, top 10) ────────────────────────

def plot_01_avg_command_count(tools: list[dict], n_runs: int, top10: list[str], fig_dir: Path):
    """Horizontal bar: average command count per run for top 10 actions."""
    cats = Counter(get_category(t) for t in tools)
    labels = top10[::-1]
    avgs = [cats[c] / n_runs for c in labels]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(labels, avgs, color=PALETTE[:10][::-1])
    ax.set_xlabel("Avg. commands per run")
    ax.set_title("Top 10 Actions — Average Command Count per Run")
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    ax.set_xlim(0, max(avgs) * 1.15)
    fig.tight_layout()
    fig.savefig(fig_dir / "01_avg_command_count.png")
    plt.close(fig)


def plot_02_total_command_count(tools: list[dict], top10: list[str], fig_dir: Path):
    """Vertical bar: total command count across all runs for top 10 actions."""
    cats = Counter(get_category(t) for t in tools)
    labels = top10
    totals = [cats[c] for c in labels]

    fig, ax = plt.subplots(figsize=(11, 5))
    bars = ax.bar(labels, totals, color=PALETTE[:10])
    ax.set_ylabel("Total commands (30 runs)")
    ax.set_title("Top 10 Actions — Total Command Count")
    ax.bar_label(bars, padding=3, fontsize=9)
    plt.xticks(rotation=25, ha="right")
    fig.tight_layout()
    fig.savefig(fig_dir / "02_total_command_count.png")
    plt.close(fig)


def plot_03_command_count_boxplot(tools: list[dict], top10: list[str], fig_dir: Path):
    """Box plot: distribution of command counts per run for top 10 actions."""
    rc = per_run_counts(tools, top10)
    labels = top10[::-1]
    data = [rc[c] for c in labels]

    fig, ax = plt.subplots(figsize=(10, 6))
    bp = ax.boxplot(
        data, vert=False, patch_artist=True,
        flierprops=dict(marker="o", markersize=5, alpha=0.6),
        medianprops=dict(color="black", linewidth=1.5),
    )
    for patch, color in zip(bp["boxes"], PALETTE[:10][::-1]):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Commands per run")
    ax.set_title("Top 10 Actions — Command Count Distribution Across Runs")
    fig.tight_layout()
    fig.savefig(fig_dir / "03_command_count_boxplot.png")
    plt.close(fig)


def plot_04_command_share(tools: list[dict], top10: list[str], fig_dir: Path):
    """Pie chart: share of total commands for top 10 + 'other'."""
    cats = Counter(get_category(t) for t in tools)
    total = sum(cats.values())
    sizes = [cats[c] for c in top10]
    other = total - sum(sizes)
    all_labels = top10 + ["other"]
    all_sizes = sizes + [other]
    colors = PALETTE[:10] + ["#D3D3D3"]

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        all_sizes, labels=all_labels, autopct="%1.1f%%",
        colors=colors, startangle=90, pctdistance=0.82,
    )
    for t in autotexts:
        t.set_fontsize(8)
    for t in texts:
        t.set_fontsize(9)
    ax.set_title("Top 10 Actions — Share of Total Commands")
    fig.tight_layout()
    fig.savefig(fig_dir / "04_command_share.png")
    plt.close(fig)


def plot_05_sql_command_counts(tools: list[dict], n_runs: int, fig_dir: Path):
    """Bar chart: average SQL command counts per run by operation type."""
    sql_cats = ["SQL SELECT", "SQL INSERT", "SQL UPDATE", "SQL DELETE", "SQL admin", "SQL other"]
    cats = Counter(get_category(t) for t in tools)
    present = [(c, cats.get(c, 0)) for c in sql_cats if cats.get(c, 0) > 0]
    if not present:
        return
    labels = [c for c, _ in present]
    avgs = [v / n_runs for _, v in present]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, avgs, color=PALETTE[:len(labels)])
    ax.set_ylabel("Avg. commands per run")
    ax.set_title("SQL Operations — Average Command Count per Run")
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "05_sql_command_counts.png")
    plt.close(fig)


def plot_06_sql_count_boxplot(tools: list[dict], fig_dir: Path):
    """Box plot: SQL command counts per run by operation type."""
    sql_cats = ["SQL SELECT", "SQL INSERT", "SQL UPDATE", "SQL DELETE", "SQL admin", "SQL other"]
    run_sql = defaultdict(Counter)
    for t in tools:
        cat = get_category(t)
        if cat in sql_cats:
            run_sql[t["run_id"]][cat] += 1

    run_ids = sorted(run_sql.keys())
    present = [c for c in sql_cats if any(run_sql[r].get(c, 0) for r in run_ids)]
    if not present:
        return
    data = [[run_sql[r].get(c, 0) for r in run_ids] for c in present]

    fig, ax = plt.subplots(figsize=(10, 6))
    bp = ax.boxplot(
        data, vert=True, patch_artist=True,
        flierprops=dict(marker="o", markersize=5, alpha=0.6),
        medianprops=dict(color="black", linewidth=1.5),
    )
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(PALETTE[i])
        patch.set_alpha(0.7)
    ax.set_xticklabels(present, fontsize=10)
    ax.set_ylabel("Commands per run")
    ax.set_title("SQL Operations — Command Count Distribution Across Runs")
    fig.tight_layout()
    fig.savefig(fig_dir / "06_sql_count_boxplot.png")
    plt.close(fig)


EXIT_CODE_LABELS = {
    "0":   "exit 0\n(success)",
    "1":   "exit 1\n(general error)",
    "2":   "exit 2\n(syntax / misuse)",
    "127": "exit 127\n(command not found)",
}

def plot_07_exit_codes(tools: list[dict], n_runs: int, fig_dir: Path):
    """Bar chart: average exit-code counts per run."""
    bash = [t for t in tools if t["tool"] == "bash" and t["exit_code"] != ""]
    codes = Counter(t["exit_code"] for t in bash)

    threshold = 10
    main_codes = {}
    other_count = 0
    for code, count in codes.most_common():
        if count >= threshold:
            label = EXIT_CODE_LABELS.get(str(code), f"exit {code}")
            main_codes[label] = count
        else:
            other_count += count
    if other_count:
        main_codes["other"] = other_count

    ordered = sorted(main_codes.items(), key=lambda kv: kv[1], reverse=True)
    labels = [k for k, _ in ordered]
    avgs = [v / n_runs for _, v in ordered]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, avgs, color=PALETTE[:len(labels)])
    ax.set_ylabel("Avg. commands per run")
    ax.set_title("Bash Exit Codes — Average Count per Run")
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "07_exit_codes.png")
    plt.close(fig)


def plot_08_tool_type_counts(tools: list[dict], n_runs: int, fig_dir: Path):
    """Bar chart: average tool-type counts per run (bash, webfetch, etc.)."""
    raw_counts = Counter(t["tool"] for t in tools)
    # Merge webfetch into 'other'
    tool_types: Counter = Counter()
    for tool, count in raw_counts.items():
        key = "other" if tool == "webfetch" else tool
        tool_types[key] += count
    ordered = tool_types.most_common()
    labels = [x[0] for x in ordered]
    avgs = [x[1] / n_runs for x in ordered]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, avgs, color=PALETTE[:len(labels)])
    ax.set_ylabel("Avg. calls per run")
    ax.set_title("Tool Types — Average Command Count per Run")
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "08_tool_type_counts.png")
    plt.close(fig)


def plot_09_success_vs_error_top10(tools: list[dict], top10: list[str], n_runs: int, fig_dir: Path):
    """Stacked bar: avg successful vs failed commands per run for top 10."""
    ok = Counter()
    fail = Counter()
    for t in tools:
        cat = get_category(t)
        if cat not in top10:
            continue
        if t["status"] == "completed" and t.get("exit_code", "0") == "0":
            ok[cat] += 1
        else:
            fail[cat] += 1

    labels = top10
    ok_avgs = [ok.get(c, 0) / n_runs for c in labels]
    fail_avgs = [fail.get(c, 0) / n_runs for c in labels]
    totals = [o + f for o, f in zip(ok_avgs, fail_avgs)]

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(12, 6))
    bars_ok   = ax.bar(x, ok_avgs,   label="Success (exit 0)",    color=PALETTE[2])
    bars_fail = ax.bar(x, fail_avgs, bottom=ok_avgs, label="Error / non-zero", color=PALETTE[3])

    # Annotate each segment with avg count + percentage
    min_height = 0.8  # minimum segment height to show a label
    for i, (o, f, tot) in enumerate(zip(ok_avgs, fail_avgs, totals)):
        if tot == 0:
            continue
        ok_pct   = 100 * o / tot
        fail_pct = 100 * f / tot
        # Success segment label (centred in green area)
        if o >= min_height:
            ax.text(x[i], o / 2, f"{o:.1f}\n({ok_pct:.0f}%)",
                    ha="center", va="center", fontsize=7.5,
                    color="white", fontweight="bold")
        # Error segment label (centred in red area)
        if f >= min_height:
            ax.text(x[i], o + f / 2, f"{f:.1f}\n({fail_pct:.0f}%)",
                    ha="center", va="center", fontsize=7.5,
                    color="white", fontweight="bold")
        # Total label above the full bar
        ax.text(x[i], tot, f"{tot:.1f}", ha="center", va="bottom",
                fontsize=8, color="black")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylabel("Avg. commands per run")
    ax.set_title("Top 10 Actions — Success vs Error Count per Run")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "09_success_vs_error.png")
    plt.close(fig)


def plot_10_avg_summary_metrics(runs: list[dict], fig_dir: Path):
    """Bar chart: average high-level run metrics."""
    n = len(runs)
    metrics = {
        "Steps": sum(int(r["total_steps"]) for r in runs) / n,
        "Tool calls": sum(int(r["total_tool_calls"]) for r in runs) / n,
        "Messages": sum(int(r["messages_count"]) for r in runs) / n,
        "Bash calls": sum(int(r["bash_calls"]) for r in runs) / n,
        "Text events": sum(int(r["total_text_events"]) for r in runs) / n,
    }
    labels = list(metrics.keys())
    values = list(metrics.values())

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, values, color=PALETTE[:len(labels)])
    ax.set_ylabel("Average count per run")
    ax.set_title(f"Average Run Metrics ({n} runs)")
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "10_avg_summary_metrics.png")
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate plots from db_admin CSVs")
    parser.add_argument("--raw-runs-dir", type=Path, default=DEFAULT_RAW_RUNS)
    args = parser.parse_args()

    raw_dir = args.raw_runs_dir.resolve()
    fig_dir = raw_dir / "figures2"
    fig_dir.mkdir(parents=True, exist_ok=True)

    summary_path = raw_dir / "db_admin_runs_summary.csv"
    tools_path = raw_dir / "db_admin_tool_calls_detail.csv"
    if not summary_path.exists() or not tools_path.exists():
        print("Error: CSVs not found. Run generate_csvs.py first.", file=sys.stderr)
        sys.exit(1)

    runs = load_csv(summary_path)
    tools = load_csv(tools_path)
    n_runs = len(runs)
    top10 = get_top10(tools)
    print(f"Loaded {n_runs} runs, {len(tools)} tool calls")
    print(f"Top 10 actions: {', '.join(top10)}")
    print(f"Saving to {fig_dir}/\n")

    plots = [
        ("01_avg_command_count",    lambda: plot_01_avg_command_count(tools, n_runs, top10, fig_dir)),
        ("02_total_command_count",  lambda: plot_02_total_command_count(tools, top10, fig_dir)),
        ("03_command_count_boxplot",lambda: plot_03_command_count_boxplot(tools, top10, fig_dir)),
        ("04_command_share",        lambda: plot_04_command_share(tools, top10, fig_dir)),
        ("05_sql_command_counts",   lambda: plot_05_sql_command_counts(tools, n_runs, fig_dir)),
        ("06_sql_count_boxplot",    lambda: plot_06_sql_count_boxplot(tools, fig_dir)),
        ("07_exit_codes",           lambda: plot_07_exit_codes(tools, n_runs, fig_dir)),
        ("08_tool_type_counts",     lambda: plot_08_tool_type_counts(tools, n_runs, fig_dir)),
        ("09_success_vs_error",     lambda: plot_09_success_vs_error_top10(tools, top10, n_runs, fig_dir)),
        ("10_avg_summary_metrics",  lambda: plot_10_avg_summary_metrics(runs, fig_dir)),
    ]

    for name, fn in plots:
        fn()
        print(f"  ✓ {name}.png")

    print(f"\nDone. {len(plots)} figures saved.")


if __name__ == "__main__":
    main()
