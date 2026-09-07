"""IEEE C57.104-2019 DGA status classification (Figure 2).

This is the *status* classifier from the 2019 revision of the guide: it puts a
transformer in Status 1 / 2 / 3 from its dissolved-gas levels, the change since
the previous sample and - where enough history exists - a multi-point rate of
change. It is a separate question from the trend *score* in
:mod:`core.dga_trend`, which produces a 0-1 number for the health index. Both
read the same samples; neither feeds the other.

The port follows `DGA_Status_Logic_C57104-2019.md` section by section:

* section 2 - column selection (O2/N2 band, age band, Table 4 period band)
* section 3 - deltas and the 3-6 point regression rate
* section 4 - the four reference tables
* section 5 - the Figure 2 decision, implemented literally
* section 6 - the confirmation-sampling and extreme-value refinements, layered
  on top as *flags*, so the classifier itself stays exactly Figure 2
* section 7 - the output shape, including the `triggered_by` audit trail

.. warning::
   The numeric tables were reconstructed from a scanned copy of the standard.
   Cells the source flagged as OCR-ambiguous carry ``verify=True`` all the way
   to the UI, and the one cell with no legible value at all (Table 3, C2H4,
   O2/N2 > 0.2) is ``None`` - that comparison is skipped and an assumption is
   recorded rather than guessed at. Confirm every number against an
   authoritative copy of IEEE C57.104-2019 6.1.3 before relying on this in
   anger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core import attributes, dga_trend

# The seven gases the status logic covers, in the standard's own order.
GASES = ["H2", "CH4", "C2H6", "C2H4", "C2H2", "CO", "CO2"]

GAS_COLUMN = dga_trend.GAS_COLUMN

# Sentinel used by C2H2 in Tables 3 and 4: any positive change counts as an
# exceedance, so there is no numeric limit to compare against.
ANY_INCREASE = "ANY_INCREASE"

RATIO_BANDS = ["<=0.2", ">0.2"]
AGE_BANDS = ["Unknown", "1-9", "10-30", ">30"]
PERIOD_BANDS = ["4-9", "10-24"]

# Rate window (section 3). At least three points, spanning no more than two
# years, and - because Table 4 is only quoted for 4-24 month intervals - no
# less than four months.
RATE_MIN_POINTS = 3
RATE_MAX_POINTS = 6
RATE_MAX_SPAN_DAYS = 730
RATE_MIN_SPAN_DAYS = 120
DAYS_PER_YEAR = 365.0


# --------------------------------------------------------------------------
# Section 4 - reference tables
# --------------------------------------------------------------------------
# Every value is uL/L (ppm); Table 4 is ppm/year. `V()` marks a cell the source
# scan rendered ambiguously - the number is carried but flagged for review, and
# the flag travels with the result all the way onto the report.
def V(value: float | None) -> tuple[float | None, bool]:
    """A table cell whose value needs verifying against the printed standard."""
    return (value, True)


def _cell(entry: Any) -> tuple[Any, bool]:
    """Normalise a table entry to (value, needs_verification)."""
    if isinstance(entry, tuple):
        return entry
    return (entry, False)


# Table 1 - 90th percentile levels, by O2/N2 band then age band.
TABLE1: dict[str, dict[str, dict[str, Any]]] = {
    "<=0.2": {
        "Unknown": {"H2": 80, "CH4": 90, "C2H6": 90, "C2H4": 50, "C2H2": 1,
                    "CO": 900, "CO2": 9000},
        "1-9":     {"H2": 75, "CH4": 45, "C2H6": 30, "C2H4": 20, "C2H2": 1,
                    "CO": 900, "CO2": 5000},
        "10-30":   {"H2": 100, "CH4": 90, "C2H6": 90, "C2H4": 50, "C2H2": 1,
                    "CO": 900, "CO2": 10000},
        ">30":     {"H2": V(100), "CH4": 110, "C2H6": 150, "C2H4": 90, "C2H2": 1,
                    "CO": 900, "CO2": V(10000)},
    },
    ">0.2": {
        "Unknown": {"H2": 40, "CH4": 20, "C2H6": 15, "C2H4": 50, "C2H2": 2,
                    "CO": 500, "CO2": 5000},
        "1-9":     {"H2": 40, "CH4": 20, "C2H6": 15, "C2H4": 25, "C2H2": 2,
                    "CO": 500, "CO2": 3500},
        "10-30":   {"H2": 40, "CH4": 20, "C2H6": 15, "C2H4": V(60), "C2H2": 2,
                    "CO": 500, "CO2": 5500},
        ">30":     {"H2": 40, "CH4": 20, "C2H6": 15, "C2H4": V(60), "C2H2": 2,
                    "CO": 500, "CO2": V(5500)},
    },
}

# Table 2 - 95th percentile levels, by O2/N2 band then age band.
TABLE2: dict[str, dict[str, dict[str, Any]]] = {
    "<=0.2": {
        "Unknown": {"H2": 200, "CH4": 150, "C2H6": 175, "C2H4": 100, "C2H2": V(2),
                    "CO": 1100, "CO2": 12500},
        "1-9":     {"H2": 200, "CH4": 100, "C2H6": 70, "C2H4": 40, "C2H2": V(2),
                    "CO": 1100, "CO2": 7000},
        "10-30":   {"H2": 200, "CH4": 150, "C2H6": 175, "C2H4": 95, "C2H2": V(4),
                    "CO": 1100, "CO2": 14000},
        ">30":     {"H2": 200, "CH4": 200, "C2H6": 250, "C2H4": 175, "C2H2": V(7),
                    "CO": 1100, "CO2": V(14000)},
    },
    ">0.2": {
        "Unknown": {"H2": 90, "CH4": 50, "C2H6": 40, "C2H4": 100, "C2H2": 7,
                    "CO": 600, "CO2": 7000},
        "1-9":     {"H2": 90, "CH4": V(60), "C2H6": 30, "C2H4": 80, "C2H2": 7,
                    "CO": 600, "CO2": 5000},
        "10-30":   {"H2": 90, "CH4": V(30), "C2H6": V(40), "C2H4": V(125), "C2H2": 7,
                    "CO": 600, "CO2": 8000},
        ">30":     {"H2": 90, "CH4": V(30), "C2H6": V(40), "C2H4": V(125), "C2H2": 7,
                    "CO": 600, "CO2": V(8000)},
    },
}

# Table 3 - 95th percentile of the change between consecutive samples. No time
# normalisation: this is the raw difference in ppm.
TABLE3: dict[str, dict[str, Any]] = {
    "<=0.2": {"H2": 40, "CH4": 30, "C2H6": 25, "C2H4": 20, "C2H2": ANY_INCREASE,
              "CO": 250, "CO2": 2500},
    # C2H4 is the one cell the source scan could not resolve at all. It stays
    # None: the comparison is skipped and the gap is reported, never guessed.
    ">0.2":  {"H2": 25, "CH4": 10, "C2H6": 7, "C2H4": V(None), "C2H2": ANY_INCREASE,
              "CO": 175, "CO2": 1750},
}

# Table 4 - 95th percentile of the 3-6 point regression rate, ppm/year.
TABLE4: dict[str, dict[str, dict[str, Any]]] = {
    "<=0.2": {
        "4-9":   {"H2": 50, "CH4": 15, "C2H6": 15, "C2H4": 10, "C2H2": ANY_INCREASE,
                  "CO": 200, "CO2": 1750},
        "10-24": {"H2": 20, "CH4": 10, "C2H6": 9, "C2H4": 7, "C2H2": ANY_INCREASE,
                  "CO": 100, "CO2": 1000},
    },
    ">0.2": {
        "4-9":   {"H2": 25, "CH4": 4, "C2H6": 3, "C2H4": 7, "C2H2": ANY_INCREASE,
                  "CO": 100, "CO2": 1000},
        "10-24": {"H2": 10, "CH4": 3, "C2H6": 2, "C2H4": 5, "C2H2": ANY_INCREASE,
                  "CO": 80, "CO2": 800},
    },
}

# Section 6, step 8 - values so far past the tables that the computed status
# understates them. The "twice Table 2" rule applies to every gas; these two are
# the standard's own worked examples.
EXTREME_LEVEL_MULTIPLE = 2.0
EXTREME_RULES: list[tuple[str, str, float, str]] = [
    ("C2H4", "delta", 200.0, "ethylene rose by 200 ppm or more between samples"),
    ("C2H6", "level", 1000.0, "ethane is at or above 1000 ppm"),
]

STATUS_META: dict[int, dict[str, str]] = {
    1: {
        "label": "Status 1",
        "verdict": "Probably normal",
        "color": "#0E9F6E",
        "bg": "#E6F6F0",
        "action": "Continue routine DGA sampling at the interval set by policy.",
    },
    2: {
        "label": "Status 2",
        "verdict": "Possibly suspicious",
        "color": "#B7791F",
        "bg": "#FDF6E3",
        "action": ("Increase sampling frequency and investigate the cause. Where no "
                   "multi-point rate exists, take enough samples to establish one."),
    },
    3: {
        "label": "Status 3",
        "verdict": "Probably suspicious",
        "color": "#D64545",
        "bg": "#FCEAEA",
        "action": ("Identify the fault (Duval triangle and pentagon, Rogers ratios), "
                   "place the unit under increased surveillance, add supporting tests "
                   "and consult a transformer specialist."),
    },
}


def reference_tables() -> dict[str, Any]:
    """The four tables in a shape the UI can render, verify flags included."""
    def flat(limits: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for gas, entry in limits.items():
            value, verify = _cell(entry)
            out[gas] = {"limit": value, "verify": verify}
        return out

    return {
        "gases": GASES,
        "ratioBands": RATIO_BANDS,
        "ageBands": AGE_BANDS,
        "periodBands": PERIOD_BANDS,
        "table1": {r: {a: flat(TABLE1[r][a]) for a in AGE_BANDS} for r in RATIO_BANDS},
        "table2": {r: {a: flat(TABLE2[r][a]) for a in AGE_BANDS} for r in RATIO_BANDS},
        "table3": {r: flat(TABLE3[r]) for r in RATIO_BANDS},
        "table4": {r: {p: flat(TABLE4[r][p]) for p in PERIOD_BANDS} for r in RATIO_BANDS},
        "anyIncrease": ANY_INCREASE,
        "source": ("IEEE C57.104-2019 6.1.3, reconstructed from a scanned copy - "
                   "cells marked for verification are flagged"),
    }


# --------------------------------------------------------------------------
# Section 2 - column selection
# --------------------------------------------------------------------------
def ratio_band(o2_n2: float | None, oscillating: bool = False) -> str:
    """Which O2/N2 section of every table applies.

    The guide's own instruction when the ratio is unavailable is to use the
    >0.2 section, which carries the lower - more conservative - limits. The
    same applies when the ratio crosses 0.2 between recent samples, so the
    column does not flip from one sample to the next.
    """
    if o2_n2 is None or oscillating or o2_n2 > 0.2:
        return ">0.2"
    return "<=0.2"


def age_band(age_years: float | None) -> str:
    """Age column for Tables 1 and 2. Tables 3 and 4 have no age dimension."""
    if age_years is None:
        return "Unknown"
    if age_years <= 9:
        return "1-9"
    if age_years <= 30:
        return "10-30"
    return ">30"


def months_between(first: datetime, last: datetime) -> int:
    """Whole calendar months between two dates."""
    months = (last.year - first.year) * 12 + (last.month - first.month)
    if last.day < first.day:
        months -= 1
    return max(0, months)


def period_band(months: int) -> str:
    return "4-9" if months <= 9 else "10-24"


# --------------------------------------------------------------------------
# Section 3 - per-gas measurements
# --------------------------------------------------------------------------
@dataclass
class GasEvidence:
    """Everything the decision knew about one gas, and what it concluded.

    This is the row the report prints: the reading, the limit it was tested
    against, and the verdict - so a reviewer can re-derive the status by hand.
    """
    gas: str
    measured: bool
    latest: float | None = None
    latestDate: str | None = None
    previous: float | None = None
    previousDate: str | None = None
    delta: float | None = None
    rate: float | None = None
    ratePoints: int = 0
    rateSpanDays: int | None = None
    t1: float | None = None
    t1Verify: bool = False
    t2: float | None = None
    t2Verify: bool = False
    t3: Any = None
    t3Verify: bool = False
    t4: Any = None
    t4Verify: bool = False
    exceedsT1: bool = False
    exceedsT2: bool = False
    exceedsT3: bool = False
    exceedsT4: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _points(samples: list[dict[str, Any]], gas: str) -> list[tuple[datetime, float]]:
    """Dated, non-null readings for one gas, oldest first."""
    out: list[tuple[datetime, float]] = []
    col = GAS_COLUMN[gas]
    for s in samples:
        value = s.get(col)
        if value is None:
            continue
        date = dga_trend._parse_date(s.get("DateSampled"))
        if date is None:
            continue
        out.append((date, float(value)))
    out.sort(key=lambda p: p[0])
    return out


def _rate_window(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The samples the multi-point rate is fitted over.

    Section 3: the last 3-6 points, not spanning more than two years. The
    oldest points are dropped first, because a rate is meant to describe what
    the unit is doing now, not what it did three years ago.
    """
    window = samples[-RATE_MAX_POINTS:]
    while len(window) > RATE_MIN_POINTS:
        span = (dga_trend._parse_date(window[-1]["DateSampled"])
                - dga_trend._parse_date(window[0]["DateSampled"])).days
        if span <= RATE_MAX_SPAN_DAYS:
            break
        window = window[1:]
    return window


def _slope_per_year(points: list[tuple[datetime, float]]) -> float | None:
    base = points[0][0]
    xs = [float((d - base).days) for d, _ in points]
    ys = [v for _, v in points]
    slope = dga_trend.least_squares_slope(xs, ys)
    return None if slope is None else slope * DAYS_PER_YEAR


# --------------------------------------------------------------------------
# Section 5 - the Figure 2 decision
# --------------------------------------------------------------------------
def classify(samples: list[dict[str, Any]], age_years: float | None = None,
             asset: str = "") -> dict[str, Any]:
    """Run the Figure 2 classifier over one asset's DGA history.

    `samples` are rows as returned by :func:`core.dga_trend.fetch_samples` -
    `DateSampled` plus the seven gas columns and O2/N2. Order does not matter.
    """
    assumptions: list[str] = []

    usable = [
        s for s in samples
        if dga_trend._parse_date(s.get("DateSampled")) is not None
        and any(s.get(GAS_COLUMN[g]) is not None for g in GASES)
    ]
    usable.sort(key=lambda s: dga_trend._parse_date(s["DateSampled"]))

    if not usable:
        return _no_data(asset, "No DGA sample with a usable date and gas reading.")

    latest_date = dga_trend._parse_date(usable[-1]["DateSampled"])

    # ---- O2/N2 band -------------------------------------------------------
    o2_n2, o2_note, oscillating = _oxygen_nitrogen(usable)
    if o2_note:
        assumptions.append(o2_note)
    r_band = ratio_band(o2_n2, oscillating)

    # ---- age band ---------------------------------------------------------
    a_band = age_band(age_years)
    if age_years is None:
        assumptions.append("Age unknown - the age-independent 'Unknown' column of "
                           "Tables 1 and 2 was used.")

    t1_limits = TABLE1[r_band][a_band]
    t2_limits = TABLE2[r_band][a_band]
    t3_limits = TABLE3[r_band]

    # ---- rate window ------------------------------------------------------
    window = _rate_window(usable)
    window_first = dga_trend._parse_date(window[0]["DateSampled"])
    window_last = dga_trend._parse_date(window[-1]["DateSampled"])
    span_days = (window_last - window_first).days
    span_months = months_between(window_first, window_last)

    rates_available = (len(window) >= RATE_MIN_POINTS
                       and RATE_MIN_SPAN_DAYS <= span_days <= RATE_MAX_SPAN_DAYS)
    p_band = period_band(span_months) if rates_available else None
    t4_limits: dict[str, Any] = TABLE4[r_band][p_band] if p_band else {}

    if not rates_available:
        if len(usable) < RATE_MIN_POINTS:
            assumptions.append(
                f"Only {len(usable)} sample(s) on record - fewer than the three a "
                "multi-point rate needs, so Table 4 was not applied (section 6, "
                "'two samples only').")
        elif span_days < RATE_MIN_SPAN_DAYS:
            assumptions.append(
                f"The last {len(window)} samples span {span_days} days, short of the "
                "four months Table 4 is quoted for, so no rate was computed.")
        else:
            assumptions.append(
                f"The last {len(window)} samples span {span_days} days, beyond Table 4's "
                "two-year range, so no rate was computed.")

    # ---- per-gas evidence -------------------------------------------------
    evidence = [
        _evaluate_gas(gas, usable, window, t1_limits, t2_limits, t3_limits,
                      t4_limits, rates_available, latest_date)
        for gas in GASES
    ]

    measured = [e for e in evidence if e.measured]
    if not measured:
        return _no_data(asset, "No gas in the record has a usable reading.")

    unmeasured = [e.gas for e in evidence if not e.measured]
    if unmeasured:
        assumptions.append("Not measured, so excluded from every comparison: "
                           f"{', '.join(unmeasured)}.")

    missing_t3 = [e.gas for e in measured if e.t3 is None and e.delta is not None]
    if missing_t3:
        assumptions.append(
            f"No Table 3 limit is legible for {', '.join(missing_t3)} in the {r_band} "
            "section, so its change was reported but not tested.")

    # ---- the decision, exactly as Figure 2 draws it ------------------------
    # Note the asymmetry the standard prints: decision 1 needs every level
    # strictly *below* Table 1, while decision 2 asks whether any level is
    # strictly *above* Table 2. A value sitting exactly on a limit therefore
    # fails both and lands in Status 2 - that is the standard's own wording,
    # not a rounding slip here.
    all_levels_below_t1 = all(
        e.latest is not None and e.t1 is not None and e.latest < e.t1 for e in measured)
    delta_tripped = any(e.exceedsT3 for e in measured)
    rate_tripped = any(e.exceedsT4 for e in measured)

    if all_levels_below_t1 and not delta_tripped and not (rates_available and rate_tripped):
        status = 1
        reason = ("Every measured gas is below its Table 1 (90th percentile) level, no "
                  "change exceeds Table 3, and no rate exceeds Table 4.")
    elif any(e.exceedsT2 for e in measured) or (rates_available and rate_tripped):
        status = 3
        reason = _status3_reason(measured, rates_available and rate_tripped)
    else:
        status = 2
        reason = _status2_reason(measured, delta_tripped)

    triggered_by = _triggers(measured, rates_available)

    # ---- section 6 refinements, as flags rather than status changes -------
    pending = status == 2 and all_levels_below_t1 and delta_tripped
    confirmation = None
    if pending:
        confirmation = {
            "required": True,
            "reason": ("Levels are all below Table 1 but the change since the previous "
                       "sample exceeds Table 3. The standard (steps 4b-4e) calls for a "
                       "confirmation DGA within one month before acting: if it shows no "
                       "real increase the unit returns to Status 1; if it confirms the "
                       "increase the unit stays at Status 2."),
            "dueWithin": "1 month",
            "fromSample": latest_date.strftime("%Y-%m-%d"),
        }

    extreme = _extreme_flags(measured)
    de_escalation = _de_escalation_candidate(status, measured, delta_tripped, rate_tripped)

    return {
        "asset": asset,
        "status": status,
        "statusLabel": STATUS_META[status]["label"],
        "verdict": STATUS_META[status]["verdict"],
        "color": STATUS_META[status]["color"],
        "bg": STATUS_META[status]["bg"],
        "action": STATUS_META[status]["action"],
        "reason": reason,
        "ratioBand": r_band,
        "ageBand": a_band,
        "periodBand": p_band,
        "ageYears": age_years,
        "o2n2": o2_n2,
        "ratesAvailable": rates_available,
        "assumptions": assumptions,
        "triggeredBy": triggered_by,
        "gases": [e.as_dict() for e in evidence],
        "measuredGases": [e.gas for e in measured],
        "pendingConfirmation": pending,
        "confirmation": confirmation,
        "extreme": extreme,
        "deEscalationCandidate": de_escalation,
        "samples": len(usable),
        "firstSample": dga_trend._parse_date(usable[0]["DateSampled"]).strftime("%Y-%m-%d"),
        "latestSample": latest_date.strftime("%Y-%m-%d"),
        "rateWindow": {
            "points": len(window),
            "from": window_first.strftime("%Y-%m-%d"),
            "to": window_last.strftime("%Y-%m-%d"),
            "spanDays": span_days,
            "spanMonths": span_months,
        },
        "decisionTrace": _trace(all_levels_below_t1, delta_tripped, rate_tripped,
                                rates_available, measured, status),
        "verifyCells": _verify_cells(measured),
        "standard": "IEEE C57.104-2019, Figure 2",
    }


def _no_data(asset: str, message: str) -> dict[str, Any]:
    """The shape callers get when there is nothing to classify.

    Same keys as a real result, so the frontend never has to branch on absence.
    """
    return {
        "asset": asset, "status": None, "statusLabel": "Not classified",
        "verdict": "No data", "color": "#94A3B8", "bg": "#F1F5F9",
        "action": "Take a DGA sample.", "reason": message,
        "ratioBand": None, "ageBand": None, "periodBand": None, "ageYears": None,
        "o2n2": None, "ratesAvailable": False, "assumptions": [message],
        "triggeredBy": [], "gases": [], "measuredGases": [],
        "pendingConfirmation": False, "confirmation": None, "extreme": [],
        "deEscalationCandidate": False, "samples": 0,
        "firstSample": None, "latestSample": None, "rateWindow": None,
        "decisionTrace": [], "verifyCells": [],
        "standard": "IEEE C57.104-2019, Figure 2",
    }


def _oxygen_nitrogen(samples: list[dict[str, Any]]) -> tuple[float | None, str, bool]:
    """The O2/N2 ratio from the newest sample that carries both gases.

    The tie note in section 2 is handled here: when the ratio crosses 0.2 across
    the recent samples the >0.2 section is forced, rather than letting the whole
    limit column flip with each result.
    """
    ratios: list[float] = []
    for s in reversed(samples[-3:]):
        o2, n2 = s.get("O2ppm"), s.get("N2ppm")
        if o2 is None or n2 is None or float(n2) == 0:
            continue
        ratios.append(float(o2) / float(n2))

    if not ratios:
        return None, ("O2/N2 was not measured - the guide's instruction for an "
                      "unavailable ratio is to use the >0.2 section, which carries the "
                      "tighter limits."), False

    newest = ratios[0]
    oscillating = any(r > 0.2 for r in ratios) and any(r <= 0.2 for r in ratios)
    if oscillating:
        return newest, ("O2/N2 crosses 0.2 across the recent samples - the >0.2 section "
                        "was forced so the limits do not flip sample to sample."), True
    return newest, "", False


def _evaluate_gas(gas: str, samples: list[dict[str, Any]], window: list[dict[str, Any]],
                  t1_limits: dict[str, Any], t2_limits: dict[str, Any],
                  t3_limits: dict[str, Any], t4_limits: dict[str, Any],
                  rates_available: bool, latest_date: datetime) -> GasEvidence:
    points = _points(samples, gas)
    t1, t1v = _cell(t1_limits.get(gas))
    t2, t2v = _cell(t2_limits.get(gas))
    t3, t3v = _cell(t3_limits.get(gas))
    t4, t4v = _cell(t4_limits.get(gas)) if t4_limits else (None, False)

    ev = GasEvidence(gas=gas, measured=bool(points),
                     t1=t1, t1Verify=t1v, t2=t2, t2Verify=t2v,
                     t3=t3, t3Verify=t3v, t4=t4, t4Verify=t4v)
    if not points:
        ev.note = "not measured"
        return ev

    ev.latest = points[-1][1]
    ev.latestDate = points[-1][0].strftime("%Y-%m-%d")
    if points[-1][0] < latest_date:
        ev.note = "carried from an earlier sample - not measured in the newest one"

    if len(points) > 1:
        ev.previous = points[-2][1]
        ev.previousDate = points[-2][0].strftime("%Y-%m-%d")
        ev.delta = ev.latest - ev.previous
    elif not ev.note:
        ev.note = "one reading only - no change to test against Table 3"

    # Levels against Tables 1 and 2.
    if t1 is not None:
        ev.exceedsT1 = ev.latest > t1
    if t2 is not None:
        ev.exceedsT2 = ev.latest > t2

    # Change against Table 3.
    if ev.delta is not None:
        if t3 == ANY_INCREASE:
            ev.exceedsT3 = ev.delta > 0
        elif t3 is not None:
            ev.exceedsT3 = ev.delta > t3

    # Rate against Table 4, fitted over the window shared by every gas so a
    # single period band applies to the whole result.
    if rates_available:
        in_window = _points(window, gas)
        if len(in_window) >= RATE_MIN_POINTS:
            ev.ratePoints = len(in_window)
            ev.rateSpanDays = (in_window[-1][0] - in_window[0][0]).days
            ev.rate = _slope_per_year(in_window)
            if ev.rate is not None:
                if t4 == ANY_INCREASE:
                    ev.exceedsT4 = ev.rate > 0
                elif t4 is not None:
                    ev.exceedsT4 = ev.rate > t4
        elif not ev.note:
            ev.note = (f"only {len(in_window)} reading(s) inside the rate window - "
                       "no Table 4 comparison")
    return ev


def _limit_text(limit: Any) -> str:
    if limit == ANY_INCREASE:
        return "any increase"
    if limit is None:
        return "no limit available"
    return f"{limit:g}"


def _triggers(measured: list[GasEvidence], rates_available: bool) -> list[dict[str, Any]]:
    """The audit trail from section 7: what actually pushed the status up.

    Ordered worst first, so the first row is the one to read out loud.
    """
    rows: list[dict[str, Any]] = []
    for e in measured:
        if e.exceedsT2:
            rows.append({"gas": e.gas, "kind": "level>T2", "value": e.latest,
                         "limit": e.t2, "severity": 3, "verify": e.t2Verify,
                         "text": (f"{e.gas} is {e.latest:g} ppm, above the Table 2 "
                                  f"(95th percentile) level of {_limit_text(e.t2)} ppm.")})
        elif e.exceedsT1:
            rows.append({"gas": e.gas, "kind": "level>T1", "value": e.latest,
                         "limit": e.t1, "severity": 2, "verify": e.t1Verify,
                         "text": (f"{e.gas} is {e.latest:g} ppm, above the Table 1 "
                                  f"(90th percentile) level of {_limit_text(e.t1)} ppm.")})
        if e.exceedsT3:
            kind = "C2H2 any-increase" if e.t3 == ANY_INCREASE else "delta>T3"
            rows.append({"gas": e.gas, "kind": kind, "value": e.delta, "limit": e.t3,
                         "severity": 2, "verify": e.t3Verify,
                         "text": (f"{e.gas} rose {e.delta:+g} ppm since {e.previousDate}, "
                                  f"against a Table 3 allowance of {_limit_text(e.t3)}.")})
        if rates_available and e.exceedsT4:
            kind = "C2H2 any-increase" if e.t4 == ANY_INCREASE else "rate>T4"
            rows.append({"gas": e.gas, "kind": kind, "value": e.rate, "limit": e.t4,
                         "severity": 3, "verify": e.t4Verify,
                         "text": (f"{e.gas} is rising at {e.rate:+.1f} ppm/year over "
                                  f"{e.ratePoints} samples, against a Table 4 allowance "
                                  f"of {_limit_text(e.t4)} ppm/year.")})
    rows.sort(key=lambda r: -r["severity"])
    return rows


def _status3_reason(measured: list[GasEvidence], rate_tripped: bool) -> str:
    over_t2 = [e.gas for e in measured if e.exceedsT2]
    over_t4 = [e.gas for e in measured if e.exceedsT4] if rate_tripped else []
    parts = []
    if over_t2:
        parts.append(f"{', '.join(over_t2)} above the Table 2 (95th percentile) level")
    if over_t4:
        parts.append(f"{', '.join(over_t4)} rising faster than Table 4 allows")
    return "Status 3 on " + " and ".join(parts) + "."


def _status2_reason(measured: list[GasEvidence], delta_tripped: bool) -> str:
    over_t1 = [e.gas for e in measured if e.exceedsT1]
    over_t3 = [e.gas for e in measured if e.exceedsT3]
    parts = []
    if over_t1:
        parts.append(f"{', '.join(over_t1)} above the Table 1 (90th percentile) level")
    if delta_tripped:
        parts.append(f"{', '.join(over_t3)} changing by more than Table 3 allows")
    if not parts:
        # Nothing is strictly over a limit, so a value is sitting exactly on one.
        on_limit = [e.gas for e in measured
                    if e.latest is not None and e.t1 is not None and e.latest == e.t1]
        parts.append(f"{', '.join(on_limit) or 'a gas'} sitting exactly on its Table 1 "
                     "level, which the standard counts as neither below nor above")
    return "Not all quiet, but nothing above Table 2 either: " + " and ".join(parts) + "."


def _extreme_flags(measured: list[GasEvidence]) -> list[dict[str, Any]]:
    """Section 6, step 8 - values far past the tables, for expert review."""
    flags: list[dict[str, Any]] = []
    for e in measured:
        if (e.latest is not None and isinstance(e.t2, (int, float))
                and e.latest >= e.t2 * EXTREME_LEVEL_MULTIPLE):
            flags.append({
                "gas": e.gas, "kind": "level",
                "text": (f"{e.gas} at {e.latest:g} ppm is at least "
                         f"{EXTREME_LEVEL_MULTIPLE:g}x its Table 2 level of "
                         f"{e.t2:g} ppm."),
            })
        for gas, kind, threshold, wording in EXTREME_RULES:
            if e.gas != gas:
                continue
            value = e.latest if kind == "level" else e.delta
            if value is not None and value >= threshold:
                flags.append({"gas": gas, "kind": kind,
                              "text": f"{wording} ({value:+g} ppm)."})
    return flags


def _de_escalation_candidate(status: int, measured: list[GasEvidence],
                             delta_tripped: bool, rate_tripped: bool) -> bool:
    """True when Status 3 rests only on carbon-oxide levels with no gassing.

    Section 6, step 7 allows such a unit to be downgraded - but by an engineer
    after a year of quiet results, never automatically, so this is only ever a
    flag on the report.
    """
    if status != 3 or delta_tripped or rate_tripped:
        return False
    over = [e.gas for e in measured if e.exceedsT2]
    return bool(over) and set(over) <= {"CO", "CO2"}


def _trace(all_below_t1: bool, delta_tripped: bool, rate_tripped: bool,
           rates_available: bool, measured: list[GasEvidence],
           status: int) -> list[dict[str, Any]]:
    """The Figure 2 path, one row per decision box, for the report."""
    over_t1 = [e.gas for e in measured if e.exceedsT1]
    over_t3 = [e.gas for e in measured if e.exceedsT3]
    over_t4 = [e.gas for e in measured if e.exceedsT4]
    over_t2 = [e.gas for e in measured if e.exceedsT2]
    return [
        {"step": "Levels vs Table 1",
         "question": "Is every measured gas below its 90th percentile level?",
         "answer": "Yes" if all_below_t1 else "No",
         "pass": all_below_t1,
         "detail": "all below" if all_below_t1 else f"{', '.join(over_t1)} above"},
        {"step": "Change vs Table 3",
         "question": "Is every change since the previous sample within the allowance?",
         "answer": "No" if delta_tripped else "Yes",
         "pass": not delta_tripped,
         "detail": f"{', '.join(over_t3)} over" if delta_tripped else "all within"},
        {"step": "Rate vs Table 4",
         "question": "Is every multi-point rate within the allowance?",
         "answer": ("Not applicable" if not rates_available
                    else "No" if rate_tripped else "Yes"),
         "pass": (not rates_available) or (not rate_tripped),
         "detail": ("no multi-point rate available" if not rates_available
                    else f"{', '.join(over_t4)} over" if rate_tripped else "all within")},
        {"step": "Levels vs Table 2",
         "question": "Is any measured gas above its 95th percentile level?",
         "answer": "Yes" if over_t2 else "No",
         "pass": not over_t2,
         "detail": f"{', '.join(over_t2)} above" if over_t2 else "none above"},
        {"step": "Result", "question": "Figure 2 outcome",
         "answer": STATUS_META[status]["label"], "pass": status == 1,
         "detail": STATUS_META[status]["verdict"]},
    ]


def _verify_cells(measured: list[GasEvidence]) -> list[dict[str, str]]:
    """Which of the limits actually used came from an ambiguous scan cell."""
    out: list[dict[str, str]] = []
    for e in measured:
        for table, used, flagged in (("Table 1", e.t1, e.t1Verify),
                                     ("Table 2", e.t2, e.t2Verify),
                                     ("Table 3", e.t3, e.t3Verify),
                                     ("Table 4", e.t4, e.t4Verify)):
            if flagged:
                out.append({"gas": e.gas, "table": table, "limit": _limit_text(used)})
    return out


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------
def _age_for(asset: str) -> tuple[float | None, dict[str, Any] | None]:
    """Asset age in years from the CMMS register, with its provenance.

    An unreachable CMMS costs the age band, not the classification: the guide
    has an explicit 'Unknown' column for exactly this case.
    """
    try:
        found = attributes.manufacture_year(asset)
    except Exception:
        return None, None
    if not found or found.get("age") is None:
        return None, None
    return float(found["age"]), {
        "manufactureYear": found.get("year"),
        "label": found.get("label"),
        "source": found.get("source"),
        "inheritedFrom": found.get("inheritedFrom"),
    }


def asset_status(asset: str, date_from: str = "1900-01-01",
                 date_to: str = "2999-12-31") -> dict[str, Any]:
    """Figure 2 status for one asset, read straight from the DGA table."""
    key = (asset or "").strip()
    samples = dga_trend.fetch_samples([key], date_from, date_to).get(key, [])
    age, provenance = _age_for(key)
    result = classify(samples, age, key)
    result["ageSource"] = provenance
    return result


def age_source() -> str:
    """Whether a fleet sweep can put ages on its rows.

    `"cmms-map"` when the snapshot job's manufacture-year map is primed and
    fresh, `"unavailable"` otherwise. The distinction matters because the
    fallback is not a slower answer, it is a different one - see
    :func:`_fleet_ages`.
    """
    return "unavailable" if attributes.loaded_map() is None else "cmms-map"


def _fleet_ages(assets: list[str]) -> dict[str, float]:
    """Ages for a whole sweep in one pass, or none at all.

    With the CMMS map primed this is pure memory. Without it,
    `manufacture_year` goes to the wire once per asset - ~0.1s each, minutes
    across a sweep - which is far too slow inside a request, so the sweep runs
    age-blind instead and the caller reports that. Tables 1 and 2 carry an
    explicit 'Unknown' column for exactly this case, so the classification is
    still valid; it just uses the age-independent limits.
    """
    if attributes.loaded_map() is None:
        return {}
    ages: dict[str, float] = {}
    for asset in assets:
        age, _ = _age_for(asset)
        if age is not None:
            ages[asset] = age
    return ages


def fleet_status(assets: list[str], date_from: str = "1900-01-01",
                 date_to: str = "2999-12-31") -> list[dict[str, Any]]:
    """One compact row per asset, worst status first."""
    grouped = dga_trend.fetch_samples(assets, date_from, date_to)
    ages = _fleet_ages(list(grouped))
    rows: list[dict[str, Any]] = []
    for asset, samples in grouped.items():
        age = ages.get(asset)
        full = classify(samples, age, asset)
        top = full["triggeredBy"][0] if full["triggeredBy"] else None
        rows.append({
            "asset": asset,
            "status": full["status"],
            "statusLabel": full["statusLabel"],
            "verdict": full["verdict"],
            "color": full["color"],
            "bg": full["bg"],
            "ratioBand": full["ratioBand"],
            "ageBand": full["ageBand"],
            "ageYears": full["ageYears"],
            "ratesAvailable": full["ratesAvailable"],
            "samples": full["samples"],
            "latestSample": full["latestSample"],
            "triggers": len(full["triggeredBy"]),
            "topTrigger": top["text"] if top else None,
            "pendingConfirmation": full["pendingConfirmation"],
            "extreme": len(full["extreme"]),
        })
    # Worst first; unclassified assets sink to the bottom of the list.
    rows.sort(key=lambda r: (-(r["status"] or 0), r["asset"]))
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fleet counts by status, for the header tiles."""
    counts = {"status1": 0, "status2": 0, "status3": 0, "unclassified": 0}
    for r in rows:
        if r["status"] == 1:
            counts["status1"] += 1
        elif r["status"] == 2:
            counts["status2"] += 1
        elif r["status"] == 3:
            counts["status3"] += 1
        else:
            counts["unclassified"] += 1
    counts["total"] = len(rows)
    counts["pendingConfirmation"] = sum(1 for r in rows if r["pendingConfirmation"])
    counts["extreme"] = sum(1 for r in rows if r["extreme"])
    return counts


# --------------------------------------------------------------------------
# Section 7 - the report
# --------------------------------------------------------------------------
def report(asset: str, date_from: str = "1900-01-01",
           date_to: str = "2999-12-31") -> dict[str, Any]:
    """Everything a signed-off DGA status report needs, in one payload.

    The status result, the samples it was computed from, the exact limit
    columns that applied, the recommended actions and the caveats. The frontend
    renders and prints it; nothing here is presentational.
    """
    key = (asset or "").strip()
    samples = dga_trend.fetch_samples([key], date_from, date_to).get(key, [])
    age, provenance = _age_for(key)
    return _build_report(samples, key, age, provenance)


def _build_report(samples: list[dict[str, Any]], key: str, age: float | None,
                  provenance: dict[str, Any] | None,
                  source: str = "stored") -> dict[str, Any]:
    """Assemble the report payload from samples that are already in hand.

    Split out of :func:`report` so the hand-entry path produces a payload of
    exactly the same shape - the frontend renders one report component, not two,
    and a what-if assessment is therefore as auditable as a stored one.
    """
    result = classify(samples, age, key)
    result["ageSource"] = provenance

    ordered = sorted(
        (s for s in samples if dga_trend._parse_date(s.get("DateSampled")) is not None),
        key=lambda s: dga_trend._parse_date(s["DateSampled"]),
    )
    sample_rows = [
        {
            "date": dga_trend._parse_date(s["DateSampled"]).strftime("%Y-%m-%d"),
            **{g: (None if s.get(GAS_COLUMN[g]) is None else float(s[GAS_COLUMN[g]]))
               for g in GASES},
            "O2": None if s.get("O2ppm") is None else float(s["O2ppm"]),
            "N2": None if s.get("N2ppm") is None else float(s["N2ppm"]),
        }
        for s in ordered
    ]

    limits_used = None
    if result["status"] is not None:
        r_band, a_band, p_band = result["ratioBand"], result["ageBand"], result["periodBand"]
        limits_used = {
            "table1": {g: _cell(TABLE1[r_band][a_band][g])[0] for g in GASES},
            "table2": {g: _cell(TABLE2[r_band][a_band][g])[0] for g in GASES},
            "table3": {g: _cell(TABLE3[r_band][g])[0] for g in GASES},
            "table4": ({g: _cell(TABLE4[r_band][p_band][g])[0] for g in GASES}
                       if p_band else None),
            "columns": {"ratioBand": r_band, "ageBand": a_band, "periodBand": p_band},
        }

    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asset": key,
        "source": source,
        "status": result,
        "sampleTable": sample_rows,
        "limitsUsed": limits_used,
        "recommendations": _recommendations(result),
        "caveats": _caveats(result),
        "standard": ("IEEE C57.104-2019 - Guide for the Interpretation of Gases "
                     "Generated in Mineral Oil-Immersed Transformers, 6.1.3 / Figure 2"),
    }


def _recommendations(result: dict[str, Any]) -> list[str]:
    """The status action, plus whatever the section 6 refinements add on top."""
    if result["status"] is None:
        return ["Take a DGA sample - there is nothing on record to classify."]

    out: list[str] = [result["action"]]

    if result["pendingConfirmation"]:
        out.append("Take a confirmation DGA within one month and re-run this "
                   "classification before changing the maintenance plan.")
    if not result["ratesAvailable"]:
        out.append("Build up to at least three samples spanning four months or more so a "
                   "multi-point rate can be established - Table 4 is the part of the "
                   "guide that catches slow, steady gassing.")
    if result["extreme"]:
        out.append("Escalate to a transformer specialist now: one or more values are far "
                   "beyond the tables, which the guide treats as an immediate "
                   "expert-review case rather than a routine status.")
    if result["deEscalationCandidate"]:
        out.append("This Status 3 rests only on carbon-oxide levels with no active "
                   "gassing. The guide allows an engineer to downgrade such a unit after "
                   "a year of quiet results - a manual decision, not an automatic one.")
    if result["status"] == 3:
        out.append("Run the Duval pentagon and triangle diagnosis on the latest sample to "
                   "name the fault type before deciding on an intervention.")
    return out


def _caveats(result: dict[str, Any]) -> list[str]:
    out = list(result["assumptions"])
    if result["verifyCells"]:
        cells = ", ".join(f"{c['gas']} {c['table']} ({c['limit']})"
                          for c in result["verifyCells"])
        out.append("These limits came from cells the source scan rendered ambiguously "
                   "and should be checked against a printed copy of the standard: "
                   f"{cells}.")
    out.append("This classification answers the status question only. It says how far "
               "the unit sits from the fleet population, not what fault is present - use "
               "the Duval methods for that.")
    return out


# --------------------------------------------------------------------------
# Hand-entered data
# --------------------------------------------------------------------------
# The same classifier, fed from a form instead of the database. This exists for
# three real cases: a unit whose lab results have not been loaded yet, a
# what-if check against figures read off a test certificate, and validating the
# port against the known-answer vector in the spec. Nothing here re-implements
# the decision - it normalises input and hands it to `classify`.

class ManualEntryError(ValueError):
    """Input the caller must fix. The route turns this into a 400."""


# What a form row may carry, mapped onto the internal sample column names.
MANUAL_FIELDS = {g: GAS_COLUMN[g] for g in GASES}
MANUAL_FIELDS.update({"O2": "O2ppm", "N2": "N2ppm"})

# A ppm reading above this is almost certainly a typo or a wrong unit. The
# guide's own extreme-value flag sits far below it, so rejecting here costs
# nothing real and catches a misplaced decimal point.
MANUAL_MAX_PPM = 1_000_000


def _manual_number(value: Any, field: str, row_no: int) -> float | None:
    """One gas cell: blank means 'not measured', never 'zero'.

    The distinction matters to the standard - section 1 says an unmeasured gas
    is skipped in every comparison, whereas a measured zero is a real reading
    that participates in deltas.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ManualEntryError(
            f"Sample {row_no}: {field} is not a number ({value!r}). Leave it blank "
            f"if the gas was not measured.")
    if out != out or out in (float("inf"), float("-inf")):
        raise ManualEntryError(f"Sample {row_no}: {field} is not a finite number.")
    if out < 0:
        raise ManualEntryError(f"Sample {row_no}: {field} is negative ({out:g}). "
                               f"Dissolved-gas concentrations cannot be below zero.")
    if out > MANUAL_MAX_PPM:
        raise ManualEntryError(
            f"Sample {row_no}: {field} is {out:g} ppm, beyond anything physically "
            f"plausible - check the value and the unit.")
    return out


def _manual_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn form rows into the sample dicts `classify` reads.

    Rows arrive as ``{date, H2, CH4, ..., O2, N2}``; the classifier wants
    ``{DateSampled, H2ppm, ...}``. Validation is strict and the messages name
    the row, because a silently dropped sample would change the rate group and
    therefore the status.
    """
    if not isinstance(rows, list) or not rows:
        raise ManualEntryError("Enter at least one sample before running the "
                               "classification.")
    if len(rows) > 24:
        raise ManualEntryError("At most 24 samples can be entered at once; the rate "
                               "window only ever uses the newest six.")

    out: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ManualEntryError(f"Sample {i} is not a valid row.")

        raw_date = str(row.get("date") or "").strip()
        if not raw_date:
            raise ManualEntryError(f"Sample {i}: a sampling date is required - the "
                                   f"date decides the rate window and the Table 4 "
                                   f"period band.")
        parsed = dga_trend._parse_date(raw_date)
        if parsed is None:
            raise ManualEntryError(f"Sample {i}: '{raw_date}' is not a date the system "
                                   f"can read. Use YYYY-MM-DD.")
        iso = parsed.strftime("%Y-%m-%d")
        if iso in seen_dates:
            raise ManualEntryError(f"Sample {i}: two samples are dated {iso}. Each "
                                   f"sample needs its own date.")
        seen_dates.add(iso)

        sample: dict[str, Any] = {"DateSampled": iso}
        for field, column in MANUAL_FIELDS.items():
            sample[column] = _manual_number(row.get(field), field, i)

        if all(sample[GAS_COLUMN[g]] is None for g in GASES):
            raise ManualEntryError(f"Sample {i} ({iso}) has no gas readings at all. "
                                   f"Enter at least one gas or remove the row.")
        out.append(sample)

    out.sort(key=lambda s: s["DateSampled"])
    return out


def _manual_age(value: Any) -> float | None:
    """Age in years, or None for 'unknown' - which selects the Unknown column."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        age = float(value)
    except (TypeError, ValueError):
        raise ManualEntryError(f"Age '{value}' is not a number. Leave it blank if the "
                               f"transformer's age is unknown.")
    if age < 0:
        raise ManualEntryError("Age cannot be negative.")
    if age > 120:
        raise ManualEntryError(f"An age of {age:g} years is implausible - enter the age "
                               f"in years, not the year of manufacture.")
    return age


def manual_report(rows: list[dict[str, Any]], age_years: Any = None,
                  label: str = "") -> dict[str, Any]:
    """Classify hand-entered samples and return the full report payload.

    Same shape as :func:`report`, so the frontend renders and exports it through
    exactly the same path as a stored asset. Raises :class:`ManualEntryError`
    for anything the user has to correct.
    """
    samples = _manual_samples(rows)
    age = _manual_age(age_years)

    name = (label or "").strip() or "Entered data"
    provenance = {
        "manufactureYear": None,
        "label": ("Age entered by hand" if age is not None
                  else "Age not supplied - Unknown age column used"),
        "source": "manual-entry",
        "inheritedFrom": None,
    }

    payload = _build_report(samples, name, age, provenance, source="manual")

    # An entered assessment is only as good as what was typed in, and the
    # report is printable - so the caveat travels with it rather than living
    # only in the screen that produced it.
    payload["caveats"].insert(0, (
        "This assessment was run against hand-entered values, not laboratory "
        "records held in the system. The figures have not been checked against "
        "CEB_DGA_DATA and no sample provenance is recorded."))
    if age is None:
        payload["caveats"].insert(1, (
            "No transformer age was entered, so the Unknown-age column of Tables 1 "
            "and 2 was used. Supplying the age can move the unit into a different "
            "column and change the status."))
    return payload
