"""Title, section and thumbnail art for the videos, and cover art for the how-to guides, from Muse Image.

    python tools/video/muse_images.py                 # every card in docs/video/IMAGE_PROMPTS.md that has no PNG yet
    python tools/video/muse_images.py --only judges-title,thumb-judges
    python tools/video/muse_images.py --dry-run       # list what would be asked for (no key needed, no call)
    python tools/video/muse_images.py --force         # ask again for cards that already have a PNG

Runs on the owner's PC (this repo's cloud sessions may not call Meta's API). Reads the key from META_API_KEY (or
MODEL_API_KEY, the name Meta's docs use); the key is never printed or written anywhere. Without a key it says so and
exits 0, so a regenerate run on a machine without one still finishes; the videos then use plain brand-colour cards.

The call, as documented by Meta (read 29 Oct 2026):
  * https://dev.meta.ai/docs/models: Muse Image is `muse-image-1.0`, reached through the single-shot
    `/v1/images/generations` endpoint (or the Responses API).
  * https://dev.meta.ai/docs/image-generation: `POST https://api.meta.ai/v1/images/generations` with a bearer key,
    OpenAI Images compatible; `n` 1-10; `size` is a "WxH" string that sets the aspect ratio only (the image comes back
    at the generator's own resolution); `response_format` "b64_json" (default) puts base64 bytes in `data[].b64_json`;
    `output_format` "webp" (default), "png" or "jpeg"; 503 is retryable, 400 `content_policy_violation` is a safety
    block, unknown top-level fields are rejected with 400.
  * https://dev.meta.ai/docs/api-reference/images/schemas: CreateImageRequest fields (`model`, `prompt`, `n`, `size`,
    `response_format`, `output_format`, `reasoning_strength`, `tool_enablement`, ...). Unknown keys nested inside
    request objects are ignored, so the tool switches below cannot break the call.
Price: USD 0.01 per image (docs/submission/META_MODELS.md); the 32 cards in IMAGE_PROMPTS.md cost about USD 0.32.

Because the size only sets the aspect ratio, each picture is cropped and scaled to the exact size its card asks for
(Pillow if installed; otherwise the original is kept and assemble.sh crops it with ffmpeg). Each PNG gets a JSON
sidecar: model, endpoint, prompt, requested and saved size, date.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "docs/video/IMAGE_PROMPTS.md"
OUT = ROOT / "docs/video/cards"
ENDPOINT = "https://api.meta.ai/v1/images/generations"
MODEL = "muse-image-1.0"


def parse_prompts(text: str) -> tuple[str, list[dict]]:
    """(style, cards): every `## id` section with its `size:`, `use:` and prompt paragraph."""
    style = ""
    cards: list[dict] = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        head, _, body = block.partition("\n")
        card_id = head.strip()
        size = re.search(r"^size:\s*(\S+)", body, re.M)
        use = re.search(r"^use:\s*(.+)$", body, re.M)
        prompt = " ".join(
            line.strip() for line in body.splitlines() if line.strip() and not re.match(r"^(size|use):", line.strip())
        )
        if card_id == "style":
            style = prompt
            continue
        if not size or not re.fullmatch(r"\d+x\d+", size.group(1)):
            raise SystemExit(f"IMAGE_PROMPTS.md: card {card_id!r} has no size: WxH line")
        cards.append(
            {"id": card_id, "size": size.group(1), "use": use.group(1).strip() if use else "", "prompt": prompt}
        )
    return style, cards


def api_key() -> str | None:
    for name in ("META_API_KEY", "MODEL_API_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return None


def request_image(key: str, prompt: str, size: str) -> bytes:
    body = {
        "model": MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "b64_json",
        "output_format": "png",
        # No reference look-ups: the cards must not pick up real logos or places.
        "tool_enablement": {"enable_image_search": False, "enable_web_search": False},
    }
    data = json.dumps(body).encode()
    delay = 4.0
    for attempt in range(4):
        req = urllib.request.Request(
            ENDPOINT,
            data=data,
            method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                payload = json.load(r)
            return base64.b64decode(payload["data"][0]["b64_json"])
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 400 and "tool_enablement" in detail:
                body.pop("tool_enablement")  # an account where the switch is not offered: plain request instead
                data = json.dumps(body).encode()
                continue
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    raise RuntimeError("no image after retries")


def fit(png: bytes, size: str) -> tuple[bytes, str]:
    """Crop to the card's aspect ratio and scale to its exact size; unchanged if Pillow is missing."""
    try:
        from PIL import Image
    except ImportError:
        return png, "original (assemble.sh crops it)"
    w, h = (int(x) for x in size.split("x"))
    im = Image.open(io.BytesIO(png)).convert("RGB")
    scale = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.Resampling.LANCZOS)
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    im = im.crop((left, top, left + w, top + h))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue(), size


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    style, cards = parse_prompts(PROMPTS.read_text(encoding="utf-8"))
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    todo = [c for c in cards if (not only or c["id"] in only) and (a.force or not (OUT / f"{c['id']}.png").exists())]
    print(f"{len(cards)} cards in {PROMPTS.relative_to(ROOT)}; {len(todo)} to make (about USD {len(todo) * 0.01:.2f})")
    if a.dry_run:
        for c in todo:
            print(f"  {c['id']:<24} {c['size']:<10} {c['use']}")
        return
    if not todo:
        return
    key = api_key()
    if not key:
        print(
            "No META_API_KEY (or MODEL_API_KEY) in the environment: no images made. Set it and run again; until then "
            "assemble.sh uses plain brand-colour cards."
        )
        return
    OUT.mkdir(parents=True, exist_ok=True)
    made = failed = 0
    for c in todo:
        prompt = f"{style} {c['prompt']}".strip()
        try:
            raw = request_image(key, prompt, c["size"])
        except Exception as e:  # noqa: BLE001 - one bad card must not stop the rest
            failed += 1
            print(f"{c['id']}: FAILED {e}")
            continue
        png, saved = fit(raw, c["size"])
        (OUT / f"{c['id']}.png").write_bytes(png)
        sidecar = {
            "id": c["id"],
            "model": MODEL,
            "endpoint": ENDPOINT,
            "prompt": prompt,
            "size_requested": c["size"],
            "size_saved": saved,
            "use": c["use"],
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "docs": "https://dev.meta.ai/docs/image-generation (read 29 Oct 2026)",
        }
        (OUT / f"{c['id']}.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
        made += 1
        print(f"{c['id']}.png  {len(png) // 1024} KB")
    print(f"done: {made} made, {failed} failed (about USD {made * 0.01:.2f})")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
