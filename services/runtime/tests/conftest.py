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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if "slow" in (config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="deeper property run: python -m pytest -m slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
