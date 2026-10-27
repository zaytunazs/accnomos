# Task: Voice → Ask (Muse Voice Transcribe) in runtime + web

Accnomos monorepo (public; UK English; no secrets). Read first: `services/runtime/app/{routes_ask.py (if present on main — otherwise
the branch claude/ask-books may not be merged yet: implement `/ask/voice` so it calls the same `answer()` once it exists, with a thin
stub that returns the transcript if `/books/ask` is unavailable)}`, `ai/config.py`, `apps/web/src/app/ask/page.tsx` and components.
Research notes (verify against https://dev.meta.ai docs before coding): `POST https://api.meta.ai/v1/asr/transcribe` multipart with a
`request` JSON part and an `audio` part; WAV mono 16-bit at 16 or 24 kHz; ≤ 32 MB, ≤ 10 min; model `muse-voice-transcribe-1.0`.

## Runtime
- `POST /ask/voice` multipart: `audio` (webm/ogg/m4a/wav from the browser or phone) + optional `period`. Steps: convert to WAV mono
  16 kHz with `ffmpeg` (check availability at startup; if missing, return 503 with a clear message and document it in DEV.md and the
  Dockerfile — add ffmpeg to `deploy/Dockerfile.runtime`), call Muse Voice with the user's Meta key (header `X-Meta-Api-Key`; in
  `local` mode return 400 "voice needs a Meta API key"), then run the Ask pipeline with the transcript. Response adds `transcript`.
- Tests: ffmpeg conversion on a generated 1-second tone (skip if ffmpeg missing), transcribe client with a stubbed HTTP, error mapping.

## Web
- Ask page: a hold-to-talk mic button (MediaRecorder → webm/opus), level indicator, "Transcribing…" state, transcript shown as the
  user's bubble, then the normal answer rendering. Disabled with a tooltip in local-AI mode. No new dependencies. `pnpm run build` passes.
- README row: "Voice ask (Muse Voice Transcribe) — key mode only".

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify (browser mic test).
