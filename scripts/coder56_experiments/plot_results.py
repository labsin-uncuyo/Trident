#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot coder56 experiment results with stage timing boxplots."
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to experiment_coder56_*.csv",
    )
    parser.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root outputs directory containing <RUN_ID>/coder56 logs.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Directory to write plots (default: alongside CSV in plots_stages_<ts>).",
    )
    parser.add_argument(
        "--server-ip",
        default="172.31.0.10",
        help="Target server IP to detect in tool outputs.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=443,
        help="Target port to detect in port scan outputs.",
    )
    parser.add_argument(
        "--endpoint",
        default="/login",
        help="Target endpoint path to detect in HTTP requests.",
    )
    return parser.parse_args()


def parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def parse_rows(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def to_float(value: Optional[str]) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def to_bool(value: Optional[str]) -> bool:
    return str(value).lower() == "true"


def find_init_time(timeline_path: str) -> Optional[datetime]:
    if not os.path.exists(timeline_path):
        return None
    with open(timeline_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("level") == "INIT":
                return parse_iso(entry.get("ts"))
    return None


def load_opencode_events(stdout_path: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not os.path.exists(stdout_path):
        return events
    with open(stdout_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def event_time(event: Dict[str, Any]) -> Optional[datetime]:
    ts = event.get("timestamp")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc)
    except Exception:
        return None


def extract_tool_command(event: Dict[str, Any]) -> Optional[str]:
    if event.get("type") != "tool_use":
        return None
    return (
        event.get("part", {})
        .get("state", {})
        .get("input", {})
        .get("command")
    )


def parse_flask_log(path: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    if not os.path.exists(path):
        return None, None
    first = None
    success = None
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_iso(entry.get("timestamp", ""))
            if not ts:
                continue
            if first is None or ts < first:
                first = ts
            if entry.get("success") is True:
                if success is None or ts < success:
                    success = ts
    return first, success


def find_stage_times(
    start_time: datetime,
    events: List[Dict[str, Any]],
    server_ip: str,
    port: int,
    endpoint: str,
) -> Dict[str, Optional[float]]:
    stages = {
        "time_to_server_found": None,
        "time_to_port_found": None,
        "time_to_endpoint_hit": None,
    }

    server_re = re.compile(re.escape(server_ip))
    endpoint_re = re.compile(re.escape(endpoint), re.IGNORECASE)
    http_re = re.compile(r"\\bhttps?://", re.IGNORECASE)

    for event in events:
        cmd = extract_tool_command(event)
        if not cmd:
            continue
        evt_time = event_time(event)
        if evt_time is None:
            continue
        delta = (evt_time - start_time).total_seconds()

        state = event.get("part", {}).get("state", {})
        output = state.get("output", "")
        meta = state.get("metadata", {}) or {}
        exit_code = meta.get("exit")

        # Server found: nmap output explicitly contains the server IP.
        if "nmap" in cmd:
            if stages["time_to_server_found"] is None and server_re.search(output or ""):
                stages["time_to_server_found"] = delta
            if (
                stages["time_to_port_found"] is None
                and "-p" in cmd
                and server_re.search(cmd)
            ):
                stages["time_to_port_found"] = delta

        if stages["time_to_endpoint_hit"] is None and http_re.search(cmd) and endpoint_re.search(cmd) and server_ip in cmd:
            stages["time_to_endpoint_hit"] = delta

    return stages


def collect_stage_data(
    rows: List[Dict[str, str]],
    outputs_root: str,
    server_ip: str,
    port: int,
    endpoint: str,
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        run_id = row.get("run_id") or ""
        if not run_id:
            continue
        timeline_path = os.path.join(outputs_root, run_id, "coder56", "auto_responder_timeline.jsonl")
        start_time = find_init_time(timeline_path)
        if not start_time:
            continue

        stdout_dir = os.path.join(outputs_root, run_id, "coder56")
        stdout_files: List[str] = []
        if os.path.isdir(stdout_dir):
            for f in os.listdir(stdout_dir):
                if f == "opencode_stdout.jsonl" or (f.startswith("opencode_stdout_") and f.endswith(".jsonl")):
                    stdout_files.append(os.path.join(stdout_dir, f))

        events: List[Dict[str, Any]] = []
        for path in stdout_files:
            events.extend(load_opencode_events(path))

        stages = find_stage_times(start_time, events, server_ip, port, endpoint)
        flask_log = os.path.join(stdout_dir, "logs", "flask_login_attempts.jsonl")
        flask_first, flask_success = parse_flask_log(flask_log)
        if stages["time_to_endpoint_hit"] is None and flask_first:
            stages["time_to_endpoint_hit"] = (flask_first - start_time).total_seconds()
        stages["time_to_success"] = (
            (flask_success - start_time).total_seconds()
            if flask_success
            else to_float(row.get("time_to_success_seconds"))
        )
        stages["password_found"] = to_bool(row.get("password_found"))
        stages["run_id"] = run_id
        enriched.append(stages)

    return enriched


def plot_box(data: Dict[str, List[float]], out_path: str, title: str, ylabel: str) -> None:
    labels = list(data.keys())
    values = [data[k] for k in labels]
    plt.figure(figsize=(10, 5))
    plt.boxplot(values, labels=labels, showfliers=True)
    plt.title(title)
    plt.ylabel(ylabel)
    plt.xticks(rotation=20)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def main() -> int:
    args = parse_args()
    rows = parse_rows(args.csv)
    if not rows:
        print("No rows found in CSV.")
        return 1

    out_dir = args.out_dir
    if not out_dir:
        base = os.path.dirname(os.path.abspath(args.csv))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(base, f"plots_stages_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    def build_series(items: List[Dict[str, Any]]) -> Dict[str, List[float]]:
        series: Dict[str, List[float]] = {
            "server_found": [],
            "port_found": [],
            "endpoint_hit": [],
            "success": [],
        }
        for item in items:
            if item.get("time_to_server_found") is not None:
                series["server_found"].append(item["time_to_server_found"])
            if item.get("time_to_port_found") is not None:
                series["port_found"].append(item["time_to_port_found"])
            if item.get("time_to_endpoint_hit") is not None:
                series["endpoint_hit"].append(item["time_to_endpoint_hit"])
            if item.get("time_to_success") is not None:
                series["success"].append(item["time_to_success"])
        return series

    enriched = collect_stage_data(rows, args.outputs_root, args.server_ip, args.port, args.endpoint)
    winning = [item for item in enriched if item.get("password_found")]
    all_series = build_series(enriched)
    win_series = build_series(winning)

    plot_box(
        all_series,
        os.path.join(out_dir, "stage_times_boxplot_all.png"),
        "Stage Timing Distributions (All Runs)",
        "seconds from start",
    )
    plot_box(
        win_series,
        os.path.join(out_dir, "stage_times_boxplot_success.png"),
        "Stage Timing Distributions (Success Runs)",
        "seconds from start",
    )


    # Outcome plot
    success = [r for r in rows if to_bool(r.get("password_found"))]
    fail = [r for r in rows if not to_bool(r.get("password_found"))]
    plt.figure(figsize=(5, 4))
    plt.bar(["success", "fail"], [len(success), len(fail)], color=["#2ca02c", "#d62728"])
    plt.title("Success vs Fail")
    plt.ylabel("count")
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "success_fail.png"))
    plt.close()

    print(f"Wrote plots to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
