"""Make `pytest` import this checkout's `app` and packages, not another editable install of them."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parents[1] / "packages" / "connectors" / "src", HERE.parents[1] / "packages" / "ledger" / "src", HERE):
    if path.is_dir():
        sys.path.insert(0, str(path))
