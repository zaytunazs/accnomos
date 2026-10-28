# Handover: sales and purchases

Branch: claude/sales-purchases. See REVIEW.md for what changed and the route list.

## Done
- Items, quotes, purchase orders, repeating invoices and bills, Sales and Purchases overviews, customer statements (runtime and web pages).
- Quotes by chat and voice: quote facts in the Ask pack, `create_quote` and `convert_quote_to_invoice` action cards (docs/ACTIONS.md updated).
- ruff clean; pyright clean on actions.py after the last fix (full-app pyright showed only those two errors, now fixed).
- Targeted runtime suites pass (actions, ask, audit, quotes, quote_ask: 126 passed). tsc clean.

## Left
- Full `python -m pytest -q`: a run was killed by the machine (exit 137) at 65%, with one unexplained F seen in an earlier run. Re-run with `-rf` to find it.
- Full e2e on ports 3170/8797/8805 was never green: the machine load (about 40) made the test-mode runtime import (testmode.py renders 200 PNGs) exceed the 60 s webServer timeout. Re-run when the machine is quiet; `e2e/sales-purchases.spec.ts` is the new spec.
- Append gate results and counts to REVIEW.md.

## How to test
Runtime: `cd services/runtime && python -m pytest -q -rf`. Web: `cd apps/web && CI=1 E2E_WEB_PORT=3170 E2E_RUNTIME_PORT=8797 E2E_RELAY_PORT=8805 pnpm run e2e:build && CI=1 E2E_WEB_PORT=3170 E2E_RUNTIME_PORT=8797 E2E_RELAY_PORT=8805 pnpm run e2e:test`.
