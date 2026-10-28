"""Accnomos teaser 1: 44 s, original synthesised music, Kokoro TTS voice-over, real app screenshots only.

    python tools/teaser/build.py                                  # 16:9 and 1:1, social and submission cuts, thumbnail
    python tools/teaser/build.py --formats 9x16 --variants social # other formats: 16x9, 1x1, 9x16
    python tools/teaser/build.py --stills-only --frames 5,12      # PNG stills into tools/teaser/.cache/stills/ only

Outputs in docs/submission/teaser/: accnomos-teaser1-<format>_<social|submission>.mp4 and
accnomos-teaser1-thumbnail.png.
`social` says "Launching November 2026" and keeps the "coming soon" beats; `submission` (judges) shows only what runs
today and ends on "Try the demo".

Material: the app's own screenshots (docs/submission/shots/, apps/mobile/screenshots/ from the Android app; a 2x
re-take in tools/teaser/shots/ is preferred when present), the Muse Image brand art in apps/web/public/brand/, the
voice clips in tools/teaser/vo/ (Kokoro TTS, Apache-2.0; text in vo/lines.json) and text. Device frames, type,
captions and motion are drawn here; the music is tools/teaser/music.py. Cuts sit on the voice and the 120 BPM grid.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import wave
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import music  # noqa: E402

FFMPEG = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
CACHE = Path(os.environ.get("TEASER_CACHE", HERE / ".cache"))  # a separate cache lets two formats render at once
OUT = Path(os.environ.get("TEASER_OUT", ROOT / "docs/submission/teaser"))
FPS = 30
DURATION = 44.0
END_START = 38.0  # end card and drums-out
BEAT = 0.5

# apps/web/src/app/globals.css
INK = (27, 31, 36)
TEAL = (15, 110, 99)
TEAL_DARK = (10, 79, 71)
TEAL_TINT = (230, 241, 239)
GROUND = (244, 243, 238)
MUTED = (75, 81, 89)
BORDER = (227, 225, 216)
WHITE = (255, 255, 255)

FORMATS = {"16x9": (1920, 1080), "1x1": (1080, 1080), "9x16": (1080, 1920)}
MANROPE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/Manrope%5Bwght%5D.ttf"


# ---------------------------------------------------------------- material


@lru_cache(None)
def load(path: str) -> Image.Image:
    return Image.open(path).convert("RGB")


def font_path() -> Path | None:
    p = CACHE / "Manrope.ttf"
    if not p.exists():
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(MANROPE_URL, p)  # OFL font used by the web app (next/font)
        except Exception:
            return None
    return p


@lru_cache(None)
def font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    p = font_path()
    if p:
        f = ImageFont.truetype(str(p), size)
        with contextlib.suppress(Exception):
            f.set_variation_by_axes([weight])
        return f
    name = {800: "Bold", 700: "Bold", 600: "SemiBold", 500: "Medium"}.get(weight, "Regular")
    return ImageFont.truetype(f"/usr/share/fonts/opentype/inter/InterDisplay-{name}.otf", size)


# ---------------------------------------------------------------- easing and drawing helpers


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def lerp(a, b, t):
    return a + (b - a) * t


@lru_cache(64)
def rounded_mask(size, radius) -> Image.Image:
    w, h = size
    s = 3  # supersample for smooth corners
    m = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius * s, fill=255)
    return m.resize((w, h), Image.LANCZOS)


@lru_cache(64)
def shadow(size, radius, blur, opacity) -> Image.Image:
    w, h = size
    pad = blur * 3
    m = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(m).rounded_rectangle([pad, pad, pad + w, pad + h], radius, fill=int(255 * opacity))
    m = m.filter(ImageFilter.GaussianBlur(blur))
    img = Image.new("RGBA", m.size, (10, 40, 36, 0))
    img.putalpha(m)
    return img


def paste_alpha(canvas: Image.Image, layer: Image.Image, xy, alpha: float = 1.0):
    if alpha <= 0:
        return
    if alpha < 1:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer = layer.copy()
        layer.putalpha(a)
    canvas.alpha_composite(layer, (int(round(xy[0])), int(round(xy[1]))))


def crop_view(img: Image.Image, cx: float, cy: float, zoom: float, out_size) -> Image.Image:
    """Ken Burns view: centre (cx, cy) in 0–1 of the image, zoom 1 = image width fills the view."""
    ow, oh = out_size
    iw, ih = img.size
    cw = iw / zoom
    ch = cw * oh / ow
    if ch > ih:  # taller view than the image allows: fit height instead
        ch = ih
        cw = ch * ow / oh
    x0 = clamp(cx * iw - cw / 2, 0, iw - cw)
    y0 = clamp(cy * ih - ch / 2, 0, ih - ch)
    return img.resize((ow, oh), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch), reducing_gap=2.0)


# ---------------------------------------------------------------- text


def parse_marked(text: str):
    """'Bookkeeping that *does itself.*' → [(word, teal?)]."""
    out, teal = [], False
    for tok in re.split(r"(\*)", text):
        if tok == "*":
            teal = not teal
            continue
        for w in tok.split():
            out.append((w, teal))
    return out


def text_block(lines_spec, max_w: int, align: str = "left") -> Image.Image:
    """lines_spec: [(text, size, weight, colour or None for INK/teal marks, gap_after)] → RGBA, wrapped to max_w."""
    rows = []  # (words, font, colour, gap)
    for text, size, weight, colour, gap in lines_spec:
        f = font(size, weight)
        words = parse_marked(text)
        space = f.getlength(" ")
        line, w = [], 0.0
        wrapped = []
        for word, teal in words:
            ww = f.getlength(word)
            if line and w + space + ww > max_w:
                wrapped.append(line)
                line, w = [], 0.0
            line.append((word, teal))
            w += (space if len(line) > 1 else 0) + ww
        if line:
            wrapped.append(line)
        for i, ln in enumerate(wrapped):
            rows.append((ln, f, colour, gap if i == len(wrapped) - 1 else 0, size))
    heights = [int(r[4] * 1.18) + r[3] for r in rows]
    H = sum(heights) + 10
    img = Image.new("RGBA", (max_w, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 0
    for (ln, f, colour, _gap, _size), hh in zip(rows, heights, strict=False):
        space = f.getlength(" ")
        total = sum(f.getlength(w) for w, _ in ln) + space * (len(ln) - 1)
        x = {"left": 0, "center": (max_w - total) / 2, "right": max_w - total}[align]
        for w, teal in ln:
            c = colour or (TEAL if teal else INK)
            if colour and teal:
                c = TEAL_TINT if colour == WHITE else TEAL
            d.text((x, y), w, font=f, fill=c + (255,))
            x += f.getlength(w) + space
        y += hh
    bbox = img.getbbox()
    return img.crop((0, 0, max_w, (bbox[3] + 4) if bbox else 1))


# ---------------------------------------------------------------- devices


@dataclass
class View:
    """One image inside a device, with its Ken Burns move and when it starts (seconds into the scene)."""

    path: str
    a: tuple  # (cx, cy, zoom) at the start
    b: tuple  # at the end
    t0: float = 0.0
    t1: float | None = None  # move ends here (default: scene end)


def browser_frame(content: Image.Image, scale: float) -> Image.Image:
    """A plain browser window drawn in code: rounded, a top bar with three dots and an empty address pill."""
    base, mask, edge, bar = _browser_chrome(content.size, scale)
    win = base.copy()
    win.paste(content, (0, bar))
    win.putalpha(mask)
    win.alpha_composite(edge)
    return win


@lru_cache(16)
def _browser_chrome(size, scale):
    cw, ch = size
    bar = int(40 * scale)
    r = int(16 * scale)
    w, h = cw, ch + bar
    win = Image.new("RGBA", (w, h), WHITE + (255,))
    d = ImageDraw.Draw(win)
    d.rectangle([0, 0, w, bar], fill=(250, 249, 246, 255))
    d.line([0, bar - 1, w, bar - 1], fill=BORDER + (255,), width=max(1, int(scale)))
    for i in range(3):
        cx = int((22 + i * 20) * scale)
        rr = int(6 * scale)
        d.ellipse([cx - rr, bar // 2 - rr, cx + rr, bar // 2 + rr], fill=(214, 211, 201, 255))
    pw = int(w * 0.36)
    d.rounded_rectangle(
        [(w - pw) // 2, int(bar * 0.24), (w + pw) // 2, int(bar * 0.76)], int(bar * 0.26), fill=(238, 236, 229, 255)
    )
    edge = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # hairline border
    ImageDraw.Draw(edge).rounded_rectangle(
        [0, 0, w - 1, h - 1], r, outline=BORDER + (255,), width=max(1, int(1.5 * scale))
    )
    return win, rounded_mask((w, h), r), edge, bar


def phone_frame(content: Image.Image, scale: float) -> Image.Image:
    """A rounded phone drawn in code: dark bezel, rounded screen, small side button."""
    cw, ch = content.size
    bez = int(12 * scale)
    r_out = int(54 * scale)
    r_in = r_out - bez
    w, h = cw + 2 * bez, ch + 2 * bez
    ph = Image.new("RGBA", (w + int(4 * scale), h), (0, 0, 0, 0))
    body = Image.new("RGBA", (w, h), (24, 28, 32, 255))
    body.putalpha(rounded_mask((w, h), r_out))
    d = ImageDraw.Draw(ph)
    d.rounded_rectangle(
        [w - int(2 * scale), int(h * 0.2), w + int(3 * scale), int(h * 0.3)], int(2 * scale), fill=(40, 44, 50, 255)
    )
    ph.alpha_composite(body)
    scr = content.convert("RGBA")
    scr.putalpha(rounded_mask((cw, ch), r_in))
    ph.alpha_composite(scr, (bez, bez))
    return ph


# ---------------------------------------------------------------- scenes


@dataclass
class Scene:
    start: float
    end: float
    texts: list  # [(t0, headline, sub)]
    kind: str = "browser"  # browser | phone | phones | hero | end
    views: list = field(default_factory=list)
    phones: list = field(default_factory=list)  # paths, for kind == "phones"
    tag: str | None = "Sample data · fictional company"  # the screens show the labelled sample books
    inset: tuple | None = None  # (x0, y0, x1, y1) of the first phone screen, shown enlarged beside the phone


ANDROID = ROOT / "apps/mobile/screenshots"
BRAND = ROOT / "apps/web/public/brand"


def S(name: str) -> str:
    """A committed app screenshot: a 2x re-take in tools/teaser/shots/ if one exists, else docs/submission/shots/."""
    p = HERE / "shots" / name
    return str(p if p.exists() else ROOT / "docs/submission/shots" / name)


def scenes(variant: str = "social") -> list[Scene]:
    """Teaser 1, timed to the voice-over (voice_cues). `social` keeps the "coming soon" beats and the launch line;
    `submission` (for judges) shows only what runs today: no compare-purchases beat, no iPhone line, and the end card
    says "Try the demo"."""
    social = variant == "social"
    # View: (cx, cy, zoom) start → end, cx/cy in 0–1 of the image.
    out = [
        Scene(
            0,
            4,
            [(0, "Bookkeeping that *does itself.*", None), (2, "Snap a receipt. *Done.*", None)],
            kind="hero",
            views=[View(str(BRAND / "hero.jpg"), (0.5, 0.5, 1.0), (0.42, 0.48, 1.22))],
            tag=None,
        ),
        Scene(
            4,
            6,
            [(0, "Snap it on your *phone.*", None)],
            kind="phone",
            views=[View(str(ANDROID / "review.png"), (0, 0, 1), (0, 0, 1))],
            inset=(30, 880, 1050, 1285),
        ),
        Scene(
            6,
            8.5,
            [(0, "Same books on the *web.*", "Phone and web stay in sync")],
            views=[View(S("05-proposal.png"), (0.58, 0.30, 1.4), (0.59, 0.31, 1.55))],
        ),
        Scene(
            8.5,
            10.5,
            [(0, "You approve. *It's posted.*", None)],
            views=[View(S("06-approve.png"), (0.6, 0.24, 1.35), (0.6, 0.24, 1.5))],
        ),
        Scene(
            10.5,
            14.5,
            [(0, "Receipts straight from your *email.*", "Outlook intake, read-only")],
            views=[View(S("02-files.png"), (0.56, 0.42, 1.3), (0.56, 0.38, 1.5))],
        ),
        Scene(
            14.5,
            17,
            [(0, "Ask your books *anything.*", None)],
            views=[View(S("ask-answer.png"), (0.6, 0.38, 1.3), (0.6, 0.52, 1.5))],
        ),
        Scene(
            17,
            19.5,
            [(0, "Reports that *explain themselves.*", None)],
            views=[View(S("reports-trend.png"), (0.59, 0.40, 1.25), (0.59, 0.44, 1.5))],
        ),
        Scene(
            19.5,
            22,
            [(0, "Hands-free. *Just say it.*", "Speak, then approve")],
            kind="phone",
            views=[View(str(ANDROID / "ask.png"), (0, 0, 1), (0, 0, 1))],
            inset=(30, 600, 1070, 1230),
        ),
    ]
    if social:
        out.append(Scene(22, 23.5, [(0, "Compare what you pay. *Save money.*", None)], kind="soon", tag=None))
    out += [
        Scene(
            23.5 if social else 22,
            26,
            [(0, "Plan your day *in one tap.*", None)],
            views=[View(S("01-home.png"), (0.58, 0.24, 1.35), (0.58, 0.22, 1.6))],
            tag="Demo data · fictional account",
        ),
        Scene(
            26,
            29.5,
            [(0, "VAT return, *worked out by code.*", "MTD-ready · HMRC sandbox")],
            views=[View(S("vat.png"), (0.45, 0.5, 1.25), (0.45, 0.68, 1.5))],
        ),
        Scene(
            29.5,
            34,
            [(0, "Your books stay in your *OneDrive.*", None)],
            views=[View(S("02-files.png"), (0.5, 0.5, 1.1), (0.52, 0.56, 1.3))],
        ),
        Scene(
            34,
            END_START,
            [(0, "Android app *now.*", "iPhone app coming soon")]
            if social
            else [(0, "On Android *and the web.*", "One set of books")],
            kind="phones",
            phones=[str(ANDROID / "home.png"), str(ANDROID / "vat.png")],
        ),
        Scene(END_START, DURATION, [], kind="end", tag=None),
    ]
    return out


def voice_cues(variant: str) -> list[tuple[str, float, float]]:
    """(clip in tools/teaser/vo/, start second, seconds trimmed off the clip's head). Kokoro TTS, voice bm_george."""
    cues = [("t1_01.wav", 0.4, 0), ("t1_02.wav", 3.8, 0), ("t1_03.wav", 10.4, 0), ("t1_04.wav", 14.4, 0)]
    if variant == "social":
        cues += [("t1_05.wav", 22.0, 0)]
    else:  # "and plan your day around your jobs" only: the compare beat is not in this cut
        cues += [("t1_05.wav", 22.1, 1.6)]
    cues += [("t1_06.wav", 26.0, 0), ("t1_07.wav", 29.5, 0)]
    if variant == "social":
        cues += [("t1_08.wav", 38.6, 0)]
    return cues


def captions(variant: str) -> list[tuple[float, float, str]]:
    """Burned-in captions: exactly the spoken words (tools/teaser/vo/lines.json), split at the voice's pauses."""
    c = [
        (0.6, 2.6, "Bookkeeping that does itself."),
        (4.0, 5.9, "Snap a receipt on your phone."),
        (6.0, 8.5, "It appears on the web, ready to approve."),
        (10.6, 14.6, "Accnomos pulls receipts and invoices straight from your email."),
        (14.6, 16.8, "Ask for a report in plain English,"),
        (16.8, 18.4, "and get exact figures."),
    ]
    if variant == "social":
        c += [(22.2, 23.6, "Compare what you pay,"), (23.6, 25.8, "and plan your day around your jobs.")]
    else:
        c += [(22.2, 24.3, "And plan your day around your jobs.")]
    c += [
        (26.2, 29.4, "VAT returns, built for Making Tax Digital."),
        (29.7, 31.9, "Your books stay in your own OneDrive."),
        (31.9, 34.0, "A.I. by Meta Muse models."),
    ]
    if variant == "social":
        c += [(38.8, 42.2, "Accnomos. Launching November 2026.")]
    return c


class Renderer:
    def __init__(self, W: int, H: int, variant: str = "social"):
        self.W, self.H = W, H
        self.variant = variant
        self.m = min(W, H)
        self.land = W / H > 1.3
        self.portrait = H / W > 1.3
        self.margin = int(0.065 * W) if not self.land else int(0.055 * W)
        self.bg = self._background()
        self.scenes = scenes(variant)
        self.captions = captions(variant)
        self._text_cache: dict = {}
        self._frame_cache: dict = {}

    # ---- layout
    def _background(self) -> Image.Image:
        W, H = self.W, self.H
        bg = Image.new("RGB", (W, H), GROUND)
        glow = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(glow)
        r = int(self.m * 0.55)
        d.ellipse([W - r * 1.2, -r * 0.6, W + r * 0.8, r * 1.4], fill=60)
        d.ellipse([-r, H - r * 1.1, r, H + r * 0.9], fill=40)
        glow = glow.filter(ImageFilter.GaussianBlur(self.m * 0.12))
        tint = Image.new("RGB", (W, H), TEAL_TINT)
        bg = Image.composite(tint, bg, glow.point(lambda v: min(255, v * 3)))
        return bg.convert("RGBA")

    def text_area(self):
        """(x, y, max_w) for the headline block."""
        if self.land:
            return self.margin, None, int(self.W * 0.30)
        return self.margin, int(self.H * (0.075 if self.portrait else 0.06)), self.W - 2 * self.margin

    def device_area(self, text_h: int):
        """Box (x0, y0, x1, y1) the device must fit in."""
        W, H = self.W, self.H
        if self.land:
            return int(W * 0.375), int(H * 0.07), W - int(W * 0.035), H - int(H * 0.09)
        top = int(H * (0.075 if self.portrait else 0.06)) + text_h + int(self.m * 0.05)
        return self.margin, top, W - self.margin, H - int(H * (0.07 if self.portrait else 0.06))

    def headline_sizes(self):
        if self.land:
            return 84, 40
        if self.portrait:
            return 94, 46
        return 76, 38

    def text_img(self, headline: str, sub: str | None, align="left"):
        key = (headline, sub, align)
        if key not in self._text_cache:
            hs, ss = self.headline_sizes()
            spec = [(headline, hs, 800, None, int(hs * 0.32))]
            if sub:
                spec.append((sub, ss, 600, MUTED, 0))
            self._text_cache[key] = text_block(spec, self.text_area()[2], align)
        return self._text_cache[key]

    def max_text_h(self, sc: Scene):
        return max((self.text_img(h, s).size[1] for _, h, s in sc.texts), default=0)

    # ---- frame
    def frame(self, t: float) -> Image.Image:
        img = self._frame(t)
        for c0, c1, text in self.captions:
            if c0 - 0.1 <= t < c1 + 0.1:
                k = clamp(min((t - c0 + 0.1) / 0.15, (c1 + 0.1 - t) / 0.15))
                img = img.convert("RGBA")
                cap = self.caption_img(text)
                # landscape: centred under the device column, clear of the headline and the sample tag
                cx = self.W * 0.67 if self.land and self.scene_at(t).kind != "end" else self.W / 2
                x = int(clamp(cx - cap.size[0] / 2, self.W * 0.02, self.W * 0.98 - cap.size[0]))
                paste_alpha(img, cap, (x, self.H - int(self.H * 0.045) - cap.size[1]), k)
                img = img.convert("RGB")
        return img

    def caption_img(self, text: str) -> Image.Image:
        key = ("cap", text)
        if key not in self._text_cache:
            size = 46 if self.portrait else 40
            maxw = int(self.W * (0.58 if self.land else 0.80))
            full = font(size, 600).getlength(text)
            if full > maxw:  # two balanced lines rather than one long line and an orphan
                maxw = min(maxw, int(full / 2 + size * 2))
            t = text_block([(text.replace("*", ""), size, 600, WHITE, 0)], maxw, "center")
            bbox = t.getbbox()
            t = t.crop((bbox[0], 0, bbox[2], t.size[1]))
            px, py = int(size * 0.7), int(size * 0.35)
            box = Image.new("RGBA", (t.size[0] + 2 * px, t.size[1] + 2 * py), (0, 0, 0, 0))
            ImageDraw.Draw(box).rounded_rectangle(
                [0, 0, box.size[0] - 1, box.size[1] - 1], int(size * 0.5), fill=INK + (222,)
            )
            box.alpha_composite(t, (px, py))
            self._text_cache[key] = box
        return self._text_cache[key]

    def scene_at(self, t: float) -> Scene:
        return next((s for s in self.scenes if s.start <= t < s.end), self.scenes[-1])

    def _frame(self, t: float) -> Image.Image:
        sc = next(s for s in self.scenes if s.start <= t < s.end) if t < self.scenes[-1].end else self.scenes[-1]
        img = self.render_scene(sc, t - sc.start)
        # 4-frame crossfade from the previous scene, on the beat
        xf = 4 / FPS
        idx = self.scenes.index(sc)
        if idx > 0 and t - sc.start < xf:
            prev = self.scenes[idx - 1]
            pimg = self.render_scene(prev, prev.end - prev.start - 1e-3)
            img = Image.blend(pimg, img, (t - sc.start) / xf)
        return img

    def render_scene(self, sc: Scene, lt: float) -> Image.Image:
        dur = sc.end - sc.start
        if sc.kind == "end":
            return self.render_end(lt, dur)
        canvas = self.bg.copy()
        th = self.max_text_h(sc)
        box = self.device_area(th)
        enter = ease_out(lt / 0.45)

        if sc.kind in ("browser", "hero"):
            self.draw_browserish(canvas, sc, lt, dur, box, enter)
        elif sc.kind == "phone":
            self.draw_phones(canvas, [sc.views[0].path], lt, dur, box, enter, sc.inset)
        elif sc.kind == "phones":
            self.draw_phones(canvas, sc.phones, lt, dur, box, enter)
        elif sc.kind == "soon":
            return self.render_soon(sc, lt, enter)

        # text: the current one slides in on its beat
        cur = [x for x in sc.texts if x[0] <= lt]
        if cur:
            t0, h, s = cur[-1]
            timg = self.text_img(h, s)
            k = ease_out((lt - t0) / 0.4)
            x, y, _ = self.text_area()
            if y is None:
                y = (self.H - timg.size[1]) // 2
            paste_alpha(canvas, timg, (x, y + (1 - k) * self.m * 0.04), k)
        if sc.tag:
            self.draw_tag(canvas, sc.tag, enter)
        return canvas.convert("RGB")

    def draw_tag(self, canvas, text, alpha):
        f = font(max(18, int(self.m * 0.02)), 600)
        tw = int(f.getlength(text))
        pad = int(self.m * 0.012)
        h = int(f.size * 1.6)
        pill = Image.new("RGBA", (tw + 2 * pad, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(pill)
        d.rounded_rectangle([0, 0, tw + 2 * pad - 1, h - 1], h // 2, fill=INK + (200,))
        d.text((pill.size[0] / 2, h / 2), text, font=f, fill=WHITE + (255,), anchor="mm")
        if self.land:  # bottom left, under the headline column
            x, y = self.margin, self.H - int(self.H * 0.045) - h
        else:  # top right, above the headline
            x, y = self.W - self.margin - pill.size[0], int(self.H * 0.012)
        paste_alpha(canvas, pill, (x, y), alpha * 0.95)

    def draw_browserish(self, canvas, sc: Scene, lt, dur, box, enter):
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        scale = self.m / 1080
        bar = int(40 * scale)
        if sc.kind == "hero":
            aspect = 1600 / 914 if self.land else (1.25 if not self.portrait else 0.9)
        else:
            aspect = 1.6 if self.land else (1.3 if not self.portrait else 0.78)
        cw = bw
        ch = int(cw / aspect)
        if ch + bar > bh:
            ch = bh - bar
            cw = int(ch * aspect)
        content = self.views_at(sc, lt, dur, (cw, ch))
        if sc.kind == "hero":
            win = content.convert("RGBA")
            win.putalpha(rounded_mask((cw, ch), int(28 * scale)))
            ww, wh = cw, ch
        else:
            win = browser_frame(content, scale)
            ww, wh = win.size
        x = x0 + (bw - ww) // 2
        y = y0 + (bh - wh) // 2 + (1 - enter) * self.m * 0.06
        sh = shadow((ww, wh), int(18 * scale), int(26 * scale), 0.22)
        pad = (sh.size[0] - ww) // 2
        paste_alpha(canvas, sh, (x - pad, y - pad + 14 * scale), enter)
        paste_alpha(canvas, win, (x, y), enter)

    def views_at(self, sc: Scene, lt, dur, size):
        def one(v: View):
            t1 = v.t1 if v.t1 is not None else dur
            k = ease_in_out((lt - v.t0) / max(0.01, t1 - v.t0))
            cx, cy, z = (lerp(a, b, k) for a, b in zip(v.a, v.b, strict=False))
            return crop_view(load(v.path), cx, cy, z, size)

        live = [v for v in sc.views if v.t0 <= lt] or sc.views[:1]
        img = one(live[-1])
        if len(live) > 1:
            k = (lt - live[-1].t0) / 0.2
            if k < 1:
                img = Image.blend(one(live[-2]), img, ease_out(k))
        return img

    def draw_phones(self, canvas, paths, lt, dur, box, enter, inset=None):
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        scale = self.m / 1080
        n = len(paths)
        gap = int(self.m * 0.04)
        bez = int(12 * scale)
        sh_h = bh
        sw = int((sh_h - 2 * bez) * 1080 / 2400)
        total = n * (sw + 2 * bez) + (n - 1) * gap
        if total > bw:
            sw = int((bw - (n - 1) * gap) / n) - 2 * bez
        sc_h = int(sw * 2400 / 1080)
        total = n * (sw + 2 * bez) + (n - 1) * gap
        drift = ease_in_out(lt / dur)
        for i, p in enumerate(paths):
            content = (
                load(p).resize((sw, sc_h), Image.LANCZOS)
                if (p, sw) not in self._frame_cache
                else self._frame_cache[(p, sw)]
            )
            if (p, sw) not in self._frame_cache:
                self._frame_cache[(p, sw)] = phone_frame(content, scale)
            ph = self._frame_cache[(p, sw)]
            e = ease_out((lt - i * 0.12) / 0.5)
            x = x0 + (bw - total) // 2 + i * (sw + 2 * bez + gap)
            y = (
                y0
                + (bh - ph.size[1]) // 2
                + (1 - e) * self.m * 0.12
                - drift * self.m * 0.012 * (1 if i % 2 == 0 else -1)
            )
            sh = shadow(ph.size, int(54 * scale), int(28 * scale), 0.28)
            pad = (sh.size[0] - ph.size[0]) // 2
            paste_alpha(canvas, sh, (x - pad, y - pad + 18 * scale), e)
            paste_alpha(canvas, ph, (x, y), e)
            if inset and i == 0:
                self.draw_inset(canvas, p, inset, lt, (x, y, x + ph.size[0], y + ph.size[1]))

    def draw_inset(self, canvas, path, region, lt, phone_box):
        """The phone's key card, enlarged on a rounded card that overlaps the phone, so it reads on a small screen."""
        k = ease_out((lt - 0.7) / 0.45)
        if k <= 0:
            return
        scale = self.m / 1080
        rw, rh = region[2] - region[0], region[3] - region[1]
        w = int(self.W * 0.30) if self.land else int(self.W * 0.56)
        h = int(w * rh / rw)
        key = ("inset", path, region, w)
        card = self._frame_cache.get(key)
        if card is None:
            img = load(path).crop(region).resize((w, h), Image.LANCZOS).convert("RGBA")
            img.putalpha(rounded_mask((w, h), int(22 * scale)))
            edge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(edge).rounded_rectangle(
                [0, 0, w - 1, h - 1], int(22 * scale), outline=TEAL + (255,), width=max(2, int(3 * scale))
            )
            img.alpha_composite(edge)
            card = self._frame_cache[key] = img
        px0, py0, px1, py1 = phone_box
        if self.land:
            x = px1 - int(w * 0.18)
            x = min(x, self.W - int(self.W * 0.03) - w)
        else:
            x = px1 - int(w * 0.62)
            x = min(x, self.W - self.margin // 2 - w)
        y = py0 + (py1 - py0) * 0.42 - h / 2 + (1 - k) * self.m * 0.03
        c = card
        sh = shadow(c.size, int(22 * scale), int(24 * scale), 0.30)
        pad = (sh.size[0] - c.size[0]) // 2
        paste_alpha(canvas, sh, (x - pad, y - pad + 14 * scale), k)
        paste_alpha(canvas, c, (x, y), k)

    def render_soon(self, sc: Scene, lt, enter) -> Image.Image:
        """A text-only beat for a feature that is not on main yet: headline and a "Coming soon" pill, no screen."""
        canvas = self.bg.copy()
        hs, _ = self.headline_sizes()
        timg = text_block(
            [(sc.texts[0][1], int(hs * 1.1), 800, None, 0)], int(self.W * (0.62 if self.land else 0.84)), "center"
        )
        f = font(int(self.m * 0.034), 800)
        label = "COMING SOON"
        tw = int(f.getlength(label))
        h = int(f.size * 2.0)
        pill = Image.new("RGBA", (tw + int(f.size * 2.0), h), (0, 0, 0, 0))
        d = ImageDraw.Draw(pill)
        d.rounded_rectangle(
            [0, 0, pill.size[0] - 1, h - 1], h // 2, fill=(255, 247, 237, 255), outline=(243, 200, 146, 255), width=3
        )
        d.text((pill.size[0] / 2, h / 2), label, font=f, fill=(138, 63, 6, 255), anchor="mm")
        gap = int(self.m * 0.04)
        total = pill.size[1] + gap + timg.size[1]
        y = (self.H - total) // 2
        k1 = ease_out(lt / 0.35)
        paste_alpha(canvas, pill, ((self.W - pill.size[0]) // 2, y + (1 - k1) * self.m * 0.03), k1)
        k2 = ease_out((lt - 0.1) / 0.4)
        paste_alpha(canvas, timg, ((self.W - timg.size[0]) // 2, y + pill.size[1] + gap + (1 - k2) * self.m * 0.03), k2)
        return canvas.convert("RGB")

    def render_end(self, lt, dur) -> Image.Image:
        W, H, m = self.W, self.H, self.m
        canvas = Image.new("RGBA", (W, H), TEAL + (255,))
        # soft light from the top
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse([W * 0.15, -H * 0.5, W * 0.85, H * 0.55], fill=70)
        glow = glow.filter(ImageFilter.GaussianBlur(m * 0.15))
        canvas = Image.composite(Image.new("RGBA", (W, H), (22, 128, 115, 255)), canvas, glow)
        icon_s = int(m * (0.2 if self.land else 0.24))
        icon = self._frame_cache.get(("icon", icon_s))
        if icon is None:
            icon = Image.open(BRAND / "icon-512.png").convert("RGBA").resize((icon_s, icon_s), Image.LANCZOS)
            icon.putalpha(ImageChops.multiply(icon.getchannel("A"), rounded_mask((icon_s, icon_s), int(icon_s * 0.22))))
            self._frame_cache[("icon", icon_s)] = icon
        k_icon = ease_out(lt / 0.5)
        word = text_block(
            [("Accnomos", int(m * (0.11 if self.land else 0.13)), 800, WHITE, 0)], W - 2 * self.margin, "center"
        )
        url = text_block([("accnomos.com", int(m * 0.05), 700, TEAL_TINT, 0)], W - 2 * self.margin, "center")
        small = text_block(
            [("Built for the Meta Global AI Developer Hackathon", int(m * 0.026), 600, (190, 222, 216), 0)],
            W - 2 * self.margin,
            "center",
        )
        # pill button
        f = font(int(m * 0.042), 800)
        label = "Launching November 2026" if self.variant == "social" else "Try the demo"
        tw = int(f.getlength(label))
        ph_ = int(f.size * 2.1)
        pill = Image.new("RGBA", (tw + int(f.size * 2.4), ph_), (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle([0, 0, pill.size[0] - 1, ph_ - 1], ph_ // 2, fill=WHITE + (255,))
        ImageDraw.Draw(pill).text((pill.size[0] / 2, ph_ / 2), label, font=f, fill=TEAL_DARK + (255,), anchor="mm")

        gap = int(m * 0.035)
        parts = [icon, word, url, pill]
        total = sum(p.size[1] for p in parts) + gap * 3 + int(m * 0.01)
        y = (H - total) // 2 - int(m * 0.03)
        delays = [0, 0.15, 0.3, 0.5]
        for p, dl in zip(parts, delays, strict=False):
            k = ease_out((lt - dl) / 0.45) if p is not icon else k_icon
            x = (W - p.size[0]) // 2
            if p is icon:
                s = 0.85 + 0.15 * k
                pp = p.resize((max(1, int(p.size[0] * s)),) * 2, Image.LANCZOS)
                paste_alpha(canvas, pp, ((W - pp.size[0]) // 2, y + (p.size[1] - pp.size[1]) // 2), k)
            else:
                paste_alpha(canvas, p, (x, y + (1 - k) * m * 0.03), k)
            y += p.size[1] + gap
        k = ease_out((lt - 0.8) / 0.5)
        paste_alpha(canvas, small, ((W - small.size[0]) // 2, int(H * 0.06)), k)
        # gentle fade to teal-dark at the very end
        out = canvas.convert("RGB")
        if lt > dur - 0.6:
            out = Image.blend(out, Image.new("RGB", (W, H), TEAL_DARK), clamp((lt - (dur - 0.6)) / 0.6) * 0.5)
        return out


# ---------------------------------------------------------------- audio, encode


def _ff(*args) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def _loudnorm_json(path: Path, target: float) -> dict:
    p = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(p.stderr[p.stderr.rindex("{") :])


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
        return x.reshape(-1, w.getnchannels())


def _write(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(music.SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def _gain_to(x: np.ndarray, tmp: Path, target: float) -> np.ndarray:
    _write(tmp, x)
    return x * 10 ** ((target - float(_loudnorm_json(tmp, target)["input_i"])) / 20)


def build_audio(variant: str) -> Path:
    """Music bed + voice-over: voice at about −16 LUFS, music ducked 11 dB under it, the mix at −14 LUFS (−1.5 dBTP)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    raw = CACHE / "music_raw.wav"
    music.render(DURATION, str(raw), drums_until=END_START)
    bed = _gain_to(_read(raw), CACHE / "tmp.wav", -14)
    n = len(bed)
    vo = np.zeros((n, 2))
    for clip, at, trim in voice_cues(variant):
        src = HERE / "vo" / clip
        res = CACHE / f"vo48_{clip}"
        _ff("-i", src, "-ar", music.SR, "-ac", 2, res)
        x = _read(res)[int(trim * music.SR) :]
        i = int(at * music.SR)
        j = min(n, i + len(x))
        vo[i:j] += x[: j - i]
    vo = _gain_to(vo, CACHE / "tmp.wav", -16)
    # duck: 11 dB wherever the voice is speaking
    env = np.abs(vo).max(axis=1)
    win = int(0.05 * music.SR)
    active = np.convolve(env > 0.01, np.ones(win), "same") > 0
    target = np.where(active, 10 ** (-11 / 20), 1.0)
    # smooth the gain with a 200 ms raised-cosine window (FFT convolution): ~100 ms fades either side of each phrase
    k = np.hanning(int(0.2 * music.SR))
    k /= k.sum()
    m = 1 << int(np.ceil(np.log2(n + len(k))))
    g = np.fft.irfft(np.fft.rfft(target - 1, m) * np.fft.rfft(k, m), m)[len(k) // 2 : len(k) // 2 + n] + 1
    mix = bed * g[:, None] + vo
    mixed = CACHE / f"mix_{variant}.wav"
    _write(mixed, mix / max(1.0, np.abs(mix).max() / 0.98))
    m = _loudnorm_json(mixed, -14)
    final = CACHE / f"audio_{variant}.wav"
    af = (
        f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
    )
    _ff("-i", mixed, "-af", af, "-ar", music.SR, final)
    return final


_WORKER: dict = {}


def _init_worker(W, H, variant, want, prefix):
    _WORKER.update(r=Renderer(W, H, variant), want=want, prefix=prefix)


def _render_frame(i: int) -> bytes:
    img = _WORKER["r"].frame(i / FPS)
    if i in _WORKER["want"]:
        img.save(CACHE / "stills" / f"{_WORKER['prefix']}_{i / FPS:05.2f}.png")
    return img.tobytes()


def encode(fmt: str, variant: str, audio: Path, frames_at: list[float], workers: int) -> Path:
    W, H = FORMATS[fmt]
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"accnomos-teaser1-{fmt}_{variant}.mp4"
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-i",
        str(audio),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-threads",
        "2",
        "-x264-params",
        "rc-lookahead=15",  # modest memory: shared build boxes OOM-kill easily
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(DURATION * FPS)
    want = {int(round(s * FPS)) for s in frames_at}
    stills = CACHE / "stills"
    stills.mkdir(parents=True, exist_ok=True)
    # frames render in worker processes (in order) and stream to ffmpeg
    with multiprocessing.Pool(workers, _init_worker, (W, H, variant, want, f"{fmt}{variant}")) as pool:
        for i, frame in enumerate(pool.imap(_render_frame, range(n), chunksize=3)):
            proc.stdin.write(frame)
            if i % 150 == 0:
                print(f"  {fmt} {variant}: {i / FPS:4.1f}s", flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit(f"ffmpeg failed for {fmt}")
    return out


def thumbnail() -> Path:
    """1280×720 YouTube thumbnail: big headline, the Muse Image hero art, the app icon and name."""
    r = Renderer(1920, 1080, "social")
    img = r.bg.copy()
    hero = load(str(BRAND / "hero.jpg"))
    w = 960
    h = int(w * hero.height / hero.width)
    card = hero.resize((w, h), Image.LANCZOS).convert("RGBA")
    card.putalpha(rounded_mask((w, h), 30))
    x, y = 1920 - w - 60, (1080 - h) // 2 + 40
    sh = shadow((w, h), 30, 30, 0.25)
    pad = (sh.size[0] - w) // 2
    img.alpha_composite(sh, (x - pad, y - pad + 16))
    img.alpha_composite(card, (x, y))
    t = text_block([("Bookkeeping that *does itself.*", 110, 800, None, 0)], 760)
    img.alpha_composite(t, (r.margin, (1080 - t.size[1]) // 2 + 60))
    icon = Image.open(BRAND / "icon-512.png").convert("RGBA").resize((130, 130), Image.LANCZOS)
    icon.putalpha(ImageChops.multiply(icon.getchannel("A"), rounded_mask((130, 130), 28)))
    img.alpha_composite(icon, (r.margin, 80))
    ImageDraw.Draw(img).text(
        (r.margin + 158, 145), "Accnomos", font=font(76, 800), fill=TEAL_DARK + (255,), anchor="lm"
    )
    out = OUT / "accnomos-teaser1-thumbnail.png"
    OUT.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").resize((1280, 720), Image.LANCZOS).save(out, optimize=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", default="16x9,1x1", help=f"comma-separated, from {', '.join(FORMATS)}")
    ap.add_argument("--variants", default="social,submission")
    ap.add_argument("--workers", type=int, default=min(3, os.cpu_count() or 1), help="frame-rendering processes")
    ap.add_argument("--frames", default="", help="comma-separated seconds to also save as PNG stills")
    ap.add_argument("--stills-only", action="store_true", help="save the --frames stills and skip the video")
    a = ap.parse_args()
    fmts, variants = a.formats.split(","), a.variants.split(",")
    if a.stills_only:
        (CACHE / "stills").mkdir(parents=True, exist_ok=True)
        for fmt in fmts:
            for v in variants:
                r = Renderer(*FORMATS[fmt], v)
                for x in a.frames.split(","):
                    r.frame(float(x)).save(CACHE / "stills" / f"{fmt}{v}_{float(x):05.2f}.png")
        return
    print(thumbnail())
    frames_at = [float(x) for x in a.frames.split(",") if x]
    audio = {v: build_audio(v) for v in variants}
    for fmt in fmts:
        for v in variants:
            out = encode(fmt, v, audio[v], frames_at, a.workers)
            print(f"{out}  {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
