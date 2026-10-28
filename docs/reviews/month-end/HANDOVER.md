# Handover: month-end close agent (claude/month-end)

**Done:** runtime agent `services/runtime/app/month_end.py` (9 steps, cards `match_bank_line` / `close_month` /
`chase_invoice`, snapshot hash, close records in `_System/close/<yyyy-mm>.json`, post-close change detection with
before/after figures, re-close), routes `app/routes_close.py` (`GET /close`, `GET /close/{m}`,
`POST /close/{m}/run?stream=1`), summary `app/ai/close_summary.py`, balance sheet in `app/reports.py`; web `/month-end`
page, Home card, nav link, ActionCard kinds; Android read-only screen and Home card; docs (ARCHITECTURE, ACTIONS,
HONESTY); REVIEW.md (the gates section is still a placeholder).

**Gates so far:** `tests/test_month_end.py` 19/19 passed; ruff check and format clean; pyright 0 errors on the changed
files (the whole-app run was OOM-killed). The first half of the runtime suite (676 tests, up to `test_paths.py`) passed
after a paths-literal fix. Second half: one failure at about 37% of the files from `test_paths.py` onward, **not yet
identified** (it may come from this branch, for example an audit-summary or docs test). eslint is clean on the changed
web files.

**Left / not run:** find that failure; the whole `pyright services/runtime/app`; `next build` / tsc and e2e (OOM-killed
on this machine); `flutter analyze` / `flutter test` (no SDK here); fill in the REVIEW.md gates. Not pushed: a force push
was refused by the permission classifier.

**Test:** `cd services/runtime && python -m pytest -q tests/test_month_end.py`, then the full suite. Web:
`CI=1 E2E_WEB_PORT=3220 E2E_RUNTIME_PORT=8814 E2E_RELAY_PORT=8815 pnpm run e2e:build`, then the same env with
`pnpm run e2e:test e2e/month-end.spec.ts`. Android: `flutter test test/month_end_test.dart`.
