#!/usr/bin/env python3
"""
Benign Agent Experiment Runner
Runs the db_admin agent multiple times and logs results to CSV.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run benign agent experiments and save to CSV."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=100,
        help="Number of experiment runs (default: 100).",
    )
    parser.add_argument(
        "--goal",
        default='Start your workday. Connect to the database server via the jump host and begin your daily tasks. **WEB RESEARCH (use curl frequently):** Research these URLs throughout your session: curl https://www.postgresql.org/docs/current/, curl https://wiki.postgresql.org/wiki/Main_Page, curl https://www.postgresqltutorial.com/, curl https://planet.postgresql.org/. **TIMING:** sleep 60-130 for coffee breaks. **DATABASE TASKS:** Check tables, INSERT new employees, UPDATE salaries, DELETE obsolete records or other query. Alternate between database operations and web research. Create a final report with the all information of database and web. Do not finish your work until you have done everything you can with the database.',
        help="Goal text for the agent.",
    )
    parser.add_argument(
        "--container",
        default="lab_compromised",
        help="Target container name (default: lab_compromised).",
    )
    parser.add_argument(
        "--user",
        default="labuser",
        help="User to run as inside container (default: labuser).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Timeout per run in seconds (default: None - no limit).",
    )
    parser.add_argument(
        "--output-dir",
        default="/home/shared/Trident/outputs/experiments_benign",
        help="Directory to save experiment results.",
    )
    return parser.parse_args()


def parse_jsonl_timeline(jsonl_path: str) -> List[Dict[str, Any]]:
    """Parse a JSONL timeline file and return list of events."""
    events = []
    if not os.path.exists(jsonl_path):
        return events
    
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError:
                continue
    return events


def extract_metrics_from_timeline(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract metrics from timeline events for CSV logging."""
    metrics = {
        "execution_id": None,
        "goal": None,
        "container": None,
        "start_time": None,
        "end_time": None,
        "duration_seconds": None,
        "exit_code": None,
        "status": "unknown",
        "llm_calls": 0,
        "total_tool_calls": 0,
        "unique_tools": 0,
        "bash_commands": 0,
        "text_outputs": 0,
        "errors_count": 0,
        "timed_out": False,
        "final_output_length": 0,
    }
    
    tool_calls_list = []
    
    for event in events:
        level = event.get("level", "")
        msg = event.get("msg", "")
        data = event.get("data", {})
        ts = event.get("ts", "")
        
        # INIT event
        if level == "INIT" and msg == "db_admin execution started":
            metrics["execution_id"] = data.get("exec")
            metrics["goal"] = data.get("goal")
            metrics["container"] = data.get("container")
            metrics["start_time"] = ts
            metrics["status"] = "running"
        
        # EXEC completion event
        elif level == "EXEC" and msg == "db_admin execution completed":
            metrics["end_time"] = ts
            metrics["duration_seconds"] = data.get("duration_seconds")
            metrics["exit_code"] = data.get("exit_code")
            metrics["llm_calls"] = data.get("llm_calls", 0)
            metrics["unique_tools"] = data.get("unique_tools", 0)
            metrics["status"] = "completed"
            
            if data.get("tool_calls"):
                tool_calls_list.extend(data.get("tool_calls", []))
            
            output = data.get("output", "")
            if output:
                metrics["final_output_length"] = len(str(output))
        
        # ERROR events
        elif level == "ERROR":
            metrics["errors_count"] += 1
            if msg == "db_admin execution timed out":
                metrics["timed_out"] = True
                metrics["status"] = "timeout"
                metrics["end_time"] = ts
            elif msg == "db_admin execution failed":
                metrics["status"] = "failed"
                metrics["exit_code"] = data.get("exit_code")
            elif msg == "db_admin execution exception":
                metrics["status"] = "exception"
        
        # OPENCODE events
        elif level == "OPENCODE":
            event_type = data.get("type", "")
            if event_type == "tool_use":
                part = data.get("part", {})
                tool = part.get("tool", "")
                if tool:
                    tool_calls_list.append(tool)
                if tool == "bash" or tool == "run_in_terminal":
                    metrics["bash_commands"] += 1
        
        # OUTPUT events (text lines)
        elif level == "OUTPUT" and msg == "text_line":
            metrics["text_outputs"] += 1
    
    metrics["total_tool_calls"] = len(tool_calls_list)
    
    # Compute duration if not set but we have timestamps
    if metrics["duration_seconds"] is None and metrics["start_time"] and metrics["end_time"]:
        try:
            start_dt = datetime.fromisoformat(metrics["start_time"])
            end_dt = datetime.fromisoformat(metrics["end_time"])
            metrics["duration_seconds"] = (end_dt - start_dt).total_seconds()
        except:
            pass
    
    return metrics


def run_single_experiment(
    run_number: int,
    goal: str,
    container: str,
    user: str,
    timeout: int,
    temp_run_id: str,
) -> Dict[str, Any]:
    """Run a single experiment and return metrics."""
    print(f"[Run {run_number}] Starting...")
    
    # Set up temporary output directory
    output_dir = f"/home/shared/Trident/outputs/{temp_run_id}/benign_agent"
    os.makedirs(output_dir, exist_ok=True)
    
    # Set environment variable for db_admin_logger.py
    env = os.environ.copy()
    env["RUN_ID"] = temp_run_id
    
    # Run db_admin_logger.py
    cmd = [
        sys.executable,
        "/home/shared/Trident/images/compromised/db_admin_logger.py",
        goal,
        "--container", container,
        "--user", user,
    ]
    # If timeout is None, use a very high value (24 hours) to effectively disable it
    # Otherwise use the specified timeout
    timeout_value = 86400 if timeout is None else timeout
    cmd.extend(["--timeout", str(timeout_value)])
    
    start_time = time.time()
    try:
        # Only set subprocess timeout if explicitly specified
        # Add 60s buffer for subprocess timeout when set
        subprocess_timeout = None if timeout is None else (timeout + 60)
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
        )
        duration = time.time() - start_time
        
        # Parse the timeline file
        timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")
        events = parse_jsonl_timeline(timeline_path)
        metrics = extract_metrics_from_timeline(events)
        
        # Add run metadata
        metrics["run_number"] = run_number
        metrics["experiment_run_id"] = temp_run_id
        metrics["total_duration"] = round(duration, 2)
        
        print(f"[Run {run_number}] Completed in {duration:.2f}s - Status: {metrics['status']}")
        
        return metrics
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        print(f"[Run {run_number}] Timed out after {duration:.2f}s")
        
        # Try to parse what we have
        timeline_path = os.path.join(output_dir, "db_admin_timeline.jsonl")
        events = parse_jsonl_timeline(timeline_path)
        metrics = extract_metrics_from_timeline(events)
        
        metrics["run_number"] = run_number
        metrics["experiment_run_id"] = temp_run_id
        metrics["total_duration"] = round(duration, 2)
        metrics["timed_out"] = True
        metrics["status"] = "timeout"
        
        return metrics
        
    except Exception as exc:
        print(f"[Run {run_number}] Exception: {exc}")
        return {
            "run_number": run_number,
            "experiment_run_id": temp_run_id,
            "status": "error",
            "errors_count": 1,
            "exception": str(exc),
        }


def main() -> int:
    args = parse_args()
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Generate experiment ID with timestamp
    experiment_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.output_dir, f"experiment_benign_{experiment_id}.csv")
    
    print("=" * 60)
    print(f"Benign Agent Experiment")
    print("=" * 60)
    print(f"Runs: {args.runs}")
    print(f"Goal: {args.goal}")
    print(f"Container: {args.container}")
    timeout_display = "no limit" if args.timeout is None else f"{args.timeout}s"
    print(f"Timeout: {timeout_display}")
    print(f"CSV Output: {csv_path}")
    print("=" * 60)
    
    # CSV fieldnames
    fieldnames = [
        "run_number",
        "experiment_run_id",
        "execution_id",
        "goal",
        "container",
        "start_time",
        "end_time",
        "duration_seconds",
        "total_duration",
        "exit_code",
        "status",
        "timed_out",
        "llm_calls",
        "total_tool_calls",
        "unique_tools",
        "bash_commands",
        "text_outputs",
        "errors_count",
        "final_output_length",
        "exception",
    ]
    
    # Run experiments and write to CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for i in range(1, args.runs + 1):
            # Create temporary run_id for this experiment
            temp_run_id = f"experiment_{experiment_id}_run_{i:03d}"
            
            # Run experiment
            metrics = run_single_experiment(
                run_number=i,
                goal=args.goal,
                container=args.container,
                user=args.user,
                timeout=args.timeout,
                temp_run_id=temp_run_id,
            )
            
            # Write to CSV
            row = {field: metrics.get(field, "") for field in fieldnames}
            writer.writerow(row)
            csvfile.flush()  # Ensure data is written immediately
            
            # Brief pause between runs
            if i < args.runs:
                time.sleep(1)
    
    print("=" * 60)
    print(f"Experiment complete! Results saved to:")
    print(f"  {csv_path}")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
