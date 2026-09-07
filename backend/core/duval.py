"""Duval triangles, IEEE C57.104-2019 severity, Rogers ratios and key gas.

The triangle says *what kind* of fault; the IEEE tables say *how bad*. Both are
reported, and disagreements between methods are surfaced rather than resolved -
that disagreement is the diagnostic value.

Triangle 1 (CH4 / C2H4 / C2H2) is specified in full by the build spec, including
its zone polygons, and is implemented exactly.

Triangles 4 and 5 are **provisional**: the build spec names them as a future
extension (reusing the same projection with a different gas triplet) but does
not give their coordinates, so the polygons below come from the published Duval
method rather than from the project's own specification. Every payload carries
``provisional: true`` for them, and the UI badges them, pending engineering
sign-off against the plant's reference charts.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

Ternary = tuple[float, float, float]
Point = tuple[float, float]

EPS = 1e-6

# ==========================================================================
# Ternary projection
# ==========================================================================
def ternary_to_cartesian(a: float, b: float, c: float) -> Point:
    """`a` -> left vertex, `b` -> right vertex, `c` -> apex. Normalised here."""
    total = a + b + c
    if total == 0:
        return (0.5, 0.5)
    a, b, c = a / total, b / total, c / total
    return (b + c * 0.5, c * (3 ** 0.5) / 2)


def point_in_polygon(px: float, py: float, poly: Sequence[Point]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            if px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


# ==========================================================================
# Triangle definitions
# ==========================================================================
ZONE_COLORS = {
    "PD": "#AED6F1", "T1": "#A9DFBF", "T2": "#F9E79F", "T3": "#F0B27A",
    "D1": "#D2B4DE", "D2": "#F1948A", "DT": "#CCD1D1",
    "S": "#AED6F1", "C": "#F1948A", "O": "#D7BDE2", "ND": "#E2E8F0",
}

ZONE_MEANING = {
    "PD": "Partial discharges (corona)",
    "D1": "Discharges of low energy (sparking)",
    "D2": "Discharges of high energy (arcing)",
    "T1": "Thermal fault < 300 °C",
    "T2": "Thermal fault 300-700 °C",
    "T3": "Thermal fault > 700 °C",
    "DT": "Mixed thermal and electrical fault",
    "S": "Stray gassing of mineral oil",
    "C": "Thermal fault with carbonisation of paper",
    "O": "Overheating < 250 °C",
    "ND": "Not determined",
}

# --- Triangle 1: CH4 (left) / C2H4 (right) / C2H2 (apex) ------------------
# Derived from the threshold lines the build spec states in its own rule ladder
# (CH4=98, C2H2=4/13/15, C2H4=20/23/50), so the drawn zones and the classifier
# are the same object and can never disagree.
#
# The spec's literal section 4.2 vertex list is NOT used: several of its
# vertices do not sum to 100 - T1 (0,0,4), (98,0,0), (0,0,0); T2 (0,20,4),
# (0,50,0), (0,20,0); T3 (0,50,0); DT (0,0,4), (0,20,4) - and because
# ternary_to_cartesian normalises its inputs, (0,0,4) lands on the C2H2 apex and
# (0,0,0) has no defined position at all. Rendered verbatim, T1/T2/T3/DT come
# out as wrong, partly self-intersecting shapes. Every vertex below sums to 100
# and the seven zones tile the triangle exactly once.
T1_POLYS: dict[str, list[Ternary]] = {
    "PD": [(100, 0, 0), (98, 2, 0), (98, 0, 2)],
    "T1": [(98, 2, 0), (80, 20, 0), (76, 20, 4), (96, 0, 4), (98, 0, 2)],
    "T2": [(80, 20, 0), (50, 50, 0), (46, 50, 4), (76, 20, 4)],
    "T3": [(50, 50, 0), (0, 100, 0), (0, 85, 15), (35, 50, 15)],
    "DT": [(96, 0, 4), (46, 50, 4), (37, 50, 13), (87, 0, 13)],
    "D1": [(87, 0, 13), (64, 23, 13), (0, 23, 77), (0, 0, 100)],
    "D2": [(64, 23, 13), (37, 50, 13), (35, 50, 15), (0, 85, 15), (0, 23, 77)],
}

# --- Triangle 4 (provisional): H2 (left) / C2H6 (right) / CH4 (apex) ------
# Low-energy faults; refines PD / S / C / O.
T4_POLYS: dict[str, list[Ternary]] = {
    "PD": [(100, 0, 0), (98, 0, 2), (98, 2, 0)],
    "S": [(98, 2, 0), (98, 0, 2), (0, 0, 100), (0, 9, 91), (46, 9, 45), (46, 54, 0)],
    "C": [(0, 9, 91), (0, 30, 70), (24, 30, 46), (46, 9, 45)],
    "O": [(0, 30, 70), (0, 100, 0), (46, 54, 0), (46, 9, 45), (24, 30, 46)],
}

# --- Triangle 5 (provisional): CH4 (left) / C2H4 (right) / C2H6 (apex) ----
# Thermal faults; separates T2 / T3 from paper carbonisation and overheating.
T5_POLYS: dict[str, list[Ternary]] = {
    "S": [(100, 0, 0), (0, 0, 100), (0, 1, 99), (85, 1, 14)],
    "O": [(85, 1, 14), (0, 1, 99), (0, 24, 76), (54, 24, 22)],
    "C": [(0, 24, 76), (0, 60, 40), (30, 60, 10), (54, 24, 22)],
    "T3": [(0, 60, 40), (0, 100, 0), (49, 51, 0), (30, 60, 10)],
    "T2": [(49, 51, 0), (100, 0, 0), (85, 1, 14), (54, 24, 22), (30, 60, 10)],
}

TRIANGLES: dict[str, dict[str, Any]] = {
    "1": {
        "id": "1",
        "title": "Duval Triangle 1",
        "subtitle": "Primary fault-type diagnosis",
        "gases": ("CH4", "C2H4", "C2H2"),
        "axisLabels": ("% CH₄", "% C₂H₄", "% C₂H₂"),
        "polys": T1_POLYS,
        "order": ["PD", "D1", "D2", "DT", "T3", "T2", "T1"],
        "provisional": False,
    },
    "4": {
        "id": "4",
        "title": "Duval Triangle 4",
        "subtitle": "Low-energy fault refinement",
        "gases": ("H2", "C2H6", "CH4"),
        "axisLabels": ("% H₂", "% C₂H₆", "% CH₄"),
        "polys": T4_POLYS,
        "order": ["PD", "S", "C", "O"],
        "provisional": True,
    },
    "5": {
        "id": "5",
        "title": "Duval Triangle 5",
        "subtitle": "Thermal fault refinement",
        "gases": ("CH4", "C2H4", "C2H6"),
        "axisLabels": ("% CH₄", "% C₂H₄", "% C₂H₆"),
        "polys": T5_POLYS,
        "order": ["S", "O", "C", "T3", "T2"],
        "provisional": True,
    },
}


def _poly_centroid(cart: list[Point]) -> Point:
    n = len(cart)
    if n == 0:
        return (0.0, 0.0)
    a2 = cx = cy = 0.0
    for i in range(n):
        x_i, y_i = cart[i]
        x_j, y_j = cart[(i + 1) % n]
        cross = x_i * y_j - x_j * y_i
        a2 += cross
        cx += (x_i + x_j) * cross
        cy += (y_i + y_j) * cross
    area = a2 / 2.0
    if abs(area) < 1e-12:
        return (sum(p[0] for p in cart) / n, sum(p[1] for p in cart) / n)
    return (cx / (6.0 * area), cy / (6.0 * area))


def triangle_geometry(triangle_id: str = "1") -> dict[str, Any]:
    """Static drawing data for one triangle."""
    spec = TRIANGLES[triangle_id]
    zones = []
    for name in spec["order"]:
        pts = spec["polys"][name]
        cart = [ternary_to_cartesian(*t) for t in pts]
        lx, ly = _poly_centroid(cart)
        zones.append({
            "zone": name,
            "meaning": ZONE_MEANING.get(name, ""),
            "color": ZONE_COLORS.get(name, "#E2E8F0"),
            "points": [[round(x, 5), round(y, 5)] for x, y in cart],
            "labelX": round(lx, 4),
            "labelY": round(ly, 4),
        })
    return {
        "id": spec["id"], "title": spec["title"], "subtitle": spec["subtitle"],
        "gases": list(spec["gases"]), "axisLabels": list(spec["axisLabels"]),
        "provisional": spec["provisional"], "zones": zones,
        "outline": [[0, 0], [1, 0], [0.5, round(3 ** 0.5 / 2, 5)]],
    }


# Centre of the unit triangle, used to nudge boundary points inward.
_TRI_CENTRE = (0.5, 3 ** 0.5 / 6)


def classify_by_polygon(triangle_id: str, a: float, b: float, c: float) -> str:
    """Exact, drawing-consistent classification by point-in-polygon test.

    Preferred over a rule ladder: the ladder in the build spec is a rectangular
    approximation whose verdict can disagree with where the point visually
    lands, which destroys trust in the chart.

    A sample sitting exactly on a shared edge or a corner - a pure gas puts it
    right on a triangle vertex - is ambiguous under ray casting and would fall
    through every zone. Such points are retested a hair's breadth toward the
    centre, which resolves them to the zone they visually belong to while
    leaving interior points untouched.
    """
    spec = TRIANGLES[triangle_id]
    px, py = ternary_to_cartesian(a, b, c)
    zones = {name: [ternary_to_cartesian(*t) for t in spec["polys"][name]]
             for name in spec["order"]}

    for nudge in (0.0, 1e-9, 1e-6, 1e-4, 1e-3):
        qx = px + (_TRI_CENTRE[0] - px) * nudge
        qy = py + (_TRI_CENTRE[1] - py) * nudge
        for name in spec["order"]:
            if point_in_polygon(qx, qy, zones[name]):
                return name
    return "DT" if triangle_id == "1" else "ND"


def classify_by_ladder(pch4: float, pc2h4: float, pc2h2: float) -> str:
    """The legacy ordered rule ladder for Triangle 1, kept for comparison.

    Retained so the UI can show where the rectangular approximation and the
    exact polygon test disagree.
    """
    if pch4 >= 98:
        return "PD"
    if pc2h2 >= 29 and pc2h4 >= 23:
        return "D2"
    if pc2h2 >= 13 and pc2h4 < 23:
        return "D1"
    if 4 <= pc2h2 < 13:
        return "DT"
    if pc2h4 >= 50 and pc2h2 < 15:
        return "T3"
    if 20 <= pc2h4 < 50 and pc2h2 < 4:
        return "T2"
    if pch4 < 98 and pc2h4 < 20 and pc2h2 < 4:
        return "T1"
    return "DT"


def analyse_triangle(triangle_id: str, gases: dict[str, float]) -> dict[str, Any]:
    """Percentages, plotted point and zone for one triangle."""
    spec = TRIANGLES[triangle_id]
    ga, gb, gc = spec["gases"]
    a, b, c = (gases.get(ga) or 0.0), (gases.get(gb) or 0.0), (gases.get(gc) or 0.0)
    total = a + b + c
    if total <= 0:
        return {
            "id": spec["id"], "title": spec["title"], "provisional": spec["provisional"],
            "valid": False, "zone": None,
            "reason": f"All of {ga}, {gb}, {gc} are zero - nothing to plot.",
            "percentages": None, "point": None,
        }
    pa, pb, pc = a / total * 100, b / total * 100, c / total * 100
    zone = classify_by_polygon(triangle_id, pa, pb, pc)
    px, py = ternary_to_cartesian(pa, pb, pc)

    payload = {
        "id": spec["id"], "title": spec["title"], "subtitle": spec["subtitle"],
        "provisional": spec["provisional"], "valid": True,
        "gases": list(spec["gases"]),
        "percentages": {ga: round(pa, 1), gb: round(pb, 1), gc: round(pc, 1)},
        "point": {"x": round(px, 5), "y": round(py, 5)},
        "zone": zone,
        "meaning": ZONE_MEANING.get(zone, ""),
        "color": ZONE_COLORS.get(zone, "#E2E8F0"),
    }
    if triangle_id == "1":
        ladder = classify_by_ladder(pa, pb, pc)
        payload["ladderZone"] = ladder
        payload["ladderAgrees"] = ladder == zone
    return payload


# ==========================================================================
# IEEE C57.104-2019 severity
# ==========================================================================
# Column order: [Sealed 1-9y, Sealed 10-30y, Sealed >30y, Sealed unknown,
#                Free 1-9y, Free 10-30y, Free >30y, Free unknown]
TABLE1 = {
    "H2": [10, 40, 40, 40, 80, 100, 100, 100],
    "CH4": [25, 50, 90, 50, 90, 150, 200, 150],
    "C2H6": [10, 60, 150, 60, 90, 175, 250, 175],
    "C2H4": [20, 50, 90, 50, 50, 95, 175, 100],
    "C2H2": [1, 2, 2, 2, 1, 2, 4, 2],
    "CO": [500, 700, 900, 700, 900, 1100, 1100, 1100],
    "CO2": [3500, 5500, 7000, 5500, 9000, 14000, 14000, 12500],
}

TABLE2 = {
    "H2": [40, 80, 80, 80, 100, 150, 150, 150],
    "CH4": [45, 90, 145, 90, 110, 240, 310, 240],
    "C2H6": [30, 115, 245, 115, 150, 280, 400, 280],
    "C2H4": [25, 60, 115, 60, 80, 155, 280, 165],
    "C2H2": [2, 2, 4, 2, 2, 4, 7, 4],
    "CO": [600, 900, 1100, 900, 1100, 1400, 1400, 1400],
    "CO2": [5000, 8000, 10000, 8000, 12500, 18500, 18500, 16500],
}

# [Sealed, Free-breathing]
TABLE3 = {"H2": [25, 40], "CH4": [10, 30], "C2H6": [7, 25], "C2H4": [20, 20],
          "C2H2": [0, 0], "CO": [175, 250], "CO2": [1750, 2500]}

# [Sealed 4-9mo, Sealed 10-24mo, Free 4-9mo, Free 10-24mo]
TABLE4 = {"H2": [25, 10, 50, 20], "CH4": [4, 3, 15, 10], "C2H6": [3, 2, 15, 9],
          "C2H4": [7, 5, 10, 7], "C2H2": [0, 0, 0, 0],
          "CO": [100, 80, 200, 100], "CO2": [1000, 800, 1750, 1000]}

IEEE_GASES = ["H2", "CH4", "C2H6", "C2H4", "C2H2", "CO", "CO2"]

STATUS_INFO = {
    1: {"label": "NORMAL", "color": "#0E9F6E",
        "action": "Continue routine DGA sampling per company policy."},
    2: {"label": "INVESTIGATE", "color": "#B7791F",
        "action": "Resample within 1 month to confirm. Investigate possible causes."},
    3: {"label": "URGENT ATTENTION", "color": "#D64545",
        "action": ("Increased surveillance; consider online monitoring; consult a "
                   "transformer expert; additional testing.")},
}


def select_column(o2: float | None, n2: float | None, age: int | None) -> tuple[int, str]:
    """Pick the limit-table column from oxygen ratio and transformer age."""
    ratio = (o2 / n2) if (o2 and n2 and n2 > 0) else 0.0
    sealed = ratio <= 0.2
    if not age or age <= 0:
        idx = 3 if sealed else 7
        age_label = "unknown age"
    elif age <= 9:
        idx = 0 if sealed else 4
        age_label = "1-9 years"
    elif age <= 30:
        idx = 1 if sealed else 5
        age_label = "10-30 years"
    else:
        idx = 2 if sealed else 6
        age_label = ">30 years"
    kind = "Sealed / N₂-blanketed" if sealed else "Free-breathing"
    return idx, f"{kind}, {age_label}"


def assess_levels(gases: dict[str, float], age: int | None = None,
                  previous: dict[str, float] | None = None,
                  rates: dict[str, float] | None = None) -> dict[str, Any]:
    """Per-gas IEEE assessment and the overall DGA status.

    Note the deliberate asymmetry: a **rate** exceedance (Table 4) jumps
    straight to status 3, while a **delta** exceedance (Table 3) only reaches
    status 2 - a fast-rising gas is more dangerous than a merely high one.
    """
    col, col_label = select_column(gases.get("O2"), gases.get("N2"), age)
    sealed = col in (0, 1, 2, 3)
    t3_idx = 0 if sealed else 1
    rates = rates or {}

    rows = []
    any_t1 = any_t2 = any_t3 = any_t4 = False
    for gas in IEEE_GASES:
        value = float(gases.get(gas) or 0.0)
        lim1 = TABLE1[gas][col]
        lim2 = TABLE2[gas][col]
        lim3 = TABLE3[gas][t3_idx]

        delta = None
        if previous and previous.get(gas) is not None:
            delta = value - float(previous[gas])

        rate = rates.get(gas)
        # Table 4 column: <=9 months uses index 0/2, otherwise 1/3.
        t4_span = rates.get("_spanMonths")
        if t4_span is not None and t4_span <= 9:
            lim4 = TABLE4[gas][0 if sealed else 2]
        else:
            lim4 = TABLE4[gas][1 if sealed else 3]

        above1 = value > lim1
        above2 = value > lim2
        # Acetylene should not be generated at all in a healthy unit, so any
        # increase is flagged regardless of the table limit.
        above3 = delta is not None and (delta > lim3 or (gas == "C2H2" and delta > 0))
        above4 = rate is not None and (rate > lim4 or (gas == "C2H2" and rate > 0))

        any_t1 = any_t1 or above1
        any_t2 = any_t2 or above2
        any_t3 = any_t3 or above3
        any_t4 = any_t4 or above4

        rows.append({
            "gas": gas, "value": value, "table1": lim1, "table2": lim2,
            "table3": lim3, "table4": lim4, "delta": delta, "rate": rate,
            "aboveTable1": above1, "aboveTable2": above2,
            "aboveTable3": above3, "aboveTable4": above4,
            "severity": 3 if (above2 or above4) else (2 if (above1 or above3) else 1),
        })

    if any_t2 or any_t4:
        status = 3
    elif any_t1 or any_t3:
        status = 2
    else:
        status = 1

    info = STATUS_INFO[status]
    return {
        "status": status, "label": info["label"], "color": info["color"],
        "action": info["action"], "column": col, "columnLabel": col_label,
        "o2n2Ratio": round((gases.get("O2") or 0) / (gases.get("N2") or 1), 4)
        if gases.get("N2") else None,
        "gases": rows,
    }


def regression_rate(gas: str, points: list[tuple[Any, float]]) -> dict[str, Any]:
    """Least-squares ppm/year over 3..6 samples inside a 24-month window."""
    from datetime import datetime as _dt

    def _d(v):
        if isinstance(v, _dt):
            return v
        try:
            return _dt.fromisoformat(str(v)[:19])
        except ValueError:
            return None

    parsed = [(d, y) for d, y in ((_d(x), y) for x, y in points) if d is not None]
    if len(parsed) < 3:
        return {"rate": None, "points": len(parsed), "spanMonths": None}
    parsed.sort(key=lambda p: p[0])
    parsed = parsed[-6:]                       # keep the fit responsive
    earliest = parsed[0][0]
    xs = [float((d - earliest).days) for d, _ in parsed]
    ys = [float(v) for _, v in parsed]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return {"rate": None, "points": n, "spanMonths": None}
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    span = (parsed[-1][0] - earliest).days / 30.44
    return {"rate": round(slope * 365.25, 2), "points": n, "spanMonths": round(span, 1)}


# ==========================================================================
# Rogers ratios / key gas / paper involvement
# ==========================================================================
def rogers_ratios(gases: dict[str, float]) -> dict[str, Any]:
    """Rogers ratio case. `eps` guards every division, as in the ML features."""
    h2 = float(gases.get("H2") or 0.0)
    ch4 = float(gases.get("CH4") or 0.0)
    c2h6 = float(gases.get("C2H6") or 0.0)
    c2h4 = float(gases.get("C2H4") or 0.0)
    c2h2 = float(gases.get("C2H2") or 0.0)

    r1 = c2h2 / (c2h4 + EPS)
    r2 = ch4 / (h2 + EPS)
    r3 = c2h4 / (c2h6 + EPS)

    if r1 < 0.1 and 0.1 <= r2 <= 1.0 and r3 < 1.0:
        case, text = 0, "Unit Normal"
    elif r1 < 0.1 and r2 < 0.1 and r3 < 1.0:
        case, text = 1, "Low-Energy Density Arcing - Partial Discharge (PD)"
    elif 0.1 <= r1 <= 3.0 and 0.1 <= r2 <= 1.0 and r3 > 3.0:
        case, text = 2, "High-Energy Arcing - Discharge (D2)"
    elif r1 < 0.1 and r2 > 1.0 and 1.0 <= r3 <= 3.0:
        case, text = 3, "Low-Temperature Thermal Fault"
    elif r1 < 0.1 and r2 > 1.0 and r3 > 3.0:
        case, text = 4, "High-Temperature Thermal Fault"
    else:
        case, text = None, "Cannot identify fault using Rogers ratios method"

    return {"R1": round(r1, 4), "R2": round(r2, 4), "R3": round(r3, 4),
            "case": case, "diagnosis": text,
            "identified": case is not None}


KEY_GAS_MEANING = {
    "H2": "Corona partial discharge (PD) or catalytic reaction",
    "CH4": "Low-temperature thermal fault in oil (T1)",
    "C2H6": "Low-to-medium temperature thermal fault in oil",
    "C2H4": "High-temperature thermal fault in oil (T2/T3)",
    "C2H2": "Arcing at very high temperature (D2 / >1000 °C)",
    "CO": "Cellulose (paper insulation) thermal degradation",
}


def key_gas(gases: dict[str, float]) -> dict[str, Any]:
    candidates = {g: float(gases.get(g) or 0.0)
                  for g in ["H2", "CH4", "C2H6", "C2H4", "C2H2", "CO"]}
    total = sum(candidates.values())
    if total <= 0:
        return {"dominant": None, "interpretation": "No combustible gas detected.",
                "shares": []}
    dominant = max(candidates, key=lambda g: candidates[g])
    shares = [{"gas": g, "value": v, "percent": round(v / total * 100, 1)}
              for g, v in sorted(candidates.items(), key=lambda kv: -kv[1])]
    return {"dominant": dominant, "interpretation": KEY_GAS_MEANING[dominant],
            "shares": shares, "totalCombustible": round(total, 1)}


def paper_involvement(gases: dict[str, float]) -> dict[str, Any]:
    co = float(gases.get("CO") or 0.0)
    co2 = float(gases.get("CO2") or 0.0)
    notes: list[str] = []
    if co2 > 0 and co / (co2 + EPS) > 0.1:
        notes.append("CO/CO₂ > 0.1 - paper/cellulose insulation may be involved.")
    ratio = co2 / (co + EPS) if co > 0 else None
    if ratio is not None:
        if ratio < 3 and co > 500:
            notes.append("CO₂/CO < 3 with CO > 500 ppm - severe cellulose "
                         "degradation or arcing in paper.")
        elif ratio > 10:
            notes.append("CO₂/CO > 10 - normal ageing / low-intensity overheating; "
                         "paper not implicated.")
        elif 3 <= ratio <= 10:
            notes.append("CO₂/CO between 3 and 10 - mild or no abnormal cellulose "
                         "degradation.")
    return {"co": co, "co2": co2, "co2CoRatio": round(ratio, 2) if ratio else None,
            "notes": notes or ["Insufficient CO/CO₂ data to assess paper involvement."]}


def integrity_caveats(gases: dict[str, float]) -> list[str]:
    """Cheap sanity checks that catch most bad inputs before an engineer acts."""
    out: list[str] = []
    h2 = float(gases.get("H2") or 0)
    c2h4 = float(gases.get("C2H4") or 0)
    c2h2 = float(gases.get("C2H2") or 0)
    o2 = float(gases.get("O2") or 0)
    n2 = float(gases.get("N2") or 0)
    if c2h2 > 0 and h2 < 10 and c2h4 < 10:
        out.append("High C₂H₂ without matching H₂/C₂H₄ is physically implausible - "
                   "suspect a lab artifact or data-entry error.")
    if o2 > 10000:
        out.append("Free-breathing unit indicated by high O₂; gas limits are "
                   "naturally higher.")
    if o2 < 2000 and n2 > 10000:
        out.append("Sealed / nitrogen-blanketed unit; saturated hydrocarbons "
                   "accumulate over time without an emergency.")
    return out


DISCLAIMER = ("DGA analysis should always be performed by a qualified engineer. "
              "This tool is for guidance only, per IEEE C57.104-2019. Never act "
              "on DGA alone without expert review.")
