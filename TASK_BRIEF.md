# Task: VAT periods end to end — period picker, date-in-period check, obligations from HMRC, demo data in the live quarter

Accnomos monorepo (public; UK English; no secrets; stateless runtime). Read first: `services/runtime/app/{routes_vat.py,pipeline.py,
checks.py,facts.py}`, `packages/ledger/src/accnomos_ledger/vat.py`, `services/hmrc-relay/relay/*` (obligations endpoint, if present),
`apps/web/src/components/settings/VatPeriodSettings.tsx` (saved stagger / start month), `apps/web/src/app/vat/*`, `apps/web/src/lib/runtime.ts`,
`docs/reviews/judges-docs/REVIEW.md` ("What remains": the demo receipt is dated outside the judging quarter and the date-in-period warning never fires).

## Deliverables
1. Runtime `GET /books/vat` takes `?period_start=&period_end=` (ISO dates) or `?period=<yyyy-Qn>` and defaults to the **current period
   from the saved VAT settings** (stagger/start month sent as headers or query by the web app — reuse what `/books/deadlines` already
   accepts), not the calendar quarter. Response names the period it used. `GET /books/vat/periods` lists the last 8 periods with
   status (open / submitted via relay / none) so the picker can be built by code.
2. Wire the existing `check_date` into the scan pipeline with the current period: a document dated outside the period gets a
   `warn` ("dated 14 Aug — falls in the previous period; it will go on that return") — never a fail, never changes the ledger date.
   Tests for both sides of the boundary and the 6 April tax-year edge.
3. Web `/vat`: period picker (previous 8 + current), the 9 boxes recompute for the picked period, "Submit to HMRC" only on the current
   or previous open period; the Ask facts pack takes the same period. Android `VatScreen` gets the same picker (thin: reuse the
   runtime list; no VAT maths on the phone).
4. Demo data: regenerate `evals/gold/sample-receipt.png` (and any sample used in `docs/DEMO.md`) with a date **inside the quarter that
   contains 4 Nov 2026**, keep the `SAMPLE — FICTIONAL COMPANY` label, update `docs/DEMO.md` so the on-stage script's Box 4/Box 7
   numbers are true. Do not touch `tools/seed_demo.py` if the demo-seed lane owns it; say so.
5. README "What works today" row + `docs/HONESTY.md` bullet updated. `pytest`, `pnpm run build`, `flutter analyze` must pass.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
