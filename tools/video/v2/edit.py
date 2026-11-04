#!/usr/bin/env python3
"""Demo video v2: cut the live footage, the voice-over and the cards into the submission video (ffmpeg + Pillow).

    python3 edit.py ROOT [--only s3] [--draft]
ROOT holds raw/ (capture_live.ts WebMs + phone.ps1 MP4s, each with its marks), vo/s1..s8.wav, cards/ (the Muse Image
art: judges-title.png, section-demo.png, section-meta-ai.png) and fonts/ (Atkinson Hyperlegible). Writes ROOT/out/:

  accnomos-demo-v2.mp4          1080p H.264, voice-over + burned-in UK English captions
  accnomos-demo-v2-novo.mp4     the same picture without voice or captions, for a new voice-over
  accnomos-demo-v2-vo.wav       the voice-over alone, timed to the picture (48 kHz)
  accnomos-demo-v2.srt          the captions
  timeline.json                 every scene and shot with its start time (for re-voicing)

The edit is data: EDL below. Each scene has a voice line (vo/<id>.wav, starting `lead` seconds into the scene) and
shots played back to back; a shot's `segs` pick seconds of its source ("a..b", where a/b are numbers, "end", or a
mark name from the capture, optionally +/- seconds), joined with a short crossfade, then fitted to `dur`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
BROWN, CREAM, GOLD, DARK = "#5A2D00", "#F8F6F3", "#C9A45C", "#2A1A0D"
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), "-video_track_timescale", "15360"]
XF = 0.3  # crossfade between the kept parts of one recording

# --------------------------------------------------------------------------------------------------------------------
# The edit. Lower thirds: (feature, the Meta model at work). Text on screen: UK English, Meta models only.
EDL: list[dict] = [
    {"id": "title", "card": "title", "dur": 2.6},
    {"id": "s1", "lead": 0.3, "lt": ("Home, in plain English", "Summary worded by Muse Spark · figures by code"), "shots": [
        {"layout": "split", "src": "w-home", "segs": ["0..end"], "phone": "p-home", "psegs": ["0..end"], "dur": 17.6},
    ]},
    {"id": "s2", "lead": 0.3, "lt": ("Goals and spending", "Progress note by Muse Spark"), "shots": [
        {"layout": "full", "src": "w-goals", "segs": ["0..end"], "dur": 6.6},
        {"layout": "full", "src": "w-spending", "segs": ["0..end"], "dur": 4.4},
    ]},
    {"id": "s3", "lead": 0.3, "lt": ("Talk to your books", "Muse Voice Transcribe · Muse Spark"), "shots": [
        {"layout": "full", "src": "w-home-action", "segs": ["0..end"], "dur": 6.0},
        {"layout": "full", "src": "w-talk", "segs": ["0..wait+1.6", "ready-0.4..end"], "dur": 11.5},
    ]},
    {"id": "s4", "lead": 0.3, "lt": ("Receipts and invoices", "Read by Muse Spark · checked by code"), "shots": [
        {"layout": "phone", "src": "p-receipt", "segs": ["0..wait+1.0", "ready-0.3..wait2+1.5", "ready2-0.5..end"], "dur": 10.5,
         "side": ("Snap a receipt", "Muse Spark reads it. Code checks every number. You approve.")},
        {"layout": "full", "src": "w-invoice", "segs": ["0..wait+1.4", "ready-0.4..wait2+0.8", "ready2-0.2..end"], "dur": 9.4},
    ]},
    {"id": "s5", "lead": 0.3, "lt": ("Reports and VAT", "Worked out by code from the ledger"), "shots": [
        {"layout": "full", "src": "w-reports", "segs": ["0..end"], "dur": 5.4},
        {"layout": "split", "src": "w-vat", "segs": ["0..end"], "phone": "p-vat", "psegs": ["0..end"], "dur": 7.6},
    ]},
    {"id": "s6", "lead": 0.3, "lt": ("Sole traders, landlords and households", "Quarterly MTD updates · household budget"), "shots": [
        {"layout": "full", "src": "w-selfemp", "segs": ["0..end"], "dur": 5.6},
        {"layout": "split", "src": "w-personal", "segs": ["0..end"], "phone": "p-personal", "psegs": ["0..end"], "dur": 6.2},
        {"layout": "full", "src": "w-personal-cal", "segs": ["0..wait+1.2", "ready-0.3..wait2+0.6", "ready2..end"], "dur": 5.0},
    ]},
    {"id": "s7", "lead": 0.3, "lt": ("Your choice of Meta model", "Muse Spark (Meta API) · Muse Glimmer 30B (open weights)"), "shots": [
        {"layout": "full", "src": "w-ai", "segs": ["0..end"], "dur": 9.0},
        {"layout": "full", "src": "w-calls", "segs": ["0..end"], "dur": 5.0},
        {"layout": "full", "src": "w-files", "segs": ["0..end"], "dur": 4.6},
        {"layout": "full", "src": "w-backups", "segs": ["0..end"], "dur": 3.0},
    ]},
    {"id": "s8", "lead": 0.4, "card": "end", "dur": 20.6},
    {"id": "judges", "card": "judges", "dur": 6.6},
]

# --------------------------------------------------------------------------------------------------------------------


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd[:8])} …")


def probe_dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def wav_dur(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


class Fonts:
    def __init__(self, root: Path):
        d = root / "fonts"
        self.bold = str(d / "AtkinsonHyperlegible-Bold.ttf")
        self.reg = str(d / "AtkinsonHyperlegible-Regular.ttf")

    def b(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.bold, size)

    def r(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.reg, size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        t = f"{line} {word}".strip()
        if draw.textlength(t, font=font) <= width or not line:
            line = t
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


# --------------------------------------------------------------------------------------------------------------------
# Marks and segments


def marks_of(raw: Path, src: str) -> dict[str, float]:
    m: dict[str, float] = {}
    j = raw / f"{src}.marks.json"
    t = raw / f"{src}.marks.txt"
    if j.exists():
        m.update(json.loads(j.read_text(encoding="utf-8-sig")).get("marks", {}))
    if t.exists():
        for line in t.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            p = line.split()
            if len(p) == 3 and p[0] == "MARK":
                m[p[1]] = float(p[2])
    return m


def source(raw: Path, src: str) -> Path:
    for ext in (".webm", ".mp4"):
        if (raw / f"{src}{ext}").exists():
            return raw / f"{src}{ext}"
    raise FileNotFoundError(f"raw/{src}.webm|mp4")


def resolve(expr: str, marks: dict[str, float], end: float) -> float:
    m = re.fullmatch(r"\s*([A-Za-z_][\w]*|[\d.]+)\s*(?:([+-])\s*([\d.]+))?\s*", expr)
    if not m:
        raise ValueError(expr)
    base = m[1]
    if re.fullmatch(r"[\d.]+", base):
        v = float(base)
    elif base == "end":
        v = end
    elif base in marks:
        v = marks[base]
    else:
        raise KeyError(f"mark {base!r} missing (have {sorted(marks)})")
    if m[2]:
        v += float(m[3]) * (1 if m[2] == "+" else -1)
    return max(0.0, min(end, v))


def segments(raw: Path, src: str, segs: list[str]) -> list[tuple[float, float]]:
    p = source(raw, src)
    end = probe_dur(p)
    marks = marks_of(raw, src)
    out = []
    for s in segs:
        a, b = s.split("..")
        try:
            ta, tb = resolve(a, marks, end), resolve(b, marks, end)
        except KeyError as e:  # a step that did not happen on this take: keep the whole source
            print(f"  {src}: {e}; using 0..end", file=sys.stderr)
            return [(0.0, end)]
        if tb - ta > 0.2:
            out.append((ta, tb))
    return out or [(0.0, end)]


def chain(label_in: str, segs: list[tuple[float, float]], dur: float, tag: str, pre: str = "") -> tuple[str, str]:
    """Filter text: the kept parts of one input joined with crossfades, fitted to `dur` (sped up a little if long,
    held on the last frame if short). Returns (filter, output label)."""
    f = []
    labels = []
    for i, (a, b) in enumerate(segs):
        lab = f"{tag}p{i}"
        f.append(f"[{label_in}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},{pre}format=yuv420p,settb=1/{FPS * 512}[{lab}]")
        labels.append((lab, b - a))
    # split the input once per segment
    if len(segs) > 1:
        f.insert(0, f"[{label_in}]split={len(segs)}" + "".join(f"[{tag}in{i}]" for i in range(len(segs))))
        f[1:] = [s.replace(f"[{label_in}]", f"[{tag}in{i}]", 1) for i, s in enumerate(f[1:])]
    cur, cur_len = labels[0]
    for i, (lab, ln) in enumerate(labels[1:], 1):
        out = f"{tag}x{i}"
        off = max(0.05, cur_len - XF)
        f.append(f"[{cur}][{lab}]xfade=transition=fade:duration={XF}:offset={off:.3f}[{out}]")
        cur, cur_len = out, cur_len + ln - XF
    total = cur_len
    speed = 1.0
    if total > dur:
        speed = min(total / dur, 1.6)
    out = f"{tag}fit"
    f.append(f"[{cur}]setpts=PTS/{speed:.4f},fps={FPS},tpad=stop_mode=clone:stop_duration={dur + 1:.2f},trim=duration={dur:.3f},setpts=PTS-STARTPTS[{out}]")
    if speed > 1.02:
        print(f"  {tag}: {total:.1f}s of footage in {dur:.1f}s (x{speed:.2f}){'  TRIMMED' if total / dur > 1.6 else ''}", file=sys.stderr)
    return ";".join(f), out


# --------------------------------------------------------------------------------------------------------------------
# Graphics (Pillow): phone frame, lower thirds, cards


def phone_assets(work: Path, sw: int, sh: int) -> tuple[Path, Path, int, int]:
    """A dark device frame for a sw x sh screen, and the screen's rounded-corner mask. Returns (frame, mask, fw, fh)."""
    bez, r = 16, 46
    fw, fh = sw + 2 * bez, sh + 2 * bez
    frame = Image.new("RGBA", (fw + 60, fh + 60), (0, 0, 0, 0))
    sh_ = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh_).rounded_rectangle((30, 40, 30 + fw, 40 + fh), r + bez, fill=(0, 0, 0, 110))
    frame = Image.alpha_composite(frame, sh_.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(frame)
    d.rounded_rectangle((30, 30, 30 + fw, 30 + fh), r + bez, fill=(22, 16, 12, 255))
    d.rounded_rectangle((31, 31, 29 + fw, 29 + fh), r + bez, outline=(90, 70, 55, 255), width=2)
    d.rounded_rectangle((30 + bez, 30 + bez, 30 + bez + sw, 30 + bez + sh), r, fill=(0, 0, 0, 0))
    fp = work / f"phone_frame_{sw}x{sh}.png"
    frame.save(fp)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), r, fill=255)
    mp = work / f"phone_mask_{sw}x{sh}.png"
    mask.save(mp)
    return fp, mp, fw + 60, fh + 60


def lower_third(work: Path, fonts: Fonts, sid: str, title: str, model: str) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ft, fm = fonts.b(34), fonts.r(26)
    tw = max(d.textlength(title, font=ft), d.textlength(model, font=fm))
    x, y, pad = 48, 64, 22
    box = (x, y, x + tw + 2 * pad + 10, y + 112)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((box[0] + 4, box[1] + 6, box[2] + 4, box[3] + 6), 14, fill=(0, 0, 0, 90))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, 14, fill=(90, 45, 0, 240))
    d.rounded_rectangle((box[0], box[1], box[0] + 10, box[3]), 5, fill=GOLD)
    d.text((x + pad + 10, y + 16), title, font=ft, fill=CREAM)
    d.text((x + pad + 10, y + 64), model, font=fm, fill="#E8D7AE")
    p = work / f"lt_{sid}.png"
    img.save(p)
    return p


def side_panel(work: Path, fonts: Fonts, tag: str, head: str, body: str, x0: int, x1: int) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fh, fb = fonts.b(76), fonts.r(40)
    y = 330
    for line in wrap(d, head, fh, x1 - x0):
        d.text((x0, y), line, font=fh, fill=BROWN)
        y += 92
    d.rectangle((x0, y + 18, x0 + 110, y + 26), fill=GOLD)
    y += 64
    for line in wrap(d, body, fb, x1 - x0):
        d.text((x0, y), line, font=fb, fill=DARK)
        y += 56
    p = work / f"side_{tag}.png"
    img.save(p)
    return p


def fill(img: Image.Image) -> Image.Image:
    s = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    l, t = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((l, t, l + W, t + H)).convert("RGB")


def card_image(root: Path, work: Path, fonts: Fonts, kind: str) -> Path:
    cards = root / "cards"
    if kind == "title":
        img = fill(Image.open(cards / "judges-title.png"))
        d = ImageDraw.Draw(img)
        d.text((150, 330), "Accnomos", font=fonts.b(150), fill=CREAM)
        d.rectangle((156, 520, 296, 530), fill=GOLD)
        d.text((150, 572), "Your business and household money,", font=fonts.r(52), fill=CREAM)
        d.text((150, 640), "in plain English.", font=fonts.r(52), fill=CREAM)
        d.text((150, 760), "Running on Meta's Muse models", font=fonts.b(38), fill=GOLD)
    elif kind == "end":
        img = fill(Image.open(cards / "section-demo.png"))
        d = ImageDraw.Draw(img)
        cx = W // 2

        def centre(y: int, text: str, font, colour: str) -> None:
            d.text((cx - d.textlength(text, font=font) / 2, y), text, font=font, fill=colour)

        centre(515, "Accnomos", fonts.b(104), BROWN)
        centre(648, "accnomos.com  ·  Try the demo, no sign-in", fonts.b(46), DARK)
        centre(716, "github.com/zaytunazs/accnomos", fonts.r(42), DARK)
        centre(790, "HMRC filing in this demo goes to HMRC's sandbox.", fonts.r(30), "#6b5a48")
    elif kind == "judges":
        img = fill(Image.open(cards / "section-meta-ai.png"))
        scrim = Image.new("RGBA", (W, H), (42, 26, 13, 215))
        img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")
        d = ImageDraw.Draw(img)
        x, y = 110, 80
        d.text((x, y), "For the judges", font=fonts.b(58), fill=GOLD)
        y += 100
        rows = [
            ("Meta models at run time", "Muse Spark 1.3 (Meta Model API, the default) · Muse Glimmer 30B (Meta open weights, on our own GPU server or the user's computer) · Muse Voice Transcribe. Muse Image made the art at build time."),
            ("Measured", "Share of 200 synthetic documents with every field right, clean / messy:  Muse Spark 1.3  95 % / 96 %  ·  Glimmer  85 % / 80 %"),
            ("Provenance", "Live call records for both models: docs/submission/OPEN_WEIGHTS.md"),
            ("Try it", "accnomos.com, then Try the demo. Android APK on GitHub Releases; the Play listing is in review."),
            ("Limits", "HMRC filing is sandbox only. The demo data is fictional."),
        ]
        fl, fb = fonts.b(34), fonts.r(32)
        for head, body in rows:
            d.text((x, y), head, font=fl, fill=CREAM)
            yy = y
            for line in wrap(d, body, fb, W - 2 * x - 470):
                d.text((x + 470, yy), line, font=fb, fill="#EFE6D8")
                yy += 44
            y = max(y + 52, yy) + 34
    else:
        raise ValueError(kind)
    p = work / f"card_{kind}.png"
    img.save(p)
    return p


# --------------------------------------------------------------------------------------------------------------------
# Rendering


def render_shot(root: Path, work: Path, fonts: Fonts, scene: dict, i: int, shot: dict, out: Path) -> None:
    raw = root / "raw"
    dur = shot["dur"]
    inputs: list[str] = []
    fl: list[str] = []
    tag = f"{scene['id']}_{i}"
    layout = shot["layout"]
    inputs += ["-i", str(source(raw, shot["src"]))]
    if layout == "full":
        f, v = chain("0:v", segments(raw, shot["src"], shot["segs"]), dur, "a", pre=f"scale={W}:{H}:flags=lanczos,")
        fl.append(f)
        base = v
        n = 1
    else:
        sw, sh = (450, 1000) if layout == "phone" else (404, 898)
        frame, mask, fw, fh = phone_assets(work, sw, sh)
        psrc = shot["src"] if layout == "phone" else shot["phone"]
        psegs = shot["segs"] if layout == "phone" else shot["psegs"]
        if layout == "split":
            inputs += ["-i", str(source(raw, psrc))]
            pin = "1:v"
            n = 2
        else:
            pin = "0:v"
            n = 1
        inputs += ["-loop", "1", "-i", str(frame), "-loop", "1", "-i", str(mask)]
        fi, mi = n, n + 1
        n += 2
        f, pv = chain(pin, segments(raw, psrc, psegs), dur, "p", pre=f"scale={sw}:{sh}:flags=lanczos,")
        fl.append(f)
        fl.append(f"[{mi}:v]format=gray,trim=duration={dur:.3f},fps={FPS}[pm];[{pv}]format=rgba[pva];[pva][pm]alphamerge[pmasked]")
        bg = f"color=c={'0xF8F6F3' if layout == 'phone' else '0x2A1A0D'}:s={W}x{H}:r={FPS}:d={dur:.3f}"
        fl.append(f"{bg}[bg]")
        if layout == "split":
            ww, wh = 1392, 783
            f, wv = chain("0:v", segments(raw, shot["src"], shot["segs"]), dur, "w", pre=f"scale={ww}:{wh}:flags=lanczos,")
            fl.append(f)
            wx, wy = 56, 200
            px = wx + ww + (W - (wx + ww) - fw) // 2 + 8
            py = (H - fh) // 2 + 4
            fl.append(f"[bg][{wv}]overlay={wx}:{wy}[b1]")
            prev = "b1"
        else:
            px, py = 1180, (H - fh) // 2 + 4
            head, body = shot.get("side", ("", ""))
            sp = side_panel(work, fonts, tag, head, body, 150, 1040)
            inputs += ["-loop", "1", "-i", str(sp)]
            si = n
            n += 1
            fl.append(f"[bg][{si}:v]overlay=0:0:shortest=1[b1]")
            prev = "b1"
        fl.append(f"[{fi}:v]trim=duration={dur:.3f},fps={FPS}[fr];[{prev}][fr]overlay={px}:{py}[b2];[b2][pmasked]overlay={px + 46}:{py + 46}[b3]")
        base = "b3"
    if i == 0 and scene.get("lt"):
        lt = lower_third(work, fonts, scene["id"], *scene["lt"])
        inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(lt)]
        li = n
        n += 1
        fl.append(f"[{li}:v]format=rgba,fade=t=in:st=0.25:d=0.4:alpha=1,fade=t=out:st=4.8:d=0.5:alpha=1[lt];[{base}][lt]overlay=0:0:shortest=1[lto]")
        base = "lto"
    fl.append(f"[{base}]trim=duration={dur:.3f},setpts=PTS-STARTPTS,format=yuv420p[vout]")
    tmp = out.with_name(out.stem + ".part.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fl), "-map", "[vout]", "-an", *ENC, "-t", f"{dur:.3f}", str(tmp)])
    tmp.rename(out)


def render_card(root: Path, work: Path, fonts: Fonts, scene: dict, out: Path) -> None:
    img = card_image(root, work, fonts, scene["card"])
    dur = scene["dur"]
    # a slow push-in (3 %) so a long card does not look frozen; fade in from black on the first card
    z = 0.03
    vf = (f"scale={W * 2}:{H * 2},zoompan=z='1+{z}*on/({dur * FPS:.0f})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={round(dur * FPS)}:s={W}x{H}:fps={FPS},"
          f"format=yuv420p")
    if scene["card"] == "title":
        vf += ",fade=t=in:st=0:d=0.5"
    if scene["card"] == "judges":
        vf += f",fade=t=out:st={dur - 0.6:.2f}:d=0.6"
    tmp = out.with_name(out.stem + ".part.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(img), "-vf", vf, "-frames:v", str(round(dur * FPS)), *ENC, str(tmp)])
    tmp.rename(out)


# --------------------------------------------------------------------------------------------------------------------
# Captions and audio


def silences(p: Path) -> list[tuple[float, float]]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", "silencedetect=noise=-38dB:d=0.22", "-f", "null", "-"], capture_output=True, text=True)
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(st, en))


def chunks(text: str, limit: int = 84) -> list[str]:
    """Caption-sized pieces (at most two lines), split at sentence and clause ends."""
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?:])\s+", text.strip()):
        parts = [sent]
        while any(len(p) > limit for p in parts):
            nxt = []
            for p in parts:
                if len(p) <= limit:
                    nxt.append(p)
                    continue
                cut = max((m.end() for m in re.finditer(r"[,;:]\s", p) if m.end() < len(p) - 8 and m.end() > 12), key=lambda e: -abs(e - len(p) / 2), default=None)
                if cut is None:
                    words = p.split()
                    half = len(words) // 2
                    nxt += [" ".join(words[:half]), " ".join(words[half:])]
                else:
                    nxt += [p[:cut].strip(), p[cut:].strip()]
            parts = nxt
        out += parts
    return out


def timed_captions(text: str, wav: Path) -> list[tuple[float, float, str]]:
    """Each chunk gets a share of the line's length; chunk boundaries snap to the pauses the voice leaves."""
    d = wav_dur(wav)
    sil = [(a, b) for a, b in silences(wav) if 0.3 < a < d - 0.3]
    cs = chunks(text)
    tot = sum(len(c) for c in cs)
    t, raw_b = 0.0, []
    lead = sil[0][1] if sil and sil[0][0] < 0.05 else 0.0
    speak = d - lead
    acc = 0
    for c in cs[:-1]:
        acc += len(c)
        raw_b.append(lead + speak * acc / tot)
    mids = [(a + b) / 2 for a, b in sil]
    bounds = []
    for b in raw_b:
        near = min(mids, key=lambda m: abs(m - b), default=None)
        bounds.append(near if near is not None and abs(near - b) < 0.9 else b)
    edges = [0.0, *bounds, d]
    return [(edges[i], edges[i + 1], c) for i, c in enumerate(cs)]


def ts_srt(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def ts_ass(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_subs(caps: list[tuple[float, float, str]], srt: Path, ass: Path) -> None:
    srt.write_text("".join(f"{i}\n{ts_srt(a)} --> {ts_srt(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(caps, 1)), encoding="utf-8")
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Atkinson Hyperlegible,46,&H00FFFFFF,&H00FFFFFF,&H5A1A0D2A,&H5A1A0D2A,1,0,0,0,100,100,0,0,3,14,0,2,260,260,44,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass.write_text(head + "".join(f"Dialogue: 0,{ts_ass(a)},{ts_ass(b - 0.04)},Cap,,0,0,0,,{t}\n" for a, b, t in caps), encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------------


def contact_sheet(video: Path, timeline: list[dict], dest: Path) -> None:
    """One frame from the middle of every shot, 4 across, with its time."""
    times = []
    for sc in timeline:
        t0 = sc["start"]
        for sh in sc["shots"]:
            times.append((t0 + sh["dur"] / 2, f"{sc['scene']} {sh['src']}"))
            t0 += sh["dur"]
    tiles = []
    for t, label in times:
        f = dest.with_name(f".cs_{len(tiles)}.jpg")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:270", str(f)])
        im = Image.open(f).convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 480, 26), fill=(0, 0, 0))
        d.text((6, 4), f"{int(t // 60)}:{t % 60:05.2f}  {label}", fill=(255, 255, 255))
        tiles.append(im)
        f.unlink()
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 480, rows * 270), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 480, (i // cols) * 270))
    sheet.save(dest, quality=85)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", action="store_true", help="reuse scene files already rendered")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    work, out = root / "work", root / "out"
    work.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    fonts = Fonts(root)
    only = set(filter(None, a.only.split(",")))
    lines = {x["id"]: x["text"] for x in json.loads((root / "vo_lines.json").read_text(encoding="utf-8"))}

    files, timeline, caps, vo_parts = [], [], [], []
    t = 0.0
    for sc in EDL:
        sid = sc["id"]
        wav = root / "vo" / f"{sid}.wav"
        vo_len = wav_dur(wav) if wav.exists() else 0.0
        if "card" in sc:
            pieces = [(work / f"{sid}.mp4", sc["dur"], None)]
        else:
            pieces = [(work / f"{sid}_{i}.mp4", s["dur"], s) for i, s in enumerate(sc["shots"])]
        sdur = sum(p[1] for p in pieces)
        lead = sc.get("lead", 0.3)
        if vo_len and lead + vo_len > sdur - 0.2:
            print(f"WARNING {sid}: voice {vo_len:.1f}s + lead {lead}s is longer than the scene ({sdur:.1f}s)", file=sys.stderr)
        for i, (f, d, shot) in enumerate(pieces):
            if (not only or sid in only) and not (a.keep and f.exists()):
                print(f"render {f.name} ({d:.1f}s)", file=sys.stderr, flush=True)
                if shot is None:
                    render_card(root, work, fonts, sc, f)
                else:
                    render_shot(root, work, fonts, sc, i, shot, f)
            files.append(f)
        if vo_len:
            vo_parts.append((wav, t + lead))
            caps += [(t + lead + x, t + lead + y, c) for x, y, c in timed_captions(lines[sid], wav)]
        timeline.append({"scene": sid, "start": round(t, 2), "dur": round(sdur, 2), "vo_start": round(t + lead, 2) if vo_len else None,
                         "vo_len": round(vo_len, 2), "shots": [{"src": (p[2] or {}).get("src", sc.get("card")), "layout": (p[2] or {}).get("layout", "card"), "dur": p[1]} for p in pieces],
                         "text": lines.get(sid, "")})
        t += sdur
    total = t
    print(f"total {total:.2f}s", file=sys.stderr)
    if only:
        return

    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{f}'\n" for f in files))
    clean = work / "clean.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(clean)])

    # voice-over track, timed to the picture, loudness-normalised (-16 LUFS, web)
    vo = out / "accnomos-demo-v2-vo.wav"
    ins, flt = [], []
    for k, (w, st) in enumerate(vo_parts):
        ins += ["-i", str(w)]
        flt.append(f"[{k}:a]aresample=48000,adelay={round(st * 1000)}:all=1[a{k}]")
    flt.append("".join(f"[a{k}]" for k in range(len(vo_parts))) + f"amix=inputs={len(vo_parts)}:normalize=0,apad,atrim=duration={total:.3f},loudnorm=I=-16:TP=-1.5:LRA=7[vo]")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins, "-filter_complex", ";".join(flt), "-map", "[vo]", "-ar", "48000", "-ac", "1", str(vo)])

    srt, ass = out / "accnomos-demo-v2.srt", work / "captions.ass"
    write_subs(caps, srt, ass)
    fontsdir = str(root / "fonts")
    final = out / "accnomos-demo-v2.mp4"
    tmp = final.with_name("final.part.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(clean), "-i", str(vo), "-vf", f"subtitles=filename={ass}:fontsdir={fontsdir}",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-ac", "2", "-movflags", "+faststart", "-shortest", str(tmp)])
    tmp.rename(final)
    novo = out / "accnomos-demo-v2-novo.mp4"
    tmp = novo.with_name("novo.part.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(clean), "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", "-shortest", str(tmp)])
    tmp.rename(novo)
    contact_sheet(final, timeline, out / "accnomos-demo-v2-contact-sheet.jpg")
    (out / "timeline.json").write_text(json.dumps({"total": round(total, 2), "scenes": timeline}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"DONE {final} {probe_dur(final):.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
