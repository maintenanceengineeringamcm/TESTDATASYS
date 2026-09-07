"""Score bands and component weights, loaded from the live configuration tables.

Two versioned config stores drive every health index:

* `SCORE_MAIN` / `SCORE_VALUE` - the range tables. `SCORE_VALUE.Parent` points at
  a `SCORE_MAIN.ID`; the newest id per asset type wins.
* `WEIGHT_MAIN` / `WEIGHT_VALUE` - component weights, same parent/child shape.

Two properties of the live data shape the lookup:

1. Component scores run 0..1 where **1 is healthy**, and weights sum to 100, so
   `HI = sum(normalisedWeight% * score)` lands on 0..100 with **higher = better**.
   This settles the polarity question left open in the automation spec.
2. Bands for "higher is better" quantities (BDV, IFT, IR, PD) are stored
   *descending*: `RangeFrom` is the upper edge and `RangeTo` the lower one. The
   lookup must therefore normalise each band before comparing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import db
from core import overrides

log = logging.getLogger(__name__)

# Component code (spec vocabulary) -> band name stored in SCORE_VALUE.Type,
# per asset type. Components absent from a map are manual-entry only.
BAND_FOR_COMPONENT: dict[str, dict[str, str]] = {
    "TR": {
        "AGE": "AGE",
        "FURAN": "FURAN",
        "DGAL": "DGA",       # the weighted gas index, not a raw gas
        "TAND": "DF",
        "DRA": "DIRANA",
        "TR": "TTR",
        "LR": "LEAK",
        "WR": "DCW",
        "EC": "EXCU",
        "IR": "IR",
        "BDVO1": "BDV",
        "MIO1": "MOIST",
        "AIO": "ACID",
        "IFTO": "IFT",
        "PDL": "PD",
        "BDVO2": "BDV",
        "MIO2": "MOIST",
    },
    "CTVT": {"AGE": "AGE#CTVT", "TAND": "TAND#CTVT", "IR": "IR#CTVT"},
    "CB": {
        "AGE": "AGE#CB",
        "NOO": "NOO#CB",
        "CR": "CR#CB",
        "IR": "IR#CB",
        "SFDP": "SFDP#CB",
    },
    "ESDS": {"AGE": "AGE#ESDS", "CR": "CR#ESDS"},
    # The surge-arrester "CR" component reads a counter reading, and the live
    # config stores its band under NOO#SA rather than CR#SA.
    "SA": {"AGE": "AGE#SA", "CR": "NOO#SA", "IR": "IR#SA"},
    "CBank": {"AGE": "AGE#CBank"},
    "BBank": {"AGE": "AGE#BBank"},
}

# Per-gas bands used by the DGA gas-level component.
DGA_GAS_BANDS = {
    "H2": "H2",
    "CH4": "CH4",
    "CO": "CO",
    "CO2": "CO2",
    "C2H4": "C2H4",
    "C2H6": "C2H6",
    "C2H2": "C2H2",
}

# Components with no database read - a human supplies the score.
MANUAL_COMPONENTS: dict[str, set[str]] = {
    "TR": {"DGAT", "SFRAPBC", "SFRATBC", "PDL", "OLTC"},
    "CTVT": {"DRA", "RC", "OVC"},
    "CB": {"OCT", "TD", "SFP", "OVC"},
    "ESDS": {"OVC"},
    "SA": {"OC"},
    "CBank": {"CAP"},
    "BBank": {"IR", "CV", "SG"},
}

# Display order for each asset type's components. This is also the slot order
# used by HEALTH_INDEX.LastScores.
COMPONENT_ORDER: dict[str, list[str]] = {
    "TR": [
        "AGE", "FURAN", "DGAL", "DGAT", "TAND", "DRA", "SFRAPBC", "SFRATBC",
        "TR", "LR", "WR", "EC", "IR", "BDVO1", "MIO1", "AIO", "IFTO", "PDL",
        "BDVO2", "MIO2", "OLTC",
    ],
    "CTVT": ["AGE", "TAND", "DRA", "RC", "IR", "OVC"],
    "CB": ["AGE", "NOO", "CR", "OCT", "TD", "IR", "SFP", "SFDP", "OVC"],
    "ESDS": ["AGE", "CR", "OVC"],
    "SA": ["AGE", "CR", "IR", "OC"],
    "CBank": ["AGE", "CAP"],
    "BBank": ["AGE", "IR", "CV", "SG"],
}

COMPONENT_LABEL = {
    "AGE": "Age", "FURAN": "Furanic Level / DP", "DGAL": "DGA Gas Levels",
    "DGAT": "DGA Trend", "TAND": "Winding Tan δ", "DRA": "Moisture in Paper (DIRANA)",
    "SFRAPBC": "SFRA Phase-Based Comparison", "SFRATBC": "SFRA Time-Based Comparison",
    "TR": "Turns Ratio", "LR": "Leakage Reactance", "WR": "Winding Resistance",
    "EC": "Exciting Current", "IR": "Insulation Resistance", "BDVO1": "Oil BDV - Main Tank",
    "MIO1": "Moisture in Oil - Main Tank", "AIO": "Acidity in Oil",
    "IFTO": "Interfacial Tension", "PDL": "Partial Discharge Level",
    "BDVO2": "Oil BDV - OLTC", "MIO2": "Moisture in Oil - OLTC",
    "OLTC": "Dynamic OLTC Scan", "RC": "Ratio / Contact Check",
    "OVC": "Overall Visual Condition", "NOO": "Number of Operations",
    "CR": "Contact Resistance", "OCT": "Operating / Closing Time",
    "TD": "Timing & Travel", "SFP": "SF6 Pressure", "SFDP": "SF6 Dew Point",
    "OC": "Operation Counter", "CAP": "Capacitance", "CV": "Cell Voltage",
    "SG": "Specific Gravity",
}

COMPONENT_UNIT = {
    "AGE": "years", "FURAN": "ppb", "TAND": "%", "DRA": "%", "TR": "%", "LR": "%",
    "WR": "%", "EC": "%", "IR": "GΩ", "BDVO1": "kV", "BDVO2": "kV",
    "MIO1": "ppm", "MIO2": "ppm", "AIO": "mg KOH/g", "IFTO": "mN/m", "PDL": "pC",
    "NOO": "ops", "CR": "μΩ", "SFDP": "°C", "OC": "ops",
}


@dataclass(frozen=True)
class Band:
    """One row of a range table, normalised to [low, high)."""
    low: float
    high: float
    score: float
    sequence: int
    descending: bool

    def contains(self, value: float) -> bool:
        return self.low <= value < self.high


def _normalise(range_from: float, range_to: float) -> tuple[float, float, bool]:
    if range_from <= range_to:
        return range_from, range_to, False
    return range_to, range_from, True


def _load_score_sets() -> dict[str, dict[str, list[Band]]]:
    """Newest score set per asset type -> {bandName: [Band, ...]}."""
    latest = db.query(
        "SELECT UpdatedBy AS t, MAX(ID) AS pid FROM SCORE_MAIN "
        "WHERE UpdatedBy IS NOT NULL GROUP BY UpdatedBy"
    )
    out: dict[str, dict[str, list[Band]]] = {}
    for row in latest:
        asset_type, pid = row["t"], row["pid"]
        rows = db.query(
            "SELECT Type, Sequence, RangeFrom, RangeTo, Value FROM SCORE_VALUE "
            "WHERE Parent = ? ORDER BY Type, Sequence",
            (pid,),
        )
        bands: dict[str, list[Band]] = {}
        for r in rows:
            rf = float(r["RangeFrom"] or 0.0)
            rt = float(r["RangeTo"] or 0.0)
            if rf == rt:
                # An unconfigured slot; carries no information.
                continue
            low, high, desc = _normalise(rf, rt)
            bands.setdefault(r["Type"], []).append(
                Band(low=low, high=high, score=float(r["Value"] or 0.0),
                     sequence=int(r["Sequence"] or 0), descending=desc)
            )
        for name in bands:
            bands[name].sort(key=lambda b: b.low)
        out[asset_type] = bands
    return out


def _load_weight_sets() -> dict[str, dict[str, float]]:
    """Newest weight set per type (asset types plus the 'DGA' per-gas set)."""
    latest = db.query(
        "SELECT Type AS t, MAX(ID) AS pid FROM WEIGHT_MAIN WHERE Type IS NOT NULL GROUP BY Type"
    )
    out: dict[str, dict[str, float]] = {}
    for row in latest:
        rows = db.query(
            "SELECT Type, Value FROM WEIGHT_VALUE WHERE Parent = ? ORDER BY ID",
            (row["pid"],),
        )
        out[row["t"]] = {r["Type"]: float(r["Value"] or 0.0) for r in rows}
    return out


def _bands_from_rows(rows: list[dict[str, Any]]) -> list[Band]:
    """Build a band list from override rows (rangeFrom/rangeTo/score/sequence)."""
    bands: list[Band] = []
    for i, r in enumerate(rows, start=1):
        rf = float(r.get("rangeFrom") or 0.0)
        rt = float(r.get("rangeTo") or 0.0)
        if rf == rt:
            continue
        low, high, desc = _normalise(rf, rt)
        bands.append(Band(low=low, high=high, score=float(r.get("score") or 0.0),
                          sequence=int(r.get("sequence") or i), descending=desc))
    bands.sort(key=lambda b: b.low)
    return bands


def score_sets() -> dict[str, dict[str, list[Band]]]:
    """Source bands with any engineer-saved overrides layered on top.

    An override replaces a band table wholesale rather than patching rows, so a
    saved table is exactly what the engineer reviewed - no silent blending of
    old and new thresholds.
    """
    base = db.cached("cfg:scores", _load_score_sets)
    stored = overrides.snapshot()["bands"]
    if not stored:
        return base

    merged = {t: dict(tables) for t, tables in base.items()}
    for key, entry in stored.items():
        asset_type, _, band_name = key.partition("/")
        if not asset_type or not band_name:
            continue
        bands = _bands_from_rows(entry.get("bands") or [])
        if bands:
            merged.setdefault(asset_type, {})[band_name] = bands
    return merged


def weight_sets() -> dict[str, dict[str, float]]:
    base = db.cached("cfg:weights", _load_weight_sets)
    stored = overrides.snapshot()["weights"]
    if not stored:
        return base
    merged = {t: dict(w) for t, w in base.items()}
    for asset_type, entry in stored.items():
        components = entry.get("components") or {}
        if components:
            merged[asset_type] = {k: float(v) for k, v in components.items()}
    return merged


def bands_for(asset_type: str, band_name: str) -> list[Band]:
    return score_sets().get(asset_type, {}).get(band_name, [])


def lookup(value: float | None, bands: list[Band]) -> float | None:
    """Map a measured value to its band score.

    Values outside every band are clamped to the nearest end rather than being
    dropped - a breakdown voltage of 90 kV is better than the best band, not
    unscorable. Returns None only when there is no band table at all.
    """
    if value is None or not bands:
        return None
    for band in bands:
        if band.contains(value):
            return band.score
    lowest, highest = bands[0], bands[-1]
    if value < lowest.low:
        return lowest.score
    return highest.score


def score_component(asset_type: str, component: str, value: float | None) -> float | None:
    """Look a component's raw value up in its configured band table."""
    band_name = BAND_FOR_COMPONENT.get(asset_type, {}).get(component)
    if not band_name:
        return None
    return lookup(value, bands_for(asset_type, band_name))


def weights_for(asset_type: str) -> dict[str, float]:
    return weight_sets().get(asset_type, {})


def normalise_weights(asset_type: str, available: list[str]) -> dict[str, float]:
    """Re-spread the configured weights across the components actually present.

    `weight[c] = w[c] / sum(w over available) * sum(w over all)`

    Verified against `HEALTH_INDEX.LastScores`, which stores exactly these
    normalised percentages alongside the scores that produced a stored Result.
    """
    configured = weights_for(asset_type)
    if not configured:
        return {}
    total = sum(configured.values())
    considered = sum(configured.get(c, 0.0) for c in available)
    if considered <= 0:
        return {c: 0.0 for c in available}
    return {c: configured.get(c, 0.0) / considered * total for c in available}


# --------------------------------------------------------------------------
# Health-index banding for the UI colour codes.
# --------------------------------------------------------------------------
HI_BANDS = [
    {"key": "very-good", "label": "Very Good", "min": 85.0, "max": 100.01,
     "color": "#0E9F6E", "bg": "#E6F6F0"},
    {"key": "good", "label": "Good", "min": 70.0, "max": 85.0,
     "color": "#2E7DD1", "bg": "#E8F1FC"},
    {"key": "fair", "label": "Fair", "min": 55.0, "max": 70.0,
     "color": "#B7791F", "bg": "#FDF6E3"},
    {"key": "poor", "label": "Poor", "min": 40.0, "max": 55.0,
     "color": "#DD6B20", "bg": "#FDEDE3"},
    {"key": "very-poor", "label": "Very Poor", "min": -0.01, "max": 40.0,
     "color": "#D64545", "bg": "#FCEAEA"},
]


def hi_band(value: float | None) -> dict[str, Any] | None:
    if value is None:
        return None
    for band in HI_BANDS:
        if band["min"] <= value < band["max"]:
            return band
    return HI_BANDS[0] if value >= 100 else HI_BANDS[-1]


# --------------------------------------------------------------------------
# Configuration audit
#
# The live range tables are only fully populated for TR and CB. CTVT's bands
# carry scores of 0.01-0.05 where the convention is 0..1, and SA's are all
# zero, which drives those asset types to a near-zero index that looks like a
# condition verdict but is really an unconfigured band table. Every consumer
# gets this audit so the UI can say so plainly.
# --------------------------------------------------------------------------
def audit_band_table(bands: list[Band]) -> dict[str, Any]:
    scores = [b.score for b in bands]
    if not scores:
        return {"status": "missing", "reason": "No bands configured."}
    top = max(scores)
    if top == 0:
        return {"status": "unusable",
                "reason": "Every band scores 0, so this component can only ever "
                          "contribute nothing."}
    if top < 0.5:
        return {"status": "suspect",
                "reason": f"Highest band scores {top:g}, but the convention is 0..1 "
                          "with 1 healthy. The table looks mis-scaled."}
    return {"status": "ok", "reason": ""}


def audit_asset_type(asset_type: str) -> dict[str, Any]:
    """Whether an asset type's scoring configuration can be trusted."""
    tables = score_sets().get(asset_type, {})
    expected = set(BAND_FOR_COMPONENT.get(asset_type, {}).values())
    if asset_type == "TR":
        expected |= set(DGA_GAS_BANDS.values())

    issues: list[dict[str, Any]] = []
    for name in sorted(expected):
        bands = tables.get(name, [])
        verdict = audit_band_table(bands)
        if verdict["status"] != "ok":
            issues.append({"band": name, **verdict})

    if not expected:
        status = "manual-only"
    elif not issues:
        status = "ok"
    elif len(issues) >= len(expected):
        status = "unconfigured"
    else:
        status = "partial"

    messages = {
        "ok": "",
        "manual-only": "This asset type is scored entirely from manual entry.",
        "partial": ("Some score bands for this asset type are missing or mis-scaled, "
                    "so its health index understates true condition."),
        "unconfigured": ("The score bands for this asset type are not usable, so its "
                         "health index is not a valid condition assessment."),
    }
    return {
        "assetType": asset_type,
        "status": status,
        "trustworthy": status in {"ok", "manual-only"},
        "message": messages[status],
        "issues": issues,
        "bandsExpected": len(expected),
        "bandsWithIssues": len(issues),
    }


def config_audit() -> dict[str, dict[str, Any]]:
    return {t: audit_asset_type(t) for t in COMPONENT_ORDER}


def config_snapshot() -> dict[str, Any]:
    """Everything the Configuration screen needs, in one payload."""
    scores = score_sets()
    weights = weight_sets()
    meta = overrides.metadata()
    overridden_weights = set(overrides.snapshot()["weights"])
    return {
        "hiBands": HI_BANDS,
        "audit": config_audit(),
        "overrides": meta,
        "weights": {
            t: {
                "components": w,
                "total": round(sum(w.values()), 4),
                "overridden": t in overridden_weights,
            }
            for t, w in sorted(weights.items())
        },
        "scoreBands": {
            t: {
                name: {
                    "overridden": f"{t}/{name}" in meta["bands"],
                    "updatedAt": meta["bands"].get(f"{t}/{name}", {}).get("updatedAt"),
                    "updatedBy": meta["bands"].get(f"{t}/{name}", {}).get("updatedBy"),
                    "note": meta["bands"].get(f"{t}/{name}", {}).get("note", ""),
                    "bands": [
                        {
                            "sequence": b.sequence,
                            # Presented the way it is stored: a descending table
                            # keeps its high edge first so the engineer edits what
                            # they see in the source system.
                            "rangeFrom": b.high if b.descending else b.low,
                            "rangeTo": b.low if b.descending else b.high,
                            "low": b.low,
                            "high": b.high,
                            "score": b.score,
                            "descending": b.descending,
                        }
                        for b in bands
                    ],
                }
                for name, bands in sorted(tables.items())
            }
            for t, tables in sorted(scores.items())
        },
        "bandsForComponent": BAND_FOR_COMPONENT,
        "dgaGasBands": DGA_GAS_BANDS,
        "componentOrder": COMPONENT_ORDER,
        "componentLabels": COMPONENT_LABEL,
        "componentUnits": COMPONENT_UNIT,
        "manualComponents": {k: sorted(v) for k, v in MANUAL_COMPONENTS.items()},
    }
