# Handover: claude/self-employment (MTD Income Tax, sandbox only)

**Done** (see REVIEW.md, docs/HMRC.md): runtime figures, receipts and reports (`app/itsa.py`, `routes_itsa.py`,
`itsa_reports.py`); relay Income Tax routes (`relay/itsa.py`, sandbox only, `RELAY_ITSA_PRODUCTION` switch); web page
`/self-employment` behind Settings › "I am self-employed"; docs. API versions checked live on 28 Oct 2026. Never run
against HMRC. Branch not pushed (the force push was refused by the permission check).

**Left**: a full green run of the runtime and e2e suites on a quiet machine (this one was overloaded: OOM kills,
web-server start over 60 s). Check `test_sample_books.py::test_a_second_press_while_running_or_after_is_the_same_run`
(failed under load; looks timing-only). Not built: annual submission, consolidated expenses. Cash basis: built on `claude/cash-basis` (docs/reviews/cash-basis/REVIEW.md).
Reports are ready to register in the `claude/exports` registry.

**Test**: `cd services/runtime && python -m pytest -q tests/test_itsa.py tests/test_security_routes.py`;
`cd services/hmrc-relay && python -m pytest -q`; `ruff check . && ruff format --check .`; `pyright services/runtime/app`;
web: `CI=1 E2E_WEB_PORT=3120 E2E_RUNTIME_PORT=8792 E2E_RELAY_PORT=8800 pnpm run e2e:build`, then the same with
`e2e:test` (`e2e/self-employment.spec.ts`). Sandbox checks for a human: REVIEW.md, "What a human must check".
