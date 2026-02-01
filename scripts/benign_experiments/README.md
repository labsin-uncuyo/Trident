# Benign Agent Experiments

This directory contains scripts for running controlled experiments with the benign db_admin agent.

## Overview

The `run_experiment.py` script runs the benign agent multiple times and logs structured results to CSV format for analysis and graphing.

## Usage

### Basic Usage (100 runs with default goal)

```bash
python scripts/benign_experiments/run_experiment.py
```

### Custom Number of Runs

```bash
python scripts/benign_experiments/run_experiment.py --runs 50
```

### Custom Goal

```bash
python scripts/benign_experiments/run_experiment.py --goal "Perform database maintenance tasks"
```

### Custom Timeout (Optional - by default no limit)

```bash
# Set a 5-minute timeout
python scripts/benign_experiments/run_experiment.py --timeout 300
```

### All Options Combined

```bash
python scripts/benign_experiments/run_experiment.py \
    --runs 100 \
    --goal "Start your workday. Connect to the database server via the jump host..." \
    --container lab_compromised \
    --user labuser \
    --timeout 600 \
    --output-dir /home/shared/Trident/outputs/experiments_benign
```

## Output

The script generates:

1. **CSV file**: `outputs/experiments_benign/experiment_benign_{timestamp}.csv`
   - Contains structured data from all runs
   - Each row represents one experiment run
   - Includes metrics like duration, tool calls, LLM calls, errors, etc.

2. **Individual run logs**: `outputs/experiment_{timestamp}_run_{number}/benign_agent/`
   - `db_admin_timeline.jsonl` - Full event timeline in JSONL format
   - `opencode_stdout.jsonl` - Raw stdout from OpenCode
   - `opencode_stderr.log` - Raw stderr from OpenCode

## CSV Columns

The CSV output includes the following columns:

- `run_number`: Sequential run number (1 to N)
- `experiment_run_id`: Unique identifier for this specific run
- `execution_id`: Short execution ID from db_admin_logger
- `goal`: The goal text provided to the agent
- `container`: Container name where agent ran
- `start_time`: ISO 8601 timestamp when execution started
- `end_time`: ISO 8601 timestamp when execution ended
- `duration_seconds`: Duration reported by db_admin_logger
- `total_duration`: Total wall-clock duration including overhead
- `exit_code`: Process exit code
- `status`: Execution status (completed, timeout, failed, exception)
- `timed_out`: Boolean indicating if execution timed out
- `llm_calls`: Number of LLM calls made
- `total_tool_calls`: Total number of tool calls
- `unique_tools`: Number of unique tools used
- `bash_commands`: Number of bash/terminal commands executed
- `text_outputs`: Number of text output lines
- `errors_count`: Number of errors encountered
- `final_output_length`: Length of final output text
- `exception`: Exception message if any

## Log Format

The timeline logs follow the same format as regular benign agent runs:

```jsonl
{"ts":"2026-01-27T10:00:00.000000+00:00","level":"INIT","msg":"db_admin execution started","data":{"goal":"go work","container":"lab_compromised","exec":"abc12345"}}
{"ts":"2026-01-27T10:00:01.000000+00:00","level":"OUTPUT","msg":"text_line","exec":"abc12345","data":{"text":"Starting morning checks..."}}
{"ts":"2026-01-27T10:00:05.000000+00:00","level":"OPENCODE","msg":"tool_use","exec":"abc12345","data":{"type":"tool_use","part":{"tool":"bash"}}}
{"ts":"2026-01-27T10:10:00.000000+00:00","level":"EXEC","msg":"db_admin execution completed","data":{"exit_code":0,"duration_seconds":598.45,...}}
```

## Analysis

You can use the CSV output for:

- Performance analysis (duration distributions)
- Success rate calculations
- Tool usage patterns
- Error rate tracking
- Graphing trends over multiple runs

Example Python analysis:

```python
import pandas as pd
import matplotlib.pyplot as plt

# Load results
df = pd.read_csv('outputs/experiments_benign/experiment_benign_20260127_100000.csv')

# Basic statistics
print(df['status'].value_counts())
print(df['duration_seconds'].describe())

# Plot duration distribution
df['duration_seconds'].hist(bins=30)
plt.xlabel('Duration (seconds)')
plt.ylabel('Frequency')
plt.title('Benign Agent Execution Time Distribution')
plt.show()
```

## Requirements

- Docker containers must be running (`make up`)
- `lab_compromised` container must be accessible
- OpenCode must be installed in the container
- Sufficient disk space for logs

## Notes

- Each run creates a separate temporary RUN_ID to isolate logs
- The script includes a 1-second pause between runs
- Failed runs are still logged with available metrics
- The script flushes CSV data after each run for real-time monitoring
