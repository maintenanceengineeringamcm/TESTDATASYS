"""Tests for the hand-entry path into the Figure 2 classifier.

`test_dga_status.py` proves the decision itself. This file covers the layer in
front of it: turning form rows into samples, and refusing input that would
silently change the answer. No database - every case is built in memory.

The distinction that carries most of the weight here is blank vs zero. Section 1
of `DGA_Status_Logic_C57104-2019.md` says an unmeasured gas is skipped in every
comparison, while a measured zero is a real reading that takes part in the
delta. Conflating the two moves units between statuses, so it is asserted from
both directions.
"""
from __future__ import annotations

import pytest

from core import dga_status as ds


def gases(result: dict) -> dict:
    return {g["gas"]: g for g in result["gases"]}


# --------------------------------------------------------------------------
# The section 8 vector, entered by hand
# --------------------------------------------------------------------------
# The same figures as the stored-sample test, through the form path. If the two
# ever disagree, the normaliser has changed the meaning of the input.
VECTOR = {
    "R": (dict(H2=87, CH4=0, C2H4=2, C2H6=0, C2H2=1),
          dict(H2=125, CH4=5, C2H4=3, C2H6=0, C2H2=2)),
    "Y": (dict(H2=53, CH4=8, C2H4=4, C2H6=52, C2H2=4),
          dict(H2=110, CH4=17, C2H4=4, C2H6=53, C2H2=5)),
    "B": (dict(H2=39, CH4=9, C2H4=4, C2H6=52, C2H2=3),
          dict(H2=84, CH4=20, C2H4=4, C2H6=53, C2H2=3)),
}


def entered(phase: str) -> dict:
    previous, latest = VECTOR[phase]
    return ds.manual_report(
        [dict(date="2024-06-01", **previous), dict(date="2024-12-01", **latest)],
        age_years=43, label=f"IBT02-{phase}")


@pytest.mark.parametrize("phase", ["R", "Y", "B"])
def test_entered_vector_matches_the_stored_vector(phase):
    """Hand-entered figures reach the same Status 3 as the stored ones."""
    assert entered(phase)["status"]["status"] == 3


def test_entered_vector_selects_the_same_columns():
    result = entered("R")["status"]
    assert result["ratioBand"] == ">0.2"
    assert result["ageBand"] == ">30"


@pytest.mark.parametrize("phase,expected", [("R", True), ("Y", True), ("B", False)])
def test_acetylene_any_increase_survives_the_form_path(phase, expected):
    """C2H2 +1 flags R and Y; B's flat 3->3 does not."""
    assert gases(entered(phase)["status"])["C2H2"]["exceedsT3"] is expected


# --------------------------------------------------------------------------
# Blank is not zero
# --------------------------------------------------------------------------
def test_blank_gas_is_unmeasured():
    """An omitted gas is skipped in every comparison, not read as 0 ppm."""
    result = ds.manual_report([dict(date="2024-01-01", H2=10),
                               dict(date="2024-08-01", H2=12)])["status"]
    assert gases(result)["CO"]["measured"] is False
    assert "CO" not in result["measuredGases"]


def test_empty_string_is_also_unmeasured():
    """The form sends '' for a cell the user cleared; that is 'not measured'."""
    result = ds.manual_report([dict(date="2024-01-01", H2=10, CO=""),
                               dict(date="2024-08-01", H2=12, CO="")])["status"]
    assert gases(result)["CO"]["measured"] is False


def test_typed_zero_is_a_real_reading():
    """A zero participates: C2H2 0 -> 2 is an increase the standard acts on."""
    result = ds.manual_report([dict(date="2024-01-01", H2=10, C2H2=0),
                               dict(date="2024-08-01", H2=12, C2H2=2)])["status"]
    c2h2 = gases(result)["C2H2"]
    assert c2h2["measured"] is True
    assert c2h2["delta"] == 2
    assert c2h2["exceedsT3"] is True


def test_numbers_may_arrive_as_strings():
    """The form posts text; '125' has to classify the same as 125."""
    numeric = ds.manual_report([dict(date="2024-06-01", H2=87),
                                dict(date="2024-12-01", H2=125)], age_years=43)
    textual = ds.manual_report([dict(date="2024-06-01", H2="87"),
                                dict(date="2024-12-01", H2="125")], age_years="43")
    assert numeric["status"]["status"] == textual["status"]["status"] == 3


# --------------------------------------------------------------------------
# Ordering, dates and the rate window
# --------------------------------------------------------------------------
def test_rows_are_sorted_by_date_not_by_entry_order():
    """Typing the newest sample first must not invert the delta."""
    out_of_order = ds.manual_report([dict(date="2024-12-01", H2=125),
                                     dict(date="2024-06-01", H2=87)], age_years=43)
    h2 = gases(out_of_order["status"])["H2"]
    assert h2["latest"] == 125
    assert h2["previous"] == 87
    assert h2["delta"] == 38


def test_three_samples_over_four_months_enable_table_4():
    rows = [dict(date=d, H2=h) for d, h in
            [("2023-01-10", 20), ("2023-07-10", 35), ("2024-01-10", 52)]]
    result = ds.manual_report(rows, age_years=15)["status"]
    assert result["ratesAvailable"] is True
    assert result["periodBand"] == "10-24"
    assert gases(result)["H2"]["rate"] > 0


def test_two_samples_leave_table_4_unusable():
    result = ds.manual_report([dict(date="2024-01-01", H2=20),
                               dict(date="2024-08-01", H2=35)])["status"]
    assert result["ratesAvailable"] is False
    assert result["periodBand"] is None


def test_a_single_sample_classifies_on_levels_alone():
    result = ds.manual_report([dict(date="2024-01-01", H2=250)], age_years=20)["status"]
    assert result["status"] == 3
    assert result["ratesAvailable"] is False
    assert gases(result)["H2"]["delta"] is None


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------
def test_report_is_marked_as_hand_entered():
    """The report is printed and passed on, so the provenance travels with it."""
    report = entered("R")
    assert report["source"] == "manual"
    assert "hand-entered" in report["caveats"][0]


def test_missing_age_is_flagged_and_uses_the_unknown_column():
    report = ds.manual_report([dict(date="2024-01-01", H2=50)])
    assert report["status"]["ageBand"] == "Unknown"
    assert any("Unknown-age column" in c for c in report["caveats"])


def test_supplied_age_is_not_flagged():
    report = ds.manual_report([dict(date="2024-01-01", H2=50)], age_years=43)
    assert report["status"]["ageBand"] == ">30"
    assert not any("Unknown-age column" in c for c in report["caveats"])


def test_label_names_the_report():
    report = ds.manual_report([dict(date="2024-01-01", H2=50)], label="Certificate 4471")
    assert report["asset"] == "Certificate 4471"


def test_blank_label_falls_back_to_a_readable_name():
    assert ds.manual_report([dict(date="2024-01-01", H2=50)])["asset"] == "Entered data"


def test_payload_has_the_same_shape_as_a_stored_report():
    """One report component renders both paths, so the keys must match."""
    report = entered("R")
    for key in ("generatedAt", "asset", "status", "sampleTable", "limitsUsed",
                "recommendations", "caveats", "standard"):
        assert key in report, key
    assert len(report["sampleTable"]) == 2
    assert report["limitsUsed"]["columns"]["ratioBand"] == ">0.2"


# --------------------------------------------------------------------------
# Input the user has to correct
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rows,age,fragment", [
    ([], None, "at least one sample"),
    ([dict(H2=5)], None, "sampling date is required"),
    ([dict(date="not a date", H2=5)], None, "not a date"),
    ([dict(date="2024-01-01", H2=-5)], None, "negative"),
    ([dict(date="2024-01-01", H2="abc")], None, "not a number"),
    ([dict(date="2024-01-01", H2=5), dict(date="2024-01-01", H2=6)], None, "own date"),
    ([dict(date="2024-01-01")], None, "no gas readings"),
    ([dict(date="2024-01-01", H2=5)], 1982, "not the year of manufacture"),
    ([dict(date="2024-01-01", H2=5)], -3, "cannot be negative"),
    ([dict(date="2024-01-01", H2=9_999_999)], None, "physically plausible"),
])
def test_bad_input_is_rejected_with_a_message_that_says_what_to_fix(rows, age, fragment):
    with pytest.raises(ds.ManualEntryError) as exc:
        ds.manual_report(rows, age)
    assert fragment in str(exc.value)


def test_rejection_names_the_offending_row():
    """With a grid on screen, 'sample 2' is the difference between fixable and not."""
    with pytest.raises(ds.ManualEntryError) as exc:
        ds.manual_report([dict(date="2024-01-01", H2=5), dict(date="2024-06-01", H2=-1)])
    assert "Sample 2" in str(exc.value)


def test_too_many_rows_are_refused():
    rows = [dict(date=f"2024-{m:02d}-01", H2=10) for m in range(1, 13)] + \
           [dict(date=f"2023-{m:02d}-01", H2=10) for m in range(1, 13)] + \
           [dict(date="2022-01-01", H2=10)]
    with pytest.raises(ds.ManualEntryError):
        ds.manual_report(rows)
