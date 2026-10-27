"""Oil filtration point detection and the manual-mark store (unit, no database)."""
from __future__ import annotations

import pytest

from core import dga_filter


def sample(date, h2=0, ch4=0, c2h6=0, c2h4=0, c2h2=0, co=0, co2=0):
    return {"DateSampled": date, "H2ppm": h2, "CH4ppm": ch4, "C2H6ppm": c2h6,
            "C2H4ppm": c2h4, "C2H2ppm": c2h2, "COppm": co, "CO2ppm": co2}


def test_detects_the_recorded_g051_filtration():
    # G051 MT01, 4 May -> 15 May 2020: the one filtration on record in the CMMS.
    found = dga_filter.detect([
        sample("2020-05-04", h2=88, ch4=0, c2h6=14, c2h4=7, co=455, co2=7456),
        sample("2020-05-15", h2=0, ch4=3, c2h6=8, c2h4=0, co=43, co2=258),
    ])
    assert [p["date"] for p in found] == ["2020-05-15"]
    assert found[0]["previousSample"] == "2020-05-04"
    assert set(found[0]["droppedGases"]) == {"H2", "CO", "CO2"}


def test_rising_gases_are_not_a_filter_point():
    assert dga_filter.detect([
        sample("2021-01-01", h2=50, ch4=40, co=300, co2=3000),
        sample("2021-06-01", h2=60, ch4=45, co=320, co2=3200),
    ]) == []


def test_drop_without_co2_is_not_a_filter_point():
    # Hydrocarbons halve but CO2 holds - a bad sample, not oil processing.
    assert dga_filter.detect([
        sample("2021-01-01", h2=100, ch4=80, c2h6=60, co=300, co2=3000),
        sample("2021-02-01", h2=10, ch4=8, c2h6=6, co=30, co2=2900),
    ]) == []


def test_gases_below_floor_are_ignored():
    # Only CO2 is above its floor: too few gases to call it a reset.
    assert dga_filter.detect([
        sample("2021-01-01", h2=5, co=50, co2=900),
        sample("2021-02-01", h2=0, co=10, co2=100),
    ]) == []


def test_order_and_undated_samples():
    found = dga_filter.detect([
        sample("2022-01-01", h2=0, ch4=2, co=20, co2=200),
        sample(None, h2=999),
        sample("2021-01-01", h2=120, ch4=90, co=500, co2=6000),
    ])
    assert [p["date"] for p in found] == ["2022-01-01"]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(dga_filter, "DB_PATH", tmp_path / "fp.db")
    monkeypatch.setattr(dga_filter, "_ready", False)
    history = [sample("2020-05-04", h2=88, co=455, co2=7456, c2h6=14),
               sample("2020-05-15", h2=0, co=43, co2=258, c2h6=8)]
    monkeypatch.setattr(dga_filter.dga_trend, "fetch_samples",
                        lambda assets, *a, **k: {assets[0].strip(): list(history)})
    return dga_filter


def test_manual_point_round_trip(store):
    out = store.add("G1/MT", "2023-03-01", note="filtered by contractor", user="eng")
    manual = [p for p in out["points"] if p["source"] == "manual"]
    assert manual[0]["date"] == "2023-03-01" and manual[0]["note"] == "filtered by contractor"
    point_id = int(manual[0]["id"].split(":")[1])
    out = store.remove("G1/MT", point_id)
    assert [p["source"] for p in out["points"]] == ["detected"]


def test_reject_and_restore_detected(store):
    out = store.add("G1/MT", "2020-05-15", kind="rejected", note="resample")
    det = out["points"][0]
    assert det["source"] == "detected" and det["rejected"] and det["note"] == "resample"
    out = store.remove("G1/MT", det["rejectionId"])
    assert out["points"][0]["rejected"] is False


@pytest.mark.parametrize("date, kind", [("not-a-date", "manual"), ("2999-01-01", "manual"),
                                        ("2023-01-01", "other")])
def test_add_validation(store, date, kind):
    with pytest.raises(ValueError):
        store.add("G1/MT", date, kind=kind)


def test_remove_unknown(store):
    with pytest.raises(LookupError):
        store.remove("G1/MT", 999)


# ---------------------------------------------------------------------------
# Which side of a filter point DGA level and trend are scored on
# ---------------------------------------------------------------------------
def dates(window):
    return [s["DateSampled"] for s in window["samples"]]


HISTORY = [sample(d, h2=50, co=300, co2=3000) for d in
           ("2019-01-01", "2019-06-01", "2020-01-01", "2020-06-01", "2021-01-01",
            "2021-06-01", "2022-01-01")]


def test_no_filter_point_uses_full_history():
    w = dga_filter.choose_window(HISTORY, [], min_after=3)
    assert len(w["samples"]) == 7 and w["fromDate"] is None and w["beforeDate"] is None


def test_three_samples_after_point_uses_after():
    w = dga_filter.choose_window(HISTORY, ["2021-01-01"], min_after=3)
    assert dates(w) == ["2021-01-01", "2021-06-01", "2022-01-01"]
    assert w["fromDate"] == "2021-01-01" and w["skippedPoints"] == []


def test_too_few_after_point_uses_data_before():
    w = dga_filter.choose_window(HISTORY, ["2021-06-01"], min_after=3)
    assert dates(w) == ["2019-01-01", "2019-06-01", "2020-01-01", "2020-06-01", "2021-01-01"]
    assert w["fromDate"] is None and w["beforeDate"] == "2021-06-01"
    assert w["skippedPoints"] == [{"date": "2021-06-01", "samplesAfter": 2}]


def test_rule_repeats_on_the_earlier_data():
    # Last point has 2 after it; the one before has 3 between the two points.
    w = dga_filter.choose_window(HISTORY, ["2020-01-01", "2021-06-01"], min_after=3)
    assert dates(w) == ["2020-01-01", "2020-06-01", "2021-01-01"]
    assert (w["fromDate"], w["beforeDate"]) == ("2020-01-01", "2021-06-01")


def test_earlier_segment_also_short_falls_back_further():
    w = dga_filter.choose_window(HISTORY, ["2020-06-01", "2021-06-01"], min_after=3)
    # 2020-06 .. 2021-06 holds only 2 samples, so it goes back to before 2020-06.
    assert dates(w) == ["2019-01-01", "2019-06-01", "2020-01-01"]
    assert [p["date"] for p in w["skippedPoints"]] == ["2021-06-01", "2020-06-01"]


def test_nothing_before_point_keeps_after_data():
    w = dga_filter.choose_window(HISTORY[:2], ["2019-01-01"], min_after=3)
    assert dates(w) == ["2019-01-01", "2019-06-01"]


def test_point_after_last_sample_is_ignored_side():
    # A mark with no samples after it: score on everything before it.
    w = dga_filter.choose_window(HISTORY, ["2023-01-01"], min_after=3)
    assert len(w["samples"]) == 7 and w["beforeDate"] == "2023-01-01"


def test_rejected_points_do_not_count(store):
    # The detected 2020-05-15 point is rejected, leaving no filter point.
    store.add("G1/MT", "2020-05-15", kind="rejected")
    assert store.active_dates("G1/MT", store.dga_trend.fetch_samples(["G1/MT"])["G1/MT"]) == []
