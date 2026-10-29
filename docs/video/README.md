# Video footage, previews and how-to screenshots

Everything here is generated from the scripts by `tools/video/` (branch `claude/video-capture`, 29 Oct 2026):

| What | Where | In git |
|---|---|---|
| Scripts (Muse Spark) | `JUDGES_VIDEO.md` (3:00, 11 shots), `CLIPS.md` (8 clips × 35 s) | yes |
| Shot list with timing, caption, voice-over, flow, and why a shot must be re-filmed live | `manifest.json` | yes |
| Contact sheets, one frame per shot | `contact-sheet-judges.png`, `contact-sheet-clip-01.png` … `-08.png` | yes |
| Raw silent footage per shot (1920 × 1080 judges, 1080 × 1920 clips, VP9 WebM, 30 fps) | `raw/<shot-id>.webm` | under 5 MB each, yes; over 5 MB listed in `raw/.gitignore` |
| Silent previews with burned captions | `preview/judges.mp4`, `preview/clip-01.mp4` … | no (regenerate) |
| Final renders with voice-over | `out/<sequence>.mp4` | no |
| Voice-over lines for TTS; the WAVs | `vo/lines.json`; `vo/<shot-id>.wav` | lines yes; WAVs your call |
| How-to screenshots (1440 × 900, cropped, highlight box) | `../howto/img/<guide>-<N>.png` | yes |

## Look first

1. `contact-sheet-judges.png`: every judges' shot at a glance; amber tiles failed, brown tiles are *Film live* or
   camera placeholders.
2. `preview/judges.mp4` (regenerate, or the copy sent in the session): the 3:00 cut with captions and cards, silent.
3. `manifest.json` → each shot's `live` field: what the test-mode build cannot show honestly (list below).
4. `../howto/*.md`: the guides now render with their screenshots; `../howto/img/SHOTS.md` says which page and control
   each picture boxes, and which are approximate.

## Regenerate

```bash
tools/video/regenerate.sh
```

That runs, in order (each also works on its own):

- `node tools/video/capture.ts [--skip-build] [--only judges-04,clip-03] [--plan]`: builds the test-mode export with
  `NEXT_PUBLIC_SUBMISSION_MODE=1` (the judges' build), starts the test-mode runtime with `DEMO_MODE=1` and the static
  server (unless already running on 8781 / 3100), and records every shot from Chromium's compositor (CDP screencast,
  JPEG 92, then ffmpeg to constant 30 fps). Each shot starts a fresh demo sandbox off camera, so the books are the same
  every time: the fictional Bramblewood Joinery Ltd, labelled SAMPLE — FICTIONAL COMPANY. `--plan` prints the shot →
  flow table without recording.
- `node tools/video/howto.ts [--only vat-return] [--dry-run]`: one screenshot per placeholder in `docs/howto/*.md`,
  then rewrites the placeholder as the image (the "Must be visible" brief becomes its alt text).
- `python3 tools/video/vo.py lines`: `vo/lines.json` for the TTS run.
- `tools/video/assemble.sh [--final] [--only judges] [--no-test-tag]`: per shot, fit the footage to the script's
  length (held on the last frame if short; sped up and tagged *sped up ×n* if long), burn the caption (Atkinson
  Hyperlegible, white on a dark box, inside 10 % side and 8 % bottom margins; 12 % bottom in vertical clips so it sits
  above the phone UI), draw cards (provenance, eval table, end card) from the script's text, and lay
  `vo/<shot-id>.wav` on the shot or silence when there is none. The judges' video always opens with the provenance
  card (the script's own shot 1, else a built-in one from `docs/PROVENANCE.md`); clips open on a 2 s title card.

Needs Node 22.18+ (it runs the TypeScript directly), `pnpm install` in `apps/web`, the runtime's Python
(`uv sync --all-packages`, or `E2E_PYTHON`), and ffmpeg with libass and libvpx. Nothing contacts Meta, Microsoft or
HMRC. A full capture takes about 10 minutes on a 4-core box.

How the pieces fit: `tools/video/lib/script.ts` reads both script layouts (headed "Shot N — … (0:08–0:28, 20 s)"
sections with Screen / On-screen action / Caption / Voice-over paragraphs, and Markdown tables with Time, Screen,
Caption and Voice-over columns); `tools/video/flows.ts` holds one scripted flow per thing a shot can show and
`SHOT_PLAN`, the flow for each shot id; `tools/video/lib/human.ts` draws the cursor (headless Chromium paints none),
glides it with easing, types at 55–130 ms a key and scrolls smoothly; `tools/video/lib/recorder.ts` records.
When Muse changes a script, re-run `--plan`: a new shot id needs a line in `SHOT_PLAN` (otherwise a keyword rule picks
a flow), and a changed duration needs nothing.

## Voice-over on the Spark

1. `git pull`, then `python3 tools/video/vo.py lines` (or use the committed `vo/lines.json`).
2. Make the WAVs with the teaser's Kokoro set-up (voice `bm_george`, British English, 24 kHz mono):
   `python tools/video/vo.py kokoro` writes `vo/<shot-id>.wav` for every line that has none (`--force` redoes them)
   and prints each length against its shot. Any TTS works if the files keep those names. *Not run in the cloud
   session that wrote it (no Kokoro there).*
3. `tools/video/assemble.sh --final` → `out/judges.mp4` and `out/clip-NN.mp4` (H.264 CRF 18, AAC 160 kb/s).
   It warns when a WAV is longer than its shot (the end is cut): shorten the line or lengthen the shot in the script.
4. Swap in the live footage (below) by replacing `raw/<shot-id>.webm` with your recording, same name, then re-run
   step 3. Once no stubbed screen is left, add `--no-test-tag`.

## Shots the test-mode build cannot show honestly

The capture runs on the test-mode build, where a stub stands in for every model and the demo simulates HMRC. These
shots get a stand-in (tagged *Stand-in: film live* in the preview) or a *Film live* card; record them for real before
the final cut. From `SHOT_PLAN` in `tools/video/flows.ts`:

| Shot | What to film live | Why |
|---|---|---|
| judges-03, clip-01-02 | Android camera capture; an Outlook email arriving | The app has never run on a real device; no real mailbox in the demo |
| judges-04 | The reader line naming Muse Glimmer / Muse Spark on a live reading | In test mode the card's reader is the stub |
| judges-07, judges-10, clip-03-02 | Connect to HMRC's sandbox, obligations, declaration, receipt | The demo simulates HMRC ("Demo — submission simulated") |
| judges-08, clip-01-01 | Outlook intake on a throwaway mailbox | The demo has no mailbox |
| judges-09, clip-02-02 | Home's AI summary | In test mode it reads "Test stub summary" (hidden in the captures) |
| judges-11, clip-07-01 | Voice | Muse Voice Transcribe has never been run live (`docs/HONESTY.md`) |
| clip-07-02, clip-07-03 | Quote and to-do from chat | The stub cannot turn those lines into cards |
| clip-04-03 | The MTD Income Tax sandbox submission | Never run against HMRC |
| clip-08-01 | The accountant portal on shared books | Needs books shared through Microsoft Graph |

The one thing hidden in captures: Home's summary card (`section[aria-labelledby="home-summary"]`), because in test mode
it says "Test stub summary … (accnomos-test-stub)". The Ask answer still says "explanation by accnomos-test-stub"
under its figures; the corner tag covers that until it is re-filmed.

## Checklist against the judging requirements

Criteria: Impact, Use of Meta AI tooling, Technical depth and execution, Demo quality (equal weight); the video must
open with one line on what pre-existed and stay within 3:00.

- [x] **Opens with what pre-existed**: shot 1 is the provenance card (DGX Spark with Ollama only; repo created
      26 Oct 22:30 UTC after the 16:00 kickoff; `docs/PROVENANCE.md`), held 8 s.
- [x] **Length**: 180 s exactly (11 shots); each clip 35 s plus a 2 s title card.
- [x] **Impact** (shots 2–3): the dashboard and MTD deadlines are real footage; shot 3 needs the phone filmed.
- [ ] **Use of Meta AI tooling** (shots 4–5): the eval card is drawn from the script's table, which matches
      `docs/submission/META_MODELS.md` (91/93 % Spark Open, 85/80 % Glimmer, Ask 32/32, synthetic). Shot 4 needs a
      live reading so the card names a Meta model honestly.
- [x] **Technical depth** (shots 6–7): approve → ledger event file → `Books.xlsx`, and the nine VAT boxes by code, are
      real footage. **Check before recording:** shot 7's voice-over quotes "1260 runtime checks, 208 browser tests and
      248 app tests", the owner's 28 Oct gate figures (`docs/HONESTY.md`); re-run the gates and update the line.
- [ ] **HMRC wording**: shot 10's caption says "VAT return submitted to sandbox", but `docs/HONESTY.md` says the browser
      flow has not been run end to end against HMRC's sandbox. Run it off camera first; if it fails, use the script's
      fallback (`submission not yet run end to end`).
- [ ] **Voice** (shot 11, clip 7): never run live. Either run it live once before filming or replace the shot (the older
      script, `docs/submission/VIDEO_SCRIPT.md`, said not to film the mic).
- [x] **Demo quality**: smooth cursor, human-speed typing, captions burned in at accessible size, no dev overlays
      (static export, no Next.js indicator), SAMPLE — FICTIONAL COMPANY banner on every app screen.
- [x] **No secrets on screen**: the demo sandbox has no keys, tokens, passwords or real mailboxes.
- [ ] **Voice-over**: Kokoro WAVs on the Spark, then `assemble.sh --final`, then watch it through once with the sound on.
