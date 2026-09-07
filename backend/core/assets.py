"""Asset inventory.

`CEB_ASSET` is empty in the live database, so the fleet is derived from the
`AssetNumber` values present in the test tables. Asset numbers are structured:

    G001/PE/1/02/MT01_X/01
    |    |  | |  |    |  +-- occurrence
    |    |  | |  |    +----- phase (R/Y/B/X/N)
    |    |  | |  +---------- equipment type + index (MT01, CT01, VT01, SA01, 52, 89A...)
    |    |  | +------------- bay
    |    |  +--------------- voltage/section index
    |    +------------------ PE = primary equipment
    +----------------------- grid substation code

OLTC assets carry an extra segment: `G001/PE/1/02/MT01_X/OLTC/01`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

import db

# Equipment-type token -> (asset type used by the HI engine, display label)
TYPE_TOKENS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^MT\d*$"), "TR", "Power Transformer"),
    (re.compile(r"^IBT\d*$"), "TR", "Inter Bus Transformer"),
    (re.compile(r"^ET\d*$"), "TR", "Earthing Transformer"),
    (re.compile(r"^AT\d*$"), "TR", "Auxiliary Transformer"),
    (re.compile(r"^AET\d*$"), "TR", "Auxiliary/Earthing Transformer"),
    (re.compile(r"^CT\d*$"), "CTVT", "Current Transformer"),
    (re.compile(r"^VT\d*$"), "CTVT", "Voltage Transformer"),
    (re.compile(r"^CVT\d*$"), "CTVT", "Capacitor Voltage Transformer"),
    (re.compile(r"^SA\d*$"), "SA", "Surge Arrester"),
    (re.compile(r"^52\w*$"), "CB", "Circuit Breaker"),
    (re.compile(r"^89\w*$"), "ESDS", "Earth Switch / Disconnector"),
    (re.compile(r"^CB\d*$"), "CBank", "Capacitor Bank"),
    (re.compile(r"^BB\d*$"), "BBank", "Battery Bank"),
]

# Human labels for the engine's asset-type codes.
ASSET_TYPE_LABEL = {
    "TR": "Power Transformer",
    "CTVT": "Current / Voltage Transformer",
    "CB": "Circuit Breaker",
    "ESDS": "Earth Switch / Disconnector",
    "SA": "Surge Arrester",
    "CBank": "Capacitor Bank",
    "BBank": "Battery Bank",
}

# --------------------------------------------------------------------------
# Categories
#
# `assetType` drives scoring - it selects the weights and score bands, and every
# transformer variant shares the TR configuration. `category` is the reporting
# grouping, which separates the three kinds of transformer that engineers treat
# as distinct populations:
#
#   TR    power and inter-bus transformers - the main fleet
#   AET   earthing (ET) and auxiliary (AT) transformers
#   OLTC  on-load tap changers, which are their own asset numbers under a
#         parent transformer and are scored only on OLTC oil tests
#
# OTHER collects entries that are not really assets - bare site codes, IEDs,
# spares - so they cannot inflate the transformer population.
# --------------------------------------------------------------------------
EARTHING_TOKENS = re.compile(r"^(ET|AT|AET)\d*$")
POWER_TOKENS = re.compile(r"^(MT|IBT)\d*$")

CATEGORY_LABEL = {
    "TR": "Power Transformers",
    "AET": "Earthing / Auxiliary Transformers",
    "OLTC": "On-Load Tap Changers",
    "CTVT": "Current / Voltage Transformers",
    "CB": "Circuit Breakers",
    "ESDS": "Earth Switches / Disconnectors",
    "SA": "Surge Arresters",
    "CBank": "Capacitor Banks",
    "BBank": "Battery Banks",
    "OTHER": "Other / Unclassified",
}

# Display order for the type selector.
CATEGORY_ORDER = ["TR", "AET", "OLTC", "CTVT", "CB", "ESDS", "SA", "CBank",
                  "BBank", "OTHER"]


def categorise(asset_type: str, sub_type: str, is_oltc: bool) -> str:
    """Reporting category for an asset. See the note above."""
    if is_oltc:
        return "OLTC"
    token = (sub_type or "").upper()
    if asset_type == "TR":
        if EARTHING_TOKENS.match(token):
            return "AET"
        if POWER_TOKENS.match(token):
            return "TR"
        # Bare site codes, IEDs, voltage regulators, spares - not transformers.
        return "OTHER"
    return asset_type if asset_type in CATEGORY_LABEL else "OTHER"

# Tables scanned to build the inventory, with the asset type they imply when the
# asset number itself is ambiguous.
SOURCE_TABLES: list[tuple[str, str | None]] = [
    ("CEB_MT_IBT", "TR"),
    ("CEB_DGA_DATA", "TR"),
    ("CEB_AET", "TR"),
    ("CEB_OUT_CT", "CTVT"),
    ("CEB_OUT_VT", "CTVT"),
    ("CEB_SA", "SA"),
    ("CEB_OUT_3PH_CB", "CB"),
    ("CEB_OUT_1PH_CB", "CB"),
    ("CEB_OUT_ESDS", "ESDS"),
    ("CEB_OLTC", "TR"),
]

_SEG = re.compile(r"[/\\]")

# `OLTC`, plus `OLTC1` / `OLTC2` for units with two tap changers.
OLTC_SEGMENT = re.compile(r"^OLTC\d*$")


@dataclass
class Asset:
    assetNumber: str
    assetType: str          # scoring type: TR | CTVT | CB | ESDS | SA | CBank | BBank
    category: str           # reporting group: TR | AET | OLTC | CTVT | ... | OTHER
    subType: str            # CT / VT / MT / ET / AT / SA / 52 / 89A ...
    label: str              # human description of the equipment kind
    site: str               # G001
    bay: str                # 02
    phase: str              # R / Y / B / X / N / ''
    isOltc: bool
    sources: list[str]      # tables the asset was seen in

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_asset_number(number: str) -> dict[str, Any] | None:
    """Split an asset number into its parts. Returns None if unrecognisable."""
    if not number:
        return None
    raw = number.strip()
    if not raw:
        return None
    segs = [s for s in _SEG.split(raw) if s != ""]
    if len(segs) < 5:
        # Bare site codes such as "G001" or foreign ids such as "AST100006".
        return {
            "site": segs[0] if segs else raw,
            "bay": "",
            "typeToken": "",
            "index": "",
            "phase": "",
            "isOltc": False,
        }

    # A transformer's tap changer is its own asset number, carrying an extra
    # segment. Inter-bus units have two of them, numbered OLTC1 and OLTC2, so
    # the match cannot be an exact "OLTC".
    is_oltc = any(OLTC_SEGMENT.match(s.upper()) for s in segs)
    equip = next((s for s in segs[4:] if not OLTC_SEGMENT.match(s.upper())), segs[4])

    phase = ""
    token = equip
    if "_" in equip:
        token, _, phase = equip.partition("_")
    m = re.match(r"^([A-Za-z]+|\d{2}[A-Za-z]?)(\d*)$", token)
    base, idx = (m.group(1), m.group(2)) if m else (token, "")

    return {
        "site": segs[0],
        "bay": segs[3] if len(segs) > 3 else "",
        "typeToken": token,
        "baseToken": base,
        "index": idx,
        "phase": phase.upper(),
        "isOltc": is_oltc,
    }


def classify(number: str, hint: str | None = None) -> tuple[str, str, str]:
    """Return (assetType, subType, label) for an asset number."""
    parts = parse_asset_number(number)
    token = (parts or {}).get("typeToken", "") or ""
    for pattern, asset_type, label in TYPE_TOKENS:
        if pattern.match(token.upper()):
            return asset_type, token.upper(), label
    if hint:
        return hint, token.upper() or hint, ASSET_TYPE_LABEL.get(hint, hint)
    return "UNKNOWN", token.upper(), "Unclassified"


def _fetch_numbers(table: str) -> list[str]:
    rows = db.query(
        f"SELECT DISTINCT LTRIM(RTRIM(AssetNumber)) AS a FROM {table} "
        "WHERE AssetNumber IS NOT NULL AND LTRIM(RTRIM(AssetNumber)) <> ''"
    )
    return [r["a"] for r in rows if r["a"]]


def _build() -> list[Asset]:
    seen: dict[str, Asset] = {}
    for table, hint in SOURCE_TABLES:
        try:
            numbers = _fetch_numbers(table)
        except db.DatabaseError:
            continue
        for number in numbers:
            parts = parse_asset_number(number)
            if not parts:
                continue
            # OLTC rows describe the parent transformer, not a separate asset.
            key = number
            existing = seen.get(key)
            if existing:
                if table not in existing.sources:
                    existing.sources.append(table)
                continue
            asset_type, sub, label = classify(number, hint)
            is_oltc = bool(parts.get("isOltc"))
            category = categorise(asset_type, sub, is_oltc)
            seen[key] = Asset(
                assetNumber=number,
                assetType=asset_type,
                category=category,
                subType=sub,
                label="On-Load Tap Changer" if category == "OLTC" else label,
                site=parts.get("site", ""),
                bay=parts.get("bay", ""),
                phase=parts.get("phase", ""),
                isOltc=is_oltc,
                sources=[table],
            )
    return sorted(seen.values(), key=lambda a: a.assetNumber)


def all_assets(refresh: bool = False) -> list[Asset]:
    if refresh:
        db.clear_cache("assets:")
    return db.cached("assets:all", _build)


def by_type(asset_type: str) -> list[Asset]:
    return [a for a in all_assets() if a.assetType == asset_type]


def get(number: str) -> Asset | None:
    number = (number or "").strip()
    return next((a for a in all_assets() if a.assetNumber == number), None)


def counts(items: list[Asset] | None = None) -> dict[str, Any]:
    """Headline inventory counts for the dashboard tiles.

    CT and VT are separated here because the dashboard shows them as distinct
    tiles even though the HI engine scores them under one 'CTVT' type.

    `items` narrows the tally to a subset - the hierarchy scope passes its
    filtered list so the tiles count what is actually on screen.
    """
    assets = all_assets() if items is None else items
    tally: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for a in assets:
        tally[a.assetType] = tally.get(a.assetType, 0) + 1
        by_category[a.category] = by_category.get(a.category, 0) + 1

    ct = sum(1 for a in assets if a.subType.startswith("CT"))
    vt = sum(1 for a in assets if a.subType.startswith("VT") or a.subType.startswith("CVT"))

    sites = sorted({a.site for a in assets if a.site})
    return {
        "total": len(assets),
        # "transformers" now means power and inter-bus units only; earthing and
        # OLTC are reported separately because they are distinct populations.
        "transformers": by_category.get("TR", 0),
        "earthingTransformers": by_category.get("AET", 0),
        "oltc": by_category.get("OLTC", 0),
        "transformersAll": tally.get("TR", 0),
        "ct": ct,
        "vt": vt,
        "ctvt": tally.get("CTVT", 0),
        "surgeArresters": tally.get("SA", 0),
        "circuitBreakers": tally.get("CB", 0),
        "esds": tally.get("ESDS", 0),
        "capacitorBanks": tally.get("CBank", 0),
        "batteryBanks": tally.get("BBank", 0),
        "other": by_category.get("OTHER", 0),
        "sites": len(sites),
        "byType": tally,
        "byCategory": by_category,
    }


def by_category(category: str) -> list[Asset]:
    return [a for a in all_assets() if a.category == category]


def sites() -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for a in all_assets():
        if not a.site:
            continue
        entry = grouped.setdefault(a.site, {"site": a.site, "total": 0, "byType": {}})
        entry["total"] += 1
        entry["byType"][a.assetType] = entry["byType"].get(a.assetType, 0) + 1
    return sorted(grouped.values(), key=lambda e: e["site"])
