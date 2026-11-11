# Live checks of the hosted-model paths

Run at 2026-11-04T04:04:32+00:00 against `https://api.accnomos.com` in a company demo session (`POST /demo/session?kind=company`, the fictional Bramblewood Joinery Ltd sample books). Script: `evals/harness/live_checks.py`; raw results with every step's `/ai/calls` records: `checks.json`. The script holds no key: the server uses its own.

| # | Check | Request | HTTP | Result | Served by (`/ai/calls`) | Time |
|---|---|---|---:|---|---|---:|
| 1 | demo session | `POST /demo/session?kind=company` | 200 | kind=company, business=Bramblewood Joinery Ltd, today=2026-11-04 | no AI call | 0.06 s |
| 2 | ai health | `GET /ai/health` | 200 | meta `muse-spark-1.3-contributor` up; spark `muse-glimmer:30b` up | no AI call | 0.95 s |
| 3 | transcribe ('How much did we spend on fuel this year?', synthetic speech) | `POST /books/ask/transcribe` | 200 | heard: “How much did we spend on fuel this year?” | The speech-to-text model (`muse-voice-transcribe-1.0`) | 2.73 s |
| 4 | ask by voice ('How much did we spend on fuel this year?', synthetic speech) | `POST /books/ask/voice` | 200 | heard: “How much did we spend on fuel this year?”; answer: “Sorry, the books you gave me don't show any fuel spend. If fuel is logged with its own code in Books.xlsx, that detail would let me answer.” | transcribed by the speech-to-text model (`muse-voice-transcribe-1.0`); ask_answer: meta `muse-spark-1.3-contributor` | 6.44 s |
| 5 | transcribe ('What is our VAT bill for this quarter?', synthetic speech) | `POST /books/ask/transcribe` | 200 | heard: “What is our our VAT bill for this quarter?” | The speech-to-text model (`muse-voice-transcribe-1.0`) | 1.49 s |
| 6 | ask by voice ('What is our VAT bill for this quarter?', synthetic speech) | `POST /books/ask/voice` | 200 | heard: “What is our VAT bill for this quarter?”; answer: “For Oct–Dec 2026 there's nothing due — your VAT bill is £0.00.” | transcribed by the speech-to-text model (`muse-voice-transcribe-1.0`); ask_answer: meta `muse-spark-1.3-contributor` | 7.42 s |
| 7 | ask, route meta_first | `POST /books/ask` | 200 | answer: “The books you’ve given me only show sales for Jul–Sep 2026 as a whole, so I can’t pick out last month on its own. A monthly sales breakdown would show it.” | ask_answer: meta `muse-spark-1.3-contributor` | 6.4 s |
| 8 | ask, route local_first | `POST /books/ask` | 200 | answer: “The books you were given don’t show a monthly total. They only show the Jul–Sep 2026 quarter, with net sales £19,288.15 and VAT £3,857.63. To get last month you’d need the ledger broken down by month.” | ask_answer: spark `muse-glimmer:30b` | 5.66 s |
| 9 | ask, route local_only | `POST /books/ask` | 200 | answer: “The books you were given don’t show a monthly total. They only show the Jul–Sep 2026 quarter, with net sales £19,288.15 and VAT £3,857.63. To get last month you’d need the ledger broken down by month.” | ask_answer: spark `muse-glimmer:30b` | 5.66 s |
| 10 | upload a receipt photo to the demo inbox | `PUT /demo/graph/v1.0/me/drive/special/approot:/00 Inbox/live-check-021_foreign.png:/content` | 201 | name=live-check-021_foreign.png | no AI call | 0.08 s |
| 11 | start scan job | `POST /books/scan/jobs` | 202 | id=9c31cc2009c34545a9a2fdb9bf00642f | no AI call | 0.06 s |
| 12 | scan job: classify | `GET /books/scan/jobs/{id} (polled until not working, max 240 s)` | 200 | job waiting; file stage Confirm the type; type guessed purchase_invoice (0.95, by ai) | classify: meta `muse-spark-1.3-contributor` | 6.08 s |
| 13 | confirm the type (as guessed) | `POST /books/scan/jobs/9c31cc2009c34545a9a2fdb9bf00642f/confirm` | 200 | status=working | no AI call | 0.06 s |
| 14 | scan job: read | `GET /books/scan/jobs/{id} (polled until not working, max 240 s)` | 200 | job done; file stage Needs a look; type guessed purchase_invoice (0.95, by ai) | extract: meta `muse-spark-1.3-contributor` | 12.11 s |
| 15 | the proposal the scan made | `GET /books/proposals/28ab7d92505a4f0ebf39f9de6f463d20` | 200 | status needs_a_look; read DE VRIES & ZONEN TRADING BV, 2026-08-14, gross 375.0; crop: Cropped by code | no AI call | 0.06 s |
| 16 | home summary | `GET /books/home` | 200 | summary: “3 things need attention now and 3 more soon” (by muse-spark-1.3-contributor) | home_summary_items: meta `muse-spark-1.3-contributor` | 11.29 s |
| 17 | goals note | `GET /books/goals` | 200 | 3 goals; note: “Your VAT bill pot most needs a little attention, as it is £610.93 behind plan to date with £610.00 saved so far towards £4,500.00. Record what you put aside as you go, so the progress stays current, keeping in mind there is £3,890.00 still to go: about £1,258.90 a month. November sales is Just started: too early to judge the pace, while utilities is £26.67 under plan to date.” (by muse-spark-1.3-contributor) | goals_note: meta `muse-spark-1.3-contributor` | 10.7 s |

AI calls logged: 9 (7 to the hosted model's API), 0 fell back, 0 failed; 4 transcriptions by the speech-to-text model.

Gold for the scanned photo (`021_foreign.json`): supplier De Vries & Zonen Trading BV, date 2026-08-14, gross 375.0, expected status needs_a_look.

**The spoken questions are synthetic speech** (text to speech on our own server, mono WAV, about 3 s each), used only
as test input. Separately, the owner used spoken questions from the Android app on his own phone on 4 Nov 2026; that
use is not recorded here.

What this shows and does not show:

- Each step's "Served by" is what the runtime's own call log (`GET /ai/calls`) recorded for that step. With
  `X-AI-Route: local_first` and `local_only` a call served by `spark` is the local open-weights model on our own server.
- The answers were not scored against an answer key; every figure an answer quotes is checked by code against the
  books (the KnownNumbers check). Reading accuracy is measured separately on 200 synthetic documents:
  `evals/runs/spark13_200` and `evals/runs/spark13_messy_200`; the word-error figure for transcription is in
  `evals/runs/stt`. A few live calls are not a measurement.
- The scanned photo is a synthetic scene (a gold receipt on a cluttered desk, `harness.crop_bench.make_scene`); its
  reading is compared with that gold document above. The image model's receipt crop was not on for this run (the scan says
  "Cropped by code"); the receipt-crop image model was checked separately: `evals/runs/sam_crop_live/report.md`.
