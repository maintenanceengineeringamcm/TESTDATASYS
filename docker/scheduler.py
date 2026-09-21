"""Daily snapshot scheduler - the container replacement for the Windows task.

Runs backend/run_snapshot.py every day at SNAPSHOT_TIME (default 08:00, in the
container's TZ). If no snapshot exists yet - the first start after a fresh
restore - it runs one straight away so the dashboard is not empty until
tomorrow morning.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path("/app/backend")
SNAPSHOT_DB = BACKEND / "snapshots" / "hi_snapshots.db"
AT = os.getenv("SNAPSHOT_TIME", "08:00")


def log(msg: str) -> None:
    print(f"[scheduler {datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def has_snapshot() -> bool:
    if not SNAPSHOT_DB.exists():
        return False
    try:
        with sqlite3.connect(SNAPSHOT_DB) as c:
            return bool(c.execute("SELECT 1 FROM snapshot_run WHERE status = 'complete' LIMIT 1")
                        .fetchone())
    except sqlite3.Error:
        return False


def run() -> None:
    log("snapshot starting")
    started = time.time()
    code = subprocess.call([sys.executable, "run_snapshot.py", "--triggered-by", "schedule"],
                           cwd=BACKEND)
    log(f"snapshot finished with exit code {code} in {time.time() - started:.0f} s")


def next_run(now: datetime) -> datetime:
    hour, minute = (int(x) for x in AT.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def main() -> None:
    log(f"daily snapshot at {AT} ({os.getenv('TZ', 'UTC')})")
    if not has_snapshot():
        log("no completed snapshot yet - running one now")
        run()
    while True:
        target = next_run(datetime.now())
        log(f"next snapshot at {target:%Y-%m-%d %H:%M}")
        # Sleep in short steps so a clock change or container pause cannot
        # make the job skip a day.
        while datetime.now() < target:
            time.sleep(min(300, max(1, (target - datetime.now()).total_seconds())))
        run()


if __name__ == "__main__":
    main()
