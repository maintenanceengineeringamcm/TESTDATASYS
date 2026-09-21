"""Restore the .bak files in the backup folder into the SQL Server container.

Runs once as the `db-init` service before the API starts. It is safe to run
again: a database that already exists is left untouched, so a restart never
overwrites data. To force a fresh restore, drop the database first (see
DEPLOYMENT_DOCKER.md).

For every *.bak file in BACKUP_DIR it:
  1. reads the backup header to learn the database name (no renaming needed),
  2. reads the file list and MOVEs each data/log file into the container's
     data folder - the original Windows paths (C:\\Program Files\\...) do not
     exist on Linux,
  3. restores the newest full backup set in the file.

Then it creates the read-only login the application uses (HI_DB_USER) with
db_datareader on every restored database. The API never writes to SQL Server.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pyodbc

SQL_HOST = os.getenv("HI_DB_SERVER", "mssql")
SA_PASSWORD = os.environ["MSSQL_SA_PASSWORD"]
APP_USER = os.getenv("HI_DB_USER", "hi_app")
APP_PASSWORD = os.environ["HI_DB_PASSWORD"]
# Same folder, seen from two containers: this one lists the files, SQL Server
# (which does the actual reading) sees them under SQL_BACKUP_DIR.
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
SQL_BACKUP_DIR = os.getenv("SQL_BACKUP_DIR", "/var/opt/mssql/backup")
SQL_DATA_DIR = os.getenv("SQL_DATA_DIR", "/var/opt/mssql/data")
REQUIRED = [d.strip() for d in os.getenv("HI_REQUIRED_DATABASES", "").split(",") if d.strip()]


def log(msg: str) -> None:
    print(f"[db-init] {msg}", flush=True)


def connect() -> pyodbc.Connection:
    conn_str = (f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQL_HOST};"
                f"DATABASE=master;UID=sa;PWD={SA_PASSWORD};TrustServerCertificate=yes;")
    for attempt in range(60):
        try:
            # RESTORE cannot run inside a transaction, hence autocommit.
            return pyodbc.connect(conn_str, autocommit=True, timeout=10)
        except pyodbc.Error as exc:
            if attempt == 0:
                log("waiting for SQL Server to accept connections...")
            last = exc
            time.sleep(5)
    raise SystemExit(f"SQL Server did not come up: {last}")


def rows(cur: pyodbc.Cursor, sql: str, *params) -> list[dict]:
    cur.execute(sql, *params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def drain(cur: pyodbc.Cursor) -> None:
    """Consume every result set so RESTORE runs to completion."""
    while cur.nextset():
        pass


def quote(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def restore(cur: pyodbc.Cursor, bak: Path) -> str | None:
    sql_path = f"{SQL_BACKUP_DIR}/{bak.name}"
    headers = rows(cur, "RESTORE HEADERONLY FROM DISK = ?", sql_path)
    full = [h for h in headers if h.get("BackupType") == 1]
    if not full:
        log(f"{bak.name}: no full database backup inside - skipped")
        return None
    newest = max(full, key=lambda h: h["Position"])
    db_name, position = newest["DatabaseName"], newest["Position"]

    if rows(cur, "SELECT 1 AS x FROM sys.databases WHERE name = ?", db_name):
        log(f"{bak.name}: database {db_name} already exists - left as is")
        return db_name

    files = rows(cur, f"RESTORE FILELISTONLY FROM DISK = ? WITH FILE = {int(position)}", sql_path)
    moves, params, data_no, log_no = [], [], 0, 0
    for f in files:
        kind = f["Type"]
        if kind == "L":
            target = f"{SQL_DATA_DIR}/{db_name}_log{log_no}.ldf"
            log_no += 1
        elif kind == "D":
            ext = ".mdf" if data_no == 0 else ".ndf"
            target = f"{SQL_DATA_DIR}/{db_name}_data{data_no}{ext}"
            data_no += 1
        else:  # full-text catalogue or FILESTREAM container: a folder
            target = f"{SQL_DATA_DIR}/{db_name}_{f['LogicalName']}"
        moves.append("MOVE ? TO ?")
        params += [f["LogicalName"], target]

    size_gb = bak.stat().st_size / 1024 ** 3
    log(f"{bak.name}: restoring {db_name} ({size_gb:.1f} GB backup, set {position}) - "
        f"large databases take several minutes...")
    started = time.time()
    cur.execute(f"RESTORE DATABASE {quote(db_name)} FROM DISK = ? WITH FILE = {int(position)}, "
                + ", ".join(moves) + ", STATS = 10", sql_path, *params)
    drain(cur)
    log(f"{bak.name}: {db_name} restored in {time.time() - started:.0f} s")
    return db_name


def literal(value: str) -> str:
    """N'...' string literal - CREATE/ALTER LOGIN do not accept a parameter."""
    return "N'" + value.replace("'", "''") + "'"


def grant_read_only(cur: pyodbc.Cursor, databases: list[str]) -> None:
    user = quote(APP_USER)
    if not rows(cur, "SELECT 1 AS x FROM sys.server_principals WHERE name = ?", APP_USER):
        cur.execute(f"CREATE LOGIN {user} WITH PASSWORD = {literal(APP_PASSWORD)}, "
                    f"CHECK_POLICY = OFF, DEFAULT_DATABASE = {quote(databases[0]) if databases else 'master'}")
        log(f"created login {APP_USER}")
    else:
        # Keep the login in step with .env if the password was changed there.
        cur.execute(f"ALTER LOGIN {user} WITH PASSWORD = {literal(APP_PASSWORD)}")
    for db in databases:
        cur.execute(f"USE {quote(db)}")
        if rows(cur, "SELECT 1 AS x FROM sys.database_principals WHERE name = ?", APP_USER):
            # A user restored from the old server is orphaned (its SID belonged
            # to another server's login): re-link it, or replace it when it
            # cannot be re-linked (e.g. it was created WITHOUT LOGIN).
            try:
                cur.execute(f"ALTER USER {user} WITH LOGIN = {user}")
            except pyodbc.Error:
                cur.execute(f"DROP USER {user}")
                cur.execute(f"CREATE USER {user} FOR LOGIN {user}")
        else:
            cur.execute(f"CREATE USER {user} FOR LOGIN {user}")
        cur.execute(f"ALTER ROLE db_datareader ADD MEMBER {user}")
        log(f"{db}: {APP_USER} has read-only access")
    cur.execute("USE master")


def main() -> int:
    baks = sorted(p for p in BACKUP_DIR.glob("*") if p.suffix.lower() == ".bak")
    if not baks:
        log(f"no .bak files in {BACKUP_DIR} - put the backups in the folder set as "
            f"BACKUP_DIR in .env")
    cur = connect().cursor()
    restored = []
    for bak in baks:
        try:
            name = restore(cur, bak)
        except pyodbc.Error as exc:
            log(f"{bak.name}: RESTORE FAILED - {exc}")
            return 1
        if name:
            restored.append(name)

    present = {r["name"] for r in rows(cur, "SELECT name FROM sys.databases")}
    missing = [d for d in REQUIRED if d not in present]
    if missing:
        log(f"MISSING databases the application needs: {', '.join(missing)}")
        return 1
    grant_read_only(cur, [d for d in (REQUIRED or restored) if d in present])
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
