# Handover: accounting tools (branch claude/accounting-tools)

**Done:** chart of accounts, manual journals (approval, VAT side, auto-reversal, void), fixed assets (register,
depreciation runs and disposals as journals, schedule, reconciliation), find and recode (adjusting entries; undo unwinds
them), tracking categories (invoice/bill/journal tags, Tracking Summary), budgets (summary, variance), 30/60/90-day cash
flow (with a checked AI sentence), seven web pages, audit sentences, docs, REVIEW.md. Multi-currency dropped by the owner.

**Left:** run the web e2e (never run: `next build` was OOM-killed on the shared machine) and fix what
`e2e/accounting.spec.ts` and the axe/phone sweeps (7 routes added to `e2e/pages.ts`) find; link the 7 routes from the new
top menu (REVIEW.md), then drop `ToolsNav`.

**Test:** `. .v/bin/activate`; `cd packages/ledger && python -m pytest -q`; `cd services/runtime && python -m pytest -q`
(in batches on a small machine); `ruff check . && ruff format --check .`; `pyright services/runtime/app`; web:
`cd apps/web && pnpm install --frozen-lockfile && pnpm exec eslint .`, then with `CI=1 E2E_WEB_PORT=3180
E2E_RUNTIME_PORT=8798 E2E_RELAY_PORT=8806 E2E_PYTHON=python PYTHONPATH=<worktree>/packages/ledger/src:<worktree>/packages/connectors/src`
run `pnpm run e2e:build && pnpm run e2e:test` (PYTHONPATH matters with a shared venv).
