"""Help centre pictures: PNG screenshots -> apps/web/public/help/<name>.webp (1280 wide, WebP quality 78).

Sources: the new shots from apps/web/e2e/help-shots.spec.ts (apps/web/test-results/help-shots/*.png) and a few how-to
shots reused from docs/howto/img/ (REUSED). Every picture is read with OCR (tesseract, when installed) first and refused
if its text names an AI vendor or model: help pictures say "the AI", never a model or vendor name.

    python tools/help_shots_webp.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "apps/web/test-results/help-shots"
HOWTO = ROOT / "docs/howto/img"
OUT = ROOT / "apps/web/public/help"
# Checked by OCR on 11 Nov 2026: no vendor or model names in these.
REUSED = [
    "connect-books-1", "connect-books-2", "connect-books-4", "review-approve-1", "review-approve-2",
    "reconcile-bank-1", "reconcile-bank-2", "reconcile-bank-3", "vat-return-1", "vat-return-2", "vat-return-4",
]  # fmt: skip
BANNED = re.compile(r"(?i:\bmeta\b|\bmuse\b|glimmer|llama|anthropic|claude|openai|qwen|whisper)|\bSAM\b")


def ocr_problem(png: Path) -> str | None:
    if shutil.which("tesseract") is None:
        return None
    text = subprocess.run(["tesseract", str(png), "-"], capture_output=True, text=True, check=False).stdout
    hit = BANNED.search(text)
    return f"names {hit.group(0)!r}" if hit else None


def convert(png: Path, name: str) -> bool:
    if problem := ocr_problem(png):
        print(f"REFUSED {name}: {problem}")
        return False
    img = Image.open(png).convert("RGB")
    if img.width > 1280:
        img = img.resize((1280, round(img.height * 1280 / img.width)))
    img.save(OUT / f"{name}.webp", "WEBP", quality=78, method=6)
    print(f"ok {name}.webp ({(OUT / f'{name}.webp').stat().st_size // 1024} KB)")
    return True


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    for name in REUSED:
        bad += not convert(HOWTO / f"{name}.png", name)
    for png in sorted(NEW.glob("*.png")) if NEW.exists() else []:
        bad += not convert(png, png.stem)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
