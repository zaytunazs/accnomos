#!/usr/bin/env python3
"""Draw the fictional demo receipt served at accnomos.com/sample-receipt.png (apps/web/public/).

Deterministic (fixed seed), so re-running gives the same file. The supplier is fictional and the image says so.
The date sits inside the VAT quarter that contains 4 Nov 2026 for every HMRC stagger (Oct–Dec, Nov–Jan, Sep–Nov)
and for monthly returns, so approving it on stage moves Box 4 by £8.65 and Box 7 by £43.

    python tools/make_sample_receipt.py            # writes apps/web/public/sample-receipt.png
    python tools/make_sample_receipt.py out.png
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps/web/public/sample-receipt.png"
DATE = "2026-11-02"
LABEL = "SAMPLE — FICTIONAL COMPANY"
RULE = "-" * 30
LINES = [
    "NOVEX OFFICE SUPPLIES LTD",
    "14 Industrial Park, Leeds",
    "VAT: GB 882431902",
    f"Date: {DATE}",
    RULE,
    "2 x A4 Paper Ream (80gsm)",
    "    2 @ 12.50          25.00",
    "1 x Gel Pens Black (10pk)",
    "    1 @ 18.25          18.25",
    RULE,
    "Net:                   43.25",
    "VAT @ 20%:              8.65",
    RULE,
    "TOTAL:                 51.90",
    "Paid by Card ****4821",
    "Thank you for your business!",
]
FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "DejaVuSansMono.ttf", "consola.ttf", "cour.ttf")


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def receipt() -> Image.Image:
    rnd = random.Random(26)
    body, small = font(21), font(15)
    w, line_h, pad = 500, 29, 28
    h = pad * 2 + line_h * len(LINES) + 40
    paper = Image.new("RGB", (w, h), (246, 245, 240))
    d = ImageDraw.Draw(paper)
    for x in range(w):  # a little shading across the paper
        shade = 246 - int(14 * x / w)
        d.line([(x, 0), (x, h)], fill=(shade, shade - 1, shade - 6))
    for _ in range(260):  # specks
        x, y = rnd.randrange(w), rnd.randrange(h)
        g = rnd.randrange(60, 150)
        d.point((x, y), fill=(g, g, g))
    y = pad
    for text in LINES:
        d.text((pad, y), text, font=body, fill=(28, 28, 30))
        y += line_h
    # The label the brief asks for, boxed so a reader (human or model) cannot miss it.
    tw = d.textlength(LABEL, font=small)
    box = (pad, y + 8, pad + tw + 16, y + 8 + 24)
    d.rectangle(box, outline=(170, 40, 30), width=2)
    d.text((pad + 8, y + 11), LABEL, font=small, fill=(170, 40, 30))
    return paper.filter(ImageFilter.GaussianBlur(0.35))


def main(out: Path) -> None:
    desk = Image.new("RGB", (750, 640), (92, 78, 64))
    dd = ImageDraw.Draw(desk)
    for y in range(desk.height):  # dark desk, lighter towards the top right
        c = 92 - int(18 * y / desk.height)
        dd.line([(0, y), (desk.width, y)], fill=(c, c - 13, c - 27))
    paper = receipt().convert("RGBA").rotate(-4, resample=Image.BICUBIC, expand=True)
    shadow = Image.new("RGBA", paper.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 110), mask=paper.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    x, y = (desk.width - paper.width) // 2, (desk.height - paper.height) // 2
    desk.paste(shadow, (x + 8, y + 10), shadow)
    desk.paste(paper, (x, y), paper)
    out.parent.mkdir(parents=True, exist_ok=True)
    desk.save(out, optimize=True)
    print(f"wrote {out} ({desk.width}x{desk.height}), dated {DATE}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
