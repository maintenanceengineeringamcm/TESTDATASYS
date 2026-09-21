"""Raw per-test record history for a single asset.

The availability report answers *does this test exist for this asset* - this
module answers the follow-up: *show me every record it has, oldest to newest*.

The catalogue is deliberately the same list the availability report uses, so a
tick there always leads to rows here. Two shapes of history exist:

* **table** tests live in one ``CEB_*`` table keyed on ``AssetNumber``; one row
  per test date.
* **omicron** tests come off the JOB -> EXECUTED_TEST path. Where the test's
  measurement table is known, one row per measurement is returned carrying the
  execution date; where it is not, the executions themselves are the history.

Columns are discovered from ``INFORMATION_SCHEMA`` rather than hard-coded: these
tables are wide, differ between sites, and an engineer looking at history wants
the whole record, not the one field the scorer happens to read.
"""
from __future__ import annotations

import logging
from typing import Any

import db
from core.readers import (AVAILABILITY_OMICRON, AVAILABILITY_TESTS, OPEN_FROM,
                          OPEN_TO, availability)

log = logging.getLogger(__name__)

MAX_ROWS = 500

# Bookkeeping columns carry no engineering meaning in a history view. The asset
# number is dropped because every row already belongs to the selected asset;
# RowId / MasterRowId are the source system's internal keys.
HIDDEN_COLUMNS = {"id", "assetnumber", "asset", "parent", "job",
                  "rowid", "masterrowid"}

NUMERIC_TYPES = {"int", "bigint", "smallint", "tinyint", "decimal", "numeric",
                 "float", "real", "money", "smallmoney"}

DATE_TYPES = {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"}

# Omicron test name -> (header table, measurement table). The header row links a
# job to its measurements; the same joins the readers use for scoring.
OMICRON_DATA: dict[str, tuple[str, str]] = {
    "Turns Ratio Prim-Sec": ("TURNS_RATIO_PRIM_SEC", "TURNS_RATIO_PRIM_SEC_DATA"),
    "Short Circuit Impedance": ("SHORT_CIRCUIT_IMPEDANCE_PRIM_SEC",
                                "PHA_EQUIV_ASSESSMENT_ZK"),
    "DC Winding Resistance Prim": ("DC_WINDING_RESISTANCE_PRIM",
                                   "DC_WINDING_RESISTANCE_PRIM_DATA"),
    "Exciting Current": ("EXCITING_CURRENT", "EXCITING_CURRENT_DATA"),
    "Winding DF & CAP": ("WINDING_TAND_CAP", "WINDING_TAND_CAP_MEASUREMENT_DATA"),
}


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------
def _catalogue() -> dict[str, dict[str, Any]]:
    """Every test that can be browsed, keyed by test id."""
    out: dict[str, dict[str, Any]] = {}
    for test_id, name, table, date_col in AVAILABILITY_TESTS:
        out[test_id] = {"testId": test_id, "name": name, "table": table,
                        "dateColumn": date_col, "kind": "table"}
    for test_id, name in AVAILABILITY_OMICRON:
        header, data = OMICRON_DATA.get(name, (None, None))
        out[test_id] = {"testId": test_id, "name": f"Omicron: {name}",
                        "table": data or "EXECUTED_TEST", "dateColumn": "DateTime",
                        "kind": "omicron", "omicronName": name,
                        "headerTable": header, "dataTable": data}
    return out


CATALOGUE = _catalogue()


def catalogue() -> list[dict[str, Any]]:
    return list(CATALOGUE.values())


# Test dates outside this window are data-entry noise, not tests: 1753-01-01 is
# SQL Server's empty-datetime placeholder, and typed years such as 7024 turn up
# in the CT/VT/SA sheets. Such rows still count as records; they just cannot
# set the first or last test date.
PLAUSIBLE_FROM = "1950-01-01"


def _span(col: str) -> str:
    plausible = f"CASE WHEN {col} >= '{PLAUSIBLE_FROM}' AND {col} <= GETDATE() THEN {col} END"
    return f"MIN({plausible}) AS firstTested, MAX({plausible}) AS lastTested"


def _table_summary(test: dict[str, Any]) -> dict[str, Any]:
    table, date_col = test["table"], test["dateColumn"]
    return db.query_one(
        f"SELECT COUNT(*) AS records, "
        f"COUNT(DISTINCT LTRIM(RTRIM(AssetNumber))) AS assets, "
        f"{_span(f'[{date_col}]')} FROM {table}"
    ) or {}


def _omicron_summary(test: dict[str, Any]) -> dict[str, Any]:
    return db.query_one(
        "SELECT COUNT(*) AS records, COUNT(DISTINCT LTRIM(RTRIM(j.Asset))) AS assets, "
        f"{_span('e.DateTime')} "
        "FROM JOB j JOIN EXECUTED_TEST e ON e.Job = j.ID WHERE e.Name LIKE ?",
        (f"%{test['omicronName']}%",),
    ) or {}


def fleet_summary() -> list[dict[str, Any]]:
    """The catalogue with fleet-wide record counts and date span per test.

    One aggregate per test across the whole database, cached for ten minutes -
    the tables only grow when a new test sheet is loaded. A table absent from
    this database is reported as unavailable rather than failing the list.
    """
    def build() -> list[dict[str, Any]]:
        out = []
        for test in catalogue():
            try:
                row = (_omicron_summary(test) if test["kind"] == "omicron"
                       else _table_summary(test))
                message = None
            except db.DatabaseError as exc:
                log.warning("test summary failed for %s: %s", test["testId"], exc)
                row, message = {}, f"Could not read {test['table']}: {exc}"
            records = int(row.get("records") or 0)
            out.append({**test, "available": records > 0, "records": records,
                        "assets": int(row.get("assets") or 0),
                        "firstTested": row.get("firstTested"),
                        "lastTested": row.get("lastTested"),
                        **({"message": message} if message else {})})
        return out
    return db.cached("history:fleet-summary", build, ttl=600)


def asset_summary(asset: str, date_from: str = OPEN_FROM,
                  date_to: str = OPEN_TO) -> list[dict[str, Any]]:
    """The catalogue with one asset's record count and last test date per test."""
    counts = {t["testId"]: t for t in availability(asset, date_from, date_to)}
    items = []
    for test in catalogue():
        got = counts.get(test["testId"], {})
        items.append({**test,
                      "available": got.get("available", False),
                      "records": got.get("records", 0),
                      "lastTested": got.get("lastTested")})
    return items


# --------------------------------------------------------------------------
# column discovery
# --------------------------------------------------------------------------
def _columns(table: str) -> list[dict[str, Any]]:
    """Readable columns of a table, in declaration order.

    Cached because the schema does not move between requests and every history
    view needs it before it can build its SELECT.
    """
    def build() -> list[dict[str, Any]]:
        rows = db.query(
            "SELECT COLUMN_NAME AS name, DATA_TYPE AS type "
            "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            (table,),
        )
        return [
            {"name": r["name"], "type": r["type"],
             "numeric": r["type"] in NUMERIC_TYPES,
             "date": r["type"] in DATE_TYPES}
            for r in rows
            if r["name"].lower() not in HIDDEN_COLUMNS
        ]
    return db.cached(f"cols:{table}", build, ttl=3600)


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------
def _table_history(test: dict[str, Any], asset: str, date_from: str, date_to: str,
                   limit: int) -> dict[str, Any]:
    table, date_col = test["table"], test["dateColumn"]
    columns = _columns(table)
    if not columns:
        return {"columns": [], "rows": [],
                "message": f"Table {table} is not present in this database."}

    # The date column is pulled to the front and every other column follows, so
    # the table reads chronologically without the caller reordering anything.
    ordered = ([c for c in columns if c["name"] == date_col]
               + [c for c in columns if c["name"] != date_col])
    select = ", ".join(f"[{c['name']}]" for c in ordered)

    rows = db.query(
        f"SELECT TOP {limit} {select} FROM {table} "
        f"WHERE LTRIM(RTRIM(AssetNumber)) = ? AND [{date_col}] IS NOT NULL "
        f"  AND [{date_col}] >= ? AND [{date_col}] <= ? "
        f"ORDER BY [{date_col}] DESC",
        (asset.strip(), date_from, date_to),
    )
    return {"columns": ordered, "rows": rows, "dateColumn": date_col}


_EXECUTION_COLUMNS = [
    {"name": "DateTested", "type": "datetime", "numeric": False, "date": True},
    {"name": "TestName", "type": "nvarchar", "numeric": False, "date": False},
    {"name": "JobNumber", "type": "int", "numeric": True, "date": False},
]


def _executions(name: str, asset: str, date_from: str, date_to: str,
                limit: int) -> list[dict[str, Any]]:
    """The test runs themselves, with no measurement rows attached."""
    return db.query(
        f"SELECT TOP {limit} e.DateTime AS DateTested, e.Name AS TestName, "
        f"j.ID AS JobNumber "
        f"FROM JOB j JOIN EXECUTED_TEST e ON e.Job = j.ID "
        f"WHERE LTRIM(RTRIM(j.Asset)) = ? AND e.Name LIKE ? "
        f"  AND e.DateTime >= ? AND e.DateTime <= ? "
        f"ORDER BY e.DateTime DESC",
        (asset.strip(), f"%{name}%", date_from, date_to),
    )


def _omicron_history(test: dict[str, Any], asset: str, date_from: str, date_to: str,
                     limit: int) -> dict[str, Any]:
    name = test["omicronName"]
    header, data = test.get("headerTable"), test.get("dataTable")

    if not (header and data and _columns(data)):
        # No measurement table mapped (or it is absent here): the executions
        # themselves are the history, which still gives dates and job numbers.
        return {
            "columns": _EXECUTION_COLUMNS,
            "rows": _executions(name, asset, date_from, date_to, limit),
            "dateColumn": "DateTested",
            "message": "No measurement table is mapped for this test, so only the "
                       "test executions are listed.",
        }

    cols = _columns(data)
    select = ", ".join(f"d.[{c['name']}]" for c in cols)
    rows = db.query(
        f"SELECT TOP {limit} e.DateTime AS DateTested, j.ID AS JobNumber, {select} "
        f"FROM JOB j "
        f"JOIN EXECUTED_TEST e ON e.Job = j.ID "
        f"JOIN {header} t ON t.Job = j.ID "
        f"JOIN {data} d ON d.Parent = t.ID "
        f"WHERE LTRIM(RTRIM(j.Asset)) = ? AND e.Name LIKE ? "
        f"  AND e.DateTime >= ? AND e.DateTime <= ? "
        f"ORDER BY e.DateTime DESC",
        (asset.strip(), f"%{name}%", date_from, date_to),
    )
    if not rows:
        # Some units record an execution under this name but store nothing in the
        # mapped measurement table. Listing the runs is more honest than an empty
        # grid under a side panel that promises records.
        runs = _executions(name, asset, date_from, date_to, limit)
        if runs:
            return {"columns": _EXECUTION_COLUMNS, "rows": runs,
                    "dateColumn": "DateTested",
                    "message": f"This asset has {len(runs)} run(s) of the test, but "
                               f"no measurements stored in {data}. Only the runs are "
                               f"listed."}

    columns = ([{"name": "DateTested", "type": "datetime", "numeric": False, "date": True},
                {"name": "JobNumber", "type": "int", "numeric": True, "date": False}]
               + cols)
    return {"columns": columns, "rows": rows, "dateColumn": "DateTested",
            "message": "One row per measurement; a test execution normally "
                       "contributes several."}


def test_history(asset: str, test_id: str, date_from: str = OPEN_FROM,
                 date_to: str = OPEN_TO, limit: int = 200) -> dict[str, Any] | None:
    """Every stored record of one test for one asset, newest first.

    Returns ``None`` for an unknown test id so the caller can answer 404.
    """
    test = CATALOGUE.get(test_id)
    if not test:
        return None

    limit = max(1, min(int(limit), MAX_ROWS))
    try:
        if test["kind"] == "omicron":
            body = _omicron_history(test, asset, date_from, date_to, limit)
        else:
            body = _table_history(test, asset, date_from, date_to, limit)
    except db.DatabaseError as exc:
        log.warning("history failed for %s/%s: %s", asset, test_id, exc)
        body = {"columns": [], "rows": [], "message": str(exc)}

    return {"asset": asset, "test": test, "limit": limit,
            "truncated": len(body.get("rows") or []) >= limit, **body}
