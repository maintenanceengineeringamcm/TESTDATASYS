"""Storage for scoring-configuration overrides.

Deliberately a separate database from CEB_TRANSMISSION: the source system stays
read-only, and everything an engineer edits here lives in its own store that can
be backed up, audited and rolled back without touching plant data.

SQLite by default so the service runs with no install step. Point
`CFG_DB_PATH` elsewhere to relocate the file.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("CFG_DB_PATH", Path(__file__).resolve().parent / "config_store.db"))

_lock = threading.Lock()
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS band_override (
    asset_type   TEXT NOT NULL,
    band_name    TEXT NOT NULL,
    bands_json   TEXT NOT NULL,      -- [{sequence, rangeFrom, rangeTo, score}, ...]
    updated_at   TEXT NOT NULL,
    updated_by   TEXT NOT NULL DEFAULT 'unknown',
    note         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (asset_type, band_name)
);

CREATE TABLE IF NOT EXISTS weight_override (
    asset_type      TEXT PRIMARY KEY,
    components_json TEXT NOT NULL,   -- {componentCode: weight}
    updated_at      TEXT NOT NULL,
    updated_by      TEXT NOT NULL DEFAULT 'unknown',
    note            TEXT NOT NULL DEFAULT ''
);

-- Append-only history. Scoring thresholds drive maintenance decisions, so every
-- edit must remain answerable months later.
CREATE TABLE IF NOT EXISTS change_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,       -- band | weight
    asset_type  TEXT NOT NULL,
    band_name   TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,       -- save | reset
    before_json TEXT,
    after_json  TEXT,
    changed_at  TEXT NOT NULL,
    changed_by  TEXT NOT NULL DEFAULT 'unknown',
    note        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_change_log_at ON change_log (changed_at DESC);
"""


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init() -> None:
    with _lock:
        _conn().executescript(SCHEMA)
        _conn().commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Bands
# --------------------------------------------------------------------------
def _clean_bands(bands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalise a band list before it is stored."""
    out = []
    for i, b in enumerate(bands, start=1):
        try:
            lo = float(b["rangeFrom"])
            hi = float(b["rangeTo"])
            score = float(b["score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Band {i} is missing a numeric rangeFrom/rangeTo/score.") from exc
        if lo == hi:
            raise ValueError(f"Band {i} has an empty range ({lo} to {hi}).")
        out.append({
            "sequence": int(b.get("sequence") or i),
            "rangeFrom": lo,
            "rangeTo": hi,
            "score": score,
        })
    if not out:
        raise ValueError("At least one band is required.")
    out.sort(key=lambda b: b["sequence"])
    return out


def get_band(asset_type: str, band_name: str) -> dict[str, Any] | None:
    row = _conn().execute(
        "SELECT * FROM band_override WHERE asset_type=? AND band_name=?",
        (asset_type, band_name),
    ).fetchone()
    if not row:
        return None
    return {
        "assetType": row["asset_type"],
        "bandName": row["band_name"],
        "bands": json.loads(row["bands_json"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
        "note": row["note"],
    }


def all_bands() -> dict[str, dict[str, Any]]:
    """Every band override, keyed `assetType/bandName` for cheap lookup."""
    rows = _conn().execute("SELECT * FROM band_override").fetchall()
    return {
        f"{r['asset_type']}/{r['band_name']}": {
            "assetType": r["asset_type"],
            "bandName": r["band_name"],
            "bands": json.loads(r["bands_json"]),
            "updatedAt": r["updated_at"],
            "updatedBy": r["updated_by"],
            "note": r["note"],
        }
        for r in rows
    }


def save_band(asset_type: str, band_name: str, bands: list[dict[str, Any]],
              user: str = "unknown", note: str = "") -> dict[str, Any]:
    cleaned = _clean_bands(bands)
    before = get_band(asset_type, band_name)
    with _lock:
        conn = _conn()
        conn.execute(
            "INSERT INTO band_override (asset_type, band_name, bands_json, updated_at, "
            "updated_by, note) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(asset_type, band_name) DO UPDATE SET "
            "bands_json=excluded.bands_json, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by, note=excluded.note",
            (asset_type, band_name, json.dumps(cleaned), _now(), user, note),
        )
        conn.execute(
            "INSERT INTO change_log (kind, asset_type, band_name, action, before_json, "
            "after_json, changed_at, changed_by, note) VALUES (?,?,?,?,?,?,?,?,?)",
            ("band", asset_type, band_name, "save",
             json.dumps(before["bands"]) if before else None,
             json.dumps(cleaned), _now(), user, note),
        )
        conn.commit()
    return get_band(asset_type, band_name)  # type: ignore[return-value]


def reset_band(asset_type: str, band_name: str, user: str = "unknown") -> bool:
    before = get_band(asset_type, band_name)
    if not before:
        return False
    with _lock:
        conn = _conn()
        conn.execute("DELETE FROM band_override WHERE asset_type=? AND band_name=?",
                     (asset_type, band_name))
        conn.execute(
            "INSERT INTO change_log (kind, asset_type, band_name, action, before_json, "
            "after_json, changed_at, changed_by, note) VALUES (?,?,?,?,?,?,?,?,?)",
            ("band", asset_type, band_name, "reset", json.dumps(before["bands"]),
             None, _now(), user, "reverted to source configuration"),
        )
        conn.commit()
    return True


# --------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------
def get_weights(asset_type: str) -> dict[str, Any] | None:
    row = _conn().execute("SELECT * FROM weight_override WHERE asset_type=?",
                          (asset_type,)).fetchone()
    if not row:
        return None
    return {
        "assetType": row["asset_type"],
        "components": json.loads(row["components_json"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
        "note": row["note"],
    }


def all_weights() -> dict[str, dict[str, Any]]:
    rows = _conn().execute("SELECT * FROM weight_override").fetchall()
    return {
        r["asset_type"]: {
            "assetType": r["asset_type"],
            "components": json.loads(r["components_json"]),
            "updatedAt": r["updated_at"],
            "updatedBy": r["updated_by"],
            "note": r["note"],
        }
        for r in rows
    }


def save_weights(asset_type: str, components: dict[str, Any], user: str = "unknown",
                 note: str = "") -> dict[str, Any]:
    cleaned: dict[str, float] = {}
    for code, value in components.items():
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Weight for '{code}' is not a number.") from exc
        if v < 0:
            raise ValueError(f"Weight for '{code}' cannot be negative.")
        cleaned[str(code)] = v
    if not cleaned:
        raise ValueError("At least one component weight is required.")

    before = get_weights(asset_type)
    with _lock:
        conn = _conn()
        conn.execute(
            "INSERT INTO weight_override (asset_type, components_json, updated_at, "
            "updated_by, note) VALUES (?,?,?,?,?) "
            "ON CONFLICT(asset_type) DO UPDATE SET "
            "components_json=excluded.components_json, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by, note=excluded.note",
            (asset_type, json.dumps(cleaned), _now(), user, note),
        )
        conn.execute(
            "INSERT INTO change_log (kind, asset_type, band_name, action, before_json, "
            "after_json, changed_at, changed_by, note) VALUES (?,?,?,?,?,?,?,?,?)",
            ("weight", asset_type, "", "save",
             json.dumps(before["components"]) if before else None,
             json.dumps(cleaned), _now(), user, note),
        )
        conn.commit()
    return get_weights(asset_type)  # type: ignore[return-value]


def reset_weights(asset_type: str, user: str = "unknown") -> bool:
    before = get_weights(asset_type)
    if not before:
        return False
    with _lock:
        conn = _conn()
        conn.execute("DELETE FROM weight_override WHERE asset_type=?", (asset_type,))
        conn.execute(
            "INSERT INTO change_log (kind, asset_type, band_name, action, before_json, "
            "after_json, changed_at, changed_by, note) VALUES (?,?,?,?,?,?,?,?,?)",
            ("weight", asset_type, "", "reset", json.dumps(before["components"]),
             None, _now(), user, "reverted to source configuration"),
        )
        conn.commit()
    return True


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------
def history(limit: int = 100) -> list[dict[str, Any]]:
    rows = _conn().execute(
        "SELECT * FROM change_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        {
            "id": r["id"], "kind": r["kind"], "assetType": r["asset_type"],
            "bandName": r["band_name"], "action": r["action"],
            "before": json.loads(r["before_json"]) if r["before_json"] else None,
            "after": json.loads(r["after_json"]) if r["after_json"] else None,
            "changedAt": r["changed_at"], "changedBy": r["changed_by"],
            "note": r["note"],
        }
        for r in rows
    ]


def stats() -> dict[str, Any]:
    conn = _conn()
    return {
        "database": str(DB_PATH),
        "bandOverrides": conn.execute("SELECT COUNT(*) c FROM band_override").fetchone()["c"],
        "weightOverrides": conn.execute("SELECT COUNT(*) c FROM weight_override").fetchone()["c"],
        "changes": conn.execute("SELECT COUNT(*) c FROM change_log").fetchone()["c"],
    }
