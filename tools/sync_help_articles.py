"""Copy the help centre's articles (apps/web/src/content/help/articles.json, the source) to the runtime
(services/runtime/app/support/help_articles.json), which the support assistant retrieves from. The runtime is
deployed without apps/web, so it keeps a copy; tests/test_support.py fails when the two differ.

    python tools/sync_help_articles.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps/web/src/content/help/articles.json"
DST = ROOT / "services/runtime/app/support/help_articles.json"

if __name__ == "__main__":
    shutil.copyfile(SRC, DST)
    print(f"copied {SRC.relative_to(ROOT)} -> {DST.relative_to(ROOT)}")
