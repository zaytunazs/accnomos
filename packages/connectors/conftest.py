"""Make `pytest` import this checkout's connectors, not another editable install of them."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
