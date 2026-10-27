"""Make `pytest` import this checkout's ledger, not another editable install of it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
