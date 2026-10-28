"""Make the website's screenshots (apps/web/public/shots/*.webp) from the real ones in the repo.

Sources: docs/submission/shots/ (the web app in test mode with the fictional sample books, taken by e2e/demo.spec.ts and
e2e/shots.spec.ts), apps/mobile/screenshots/ (the Android app on an emulator, signed out, sample data) and
apps/web/public/sample-receipt.png. Every output is a crop or resize of one of those: nothing is drawn or edited.
Run from the repo root: `python apps/web/scripts/marketing-images.py` (needs Pillow with WebP).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
SHOTS = ROOT / "docs/submission/shots"
MOBILE = ROOT / "apps/mobile/screenshots"
OUT = ROOT / "apps/web/public/shots"

# name: (source, crop box in source pixels or None, output width)
JOBS: dict[str, tuple[Path, tuple[int, int, int, int] | None, int]] = {
    # Hero: the Review page with the Novex receipt read and waiting; the same card at phone width.
    "hero-review-1280": (SHOTS / "04-scan.png", None, 1280),
    "hero-review-640": (SHOTS / "04-scan.png", None, 640),
    "hero-phone": (SHOTS / "05-proposal-phone.png", None, 390),
    "hero-phone-200": (SHOTS / "05-proposal-phone.png", None, 200),  # shown at about 130-200 px wide
    # The five steps of the process animation (main column only, 816 x 510 shown at 16:10; the highlight boxes in
    # src/components/marketing/ProcessDemo.tsx are percentages of these crops).
    "step-1-receipt": (ROOT / "apps/web/public/sample-receipt.png", None, 750),
    "step-2-read": (SHOTS / "04-scan.png", (348, 290, 1164, 800), 816),
    "step-3-check": (SHOTS / "05-proposal.png", (348, 290, 1164, 800), 816),
    "step-4-approved": (SHOTS / "06-approve.png", (348, 0, 1164, 510), 816),
    "step-5-vat": (SHOTS / "07-vat.png", (348, 0, 1164, 510), 816),
    # Feature screens (main column, below the sample banner where there is one).
    "feat-invoices": (SHOTS / "invoices.png", (352, 50, 1160, 600), 808),
    "feat-reports": (SHOTS / "reports-pl.png", (352, 50, 1160, 800), 808),
    "feat-contacts": (SHOTS / "contacts-statement.png", (352, 50, 1240, 800), 888),
    "feat-files": (SHOTS / "02-files.png", (352, 0, 1160, 560), 808),
    "feat-your-data": (SHOTS / "settings-your-data.png", (352, 50, 1160, 760), 808),
    "feat-ask": (SHOTS / "10-ask.png", (352, 180, 1160, 740), 808),
    "feat-action": (SHOTS / "11-invoice-card.png", (352, 180, 1160, 580), 808),
    # Android (emulator, signed out, labelled sample data).
    "android-review": (MOBILE / "review.png", None, 360),
    "android-ask": (MOBILE / "ask.png", None, 360),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (src, box, width) in JOBS.items():
        im = Image.open(src).convert("RGB")
        if box:
            im = im.crop(box)
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
        path = OUT / f"{name}.webp"
        im.save(path, "WEBP", quality=80, method=6)
        print(f"{path.relative_to(ROOT)}  {im.width}x{im.height}  {path.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
