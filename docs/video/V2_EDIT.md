# Demo video v2: the edit (4 Nov 2026)

Script: `docs/video/SCRIPT_V2.md` (voice lines spoken verbatim). Length **2:41** (161.6 s), 1920 × 1080, 30 fps.
Made by `tools/video/v2/` (capture, voice, edit); media is not in git.

## Files (owner's PC: `builds\video-v2\`; Spark: `~/video-v2/out/`)

| File | What |
|---|---|
| `accnomos-demo-v2.mp4` | Final: H.264 CRF 20, AAC 192 k, voice-over, burned-in UK English captions |
| `accnomos-demo-v2-novo.mp4` | Same picture, no voice and no captions (silent track), for a new voice-over |
| `accnomos-demo-v2-vo.wav` | The voice-over alone, 48 kHz mono, timed to the picture, -16 LUFS |
| `accnomos-demo-v2.srt` | Captions |
| `timeline.json` | Every scene and shot with start, length and voice start |
| `accnomos-demo-v2-contact-sheet.jpg` | One frame from the middle of every shot |
| `raw\` | The footage: `w-*.webm` (web), `p-*.mp4` (Android), each with its marks |

## Shot list

Times are the final cut's. "Live" = recorded from https://accnomos.com (main `fdb0beeb`, deployed 4 Nov ~05:25 UK)
with the real Meta chain answering; Android = APK 0.3.16 (21) on the emulator, talking to the same live API.
Nothing is from the test-mode build; no stub text is on screen.

| Time | Scene (voice) | Shot | Source | Meta model on screen |
|---|---|---|---|---|
| 0:00–0:02.6 | Title | Card over the Muse Image art (`cards-zaytuna/judges-title.png`) | card | — |
| 0:02.6–0:21.8 | 1 | Home on web (summary hovered item by item) and the phone side by side | live web `w-home` + Android `p-home` | "worded by your AI (Muse Spark)" |
| 0:21.8–0:35.2 | 2 | Spending › Regular costs (cropped), then Goals & progress with the AI note "What your goals are telling you" | live `w-spending`, `w-goals` | Muse Spark (goals note) |
| 0:35.2–0:54.2 | 3 | Home summary → Review → button; Talk to Accnomos: **spoken** "Add a site visit tomorrow at ten" → "Transcribed by Muse Voice Transcribe" → calendar card (needs your OK) → Approve → "Added" | live `w-home`, `w-home-action`, `w-talk` (panel cropped) | Muse Voice Transcribe, Muse Spark |
| 0:54.2–1:16.8 | 4 | Phone: Photograph a receipt → gallery → upload → "Looks like a receipt (97 % sure)" → Confirm → NOVEX card "Read by Muse Spark", "Cropped", verifier agrees. Web: Ask "send a £450 invoice to Hartwell" → priced card (needs a tap) → Approve → "Invoice INV-0007 … sent" (demo: not actually sent) | Android `p-receipt`; live `w-invoice` | Muse Spark (reading, second reading, invoice) |
| 1:16.8–1:33.8 | 5 | Reports Jul–Sep 2026, profit and loss, Export to OneDrive; VAT nine boxes by code → Connect (simulated) → declaration → Submit (demo — simulated) → receipt with form bundle number | live `w-reports`, `w-vat` | none (code) |
| 1:33.8–1:51.8 | 6 | Self-employment (MTD Income Tax, sandbox) and Property; the Harrison household: summary → budget (web + phone); household goals | live `w-selfemp`, `w-personal` + Android `p-personal`, `w-personal-goals` | Muse Spark (household summary) |
| 1:51.8–2:14.4 | 7 | Settings › AI: the three choices, Local model only and its warning; `GET /ai/calls` drawn as a page (records `spark / muse-glimmer:30b` and `meta / muse-spark-1.3-contributor` made just before, by asking with `X-AI-Route: local_only` then `meta_first`); Files (OneDrive folder, Books.xlsx, backups) and Settings › Files & backups | live `w-ai`, `w-calls`, `w-files`, `w-backups` | Muse Spark, Muse Glimmer 30B |
| 2:14.4–2:34.6 | 8 | End card: accnomos.com · github.com/zaytunazs/accnomos · HMRC sandbox note | card (`section-demo.png`) | — |
| 2:34.6–2:41.6 | Judges' slide (silent) | Models at run time, measured figures, provenance, try it, limits; Muse Image credited here only | card (`section-meta-ai.png`) | — |

Each scene opens with a lower third (feature · Meta model) for 5 s. Waits for a live model are cut (a short
crossfade where the "working" moment ends); footage runs at up to 1.45× and very long takes lose their middle.

## Live, simulated, not shown

- Live Meta calls on camera: Home summary, goals note, Muse Voice Transcribe, the calendar card, the receipt reading
  and its second reading (phone), the invoice card, the household summary, the `/ai/calls` records.
- Simulated by the demo (and said so on screen): HMRC VAT submission ("Demo — submission simulated", "HMRC was not
  contacted"); the invoice email ("demo — not actually sent"). Scene 8's voice explains the sandbox.
- Voice input on the web uses Chromium's fake microphone fed with a recorded line (a second open-source voice,
  `bf_emma`); the phone shots use taps only (the emulator has no microphone or real camera: the receipt comes from the
  gallery after "Photograph a receipt").
- Not shown: the bill going into the household calendar (live take proposed "BT Broadband bill on , all day" — a
  subject-parsing slip, reported); Settings › Connection (says "AI: Not set up" in the demo).

## Voice

Open-source Kokoro-82M (Apache-2.0) on the owner's Spark, British English voice **bm_lewis**, 24 kHz, speed 1.0.
Chosen over bm_george, bf_emma, bm_daniel and bm_fable by running each through Muse Voice Transcribe: bm_lewis was the
only one transcribed word for word (bm_george came back "Snapper receipt"). Spoken-only fixes (captions keep the
script): "£450" → "four hundred and fifty pounds", "CSV" → "C S V", "HMRC" → "H M R C", "OneDrive" → "One Drive".
No line was changed. No music.

## Re-voicing

Record each line to `vo/s1.wav` … `vo/s8.wav` (any rate), then on the Spark: `cd ~/video-v2 && python3 edit.py .`
(about 90 s). Scene lengths are in `EDL` at the top of `tools/video/v2/edit.py`; a line longer than its scene is
warned about. To keep the picture as it is, lay a new voice over `accnomos-demo-v2-novo.mp4` using the scene starts
in `timeline.json`.

## Rebuilding

PC: `tools/video/v2/capture_live.ts` (Playwright, 1280 × 720 at device scale 2, Chromium screencast → 1920 × 1080 VP9,
human-speed cursor and typing from `tools/video/lib/human.ts`), `phone.ps1` (adb screenrecord). Spark: `tts.py`
(voice), `edit.py` (edit). The live API limits requests per IP: shots run one at a time with pauses.
