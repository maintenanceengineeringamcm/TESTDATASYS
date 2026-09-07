"""Nightly health-index snapshots.

Scoring the whole fleet touches ~20 tables per asset, so computing 13,000-odd
assets on every dashboard render is not viable. Instead a scheduled job runs
once a day, writes one row per asset, and the dashboard and health-index table
read those rows instantly. Anything needing a fresh number - a single asset, or
a what-if - goes through the live engine or the manual workbench as before.

Snapshots live in their own SQLite database. `CEB_TRANSMISSION` stays read-only:
these are our derived numbers, not plant data.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import BASE_DIR
from core import assets as assets_mod
from core import attributes, hi_engine, scoring

log = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("HI_SNAPSHOT_DB", BASE_DIR / "snapshots" / "hi_snapshots.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot_run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,          -- running | complete | failed
    triggered_by  TEXT NOT NULL DEFAULT 'schedule',
    assets_total  INTEGER NOT NULL DEFAULT 0,
    assets_scored INTEGER NOT NULL DEFAULT 0,
    assets_failed INTEGER NOT NULL DEFAULT 0,
    duration_s    REAL,
    error         TEXT
);

-- One row per asset: the current snapshot. The daily run upserts in place, so
-- this table always holds the latest picture without growing unbounded.
CREATE TABLE IF NOT EXISTS asset_health (
    asset_number     TEXT PRIMARY KEY,
    run_id           INTEGER NOT NULL,
    asset_type       TEXT,
    category         TEXT,
    asset_type_label TEXT,
    site             TEXT,
    health_index     REAL,
    band_key         TEXT,
    band_label       TEXT,
    band_color       TEXT,
    band_bg          TEXT,
    components_used  INTEGER,
    components_total INTEGER,
    coverage         REAL,
    config_trusted   INTEGER NOT NULL DEFAULT 1,
    config_status    TEXT,
    computed_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_asset_health_type ON asset_health (asset_type);
CREATE INDEX IF NOT EXISTS ix_asset_health_hi   ON asset_health (health_index);
CREATE INDEX IF NOT EXISTS ix_asset_health_site ON asset_health (site);

-- Dashboard rollups, computed once with the sweep rather than re-aggregated on
-- every page load.
CREATE TABLE IF NOT EXISTS dashboard_summary (
    run_id       INTEGER PRIMARY KEY,
    payload_json TEXT NOT NULL,
    computed_at  TEXT NOT NULL
);
"""

_local = threading.local()
_write_lock = threading.Lock()

# Guards against two sweeps running at once - a slow manual refresh overlapping
# the 08:00 job would double the database load for no benefit.
_job_lock = threading.Lock()
_progress: dict[str, Any] = {"running": False, "done": 0, "total": 0, "startedAt": None}


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


def init() -> None:
    with _write_lock:
        conn = _conn()
        conn.executescript(SCHEMA)
        # Migrate databases created before `category` existed. CREATE TABLE is a
        # no-op once the table exists, so the column has to be added explicitly -
        # and its index only after that, or the index refers to nothing.
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(asset_health)")}
        if "category" not in existing:
            conn.execute("ALTER TABLE asset_health ADD COLUMN category TEXT")
            log.info("snapshot store migrated: added asset_health.category")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_asset_health_cat "
                     "ON asset_health (category)")
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------
def latest_run() -> dict[str, Any] | None:
    row = _conn().execute(
        "SELECT * FROM snapshot_run WHERE status = 'complete' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def last_attempt() -> dict[str, Any] | None:
    row = _conn().execute("SELECT * FROM snapshot_run ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def has_data() -> bool:
    return _conn().execute("SELECT 1 FROM asset_health LIMIT 1").fetchone() is not None


def _row_to_summary(r: sqlite3.Row) -> dict[str, Any]:
    keys = r.keys()
    return {
        "asset": r["asset_number"],
        "assetType": r["asset_type"],
        "category": r["category"] if "category" in keys else r["asset_type"],
        "assetTypeLabel": r["asset_type_label"],
        "site": r["site"],
        "healthIndex": r["health_index"],
        "bandKey": r["band_key"],
        "bandLabel": r["band_label"],
        "bandColor": r["band_color"],
        "bandBg": r["band_bg"],
        "componentsUsed": r["components_used"],
        "componentsTotal": r["components_total"],
        "coverage": r["coverage"],
        "configTrusted": bool(r["config_trusted"]),
        "configStatus": r["config_status"],
    }


def _like_escape(value: str) -> str:
    r"""Escape LIKE metacharacters, backslash first.

    Asset numbers routinely contain '_' (MT01_X, 52A_X), which LIKE reads as
    "any single character". Unescaped, a subtree filter on `G008/PE/1/02/MT01_X`
    would also match `MT01AX` and every other one-character variant.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _scope_clause(node: str | None,
                  exclude: set[str] | None) -> tuple[list[str], list[Any]]:
    """Shared WHERE fragments for the subtree and status filters."""
    where: list[str] = []
    params: list[Any] = []
    if node:
        scope = node.strip().rstrip("/")
        if scope:
            where.append(r"(asset_number = ? OR asset_number LIKE ? ESCAPE '\')")
            params.extend([scope, f"{_like_escape(scope)}/%"])
    if exclude:
        # Deactivated plant, per the navigator's status filter. Excluding is
        # done by list rather than by a status column because the snapshot
        # store has none - the status lives in the CMMS feed. The list is
        # bounded by the fleet size (~13k) and SQLite allows 32,766 bound
        # variables, so this cannot outgrow the parameter limit.
        where.append(f"asset_number NOT IN ({', '.join('?' * len(exclude))})")
        params.extend(sorted(exclude))
    return where, params


def rows(asset_type: str | None = None, site: str | None = None,
         node: str | None = None, exclude: set[str] | None = None,
         limit: int = 500, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Stored rows, filtered by reporting category (TR, AET, OLTC, ...).

    `node` scopes to one hierarchy subtree. Asset numbers are a materialised
    path, so the subtree is the node itself plus everything prefixed by it.
    `exclude` drops assets the status filter rejects.
    """
    where, params = [], []
    if asset_type:
        where.append("category = ?")
        params.append(asset_type)
    if site:
        where.append("site = ?")
        params.append(site)
    scope_where, scope_params = _scope_clause(node, exclude)
    where.extend(scope_where)
    params.extend(scope_params)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = _conn().execute(
        f"SELECT COUNT(*) c FROM asset_health {clause}", params
    ).fetchone()["c"]

    # Unscored assets sort last so the table opens on real results.
    found = _conn().execute(
        f"SELECT * FROM asset_health {clause} "
        "ORDER BY (health_index IS NULL), health_index ASC, asset_number ASC "
        "LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_row_to_summary(r) for r in found], total


def asset(asset_number: str) -> dict[str, Any] | None:
    row = _conn().execute(
        "SELECT * FROM asset_health WHERE asset_number = ?", (asset_number.strip(),)
    ).fetchone()
    return _row_to_summary(row) if row else None


def dashboard() -> dict[str, Any] | None:
    row = _conn().execute(
        "SELECT payload_json, computed_at FROM dashboard_summary "
        "ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    payload["computedAt"] = row["computed_at"]
    return payload


def summary(asset_type: str | None = None, node: str | None = None,
            exclude: set[str] | None = None) -> dict[str, Any] | None:
    """Distribution, average and worst assets, optionally for one asset type.

    Recomputed from the stored rows rather than read from `dashboard_summary`,
    because the dashboard defaults to transformers and the stored rollup is
    fleet-wide. Aggregating 13,000 SQLite rows costs a few milliseconds.

    `node` and `exclude` apply the navigator's subtree scope and status filter,
    so a scoped dashboard averages only the assets it is showing.
    """
    if not has_data():
        return None

    conditions, params = [], []
    if asset_type:
        conditions.append("category = ?")
        params.append(asset_type)
    scope_where, scope_params = _scope_clause(node, exclude)
    conditions.extend(scope_where)
    params.extend(scope_params)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    found = _conn().execute(
        f"SELECT health_index, band_key, config_trusted FROM asset_health {where}", params
    ).fetchall()
    if not found:
        return None

    rows = [{"healthIndex": r["health_index"], "bandKey": r["band_key"],
             "configTrusted": bool(r["config_trusted"])} for r in found]
    scored = [r for r in rows if r["healthIndex"] is not None]
    trusted = [r for r in scored if r["configTrusted"]]

    # Built from the same condition list so the worst-assets panel can never
    # drift out of step with the averages above it.
    worst_conditions = conditions + ["health_index IS NOT NULL",
                                     "config_trusted = 1"]
    worst_rows = _conn().execute(
        f"SELECT * FROM asset_health WHERE {' AND '.join(worst_conditions)} "
        "ORDER BY health_index ASC LIMIT 10",
        params,
    ).fetchall()

    return {
        "distribution": hi_engine.distribution(rows),
        "worst": [_row_to_summary(r) for r in worst_rows],
        "scoredCount": len(scored),
        "evaluated": len(rows),
        "untrustedCount": len(scored) - len(trusted),
        "averageHealthIndex": round(sum(r["healthIndex"] for r in trusted) / len(trusted), 2)
        if trusted else None,
    }


def available_types(node: str | None = None,
                    exclude: set[str] | None = None) -> list[dict[str, Any]]:
    """Reporting categories present in the snapshot, for the type selector.

    `node` narrows the counts to one hierarchy subtree, and `exclude` drops
    out-of-service plant. Without them the chips would advertise fleet totals
    while the table below shows one substation, which reads as a bug.
    """
    where, params = ["category IS NOT NULL"], []
    scope_where, scope_params = _scope_clause(node, exclude)
    where.extend(scope_where)
    params.extend(scope_params)
    found = _conn().execute(
        "SELECT category AS t, COUNT(*) AS n, "
        "       SUM(CASE WHEN health_index IS NOT NULL THEN 1 ELSE 0 END) AS scored, "
        "       MIN(config_trusted) AS trusted "
        f"FROM asset_health WHERE {' AND '.join(where)} GROUP BY category",
        params,
    ).fetchall()
    order = {c: i for i, c in enumerate(assets_mod.CATEGORY_ORDER)}
    items = [{"assetType": r["t"],
              "label": assets_mod.CATEGORY_LABEL.get(r["t"], r["t"]),
              "count": r["n"], "scored": r["scored"] or 0,
              "trusted": bool(r["trusted"])} for r in found]
    items.sort(key=lambda x: order.get(x["assetType"], 99))
    return items


def status() -> dict[str, Any]:
    run = latest_run()
    attempt = last_attempt()
    stale = None
    if run and run.get("finished_at"):
        try:
            finished = datetime.fromisoformat(run["finished_at"])
            stale = (datetime.now(timezone.utc) - finished).total_seconds() / 3600.0
        except ValueError:
            stale = None
    return {
        "hasData": has_data(),
        "lastRun": run,
        "lastAttempt": attempt,
        "ageHours": round(stale, 2) if stale is not None else None,
        # Anything older than a day and a half means the 08:00 job has not fired.
        "stale": stale is not None and stale > 36,
        "database": str(DB_PATH),
        "inProgress": dict(_progress),
    }


def history(limit: int = 30) -> list[dict[str, Any]]:
    found = _conn().execute(
        "SELECT * FROM snapshot_run ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in found]


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def _start_run(triggered_by: str, total: int) -> int:
    with _write_lock:
        conn = _conn()
        cur = conn.execute(
            "INSERT INTO snapshot_run (started_at, status, triggered_by, assets_total) "
            "VALUES (?, 'running', ?, ?)",
            (_now(), triggered_by, total),
        )
        conn.commit()
        return int(cur.lastrowid)


def _finish_run(run_id: int, scored: int, failed: int, seconds: float,
                error: str | None = None) -> None:
    with _write_lock:
        conn = _conn()
        conn.execute(
            "UPDATE snapshot_run SET finished_at=?, status=?, assets_scored=?, "
            "assets_failed=?, duration_s=?, error=? WHERE id=?",
            (_now(), "failed" if error else "complete", scored, failed,
             round(seconds, 2), error, run_id),
        )
        conn.commit()


def _write_batch(run_id: int, batch: list[dict[str, Any]]) -> None:
    if not batch:
        return
    stamp = _now()
    with _write_lock:
        conn = _conn()
        conn.executemany(
            "INSERT INTO asset_health (asset_number, run_id, asset_type, category,"
            " asset_type_label, site, health_index, band_key, band_label, band_color,"
            " band_bg, components_used, components_total, coverage, config_trusted,"
            " config_status, computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(asset_number) DO UPDATE SET "
            " run_id=excluded.run_id, asset_type=excluded.asset_type,"
            " category=excluded.category,"
            " asset_type_label=excluded.asset_type_label, site=excluded.site,"
            " health_index=excluded.health_index, band_key=excluded.band_key,"
            " band_label=excluded.band_label, band_color=excluded.band_color,"
            " band_bg=excluded.band_bg, components_used=excluded.components_used,"
            " components_total=excluded.components_total, coverage=excluded.coverage,"
            " config_trusted=excluded.config_trusted, config_status=excluded.config_status,"
            " computed_at=excluded.computed_at",
            [
                (r["asset"], run_id, r["assetType"], r.get("category") or r["assetType"],
                 r["assetTypeLabel"], r["site"],
                 r["healthIndex"], r["bandKey"], r["bandLabel"], r["bandColor"],
                 r["bandBg"], r["componentsUsed"], r["componentsTotal"], r["coverage"],
                 1 if r.get("configTrusted", True) else 0, r.get("configStatus"), stamp)
                for r in batch
            ],
        )
        conn.commit()


def _write_dashboard(run_id: int, payload: dict[str, Any]) -> None:
    with _write_lock:
        conn = _conn()
        conn.execute(
            "INSERT INTO dashboard_summary (run_id, payload_json, computed_at) "
            "VALUES (?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
            "payload_json=excluded.payload_json, computed_at=excluded.computed_at",
            (run_id, json.dumps(payload), _now()),
        )
        conn.commit()


def _build_dashboard(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in all_rows if r["healthIndex"] is not None]
    trusted = [r for r in scored if r.get("configTrusted")]
    worst = sorted(trusted, key=lambda r: r["healthIndex"])[:10]
    return {
        "counts": assets_mod.counts(),
        "configAudit": scoring.config_audit(),
        "distribution": hi_engine.distribution(all_rows),
        "worst": worst,
        "scoredCount": len(scored),
        "evaluated": len(all_rows),
        "untrustedCount": len(scored) - len(trusted),
        "averageHealthIndex": round(sum(r["healthIndex"] for r in trusted) / len(trusted), 2)
        if trusted else None,
        "bands": scoring.HI_BANDS,
    }


def run_snapshot(triggered_by: str = "schedule", asset_types: list[str] | None = None,
                 limit: int | None = None,
                 on_progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Score every asset and store the result. Returns a summary of the run.

    Only one sweep runs at a time; a second caller is told the first is still
    going rather than being queued behind it.
    """
    if not _job_lock.acquire(blocking=False):
        return {"started": False, "reason": "A snapshot run is already in progress.",
                "progress": dict(_progress)}

    started = time.perf_counter()
    run_id: int | None = None
    scored = failed = 0
    try:
        init()
        targets = [a for a in assets_mod.all_assets()
                   if a.assetType in scoring.COMPONENT_ORDER]
        if asset_types:
            targets = [a for a in targets if a.assetType in asset_types]
        if limit:
            targets = targets[:limit]

        # Load the CMMS manufacture-year map once, up front. Per-asset it is a
        # ~0.1s lookup - fine for a page, 20 minutes across the fleet - and the
        # AGE criterion needs it for 9,065 of these assets. The bulk pull is a
        # heap scan taking ~4 minutes, which is why only this scheduled job
        # triggers it; a failure is logged and the sweep goes on with whatever
        # per-asset lookups can answer.
        primed = attributes.prime()
        log.info("manufacture-year map: %s assets from %s%s",
                 primed.get("assets"), primed.get("source"),
                 f" - {primed['error']}" if primed.get("error") else "")

        total = len(targets)
        run_id = _start_run(triggered_by, total)
        _progress.update(running=True, done=0, total=total, startedAt=_now())
        log.info("snapshot run %s started: %d assets (%s)", run_id, total, triggered_by)

        collected: list[dict[str, Any]] = []
        batch: list[dict[str, Any]] = []
        BATCH = 200

        for i, a in enumerate(targets, start=1):
            try:
                result = hi_engine.compute(a.assetNumber)
                row = hi_engine.summary_row(result)
                scored += 1
            except Exception as exc:            # one bad asset must not end the sweep
                log.warning("snapshot failed for %s: %s", a.assetNumber, exc)
                failed += 1
                row = {
                    "asset": a.assetNumber, "assetType": a.assetType,
                    "assetTypeLabel": a.label, "site": a.site, "healthIndex": None,
                    "bandKey": None, "bandLabel": None, "bandColor": None,
                    "bandBg": None, "componentsUsed": 0, "componentsTotal": 0,
                    "coverage": 0.0, "configTrusted": True, "configStatus": None,
                }
            collected.append(row)
            batch.append(row)
            if len(batch) >= BATCH:
                _write_batch(run_id, batch)
                batch = []
            _progress["done"] = i
            if on_progress and i % 100 == 0:
                on_progress(i, total)

        _write_batch(run_id, batch)
        _write_dashboard(run_id, _build_dashboard(collected))

        seconds = time.perf_counter() - started
        _finish_run(run_id, scored, failed, seconds)
        log.info("snapshot run %s complete: %d scored, %d failed, %.1fs",
                 run_id, scored, failed, seconds)
        return {"started": True, "runId": run_id, "assets": total, "scored": scored,
                "failed": failed, "durationSeconds": round(seconds, 2)}

    except Exception as exc:
        seconds = time.perf_counter() - started
        log.exception("snapshot run failed")
        if run_id is not None:
            _finish_run(run_id, scored, failed, seconds, str(exc))
        return {"started": True, "runId": run_id, "error": str(exc),
                "durationSeconds": round(seconds, 2)}
    finally:
        _progress.update(running=False)
        _job_lock.release()


def run_in_background(triggered_by: str = "manual", **kwargs) -> dict[str, Any]:
    """Kick off a sweep without holding the HTTP request open."""
    if _progress.get("running"):
        return {"started": False, "reason": "A snapshot run is already in progress.",
                "progress": dict(_progress)}
    thread = threading.Thread(target=run_snapshot, kwargs={"triggered_by": triggered_by, **kwargs},
                              daemon=True, name="hi-snapshot")
    thread.start()
    return {"started": True, "background": True}


def refresh_asset(asset_number: str) -> dict[str, Any] | None:
    """Recompute one asset live and update its snapshot row.

    Backs the per-asset Refresh action, so a user who needs a current number for
    one transformer does not wait for a fleet sweep.
    """
    result = hi_engine.compute(asset_number)
    row = hi_engine.summary_row(result)
    run = latest_run()
    _write_batch(int(run["id"]) if run else 0, [row])
    return row
