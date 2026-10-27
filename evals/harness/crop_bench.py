"""Crop bench: place gold receipts on cluttered scenes at a known spot, score the crop box.

    cd evals && python -m harness.crop_bench --limit 20
    (method A also runs when MODEL_API_KEY or META_API_KEY is set; it costs ~$2.50 per 1k images)

Scenes cycle through: wood table, hard shadow + hand, second paper, pale desk, dark desk with
mug and pen. Truth = axis-aligned box of the rotated receipt. Scores per method:
IoU(crop box, truth), 'kept' = share of the receipt inside the crop, and 'cropped' = a box was
returned at all (method B returns the original when unsure; that scores IoU of the full frame).
Writes evals/REPORT_crop_<methods>_<n>_<date>.md unless --no-report.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app.ai import crop  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402

from harness.render import _paper  # noqa: E402

GOLD_DIR = REPO / "evals" / "gold" / "receipts"
SCENES = ("wood_table", "shadow_hand", "second_paper", "pale_desk", "dark_desk_mug")
Box = tuple[int, int, int, int]


def _table(w: int, h: int, base: tuple[int, int, int], rng: random.Random, grain: bool) -> Image.Image:
    img = Image.new("RGB", (w, h), base)
    if grain:
        d = ImageDraw.Draw(img)
        for y in range(0, h, 3):
            k = rng.randint(-14, 14)
            d.line((0, y, w, y + rng.randint(-4, 4)), fill=tuple(max(0, min(255, c + k)) for c in base), width=2)
    return img


def _rotated(paper: Image.Image, angle: float) -> Image.Image:
    return paper.convert("RGBA").rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))


def _shadow_mul(img: Image.Image, rng: random.Random, lo: float) -> Image.Image:
    w, h = img.size
    ramp = Image.linear_gradient("L").rotate(rng.choice((0, 90, 180, 270))).resize((w, h))
    ramp = ramp.point(lambda v: int(255 * (lo + (1 - lo) * v / 255)))
    from PIL import ImageChops

    return ImageChops.multiply(img, Image.merge("RGB", (ramp, ramp, ramp)))


def make_scene(text: str, scene: str, seed: int) -> tuple[bytes, Box]:
    """Return (PNG bytes, truth box) for one gold receipt on one cluttered scene."""
    rng = random.Random(seed)
    paper = _paper(text, rng)
    rec = _rotated(paper, rng.uniform(-8, 8))
    # the receipt covers roughly 30-60 % of the frame, like a hand-held phone photo
    fw = int(rec.width * rng.uniform(1.5, 1.9))
    fh = int(rec.height * rng.uniform(1.15, 1.4))
    base = {
        "wood_table": (120, 86, 56),
        "shadow_hand": (96, 92, 88),
        "second_paper": (70, 74, 80),
        "pale_desk": (176, 170, 160),
        "dark_desk_mug": (40, 38, 36),
    }[scene]
    img = _table(fw, fh, base, rng, grain=scene in ("wood_table", "pale_desk"))
    d = ImageDraw.Draw(img)
    x = rng.randint(10, fw - rec.width - 10)
    y = rng.randint(10, max(11, fh - rec.height - 10))

    if scene == "second_paper":  # a smaller sheet, partly off-frame, not touching the receipt
        other = _rotated(Image.new("RGB", (int(rec.width * 0.7), int(rec.height * 0.5)), (240, 240, 236)), rng.uniform(-20, 20))
        ox = x + rec.width + 20 if x + rec.width + 20 < fw - 40 else max(0, x - other.width - 20)
        img.paste(other, (ox, rng.randint(-other.height // 4, fh // 3)), other)
    if scene == "dark_desk_mug":
        cx, cy, r = (x + rec.width + 60, y + 80, 70) if x + rec.width + 140 < fw else (max(70, x - 80), y + 80, 70)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(210, 205, 196))  # mug rim (bright!)
        d.ellipse((cx - r + 12, cy - r + 12, cx + r - 12, cy + r - 12), fill=(60, 36, 20))  # coffee
        d.line((10, fh - 30, fw // 2, fh - 60), fill=(20, 40, 160), width=9)  # pen

    img.paste(rec, (x, y), rec)
    truth: Box = (x, y, x + rec.width, y + rec.height)
    bb = rec.getchannel("A").getbbox()
    if bb:
        truth = (x + bb[0], y + bb[1], x + bb[2], y + bb[3])

    if scene == "shadow_hand":  # skin-tone hand over the lower edge, then a hard side shadow
        hx = rng.randint(truth[0], truth[2] - 60)
        d = ImageDraw.Draw(img)
        d.ellipse((hx - 70, truth[3] - 50, hx + 90, truth[3] + 160), fill=(214, 168, 138))
        img = _shadow_mul(img, rng, lo=0.55)
    else:
        img = _shadow_mul(img, rng, lo=rng.uniform(0.8, 0.92))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), truth


def kept(box: Box, truth: Box) -> float:
    ix = max(0, min(box[2], truth[2]) - max(box[0], truth[0]))
    iy = max(0, min(box[3], truth[3]) - max(box[1], truth[1]))
    return ix * iy / float((truth[2] - truth[0]) * (truth[3] - truth[1]))


async def run(limit: int, out_dir: Path | None) -> dict[str, Any]:
    golds = sorted(GOLD_DIR.glob("*.json"))[:limit]
    key = os.getenv("MODEL_API_KEY") or os.getenv("META_API_KEY")
    cfg = AiConfig.resolve(mode="key", api_key=key) if key else None
    rows: list[dict[str, Any]] = []
    for i, path in enumerate(golds):
        gold = json.loads(path.read_text())
        scene = SCENES[i % len(SCENES)]
        data, truth = make_scene(gold["printed_text"], scene, seed=1000 + i)
        size = Image.open(io.BytesIO(data)).size
        full: Box = (0, 0, *size)
        row: dict[str, Any] = {"case": path.stem, "scene": scene, "size": size, "truth": truth}
        if out_dir:
            (out_dir / f"{path.stem}_{scene}.png").write_bytes(data)

        os.environ["CROP_MODE"] = "code"
        t0 = time.perf_counter()
        r = await crop.crop_document(data)
        box = r.box or full
        row["code"] = {"box": r.box, "iou": crop.iou(box, truth), "kept": kept(box, truth),
                       "s": time.perf_counter() - t0, "note": r.note}
        if cfg:
            t0 = time.perf_counter()
            try:
                img = Image.open(io.BytesIO(data))
                import base64

                sbox, info = await crop.sam_box(img, "data:image/png;base64," + base64.b64encode(data).decode(), cfg)
                sbox = crop.pad_box(sbox, size) if sbox else None
                note = info.get("reason", "")
            except Exception as exc:  # noqa: BLE001
                sbox, note = None, f"error: {exc!r}"[:120]
            b = sbox or full
            row["sam"] = {"box": sbox, "iou": crop.iou(b, truth), "kept": kept(b, truth),
                          "s": time.perf_counter() - t0, "note": note}
        rows.append(row)
    os.environ.pop("CROP_MODE", None)
    return {"rows": rows, "methods": ["code"] + (["sam"] if cfg else [])}


def summarise(res: dict[str, Any]) -> str:
    rows = res["rows"]
    lines = [f"# Crop bench — {len(rows)} gold receipts on cluttered scenes ({date.today().isoformat()})", ""]
    lines += [
        "Generated by `python -m harness.crop_bench`. Truth = axis-aligned box of the rotated receipt as placed.",
        "IoU is of the box the extractor would receive (3 % padding included; full frame when no crop).",
        "The padding alone caps IoU at ~0.89 (1 / 1.06²), so 0.89 means the paper was found exactly.",
        "Scenes are synthetic (flat colours, drawn mug/pen/hand), so real phone photos will score lower.",
        "Kept = share of the receipt inside that box. Cropped = a box was returned rather than the original.",
        "",
        "| Method | Cropped | Mean IoU | Median IoU | IoU ≥ 0.8 | Kept ≥ 99 % | Full-frame IoU (baseline) | Mean time |",
        "|---|---|---|---|---|---|---|---|",
    ]
    base = [crop.iou((0, 0, *r["size"]), r["truth"]) for r in rows]
    for m in res["methods"]:
        ious = [r[m]["iou"] for r in rows]
        lines.append(
            f"| {m} | {sum(r[m]['box'] is not None for r in rows)}/{len(rows)} | {statistics.mean(ious):.3f} | "
            f"{statistics.median(ious):.3f} | {sum(v >= 0.8 for v in ious)}/{len(rows)} | "
            f"{sum(r[m]['kept'] >= 0.99 for r in rows)}/{len(rows)} | {statistics.mean(base):.3f} | "
            f"{statistics.mean(r[m]['s'] for r in rows):.2f} s |"
        )
    if "sam" not in res["methods"]:
        lines += ["", "Method A (SAM 3.1) not run: no MODEL_API_KEY in this environment."]
    lines += ["", "## By scene", "", "| Scene | n | " + " | ".join(f"{m} mean IoU" for m in res["methods"]) + " |",
              "|---|---|" + "---|" * len(res["methods"])]
    for s in SCENES:
        sr = [r for r in rows if r["scene"] == s]
        if sr:
            lines.append(f"| {s} | {len(sr)} | " + " | ".join(
                f"{statistics.mean(r[m]['iou'] for r in sr):.3f}" for m in res["methods"]) + " |")
    lines += ["", "## Cases", "", "| Case | Scene | Truth | " + " | ".join(f"{m} box / IoU / kept / note" for m in res["methods"]) + " |",
              "|---|---|---|" + "---|" * len(res["methods"])]
    for r in rows:
        cells = [f"{list(r[m]['box']) if r[m]['box'] else '—'} / {r[m]['iou']:.2f} / {r[m]['kept']:.0%} / {r[m]['note']}"
                 for m in res["methods"]]
        lines.append(f"| {r['case']} | {r['scene']} | {list(r['truth'])} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--images", type=Path, help="also write the scene PNGs here")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()
    if args.images:
        args.images.mkdir(parents=True, exist_ok=True)
    res = asyncio.run(run(args.limit, args.images))
    md = summarise(res)
    print(md)
    if not args.no_report:
        name = f"REPORT_crop_{'_'.join(res['methods'])}_{len(res['rows'])}_{date.today().isoformat()}.md"
        (REPO / "evals" / name).write_text(md)
        print(f"wrote evals/{name}")


if __name__ == "__main__":
    main()
