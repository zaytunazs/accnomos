# Review: `claude/dashboard-live`

Second-agent review of the "Home dashboard goes live" task (`TASK_BRIEF.md`). 27 Oct 2026.

## What was checked

- `services/runtime`: `pytest -q`: 523 passed before the review, **527 passed** after (4 new tests). No other Python package or service is touched by the branch.
- `apps/web`: `pnpm run build` passes (TypeScript clean) before and after.
- `apps/mobile`: **`flutter analyze` and `flutter test` not run.** There is no Flutter or Dart SDK on this machine.
- Read the whole diff. Runtime: `app/dashboard.py`, `routes_dashboard.py`, the `routes_vat.py` split. Web: `HomeData`, `Greeting`, `Tiles`, `Deadlines`, `Activity`, `runtime.ts`. Mobile: `home_screen.dart`, `models/dashboard.dart`, `runtime_client.dart`.
- Checked against the product rules:
  - Reads only. The test asserts storage is unchanged.
  - No model call on the dashboard path.
  - Money stays in integer pence end to end. VAT Box 5 is the existing 2 dp string.
  - Nothing is written server-side.
  - Signed-out sample is labelled.
  - UK English throughout.

## What I fixed

| Commit | Fix |
|---|---|
| `618ab68` | **One hand-edited file broke the whole dashboard.** A bank-lines, proposal or ledger-event file that no longer parsed made `GET /books/dashboard` return 500. The docstring and README both promised the other tiles would still show. The three parts of the ledger are now read on their own, and only the sections that need a broken part come back null and are named in `unavailable`. Bank lines broken: cash, owed and attention are blanked. Proposals broken: attention only. Events broken: VAT and owed. Owed figures are never guessed without the payments. Added tests for each case, and for `months=2` → 422. |
| `a231368` | Web: the signed-out Home badge now uses the standard `SAMPLE — FICTIONAL COMPANY` label. The VAT tile no longer says "£0 · To pay by …" for a nil return, and a reclaim says "return due". |
| `f48146c` | Mobile: when the runtime cannot be reached, the tiles say "Could not load". Before, they showed misleading notes like "Match a bank line to see" and "You owe —". A malformed Box 5 string no longer throws (`double.tryParse`). The `d?.` uses that would trip analyser warnings are removed. |
| `0ea05fc` | README row: says exactly what survives a broken file. Notes that mobile shows four tiles and uses stagger 1 VAT quarters. |

## What remains

- **`flutter analyze` / `flutter test` have not been run** on the original mobile work or on `f48146c`. Run both on a machine with the SDK before merging. The new widget test in `test/signed_out_test.dart` assumes `AuthService.account()` returns quickly with no account under test.
- Mobile always asks for stagger 1 VAT quarters. It has no VAT period setting yet, so a stagger 2/3 or monthly business sees the wrong VAT deadline and estimate on the phone. The web app sends the user's VAT period from Settings.
- On the web, the global `DemoBanner` (from `AppShell`, not touched by this branch) still says "SAMPLE — FICTIONAL COMPANY" on every page, even when Home shows live figures. Hiding it when signed in should be a separate change.
- On mobile, a failed pull-to-refresh keeps the previous figures under the error message, with no "stale" marker.
- If an audit or storage read fails at the provider level (not a parse error), the dashboard still returns 500. Only parse and validation errors are isolated per section.
- `default today` on the runtime is the UTC date. Both clients send `today`, so this only affects direct API callers.
- `TASK_BRIEF.md` was committed by the "wip: checkpoint" commit (`50626ae`). Drop it or squash it out before merging if briefs should not land on `main`.
- Not run against a real OneDrive or MSAL sign-in.
- `ruff` is not installed in this environment, so no lint run.

## How to verify by hand

Start the runtime (`cd services/runtime && uvicorn app.main:app`) and the web app (`cd apps/web && pnpm dev`).

1. **Signed out.** Open `/`. You should see Priya / Bramblewood with the dark "SAMPLE — FICTIONAL COMPANY · Bramblewood Joinery Ltd" badge, five tiles, sample deadlines and "What the agents did today".
2. **Signed in.** Sign in with Microsoft against a OneDrive that has a few approved entries, one imported bank statement with a matched line, and one sent invoice past its due date. You should see:
   - grey skeletons briefly;
   - then "Good morning/afternoon/evening, <first name>" and today's date with the business name from Settings;
   - cash equal to that statement's closing balance;
   - owed to you, with the overdue invoice in amber;
   - owed by you;
   - the VAT tile and Deadlines matching `/vat`;
   - "Needs attention" counts matching `/review` and `/bank`;
   - "Recent activity" listing the last ten audit lines.
3. **Broken file.** Hand-edit one file in `_System/bank/` to `[{}]` and reload. Cash, owed and needs attention should show "—" while VAT and activity still show.
4. **Runtime down.** Stop the runtime and reload. Every tile should show "—" with "Could not reach your books", and the sample should not appear.
5. **Mobile.** On the phone app, the Home tab should show the same figures, or "Could not load" with the runtime stopped.
