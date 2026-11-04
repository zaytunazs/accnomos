# Demo video v3: the edit (4 Nov 2026)

Script: `docs/video/SCRIPT_V3.md` (voice lines verbatim). Made by `tools/video/v3/` (capture, voice, edit); media is
not in git. Length **2:55.9** (175.9 s), 1920 × 1080, 30 fps. Rule from the organisers (Cerebral Valley, 4 Nov): 3:00 or less, and the video opens
with what existed before the hackathon and what was built during it.

## Files (owner's PC: `builds\video-v2\`, next to v2's; Spark: `~/video-v3/out/`)

| File | What |
|---|---|
| `accnomos-demo-v3.mp4` | Final: H.264 CRF 20, AAC 192 k, voice-over, burned-in UK English captions |
| `accnomos-demo-v3-novo.mp4` | Same picture, silent track, no captions |
| `accnomos-demo-v3-vo.wav` | The voice-over alone, 48 kHz mono, timed to the picture, -16 LUFS |
| `accnomos-demo-v3.srt` | Captions |
| `accnomos-demo-v3-timeline.json` | Every scene and shot with start, length and voice start (`timeline.json` on the Spark) |
| `accnomos-demo-v3-contact-sheet.jpg` | One frame from the middle of every shot |

## Shot list (final cut)

| Time | Scene | Shot | Meta model on screen |
|---|---|---|---|
| 0:00–0:11.4 | title | Title card with the provenance band | — |
| 0:11.4–0:16.6 | f1 | Feature list card (12 items, animated) | — |
| 0:16.6–0:33.7 | s1 | Home on web + phone (v2 footage) | Muse Spark (summary) |
| 0:33.7–0:44.3 | s2 | Regular costs; Goals & progress with the AI note | Muse Spark |
| 0:44.3–1:01.0 | s3 | Home → Review; Talk, spoken site visit → card → Approve | Muse Voice Transcribe, Muse Spark |
| 1:01.0–1:20.0 | s4 | Phone receipt; web £450 invoice → Approve | Muse Spark |
| 1:20.0–1:36.0 | s4b | Ask: profit this quarter; Ellie overtime timesheet → Approve; tiles for the Harrogate job | Muse Spark (byline) |
| 1:36.0–1:42.0 | s5a | Bank feed, TrueLayer sandbox | — (code) |
| 1:42.0–1:54.9 | s5 | Reports, Export to OneDrive; VAT → HMRC sandbox (password blurred) → receipt | — (code) |
| 1:54.9–2:10.9 | s6 | Self-employment, property; Harrison household (web + phone); household goals | Muse Spark |
| 2:10.9–2:32.1 | s7 | Settings › AI Local model only → Ask → "explanation by Glimmer 30B"; Meta Model API first → "explanation by Muse Spark"; Files; Files & backups | Muse Glimmer 30B, Muse Spark |
| 2:32.1–2:50.1 | s8 | End card with the how-to guides | — |
| 2:50.1–2:55.9 | judges | Judges' slide (silent) | Muse Image credited here only |

New live takes (4 Nov, accnomos.com): `w-route` (main `bf1de521`), `w-timesheet` (main `e1fcfcd7`), `w-bankfeed` (main
`3c83782c`), and `w-profit` and `w-tiles` re-taken at 20:40 UK on main `b5ab4604` for **v3.1** (the submitted file,
`accnomos-demo-v3.1.mp4`, same 175.9 s): the Ask answer's cited files now read "Ledger · Oct 2026 (2 entries)" instead of
five event file paths (`apps/web/src/components/ask/AnswerCard.tsx`). Only scene s4b was re-rendered (`edit.py . --keep`
with `work/s4b_0.mp4` and `work/s4b_2.mp4` removed). Everything else is v2 footage.

## What changed from v2

- Opening: the title card carries the provenance line (before 26 Oct: only our own AI server hardware; built during the
  hackathon: its local model setup, the web and Android app, every feature) with a voice line; then a 5.2 s feature card
  (brand brown, two columns, lines rising in one by one).
- Scene 7: the `/ai/calls` JSON page is gone. The switch is shown in the app: Settings › AI → Local model only → Ask
  "Who owes me the most?" → byline "Numbers by code · explanation by Glimmer 30B · 5.5 s"; Settings › AI → Meta Model
  API first → the same question → "explanation by Muse Spark · 3.6 s". The app's byline says "Glimmer 30B"
  (`shortModelName`); the lower third names Muse Glimmer 30B.
- New Ask scene (after invoices), typed on the live site: "How much profit did we make this quarter?" (£2,489.10, worded
  by Muse Spark, figures by code); "Add 2 hours for Ellie on the Kitchen fit-out, Harrogate job, including 1 hour
  overtime at double rate" → timesheet card (1 h × £11.00 + 1 h × 2 = £33.00) → Approve → "Logged 2 hours for Ellie
  Hale…"; "What tiles did we order for the Kitchen fit-out, Harrogate job?" → Matt white metro tiles 300×100, 8 m²,
  £196.00.
- Bank feed (live, TrueLayer sandbox, main `3c83782c`): Connect the test bank → TrueLayer's consent page (Allow) → back
  on Bank, connected ("mock · test bank, sample data only", Last fetched 4 Nov 2026). The take fetched 2,145 sample
  lines, all left unmatched (TrueLayer's mock data does not match the demo's books), so the line says "ready to match"
  and the counters are not the focus. The scene (`s5a`) is left out automatically if `raw/w-bankfeed.webm` is missing.
- VAT: the HMRC sandbox test user's password is blurred while it is on screen (`HMRC_PW` in the EDL).
- End card: "Step-by-step how-to guides: accnomos.com · github.com/zaytunazs/accnomos/tree/main/docs/howto" with a
  voice line; the v2 closing line is cut for time (the sandbox limit stays on the lower third, the end card and the
  judges' slide).
- Muse Image is credited only on the judges' slide, as in v2.
- Kept from v2 unchanged: scenes 1–6 footage (shorter cuts), the voice (Kokoro bm_lewis), the judges' slide.

## How to rebuild

PC: `tools/video/v3/pc/sync.cmd` (fetch the scripts from the branch), `cap.ps1 w-route,w-profit,w-timesheet,w-tiles,w-bankfeed`
(one shot at a time; the live API limits requests per IP; the demo books take ~10 s to build). Spark (`~/video-v3`, with
`raw/`, `cards/`, `fonts/` linked to `~/video-v2`): `tts.py vo_lines.json vo bm_lewis`, then `python3 edit.py .` (about
90 s; `--keep` reuses scene files, `--only s4b` renders one scene). `pc/spark_fetch.ps1` brings the files back.
