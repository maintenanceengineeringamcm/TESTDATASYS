"""Oil filtration / degassing points in a transformer's DGA history.

Gas levels in a sealed transformer do not fall by themselves, so a sample in
which almost every gas has collapsed at once is the fingerprint of oil
processing. Such a reset can hide a live fault - the levels and the change since
the last sample both look healthy again - so the trend screens mark these
points and let the engineer score the trend from after one of them.

Two sources of filter points:

* **detected** - consecutive samples where, of the gases that were above a small
  floor beforehand, all (or all but one, with at least three) fell to half or
  less, and CO2 is among them. CO2 builds up slowly from paper ageing and only
  leaves through oil processing, which is what separates filtration from a bad
  single sample. Checked against the one filtration on record in the CMMS
  (G051 MT01, May 2020, CO2 7,456 -> 258 ppm), which it finds.
* **manual** - a date an engineer marks, for filtrations the data alone does
  not show (or that the CMMS records elsewhere).

A detected point can be rejected (a lab error, a resample) without deleting
anything; the rejection is stored like a manual mark and can be undone.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import BASE_DIR, Config
from core import dga_trend

DB_PATH = Path(os.getenv("HI_FILTER_POINTS_DB",
                         BASE_DIR / "snapshots" / "dga_filter_points.db"))

# Gases the detector looks at, and the level each must have reached before a
# drop counts - below these a halving is noise, not a reset.
DETECT_GASES = ["H2", "CH4", "C2H6", "C2H4", "C2H2", "CO", "CO2"]
DETECT_FLOOR = {"H2": 20, "CH4": 10, "C2H6": 10, "C2H4": 10, "C2H2": 1,
                "CO": 100, "CO2": 500}
DROP_RATIO = 0.5          # after <= 50 % of before
MIN_GASES = 3

RULE = ("A filter point is flagged when, between two consecutive samples, every gas "
        "that was above its floor (H2 20, CH4 10, C2H6 10, C2H4 10, C2H2 1, CO 100, "
        "CO2 500 ppm) - or all but one, at least three gases - fell to half or less, "
        "and CO2 is one of them.")

KINDS = {"manual", "rejected"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS filter_point (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset      TEXT NOT NULL,
    date       TEXT NOT NULL,          -- YYYY-MM-DD
    kind       TEXT NOT NULL,          -- manual | rejected
    note       TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (asset, date, kind)
);
CREATE INDEX IF NOT EXISTS ix_filter_point_asset ON filter_point (asset);
"""

_lock = threading.Lock()
_ready = False


def _conn() -> sqlite3.Connection:
    global _ready
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if not _ready:
        with _lock:
            conn.executescript(SCHEMA)
            _ready = True
    return conn


def _day(value: Any) -> str | None:
    d = dga_trend._parse_date(value)
    return d.strftime("%Y-%m-%d") if d else None


def _gas(sample: dict[str, Any], gas: str) -> float | None:
    v = sample.get(dga_trend.GAS_COLUMN[gas])
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def detect(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter points found in one asset's samples (any order, any date window)."""
    dated = sorted((s for s in samples if _day(s.get("DateSampled"))),
                   key=lambda s: _day(s["DateSampled"]))
    found: list[dict[str, Any]] = []
    for prev, cur in zip(dated, dated[1:]):
        eligible, dropped = [], []
        for g in DETECT_GASES:
            before, after = _gas(prev, g), _gas(cur, g)
            if before is None or after is None or before < DETECT_FLOOR[g]:
                continue
            eligible.append(g)
            if after <= DROP_RATIO * before:
                dropped.append(g)
        if (len(eligible) >= MIN_GASES and "CO2" in dropped
                and len(dropped) >= max(MIN_GASES, len(eligible) - 1)):
            found.append({
                "date": _day(cur["DateSampled"]),
                "previousSample": _day(prev["DateSampled"]),
                "droppedGases": dropped,
                "gases": {g: {"before": _gas(prev, g), "after": _gas(cur, g)}
                          for g in DETECT_GASES},
            })
    return found


def _stored(asset: str) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT id, date, kind, note, created_by, created_at "
                         "FROM filter_point WHERE asset = ? ORDER BY date", (asset,)).fetchall()
    return [dict(r) for r in rows]


def points(asset: str) -> dict[str, Any]:
    """Detected and manual filter points for one asset, oldest first."""
    asset = (asset or "").strip()
    samples = dga_trend.fetch_samples([asset]).get(asset, [])
    stored = _stored(asset)
    rejected = {r["date"]: r for r in stored if r["kind"] == "rejected"}

    out: list[dict[str, Any]] = []
    for p in detect(samples):
        rej = rejected.get(p["date"])
        out.append({**p, "id": f"auto:{p['date']}", "source": "detected",
                    "rejected": rej is not None, "rejectionId": rej["id"] if rej else None,
                    "note": rej["note"] if rej else None})
    for r in stored:
        if r["kind"] != "manual":
            continue
        out.append({"id": f"manual:{r['id']}", "date": r["date"], "source": "manual",
                    "rejected": False, "note": r["note"], "createdBy": r["created_by"],
                    "createdAt": r["created_at"], "droppedGases": [], "gases": {},
                    "previousSample": None})
    out.sort(key=lambda p: (p["date"], p["source"]))
    # The side of the filter points the health index scores DGA level and trend on.
    chosen = choose_window(samples, sorted({p["date"] for p in out if not p["rejected"]}))
    hi_window = {k: chosen[k] for k in ("fromDate", "beforeDate", "samplesUsed",
                                        "skippedPoints", "minSamplesAfter", "reason")}
    hi_window["enabled"] = Config.DGA_FILTER_WINDOW
    return {"asset": asset, "points": out, "rule": RULE, "hiWindow": hi_window,
            "samples": sum(1 for s in samples if _day(s.get("DateSampled")))}


def active_dates(asset: str, samples: list[dict[str, Any]]) -> list[str]:
    """Dates of the filter points that count: detected and not rejected, plus manual."""
    stored = _stored((asset or "").strip())
    rejected = {r["date"] for r in stored if r["kind"] == "rejected"}
    dates = {p["date"] for p in detect(samples) if p["date"] not in rejected}
    dates |= {r["date"] for r in stored if r["kind"] == "manual"}
    return sorted(dates)


def _has_gas(sample: dict[str, Any]) -> bool:
    return any(_gas(sample, g) is not None for g in dga_trend.TREND_GASES)


def choose_window(samples: list[dict[str, Any]], point_dates: list[str],
                  min_after: int | None = None) -> dict[str, Any]:
    """Which samples DGA level and DGA trend should be scored on.

    From the last filter point: with at least `min_after` samples on or after
    it, use those. Otherwise drop them and use the data before it - and apply
    the same rule to that earlier data, so a score never spans an oil reset.

    Returns the chosen samples with their bounds: `fromDate` (inclusive) and
    `beforeDate` (exclusive), either of which may be None for an open end.
    """
    need = Config.DGA_MIN_SAMPLES_AFTER_FILTER if min_after is None else min_after
    dated = sorted((s for s in samples if _day(s.get("DateSampled")) and _has_gas(s)),
                   key=lambda s: _day(s["DateSampled"]))
    pending = sorted(set(point_dates))
    before: str | None = None            # exclusive upper bound so far
    skipped: list[dict[str, Any]] = []   # filter points whose after-data was too short

    def window(chosen, start, reason):
        return {"samples": chosen, "fromDate": start, "beforeDate": before,
                "filterPoint": start, "skippedPoints": skipped, "reason": reason,
                "minSamplesAfter": need, "samplesUsed": len(chosen)}

    while pending:
        point = pending.pop()
        if before and point >= before:
            continue
        inside = [s for s in dated if before is None or _day(s["DateSampled"]) < before]
        after = [s for s in inside if _day(s["DateSampled"]) >= point]
        earlier = [s for s in inside if _day(s["DateSampled"]) < point]
        if len(after) >= need or not earlier:
            reason = (f"{len(after)} samples since the filter point of {point} - "
                      "scored on the data after it")
            if skipped:
                reason += _skipped_text(skipped)
            return window(after, point, reason)
        skipped.append({"date": point, "samplesAfter": len(after)})
        before = point

    chosen = [s for s in dated if before is None or _day(s["DateSampled"]) < before]
    if not skipped:
        return window(chosen, None, "no filter point - full sample history")
    return window(chosen, None, "scored on the data before the filter point" + _skipped_text(skipped))


def _skipped_text(skipped: list[dict[str, Any]]) -> str:
    parts = [f"{s['date']} ({s['samplesAfter']} sample{'s' if s['samplesAfter'] != 1 else ''} after)"
             for s in skipped]
    return "; too few samples since " + ", ".join(parts)


def analysis_window(asset: str, samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`choose_window` for one asset, its filter points read from the history and store."""
    asset = (asset or "").strip()
    if samples is None:
        samples = dga_trend.fetch_samples([asset]).get(asset, [])
    return choose_window(samples, active_dates(asset, samples))


def add(asset: str, date: str, kind: str = "manual", note: str | None = None,
        user: str = "engineer") -> dict[str, Any]:
    """Store a manual filter point, or a rejection of a detected one."""
    asset = (asset or "").strip()
    if not asset:
        raise ValueError("asset is required")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    day = _day(date)
    if not day:
        raise ValueError("date must be YYYY-MM-DD")
    if day > datetime.now().strftime("%Y-%m-%d"):
        raise ValueError("a filter point cannot be in the future")
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO filter_point (asset, date, kind, note, created_by, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?)",
                  (asset, day, kind, (note or "").strip() or None, user,
                   datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return points(asset)


def remove(asset: str, point_id: int) -> dict[str, Any]:
    """Delete a stored mark (a manual point, or a rejection - which restores it)."""
    asset = (asset or "").strip()
    with _conn() as c:
        gone = c.execute("DELETE FROM filter_point WHERE id = ? AND asset = ?",
                         (point_id, asset)).rowcount
    if not gone:
        raise LookupError("no such filter point for this asset")
    return points(asset)
