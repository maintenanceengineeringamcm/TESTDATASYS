from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

import db

TREND_GASES = ["H2", "CH4", "CO", "CO2", "C2H4", "C2H6", "C2H2"]

GAS_COLUMN = {
    "H2": "H2ppm", "CH4": "CH4ppm", "CO": "COppm", "CO2": "CO2ppm",
    "C2H4": "C2H4ppm", "C2H6": "C2H6ppm", "C2H2": "C2H2ppm",
    "O2": "O2ppm", "N2": "N2ppm",
}

# Table 3 - allowable difference between consecutive samples (ppm)
TABLE3_LIMIT = {"H2": 40, "CH4": 30, "CO": 250, "CO2": 2500,
                "C2H4": 20, "C2H6": 25, "C2H2": 0}

# Table 4 - allowable rate of change (ppm/year), interval 120-270 days
TABLE4_SHORT = {"H2": 50, "CH4": 15, "CO": 200, "CO2": 1750,
                "C2H4": 10, "C2H6": 15, "C2H2": 0}

# Table 4 - allowable rate of change (ppm/year), interval 271-720 days
TABLE4_LONG = {"H2": 20, "CH4": 10, "CO": 100, "CO2": 1000,
               "C2H4": 7, "C2H6": 9, "C2H2": 0}

# Relative importance in the weighted average (total 18). Acetylene, the arcing
# gas, carries the heaviest weight and has limits of zero, so any increase in it
# scores zero on both tables.
GAS_WEIGHT = {"H2": 2, "CH4": 3, "CO": 1, "CO2": 1,
              "C2H4": 3, "C2H6": 3, "C2H2": 5}

MIN_DAYS_FOR_RATE = 120
T4_SHORT_MAX = 270
T4_LONG_MAX = 720

CONDITION_BANDS = [
    (0.875, "Very Good", "#0E9F6E"),
    (0.625, "Good", "#2E7DD1"),
    (0.375, "Acceptable", "#B7791F"),
    (0.125, "Poor", "#DD6B20"),
    (0.000, "Very Poor", "#D64545"),
]


def condition_label(score: float | None) -> tuple[str, str]:
    if score is None:
        return "Not scored", "#94A3B8"
    for threshold, label, color in CONDITION_BANDS:
        if score >= threshold:
            return label, color
    return "Very Poor", "#D64545"


def least_squares_slope(xs: list[float], ys: list[float]) -> float | None:
    """Excel SLOPE(): None when fewer than 2 points or all x are identical."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


@dataclass
class SampleRow:
    """One row of the per-gas audit trail - mirrors the source workbook."""
    sampleNo: int
    date: str
    daysFromFirst: int
    periodDays: int | None
    value: float
    difference: float | None
    table3Limit: float
    rate: float | None
    table4Limit: float | None
    score1: float | None
    score2: float | None


@dataclass
class GasTrend:
    gas: str
    weight: int
    subScore: float | None
    score1: float | None
    score2: float | None
    latest: float | None
    previous: float | None
    difference: float | None
    rate: float | None
    table3Limit: float
    table4Limit: float | None
    note: str
    rows: list[SampleRow] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gas": self.gas, "weight": self.weight, "subScore": self.subScore,
            "score1": self.score1, "score2": self.score2, "latest": self.latest,
            "previous": self.previous, "difference": self.difference,
            "rate": self.rate, "table3Limit": self.table3Limit,
            "table4Limit": self.table4Limit, "note": self.note,
            "rows": [r.__dict__ for r in self.rows],
        }


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def score_gas(gas: str, dates: list[datetime], values: list[float]) -> GasTrend:
    """Score one gas over its own non-null subsequence."""
    weight = GAS_WEIGHT[gas]
    limit3 = TABLE3_LIMIT[gas]

    if not dates:
        return GasTrend(gas, weight, None, None, None, None, None, None, None,
                        limit3, None, "column not available")
    if len(dates) < 2:
        return GasTrend(gas, weight, None, None, None, values[0] if values else None,
                        None, None, None, limit3, None, "only one reading")

    base = dates[0]
    days = [(d - base).days for d in dates]
    rows: list[SampleRow] = []
    last_rate = None
    last_limit4 = None

    for i in range(len(dates)):
        # Period governing the Table 4 band: the span of the last three samples
        # once the record is long enough, otherwise the span from the first.
        if days[i] < MIN_DAYS_FOR_RATE or i < 2:
            period = days[i]
        else:
            period = days[i] - days[i - 2]

        difference = None if i == 0 else values[i] - values[i - 1]

        if i == 0 or days[i] < MIN_DAYS_FOR_RATE:
            rate = None
        else:
            lo = max(0, i - 2)
            slope = least_squares_slope(
                [float(d) for d in days[lo:i + 1]], values[lo:i + 1]
            )
            rate = None if slope is None else slope * 365.0

        if period is None or period < MIN_DAYS_FOR_RATE:
            limit4 = None
        elif period <= T4_SHORT_MAX:
            limit4 = float(TABLE4_SHORT[gas])
        elif period <= T4_LONG_MAX:
            limit4 = float(TABLE4_LONG[gas])
        else:
            limit4 = None                 # interval beyond Table 4's range

        if difference is None:
            s1 = None
        elif difference <= 0:
            s1 = 1.0
        elif difference <= limit3:
            s1 = 0.5
        else:
            s1 = 0.0

        if rate is None or limit4 is None:
            s2 = None
        elif rate <= 0:
            s2 = 1.0
        elif rate <= limit4:
            s2 = 0.5
        else:
            s2 = 0.0

        rows.append(SampleRow(
            sampleNo=i + 1, date=dates[i].strftime("%Y-%m-%d"), daysFromFirst=days[i],
            periodDays=period, value=values[i], difference=difference,
            table3Limit=limit3, rate=rate, table4Limit=limit4, score1=s1, score2=s2,
        ))
        last_rate, last_limit4 = rate, limit4

    last = rows[-1]
    scores = [s for s in (last.score1, last.score2) if s is not None]
    sub = min(scores) if scores else None      # deliberately pessimistic

    if sub is None:
        note = "no comparable reading"
    elif last.score2 is None and last_rate is None:
        note = "Table 3 only - record spans < 120 days"
    elif last.score2 is None:
        note = "Table 3 only - sampling interval outside Table 4 range"
    else:
        note = ""

    return GasTrend(
        gas=gas, weight=weight, subScore=sub, score1=last.score1, score2=last.score2,
        latest=last.value, previous=values[-2] if len(values) > 1 else None,
        difference=last.difference, rate=last_rate, table3Limit=limit3,
        table4Limit=last_limit4, note=note, rows=rows,
    )


def compute_asset_trend(asset: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Score all seven gases for one asset and roll them up."""
    # Drop placeholder rows: a stub date with no trend-gas value at all.
    usable = [
        s for s in samples
        if _parse_date(s.get("DateSampled")) is not None
        and any(s.get(GAS_COLUMN[g]) is not None for g in TREND_GASES)
    ]
    usable.sort(key=lambda s: _parse_date(s["DateSampled"]))

    gas_results: list[GasTrend] = []
    for gas in TREND_GASES:
        col = GAS_COLUMN[gas]
        dates: list[datetime] = []
        values: list[float] = []
        for s in usable:
            v = s.get(col)
            if v is None:
                continue
            d = _parse_date(s.get("DateSampled"))
            if d is None:
                continue
            dates.append(d)
            values.append(float(v))
        gas_results.append(score_gas(gas, dates, values))

    scored = [g for g in gas_results if g.subScore is not None]
    numerator = sum(g.subScore * g.weight for g in scored)
    denominator = sum(g.weight for g in scored)
    trend = numerator / denominator if denominator else None
    label, color = condition_label(trend)

    excluded = [g.gas for g in gas_results if g.subScore is None]
    if trend is None:
        message = ("Not enough history to score - at least two samples with gas "
                   "readings are needed.")
    elif excluded:
        message = (f"Scored on {', '.join(g.gas for g in scored)}. "
                   f"No usable reading for {', '.join(excluded)} - "
                   "excluded from the weighted average.")
    else:
        message = "Scored on all seven gases."

    first = usable[0]["DateSampled"] if usable else None
    latest = usable[-1]["DateSampled"] if usable else None

    return {
        "asset": asset,
        "trend": trend,
        "condition": label,
        "conditionColor": color,
        "samples": len(usable),
        "firstSample": first,
        "latestSample": latest,
        "denominator": denominator,
        "excludedGases": excluded,
        "message": message,
        "gases": [g.as_dict() for g in gas_results],
    }


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------
def fetch_samples(assets: list[str], date_from: str = "1900-01-01",
                  date_to: str = "2999-12-31") -> dict[str, list[dict[str, Any]]]:
    """Fetch DGA samples for a set of assets, grouped by asset."""
    if not assets:
        return {}
    cleaned = [a.strip() for a in assets if a and a.strip()]
    if not cleaned:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {a: [] for a in cleaned}

    # Chunked so the parameter count stays well inside SQL Server's 2100 limit.
    CHUNK = 400
    for start in range(0, len(cleaned), CHUNK):
        batch = cleaned[start:start + CHUNK]
        placeholders = ", ".join("?" * len(batch))
        rows = db.query(
            "SELECT LTRIM(RTRIM(AssetNumber)) AS AssetNumber, DateSampled, "
            "       H2ppm, CH4ppm, COppm, CO2ppm, C2H4ppm, C2H6ppm, C2H2ppm, O2ppm, N2ppm "
            "FROM CEB_DGA_DATA "
            f"WHERE LTRIM(RTRIM(AssetNumber)) IN ({placeholders}) "
            "  AND DateSampled >= ? AND DateSampled <= ? "
            "ORDER BY AssetNumber, DateSampled",
            (*batch, date_from, date_to),
        )
        for r in rows:
            grouped.setdefault(r["AssetNumber"], []).append(r)
    return grouped


def dga_assets() -> list[dict[str, Any]]:
    """Assets that have DGA history, with record counts and date span."""
    return db.cached("dga:assets", lambda: db.query(
        "SELECT LTRIM(RTRIM(AssetNumber)) AS assetNumber, COUNT(*) AS records, "
        "       CONVERT(varchar, MIN(DateSampled), 23) AS earliest, "
        "       CONVERT(varchar, MAX(DateSampled), 23) AS latest "
        "FROM CEB_DGA_DATA WHERE AssetNumber IS NOT NULL "
        "GROUP BY LTRIM(RTRIM(AssetNumber)) ORDER BY AssetNumber"
    ))


def asset_trend(asset: str, date_from: str = "1900-01-01",
                date_to: str = "2999-12-31") -> dict[str, Any]:
    samples = fetch_samples([asset], date_from, date_to).get(asset.strip(), [])
    return compute_asset_trend(asset.strip(), samples)


def fleet_trend(assets: list[str], date_from: str = "1900-01-01",
                date_to: str = "2999-12-31") -> list[dict[str, Any]]:
    """One entry per asset, worst first, unscored assets last."""
    grouped = fetch_samples(assets, date_from, date_to)
    results = [compute_asset_trend(a, grouped.get(a, [])) for a in grouped]
    results.sort(key=lambda r: (r["trend"] is None, r["trend"] if r["trend"] is not None else 0))
    return results


def series(asset: str, gases: Iterable[str], date_from: str = "1900-01-01",
           date_to: str = "2999-12-31") -> dict[str, Any]:
    """Chart-ready time series for the requested gases."""
    samples = fetch_samples([asset], date_from, date_to).get(asset.strip(), [])
    wanted = [g for g in gases if g in GAS_COLUMN]
    points = []
    for s in samples:
        d = _parse_date(s.get("DateSampled"))
        if d is None:
            continue
        entry: dict[str, Any] = {"date": d.strftime("%Y-%m-%d")}
        has_any = False
        for g in wanted:
            v = s.get(GAS_COLUMN[g])
            entry[g] = None if v is None else float(v)
            has_any = has_any or v is not None
        if has_any:
            points.append(entry)
    return {"asset": asset, "gases": wanted, "points": points}
