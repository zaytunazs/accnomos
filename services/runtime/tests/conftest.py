"""Hypothesis profiles for the property tests (tests/test_properties_*.py).

"default" keeps the suite quick; HYPOTHESIS_PROFILE=deep runs many more examples. Tests marked `slow` (the long
random runs of the books) only run when asked for: `python -m pytest -m slow`.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "default",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.register_profile(
    "deep",
    max_examples=2000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: deeper property runs; only with `-m slow`")
    config.addinivalue_line("markers", "real_identity: use app.identity.verified_identity, not the Graph /me stand-in")


@pytest.fixture(autouse=True)
def graph_me_stand_in(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Routes that need to know who is calling (app/identity.py) would ask Graph /me; no test has a real token.
    Stand-in: any non-blank token is the user named in X-User (as test mode's fakes do), else sam@example.co.uk.
    Mark a test `real_identity` to run the real verifier against its own fake Graph."""
    if request.node.get_closest_marker("real_identity"):
        return
    from fastapi import HTTPException

    from accnomos_connectors.base import Identity
    from app import identity

    async def stand_in(token: str, hint: str | None = None, kind: str | None = None) -> Identity:
        if not token.strip().removeprefix("Bearer ").strip():
            raise HTTPException(status_code=401, detail="X-Graph-Token header required")
        return Identity(email=(hint or "").strip() or "sam@example.co.uk")

    monkeypatch.setattr(identity, "verified_identity", stand_in)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if "slow" in (config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="deeper property run: python -m pytest -m slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
