#!/usr/bin/env python3
"""
Experiment runner for benign agent executions.

Runs the benign agent multiple times and collects logs for analysis.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def get_trident_root():
    """Get the Trident project root directory."""
    script_dir = Path(__file__).parent
    # images/compromised -> Trident root
    return script_dir.parent.parent


def generate_run_id():
    """Generate a unique RUN_ID based on timestamp."""
    return f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def check_progress(run_id: str, outputs_dir: Path):
    """Check the progress of the current execution."""
    log_dir = outputs_dir / run_id / "benign_agent"
    
    if not log_dir.exists():
        return {"status": "not_started"}
    
    # Check for timeline file
    timeline_file = log_dir / "db_admin_timeline.jsonl"
    if not timeline_file.exists():
        return {"status": "running", "events": 0}
    
    # Parse timeline to get status
    events = []
    try:
        with open(timeline_file) as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
    except Exception as e:
        return {"status": "reading", "error": str(e), "events": len(events)}
    
    # Extract key information
    status = {
        "status": "running",
        "events": len(events),
        "sessions": 0,
        "tool_calls": 0,
        "errors": 0,
    }
    
    for event in events:
        event_type = event.get("type", "")
        
        if event_type == "SESSION":
            status["sessions"] += 1
        elif event_type == "tool_use":
            status["tool_calls"] += 1
        elif event_type in ("error", "ERROR"):
            status["errors"] += 1
        elif event_type == "DONE":
            status["status"] = "completed"
    
    return status


def run_single_execution(execution_num: int, total: int, outputs_dir: Path, goal: str = None):
    """Run a single benign execution."""
    run_id = generate_run_id()
    
    print(f"\n{'='*70}")
    print(f"Execution {execution_num}/{total}")
    print(f"RUN_ID: {run_id}")
    print(f"{'='*70}")
    
    # Create output directory
    log_dir = outputs_dir / run_id / "benign_agent"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Write RUN_ID to .current_run
    current_run_file = outputs_dir / ".current_run"
    with open(current_run_file, "w") as f:
        f.write(run_id)
    
    # Build the make command
    cmd = ["make", "benign"]
    if goal:
        cmd.append(f"GOAL={goal}")
    
    trident_root = get_trident_root()
    
    print(f"Starting execution at {datetime.now().strftime('%H:%M:%S')}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Log directory: {log_dir}")
    print()
    
    # Run the command
    start_time = time.time()
    last_progress_check = 0
    
    try:
        process = subprocess.Popen(
            cmd,
            cwd=trident_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        
        # Stream output and check progress
        for line in process.stdout:
            print(line, end="")
            
            # Check progress every 30 seconds
            elapsed = time.time() - start_time
            if elapsed - last_progress_check >= 30:
                last_progress_check = elapsed
                progress = check_progress(run_id, outputs_dir)
                print(f"\n[Progress Check @ {elapsed:.0f}s]")
                print(f"  Status: {progress['status']}")
                print(f"  Events: {progress.get('events', 0)}")
                print(f"  Sessions: {progress.get('sessions', 0)}")
                print(f"  Tool calls: {progress.get('tool_calls', 0)}")
                print(f"  Errors: {progress.get('errors', 0)}")
                print()
        
        process.wait()
        duration = time.time() - start_time
        
        print(f"\n{'='*70}")
        print(f"Execution {execution_num} completed")
        print(f"Duration: {duration:.1f}s ({duration/60:.1f} minutes)")
        print(f"Exit code: {process.returncode}")
        
        # Final progress check
        final_progress = check_progress(run_id, outputs_dir)
        print(f"\nFinal status:")
        print(f"  Sessions: {final_progress.get('sessions', 0)}")
        print(f"  Tool calls: {final_progress.get('tool_calls', 0)}")
        print(f"  Errors: {final_progress.get('errors', 0)}")
        print(f"{'='*70}")
        
        return {
            "execution": execution_num,
            "run_id": run_id,
            "duration": duration,
            "exit_code": process.returncode,
            "final_status": final_progress,
        }
        
    except Exception as e:
        print(f"\nERROR: Execution failed with exception: {e}")
        return {
            "execution": execution_num,
            "run_id": run_id,
            "duration": time.time() - start_time,
            "exit_code": -1,
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Run benign agent experiments multiple times"
    )
    parser.add_argument(
        "num_executions",
        type=int,
        help="Number of times to run the benign agent",
    )
    parser.add_argument(
        "--goal",
        type=str,
        default=None,
        help="Custom goal for the agent (default: use built-in goal)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: Trident/outputs)",
    )
    
    args = parser.parse_args()
    
    # Determine outputs directory
    if args.output_dir:
        outputs_dir = Path(args.output_dir)
    else:
        outputs_dir = get_trident_root() / "outputs"
    
    outputs_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"{'='*70}")
    print(f"Benign Agent Experiment Runner")
    print(f"{'='*70}")
    print(f"Number of executions: {args.num_executions}")
    print(f"Output directory: {outputs_dir}")
    if args.goal:
        print(f"Custom goal: {args.goal}")
    else:
        print(f"Goal: Built-in default")
    print(f"{'='*70}")
    
    # Run experiments
    results = []
    total_start = time.time()
    
    for i in range(1, args.num_executions + 1):
        result = run_single_execution(i, args.num_executions, outputs_dir, args.goal)
        results.append(result)
        
        # Small delay between executions
        if i < args.num_executions:
            print(f"\nWaiting 5 seconds before next execution...")
            time.sleep(5)
    
    total_duration = time.time() - total_start
    
    # Print summary
    print(f"\n{'='*70}")
    print(f"EXPERIMENT SUMMARY")
    print(f"{'='*70}")
    print(f"Total executions: {len(results)}")
    print(f"Total duration: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
    print(f"Average duration: {total_duration/len(results):.1f}s per execution")
    print()
    
    # Detailed results
    successful = sum(1 for r in results if r.get("exit_code") == 0)
    failed = len(results) - successful
    
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print()
    
    # Tool call statistics
    total_tool_calls = sum(
        r.get("final_status", {}).get("tool_calls", 0)
        for r in results
    )
    total_sessions = sum(
        r.get("final_status", {}).get("sessions", 0)
        for r in results
    )
    
    print(f"Total tool calls: {total_tool_calls}")
    print(f"Total sessions: {total_sessions}")
    print(f"Average tool calls per execution: {total_tool_calls/len(results):.1f}")
    print()
    
    # Save results to JSON
    results_file = outputs_dir / "experiment_results.json"
    with open(results_file, "w") as f:
        json.dump({
            "config": {
                "num_executions": args.num_executions,
                "goal": args.goal,
                "output_dir": str(outputs_dir),
            },
            "summary": {
                "total_duration": total_duration,
                "successful": successful,
                "failed": failed,
                "total_tool_calls": total_tool_calls,
                "total_sessions": total_sessions,
            },
            "results": results,
        }, f, indent=2)
    
    print(f"Results saved to: {results_file}")
    print(f"{'='*70}")
    
    return 0 if successful == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
