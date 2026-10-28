# Judging: every criterion mapped to evidence, and how to run it

Refreshed 28 Oct 2026 against the official criteria: **Impact, Use of Meta AI tooling, Technical depth and execution, and
Demo quality, weighted equally.** Every claim names a path in this repo; nothing here goes beyond `docs/HONESTY.md`.
Status words: *run live* = the maintainers' own run, no log committed; *measured* = a committed report under `evals/`;
*tested on fakes* = automated tests against in-memory fakes or stubs (this proves our logic, not Microsoft, Meta or HMRC).

**Provenance.** Only the owner's DGX Spark with Ollama predates the event; the first commit is 6 h 29 min after kickoff,
and every merge has a second-agent review. Timestamps, commits per day and how each part was built: `docs/PROVENANCE.md`.

**Not on `main` on 28 Oct** (so not claimed below): the month-end close agent, company / sole-trader / personal profiles,
the Meta models panel with Glimmer on Modal, and the no-sign-in `/judges` page. iPhone is not built.

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
| Muse Spark Open on Baseten is the key-mode second reader: a different prompt, never sees the first answer; code compares six fields | `services/runtime/app/ai/verify.py`, `services/runtime/tests/test_verify.py` | **Measured** as reader and Verifier: all fields 91 % clean / 93 % messy, about 13 s per document (`evals/runs/spark_open_200/summary.json`, `spark_open_messy_200/summary.json`) |
| What the second reading is worth, honestly: Glimmer checking Glimmer caught 8 wrong readings in 400 with 44 false alarms; Spark Open caught 1 with 11; false alarms go to *Needs a look*, the safe direction | `docs/submission/META_MODELS.md` (extraction table), `evals/runs/*/report.md` | Measured, synthetic |
| Glimmer in other roles: Ask figures exact 32/32 with no invented figure shown; triage category 5/5; Autopilot L2 over 467 documents | `evals/runs/ask_40/report.md`, `evals/runs/mail_intake/report.md`, `evals/runs/autopilot_l2/report.md` | Measured, synthetic |
| Muse Spark 1.3 (Meta Model API, the user's key) does the same jobs without a GPU | `services/runtime/app/ai/extract.py` (key mode), `services/runtime/tests/` | **Unit-tested only**; never called live by us |
| Muse Voice Transcribe for spoken Ask; SAM 3.1 crop (off by default) | `services/runtime/app/ai/voice.py`, `services/runtime/app/ai/crop.py` | **Unit-tested only; never run live**. The code crop SAM falls back to is measured (IoU 0.88 against 0.48, `evals/REPORT_crop_code_20_2026-10-27.md`) |
| Muse Image made the brand art | `tools/brand_muse.py`, `apps/web/public/brand/` | Run at build time (12 images) |
| Muse Code (Meta's coding assistant, `muse-spark-1.3`) wrote web and Android screens; 54 `muse/*` branches merged | `docs/PROVENANCE.md` ("How each part was built"), `git log -i --grep='Muse Code'` | In git history |

Say plainly: Spark 1.3, Voice and SAM are integrated and stub-tested but have not been called for real; every number is
on synthetic documents, and real phone photos will score lower.

## 3. Technical depth and execution

| Claim | Evidence | Status |
|---|---|---|
| A strict split: models propose, code decides. VAT boxes, ledger, invoice totals, payments, credit notes, reports, mileage and pay estimates are deterministic code; `packages/ledger` has no model imports | `packages/ledger/src`, `packages/ledger/tests/test_vat.py`, `docs/DEV.md` (Conventions), `docs/ARCHITECTURE.md` | Tested |
| Pipeline: capture, code crop, model read, code repairs and checks, independent second reading, proposal, human Approve, balanced immutable ledger event. The "why" line is code, **not** an LLM reviewer | `services/runtime/app/pipeline.py`, `checks.py`, `approve.py`; `services/runtime/tests/test_books.py`, `test_verify.py` | Tested on fakes; read → approve → VAT boxes run live (our record) |
| Grounded Ask: every figure in an answer is checked against a code-built facts pack and an invented one is replaced; chat actions return an intent only, code prices the lines and a signed card waits for Approve | `services/runtime/app/ai/ask.py`, `facts.py`, `actions.py`, `tests/test_ask.py`, `test_actions.py`, `apps/web/src/components/ask/AskThread.tsx` | Tested; Ask measured (`evals/runs/ask_40/report.md`) |
| HMRC MTD VAT: OAuth with PKCE through a relay that holds only the client secret, fraud-prevention headers, return validation; a fulfilled period cannot be submitted twice | `services/hmrc-relay`, `docs/HMRC.md` | Tested on mocks; the owner has connected once; **no end-to-end sandbox submission recorded** |
| Money as code: part payments, overpayments, credit notes as reversals with the same VAT codes, credits applied or refunded | `services/runtime/app/settlement.py`, `payments.py`, `credit_notes.py`, `credits.py`, `tests/test_payments.py` | Tested on fakes |
| Bank rules and reconciliation; matching measured (precision 83/83, recall 83/106) | `services/runtime/app/bank_rules.py`, `bank_reconcile.py`, `evals/runs/bank_matching/report.md` | Measured, synthetic |
| Autopilot L2 with a safety eval that found a real bug (21 of 32 re-photographed receipts posted twice), fixed by a same-document rule (0 of 42 after) | `services/runtime/app/autopilot.py`, `evals/runs/autopilot_l2/`, `docs/reviews/autopilot-eval/REVIEW.md` | Measured, Glimmer, synthetic |
| Security: log scrubbing, size caps, rate limit, exact-origin CORS, one-time OAuth state, safe file names | `docs/SECURITY.md`, `services/runtime/tests/test_security.py` | Tested; **not load-tested** |
| Two clients on one stateless runtime: a web app and an Android app (0.3.5+10) with page-by-page parity | `apps/web/src/app`, `apps/mobile/lib/screens`, `apps/mobile/PARITY.md`, `apps/mobile/RELEASE_NOTES.md` | Android **never run on a real device** |
| Tests, 28 Oct gates (owner's figures): runtime 1260, evals 258, relay 119, Playwright 208 (36 spec files), Flutter 248 | `uv run pytest -q`, `apps/web/e2e/*.spec.ts`, `apps/mobile/test`, `docs/HONESTY.md` | Re-run before quoting; every suite runs on GitHub in `.github/workflows/ci.yml` on every push and PR (`docs/reviews/ci/REVIEW.md`) |
| Process: every branch reviewed by a second agent before merging, with what was fixed and what remains | `docs/reviews/*/REVIEW.md` (54 reviews), `docs/PROVENANCE.md` | Documented |

## 4. Demo quality

| Claim | Evidence |
|---|---|
| A 3:00 script that follows one receipt from the phone to the VAT boxes and the HMRC sandbox, opening with the provenance line, with captions and a fallback for every shot not yet run live | `docs/submission/VIDEO_SCRIPT.md` |
| A longer click-by-click walkthrough with the expected figures (Box 4 £8.65, Box 7 £43) | `docs/DEMO.md` |
| The demo's labels are held by an end-to-end test, and every page has a phone-width check | `apps/web/e2e/demo.spec.ts`, `apps/web/e2e/phone.spec.ts` |
| Storyboard stills from the test-mode dry run (stub AI, not proof of a live run) | `docs/submission/shots/` |
| Sample data is fictional and labelled *SAMPLE — FICTIONAL COMPANY* in the product, reports and exports | `apps/web/src/components/DemoBanner.tsx`, `tools/seed_demo.md` |
| Every known gap is written down, so nothing in the video is staged | `docs/HONESTY.md`, `docs/REMAINING.md` |

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
