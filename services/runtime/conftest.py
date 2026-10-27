"""Make `pytest` import this checkout's `app`, not another editable install of accnomos-runtime."""

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
