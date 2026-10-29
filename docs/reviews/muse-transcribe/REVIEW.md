# Review: Muse Voice Transcribe first, Whisper on the Spark as fallback (`claude/muse-transcribe`)

Branch from `origin/main` (`c353bd4`). No push to main, no PR. Meta's API, Baseten and Modal were not called from here.

## What the brief assumed, and what was there

- The brief says voice "today is transcribed by Whisper on the owner's Spark voice server". **It was not.** `git grep -i
  'whisper\|transcri\|audio/transcriptions'` over `services`, `apps` and every `origin/*` branch found no Whisper client:
  `POST /books/ask/voice` already called Muse Voice Transcribe (`app/ai/voice.py`), key mode only, with a request shape
  taken from research notes. So this branch (a) corrects the Muse request to the documented shape, (b) adds the
  Whisper client as an OpenAI-compatible `/audio/transcriptions` call configured by `SPARK_WHISPER_URL` (empty = off),
  and (c) puts both behind a chain. Whether the Spark actually serves Whisper, and under which model id, is for the
  owner to set up; `docs/HONESTY.md` says so.
- The brief points at a Spark Kokoro endpoint "described in docs". No doc describes it (only the teaser's credits name
  Kokoro, voice `bm_george`). `harness/stt.py --generate` uses Kokoro-FastAPI's OpenAI-compatible
  `POST /v1/audio/speech`, base `KOKORO_URL` (default `http://127.0.0.1:8880/v1`).

## Sources (read 29 Oct 2026)

| What | Source | Notes |
|---|---|---|
| Endpoint, auth, multipart parts, request JSON (`mode`, `model`, `audioEncoding: "WAV"`, `keywords`, `languageBias`), response (`sessionId`, `transcript`, `audioDurationMs`, `turns`), error codes, audio formats (mono 16-bit WAV, 16 or 24 kHz), limits (10 min or 32 MB one-shot; 60 min streaming), streaming handshake, events and close codes | Meta's cookbook `meta-models/meta-model-cookbook`, commit `0a99b98` (7 Oct 2026), `06_muse_voice/README.md`, `06_muse_voice/01_voice_api_fundamentals/{README.md,utils.py,transcribe_file.py}` | Official (Meta's own repo; it links https://dev.meta.ai/docs/speech-to-text and https://dev.meta.ai/docs/api-reference/voice). **dev.meta.ai and developer.meta.com do not resolve from this sandbox**, so the pages the brief names (https://dev.meta.ai/docs/overview, https://dev.meta.ai/docs/models, https://developer.meta.com/ai/resources/blog/meet-muse-voice-transcribe-streaming-speech-to-text/) could not be read directly; search snippets of them agree on the base URL, the two endpoints and the WebSocket auth-in-handshake. |
| Price, USD 3.00 per 1,000 audio minutes (USD 0.18 an hour), same for streaming and file | orcarouter.ai/blog/muse-voice-transcribe, openrouter.ai/meta/muse-voice-transcribe-1.0, productbuilder.net/models/muse-voice-transcribe-1-0 (web search) | **Third party only**; no Meta pricing page was readable. Recorded as such in `docs/META_MODELS.md`. |
| Whisper request (`file`, `model`, `language`, `prompt`, `response_format=json` → `{"text"}`) | OpenAI audio API reference, https://platform.openai.com/docs/api-reference/audio/createTranscription | The shape faster-whisper-server / speaches implement; from knowledge, not re-fetched. |

## Design

- **`app/ai/stt.py`**: providers `muse` and `whisper`, order from `STT_PROVIDERS` (default `muse,whisper`), each left
  out when unconfigured, like `app/ai/providers.py`. Muse's key: the user's own `X-Meta-Api-Key` in key mode, else the
  server chain's `meta` provider, else `META_API_KEY`. `transcribe()` tries each in order and falls over on **any**
  `VoiceError` (network, timeout, 401/403, 400, 413, 429, 5xx, no words). Both failing raises Muse's status and reason
  plus "the fallback failed too: …". Timeouts `MUSE_STT_TIMEOUT_S` (45 s) and `WHISPER_STT_TIMEOUT_S` (90 s). Test mode
  returns no providers, so no e2e run can reach a real service.
- **`app/ai/voice.py`**: the Muse client now sends `{"mode": "PUSH_TO_TALK", "model", "audioEncoding": "WAV",
  "languageBias": ["english"], "keywords"?}`, reads `transcript` first (keeps `text`, `turns`, `results`, `segments`
  for tolerance), maps 400 to 422 and a timeout to 504. The realtime WebSocket is documented but not used: a question
  is recorded whole, so one POST is quicker than replaying it at real time (the server closes a session that is sent
  faster than 5 s ahead).
- **Provenance**: `schemas.Transcription {provider, label, model, fallback_reason}`. `AskVoiceAnswer.transcribed_by`;
  `ProposedAction.transcribed_by` (re-signed after it is set, so it cannot be changed before Approve; left out of the
  signed payload when None, so typed proposals sign exactly as before); `actions._claim` and `actions.reject` write it
  to `_System/audit/actions/<yyyy-mm>.jsonl`. `/health` gains `stt` (names, labels, models, configured; no keys, no URLs).
- **Keywords**: job and staff names from the books (best effort, read in parallel with the ffmpeg step) go to Muse as
  `keywords` and to Whisper as a `prompt`, so "Hendon" and "Andy" are spelt as in the books.
- **Keys and audio**: keys only from the request header or env; held in `SttProvider.key` (`repr=False`), never in an
  error message, log line, answer, audit line or eval output (tested). Audio: unchanged; ffmpeg runs in a temporary
  directory deleted at once, and the WAV bytes go to each provider in memory.
- **Web** (`AskThread.tsx`, `ActionCard.tsx`, `runtime.ts`): "Transcribed by Muse Voice Transcribe" under a spoken
  question; "Spoken request · transcribed by … (kept in the audit log)" on its action card. The mic is now enabled in
  local mode when `/health.stt` lists a configured provider. Capture is unchanged.
- **Android** (`ask_screen.dart`, `runtime_client.dart`): `VoiceAnswer.transcribedBy`; the "Spoken" label reads
  "Spoken · Transcribed by …" (`SpokenTag`); mic gating moved into `voiceOffReason()` with the same rule as the web.
- **Eval** (`evals/harness/stt.py`, step `stt` last in `tools/spark_queue.sh`, probe `none`): each provider alone over
  the 14 teaser VO WAVs and 20 UK accounting utterances (`UTTERANCES`, incl. the overtime and bolts sentences and a
  £450 quote) made by Kokoro into `evals/gold/voice/` when `--generate` is given. Scores WER after normalising (£ →
  "pounds", number words → digits), whether every number and every pound amount was heard, and latency mean / p50 /
  p95. `--stub` and `--dry-run` work offline. **Not run**: needs the Spark and a key.

## Tests

| Where | New / changed | Result here |
|---|---|---|
| `services/runtime/tests/test_stt.py` | 27 new: chain config (user key, server key in local mode, server chain, order and timeouts from env, test mode empty, no key in repr/describe), Muse-first, Whisper after each of 8 Muse failures (500, 429, 413, 400, 401, timeout, connect error, no words), Whisper request shape with and without a key, both failing, single provider, none, **no key in logs (DEBUG incl. httpx) / errors / results**; route: spoken overtime "Andy did 2 hours overtime at double time on the Hendon job last week" heard by Muse → signed `pay_overtime` card with `transcribed_by`, tampering refused (403), approve writes it to the audit; Muse 503 → Whisper with the server key in local mode → card says Whisper, reject audits it; typed proposals sign as before; no provider = 400; `/health.stt` without secrets | pass |
| `services/runtime/tests/test_voice.py` | documented request JSON asserted exactly; keywords only when given; `turns` reply shape; 400 → 422; route returns `transcribed_by`; local-mode message | 28 pass |
| `services/runtime/tests/test_shopping.py` | the bolts-for-Hendon voice test's fake accepts the new keyword args | pass |
| `services/runtime/tests/test_security_routes.py` | `ai/stt.py` added to the modules allowed to make HTTP calls (bases: user cfg / `MODEL_API_BASE` / `SPARK_WHISPER_URL`) | pass |
| `evals/tests/test_stt_harness.py` | 14 new: normalising (7 cases), scoring, the 20 utterances, Kokoro generator against a fake (and resumable, and Kokoro down), providers from env, a stubbed run of both writing the report without the key, dry run | pass |
| `evals/tests/test_spark_queue.py` | `stt` is the 7th step; with Qwen and Ollama down only `stt` runs | pass |
| `apps/mobile/test/voice_provider_test.dart` | 3 new: `VoiceAnswer.transcribedBy`, `SpokenTag` widget, `voiceOffReason` | **not run: no Flutter SDK in this sandbox** |

Gates, all from this branch: runtime `pytest -q` 2,390 passed, 2 skipped; `ruff check .` and `ruff format --check .` clean;
`pyright services/runtime/app` 0 errors; evals `pytest -q tests` 368 passed; web `pnpm install --frozen-lockfile`,
`eslint .` clean, `e2e:build` built, `e2e:test` 469 passed, 94 skipped, 8 failed on the first full run, then all 8 (10 tests in their files) passed on
re-run. The sandbox's browsers are older than the ones `@playwright/test` pins, so e2e ran with a local, uncommitted
config that only sets `launchOptions.executablePath`. The full run used `/opt/pw-browsers/chromium`, whose built-in PDF
viewer fetches a `chrome-extension://` stylesheet on invoice and quote previews, which the suite's "nothing leaves
127.0.0.1" guard rejects (6 failures). The other two were a Tab-order check on `/vat` and a 30 s timeout over 15 pages
on a loaded machine. Re-run with the headless shell (`/opt/pw-browsers/chromium_headless_shell-1243`), the binary
Playwright itself uses: all passed. None of the 8 touches a file this branch changed. No e2e covers voice (test mode has no speech-to-text, and there is no mic in CI).

## Risks

- **Live shapes unverified.** Built against Meta's cookbook, not a live call. If the server wants another
  `languageBias` value than `"english"` it ignores it silently (per the cookbook), so the risk is a weaker bias, not an
  error. The first owner run of `tools/spark_queue.sh --only stt` with a key will show it.
- **Server key in local mode.** By design, `META_API_KEY` now also transcribes voice for local-mode users. On a public
  server, leave it unset if strangers' audio should not run on the operator's account (HONESTY.md).
- **Whisper server unknown.** The client assumes an OpenAI-compatible server; a different server (e.g. whisper.cpp's
  `/inference`) would fail and be reported as "Whisper on the Spark returned HTTP 404".
- **Provenance after a clarification** is lost when the follow-up is typed or tapped (HONESTY.md).
- **Eval numbers are synthetic-speech numbers** (Kokoro, one clean voice); real phone audio in a van will be worse.
- Dart changes are unanalysed and untested here.
