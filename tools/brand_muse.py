"""Generate Accnomos brand concepts with Muse Image (muse-image-1.0, $0.01/image).

Reads MODEL_API_KEY from the repo .env (never printed). Writes PNGs to builds/listing/muse/ in the project folder.
Usage: python tools/brand_muse.py [--n 4]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(
    r"C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\listing\muse"
)

BRIEF = (
    "Accnomos is a UK small-business bookkeeping app: receipts are read by AI, the owner approves each entry, "
    "and the VAT return is computed by code. Brand feel: calm, trustworthy, modern, warm off-white paper and deep teal "
    "(#0F6E63) with a darker teal (#0A4F47) and charcoal (#1B1F24). No text, no letters, no numbers, no logos of other companies."
)

PROMPTS = {
    "icon": (
        f"{BRIEF} Design a flat, minimal Android app icon on a solid deep-teal rounded square: a single simplified "
        "paper receipt or ledger card with three short lines, and a bold check-mark badge in the lower-right corner. "
        "Centered, high contrast, crisp vector-like edges, no gradients heavier than subtle, no shadows, no text."
    ),
    "feature": (
        f"{BRIEF} Design a wide 1024x500 Google Play feature graphic background: abstract composition of soft paper "
        "receipt shapes drifting from the left into a tidy ledger grid on the right, deep-teal background with warm "
        "off-white shapes, generous empty space on the right third for a headline to be added later. No text at all."
    ),
    "hero": (
        f"{BRIEF} Design a website hero illustration, landscape: a tradesperson's phone photographing a crumpled receipt, "
        "which turns into neat ledger lines with a teal tick; flat vector style, warm off-white and teal palette, "
        "no text, no faces."
    ),
}


def load_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("MODEL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("MODEL_API_KEY not found in .env")


def generate(key: str, prompt: str, size: str, n: int) -> list[bytes]:
    body = json.dumps(
        {
            "model": "muse-image-1.0",
            "prompt": prompt,
            "n": n,
            "size": size,
            "response_format": "b64_json",
            "output_format": "png",
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.meta.ai/v1/images/generations",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.load(r)
    return [base64.b64decode(d["b64_json"]) for d in data["data"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    key = load_key()
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {"icon": "1024x1024", "feature": "1792x1024", "hero": "1792x1024"}
    total = 0
    for name, prompt in PROMPTS.items():
        if a.only and name != a.only:
            continue
        try:
            imgs = generate(key, prompt, sizes[name], a.n)
        except Exception as e:  # noqa: BLE001
            print(f"{name}: FAILED {e}")
            continue
        for i, b in enumerate(imgs, 1):
            p = OUT / f"{name}-{i}.png"
            p.write_bytes(b)
            total += 1
            print(f"{name}-{i}.png {len(b) // 1024} KB")
    print(f"done: {total} images (~${total * 0.01:.2f})")


if __name__ == "__main__":
    main()
