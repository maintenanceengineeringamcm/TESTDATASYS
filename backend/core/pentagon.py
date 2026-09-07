"""Duval Dual-Pentagon geometry and diagnosis.

Two pentagons are built from the same five-gas point. Only the zone
partitioning differs - outer geometry, axes, percentage maths, gas polygon and
centroid are identical.

The reference implementation drew everything but never classified the centroid;
:func:`diagnose` closes that gap, so both pentagons report a fault zone.

Pure functions only - no database or rendering dependency.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

Point = tuple[float, float]

# Clockwise from the top. The order is load-bearing: the gas polygon, the outer
# boundary and the shoelace centroid all assume this traversal.
GAS_ORDER = ["H2", "C2H2", "C2H4", "CH4", "C2H6"]

GAS_ANGLE = {"H2": 90.0, "C2H2": 18.0, "C2H4": -54.0, "CH4": -126.0, "C2H6": 162.0}

# Distance from centre to a vertex = 100% of one gas. Not arbitrary: the zone
# polygons below are hard-coded in these units, so R must not change unless
# every zone is rescaled with it.
R = 40.0

GAS_LABEL = {"H2": "H₂", "C2H2": "C₂H₂", "C2H4": "C₂H₄", "CH4": "CH₄", "C2H6": "C₂H₆"}

# Outward offsets for the vertex labels, in the same clockwise order.
LABEL_OFFSET = {
    "H2": (0.0, 2.5, "middle", "bottom"),
    "C2H2": (3.0, 0.5, "start", "middle"),
    "C2H4": (2.0, -2.0, "start", "hanging"),
    "CH4": (-2.0, -2.0, "end", "hanging"),
    "C2H6": (-3.0, 0.5, "end", "middle"),
}

ZONE_MEANING = {
    "PD": "Partial discharge (corona)",
    "D1": "Discharge of low energy",
    "D2": "Discharge of high energy",
    "T1": "Thermal fault, T < 300 °C",
    "T2": "Thermal fault, 300 °C < T < 700 °C",
    "T3": "Thermal fault, T > 700 °C",
    "S": "Stray gassing of mineral oil (< 200 °C)",
    "O": "Overheating, T < 250 °C",
    "C": "Thermal fault with carbonisation of paper",
    "T3-H": "Thermal fault T > 700 °C in oil only, no paper involved",
}

# S, PD, D1 and D2 are shared by both pentagons; defining them once keeps the
# two lists from drifting apart.
_SHARED = {
    "S": [(0, 1.5), (-35, 3.1), (-38, 12.4), (0, 40), (0, 33), (-1, 33),
          (-1, 24.5), (0, 24.5)],
    "PD": [(0, 33), (-1, 33), (-1, 24.5), (0, 24.5)],
    "D1": [(0, 40), (38, 12.4), (32, -6.1), (4, 16), (0, 1.5)],
    "D2": [(4, 16), (32, -6.1), (24.3, -30), (0, -3), (0, 1.5)],
}

ZONE_COLORS = {
    "S": "#AED6F1", "PD": "#F9E79F", "D1": "#A9DFBF", "D2": "#A3E4D7",
    "T3": "#FAD7A0", "T2": "#F1948A", "T1": "#D7BDE2",
    "O": "#D7BDE2", "C": "#F1948A", "T3-H": "#FAD7A0",
}

P1_ZONES: dict[str, list[Point]] = {
    **_SHARED,
    "T3": [(0, -3), (24.3, -30), (23.5, -32.4), (1, -32.4), (-6, -4)],
    "T2": [(-6, -4), (1, -32.4), (-22.5, -32.4)],
    "T1": [(-6, -4), (-22.5, -32.4), (-23.5, -32.4), (-35, 3.1), (0, 1.5), (0, -3)],
}

P2_ZONES: dict[str, list[Point]] = {
    **_SHARED,
    "O": [(-3.5, -3), (-11, -8), (-21.5, -32.4), (-23.5, -32.4), (-35, 3.1),
          (0, 1.5), (0, -3)],
    "C": [(-3.5, -3), (2.5, -32.4), (-21.5, -32.4), (-11, -8)],
    "T3-H": [(0, -3), (24.3, -30), (23.5, -32.4), (2.5, -32.4), (-3.5, -3)],
}

# PD is a narrow sliver carved out of S and must be tested before it.
_TEST_ORDER_1 = ["PD", "S", "D1", "D2", "T3", "T2", "T1"]
_TEST_ORDER_2 = ["PD", "S", "D1", "D2", "O", "C", "T3-H"]


def calc_percentages(h2: float, ch4: float, c2h6: float, c2h4: float,
                     c2h2: float) -> dict[str, float] | None:
    """Each gas as a percentage of the five-gas sum. None when nothing to plot."""
    values = {"H2": h2 or 0.0, "CH4": ch4 or 0.0, "C2H6": c2h6 or 0.0,
              "C2H4": c2h4 or 0.0, "C2H2": c2h2 or 0.0}
    total = sum(values.values())
    if total <= 0:
        return None
    return {g: v / total * 100.0 for g, v in values.items()}


def gas_points(pct: dict[str, float]) -> list[Point]:
    """The five gas coordinates, ordered by GAS_ORDER."""
    points: list[Point] = []
    for gas in GAS_ORDER:
        r = pct.get(gas, 0.0) / 100.0 * R
        theta = math.radians(GAS_ANGLE[gas])
        points.append((r * math.cos(theta), r * math.sin(theta)))
    return points


def polygon_centroid(points: Sequence[Point]) -> Point:
    """Area centroid by the shoelace formula.

    The signed area comes out negative under the clockwise traversal used here;
    the sign cancels in Cx/Cy, so it must not be made absolute first. Falls back
    to the arithmetic mean when the polygon degenerates to a line or a point.
    """
    n = len(points)
    if n == 0:
        return (0.0, 0.0)
    a2 = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x_i, y_i = points[i]
        x_j, y_j = points[(i + 1) % n]
        cross = x_i * y_j - x_j * y_i
        a2 += cross
        cx += (x_i + x_j) * cross
        cy += (y_i + y_j) * cross
    area = a2 / 2.0
    if abs(area) < 1e-12:
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    return (cx / (6.0 * area), cy / (6.0 * area))


def point_in_polygon(px: float, py: float, poly: Sequence[Point]) -> bool:
    """Standard ray-casting containment test."""
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


def diagnose(cx: float, cy: float, zones: dict[str, list[Point]],
             order: Iterable[str]) -> str | None:
    """Name the zone containing the centroid, honouring the test order."""
    for name in order:
        poly = zones.get(name)
        if poly and point_in_polygon(cx, cy, poly):
            return name
    return None


def vertices() -> list[dict[str, Any]]:
    """Outer pentagon vertices with their label placement."""
    out = []
    for gas in GAS_ORDER:
        theta = math.radians(GAS_ANGLE[gas])
        x, y = R * math.cos(theta), R * math.sin(theta)
        dx, dy, anchor, baseline = LABEL_OFFSET[gas]
        out.append({
            "gas": gas, "label": GAS_LABEL[gas], "x": round(x, 4), "y": round(y, 4),
            "labelX": round(x + dx, 4), "labelY": round(y + dy, 4),
            "anchor": anchor, "baseline": baseline,
        })
    return out


def _zone_payload(zones: dict[str, list[Point]], order: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in order:
        poly = zones[name]
        lx, ly = polygon_centroid(poly)
        out.append({
            "zone": name,
            "meaning": ZONE_MEANING.get(name, ""),
            "color": ZONE_COLORS.get(name, "#E2E8F0"),
            "points": [[float(x), float(y)] for x, y in poly],
            "labelX": round(lx, 3),
            "labelY": round(ly, 3),
            # The PD sliver is too narrow for a full-size label.
            "labelSize": 7 if name == "PD" else 10,
        })
    return out


def geometry() -> dict[str, Any]:
    """Static drawing data - zones, vertices, view box. Cached by the client."""
    return {
        "radius": R,
        "gasOrder": GAS_ORDER,
        "vertices": vertices(),
        "viewBox": {"xMin": -54, "xMax": 54, "yMin": -44, "yMax": 52},
        "pentagon1": {"title": "Duval Pentagon 1",
                      "subtitle": "Electrical vs. thermal faults",
                      "zones": _zone_payload(P1_ZONES, _TEST_ORDER_1)},
        "pentagon2": {"title": "Duval Pentagon 2",
                      "subtitle": "Sub-types of thermal / paper faults",
                      "zones": _zone_payload(P2_ZONES, _TEST_ORDER_2)},
        "zoneMeanings": ZONE_MEANING,
    }


def analyse(h2: float, ch4: float, c2h6: float, c2h4: float, c2h2: float,
            asset: str | None = None, sample_date: str | None = None) -> dict[str, Any]:
    """Full dual-pentagon result for one gas sample."""
    pct = calc_percentages(h2, ch4, c2h6, c2h4, c2h2)
    if pct is None:
        return {
            "asset": asset, "sampleDate": sample_date, "valid": False,
            "reason": "All five pentagon gases are zero - nothing to plot.",
            "percentages": None, "points": None, "centroid": None,
            "pentagon1": None, "pentagon2": None,
        }

    points = gas_points(pct)
    cx, cy = polygon_centroid(points)
    z1 = diagnose(cx, cy, P1_ZONES, _TEST_ORDER_1)
    z2 = diagnose(cx, cy, P2_ZONES, _TEST_ORDER_2)

    return {
        "asset": asset,
        "sampleDate": sample_date,
        "valid": True,
        "gases": {"H2": h2, "CH4": ch4, "C2H6": c2h6, "C2H4": c2h4, "C2H2": c2h2},
        "percentages": {g: round(v, 1) for g, v in pct.items()},
        "points": [{"gas": g, "x": round(x, 4), "y": round(y, 4),
                    "percent": round(pct[g], 1)}
                   for g, (x, y) in zip(GAS_ORDER, points)],
        "centroid": {"x": round(cx, 2), "y": round(cy, 2)},
        "pentagon1": {"zone": z1, "meaning": ZONE_MEANING.get(z1 or "", ""),
                      "color": ZONE_COLORS.get(z1 or "", "#E2E8F0")},
        "pentagon2": {"zone": z2, "meaning": ZONE_MEANING.get(z2 or "", ""),
                      "color": ZONE_COLORS.get(z2 or "", "#E2E8F0")},
    }
