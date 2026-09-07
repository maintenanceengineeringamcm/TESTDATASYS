"""Scoring Configuration microservice.

Owns every engineer-edited scoring threshold, in its own database, so the plant
system (CEB_TRANSMISSION) is never written to. The main API reads overrides from
here and merges them over the bands it loads from the source database; if this
service is unavailable the main API simply falls back to the source values, so
the fleet keeps scoring.

Runs on port 5001 by default.
"""
from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, request
from flask_cors import CORS

import store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s cfg: %(message)s")
log = logging.getLogger("cfg")

app = Flask(__name__)
CORS(app)

PORT = int(os.getenv("CFG_PORT", "5001"))
HOST = os.getenv("CFG_HOST", "127.0.0.1")


def _user() -> str:
    """Identify the editor. Header first, then body, then a safe default."""
    body = request.get_json(silent=True) or {}
    return (request.headers.get("X-User") or body.get("user") or "engineer").strip()[:80]


@app.errorhandler(ValueError)
def _bad_value(exc: ValueError):
    return jsonify({"error": "validation", "message": str(exc)}), 400


@app.errorhandler(Exception)
def _unhandled(exc: Exception):
    log.exception("unhandled")
    return jsonify({"error": "server", "message": str(exc)}), 500


@app.get("/api/health")
def health():
    return jsonify({"service": "config", "ok": True, **store.stats()})


# --------------------------------------------------------------------------
# Everything, in one call - this is what the main API polls.
# --------------------------------------------------------------------------
@app.get("/api/overrides")
def overrides():
    return jsonify({"bands": store.all_bands(), "weights": store.all_weights()})


# --------------------------------------------------------------------------
# Bands
# --------------------------------------------------------------------------
@app.get("/api/bands/<asset_type>/<band_name>")
def get_band(asset_type: str, band_name: str):
    found = store.get_band(asset_type, band_name)
    if not found:
        return jsonify({"error": "not_found",
                        "message": "No override stored; the source values apply."}), 404
    return jsonify(found)


@app.put("/api/bands/<asset_type>/<band_name>")
def put_band(asset_type: str, band_name: str):
    body = request.get_json(silent=True) or {}
    bands = body.get("bands")
    if not isinstance(bands, list):
        raise ValueError("Body must contain a 'bands' array.")
    saved = store.save_band(asset_type, band_name, bands, _user(), body.get("note", ""))
    log.info("band saved %s/%s by %s", asset_type, band_name, saved["updatedBy"])
    return jsonify(saved)


@app.delete("/api/bands/<asset_type>/<band_name>")
def delete_band(asset_type: str, band_name: str):
    removed = store.reset_band(asset_type, band_name, _user())
    return jsonify({"reset": removed})


# --------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------
@app.get("/api/weights/<asset_type>")
def get_weights(asset_type: str):
    found = store.get_weights(asset_type)
    if not found:
        return jsonify({"error": "not_found",
                        "message": "No override stored; the source values apply."}), 404
    return jsonify(found)


@app.put("/api/weights/<asset_type>")
def put_weights(asset_type: str):
    body = request.get_json(silent=True) or {}
    components = body.get("components")
    if not isinstance(components, dict):
        raise ValueError("Body must contain a 'components' object.")
    saved = store.save_weights(asset_type, components, _user(), body.get("note", ""))
    log.info("weights saved %s by %s", asset_type, saved["updatedBy"])
    return jsonify(saved)


@app.delete("/api/weights/<asset_type>")
def delete_weights(asset_type: str):
    return jsonify({"reset": store.reset_weights(asset_type, _user())})


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------
@app.get("/api/history")
def history():
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        limit = 100
    return jsonify({"items": store.history(min(max(limit, 1), 500))})


if __name__ == "__main__":
    store.init()
    log.info("Config service on http://%s:%s (db: %s)", HOST, PORT, store.DB_PATH)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
