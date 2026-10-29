# Meta models in Accnomos

Everything below was checked against the code on `main` (27 Oct 2026). "Run" means we have run it for real; "unit-tested" means
only stubbed HTTP. Prices are **quotes from our own docs or scripts**, not measurements, unless the cell says "measured".

| Model | Where in the product | Purpose | Cost per unit | Fallback | Status |
|---|---|---|---|---|---|
| **Muse Glimmer 30B** (`muse-glimmer:30b`, open weights, Ollama) | `app/ai/extract.py`, local mode; also the local-mode Verifier, *Ask*, chat-action intents, inbox triage, reminders and planner rationale (all via `ask.call_json_model`) | Reads receipts/invoices into a strict-JSON schema; categorises; writes grounded answers | No per-call fee (our hardware). Measured on a DGX Spark: mean 17.7 s clean and 24.1 s messy per document, max 41.7 s and 111.3 s (200 documents each, 27 Oct, with repairs, re-read and Verifier); the earlier run without them was 22 s mean, 40 s max; the second reading about 7.6 s | Key mode (Muse Spark) | **Run**: 200 clean and 200 messy documents, 60 messy, 20 verified (below) |
| **Muse Spark** (`muse-spark-1.3`, Meta Model API, the user's key) | Key-mode extraction (`/chat/completions`), key-mode *Ask*, key-mode Verifier when no Baseten key | Same jobs as Glimmer, no hardware needed | Not measured; see dev.meta.ai | Local mode (Glimmer) | Unit-tested; **not run in our evals** (no key in the eval environment) |
| **Muse Spark Open** (Baseten, optional) | `app/ai/verify.py`, key mode only, when the server owner sets `BASETEN_API_KEY` | Independent second reading | Not measured | Meta API verifier, or none (`VERIFIER=off`) | Wired on the demo server (Baseten key set 27 Oct 2026; id `meta-models/muse-spark-open`); one real call checked; eval on 200 gold documents: all fields 91 % clean, 93 % messy (`evals/runs/spark_open_200`, `spark_open_messy_200`) |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | `app/ai/stt.py` → `app/ai/voice.py`, `POST /books/ask/voice`; web and Android mic on *Ask* | Spoken question or instruction → text, then the normal grounded *Ask* or action card | Not measured yet (`evals/harness/stt.py`, run on the Spark) | Whisper on the DGX Spark, then a typed question | Faked HTTP in the documented shapes only; **never called live from CI; no live mic run** |
| **SAM 3.1** (`sam-3.1`) | `app/ai/crop.py`, key mode, only with `SAM_CROP=1` | Find and crop the receipt in a phone photo before reading | Quote: about $2.50 per 1,000 images (`docs/DEV.md`) | Code crop (Pillow + Otsu), on by default | **Off by default; never run live.** Request/response shape is unverified |
| **Muse Image** (`muse-image-1.0`) | `tools/brand_muse.py`, build time only | Brand concepts for the launcher icon, feature graphic and site hero | $0.01 per image (script docstring); 12 images, USD 0.12 in total (commit message) | n/a | Run. **Not part of the runtime** |

Not used: `muse-wonder-1.0` (multi-step planning) is not called anywhere. Chat actions (`app/actions.py`) use the user's configured Glimmer or Spark.
There is no separate LLM "Reviewer" stage (see `docs/ARCHITECTURE.md`).

## Speech-to-text: Muse Voice Transcribe first, Whisper on the Spark as fallback

`app/ai/stt.py` is a provider chain for voice in the same style as the text chain below. `STT_PROVIDERS` (default
`muse,whisper`) sets the order; a provider without its settings is left out.

| Order | Provider | Model | Key / URL | Default timeout |
|---|---|---|---|---|
| 1st | Meta Model API, `POST {MODEL_API_BASE}/asr/transcribe` | Muse Voice Transcribe (`muse-voice-transcribe-1.0`) | the user's own `X-Meta-Api-Key` in key mode, else the server's `META_API_KEY` | 45 s (`MUSE_STT_TIMEOUT_S`) |
| 2nd | Whisper on the DGX Spark behind an OpenAI-compatible server, `POST {SPARK_WHISPER_URL}/audio/transcriptions` | `SPARK_WHISPER_MODEL` (default `Systran/faster-whisper-large-v3`) | `SPARK_WHISPER_URL`, optional `SPARK_WHISPER_KEY` | 90 s (`WHISPER_STT_TIMEOUT_S`) |

Any failure of the first (network, timeout, 401/403, 400 over 10 minutes or malformed, 413 over 32 MB, 429, 5xx, a
reply with no words) tries the next; when both fail the user sees Muse's reason and that the fallback failed too. The
answer carries `transcribed_by` (`provider`, `label`, `model`, `fallback_reason`), shown as "Transcribed by Muse Voice
Transcribe" under the spoken question on web and Android. A proposal that came from a spoken request carries the same
`transcribed_by`, covered by its signature, and the actions audit log (`_System/audit/actions/`) records it on the
`approving` and `rejected` lines. Job and staff names from the books are sent as `keywords` (Muse) or a `prompt`
(Whisper) so "Hendon" and "Andy" are spelt right. Keys come only from the request header or the server's environment and
are never logged; audio is converted in a temporary directory deleted at once and passed to each provider in memory.
`/health` lists the chain (`stt`: names, labels, models, configured) without keys or URLs. Test mode has no
speech-to-text, so no e2e run can reach a real service.

**Muse Voice Transcribe as documented** (source: Meta's own cookbook, `meta-models/meta-model-cookbook` commit `0a99b98` (7 Oct 2026), `06_muse_voice/01_voice_api_fundamentals/{utils.py,README.md}`, which links https://dev.meta.ai/docs/speech-to-text and https://dev.meta.ai/docs/api-reference/voice (read 29 Oct 2026; dev.meta.ai and developer.meta.com themselves are not reachable from the build sandbox)):

- One-shot: `POST https://api.meta.ai/v1/asr/transcribe`, `Authorization: Bearer <Model API key>`, multipart with a
  `request` part (JSON: `mode` `PUSH_TO_TALK` | `ENDPOINTING` | `DIARIZATION`, `model`, `audioEncoding: "WAV"`, optional
  `keywords` and `languageBias` lists) and an `audio` part. Reply: `{"sessionId", "transcript", "audioDurationMs",
  "turns": [...]}` (`turns` in the speech modes; `speaker` only with diarization). Errors: 400 (over 10 minutes, or
  malformed), 401, 404, 413 (over 32 MB), 429, 500 (processing budget exceeded).
- Audio: mono 16-bit WAV at 24 kHz (engine-native) or 16 kHz. Limits: 10 minutes or 32 MB per one-shot request,
  whichever comes first; a streaming session up to 60 minutes. 25 languages.
- Streaming: `wss://api.meta.ai/v1/asr/realtime`; the first frame is a JSON handshake carrying the credential
  (`authorization.accessToken`), `mode`, `audioEncoding` (`PCM_16KHZ` | `PCM_24KHZ`), `model`, `partialMode`
  (`CUMULATIVE` | `DELTA`); then raw PCM in binary frames paced at real time (about 80 ms each), `{"type": "endStream"}`
  to finish; events are `type`-tagged (`transcript` partials with `final: true` at the end, `speechStart`, `speaker`,
  `speechEnd`, `speechComplete`, `error`). Close codes: 1008 (no handshake in 10 s, more than 5 s of backlog, or
  slower than real time for 10 s), 1011 (over 60 minutes or server error), 1013 (rate limited). **Not used**: a question
  is recorded whole on the phone or in the browser, so one POST returns sooner than replaying it at real time.
- Price: **not on a Meta page we could read.** Third-party listings give USD 3.00 per 1,000 audio minutes (USD 0.18 an
  hour) for both endpoints (orcarouter.ai/blog/muse-voice-transcribe, openrouter.ai/meta/muse-voice-transcribe-1.0,
  productbuilder.net/models/muse-voice-transcribe-1-0; searched 29 Oct 2026). A 10-second question would be about
  USD 0.0005. Whisper on the Spark has no per-call fee (our hardware).

## The provider chain: who serves each call

With `AI_PROVIDERS=modal,meta,spark` (the production and demo setting, `docs/PRODUCTION.md` section 7) every AI call that
names no backend of its own goes to the first provider that answers. All three are Meta models:

| Order | Provider | Model | Reads images | Strict JSON | Voice | Default timeouts (connect / first token / request) |
|---|---|---|---|---|---|---|
| 1st | Modal (`tools/modal_glimmer.py`, Ollama on an L40S) | Muse Glimmer 30B | yes | yes (`format` schema) | no | 10 / 150 / 240 s (cold start 60-120 s) |
| 2nd | Meta Model API, the server's `META_API_KEY` | Muse Spark (`muse-spark-1.3`) | yes | yes (`json_schema` strict) | yes (Muse Voice Transcribe; see the speech-to-text chain above) | 10 / 90 / 120 s |
| last | DGX Spark, local Ollama | Muse Glimmer 30B | yes | yes | no | 5 / 180 / 200 s |

The Verifier runs on the same chain, with Muse Spark Open on Baseten tried first when `BASETEN_API_KEY` is set. Every
result records who served it (`served_by`: provider, model, latency_ms, fell_back_from) on proposal cards, Verifier
readings, Ask answers and inbox triage; the Review card shows it ("Read by Muse Glimmer 30B (Modal) · 14 s · checked by
…") and links to the app's **/models** page, which shows the chain's live health (`GET /ai/health`), the last 50 calls
(`GET /ai/calls`, in memory only) and the headline numbers of the eval runs below, read from their summary files when
the site is built. A user's own backend (their local agent or their own Meta key) is never replaced by the chain.

## Eval results (synthetic gold set, so real photos will score lower)

| Report | Setup | Result |
|---|---|---|
| [`REPORT_glimmer_messy_60`](../evals/REPORT_glimmer_messy_60_2026-10-27.md) | Glimmer, local, 60 messy renderings | Every field right on 73 % of documents; supplier 100 %, VAT 100 %, total 100 %, date 98 %, net 97 %, VAT number 95 %; proposed vs *Needs a look* decision 80 %. Weak cases: `mixed` (0 of 6), `no_vat_number` (2 of 6), `foreign` (3 of 5) |
| [`REPORT_verifier_glimmer_messy_20`](../evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md) | Glimmer extracts, Glimmer verifies with a different prompt, 20 docs | 17 of 18 verified documents agreed on all six fields; **0 extra errors caught** (the code checks had already caught them); 1 false alarm. Too few documents to measure a catch rate |
| [`REPORT_crop_code_20`](../evals/REPORT_crop_code_20_2026-10-27.md) | Code crop on 20 cluttered synthetic scenes | Mean IoU 0.882 against 0.475 for the full frame; 19 of 20 at IoU ≥ 0.8; the receipt was always inside the box. SAM 3.1 was **not run** |
| [`JUDGE_glimmer_messy_60`](../evals/JUDGE_glimmer_messy_60_2026-10-27.json) | Claude (Haiku, escalating to Sonnet) graded the same 60 | Raw output only, with no write-up: severities none 18, minor 15, major 22, unparsed 4. It also flags missing detail such as addresses and line text, so it is stricter than the field table above. Treat it as an unreviewed artefact |
| [`REPORT_glimmer_messy_200`](../evals/REPORT_glimmer_messy_200_2026-10-27.md) + [`JUDGE_glimmer_messy_200`](../evals/JUDGE_glimmer_messy_200_2026-10-27.json) | Glimmer, local, 200 messy renderings; Claude judge (Haiku, escalating to Sonnet, 4,000-token cap) | Earlier run, without the code repairs, the re-read or the Verifier: every field right on 88 %; side 100 %; status 93 %. The run with all three on is in the table below. Judge: 0 unparsed, agrees with the code score on 79/200 (167/200 counting `minor` as right) |
| [`runs/ask_40`](../evals/runs/ask_40/report.md) | Ask, 40 prompts over the seeded books, Glimmer (local) and Qwen3.8-27B (vLLM) | Numbers exact 32/32 on both (28/32 and 31/32 before the routed facts pack); citations 32/32; no invented figure shown; instructions → right action card 3/5 (Glimmer) and 4/5 (Qwen); Glimmer 0 timeouts (4 before) |
| [`runs/mail_intake`](../evals/runs/mail_intake/report.md) | Outlook intake (code) and triage (Glimmer) on 20 mailbox fixtures | 12/17 documents kept, 11/11 decoys dropped; triage filter 13/13, category 5/5 |
| [`runs/bank_matching`](../evals/runs/bank_matching/report.md) | Matcher (code) on six two-month statements | Precision 83/83, recall 83/106 (part payments unsupported) |

Reproduce: `cd evals && python -m harness.run_extraction --mode local --messy`, see `docs/DEV.md`. Feature evals: `python -m harness.bank_match`, `python -m harness.mail_intake`, `python -m harness.ask_40`, judge `python -m harness.judge runs/glimmer_messy_200 --escalate claude-sonnet-5-5`. Offline checks: `python -m pytest -q tests`.

### Extraction evals with repairs, re-read and Verifier on (27 Oct 2026)

200 synthetic gold documents each, books owner passed in; the full table, with the Verifier's caught / missed / false-alarm counts, is in `docs/submission/META_MODELS.md`.

| Run | All fields | Side | Status | Mean per doc |
|---|---:|---:|---:|---:|
| Spark Open on Baseten, clean (`evals/runs/spark_open_200`) | 91 % | 100 % | 94 % | 12.9 s |
| Spark Open on Baseten, messy (`evals/runs/spark_open_messy_200`) | 93 % | 100 % | 97 % | 13.1 s |
| Glimmer 30B local, clean (`evals/runs/glimmer_200_v2`) | 85 % | 100 % | 88 % | 17.7 s |
| Glimmer 30B local, messy (`evals/runs/glimmer_messy_200_v2`) | 80 % | 100 % | 83 % | 24.1 s |

The Verifier's false alarms count against status (without it, status is 98 % in all four runs). Only the 200-document Glimmer and Spark Open runs are current; the 88 % row above is the earlier Glimmer run.
