"""Contact sheet for one sequence of docs/video/manifest.json: a frame from each shot, labelled with its id, length and
flow; cards and camera shots get a plain tile with their caption. Writes docs/video/contact-sheet-<sequence>.png.

    python tools/video/contact_sheet.py --sequence judges --format landscape
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = Path(__file__).resolve().parent / "fonts"
INK = (27, 31, 36)
TEAL = (15, 110, 99)
GROUND = (244, 243, 238)
WHITE = (255, 255, 255)
AMBER = (176, 82, 0)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "AtkinsonHyperlegible-Bold.ttf" if bold else "AtkinsonHyperlegible-Regular.ttf"
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


def frame(video: Path, at: float, out: Path) -> bool:
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", str(out)],
        check=False,
    )
    return r.returncode == 0 and out.exists()


def wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--format", default="landscape")
    ap.add_argument("--manifest", default=str(ROOT / "docs/video/manifest.json"))
    a = ap.parse_args()
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    seq = next(s for s in manifest["sequences"] if s["id"] == a.sequence)
    portrait = seq["height"] > seq["width"]
    tw, th = (216, 384) if portrait else (384, 216)
    cols = 6 if portrait else 4
    label_h = 54
    pad = 12
    shots = seq["shots"]
    rows = (len(shots) + cols - 1) // cols
    head = 56
    sheet = Image.new("RGB", (pad + cols * (tw + pad), head + rows * (th + label_h + pad) + pad), GROUND)
    d = ImageDraw.Draw(sheet)
    total = seq["duration"]
    d.text(
        (pad, 16),
        f"{seq['id']} · {seq['title']} · {len(shots)} shots · {total:.0f} s · {seq['width']}×{seq['height']}",
        font=font(22, True),
        fill=INK,
    )
    with tempfile.TemporaryDirectory() as tmp:
        for i, s in enumerate(shots):
            x = pad + (i % cols) * (tw + pad)
            y = head + (i // cols) * (th + label_h + pad)
            tile: Image.Image | None = None
            if s.get("file") and (ROOT / s["file"]).exists():
                png = Path(tmp) / f"{s['id']}.png"
                at = max(0.2, (s.get("recorded") or s["duration"]) * 0.7)
                if frame(ROOT / s["file"], at, png):
                    tile = Image.open(png).convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
            if tile is None:
                live = bool(s.get("live"))
                bg = (90, 58, 16) if live else (60, 40, 20) if s["kind"] == "camera" else INK
                tile = Image.new("RGB", (tw, th), bg)
                td = ImageDraw.Draw(tile)
                tag = (
                    "FILM LIVE"
                    if live
                    else {"card": "CARD", "camera": "CAMERA (film for real)"}.get(s["kind"], s["status"].upper())
                )
                td.text(
                    (12, 10), tag, font=font(16, True), fill=(255, 200, 120) if live or s["kind"] == "camera" else WHITE
                )
                yy = 36
                text = s.get("live") if live else s.get("card") or s["caption"] or s["what"]
                for ln in wrap(td, " ".join(text.split()), font(15), tw - 24)[:8]:
                    td.text((12, yy), ln, font=font(15), fill=WHITE)
                    yy += 20
            sheet.paste(tile, (x, y))
            colour = AMBER if s["status"] == "failed" else TEAL
            d.rectangle([x, y, x + tw - 1, y + th - 1], outline=colour, width=2)
            d.text((x, y + th + 6), f"{s['id']} · {s['duration']:g} s", font=font(15, True), fill=INK)
            d.text(
                (x, y + th + 26),
                f"{s['flow']}{' · FAILED' if s['status'] == 'failed' else ''}",
                font=font(14),
                fill=colour,
            )
    out = ROOT / "docs/video" / f"contact-sheet-{a.sequence}.png"
    sheet.save(out, optimize=True)
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
