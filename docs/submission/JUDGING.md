# Judging: how Accnomos maps to the likely criteria, and how to run it

The hackathon's exact rubric was not available when this was drafted, so the five headings below are the usual ones (technical depth, use of Meta models,
impact, completeness, honesty). **Replace them with the official wording once you have it.** Every claim links to a file on `main`.
Status words follow `README.md`: *run live* = maintainers' own run, no log committed; *tested on fakes* = automated tests against in-memory fakes or stubs.

## 1. Technical depth

| Claim | Evidence | Strength |
|---|---|---|
| A strict split: models propose, code decides. VAT nine boxes, ledger, invoice totals, mileage, pay estimates are deterministic code; `packages/ledger` has no model imports | `packages/ledger/src`, `packages/ledger/tests/test_vat.py`, `docs/DEV.md` (Conventions), `docs/ARCHITECTURE.md` | Tested |
| Pipeline: scan → optional code crop → model read → code checks → independent verifier → proposal → human Approve → balanced ledger event → filing. Reviewer step is code, **not** an LLM | `docs/ARCHITECTURE.md` (pipeline table), `services/runtime/app/{pipeline,checks,approve}.py`, `tests/test_books.py`, `test_checks_journal.py`, `test_verify.py` | Tested on fakes; read → approve → VAT boxes run live |
| Stateless runtime; books are append-only event files in the user's OneDrive, rebuilt into `Books.xlsx` (12 sheets) | `docs/ARCHITECTURE.md` (folder layout), `services/runtime/app/projection.py`, `tests/test_integration.py`, `test_bank_projection.py` | Tested on fakes; one live run on a personal account |
| Grounding guards: every figure in an Ask answer, a reminder, a triage reply or a planner rationale is checked against code-built facts; chat actions return an intent only, code finds names and prices lines, a signed card waits for Approve | `services/runtime/app/ai/ask.py`, `actions.py`, `tests/test_ask.py`, `test_actions.py`, `docs/ACTIONS.md` | Tested with stubbed models |
| HMRC MTD VAT: OAuth with PKCE through a relay that holds only the client secret, fraud-prevention headers v3.3, return validation (box 3 = 1 + 2, box 5 = abs(3 − 4)) | `services/hmrc-relay`, `docs/HMRC.md`, relay tests (HMRC mocked) | Tested on mocks; **never run against HMRC's sandbox from the app** |
| Security: log scrubbing, size caps, rate limit, exact-origin CORS, one-time OAuth state, safe file names, hardened containers | `docs/SECURITY.md`, `tests/test_security.py`, `test_validation.py`, `test_deploy_hardening.py` | Tested; **not deployed or load-tested** |
| Breadth: bank CSV matching, sales invoicing with PDF and Outlook send, jobs, mileage, pay-run estimates, Outlook intake and triage, day planner, PWA and Android app | README feature table, matching `services/runtime/tests/test_*.py` | Tested on fakes |
| Process: 24 reviewed branches, each with a second-agent `REVIEW.md` listing what was fixed and what remains | `docs/reviews/*/REVIEW.md` (e.g. `loose-ends-1` found and fixed a double-billing bug) | Documented |

Test counts differ across the docs (runtime 607 in `README.md`, 638 passed and 1 skipped in `docs/reviews/loose-ends-1/REVIEW.md`; relay 100 versus 102). A static count
of `def test_` in `services/runtime/tests` gives 439 functions, because many tests are parametrised. **Quote none of these numbers until you have run `uv run pytest -q` yourself.**

## 2. Use of Meta models

| Claim | Evidence |
|---|---|
| Six Meta models are wired in, each at a named file and with a stated status | `docs/submission/META_MODELS.md`, `docs/META_MODELS.md`, `docs/ARCHITECTURE.md` (models table) |
| Muse Glimmer 30B (open weights, Ollama) does the receipt reading and verifier in local mode, so documents need not leave the machine; measured 22 s mean per document | `services/runtime/app/ai/extract.py`, `verify.py`; `evals/REPORT_glimmer_messy_200_2026-10-27.md` |
| Real evals against a synthetic gold set: 200 messy documents, all fields right 88 %, sale or purchase side 100 %, status 93 %. Weakness reported: VAT-inclusive receipts with net read as the total | the report above; failures listed in `docs/META_MODELS.md` |
| Two-model design: the verifier is meant to be a different model (Muse Spark Open on Baseten) with a different prompt; code compares six fields | `verify.py`, `docs/AUTOPILOT.md`. **Only Glimmer-checking-Glimmer has run (20 documents, 0 extra catches); Baseten is unit-tested only** |
| Voice input via Muse Voice Transcribe, Ask grounded by code | `app/ai/voice.py`, `tests/test_voice.py`. **Request format unverified; no live mic run** |
| Muse Image produced the brand artwork; SAM 3.1 crop exists but is off by default | `tools/brand_muse.py`, `app/ai/crop.py`. SAM **never run live** |

Say plainly in the submission: the live-proven Meta model is Glimmer; Spark 1.3, Spark Open, Voice and SAM are integrated and stub-tested but unproven against the real endpoints.

## 3. Impact

| Claim | Evidence |
|---|---|
| Target user: a VAT-registered UK small business or sole trader doing its own bookkeeping | `README.md`, `docs/DEMO.md` |
| Owner keeps the records: nothing in an Accnomos database, so disconnecting loses nothing | `docs/ARCHITECTURE.md` ("Runtime state: none") |
| Nothing is sent or posted without a human tap: Approve, the invoice-send tick, the HMRC legal declaration; Accnomos never sends inbox mail, only drafts | `docs/AUTOPILOT.md`, `docs/INBOX.md`, `docs/HMRC.md` |

No user research, usage numbers or time-saved measurements exist in the repo. **Do not claim a saving in hours or pounds.** The honest impact statement is the design: low cost to try, data stays with the owner.

## 4. Completeness

| Claim | Evidence |
|---|---|
| Web PWA covers Home, Review, Ask, Invoices, Bank, VAT return, Jobs, Payroll, Contacts, Vehicles, Files, Settings | `apps/web/src/app`, README layout table |
| Android app: sign-in, capture, Review, Ask with mic, Home, VAT, and More screens | `apps/mobile/lib/screens` — **Flutter analyse and test have never been run** |
| End-to-end suite: Playwright against a test-mode runtime with fakes, one spec per page, plus phone-width checks | `apps/web/e2e/*.spec.ts`, `docs/DEV.md`; CI file `.github/workflows/e2e.yml` has **never run on GitHub** |
| Seeded demo: `tools/seed_demo.py` fills a throwaway account with six months of fictional books | `tools/seed_demo.md`, `tests/test_seed_demo.py`; **not yet run against a real OneDrive** |
| Not built: production HMRC filing, Google Drive, credit notes, RTI, `muse-wonder` multi-step planning | `README.md`, `docs/REMAINING.md` |

The e2e test count is stated as 23 in one README row and 44 in another; neither was re-run in this pass.

## 5. Honesty

| Claim | Evidence |
|---|---|
| A flat list of every known gap, plus severity-ordered table | `docs/HONESTY.md`, `docs/REMAINING.md` |
| Every README row has a "NOT verified" column | `README.md` feature table |
| Synthetic demo data labelled "SAMPLE — FICTIONAL COMPANY" in the product | `apps/web/src/components/DemoBanner.tsx` (named in `docs/HONESTY.md`) |
| Real versus faked is spelled out: only sign-in, folder setup and read → approve → ledger → VAT boxes ran live, by the maintainers, with no committed log | `docs/HONESTY.md` ("What is real, and what is not") |
| AI-assisted authorship disclosed: Claude, Muse Code and a local Qwen wrote code; every merge was reviewed | `README.md` (Honesty notes), `docs/reviews/` |

**Housekeeping before judges read the README:** `README.md` still contains stale leftover tables after the main feature table (a second *Books.xlsx* row with
fewer sheets, "status 80 %" next to "88 %", a table where *Sales invoicing* is "not started", "runtime 271 tests"). They contradict the top table. Delete them
or judges will find the contradiction (see `CHECKLIST.md`).

## How to run it in 10 minutes (test mode, no accounts)

Test mode uses in-memory fakes for OneDrive, Outlook, calendar and contacts and a **stub AI** that returns the gold fields for the gold receipt images and nothing for
any other image. It proves the plumbing, not the models, not Microsoft and not HMRC (`docs/DEV.md`, "Runtime test mode"). Needs Python 3.12, `uv`, Node, pnpm 11.
"10 minutes" assumes a warm cache and was not timed; the first `pnpm install` and Chromium download can take longer.

**A. The automated route (documented in `docs/DEV.md`)**

```bash
uv sync --all-packages --all-extras
uv run pytest -q                      # all packages: no network, no keys
cd apps/web
pnpm install
pnpm exec playwright install chromium
pnpm run e2e                          # builds the test-mode export, starts both servers, runs the browser tests
```

Playwright starts the runtime on :8781 and a static host for `out-e2e/` on :3100 itself. On Windows set `E2E_PYTHON` to the venv's `python.exe` (`docs/DEV.md`).

**B. Click through it yourself (composed from `apps/web/playwright.config.ts`, `e2e/build.mjs`, `e2e/serve.mjs`; DEV.md only documents route A)**

```bash
# terminal 1: runtime in test mode
ACCNOMOS_TEST_MODE=1 PORT=8781 CORS_ORIGINS=http://127.0.0.1:3100 \
  uv run --package accnomos-runtime uvicorn app.main:app --app-dir services/runtime --host 127.0.0.1 --port 8781
# terminal 2: test-mode web export, then serve it
cd apps/web && pnpm install && pnpm run e2e:build && node e2e/serve.mjs
```

Open `http://127.0.0.1:3100`, press **Sign in** (a fake account; nothing leaves your machine). Then:

1. **Connect:** folder setup completes against the fake OneDrive.
2. **Review:** the stub AI only reads gold receipts. List them at `http://127.0.0.1:8781/__test/gold`, save one from `/__test/gold/<name>.png`, then **Add a receipt** and **Scan 00 Inbox now**.
   `apps/web/public/sample-receipt.png` will **not** be read in test mode.
3. **Approve (post to books)**, then **VAT return**. Test "today" is pinned to 27 Oct 2026 and the gold receipts are dated Jul–Sep, so pick **Jul–Sep 2026** in the picker to see the boxes move.
4. **Ask**, **Invoices** (create → preview → send: the fake sender only records), **Bank** (import `evals/gold/bank/barclays.csv`), **Jobs**, **Vehicles**, **Payroll**.

I have **not** executed A or B in this pass (`uv run` needed approval that was not available); they are checked against `docs/DEV.md` and the config files by reading.
Run A once yourself before submitting, and update the line above.

**Not reproducible without accounts:** real Microsoft sign-in, real Glimmer or Spark output, HMRC sandbox, Outlook, the Android app. For a real-model run use `docs/DEV.md` (local Ollama with `muse-glimmer:30b`, or your own Meta key) and `evals/` (`python -m harness.run_extraction --mode local --messy`).
