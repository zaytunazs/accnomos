"""Plans the assembly of one sequence of docs/video/manifest.json for assemble.sh (standard library only).

For each segment (an optional title card, the opening provenance card for the judges' video, then every shot) it
writes an ASS subtitle file with the burned-in caption (and, on cards, the card text) and prints one tab-separated line:

    kind  id  duration  source  speed  ass_file  vo_wav

kind is `video` (source = the raw WebM, speed = recorded / duration; above 1.0 it is sped up and the corner says so)
or `card` (source = a background colour). assemble.sh turns each line into one MP4 segment and concatenates them.

    python3 tools/video/segments.py --sequence judges --work docs/video/.work/judges [--no-test-tag]
"""

# ruff: noqa: E501  (ASS style lines and ffmpeg plan rows are long by format)
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# docs/PROVENANCE.md, "The one line for the video" (checked 29 Oct 2026). The script's own first card wins when it has one.
PROVENANCE_TITLE = "Before the hackathon I had only my DGX Spark with Ollama."
PROVENANCE_BODY = (
    "Everything else, all code and every Meta model set-up, was built after kickoff on 26 Oct 2026. "
    "Evidence: docs/PROVENANCE.md"
)
TEST_TAG = "Test-mode capture · fictional sample data · AI stubbed"
INK = "1B1F24"
TEAL_DARK = "0A4F47"


def ass_colour(hex_rgb: str, alpha: int = 0) -> str:
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H{alpha:02X}{b}{g}{r}"


def ts(t: float) -> str:
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


RAW = "\x01"  # an event text starting with this is ASS markup already (override tags, drawings)


def esc(text: str) -> str:
    if text.startswith(RAW):
        return text[1:]
    return text.replace("{", "(").replace("}", ")").replace("\n", "\\N")


def header(w: int, h: int) -> str:
    portrait = h > w
    base = w if portrait else h  # type scales with the short side
    cap = round(base * (0.050 if portrait else 0.042))
    # Safe margins: captions inside title-safe (10 % each side, 8 % from the bottom, above phone UI in vertical clips).
    ml = round(w * 0.10)
    mv = round(h * (0.12 if portrait else 0.08))
    tag = round(base * 0.022)
    title = round(base * (0.075 if portrait else 0.066))
    body = round(base * (0.040 if portrait else 0.036))
    white = ass_colour("FFFFFF")
    box = ass_colour(INK, 0x30)
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Atkinson Hyperlegible,{cap},{white},{white},{box},{box},1,0,0,0,100,100,0,0,3,{round(cap * 0.32)},0,2,{ml},{ml},{mv},1
Style: Tag,Atkinson Hyperlegible,{tag},{white},{white},{box},{box},0,0,0,0,100,100,0,0,3,{round(tag * 0.35)},0,3,{round(w * 0.03)},{round(w * 0.03)},{round(h * 0.02)},1
Style: Title,Atkinson Hyperlegible,{title},{white},{white},{white},{white},1,0,0,0,100,100,0,0,1,0,0,5,{ml},{ml},0,1
Style: Panel,Atkinson Hyperlegible,10,{white},{white},{white},{white},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Mono,DejaVu Sans Mono,{round(body * (0.75 if portrait else 1.0))},{white},{white},{white},{white},0,0,0,0,100,100,0,0,1,0,0,4,{round(w * 0.12)},{round(w * 0.05)},0,1
Style: Body,Atkinson Hyperlegible,{body},{ass_colour("D8E9E6")},{white},{white},{white},0,0,0,0,100,100,0,0,1,0,0,8,{ml},{ml},{round(h * 0.60)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(path: Path, w: int, h: int, events: list[tuple[str, float, float, str]]) -> None:
    lines = [header(w, h)]
    for style, start, end, text in events:
        if text:
            layer = 1 if text.startswith(RAW) else 0  # the end card sits above the shot's caption and tag
            lines.append(f"Dialogue: {layer},{ts(start)},{ts(end)},{style},,0,0,0,,{esc(text)}\n")
    path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--manifest", default=str(ROOT / "docs/video/manifest.json"))
    ap.add_argument("--no-test-tag", action="store_true", help="drop the corner tag once no stubbed AI is on screen")
    ap.add_argument(
        "--title-card", type=float, default=None, help="seconds; default 2 for clips, 0 for the judges' video"
    )
    a = ap.parse_args()
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    seq = next(s for s in manifest["sequences"] if s["id"] == a.sequence)
    w, h = seq["width"], seq["height"]
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    out: list[str] = []

    def end_card_events(dur: float, text: str) -> list[tuple[str, float, float, str]]:
        """An end card over the last 3 s of a shot: a full-frame panel drawn in ASS, then the text."""
        if not text:
            return []
        start = max(0.0, dur - 3.0)
        panel = f"{{\\an7\\pos(0,0)\\p1\\1c&H{TEAL_DARK[4:6]}{TEAL_DARK[2:4]}{TEAL_DARK[0:2]}&\\bord0\\shad0\\fad(250,0)}}m 0 0 l {w} 0 {w} {h} 0 {h}{{\\p0}}"
        return [("Panel", start, dur, RAW + panel), ("Title", start, dur, RAW + "{\\fad(250,0)}" + esc(text))]

    def emit(kind: str, seg_id: str, dur: float, src: str, speed: float, events: list, vo_path: str) -> None:
        ass = work / f"{seg_id}.ass"
        write_ass(ass, w, h, events)
        out.append("\t".join([kind, seg_id, f"{dur:.3f}", src, f"{speed:.4f}", str(ass), vo_path]))

    def card(
        seg_id: str,
        dur: float,
        title: str,
        body: str,
        caption: str = "",
        bg: str = INK,
        vo_path: str = "",
        mono: bool = False,
        end: str = "",
        tag: str = "",
    ) -> None:
        ev = [
            ("Title", 0, dur, title),
            ("Mono" if mono else "Body", 0, dur, body),
            ("Caption", 0, dur, caption),
            ("Tag", 0, dur, tag),
        ]
        emit("card", seg_id, dur, f"0x{bg}", 1.0, ev + end_card_events(dur, end), vo_path)

    shots = seq["shots"]
    title_secs = a.title_card if a.title_card is not None else (0.0 if seq["id"] == "judges" else 2.0)
    first = shots[0] if shots else None
    if seq["id"] == "judges":
        text = (first or {}).get("card", "") + (first or {}).get("caption", "") + (first or {}).get("vo", "")
        if not (first and first["kind"] == "card" and re.search(r"pre-exist|predate|before the hackathon", text, re.I)):
            card("00-provenance", 7.0, PROVENANCE_TITLE, PROVENANCE_BODY)
    if title_secs > 0:
        card("00-title", title_secs, seq["title"], "Accnomos")

    for s in shots:
        vo = ROOT / s["vo_wav"]
        vo_path = str(vo) if vo.exists() else ""
        dur = float(s["duration"])
        end = s.get("end_card") or ""
        live = s.get("live") or ""
        have_video = s["kind"] == "app" and s.get("file") and (ROOT / s["file"]).exists()
        if not have_video:
            if s["kind"] == "card" and not live:
                # A script card: its own text (provenance lines, the eval table), else its caption.
                text = s.get("card") or s["caption"] or s["what"]
                lines = text.split("\n")
                if s.get("card") and len(lines) > 1 and any("  " in ln for ln in lines):  # a table: monospaced
                    card(s["id"], dur, "", text, s["caption"], vo_path=vo_path, mono=True, end=end)
                elif len(lines) > 1:
                    card(s["id"], dur, lines[0], "\n".join(lines[1:]), s["caption"], vo_path=vo_path, end=end)
                else:
                    card(s["id"], dur, text, "", "" if text == s["caption"] else s["caption"], vo_path=vo_path, end=end)
            elif live:
                card(
                    s["id"],
                    dur,
                    "Film live",
                    f"{s['what']}\n\nWhy: {live}",
                    s["caption"],
                    bg="5A3A10",
                    vo_path=vo_path,
                    end=end,
                )
            elif s["kind"] == "camera":
                card(
                    s["id"],
                    dur,
                    "Camera shot (film for real)",
                    s["what"],
                    s["caption"],
                    bg="3C2814",
                    vo_path=vo_path,
                    end=end,
                )
            else:
                card(
                    s["id"],
                    dur,
                    f"Missing footage: {s['id']}",
                    s.get("error") or s["what"],
                    s["caption"],
                    bg="7A2E00",
                    vo_path=vo_path,
                    end=end,
                )
            continue
        recorded = float(s.get("recorded") or dur)
        speed = max(1.0, recorded / dur)
        tags = []
        if live:
            tags.append("Stand-in: film live")
        if not a.no_test_tag:
            tags.append(TEST_TAG)
        if speed > 1.08:
            tags.append(f"sped up ×{speed:.1f}")
        ev = [("Caption", 0.15, dur, s["caption"]), ("Tag", 0, dur, " · ".join(tags))]
        emit("video", s["id"], dur, str(ROOT / s["file"]), speed, ev + end_card_events(dur, end), vo_path)
    print("\n".join(out))


if __name__ == "__main__":
    main()
