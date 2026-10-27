# Review: `claude/vat-periods`

Second-agent review of the VAT-periods task (`TASK_BRIEF.md`). Reviewed on 27 Oct 2026.

## What was checked

- `pytest -q`: `services/runtime` 548 passed, `services/hmrc-relay` 100 passed, `packages/ledger` 32 passed,
  `packages/connectors` 28 passed.
- `cd apps/web && pnpm run build`: passes, and `/vat` is prerendered.
- The full diff against `origin/main`: runtime routes (`/books/vat`, `/books/vat/periods`, `/books/scan`, `/extract`, Ask),
  `checks.check_date_in_period`, `deadlines.period_id/period_from_id/recent_periods`, `vat_cycle.py`, the web picker
  (`VatPeriodPicker`, `lib/vat-period.ts`, `LiveVat`, `ConnectHmrc`, `AskThread`), the Android `VatScreen`/client/model,
  `tools/make_sample_receipt.py`, the regenerated `apps/web/public/sample-receipt.png`, README, `docs/DEMO.md` and
  `docs/HONESTY.md`.
- Product rules:
  - Nothing is stored server-side. The picked period lives in the browser's sessionStorage, and "submitted" is read
    from the user's own `05 VAT returns/`.
  - Out-of-period dates only ever produce a warning and never change the ledger date (tested).
  - Box amounts come from `compute_vat_return`, so pence are handled in code and no model is involved. The phone does no VAT maths.
  - The receipt image says "SAMPLE — FICTIONAL COMPANY" and is dated 2026-11-02. I checked the image by eye.
  - `tools/seed_demo.py` is untouched.
- Both sides of each boundary, the 6 April edge, the previous/earlier/later wording, period ids, the 8+1 list,
  submitted status and `can_submit` were already tested in `services/runtime/tests/test_vat_periods.py`.

## What I fixed

- `974b092`: the implementer's `wip` checkpoint had committed about 150 build artefacts (`apps/web/out-e2e/`, including a copy
  of the old receipt) and `apps/web/test-results/`. I removed them from the index and added both to `apps/web/.gitignore`.
- `661abfc`: removed `routes_vat.quarter_bounds` and its test. The function defaulted to the *previous* calendar
  quarter and nothing in the app called it any more. I also added a route test showing that `POST /books/scan` takes the VAT
  settings from the query (`months=1`) and warns on a document dated last month, without failing it.
- `f882a94`: `docs/HONESTY.md` said the live card shows the `26A4` period key, but it no longer does. `docs/DEMO.md` gave the
  relay test count as 39; it is now 100.

## What remains

- `flutter analyze` was **not run**: there is no Flutter SDK on this machine. `runtime_client.dart` uses the null-aware map
  element `{'period': ?period}`, which needs Dart ≥ 3.8 (pubspec says `^3.13.7`, so it should be fine). Run it before merging.
- `ruff` was not run (no permission in this session).
- Android sends no VAT stagger because the phone has no such setting, so its picker always shows calendar quarters. This is
  disclosed in README and HONESTY.
- "Submitted" status comes only from receipts our relay submission saved in `05 VAT returns/`. HMRC's obligations
  endpoint is not used by `/books/vat/periods`, because the runtime holds no HMRC token. The brief's title mentions "obligations from
  HMRC", but this part is not built and the docs say so.
- The brief names `evals/gold/sample-receipt.png`, but that path does not exist in this repo. Only
  `apps/web/public/sample-receipt.png` (the file `docs/DEMO.md` uses) was regenerated.
- `GET /books/vat` and `/books/vat/periods` accept `?today=`, so a client can move "current" and with it `can_submit`.
  This is harmless, because HMRC decides what can be filed, but the web gate is advisory only.
- For monthly returns, `period_key_for` gives the same placeholder key to all three months of a quarter (for example `26A4` for Oct, Nov and Dec).
  This was already the case before this branch, and the submission uses HMRC's key.
- Nothing on this branch has been run against a real OneDrive or the HMRC sandbox.

## How to verify by hand

Start the runtime (`docs/DEV.md`, :8780) and the web app (:3000), sign in with a throwaway Microsoft account, and leave
Settings → VAT periods on quarterly, stagger 1. Upload `apps/web/public/sample-receipt.png` on Review and scan. The card should
show no date warning. Approve it. On `/vat` the picker should read "Oct–Dec 2026 · current", with Box 4 at £8.65 and Box 7 at £43.
Pick Jul–Sep 2026: the boxes should go to zero and *Prepare submission* should still be offered. Pick Apr–Jun 2026: the
"too far back" note should appear and the button should be disabled. Change Settings to stagger 3: the current period
should become Sep–Nov 2026 and still include the receipt. Set it back to stagger 1, then scan a receipt dated in August. Its card should warn
"falls in the previous period (Jul–Sep 2026); it will go on that return", and after you approve it, it should count in Jul–Sep.
On `/ask`, with Jul–Sep picked, "How much VAT have I reclaimed?" should answer for Jul–Sep. On Android, the VAT tab's
dropdown should list nine calendar quarters.
