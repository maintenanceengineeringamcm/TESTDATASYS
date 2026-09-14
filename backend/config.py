"""Runtime configuration.

Connection settings come from the environment (optionally via a .env file next
to this module) so that no credential is ever committed. Windows integrated
auth is the default and needs no secret at all.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load .env if python-dotenv is available; absence is not an error.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - optional dependency
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


class Config:
    # --- database -------------------------------------------------------
    # Note the instance: CEB_TRANSMISSION lives on SQLEXPRESS, while the Tomms
    # CMMS is on the default instance of the same machine. See TOMMS_DB_SERVER.
    DB_SERVER = os.getenv("HI_DB_SERVER", r"DESKTOP-E3R1QOH\SQLEXPRESS")
    DB_NAME = os.getenv("HI_DB_NAME", "CEB_TRANSMISSION")
    DB_TRUSTED = _bool("HI_DB_TRUSTED", True)
    DB_USER = os.getenv("HI_DB_USER", "")
    DB_PASSWORD = os.getenv("HI_DB_PASSWORD", "")
    DB_TIMEOUT = int(os.getenv("HI_DB_TIMEOUT", "60"))

    # --- server ---------------------------------------------------------
    HOST = os.getenv("HI_HOST", "127.0.0.1")
    PORT = int(os.getenv("HI_PORT", "5000"))
    DEBUG = _bool("HI_DEBUG", True)

    # Vite dev server origins allowed to call the API directly. In normal use the
    # Vite proxy keeps everything same-origin, so this only matters if the
    # frontend is served from somewhere else.
    CORS_ORIGINS = [
        o.strip()
        for o in os.getenv(
            "HI_CORS_ORIGINS",
            "http://localhost:5180,http://127.0.0.1:5180",
        ).split(",")
        if o.strip()
    ]

    # --- caching --------------------------------------------------------
    # Seconds to hold query results. The dashboard recomputes health indices
    # across the whole fleet, which is expensive; 15 minutes matches the
    # cadence the source tools used.
    CACHE_TTL = int(os.getenv("HI_CACHE_TTL", "900"))

    # --- engine behaviour flags ----------------------------------------
    # Each flag corresponds to a documented discrepancy in
    # HealthIndex_Automation_Spec.md section 9. Defaults implement the
    # "intended" reading; flipping a flag restores the literal legacy
    # behaviour. Every firing is logged (see core/hi_engine.py).
    DGA_PER_GAS_OWN_FIELD = _bool("HI_DGA_PER_GAS_OWN_FIELD", True)  # item 1
    DIRANA_SCORE_OWN_VALUE = _bool("HI_DIRANA_SCORE_OWN_VALUE", True)  # item 2
    AIO_IFTO_UNCROSSED = _bool("HI_AIO_IFTO_UNCROSSED", True)  # item 3
    SA_IR_USES_IR_FIELD = _bool("HI_SA_IR_USES_IR_FIELD", True)  # item 4
    OLTC_USES_CEB_OLTC = _bool("HI_OLTC_USES_CEB_OLTC", True)  # item 5
    EC_BAND_ASCENDING = _bool("HI_EC_BAND_ASCENDING", True)  # item 6

    # --- Tomms CMMS (asset hierarchy source) ----------------------------
    # The CMMS database holding `ast_mst`, whose `ast_mst_asset_shortdesc` is
    # the engineer-written name shown in the asset navigator. Read-only.
    #
    # NOTE the instance. The two databases live on the same machine but on
    # *different* SQL Server instances:
    #     CEB_TRANSMISSION -> DESKTOP-E3R1QOH\SQLEXPRESS   (SQL Server 2022)
    #     Tomms_CEBT       -> DESKTOP-E3R1QOH              (default, 2025)
    # So this cannot be derived from DB_SERVER by swapping the database name.
    #
    # Set to an empty string to skip the CMMS, in which case the navigator
    # falls back to the local `Tomms_CEBT` staging table and then to names
    # derived from the asset codes.
    TOMMS_DB_SERVER = os.getenv("HI_TOMMS_DB_SERVER", "DESKTOP-E3R1QOH")
    TOMMS_DB_NAME = os.getenv("HI_TOMMS_DB_NAME", "Tomms_CEBT")
    TOMMS_DB_TRUSTED = _bool("HI_TOMMS_DB_TRUSTED", True)
    TOMMS_DB_USER = os.getenv("HI_TOMMS_DB_USER", "")
    TOMMS_DB_PASSWORD = os.getenv("HI_TOMMS_DB_PASSWORD", "")
    # The site key that leads every composite key in the CMMS (doc 1).
    TOMMS_SITE_CD = os.getenv("HI_TOMMS_SITE_CD", "CEBT")
    # Deliberately shorter than DB_TIMEOUT - the hierarchy degrades to derived
    # names when the CMMS is slow, so waiting a full minute buys nothing.
    TOMMS_DB_TIMEOUT = int(os.getenv("HI_TOMMS_DB_TIMEOUT", "15"))

    # --- asset age (year of manufacture) --------------------------------
    # The AGE criterion is scored on `ast_det.ast_det_datetime1` in the CMMS -
    # "Year of Manufacture(G)" - read by core/attributes.py per
    # ASSET_ATTRIBUTES_INTEGRATION.md. See that module for why each of these
    # exists.
    #
    # Values below the floor are the source's 1900/1905 placeholders, not old
    # plant; values above the current year are data-entry typos. Both read as
    # "no year".
    MANUFACTURE_YEAR_MIN = int(os.getenv("HI_MANUFACTURE_YEAR_MIN", "1950"))
    # Whole-fleet map of asset -> year, so the snapshot sweep does not pay a
    # per-asset round trip 13,000 times. Refreshed by the daily job, hence a
    # day plus a margin.
    MANUFACTURE_YEAR_CACHE = os.getenv(
        "HI_MANUFACTURE_YEAR_CACHE", str(BASE_DIR / "snapshots" / "manufacture_years.json"))
    MANUFACTURE_YEAR_TTL_HOURS = float(os.getenv("HI_MANUFACTURE_YEAR_TTL_HOURS", "30"))
    # `ast_det` is an unindexed 150k-row heap on a memory-starved instance, so
    # the bulk pull takes ~4 minutes and needs far longer than TOMMS_DB_TIMEOUT.
    # Only the scheduled job triggers it.
    MANUFACTURE_YEAR_BULK_TIMEOUT = int(
        os.getenv("HI_MANUFACTURE_YEAR_BULK_TIMEOUT", "600"))

    # --- asset hierarchy ------------------------------------------------
    # Asset statuses admitted to the navigator tree. 'ISF' (In Service Full)
    # is the operational fleet; 'DEC' is deactivated plant, 'REU' to-be-reused,
    # 'ADS'/'DIS' awaiting-disposal and disposed. See section 14 of
    # ASSET_HIERARCHY_INTEGRATION.md for the full code list.
    HIERARCHY_STATUSES = frozenset(
        s.strip().upper()
        for s in os.getenv("HI_HIERARCHY_STATUSES", "ISF").split(",")
        if s.strip()
    )

    # An asset the status feed says nothing about. Keeping it is the safe
    # default: a partially-synced staging table would otherwise silently hide
    # in-service plant that the HI engine is actively scoring. Set to false
    # once the sync is known to be complete.
    HIERARCHY_KEEP_UNKNOWN_STATUS = _bool("HI_HIERARCHY_KEEP_UNKNOWN", True)

    # --- configuration microservice -------------------------------------
    # Owns engineer-edited score bands and weights in its own database. Optional
    # infrastructure: when unreachable the engine falls back to the values in
    # CEB_TRANSMISSION rather than failing to score.
    # --- built frontend --------------------------------------------------
    # In development the Vite dev server serves the UI and proxies /api here.
    # In production there is no Vite, so the API also serves the built SPA and
    # the whole system answers on one port - which is what makes plain
    # http://<server-ip>:5000/ work without a reverse proxy or CORS.
    FRONTEND_DIST = os.getenv(
        "HI_FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist"))

    CONFIG_SERVICE_URL = os.getenv("HI_CONFIG_SERVICE_URL", "http://127.0.0.1:5001")
    CONFIG_SERVICE_TIMEOUT = float(os.getenv("HI_CONFIG_SERVICE_TIMEOUT", "3"))
    CONFIG_SERVICE_TTL = int(os.getenv("HI_CONFIG_SERVICE_TTL", "20"))

    # --- snapshots ------------------------------------------------------
    # Optional shared secret for POST /api/snapshot/run. Leave unset while the
    # API is bound to localhost; set it if the API is exposed on a network.
    SNAPSHOT_TOKEN = os.getenv("HI_SNAPSHOT_TOKEN", "")

    # --- ML -------------------------------------------------------------
    ML_DATA_DIR = Path(os.getenv("HI_ML_DATA_DIR", str(BASE_DIR / "ml_data")))
    ML_MODEL_DIR = Path(os.getenv("HI_ML_MODEL_DIR", str(BASE_DIR / "ml_models")))
    # How to resolve the coarse "Low/Middle-temperature overheating" class,
    # which overlaps the finer Low- and Middle- classes: "drop" or "merge".
    ML_COARSE_LABEL_STRATEGY = os.getenv("HI_ML_COARSE_LABEL", "drop").strip().lower()


def odbc_driver() -> str:
    """Pick the best installed SQL Server ODBC driver.

    Preference order follows the source tools. Falls back to the legacy
    "SQL Server" driver, which is present on every Windows install.
    """
    preferred = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]
    try:
        import pyodbc

        installed = set(pyodbc.drivers())
    except Exception:  # pragma: no cover - pyodbc missing/broken
        return preferred[-1]
    for name in preferred:
        if name in installed:
            return name
    return preferred[-1]


def _connection_string(server: str, database: str, trusted: bool,
                       user: str, password: str) -> str:
    parts = [
        f"DRIVER={{{odbc_driver()}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        "TrustServerCertificate=yes",
    ]
    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={user}")
        parts.append(f"PWD={password}")
    return ";".join(parts) + ";"


def connection_string() -> str:
    return _connection_string(Config.DB_SERVER, Config.DB_NAME, Config.DB_TRUSTED,
                              Config.DB_USER, Config.DB_PASSWORD)


def tomms_configured() -> bool:
    """True when a Tomms CMMS server has been named."""
    return bool(Config.TOMMS_DB_SERVER.strip())


def tomms_connection_string() -> str:
    """Connection to the CMMS that owns `ast_mst`. Read-only by convention."""
    return _connection_string(Config.TOMMS_DB_SERVER.strip(), Config.TOMMS_DB_NAME,
                              Config.TOMMS_DB_TRUSTED, Config.TOMMS_DB_USER,
                              Config.TOMMS_DB_PASSWORD)
