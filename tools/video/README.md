# tools/video: regenerating the footage, art, previews and voice-over

Internal notes for whoever rebuilds the video material. What the outputs are and the judging checklist are in
`docs/video/README.md`; keep hardware, tool and voice-engine names out of that file and out of anything on screen.

## Everything at once

```bash
tools/video/regenerate.sh
```

Runs, in order (each also works on its own):

1. `node tools/video/capture.ts [--skip-build] [--only judges-04,clip-03] [--plan]`: builds the test-mode export with
   `NEXT_PUBLIC_SUBMISSION_MODE=1`, starts the test-mode runtime with `DEMO_MODE=1` and the static server (unless
   already up on 8781 / 3100), records every shot from Chromium's compositor (CDP screencast, then ffmpeg to constant
   30 fps VP9). Each shot starts a fresh demo sandbox off camera. `--plan` prints the shot → flow table.
2. `node tools/video/howto.ts [--only vat-return] [--dry-run] [--reshoot]`: a screenshot per guide placeholder.
3. `python3 tools/video/vo.py lines`: `docs/video/vo/lines.json`.
4. `python3 tools/video/muse_images.py`: Muse Image art for every card in `docs/video/IMAGE_PROMPTS.md` that has no
   PNG yet (below). Without `META_API_KEY` it says so and exits 0.
5. `python3 tools/video/covers.py` (also `assemble.sh --covers`): guide covers.
6. `tools/video/assemble.sh [--final] [--only judges] [--no-test-tag]`: previews (or finals) and thumbnails.

Needs Node 22.18+, `pnpm install` in `apps/web`, the runtime's Python (`uv sync --all-packages`, or `E2E_PYTHON`) and
ffmpeg with libass and libvpx. Nothing in steps 1–3, 5 and 6 contacts Meta, Microsoft or HMRC.

## Title art (Muse Image), on the owner's PC

```bash
python tools/video/muse_images.py --dry-run
```

```bash
META_API_KEY=... python tools/video/muse_images.py
```

Calls `POST https://api.meta.ai/v1/images/generations` with `muse-image-1.0` (Meta's docs, read 29 Oct 2026:
https://dev.meta.ai/docs/models, https://dev.meta.ai/docs/image-generation,
https://dev.meta.ai/docs/api-reference/images/schemas). `size` only sets the aspect ratio, so each picture is cropped
to its card's exact size (1920 × 1080, 1080 × 1920 or 1280 × 720). The key is read from the environment and never
printed; `MODEL_API_KEY` (the name in Meta's docs) also works. Existing PNGs are skipped (`--force` redoes them).
32 cards, about USD 0.32 at USD 0.01 each. Then `tools/video/assemble.sh` and `python3 tools/video/covers.py` again.

## Voice-over

`docs/video/vo/lines.json` holds one line per shot (file name, text, the shot's length). Any TTS works as long as the
files are named `docs/video/vo/<shot-id>.wav`; `assemble.sh` picks them up by name and warns when one runs longer than
its shot. The owner's set-up is Kokoro (open model, run locally, voice `bm_george`, British English, 24 kHz mono, the
same as the teaser):

```bash
python tools/video/vo.py kokoro
```

It writes a WAV for every line that has none (`--force` redoes them) and prints each length against its shot. Not run
in the cloud session that wrote it. Then:

```bash
tools/video/assemble.sh --final
```

Do not name the voice engine in the video, its captions or `docs/video/`.

## Swapping in live footage

Replace `docs/video/raw/<shot-id>.webm` with your recording (same name, any length: it is fitted to the shot), then
re-run `assemble.sh`. Once no stubbed screen is left, add `--no-test-tag`.

## How the pieces fit

`lib/script.ts` reads both script layouts (headed "Shot N — … (0:10–0:28, 18 s)" sections and Markdown tables);
`flows.ts` holds the scripted flows and `SHOT_PLAN` (flow per shot id, live-only reason, pace); `lib/human.ts` draws
the cursor and moves, types and scrolls like a person; `lib/recorder.ts` records; `segments.py` plans each segment
(captions, cards, card art, end card) for `assemble.sh`; `covers.py` and `contact_sheet.py` make the stills. When Muse
changes a script, run `capture.ts --plan`: a new shot id needs a line in `SHOT_PLAN`. Tests: `node --test
tools/video/video.test.ts` and `python3 -m pytest -q tools/video`.
