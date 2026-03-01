#!/usr/bin/env python3
"""
Run multiple executions of the db_admin benign agent and collect logs.

For each run the script:
  1. Assigns a unique RUN_ID  (<prefix>_run_NNN)
  2. Optionally recreates infra via `make up` when --isolate is set
  3. Invokes db_admin_opencode_client.py with the requested --time-limit
  4. Mirrors the produced logs into
       experiments_db_admin/raw_runs/<RUN_ID>/benign_agent/

Usage example (30 minute time-limit, 5 runs):
  python3 scripts/db_admin_experiments/run_experiment.py \\
      --runs 5 --time-limit 1800

See --help for the full list of options.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def run_cmd(cmd: List[str], check: bool = True,
            env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True,
                          env=env)


def trident_root() -> str:
    """Return the absolute path to the Trident workspace root."""
    # This script lives at <root>/scripts/db_admin_experiments/run_experiment.py
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", ".."))


def write_current_run(root: str, run_id: str) -> None:
    outputs_dir = os.path.join(root, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    with open(os.path.join(outputs_dir, ".current_run"), "w",
              encoding="utf-8") as fh:
        fh.write(run_id)


def ensure_output_dirs(root: str, run_id: str) -> str:
    """Pre-create the output directories that make up would normally create."""
    benign_dir = os.path.join(root, "outputs", run_id, "benign_agent")
    for sub in (
        os.path.join(root, "outputs", run_id, "pcaps"),
        os.path.join(root, "outputs", run_id, "slips"),
        os.path.join(root, "outputs", run_id, "aracne"),
        benign_dir,
    ):
        os.makedirs(sub, exist_ok=True)
    return benign_dir


def wait_for_health(container: str, max_wait: int = 180) -> bool:
    start = time.time()
    while time.time() - start < max_wait:
        result = subprocess.run(
            ["docker", "inspect", "-f",
             "{{.State.Health.Status}}", container],
            capture_output=True, text=True,
        )
        if (result.stdout or "").strip() == "healthy":
            return True
        time.sleep(3)
    return False


def ensure_infra_ready() -> None:
    for container in ("lab_router", "lab_server", "lab_compromised"):
        if not wait_for_health(container):
            raise RuntimeError(
                f"{container} not healthy after waiting 180 s")


def restore_infra(mode: str) -> Tuple[bool, float, Optional[str]]:
    """Restore containers after a run.  Returns (ok, elapsed_s, error)."""
    if mode == "none":
        return True, 0.0, None

    start = time.time()
    try:
        if mode == "compromised":
            result = subprocess.run(
                ["docker", "compose", "up", "-d", "--no-deps",
                 "--force-recreate", "compromised"],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"docker compose recreate compromised failed: "
                    f"{(result.stderr or result.stdout or '').strip()}")
            if not wait_for_health("lab_compromised"):
                raise RuntimeError(
                    "lab_compromised not healthy after compromised restore")
            return True, round(time.time() - start, 2), None

        if mode == "core":
            result = subprocess.run(
                ["docker", "compose", "up", "-d", "--no-deps",
                 "--force-recreate", "router", "server", "compromised"],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"docker compose recreate core failed: "
                    f"{(result.stderr or result.stdout or '').strip()}")
            ensure_infra_ready()
            return True, round(time.time() - start, 2), None

        raise RuntimeError(f"Unknown restore mode: {mode}")
    except Exception as exc:
        return False, round(time.time() - start, 2), str(exc)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run N executions of the db_admin benign agent.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--runs", type=int, default=100,
        help="Total number of agent executions.",
    )
    parser.add_argument(
        "--time-limit", type=int, default=1800,
        help=(
            "Per-run time limit in seconds passed to db_admin_opencode_client.py. "
            "All runs share the same limit. "
            "Example: 1800 = 30 minutes."
        ),
    )
    parser.add_argument(
        "--cooldown", type=int, default=5,
        help="Seconds to wait between consecutive runs.",
    )
    parser.add_argument(
        "--output-dir", default="experiments_db_admin",
        help=(
            "Top-level directory for experiment outputs. "
            "Relative paths are resolved from the Trident workspace root."
        ),
    )
    parser.add_argument(
        "--run-id-prefix", default="db_admin_experiment",
        help="Prefix prepended to every RUN_ID.",
    )
    parser.add_argument(
        "--host", default=None,
        help=(
            "OpenCode server host (forwarded to db_admin_opencode_client.py). "
            "Defaults to the client's built-in value (172.30.0.10)."
        ),
    )
    parser.add_argument(
        "--isolate", action="store_true",
        help=(
            "Run `make down && RUN_ID=<id> make up` before each execution "
            "to guarantee a fully-fresh infrastructure state."
        ),
    )
    parser.add_argument(
        "--restore-mode",
        choices=["none", "compromised", "core"],
        default="compromised",
        help=(
            "How to restore infra after each run (skipped when --isolate is "
            "used, since the next iteration runs make up anyway): "
            "'compromised' recreates only lab_compromised, "
            "'core' recreates router/server/compromised, "
            "'none' skips restore."
        ),
    )
    parser.add_argument(
        "--restore-after-last", action="store_true",
        help="Also restore infrastructure after the final run.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:  # noqa: C901  (intentionally long, like run_experiment.py)
    args = parse_args()
    root = trident_root()
    timestamp = now_utc().strftime("%Y%m%d_%H%M%S")

    # Resolve output directory relative to the workspace root when relative.
    if os.path.isabs(args.output_dir):
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(root, args.output_dir)

    raw_runs_dir = os.path.join(output_dir, "raw_runs")
    os.makedirs(raw_runs_dir, exist_ok=True)

    db_admin_script = os.path.join(
        root, "images", "compromised", "db_admin_opencode_client.py")
    if not os.path.isfile(db_admin_script):
        print(f"[db_admin_exp] ERROR: agent script not found: {db_admin_script}",
              file=sys.stderr)
        return 1

    print(f"[db_admin_exp] Trident root  : {root}")
    print(f"[db_admin_exp] Output dir    : {output_dir}")
    print(f"[db_admin_exp] Raw runs dir  : {raw_runs_dir}")
    print(f"[db_admin_exp] Runs          : {args.runs}")
    print(f"[db_admin_exp] Time-limit    : {args.time_limit}s "
          f"({args.time_limit / 60:.1f} min) per run")
    print(f"[db_admin_exp] Restore mode  : {args.restore_mode}")
    print(f"[db_admin_exp] Isolate       : {args.isolate}")
    print()

    # When not using --isolate we need infra already running.
    if not args.isolate:
        print("[db_admin_exp] Checking infrastructure health...")
        try:
            ensure_infra_ready()
        except RuntimeError as exc:
            print(f"[db_admin_exp] WARNING: {exc} – continuing anyway",
                  file=sys.stderr)

    failures = 0

    for run_number in range(1, args.runs + 1):
        run_id = (
            f"{args.run_id_prefix}_{timestamp}_run_{run_number:03d}"
        )
        run_start = now_utc()
        print(f"\n{'=' * 70}")
        print(f"[db_admin_exp] Run {run_number}/{args.runs}  RUN_ID={run_id}")
        print(f"[db_admin_exp] Started at {run_start.isoformat()}")
        print(f"{'=' * 70}")

        # ── Infrastructure setup ──────────────────────────────────────
        if args.isolate:
            env_for_make = os.environ.copy()
            env_for_make["RUN_ID"] = run_id
            print(f"[db_admin_exp] make down ...")
            subprocess.run(["make", "down"], check=False, cwd=root,
                           env=env_for_make)
            print(f"[db_admin_exp] make up (RUN_ID={run_id}) ...")
            result_up = subprocess.run(["make", "up"], check=False, cwd=root,
                                       env=env_for_make)
            if result_up.returncode != 0:
                print(f"[db_admin_exp] ERROR: make up failed for run "
                      f"{run_number}", file=sys.stderr)
                failures += 1
                continue
            try:
                ensure_infra_ready()
            except RuntimeError as exc:
                print(f"[db_admin_exp] ERROR: infra not ready after make up: "
                      f"{exc}", file=sys.stderr)
                failures += 1
                continue
        else:
            # Write RUN_ID so the agent resolves the right output directory.
            write_current_run(root, run_id)
            ensure_output_dirs(root, run_id)

        # ── Run agent ─────────────────────────────────────────────────
        cmd = [sys.executable, db_admin_script,
               "--time-limit", str(args.time_limit)]
        if args.host:
            cmd += ["--host", args.host]

        agent_env = os.environ.copy()
        agent_env["RUN_ID"] = run_id

        print(f"[db_admin_exp] Launching agent (time-limit={args.time_limit}s)...")
        agent_start = time.time()
        try:
            result = subprocess.run(
                cmd,
                cwd=root,
                env=agent_env,
                # Allow up to 2× the time-limit as subprocess timeout so the
                # agent has room to flush logs and exit cleanly.
                timeout=args.time_limit * 2 + 120,
                text=True,
            )
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            print(f"[db_admin_exp] WARNING: subprocess timed out for run "
                  f"{run_number}", file=sys.stderr)
            exit_code = 124
        except Exception as exc:
            print(f"[db_admin_exp] ERROR running agent: {exc}", file=sys.stderr)
            exit_code = 1

        agent_duration = round(time.time() - agent_start, 2)
        print(f"[db_admin_exp] Agent exited with code {exit_code} "
              f"after {agent_duration:.0f}s")

        if exit_code not in (0, 124):
            failures += 1

        # ── Mirror logs into experiments_db_admin ─────────────────────
        src_benign = os.path.join(root, "outputs", run_id, "benign_agent")
        dst_run = os.path.join(raw_runs_dir, run_id)
        dst_benign = os.path.join(dst_run, "benign_agent")

        if os.path.isdir(src_benign):
            os.makedirs(dst_run, exist_ok=True)
            if os.path.exists(dst_benign):
                shutil.rmtree(dst_benign)
            shutil.copytree(src_benign, dst_benign)
            print(f"[db_admin_exp] Logs mirrored → {dst_benign}")
        else:
            print(f"[db_admin_exp] WARNING: no benign_agent logs found at "
                  f"{src_benign}", file=sys.stderr)

        # ── Infrastructure restore ─────────────────────────────────────
        # Skip restore when --isolate is used: the next iteration will run
        # `make down` + `make up` anyway.
        is_last_run = run_number == args.runs
        should_restore = (
            not args.isolate
            and args.restore_mode != "none"
            and (not is_last_run or args.restore_after_last)
        )
        if should_restore:
            print(f"[db_admin_exp] Restoring infra "
                  f"(mode={args.restore_mode})...")
            ok, elapsed, err = restore_infra(args.restore_mode)
            if ok:
                print(f"[db_admin_exp] Restore OK ({elapsed:.1f}s)")
            else:
                print(f"[db_admin_exp] ERROR: restore failed: {err}",
                      file=sys.stderr)
                failures += 1
                print(f"[db_admin_exp] Aborting experiment after restore "
                      f"failure on run {run_number}.", file=sys.stderr)
                break

        run_end = now_utc()
        total_run_seconds = round(
            (run_end - run_start).total_seconds(), 2)
        print(f"[db_admin_exp] Run {run_number} complete in "
              f"{total_run_seconds:.0f}s  (exit={exit_code})")

        # Cooldown between runs (skip after the last one).
        if args.cooldown > 0 and not is_last_run:
            print(f"[db_admin_exp] Cooldown {args.cooldown}s ...")
            time.sleep(args.cooldown)

    # ── Final summary ─────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"[db_admin_exp] Experiment complete.")
    print(f"[db_admin_exp] Runs        : {args.runs}")
    print(f"[db_admin_exp] Failures    : {failures}")
    print(f"[db_admin_exp] Raw runs dir: {raw_runs_dir}")
    print(f"{'=' * 70}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
