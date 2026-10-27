# Review: `claude/voice-ask` (Voice → Ask with Muse Voice Transcribe)

Second-agent review of the implementation of `TASK_BRIEF.md`. A spoken question goes through ffmpeg to WAV mono 16 kHz, then to Muse Voice Transcribe with the user's Meta key, then through the same grounded Ask as a typed question.

## What was checked

- **Tests, all green after the fixes:**
  - `services/runtime`: 124 passed (121 before, plus 3 new tests). Run with ffmpeg present, so the conversion tests ran and were not skipped.
  - `packages/ledger` and `packages/connectors`: 32 passed. The branch doesn't touch them.
  - `services/hmrc-relay`: not run, because the branch doesn't touch it.
  - `apps/web`: `pnpm run build` compiles and prerenders all 14 routes.
- **Runtime diff** (`app/ai/voice.py`, `routes_ask.py`, `schemas.py`, `main.py`):
  - The route is `POST /books/ask/voice`, next to the existing `POST /books/ask`. The brief says `/ask/voice`, but every Ask route sits under `/books`.
  - Local mode gets 400 "voice needs a Meta API key" before any audio is read.
  - ffmpeg is checked at startup: a warning is logged and `/health` reports `"voice": false`. Each request checks again, so a missing ffmpeg gives 503 with a pointer to `docs/DEV.md`.
  - Size limits: an empty upload is 400; over 32 MB is 413, checked before ffmpeg runs and with the read capped at 32 MB + 1; over 10 minutes is 413; under 0.2 s is 422. The ffmpeg conversion times out after 60 s.
  - The transcript goes through the same `_answer()` as typed questions, so it gets the same facts pack and figure and citation checks. A transcript over the 500-character `AskRequest` limit is a clear 422.
  - Audio is only written inside a `TemporaryDirectory` that is removed after the conversion. Nothing is stored in the user's storage or on the server. Starlette's own upload spooling is also temporary.
  - Muse Voice errors map as follows: 401/403 → 401, 413 → 413, 429 → 429, other 4xx/5xx → 502, a network error → 502, a response that isn't JSON → 502, an empty transcript → 422.
  - The client's request URL (`{base}/asr/transcribe`), Bearer key and multipart parts (`request` JSON + `audio`) are tested on stubbed HTTP.
- **Web diff** (`MicButton.tsx`, `AskThread.tsx`, `runtime.ts`):
  - Hold-to-talk uses pointer capture and also works with Space/Enter. Releasing while the permission prompt is open stops the stream.
  - Recording uses MediaRecorder, preferring webm/opus, with an RMS level meter. Recordings are capped at 60 s, and anything under 400 ms counts as a tap.
  - While a question is transcribed, a "Transcribing…" bubble shows. The transcript then replaces it as the user's bubble, and the normal `AnswerCard` follows.
  - The mic is disabled with a reason outside key mode, when `/health` says there is no ffmpeg, while an answer is pending and when signed out.
  - `call()` now sets JSON Content-Type only for string bodies, so FormData keeps its multipart boundary.
  - No new dependencies.
- **Docs:**
  - README row: accurate. It says plainly that the Muse Voice wire format comes from research notes and that a live mic run is pending.
  - `docs/DEV.md`: the ffmpeg section matches the code.
  - `deploy/Dockerfile.runtime`: already installed ffmpeg on main; the branch adds a comment saying why.
- **Product rules:**
  - No user database and no audio kept.
  - Meta models do the runtime work: Muse Voice, then the configured Muse model for the answer.
  - Code still checks every figure.
  - UK English throughout.

## What I fixed

- `39e34ec` fixes a flaky test in `test_autopilot.py`, which came from main and is not caused by this branch. Ledger event paths sort by a one-second timestamp and then a random uuid. Two events posted in the same second could therefore swap, and `_events(fake)[-1]` then picked the wrong one. The full suite failed about half the time. The test now finds the event by `p.event_id`.
- `a949eca`:
  - ffmpeg's error line is shown to the user with the server's temp path replaced by `input`. ffmpeg 5.x, which ships in the Debian-based image, prints `<path>: Invalid data…` as the last line.
  - The ffmpeg startup check in `main.py` was sitting between two router imports. It now comes after the routers.
- `e96a1be`: the mic's "why disabled" text is now also on the wrapper. Some browsers don't show the `title` of a disabled `<button>`, and the brief asks for a tooltip in local-AI mode.
- `ad2f257` adds tests for three things:
  - no files are left in the temp directory after a good conversion or a failed one, and the temp path is not in the error;
  - `/health` reports `voice` from the startup check;
  - an overlong transcript gives 422 with a clear message.

## What remains

- **The Muse Voice wire format has not been checked against https://dev.meta.ai.** This covers the endpoint `/asr/transcribe`, the `request` + `audio` multipart parts, `{"model": "muse-voice-transcribe-1.0"}` and the response field holding the text (`text`, `transcript` or `results[]`/`segments[]` are all accepted). Everything here comes from the research notes and is confined to `transcribe()` in `app/ai/voice.py`. A live call with a real key is needed.
- **No live browser mic run yet.** Chrome/Edge (webm/opus), Firefox (ogg/opus) and Safari/iOS (mp4) all need a test. The Safari mp4 → m4a path is only covered in principle; ffmpeg reads it from a temp file because the moov atom can come last.
- The temp-path test passes on this machine's ffmpeg with or without the fix, because this version doesn't print the path. It guards against a regression but doesn't prove the fix here.
- Behaviour from main, unchanged: in key mode with no `X-Meta-Api-Key` header, `AiConfig` falls back to the server's `META_API_KEY` env var, so voice would then use the operator's key rather than the user's. This is the same as typed Ask.
- Error text in the thread is the raw `runtime POST … -> 4xx: {"detail": …}` string, the same as typed Ask. A friendlier mapping of `detail` would help both.
- The web app always sends `period: null` for voice, as typed Ask does. The runtime accepts a period, but the UI has no picker yet.
- `TASK_BRIEF.md` was overwritten by the WIP commit `0e4baa2`, replacing the Autopilot brief with this one. That is expected for the lane, but it should not be merged as if it were a doc.

## How to verify by hand

1. Install ffmpeg and start the runtime.
2. Open `GET /health` and check that it shows `"voice": true`.
3. In the web app, go to Settings and set the AI to key mode with a real Meta API key. Open `/ask`.
4. Hold the mic button. The level bars should move while you speak.
5. Say "How much VAT do I owe this quarter?" and release. A "Transcribing…" bubble should appear and then be replaced by your words, followed by an answer card whose figures match `/vat`. A tap under half a second should give the "Hold the mic button…" hint.
6. Repeat in Firefox and on an iPhone in Safari.
7. Switch to local AI. The mic should be greyed out, and hovering over it should explain that voice needs a Meta API key.
8. Stop the runtime, remove ffmpeg from `PATH` and restart it. `/health` should say `"voice": false` and the mic should explain that ffmpeg is missing.
9. If the live transcribe call fails with 502, compare the request and response with the dev.meta.ai docs and adjust `transcribe()` only.
