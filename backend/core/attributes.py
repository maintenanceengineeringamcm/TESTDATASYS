"""Asset attributes read from the Tomms CMMS.

Implements the extraction method documented in `ASSET_ATTRIBUTES_INTEGRATION.md`.
Only the part the health index needs is here: the **year of manufacture**, which
is what the AGE criterion is scored on.

Why this module exists
----------------------
`CEB_ASSET` in the HI database is empty (0 rows) and `SFRA_HEADER.ManufactureYear`
covers 165 assets. The CMMS holds a manufacture year for **9,065 of the 13,109
assets the engine scores** - AGE goes from a rounding error to the best-covered
criterion in the system.

The method (doc sections 1, 3 and 9)
------------------------------------
* The field is `ast_det.ast_det_datetime1`. There is no column named for it: in
  TOMMS the meaning of a user-defined field is *data*, held in `cf_label`. The
  caption to trust is `customize_label` where `language_cd = 'DEFAULT'` - the
  other language rows still carry the vendor's `UDF Date1:` placeholder.
  :func:`verify_label_mapping` asserts the mapping still points here; run it
  after any CMMS reconfiguration.
* It is a **year**, not a date. Take ``YEAR(...)`` and never render the day.
  The doc overstates this - it claims zero rows carry a month or day other than
  1, and 773 of 17,508 do (Feb 1 x368, Aug 1 x77, ...), with ~23 carrying a real
  day-of-month. So ``YEAR(...)`` can move a whole-year age by one for 4.4% of
  rows. The convention still holds for the other 95.6%, and the AGE score bands
  are far coarser than a year, so the rule stands - but it is measured rather
  than assumed, in `tests/test_live_manufacture_year.py`, and that test fails
  loudly if the CMMS starts recording real dates in bulk.
* `ast_det` joins on the surrogate key, ``d.mst_RowID = m.RowID``. The business
  key (`..._asset_no`) is the join for history tables only; using the wrong one
  returns zero rows silently.
* The source carries junk: 1900/1905 placeholders and 2102/2103/2180 typos.
  :data:`YEAR_MIN` / :func:`_this_year` bound it. 41 of the fleet's values are
  dropped this way - they must read as "no year", never as a 126-year-old asset.
* `ast_det_datetime6` is "Year of Manufacture(L)". The (G)/(L) split is
  unresolved (doc 9.2), so it is a fallback only, kept visible as its own
  candidate. No asset in the scored fleet currently depends on it.

Performance (doc 10)
--------------------
`ast_det` is a 150k-row heap with no index, on a memory-starved instance. One
asset costs ~0.1s - fine for a page - but the whole-fleet pull scans and takes
~4 minutes. So:

    per-asset lookup   -> live requests (asset detail, manual calculation)
    bulk map           -> the fleet sweep, built once and cached on disk

The bulk map is never built on a live request. :func:`prime` builds it, and the
snapshot job calls that before scoring 13,000 assets; everything else falls
through to the per-asset query.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import db
from config import Config, tomms_configured

log = logging.getLogger(__name__)

# The UDF slot holding the manufacture year, and its expected caption. Both are
# asserted by verify_label_mapping() - the whole integration rests on a mapping
# an administrator can change from inside the CMMS.
YEAR_COLUMN = "ast_det_datetime1"
YEAR_LABEL = "Year of Manufacture(G)"
YEAR_COLUMN_LOCAL = "ast_det_datetime6"
YEAR_LABEL_LOCAL = "Year of Manufacture(L)"

# 1900 and 1905 are placeholders; 2102/2103/2180 are data-entry errors.
YEAR_MIN = Config.MANUFACTURE_YEAR_MIN

CACHE_PATH = Path(Config.MANUFACTURE_YEAR_CACHE)
CACHE_TTL_HOURS = Config.MANUFACTURE_YEAR_TTL_HOURS
BULK_TIMEOUT = Config.MANUFACTURE_YEAR_BULK_TIMEOUT

# An OLTC is its own asset number under its transformer. 252 of the 254 scored
# tap changers carry their own year in the CMMS and 78 of those differ from the
# parent transformer's, so the parent is a fallback only - never a shortcut.
_OLTC_SEGMENT = re.compile(r"^OLTC\d*$", re.IGNORECASE)

_ASSET_SQL = f"""
SELECT TOP 1 YEAR(d.{YEAR_COLUMN})       AS grid_year,
             YEAR(d.{YEAR_COLUMN_LOCAL}) AS line_year
FROM   ast_mst m
JOIN   ast_det d ON d.mst_RowID = m.RowID
WHERE  m.site_cd = ? AND LTRIM(RTRIM(m.ast_mst_asset_no)) = ?
"""

_BULK_SQL = f"""
SELECT LTRIM(RTRIM(m.ast_mst_asset_no)) AS asset_no,
       YEAR(d.{YEAR_COLUMN})            AS grid_year,
       YEAR(d.{YEAR_COLUMN_LOCAL})      AS line_year
FROM   ast_mst m
JOIN   ast_det d ON d.mst_RowID = m.RowID
WHERE  m.site_cd = ?
  AND  (d.{YEAR_COLUMN} IS NOT NULL OR d.{YEAR_COLUMN_LOCAL} IS NOT NULL)
  AND  m.ast_mst_asset_no IS NOT NULL
  AND  LTRIM(RTRIM(m.ast_mst_asset_no)) <> ''
"""

_LABEL_SQL = """
SELECT LTRIM(RTRIM(column_name))     AS column_name,
       LTRIM(RTRIM(customize_label)) AS label
FROM   cf_label
WHERE  table_name = 'ast_det' AND language_cd = 'DEFAULT'
  AND  column_name IN (?, ?)
"""

_map_lock = threading.Lock()
_map: dict[str, dict[str, int | None]] | None = None
_map_loaded_at: float = 0.0


# --------------------------------------------------------------------------
# year cleaning
# --------------------------------------------------------------------------
def _this_year() -> int:
    return datetime.now().year


def usable_year(value: Any) -> int | None:
    """A manufacture year, or None when the source value is not one.

    Applies the cleaning predicate from doc section 1: ``BETWEEN 1950 AND
    YEAR(GETDATE())``. Everything outside it - the 1900/1905 placeholders, the
    2102/2103/2180 typos, blanks - is *absent*, not a very old or very new
    asset. Returning 0 or a negative age here would score plant on a typo.
    """
    if value is None or value == "":
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if YEAR_MIN <= year <= _this_year():
        return year
    return None


def age_from_year(year: int | None) -> float | None:
    """Age in whole years from a manufacture year. None if the year is unusable."""
    year = usable_year(year)
    if year is None:
        return None
    return float(_this_year() - year)


def normalise(asset_no: str) -> str:
    """Map key for an asset number.

    The CMMS collation is case-insensitive and its columns are padded, so the
    key is trimmed and upper-cased on both sides of the lookup.
    """
    return (asset_no or "").strip().upper()


_NAME_SQL = """
SELECT LTRIM(RTRIM(m.ast_mst_asset_no))        AS asset_no,
       LTRIM(RTRIM(m.ast_mst_asset_shortdesc)) AS short_desc
FROM   ast_mst m
WHERE  m.site_cd = ?
  AND  LTRIM(RTRIM(m.ast_mst_asset_no)) IN (?, ?)
"""


def asset_naming(asset_no: str) -> dict[str, str | None]:
    """What the CMMS calls this asset, and the substation it stands in.

    Returns ``{"assetName", "siteName", "siteCode"}``, any of which may be None
    when the CMMS has no row or is unreachable - a report still prints, named by
    its asset number alone, exactly as it did before.

    Two targeted lookups rather than the navigator's tree: naming one asset does
    not justify building 24,000 nodes, which costs the better part of a minute
    on a cold process. `'N/A'` arrives as a string here, not a null (integration
    doc 9.3), so it is normalised away rather than printed as a name.
    """
    key = normalise(asset_no)
    site = key.split("/")[0]

    def build() -> dict[str, str | None]:
        blank: dict[str, str | None] = {"assetName": None, "siteName": None,
                                        "siteCode": site or None}
        if not (key and tomms_configured()):
            return blank
        try:
            rows = db.tomms_query(_NAME_SQL, (Config.TOMMS_SITE_CD, key, site))
        except db.DatabaseError as exc:
            log.warning("asset name lookup failed for %s: %s", key, exc)
            return blank
        found: dict[str, str] = {}
        for row in rows:
            code = (row.get("asset_no") or "").strip().upper()
            desc = (row.get("short_desc") or "").strip()
            if code and desc and desc != "N/A":
                found[code] = desc
        return {"assetName": found.get(key), "siteName": found.get(site),
                "siteCode": site or None}

    # Names change when an engineer renames plant in the CMMS, which is rare;
    # an hour of staleness is cheaper than a round trip on every report.
    return db.cached(f"attributes:name:{key}", build, ttl=3600)


def parent_of_oltc(asset_no: str) -> str | None:
    """The transformer an OLTC asset number hangs off, or None if not an OLTC.

    `G001/PE/1/02/MT01_X/OLTC/01` -> `G001/PE/1/02/MT01_X/01`. Inter-bus units
    number theirs OLTC1/OLTC2, hence the pattern rather than an equality test.
    """
    segments = [s for s in (asset_no or "").split("/") if s != ""]
    kept = [s for s in segments if not _OLTC_SEGMENT.match(s)]
    if len(kept) == len(segments):
        return None
    return "/".join(kept)


# --------------------------------------------------------------------------
# bulk map - built by the snapshot job, cached on disk
# --------------------------------------------------------------------------
def _cache_age_hours() -> float | None:
    try:
        return (time.time() - CACHE_PATH.stat().st_mtime) / 3600.0
    except OSError:
        return None


def _read_cache() -> dict[str, dict[str, int | None]] | None:
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("manufacture-year cache unreadable: %s", exc)
        return None
    if not isinstance(raw, dict):
        return None
    return {normalise(k): {"grid": v.get("grid"), "line": v.get("line")}
            for k, v in raw.get("assets", {}).items()}


def _write_cache(rows: dict[str, dict[str, int | None]]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"builtAt": datetime.now().isoformat(timespec="seconds"),
                   "source": f"{Config.TOMMS_DB_SERVER}/{Config.TOMMS_DB_NAME}",
                   "column": YEAR_COLUMN, "assets": rows}
        tmp = CACHE_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, CACHE_PATH)
    except OSError as exc:
        log.warning("could not write manufacture-year cache: %s", exc)


def _pull_all() -> dict[str, dict[str, int | None]]:
    """One scan of the CMMS for every asset carrying a manufacture year.

    ~4 minutes against the live instance - see the module docstring. Callers
    must be a scheduled job, never an HTTP request.
    """
    rows = db.tomms_query_long(_BULK_SQL, (Config.TOMMS_SITE_CD,),
                               timeout=BULK_TIMEOUT)
    out: dict[str, dict[str, int | None]] = {}
    for row in rows:
        key = normalise(row.get("asset_no"))
        if key:
            out[key] = {"grid": row.get("grid_year"), "line": row.get("line_year")}
    return out


def prime(force: bool = False) -> dict[str, Any]:
    """Load the whole-fleet manufacture-year map. Safe to call at any time.

    Uses the disk cache while it is inside :data:`CACHE_TTL_HOURS`; otherwise
    re-pulls from the CMMS and rewrites it. If the CMMS is unreachable, a stale
    cache is still used - a year-old manufacture year is exactly as correct as
    today's, and refusing to score AGE because the CMMS is down would be worse.
    """
    global _map, _map_loaded_at
    with _map_lock:
        age = _cache_age_hours()
        # Freshness of what is already in memory is judged by when *it* was
        # loaded, not by the cache file's mtime: if the disk write failed, the
        # map is still good and re-pulling for four minutes would be pointless.
        in_memory_hours = (time.time() - _map_loaded_at) / 3600.0
        if not force and _map is not None and in_memory_hours < CACHE_TTL_HOURS:
            return {"assets": len(_map), "source": "memory",
                    "cacheAgeHours": round(in_memory_hours, 2)}

        if not force and age is not None and age < CACHE_TTL_HOURS:
            cached = _read_cache()
            if cached is not None:
                _map, _map_loaded_at = cached, time.time()
                return {"assets": len(cached), "source": "disk",
                        "cacheAgeHours": round(age, 2)}

        if not tomms_configured():
            cached = _read_cache()
            if cached is not None:
                _map, _map_loaded_at = cached, time.time()
                return {"assets": len(cached), "source": "disk (CMMS not configured)",
                        "cacheAgeHours": round(age or 0, 2)}
            return {"assets": 0, "source": "unavailable",
                    "error": "No Tomms CMMS server configured (HI_TOMMS_DB_SERVER)."}

        started = time.perf_counter()
        try:
            rows = _pull_all()
        except db.DatabaseError as exc:
            log.warning("manufacture-year pull failed, falling back to cache: %s", exc)
            cached = _read_cache()
            if cached is not None:
                _map, _map_loaded_at = cached, time.time()
                return {"assets": len(cached), "source": "stale disk cache",
                        "cacheAgeHours": round(age or 0, 2), "error": str(exc)}
            return {"assets": 0, "source": "unavailable", "error": str(exc)}

        _write_cache(rows)
        _map, _map_loaded_at = rows, time.time()
        return {"assets": len(rows), "source": "cmms",
                "seconds": round(time.perf_counter() - started, 1)}


def loaded_map() -> dict[str, dict[str, int | None]] | None:
    """The in-memory map if it is loaded and fresh, else the disk cache. No pull.

    Deliberately never triggers :func:`prime` - the bulk pull is a four-minute
    scan and must not happen inside a request.
    """
    global _map, _map_loaded_at
    age = _cache_age_hours()
    if _map is not None and (time.time() - _map_loaded_at) / 3600.0 < CACHE_TTL_HOURS:
        return _map
    if age is not None and age < CACHE_TTL_HOURS:
        with _map_lock:
            cached = _read_cache()
            if cached is not None:
                _map, _map_loaded_at = cached, time.time()
                return cached
    return None


# --------------------------------------------------------------------------
# the lookup
# --------------------------------------------------------------------------
def _from_map(key: str) -> tuple[bool, dict[str, int | None] | None]:
    """``(map_was_loaded, row)``.

    The two must be distinguished. The bulk query selects every asset carrying
    a non-null year, so **absence from a loaded map means the asset has no year**
    - an answer, not a miss. Treating it as a miss would send the 4,044 scored
    assets with no manufacture year to the CMMS one at a time on every sweep,
    adding ~7 minutes to a job the map exists to make fast.
    """
    table = loaded_map()
    if table is None:
        return False, None
    return True, table.get(key)


def _from_cmms(key: str) -> dict[str, int | None] | None:
    if not tomms_configured():
        return None
    try:
        rows = db.tomms_query(_ASSET_SQL, (Config.TOMMS_SITE_CD, key))
    except db.DatabaseError as exc:
        log.warning("manufacture-year lookup failed for %s: %s", key, exc)
        return None
    if not rows:
        return None
    return {"grid": rows[0].get("grid_year"), "line": rows[0].get("line_year")}


def manufacture_year(asset_no: str, follow_oltc_parent: bool = True) -> dict[str, Any] | None:
    """Year of manufacture for one asset, cleaned, with its provenance.

    Returns ``{"year", "age", "column", "label", "source", "assetNo", "raw"}``
    or None when the CMMS has no usable year. `source` is one of
    ``cmms``/``cmms-map`` (`ast_det_datetime1`), ``cmms-local`` (the `(L)`
    fallback), or the same suffixed ``-parent`` when the value came from an
    OLTC's transformer.
    """
    key = normalise(asset_no)
    if not key:
        return None

    have_map, row = _from_map(key)
    via = "cmms-map"
    if not have_map:
        # No map primed - this is a live page, so one row over the wire (~0.1s).
        row = _from_cmms(key)
        via = "cmms"

    result = _resolve(row, key, via)
    if result is not None:
        return result

    # An OLTC with no year of its own inherits its transformer's. Two of the 254
    # scored tap changers need this; the rest carry their own, and 78 of those
    # differ from the parent - so this can only ever be a last resort.
    if follow_oltc_parent:
        parent = parent_of_oltc(asset_no)
        if parent:
            inherited = manufacture_year(parent, follow_oltc_parent=False)
            if inherited:
                inherited = dict(inherited)
                inherited["source"] = inherited["source"] + "-parent"
                inherited["assetNo"] = parent
                inherited["inheritedFrom"] = parent
                return inherited
    return None


def _resolve(row: dict[str, int | None] | None, key: str,
             via: str) -> dict[str, Any] | None:
    if not row:
        return None
    grid = usable_year(row.get("grid"))
    if grid is not None:
        return {"year": grid, "age": age_from_year(grid), "column": YEAR_COLUMN,
                "label": YEAR_LABEL, "source": via, "assetNo": key,
                "raw": row.get("grid")}
    line = usable_year(row.get("line"))
    if line is not None:
        return {"year": line, "age": age_from_year(line),
                "column": YEAR_COLUMN_LOCAL, "label": YEAR_LABEL_LOCAL,
                "source": f"{via}-local", "assetNo": key, "raw": row.get("line")}
    return None


# --------------------------------------------------------------------------
# validation - doc section 11
# --------------------------------------------------------------------------
def verify_label_mapping() -> dict[str, Any]:
    """Cached wrapper - /api/health is polled, and `cf_label` changes rarely."""
    return db.cached("attributes:label-mapping", _verify_label_mapping, ttl=600)


def _verify_label_mapping() -> dict[str, Any]:
    """Assert `cf_label` still calls `ast_det_datetime1` the manufacture year.

    Doc section 11 check 3, and the one that matters: the column number is
    meaningless on its own, and an administrator can re-purpose the UDF slot
    from inside the CMMS with no schema change and no error anywhere. Anything
    reading this field should assert the caption rather than trust the number.
    """
    if not tomms_configured():
        return {"checked": False, "reason": "CMMS not configured"}
    try:
        rows = db.tomms_query(_LABEL_SQL, (YEAR_COLUMN, YEAR_COLUMN_LOCAL))
    except db.DatabaseError as exc:
        return {"checked": False, "reason": str(exc)}

    found = {r["column_name"]: (r.get("label") or "").rstrip(":").strip()
             for r in rows}
    grid = found.get(YEAR_COLUMN)
    return {
        "checked": True,
        "ok": grid == YEAR_LABEL,
        "column": YEAR_COLUMN,
        "expected": YEAR_LABEL,
        "actual": grid,
        "localColumn": YEAR_COLUMN_LOCAL,
        "localActual": found.get(YEAR_COLUMN_LOCAL),
        "message": ("" if grid == YEAR_LABEL else
                    f"{YEAR_COLUMN} is now labelled {grid!r}, not {YEAR_LABEL!r}. "
                    "Someone reconfigured the CMMS - re-run the cf_label lookup "
                    "in ASSET_ATTRIBUTES_INTEGRATION.md section 3 and update "
                    "YEAR_COLUMN before trusting any age."),
    }


def coverage(asset_numbers: list[str]) -> dict[str, Any]:
    """How many of the given assets get a usable manufacture year. For /api/health."""
    table = loaded_map()
    if table is None:
        return {"available": False,
                "reason": "manufacture-year map not primed (run the snapshot job)"}
    hit = junk = 0
    for number in asset_numbers:
        row = table.get(normalise(number))
        if not row:
            continue
        if _resolve(row, normalise(number), "cmms-map") is not None:
            hit += 1
        else:
            junk += 1
    return {"available": True, "assets": len(asset_numbers), "withYear": hit,
            "rejectedAsJunk": junk, "mapSize": len(table),
            "cacheAgeHours": round(_cache_age_hours() or 0.0, 2),
            "percent": round(hit / len(asset_numbers) * 100, 1) if asset_numbers else 0.0}
