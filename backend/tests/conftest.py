"""Shared fixtures.

The suite splits in two:

* **unit** - pure logic, no database. Always runs, anywhere.
* **live**  - runs against the real `Tomms_CEBT` and `CEB_TRANSMISSION`
  instances and asserts the figures in `ASSET_ATTRIBUTES_INTEGRATION.md`. These
  skip, rather than fail, when a database is unreachable, so the suite is still
  useful on a laptop off the plant network.

Run everything:            python -m pytest backend/tests
Unit only (no databases):  python -m pytest backend/tests -m "not live"
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: needs the live SQL Server instances; skipped when unreachable")


def _reachable(probe) -> bool:
    import db
    try:
        probe()
        return True
    except db.DatabaseError:
        return False


@pytest.fixture(scope="session")
def cmms():
    """The Tomms CMMS, or a skip when it is not reachable."""
    import db
    from config import tomms_configured
    if not tomms_configured():
        pytest.skip("HI_TOMMS_DB_SERVER is not set")
    if not _reachable(lambda: db.scalar_tomms("SELECT 1")):
        pytest.skip("Tomms CMMS unreachable")
    return db


@pytest.fixture(scope="session")
def hidb():
    """The HI database (CEB_TRANSMISSION), or a skip when it is not reachable."""
    import db
    if not _reachable(lambda: db.scalar("SELECT 1")):
        pytest.skip("CEB_TRANSMISSION unreachable")
    return db
