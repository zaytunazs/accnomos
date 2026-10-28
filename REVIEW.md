# Review: basic personal finances (branch `claude/personal-finance`)

## What changed
- `services/runtime/app/personal.py` (new): categories (12 defaults, editable, "Other" always present), monthly budgets, a separate personal rule set (`_System/personal/rules.json`, reuses `rule_matches` from `bank_rules.py`, money out only), per-line hand overrides, spend-vs-budget and the monthly summary, recurring bill/subscription detection, savings-goal maths. All files live under `_System/personal/` in the books folder; no database. Money is pence; no model is called.
- `services/runtime/app/routes_personal.py` (new, registered in `main.py`): `/personal/{categories,budgets,rules,rules/starter,lines/{id}/category,summary,recurring,goals}`. It reads bank lines via `Books.list_bank_lines()`, so the existing CSV import feeds it. It has no profile logic: it works on whichever `Books` the request carries.
- `audit_view.py`: summaries for the seven new audit actions (a test requires one per action).
- Web: `/personal` page (`components/personal/LivePersonal.tsx`: summary, budgets with progress bars, sorting rules, bills list, goals), Settings › Business › "Show personal finances" (localStorage `accnomos.personal.show`, off by default), nav link only when on (`AppNav.tsx`), `runtime.personal.*` client, `/personal` added to the phone/axe page list.
- `docs/HONESTY.md`: new "Personal finances" section.

## Tests
- `tests/test_personal.py`: 27 tests (rule categorisation, budget states, summary totals, recurring detection incl. weekly/fortnightly/quarterly/annual, varying bills, stopped, goals maths, routes). Full runtime suite: 1253 passed, 1 skipped; ruff check/format and pyright are clean.
- Full e2e: 230 passed, 58 skipped (other projects), 1 timing failure in review.spec.ts (U-undo) under load that passes alone.
- `e2e/personal.spec.ts`: 2 tests (off by default -> Settings switch -> import statement -> rules, budgets, bills, goals; and a 360 px no-sideways-scroll + axe check). Existing phone/axe suites also visit `/personal`.

## Risks
- Recurring detection is heuristic (payee key = first three words without digits/dates/bank filler). It has only been run on hand-made statements. Expect misses and false positives on real exports; thresholds are constants at the top of the recurring section.
- Starter merchants are a fixed guess list, not verified categories.
- Income is all money in; refunds are not netted against categories.
- The setting is per device (localStorage), not in the books; the lead will wire it to profile kind `personal` at merge. On a phone the page is reached from the Settings link only (not the tab bar).
- Goals' "saved so far" is user-entered; nothing reads savings balances.
- Not tried on a real OneDrive or real bank CSVs.

## A human should check
- Import a real month of statements and read the Bills list and "Other" total for sense.
- Budgets/progress colours and wording at 360 px on a real phone.
- That `.v` was not added and no secrets are present (`git status`).
