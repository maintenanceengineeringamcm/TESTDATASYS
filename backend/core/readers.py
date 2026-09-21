"""Per-component measurement readers.

Every reader answers one question: *what single number feeds this component's
range lookup, and when was it measured?* Each returns a :class:`Reading` or
``None`` when the asset has no qualifying record, in which case the component is
excluded from weight normalisation rather than scored zero.

Column names here are the live schema's, which differ in case and spelling from
the automation spec in several places (``PhaARatioDev`` not ``PhaAratioDev``,
``PhaARCorrO`` not ``PhaArCorro``, ``PhaAIOutA`` not ``PhaAiOuta``,
``BDVOfOilkV`` not ``BdvOfOilkv``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Sequence

import db
from config import Config
from core import attributes
from core.assets import OLTC_SEGMENT

log = logging.getLogger(__name__)

OPEN_FROM = "1900-01-01"
OPEN_TO = "2999-12-31"


@dataclass
class Candidate:
    """One measurement that was in the running for a component's value.

    Several tests can record the same quantity - oil BDV lives in both
    CEB_OBV_TMT and CEB_MT_IBT, for instance - and a single test can report one
    figure per phase or per tap. Every one of them is carried through so the UI
    can show the full set and highlight which was actually used.
    """
    label: str                        # e.g. "BDVOfOilkV" or "R phase"
    value: float
    date: str | None = None
    source: str | None = None
    used: bool = False
    reason: str = ""                  # why this one won, or why it lost

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "value": self.value, "date": self.date,
                "source": self.source, "used": self.used, "reason": self.reason}


@dataclass
class Reading:
    value: float
    date: str | None
    source: str                       # table the value came from
    detail: dict[str, Any] = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)
    rule: str = ""                    # how the value was picked from the candidates
    # 'single' - one measurement; 'pick' - one of several was chosen, and the
    # chosen one is highlighted; 'blend' - all of them combine into the value,
    # so highlighting any single one would be misleading.
    mode: str = "single"

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "date": self.date, "source": self.source,
                "detail": self.detail, "rule": self.rule, "mode": self.mode,
                "candidates": [c.as_dict() for c in self.candidates]}

    def mark_used(self) -> "Reading":
        """Flag the candidate matching this reading's value and source."""
        for c in self.candidates:
            c.used = (c.value == self.value and (c.source is None or c.source == self.source))
        if not any(c.used for c in self.candidates):
            for c in self.candidates:
                if c.value == self.value:
                    c.used = True
                    break
        return self


def _f(row: dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mins(row: dict[str, Any], keys: Sequence[str]) -> float | None:
    vals = [v for v in (_f(row, k) for k in keys) if v is not None]
    return min(vals) if vals else None


def _maxs(row: dict[str, Any], keys: Sequence[str]) -> float | None:
    vals = [v for v in (_f(row, k) for k in keys) if v is not None]
    return max(vals) if vals else None


def newest_row(
    table: str,
    asset: str,
    columns: Sequence[str],
    date_col: str = "DateTested",
    date_from: str = OPEN_FROM,
    date_to: str = OPEN_TO,
    require: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Newest record for one asset inside a date window that carries a value.

    Only rows where at least one `require` column is filled qualify (default:
    every column asked for). Multi-test tables such as CEB_MT_IBT often have a
    newer row with moisture filled but BDV empty; without this filter that row
    would win and hide an older, real BDV. Each reader asks for its own value,
    so the fallback to older rows happens per value, never for the whole row.

    Asset numbers are compared trimmed on both sides - the live data carries
    stray whitespace.
    """
    cols = ", ".join(columns)
    has_value = " OR ".join(f"{c} IS NOT NULL" for c in (require or columns))
    sql = (
        f"SELECT TOP 1 {cols}, {date_col} AS _d FROM {table} "
        f"WHERE LTRIM(RTRIM(AssetNumber)) = ? AND {date_col} IS NOT NULL "
        f"  AND {date_col} >= ? AND {date_col} <= ? AND ({has_value}) "
        f"ORDER BY {date_col} DESC"
    )
    try:
        return db.query_one(sql, (asset.strip(), date_from, date_to))
    except db.DatabaseError as exc:
        log.warning("read failed on %s for %s: %s", table, asset, exc)
        return None


def _pick_newest(*readings: Reading | None) -> Reading | None:
    """Two-source 'newest wins' helper used by IR / BDV / MIO components.

    Both sources' values survive on the winner as candidates, so the UI can show
    "40.0, 32.0" and highlight the one that was actually scored.
    """
    present = [r for r in readings if r is not None]
    if not present:
        return None
    winner = max(present, key=lambda r: r.date or "")

    pooled: list[Candidate] = []
    for r in present:
        if r.candidates:
            pooled.extend(r.candidates)
        else:
            pooled.append(Candidate(label=r.source or "value", value=r.value,
                                    date=r.date, source=r.source))
    for c in pooled:
        c.used = c.source == winner.source and c.value == winner.value
        if not c.used and c.source != winner.source:
            c.reason = "superseded - other source tested more recently"

    winner.candidates = pooled
    if len(present) > 1:
        winner.mode = "pick"
        winner.rule = ("newest test wins across "
                       f"{len(present)} sources ({winner.source}, "
                       f"tested {str(winner.date or '')[:10]})")
    return winner


def _spread(label_values: list[tuple[str, float | None]], mode: str,
            date: str | None, source: str) -> Reading | None:
    """Reduce several same-test readings (phases, taps, windings) to one value.

    `mode` is 'max' for worse-is-higher quantities (contact resistance, tan
    delta) or 'min' for worse-is-lower ones (insulation resistance).
    """
    pairs = [(lab, v) for lab, v in label_values if v is not None]
    if not pairs:
        return None
    chosen = max(pairs, key=lambda p: p[1]) if mode == "max" else min(pairs, key=lambda p: p[1])
    cands = [Candidate(label=lab, value=v, date=date, source=source,
                       used=(lab == chosen[0] and v == chosen[1]))
             for lab, v in pairs]
    return Reading(value=chosen[1], date=date, source=source, candidates=cands,
                   mode="pick" if len(pairs) > 1 else "single",
                   rule=f"{'worst (max)' if mode == 'max' else 'lowest (min)'} of "
                        f"{len(pairs)} readings")


# ==========================================================================
# Omicron path: JOB -> EXECUTED_TEST -> <test table> -> <test data table>
# ==========================================================================
def newest_job_test(asset: str, test_name: str, date_from: str = OPEN_FROM,
                    date_to: str = OPEN_TO) -> dict[str, Any] | None:
    """Find the most recent executed Omicron test of a given name for an asset.

    `EXECUTED_TEST.Name` carries a bracketed sequence prefix in the live data
    (e.g. "(2) Turns Ratio Prim-Sec"), so the match is a contains-match.
    """
    sql = (
        "SELECT TOP 1 j.ID AS JobId, e.ID AS TestId, e.Name, e.DateTime AS _d "
        "FROM JOB j JOIN EXECUTED_TEST e ON e.Job = j.ID "
        "WHERE LTRIM(RTRIM(j.Asset)) = ? AND e.Name LIKE ? "
        "  AND e.DateTime IS NOT NULL AND e.DateTime >= ? AND e.DateTime <= ? "
        "ORDER BY e.DateTime DESC"
    )
    try:
        return db.query_one(sql, (asset.strip(), f"%{test_name}%", date_from, date_to))
    except db.DatabaseError as exc:
        log.warning("job lookup failed for %s/%s: %s", asset, test_name, exc)
        return None


def _job_rows(table: str, job_id: int, columns: str, data_table: str | None = None,
              data_columns: str | None = None) -> list[dict[str, Any]]:
    """Fetch a test's header rows, optionally joined to its data rows."""
    try:
        if data_table:
            sql = (
                f"SELECT {data_columns} FROM {data_table} d "
                f"JOIN {table} t ON d.Parent = t.ID WHERE t.Job = ?"
            )
        else:
            sql = f"SELECT {columns} FROM {table} WHERE Job = ?"
        return db.query(sql, (job_id,))
    except db.DatabaseError as exc:
        log.warning("job rows failed on %s: %s", table, exc)
        return []


# ==========================================================================
# AGE
# ==========================================================================
def read_age(asset: str, manual_age: float | None = None, **_: Any) -> Reading | None:
    """Asset age in years, counted from the year of manufacture.

    Sources, in the order they are preferred:

    1. **The age the engineer typed on this calculation.** Always wins.
    2. **The Tomms CMMS** - `ast_det.ast_det_datetime1`, "Year of Manufacture(G)",
       read by :mod:`core.attributes` using the method in
       `ASSET_ATTRIBUTES_INTEGRATION.md`. This is the asset register of record
       and covers 9,065 of the 13,109 scored assets.
    3. `CEB_ASSET.ManufacturedYear` - the HI database's own asset table, empty
       today but the natural home for the value if it is ever populated.
    4. `SFRA_HEADER.ManufactureYear` - a year typed into an SFRA test header.
       165 assets, and it disagrees with the CMMS on 15 of the 157 it shares
       with it, so it ranks last: it is one engineer's note on a test file,
       not the register.

    Every source that had something to say is returned as a candidate with the
    reason it lost, so the workbench can show the disagreement rather than hide
    it. Where no source has a usable year, AGE is unavailable and is dropped
    from weight normalisation rather than scored zero.
    """
    asset = (asset or "").strip()
    candidates: list[Candidate] = []
    picked: tuple[float, int, str, dict[str, Any], str] | None = None

    # 1. the CMMS - the register of record
    found = attributes.manufacture_year(asset)
    if found and found.get("age") is not None:
        year = int(found["year"])
        inherited = found.get("inheritedFrom")
        label = (f"{found['label']} from the CMMS ({year})" if not inherited
                 else f"{found['label']} from the CMMS ({year}), via {inherited}")
        source = f"Tomms_CEBT.{found['column']}"
        candidates.append(Candidate(label=label, value=float(found["age"]),
                                    date=f"{year}-01-01", source=source))
        detail: dict[str, Any] = {
            "manufactureYear": year,
            "manufactureYearColumn": found["column"],
            "manufactureYearLabel": found["label"],
            "manufactureYearSource": found["source"],
        }
        if inherited:
            detail["inheritedFrom"] = inherited
        picked = (float(found["age"]), year, source, detail,
                  "year of manufacture from the Tomms CMMS asset register")

    # 2. CEB_ASSET, then 3. SFRA_HEADER - both fall back on the same shape
    for sql, params, source in (
        ("SELECT TOP 1 ManufacturedYear AS y FROM CEB_ASSET "
         "WHERE LTRIM(RTRIM(AssetNumber)) = ? AND ManufacturedYear > 1900 "
         "ORDER BY ID DESC", (asset,), "CEB_ASSET"),
        ("SELECT TOP 1 ManufactureYear AS y FROM SFRA_HEADER "
         "WHERE LTRIM(RTRIM(Asset)) = ? AND ManufactureYear > 1900 "
         "ORDER BY TestDate DESC", (asset,), "SFRA_HEADER"),
    ):
        try:
            row = db.query_one(sql, params)
        except db.DatabaseError as exc:
            log.warning("age lookup failed on %s for %s: %s", source, asset, exc)
            continue
        year = attributes.usable_year(row.get("y")) if row else None
        if year is None:
            continue
        age = attributes.age_from_year(year)
        candidates.append(Candidate(label=f"from {source} ({year})", value=age,
                                    date=f"{year}-01-01", source=source))
        if picked is None:
            picked = (age, year, source, {"manufactureYear": year},
                      f"year of manufacture from {source}")

    if manual_age is not None:
        candidates.append(Candidate(label="entered manually", value=float(manual_age),
                                    source="manual entry", used=True))
        for c in candidates:
            if c.source != "manual entry":
                c.reason = "overridden by the age entered on this calculation"
        return Reading(value=float(manual_age), date=None, source="manual entry",
                       candidates=candidates, rule="engineer-entered age overrides the database",
                       mode="pick" if len(candidates) > 1 else "single",
                       detail={"manualAge": float(manual_age)})

    if picked is None:
        return None

    age, year, source, detail, rule = picked
    for c in candidates:
        if c.source != source:
            c.reason = (f"{source} ranks above {c.source} as a source for the "
                        "year of manufacture")
    reading = Reading(value=age, date=f"{year}-01-01", source=source,
                      candidates=candidates, rule=rule, detail=detail,
                      mode="pick" if len(candidates) > 1 else "single")
    return reading.mark_used()


# ==========================================================================
# TR (Power Transformer) components
# ==========================================================================
def read_furan(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    row = newest_row("CEB_TRANS_FURAN_DP", asset, ["FuranicComponentPpb", "DegreeOfPoly"],
                     "DateTested", date_from, date_to, require=["FuranicComponentPpb"])
    reading = _single(row, "FuranicComponentPpb", "CEB_TRANS_FURAN_DP")
    if reading and row:
        reading.detail = {"degreeOfPolymerisation": _f(row, "DegreeOfPoly")}
    return reading


DGA_GAS_FIELDS = {
    "H2": "H2ppm", "CH4": "CH4ppm", "CO": "COppm", "CO2": "CO2ppm",
    "C2H4": "C2H4ppm", "C2H6": "C2H6ppm", "C2H2": "C2H2ppm",
}


def read_dga_sample(asset: str, date_from: str = OPEN_FROM,
                    date_to: str = OPEN_TO) -> dict[str, Any] | None:
    """Newest DGA sample, as a gas dict plus its sampling date."""
    cols = list(DGA_GAS_FIELDS.values()) + ["O2ppm", "N2ppm"]
    row = newest_row("CEB_DGA_DATA", asset, cols, "DateSampled", date_from, date_to,
                     require=list(DGA_GAS_FIELDS.values()))
    if not row:
        return None
    gases = {g: _f(row, col) for g, col in DGA_GAS_FIELDS.items()}
    if all(v is None for v in gases.values()):
        return None
    gases["O2"] = _f(row, "O2ppm")
    gases["N2"] = _f(row, "N2ppm")
    return {"gases": gases, "date": row["_d"], "source": "CEB_DGA_DATA"}


def read_tand(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    """Winding dissipation factor: worst corrected tan-delta across the test."""
    job = newest_job_test(asset, "Winding DF & CAP", date_from, date_to)
    if not job:
        return None
    pairs: list[tuple[str, float | None]] = []
    for tbl, data_tbl, tag in (
        ("WINDING_TAND_CAP", "WINDING_TAND_CAP_MEASUREMENT_DATA", "meas"),
        ("WINDING_TAND_CAP", "WINDING_TAND_CAP_DATA", "data"),
    ):
        rows = _job_rows(tbl, job["JobId"], "", data_tbl, "d.TanDCorrPerc AS v")
        for i, r in enumerate(rows, start=1):
            pairs.append((f"{tag} {i}", _f(r, "v")))
    reading = _spread(pairs, "max", job["_d"], "WINDING_TAND_CAP")
    if reading:
        reading.detail = {"measurements": sum(1 for _, v in pairs if v is not None)}
    return reading


def read_dirana(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    return _single(newest_row("CEB_MIP", asset, ["MoistureContentOfInsulationPerc"],
                              "DateTested", date_from, date_to),
                   "MoistureContentOfInsulationPerc", "CEB_MIP")


def read_turns_ratio(asset: str, date_from: str = OPEN_FROM,
                     date_to: str = OPEN_TO) -> Reading | None:
    job = newest_job_test(asset, "Turns Ratio Prim-Sec", date_from, date_to)
    if not job:
        return None
    rows = _job_rows("TURNS_RATIO_PRIM_SEC", job["JobId"], "",
                     "TURNS_RATIO_PRIM_SEC_DATA",
                     "d.Tap AS tap, d.PhaARatioDev AS a, d.PhaBRatioDev AS b, "
                     "d.PhaCRatioDev AS c")
    pairs: list[tuple[str, float | None]] = []
    for r in rows:
        tap = r.get("tap")
        for phase, key in (("R", "a"), ("Y", "b"), ("B", "c")):
            v = _f(r, key)
            pairs.append((f"tap {tap} {phase}", abs(v) if v is not None else None))
    reading = _spread(pairs, "max", job["_d"], "TURNS_RATIO_PRIM_SEC")
    if reading:
        reading.detail = {"taps": len(rows)}
    return reading


def read_leakage_reactance(asset: str, date_from: str = OPEN_FROM,
                           date_to: str = OPEN_TO) -> Reading | None:
    job = newest_job_test(asset, "Short Circuit Impedance", date_from, date_to)
    if not job:
        return None
    rows = _job_rows("SHORT_CIRCUIT_IMPEDANCE_PRIM_SEC", job["JobId"], "",
                     "PHA_EQUIV_ASSESSMENT_ZK", "d.ZkDev AS v, d.Phase AS ph")
    pairs: list[tuple[str, float | None]] = []
    for i, r in enumerate(rows, start=1):
        v = _f(r, "v")
        label = str(r.get("ph") or f"phase {i}")
        pairs.append((label, abs(v) if v is not None else None))
    reading = _spread(pairs, "max", job["_d"], "SHORT_CIRCUIT_IMPEDANCE_PRIM_SEC")
    if reading:
        reading.detail = {"phases": sum(1 for _, v in pairs if v is not None)}
    return reading


def _winding_resistance_spread(rows: list[dict[str, Any]]) -> float | None:
    """Worst inter-phase relative deviation across every tap row.

    For each tap the six pairwise deviations are formed, each normalised by the
    phase it is referenced to, and the largest is kept.
    """
    worst: float | None = None
    for r in rows:
        a, b, c = _f(r, "a"), _f(r, "b"), _f(r, "c")
        if None in (a, b, c) or 0 in (a, b, c):
            continue
        devs = [
            abs(a - b) / a, abs(a - b) / b,
            abs(b - c) / b, abs(b - c) / c,
            abs(c - a) / c, abs(c - a) / a,
        ]
        row_max = max(devs)
        worst = row_max if worst is None else max(worst, row_max)
    return worst


def read_winding_resistance(asset: str, date_from: str = OPEN_FROM,
                            date_to: str = OPEN_TO) -> Reading | None:
    results: dict[str, float] = {}
    job_date = None
    for label, test, tbl, data_tbl in (
        ("primary", "DC Winding Resistance Prim", "DC_WINDING_RESISTANCE_PRIM",
         "DC_WINDING_RESISTANCE_PRIM_DATA"),
        ("secondary", "DC Winding Resistance Sec", "DC_WINDING_RESISTANCE_SEC",
         "DC_WINDING_RESISTANCE_SEC_DATA"),
    ):
        job = newest_job_test(asset, test, date_from, date_to)
        if not job:
            continue
        rows = _job_rows(tbl, job["JobId"], "", data_tbl,
                         "d.PhaARCorrO AS a, d.PhaBRCorrO AS b, d.PhaCRCorrO AS c")
        spread = _winding_resistance_spread(rows)
        if spread is not None:
            results[label] = spread
            job_date = max(job_date or "", job["_d"] or "")
    if not results:
        return None
    pairs = [(f"{k} winding", v * 100.0) for k, v in results.items()]
    reading = _spread(pairs, "max", job_date, "DC_WINDING_RESISTANCE")
    if reading:
        reading.detail = {k: round(v * 100, 4) for k, v in results.items()}
        reading.rule = ("worst inter-phase deviation across "
                        f"{len(pairs)} winding(s), as a percentage")
    return reading


def read_exciting_current(asset: str, date_from: str = OPEN_FROM,
                          date_to: str = OPEN_TO) -> Reading | None:
    """Worst phase-to-phase exciting-current deviation, as a percentage.

    The legacy banding condition mixed two separately computed deviations across
    the two range bounds with an OR, which cannot select a band deterministically
    (spec section 9 item 6). With `EC_BAND_ASCENDING` set - the default - the
    governing value is the larger of the two deviations and it is banded
    normally.
    """
    job = newest_job_test(asset, "Exciting Current", date_from, date_to)
    if not job:
        return None
    rows = _job_rows("EXCITING_CURRENT", job["JobId"], "", "EXCITING_CURRENT_DATA",
                     "d.Tap AS tap, d.PhaAIOutA AS a, d.PhaBIOutA AS b, d.PhaCIOutA AS c")
    pairs: list[tuple[str, float | None]] = []
    for i, r in enumerate(rows, start=1):
        a, b, c = _f(r, "a"), _f(r, "b"), _f(r, "c")
        if None in (a, b, c) or 0 in (a, b, c):
            continue
        diff1 = max(abs(a - b) / a, abs(b - c) / c)
        diff2 = max(abs(c - a) / c, abs(c - a) / a)
        chosen = max(diff1, diff2) if Config.EC_BAND_ASCENDING else diff1
        pairs.append((f"tap {r.get('tap') or i}", chosen * 100.0))
    reading = _spread(pairs, "max", job["_d"], "EXCITING_CURRENT")
    if reading:
        reading.detail = {"taps": len(rows)}
    return reading


_IR_POL_FIELDS = ["IRHVE1", "IRHVE10", "IRHVLV1", "IRHVLV10", "IRLVE1", "IRLVE10"]
_IR_MTIBT_FIELDS = ["InsulationResistanceHVToEGOhm", "InsulationResistanceLVToEGOhm",
                    "InsulationResistanceHVToLVGOhm"]


def read_tr_insulation_resistance(asset: str, date_from: str = OPEN_FROM,
                                  date_to: str = OPEN_TO) -> Reading | None:
    """Lowest insulation resistance, newest of two possible test sources."""
    r1 = newest_row("CEB_TRANS_INS_RES_POL_INDX", asset,
                    _IR_POL_FIELDS + ["PolarityIndex"], "DateTested", date_from, date_to,
                    require=_IR_POL_FIELDS)
    a = None
    if r1:
        a = _spread([(f, _f(r1, f)) for f in _IR_POL_FIELDS], "min", r1["_d"],
                    "CEB_TRANS_INS_RES_POL_INDX")
        if a:
            a.detail = {"polarityIndex": _f(r1, "PolarityIndex")}

    r2 = newest_row("CEB_MT_IBT", asset, _IR_MTIBT_FIELDS, "DateTested", date_from, date_to)
    b = _spread([(f, _f(r2, f)) for f in _IR_MTIBT_FIELDS], "min", r2["_d"], "CEB_MT_IBT") \
        if r2 else None
    return _pick_newest(a, b)


def _single(row: dict[str, Any] | None, column: str, source: str) -> Reading | None:
    """A one-field reading, carrying itself as its own candidate."""
    if not row:
        return None
    value = _f(row, column)
    if value is None:
        return None
    return Reading(value=value, date=row["_d"], source=source,
                   candidates=[Candidate(label=column, value=value, date=row["_d"],
                                         source=source, used=True)])


def read_bdv_main(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    """Main-tank oil breakdown voltage - the worked example of the spec.

    Two tests record the same quantity, so take the newest record from each and
    keep whichever was tested more recently. Both figures are returned as
    candidates so the UI can show the full set with the used one highlighted.
    """
    a = _single(newest_row("CEB_OBV_TMT", asset, ["BDVOfOilkV"], "DateTested",
                           date_from, date_to), "BDVOfOilkV", "CEB_OBV_TMT")
    b = _single(newest_row("CEB_MT_IBT", asset, ["OilBreakdownVoltagekV"], "DateTested",
                           date_from, date_to), "OilBreakdownVoltagekV", "CEB_MT_IBT")
    return _pick_newest(a, b)


def read_bdv_oltc(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    a = _single(newest_row("CEB_OBV_OLTC", asset, ["BDVOfOilkV"], "DateTested",
                           date_from, date_to), "BDVOfOilkV", "CEB_OBV_OLTC")
    # The OLTC table keys on the transformer's OLTC asset number.
    oltc_asset = asset if "/OLTC" in asset.upper() else _oltc_number(asset)
    r2 = newest_row("CEB_OLTC", oltc_asset, ["OilBreakdownVoltagekV"], "DateTested",
                    date_from, date_to) if Config.OLTC_USES_CEB_OLTC else None
    b = _single(r2, "OilBreakdownVoltagekV", "CEB_OLTC")
    return _pick_newest(a, b)


def _oltc_number(asset: str) -> str:
    """Map a transformer asset number to its OLTC child number.

    Units with two tap changers number them OLTC1 / OLTC2; this returns the
    plain `/OLTC/` form, and the caller falls back to the dedicated OLTC oil
    tables when that finds nothing.
    """
    parts = asset.strip().split("/")
    if len(parts) >= 2 and not OLTC_SEGMENT.match(parts[-2].upper()):
        return "/".join(parts[:-1] + ["OLTC", parts[-1]])
    return asset.strip()


def read_moisture_main(asset: str, date_from: str = OPEN_FROM,
                       date_to: str = OPEN_TO) -> Reading | None:
    a = _single(newest_row("CEB_MCO_TMT", asset, ["MoistureContentOfOilPpm"],
                           "DateTested", date_from, date_to),
                "MoistureContentOfOilPpm", "CEB_MCO_TMT")
    b = _single(newest_row("CEB_MT_IBT", asset, ["MoistureContentOfOilppm"],
                           "DateTested", date_from, date_to),
                "MoistureContentOfOilppm", "CEB_MT_IBT")
    return _pick_newest(a, b)


def read_moisture_oltc(asset: str, date_from: str = OPEN_FROM,
                       date_to: str = OPEN_TO) -> Reading | None:
    a = _single(newest_row("CEB_MCO_OLTC", asset, ["MoistureContentOfOilPpm"],
                           "DateTested", date_from, date_to),
                "MoistureContentOfOilPpm", "CEB_MCO_OLTC")
    oltc_asset = asset if "/OLTC" in asset.upper() else _oltc_number(asset)
    r2 = newest_row("CEB_OLTC", oltc_asset, ["MoistureContentOfOilppm"], "DateTested",
                    date_from, date_to) if Config.OLTC_USES_CEB_OLTC else None
    return _pick_newest(a, _single(r2, "MoistureContentOfOilppm", "CEB_OLTC"))


def read_acidity(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    """Acidity reads TRANS_ACIDITY.AcidityInOil.

    The legacy code had acidity and interfacial tension pointing at each other's
    table (spec section 9 item 3); `AIO_IFTO_UNCROSSED` restores the crossed
    behaviour if it ever needs reproducing.
    """
    table, column = ("CEB_TRANS_ACIDITY", "AcidityInOil") if Config.AIO_IFTO_UNCROSSED \
        else ("CEB_TRANS_ITO", "ITOIFT")
    return _single(newest_row(table, asset, [column], "DateTested", date_from, date_to),
                   column, table)


def read_ift(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    table, column = ("CEB_TRANS_ITO", "ITOIFT") if Config.AIO_IFTO_UNCROSSED \
        else ("CEB_TRANS_ACIDITY", "AcidityInOil")
    return _single(newest_row(table, asset, [column], "DateTested", date_from, date_to),
                   column, table)


# ==========================================================================
# CTVT
# ==========================================================================
def read_ctvt_tand(asset: str, date_from: str = OPEN_FROM,
                   date_to: str = OPEN_TO) -> Reading | None:
    is_vt = "/VT" in asset.upper() or "/CVT" in asset.upper()
    test, tbl, data_tbl = ("TanDelta - CP TD", "TAN_DELTA_VT",
                           "TAN_DELTA_VT_MEASUREMENT_DATA") if is_vt else \
                          ("CT DF & CAP", "TAN_DELTA_CT", "TAN_DELTA_CT_MEASUREMENT_DATA")
    job = newest_job_test(asset, test, date_from, date_to)
    if not job:
        return None
    rows = _job_rows(tbl, job["JobId"], "", data_tbl, "d.TanDCorrPerc AS v")
    pairs = [(f"meas {i}", _f(r, "v")) for i, r in enumerate(rows, start=1)]
    reading = _spread(pairs, "max", job["_d"], tbl)
    if reading:
        reading.detail = {"measurements": sum(1 for _, v in pairs if v is not None)}
    return reading


def read_ctvt_ir(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    upper = asset.upper()
    if "/VT" in upper or "/CVT" in upper:
        keys = _IR_MTIBT_FIELDS
        row = newest_row("CEB_OUT_VT", asset, keys, "DateTested", date_from, date_to)
        if not row:
            return None
        return _spread([(k, _f(row, k)) for k in keys], "min", row["_d"], "CEB_OUT_VT")
    return _single(newest_row("CEB_OUT_CT", asset, ["InsulationResistanceHVToEGOhm"],
                              "DateTested", date_from, date_to),
                   "InsulationResistanceHVToEGOhm", "CEB_OUT_CT")


# ==========================================================================
# CB
# ==========================================================================
_CB3_IR = ["TopToEarthRPhaGOhm", "TopToEarthYPhaseGOhm", "TopToEarthBPhaseGOhm",
           "BottomToEarthRPhaseGOhm", "BottomToEarthYPhaseGOhm", "BottomToEarthBPhaseGOhm",
           "TopToBottomRPhaseGOhm", "TopToBottomYPhaseGOhm", "TopToBottomBPhaseGOhm"]
_CB3_CR = ["RPhaseUOhm", "YPhaseUOhm", "BPhaseUOhm"]


_CB1_IR = ["TopToEarthGOhm", "BottomToEarthGOhm", "TopToBottomGcOhm"]
_CB1_CR = ["ContactResistanceUOhm"]
_CB_OPS = ["OperationCounterReadings"]


def _cb_row(asset: str, date_from: str, date_to: str, keys_3ph: list[str],
            keys_1ph: list[str]) -> tuple[str, dict[str, Any], list[str]] | None:
    """Newest CB row carrying *this component's* value.

    Prefers the three-phase table and falls back to the single-phase one. Each
    component asks for its own columns, so a newer test that filled in contact
    resistance but not IR does not hide an older IR reading.
    """
    r3 = newest_row("CEB_OUT_3PH_CB", asset, keys_3ph, "DateTested", date_from, date_to)
    if r3:
        return "CEB_OUT_3PH_CB", r3, keys_3ph
    r1 = newest_row("CEB_OUT_1PH_CB", asset, keys_1ph, "DateTested", date_from, date_to)
    if r1:
        return "CEB_OUT_1PH_CB", r1, keys_1ph
    return None


def read_cb_operations(asset: str, date_from: str = OPEN_FROM,
                       date_to: str = OPEN_TO) -> Reading | None:
    found = _cb_row(asset, date_from, date_to, _CB_OPS, _CB_OPS)
    if not found:
        return None
    table, row, _ = found
    return _single(row, "OperationCounterReadings", table)


def read_cb_contact_resistance(asset: str, date_from: str = OPEN_FROM,
                               date_to: str = OPEN_TO) -> Reading | None:
    found = _cb_row(asset, date_from, date_to, _CB3_CR, _CB1_CR)
    if not found:
        return None
    table, row, keys = found
    return _spread([(k, _f(row, k)) for k in keys], "max", row["_d"], table)


def read_cb_ir(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    found = _cb_row(asset, date_from, date_to, _CB3_IR, _CB1_IR)
    if not found:
        return None
    table, row, keys = found
    return _spread([(k, _f(row, k)) for k in keys], "min", row["_d"], table)


def read_cb_sf6_dewpoint(asset: str, date_from: str = OPEN_FROM,
                         date_to: str = OPEN_TO) -> Reading | None:
    row = newest_row("CEB_SF6_GAS", asset, ["DewPoint", "SF6GasPressure", "SF6GasPurityPerc"],
                     "DateTested", date_from, date_to, require=["DewPoint"])
    reading = _single(row, "DewPoint", "CEB_SF6_GAS")
    if reading and row:
        reading.detail = {"pressure": _f(row, "SF6GasPressure"),
                          "purityPerc": _f(row, "SF6GasPurityPerc")}
    return reading


# ==========================================================================
# ESDS / SA
# ==========================================================================
def read_esds_contact_resistance(asset: str, date_from: str = OPEN_FROM,
                                 date_to: str = OPEN_TO) -> Reading | None:
    keys = ["RPhaseUOhm", "YPhaseUOhm", "BPhaseUOhm"]
    row = newest_row("CEB_OUT_ESDS", asset, keys, "DateTested", date_from, date_to)
    if not row:
        return None
    return _spread([(k, _f(row, k)) for k in keys], "max", row["_d"], "CEB_OUT_ESDS")


def read_sa_counter(asset: str, date_from: str = OPEN_FROM,
                    date_to: str = OPEN_TO) -> Reading | None:
    return _single(newest_row("CEB_SA", asset, ["CounterReading"], "DateTested",
                              date_from, date_to), "CounterReading", "CEB_SA")


def read_sa_ir(asset: str, date_from: str = OPEN_FROM, date_to: str = OPEN_TO) -> Reading | None:
    """Surge-arrester insulation resistance.

    The legacy function read `CounterReading` here, identical to the CR
    component (spec section 9 item 4). The live schema does carry a genuine IR
    column, `InsulationResistanceHVEGOhm`, populated on ~63% of rows, so that is
    used by default.
    """
    column = "InsulationResistanceHVEGOhm" if Config.SA_IR_USES_IR_FIELD else "CounterReading"
    reading = _single(newest_row("CEB_SA", asset, [column], "DateTested", date_from, date_to),
                      column, "CEB_SA")
    if reading:
        reading.detail = {"column": column}
    return reading


# ==========================================================================
# Test-data availability report
# ==========================================================================
AVAILABILITY_TESTS: list[tuple[str, str, str, str]] = [
    ("TEST001", "DGA", "CEB_DGA_DATA", "DateSampled"),
    ("TEST011", "Oil BDV - Main Tank", "CEB_OBV_TMT", "DateTested"),
    ("TEST012", "Oil BDV - OLTC", "CEB_OBV_OLTC", "DateTested"),
    ("TEST013", "Moisture in Oil - Main Tank", "CEB_MCO_TMT", "DateTested"),
    ("TEST014", "Moisture in Oil - OLTC", "CEB_MCO_OLTC", "DateTested"),
    ("TEST015", "Insulation Resistance & PI", "CEB_TRANS_INS_RES_POL_INDX", "DateTested"),
    ("TEST016", "Furanic Level / DP", "CEB_TRANS_FURAN_DP", "DateTested"),
    ("TEST017", "Acidity in Oil", "CEB_TRANS_ACIDITY", "DateTested"),
    ("TEST018", "Interfacial Tension", "CEB_TRANS_ITO", "DateTested"),
    ("TEST019", "Moisture in Paper", "CEB_MIP", "DateTested"),
    ("TEST020", "Contact Resistance", "CEB_CONTACT_RES", "DateTested"),
    ("TEST025", "SF6 Gas", "CEB_SF6_GAS", "DateTested"),
    ("PRM004", "Power Transformer", "CEB_MT_IBT", "DateTested"),
    ("PRM010", "On-Load Tap Changer", "CEB_OLTC", "DateTested"),
    ("PRM002", "Current Transformer", "CEB_OUT_CT", "DateTested"),
    ("PRM007", "Voltage Transformer", "CEB_OUT_VT", "DateTested"),
    ("PRM006", "Surge Arrester", "CEB_SA", "DateTested"),
    ("PRM001", "Circuit Breaker 3-Phase", "CEB_OUT_3PH_CB", "DateTested"),
    ("PRM011", "Circuit Breaker 1-Phase", "CEB_OUT_1PH_CB", "DateTested"),
    ("PRM003", "ES / DS", "CEB_OUT_ESDS", "DateTested"),
]

AVAILABILITY_OMICRON: list[tuple[str, str]] = [
    ("OMI-TTR", "Turns Ratio Prim-Sec"),
    ("OMI-SCI", "Short Circuit Impedance"),
    ("OMI-DCWR", "DC Winding Resistance Prim"),
    ("OMI-EXC", "Exciting Current"),
    ("OMI-WTC", "Winding DF & CAP"),
    ("OMI-DIRANA", "DIRANA Test"),
    ("OMI-OLTC", "Dyn. OLTC"),
    ("OMI-DEMAG", "Demagnetization"),
]


def availability(asset: str, date_from: str = OPEN_FROM,
                 date_to: str = OPEN_TO) -> list[dict[str, Any]]:
    """Y/N (plus last date and row count) per test for one asset.

    The year of manufacture leads the list. It is not a test, but it is the
    input to a scored criterion and it is the one the engineer can do something
    about - a blank here is a row to fill in the CMMS, not a test to schedule.
    """
    year = attributes.manufacture_year(asset)
    out: list[dict[str, Any]] = [{
        "testId": "AGE",
        "name": "Year of manufacture (Tomms CMMS)",
        "table": f"Tomms_CEBT.{attributes.YEAR_COLUMN}",
        "available": year is not None,
        "records": 1 if year else 0,
        "lastTested": f"{year['year']}-01-01" if year else None,
    }]
    for test_id, name, table, date_col in AVAILABILITY_TESTS:
        try:
            row = db.query_one(
                f"SELECT COUNT(*) AS n, MAX({date_col}) AS last FROM {table} "
                f"WHERE LTRIM(RTRIM(AssetNumber)) = ? AND {date_col} >= ? AND {date_col} <= ?",
                (asset.strip(), date_from, date_to),
            ) or {}
        except db.DatabaseError:
            row = {}
        n = int(row.get("n") or 0)
        out.append({"testId": test_id, "name": name, "table": table,
                    "available": n > 0, "records": n, "lastTested": row.get("last")})

    for test_id, name in AVAILABILITY_OMICRON:
        try:
            row = db.query_one(
                "SELECT COUNT(*) AS n, MAX(e.DateTime) AS last FROM JOB j "
                "JOIN EXECUTED_TEST e ON e.Job = j.ID "
                "WHERE LTRIM(RTRIM(j.Asset)) = ? AND e.Name LIKE ? "
                "  AND e.DateTime >= ? AND e.DateTime <= ?",
                (asset.strip(), f"%{name}%", date_from, date_to),
            ) or {}
        except db.DatabaseError:
            row = {}
        n = int(row.get("n") or 0)
        out.append({"testId": test_id, "name": f"Omicron: {name}", "table": "EXECUTED_TEST",
                    "available": n > 0, "records": n, "lastTested": row.get("last")})
    return out
