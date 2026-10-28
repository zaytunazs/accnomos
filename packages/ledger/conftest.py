"""Make `pytest` import this checkout's `accnomos_ledger`, not another checkout's editable install.

Also the Hypothesis profiles for the property tests (tests/test_properties.py): "default" keeps the suite quick,
HYPOTHESIS_PROFILE=deep runs twenty times the examples.
"""

import os
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

settings.register_profile("default", max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("deep", max_examples=2000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
