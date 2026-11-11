"""Generate the iOS AppIcon set and launch image from the brand mark.

Source: apps/web/public/brand/zaytuna/icon.svg (the same mark as the Android
launcher and Play icon). Needs `rsvg-convert` (librsvg) and Pillow; runs on
Linux or macOS:

    python3 tools/make_ios_icons.py

* AppIcon: full-bleed square (iOS applies its own corner mask), RGB with no
  alpha channel, which App Store Connect requires for the 1024 px icon.
* LaunchImage: the rounded mark at 112 pt (@1x/@2x/@3x) on a transparent
  background, drawn over the deep-brown launch screen (as Android's
  launch_background.xml).
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "apps/web/public/brand/zaytuna/icon.svg"
ASSETS = ROOT / "apps/mobile/ios/Runner/Assets.xcassets"
ICONSET = ASSETS / "AppIcon.appiconset"
LAUNCH = ASSETS / "LaunchImage.imageset"
BROWN = (0x5A, 0x2D, 0x00)


def render(svg: str, size: int) -> Image.Image:
    png = subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size), "-f", "png"],
        input=svg.encode(),
        capture_output=True,
        check=True,
    ).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> int:
    svg = SVG.read_text(encoding="utf-8")
    square = re.sub(r'rx="\d+(\.\d+)?"', 'rx="0"', svg, count=1)

    master = render(square, 1024)
    flat = Image.new("RGB", master.size, BROWN)
    flat.paste(master, mask=master.getchannel("A"))

    contents = json.loads((ICONSET / "Contents.json").read_text(encoding="utf-8"))
    for image in contents["images"]:
        points = float(image["size"].split("x")[0])
        scale = int(image["scale"].rstrip("x"))
        px = round(points * scale)
        out = flat if px == 1024 else flat.resize((px, px), Image.Resampling.LANCZOS)
        out.save(ICONSET / image["filename"], optimize=True)

    for scale, name in ((1, "LaunchImage.png"), (2, "LaunchImage@2x.png"), (3, "LaunchImage@3x.png")):
        render(svg, 112 * scale).save(LAUNCH / name, optimize=True)

    print(f"Wrote {len(contents['images'])} app icons and 3 launch images.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
