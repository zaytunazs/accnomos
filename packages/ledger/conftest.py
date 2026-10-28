"""Make `pytest` import this checkout's `accnomos_ledger`, not another checkout's editable install.

Also the Hypothesis profiles for the property tests (tests/test_properties.py): "default" keeps the suite quick,
"deep" (HYPOTHESIS_PROFILE=deep) runs many more examples; tests marked `slow` only run with `-m slow`.
"""

import os
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

settings.register_profile("default", max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("deep", max_examples=2000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: deeper property runs; only with `-m slow`")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if "slow" in (config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="deeper property run: pytest -m slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
