# Judging: how Accnomos maps to the likely criteria, and how to run it

Refreshed 27 Oct 2026. The hackathon's exact rubric was not available when this was drafted, so the five headings below are the usual ones (technical depth, use of Meta models, impact, completeness, honesty). **Replace them with the official wording once you have it.** Every claim names a path in this repo.
Status words follow `README.md`: *run live* = the maintainers' own run, no log committed; *measured* = a committed report; *tested on fakes* = automated tests against in-memory fakes or stubs (this proves our logic, not Microsoft, Meta or HMRC).

## 1. Technical depth

| Claim | Evidence | Strength |
|---|---|---|
| A strict split: models propose, code decides. VAT boxes, ledger, invoice totals, payments, credit notes, reports, mileage and pay estimates are deterministic code; `packages/ledger` has no model imports | `packages/ledger/src`, `packages/ledger/tests/test_vat.py`, `docs/DEV.md` (Conventions), `docs/ARCHITECTURE.md` | Tested |
| Pipeline: scan, optional code crop, model read, code repairs and checks, independent verifier, proposal, human Approve, balanced ledger event. The reviewer step is code, **not** an LLM | `docs/ARCHITECTURE.md`, `services/runtime/app/{pipeline,checks,approve}.py`, `services/runtime/tests/test_books.py`, `test_checks_journal.py`, `test_verify.py` | Tested on fakes; read, approve and VAT boxes run live (our record) |
| Stateless runtime; books are append-only event files in the user's OneDrive, rebuilt into a 13-sheet `Books.xlsx` | `docs/ARCHITECTURE.md`, `services/runtime/app/projection.py`, `tests/test_integration.py`, `test_bank_projection.py` | Tested on fakes; one live run on a personal account |
| Money as code: part payments, overpayments, credit notes (a reversal with the same VAT codes), credits applied or refunded, supplier bills paid, one bank movement counted once | `services/runtime/app/{settlement,payments,credit_notes,credits}.py`, `tests/test_payments.py`, `docs/reviews/part-payments/REVIEW.md`, `docs/reviews/payments-2/REVIEW.md` | Tested on fakes |
| A second gold set built for the ledger: 40 supplier credit notes, 40 part-paid or overpaid sales invoices, 10 overlapping bank statement pairs, all SAMPLE, sums checked in code | `evals/gold/ledger2/`, `evals/tests/test_gold_ledger2.py` (92 tests), `services/runtime/tests/test_gold_ledger2_runtime.py` (90 tests), `docs/reviews/gold-ledger2/REVIEW.md` | Tested |
| Bank rules and reconciliation: contains / equals / a safe regex subset that refuses nested quantifiers, first match wins; exact invoice match; AI coding labelled as such and posted only through Review approval; overlap-safe re-imports | `services/runtime/app/{bank_rules,bank_reconcile}.py`, `tests/test_bank_rules.py`, `apps/web/e2e/bank-rules.spec.ts` | Tested; AI coding on the test stub only |
| Matching measured: six statements, precision 83/83, recall 83/106 (part payments were unsupported when it ran) | `evals/runs/bank_matching/report.md` | Measured, synthetic |
| Reports and audit trail: profit and loss, ageing, VAT, 12-month trend with no model call; every audit line shown with who and a sentence; both read-only | `services/runtime/app/{reports,routes_reports,audit_view}.py`, `tests/test_reports.py`, `tests/test_audit.py`, `docs/reviews/reports/REVIEW.md`, `docs/reviews/audit-trail/REVIEW.md` | Tested on fakes |
| Grounding guards: every figure in an Ask answer, reminder, triage reply or planner rationale is checked against code-built facts; chat and voice actions return an intent only, code finds names and prices lines in pence, a signed card waits for Approve and runs once | `services/runtime/app/ai/ask.py`, `actions.py`, `facts.py`, `tests/test_ask.py`, `test_actions.py`, `docs/ACTIONS.md` | Tested with stubbed models; Ask measured, 40 prompts (`evals/runs/ask_40/report.md`) |
| Autopilot L2 with a measured safety eval; the eval found that re-photographed receipts were posted twice (21 of 32), a same-document rule was added, and the re-run shows 0 of 42 | `services/runtime/app/autopilot.py`, `evals/harness/autopilot_sim.py`, `evals/runs/autopilot_l2/` (report, `before_tightening/`), `docs/reviews/autopilot-eval/REVIEW.md` | Measured, Glimmer only, synthetic |
| HMRC MTD VAT: OAuth with PKCE through a relay that holds only the client secret, fraud-prevention headers v3.3, return validation; obligations posted to the runtime so a fulfilled period cannot be submitted again | `services/hmrc-relay`, `docs/HMRC.md`, relay tests (HMRC mocked) | Tested on mocks; relay configured for the sandbox and the owner has connected once (27 Oct); **no end-to-end sandbox submission recorded** |
| Security: log scrubbing, size caps, rate limit, exact-origin CORS, strict bodies, one-time OAuth state, safe file names, hardened containers | `docs/SECURITY.md`, `tests/test_security.py`, `test_validation.py`, `test_deploy_hardening.py` | Tested; **not load-tested** |
| Process: 46 reviewed branches, each with a second-agent `REVIEW.md` listing what was fixed and what remains | `docs/reviews/*/REVIEW.md` (e.g. `loose-ends-1` found and fixed a double-billing bug) | Documented |

Test counts on `main`, 27 Oct 2026 (as given by the owner that day): runtime and packages 1,176 passed (1 skipped), evals 258, relay 102, Playwright 195, Flutter 158. `docs/HONESTY.md` and `README.md` quote older figures until their own branches merge; re-run before quoting.

## 2. Use of Meta models

One table, with status and evidence path for each model: `docs/submission/META_MODELS.md`.

| Claim | Evidence |
|---|---|
| Six Meta models are wired in, each at a named file with a stated status | `docs/submission/META_MODELS.md`, `docs/META_MODELS.md`, `docs/ARCHITECTURE.md` |
| Muse Glimmer 30B (open weights, Ollama on our DGX Spark) reads receipts and does the other text tasks locally, so documents need not leave the machine; mean 22 s per document | `services/runtime/app/ai/extract.py`, `verify.py`; `evals/REPORT_glimmer_messy_200_2026-10-27.md` |
| Real evals on a synthetic gold set: 200 messy documents, all fields right 88 %, side 100 %, status 93 %; weakness reported: VAT-inclusive receipts with net read as the total | the report above; `docs/META_MODELS.md` |
| Glimmer in other roles, measured: Ask figures exact 32/32 with no invented figure shown; inbox triage category 5/5; Autopilot L2 over 467 documents per mode | `evals/runs/ask_40/report.md`, `evals/runs/mail_intake/report.md`, `evals/runs/autopilot_l2/report.md` |
| Two-model design: in key mode the verifier is Muse Spark Open on Baseten with a different prompt; code compares six fields. Wired 27 Oct: Baseten's `/v1/models` lists the id and one real call read a gold receipt in 7 s. The 200-receipt Spark Open eval is **[pending: evals/runs/spark_open_200]** | `services/runtime/app/ai/verify.py`, `services/runtime/tests/test_verify.py`; [pending: evals/runs/spark_open_200] |
| What the verifier is worth, honestly: Glimmer checking Glimmer, 20 documents, 0 extra catches; in the Autopilot eval it removed one false post on clean documents and cost 16 correct posts | `evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md`, `docs/reviews/autopilot-eval/REVIEW.md` |
| Voice input via Muse Voice Transcribe feeds the same grounded Ask and actions | `services/runtime/app/ai/voice.py`, `tests/test_voice.py`. **Request shape unverified; no live mic run** |
| Muse Image made the brand art; SAM 3.1 crop exists, off by default; the code crop it falls back to is measured (IoU 0.88 against 0.48) | `tools/brand_muse.py`, `services/runtime/app/ai/crop.py`, `evals/REPORT_crop_code_20_2026-10-27.md`. SAM **never run live** |

Say plainly in the submission: every measured number is Glimmer 30B; Spark 1.3, Voice and SAM are integrated and stub-tested but have not been called for real; Spark Open has one live call and an eval still running.

## 3. Impact

| Claim | Evidence |
|---|---|
| Target user: a VAT-registered UK small business or sole trader doing its own bookkeeping | `README.md`, `docs/DEMO.md` |
| The owner keeps the records: nothing in an Accnomos database, so disconnecting loses nothing | `docs/ARCHITECTURE.md` ("Runtime state: none") |
| Nothing is sent or posted without a human tap by default: Approve, the invoice-send tick, the HMRC legal declaration; Autopilot is opt-in, rule-based and undoable; Accnomos never sends inbox mail, only drafts | `docs/AUTOPILOT.md`, `docs/INBOX.md`, `docs/HMRC.md` |
| Open weights option: Glimmer keeps documents off third-party model APIs (here, on our own hardware) | `docs/submission/META_MODELS.md` |

No user research, usage numbers or time-saved measurements exist in the repo. **Do not claim a saving in hours or pounds.** The honest impact statement is the design: low cost to try, data stays with the owner.

## 4. Completeness

| Claim | Evidence |
|---|---|
| Web app covers Home, Review, Ask, Invoices, Bank, VAT return, Jobs, Payroll, Reports, Contacts, Vehicles, Files, Audit trail, Settings | `apps/web/src/app`, README layout table |
| Android app 0.3.2+5: sign-in, capture, Review, Ask with mic and action cards, Home, VAT, and More (Files, Contacts with Add from phone, Invoices, Jobs, Vehicles, Bank, Payroll, Reports, Audit trail). `flutter analyze` and `flutter test` (158 tests) run on every Android merge. The Play app-signing hash is registered in Entra (27 Oct) and in builds from 0.3.1+4; the Play production track has build 1 in review. **No real-phone sign-in is recorded** | `apps/mobile/lib/screens`, `apps/mobile/test`, `apps/mobile/RELEASE_NOTES.md`, `apps/mobile/pubspec.yaml` |
| End-to-end suite: Playwright against a test-mode runtime with fakes, one spec per page (29 spec files), phone-width and accessibility checks, and the demo as one flow | `apps/web/e2e/*.spec.ts`, `docs/DEV.md`, `.github/workflows/e2e.yml` (**never run on GitHub** per `docs/HONESTY.md`) |
| Seeded demo: `tools/seed_demo.py` fills a throwaway account with six months of fictional books | `tools/seed_demo.md`, `tests/test_seed_demo.py`; **not yet run against a real OneDrive** |
| Not built: production HMRC filing, Google Drive, RTI payroll, `muse-wonder` multi-step planning; Apply credit, Refund and paying bills are web only | `README.md`, `docs/REMAINING.md` |

## 5. Honesty

| Claim | Evidence |
|---|---|
| A flat list of every known gap, plus a severity-ordered table | `docs/HONESTY.md`, `docs/REMAINING.md` |
| Every README feature row has a "NOT verified" column | `README.md` feature table |
| Synthetic demo data labelled "SAMPLE — FICTIONAL COMPANY" in the product, reports and exports | `apps/web/src/components/DemoBanner.tsx`, `docs/reviews/reports/REVIEW.md` |
| Real versus faked is spelled out: only sign-in, folder setup, read to approve to ledger to VAT boxes, and the Glimmer evals ran for real, with no committed log for the live runs | `docs/HONESTY.md` ("What is real, and what is not") |
| Evals report their failures and what they do not show: Autopilot's 17 false posts and their cause, the earlier 21 double posts, the bank matcher's 23 misses, intake's 5 misses, Ask's declined and unanswerable rows | `evals/runs/*/report.md`, `docs/reviews/autopilot-eval/REVIEW.md` |
| AI-assisted authorship disclosed: Claude, Muse Code and a local Qwen wrote code; every merge was reviewed | `README.md` (Honesty notes), `docs/reviews/` |

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

In the first review pass (before this refresh) the `pytest` half of A was run (with the shared venv's `pytest` rather than `uv run`, which needed approval); everything passed. The Playwright
half of A and all of B were **not** executed; they are checked against `docs/DEV.md` and the config files by reading. Run A once yourself before submitting.

**Not reproducible without accounts:** real Microsoft sign-in, real Glimmer or Spark output, HMRC sandbox, Outlook, the Android app. For a real-model run use `docs/DEV.md` (local Ollama with `muse-glimmer:30b`, or your own Meta key) and `evals/` (`python -m harness.run_extraction --mode local --messy`).
