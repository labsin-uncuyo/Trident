#!/usr/bin/env python3

import os
import shutil
import time
from pathlib import Path

RUN_ID = os.getenv("RUN_ID", "run_local")
SOURCE_ROOT = Path("/outputs")
TARGET_ROOT = Path("/outputs") / RUN_ID / "slips"
SYNC_INTERVAL = 30  # seconds

def sync_alerts():
    """Sync all alert files from various Slips output directories to the mounted volume."""
    try:
        # Ensure target directory exists
        TARGET_ROOT.mkdir(parents=True, exist_ok=True)

        # Find all alert files in the source
        for alert_file in SOURCE_ROOT.rglob("alerts.log"):
            if alert_file.is_file():
                # Calculate relative path from SOURCE_ROOT
                rel_path = alert_file.relative_to(SOURCE_ROOT)
                target_file = TARGET_ROOT / rel_path

                # Create parent directories if needed
                target_file.parent.mkdir(parents=True, exist_ok=True)

                # Copy if newer or doesn't exist
                if not target_file.exists() or alert_file.stat().st_mtime > target_file.stat().st_mtime:
                    try:
                        shutil.copy2(alert_file, target_file)
                        print(f"[sync_alerts] Copied {alert_file} -> {target_file}")
                    except Exception as e:
                        print(f"[sync_alerts] Failed to copy {alert_file}: {e}")

        # Find all JSON alert files
        for alert_file in SOURCE_ROOT.rglob("alerts.json"):
            if alert_file.is_file():
                # Calculate relative path from SOURCE_ROOT
                rel_path = alert_file.relative_to(SOURCE_ROOT)
                target_file = TARGET_ROOT / rel_path

                # Create parent directories if needed
                target_file.parent.mkdir(parents=True, exist_ok=True)

                # Copy if newer or doesn't exist
                if not target_file.exists() or alert_file.stat().st_mtime > target_file.stat().st_mtime:
                    try:
                        shutil.copy2(alert_file, target_file)
                        print(f"[sync_alerts] Copied {alert_file} -> {target_file}")
                    except Exception as e:
                        print(f"[sync_alerts] Failed to copy {alert_file}: {e}")

    except Exception as e:
        print(f"[sync_alerts] Error during sync: {e}")

def main():
    print(f"[sync_alerts] Starting alert sync from {SOURCE_ROOT} to {TARGET_ROOT}")
    while True:
        sync_alerts()
        time.sleep(SYNC_INTERVAL)

if __name__ == "__main__":
    main()