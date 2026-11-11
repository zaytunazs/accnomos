# Task: The receipt-crop image model receipt crop before extraction (the hosted model's API), with code fallback

Accnomos monorepo (public; UK English; no secrets). Read first: `services/runtime/app/{pipeline.py,ai/extract.py,ai/config.py,checks.py}`,
`evals/harness/*`, `evals/gold/receipts/README.md`, and the research note in `README.md`/`docs/DEV.md` about the receipt-crop image model
(`POST https://api.meta.ai/v1/responses`, `model: "sam-3.1"`, input = `input_text` short noun + `input_image`; output text carries boxes
in source pixels plus base85 masks; $2.50 per 1k images). Verify the exact request/response shape against the model provider docs link in the notes
before coding; if the docs are unreachable, implement behind a feature flag with a clearly marked parser and a fixture.

## Goal
Phone photos often contain a table, hands, other papers. Before the local open-weights model/Spark reads a document, crop to the receipt:
1. `app/ai/crop.py`: `crop_document(image_bytes, cfg) -> CropResult(image_bytes, box, method)`.
   - Method A (`sam`): when the user's AI mode is `key` (the hosted model's API), call the receipt-crop image model with the noun "receipt" (fallback noun "invoice"),
     parse the largest box, pad 3 %, crop. Cache nothing.
   - Method B (`code`): OpenCV-free fallback using Pillow + numpy: grayscale → Otsu threshold → largest bright connected component →
     bounding box; accept only if it covers 25–95 % of the image, else return the original.
   - Always return the original when confidence is low; never fail the pipeline because of cropping.
2. Wire into `process_image(...)` before extraction; record `crop.method` and `crop.box` in the proposal's `checks`/metadata so the UI
   can show "Cropped with the receipt-crop image model" / "Cropped by code" chips.
3. Evals: add `evals/harness/crop_bench.py` that renders 20 gold receipts onto cluttered backgrounds (tables, shadows, a second paper),
   runs method B (and A if `MODEL_API_KEY` is set), and reports IoU vs the known placement. Commit a small report `evals/REPORT_crop_*.md`
   with the numbers you actually got (method B at least).
4. Tests: parser fixture for the receipt-crop image model output, fallback box logic, "returns original when uncertain".

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
