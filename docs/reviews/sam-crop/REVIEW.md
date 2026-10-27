# Review — `claude/sam-crop`

Task: SAM 3.1 receipt crop before extraction, with a Pillow + numpy fallback (`TASK_BRIEF.md`).

## What was checked

- `services/runtime`: `pytest -q`: 56 passed before the review, 58 after. No other Python package or service was touched.
- `apps/web`: `pnpm run build` compiled cleanly before and after the review.
- `evals/harness/crop_bench.py --limit 20 --no-report` reproduces `evals/REPORT_crop_code_20_2026-10-27.md` exactly
  (code: 20/20 cropped, mean IoU 0.882, median 0.890, 19/20 ≥ 0.8, 20/20 kept ≥ 99 %).
- Diff read for product rules. Nothing is written server-side: the crop runs in memory and nothing is cached. The
  `details` diagnostics are never put on the proposal. Duplicate detection still hashes the original file. Cropping
  cannot fail the pipeline: every path falls back to the original bytes. SAM only runs in key mode (the user's
  Meta API key) and only with `SAM_CROP=1`. No secrets, money maths or UK-English slips found.

## What I fixed

- `b3cd483` runtime(crop):
  - Phone JPEGs that Pillow reports as `MPO` were re-encoded as **PNG** while the request still said
    `image/jpeg`. They now stay JPEG.
  - Any format other than JPEG/PNG/WebP (for example GIF) is now passed through uncropped, so the MIME type stays true.
  - SAM used to receive the raw, unrotated bytes while its box was applied to the EXIF-upright image. Rotated
    phone photos now send SAM the upright pixels.
  - The pure-Python flood fill and the re-encoding now run in `asyncio.to_thread` instead of blocking the event loop.
  - Two tests added: SAM sees upright pixels; MPO stays JPEG and GIF passes through.
- `a242ae3` web(review): the ok `CROP` check was counted in "Checks run by code: N of M passed", which made the count
  bigger than the real number of checks. It is now left out of the count, and the crop note ("Cropped with SAM 3.1" /
  "Cropped by code") is added to the end of the same line.
- This commit: one line in `docs/DEV.md` on format pass-through, plus this file.

## What remains

- **`uv.lock` is stale**: `services/runtime/pyproject.toml` now depends on `pillow>=10` and `numpy>=1.26`, but the lock's
  `accnomos-runtime` entry does not list them. I did not have permission to run `uv lock` here. Run `uv lock` and commit before merging.
- **The SAM 3.1 wire format is unverified.** The request body and the parser follow the research note only. The fixture
  is marked ILLUSTRATIVE. `SAM_CROP` stays off by default until a real response has been captured and checked against `parse_sam_boxes`.
  Method A has never run against the live API, and the crop report has numbers for method B only.
- No dedicated chip component in the UI. The crop note is plain text on the verifier line (`LiveReview.tsx`), and
  `ProposalCard` has no crop-specific styling.
- Bench scenes are synthetic (flat colours, drawn hand, mug and pen). Expect lower IoU on real phone photos.
  The code method is a pure-Python flood fill on a ≤400 px copy (~0.06 s per image here). Fine for one upload; not tuned for batches.
- README "What works today" correctly does not list cropping. Add a row only after it has been checked live.
- `TASK_BRIEF.md` is committed at the repo root (commit `f7f1a76`). Decide whether it should be merged.

## How to verify by hand

Run `cd services/runtime && pytest -q tests/test_crop.py` (18 tests, under 2 s). Then
`cd evals && python -m harness.crop_bench --limit 20 --no-report --images /tmp/crop` and open a few of the scene PNGs
next to the boxes in the printed table. Start the runtime with `CROP_MODE=auto` (and no `SAM_CROP`). Upload a phone photo of
a receipt on a table through `/review`. The proposal should show "· Cropped by code" on the verifier line, the
`crop` box should be in `_System/proposals/<id>.json`, and `doc_sha256` should equal the hash of the uploaded file. Repeat with
`CROP_MODE=off` and check that `crop.method` is `"none"`. Only after capturing a real `sam-3.1` response should you try
`SAM_CROP=1` with a key-mode config.
