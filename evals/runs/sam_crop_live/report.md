# SAM 3.1 crop, live on the Meta Model API (20 synthetic phone-photo scenes)

SAM model `sam-3.1` and reader `muse-spark-1.3-contributor`, both at `https://api.meta.ai/v1`,
run from the owner's server with the server's key (never printed or stored).
Script: `evals/harness/sam_crop_live.py`; per-image rows: `rows.json` (boxes, timings, a mask-free
sample of each SAM reply, no response ids). Scenes: gold receipts placed on five cluttered backgrounds
with a known box (`harness.crop_bench.make_scene`), as in `evals/REPORT_crop_code_20_2026-10-27.md`.

## SAM calls

- Calls: 20, answered 200: 20; errors: none.
- Latency per call: median 1.5 s, max 3.17 s.
- A box was returned and used for 20 of 20 photos; fell back to the code crop for 0.

## Crop box against the known receipt box

| Method | Mean IoU | IoU ≥ 0.8 | Receipt fully inside | Mean share kept | Median time |
|---|---:|---:|---:|---:|---:|
| SAM 3.1 (with code fallback) | 0.901 | 20/20 | 20/20 | 1.0 | 1.52 s |
| Code crop | 0.88 | 18/20 | 20/20 | 1.0 | 0.07 s |

## Reading each crop with `muse-spark-1.3-contributor`

Same pipeline as the app (`process_image(..., crop=False)` on the given crop: code repairs, checks, one
re-read when unsure, the Verifier), scored field by field against the gold document.

| Image read | Every field right | Errors |
|---|---:|---:|
| SAM crop | 19/20 | 0 |
| Code crop | 19/20 | 0 |
| Whole photo, no crop | 19/20 | 0 |

Lowest code-crop IoU: 041_sales_invoice (dark_desk_mug): code 0.7624, SAM 0.8976; 061_credit_note (shadow_hand): code 0.7806, SAM 0.8995; 191_pi_subcontractor (dark_desk_mug): code 0.8633, SAM 0.8982.

## Limits

- Synthetic scenes, not real phone photos; one rotation and one clutter pattern per scene.
- Where every crop (and the uncropped photo) reads the same, this run shows no reading gain from SAM on these
  scenes: they are legible uncropped. It shows that SAM does not hurt and gives a tighter box.
- Box only: the mask SAM returns is not used.
