"""Make `pytest` import this checkout's `relay`, not another checkout's editable install."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
