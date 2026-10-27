# Task: Receipt extraction quality — fix the known failure modes with the 200-document eval as the yardstick (Glimmer local)

Accnomos monorepo (public; UK English; no secrets; Glimmer 30B on Ollama :11434 is the model; Qwen on vLLM :8000 may be used only to
generate extra synthetic documents). Read first `evals/runs/glimmer_messy_200/report.md` (weaknesses: VAT-inclusive net, quantity applied
twice, handwritten totals, no-VRN handling), `evals/harness/run_extraction.py`, `services/runtime/app/ai/extract.py` (prompt + schema),
`app/checks.py` (post-read checks), `app/pipeline.py`, `docs/reviews/evals-expand/REVIEW.md`, `docs/reviews/verifier/REVIEW.md`.

## Deliverables
1. Baseline: run the 200-doc eval once as-is and commit the report under `evals/runs/glimmer_messy_200_before/` (numbers only; no PNGs).
2. Improve in this order, each a separate commit with its before/after numbers in the message, keeping every runtime test green:
   a. **Deterministic repair in code before the checks**: when the model's net + VAT ≠ gross but gross − VAT = net ± 1p or
      net × 1.2 = gross ± 1p (VAT-inclusive confusion), repair the figures by arithmetic and record `repaired_by_code` in the
      proposal so the card can say so; never silently.
   b. **Quantity × unit price** handled per line (lines sum must equal net; if a line's total already includes the quantity, do not
      multiply again); same `repaired_by_code` note.
   c. **Prompt/schema**: one or two sentences in the extractor prompt for the specific confusions (stay within the JSON schema; no
      chain-of-thought dumps); measure, keep only if the eval improves on *every* class.
   d. **Handwritten / faded**: route documents whose first read has confidence < 0.6 or failing arithmetic to a second read of the
      cropped image at higher resolution (reuse `crop_document`), then take the read that passes more checks; cap at one retry.
3. Final run → `evals/runs/glimmer_messy_200/` updated; README eval row, `docs/HONESTY.md` and the card wording ("Figures repaired
   by code from the receipt's own arithmetic") updated. Target: field accuracy up with no increase in false `passed` status.
Commit in small steps; do not push. Finish with `git log --oneline -8` and the before/after table.
