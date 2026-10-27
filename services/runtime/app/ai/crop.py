"""Crop a phone photo to the document before extraction.

Two methods, tried in order; any error or doubt returns the original bytes untouched:

* sam  -> Meta SAM 3.1 on `/responses` (key mode only, and only with `SAM_CROP=1`).
          Prompts "receipt", then "invoice"; takes the largest box, pads 3 %, crops.
* code -> Pillow + numpy: grayscale -> Otsu threshold -> largest bright connected
          component -> bounding box. Accepted only if it covers 25-95 % of the photo and
          the paper fills most of its box; otherwise the original is returned.

Env: CROP_MODE = auto (default: sam if allowed, else code) | code | off; SAM_CROP = 1 to allow sam.
Nothing is cached. Boxes are [x0, y0, x1, y1] in source pixels (x1/y1 exclusive), after
EXIF orientation is applied.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
import numpy as np
from PIL import Image, ImageOps

from app.ai.config import AiConfig

log = logging.getLogger(__name__)

CropMethod = Literal["sam", "code", "none"]
Box = tuple[int, int, int, int]

SAM_MODEL = "sam-3.1"
SAM_NOUNS = ("receipt", "invoice")
SAM_TIMEOUT_S = 30.0
SAM_MIN_COVER = 0.05  # SAM is trusted to find a small receipt in a wide photo
SAM_MIN_SCORE = 0.5
PAD = 0.03
CODE_MIN_COVER, CODE_MAX_COVER = 0.25, 0.95
CODE_MIN_FILL = 0.55  # component pixels / box area; a tilted rectangle fills ~0.8+
NOOP_COVER = 0.95  # a crop keeping more than this of the photo is not worth re-encoding
WORK_SIDE = 400  # code method works on a downscaled copy (longest side, px)

_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_ALIASES = {"MPO": "JPEG"}  # many phone cameras write multi-picture JPEGs; Pillow reports them as MPO
_ORIENTATION = 0x0112


@dataclass
class CropResult:
    image_bytes: bytes
    box: Box | None  # None = original returned
    method: CropMethod
    note: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {"method": self.method, "box": list(self.box) if self.box else None, "note": self.note}


# --------------------------------------------------------------------------- geometry


def pad_box(box: Box, size: tuple[int, int], frac: float = PAD) -> Box:
    """Grow a box by `frac` of its own width/height on each side, clamped to the image."""
    x0, y0, x1, y1 = box
    w, h = size
    dx, dy = round((x1 - x0) * frac), round((y1 - y0) * frac)
    return max(0, x0 - dx), max(0, y0 - dy), min(w, x1 + dx), min(h, y1 + dy)


def cover(box: Box, size: tuple[int, int]) -> float:
    x0, y0, x1, y1 = box
    return max(0, x1 - x0) * max(0, y1 - y0) / float(size[0] * size[1])


def iou(a: Box, b: Box) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


# --------------------------------------------------------------------------- method B: code


def otsu_threshold(gray: np.ndarray) -> tuple[int, float]:
    """Return (threshold, separability 0..1). Pixels > threshold are 'bright'."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    p = hist / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu_t * omega - mu) ** 2 / (omega * (1 - omega))
    between = np.nan_to_num(between)
    t = int(np.argmax(between))
    var_t = float((p * (np.arange(256) - mu_t) ** 2).sum())
    return t, (float(between[t]) / var_t if var_t > 0 else 0.0)


def _erode(mask: np.ndarray) -> np.ndarray:
    """3x3 binary erosion (cuts thin bridges such as a shadow line touching another paper)."""
    m = np.pad(mask, 1, constant_values=False)
    out = mask.copy()
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out &= m[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
    return out


def largest_component(mask: np.ndarray) -> tuple[Box, float] | None:
    """Bounding box (x0, y0, x1, y1) and fill of the largest 4-connected True region.

    Fill = sum over rows of the region's left-to-right span / box area, so dark print inside
    the paper counts as paper; a tilted rectangle scores ~0.8+, a ragged blob much less.
    """
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best: tuple[int, list[tuple[int, int]]] | None = None
    for start in np.flatnonzero(mask.ravel()):
        sy, sx = divmod(int(start), w)
        if seen[sy, sx]:
            continue
        seen[sy, sx] = True
        q = deque([(sy, sx)])
        pixels: list[tuple[int, int]] = []
        while q:
            y, x = q.popleft()
            pixels.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if best is None or len(pixels) > best[0]:
            best = (len(pixels), pixels)
    if best is None:
        return None
    pts = np.asarray(best[1])
    ys, xs = pts[:, 0], pts[:, 1]
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    lo = np.full(h, w, dtype=np.int64)
    hi = np.full(h, -1, dtype=np.int64)
    np.minimum.at(lo, ys, xs)
    np.maximum.at(hi, ys, xs)
    rows = hi >= 0
    spans = int((hi[rows] - lo[rows] + 1).sum())
    return (x0, y0, x1, y1), spans / float((x1 - x0) * (y1 - y0))


def code_box(img: Image.Image) -> tuple[Box | None, dict[str, Any]]:
    """Find the paper in `img`; return its box in `img` pixels (or None) and diagnostics."""
    w, h = img.size
    scale = min(1.0, WORK_SIDE / max(w, h))
    small = img.convert("L")
    if scale < 1.0:
        small = small.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.BILINEAR)
    gray = np.asarray(small, dtype=np.uint8)
    t, sep = otsu_threshold(gray)
    mask = _erode(gray > t)
    found = largest_component(mask)
    info: dict[str, Any] = {"threshold": t, "separability": round(sep, 3)}
    if found is None:
        return None, {**info, "reason": "no bright region"}
    (bx0, by0, bx1, by1), fill = found
    # undo the erosion (1 px) and the downscale
    bx0, by0, bx1, by1 = max(0, bx0 - 1), max(0, by0 - 1), min(gray.shape[1], bx1 + 1), min(gray.shape[0], by1 + 1)
    box = (int(bx0 / scale), int(by0 / scale), min(w, int(np.ceil(bx1 / scale))), min(h, int(np.ceil(by1 / scale))))
    c = cover(box, (w, h))
    info.update(cover=round(c, 3), fill=round(fill, 3))
    if not CODE_MIN_COVER <= c <= CODE_MAX_COVER:
        return None, {**info, "reason": f"covers {c:.0%} of the photo (needs 25-95 %)"}
    if fill < CODE_MIN_FILL:
        return None, {**info, "reason": f"region fills only {fill:.0%} of its box"}
    return box, info


# --------------------------------------------------------------------------- method A: SAM 3.1
#
# UNVERIFIED WIRE FORMAT. The Meta docs could not be fetched when this was written, so the
# request follows the research note (POST {base}/responses, model "sam-3.1", input_text noun +
# input_image) and the parser below is deliberately tolerant. It is off unless SAM_CROP=1.
# Fixture: services/runtime/tests/fixtures/sam_response.json. Check both against a live call
# before enabling.

_BOX_KEYS = ("box", "bbox", "bounding_box", "xyxy")
_QUAD = re.compile(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]")


def sam_request_body(noun: str, data_url: str) -> dict[str, Any]:
    return {
        "model": SAM_MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": noun},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
    }


def _response_text(data: dict[str, Any]) -> str:
    """Concatenate the text parts of a Responses-style payload."""
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for c in item.get("content") or []:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "\n".join(parts)


def _as_box(v: Any) -> Box | None:
    if isinstance(v, (list, tuple)) and len(v) == 4 and all(isinstance(n, (int, float)) for n in v):
        x0, y0, x1, y1 = v
    elif isinstance(v, dict) and all(k in v for k in ("x0", "y0", "x1", "y1")):
        x0, y0, x1, y1 = v["x0"], v["y0"], v["x1"], v["y1"]
    elif isinstance(v, dict) and all(k in v for k in ("x", "y", "w", "h")):
        x0, y0, x1, y1 = v["x"], v["y"], v["x"] + v["w"], v["y"] + v["h"]
    else:
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return round(x0), round(y0), round(x1), round(y1)


def _walk(obj: Any, out: list[tuple[Box, float | None]]) -> None:
    if isinstance(obj, dict):
        used = None
        for k in _BOX_KEYS:
            if k in obj and (b := _as_box(obj[k])):
                score = obj.get("score", obj.get("confidence"))
                out.append((b, float(score) if isinstance(score, (int, float)) else None))
                used = k
                break
        else:
            if (b := _as_box(obj)) is not None:
                out.append((b, None))
                return
        for k, v in obj.items():
            if k != used and isinstance(v, (dict, list)):
                _walk(v, out)
    elif isinstance(obj, list):
        if obj and all(isinstance(v, (list, tuple)) for v in obj):
            for v in obj:
                if (b := _as_box(v)) is not None:
                    out.append((b, None))
                    continue
                _walk(v, out)
        else:
            for v in obj:
                _walk(v, out)


def parse_sam_boxes(data: dict[str, Any]) -> list[tuple[Box, float | None]]:
    """Every (box, score) found in a SAM response; masks (base85) are ignored."""
    text = _response_text(data).strip()
    found: list[tuple[Box, float | None]] = []
    if text:
        try:
            _walk(json.loads(text), found)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            try:
                _walk(json.loads(text[start : end + 1]), found) if 0 <= start < end else None
            except json.JSONDecodeError:
                pass
            if not found:
                found = [(b, None) for q in _QUAD.findall(text) if (b := _as_box([float(n) for n in q]))]
    return found


def pick_sam_box(boxes: list[tuple[Box, float | None]], size: tuple[int, int]) -> Box | None:
    """Largest confident box, clamped to the image."""
    w, h = size
    ok: list[Box] = []
    for (x0, y0, x1, y1), score in boxes:
        if score is not None and score < SAM_MIN_SCORE:
            continue
        b = (max(0, x0), max(0, y0), min(w, x1), min(h, y1))
        if b[2] > b[0] and b[3] > b[1]:
            ok.append(b)
    return max(ok, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), default=None)


async def _call_sam(noun: str, data_url: str, cfg: AiConfig) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(SAM_TIMEOUT_S)) as client:
        r = await client.post(f"{cfg.base_url}/responses", json=sam_request_body(noun, data_url), headers=headers)
        r.raise_for_status()
        return r.json()


async def sam_box(img: Image.Image, data_url: str, cfg: AiConfig) -> tuple[Box | None, dict[str, Any]]:
    for noun in SAM_NOUNS:
        boxes = parse_sam_boxes(await _call_sam(noun, data_url, cfg))
        box = pick_sam_box(boxes, img.size)
        if box is not None:
            c = cover(box, img.size)
            if c < SAM_MIN_COVER:
                return None, {"noun": noun, "reason": f"box covers only {c:.0%}"}
            return box, {"noun": noun, "candidates": len(boxes), "cover": round(c, 3)}
    return None, {"reason": "no box for receipt/invoice"}


# --------------------------------------------------------------------------- entry point


def sam_allowed(cfg: AiConfig | None) -> bool:
    return bool(cfg and cfg.mode == "key" and cfg.api_key and os.getenv("SAM_CROP", "") == "1")


def _encode(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=92)
    elif fmt == "WEBP":
        img.save(buf, format="WEBP", quality=92)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


def _original(image_bytes: bytes, note: str, **details: Any) -> CropResult:
    return CropResult(image_bytes, None, "none", note, details)


async def crop_document(image_bytes: bytes, cfg: AiConfig | None = None) -> CropResult:
    """Crop to the document if we are confident; never raises.

    The cropped image keeps the source format (JPEG/PNG/WebP), so the caller's MIME type still holds;
    any other format is passed through uncropped.
    """
    mode = os.getenv("CROP_MODE", "auto").strip().lower()
    if mode == "off":
        return _original(image_bytes, "cropping off")
    try:
        src = Image.open(io.BytesIO(image_bytes))
        fmt = _ALIASES.get(src.format or "", src.format or "")
        rotated = src.getexif().get(_ORIENTATION, 1) not in (1, None)
        img = ImageOps.exif_transpose(src)
        img.load()
    except Exception as exc:  # noqa: BLE001 - unreadable image: let extraction report it
        return _original(image_bytes, f"could not open image: {exc}")
    if fmt not in _FORMATS:  # re-encoding would no longer match the caller's MIME type
        return _original(image_bytes, f"format {src.format} not cropped")

    details: dict[str, Any] = {}
    box: Box | None = None
    method: CropMethod = "none"
    if mode == "auto" and sam_allowed(cfg):
        try:
            # SAM's boxes must be in the same (EXIF-upright) pixels we crop
            sam_bytes = await asyncio.to_thread(_encode, img, fmt) if rotated else image_bytes
            b64 = base64.b64encode(sam_bytes).decode("ascii")
            box, details["sam"] = await sam_box(img, f"data:{_FORMATS[fmt]};base64,{b64}", cfg)  # type: ignore[arg-type]
            if box is not None:
                method = "sam"
        except Exception as exc:  # noqa: BLE001 - SAM is best effort; fall back to code
            log.warning("SAM crop failed: %r", exc)
            details["sam"] = {"reason": f"error: {type(exc).__name__}"}
    if box is None:
        try:
            box, details["code"] = await asyncio.to_thread(code_box, img)  # pure-Python flood fill: off the event loop
            if box is not None:
                method = "code"
        except Exception as exc:  # noqa: BLE001
            log.warning("code crop failed: %r", exc)
            details["code"] = {"reason": f"error: {type(exc).__name__}"}
    if box is None:
        reason = (details.get("code") or details.get("sam") or {}).get("reason", "no confident box")
        return _original(image_bytes, reason, **details)

    box = pad_box(box, img.size)
    if cover(box, img.size) > NOOP_COVER:
        return _original(image_bytes, "document already fills the photo", **details)
    try:
        out = await asyncio.to_thread(_encode, img.crop(box), fmt)
    except Exception as exc:  # noqa: BLE001
        return _original(image_bytes, f"could not encode crop: {exc}", **details)
    label = "Cropped with SAM 3.1" if method == "sam" else "Cropped by code"
    return CropResult(out, box, method, label, details)


REREAD_SCALE = 2.0
REREAD_MAX_SIDE = 2000  # px, longest side of the second-read image


def _upscale(image_bytes: bytes) -> bytes:
    src = Image.open(io.BytesIO(image_bytes))
    fmt = _ALIASES.get(src.format or "", src.format or "")
    if fmt not in _FORMATS:  # re-encoding would no longer match the caller's MIME type
        return image_bytes
    img = ImageOps.exif_transpose(src)
    scale =min(REREAD_SCALE, REREAD_MAX_SIDE / max(img.size))
    if scale > 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
    img = ImageOps.autocontrast(img.convert("RGB"), cutoff=1)  # lifts faded thermal print and pale ink
    return _encode(img, fmt)


async def reread_image(image_bytes: bytes) -> bytes:
    """The (already cropped) document at up to 2x resolution with auto-contrast, for a second read.

    Keeps the source format, so the caller's MIME type still holds; on any error returns the input.
    """
    try:
        return await asyncio.to_thread(_upscale, image_bytes)
    except Exception as exc:  # noqa: BLE001 - a second read on the same image is still worth having
        log.warning("re-read upscale failed: %r", exc)
        return image_bytes
