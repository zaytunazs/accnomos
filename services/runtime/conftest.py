"""Make `pytest` import this checkout's `app` and packages, not another editable install of them."""
"""Make `pytest` import this checkout's `app`, ledger and connectors, not another checkout's editable installs."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    """Every test starts with a full per-IP bucket (the app, and so the limiter, is shared across tests)."""
    from app import security

    if security.LIMITER:
        security.LIMITER.reset()
    yield
HERE = Path(__file__).resolve().parent
for path in (HERE.parents[1] / "packages" / "connectors" / "src", HERE.parents[1] / "packages" / "ledger" / "src", HERE):
    if path.is_dir():
        sys.path.insert(0, str(path))
HERE = Path(__file__).resolve().parent
for path in (HERE.parents[1] / "packages/connectors/src", HERE.parents[1] / "packages/ledger/src", HERE):
    sys.path.insert(0, str(path))
