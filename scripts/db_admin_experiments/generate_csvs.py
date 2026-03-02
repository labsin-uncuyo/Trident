#!/usr/bin/env python3
"""
Generate CSV reports from db_admin experiment raw runs.

Reads from:
  - db_admin_timeline.jsonl   (execution timeline events)
  - opencode_api_messages.json (structured session/message data)
  - opencode_stdout.jsonl      (raw event stream)

Produces 3 CSVs in the raw_runs directory:
  1. db_admin_runs_summary.csv      – one row per run (aggregated metrics)
  2. db_admin_steps_detail.csv      – one row per assistant step (tokens, tools)
  3. db_admin_tool_calls_detail.csv  – one row per tool invocation (commands, outputs)

Usage:
    python generate_csvs.py [--raw-runs-dir DIR]
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ── Defaults ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_RAW_RUNS = PROJECT_ROOT / "experiments_db_admin" / "raw_runs"


# ── Helpers ───────────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> list[dict]:
    """Read a .jsonl file, skipping blank / malformed lines."""
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  ⚠ Skipping malformed JSONL at {path.name}:{lineno}", file=sys.stderr)
    return records


def read_json(path: Path) -> list | dict:
    """Read a standard JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ts_to_iso(epoch_ms: int | float | None) -> str:
    """Convert epoch milliseconds to ISO-8601 string."""
    if epoch_ms is None:
        return ""
    try:
        return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, TypeError):
        return ""


def safe_get(d: dict, *keys, default=None):
    """Nested dict access."""
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d


def truncate(text: str, maxlen: int = 500) -> str:
    """Truncate text for CSV readability."""
    if text is None:
        return ""
    if len(text) <= maxlen:
        return text
    return text[:maxlen] + "…[truncated]"


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_timeline(timeline_records: list[dict]) -> dict:
    """
    Parse db_admin_timeline.jsonl into a summary dict for one run.
    """
    summary = {
        # From INIT
        "goal": "",
        "host": "",
        "agent": "",
        "exec_id": "",
        "mode": "",
        "time_limit": 0,
        "start_ts": "",
        "end_ts": "",
        # From DONE
        "total_sessions": 0,
        "total_duration_seconds": 0.0,
        # From SESSION_END
        "session_turns": 0,
        "session_duration_seconds": 0.0,
        "agent_done": False,
        "context_overflow": False,
        "messages_count": 0,
        # Aggregated from events
        "total_steps": 0,
        "total_tool_calls": 0,
        "total_text_events": 0,
        "bash_calls": 0,
        "unique_tools": set(),
        "tool_counts": Counter(),
        # Tokens
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "peak_step_tokens": 0,
        # Finish reasons
        "finish_reasons": Counter(),
    }

    for rec in timeline_records:
        level = rec.get("level", "")
        msg = rec.get("msg", "")
        data = rec.get("data", {})

        if level == "INIT":
            summary["goal"] = truncate(data.get("goal", ""), 200)
            summary["host"] = data.get("host", "")
            summary["agent"] = data.get("agent", "")
            summary["exec_id"] = data.get("exec", "")
            summary["mode"] = data.get("mode", "")
            summary["time_limit"] = data.get("time_limit", 0)
            summary["start_ts"] = rec.get("ts", "")

        elif level == "DONE":
            summary["total_sessions"] = data.get("total_sessions", 0)
            summary["total_duration_seconds"] = data.get("total_duration_seconds", 0.0)
            summary["end_ts"] = rec.get("ts", "")
            summary["exec_id"] = summary["exec_id"] or data.get("exec", "")

        elif level == "SESSION_END":
            summary["session_turns"] = data.get("turns", 0)
            summary["session_duration_seconds"] = data.get("duration_seconds", 0.0)
            summary["agent_done"] = data.get("agent_done", False)
            summary["context_overflow"] = data.get("context_overflow", False)
            summary["messages_count"] = data.get("messages_count", 0)

        elif level == "OPENCODE":
            evt_type = data.get("type", "")

            if evt_type == "step_finish":
                summary["total_steps"] += 1
                part = data.get("part", {})
                tokens = part.get("tokens", {})
                t_total = tokens.get("total", 0)
                summary["total_tokens"] += t_total
                summary["input_tokens"] += tokens.get("input", 0)
                summary["output_tokens"] += tokens.get("output", 0)
                summary["reasoning_tokens"] += tokens.get("reasoning", 0)
                cache = tokens.get("cache", {})
                summary["cache_read_tokens"] += cache.get("read", 0)
                summary["cache_write_tokens"] += cache.get("write", 0)
                if t_total > summary["peak_step_tokens"]:
                    summary["peak_step_tokens"] = t_total
                reason = part.get("reason", "")
                if reason:
                    summary["finish_reasons"][reason] += 1

            elif evt_type == "tool_use":
                summary["total_tool_calls"] += 1
                part = data.get("part", {})
                tool_name = part.get("tool", "unknown")
                summary["unique_tools"].add(tool_name)
                summary["tool_counts"][tool_name] += 1
                if tool_name == "bash":
                    summary["bash_calls"] += 1

            elif evt_type == "text":
                summary["total_text_events"] += 1

    # Serialize sets/counters for CSV
    summary["unique_tools"] = ";".join(sorted(summary["unique_tools"]))
    summary["tool_counts"] = ";".join(f"{k}={v}" for k, v in sorted(summary["tool_counts"].items()))
    summary["finish_reasons"] = ";".join(f"{k}={v}" for k, v in sorted(summary["finish_reasons"].items()))

    return summary


def parse_api_messages_steps(sessions: list[dict], run_id: str) -> list[dict]:
    """
    Parse opencode_api_messages.json into a list of rows
    (one per assistant message / step).
    """
    rows = []
    for session in sessions:
        session_id = session.get("session_id", "")
        session_num = session.get("session_num", 0)
        messages = session.get("messages", [])

        for msg_idx, msg in enumerate(messages):
            info = msg.get("info", {})
            role = info.get("role", "")
            parts = msg.get("parts", [])

            # Count parts by type
            text_parts = [p for p in parts if p.get("type") == "text"]
            tool_parts = [p for p in parts if p.get("type") == "tool"]
            step_starts = [p for p in parts if p.get("type") == "step-start"]

            # Extract tokens
            tokens = info.get("tokens", {})
            cache = tokens.get("cache", {}) if tokens else {}

            # Extract tools used
            tools_used = []
            tool_statuses = []
            bash_commands = []
            for tp in tool_parts:
                state = tp.get("state", {})
                tool_name = tp.get("tool", "")
                tools_used.append(tool_name)
                tool_statuses.append(state.get("status", ""))
                if tool_name == "bash":
                    cmd = safe_get(state, "input", "command", default="")
                    if cmd:
                        bash_commands.append(cmd)

            # Combine text
            combined_text = " ".join(
                p.get("text", "") for p in text_parts if p.get("text")
            )

            time_info = info.get("time", {})

            rows.append({
                "run_id": run_id,
                "session_id": session_id,
                "session_num": session_num,
                "message_idx": msg_idx,
                "message_id": info.get("id", ""),
                "role": role,
                "model_id": info.get("modelID", ""),
                "provider_id": info.get("providerID", ""),
                "agent": info.get("agent", ""),
                "created_ts": ts_to_iso(time_info.get("created")),
                "completed_ts": ts_to_iso(time_info.get("completed")),
                "finish_reason": info.get("finish", ""),
                "tokens_total": tokens.get("total", 0) if tokens else 0,
                "tokens_input": tokens.get("input", 0) if tokens else 0,
                "tokens_output": tokens.get("output", 0) if tokens else 0,
                "tokens_reasoning": tokens.get("reasoning", 0) if tokens else 0,
                "tokens_cache_read": cache.get("read", 0) if cache else 0,
                "tokens_cache_write": cache.get("write", 0) if cache else 0,
                "num_parts": len(parts),
                "num_text_parts": len(text_parts),
                "num_tool_parts": len(tool_parts),
                "tools_used": ";".join(tools_used),
                "tool_statuses": ";".join(tool_statuses),
                "bash_commands_count": len(bash_commands),
                "text_preview": truncate(combined_text, 300),
            })

    return rows


def parse_stdout_tool_calls(stdout_records: list[dict], run_id: str) -> list[dict]:
    """
    Parse opencode_stdout.jsonl into a list of rows (one per tool call).
    """
    rows = []
    call_idx = 0

    for rec in stdout_records:
        evt_type = rec.get("type", "")
        if evt_type != "tool_use":
            continue

        part = rec.get("part", {})
        state = part.get("state", {})
        tool_name = part.get("tool", "")
        call_id = part.get("callID", "")
        session_id = rec.get("sessionID", "")
        message_id = part.get("messageID", "")
        status = state.get("status", "")

        inp = state.get("input", {})
        command = inp.get("command", "") if isinstance(inp, dict) else ""
        description = inp.get("description", "") if isinstance(inp, dict) else ""

        output_raw = state.get("output", "")
        metadata = state.get("metadata", {})
        exit_code = metadata.get("exit", "") if isinstance(metadata, dict) else ""
        truncated_flag = metadata.get("truncated", False) if isinstance(metadata, dict) else False

        time_info = state.get("time", {})
        start_ts = time_info.get("start")
        end_ts = time_info.get("end")
        duration_ms = None
        if start_ts and end_ts:
            try:
                duration_ms = end_ts - start_ts
            except TypeError:
                pass

        rows.append({
            "run_id": run_id,
            "call_idx": call_idx,
            "session_id": session_id,
            "message_id": message_id,
            "call_id": call_id,
            "tool": tool_name,
            "status": status,
            "command": command,
            "description": description,
            "output_preview": truncate(output_raw, 500),
            "output_length": len(output_raw) if output_raw else 0,
            "exit_code": exit_code,
            "output_truncated": truncated_flag,
            "start_ts": ts_to_iso(start_ts),
            "end_ts": ts_to_iso(end_ts),
            "duration_ms": duration_ms if duration_ms is not None else "",
        })
        call_idx += 1

    return rows


# ── CSV writers ───────────────────────────────────────────────────────────────

RUN_SUMMARY_FIELDS = [
    "run_id",
    "run_number",
    "experiment_batch",
    "agent_type",
    "exec_id",
    "host",
    "agent",
    "mode",
    "time_limit",
    "start_ts",
    "end_ts",
    "total_duration_seconds",
    "session_duration_seconds",
    "total_sessions",
    "session_turns",
    "messages_count",
    "agent_done",
    "context_overflow",
    "total_steps",
    "total_tool_calls",
    "total_text_events",
    "bash_calls",
    "unique_tools",
    "tool_counts",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "peak_step_tokens",
    "finish_reasons",
    "goal",
]

STEPS_DETAIL_FIELDS = [
    "run_id",
    "session_id",
    "session_num",
    "message_idx",
    "message_id",
    "role",
    "model_id",
    "provider_id",
    "agent",
    "created_ts",
    "completed_ts",
    "finish_reason",
    "tokens_total",
    "tokens_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_cache_read",
    "tokens_cache_write",
    "num_parts",
    "num_text_parts",
    "num_tool_parts",
    "tools_used",
    "tool_statuses",
    "bash_commands_count",
    "text_preview",
]

TOOL_CALLS_FIELDS = [
    "run_id",
    "call_idx",
    "session_id",
    "message_id",
    "call_id",
    "tool",
    "status",
    "command",
    "description",
    "output_preview",
    "output_length",
    "exit_code",
    "output_truncated",
    "start_ts",
    "end_ts",
    "duration_ms",
]


# ── Main ──────────────────────────────────────────────────────────────────────

def discover_runs(raw_runs_dir: Path) -> list[tuple[str, Path]]:
    """
    Find all run directories and their agent sub-directories.
    Returns list of (run_id, agent_dir_path).
    """
    runs = []
    for entry in sorted(raw_runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Each run may have one or more agent sub-directories
        for agent_dir in sorted(entry.iterdir()):
            if not agent_dir.is_dir():
                continue
            # Check that at least one expected file exists
            timeline_path = agent_dir / "db_admin_timeline.jsonl"
            if timeline_path.exists():
                runs.append((entry.name, agent_dir))
    return runs


def extract_run_metadata(run_id: str) -> dict:
    """
    Extract batch timestamp and run number from run_id.
    Example: db_admin_experiment_20260228_231950_run_001
    """
    parts = run_id.rsplit("_run_", 1)
    batch = parts[0] if len(parts) == 2 else run_id
    run_num = int(parts[1]) if len(parts) == 2 else 0
    return {"experiment_batch": batch, "run_number": run_num}


def main():
    parser = argparse.ArgumentParser(description="Generate CSVs from db_admin raw runs")
    parser.add_argument(
        "--raw-runs-dir",
        type=Path,
        default=DEFAULT_RAW_RUNS,
        help=f"Path to raw_runs directory (default: {DEFAULT_RAW_RUNS})",
    )
    args = parser.parse_args()

    raw_runs_dir = args.raw_runs_dir.resolve()
    if not raw_runs_dir.is_dir():
        print(f"Error: {raw_runs_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    runs = discover_runs(raw_runs_dir)
    if not runs:
        print(f"No runs found in {raw_runs_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(runs)} run(s) in {raw_runs_dir}")

    # Prepare output files
    summary_csv_path = raw_runs_dir / "db_admin_runs_summary.csv"
    steps_csv_path = raw_runs_dir / "db_admin_steps_detail.csv"
    tools_csv_path = raw_runs_dir / "db_admin_tool_calls_detail.csv"

    all_summary_rows = []
    all_steps_rows = []
    all_tools_rows = []

    for run_id, agent_dir in runs:
        agent_type = agent_dir.name
        meta = extract_run_metadata(run_id)
        print(f"  Processing {run_id}/{agent_type} ...")

        # ── 1. Timeline ──────────────────────────────────────────────────
        timeline_path = agent_dir / "db_admin_timeline.jsonl"
        if timeline_path.exists():
            timeline_records = read_jsonl(timeline_path)
            summary = parse_timeline(timeline_records)
        else:
            print(f"    ⚠ Missing db_admin_timeline.jsonl", file=sys.stderr)
            summary = {}

        summary["run_id"] = run_id
        summary["run_number"] = meta["run_number"]
        summary["experiment_batch"] = meta["experiment_batch"]
        summary["agent_type"] = agent_type
        all_summary_rows.append(summary)

        # ── 2. API messages (steps detail) ────────────────────────────────
        api_path = agent_dir / "opencode_api_messages.json"
        if api_path.exists():
            try:
                sessions = read_json(api_path)
                if isinstance(sessions, list):
                    steps_rows = parse_api_messages_steps(sessions, run_id)
                    all_steps_rows.extend(steps_rows)
                else:
                    print(f"    ⚠ opencode_api_messages.json is not a list", file=sys.stderr)
            except json.JSONDecodeError as exc:
                print(f"    ⚠ Malformed opencode_api_messages.json: {exc}", file=sys.stderr)
        else:
            print(f"    ⚠ Missing opencode_api_messages.json", file=sys.stderr)

        # ── 3. Stdout (tool calls detail) ─────────────────────────────────
        stdout_path = agent_dir / "opencode_stdout.jsonl"
        if stdout_path.exists():
            stdout_records = read_jsonl(stdout_path)
            tool_rows = parse_stdout_tool_calls(stdout_records, run_id)
            all_tools_rows.extend(tool_rows)
        else:
            print(f"    ⚠ Missing opencode_stdout.jsonl", file=sys.stderr)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    # 1. Run summary
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RUN_SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_summary_rows:
            writer.writerow(row)
    print(f"\n✓ Run summary:       {summary_csv_path}  ({len(all_summary_rows)} rows)")

    # 2. Steps detail
    with open(steps_csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STEPS_DETAIL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_steps_rows:
            writer.writerow(row)
    print(f"✓ Steps detail:      {steps_csv_path}  ({len(all_steps_rows)} rows)")

    # 3. Tool calls detail
    with open(tools_csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TOOL_CALLS_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in all_tools_rows:
            writer.writerow(row)
    print(f"✓ Tool calls detail: {tools_csv_path}  ({len(all_tools_rows)} rows)")

    print("\nDone.")


if __name__ == "__main__":
    main()
