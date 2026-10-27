# Task: Verifier agent (second opinion) — Muse Spark Open on Baseten, or Spark via Meta API, agreeing/disagreeing per field

Accnomos monorepo (public; UK English; no secrets). Read first: `services/runtime/app/{pipeline.py,ai/extract.py,ai/config.py,checks.py,
schemas.py}`, `evals/harness/{run_extraction,judge}.py`, README (the "Reviewer → Verifier → Human" pipeline).

## Goal
After the Extractor (Glimmer or Spark) produces a document, a **Verifier** model re-reads the image independently with a *different*
prompt (field-by-field questions, no access to the first answer) and the code compares the two. Agreement raises confidence; a
disagreement on supplier/date/total/VAT puts the proposal into "Needs a look" with both values shown. The model never merges values.

## Implementation
- `app/ai/verify.py`: `verify(image_bytes, extracted: Doc, cfg) -> Verification(fields: {name: {extractor, verifier, agree: bool}}, agree_all: bool, model: str)`.
  Backends in priority: (1) Baseten Spark Open — OpenAI-compatible `https://inference.baseten.co/v1/chat/completions`, model
  `meta-models/muse-spark-open` (verify slug in docs; env `BASETEN_API_KEY`, `VERIFIER_MODEL`); (2) Meta API `muse-spark-1.3` with the
  user's key when (1) is not configured; (3) Glimmer via Ollama with a *different* prompt when in local mode. The user's choice of
  mode/key stays the same headers as today; Baseten key is a server env **only if the owner sets it** (`.env.example` entry, never a real value).
- Compare in code: strings normalised (case, punctuation, whitespace, "Ltd/Limited"), dates by value, money by pence with ±1p tolerance,
  VAT number by digits.
- Pipeline: run the verifier only when the first extraction passed checks (saves cost); attach `verification` to the proposal; the UI's
  existing "Verifier agrees · all N fields match" chip must now be real (web `review/*` — find where the chip is rendered and bind it).
- Evals: extend `evals/harness/run_extraction.py` with `--verify`; run on 20 gold docs with whatever backend is configured on the Spark
  (Glimmer local is fine) and commit `evals/REPORT_verifier_*.md` with the real agreement numbers.
- Tests: comparison normalisation, disagreement routing, backend selection.

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
