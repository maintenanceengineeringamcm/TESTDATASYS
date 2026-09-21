r"""Asset hierarchy - the browsable tree behind the navigator sidebar.

Rebuilds the CEB transmission hierarchy described in
`ASSET_HIERARCHY_INTEGRATION.md` so users can find plant by *name* instead of by
asset code, and use a tree selection as a scope filter on the analysis screens.

The name shown for a node is `ast_mst_asset_shortdesc`, the description an
engineer wrote in the CMMS. Three sources supply it, tried in order:

1. **The `Tomms_CEBT` CMMS database directly** (`source = "cmms"`) - reads
   `ast_mst` live, so a rename in the CMMS shows up on the next cache expiry.
   Requires `HI_TOMMS_DB_SERVER`; skipped when that is unset or unreachable.

2. **The `Tomms_CEBT` staging table** in CEB_TRANSMISSION (`source = "staging"`)
   - `tomms_asset_no` + `asset_desc`, a local copy of the same two columns for
   sites where the CMMS is not reachable from the API host. Fill it with
   `sync_hierarchy.py`.

3. **Derived from the asset numbers** (`source = "derived"`) - the fallback when
   neither is available. `ast_mst_asset_no` is a materialised path (doc 3), so
   the tree can be rebuilt from the asset numbers the HI engine already knows,
   and a readable label synthesised at every level from the code semantics in
   doc 4. Nothing is blank, but no name here was written by an engineer.

On this machine both databases sit on the same host but on *different SQL Server
instances*, which is easy to miss:

    CEB_TRANSMISSION -> DESKTOP-E3R1QOH\SQLEXPRESS   (SQL Server 2022)
    Tomms_CEBT       -> DESKTOP-E3R1QOH              (default instance, 2025)

`source` and `named` in the API payload say which source produced the tree and
how many nodes carry a real description.

Points from the integration document that this module honours:

* the parent link, not the string path, is authoritative when both exist (3);
* `'N/A'` is a *string*, not a null, and must be normalised on ingest (9.3);
* the source collation is case-insensitive, so the index is keyed upper-case
  (9.7) - `g001` and `G001` are one node, not two;
* depth is derived by iterative BFS, never read from a column and never
  recursive, so a data-entry cycle fails loudly instead of blowing the stack
  (7 step 3);
* orphans are promoted to roots and flagged rather than dropped (9.1).
"""
from __future__ import annotations

import logging
import re
from collections import deque
from typing import Any

import db
from config import Config, tomms_configured

from . import assets as assets_mod

log = logging.getLogger(__name__)

# Statuses admitted to the tree. 'ISF' (In Service Full) alone by default, so
# the navigator shows the operational fleet and not decommissioned plant.
KEEP_STATUSES = Config.HIERARCHY_STATUSES

# Column names the status could arrive under once the staging sync carries it.
# Matched against this whitelist before use - never interpolated blind.
STATUS_COLUMNS = ("ast_mst_asset_status", "asset_status", "status_cd", "status")

# --------------------------------------------------------------------------
# Level vocabulary (integration doc section 4)
# --------------------------------------------------------------------------

# Level-4 discipline codes. The HI fleet is almost all PE, but the others appear.
DISCIPLINE = {
    "PE": "Primary Equipment",
    "CP": "Control & Protection",
    "CE": "Communication Equipment",
    "ME": "Metering Equipment",
    "SE": "Secondary Equipment",
}

# Level-5 voltage codes. Deliberately NOT ordered by magnitude - sorting the
# code sorts wrongly, so the display order is kept explicit below.
VOLTAGE_KV = {"0": 11, "1": 132, "2": 220, "3": 33}
VOLTAGE_ORDER = {"2": 0, "1": 1, "3": 2, "0": 3}  # 220 -> 132 -> 33 -> 11

# Substation names. Only the ten largest are published in the integration
# document; the rest resolve once the Tomms staging table is synced. Unknown
# codes fall back to "Grid Substation <code>" so the tree is never blank.
SITE_NAMES = {
    "G008": "Biyagama GS",
    "G025": "Kotugoda SS",
    "G043": "Pannipitiya SS",
    "G023": "Kolonnawa SS",
    "G036": "New Galle GS",
    "G061": "Colombo L (Port) GSS",
    "G018": "Kelanitissa GS",
    "G034": "New Anuradhapura GS",
}

_SEG = re.compile(r"[/\\]")
_OLTC_SEG = re.compile(r"^OLTC(\d*)$", re.I)
_BUSBAR_SEG = re.compile(r"^BB(\d*)$", re.I)
_NUMERIC_SEG = re.compile(r"^\d+$")
_SITE_CODE = re.compile(r"^G\d+$")

PHASE_LABEL = {"R": "R-phase", "Y": "Y-phase", "B": "B-phase", "N": "Neutral"}


def _norm(value: Any) -> str | None:
    """Trim, and collapse the placeholder strings to None (doc 9.3)."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "N/A") else text


# --------------------------------------------------------------------------
# Label synthesis - turns a path segment into something a human can search
# --------------------------------------------------------------------------
def _describe(segment: str, depth: int, segments: list[str]) -> tuple[str, str]:
    """Return (label, kind) for one segment at `depth` (1-based)."""
    up = segment.upper()

    if depth == 1:
        if up in SITE_NAMES:
            return SITE_NAMES[up], "site"
        # A few test records carry a foreign id rather than a site code
        # (doc 9.2). Calling those "Grid Substation AST100006" would be a lie.
        if _SITE_CODE.match(up):
            return f"Grid Substation {segment}", "site"
        return f"Unassigned - {segment}", "unassigned"

    if depth == 2:
        return DISCIPLINE.get(up, segment), "discipline"

    if depth == 3:
        kv = VOLTAGE_KV.get(up)
        return (f"{kv} kV" if kv else segment), "voltage"

    if depth == 4:
        busbar = _BUSBAR_SEG.match(up)
        if busbar:
            return (f"Busbar {busbar.group(1)}".strip(), "bay")
        return f"Bay {segment}", "bay"

    # Depth 5+ : equipment, an optional OLTC segment, then the unit number.
    oltc = _OLTC_SEG.match(up)
    if oltc:
        return (f"On-Load Tap Changer {oltc.group(1)}".strip(), "oltc")

    if _NUMERIC_SEG.match(up) and depth >= 6:
        return f"Unit {segment}", "unit"

    # Equipment segment: MT01_X, CT01_R, 52A_X, 89D_X ...
    token, _, phase = segment.partition("_")
    # classify() reads the equipment token out of a full asset number, so a
    # representative one is rebuilt around this segment rather than passing the
    # bare token, which would not parse.
    _, _, label = assets_mod.classify("/".join(segments[:4] + [segment, "01"]))
    if label == "Unclassified":
        label = token.upper()
    name = f"{label} {token.upper()}"
    phase_text = PHASE_LABEL.get(phase.upper(), "")
    if phase_text:
        name = f"{name}, {phase_text}"
    return name, "equipment"


def _sort_key(node: dict[str, Any]) -> tuple:
    """Children sort by meaning, not by code.

    Voltage is the case that matters: the codes are 0/1/2/3 for 11/132/220/33 kV,
    so a plain string sort puts 11 kV before 220 kV. Bays sort numerically.
    """
    code, kind = node["code"], node["kind"]
    if kind == "voltage":
        return (0, VOLTAGE_ORDER.get(code.upper(), 9), code.upper())
    if kind == "bay" and _NUMERIC_SEG.match(code):
        return (0, int(code), "")
    return (1, 0, code.upper())


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
class CycleDetected(RuntimeError):
    """A parent link points back into its own subtree (doc 9.6)."""


# The CMMS pull. `ast_mst_asset_shortdesc` is the display name the navigator
# shows; the status drives the ISF filter. Kept to the two columns actually
# used - the full enrichment join in doc 6.1 is not needed to name a node.
TOMMS_SQL = """
SELECT LTRIM(RTRIM(m.ast_mst_asset_no))        AS asset_no,
       LTRIM(RTRIM(m.ast_mst_asset_shortdesc)) AS short_desc,
       LTRIM(RTRIM(m.ast_mst_asset_status))    AS status
FROM ast_mst m
WHERE m.site_cd = ?
  AND m.ast_mst_asset_no IS NOT NULL
  AND LTRIM(RTRIM(m.ast_mst_asset_no)) <> ''
"""


def _cmms_rows() -> list[dict[str, Any]]:
    """Rows straight from the CMMS `ast_mst`, or [] when it is not reachable.

    Preferred over the staging table because it cannot go stale. A failure here
    is not fatal - the navigator falls back rather than refusing to render.
    """
    if not tomms_configured():
        return []
    try:
        rows = db.tomms_query(TOMMS_SQL, [Config.TOMMS_SITE_CD])
    except db.DatabaseError as exc:
        log.warning("Tomms CMMS unreachable, falling back: %s", exc)
        return []
    return [r for r in rows if _norm(r.get("asset_no"))]


def _staging_columns() -> set[str]:
    """Column names present on the staging table, lower-cased."""
    try:
        rows = db.query(
            "SELECT LOWER(COLUMN_NAME) AS c FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'Tomms_CEBT'"
        )
    except db.DatabaseError:
        return set()
    return {r["c"] for r in rows if r.get("c")}


def _staging_rows() -> list[dict[str, Any]]:
    """Rows from the Tomms_CEBT staging table, or [] when it is empty/absent.

    The staging table as it stands carries no status column, so the ISF filter
    has nothing to act on yet. Rather than hard-code that, the status column is
    picked up whenever the sync adds one under any of its plausible names - the
    filter then starts working with no code change. The name is matched against
    a fixed whitelist before it reaches the SQL, so nothing dynamic is
    interpolated into the statement.
    """
    available = _staging_columns()
    status_col = next((c for c in STATUS_COLUMNS if c in available), None)
    status_select = (
        f"LTRIM(RTRIM({status_col})) AS status" if status_col else "NULL AS status"
    )
    try:
        rows = db.query(
            "SELECT LTRIM(RTRIM(tomms_asset_no)) AS asset_no, "
            "       LTRIM(RTRIM(asset_desc))     AS short_desc, "
            f"      {status_select} "
            "FROM Tomms_CEBT "
            "WHERE tomms_asset_no IS NOT NULL AND LTRIM(RTRIM(tomms_asset_no)) <> ''"
        )
    except db.DatabaseError:
        return []
    return [r for r in rows if _norm(r.get("asset_no"))]


def _build() -> dict[str, Any]:
    """Build the whole tree once. O(n); cached by :func:`tree`."""
    fleet = assets_mod.all_assets()

    # Names and statuses, in order of authority: the live CMMS, then the local
    # staging copy of it, then nothing (labels get synthesised from the codes).
    feed = _cmms_rows()
    source = "cmms"
    if not feed:
        feed = _staging_rows()
        source = "staging"

    # Keyed upper-case to match the source collation (doc 9.7).
    descriptions: dict[str, str] = {}
    statuses: dict[str, str] = {}
    for row in feed:
        code = _norm(row.get("asset_no"))
        if not code:
            continue
        desc = _norm(row.get("short_desc"))
        if desc:
            descriptions[code.upper()] = desc
        status = _norm(row.get("status"))
        if status:
            statuses[code.upper()] = status.upper()
    if not descriptions:
        source = "derived"

    index: dict[str, dict[str, Any]] = {}   # keyed UPPER (doc 9.7)
    roots: list[dict[str, Any]] = []

    def ensure(segments: list[str], depth: int) -> dict[str, Any]:
        """Create (or fetch) the node for the first `depth` segments."""
        key = "/".join(segments[:depth]).upper()
        node = index.get(key)
        if node is not None:
            return node

        code = segments[depth - 1]
        label, kind = _describe(code, depth, segments)
        node = {
            "assetNo": "/".join(segments[:depth]),
            "parentId": "/".join(segments[: depth - 1]) if depth > 1 else None,
            "code": code,
            "label": descriptions.get(key, label),
            # True when the name is the CMMS ast_mst_asset_shortdesc rather
            # than one this app synthesised from the code.
            "named": key in descriptions,
            "kind": kind,
            "depth": depth,
            "children": [],
            "assetCount": 0,        # HI assets in this subtree
            "categories": set(),
            "isAsset": False,
        }
        index[key] = node

        if depth == 1:
            roots.append(node)
        else:
            ensure(segments, depth - 1)["children"].append(node)
        return node

    # Status tally, reported so it is visible whether the filter did anything.
    kept = excluded = unknown = 0

    for asset in fleet:
        segments = [s for s in _SEG.split(asset.assetNumber) if s]
        if not segments:
            continue
        leaf = ensure(segments, len(segments))
        leaf["isAsset"] = True
        leaf["assetType"] = asset.assetType
        leaf["category"] = asset.category
        # A synthesised "Unit 01" is not searchable on its own, so it borrows
        # its equipment's name. A real CMMS description is never touched -
        # prefixing it would corrupt the name an engineer actually wrote.
        if leaf["kind"] == "unit" and len(segments) >= 2 and not leaf["named"]:
            parent = index["/".join(segments[:-1]).upper()]
            if parent["kind"] in ("equipment", "oltc"):
                leaf["label"] = f'{parent["label"]} - {leaf["label"]}'

        # Only in-service plant is counted. The node is still created either
        # way: a deactivated parent has to stay walkable or every in-service
        # child beneath it is detached (doc 9.10).
        status = statuses.get(asset.assetNumber.upper())
        leaf["status"] = status
        if status is None:
            unknown += 1
            in_service = Config.HIERARCHY_KEEP_UNKNOWN_STATUS
        else:
            in_service = status in KEEP_STATUSES
        if not in_service:
            excluded += 1
            continue
        kept += 1

        # Roll the asset up through every ancestor.
        for depth in range(1, len(segments) + 1):
            node = index["/".join(segments[:depth]).upper()]
            node["assetCount"] += 1
            node["categories"].add(asset.category)

    # Prune what holds no in-service plant. Done *after* the tree is built,
    # never during: filtering on the way in would drop a deactivated bay and
    # take its in-service equipment with it (doc 9.10). A node's own asset
    # counts toward its `assetCount`, so this drops excluded leaves and keeps
    # any ancestor that still has something in service beneath it.
    for node in list(index.values()):
        if node["assetCount"] == 0:
            del index[node["assetNo"].upper()]
    for node in index.values():
        node["children"] = [c for c in node["children"] if c["assetCount"] > 0]
    roots = [r for r in roots if r["assetCount"] > 0]

    # Lift a name up through a pure grouping node.
    #
    # `ast_mst` has no row for the equipment segment: the CMMS names the unit
    # (`.../52_X/01` - "Circuit Breaker B-Phase") but not the `.../52_X` level,
    # which exists only because the asset number has a segment there. Left
    # alone, 11,000-odd equipment nodes would show a derived name directly
    # above a child carrying the real one.
    #
    # Only when the node has exactly one child: with siblings there is no
    # single description that speaks for the group, and picking one would be a
    # guess. The name is still the engineer's, recorded one level down.
    for node in index.values():
        if node["named"] or len(node["children"]) != 1:
            continue
        only = node["children"][0]
        if only["named"]:
            node["label"] = only["label"]
            node["named"] = True

    # Depth + path by iterative BFS. A cycle cannot arise from a path-derived
    # tree, but the guard is kept so the same code survives a switch to the
    # parent-link source, where one could (doc 7 step 3, 9.6).
    seen: set[str] = set()
    queue: deque[dict[str, Any]] = deque()
    for node in roots:
        node["path"] = node["label"]
        queue.append(node)
    while queue:
        node = queue.popleft()
        if node["assetNo"].upper() in seen:
            raise CycleDetected(node["assetNo"])
        seen.add(node["assetNo"].upper())
        node["children"].sort(key=_sort_key)
        for child in node["children"]:
            child["path"] = f'{node["path"]} > {child["label"]}'
            queue.append(child)
    if len(seen) != len(index):
        raise CycleDetected(f"{len(index) - len(seen)} nodes unreachable")

    roots.sort(key=_sort_key)
    for node in index.values():
        node["categories"] = sorted(node["categories"])
        # Searchable haystack: the code plus every ancestor label, so
        # "biyagama transformer" matches without the user knowing G008.
        node["_hay"] = f'{node["assetNo"]} {node["path"]}'.lower()

    named = sum(1 for n in index.values() if n["named"])
    return {
        "roots": roots, "index": index, "source": source,
        "total": len(index),
        # How many nodes show ast_mst_asset_shortdesc rather than a synthesised
        # name. Partial coverage is normal - intermediate nodes such as a bay
        # may have no CMMS row even when its equipment does.
        "named": named,
        # `assets` is the in-service population now, not the raw fleet - it is
        # what the navigator counts add up to.
        "assets": kept,
        "status": {
            "keep": sorted(KEEP_STATUSES),
            "kept": kept,
            "excluded": excluded,
            "unknown": unknown,
            # False while nothing feeds a status through, so the UI can say the
            # filter is declared but inert rather than implying it ran.
            "available": bool(statuses),
            "keepUnknown": Config.HIERARCHY_KEEP_UNKNOWN_STATUS,
        },
    }


def tree(refresh: bool = False) -> dict[str, Any]:
    if refresh:
        db.clear_cache("hierarchy:")
    return db.cached("hierarchy:tree", _build)


# --------------------------------------------------------------------------
# Public accessors
# --------------------------------------------------------------------------
def _public(node: dict[str, Any], with_children: bool = False) -> dict[str, Any]:
    out = {
        "assetNo": node["assetNo"],
        "parentId": node["parentId"],
        "code": node["code"],
        "label": node["label"],
        "named": node.get("named", False),
        "kind": node["kind"],
        "depth": node["depth"],
        "path": node.get("path", node["label"]),
        "assetCount": node["assetCount"],
        "categories": node["categories"],
        "isAsset": node["isAsset"],
        "childCount": len(node["children"]),
    }
    if node["isAsset"]:
        out["assetType"] = node.get("assetType")
        out["category"] = node.get("category")
        out["status"] = node.get("status")
    if with_children:
        out["children"] = [_public(c) for c in node["children"]]
    return out


def get(asset_no: str | None) -> dict[str, Any] | None:
    code = _norm(asset_no)
    return tree()["index"].get(code.upper()) if code else None


def node(asset_no: str) -> dict[str, Any] | None:
    """One node in its public shape, or None if the code is unknown."""
    found = get(asset_no)
    return _public(found) if found else None


def children(parent: str | None = None) -> list[dict[str, Any]]:
    """One level of the tree. `None` returns the roots (the substations)."""
    if not _norm(parent):
        return [_public(n) for n in tree()["roots"]]
    node = get(parent)
    return [_public(c) for c in node["children"]] if node else []


def subtree(asset_no: str | None = None, depth: int = 1) -> list[dict[str, Any]] | None:
    """Nested nodes `depth` levels deep, starting at `asset_no` or at the roots.

    `depth=0` returns the starting node(s) alone. Every node carries `children`
    - empty past the depth limit, with `childCount` still saying what is there -
    so a caller can tell "a leaf" from "not expanded". Returns None for an
    unknown `asset_no`.
    """
    def expand(node: dict[str, Any], remaining: int) -> dict[str, Any]:
        out = _public(node)
        out["children"] = ([expand(c, remaining - 1) for c in node["children"]]
                           if remaining > 0 else [])
        return out

    if not _norm(asset_no):
        return [expand(n, depth) for n in tree()["roots"]]
    start = get(asset_no)
    return [expand(start, depth)] if start else None


def ancestors(asset_no: str) -> list[dict[str, Any]]:
    """Root-first breadcrumb, inclusive of the node itself (doc 6.4)."""
    node, trail, guard = get(asset_no), [], 0
    while node is not None and guard < 100:
        trail.append(_public(node))
        node = get(node["parentId"])
        guard += 1
    return list(reversed(trail))


def search(term: str, limit: int = 40) -> list[dict[str, Any]]:
    """Match on asset code *or* any word of the description path.

    Every whitespace-separated word must appear somewhere in the node's code or
    its full breadcrumb, so "biyagama 132 breaker" narrows the way a user
    expects rather than returning the union of three loose matches.
    """
    words = [w for w in (term or "").lower().split() if w]
    if not words:
        return []
    hits = [n for n in tree()["index"].values()
            if all(w in n["_hay"] for w in words)]
    # Shallow, asset-heavy nodes first: scoping to a substation is more often
    # what was meant than scoping to one of its 1,200 individual units.
    hits.sort(key=lambda n: (n["depth"], -n["assetCount"], n["assetNo"]))
    return [_public(n) for n in hits[:limit]]


def descendants(asset_no: str) -> list[str]:
    """Every HI asset number beneath `asset_no`, inclusive."""
    node = get(asset_no)
    if not node:
        return []
    out: list[str] = []
    queue = deque([node])
    while queue:
        current = queue.popleft()
        if current["isAsset"]:
            out.append(current["assetNo"])
        queue.extend(current["children"])
    return out


def excluded_assets() -> set[str]:
    """Asset numbers the status filter rejects.

    Empty while no status feed exists — nothing can be excluded on evidence we
    do not have. Callers use this to keep other screens consistent with the
    navigator, which has already pruned these from the tree.

    Returns the *rejected* set rather than the accepted one because it is the
    small side: a few hundred deactivated units against 13k in service.
    """
    data = tree()
    if not data["status"]["available"]:
        return set()
    kept = {n["assetNo"] for n in data["index"].values() if n["isAsset"]}
    return {a.assetNumber for a in assets_mod.all_assets()
            if a.assetNumber not in kept}


def scope_label(asset_no: str) -> str | None:
    """Breadcrumb text for the scope banner on a filtered screen."""
    node = get(asset_no)
    return node["path"] if node else None


def stats() -> dict[str, Any]:
    data = tree()
    return {
        "source": data["source"],
        "nodes": data["total"],
        "assets": data["assets"],
        "roots": len(data["roots"]),
        "named": data["named"],
        "maxDepth": max((n["depth"] for n in data["index"].values()), default=0),
        "status": data["status"],
    }
