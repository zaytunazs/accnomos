# Review: `claude/security-2`

Second security pass (brief in `TASK_BRIEF.md`; the implementer's own record is `docs/reviews/security-2/REVIEW.md`).

## What was checked

- **Suites run:** `packages/connectors` 43 passed, `packages/ledger` 35 passed, `services/hmrc-relay` 102 passed,
  `services/runtime` 741 passed + 1 skipped (740 before the test added here). `apps/web` `pnpm run build` passes
  (no web files changed on this branch; run anyway because the implementer's record says it passed).
- **Diff read in full** (`git diff origin/main...HEAD`, 35 files): `StrictBody`/`Day`/`Pence` and `LENIENT`
  reading back user files (checked pydantic 2.14's `extra=` override reaches nested models, so hand-edited
  invoices and vehicles still open); create-only writes in `Books._update`, the fake provider and Graph
  (`conflictBehavior=fail` → 409 → `FileExistsError`; test-mode storage is the fake provider, so e2e is unaffected);
  the Graph-origin check in `_request` (needs the trailing `/`, so `graph.microsoft.com.evil` is refused); stale
  `approving` handling in approve and reject; the tenant bound into the signing key only in test mode; logo
  sniffing, Pillow decode and 4000 px limit; `load_logo` reading only the two upload targets; the fpdf page alias;
  the 2 MB logo cap in the middleware and nginx; audit actors (`user:` prefix on rebuilds); CORS `PATCH`.
- **Product rules:** no user database (everything stays in the user's OneDrive); actions are still proposed by
  the model, approved by the user and priced by code; money remains integer pence; no synthetic data was added.
- **Brief items that the diff doesn't touch:** `routes_mail.py` (draft replies are `html.escape`d in
  `msgraph.py`, tested in `packages/connectors/tests/test_mail.py`), `routes_contacts.py` and
  `routes_dashboard.py`. They are covered by the route-walking tests in `test_security_routes.py` (strict
  bodies, length caps, `X-User` on writes).
- **Docs:** `docs/SECURITY.md`, `docs/ACTIONS.md`, `docs/HONESTY.md`, `docs/REMAINING.md`, `deploy/README.md`
  match the code. README *What works today* did not mention the second pass, so I added it.

## What I fixed

- `8d1d286`: a new test. A real PNG between 1 MB and 2 MB gets past the middleware's body cap and must be
  refused by the route's own 1 MB check (413, nothing written). The brief asked for the 1 MB limit, but no test
  covered that band.
- `02dddc1`: the README Security row now covers the second pass, lists `test_security_routes.py`, and names
  the open item about the action card.

No code defects needed fixing. One thing I checked and left alone: in `run_mileage` the `[:200]` cut only
applies to the "from to to" fallback, not to `job_name`. That is safe, because `Job.name` is already capped at
200 and loaded with that check.

## What remains

- The web action card does not explain the stale-`approving` path (wait 10 minutes, check, Reject, ask again);
  only the API message and `docs/ACTIONS.md` do.
- Nothing was run against a real Graph tenant, model or `api.accnomos.com`; the images were not built and
  `nginx -t` was not run (the deploy files are checked by config tests only).
- The logo upload shares the general per-IP rate limit (60/min), which allows up to about 120 MB a minute from
  one address. This is accepted in `docs/SECURITY.md`; volumetric protection is left to the front proxy.
- Without `ACTIONS_SIGNING_KEY` the signing key is random per process (cards fail after a restart or across
  replicas). This is documented, not changed.
- `TASK_BRIEF.md` is committed at the repo root (the `wip` checkpoint `921e48c`); drop it before merging if
  briefs shouldn't live in `main`.

## How to verify by hand

Run `pytest -q` in `packages/connectors`, `packages/ledger`, `services/hmrc-relay` and `services/runtime`, and
`pnpm run build` in `apps/web`; all should pass. Then start the runtime (`uvicorn app.main:app` in
`services/runtime`, `ACCNOMOS_TEST_MODE` unset) and confirm `POST /__test/reset` returns 404. With a test-mode
runtime (`ACCNOMOS_TEST_MODE=1`), post a GIF renamed to `logo.png` to `/invoices/profile/logo` with
`X-Graph-Token` and `X-User` set and expect 415. Post a 5000×1 PNG and expect 413. Post a small real PNG and
expect 200 with `logo_path: "_System/Invoicing/logo.png"`. Post an invoice draft with `"issue_date": 1700000000`
or `"unit_price_pence": 12.5` and expect 422. In Ask, make a timesheet card and approve it twice: the second
answer is `already_done` and only one timesheet entry exists.
