"""Copy the three CMMS tables the HI system reads into a database on another
SQL Server instance - of any version.

Why this exists: Tomms_CEBT lives on SQL Server 2025, and a SQL Server backup
only restores onto the same or a newer version. A SQL Server 2022 Express
instance (the one Windows Server 2016 can run) therefore cannot restore
Tomms_CEBT_HI.bak. Copying the rows instead of the backup avoids that.

What it copies (same rules as create_tomms_slim.sql):
    ast_mst   rows of site CEBT
    ast_det   rows belonging to those ast_mst rows
    cf_label  all rows
with the same indexes, and checks the row counts.

The source is only read. The target database is dropped and rebuilt, so
re-running the script is how you refresh the copy.

Usage (Windows authentication on both sides):
    python copy_tomms_slim.py --source-server DESKTOP-E3R1QOH --source-db Tomms_CEBT
                              --target-server DESKTOP-E3R1QOH\\SQLEXPRESS
Optional:
    --target-db Tomms_CEBT_HI   (default)
    --backup-dir D:\\HI_Backup  back the target up to this folder afterwards
                                (a folder the target SQL Server service can write to)
"""
import argparse
import sys
import time

import pyodbc

TABLES = ["ast_mst", "ast_det", "cf_label"]
# Created on the empty tables, before the rows go in: building them afterwards
# needs one large sort, and a memory-starved SQL Server (Express on a busy
# machine) can wait on that memory grant indefinitely.
INDEXES = {
    "ast_mst": ["CREATE UNIQUE CLUSTERED INDEX cx_ast_mst ON dbo.ast_mst (RowID)",
                "CREATE INDEX ix_ast_mst_asset ON dbo.ast_mst (site_cd, ast_mst_asset_no) "
                "INCLUDE (ast_mst_asset_shortdesc, ast_mst_asset_status)"],
    "ast_det": ["CREATE CLUSTERED INDEX cx_ast_det ON dbo.ast_det (mst_RowID)"],
    "cf_label": ["CREATE CLUSTERED INDEX cx_cf_label ON dbo.cf_label (table_name, language_cd, column_name)"],
}
# Rows are read in clustered-key order so every insert appends.
ORDER = {"ast_mst": "RowID", "ast_det": "mst_RowID", "cf_label": "table_name, language_cd, column_name"}
# Old LOB types are created as their modern equivalents; rowversion cannot be
# inserted into and is not used, so it is left out.
TYPE_MAP = {"text": "varchar(max)", "ntext": "nvarchar(max)", "image": "varbinary(max)"}
SKIP_TYPES = {"timestamp"}
BATCH = 2000


def connect(server, db="master", autocommit=False):
    driver = next((d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
                   if d in pyodbc.drivers()), None)
    if not driver:
        sys.exit("No 'ODBC Driver 17/18 for SQL Server' installed.")
    return pyodbc.connect(f"DRIVER={{{driver}}};SERVER={server};DATABASE={db};"
                          "Trusted_Connection=yes;TrustServerCertificate=yes;",
                          autocommit=autocommit, timeout=60)


def columns(cur, table):
    cur.execute("""
        SELECT c.name, t.name, c.max_length, c.precision, c.scale, c.is_nullable
        FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id
        WHERE c.object_id = OBJECT_ID(?) ORDER BY c.column_id""", f"dbo.{table}")
    out = []
    for name, typ, length, prec, scale, nullable in cur.fetchall():
        if typ in SKIP_TYPES:
            continue
        if typ in TYPE_MAP:
            decl = TYPE_MAP[typ]
        elif typ in ("varchar", "char", "varbinary", "binary"):
            decl = f"{typ}({'max' if length == -1 else length})"
        elif typ in ("nvarchar", "nchar"):
            decl = f"{typ}({'max' if length == -1 else length // 2})"
        elif typ in ("decimal", "numeric"):
            decl = f"{typ}({prec},{scale})"
        elif typ in ("datetime2", "time", "datetimeoffset"):
            decl = f"{typ}({scale})"
        else:
            decl = typ
        out.append((name, decl, nullable))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-server", required=True)
    ap.add_argument("--source-db", default="Tomms_CEBT")
    ap.add_argument("--target-server", required=True)
    ap.add_argument("--target-db", default="Tomms_CEBT_HI")
    ap.add_argument("--site", default="CEBT")
    ap.add_argument("--backup-dir", default="")
    a = ap.parse_args()
    if a.source_server.lower() == a.target_server.lower() and a.source_db.lower() == a.target_db.lower():
        sys.exit("Source and target are the same database - the target is dropped, so refusing.")
    t0 = time.time()

    src = connect(a.source_server, a.source_db).cursor()
    master = connect(a.target_server, autocommit=True).cursor()
    db = a.target_db.replace("]", "]]")
    print(f"1/4 Recreating [{a.target_db}] on {a.target_server} ...", flush=True)
    master.execute(f"IF DB_ID(N'{db}') IS NOT NULL BEGIN "
                   f"ALTER DATABASE [{db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{db}]; END")
    master.execute(f"CREATE DATABASE [{db}]")
    master.execute(f"ALTER DATABASE [{db}] SET RECOVERY SIMPLE")
    tgt_conn = connect(a.target_server, a.target_db)
    tgt = tgt_conn.cursor()
    tgt.fast_executemany = True

    where = {
        "ast_mst": ("WHERE site_cd = ?", [a.site]),
        "ast_det": ("WHERE mst_RowID IN (SELECT RowID FROM dbo.ast_mst WHERE site_cd = ?)", [a.site]),
        "cf_label": ("", []),
    }
    counts = {}
    for table in TABLES:
        cols = columns(src, table)
        names = ", ".join(f"[{n}]" for n, _, _ in cols)
        ddl = ",\n  ".join(f"[{n}] {d} {'NULL' if nl else 'NOT NULL'}" for n, d, nl in cols)
        tgt.execute(f"CREATE TABLE dbo.[{table}] (\n  {ddl}\n)")
        for stmt in INDEXES[table]:
            tgt.execute(stmt)
        tgt_conn.commit()
        lob = [i for i, (_, d, _) in enumerate(cols) if d.endswith("(max)")]
        sql = f"INSERT INTO dbo.[{table}] ({names}) VALUES ({', '.join('?' * len(cols))})"
        # (max) columns defeat fast_executemany's fixed buffers; send those rows normally.
        tgt.fast_executemany = not lob
        cond, params = where[table]
        src.execute(f"SELECT {names} FROM dbo.[{table}] {cond} ORDER BY {ORDER[table]}", params)
        n = 0
        print(f"2/4 Copying {table} ...", flush=True)
        while True:
            rows = src.fetchmany(BATCH)
            if not rows:
                break
            tgt.executemany(sql, [tuple(r) for r in rows])
            tgt_conn.commit()
            n += len(rows)
            if n % 20000 < BATCH:
                print(f"      {n:,} rows  {time.time() - t0:.0f}s", flush=True)
        counts[table] = n

    print("3/4 Verifying ...", flush=True)
    ok = True
    for table in TABLES:
        cond, params = where[table]
        src.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{table}] {cond}", params)
        s = src.fetchone()[0]
        tgt.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{table}]")
        t = tgt.fetchone()[0]
        ok &= s == t
        print(f"      {table:9} source {s:>8,}  copied {t:>8,}  {'OK' if s == t else 'MISMATCH'}")
    if not ok:
        sys.exit("Row counts differ - the copy is incomplete.")

    if a.backup_dir:
        f = a.backup_dir.rstrip("\\/") + "\\" + a.target_db + ".bak"
        print(f"4/4 Backing up to {f} ...", flush=True)
        master.execute(f"BACKUP DATABASE [{db}] TO DISK = ? WITH INIT, CHECKSUM", f)
        while master.nextset():
            pass
    else:
        print("4/4 No --backup-dir given, skipping the backup.")
    print(f"Done in {time.time() - t0:.0f}s.")


if __name__ == "__main__":
    main()
