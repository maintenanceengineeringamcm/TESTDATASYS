"""Thin SQL Server access layer.

Everything goes through :func:`query`, which returns plain dicts with JSON-safe
values. Callers never build SQL by string interpolation - asset numbers contain
'/' and '_' and must always travel as parameters.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Sequence

import pyodbc

from config import (Config, connection_string, tomms_configured,
                    tomms_connection_string)

log = logging.getLogger(__name__)

_local = threading.local()


class DatabaseError(RuntimeError):
    """Raised when the database is unreachable or a query fails."""


def _connection() -> pyodbc.Connection:
    """One connection per thread, reopened if the server dropped it."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1").fetchone()
            return conn
        except pyodbc.Error:
            try:
                conn.close()
            except pyodbc.Error:
                pass
            _local.conn = None
    try:
        conn = pyodbc.connect(connection_string(), timeout=Config.DB_TIMEOUT)
    except pyodbc.Error as exc:
        raise DatabaseError(f"Cannot connect to {Config.DB_SERVER}/{Config.DB_NAME}: {exc}") from exc
    conn.timeout = Config.DB_TIMEOUT
    _local.conn = conn
    return conn


def _tomms_connection() -> pyodbc.Connection:
    """Read-only connection to the Tomms CMMS, kept apart from the HI database.

    Its own thread-local slot: the two databases can live on different servers,
    and reusing one connection for both would silently query the wrong one.
    """
    conn = getattr(_local, "tomms", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1").fetchone()
            return conn
        except pyodbc.Error:
            try:
                conn.close()
            except pyodbc.Error:
                pass
            _local.tomms = None
    if not tomms_configured():
        raise DatabaseError("No Tomms CMMS server configured (HI_TOMMS_DB_SERVER).")
    try:
        # A shorter timeout than the HI database on purpose: the navigator has
        # a working fallback, so a misconfigured CMMS should degrade quickly
        # rather than hold a request open for a minute.
        conn = pyodbc.connect(tomms_connection_string(),
                              timeout=Config.TOMMS_DB_TIMEOUT, readonly=True)
    except pyodbc.Error as exc:
        raise DatabaseError(
            f"Cannot connect to {Config.TOMMS_DB_SERVER}/{Config.TOMMS_DB_NAME}: {exc}"
        ) from exc
    conn.timeout = Config.DB_TIMEOUT
    _local.tomms = conn
    return conn


def _clean(value: Any) -> Any:
    """Coerce driver types into JSON-serialisable Python values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, str):
        return value.strip()
    return value


def query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Run a SELECT and return a list of dicts."""
    cur = _connection().cursor()
    try:
        cur.execute(sql, tuple(params))
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, (_clean(v) for v in row))) for row in cur.fetchall()]
    except pyodbc.Error as exc:
        raise DatabaseError(f"Query failed: {exc}\nSQL: {sql.strip()[:400]}") from exc
    finally:
        cur.close()


def tomms_query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Run a SELECT against the Tomms CMMS. Raises DatabaseError if unreachable."""
    cur = _tomms_connection().cursor()
    try:
        cur.execute(sql, tuple(params))
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, (_clean(v) for v in row))) for row in cur.fetchall()]
    except pyodbc.Error as exc:
        raise DatabaseError(
            f"Tomms query failed: {exc}\nSQL: {sql.strip()[:400]}") from exc
    finally:
        cur.close()


def tomms_query_long(sql: str, params: Sequence[Any] = (),
                     timeout: int = 600) -> list[dict[str, Any]]:
    """A CMMS query allowed to run far past the normal timeout.

    `ast_det` and `ast_rat` are unindexed heaps on a memory-starved instance
    (ASSET_ATTRIBUTES_INTEGRATION.md section 10), so a whole-table pull takes
    minutes. Only scheduled jobs may use this - never an HTTP request. The
    thread-local connection's timeout is restored afterwards so a long pull
    cannot leave every later query on this thread waiting ten minutes.
    """
    conn = _tomms_connection()
    previous = conn.timeout
    conn.timeout = timeout
    cur = conn.cursor()
    try:
        cur.execute(sql, tuple(params))
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, (_clean(v) for v in row))) for row in cur.fetchall()]
    except pyodbc.Error as exc:
        raise DatabaseError(
            f"Tomms query failed: {exc}\nSQL: {sql.strip()[:400]}") from exc
    finally:
        cur.close()
        conn.timeout = previous


def tomms_health() -> dict[str, Any]:
    """Reachability probe for the CMMS, reported alongside the HI database.

    Cached: /api/health is polled by the UI, and each poll can land on a fresh
    Flask worker thread whose thread-local connection is cold. Without this the
    header status pill would pay a full connect on every tick.
    """
    return cached("tomms:health", _tomms_health, ttl=60)


def _tomms_health() -> dict[str, Any]:
    if not tomms_configured():
        return {"configured": False, "connected": False,
                "reason": "HI_TOMMS_DB_SERVER is not set."}
    started = time.perf_counter()
    try:
        # Row count from catalog metadata, not COUNT(*). `ast_mst` carries one
        # index and 150k rows, so a real count is a full scan taking ~19s - far
        # too slow for a probe the UI polls. This is approximate by definition,
        # which is fine for "is the CMMS reachable and roughly how big".
        assets = scalar_tomms(
            "SELECT SUM(p.rows) FROM sys.partitions p "
            "WHERE p.object_id = OBJECT_ID('ast_mst') AND p.index_id IN (0, 1)")
        return {"configured": True, "connected": True,
                "server": Config.TOMMS_DB_SERVER, "database": Config.TOMMS_DB_NAME,
                "assets": assets,
                "latencyMs": round((time.perf_counter() - started) * 1000, 1)}
    except DatabaseError as exc:
        return {"configured": True, "connected": False,
                "server": Config.TOMMS_DB_SERVER, "database": Config.TOMMS_DB_NAME,
                "error": str(exc),
                "latencyMs": round((time.perf_counter() - started) * 1000, 1)}


def scalar_tomms(sql: str, params: Sequence[Any] = ()) -> Any:
    rows = tomms_query(sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def query_one(sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: Sequence[Any] = ()) -> Any:
    row = query_one(sql, params)
    if not row:
        return None
    return next(iter(row.values()))


def in_clause(values: Iterable[Any]) -> str:
    """Build a parameter placeholder list, e.g. '(?, ?, ?)'."""
    n = len(list(values))
    if n == 0:
        return "(NULL)"
    return "(" + ", ".join("?" * n) + ")"


def health() -> dict[str, Any]:
    """Connectivity probe used by /api/health."""
    started = time.perf_counter()
    try:
        version = scalar("SELECT @@VERSION")
        tables = scalar(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'"
        )
        return {
            "connected": True,
            "server": Config.DB_SERVER,
            "database": Config.DB_NAME,
            "driver": connection_string().split("}")[0].split("{")[-1],
            "version": (version or "").split("\n")[0].strip(),
            "tables": tables,
            "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        }
    except DatabaseError as exc:
        return {
            "connected": False,
            "server": Config.DB_SERVER,
            "database": Config.DB_NAME,
            "error": str(exc),
            "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        }


# --------------------------------------------------------------------------
# Tiny TTL cache. The fleet health-index sweep touches ~20 tables per asset,
# so repeated dashboard renders must not re-query.
# --------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def cached(key: str, producer, ttl: int | None = None):
    ttl = Config.CACHE_TTL if ttl is None else ttl
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = producer()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def clear_cache(prefix: str = "") -> int:
    with _cache_lock:
        keys = [k for k in _cache if k.startswith(prefix)]
        for k in keys:
            del _cache[k]
        return len(keys)
