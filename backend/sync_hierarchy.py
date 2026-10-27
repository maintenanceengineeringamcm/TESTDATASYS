"""Copy the CEB asset hierarchy from the Tomms CMMS into the local staging table.

Fills `CEB_TRANSMISSION.dbo.Tomms_CEBT` from `Tomms_CEBT.dbo.ast_mst`, so the
asset navigator can show `ast_mst_asset_shortdesc` - the name an engineer wrote
- instead of a name derived from the asset code.

Use this when the API host cannot reach the CMMS at request time. If it can,
set `HI_TOMMS_DB_SERVER` and the navigator reads `ast_mst` live; no sync needed.

    python sync_hierarchy.py --server CMMSHOST\\SQLEXPRESS
    python sync_hierarchy.py --dry-run            # report, write nothing

Per doc 13, structure is never delta-synced: re-parenting and deletes corrupt a
tree quietly. This does a full replace inside one transaction - 150k rows is
seconds, and correctness is guaranteed.

The source is opened read-only. Nothing is ever written back to the CMMS.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import pyodbc

from config import Config, connection_string, odbc_driver

log = logging.getLogger("hi.sync")

# Doc 6.1, narrowed to what the staging table holds. `line_name` carries the
# LINE-branch name so line plant keeps a human label too.
SOURCE_SQL = """
SELECT LTRIM(RTRIM(m.ast_mst_asset_no))        AS asset_no,
       LTRIM(RTRIM(m.ast_mst_asset_shortdesc)) AS short_desc,
       LTRIM(RTRIM(m.ast_mst_asset_status))    AS status,
       m.RowID                                 AS row_id
FROM ast_mst m
WHERE m.site_cd = ?
  AND m.ast_mst_asset_no IS NOT NULL
  AND LTRIM(RTRIM(m.ast_mst_asset_no)) <> ''
"""

# The staging table as shipped does not fit what the CMMS actually holds, so
# the schema is brought into line before every load. All three statements are
# idempotent, and none touches a row's contents:
#
# 1. No status column at all. Adding one is what makes the ISF filter live;
#    without it every asset reads as unknown status.
# 2. `tomms_asset_no` is varchar(25), but `ast_mst_asset_no` is varchar(30) and
#    648 live asset numbers are longer than 25 - they raised
#    "String data, right truncation: length 54 buffer 50" (pyodbc counts the
#    wide-char buffer in bytes: 50 bytes = 25 characters).
# 3. `asset_desc` is NOT NULL, but one CMMS row has no short description.
#    Widening the column is not enough; the load writes '' for those.
ENSURE_SCHEMA = """
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.Tomms_CEBT')
                 AND name = 'ast_mst_asset_status')
    ALTER TABLE dbo.Tomms_CEBT ADD ast_mst_asset_status varchar(6) NULL;

IF EXISTS (SELECT 1 FROM sys.columns
           WHERE object_id = OBJECT_ID('dbo.Tomms_CEBT')
             AND name = 'tomms_asset_no' AND max_length < 30)
    ALTER TABLE dbo.Tomms_CEBT ALTER COLUMN tomms_asset_no varchar(30) NULL;
"""


def _connect(conn_str: str, readonly: bool = False) -> pyodbc.Connection:
    kwargs = {"timeout": Config.DB_TIMEOUT}
    if readonly:
        kwargs["readonly"] = True
    return pyodbc.connect(conn_str, **kwargs)


def _source_connection_string(server: str, database: str) -> str:
    parts = [
        f"DRIVER={{{odbc_driver()}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        "TrustServerCertificate=yes",
    ]
    if Config.TOMMS_DB_TRUSTED and not Config.TOMMS_DB_USER:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={Config.TOMMS_DB_USER}")
        parts.append(f"PWD={Config.TOMMS_DB_PASSWORD}")
    return ";".join(parts) + ";"


def fetch(server: str, database: str, site: str) -> list[tuple]:
    log.info("reading %s/%s (site %s)...", server, database, site)
    with _connect(_source_connection_string(server, database), readonly=True) as cx:
        cur = cx.cursor()
        cur.execute(SOURCE_SQL, site)
        rows = [(r.asset_no, r.short_desc, r.status, r.row_id) for r in cur.fetchall()]
    log.info("read %s rows", f"{len(rows):,}")
    return rows


def load(rows: list[tuple]) -> int:
    """Replace the staging table's contents in one transaction."""
    with _connect(connection_string()) as cx:
        cx.autocommit = False
        cur = cx.cursor()
        cur.execute(ENSURE_SCHEMA)
        # Full replace, per doc 13 - a delta cannot see deletes, and a row that
        # vanished upstream would linger here forever.
        cur.execute("DELETE FROM dbo.Tomms_CEBT")
        cur.fast_executemany = True
        # `tomms_id` is NOT NULL with no identity and no default, so the load
        # has to number the rows itself; `asset_desc` is NOT NULL, so an asset
        # the CMMS never named is stored with an empty description rather than
        # failing the whole batch.
        cur.executemany(
            "INSERT INTO dbo.Tomms_CEBT "
            "(tomms_id, tomms_asset_no, asset_desc, ast_mst_asset_status, mst_RowID) "
            "VALUES (?, ?, ?, ?, ?)",
            [(i, asset_no, desc or "", status, row_id)
             for i, (asset_no, desc, status, row_id) in enumerate(rows, start=1)],
        )
        cx.commit()
    return len(rows)


def report(rows: list[tuple]) -> None:
    """The checks from doc 11 that this script can answer on its own."""
    total = len(rows)
    named = sum(1 for r in rows if (r[1] or "").strip() not in ("", "N/A"))
    codes = [r[0] for r in rows]
    duplicates = len(codes) - len(set(c.upper() for c in codes))
    statuses: dict[str, int] = {}
    for r in rows:
        key = (r[2] or "").strip().upper() or "(blank)"
        statuses[key] = statuses.get(key, 0) + 1

    log.info("assets            : %s", f"{total:,}")
    log.info("with a short desc : %s (%.1f%%)", f"{named:,}",
             100 * named / total if total else 0)
    log.info("duplicate keys    : %s   (doc 11 check 5 expects 0)", duplicates)
    for code, n in sorted(statuses.items(), key=lambda kv: -kv[1]):
        log.info("  status %-8s: %s", code, f"{n:,}")
    if duplicates:
        log.warning("duplicate asset numbers present - the tree build will reject them")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", default=Config.TOMMS_DB_SERVER or Config.DB_SERVER,
                        help="SQL Server hosting the Tomms CMMS")
    parser.add_argument("--database", default=Config.TOMMS_DB_NAME)
    parser.add_argument("--site", default=Config.TOMMS_SITE_CD)
    parser.add_argument("--dry-run", action="store_true",
                        help="read and report, but write nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    started = time.perf_counter()

    try:
        rows = fetch(args.server, args.database, args.site)
    except pyodbc.Error as exc:
        log.error("cannot read the CMMS: %s", exc)
        log.error("check --server/--database, and that the login can read ast_mst")
        return 2

    if not rows:
        log.error("no rows for site '%s' - nothing written", args.site)
        return 1

    report(rows)

    if args.dry_run:
        log.info("dry run - staging table left unchanged")
        return 0

    try:
        written = load(rows)
    except pyodbc.Error as exc:
        log.error("write failed, staging table rolled back: %s", exc)
        return 3

    log.info("wrote %s rows in %.1fs", f"{written:,}", time.perf_counter() - started)
    log.info("restart the API (or wait for the cache to expire) to pick up the names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
