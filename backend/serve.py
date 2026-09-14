"""Production entry point for the API and the built UI.

`app.py` runs Flask's development server, which is single-threaded, prints a
warning, and is explicitly not meant to face a network. This module serves the
same WSGI application through waitress instead, which is a real server and
needs no compiler to install on Windows.

Run it on the server rather than `py app.py`:

    py serve.py

Everything is configured through the environment (see `config.py`); the only
settings that matter here are HI_HOST, HI_PORT and HI_THREADS.
"""
from __future__ import annotations

import logging
import os

from waitress import serve

from app import app
from config import Config
from core import ml, snapshots

log = logging.getLogger("hi.serve")


def main() -> None:
    # Same start-up work app.py does under __main__: without this the first
    # request pays for the model load and the snapshot check.
    ml.ensure_ready()
    snapshots.init()

    state = snapshots.status()
    if state["hasData"]:
        log.info("Snapshot available (age %.1f h)%s",
                 state["ageHours"] or 0, " - STALE" if state["stale"] else "")
    else:
        log.warning("No snapshot yet - run 'py run_snapshot.py'. Until then the "
                    "dashboard scores a bounded sample live and will feel slow.")

    # Four threads is enough for a handful of concurrent engineers and keeps
    # the per-thread ODBC connections (see db.py) to a number SQL Express is
    # comfortable with.
    threads = int(os.getenv("HI_THREADS", "4"))

    log.info("Serving API and UI on http://%s:%s (%d threads)",
             Config.HOST, Config.PORT, threads)
    serve(app, host=Config.HOST, port=Config.PORT, threads=threads,
          ident="HI-Analysis")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    main()
