"""DGA correction factor on the final health index (unit, no database)."""
from __future__ import annotations

import pytest

from core import hi_engine
from core.hi_engine import (DGA_CORRECTION_DEFAULTS, apply_dga_correction,
                            parse_correction_factors)


def test_defaults():
    assert DGA_CORRECTION_DEFAULTS == {1: 0.0, 2: 0.1, 3: 0.3}
    assert parse_correction_factors(None) == DGA_CORRECTION_DEFAULTS
    assert parse_correction_factors({}) == DGA_CORRECTION_DEFAULTS


def test_partial_override_keeps_other_defaults():
    assert parse_correction_factors({"3": 0.5}) == {1: 0.0, 2: 0.1, 3: 0.5}
    assert parse_correction_factors({"2": ""}) == DGA_CORRECTION_DEFAULTS


@pytest.mark.parametrize("raw", [{"4": 0.1}, {"x": 0.1}, {"3": 1.5}, {"1": -0.1}])
def test_rejects_bad_factors(raw):
    with pytest.raises(ValueError):
        parse_correction_factors(raw)


@pytest.mark.parametrize("status, expected, factor", [
    (1, 80.0, 0.0),
    (2, 72.0, 0.1),      # 80 x (1 - 0.1)
    (3, 56.0, 0.3),      # 80 x (1 - 0.3): status 3 takes 30% off
    (None, 80.0, 0.0),   # no DGA status - index unchanged
])
def test_apply(status, expected, factor):
    assert apply_dga_correction(80.0, status, DGA_CORRECTION_DEFAULTS) == (expected, factor)


def test_no_index_stays_none():
    assert apply_dga_correction(None, 3, DGA_CORRECTION_DEFAULTS) == (None, 0.0)


def test_non_transformer_is_not_corrected():
    out = hi_engine._dga_correction("G001/PE/1/02/52_X/01", "CB", 75.0,
                                    "1900-01-01", "2999-12-31", DGA_CORRECTION_DEFAULTS)
    assert out["applied"] is False and out["hiAfter"] == 75.0


def test_status_drives_correction(monkeypatch):
    monkeypatch.setattr(hi_engine.dga_status, "asset_status", lambda *a, **k: {
        "status": 3, "statusLabel": "Status 3", "verdict": "Probably suspicious",
        "color": "#D64545", "bg": "#FCEAEA", "latestSample": "2026-01-14"})
    out = hi_engine._dga_correction("X", "TR", 80.0, "1900-01-01", "2999-12-31",
                                    DGA_CORRECTION_DEFAULTS)
    assert out["applied"] and out["factor"] == 0.3
    assert out["hiBefore"] == 80.0 and out["hiAfter"] == 56.0


def test_unclassified_dga_leaves_index(monkeypatch):
    monkeypatch.setattr(hi_engine.dga_status, "asset_status",
                        lambda *a, **k: {"status": None, "reason": "No DGA samples."})
    out = hi_engine._dga_correction("X", "TR", 80.0, "1900-01-01", "2999-12-31",
                                    DGA_CORRECTION_DEFAULTS)
    assert not out["applied"] and out["hiAfter"] == 80.0
    assert out["message"] == "No DGA samples."
