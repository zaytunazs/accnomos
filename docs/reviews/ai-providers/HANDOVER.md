# Handover: AI provider chain (`claude/ai-providers`)

Done (committed): `AI_PROVIDERS=modal,meta,spark` chain (`services/runtime/app/ai/providers.py`, `ai/chain.py`) with
failover, circuit breaker and `served_by` on proposals, Verifier, Ask and triage; `GET /ai/health`, `GET /ai/calls`,
`POST /ai/warm`, `/health` chain summary (`app/routes_ai.py`); `tools/modal_glimmer.py` proxy auth + `MODAL_KEEP_WARM`
(cost cited); web Review card line, `/models` page, warm-up on Home/Review, footer and Settings links; docs
(PRODUCTION section 6, META_MODELS, HONESTY), compose, `.env.example`. Details in `REVIEW.md`.

Verified: ruff check and format clean; pyright 0 errors; `tests/test_ai_providers.py` (33) and the AI-related test
files (309 tests: triage, verify, ask, voice, planner, invoicing, duplicates, testmode, docs) pass; a per-file run of
the full suite passed every file it reached (test_actions to test_docs) before it was stopped; web eslint clean.

Left: the full runtime suite never finished in one run (OOM-killed on the shared machine; files from
`test_formats.py` onwards not run since the change). The e2e build was OOM-killed, so `apps/web/e2e/models.spec.ts`
and the existing e2e suite have NOT run with the change (watch for the new Review card line and the `AI_PROVIDERS`
env in `playwright.config.ts` affecting existing specs). Not pushed by me: the force push was refused by the
permission system.

Test: `. .v/bin/activate; cd services/runtime && python -m pytest -q`; `pyright services/runtime/app`;
`cd apps/web && pnpm exec eslint src e2e`; then `CI=1 E2E_WEB_PORT=3200 E2E_RUNTIME_PORT=8810 E2E_RELAY_PORT=8811
pnpm run e2e:build` and the same env with `pnpm run e2e:test`.
