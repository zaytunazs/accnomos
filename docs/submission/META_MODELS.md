# Meta models: what is used, where it runs, and what is actually verified

Updated 29 Oct 2026. The first section is the same facts as the public page **/meta-models**
(`apps/web/src/app/meta-models/page.tsx`, data in `apps/web/src/lib/meta-models-page.ts`, figures read from
`evals/runs/*/summary.json` when the site is built); change one, change the other. The page names Meta's models and the
Meta Model API only: no hardware and no other company's tools or engines (a non-Meta fallback is "a local fallback
model"). The engineering detail after it keeps the full names.

## Which Meta model does what (as on /meta-models)

The rule everywhere: AI proposes, the user approves, code calculates. Models return strict JSON or words; code works out
every amount in pence, checks readings (totals, VAT maths and rates, VAT number shape, duplicates, dates) and checks
every figure in a summary or answer against facts built from the books (`KnownNumbers` in `app/ai/ask.py`); nothing is
posted or sent before the user approves.

| Model | Jobs, and where the user sees them | How it is called | What code checks after it | Measured (committed runs) |
|---|---|---|---|---|
| **Muse Spark** (`muse-spark-1.3`) | Reads receipts, invoices, credit notes and emailed bills, suggests the category (Review); the key-mode Verifier when no Spark Open endpoint is set (Review card); CIS statements and reverse-charge invoices (CIS); letting statements, property bills, insurance and mortgage statements (Property); Ask answers and typed or spoken action intents (Ask); words the Home, month-end, spending, cash-flow and day-plan summaries; bank-line coding suggestions (Bank › Reconcile); inbox triage and reply drafts (Home); payment reminder drafts (Invoices); duplicate contacts and same-product items (Contacts, Prices); the website's "Ask about Accnomos" chat | **1st on the live server** (`AI_PROVIDERS=meta,spark`, owner's decision 29 Oct 2026): Meta Model API (`/chat/completions`) with the server's key; or the user's own key in key mode. Data goes only to standard Muse Spark, never to Contributor mode (which lets Meta train on content) | All three checks above | **Not measured yet**: faked HTTP only |
| **Muse Glimmer 30B** (`muse-glimmer:30b`, open weights, run by us) | Every Muse Spark job when the Meta Model API cannot answer; all of them, the Verifier included, in local mode | **Last on the live server**: the local fallback model, on our own server; or the user's own machine in local mode. The code also supports Glimmer on Modal as an optional extra provider (`modal` in `AI_PROVIDERS`); it is not deployed | All three checks above | Documents, every field right: 85 % clean, 80 % messy (200 each, 27 Oct, `glimmer_200_v2`, `glimmer_messy_200_v2`); CIS reader every figure exact 92.5 % (120, 28 Oct, `cis_read`); property reader 89.8 % (108, 28 Oct, `property_docs`); Ask figures 32/32 exact, 0 invented figures reached the user, 3/5 instructions to the right card (35 questions + 5 instructions, 27 Oct, `ask_40`); Autopilot 17 false posts in 467 (3.6 %), all re-fed documents (27 Oct, `autopilot_l2`); triage category 5/5 (12 threads, 27 Oct, `mail_intake`); bank coding **not measured yet** (`evals/harness/bank_ai.py` written, no run committed) |
| **Muse Spark Open** (`meta-models/muse-spark-open`) | The Verifier: an independent second reading with a different prompt and schema that never sees the first answer (Review card: "Verifier agrees" / Needs a look) | Hosted open weights the server owner sets up; first choice for the Verifier in key mode and in the chain; never in local mode | Code compares six fields; a disagreement sends the card to Needs a look and never changes a figure | Reader and Verifier, every field right 91 % clean, 93 % messy; second reading caught 1 and 0 wrong readings, missed 3 and 3, 8 and 3 false alarms (200 each, 27 Oct, `spark_open_200`, `spark_open_messy_200`) |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | Spoken questions and instructions (overtime, quotes, shopping list) on Ask, web and Android mic | Meta Model API (`/asr/transcribe`) first; a local fallback model second; if both fail the user sees why and can type. Audio not kept | The text takes the typed path (figures checked, action cards priced in pence by code, Approve); answer, card and audit log name the service that heard it | **Not measured yet**: faked HTTP in the cookbook's shapes; `evals/harness/stt.py` not run; no live mic run |
| **Segment Anything 3.1** (`sam-3.1`) | Finds and crops the receipt in a phone photo before reading (Review) | Meta Model API (`/responses`), key mode only, only with `SAM_CROP=1`; **off by default**; a plain-code crop otherwise | Crop kept only with a box scoring at least 0.5 that covers enough of the photo; any doubt keeps the original | **Not measured yet** (never run live). The default code crop: mean overlap 0.88 vs 0.48 uncropped (20 synthetic scenes, 27 Oct, `evals/REPORT_crop_code_20_2026-10-27.md`) |
| **Muse Image** (`muse-image-1.0`) | Made the brand artwork (hero illustration, app icon, store graphic), also the demo video's title art and thumbnail; not in the running app | Meta Model API from a build script (`tools/brand_muse.py`) | No figures; images chosen by a person | 12 images, USD 0.12 |

No other Meta model is called (`muse-wonder-1.0` appears nowhere in the code). User data goes only to standard Muse
Spark, not to Contributor mode, under which Meta may train on the content (owner's statement, 29 Oct 2026): the
app's key mode always requests `muse-spark-1.3` (`apps/web/src/lib/ai-config.ts` `DEFAULT_KEY`, no model field in
Settings) and the live server's chain uses `MODEL_API_MODEL`, default `muse-spark-1.3`. How Contributor mode is
switched on at Meta was not checked against Meta's documentation (dev.meta.ai is not reachable from the build sandbox).

Every measured figure is Glimmer's or Spark Open's: Muse Spark, which answers first on the live server, has no
measured figure yet.

## Engineering detail

**Status words:** *measured* = the maintainers ran it for real and a report is committed; *one live call* = run once by hand, no committed log; *unit-tested* = stubbed HTTP in the test suite only; *wired* = in the code path and configured, not yet measured. Nothing is marked measured that has no report.

| Model | Where it runs | What it does in the app | Status | Evidence |
|---|---|---|---|---|
| **Muse Glimmer 30B** (`muse-glimmer:30b`, open weights) | Ollama on our DGX Spark (local mode). "Local" means our hardware: a user's own laptop is not reachable from `api.accnomos.com` | Reads receipts, invoices and credit notes into strict JSON; second-reading Verifier in local mode; Ask answers, chat/voice-action intents, inbox triage, reminder drafts and the planner's rationale (words only, code does the figures) | **Measured.** Extraction with repairs, re-read and Verifier (27 Oct): 200 documents, all fields right 85 % clean and 80 % messy, side 100 %, 18–24 s per document (table below); the earlier run without them scored 88 % messy. Autopilot L2 safety: 467 documents per mode. Ask: 40 prompts, figures exact 32/32, no invented figure reached the user. Triage category 5/5. Verifier: Glimmer checking Glimmer on 20 documents, 17/18 agreed, 0 extra catches | `evals/runs/glimmer_200_v2/report.md`, `evals/runs/glimmer_messy_200_v2/report.md`, `evals/REPORT_glimmer_messy_200_2026-10-27.md`; `evals/runs/autopilot_l2/report.md`, `docs/reviews/autopilot-eval/REVIEW.md`; `evals/runs/ask_40/report.md`; `evals/runs/mail_intake/report.md`; `evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md` |
| **Muse Spark 1.3** (`muse-spark-1.3`) | Meta Model API, with the user's own key (key mode) | Same jobs as Glimmer without a GPU: extraction, Ask, actions, triage; Verifier in key mode when no Baseten key is set | **Unit-tested only.** Never called live by us; no accuracy, latency or cost figure exists | `services/runtime/tests/` (stubbed HTTP); `docs/HONESTY.md` (Models) |
| **Muse Spark Open** (`meta-models/muse-spark-open`) | Baseten (`inference.baseten.co/v1`), key mode; the server owner's `BASETEN_API_KEY` | Independent Verifier: a second reading with a different prompt that never sees the first answer; code compares six fields | **Wired as the key-mode Verifier, one live call (27 Oct 2026):** Baseten's `/v1/models` lists the id, and a real call through the verifier code read a gold receipt correctly in 7 s. Unit-tested. **Measured on all 200 gold documents (reader and Verifier):** all fields right 91 % clean and 93 % messy, side 100 %, about 13 s per document; the Verifier caught 1 wrong reading and raised 11 false alarms over 400 documents (table below) | `services/runtime/app/ai/verify.py` (`DEFAULT_BASETEN_MODEL`); `services/runtime/tests/test_verify.py`; `evals/runs/spark_open_200/report.md`, `evals/runs/spark_open_messy_200/report.md` |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | Meta Model API, the user's key or the server's `META_API_KEY`; Whisper on our DGX Spark is the fallback (`app/ai/stt.py`) | Spoken question or instruction on Ask and in chat actions (overtime, quotes, shopping list): audio to text, then the normal grounded path; the answer, the action card and the audit log say which service heard it. ffmpeg converts to WAV mono 16 kHz first; audio is not kept | **Unit-tested only** with faked HTTP in the shapes from Meta's own cookbook (meta-models/meta-model-cookbook 0a99b98, read 29 Oct 2026); never called live from CI; no live mic run on any browser or phone. `evals/harness/stt.py` compares it with Whisper (WER, numbers, latency) when run on the Spark | `services/runtime/app/ai/stt.py`, `app/ai/voice.py`; `tests/test_stt.py`, `tests/test_voice.py` |
| **SAM 3.1** (`sam-3.1`) | Meta Model API, key mode, only with `SAM_CROP=1` (**off by default**) | Finds and crops the receipt in a messy photo before reading. The default is a plain-code crop (Pillow, numpy, Otsu) | **Unit-tested only; never run live.** The code crop is measured: mean IoU 0.88 against 0.48 for the full frame on 20 synthetic scenes. The SAM fixture is marked ILLUSTRATIVE | `services/runtime/app/ai/crop.py`; `evals/REPORT_crop_code_20_2026-10-27.md` |
| **Muse Image** (`muse-image-1.0`) | Meta Model API, from the owner's PC at build time | Made the brand art (launcher icon, Play feature graphic, website hero). Not in the running product | **Run, build time only.** 12 images, USD 0.12 (commit message of `f39cb2d`) | `tools/brand_muse.py`; `apps/web/public/brand/` |

Not used: `muse-wonder-1.0` is not called anywhere. There is no separate LLM "Reviewer" stage; the card's "why" line is composed by code (`docs/ARCHITECTURE.md`).

## What the table does not say

- **Only Glimmer has numbers.** Every accuracy, latency and safety figure in this repo is Glimmer 30B on the DGX Spark over synthetic documents; real phone photos will score lower. The Ask eval also ran Qwen3.8-27B (vLLM) as a second reader; that is not a Meta model.
- **Autopilot L2 (Glimmer, 467 documents per mode, synthetic):** with the verifier on, 0 false posts on 154 clean documents and 0 on 139 messy renders; 0 on 42 re-photographed or identical receipts (after a same-document rule was added: before it, 21 of 32 re-photographed receipts were posted twice). The overall rate is **17 false posts in 467 (3.6 %)**, all 17 being gold documents already in the books, fed again with a different date, which for a receipt without an invoice number cannot be told from buying the same thing twice. Without those: 0 in 407. Verifier off: the same 17, plus 1 false post on clean documents. It also missed 75 of 200 expected posts (they wait in Review). Times were inflated by other jobs sharing the GPU. `evals/runs/autopilot_l2/report.md`.
- **Why a second model:** the verifier removed one false post on clean documents and cost 16 correct posts (132 against 148). Whether L2 should require it is a product decision recorded in `docs/reviews/autopilot-eval/REVIEW.md`. With `VERIFIER=off` Autopilot can post on a single reading.
- **Costs:** no per-call fee for Glimmer (our hardware; electricity not measured). Quotes only: SAM 3.1 about USD 2.50 per 1,000 images (`docs/DEV.md`); Muse Image USD 0.01 per image. Spark 1.3 and Spark Open have no price recorded; Muse Voice Transcribe about USD 3.00 per 1,000 audio minutes by third-party listings only (no Meta pricing page read, 29 Oct 2026). No token counts are logged.
- **Latency (Glimmer, DGX Spark):** extraction mean 17.7 s clean and 24.1 s messy, max 41.7 s and 111.3 s, over 200 documents each (the earlier run without repairs, re-read or Verifier: mean 22 s, max 40 s); second reading about 7.6 s; Ask median 16 s per question after the routed facts pack.
- **Where the 27 Oct Glimmer runs were served (checked 28 Oct):** `config.base_url` in `evals/runs/glimmer_200_v2/summary.json`
  and `glimmer_messy_200_v2/summary.json` is a Modal endpoint (`…accnomos-glimmer-serve.us-east.modal.run`), not the Spark's
  Ollama; the earlier `glimmer_messy_200` run used `localhost:11434`. So the 17.7 s and 24.1 s means are for Glimmer 30B
  on that Modal endpoint, and "local" in the table means local mode, not our own hardware. The owner should confirm and
  correct the "DGX Spark" wording in `docs/META_MODELS.md` and the README, which this branch does not edit.
- **A known gap:** in key mode with no `X-Meta-Api-Key` header the runtime falls back to the server's `META_API_KEY`, so typed and voice Ask would run on the operator's key. Leave it unset on the public demo.

## How the models are kept honest

- Models return strict JSON or words only; code does the money. `packages/ledger` never imports model code (`docs/DEV.md`).
- Every figure in an Ask answer is checked against a code-built facts pack; an invented figure, or one from the wrong period, is replaced by the facts.
- Chat and voice actions return an intent only; code finds the customer, prices the lines in pence and a signed card waits for Approve (`docs/ACTIONS.md`).
- Do not film the mic, and avoid the signed-out `/vat` mock-up, whose "Reviewer's note (Muse Spark)" is labelled sample and not backed by any running reviewer (`docs/HONESTY.md`).

## Extraction evals, 27 Oct 2026

| Run (200 synthetic gold documents, books owner passed in) | All fields | Net / VAT / gross | Side | Status | Verifier: caught / missed / false alarms | Mean per doc |
|---|---:|---:|---:|---:|---:|---:|
| Spark Open on Baseten, clean (`evals/runs/spark_open_200`) | 91 % | 98 / 98 / 99 % | 100 % | 94 % | 1 / 3 / 8 | 12.9 s |
| Spark Open on Baseten, messy (`evals/runs/spark_open_messy_200`) | 93 % | 99 / 99 / 100 % | 100 % | 97 % | 0 / 3 / 3 | 13.1 s |
| Glimmer 30B local, clean (`evals/runs/glimmer_200_v2`) | 85 % | 98 / 98 / 100 % | 100 % | 88 % | 3 / 2 / 18 | 17.7 s |
| Glimmer 30B local, messy (`evals/runs/glimmer_messy_200_v2`) | 80 % | 97 / 97 / 99 % | 100 % | 83 % | 5 / 2 / 26 | 24.1 s |

All four runs (27 Oct 2026) include the code repairs and the one re-read, with the Verifier on (Spark Open checks Spark Open in key mode; Glimmer checks Glimmer in local mode). *Status* is proposed vs *Needs a look* against the gold expectation, so the Verifier's false alarms count against it: they send a right reading to *Needs a look*, the safe direction. Without the Verifier, status is 98 % in all four runs; with it 94 / 97 / 88 / 83 %. *Missed* means both readings agreed on a wrong figure, which the user still sees on the card before Approve.
