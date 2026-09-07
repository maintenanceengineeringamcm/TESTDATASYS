"""Client for the scoring-configuration microservice.

The service is treated as optional infrastructure: if it is down or slow, the
main API logs it once and falls back to the source configuration rather than
failing to score the fleet. Overrides are cached briefly so a fleet sweep does
not make one HTTP call per asset.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from config import Config

log = logging.getLogger(__name__)

_cache: dict[str, Any] = {"at": 0.0, "data": {"bands": {}, "weights": {}}}
_lock = threading.Lock()
_warned = False


def _url(path: str) -> str:
    return f"{Config.CONFIG_SERVICE_URL.rstrip('/')}{path}"


def _fetch() -> dict[str, Any]:
    global _warned
    try:
        req = urllib.request.Request(_url("/api/overrides"),
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=Config.CONFIG_SERVICE_TIMEOUT) as res:
            data = json.load(res)
        _warned = False
        return {"bands": data.get("bands") or {}, "weights": data.get("weights") or {}}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        if not _warned:
            log.warning(
                "Configuration service unreachable at %s (%s). "
                "Falling back to the source configuration.",
                Config.CONFIG_SERVICE_URL, exc,
            )
            _warned = True
        return {"bands": {}, "weights": {}}


def snapshot(force: bool = False) -> dict[str, Any]:
    now = time.time()
    with _lock:
        fresh = now - _cache["at"] < Config.CONFIG_SERVICE_TTL
        if fresh and not force:
            return _cache["data"]
    data = _fetch()
    with _lock:
        _cache["at"] = now
        _cache["data"] = data
    return data


def invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0


def band_override(asset_type: str, band_name: str) -> list[dict[str, Any]] | None:
    entry = snapshot()["bands"].get(f"{asset_type}/{band_name}")
    return entry["bands"] if entry else None


def weight_override(asset_type: str) -> dict[str, float] | None:
    entry = snapshot()["weights"].get(asset_type)
    if not entry:
        return None
    return {k: float(v) for k, v in entry["components"].items()}


def overridden_band_names(asset_type: str) -> set[str]:
    prefix = f"{asset_type}/"
    return {k[len(prefix):] for k in snapshot()["bands"] if k.startswith(prefix)}


def metadata() -> dict[str, Any]:
    """Who changed what and when, for display next to each edited table."""
    data = snapshot()
    return {
        "bands": {
            k: {"updatedAt": v.get("updatedAt"), "updatedBy": v.get("updatedBy"),
                "note": v.get("note", "")}
            for k, v in data["bands"].items()
        },
        "weights": {
            k: {"updatedAt": v.get("updatedAt"), "updatedBy": v.get("updatedBy"),
                "note": v.get("note", "")}
            for k, v in data["weights"].items()
        },
        "serviceUrl": Config.CONFIG_SERVICE_URL,
        "reachable": bool(data["bands"] or data["weights"]) or _reachable(),
    }


def _reachable() -> bool:
    try:
        req = urllib.request.Request(_url("/api/health"))
        with urllib.request.urlopen(req, timeout=Config.CONFIG_SERVICE_TIMEOUT) as res:
            return res.status == 200
    except Exception:
        return False


def proxy(method: str, path: str, body: dict[str, Any] | None = None,
          user: str = "engineer") -> tuple[int, dict[str, Any]]:
    """Forward a write from the UI to the configuration service.

    Keeps the browser talking to one origin and means the service never has to
    be exposed separately.
    """
    payload = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(
        _url(path), data=payload, method=method,
        headers={"Content-Type": "application/json", "X-User": user},
    )
    try:
        with urllib.request.urlopen(req, timeout=Config.CONFIG_SERVICE_TIMEOUT) as res:
            invalidate()
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except Exception:
            return exc.code, {"error": "config_service", "message": exc.reason}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 503, {
            "error": "config_service_unavailable",
            "message": (f"Configuration service is not reachable at "
                        f"{Config.CONFIG_SERVICE_URL}. Start it with "
                        f"'py config-service/app.py'. ({exc})"),
        }
