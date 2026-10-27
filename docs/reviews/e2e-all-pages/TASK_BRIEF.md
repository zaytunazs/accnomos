# Task: Click through every web page in test mode with Playwright, fix what breaks, extend the e2e suite

Accnomos monorepo (public; UK English; no secrets). Read first: `docs/reviews/e2e-tests/REVIEW.md`, `apps/web/e2e/**` (or wherever the
Playwright suite lives — `apps/web/package.json` scripts), `services/runtime/app/testmode.py` (`ACCNOMOS_TEST_MODE=1`: Graph look-alike,
stub AI, fake calendar, seeded mailbox), `.github/workflows/e2e.yml`, `apps/web/src/components/AppNav.tsx` (eleven pages + Settings).

## Deliverables
1. Run the existing suite locally (runtime in test mode + `pnpm run build` + Playwright). Fix anything red first.
2. Add one spec per page not yet covered: Invoices (create → preview → send with the confirmation dialog, the fake mail sender records
   it), Bank (upload a gold CSV → confirm a match → unmatched actions), Contacts (list, edit, statement), Jobs (job + staff + timesheet →
   proposed invoice lines), Vehicles (vehicle + journey → allowance proposal appears in Review), Payroll (prepare → export CSV → confirm),
   Settings (all four tabs render, VAT period change moves the deadline, Autopilot L2 toggle, deep link `#settings-<id>`), Files, Home
   dashboard (tiles show the seeded numbers), VAT (period picker changes the boxes), Ask (typed question → cited answer; "plan my Thursday"
   → day-plan card). Phone width (390 px) run of Home, Review, Ask, VAT and Settings: no horizontal scroll, buttons visible.
3. Every bug found is fixed in the app (not papered over in the test) with a one-line note in the commit; if a fix needs a product
   decision, leave the test marked `test.fixme` with the reason.
4. Seed data needed by the specs goes into the test-mode seed (`testmode.reset`), labelled `SAMPLE — FICTIONAL COMPANY`, never into
   production paths. Keep the suite under ~6 minutes on the CI runner; use `test.describe.configure({ mode: 'parallel' })` where safe.
5. `.github/workflows/e2e.yml` runs the whole thing; make it green locally with `act` if available, otherwise by reading it twice.
Commit in small steps; do not push. Finish with `git log --oneline -8`, the list of bugs fixed, and five lines a human must verify in a real browser.
