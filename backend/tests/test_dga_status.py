"""Known-answer tests for the IEEE C57.104-2019 Figure 2 classifier.

Section 8 of `DGA_Status_Logic_C57104-2019.md` ships a test vector - the three
phases of Biyagama IBT 02 - with the status each must come out at and the
secondary delta assertions. If the tables or the decision are ever edited, this
is what catches it. No database: the samples are built in memory.
"""
from __future__ import annotations

import pytest

from core import dga_status as ds


def sample(date: str, **gases) -> dict:
    """One CEB_DGA_DATA-shaped row. Unnamed gases are absent, not zero."""
    row: dict = {"DateSampled": date}
    for gas, column in ds.GAS_COLUMN.items():
        row[column] = gases.get(gas)
    return row


# --------------------------------------------------------------------------
# Section 8 - the known-answer vector
# --------------------------------------------------------------------------
# o2_n2 is unmeasured (-> ">0.2" section) and the unit is 43 years old (-> ">30").
BIYAGAMA_AGE = 43

VECTOR = {
    "R": (dict(H2=87, CH4=0, C2H4=2, C2H6=0, C2H2=1),
          dict(H2=125, CH4=5, C2H4=3, C2H6=0, C2H2=2)),
    "Y": (dict(H2=53, CH4=8, C2H4=4, C2H6=52, C2H2=4),
          dict(H2=110, CH4=17, C2H4=4, C2H6=53, C2H2=5)),
    "B": (dict(H2=39, CH4=9, C2H4=4, C2H6=52, C2H2=3),
          dict(H2=84, CH4=20, C2H4=4, C2H6=53, C2H2=3)),
}


def classify_phase(phase: str):
    previous, latest = VECTOR[phase]
    return ds.classify([sample("2024-06-01", **previous),
                        sample("2024-12-01", **latest)],
                       age_years=BIYAGAMA_AGE, asset=f"IBT02-{phase}")


@pytest.mark.parametrize("phase", ["R", "Y", "B"])
def test_all_three_phases_are_status_3(phase):
    assert classify_phase(phase)["status"] == 3


def test_columns_selected():
    """No O2/N2 on record and a 43-year-old unit picks the >0.2 / >30 columns."""
    result = classify_phase("R")
    assert result["ratioBand"] == ">0.2"
    assert result["ageBand"] == ">30"
    assert any("O2/N2 was not measured" in a for a in result["assumptions"])


def test_r_phase_is_driven_by_hydrogen():
    """H2 125 is above the Table 2 (>0.2, >30) level of 90."""
    triggers = classify_phase("R")["triggeredBy"]
    top = [t for t in triggers if t["kind"] == "level>T2"]
    assert [t["gas"] for t in top] == ["H2"]
    assert top[0]["limit"] == 90


def test_y_phase_is_driven_by_hydrogen_and_ethane():
    over = [t["gas"] for t in classify_phase("Y")["triggeredBy"] if t["kind"] == "level>T2"]
    assert sorted(over) == ["C2H6", "H2"]


def test_b_phase_is_driven_by_ethane_alone():
    """H2 84 is under the 90 limit; C2H6 53 is over the 40 limit."""
    over = [t["gas"] for t in classify_phase("B")["triggeredBy"] if t["kind"] == "level>T2"]
    assert over == ["C2H6"]


@pytest.mark.parametrize("phase", ["R", "Y", "B"])
def test_two_samples_means_no_table_4(phase):
    result = classify_phase(phase)
    assert result["ratesAvailable"] is False
    assert all(g["rate"] is None for g in result["gases"])


@pytest.mark.parametrize("phase", ["R", "Y", "B"])
def test_delta_exceeds_table_3_for_every_phase(phase):
    """Every H2 delta clears the >0.2 Table 3 allowance of 25 ppm."""
    result = classify_phase(phase)
    by_gas = {g["gas"]: g for g in result["gases"]}
    assert by_gas["H2"]["exceedsT3"] is True
    assert any(g["exceedsT3"] for g in result["gases"])


def test_b_phase_methane_delta_also_trips():
    """CH4 +11 against the >0.2 allowance of 10."""
    by_gas = {g["gas"]: g for g in classify_phase("B")["gases"]}
    assert by_gas["CH4"]["delta"] == 11
    assert by_gas["CH4"]["exceedsT3"] is True


@pytest.mark.parametrize("phase,expected", [("R", True), ("Y", True), ("B", False)])
def test_acetylene_any_increase_flags_r_and_y_only(phase, expected):
    """C2H2 has no numeric limit in Table 3 - any positive change counts."""
    by_gas = {g["gas"]: g for g in classify_phase(phase)["gases"]}
    assert by_gas["C2H2"]["t3"] == ds.ANY_INCREASE
    assert by_gas["C2H2"]["exceedsT3"] is expected


# --------------------------------------------------------------------------
# Column selection
# --------------------------------------------------------------------------
@pytest.mark.parametrize("age,band", [
    (None, "Unknown"), (0, "1-9"), (9, "1-9"), (10, "10-30"),
    (30, "10-30"), (31, ">30"), (43, ">30"),
])
def test_age_bands(age, band):
    assert ds.age_band(age) == band


@pytest.mark.parametrize("ratio,band", [
    (None, ">0.2"), (0.05, "<=0.2"), (0.2, "<=0.2"), (0.21, ">0.2"), (1.5, ">0.2"),
])
def test_ratio_bands(ratio, band):
    assert ds.ratio_band(ratio) == band


def test_oscillating_ratio_forces_the_tighter_section():
    assert ds.ratio_band(0.1, oscillating=True) == ">0.2"


def test_o2_n2_read_from_the_newest_sample_that_has_both():
    rows = [sample("2024-01-01", H2=10), sample("2024-06-01", H2=12)]
    rows[1]["O2ppm"], rows[1]["N2ppm"] = 5000, 60000       # 0.083 -> "<=0.2"
    result = ds.classify(rows, age_years=20, asset="X")
    assert result["ratioBand"] == "<=0.2"
    assert result["o2n2"] == pytest.approx(5000 / 60000)


def test_o2_n2_crossing_the_boundary_forces_the_higher_section():
    rows = [sample("2024-01-01", H2=10), sample("2024-06-01", H2=12)]
    rows[0]["O2ppm"], rows[0]["N2ppm"] = 5000, 60000       # 0.083
    rows[1]["O2ppm"], rows[1]["N2ppm"] = 20000, 60000      # 0.333
    result = ds.classify(rows, age_years=20, asset="X")
    assert result["ratioBand"] == ">0.2"
    assert any("crosses 0.2" in a for a in result["assumptions"])


@pytest.mark.parametrize("months,band", [(4, "4-9"), (9, "4-9"), (10, "10-24"), (24, "10-24")])
def test_period_bands(months, band):
    assert ds.period_band(months) == band


# --------------------------------------------------------------------------
# The decision itself
# --------------------------------------------------------------------------
def test_quiet_unit_is_status_1():
    """Everything well under Table 1 with no meaningful change."""
    rows = [sample("2024-01-01", H2=5, CH4=2, C2H6=2, C2H4=2, C2H2=0, CO=100, CO2=1000),
            sample("2024-07-01", H2=6, CH4=2, C2H6=2, C2H4=2, C2H2=0, CO=110, CO2=1100)]
    result = ds.classify(rows, age_years=20, asset="Q")
    assert result["status"] == 1
    assert result["triggeredBy"] == []


def test_level_between_table_1_and_table_2_is_status_2():
    """H2 60 sits above the >0.2 Table 1 level of 40 and under Table 2's 90."""
    rows = [sample("2024-01-01", H2=59), sample("2024-07-01", H2=60)]
    result = ds.classify(rows, age_years=20, asset="M")
    assert result["status"] == 2
    assert [t["kind"] for t in result["triggeredBy"]] == ["level>T1"]


def test_a_value_exactly_on_the_table_1_limit_is_status_2():
    """The standard's own asymmetry: not below Table 1, not above Table 2."""
    rows = [sample("2024-01-01", H2=40), sample("2024-07-01", H2=40)]
    result = ds.classify(rows, age_years=20, asset="E")
    assert result["status"] == 2
    assert "exactly on its Table 1 level" in result["reason"]


def test_unmeasured_gases_are_skipped_not_treated_as_zero():
    rows = [sample("2024-01-01", H2=5), sample("2024-07-01", H2=6)]
    result = ds.classify(rows, age_years=20, asset="S")
    assert result["measuredGases"] == ["H2"]
    assert all(not g["measured"] for g in result["gases"] if g["gas"] != "H2")
    assert result["status"] == 1


def test_rate_over_table_4_is_status_3_even_below_table_2():
    """Three samples over a year: CH4 climbs steadily but stays under Table 2."""
    rows = [sample("2023-01-01", CH4=2), sample("2023-07-01", CH4=14),
            sample("2024-01-01", CH4=26)]
    result = ds.classify(rows, age_years=20, asset="R4")
    assert result["ratesAvailable"] is True
    assert result["periodBand"] == "10-24"
    by_gas = {g["gas"]: g for g in result["gases"]}
    assert by_gas["CH4"]["rate"] == pytest.approx(24.0, rel=0.05)   # ~24 ppm/yr vs limit 3
    assert by_gas["CH4"]["exceedsT2"] is False
    assert result["status"] == 3


def test_delta_only_trip_below_table_1_asks_for_a_confirmation_sample():
    """Section 6, steps 4b-4e: flag it, do not jump the status."""
    rows = [sample("2024-01-01", CH4=2), sample("2024-07-01", CH4=15)]
    result = ds.classify(rows, age_years=20, asset="C")
    assert result["status"] == 2                       # CH4 15 < Table 1's 20
    assert result["pendingConfirmation"] is True
    assert result["confirmation"]["dueWithin"] == "1 month"


def test_extreme_values_raise_the_expert_review_flag():
    """C2H6 at 1200 ppm is both 2x Table 2 and the standard's own example."""
    rows = [sample("2024-01-01", C2H6=1100), sample("2024-07-01", C2H6=1200)]
    result = ds.classify(rows, age_years=20, asset="X1")
    assert result["status"] == 3
    assert len(result["extreme"]) >= 1
    assert any("ethane" in f["text"] for f in result["extreme"])


def test_carbon_oxide_only_status_3_is_a_de_escalation_candidate():
    """High CO2 with no gassing - downgradeable by an engineer, not by us."""
    rows = [sample("2024-01-01", CO2=9000), sample("2024-07-01", CO2=9100)]
    result = ds.classify(rows, age_years=20, asset="CO2")
    assert result["status"] == 3
    assert result["deEscalationCandidate"] is True


def test_missing_table_3_limit_is_reported_not_guessed():
    """C2H4 in the >0.2 section is the one illegible cell in the source."""
    rows = [sample("2024-01-01", C2H4=10), sample("2024-07-01", C2H4=45)]
    result = ds.classify(rows, age_years=20, asset="V")
    by_gas = {g["gas"]: g for g in result["gases"]}
    assert by_gas["C2H4"]["t3"] is None
    assert by_gas["C2H4"]["exceedsT3"] is False
    assert any("No Table 3 limit is legible" in a for a in result["assumptions"])


def test_verify_flags_reach_the_result():
    """A >30 unit uses several ambiguous cells; the report must say so."""
    rows = [sample("2024-01-01", CH4=5), sample("2024-07-01", CH4=6)]
    result = ds.classify(rows, age_years=43, asset="VF")
    assert any(c["gas"] == "CH4" and c["table"] == "Table 2"
               for c in result["verifyCells"])


def test_no_samples_returns_the_unclassified_shape():
    result = ds.classify([], age_years=20, asset="NONE")
    assert result["status"] is None
    assert result["statusLabel"] == "Not classified"
    assert result["gases"] == []


def test_rate_window_drops_points_beyond_two_years():
    rows = [sample("2019-01-01", H2=1), sample("2020-01-01", H2=2),
            sample("2023-01-01", H2=3), sample("2023-07-01", H2=4),
            sample("2024-01-01", H2=5)]
    window = ds._rate_window(rows)
    assert [r["DateSampled"] for r in window] == ["2023-01-01", "2023-07-01", "2024-01-01"]


# --------------------------------------------------------------------------
# Reference tables
# --------------------------------------------------------------------------
def test_every_table_covers_every_gas_in_every_column():
    for ratio in ds.RATIO_BANDS:
        for age in ds.AGE_BANDS:
            assert set(ds.TABLE1[ratio][age]) == set(ds.GASES)
            assert set(ds.TABLE2[ratio][age]) == set(ds.GASES)
        assert set(ds.TABLE3[ratio]) == set(ds.GASES)
        for period in ds.PERIOD_BANDS:
            assert set(ds.TABLE4[ratio][period]) == set(ds.GASES)


def test_table_2_is_never_below_table_1():
    """The 95th percentile must sit at or above the 90th, column by column."""
    for ratio in ds.RATIO_BANDS:
        for age in ds.AGE_BANDS:
            for gas in ds.GASES:
                t1 = ds._cell(ds.TABLE1[ratio][age][gas])[0]
                t2 = ds._cell(ds.TABLE2[ratio][age][gas])[0]
                assert t2 >= t1, f"{gas} {ratio} {age}: T2 {t2} < T1 {t1}"


def test_acetylene_uses_the_any_increase_sentinel_in_tables_3_and_4():
    for ratio in ds.RATIO_BANDS:
        assert ds.TABLE3[ratio]["C2H2"] == ds.ANY_INCREASE
        for period in ds.PERIOD_BANDS:
            assert ds.TABLE4[ratio][period]["C2H2"] == ds.ANY_INCREASE


def test_reference_tables_serialise_with_verify_flags():
    tables = ds.reference_tables()
    assert tables["table2"][">0.2"][">30"]["CH4"] == {"limit": 30, "verify": True}
    assert tables["table3"][">0.2"]["C2H4"] == {"limit": None, "verify": True}
    assert tables["table1"]["<=0.2"]["1-9"]["H2"] == {"limit": 75, "verify": False}


# --------------------------------------------------------------------------
# Fleet sweep - the age lookup must never go per-asset over the wire
# --------------------------------------------------------------------------
def test_fleet_sweep_runs_age_blind_when_the_cmms_map_is_not_primed(monkeypatch):
    """Without the map, a sweep uses the Unknown column rather than 400 queries.

    `_age_for` reaching the CMMS once per asset is what made the first version
    of this sweep take minutes; if that ever comes back, this fails.
    """
    monkeypatch.setattr(ds.attributes, "loaded_map", lambda: None)

    def explode(_asset):
        raise AssertionError("per-asset CMMS lookup inside a fleet sweep")

    monkeypatch.setattr(ds, "_age_for", explode)
    monkeypatch.setattr(ds.dga_trend, "fetch_samples",
                        lambda assets, *a, **k: {"A": [sample("2024-01-01", H2=5),
                                                       sample("2024-07-01", H2=6)]})
    assert ds.age_source() == "unavailable"
    rows = ds.fleet_status(["A"])
    assert rows[0]["ageBand"] == "Unknown"
    assert rows[0]["ageYears"] is None


def test_fleet_sweep_uses_the_map_when_it_is_primed(monkeypatch):
    monkeypatch.setattr(ds.attributes, "loaded_map", lambda: {"A": {"grid": 1990}})
    monkeypatch.setattr(ds, "_age_for", lambda asset: (36.0, {"manufactureYear": 1990}))
    monkeypatch.setattr(ds.dga_trend, "fetch_samples",
                        lambda assets, *a, **k: {"A": [sample("2024-01-01", H2=5),
                                                       sample("2024-07-01", H2=6)]})
    assert ds.age_source() == "cmms-map"
    rows = ds.fleet_status(["A"])
    assert rows[0]["ageBand"] == ">30"
    assert rows[0]["ageYears"] == 36.0


def test_summary_counts_every_bucket():
    rows = [
        {"status": 1, "pendingConfirmation": False, "extreme": 0},
        {"status": 2, "pendingConfirmation": True, "extreme": 0},
        {"status": 3, "pendingConfirmation": False, "extreme": 2},
        {"status": None, "pendingConfirmation": False, "extreme": 0},
    ]
    assert ds.summary(rows) == {
        "status1": 1, "status2": 1, "status3": 1, "unclassified": 1,
        "total": 4, "pendingConfirmation": 1, "extreme": 1,
    }
