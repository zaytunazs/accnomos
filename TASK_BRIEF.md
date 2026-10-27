# Task: Home dashboard goes live — real tiles when signed in, sample when not

Accnomos monorepo (public; UK English; no secrets; stateless runtime). Read first: `apps/web/src/app/page.tsx`, `components/home/*`,
`lib/sample-home.ts`, `lib/runtime.ts`, and the runtime routes on main (`/books/summary`, `/books/vat`, `/books/deadlines`,
`/books/bank/*`, `/invoices` and `/contacts/aged` if merged, `/mail/triage` if merged). Where a route is not on main yet, read its brief
in `~/spark/accnomos/jobs/*_task.md` and code against the contract behind a feature check (`try` → tile shows "—").

## Deliverables
1. Runtime `GET /books/dashboard` that assembles, in code, one payload: cash position (latest bank balance from the last matched
   statement if any), owed to you (unpaid sales invoices), owed by you (unpaid purchase docs), VAT estimate (Box 5 so far + deadline),
   needs attention (counts: proposals, needs-a-look, unmatched bank lines, overdue invoices), recent activity (last 10 ledger/audit items),
   last Autopilot/intake/triage runs (from audit files). Cheap: no model calls. Tests with fake storage.
2. Web Home: `Tiles`, `Deadlines`, `Activity` and the greeting bind to it when signed in (user's display name from MSAL, business name
   from settings); the sample (Priya / Bramblewood) only when signed out, labelled. Skeletons while loading; "—" for unknown.
3. Mobile: Home screen tiles bind to the same endpoint (small change in `apps/mobile/lib/screens/home_screen.dart` or wherever Home lives);
   `flutter analyze` clean.
4. README row; `pnpm run build` passes.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
