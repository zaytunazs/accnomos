"""Live SAM 3.1 crop check: SAM box vs code box on cluttered phone-photo scenes, then reading accuracy per crop.

    cd evals && python -m harness.sam_crop_live --limit 20 --read --out runs/sam_crop_live

Needs META_API_KEY (or MODEL_API_KEY) in the environment; the key is never printed or written. Scenes come from
`crop_bench.make_scene` (gold receipts on wood, shadow + hand, second paper, pale desk, dark desk + mug) with a known
truth box. Per image: one crop with SAM_CROP=1 (the runtime's own `crop_document`, so the fallback to code is
included), one with CROP_MODE=code, and with --read the reader (`process_image(..., crop=False)`) on each crop and
on the full frame. Writes summary.json and report.md; per-image rows keep boxes, latencies and a mask-free sample of
the SAM output text only (no response ids, no headers).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any

from PIL import Image

from harness.crop_bench import GOLD_DIR, SCENES, kept, make_scene
from harness.run_extraction import FIELDS, score

from app.ai import crop  # noqa: E402  (crop_bench puts the runtime on sys.path)
from app.ai.config import AiConfig  # noqa: E402
from app.pipeline import process_image  # noqa: E402

_MASK = re.compile(r"<\|mask;[^|]*\|>")
BUSINESS = "Bramblewood Joinery Ltd"


def _pick(limit: int) -> list[Path]:
    golds = sorted(GOLD_DIR.glob("*.json"))
    step = max(1, len(golds) // max(1, limit))
    return golds[::step][:limit]


async def _crop(data: bytes, cfg: AiConfig, mode: str, raw: list[dict[str, Any]]) -> dict[str, Any]:
    os.environ["CROP_MODE"] = mode
    os.environ["SAM_CROP"] = "1" if mode == "auto" else "0"
    t0 = time.perf_counter()
    r = await crop.crop_document(data, cfg)
    return {"res": r, "s": round(time.perf_counter() - t0, 3), "raw": list(raw)}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    key = (os.getenv("META_API_KEY") or os.getenv("MODEL_API_KEY") or "").strip()
    if not key:
        raise SystemExit("META_API_KEY is not set")
    cfg = AiConfig.resolve(mode="key", api_key=key, model=args.model)
    raw: list[dict[str, Any]] = []
    real_call = crop._call_sam

    async def recording(noun: str, data_url: str, c: AiConfig) -> dict[str, Any]:
        t0 = time.perf_counter()
        entry: dict[str, Any] = {"noun": noun}
        try:
            data = await real_call(noun, data_url, c)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for crop_document's fallback
            entry |= {"error": f"{type(exc).__name__}: {str(exc)[:200]}", "s": round(time.perf_counter() - t0, 3)}
            if hasattr(exc, "response"):
                resp = exc.response  # type: ignore[attr-defined]
                entry["status"] = resp.status_code
                entry["body"] = _MASK.sub("<|mask;…|>", resp.text)[:400]
            raw.append(entry)
            raise
        text = crop._response_text(data)
        entry |= {
            "s": round(time.perf_counter() - t0, 3),
            "status": 200,
            "text_chars": len(text),
            "boxes": len(crop.parse_sam_boxes(data)),
            "sample": _MASK.sub("<|mask;…|>", text)[:300],
            "usage": data.get("usage"),
        }
        raw.append(entry)
        return data

    crop._call_sam = recording  # type: ignore[assignment]
    rows: list[dict[str, Any]] = []
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for i, path in enumerate(_pick(args.limit)):
        gold = json.loads(path.read_text(encoding="utf-8"))
        scene = SCENES[i % len(SCENES)]
        data, truth = make_scene(gold["printed_text"], scene, seed=1000 + i)
        size = Image.open(io.BytesIO(data)).size
        full = (0, 0, *size)
        row: dict[str, Any] = {"case": path.stem, "gold_case": gold.get("gold_case"), "scene": scene, "size": size}
        images: dict[str, bytes] = {"full": data}
        for name, mode in (("sam", "auto"), ("code", "code")):
            raw.clear()
            c = await _crop(data, cfg, mode, raw)
            r = c["res"]
            box = r.box or full
            row[name] = {
                "method": r.method,
                "box": r.box,
                "iou": round(crop.iou(box, truth), 4),
                "kept": round(kept(box, truth), 4),
                "s": c["s"],
                "note": r.note,
                "details": json.loads(json.dumps(r.details, default=str)),
                "calls": c["raw"],
            }
            images[name] = r.image_bytes
        if args.read:
            row["read"] = {}
            done: dict[bytes, dict[str, Any]] = {}
            for name in ("sam", "code", "full"):
                img = images[name]
                if img in done:  # SAM fell back to the code crop: same pixels, same read
                    row["read"][name] = done[img] | {"reused": True}
                    continue
                t0 = time.perf_counter()
                try:
                    p = (await process_image(img, "image/png", cfg, business_name=BUSINESS, crop=False)).model_dump(
                        mode="json"
                    )
                    rd = {"scores": score(gold, p), "error": None}
                except Exception as exc:  # noqa: BLE001
                    rd = {"scores": {f: False for f in FIELDS}, "error": f"{type(exc).__name__}: {exc}"[:200]}
                rd["s"] = round(time.perf_counter() - t0, 3)
                rd["all"] = all(rd["scores"].values())
                done[img] = rd
                row["read"][name] = rd
        rows.append(row)
        print(
            f"{i + 1:2d} {path.stem} {scene:14s} sam={row['sam']['method']} iou={row['sam']['iou']:.2f} "
            f"code iou={row['code']['iou']:.2f}"
            + (f" read sam/code/full={[row['read'][k]['all'] for k in ('sam', 'code', 'full')]}" if args.read else ""),
            flush=True,
        )
    crop._call_sam = real_call  # type: ignore[assignment]
    for k in ("CROP_MODE", "SAM_CROP"):
        os.environ.pop(k, None)
    return {"rows": rows, "model": cfg.model, "base_url": cfg.base_url}


def summarise(res: dict[str, Any]) -> dict[str, Any]:
    rows = res["rows"]
    n = len(rows)
    calls = [c for r in rows for c in r["sam"]["calls"]]
    ok_calls = [c for c in calls if c.get("status") == 200]
    s: dict[str, Any] = {
        "n": n,
        "sam_model": crop.SAM_MODEL,
        "reader_model": res["model"],
        "base_url": res["base_url"],
        "sam_calls": len(calls),
        "sam_calls_ok": len(ok_calls),
        "sam_call_errors": sorted({c.get("error", "")[:80] for c in calls if "error" in c}),
        "sam_call_latency_s": {
            "median": round(statistics.median([c["s"] for c in ok_calls]), 2) if ok_calls else None,
            "max": round(max(c["s"] for c in ok_calls), 2) if ok_calls else None,
        },
        "sam_box_returned": sum(r["sam"]["method"] == "sam" for r in rows),
        "sam_fell_back_to_code": sum(r["sam"]["method"] == "code" for r in rows),
    }
    for name in ("sam", "code"):
        s[name] = {
            "mean_iou": round(statistics.mean(r[name]["iou"] for r in rows), 3),
            "iou_ge_0_8": sum(r[name]["iou"] >= 0.8 for r in rows),
            "receipt_fully_kept": sum(r[name]["kept"] >= 0.999 for r in rows),
            "mean_kept": round(statistics.mean(r[name]["kept"] for r in rows), 3),
            "median_crop_s": round(statistics.median(r[name]["s"] for r in rows), 2),
        }
    if rows and "read" in rows[0]:
        for name in ("sam", "code", "full"):
            reads = [r["read"][name] for r in rows]
            s[f"read_{name}"] = {
                "all_fields_correct": sum(x["all"] for x in reads),
                "errors": sum(bool(x["error"]) for x in reads),
                "per_field": {f: sum(x["scores"][f] for x in reads) for f in FIELDS},
            }
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--read", action="store_true", help="also read each crop with the reader model")
    ap.add_argument("--model", default=os.getenv("MODEL_API_MODEL") or "muse-spark-1.3")
    ap.add_argument("--out", default="runs/sam_crop_live")
    args = ap.parse_args()
    res = asyncio.run(run(args))
    out = Path(args.out)
    (out / "rows.json").write_text(json.dumps(res["rows"], indent=2, default=str), encoding="utf-8")
    summary = summarise(res)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
