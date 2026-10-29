# Video footage, previews and how-to screenshots

Everything here is generated from the scripts by `tools/video/` (branch `claude/video-capture`). How to regenerate it,
step by step, is in `tools/video/README.md`.

Credit: **Title art: Muse Image (Meta).**

| What | Where | In git |
|---|---|---|
| Scripts (Muse Spark) | `JUDGES_VIDEO.md` (3:00, 11 shots), `CLIPS.md` (8 clips × 35 s) | yes |
| Prompts for the title, section, thumbnail and guide-cover art | `IMAGE_PROMPTS.md` (32 cards) | yes |
| The art itself (Muse Image, `muse-image-1.0`), each with a JSON sidecar: model, prompt, date | `cards/<id>.png` | once generated |
| Shot list with timing, caption, voice-over, flow, section, and why a shot must be re-filmed live | `manifest.json` | yes |
| Contact sheets, one frame per shot | `contact-sheet-judges.png`, `contact-sheet-clip-01.png` … `-08.png` | yes |
| Raw silent footage per shot (1920 × 1080 judges, 1080 × 1920 clips, 30 fps) | `raw/<shot-id>.webm` | under 5 MB each, yes |
| Silent previews with burned captions, and a 1280 × 720 thumbnail per video | `preview/<sequence>.mp4`, `preview/<sequence>-thumbnail.png` | no (regenerate) |
| Final renders with voice-over | `out/<sequence>.mp4` | no |
| Voice-over lines, one per shot | `vo/lines.json` (the WAVs go in `vo/<shot-id>.wav`) | lines yes |
| How-to screenshots (1440 × 900, cropped, highlight box) and guide covers (1280 × 720) | `../howto/img/` | yes |

## Look first

1. `contact-sheet-judges.png`: every judges' shot at a glance; amber tiles failed, brown tiles are *Film live* or
   camera placeholders.
2. `preview/judges.mp4` and `preview/judges-thumbnail.png` (regenerate with `tools/video/assemble.sh`).
3. `manifest.json` → each shot's `live` field: what the test-mode build cannot show honestly (list below).
4. `../howto/*.md`: the guides render with a cover and a screenshot per step; `../howto/img/SHOTS.md` says which
   control each picture boxes, and which are approximate.

## Cards and art

Every word on a card (titles, the provenance lines, the eval table, captions, the end card and its credit) is drawn by
`tools/video/assemble.sh` on top of the art, so it is crisp and exactly as scripted; the art carries no text. Until
`tools/video/muse_images.py` has made a card's picture, that card is plain brand colour (dark teal `#0A4F47`), so the
previews always build.

| Art | Used for |
|---|---|
| `judges-title` | Shot 1, the opening card on what existed before the event |
| `section-impact`, `section-meta-ai`, `section-depth`, `section-demo` | Card shots in each part of the judges' video (the measured-numbers card is `section-meta-ai`); `section-demo` is also the end card |
| `clip-NN-title` | The 2 s title card of each clip |
| `thumb-judges`, `thumb-clip-NN` | Thumbnails |
| `howto-<guide>` | Guide covers (`../howto/img/<guide>-cover.png`) |

## Opening card (shot 1), the owner's rule

No hardware name and no third-party tool name anywhere judge-facing in the video. Shot 1 reads:

> Before the hackathon: only a local GPU server I already owned. Everything for Accnomos, including the Meta models on
> it, was set up after kickoff. Repo created 26 Oct 2026 22:30 UTC (kickoff 16:00 UK). Meta models: Muse Spark, Muse
> Spark Open, Muse Glimmer, Muse Voice Transcribe, Muse Image, Segment Anything.

The model list was checked on 29 Oct 2026 against `docs/submission/META_MODELS.md` on `main` (`715c564`): all six are
in the build (Segment Anything is wired and off by default; Muse Image made the brand and title art). Check it again on
the day you record and drop any that has left `main`.

## Shots the test-mode build cannot show honestly

The capture runs on the test-mode build, where a stub stands in for every model and the demo simulates HMRC. These
shots get a stand-in (tagged *Stand-in: film live* in the preview) or a *Film live* card; record them for real before
the final cut. From `SHOT_PLAN` in `tools/video/flows.ts`:

| Shot | What to film live | Why |
|---|---|---|
| judges-03, clip-01-02 | Android camera capture; an Outlook email arriving | The app has never run on a real device; no real mailbox in the demo |
| judges-04 | The reader line naming a Meta model on a live reading | In test mode the card's reader is the stub |
| judges-07, judges-10, clip-03-02 | Connect to HMRC's sandbox, obligations, declaration, receipt | The demo simulates HMRC ("Demo — submission simulated") |
| judges-08, clip-01-01 | Outlook intake on a throwaway mailbox | The demo has no mailbox |
| judges-09, clip-02-02 | Home's AI summary | In test mode it reads "Test stub summary" (hidden in the captures) |
| judges-11, clip-07-01 | Voice | Muse Voice Transcribe has never been run live (`docs/HONESTY.md`) |
| clip-07-02, clip-07-03 | Quote and to-do from chat | The stub cannot turn those lines into cards |
| clip-04-03 | The MTD Income Tax sandbox submission | Never run against HMRC |
| clip-08-01 | The accountant portal on shared books | Needs books shared through Microsoft Graph |

Do not film *Connect → Choose your AI* or the *Meta models at work* page for the judges' video: both name the local
hardware or serving tools, which the owner's rule keeps out of the video.

## Checklist against the judging requirements

Criteria: Impact, Use of Meta AI tooling, Technical depth and execution, Demo quality (equal weight); the video must
open with one line on what pre-existed and stay within 3:00.

- [x] **Opens with what pre-existed**: shot 1 (10 s) in the owner's wording, no hardware or tool names.
- [x] **Length**: 180 s exactly (shot 1 10 s, shot 2 trimmed to 18 s); each clip 35 s plus a 2 s title card.
- [x] **Credit**: the end card carries "Title art: Muse Image (Meta)." on its own line; nothing else is credited.
- [x] **Impact** (shots 2–3): the dashboard and MTD deadlines are real footage; shot 3 needs the phone filmed.
- [ ] **Use of Meta AI tooling** (shots 4–5): the eval card is drawn from the script's table, which matches
      `docs/submission/META_MODELS.md` (91/93 % Muse Spark Open, 85/80 % Muse Glimmer, Ask 32/32, synthetic). Shot 4
      needs a live reading so the card names a Meta model honestly. Muse Image appears as the title art.
- [x] **Technical depth** (shots 6–7): approve → ledger event file → `Books.xlsx`, and the nine VAT boxes by code, are
      real footage. **Check before recording:** shot 7's voice-over quotes the 28 Oct test counts (1260 / 208 / 248);
      the e2e count alone was 477 on 29 Oct. Re-run the gates and update the line.
- [ ] **HMRC wording**: shot 10's caption says "VAT return submitted to sandbox", but `docs/HONESTY.md` says the browser
      flow has not been run end to end against HMRC's sandbox. Run it off camera first; if it fails, use the script's
      fallback (`submission not yet run end to end`).
- [ ] **Voice** (shot 11, clip 7): never run live. Either run it live once before filming or replace the shot.
- [x] **Demo quality**: smooth cursor, human-speed typing, captions burned in at accessible size, no dev overlays,
      SAMPLE — FICTIONAL COMPANY banner on every app screen.
- [x] **No secrets on screen**: the demo sandbox has no keys, tokens, passwords or real mailboxes.
- [ ] **Title art**: run `tools/video/muse_images.py` with the Meta key, look at `cards/`, re-run `assemble.sh`.
- [ ] **Voice-over**: render the WAVs, `assemble.sh --final`, then watch it through once with the sound on.
