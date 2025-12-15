#!/usr/bin/env python3

"""
Multi-Experiment Orchestrator
Runs multiple defender experiments and aggregates results into a comprehensive JSON report
"""

import json
import os
import sys
import time
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path

# Configuration
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RUN_EXPERIMENT_SCRIPT = SCRIPT_DIR / "run_experiment.sh"
ANALYZE_PCAPS_SCRIPT = SCRIPT_DIR / "analyze_pcaps.py"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

def setup_logging():
    """Set up logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def run_single_experiment(experiment_id, logger, config=None):
    """
    Run a single experiment using the bash script

    Args:
        experiment_id (str): Unique identifier for this experiment
        logger: Logger instance
        config (dict): Configuration overrides

    Returns:
        dict: Experiment result summary or None if failed
    """
    logger.info(f"Starting experiment: {experiment_id}")

    try:
        # Prepare environment variables
        env = os.environ.copy()
        if config:
            for key, value in config.items():
                env[key] = str(value)

        # Run the experiment script
        cmd = [str(RUN_EXPERIMENT_SCRIPT), experiment_id]
        result = subprocess.run(
            cmd,
            env=env,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes timeout
        )

        if result.returncode != 0:
            logger.error(f"Experiment {experiment_id} failed with return code {result.returncode}")
            logger.error(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            return None

        logger.info(f"Experiment {experiment_id} completed successfully")

        # Load experiment summary if available
        summary_file = OUTPUTS_DIR / experiment_id / "experiment_summary.json"
        if summary_file.exists():
            with open(summary_file, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"No experiment summary found for {experiment_id}")
            return {"experiment_id": experiment_id, "status": "completed"}

    except subprocess.TimeoutExpired:
        logger.error(f"Experiment {experiment_id} timed out")
        return None
    except Exception as e:
        logger.error(f"Error running experiment {experiment_id}: {e}")
        return None

def analyze_experiment_pcaps(experiment_id, logger):
    """
    Analyze PCAP files for a completed experiment

    Args:
        experiment_id (str): Experiment identifier
        logger: Logger instance

    Returns:
        dict: Analysis results or None if failed
    """
    logger.info(f"Analyzing PCAPs for experiment: {experiment_id}")

    try:
        pcap_folder = OUTPUTS_DIR / experiment_id / "pcaps"
        if not pcap_folder.exists():
            logger.warning(f"PCAP folder not found for experiment {experiment_id}")
            return None

        # Run analysis script
        cmd = [str(ANALYZE_PCAPS_SCRIPT), str(pcap_folder)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # 2 minutes timeout
        )

        if result.returncode != 0:
            logger.error(f"PCAP analysis failed for {experiment_id}")
            logger.error(f"STDERR: {result.stderr}")
            return None

        # Load analysis results
        analysis_file = pcap_folder / "analysis_result.json"
        if analysis_file.exists():
            with open(analysis_file, 'r') as f:
                return json.load(f)
        else:
            logger.error(f"No analysis result file found for {experiment_id}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"PCAP analysis timed out for {experiment_id}")
        return None
    except Exception as e:
        logger.error(f"Error analyzing PCAPs for {experiment_id}: {e}")
        return None

def run_experiments(num_experiments, config=None, logger=None):
    """
    Run multiple experiments sequentially

    Args:
        num_experiments (int): Number of experiments to run
        config (dict): Configuration for all experiments
        logger: Logger instance

    Returns:
        list: List of experiment results
    """
    if logger is None:
        logger = setup_logging()

    results = []
    successful_experiments = 0

    logger.info(f"Starting {num_experiments} experiments...")

    for i in range(num_experiments):
        experiment_id = f"exp_{int(time.time())}_{i+1:03d}"
        logger.info(f"Experiment {i+1}/{num_experiments}: {experiment_id}")

        # Run experiment
        experiment_result = run_single_experiment(experiment_id, logger, config)
        if experiment_result is None:
            logger.error(f"Failed to run experiment {experiment_id}")
            continue

        # Analyze PCAPs
        analysis_result = analyze_experiment_pcaps(experiment_id, logger)

        # Combine results
        combined_result = {
            "experiment_id": experiment_id,
            "experiment_number": i + 1,
            "experiment_summary": experiment_result,
            "pcap_analysis": analysis_result,
            "timestamp": datetime.now().isoformat()
        }

        results.append(combined_result)
        successful_experiments += 1

        logger.info(f"Experiment {experiment_id} completed successfully")

        # Small delay between experiments
        if i < num_experiments - 1:
            logger.info("Waiting 10 seconds before next experiment...")
            time.sleep(10)

    logger.info(f"Completed {successful_experiments}/{num_experiments} experiments successfully")
    return results

def aggregate_results(results, logger):
    """
    Aggregate results from multiple experiments into a comprehensive report

    Args:
        results (list): List of experiment results
        logger: Logger instance

    Returns:
        dict: Aggregated results
    """
    logger.info("Aggregating experiment results...")

    if not results:
        return {"error": "No successful experiments to aggregate"}

    # Initialize counters
    total_experiments = len(results)
    defender_failures = 0
    defender_warnings = 0
    defender_alerts = 0
    successful_attacks = 0

    # Status tracking
    status_counts = {}
    performance_counts = {}

    # Timing data
    timings = []
    pcap_counts = []

    for result in results:
        if not result.get("pcap_analysis"):
            continue

        analysis = result["pcap_analysis"]
        status = analysis.get("status", "Unknown")
        performance = analysis.get("defender_performance", "Unknown")

        # Count statuses
        status_counts[status] = status_counts.get(status, 0) + 1
        performance_counts[performance] = performance_counts.get(performance, 0) + 1

        # Track defender performance
        if "FAILURE" in performance:
            defender_failures += 1
            successful_attacks += 1
        elif "Critical" in performance or "Warning" in performance:
            defender_warnings += 1
        elif "Alert" in performance:
            defender_alerts += 1

        # Collect timing data
        exp_summary = result.get("experiment_summary", {})
        if "duration_seconds" in exp_summary:
            timings.append(exp_summary["duration_seconds"])

        if "pcap_count" in exp_summary:
            pcap_counts.append(exp_summary["pcap_count"])

    # Calculate statistics
    avg_duration = sum(timings) / len(timings) if timings else 0
    total_pcaps = sum(pcap_counts)

    # Create aggregated report
    aggregated = {
        "summary": {
            "total_experiments": total_experiments,
            "successful_experiments": len(results),
            "timestamp": datetime.now().isoformat(),
            "avg_duration_seconds": avg_duration,
            "total_pcaps_analyzed": total_pcaps
        },
        "defender_performance": {
            "total_failures": defender_failures,
            "failure_rate": defender_failures / total_experiments if total_experiments > 0 else 0,
            "critical_warnings": defender_warnings,
            "alerts": defender_alerts,
            "successful_attacks": successful_attacks
        },
        "status_breakdown": status_counts,
        "performance_breakdown": performance_counts,
        "detailed_results": results,
        "recommendations": generate_recommendations(defender_failures, total_experiments, performance_counts)
    }

    return aggregated

def generate_recommendations(failures, total, performance_counts):
    """
    Generate recommendations based on experiment results

    Args:
        failures (int): Number of defender failures
        total (int): Total experiments
        performance_counts (dict): Performance status breakdown

    Returns:
        list: List of recommendations
    """
    recommendations = []

    failure_rate = failures / total if total > 0 else 0

    if failure_rate > 0.5:
        recommendations.append("HIGH PRIORITY: Defender failure rate > 50%. Consider immediate security rule updates.")
    elif failure_rate > 0.2:
        recommendations.append("MEDIUM PRIORITY: Defender failure rate > 20%. Review and enhance detection rules.")
    elif failure_rate > 0:
        recommendations.append("LOW PRIORITY: Some attacks succeeded. Consider fine-tuning defender sensitivity.")

    if performance_counts.get("Passive - Server Discovered", 0) > 0:
        recommendations.append("Consider implementing early detection for network reconnaissance activities.")

    if performance_counts.get("Alert - SSH Port Scanned", 0) > 0:
        recommendations.append("Port scanning detection is working. Consider implementing automatic blocking.")

    if performance_counts.get("Critical - SSH Brute Force Detected", 0) > 0:
        recommendations.append("Brute force detection is working. Ensure automatic IP blocking is enabled.")

    if not recommendations:
        recommendations.append("Defender appears to be performing well across all test scenarios.")

    return recommendations

def save_results(results, output_file, logger):
    """
    Save aggregated results to JSON file

    Args:
        results (dict): Aggregated results
        output_file (str): Output file path
        logger: Logger instance
    """
    try:
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=4, default=str)
        logger.info(f"Results saved to: {output_file}")
    except Exception as e:
        logger.error(f"Failed to save results: {e}")

def main():
    parser = argparse.ArgumentParser(description='Run multiple defender experiments')
    parser.add_argument('num_experiments', type=int, help='Number of experiments to run')
    parser.add_argument('--output', '-o', default='multi_experiment_results.json',
                        help='Output JSON file (default: multi_experiment_results.json)')
    parser.add_argument('--config', '-c', help='JSON configuration file')
    parser.add_argument('--pcap-rotate-secs', type=int, help='PCAP rotation interval in seconds')
    parser.add_argument('--lab-password', help='Lab password for containers')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suppress logging output')

    args = parser.parse_args()

    # Set up logging
    logger = setup_logging()
    if args.quiet:
        logger.setLevel(logging.WARNING)

    # Load configuration
    config = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = json.load(f)

    # Override with command line arguments
    if args.pcap_rotate_secs:
        config['PCAP_ROTATE_SECS'] = args.pcap_rotate_secs
    if args.lab_password:
        config['LAB_PASSWORD'] = args.lab_password

    logger.info(f"Starting {args.num_experiments} experiments with configuration: {config}")

    # Create outputs directory if it doesn't exist
    OUTPUTS_DIR.mkdir(exist_ok=True)

    # Run experiments
    start_time = time.time()
    results = run_experiments(args.num_experiments, config, logger)
    end_time = time.time()

    if not results:
        logger.error("No experiments completed successfully")
        sys.exit(1)

    # Aggregate results
    logger.info("Aggregating results...")
    aggregated_results = aggregate_results(results, logger)

    # Add execution metadata
    aggregated_results['execution_metadata'] = {
        'start_time': datetime.fromtimestamp(start_time).isoformat(),
        'end_time': datetime.fromtimestamp(end_time).isoformat(),
        'total_duration_seconds': end_time - start_time,
        'args': vars(args)
    }

    # Save results
    save_results(aggregated_results, args.output, logger)

    # Print summary
    summary = aggregated_results['summary']
    defender_perf = aggregated_results['defender_performance']

    print(f"\n{'='*60}")
    print("EXPERIMENT SUMMARY")
    print(f"{'='*60}")
    print(f"Total experiments: {summary['total_experiments']}")
    print(f"Successful experiments: {summary['successful_experiments']}")
    print(f"Total duration: {summary['avg_duration_seconds']:.1f}s average")
    print(f"Total PCAPs analyzed: {summary['total_pcaps_analyzed']}")
    print(f"\nDEFENDER PERFORMANCE:")
    print(f"  Failures: {defender_perf['total_failures']} ({defender_perf['failure_rate']:.1%})")
    print(f"  Critical warnings: {defender_perf['critical_warnings']}")
    print(f"  Alerts: {defender_perf['alerts']}")
    print(f"  Successful attacks: {defender_perf['successful_attacks']}")

    print(f"\nRECOMMENDATIONS:")
    for rec in aggregated_results['recommendations']:
        print(f"  • {rec}")

    print(f"\nDetailed results saved to: {args.output}")

if __name__ == "__main__":
    main()