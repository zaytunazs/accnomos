# AI models in Accnomos

Everything below was checked against the code on `main` (27 Oct 2026). **Since 11 Nov 2026** the live server's chain is
`AI_PROVIDERS=spark,anthropic` (the local open-weights model on our own server first, Anthropic's API as the backup) and
voice is transcribed on our own server by default (`STT_PROVIDER=local`); the hosted model and the hosted speech-to-text
model are used only with a user's own API key, or when the server owner puts them back in the chain. "Run" means we have run it for real; "unit-tested" means
only stubbed HTTP. Prices are **quotes from our own docs or scripts**, not measurements, unless the cell says "measured".

| Model | Where in the product | Purpose | Cost per unit | Fallback | Status |
|---|---|---|---|---|---|
| **The local open-weights model** (open weights, on a local model server) | `app/ai/extract.py`, local mode; also the local-mode Verifier, *Ask*, chat-action intents, inbox triage, reminders and planner rationale (all via `ask.call_json_model`) | Reads receipts/invoices into a strict-JSON schema; categorises; writes grounded answers | No per-call fee (our hardware). Measured on our own server: mean 17.7 s clean and 24.1 s messy per document, max 41.7 s and 111.3 s (200 documents each, 27 Oct, with repairs, re-read and Verifier); the earlier run without them was 22 s mean, 40 s max; the second reading about 7.6 s | Key mode (the hosted model) | **Run**: 200 clean and 200 messy documents, 60 messy, 20 verified (below) |
| **The hosted model** (Contributor tier on the live server, first in its chain until 11 Nov 2026; standard tier with the user's key) | Extraction (`/chat/completions`), *Ask*, summaries, the server-chain and key-mode Verifier (the open-weights host is off) | Same jobs as the local open-weights model, no hardware needed | Not measured; see the provider's price list | The local open-weights model (the chain's next provider; local mode) | **Measured** (Contributor, 4 Nov 2026): all fields 95 % clean, 96 % messy on 200 synthetic documents each (`evals/runs/spark13_200`, `spark13_messy_200`); document type 96.5 % (`evals/runs/classify`); Ask, voice Ask, Home summary, goals note and a scan run live (`evals/runs/live_checks_2026-11-04/report.md`) |
| **The open-weights verifier model** (hosted open weights, optional, **off since 2 Nov 2026**) | `app/ai/verify.py`, only when the server owner sets `BASETEN_ENABLED=1` and `BASETEN_API_KEY` | Independent second reading | Not measured | The hosted model's API verifier, or none (`VERIFIER=off`) | Wired on the demo server (hosted-verifier key set 27 Oct 2026); one real call checked; eval on 200 gold documents: all fields 91 % clean, 93 % messy (`evals/runs/spark_open_200`, `spark_open_messy_200`) |
| **The speech-to-text model** (hosted) | `app/ai/stt.py` → `app/ai/voice.py`, `POST /books/ask/voice`; web and Android mic on *Ask* | Spoken question or instruction → text, then the normal grounded *Ask* or action card | Not measured | A local speech-to-text model on our own server, then a typed question | **Measured** on 14 synthetic clips (word error rate 12.7 %, `evals/runs/stt`); **used live** from the Android app on the owner's phone and on the live server (4 Nov 2026, `evals/runs/live_checks_2026-11-04/report.md`); not from CI |
| **The receipt-crop image model** | `app/ai/crop.py`, only with `SAM_CROP=1`: the user's key, else the server chain's hosted-model provider; not under the local-first / local-only routes | Find and crop the receipt in a phone photo before reading | Quote: about $2.50 per 1,000 images (`docs/DEV.md`) | Code crop (Pillow + Otsu) when the receipt-crop image model fails, times out or is unsure | **Run live** (4 Nov 2026) on 20 synthetic scenes: a box 20/20, mean IoU 0.90 against 0.88 for the code crop, median 1.5 s, reading 19/20 with either crop (`evals/runs/sam_crop_live/report.md`). Wire format per the provider's documentation; `SAM_CROP=1` set on the live server from its next deploy |
| **An image-generation model** | `tools/brand_muse.py`, build time only | Brand concepts for the launcher icon, feature graphic and site hero | $0.01 per image (script docstring); 12 images, USD 0.12 in total (commit message) | n/a | Run. **Not part of the runtime** |

Not used: the provider's multi-step planning model is not called anywhere. Chat actions (`app/actions.py`) use the user's configured local open-weights model or hosted model.
There is no separate LLM "Reviewer" stage (see `docs/ARCHITECTURE.md`).

## Speech-to-text: the hosted speech-to-text model first, a local speech-to-text model on our own server as fallback

`app/ai/stt.py` is a provider chain for voice in the same style as the text chain below. `STT_PROVIDERS` (default
`muse,whisper`) sets the order; a provider without its settings is left out.

| Order | Provider | Model | Key / URL | Default timeout |
|---|---|---|---|---|
| 1st | The hosted model's API, `POST {MODEL_API_BASE}/asr/transcribe` | The hosted speech-to-text model | the user's own `X-Meta-Api-Key` in key mode, else the server's `META_API_KEY` | 45 s (`MUSE_STT_TIMEOUT_S`) |
| 2nd | A local speech-to-text model on our own server behind a standard-API server, `POST {SPARK_WHISPER_URL}/audio/transcriptions` | `SPARK_WHISPER_MODEL` (default: the runtime's built-in local speech model id) | `SPARK_WHISPER_URL`, optional `SPARK_WHISPER_KEY` | 90 s (`WHISPER_STT_TIMEOUT_S`) |

Any failure of the first (network, timeout, 401/403, 400 over 10 minutes or malformed, 413 over 32 MB, 429, 5xx, a
reply with no words) tries the next; when both fail the user sees the model's reason and that the fallback failed too. The
answer carries `transcribed_by` (`provider`, `label`, `model`, `fallback_reason`), shown as "Transcribed by the speech-to-text model" under the spoken question on web and Android. A proposal that came from a spoken request carries the same
`transcribed_by`, covered by its signature, and the actions audit log (`_System/audit/actions/`) records it on the
`approving` and `rejected` lines. Job and staff names from the books are sent as `keywords` (the model) or a `prompt`
(the local speech-to-text model) so "Hendon" and "Andy" are spelt right. Keys come only from the request header or the server's environment and
are never logged; audio is converted in a temporary directory deleted at once and passed to each provider in memory.
`/health` lists the chain (`stt`: names, labels, models, configured) without keys or URLs. Test mode has no
speech-to-text, so no e2e run can reach a real service.

**Wire format.** The hosted speech-to-text endpoint's request and reply shapes, limits and error codes are recorded in
`services/runtime/app/ai/voice.py`, as documented by its provider (read 29 Oct 2026). Streaming is **not used**: a
question is recorded whole on the phone or in the browser, so one POST returns sooner than replaying it at real time.
Price: not on a provider page we could read; third-party listings gave USD 3.00 per 1,000 audio minutes (searched
29 Oct 2026), about USD 0.0005 for a 10-second question. The local speech-to-text model on our own server has no
per-call fee (our hardware).

## The provider chain: who serves each call

With `AI_PROVIDERS=modal,meta,spark` (the production and demo setting until 11 Nov 2026; `docs/PRODUCTION.md` section 7 has the current one) every AI call that
names no backend of its own goes to the first provider that answers. All three serve the models above:

| Order | Provider | Model | Reads images | Strict JSON | Voice | Default timeouts (connect / first token / request) |
|---|---|---|---|---|---|---|
| 1st | Hosted GPU (`tools/modal_glimmer.py`) | The local open-weights model | yes | yes (`format` schema) | no | 10 / 150 / 240 s (cold start 60-120 s) |
| 2nd | The hosted model's API, the server's `META_API_KEY` | The hosted model | yes | yes (`json_schema` strict) | yes (the speech-to-text model; see the speech-to-text chain above) | 10 / 90 / 120 s |
| last | Our own server, local model runtime | The local open-weights model | yes | yes | no | 5 / 180 / 200 s |

The Verifier runs on the same chain. The open-weights verifier model (hosted open weights) is tried first only when `BASETEN_ENABLED=1` and `BASETEN_API_KEY` are both set; it is off on the live server since 2 Nov 2026 (the open-weights verifier model results below are earlier runs). Every
result records who served it (`served_by`: provider, model, latency_ms, fell_back_from) on proposal cards, Verifier
readings, Ask answers and inbox triage; the Review card shows it ("Read by the local open-weights model (hosted GPU) · 14 s · checked by
…") and links to the app's **/models** page, which shows the chain's live health (`GET /ai/health`), the last 50 calls
(`GET /ai/calls`, in memory only) and the headline numbers of the eval runs below, read from their summary files when
the site is built. A user's own backend (their local agent or their own API key for the hosted model) is never replaced by the chain.

## Eval results (synthetic gold set, so real photos will score lower)

| Report | Setup | Result |
|---|---|---|
| [`REPORT_glimmer_messy_60`](../evals/REPORT_glimmer_messy_60_2026-10-27.md) | The local open-weights model, local, 60 messy renderings | Every field right on 73 % of documents; supplier 100 %, VAT 100 %, total 100 %, date 98 %, net 97 %, VAT number 95 %; proposed vs *Needs a look* decision 80 %. Weak cases: `mixed` (0 of 6), `no_vat_number` (2 of 6), `foreign` (3 of 5) |
| [`REPORT_verifier_glimmer_messy_20`](../evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md) | The local open-weights model extracts, the local open-weights model verifies with a different prompt, 20 docs | 17 of 18 verified documents agreed on all six fields; **0 extra errors caught** (the code checks had already caught them); 1 false alarm. Too few documents to measure a catch rate |
| [`REPORT_crop_code_20`](../evals/REPORT_crop_code_20_2026-10-27.md) | Code crop on 20 cluttered synthetic scenes | Mean IoU 0.882 against 0.475 for the full frame; 19 of 20 at IoU ≥ 0.8; the receipt was always inside the box. The receipt-crop image model was **not run** |
| [`JUDGE_glimmer_messy_60`](../evals/JUDGE_glimmer_messy_60_2026-10-27.json) | An AI judge (a smaller model escalating to a larger one) graded the same 60 | Raw output only, with no write-up: severities none 18, minor 15, major 22, unparsed 4. It also flags missing detail such as addresses and line text, so it is stricter than the field table above. Treat it as an unreviewed artefact |
| [`REPORT_glimmer_messy_200`](../evals/REPORT_glimmer_messy_200_2026-10-27.md) + [`JUDGE_glimmer_messy_200`](../evals/JUDGE_glimmer_messy_200_2026-10-27.json) | The local open-weights model, local, 200 messy renderings; AI judge (a smaller model escalating to a larger one, 4,000-token cap) | Earlier run, without the code repairs, the re-read or the Verifier: every field right on 88 %; side 100 %; status 93 %. The run with all three on is in the table below. Judge: 0 unparsed, agrees with the code score on 79/200 (167/200 counting `minor` as right) |
| [`runs/ask_40`](../evals/runs/ask_40/report.md) | Ask, 40 prompts over the seeded books, the local open-weights model (local) and a second open-weight model (a different model family) | Numbers exact 32/32 on both (28/32 and 31/32 before the routed facts pack); citations 32/32; no invented figure shown; instructions → right action card 3/5 (the local open-weights model) and 4/5 (the second model); the local open-weights model 0 timeouts (4 before) |
| [`runs/mail_intake`](../evals/runs/mail_intake/report.md) | Outlook intake (code) and triage (the local open-weights model) on 20 mailbox fixtures | 12/17 documents kept, 11/11 decoys dropped; triage filter 13/13, category 5/5 |
| [`runs/bank_matching`](../evals/runs/bank_matching/report.md) | Matcher (code) on six two-month statements | Precision 83/83, recall 83/106 (part payments unsupported) |

Reproduce: `cd evals && python -m harness.run_extraction --mode local --messy`, see `docs/DEV.md`. Feature evals: `python -m harness.bank_match`, `python -m harness.mail_intake`, `python -m harness.ask_40`, judge `python -m harness.judge runs/glimmer_messy_200 --escalate <judge-model>`. Offline checks: `python -m pytest -q tests`.

### Extraction evals with repairs, re-read and Verifier on (27 Oct 2026)

200 synthetic gold documents each, books owner passed in; the full table, with the Verifier's caught / missed / false-alarm counts, is in `docs/AI_MODELS.md`.

| Run | All fields | Side | Status | Mean per doc |
|---|---:|---:|---:|---:|
| The open-weights verifier model (hosted), clean (`evals/runs/spark_open_200`) | 91 % | 100 % | 94 % | 12.9 s |
| The open-weights verifier model (hosted), messy (`evals/runs/spark_open_messy_200`) | 93 % | 100 % | 97 % | 13.1 s |
| The local open-weights model, clean (`evals/runs/glimmer_200_v2`) | 85 % | 100 % | 88 % | 17.7 s |
| The local open-weights model, messy (`evals/runs/glimmer_messy_200_v2`) | 80 % | 100 % | 83 % | 24.1 s |

The Verifier's false alarms count against status (without it, status is 98 % in all four runs). Only the 200-document local open-weights model and open-weights verifier model runs are current; the 88 % row above is the earlier local open-weights model run.
