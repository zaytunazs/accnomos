"""Make `pytest` import this checkout's `app`, ledger and connectors, not another checkout's editable installs."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parents[1] / "packages/connectors/src", HERE.parents[1] / "packages/ledger/src", HERE):
    sys.path.insert(0, str(path))
