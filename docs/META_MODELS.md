# Meta models in Accnomos

Everything below was checked against the code on `claude/judges-docs`. "Run" means we have run it for real; "unit-tested" means
only stubbed HTTP. Prices are **quotes from our own docs or scripts**, not measurements, unless the cell says "measured".

| Model | Where in the product | Purpose | Cost per unit | Fallback | Status |
|---|---|---|---|---|---|
| **Muse Glimmer 30B** (`muse-glimmer:30b`, open weights, Ollama) | `app/ai/extract.py`, local mode; also the local-mode Verifier and *Ask* | Reads receipts/invoices into a strict-JSON schema; categorises; writes grounded answers | No per-call fee (our hardware). Measured on a DGX Spark: 22 s mean, 37 s max per document; the second reading about 7.6 s | Key mode (Muse Spark) | **Run**: 60 messy receipts, 20 verified (below) |
| **Muse Spark** (`muse-spark-1.3`, Meta Model API, the user's key) | Key-mode extraction (`/chat/completions`), key-mode *Ask*, key-mode Verifier when no Baseten key | Same jobs as Glimmer, no hardware needed | Not measured; see dev.meta.ai | Local mode (Glimmer) | Unit-tested; **not run in our evals** (no key in the eval environment) |
| **Muse Spark Open** (Baseten, optional) | `app/ai/verify.py`, key mode only, when the server owner sets `BASETEN_API_KEY` | Independent second reading | Not measured | Meta API verifier, or none (`VERIFIER=off`) | Unit-tested only; the model slug is unconfirmed and the demo deployment does not set the key |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | `app/ai/voice.py`, `POST /books/ask/voice`; web mic on *Ask* | Spoken question → text, then the normal grounded *Ask* | Not measured | Typed question. Disabled in local mode | Stubbed HTTP and a generated tone only; request format from research notes, **not checked against dev.meta.ai; no live mic run** |
| **SAM 3.1** (`sam-3.1`) | `app/ai/crop.py`, key mode, only with `SAM_CROP=1` | Find and crop the receipt in a phone photo before reading | Quote: about $2.50 per 1,000 images (`docs/DEV.md`) | Code crop (Pillow + Otsu), on by default | **Off by default; never run live.** Request/response shape is unverified |
| **Muse Image** (`muse-image-1.0`) | `tools/brand_muse.py`, build time only | Brand concepts for the launcher icon, feature graphic and site hero | $0.01 per image (script docstring); 12 images, USD 0.12 in total (commit message) | n/a | Run. **Not part of the runtime** |

Not used: `muse-wonder-1.0` (multi-step planning) is not called anywhere on this branch; it belongs to the unmerged `claude/chat-actions` branch.
There is no separate LLM "Reviewer" stage (see `docs/ARCHITECTURE.md`).

## Eval results (synthetic gold set, so real photos will score lower)

| Report | Setup | Result |
|---|---|---|
| [`REPORT_glimmer_messy_60`](../evals/REPORT_glimmer_messy_60_2026-10-27.md) | Glimmer, local, 60 messy renderings | Every field right on 73 % of documents; supplier 100 %, VAT 100 %, total 100 %, date 98 %, net 97 %, VAT number 95 %; proposed vs *Needs a look* decision 80 %. Weak cases: `mixed` (0 of 6), `no_vat_number` (2 of 6), `foreign` (3 of 5) |
| [`REPORT_verifier_glimmer_messy_20`](../evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md) | Glimmer extracts, Glimmer verifies with a different prompt, 20 docs | 17 of 18 verified documents agreed on all six fields; **0 extra errors caught** (the code checks had already caught them); 1 false alarm. Too few documents to measure a catch rate |
| [`REPORT_crop_code_20`](../evals/REPORT_crop_code_20_2026-10-27.md) | Code crop on 20 cluttered synthetic scenes | Mean IoU 0.882 against 0.475 for the full frame; 19 of 20 at IoU ≥ 0.8; the receipt was always inside the box. SAM 3.1 was **not run** |
| [`JUDGE_glimmer_messy_60`](../evals/JUDGE_glimmer_messy_60_2026-10-27.json) | Claude (Haiku, escalating to Sonnet) graded the same 60 | Raw output only, with no write-up: severities none 18, minor 15, major 22, unparsed 4. It also flags missing detail such as addresses and line text, so it is stricter than the field table above. Treat it as an unreviewed artefact |

Reproduce: `cd evals && python -m harness.run_extraction --mode local --messy`, see `docs/DEV.md`. The harness has no pytest tests.
