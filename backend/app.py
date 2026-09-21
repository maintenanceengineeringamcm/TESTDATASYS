"""Flask API for the Transformer Asset Health Index & Analysis system."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import api_v1
import db
from config import Config
from core import assets as assets_mod
from core import (attributes, dga_status, dga_trend, duval, hi_engine, hierarchy,
                  history, ml, overrides, pentagon, readers, scoring, snapshots)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("hi.api")

app = Flask(__name__)
CORS(app, origins=Config.CORS_ORIGINS)
# Versioned public API with Swagger UI at /apidocs/.
api_v1.init_app(app)

OPEN_FROM = readers.OPEN_FROM
OPEN_TO = readers.OPEN_TO

# The dashboard and health-index table open on transformers. Every other asset
# type either has unusable score bands or is scored on age alone, so a
# fleet-wide default drowns 835 real results in 11,000 unscoreable ones.
# Callers pass `type=all` for the whole fleet, or any specific type code.
DEFAULT_DASHBOARD_TYPE = "TR"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _range() -> tuple[str, str]:
    return (request.args.get("from") or OPEN_FROM,
            request.args.get("to") or OPEN_TO)


def _int(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def _scope() -> tuple[str, set[str]]:
    """The navigator's subtree selection plus the status exclusion set.

    Every listing endpoint reads the scope the same way, so a selection in the
    sidebar means the same thing on every screen.
    """
    node = (request.args.get("node") or "").strip().rstrip("/")
    return node, hierarchy.excluded_assets()


def _scope_payload(node: str) -> dict[str, Any] | None:
    return {"node": node, "label": hierarchy.scope_label(node)} if node else None


def _in_scope(asset_no: str, node: str, excluded: set[str]) -> bool:
    """Asset numbers are a materialised path, so a subtree is a prefix match."""
    if excluded and asset_no in excluded:
        return False
    if not node:
        return True
    return asset_no == node or asset_no.startswith(node + "/")


def _scope_filter(items, node: str, excluded: set[str], key=None):
    """Filter any asset-bearing sequence. `key` extracts the asset number."""
    if not node and not excluded:
        return items
    get = key or (lambda a: a.assetNumber)
    return [a for a in items if _in_scope(get(a), node, excluded)]



@app.errorhandler(db.DatabaseError)
def _db_error(exc: db.DatabaseError):
    log.error("database error: %s", exc)
    return jsonify({"error": "database", "message": str(exc)}), 503


@app.errorhandler(Exception)
def _unhandled(exc: Exception):
    log.exception("unhandled error")
    return jsonify({"error": "server", "message": str(exc)}), 500


# --------------------------------------------------------------------------
# health & meta
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    status, payload = overrides.proxy("GET", "/api/health")
    return jsonify({
        "api": "ok",
        "database": db.health(),
        # The CMMS that owns ast_mst_asset_shortdesc. Reported separately from
        # the HI database because the navigator degrades to derived names when
        # it is unreachable rather than failing, which is otherwise silent.
        "tomms": db.tomms_health(),
        # The AGE criterion reads `ast_det_datetime1` out of the CMMS, and what
        # that column means lives in a configuration table an administrator can
        # change with no schema change and no error. Assert the caption here so
        # a re-purposed UDF slot surfaces as a health warning rather than as
        # thousands of quietly wrong ages.
        "manufactureYear": {**attributes.verify_label_mapping(),
                            **attributes.coverage(
                                [a.assetNumber for a in assets_mod.all_assets()])},
        "hierarchy": hierarchy.stats(),
        "ml": ml.status(),
        "configService": {"reachable": status < 400, **(payload if status < 400 else {}),
                          "url": Config.CONFIG_SERVICE_URL},
        "snapshot": snapshots.status(),
    })


@app.post("/api/cache/clear")
def cache_clear():
    prefix = (request.json or {}).get("prefix", "") if request.is_json else ""
    return jsonify({"cleared": db.clear_cache(prefix)})


# --------------------------------------------------------------------------
# assets
# --------------------------------------------------------------------------
@app.get("/api/assets")
def list_assets():
    asset_type = request.args.get("type")
    site = request.args.get("site")
    search = (request.args.get("q") or "").strip().lower()
    node, excluded = _scope()

    items = _scope_filter(assets_mod.all_assets(), node, excluded)
    if asset_type:
        # Accept either a reporting category (TR, AET, OLTC) or a scoring type.
        items = [a for a in items
                 if a.category == asset_type or a.assetType == asset_type]
    if site:
        items = [a for a in items if a.site == site]
    if search:
        items = [a for a in items if search in a.assetNumber.lower()
                 or search in a.label.lower()]

    limit = _int("limit", 0)
    total = len(items)
    if limit:
        items = items[:limit]
    return jsonify({"total": total, "items": [a.as_dict() for a in items],
                    "scope": _scope_payload(node)})


@app.get("/api/assets/counts")
def asset_counts():
    return jsonify(assets_mod.counts())


@app.get("/api/assets/sites")
def asset_sites():
    return jsonify({"items": assets_mod.sites()})


@app.get("/api/assets/<path:number>")
def asset_detail(number: str):
    record = assets_mod.get(number)
    if not record:
        return jsonify({"error": "not_found",
                        "message": f"Unknown asset '{number}'."}), 404
    date_from, date_to = _range()
    return jsonify({
        "asset": record.as_dict(),
        # Year of manufacture from the CMMS, and the age the AGE criterion is
        # scored on. Same lookup the engine uses, so the detail page and the
        # health index can never quote different ages for the same asset.
        "manufacture": attributes.manufacture_year(number),
        "availability": readers.availability(number, date_from, date_to),
        "storedHistory": hi_engine.stored_history(number, limit=50),
    })


# --------------------------------------------------------------------------
# asset hierarchy
#
# Backs the navigator sidebar. The tree is served one level at a time - the
# full tree is 27k nodes, which is a large document to ship and a slow one to
# render, and users open only the branch they are looking at.
# --------------------------------------------------------------------------
@app.get("/api/hierarchy")
def hierarchy_children():
    parent = request.args.get("parent")
    return jsonify({"parent": parent,
                    "items": hierarchy.children(parent),
                    **hierarchy.stats()})


@app.get("/api/hierarchy/search")
def hierarchy_search():
    term = (request.args.get("q") or "").strip()
    limit = _int("limit", 40)
    return jsonify({"query": term, "items": hierarchy.search(term, limit)})


@app.get("/api/hierarchy/node/<path:asset_no>")
def hierarchy_node(asset_no: str):
    found = hierarchy.node(asset_no)
    if not found:
        return jsonify({"error": "not_found",
                        "message": f"Unknown hierarchy node '{asset_no}'."}), 404
    return jsonify({"node": found,
                    "ancestors": hierarchy.ancestors(asset_no),
                    "children": hierarchy.children(asset_no)})


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard():
    """Headline counts, distribution and worst assets.

    Served from the nightly snapshot by default - scoring 13,000 assets live
    takes minutes. `?live=1` forces a fresh sweep of a bounded sample, which is
    what the Refresh control uses when no snapshot exists yet.
    """
    # Transformers are the default view: they are the only asset type whose
    # score bands are fully configured, so a fleet-wide default would bury
    # 835 meaningful results under 11,000 unscoreable ones. `type=all` opts out.
    raw_type = request.args.get("type")
    asset_type = DEFAULT_DASHBOARD_TYPE if raw_type is None else raw_type
    if asset_type in {"all", "ALL", "*"}:
        asset_type = None

    limit = _int("limit", 250)
    live = request.args.get("live", "").lower() in {"1", "true", "yes"}
    node, excluded = _scope()

    if not live:
        stored = snapshots.dashboard()
        if stored:
            scoped = snapshots.summary(asset_type, node or None, excluded)
            rows, total = snapshots.rows(asset_type=asset_type,
                                         node=node or None, exclude=excluded,
                                         limit=limit)
            # The stored rollup is fleet-wide, so under a hierarchy scope the
            # inventory tiles have to be recounted from the scoped list or they
            # would advertise the whole fleet above a one-substation table.
            if node or excluded:
                stored["counts"] = assets_mod.counts(
                    _scope_filter(assets_mod.all_assets(), node, excluded))
            stored.update({
                **(scoped or {}),
                "rows": rows,
                "rowsTotal": total,
                "assetType": asset_type,
                "scope": _scope_payload(node),
                "availableTypes": snapshots.available_types(node or None, excluded),
                "source": "snapshot",
                "snapshot": snapshots.status(),
            })
            return jsonify(stored)

    date_from, date_to = _range()

    def build():
        scoped_all = _scope_filter(assets_mod.all_assets(), node, excluded)
        items = [a for a in scoped_all if a.assetType in scoring.COMPONENT_ORDER]
        if asset_type:
            items = [a for a in items if a.category == asset_type]
        subject = items[:limit]
        results = hi_engine.compute_many([a.assetNumber for a in subject],
                                         date_from, date_to)
        rows = [hi_engine.summary_row(r) for r in results]
        scored = [r for r in rows if r["healthIndex"] is not None]
        scored.sort(key=lambda r: r["healthIndex"])
        # Only assets whose scoring configuration can be trusted count toward the
        # fleet average, so unconfigured types cannot drag it into nonsense.
        trusted = [r for r in scored if r.get("configTrusted")]
        return {
            "counts": assets_mod.counts(scoped_all if (node or excluded) else None),
            "configAudit": scoring.config_audit(),
            "untrustedCount": len(scored) - len(trusted),
            "distribution": hi_engine.distribution(rows),
            "rows": rows,
            "rowsTotal": len(items),
            "worst": [r for r in scored if r.get("configTrusted")][:10],
            "scoredCount": len(scored),
            "evaluated": len(rows),
            "averageHealthIndex": round(
                sum(r["healthIndex"] for r in trusted) / len(trusted), 2)
            if trusted else None,
            "bands": scoring.HI_BANDS,
            "dateFrom": date_from, "dateTo": date_to,
            "assetType": asset_type,
            "scope": _scope_payload(node),
            "availableTypes": snapshots.available_types(node or None, excluded),
            "source": "live",
            "snapshot": snapshots.status(),
        }

    key = f"dash:{asset_type}:{node}:{limit}"
    return jsonify(db.cached(key, build))


# --------------------------------------------------------------------------
# health index
# --------------------------------------------------------------------------
@app.get("/api/health-index")
def health_index_table():
    """Health index for many assets, for the main table.

    Reads the nightly snapshot unless `?live=1` is given, which recomputes the
    requested page on the spot.
    """
    raw_type = request.args.get("type")
    asset_type = DEFAULT_DASHBOARD_TYPE if raw_type is None else raw_type
    if asset_type in {"all", "ALL", "*"}:
        asset_type = None

    site = request.args.get("site")
    # A hierarchy selection scopes the table to one subtree. Asset numbers
    # are a materialised path, so "under this node" is a prefix match.
    node, excluded = _scope()
    limit = _int("limit", 300)
    offset = _int("offset", 0)
    live = request.args.get("live", "").lower() in {"1", "true", "yes"}

    scope = _scope_payload(node)

    if not live and snapshots.has_data():
        rows, total = snapshots.rows(asset_type=asset_type, site=site,
                                     node=node or None, exclude=excluded,
                                     limit=limit, offset=offset)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "rows": rows, "bands": scoring.HI_BANDS,
                        "assetType": asset_type, "scope": scope,
                        "availableTypes": snapshots.available_types(node or None, excluded),
                        "source": "snapshot", "snapshot": snapshots.status()})

    date_from, date_to = _range()
    items = [a for a in assets_mod.all_assets() if a.assetType in scoring.COMPONENT_ORDER]
    if asset_type:
        items = [a for a in items if a.category == asset_type]
    if site:
        items = [a for a in items if a.site == site]
    items = _scope_filter(items, node, excluded)

    total = len(items)
    page = items[offset:offset + limit]

    key = f"hi:{asset_type}:{site}:{node}:{date_from}:{date_to}:{offset}:{limit}"
    rows = db.cached(key, lambda: [
        hi_engine.summary_row(r)
        for r in hi_engine.compute_many([a.assetNumber for a in page],
                                        date_from, date_to)
    ])
    return jsonify({"total": total, "offset": offset, "limit": limit,
                    "rows": rows, "bands": scoring.HI_BANDS,
                    "assetType": asset_type, "scope": scope,
                    "availableTypes": snapshots.available_types(node or None, excluded),
                    "source": "live", "snapshot": snapshots.status()})


@app.get("/api/health-index/<path:number>")
def health_index_detail(number: str):
    date_from, date_to = _range()
    manual: dict[str, float] = {}
    for key, value in request.args.items():
        if key.startswith("m_"):
            try:
                manual[key[2:]] = float(value)
            except ValueError:
                pass
    result = hi_engine.compute(number, date_from, date_to, manual=manual)
    result["storedHistory"] = hi_engine.stored_history(number, limit=50)
    return jsonify(result)


@app.post("/api/health-index/<path:number>")
def health_index_recompute(number: str):
    """Recompute with an explicit criterion selection and manual inputs.

    Body: `{manual: {CODE: score}, selected: [CODE, ...], age: <years>,
    from, to}`. Omitting `selected` scores every criterion that has data.
    """
    body = request.get_json(silent=True) or {}
    manual = {k: float(v) for k, v in (body.get("manual") or {}).items()
              if v is not None and v != ""}

    selected = body.get("selected")
    if selected is not None and not isinstance(selected, list):
        return jsonify({"error": "validation",
                        "message": "'selected' must be an array of component codes."}), 400

    age = body.get("age")
    try:
        manual_age = float(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"error": "validation",
                        "message": "'age' must be a number of years."}), 400

    result = hi_engine.compute(
        number,
        body.get("from") or OPEN_FROM,
        body.get("to") or OPEN_TO,
        manual=manual,
        selected=selected,
        manual_age=manual_age,
    )
    return jsonify(result)


@app.get("/api/health-index/stored")
def health_index_stored():
    return jsonify({"rows": hi_engine.stored_history(
        request.args.get("asset"), _int("limit", 500))})


# --------------------------------------------------------------------------
# DGA trend
# --------------------------------------------------------------------------
@app.get("/api/dga/assets")
def dga_asset_list():
    node, excluded = _scope()
    items = _scope_filter(dga_trend.dga_assets(), node, excluded,
                          key=lambda r: r["assetNumber"])
    return jsonify({"items": items, "scope": _scope_payload(node),
                    "total": len(items)})


@app.get("/api/dga/trend/<path:number>")
def dga_asset_trend(number: str):
    date_from, date_to = _range()
    # Full history by default: clipping the window changes which samples form
    # the last-three group and therefore the rate.
    if request.args.get("fullHistory", "true").lower() in {"1", "true", "yes"}:
        date_from, date_to = "1900-01-01", "2999-12-31"
    return jsonify(dga_trend.asset_trend(number, date_from, date_to))


@app.post("/api/dga/trend/fleet")
def dga_fleet_trend():
    body = request.get_json(silent=True) or {}
    assets = body.get("assets") or []
    if not assets:
        assets = [a["assetNumber"] for a in dga_trend.dga_assets()]
    date_from = body.get("from") or "1900-01-01"
    date_to = body.get("to") or "2999-12-31"
    return jsonify({"rows": dga_trend.fleet_trend(assets, date_from, date_to)})


@app.get("/api/dga/series/<path:number>")
def dga_series(number: str):
    date_from, date_to = _range()
    gases = (request.args.get("gases") or "H2,CH4,CO,CO2,C2H4,C2H6,C2H2").split(",")
    return jsonify(dga_trend.series(number, [g.strip() for g in gases],
                                    date_from, date_to))


@app.get("/api/dga/samples/<path:number>")
def dga_samples(number: str):
    date_from, date_to = _range()
    samples = dga_trend.fetch_samples([number], date_from, date_to).get(number.strip(), [])
    return jsonify({"asset": number, "samples": samples})


# --------------------------------------------------------------------------
# DGA status - IEEE C57.104-2019 Figure 2
# --------------------------------------------------------------------------
# A different question from the trend score above: the trend gives the health
# index a 0-1 number, this puts the unit in Status 1/2/3 against the standard's
# population tables. Both read CEB_DGA_DATA; neither feeds the other.
@app.get("/api/dga/status/tables")
def dga_status_tables():
    """The four reference tables, for the on-screen limit reference."""
    return jsonify(dga_status.reference_tables())


@app.get("/api/dga/status/report/<path:number>")
def dga_status_report(number: str):
    """The full report payload for one asset - status, evidence and actions."""
    date_from, date_to = _range()
    if request.args.get("fullHistory", "true").lower() in {"1", "true", "yes"}:
        date_from, date_to = "1900-01-01", "2999-12-31"
    return jsonify(dga_status.report(number, date_from, date_to))


@app.get("/api/dga/status/<path:number>")
def dga_asset_status(number: str):
    """Figure 2 status for one asset.

    Full history by default, for the same reason the trend endpoint does it:
    clipping the window changes which samples form the rate group.
    """
    date_from, date_to = _range()
    if request.args.get("fullHistory", "true").lower() in {"1", "true", "yes"}:
        date_from, date_to = "1900-01-01", "2999-12-31"
    return jsonify(dga_status.asset_status(number, date_from, date_to))


@app.post("/api/dga/status/manual")
def dga_manual_status():
    """Figure 2 status for hand-entered gas values.

    For a unit whose lab results are not loaded yet, or a what-if check against
    a test certificate. Returns the same payload as the stored-asset report, so
    the frontend renders and exports it identically.
    """
    body = request.get_json(silent=True) or {}
    try:
        payload = dga_status.manual_report(
            body.get("samples") or [],
            body.get("ageYears"),
            body.get("label") or "",
        )
    except dga_status.ManualEntryError as exc:
        return jsonify({"message": str(exc)}), 400
    return jsonify(payload)


@app.post("/api/dga/status/fleet")
def dga_fleet_status():
    """Status for every asset in scope, worst first, with the fleet counts."""
    body = request.get_json(silent=True) or {}
    node = (body.get("node") or "").strip().rstrip("/")
    excluded = hierarchy.excluded_assets()

    assets = body.get("assets") or []
    if not assets:
        listed = _scope_filter(dga_trend.dga_assets(), node, excluded,
                               key=lambda r: r["assetNumber"])
        assets = [a["assetNumber"] for a in listed]

    date_from = body.get("from") or "1900-01-01"
    date_to = body.get("to") or "2999-12-31"
    rows = dga_status.fleet_status(assets, date_from, date_to)
    return jsonify({"rows": rows, "summary": dga_status.summary(rows),
                    "scope": _scope_payload(node),
                    "ageSource": dga_status.age_source()})


# --------------------------------------------------------------------------
# Duval pentagon / triangle
# --------------------------------------------------------------------------
@app.get("/api/duval/geometry")
def duval_geometry():
    return jsonify({
        "pentagon": pentagon.geometry(),
        "triangles": {tid: duval.triangle_geometry(tid) for tid in duval.TRIANGLES},
    })


def _gases_from_request() -> tuple[dict[str, float], str | None, str | None]:
    """Gases either supplied directly or read from an asset's newest sample."""
    body = request.get_json(silent=True) or {}
    asset = body.get("asset") or request.args.get("asset")
    supplied = body.get("gases") or {}

    if supplied:
        return ({k: float(v or 0.0) for k, v in supplied.items()}, asset,
                body.get("sampleDate"))

    if not asset:
        return {}, None, None

    date_from = body.get("from") or request.args.get("from") or OPEN_FROM
    date_to = body.get("to") or request.args.get("to") or OPEN_TO
    sample = readers.read_dga_sample(asset, date_from, date_to)
    if not sample:
        return {}, asset, None
    return ({k: (v or 0.0) for k, v in sample["gases"].items()},
            asset, sample["date"])


@app.route("/api/duval/analyse", methods=["GET", "POST"])
def duval_analyse():
    """Full multi-method diagnosis for one gas sample."""
    gases, asset, sample_date = _gases_from_request()
    if not gases:
        return jsonify({
            "error": "no_data",
            "message": f"No DGA sample available for '{asset}'." if asset
            else "Supply either an asset or a gases object.",
        }), 404

    pent = pentagon.analyse(
        h2=gases.get("H2", 0), ch4=gases.get("CH4", 0), c2h6=gases.get("C2H6", 0),
        c2h4=gases.get("C2H4", 0), c2h2=gases.get("C2H2", 0),
        asset=asset, sample_date=sample_date,
    )
    triangles = {tid: duval.analyse_triangle(tid, gases) for tid in duval.TRIANGLES}

    body = request.get_json(silent=True) or {}
    age = body.get("age") or request.args.get("age")
    try:
        age = int(age) if age else None
    except ValueError:
        age = None

    previous = body.get("previous")
    rates: dict[str, Any] = {}
    if asset:
        samples = dga_trend.fetch_samples([asset]).get(asset.strip(), [])
        if len(samples) >= 2 and not previous:
            prev = samples[-2]
            previous = {g: prev.get(col) for g, col in dga_trend.GAS_COLUMN.items()}
        for gas, col in dga_trend.GAS_COLUMN.items():
            pts = [(s["DateSampled"], float(s[col])) for s in samples
                   if s.get(col) is not None]
            got = duval.regression_rate(gas, pts)
            if got["rate"] is not None:
                rates[gas] = got["rate"]
                rates["_spanMonths"] = got["spanMonths"]

    ieee = duval.assess_levels(gases, age=age, previous=previous, rates=rates)

    # The classifier is trained on transformer oil DGA, so it is offered only for
    # transformers. Manual gas entry with no asset is assumed to be transformer
    # oil - that is the only thing these gases describe.
    record = assets_mod.get(asset) if asset else None
    asset_type = record.assetType if record else ("TR" if not asset else
                                                  assets_mod.classify(asset)[0])
    ai = ml.predict(gases.get("H2", 0), gases.get("CH4", 0), gases.get("C2H6", 0),
                    gases.get("C2H4", 0), gases.get("C2H2", 0),
                    asset_type=asset_type)

    t1_zone = triangles["1"].get("zone")
    agreement = None
    if ai.get("available") and t1_zone:
        matched = ml.agrees_with_duval(ai["fault"], t1_zone)
        agreement = {
            "match": matched,
            "message": (
                f"Perfect agreement between IEEE C57.104 ratios, Duval Triangle "
                f"({t1_zone}) and the XGBoost AI model."
                if matched else
                "Discrepancy detected between the AI model and the Duval Triangle. "
                "Engineer review highly recommended."
            ),
        }

    return jsonify({
        "asset": asset, "sampleDate": sample_date, "assetType": asset_type,
        "gases": gases,
        "pentagon": pent, "triangles": triangles, "ieee": ieee,
        "rogers": duval.rogers_ratios(gases), "keyGas": duval.key_gas(gases),
        "paper": duval.paper_involvement(gases),
        "caveats": duval.integrity_caveats(gases),
        "ai": ai, "agreement": agreement, "disclaimer": duval.DISCLAIMER,
    })


# --------------------------------------------------------------------------
# availability & configuration
# --------------------------------------------------------------------------
@app.get("/api/availability")
def availability_report():
    date_from, date_to = _range()
    asset = request.args.get("asset")
    if asset:
        return jsonify({"rows": [{"asset": asset,
                                  "tests": readers.availability(asset, date_from, date_to)}]})

    asset_type = request.args.get("type")
    limit = _int("limit", 40)
    node, excluded = _scope()
    items = _scope_filter(assets_mod.all_assets(), node, excluded)
    if asset_type:
        items = [a for a in items if a.assetType == asset_type]
    subject = items[:limit]
    return jsonify({
        "rows": [{"asset": a.assetNumber, "assetType": a.assetType,
                  "tests": readers.availability(a.assetNumber, date_from, date_to)}
                 for a in subject],
        "total": len(items),
        "scope": _scope_payload(node),
    })


# --------------------------------------------------------------------------
# Test history
#
# The availability report says which tests an asset has; these endpoints return
# the records themselves so an engineer can read a single test's history.
# --------------------------------------------------------------------------
@app.get("/api/history/tests")
def history_tests():
    """Catalogue of browsable tests, with per-asset counts when an asset is given."""
    asset = request.args.get("asset")
    if not asset:
        return jsonify({"asset": None, "items": history.catalogue()})

    date_from, date_to = _range()
    items = history.asset_summary(asset, date_from, date_to)
    return jsonify({"asset": asset, "items": items,
                    "dateFrom": date_from, "dateTo": date_to})


@app.get("/api/history/<test_id>/<path:number>")
def history_records(test_id: str, number: str):
    """Every stored record of one test for one asset, newest first."""
    date_from, date_to = _range()
    result = history.test_history(number, test_id, date_from, date_to,
                                  limit=_int("limit", 200))
    if result is None:
        return jsonify({"error": "not_found",
                        "message": f"Unknown test '{test_id}'."}), 404
    return jsonify(result)


@app.get("/api/config")
def get_config():
    snapshot = scoring.config_snapshot()
    snapshot["flags"] = {
        "dgaPerGasOwnField": Config.DGA_PER_GAS_OWN_FIELD,
        "diranaScoreOwnValue": Config.DIRANA_SCORE_OWN_VALUE,
        "aioIftoUncrossed": Config.AIO_IFTO_UNCROSSED,
        "saIrUsesIrField": Config.SA_IR_USES_IR_FIELD,
        "oltcUsesCebOltc": Config.OLTC_USES_CEB_OLTC,
        "ecBandAscending": Config.EC_BAND_ASCENDING,
    }
    snapshot["assetTypeLabels"] = assets_mod.ASSET_TYPE_LABEL
    return jsonify(snapshot)


# --------------------------------------------------------------------------
# Snapshots
#
# The 08:00 scheduled task normally calls run_snapshot.py directly, but the
# same sweep is exposed here so it can be triggered from the UI or by an
# external scheduler.
# --------------------------------------------------------------------------
def _snapshot_authorised() -> bool:
    """Optional shared secret for the trigger endpoint.

    Unset means no check, which is the right default for a service bound to
    localhost. Set HI_SNAPSHOT_TOKEN when the API is reachable from elsewhere.
    """
    expected = Config.SNAPSHOT_TOKEN
    if not expected:
        return True
    supplied = request.headers.get("X-Snapshot-Token") or request.args.get("token")
    return supplied == expected


@app.get("/api/snapshot/status")
def snapshot_status():
    return jsonify(snapshots.status())


@app.get("/api/snapshot/history")
def snapshot_history():
    return jsonify({"items": snapshots.history(_int("limit", 30))})


@app.post("/api/snapshot/run")
def snapshot_run():
    """Start a fleet sweep. Returns immediately; poll /api/snapshot/status."""
    if not _snapshot_authorised():
        return jsonify({"error": "unauthorised",
                        "message": "A valid X-Snapshot-Token header is required."}), 401

    body = request.get_json(silent=True) or {}
    types = body.get("types") or None
    limit = body.get("limit")
    wait = str(body.get("wait", "")).lower() in {"1", "true", "yes"}

    kwargs: dict[str, Any] = {"asset_types": types}
    if limit:
        kwargs["limit"] = int(limit)

    if wait:                       # synchronous, for scripted use
        result = snapshots.run_snapshot(triggered_by=body.get("by", "api"), **kwargs)
    else:
        result = snapshots.run_in_background(triggered_by=body.get("by", "manual"), **kwargs)

    status_code = 200 if result.get("started") else 409
    return jsonify(result), status_code


@app.post("/api/snapshot/asset/<path:number>")
def snapshot_refresh_asset(number: str):
    """Recompute one asset now and update its stored row."""
    return jsonify(snapshots.refresh_asset(number))


# --------------------------------------------------------------------------
# Configuration microservice proxy
#
# The browser talks only to this API; writes are forwarded to the configuration
# service, which owns them in its own database. Proxying keeps one origin and
# means the service never has to be exposed separately.
# --------------------------------------------------------------------------
def _editor() -> str:
    body = request.get_json(silent=True) or {}
    return (request.headers.get("X-User") or body.get("user") or "engineer")


def _seg(value: str) -> str:
    """Percent-encode one path segment before re-sending it downstream.

    Band names carry a '#' (IR#CTVT, AGE#SA). Flask hands them over already
    decoded, and passing that straight into a URL would let urllib read
    everything after the '#' as a fragment - the configuration service would
    then store the override under 'IR' and it would never be found again.
    """
    return quote(value, safe="")


@app.put("/api/config/bands/<asset_type>/<band_name>")
def save_bands(asset_type: str, band_name: str):
    body = request.get_json(silent=True) or {}
    status, payload = overrides.proxy(
        "PUT", f"/api/bands/{_seg(asset_type)}/{_seg(band_name)}", body, _editor())
    if status < 400:
        db.clear_cache("cfg:")
        db.clear_cache("hi:")
        db.clear_cache("dash:")
    return jsonify(payload), status


@app.delete("/api/config/bands/<asset_type>/<band_name>")
def reset_bands(asset_type: str, band_name: str):
    status, payload = overrides.proxy(
        "DELETE", f"/api/bands/{_seg(asset_type)}/{_seg(band_name)}", None, _editor())
    if status < 400:
        db.clear_cache("cfg:")
        db.clear_cache("hi:")
        db.clear_cache("dash:")
    return jsonify(payload), status


@app.put("/api/config/weights/<asset_type>")
def save_weights(asset_type: str):
    body = request.get_json(silent=True) or {}
    status, payload = overrides.proxy(
        "PUT", f"/api/weights/{_seg(asset_type)}", body, _editor())
    if status < 400:
        db.clear_cache("cfg:")
        db.clear_cache("hi:")
        db.clear_cache("dash:")
    return jsonify(payload), status


@app.delete("/api/config/weights/<asset_type>")
def reset_weights(asset_type: str):
    status, payload = overrides.proxy(
        "DELETE", f"/api/weights/{_seg(asset_type)}", None, _editor())
    if status < 400:
        db.clear_cache("cfg:")
        db.clear_cache("hi:")
        db.clear_cache("dash:")
    return jsonify(payload), status


@app.get("/api/config/history")
def config_history():
    status, payload = overrides.proxy(
        "GET", f"/api/history?limit={_int('limit', 100)}")
    return jsonify(payload), status


# --------------------------------------------------------------------------
# ML
# --------------------------------------------------------------------------
@app.get("/api/ml/status")
def ml_status():
    return jsonify(ml.status())


@app.post("/api/ml/train")
def ml_train():
    return jsonify(ml.train(force=True))


@app.post("/api/ml/predict")
def ml_predict():
    """Classify an ad-hoc gas sample. Transformers only."""
    body = request.get_json(silent=True) or {}
    gases = body.get("gases") or {}
    asset = body.get("asset")
    asset_type = body.get("assetType")
    if asset and not asset_type:
        record = assets_mod.get(asset)
        asset_type = record.assetType if record else assets_mod.classify(asset)[0]
    return jsonify(ml.predict(
        gases.get("H2", 0), gases.get("CH4", 0), gases.get("C2H6", 0),
        gases.get("C2H4", 0), gases.get("C2H2", 0), asset_type=asset_type,
    ))


# --------------------------------------------------------------------------
# Built frontend
# --------------------------------------------------------------------------
# Registered last, so every /api rule above wins. In development this does
# nothing useful - Vite serves the UI and proxies here - but in production it
# is what lets the whole system answer on a single port, with the browser and
# the API on the same origin. That removes CORS and the need for IIS or nginx
# in front.
DIST = Path(Config.FRONTEND_DIST)


@app.get("/")
def spa_index():
    if not (DIST / "index.html").is_file():
        return jsonify({
            "error": "frontend-not-built",
            "message": (f"No built frontend at {DIST}. Run 'npm run build' in the "
                        f"frontend folder, or point HI_FRONTEND_DIST at the dist "
                        f"directory."),
        }), 503
    return send_from_directory(DIST, "index.html")


@app.get("/<path:path>")
def spa_files(path: str):
    """A built asset if it exists, otherwise index.html.

    The UI uses client-side routing, so a deep link such as /dga-entry is not a
    file on disk - it has to return the shell and let the router resolve it.
    Unknown /api paths must still 404 as JSON rather than being answered with
    HTML, which would turn a typo into a confusing parse error in the client.
    """
    if path.startswith("api/"):
        return jsonify({"error": "not-found", "message": f"No API route /{path}"}), 404
    candidate = (DIST / path)
    try:
        candidate.relative_to(DIST)          # refuse ../ traversal
    except ValueError:
        return jsonify({"error": "not-found"}), 404
    if candidate.is_file():
        return send_from_directory(DIST, path)
    return spa_index()


if __name__ == "__main__":
    # Loads saved weights if present, trains from the datasets otherwise, and
    # is a no-op when neither the dependencies nor the data are available.
    ml.ensure_ready()
    snapshots.init()
    state = snapshots.status()
    if state["hasData"]:
        log.info("Snapshot available (age %.1f h)%s",
                 state["ageHours"] or 0, " - STALE" if state["stale"] else "")
    else:
        log.info("No snapshot yet - run 'py run_snapshot.py' or use Refresh in the UI. "
                 "Until then the dashboard scores a bounded sample live.")
    log.info("Serving on http://%s:%s", Config.HOST, Config.PORT)
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG,
            use_reloader=False)
