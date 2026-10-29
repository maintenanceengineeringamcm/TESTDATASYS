"""Health Index computation.

For one asset the index is a weighted average of component scores:

    HI = sum( normalisedWeight[c] * score[c] )   over the asset type's components

Each component goes through three steps - read a value, band it into a score,
weight the score. Components with no qualifying record are marked *unavailable*
and dropped from weight normalisation entirely, rather than scored zero, so a
missing test never pretends to be a bad result.

Scores run 0..1 with 1 healthy and weights sum to 100, so the index lands on
0..100 where **higher is better**. That polarity is confirmed by the stored
`HEALTH_INDEX.LastScores` audit strings, which reproduce their own `Result`.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import db
from config import Config
from core import assets as assets_mod
from core import dga_filter, dga_status, dga_trend, readers, scoring

log = logging.getLogger(__name__)

OPEN_FROM = readers.OPEN_FROM
OPEN_TO = readers.OPEN_TO

# component -> reader function, per asset type. Absent entries are manual-entry.
READERS: dict[str, dict[str, Callable[..., readers.Reading | None]]] = {
    "TR": {
        "AGE": readers.read_age,
        "FURAN": readers.read_furan,
        "TAND": readers.read_tand,
        "DRA": readers.read_dirana,
        "TR": readers.read_turns_ratio,
        "LR": readers.read_leakage_reactance,
        "WR": readers.read_winding_resistance,
        "EC": readers.read_exciting_current,
        "IR": readers.read_tr_insulation_resistance,
        "BDVO1": readers.read_bdv_main,
        "MIO1": readers.read_moisture_main,
        "AIO": readers.read_acidity,
        "IFTO": readers.read_ift,
        "BDVO2": readers.read_bdv_oltc,
        "MIO2": readers.read_moisture_oltc,
    },
    "CTVT": {
        "AGE": readers.read_age,
        "TAND": readers.read_ctvt_tand,
        "IR": readers.read_ctvt_ir,
    },
    "CB": {
        "AGE": readers.read_age,
        "NOO": readers.read_cb_operations,
        "CR": readers.read_cb_contact_resistance,
        "IR": readers.read_cb_ir,
        "SFDP": readers.read_cb_sf6_dewpoint,
    },
    "ESDS": {"AGE": readers.read_age, "CR": readers.read_esds_contact_resistance},
    "SA": {"AGE": readers.read_age, "CR": readers.read_sa_counter,
           "IR": readers.read_sa_ir},
    "CBank": {"AGE": readers.read_age},
    "BBank": {"AGE": readers.read_age},
}


def _candidates(reading: readers.Reading | None) -> list[dict[str, Any]]:
    return [c.as_dict() for c in reading.candidates] if reading else []


def _window_note(window: dict[str, Any] | None) -> dict[str, Any] | None:
    """The filter-window facts shown with a DGA criterion, or None for full history."""
    if not window or (window["fromDate"] is None and not window["skippedPoints"]):
        return None
    return {k: window[k] for k in ("fromDate", "beforeDate", "samplesUsed",
                                   "skippedPoints", "minSamplesAfter", "reason")}


def _dga_window(asset: str) -> dict[str, Any] | None:
    """Samples DGA level and trend are scored on, given any oil filtration points."""
    if not Config.DGA_FILTER_WINDOW:
        return None
    try:
        return dga_filter.analysis_window(asset)
    except Exception as exc:                          # the window must not cost the HI
        log.warning("DGA filter window failed for %s: %s", asset, exc)
        return None


def _dga_level(asset: str, date_from: str, date_to: str,
               window: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """DGA gas-level component - the source logic (GetDGALevScore), with each
    gas banded on its own value:

    1. Newest CEB_DGA_DATA record (by DateTested) for the asset within the
       date range, used as it is even when gases are blank.
    2. Each gas: its own ppm value against its own band table, score = band
       Value where RangeFrom < x < RangeTo (both ends exclusive); 0 when no
       band matches or the value is blank. (The source text used H2ppm for
       every gas; HI_DGA_PER_GAS_OWN_FIELD=false restores that.)
    3. Latest DGA weight set; every gas's weight counts, scored or not.
    4. dgai = sum(score x weight) / sum(weight).
    5. Final score = DGA band Value where RangeFrom <= dgai < RangeTo; 0 if none.

    With an oil filtration in the history, step 1 only looks at the side of the
    filter point that `window` selects (see dga_filter.choose_window).
    """
    note = _window_note(window)
    sample = readers.read_dga_level_sample(
        asset, date_from, date_to,
        sampled_from=note["fromDate"] if note else None,
        sampled_before=note["beforeDate"] if note else None)
    if not sample:
        return None
    gases = sample["gases"]
    gas_weights = scoring.weight_sets().get("DGA", {})

    # Conditions are taken on the table as stored: RangeFrom < x < RangeTo can
    # never hold for a row stored highest-first, so such a row never matches.
    def strict_band(x: float | None, band_name: str) -> float:
        if x is None:
            return 0.0
        score = 0.0
        for b in scoring.bands_for("TR", band_name):
            if not b.descending and b.low < x < b.high:
                score = b.score
        return score

    per_gas = []
    score_sum = 0.0
    weight_sum = 0.0
    for gas, band_name in scoring.DGA_GAS_BANDS.items():
        raw = gases.get(gas)
        compare_value = raw if Config.DGA_PER_GAS_OWN_FIELD else gases.get("H2")
        gas_score = strict_band(compare_value, band_name)
        w = gas_weights.get(gas, 0.0)
        per_gas.append({"gas": gas, "value": raw, "comparedValue": compare_value,
                        "score": gas_score, "weight": w})
        score_sum += gas_score * w
        weight_sum += w

    if weight_sum <= 0:
        return None
    dgai = score_sum / weight_sum
    final = 0.0
    for b in scoring.bands_for("TR", "DGA"):
        if not b.descending and b.low <= dgai < b.high:
            final = b.score
    # Every gas that fed the index is a candidate, so the workbench can show the
    # full gas set behind the single number.
    candidates = [
        {"label": g["gas"], "value": g["value"], "date": sample["date"],
         "source": "CEB_DGA_DATA", "used": False,
         "reason": (f"score {g['score']:g} x weight {g['weight']:g}"
                   + (" (blank - scored 0)" if g["comparedValue"] is None else "")
                   + ("" if g["comparedValue"] is None or g["gas"] == "H2"
                      or Config.DGA_PER_GAS_OWN_FIELD else " (banded on H2ppm)"))}
        for g in per_gas
    ]
    return {
        "value": round(dgai, 4),
        "score": final,
        "date": sample["date"],
        "source": "CEB_DGA_DATA",
        "detail": {"gasIndex": round(dgai, 4), "perGas": per_gas,
                   **({"filterWindow": note} if note else {})},
        "candidates": candidates,
        "mode": "blend",
        "rule": (f"weighted index of {len(per_gas)} gases "
                 f"(sum of score x weight / {weight_sum:g}), then banded"
                 + (f" · {note['reason']}" if note else "")),
    }


def _dga_trend_component(asset: str,
                         window: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """DGA trend component, fed by the IEEE C57.104 trend engine.

    Marked manual in the automation spec, but the trend value is computable and
    the live `LastScores` audit strings show continuous values in this slot
    (0.69, 0.61, 0.44...) rather than the discrete band scores, which is exactly
    what the trend engine produces. Scored on full sample history, since
    clipping the range changes which samples form the last-three window.

    An oil filtration splits that history: `window` holds the samples on the
    side of the filter point being scored (see dga_filter.choose_window).
    """
    note = _window_note(window)
    result = (dga_trend.compute_asset_trend(asset.strip(), window["samples"]) if note
              else dga_trend.asset_trend(asset))
    if result.get("trend") is None:
        return None
    candidates = [
        {"label": g["gas"], "value": g["subScore"], "date": result.get("latestSample"),
         "source": "IEEE C57.104 trend", "used": False,
         "reason": f"sub score x weight {g['weight']}"}
        for g in result["gases"] if g["subScore"] is not None
    ]
    return {
        "value": round(result["trend"], 4),
        "score": round(result["trend"], 4),
        "date": result.get("latestSample"),
        "source": "CEB_DGA_DATA (IEEE C57.104 trend)",
        "detail": {
            "condition": result["condition"],
            "samples": result["samples"],
            "excludedGases": result["excludedGases"],
            **({"filterWindow": note} if note else {}),
        },
        "candidates": candidates,
        "mode": "blend",
        "rule": (f"weighted mean of {len(candidates)} gas sub scores "
                 f"(denominator {result['denominator']})"
                 + (f" · {note['reason']}" if note else "")),
    }


# DGA correction factor - the share of the final index taken away for each
# IEEE C57.104-2019 status. Status 3 at 0.3 means the index drops by 30%.
DGA_CORRECTION_DEFAULTS: dict[int, float] = {1: 0.0, 2: 0.1, 3: 0.3}


def parse_correction_factors(raw: dict[Any, Any] | None) -> dict[int, float]:
    """Status -> factor, defaults filled in for any status not supplied.

    Raises ValueError for a status other than 1/2/3 or a factor outside 0..1.
    """
    factors = dict(DGA_CORRECTION_DEFAULTS)
    for key, value in (raw or {}).items():
        try:
            status = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"unknown DGA status '{key}'") from None
        if status not in factors:
            raise ValueError(f"unknown DGA status '{key}'")
        if value in (None, ""):
            continue
        factor = float(value)
        if not 0.0 <= factor <= 1.0:
            raise ValueError(f"factor for status {status} must be between 0 and 1")
        factors[status] = factor
    return factors


def apply_dga_correction(hi: float | None, status: int | None,
                         factors: dict[int, float]) -> tuple[float | None, float]:
    """(corrected HI, factor applied). No status or no index means no change."""
    if hi is None or status not in factors:
        return hi, 0.0
    factor = factors[status]
    return round(hi * (1.0 - factor), 2), factor


def _dga_correction(asset: str, a_type: str, hi: float | None, date_from: str,
                    date_to: str, factors: dict[int, float],
                    window: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify the asset's DGA and scale the final index by its status factor.

    Transformers only - the IEEE status is defined for transformer oil. An asset
    with no classifiable DGA keeps its index unchanged and says why. With an oil
    filtration in the history, the status is classified on the same side of the
    filter point as DGA level and trend (`window`), so a post-filtration dip
    cannot hide a Status 3.
    """
    out: dict[str, Any] = {
        "enabled": True, "applied": False, "factors": {str(k): v for k, v in factors.items()},
        "status": None, "statusLabel": None, "verdict": None, "color": None, "bg": None,
        "latestSample": None, "reason": None, "factor": 0.0, "hiBefore": hi, "hiAfter": hi,
        "message": "",
    }
    if a_type != "TR":
        out["message"] = "DGA correction applies to transformers only."
        return out
    note = _window_note(window)
    try:
        if note:
            age, _ = dga_status._age_for(asset.strip())
            st = dga_status.classify(window["samples"], age, asset.strip())
        else:
            st = dga_status.asset_status(asset, date_from, date_to)
    except Exception as exc:                          # status must not kill the HI
        log.warning("DGA status failed for %s: %s", asset, exc)
        out["message"] = "DGA status could not be determined."
        return out
    out.update(status=st.get("status"), statusLabel=st.get("statusLabel"),
               verdict=st.get("verdict"), color=st.get("color"), bg=st.get("bg"),
               latestSample=st.get("latestSample"), reason=st.get("reason"))
    if st.get("status") is None:
        out["message"] = st.get("reason") or "No DGA sample to classify - index unchanged."
        return out
    if hi is None:
        out["message"] = "No health index to correct."
        return out
    corrected, factor = apply_dga_correction(hi, st["status"], factors)
    out.update(applied=True, factor=factor, hiAfter=corrected,
               message=(f"{st['statusLabel']}: index reduced by {factor * 100:g}%"
                        if factor else f"{st['statusLabel']}: no correction")
               + (f" (status on {note['reason']})" if note else ""),
               filterWindow=note)
    return out


def compute(asset_number: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO,
            manual: dict[str, float] | None = None,
            asset_type: str | None = None,
            selected: list[str] | None = None,
            manual_age: float | None = None,
            dga_correction: dict[int, float] | None = None) -> dict[str, Any]:
    """Compute the health index for one asset.

    `selected` restricts the calculation to a chosen set of criteria - the
    manual workbench uses it so an engineer can score on, say, DGA and BDV
    alone. Weights re-normalise over whatever survives, so the index always
    lands on 0..100. `None` means every criterion with data, which is the
    automatic behaviour.

    `dga_correction` (status -> factor) turns on the DGA correction: the final
    index is multiplied by (1 - factor) for the transformer's IEEE C57.104
    status. `None` leaves the index uncorrected, as the automatic sweep does.
    """
    asset_number = (asset_number or "").strip()
    manual = manual or {}
    record = assets_mod.get(asset_number)
    a_type = asset_type or (record.assetType if record else
                            assets_mod.classify(asset_number)[0])
    chosen = set(selected) if selected is not None else None

    order = scoring.COMPONENT_ORDER.get(a_type, [])
    if not order:
        return {
            "asset": asset_number, "assetType": a_type, "healthIndex": None,
            "band": None, "components": [],
            "message": f"No health-index definition for asset type '{a_type}'.",
        }

    readers_for_type = READERS.get(a_type, {})
    manual_set = scoring.MANUAL_COMPONENTS.get(a_type, set())
    # Which side of an oil filtration DGA level and trend are scored on - worked
    # out once, and only for a transformer that needs one of them.
    dga_window: dict[str, Any] | None = None
    if a_type == "TR" and not {"DGAL", "DGAT"} <= set(manual):
        dga_window = _dga_window(asset_number)
    components: list[dict[str, Any]] = []

    for code in order:
        band_name = scoring.BAND_FOR_COMPONENT.get(a_type, {}).get(code)
        entry: dict[str, Any] = {
            "code": code,
            "label": scoring.COMPONENT_LABEL.get(code, code),
            "unit": scoring.COMPONENT_UNIT.get(code),
            "manual": code in manual_set,
            "bandName": band_name,
            "value": None, "score": None, "date": None, "source": None,
            "available": False, "detail": {}, "candidates": [], "rule": "",
            "mode": "single",
            # A criterion is "selected" when the caller asked for it, or when no
            # explicit selection was made at all.
            "selected": chosen is None or code in chosen,
        }

        # A manual override always wins - it is how an engineer supplies the
        # components that have no test table at all.
        if code in manual and manual[code] is not None:
            entry.update(value=float(manual[code]), score=float(manual[code]),
                         source="manual entry", available=True,
                         rule="score entered by an engineer",
                         candidates=[{"label": "entered manually",
                                      "value": float(manual[code]), "date": None,
                                      "source": "manual entry", "used": True,
                                      "reason": ""}])
            components.append(entry)
            continue

        if a_type == "TR" and code == "DGAL":
            got = _dga_level(asset_number, date_from, date_to, dga_window)
            if got:
                entry.update(value=got["value"], score=got["score"], date=got["date"],
                             source=got["source"], detail=got["detail"],
                             candidates=got["candidates"], rule=got["rule"],
                             mode=got.get("mode", "blend"), available=True)
            components.append(entry)
            continue

        if a_type == "TR" and code == "DGAT":
            got = _dga_trend_component(asset_number, dga_window)
            if got:
                entry.update(value=got["value"], score=got["score"], date=got["date"],
                             source=got["source"], detail=got["detail"],
                             candidates=got["candidates"], rule=got["rule"],
                             mode=got.get("mode", "blend"), available=True)
            components.append(entry)
            continue

        reader = readers_for_type.get(code)
        if reader is None:
            components.append(entry)     # manual, not supplied
            continue

        try:
            kwargs: dict[str, Any] = {"date_from": date_from, "date_to": date_to}
            if code == "AGE":
                kwargs["manual_age"] = manual_age
            reading = reader(asset_number, **kwargs)
        except Exception as exc:                      # one bad table must not
            log.warning("reader %s/%s failed: %s", a_type, code, exc)  # kill the sweep
            reading = None

        if reading is not None and reading.value is not None:
            # A reader that scored itself (exciting current's two-limit table)
            # wins; everything else is one value banded against its range table.
            score = reading.score if reading.score is not None else \
                scoring.score_component(a_type, code, reading.value)
            entry.update(value=reading.value, score=score, date=reading.date,
                         source=reading.source, detail=reading.detail,
                         candidates=_candidates(reading), rule=reading.rule,
                         mode=reading.mode, available=score is not None)
        components.append(entry)

    available = [c["code"] for c in components
                 if c["available"] and c["score"] is not None and c["selected"]]
    weights = scoring.normalise_weights(a_type, available)

    total = 0.0
    for c in components:
        w = weights.get(c["code"], 0.0) if c["code"] in available else 0.0
        c["weight"] = round(w, 4)
        c["configuredWeight"] = round(scoring.weights_for(a_type).get(c["code"], 0.0), 4)
        c["contribution"] = round(w * c["score"], 4) if c["code"] in available else None
        if c["code"] in available:
            total += w * c["score"]

    hi = round(total, 2) if available else None
    uncorrected = hi
    correction = None
    if dga_correction is not None:
        if a_type == "TR" and dga_window is None and "DGAL" in manual and "DGAT" in manual:
            dga_window = _dga_window(asset_number)
        correction = _dga_correction(asset_number, a_type, hi, date_from, date_to,
                                     dga_correction, dga_window)
        hi = correction["hiAfter"]
    band = scoring.hi_band(hi)
    missing = [c["code"] for c in components if not c["available"]]
    deselected = [c["code"] for c in components
                  if c["available"] and not c["selected"]]

    # An asset type whose bands are unusable produces a number that looks like a
    # verdict but is not one. Ship the audit with every result so the UI can say so.
    audit = scoring.audit_asset_type(a_type)

    return {
        "asset": asset_number,
        "assetType": a_type,
        "category": record.category if record else
        assets_mod.categorise(a_type, assets_mod.classify(asset_number)[1],
                              "/OLTC" in asset_number.upper()),
        "assetTypeLabel": record.label if record else
        assets_mod.ASSET_TYPE_LABEL.get(a_type, a_type),
        "site": record.site if record else "",
        "healthIndex": hi,
        "band": band,
        "configAudit": audit,
        "components": components,
        "componentsUsed": len(available),
        "componentsTotal": len(order),
        "missingComponents": missing,
        "deselectedComponents": deselected,
        "manualAge": manual_age,
        "healthIndexUncorrected": uncorrected,
        "dgaCorrection": correction,
        "coverage": round(len(available) / len(order) * 100, 1) if order else 0.0,
        "dateFrom": date_from,
        "dateTo": date_to,
        "message": (
            "No component had a qualifying measurement in the selected window."
            if not available else ""
        ),
    }


def compute_many(asset_numbers: list[str], date_from: str = OPEN_FROM,
                 date_to: str = OPEN_TO) -> list[dict[str, Any]]:
    out = []
    for number in asset_numbers:
        try:
            out.append(compute(number, date_from, date_to))
        except Exception as exc:
            log.warning("HI failed for %s: %s", number, exc)
            out.append({"asset": number, "healthIndex": None, "band": None,
                        "components": [], "message": f"Computation failed: {exc}"})
    return out


def summary_row(result: dict[str, Any]) -> dict[str, Any]:
    """Compact row for the fleet table - drops the per-component detail."""
    band = result.get("band") or {}
    audit = result.get("configAudit") or {}
    return {
        "asset": result.get("asset"),
        "assetType": result.get("assetType"),
        "category": result.get("category"),
        "assetTypeLabel": result.get("assetTypeLabel"),
        "site": result.get("site"),
        "healthIndex": result.get("healthIndex"),
        "bandKey": band.get("key"),
        "bandLabel": band.get("label"),
        "bandColor": band.get("color"),
        "bandBg": band.get("bg"),
        "componentsUsed": result.get("componentsUsed"),
        "componentsTotal": result.get("componentsTotal"),
        "coverage": result.get("coverage"),
        "configTrusted": audit.get("trustworthy", True),
        "configStatus": audit.get("status"),
    }


# --------------------------------------------------------------------------
# Stored results
# --------------------------------------------------------------------------
def stored_history(asset: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    """Previously persisted health indices from the HEALTH_INDEX table."""
    if asset:
        rows = db.query(
            "SELECT TOP (?) ID, AssetNumber, TestDate, Result, AssetDescription, LastScores "
            "FROM HEALTH_INDEX WHERE LTRIM(RTRIM(AssetNumber)) = ? ORDER BY TestDate DESC",
            (limit, asset.strip()),
        )
    else:
        rows = db.query(
            "SELECT TOP (?) ID, AssetNumber, TestDate, Result, AssetDescription, LastScores "
            "FROM HEALTH_INDEX ORDER BY TestDate DESC",
            (limit,),
        )
    out = []
    for r in rows:
        value = float(r["Result"]) if r.get("Result") is not None else None
        band = scoring.hi_band(value)
        out.append({
            "id": r["ID"], "asset": r["AssetNumber"], "testDate": r["TestDate"],
            "healthIndex": value, "description": r.get("AssetDescription"),
            "bandKey": (band or {}).get("key"), "bandLabel": (band or {}).get("label"),
            "bandColor": (band or {}).get("color"), "bandBg": (band or {}).get("bg"),
            "breakdown": parse_last_scores(r.get("LastScores"), r["AssetNumber"]),
        })
    return out


def parse_last_scores(raw: str | None, asset: str = "") -> list[dict[str, Any]] | None:
    """Decode a `LastScores` audit string.

    Format is `s1#s2#...#sN $w1#w2#...#wN`, blank meaning the component was not
    used, with slot order matching the asset type's component order.
    """
    if not raw or "$" not in raw:
        return None
    scores_part, _, weights_part = raw.partition("$")
    raw_scores = scores_part.split("#")
    raw_weights = weights_part.split("#")

    a_type = assets_mod.classify(asset)[0] if asset else "TR"
    order = scoring.COMPONENT_ORDER.get(a_type) or scoring.COMPONENT_ORDER["TR"]

    out = []
    for i, code in enumerate(order):
        s = raw_scores[i].strip() if i < len(raw_scores) else ""
        w = raw_weights[i].strip() if i < len(raw_weights) else ""
        if not s and not w:
            continue
        try:
            score = float(s) if s else None
            weight = float(w) if w else None
        except ValueError:
            continue
        if score is None and weight is None:
            continue
        out.append({
            "code": code,
            "label": scoring.COMPONENT_LABEL.get(code, code),
            "score": score,
            "weight": weight,
            "contribution": round(score * weight, 3)
            if (score is not None and weight is not None) else None,
        })
    return out or None


def distribution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count assets per health-index band, for the dashboard chart.

    Assets whose asset type has unusable score bands are counted in their own
    bucket rather than against a condition band. Folding them in would put
    thousands of surge arresters in "Very Poor" and read as a fleet emergency,
    when the real cause is an empty configuration table.
    """
    buckets = {b["key"]: 0 for b in scoring.HI_BANDS}
    unscored = 0
    unconfigured = 0
    for r in rows:
        if not r.get("configTrusted", True):
            unconfigured += 1
            continue
        key = r.get("bandKey")
        if key in buckets:
            buckets[key] += 1
        else:
            unscored += 1
    out = [
        {"key": b["key"], "label": b["label"], "color": b["color"], "bg": b["bg"],
         "min": b["min"] if b["min"] >= 0 else 0, "max": min(b["max"], 100),
         "count": buckets[b["key"]]}
        for b in scoring.HI_BANDS
    ]
    out.append({"key": "unscored", "label": "No Data", "color": "#94A3B8",
                "bg": "#F1F5F9", "min": None, "max": None, "count": unscored})
    out.append({"key": "unconfigured", "label": "Not Configured", "color": "#C2946A",
                "bg": "#F6EFE7", "min": None, "max": None, "count": unconfigured})
    return out
