# Task: Make the Playwright suite green on main again (5 failures from merge drift), then keep it honest

Accnomos monorepo (public; UK English; no secrets). On main today `cd apps/web && pnpm run e2e` gives 47 passed, 5 failed:
`ask.spec.ts` (answer text for the picked VAT period), `invoices.spec.ts` (preview/send flow), `jobs.spec.ts` (job + staff + timesheet
→ proposed invoice lines — the hand-off to `/invoices/new` changed in `claude/loose-ends-1`), `payroll.spec.ts` (prepare → export → confirm;
the empty state is now an `EmptyState` component), `review-vat.spec.ts` (VAT now opens on the current period, not `26A3`). Read first
`docs/reviews/review-page/REVIEW.md` and `docs/reviews/e2e-all-pages/REVIEW.md` ("What remains"), `apps/web/e2e/*`, `playwright.config.ts`,
`services/runtime/app/testmode.py`.

## Deliverables
1. Run the suite; for each failure decide whether the app or the spec is wrong and fix the right one (a spec that encoded an old
   default follows the new behaviour; an app regression is fixed in the app). One commit per spec with the reason in the message.
2. Settings is tabbed now (`SettingsPanels.tsx` groups): the Settings/Outlook/Autopilot specs must open the right tab first.
3. Add the Review keyboard flow (J/K/A/E/R/U) and the "Approve all N rule matches" confirm to `review.spec.ts`, and the setup
   checklist card to `home.spec.ts` (signed in, incomplete → rows link to `/settings#…`).
4. Suite must be green (`pnpm run e2e`) and under 4 minutes; `.github/workflows/e2e.yml` unchanged unless needed.
Commit in small steps; do not push. Finish with `git log --oneline -8`, the final pass/fail line, and which failures were app bugs.
