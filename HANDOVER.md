# Handover: claude/marketing (public website + "Ask about Accnomos" chat)

**Done (committed):** runtime `POST /public/chat` with KB `services/runtime/app/public_kb.md` and 49 passing unit tests;
landing page on `/` (signed out), sample Home moved to `/try`, public shell/menu (`SiteShell.tsx`,
`components/marketing/*`), process animation on real screenshots (`public/shots`, `scripts/marketing-images.py`),
chat widget, owner additions (phone first, email intake, demo CTA to `/judges` if built else `/try`), and the
`NEXT_PUBLIC_SUBMISSION_MODE` / `PUBLIC_SUBMISSION_MODE` flags. Docs: HONESTY.md, PRODUCTION.md §3a. Details: REVIEW.md
(its RESULT_* placeholders were never filled: the gates did not finish).

**Left / known failing (last run, marketing + submission specs, 1 worker: 13 passed, 3 failed):**
1. `e2e/submission-mode.spec.ts`: the client chunk for `PublicHeader.tsx` still contains "Early access / testers" (the
   flag branch is not dead-code eliminated). Fix: render the testers link from a server component passed in as a prop,
   so its text never reaches the client bundle in the submission build.
2. Two `marketing.spec.ts` assertions were stale after the owner's copy changes; fixed in the spec but not re-run.
3. Not done because the shared machine kept OOM-killing jobs: full `pytest` (killed in `test_sample_books.py`, which
   this branch doesn't touch), `pyright services/runtime/app` after the last change, `pnpm run build` (killed),
   `pnpm run size`, and a clean full e2e run (runs failed on page crashes and timeouts at load 40+). The `.demo-mark`
   spotlight shadow was cut from a 9999px to a 900px spread in case it caused renderer crashes; unverified.
4. Screenshots in `docs/reviews/marketing/shots/` predate the phone-first and submission-mode copy; re-run
   `node apps/web/e2e/marketing-shots.mjs` with the test servers up.

**How to test:** venv active, then
`cd services/runtime && python -m pytest -q tests/test_public_chat.py tests/test_security_routes.py`;
`ruff check . && ruff format --check . && pyright services/runtime/app`;
`cd apps/web && CI=1 E2E_WEB_PORT=3160 E2E_RUNTIME_PORT=8796 E2E_RELAY_PORT=8804 pnpm run e2e:build && CI=1 E2E_WEB_PORT=3160 E2E_RUNTIME_PORT=8796 E2E_RELAY_PORT=8804 pnpm run e2e:test`
(the webServer start-up timeout was raised to 240 s for this machine).
