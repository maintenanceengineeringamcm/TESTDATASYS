"""Daily health-index snapshot job.

Run directly by the Windows scheduled task at 08:00. Does not need the API to be
up - it talks to SQL Server itself - so the fleet is refreshed even if nobody
has the web app running.

    py run_snapshot.py                 # every scorable asset
    py run_snapshot.py --types TR CB   # only these asset types
    py run_snapshot.py --limit 50      # a quick smoke run
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import BASE_DIR  # noqa: E402
from core import snapshots  # noqa: E402

LOG_DIR = BASE_DIR / "logs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute and store health-index snapshots.")
    parser.add_argument("--types", nargs="*", default=None,
                        help="Asset types to include (default: all scorable).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after this many assets (for testing).")
    parser.add_argument("--triggered-by", default="schedule")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(LOG_DIR / "snapshot.log", encoding="utf-8")
    ]
    if not args.quiet:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=handlers,
        force=True,
    )
    log = logging.getLogger("snapshot")

    started = datetime.now()
    log.info("=" * 62)
    log.info("Snapshot job starting (%s)", started.strftime("%Y-%m-%d %H:%M:%S"))

    def progress(done: int, total: int) -> None:
        log.info("  %d/%d assets (%.0f%%)", done, total, done / total * 100)

    result = snapshots.run_snapshot(
        triggered_by=args.triggered_by,
        asset_types=args.types,
        limit=args.limit,
        on_progress=progress,
    )

    if not result.get("started"):
        log.warning("Not started: %s", result.get("reason"))
        return 2
    if result.get("error"):
        log.error("Job FAILED after %.1fs: %s",
                  result.get("durationSeconds", 0), result["error"])
        return 1

    log.info("Job complete: %d scored, %d failed, %.1fs",
             result["scored"], result["failed"], result["durationSeconds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
