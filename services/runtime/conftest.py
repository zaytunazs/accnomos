"""Make `pytest` import this checkout's `app`, not another editable install of accnomos-runtime."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
