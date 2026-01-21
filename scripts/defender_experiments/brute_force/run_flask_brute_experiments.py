#!/usr/bin/env python3
"""
Simple Python script to run Flask brute force experiments sequentially.
Each experiment is independent and runs the single experiment script.
"""

import subprocess
import time
import sys
from pathlib import Path
from datetime import datetime

# Configuration
NUM_EXPERIMENTS = 1  # Adjust as needed
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
EXPERIMENT_SCRIPT = SCRIPT_DIR / "run_experiment.sh"
OUTPUT_ROOT = PROJECT_ROOT / "flask_brute_experiment_output"
LOG_FILE = Path("/tmp/flask_brute_runner.log")

def log(message):
    """Log message to both console and file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    with open(LOG_FILE, "a") as f:
        f.write(log_msg + "\n")

def run_experiment(experiment_num):
    """Run a single experiment"""
    # Generate unique experiment ID
    experiment_id = f"flask_brute_{int(time.time())}_run_{experiment_num}"

    log(f"=" * 60)
    log(f"Starting experiment {experiment_num}/{NUM_EXPERIMENTS}")
    log(f"Experiment ID: {experiment_id}")
    log(f"=" * 60)

    try:
        # Run the experiment script from PROJECT_ROOT directory
        result = subprocess.run(
            [str(EXPERIMENT_SCRIPT), experiment_id],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minute timeout
            cwd=str(PROJECT_ROOT)  # Run from project root
        )

        # Log the result
        if result.returncode == 0:
            log(f"✓ Experiment {experiment_num} completed successfully")
        else:
            log(f"✗ Experiment {experiment_num} failed with exit code {result.returncode}")
            if result.stderr:
                log(f"Error output: {result.stderr[:500]}")  # First 500 chars

        # Move results from outputs/ to final location
        source_dir = PROJECT_ROOT / "outputs" / experiment_id
        if source_dir.exists():
            final_dir = OUTPUT_ROOT / f"flask_brute_run_{experiment_num}_{experiment_id}"
            final_dir.parent.mkdir(parents=True, exist_ok=True)

            # Move the directory
            import shutil
            shutil.move(str(source_dir), str(final_dir))
            log(f"✓ Results moved to: {final_dir}")
        else:
            log(f"⚠ Warning: No results directory found at {source_dir}")

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        log(f"✗ Experiment {experiment_num} timed out after 30 minutes")
        return False
    except Exception as e:
        log(f"✗ Experiment {experiment_num} failed with exception: {str(e)}")
        return False

def main():
    """Main execution"""
    start_time = time.time()

    # Create output directory
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Clear log file
    LOG_FILE.write_text("")

    log("=" * 60)
    log("FLASK BRUTE FORCE EXPERIMENT RUNNER STARTED")
    log(f"Running {NUM_EXPERIMENTS} experiments sequentially")
    log(f"Output directory: {OUTPUT_ROOT}")
    log(f"Log file: {LOG_FILE}")
    log("=" * 60)

    successful = 0
    failed = 0

    for i in range(1, NUM_EXPERIMENTS + 1):
        if run_experiment(i):
            successful += 1
        else:
            failed += 1

        # Wait 30 seconds between experiments (except after the last one)
        if i < NUM_EXPERIMENTS:
            log(f"Waiting 30 seconds before next experiment...")
            time.sleep(30)

    # Final summary
    duration = time.time() - start_time
    log("=" * 60)
    log("ALL EXPERIMENTS COMPLETED")
    log(f"Total: {NUM_EXPERIMENTS}")
    log(f"Successful: {successful}")
    log(f"Failed: {failed}")
    log(f"Duration: {duration:.0f}s ({duration/60:.1f} minutes)")
    log(f"Results: {OUTPUT_ROOT}")
    log("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n✗ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"\n✗ Fatal error: {str(e)}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)
