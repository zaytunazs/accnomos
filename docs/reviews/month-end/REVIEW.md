# Review: the month-end close agent (branch `claude/month-end`)

One button, **Close October**, works through the close checklist, does what code can, and turns everything that
needs the user into cards. Built for the "Best Agentic Use-Case" award: the loop is visible step by step, and nothing
is posted, sent or closed without an Approve.

## What was built

| Part | Files |
|---|---|
| The agent (nine steps, snapshot, close records, change detection, re-close) | `services/runtime/app/month_end.py` |
| Routes: `GET /close`, `GET /close/{yyyy-mm}`, `POST /close/{yyyy-mm}/run` (`?stream=1`: server-sent events) | `services/runtime/app/routes_close.py`, `app/main.py` |
| Summary written by the user's AI, checked with Ask's number check; code fallback | `services/runtime/app/ai/close_summary.py` |
| Cards: `match_bank_line`, `close_month` (new), `chase_invoice` (shared with Ask via `actions.chase_draft`) | `services/runtime/app/actions.py`, `app/schemas.py` |
| Balance sheet and the month-end workbook (About, P&L, Balance sheet) | `services/runtime/app/reports.py` |
| Reminders with no AI set up: code writes them | `services/runtime/app/ai/remind.py` |
| Audit sentences (`close_run`, `month_closed`, `month_reclosed`), `agent:close` → "Month-end" | `services/runtime/app/audit_view.py` |
| Test-mode stub reply for the summary | `services/runtime/app/testmode.py` |
| Web: *Month-end* page (month picker, streamed checklist, cards under their step, changes banner with before/after) | `apps/web/src/app/month-end/page.tsx`, `apps/web/src/components/month-end/MonthEnd.tsx` |
| Web: Home card, nav link (Money group), ActionCard for the two new kinds | `apps/web/src/components/home/MonthEndCard.tsx`, `AppNav.tsx`, `components/ask/ActionCard.tsx`, `lib/runtime.ts` |
| Android: read-only checklist (More › Month-end) and Home card | `apps/mobile/lib/models/month_end.dart`, `lib/screens/month_end_screen.dart`, `home_screen.dart`, `more_screen.dart`, `services/runtime_client.dart` |
| Tests | `services/runtime/tests/test_month_end.py` (19), `apps/web/e2e/month-end.spec.ts` (2), `apps/mobile/test/month_end_test.dart` (5) |
| Docs | `docs/ARCHITECTURE.md` ("The month-end close", folder tables, actors), `docs/ACTIONS.md`, `docs/HONESTY.md` |

## Decisions

- **The loop is code, not a model.** The model writes only the run summary, from the steps' own reasons and counts,
  and code rejects any figure not in them (Ask's `KnownNumbers`), any link, and "ready to close" when it is not.
- **Three levels per finding.** `blocking` (the month's figures are incomplete or wrong: inbox documents, missing
  statements, balance jumps, unreconciled lines, draft invoices dated in the month, a pay run missing with hours logged
  or still a draft, Sundry/uncoded balances, duplicates, a step that failed), `needs_you` (overdue invoices, bills due,
  supplier credits, the VAT return to file, negative balances, unusual postings) and `note`. Reports and Lock wait only
  for `blocking`.
- **Cards reuse the signed actions.** No new approval path: `/actions/approve` executes once, refuses changed or
  expired cards. `close_month` recomputes the snapshot on Approve and refuses (409) if anything dated in the month
  changed after the run.
- **Closing detects, it does not lock.** A stateless runtime with books in the user's OneDrive cannot stop a posting
  into a closed month; the snapshot hash makes every later change visible (Home, Month-end), with before/after P&L
  lines and VAT boxes, and the next run offers a re-close (a second close record, a second report ` (2)`).
- **Outlook is a dry run.** Intake copies only on the user's *Check now*; the close only counts what it would copy.
- **No suspense account exists** in the chart; `7999 Sundry expenses` stands in for "uncategorised".
- **"Under Accounting"**: the web has no Accounting group; Month-end sits in the *Money* group after VAT return.
- **Reports**: the draft (`<yyyy-mm>-month-end-draft.xlsx`) is rewritten by each unblocked run; the closed one is never
  overwritten.

## Gates

GATES_PLACEHOLDER

## What remains

- Never run against a real OneDrive, mailbox or Graph token; streaming through the Graph-backed `get_books` is
  untested (the fake has no cleanup to race).
- Flutter: no SDK on this machine, so `flutter analyze` and `flutter test` were not run; the five widget tests need the
  lead's run.
- Coverage gaps are inferred from line dates with a 3-day allowance; two accounts at one bank are one bank.
- The run reads the whole ledger and every bank line; unmeasured on a large real book.
- Cards are not kept server-side: a reload shows the last run without its cards (run again).
