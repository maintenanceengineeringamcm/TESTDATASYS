"""Live validation against `Tomms_CEBT` and `CEB_TRANSMISSION`.

This is the validation suite from `ASSET_ATTRIBUTES_INTEGRATION.md` section 11,
plus the checks that matter to the health index specifically: that the ages the
engine scores really are the CMMS manufacture years, and that the junk in the
source never reaches a score.

The document's baseline was verified on 2026-08-31. Counts move as engineers
enter data, so the assertions are bounds and relationships rather than exact
figures - except the ones that must never move at all, which are exact.

Skipped, not failed, when a database is unreachable.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from config import Config
from core import assets as assets_mod
from core import attributes, hi_engine, readers

pytestmark = pytest.mark.live

THIS_YEAR = datetime.now().year

# Assets used as fixed points. Verified against the live CMMS on 2026-09-01.
KNOWN_YEARS = {
    "G001/PE/1/02/MT01_X/01": 2007,
    "G083/PE/3/04/SA01_B/01": 2020,     # doc section 7.2's worked example
    "G030/PE/1/01/89L_Y/01": 2012,
}
# Carries the 1900 placeholder: it must read as "no year", not as 126 years old.
PLACEHOLDER_ASSET = "G008/PE/3/08/VT01_Y/01"


# --------------------------------------------------------------------------
# doc section 11 check 3 - the mapping the whole integration rests on
# --------------------------------------------------------------------------
def test_cf_label_still_calls_datetime1_the_manufacture_year(cmms):
    """The UDF slot's meaning is data, not schema.

    An administrator can re-purpose `ast_det_datetime1` from inside the CMMS
    with no schema change, no error, and no sign anywhere except that every age
    in the system silently becomes something else. Assert the caption.
    """
    got = attributes.verify_label_mapping()
    assert got["checked"] is True
    assert got["ok"] is True, got["message"]
    assert got["actual"] == "Year of Manufacture(G)"
    assert got["localActual"] == "Year of Manufacture(L)"


@pytest.mark.slow
def test_the_column_is_still_a_year_not_a_date(cmms):
    """How safe is `YEAR(...)`? Measured, not assumed. A full heap scan.

    ⚠ The document overstates this. Section 1 says "every value is January 1st
    ... Verified: zero rows carry a month or day other than 1". Run against the
    live database on 2026-09-01 that is not true:

        Jan 1        16,735
        other month     773   (Feb 1 x368, Aug 1 x77, Dec 1 x71, ...)
        real day-of-month ~23 (Feb 25 x10, Jun 22 x4, ...)

    So `YEAR(...)` does discard a month for 4.4% of rows, which can move a
    whole-year age by one. The year-only convention still holds for 95.6% of
    the data, the AGE score bands are far coarser than a year, and mixing
    year-arithmetic with elapsed-date arithmetic across the fleet would be
    worse than the error it fixes - so the documented `YEAR(...)` rule stands.

    This test guards the assumption rather than the doc's number: if the CMMS
    ever starts recording real dates in bulk, the day-level answer stops being
    good enough and this fails loudly.
    """
    row = cmms.tomms_query(
        f"SELECT SUM(CASE WHEN {attributes.YEAR_COLUMN} IS NOT NULL "
        f"          THEN 1 ELSE 0 END) AS filled, "
        f"       SUM(CASE WHEN MONTH({attributes.YEAR_COLUMN}) <> 1 "
        f"          THEN 1 ELSE 0 END) AS other_month, "
        f"       SUM(CASE WHEN DAY({attributes.YEAR_COLUMN}) <> 1 "
        f"          THEN 1 ELSE 0 END) AS other_day "
        f"FROM ast_det")[0]

    assert row["filled"] > 15000, row
    assert row["other_month"] / row["filled"] < 0.10, (
        f"{row['other_month']} of {row['filled']} rows now carry a real month - "
        "the year-only convention no longer holds and age should be computed "
        "from the full date")
    assert row["other_day"] / row["filled"] < 0.01, row


def test_detail_joins_on_the_surrogate_key(cmms):
    """`ast_det` joins on `mst_RowID = RowID`, not on the asset number.

    Doc section 4: using the business key here returns zero rows silently. This
    asserts the join we use actually finds the row.
    """
    rows = cmms.tomms_query(
        "SELECT TOP 1 YEAR(d.ast_det_datetime1) AS y "
        "FROM ast_mst m JOIN ast_det d ON d.mst_RowID = m.RowID "
        "WHERE m.site_cd = ? AND LTRIM(RTRIM(m.ast_mst_asset_no)) = ?",
        (Config.TOMMS_SITE_CD, next(iter(KNOWN_YEARS))))
    assert rows and rows[0]["y"] is not None


# --------------------------------------------------------------------------
# the values themselves
# --------------------------------------------------------------------------
@pytest.mark.parametrize("asset,year", sorted(KNOWN_YEARS.items()))
def test_known_assets_read_the_expected_year_and_age(cmms, asset, year):
    got = attributes.manufacture_year(asset)
    assert got is not None, f"{asset} lost its manufacture year"
    assert got["year"] == year
    assert got["age"] == float(THIS_YEAR - year)
    assert got["column"] == attributes.YEAR_COLUMN


def test_placeholder_year_reads_as_no_year(cmms):
    """1900 is a blank field. Left alone it would score this asset 126 years old."""
    raw = cmms.scalar_tomms(
        "SELECT TOP 1 YEAR(d.ast_det_datetime1) "
        "FROM ast_mst m JOIN ast_det d ON d.mst_RowID = m.RowID "
        "WHERE m.site_cd = ? AND LTRIM(RTRIM(m.ast_mst_asset_no)) = ?",
        (Config.TOMMS_SITE_CD, PLACEHOLDER_ASSET))
    assert raw == 1900, "fixture asset no longer carries the placeholder"
    assert attributes.manufacture_year(PLACEHOLDER_ASSET) is None


def test_no_asset_in_the_fleet_gets_an_impossible_age(cmms, hidb):
    """No score may rest on a 1900 placeholder or a 2103 typo.

    Sampled rather than exhaustive: a per-asset CMMS lookup is ~0.1s, so the
    whole 13,109-asset fleet would take 20 minutes. The sample is spread across
    the fleet, not taken from the front of it.
    """
    fleet = [a.assetNumber for a in assets_mod.all_assets()]
    assert fleet, "no assets found - is CEB_TRANSMISSION populated?"
    sample = fleet[::max(1, len(fleet) // 120)][:120]

    for asset in sample:
        got = attributes.manufacture_year(asset)
        if got is None:
            continue
        assert attributes.YEAR_MIN <= got["year"] <= THIS_YEAR, f"{asset}: {got['year']}"
        assert 0 <= got["age"] <= THIS_YEAR - attributes.YEAR_MIN, f"{asset}: {got['age']}"


# --------------------------------------------------------------------------
# the binding: what the engine actually scores
# --------------------------------------------------------------------------
@pytest.mark.parametrize("asset,year", sorted(KNOWN_YEARS.items()))
def test_the_age_component_carries_the_cmms_year(cmms, hidb, asset, year):
    """End to end: CMMS year -> reader -> AGE component -> a banded score."""
    result = hi_engine.compute(asset)
    age = next((c for c in result["components"] if c["code"] == "AGE"), None)
    assert age is not None, f"{result['assetType']} has no AGE criterion"
    assert age["available"] is True
    assert age["value"] == float(THIS_YEAR - year)
    assert age["date"] == f"{year}-01-01"
    assert age["detail"]["manufactureYear"] == year
    assert age["source"] == f"Tomms_CEBT.{attributes.YEAR_COLUMN}"
    assert age["score"] is not None


def test_manual_age_still_overrides_the_cmms(cmms, hidb):
    asset, year = next(iter(sorted(KNOWN_YEARS.items())))
    result = hi_engine.compute(asset, manual_age=5)
    age = next(c for c in result["components"] if c["code"] == "AGE")
    assert age["value"] == 5.0
    assert age["source"] == "manual entry"
    # ...and the CMMS year is still visible as the candidate it overrode.
    overridden = [c for c in age["candidates"] if not c["used"]]
    assert any(str(year) in c["label"] for c in overridden)


def test_the_cmms_is_a_large_improvement_on_what_we_had(cmms, hidb):
    """The reason for this integration, asserted rather than claimed.

    Before it, AGE came from `SFRA_HEADER` (165 assets) and `CEB_ASSET`
    (0 rows). If this ever inverts, the CMMS pull has broken and thousands of
    assets have quietly lost their age.
    """
    sfra = hidb.scalar(
        "SELECT COUNT(DISTINCT LTRIM(RTRIM(Asset))) FROM SFRA_HEADER "
        "WHERE ManufactureYear > 1900")
    fleet = [a.assetNumber for a in assets_mod.all_assets()]
    sample = fleet[::max(1, len(fleet) // 120)][:120]
    with_year = sum(1 for a in sample if attributes.manufacture_year(a))

    assert with_year / len(sample) > 0.5, (
        f"only {with_year}/{len(sample)} sampled assets have a CMMS year")
    assert with_year / len(sample) * len(fleet) > sfra * 10


# --------------------------------------------------------------------------
# the bulk map (doc section 10) - slow, opt in with -m "live and slow"
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_bulk_map_covers_the_fleet(cmms, hidb):
    """The pull the snapshot job does, and the coverage it buys.

    `prime()` re-pulls only when the disk cache has aged past its TTL, so this
    is usually instant; on a cold cache it is the real ~4-9 minute heap scan.
    """
    primed = attributes.prime()
    assert primed["assets"] > 15000, primed
    table = attributes.loaded_map()
    assert table is not None

    fleet = [a.assetNumber for a in assets_mod.all_assets()]
    hit = sum(1 for a in fleet if attributes.manufacture_year(a))
    assert hit > len(fleet) * 0.6, f"only {hit} of {len(fleet)} assets have a year"


@pytest.mark.slow
def test_map_and_per_asset_lookup_agree(cmms):
    """The fleet sweep and a single page must never quote different ages.

    The snapshot reads the bulk map; the asset detail page reads one row over
    the wire. Two code paths, one answer required.
    """
    attributes.prime()
    for asset, year in KNOWN_YEARS.items():
        from_map = attributes.manufacture_year(asset)
        direct = attributes._resolve(attributes._from_cmms(attributes.normalise(asset)),
                                    attributes.normalise(asset), "cmms")
        assert from_map["year"] == direct["year"] == year
