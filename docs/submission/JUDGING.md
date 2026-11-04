# Judging: every criterion mapped to evidence, and how to run it

Refreshed 4 Nov 2026 against the official criteria: **Impact, Use of Meta AI tooling, Technical depth and execution, and
Demo quality** (the participant guide gives the weighting; the event page says the indie track is judged on creativity,
technical ambition and whether it works).
Every claim names a path in this repo; nothing here goes beyond `docs/HONESTY.md`.
Status words: *run live* = run for real against the live server or a real sandbox, with the record named (or, where it says
"our record", the maintainers' word with no log committed); *measured* = a committed report under `evals/`;
*tested on fakes* = automated tests against in-memory fakes or stubs (this proves our logic, not Microsoft, Meta or HMRC).

**Provenance.** Only the owner's own AI server with a local model runtime predates the event; the first commit is 6 h 29 min after kickoff,
and every merge has a second-agent review. Timestamps, commits per day and how each part was built: `docs/PROVENANCE.md`.

**On `main` since 28 Oct** and claimed below where they are tested: the month-end close, company / sole-trader / personal
profiles, the Meta models page, the no-sign-in demo sandbox (`/judges`, also linked as *Try the demo*), the personal demo,
the HMRC sandbox and TrueLayer sandbox in the demo, the hands-free assistant, goals and the calendar. iPhone is not built.

**Android app:** install the APK from [GitHub Releases](https://github.com/zaytunazs/accnomos/releases) (newest `android-*` release; 0.3.19: [accnomos-0.3.19-24.apk](https://github.com/zaytunazs/accnomos/releases/download/android-0.3.19-24/accnomos-0.3.19-24.apk)) and press **Try the company demo** (or **Try the personal demo**): no account needed. The Google Play listing is in Google's review, which takes several days, so use the APK for now.

## 1. Impact


| Claim | Evidence | Status |
|---|---|---|
| A real, compulsory job: VAT-registered UK businesses must keep digital records and file through MTD software | `README.md`, `docs/HMRC.md` | Context |
| Target user: a UK small business or sole trader doing their own books, often from a phone | `README.md`, `docs/DEMO.md`, `apps/mobile/` | Context |
| The owner keeps the records: no Accnomos database; the ledger and `Books.xlsx` are files in the user's own OneDrive, so disconnecting loses nothing | `docs/ARCHITECTURE.md` ("Runtime state: none"), `services/runtime/app/projection.py` | Tested on fakes; one live run on a personal account (our record) |
| Paperwork comes in where it already is: Android camera and share target, web upload, Outlook intake (read-only `Mail.Read`) | `apps/mobile/lib/screens/capture_screen.dart`, `apps/mobile/android/app/src/main/AndroidManifest.xml` (share target), `services/runtime/app/intake.py`, `apps/web/src/components/settings/OutlookIntake.tsx`, `docs/INBOX.md` | Tested on fakes; intake measured on fixtures (`evals/runs/mail_intake/report.md`: 12/17 kept, 11/11 decoys dropped). **No real phone, no real mailbox** |
| Nothing is posted or sent without a human tap by default: Approve, the invoice-send tick, the HMRC legal declaration; Autopilot is opt-in, rule-based and undoable; inbox mail is never sent, moved or deleted | `docs/AUTOPILOT.md`, `docs/INBOX.md`, `docs/HMRC.md`, `docs/ACTIONS.md` | Tested on fakes |
| Low cost to try: open-weights Glimmer has no per-call API fee (hosting is the cost); judges can load six months of fictional books with one button | `docs/submission/META_MODELS.md` (Costs), `services/runtime/app/sample_books.py`, `apps/web/src/components/home/SampleBooks.tsx` | Sample books **never run against a real OneDrive** |

No user research, usage numbers or time-saved measurements exist. **Do not claim a saving in hours or pounds.**

## 2. Use of Meta AI tooling

One table with status and evidence for each model: `docs/submission/META_MODELS.md`.

| Claim | Evidence | Status |
|---|---|---|
| Muse Glimmer 30B (open weights) reads receipts, invoices and credit notes into strict JSON, and does Ask, triage, reminders and the planner's words | `services/runtime/app/ai/extract.py`, `services/runtime/app/ai/ask.py`, `docs/META_MODELS.md` | **Measured**: all fields right 85 % clean / 80 % messy on 200 synthetic documents each, mean 17.7 s / 24.1 s (`evals/runs/glimmer_200_v2/summary.json`, `glimmer_messy_200_v2/summary.json`) |
| Muse Spark Open (hosted open weights) is the key-mode second reader: a different prompt, never sees the first answer; code compares six fields | `services/runtime/app/ai/verify.py`, `services/runtime/tests/test_verify.py` | **Measured** as reader and Verifier: all fields 91 % clean / 93 % messy, about 13 s per document (`evals/runs/spark_open_200/summary.json`, `spark_open_messy_200/summary.json`) |
| What the second reading is worth, honestly: Glimmer checking Glimmer caught 8 wrong readings in 400 with 44 false alarms; Spark Open caught 1 with 11; false alarms go to *Needs a look*, the safe direction | `docs/submission/META_MODELS.md` (extraction table), `evals/runs/*/report.md` | Measured, synthetic |
| Glimmer in other roles: Ask figures exact 32/32 with no invented figure shown; triage category 5/5; Autopilot L2 over 467 documents | `evals/runs/ask_40/report.md`, `evals/runs/mail_intake/report.md`, `evals/runs/autopilot_l2/report.md` | Measured, synthetic |
| Muse Spark 1.3 (Meta Model API) is the live server's first model (Contributor mode for the demo), and does the same jobs with the user's own key | `services/runtime/app/ai/extract.py`, `services/runtime/app/ai/providers.py`, `evals/runs/spark13_200/report.md`, `evals/runs/live_checks_2026-11-04/report.md` | **Measured** as reader and Verifier: all fields 95 % clean / 96 % messy on 200 synthetic documents each (`evals/runs/spark13_200`, `spark13_messy_200`); document type 96.5 % of 434 (`evals/runs/classify`). Ask, voice Ask, Home summary, goals note and a scan **run live** on the live server, 4 Nov 2026, not scored |
| Muse Voice Transcribe for spoken Ask | `services/runtime/app/ai/voice.py`, `services/runtime/app/ai/stt.py`, `evals/runs/stt/report.md` | **Measured** on 14 synthetic clips (word error rate 12.7 %, spoken numbers 50 %); **used live** from the Android app on the owner's phone and on the live server with two synthetic-speech clips, 4 Nov 2026 (`evals/runs/live_checks_2026-11-04/report.md`) |
| SAM 3.1 crops the receipt in a phone photo before reading, with the code crop as fallback (`SAM_CROP=1`) | `services/runtime/app/ai/crop.py`, `evals/runs/sam_crop_live/report.md` | **Run live** on 20 synthetic scenes, 4 Nov 2026: a box for 20/20, mean IoU 0.90 against 0.88 for the code crop, median 1.5 s; reading 19/20 either way (no gain on these scenes). Switched on in the live server's settings on 4 Nov 2026, live from its next deploy |
| Muse Image made the brand art | `tools/brand_muse.py`, `apps/web/public/brand/` | Run at build time (12 images) |
| Muse Code (Meta's coding assistant, `muse-spark-1.3`) wrote web and Android screens; 54 `muse/*` branches merged | `docs/PROVENANCE.md` ("How each part was built"), `git log -i --grep='Muse Code'` | In git history |

Say plainly: Spark 1.3, Voice Transcribe and SAM 3.1 have all been called for real on the Meta Model API (reports
above); every accuracy number is on synthetic documents, and real phone photos will score lower.

## 3. Technical depth and execution

| Claim | Evidence | Status |
|---|---|---|
| A strict split: models propose, code decides. VAT boxes, ledger, invoice totals, payments, credit notes, reports, mileage and pay estimates are deterministic code; `packages/ledger` has no model imports | `packages/ledger/src`, `packages/ledger/tests/test_vat.py`, `docs/DEV.md` (Conventions), `docs/ARCHITECTURE.md` | Tested |
| Pipeline: capture, code crop, model read, code repairs and checks, independent second reading, proposal, human Approve, balanced immutable ledger event. The "why" line is code, **not** an LLM reviewer | `services/runtime/app/pipeline.py`, `checks.py`, `approve.py`; `services/runtime/tests/test_books.py`, `test_verify.py` | Tested on fakes; read → approve → VAT boxes run live (our record) |
| Grounded Ask: every figure in an answer is checked against a code-built facts pack and an invented one is replaced; chat actions return an intent only, code prices the lines and a signed card waits for Approve | `services/runtime/app/ai/ask.py`, `facts.py`, `actions.py`, `tests/test_ask.py`, `test_actions.py`, `apps/web/src/components/ask/AskThread.tsx` | Tested; Ask measured (`evals/runs/ask_40/report.md`) |
| HMRC MTD VAT: OAuth with PKCE through a relay that holds only the client secret, fraud-prevention headers, return validation; a fulfilled period cannot be submitted twice | `services/hmrc-relay`, `docs/HMRC.md`, `docs/HMRC_SANDBOX_DEMO.md` | Tested on mocks; **run live against HMRC's sandbox** on 4 Nov 2026 through the public relay with the demo's call sequence (test user, HMRC's sandbox sign-in, obligations, submit, HMRC's receipt with its form bundle number recorded); the live site's VAT card makes a sandbox test user (checked 4 Nov). Never production |
| Money as code: part payments, overpayments, credit notes as reversals with the same VAT codes, credits applied or refunded | `services/runtime/app/settlement.py`, `payments.py`, `credit_notes.py`, `credits.py`, `tests/test_payments.py` | Tested on fakes |
| Bank rules and reconciliation; matching measured (precision 83/83, recall 83/106) | `services/runtime/app/bank_rules.py`, `bank_reconcile.py`, `evals/runs/bank_matching/report.md` | Measured, synthetic |
| Autopilot L2 with a safety eval that found a real bug (21 of 32 re-photographed receipts posted twice), fixed by a same-document rule (0 of 42 after) | `services/runtime/app/autopilot.py`, `evals/runs/autopilot_l2/`, `docs/reviews/autopilot-eval/REVIEW.md` | Measured, Glimmer, synthetic |
| Security: log scrubbing, size caps, rate limit, exact-origin CORS, one-time OAuth state, safe file names | `docs/SECURITY.md`, `services/runtime/tests/test_security.py` | Tested; **not load-tested** |
| Two clients on one stateless runtime: a web app and an Android app (0.3.19+24) with page-by-page parity | `apps/web/src/app`, `apps/mobile/lib/screens`, `apps/mobile/PARITY.md`, `apps/mobile/RELEASE_NOTES.md` | Android run on the owner's own phone (4 Nov 2026) and smoke-tested on the emulator (`docs/reviews/final-audit-4nov/REPORT.md`); no other phones |
| Tests, 4 Nov 2026 (`pytest --collect-only` on `main` at `8debc2e9`): runtime 2789, ledger 101, connectors 67, evals 383, relay 181; Playwright about 300 tests in 84 spec files; Flutter about 470 | `uv run pytest -q`, `apps/web/e2e/*.spec.ts`, `apps/mobile/test`, `docs/HONESTY.md` | Every suite runs on GitHub in `.github/workflows/ci.yml` on every push and PR and was green on that commit (`docs/reviews/ci/REVIEW.md`) |
| Process: every branch reviewed by a second agent before merging, with what was fixed and what remains | `docs/reviews/*/REVIEW.md` (101 reviews on 4 Nov), `docs/PROVENANCE.md` | Documented |

## 4. Demo quality

| Claim | Evidence |
|---|---|
| A 2:56 video (v3) that opens with the provenance line and shows the live site: Review, Talk, Ask, the TrueLayer sandbox bank feed, the HMRC sandbox return, the personal demo and the in-app Meta model switch (the 28 Oct 3:00 script is kept for the record) | `docs/video/SCRIPT_V3.md`, `docs/video/V3_EDIT.md`, `docs/submission/VIDEO_SCRIPT.md` |
| A longer click-by-click walkthrough with the expected figures (Box 4 £8.65, Box 7 £43) | `docs/DEMO.md` |
| The demo's labels are held by an end-to-end test, and every page has a phone-width check | `apps/web/e2e/demo.spec.ts`, `apps/web/e2e/phone.spec.ts` |
| Storyboard stills from the test-mode dry run (stub AI, not proof of a live run) | `docs/submission/shots/` |
| Sample data is fictional and labelled *SAMPLE — FICTIONAL COMPANY* in the product, reports and exports | `apps/web/src/components/DemoBanner.tsx`, `tools/seed_demo.md` |
| Every known gap is written down, so nothing in the video is staged | `docs/HONESTY.md`, `docs/REMAINING.md` |

## The judges' path: the demo sandbox (no sign-in, no two-step verification)

Open **`/judges`** on the web app (also linked as *For judges* in every page's footer and from Connect) and press
**Start the demo**, or press **Try the demo — no sign-in** on the signed-out Home or on Connect. You get your own copy
of six months of books for the fictional Bramblewood Joinery Ltd (labelled SAMPLE — FICTIONAL COMPANY), held in the
runtime's memory for 2 hours; nobody else sees your changes and nothing about you is stored (`services/runtime/app/demo.py`,
`docs/PRODUCTION.md` section 5). What to try, in this order:

1. **Review a receipt**: six documents wait in Review; two need a look (an invoice in euros, a malformed VAT number).
2. **Approve** one: it is posted to the ledger and Books.xlsx.
3. **VAT return**: pick the previous quarter (*Jul–Sep 2026* in early November 2026) for the 9 boxes worked out by code; *Make an HMRC sandbox test user* → *Connect to HMRC sandbox* (HMRC's own sandbox sign-in with that test user) → *Show obligations* (HMRC's 2017 test periods) → *Prepare submission* → tick the declaration → *Submit to HMRC sandbox*: HMRC's own sandbox receipt, no real tax filed (`docs/HMRC_SANDBOX_DEMO.md`). If the sandbox cannot be reached the card says so and simulates instead.
4. **Ask**: "How much VAT do I owe this quarter?"; the figures come from code, the explanation from the server's AI.
5. **Reports**, 6. **Contacts**, 7. **Bank** (two reconciled statements and bank rules; *Connect the test bank* joins TrueLayer's sandbox Mock Bank with its public `john` / `doe` login, `docs/BANK_FEED_SANDBOX_DEMO.md`).

*Reset demo* (banner and sidebar) starts again from fresh books; *Set up your own books →* leaves the demo for the real
Microsoft sign-in, which sets up books in your own OneDrive (HMRC through the sandbox). Simulated in a demo: email is
never sent ("Sent (demo — not actually sent)"), and the Companies House and VAT-number look-ups are off. Real: the app, the
checks, the ledger and VAT arithmetic, the AI the server runs, HMRC's sandbox and TrueLayer's sandbox. Why a sandbox rather than a shared sign-in: see
`docs/HONESTY.md` ("Demo sandbox") and the branch review (REVIEW.md, "Why a sandbox").

## How to run it in 10 minutes (test mode, no accounts)

Test mode uses in-memory fakes for OneDrive, Outlook, calendar and contacts and a **stub AI** that returns the gold fields
for the gold receipt images and nothing for any other image. It proves the plumbing, not the models, not Microsoft and not
HMRC (`docs/DEV.md`, "Runtime test mode"). Needs Python 3.12, `uv`, Node, pnpm 11. "10 minutes" assumes a warm cache and was
not timed.

**A. The automated route (documented in `docs/DEV.md`)**

```bash
uv sync --all-packages --all-extras
uv run pytest -q                      # all packages: no network, no keys
cd apps/web
pnpm install
pnpm exec playwright install chromium
pnpm run e2e                          # builds the test-mode export, starts both servers, runs the browser tests
```

Playwright starts the runtime on :8781 and a static host for `out-e2e/` on :3100 itself. On Windows set `E2E_PYTHON` to
the venv's `python.exe` (`docs/DEV.md`).

**B. Click through it yourself (composed from `apps/web/playwright.config.ts`, `e2e/build.mjs`, `e2e/serve.mjs`)**

```bash
# terminal 1: runtime in test mode
ACCNOMOS_TEST_MODE=1 PORT=8781 CORS_ORIGINS=http://127.0.0.1:3100 \
  uv run --package accnomos-runtime uvicorn app.main:app --app-dir services/runtime --host 127.0.0.1 --port 8781
# terminal 2: test-mode web export, then serve it
cd apps/web && pnpm install && pnpm run e2e:build && node e2e/serve.mjs
```

Open `http://127.0.0.1:3100`, press **Sign in** (a fake account; nothing leaves your machine). Then:

1. **Connect:** folder setup completes against the fake OneDrive.
2. **Review:** the stub AI only reads gold receipts. List them at `http://127.0.0.1:8781/__test/gold`, save one from
   `/__test/gold/<name>.png`, then **Add a receipt** and **Scan 00 Inbox now**. `apps/web/public/sample-receipt.png` will
   **not** be read in test mode.
3. Approve it, then **VAT return**. Test "today" is pinned to 27 Oct 2026 and the gold receipts are dated Jul–Sep, so pick
   **Jul–Sep 2026** in the picker to see the boxes move.
4. **Ask**, **Invoices** (create → preview → send: the fake sender only records), **Bank** (import
   `evals/gold/bank/barclays.csv`), **Jobs**, **Vehicles**, **Payroll**.

Route B was checked against the config files by reading, not executed in this refresh. **Not reproducible without
accounts:** real Microsoft sign-in, real Glimmer or Spark output, the HMRC sandbox, Outlook and the Android app. For a
real-model run see `docs/DEV.md` and `evals/` (`python -m harness.run_extraction --mode local --messy`).
