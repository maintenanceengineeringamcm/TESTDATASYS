"""The AGE criterion must be the CMMS manufacture year, and must say so.

These tests stub out both databases, so they assert the *binding* - which
source wins, what the engine is handed, and what the UI is told - rather than
any particular asset's age.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core import attributes, readers

THIS_YEAR = datetime.now().year


@pytest.fixture
def sources(monkeypatch):
    """Control every age source independently.

    `cmms` is the year `core.attributes` finds; `ceb_asset` and `sfra` are the
    years the two HI-database tables return.
    """
    state = {"cmms": None, "ceb_asset": None, "sfra": None}

    def fake_manufacture_year(asset_no, follow_oltc_parent=True):
        year = state["cmms"]
        if year is None:
            return None
        return {"year": year, "age": attributes.age_from_year(year),
                "column": attributes.YEAR_COLUMN, "label": attributes.YEAR_LABEL,
                "source": "cmms", "assetNo": asset_no, "raw": year}

    def fake_query_one(sql, params=()):
        if "CEB_ASSET" in sql:
            return {"y": state["ceb_asset"]} if state["ceb_asset"] else None
        if "SFRA_HEADER" in sql:
            return {"y": state["sfra"]} if state["sfra"] else None
        return None

    monkeypatch.setattr(readers.attributes, "manufacture_year", fake_manufacture_year)
    monkeypatch.setattr(readers.db, "query_one", fake_query_one)
    return state


class TestSourcePrecedence:
    def test_cmms_year_becomes_the_age(self, sources):
        sources["cmms"] = THIS_YEAR - 19
        reading = readers.read_age("G001/PE/1/02/MT01_X/01")
        assert reading.value == 19.0
        assert reading.source == f"Tomms_CEBT.{attributes.YEAR_COLUMN}"
        assert reading.detail["manufactureYear"] == THIS_YEAR - 19
        assert reading.detail["manufactureYearLabel"] == "Year of Manufacture(G)"

    def test_cmms_beats_sfra_when_they_disagree(self, sources):
        """They disagree on 15 of the 157 assets both know about.

        The CMMS is the asset register; the SFRA year is one engineer's note in
        a test-file header. The register wins, and the loser stays visible.
        """
        sources["cmms"] = 1997
        sources["sfra"] = 2012
        reading = readers.read_age("G002/PE/1/03/MT02_X/01")
        assert reading.detail["manufactureYear"] == 1997
        losers = [c for c in reading.candidates if not c.used]
        assert [c.source for c in losers] == ["SFRA_HEADER"]
        assert "ranks above" in losers[0].reason

    def test_sfra_still_used_when_the_cmms_has_nothing(self, sources):
        """8 assets have an SFRA year and no CMMS row - they must not lose AGE."""
        sources["sfra"] = THIS_YEAR - 30
        reading = readers.read_age("G0XX/PE/1/01/MT01_X/01")
        assert reading.value == 30.0
        assert reading.source == "SFRA_HEADER"

    def test_manual_age_overrides_everything(self, sources):
        sources["cmms"] = 1997
        sources["sfra"] = 2012
        reading = readers.read_age("G002/PE/1/03/MT02_X/01", manual_age=42)
        assert reading.value == 42.0
        assert reading.source == "manual entry"
        overridden = [c.reason for c in reading.candidates if not c.used]
        assert all("overridden by the age entered" in r for r in overridden)

    def test_manual_age_of_zero_is_honoured(self, sources):
        """0 is a real answer - a new asset - and must not read as 'not entered'."""
        sources["cmms"] = 1997
        assert readers.read_age("G002/PE/1/03/MT02_X/01", manual_age=0).value == 0.0

    def test_no_source_means_unavailable_not_zero(self, sources):
        """A missing year must drop AGE from the weights, never score it 0.

        Scoring an unknown age as 0 years would hand the asset a *perfect* age
        score it has not earned.
        """
        assert readers.read_age("G999/PE/1/01/MT01_X/01") is None


class TestCandidatesAreShown:
    def test_every_source_appears_as_a_candidate(self, sources):
        sources["cmms"] = 1997
        sources["ceb_asset"] = 1996
        sources["sfra"] = 2012
        reading = readers.read_age("G002/PE/1/03/MT02_X/01")
        assert {c.source for c in reading.candidates} == {
            f"Tomms_CEBT.{attributes.YEAR_COLUMN}", "CEB_ASSET", "SFRA_HEADER"}
        assert sum(1 for c in reading.candidates if c.used) == 1
        assert reading.mode == "pick"

    def test_single_source_is_not_a_pick(self, sources):
        sources["cmms"] = 1997
        assert readers.read_age("G001/PE/1/02/MT01_X/01").mode == "single"

    def test_junk_years_in_the_hi_tables_are_dropped_too(self, sources):
        """1900 in SFRA_HEADER is as meaningless as 1900 in the CMMS."""
        sources["sfra"] = 1900
        assert readers.read_age("G0XX/PE/1/01/MT01_X/01") is None

    def test_candidate_carries_the_year_and_its_date(self, sources):
        sources["cmms"] = 2007
        reading = readers.read_age("G001/PE/1/02/MT01_X/01")
        used = next(c for c in reading.candidates if c.used)
        assert "2007" in used.label
        assert used.date == "2007-01-01"


class TestEngineBinding:
    """The value the engine bands is the age, and it comes from this reader."""

    def test_age_reader_is_wired_for_every_scored_asset_type(self):
        from core import hi_engine
        for asset_type, table in hi_engine.READERS.items():
            assert table.get("AGE") is readers.read_age, asset_type

    def test_component_value_is_the_age_in_years(self, sources, monkeypatch):
        from core import hi_engine, scoring
        sources["cmms"] = THIS_YEAR - 19

        # Score only AGE: every other reader has nothing to say.
        monkeypatch.setattr(hi_engine, "READERS", {"TR": {"AGE": readers.read_age}})
        monkeypatch.setattr(hi_engine.assets_mod, "get", lambda n: None)
        result = hi_engine.compute("G001/PE/1/02/MT01_X/01", selected=["AGE"])

        age = next(c for c in result["components"] if c["code"] == "AGE")
        assert age["value"] == 19.0
        assert age["available"] is True
        assert age["date"] == f"{THIS_YEAR - 19}-01-01"
        assert age["detail"]["manufactureYear"] == THIS_YEAR - 19
        # AGE alone, so it carries the whole normalised weight. Weights sum to
        # 100 and scores to 1, which is what puts the index on 0..100.
        assert age["weight"] == pytest.approx(100.0)
        assert result["healthIndex"] == pytest.approx(
            scoring.score_component("TR", "AGE", 19.0) * 100)
