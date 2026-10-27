"""Render gold documents to PNG/PDF files (same renders `run_extraction --messy` feeds the model).

    cd evals && python -m harness.render_gold OUT_DIR [--only 061_credit_note ...] [--clean]

The seed is the document's position in the sorted gold directory, exactly as in run_extraction.
Prints file sizes; fails if any PNG exceeds 300 KB.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from PIL import Image

from harness.render import render_receipt

GOLD_DIR = Path(__file__).resolve().parents[1] / "gold" / "receipts"
MAX_PNG = 300 * 1024


def gold_files() -> list[Path]:
    return sorted(GOLD_DIR.glob("*.json"))


def render_one(path: Path, idx: int, messy: bool = True) -> bytes:
    gold = json.loads(path.read_text(encoding="utf-8"))
    return render_receipt(gold["printed_text"], messy=messy, seed=idx, damage=gold.get("damage"))


def png_to_pdf(png: bytes) -> bytes:
    """Image-only PDF (a scanned receipt), JPEG-compressed to stay small."""
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, format="PDF", quality=70, resolution=100)
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out", type=Path)
    ap.add_argument("--only", nargs="*", help="gold stems, e.g. 061_credit_note")
    ap.add_argument("--clean", action="store_true", help="clean scans instead of messy photos")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    biggest = 0
    for idx, path in enumerate(gold_files()):
        if args.only and path.stem not in args.only:
            continue
        png = render_one(path, idx, messy=not args.clean)
        (args.out / f"{path.stem}.png").write_bytes(png)
        biggest = max(biggest, len(png))
    print(f"largest PNG: {biggest / 1024:.0f} KB")
    if biggest > MAX_PNG:
        raise SystemExit("a PNG exceeds 300 KB")


if __name__ == "__main__":
    main()
