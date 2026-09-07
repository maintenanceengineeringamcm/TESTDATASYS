"""Unit tests for the manufacture-year extraction rules.

No database. Everything here is a rule stated in `ASSET_ATTRIBUTES_INTEGRATION.md`
that the code must keep obeying: which junk values are rejected, how a year
becomes an age, how an OLTC resolves to its transformer, and which of the
several possible sources wins when they disagree.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core import attributes


THIS_YEAR = datetime.now().year


# --------------------------------------------------------------------------
# doc section 1 - the cleaning predicate
# --------------------------------------------------------------------------
class TestUsableYear:
    @pytest.mark.parametrize("year", [1963, 1987, 1997, 2007, 2015, 2023, THIS_YEAR])
    def test_real_years_pass(self, year):
        assert attributes.usable_year(year) == year

    @pytest.mark.parametrize("junk", [1900, 1905])
    def test_placeholders_are_not_years(self, junk):
        """1900 and 1905 are 'nothing entered', not the age of the plant.

        69 assets carry 1900. Reading it literally would score them as 126
        years old - the worst band there is - on the strength of a blank field.
        """
        assert attributes.usable_year(junk) is None

    @pytest.mark.parametrize("typo", [2102, 2103, 2180])
    def test_impossible_future_years_rejected(self, typo):
        """8 rows carry a year that has not happened; they would give a negative age."""
        assert attributes.usable_year(typo) is None

    def test_next_year_rejected(self):
        assert attributes.usable_year(THIS_YEAR + 1) is None

    def test_boundaries(self):
        assert attributes.usable_year(attributes.YEAR_MIN) == attributes.YEAR_MIN
        assert attributes.usable_year(attributes.YEAR_MIN - 1) is None

    @pytest.mark.parametrize("blank", [None, "", "  ", "not a year", object()])
    def test_non_numeric_is_absent(self, blank):
        assert attributes.usable_year(blank) is None

    def test_numeric_strings_accepted(self):
        """The driver can hand back a string; a real year in one is still a year."""
        assert attributes.usable_year("1997") == 1997


class TestAgeFromYear:
    def test_age_is_years_since_manufacture(self):
        assert attributes.age_from_year(THIS_YEAR - 19) == 19.0

    def test_manufactured_this_year_is_zero_not_missing(self):
        """A brand-new asset is 0 years old, which is a value, not an absence."""
        assert attributes.age_from_year(THIS_YEAR) == 0.0

    @pytest.mark.parametrize("junk", [1900, 2103, None])
    def test_junk_year_yields_no_age(self, junk):
        assert attributes.age_from_year(junk) is None

    def test_age_never_negative(self):
        """The 2102/2103/2180 rows must not produce a negative age."""
        assert attributes.age_from_year(THIS_YEAR + 5) is None


# --------------------------------------------------------------------------
# doc section 9.5 - whitespace, and the case-insensitive collation
# --------------------------------------------------------------------------
class TestNormalise:
    def test_trims_and_upper_cases(self):
        assert attributes.normalise("  g001/pe/1/02/mt01_x/01 ") == "G001/PE/1/02/MT01_X/01"

    def test_empty(self):
        assert attributes.normalise(None) == ""
        assert attributes.normalise("   ") == ""


# --------------------------------------------------------------------------
# OLTC asset numbers
# --------------------------------------------------------------------------
class TestOltcParent:
    def test_plain_oltc(self):
        assert (attributes.parent_of_oltc("G001/PE/1/02/MT01_X/OLTC/01")
                == "G001/PE/1/02/MT01_X/01")

    def test_numbered_oltc(self):
        """Inter-bus units carry two tap changers, OLTC1 and OLTC2."""
        assert (attributes.parent_of_oltc("G025/PE/2/06/IBT02_R/OLTC2/02")
                == "G025/PE/2/06/IBT02_R/02")

    def test_non_oltc_returns_none(self):
        assert attributes.parent_of_oltc("G001/PE/1/02/MT01_X/01") is None

    def test_lowercase(self):
        assert (attributes.parent_of_oltc("G001/PE/1/02/MT01_X/oltc/01")
                == "G001/PE/1/02/MT01_X/01")


# --------------------------------------------------------------------------
# resolution order within the CMMS: (G) first, (L) only as a fallback (doc 9.2)
# --------------------------------------------------------------------------
class TestResolve:
    def test_grid_year_wins_over_local(self):
        got = attributes._resolve({"grid": 2020, "line": 2016}, "A", "cmms")
        assert got["year"] == 2020
        assert got["column"] == attributes.YEAR_COLUMN
        assert got["source"] == "cmms"

    def test_local_used_only_when_grid_missing(self):
        got = attributes._resolve({"grid": None, "line": 2016}, "A", "cmms")
        assert got["year"] == 2016
        assert got["column"] == attributes.YEAR_COLUMN_LOCAL
        assert got["source"] == "cmms-local"

    def test_junk_grid_falls_through_to_local(self):
        got = attributes._resolve({"grid": 1900, "line": 2016}, "A", "cmms")
        assert got["year"] == 2016

    def test_all_junk_is_no_year(self):
        assert attributes._resolve({"grid": 1900, "line": 2103}, "A", "cmms") is None
        assert attributes._resolve({"grid": None, "line": None}, "A", "cmms") is None
        assert attributes._resolve(None, "A", "cmms") is None


# --------------------------------------------------------------------------
# the map lookup and the OLTC parent fallback, with the CMMS stubbed out
# --------------------------------------------------------------------------
@pytest.fixture
def stub_map(monkeypatch):
    """Replace the bulk map with an in-memory table.

    `_from_cmms` is made to explode rather than return None: with a map loaded,
    nothing may reach the per-asset query. That is the property being guarded,
    not an incidental detail of the stub.
    """
    table: dict[str, dict[str, int | None]] = {}

    def no_round_trips(key):
        raise AssertionError(
            f"per-asset CMMS query for {key} while the bulk map was loaded")

    monkeypatch.setattr(attributes, "loaded_map", lambda: table)
    monkeypatch.setattr(attributes, "_from_cmms", no_round_trips)
    return table


class TestManufactureYearLookup:
    def test_found(self, stub_map):
        stub_map["G001/PE/1/02/MT01_X/01"] = {"grid": THIS_YEAR - 19, "line": None}
        got = attributes.manufacture_year("G001/PE/1/02/MT01_X/01")
        assert got["age"] == 19.0
        assert got["source"] == "cmms-map"

    def test_lookup_is_case_and_space_insensitive(self, stub_map):
        stub_map["G001/PE/1/02/MT01_X/01"] = {"grid": 2007, "line": None}
        assert attributes.manufacture_year(" g001/pe/1/02/mt01_x/01 ")["year"] == 2007

    def test_absent_asset(self, stub_map):
        assert attributes.manufacture_year("G999/PE/1/01/MT01_X/01") is None

    def test_junk_year_reads_as_no_year(self, stub_map):
        stub_map["G008/PE/3/08/VT01_Y/01"] = {"grid": 1900, "line": None}
        assert attributes.manufacture_year("G008/PE/3/08/VT01_Y/01") is None

    def test_oltc_uses_its_own_year_when_it_has_one(self, stub_map):
        """78 tap changers carry a year that differs from their transformer's."""
        stub_map["G001/PE/1/02/MT01_X/OLTC/01"] = {"grid": 2015, "line": None}
        stub_map["G001/PE/1/02/MT01_X/01"] = {"grid": 1997, "line": None}
        got = attributes.manufacture_year("G001/PE/1/02/MT01_X/OLTC/01")
        assert got["year"] == 2015
        assert "inheritedFrom" not in got

    def test_oltc_falls_back_to_its_transformer(self, stub_map):
        stub_map["G001/PE/1/02/MT01_X/01"] = {"grid": 1997, "line": None}
        got = attributes.manufacture_year("G001/PE/1/02/MT01_X/OLTC/01")
        assert got["year"] == 1997
        assert got["inheritedFrom"] == "G001/PE/1/02/MT01_X/01"
        assert got["source"].endswith("-parent")

    def test_inheritance_does_not_recurse(self, stub_map):
        """A transformer with no year does not somehow acquire one."""
        assert attributes.manufacture_year("G001/PE/1/02/MT01_X/OLTC/01") is None

    def test_blank_asset_number(self, stub_map):
        assert attributes.manufacture_year("") is None
        assert attributes.manufacture_year(None) is None


class TestMapIsAuthoritative:
    """A loaded map answers for every asset, including "this one has no year"."""

    def test_absent_from_a_loaded_map_means_no_year(self, stub_map):
        stub_map["G001/PE/1/02/MT01_X/01"] = {"grid": 2007, "line": None}
        # No CMMS round trip: the stub would raise. 4,044 scored assets have no
        # year, and querying for each on every sweep would cost ~7 minutes.
        assert attributes.manufacture_year("G500/PE/1/01/CT01_R/01") is None

    def test_without_a_map_the_per_asset_query_is_used(self, monkeypatch):
        monkeypatch.setattr(attributes, "loaded_map", lambda: None)
        monkeypatch.setattr(attributes, "_from_cmms",
                            lambda key: {"grid": 2007, "line": None})
        got = attributes.manufacture_year("G001/PE/1/02/MT01_X/01")
        assert got["year"] == 2007
        assert got["source"] == "cmms"


# --------------------------------------------------------------------------
# the map is never built inside a request (doc section 10)
# --------------------------------------------------------------------------
def test_loaded_map_never_triggers_a_pull(monkeypatch):
    """`loaded_map` must not fall back to the 4-minute scan.

    A single dashboard render would otherwise hang for minutes the first time
    the cache expired.
    """
    def explode():
        raise AssertionError("loaded_map() must not trigger the bulk pull")

    monkeypatch.setattr(attributes, "_pull_all", explode)
    monkeypatch.setattr(attributes, "_map", None)
    monkeypatch.setattr(attributes, "_map_loaded_at", 0.0)
    monkeypatch.setattr(attributes, "CACHE_PATH",
                        attributes.CACHE_PATH.with_name("does-not-exist.json"))
    assert attributes.loaded_map() is None
