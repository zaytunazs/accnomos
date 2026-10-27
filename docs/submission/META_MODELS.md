# Meta models: what is used, where, and what is actually verified

Source: `docs/META_MODELS.md`, `docs/ARCHITECTURE.md` (models table), `docs/HONESTY.md`, the code paths named below (all exist on `main`), and the
eval reports in `evals/`. Prices are quotes from our own docs or scripts unless marked measured. **"Run" means the maintainers ran it for real;
"unit-tested" means stubbed HTTP only; "modelled" means the request or response shape is our reading of Meta's docs, not checked against a live call.**

## Summary: verified versus modelled

| Model | Status in one word | Evidence |
|---|---|---|
| Muse Glimmer 30B | **Run** (extraction, verifier) | 60, 200 and 20-document evals, local on a DGX Spark; the other text tasks are stub-tested only |
| Muse Spark 1.3 | **Unit-tested only** | No Meta key in our eval environment; never called live by us |
| Muse Spark Open (Baseten) | **Unit-tested only, slug unconfirmed** | `meta-models/muse-spark-open` is a guess; the demo sets no Baseten key |
| Muse Voice Transcribe | **Modelled** | Request format from research notes, not dev.meta.ai; no live mic run anywhere |
| SAM 3.1 | **Modelled, off by default** | Wire format is a guess; fixture is marked ILLUSTRATIVE; never run live |
| Muse Image | **Run, build time only** | 12 images, USD 0.12 (commit message); not in the runtime |

Not used: `muse-wonder-1.0` is not called anywhere.

## Per model

### Muse Glimmer 30B (`muse-glimmer:30b`, open weights, Ollama, local mode)

- **Where:** `services/runtime/app/ai/extract.py` (reads a receipt or invoice into a strict-JSON schema); `app/ai/verify.py` (the local-mode second reading);
  `app/ai/ask.py` `call_json_model` (Ask, and through it `app/actions.py` chat intents, `app/ai/triage.py`, `app/ai/remind.py`, `app/ai/plan.py` rationale).
- **Why:** open weights mean a document need not leave the machine running Ollama. Caveat to state aloud: in our demo that machine is our DGX Spark, so "local"
  means our hardware; a user's own laptop is not reachable from `api.accnomos.com` (`docs/HONESTY.md`).
- **Verified:** measured on a DGX Spark, mean 22 s and max 37–40 s per document for extraction, about 7.6 s for the second reading (`docs/META_MODELS.md`).
  Evals: `evals/REPORT_glimmer_messy_200_2026-10-27.md` (200 synthetic messy documents: all fields right 88 %, supplier 100 %, date 100 %, net 93 %, side
  100 %, status 93 %); `evals/REPORT_glimmer_messy_60_2026-10-27.md` (first 60, older scoring: 73 %); `evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md`.
  A live run on 27 Oct (upload, scan, 40 s, 9/9 code checks, approve, ledger event) is the maintainers' record with no log committed.
- **Modelled/unverified:** the non-extraction tasks (Ask, intents, triage, reminders, planner) have only run against a stubbed model.
- **Cost:** no per-call fee (our hardware); electricity is not measured.

### Muse Spark 1.3 (`muse-spark-1.3`, Meta Model API, the user's own key)

- **Where:** the same call sites as Glimmer in key mode (`/chat/completions`): `extract.py`, `ask.py` `call_json_model`; `verify.py` in key mode when no Baseten key is set.
- **Why:** no GPU needed; the user brings their own key.
- **Verified:** `services/runtime/tests` against stubbed HTTP. **Not run in our evals.** No accuracy or latency figure exists for it.
- **Cost:** not measured; the repo points to dev.meta.ai. In key mode with no `X-Meta-Api-Key` header the runtime falls back to the server's `META_API_KEY`
  (`app/ai/config.py`; a known, documented gap: typed and voice Ask would run on the operator's key). Only *Test connection* (`/ai/test`) insists on the header.

### Muse Spark Open (Baseten, optional verifier)

- **Where:** `services/runtime/app/ai/verify.py`, key mode only, and only if the server owner sets `BASETEN_API_KEY` (`.env.example`).
  Default slug `meta-models/muse-spark-open`, overridable with `VERIFIER_MODEL` or `BASETEN_MODEL`.
- **Why:** an independent model for the second reading, so the checker is not the model that did the first reading. A different prompt is used and the verifier never sees the first answer.
- **Verified:** unit-tested only (`services/runtime/tests/test_verify.py`). The slug is unconfirmed and no Baseten key is set on the demo, so the demo verifier is Glimmer (local)
  or Spark 1.3 (key mode). The one verifier eval is **Glimmer checking Glimmer** on 20 documents: 17 of 18 verified documents agreed on all six fields,
  0 extra errors caught, 1 false alarm. That does not measure catch rate.
- **Cost:** not measured. `VERIFIER=off` disables it.

### Muse Voice Transcribe (`muse-voice-transcribe-1.0`)

- **Where:** `services/runtime/app/ai/voice.py` `transcribe()`, reached from `POST /books/ask/voice`; the web mic button and the Android mic on Ask. ffmpeg converts to WAV mono 16 kHz first. Key mode only; local mode returns 400.
- **Verified:** `services/runtime/tests/test_voice.py` on a generated tone and stubbed HTTP. The endpoint (`/asr/transcribe`), multipart parts and response field are from research notes. **No live mic run on any browser or phone.**
- **Do not demo the mic** unless you have tested it live first. Meta has no text-to-speech model; Accnomos does not read answers aloud.
- **Cost:** not measured.

### SAM 3.1 (`sam-3.1`)

- **Where:** `services/runtime/app/ai/crop.py` `_call_sam`, key mode, only with `SAM_CROP=1`, to crop a receipt in a messy photo before reading.
- **Default:** a plain-code crop (Pillow, numpy, Otsu) measured on 20 synthetic scenes: mean IoU 0.88 against 0.48 for the full frame (`evals/REPORT_crop_code_20_2026-10-27.md`).
- **Verified:** nothing live. `services/runtime/tests/fixtures/sam_response.json` is marked ILLUSTRATIVE and must be replaced with a captured response before switching it on.
- **Cost (quote, `docs/DEV.md`):** about $2.50 per 1,000 images, two calls when "receipt" finds nothing and "invoice" is tried.

### Muse Image (`muse-image-1.0`)

- **Where:** `tools/brand_muse.py`, at build time only; the script writes concepts to a local folder on the owner's PC, outside the repo. The chosen concepts, composed with the
  headline, are the launcher icon, Play feature graphic and website hero (commit `f39cb2d`); the web copies are `apps/web/public/brand/` (`icon-512.png`, `feature-1024x500.png`, `hero.jpg`). Not in the runtime.
- **Cost:** $0.01 per image (script docstring); 12 images, USD 0.12 in total (commit `f39cb2d`).
- **Honesty line for the video:** "Muse Image made the brand art; it plays no part in the running product."

## Token and cost notes found in the repo

- No token counts are logged or committed. There is no usage dashboard in the repo.
- Per-image quotes only: SAM 3.1 about $2.50 per 1,000 images; Muse Image $0.01 per image. Spark 1.3, Spark Open and Voice have no price recorded.
- Latency (measured, Glimmer on DGX Spark): extraction mean 22.2 s, max 39.8 s over 200 documents; second reading about 7.6 s.

## How the models are kept honest (useful for the "use of Meta models" criterion)

- Models return strict JSON or words only; code does the money. `packages/ledger` never imports model code (`docs/DEV.md`, Conventions).
- Every figure in an Ask answer is checked against a code-built facts pack; an invented figure is replaced by the facts.
- There is **no separate LLM "Reviewer"** stage; the card's "why" line is composed by code (`docs/ARCHITECTURE.md`). Do not describe a reviewer model.
- The signed-out `/vat` mock-up shows a "Reviewer's note (Muse Spark)" that is labelled sample and not backed by any running reviewer (`docs/HONESTY.md`). Avoid it in the video.
