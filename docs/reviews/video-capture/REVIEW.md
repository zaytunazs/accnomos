# Review: video capture, previews and how-to screenshots (`claude/video-capture`)

Written 29 Oct 2026 by the session that built it, for the integrator. Merges `muse/video-scripts` (Muse Spark's
`docs/video/JUDGES_VIDEO.md`, `docs/video/CLIPS.md` and the ten `docs/howto/*.md` guides) unchanged apart from the
how-to placeholders, which now point at real screenshots.

## What it adds

| Path | What |
|---|---|
| `tools/video/capture.ts` | Starts the test-mode runtime (`DEMO_MODE=1`) and static server, builds with `NEXT_PUBLIC_SUBMISSION_MODE=1`, records each shot via CDP screencast (1920 × 1080 / 1080 × 1920, 30 fps VP9), writes `docs/video/manifest.json` and contact sheets |
| `tools/video/flows.ts` | 46 scripted flows (review, approve, VAT, simulated HMRC, Ask, month-end, Files, payroll, CIS, …), `SHOT_PLAN` (flow per shot id and why a shot must be filmed live), keyword fallback rules |
| `tools/video/lib/human.ts` | Cursor overlay (arrow on desktop, touch dot on phone) with click ripple, eased glides, 55–130 ms typing, smooth scroll, a pace factor |
| `tools/video/lib/recorder.ts`, `lib/script.ts` | Screencast → ffconcat → WebM; parser for both script layouts (headed sections and tables) |
| `tools/video/assemble.sh`, `segments.py` | ffmpeg + libass: fit each shot to its length (hold or speed up with a "sped up" tag), burned captions in Atkinson Hyperlegible (OFL, in `tools/video/fonts/`), cards, end cards, provenance card first, VO slot `docs/video/vo/<shot-id>.wav` |
| `tools/video/howto.ts` | 54 screenshots for the guides (1440 × 900, 80 % crop round the named control, amber box), placeholders replaced, `docs/howto/img/SHOTS.md` |
| `tools/video/vo.py`, `regenerate.sh`, `contact_sheet.py` | Voice-over lines (and the owner-run TTS step), one-command regeneration, contact sheets |
| `tools/video/muse_images.py`, `docs/video/IMAGE_PROMPTS.md`, `covers.py` | Muse Image (`muse-image-1.0`) art for 32 cards: title, section, thumbnail and guide covers, from Meta's documented `/v1/images/generations` (cited in the script); text is always drawn by `assemble.sh` / `covers.py` on top, plain brand colour where a picture is missing |
| `apps/web/src/app/how-it-works/page.tsx` | The Help page (top bar "Help") gets a "Step-by-step guides" section linking the ten guides on GitHub |
| `docs/video/README.md`, `tools/video/README.md` | Outputs, card art, live-only shots and the judging checklist (judge-facing, no hardware, tool or voice-engine names); regeneration and voice-over steps (internal) |

## Design choices

- **CDP screencast rather than Playwright's `recordVideo`**: sharp text at 1080p (JPEG 92 frames, then VP9 CRF 28) and
  nothing is recorded during off-camera set-up. Frames come only on change, so the ffconcat durations rebuild real time.
- **A fresh demo session per shot**, started off camera, so every shot sees the same books whatever ran before.
- **Honesty over polish**: the test-mode stub is not a model, so shots whose point is a live reading, voice, a mailbox,
  HMRC's sandbox or shared books are marked in `SHOT_PLAN` and the preview says *Stand-in: film live* or shows a
  *Film live* card. Every app frame also carries a small "Test-mode capture · fictional sample data · AI stubbed" tag
  until `--no-test-tag`. Only Home's stub summary card is hidden.
- Raw shots are committed (each 0.3–2 MB, 25 MB in all) so another machine can assemble without re-capturing; anything over
  5 MB is listed in `docs/video/raw/.gitignore` by `regenerate.sh`. Previews and finals are git-ignored.

## Owner's corrections (29 Oct, second round)

  *Integrator, 29 Oct 2026:* on `main` the raw shots are **not** in git. The owner asked for raw video to stay out, so
  `docs/video/raw/*.webm` was filtered out of this branch's commits before the merge, and the root `.gitignore` excludes
  them. Re-capture with `tools/video/capture.ts` (or `regenerate.sh`) before assembling.
- Shot 1 now uses the owner's wording (10 s; shot 2 trimmed to 18 s, total still 180 s) and names no hardware and no
  third-party tool; the Meta model list was checked against `docs/submission/META_MODELS.md` on `main` (`715c564`).
- The end card credits only "Title art: Muse Image (Meta)."; the voice engine is named nowhere judge-facing
  (a test, `tools/video/test_video_tools.py`, scans the scripts, README, prompts, VO lines and manifest for it).

- Shot 5's eval card names Meta models only (no hosting provider) and carries the latest committed figures with sample
  sizes (CIS 92.5 % of 120, property 89.8 % of 108, extraction 91/93 % and 85/80 % on 200 + 200, Ask 32/32); the bank
  row (91.6 % of 459) is the owner's figure with no committed summary yet, flagged in the script, README and HONESTY.

## Tests

- `python3 -m pytest -q tools/video`: **8 passed** (no non-Meta names on any caption or card, eval-card figures; prompts file covers every card, no-key exit 0, request shape and
  exact-size crop and sidecar with the key never printed, 503 retry, safety block, art fallback, no banned names).
- `node --test tools/video/video.test.ts`: **6 passed** (durations, both script layouts, Muse's scripts total 180 s and
  every shot has a plan entry with a known flow, keyword rules, how-to placeholder parsing). It found one bug, fixed:
  a voice-over cell `"…" (28 words)` kept a stray quote.
- Full capture: 30 shots planned, 22 recorded, 8 cards/placeholders, **0 failed**; 9 previews assembled
  (judges 3:00, clips 0:37 each).
- Gates: runtime `pytest -q` **2360 passed, 2 skipped**; `ruff check` and `ruff format --check` clean; `pyright
  services/runtime/app` 0 errors; `eslint .` and `tsc --noEmit` clean in `apps/web`; `pnpm run e2e:build && pnpm run
  e2e:test` **477 passed, 94 skipped, 0 failed** (16 min; the container's Playwright browser build differs from the
  pinned version, so the pre-installed one was linked in; nothing in the repo changed for it).

## Risks and what remains

- **Live footage is still needed** for 16 of the 30 shots (`docs/video/README.md`). Until then the previews are a
  storyboard with real app footage where the build can honestly provide it.
- **Script claims to check before recording** (also in the README checklist and `docs/HONESTY.md`): shot 10's
  "VAT return submitted to sandbox", the voice shots, and shot 7's test counts.
- Several clip flows show the screen the script names but not its whole action (CIS shows registration rather than a
  contractor's deductions; Property shows an empty list, as the demo books have no property). Clip 5 and 4-02 need
  richer demo data or live footage.
- 24 how-to pictures are whole-page approximations; re-shoot by hand where the step needs a specific state (an open
  dialog, an external page).
- The voice-over render and `muse_images.py` have never run here (no TTS model; Meta's API may not be called from this
  session). `muse_images.py` is tested on stubbed HTTP against the documented request and response. Fonts: Atkinson Hyperlegible ships with the tool;
  the eval card's monospace falls back to the system's DejaVu Sans Mono.
- Capture timing depends on machine load; the flows use waits on visible state, not fixed sleeps, but a slow box can
  overrun a shot (it is then sped up and tagged, never cut).
