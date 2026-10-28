# Handover: profiles (linked accounts) + Xero-style menu bar

Full design, risks and checks: `REVIEW.md`.

## Done
- Runtime: `GET/PUT /profile` (`_System/profile.json`), kind gating (404 with a sentence on VAT, invoices, credit notes, payroll for kinds that lack them), a fake drive per test account (`test-token.<account>`), `tests/test_profile.py` (17 pass). pytest 1242/1243 passed before a fix (an audit summary), which was then checked with a targeted run; ruff and pyright clean.
- Web: several Microsoft accounts linked in MSAL, one-click switcher, per-account browser settings, HMRC dropped on switch, a Xero-style menu bar (switcher, groups, drawer under 900 px, Search, Ask, Help, Notifications, account menu), links only for pages in the build (`lib/routes.server.ts`), and Settings › Business › Profile. `e2e/profiles.spec.ts` passes (3/3). Existing specs were updated for the menu bar.
- Android: profile line plus *Switch account* (single-account MSAL); widget tests added but **not run**.
- Docs: ARCHITECTURE (Profiles section) and HONESTY (Profiles section).

## Left
- **No clean full e2e run yet.** The shared machine sat at load 30–50 on 2 CPUs, so browsers crashed and tests timed out, signed-out specs included. The one real failure found, an axe name mismatch on the account button, is fixed. Re-run the whole suite on a quiet machine.
- Last full runtime pytest was interrupted. Re-run it.
- `flutter analyze` and `flutter test` in `apps/mobile` have not been run.
- Open items: the dashboard VAT tile is not gated, Contacts has no customer/supplier filter, and the Android More screen does not hide features for personal books.

## How to test
```
. .v/bin/activate
cd services/runtime && python -m pytest -q && ruff check . && ruff format --check . && pyright app
cd apps/web && pnpm install --frozen-lockfile && pnpm exec eslint .
E2E_SERVER_TIMEOUT_MS=400000 E2E_PYTHON=$PWD/../../.v/bin/python CI=1 E2E_WEB_PORT=3110 E2E_RUNTIME_PORT=8791 E2E_RELAY_PORT=8799 pnpm run e2e:build
E2E_SERVER_TIMEOUT_MS=400000 E2E_PYTHON=$PWD/../../.v/bin/python CI=1 E2E_WEB_PORT=3110 E2E_RUNTIME_PORT=8791 E2E_RELAY_PORT=8799 pnpm run e2e:test
cd apps/mobile && flutter analyze && flutter test
```
