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
NUM_EXPERIMENTS = 100  # Adjust as needed
SCRIPT_DIR = Path(__file__).parent
# Go up from scripts/defender_experiments/brute_force/ to project root
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
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
            [str(EXPERIMENT_SCRIPT.resolve()), experiment_id],
            capture_output=True,
            text=True,
            timeout=4200,  # 70 minutes - allow time for experiment + OpenCode completion
            cwd=str(PROJECT_ROOT.resolve())  # Run from project root
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

def cleanup_containers():
    """Clean up containers and volumes between experiments"""
    log("Cleaning up containers and volumes...")
    try:
        # Stop and remove containers using make
        result = subprocess.run(
            ["make", "down"],
            cwd=str(PROJECT_ROOT.resolve()),
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            log(f"⚠ make down returned: {result.stderr}")

        # Force remove all lab containers
        for container in ["lab_slips_defender", "lab_server", "lab_compromised", "lab_router"]:
            subprocess.run(
                ["docker", "rm", "-f", container],
                capture_output=True,
                text=True,
                timeout=30
            )

        # Try docker compose down with volumes (use 'docker compose' not 'docker-compose')
        try:
            result = subprocess.run(
                ["docker", "compose", "down", "-v", "--remove-orphans"],
                cwd=str(PROJECT_ROOT.resolve()),
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                log(f"⚠ docker compose down returned: {result.stderr}")
        except FileNotFoundError:
            # docker compose not available, skip
            pass

        # Explicitly remove named volumes to ensure clean state
        named_volumes = [
            "lab_auto_responder_ssh_keys",
            "lab_opencode_data",
            "lab_postgres_data",
            "lab_slips_redis_data",
            "lab_slips_ti_data"
        ]
        for volume in named_volumes:
            subprocess.run(
                ["docker", "volume", "rm", "-f", volume],
                capture_output=True,
                text=True,
                timeout=30
            )

        log("✓ Containers and volumes cleaned")
        time.sleep(5)  # Wait for cleanup to complete
    except Exception as e:
        log(f"⚠ Warning: Container cleanup failed: {str(e)}")

def main():
    """Main execution"""
    start_time = time.time()

    # Create output directory
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Clear log file
    LOG_FILE.write_text("")

    # Clean up any existing containers before starting
    cleanup_containers()

    log("=" * 60)
    log("FLASK BRUTE FORCE EXPERIMENT RUNNER STARTED")
    log(f"Running {NUM_EXPERIMENTS} experiments sequentially")
    log(f"Output directory: {OUTPUT_ROOT}")
    log(f"Log file: {LOG_FILE}")
    log("=" * 60)

    successful = 0
    failed = 0

    for i in range(1, NUM_EXPERIMENTS + 1):
        # Clean up before each experiment
        cleanup_containers()

        if run_experiment(i):
            successful += 1
        else:
            failed += 1

        # Clean up after each experiment
        cleanup_containers()

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

    # Final cleanup
    cleanup_containers()

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
