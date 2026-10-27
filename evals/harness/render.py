"""Render gold `printed_text` into receipt images (PNG bytes) for extraction evals.

`render_receipt(..., messy=False)` is a clean thermal-roll scan; `messy=True` imitates
a phone photo (rotation, skew, uneven lighting, the odd fold). `render_two_up` puts
two receipts in one photo for the crop/segmentation test. Deterministic per `seed`.
"""

from __future__ import annotations

import io
import random
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFont

PAPER_W = 600
MARGIN = 24
PAPER = (252, 251, 247)
INK = (28, 28, 30)
TABLE = (104, 88, 72)
_FONT_CANDIDATES = (
    "DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/Library/Fonts/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "Menlo.ttc",
)

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


@lru_cache(maxsize=32)
def _font(size: int) -> Font:
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)  # Pillow >= 10.1


def _fit_font(lines: list[str]) -> Font:
    """Largest size (12..22 px) at which the longest line fits the paper width."""
    longest = max(lines, key=len, default="") or " "
    for size in range(22, 11, -1):
        f = _font(size)
        if f.getlength(longest) <= PAPER_W - 2 * MARGIN:
            return f
    return _font(12)


def _paper(text: str, rng: random.Random) -> Image.Image:
    lines = text.expandtabs(4).splitlines() or [""]
    font = _fit_font(lines)
    asc, desc = font.getmetrics() if hasattr(font, "getmetrics") else (12, 4)
    lh = int((asc + desc) * 1.25)
    h = 2 * MARGIN + lh * len(lines)
    img = Image.new("RGB", (PAPER_W, h), PAPER)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((MARGIN, MARGIN + i * lh), line, font=font, fill=INK)
    # 1-2 px grey specks (dust / thermal noise)
    for _ in range(PAPER_W * h // 900):
        x, y, s = rng.randrange(PAPER_W), rng.randrange(h), rng.choice((1, 1, 2))
        g = rng.randint(150, 215)
        d.rectangle((x, y, x + s - 1, y + s - 1), fill=(g, g, g))
    return img


def _fold(img: Image.Image, rng: random.Random) -> None:
    d = ImageDraw.Draw(img)
    y = rng.randint(img.height // 4, 3 * img.height // 4)
    d.line((0, y, img.width, y + rng.randint(-6, 6)), fill=(200, 198, 192), width=2)
    d.line((0, y + 2, img.width, y + 2), fill=(240, 239, 234), width=1)


def _shadow(img: Image.Image, rng: random.Random) -> Image.Image:
    """Multiply by a soft side-to-side lighting gradient (1.0 -> ~0.8)."""
    w, h = img.size
    lo = rng.uniform(0.78, 0.9)
    ramp = Image.linear_gradient("L").rotate(rng.choice((90, -90))).resize((w, h))
    ramp = ramp.point(lambda v: int(255 * (lo + (1 - lo) * v / 255)))
    return ImageChops.multiply(img, Image.merge("RGB", (ramp, ramp, ramp)))


def _photo(paper: Image.Image, rng: random.Random, angle: float) -> Image.Image:
    """Place paper on a table, shear slightly, rotate, return RGB photo."""
    pad = 60
    rgba = paper.convert("RGBA")
    shx, shy = rng.uniform(-0.05, 0.05), rng.uniform(-0.03, 0.03)
    w, h = rgba.size
    out_w, out_h = int(w + abs(shx) * h), int(h + abs(shy) * w)
    off_x = -shx * h if shx > 0 else 0
    off_y = -shy * w if shy > 0 else 0
    rgba = rgba.transform(
        (out_w, out_h), Image.Transform.AFFINE, (1, shx, off_x, shy, 1, off_y),
        resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0),
    )
    rgba = rgba.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))
    canvas = Image.new("RGB", (rgba.width + 2 * pad, rgba.height + 2 * pad), TABLE)
    canvas.paste(rgba, (pad, pad), rgba)
    return canvas


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_receipt(printed_text: str, *, messy: bool = False, seed: int = 0) -> bytes:
    """Render `printed_text` as a 600 px-wide receipt PNG."""
    rng = random.Random(seed)
    paper = _paper(printed_text, rng)
    if not messy:
        return _png(paper)
    if rng.random() < 0.04:
        _fold(paper, rng)
    angle = rng.uniform(2, 6) * rng.choice((-1, 1))
    photo = _photo(paper, rng, angle)
    return _png(_shadow(photo, rng))


def render_two_up(text_a: str, text_b: str, *, seed: int = 0) -> bytes:
    """Two receipts side by side on one table photo, at different angles."""
    rng = random.Random(seed)
    parts = []
    for text, angle in ((text_a, rng.uniform(-9, -3)), (text_b, rng.uniform(3, 9))):
        rgba = _paper(text, rng).convert("RGBA")
        parts.append(rgba.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0)))
    gap, pad = 80, 60
    w = sum(p.width for p in parts) + gap + 2 * pad
    h = max(p.height for p in parts) + 2 * pad + 40
    canvas = Image.new("RGB", (w, h), TABLE)
    x = pad
    for i, part in enumerate(parts):
        canvas.paste(part, (x, pad + (40 if i else 0)), part)
        x += part.width + gap
    return _png(_shadow(canvas, rng))
