"""Cover images for the how-to guides: docs/howto/img/<guide>-cover.png (1280 × 720), the guide's title drawn over
the Muse Image cover art (docs/video/cards/howto-<guide>.png, from tools/video/muse_images.py) or over plain brand
colour when that picture is missing. Adds the cover under each guide's title once. Run by `assemble.sh --covers`.

    python3 tools/video/covers.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from segments import CARDS, CREDIT, TEAL_DARK, write_ass  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HOWTO = ROOT / "docs/howto"
FONTS = Path(__file__).resolve().parent / "fonts"
W, H = 1280, 720


def cover(guide: str, title: str) -> Path:
    out = HOWTO / "img" / f"{guide}-cover.png"
    art = CARDS / f"howto-{guide}.png"
    with tempfile.TemporaryDirectory() as tmp:
        ass = Path(tmp) / "c.ass"
        events = [("Title", 0, 1, title), ("Body", 0, 1, "Accnomos how-to guide")]
        if art.exists():
            # The art leaves its left half plain for the title (docs/video/IMAGE_PROMPTS.md): the title goes on a solid
            # brand panel over exactly that half, so it never sits across the picture; the credit stays bottom right.
            panel = W // 2
            write_ass(ass, panel, H, events)
            credit = Path(tmp) / "credit.ass"
            write_ass(credit, W, H, [("Tag", 0, 1, CREDIT)])
            src = ["-i", str(art), "-f", "lavfi", "-i", f"color=c=0x{TEAL_DARK}:s={panel}x{H}"]
            vf = (
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[art];"
                f"[1:v]subtitles=filename='{ass}':fontsdir='{FONTS}'[panel];"
                f"[art][panel]overlay=0:0,subtitles=filename='{credit}':fontsdir='{FONTS}'"
            )
        else:
            write_ass(ass, W, H, events)
            src = ["-f", "lavfi", "-i", f"color=c=0x{TEAL_DARK}:s={W}x{H}"]
            vf = f"subtitles=filename='{ass}':fontsdir='{FONTS}'"
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                *src,
                "-filter_complex" if art.exists() else "-vf",
                vf,
                "-frames:v",
                "1",
                str(out),
            ],
            check=True,
        )
    return out


def main() -> None:
    for md in sorted(HOWTO.glob("*.md")):
        if md.name == "README.md":
            continue
        guide = md.stem
        text = md.read_text(encoding="utf-8")
        m = re.search(r"^# (.+)$", text, re.M)
        if not m:
            continue
        title = m.group(1).strip()
        out = cover(guide, title)
        line = f"![{title}](img/{out.name})"
        if line not in text:
            text = text[: m.end()] + "\n\n" + line + text[m.end() :]
            md.write_text(text, encoding="utf-8")
        art = "Muse Image art" if (CARDS / f"howto-{guide}.png").exists() else "brand colour (no art yet)"
        print(f"{out.relative_to(ROOT)}  {art}")


if __name__ == "__main__":
    main()
