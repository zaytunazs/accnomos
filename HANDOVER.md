# Handover: claude/payroll-rti

**Done (committed):** a 2026-27 PAYE, NI, student loan, SSP and SMP engine with HMRC golden tests (`paye.py`, `paye_rates.py`); auto-enrolment and pension provider CSVs (`pension_ae.py`); pay runs with year-to-date figures, posted through proposal → approve (`payrun.py`); FPS and EPS XML validated against HMRC's 2026-27 XSDs, plus P45, P60 and P32 (`rti.py`); reports in web, PDF, CSV and XLSX, and payslips (`payroll_reports.py`, `pdf.py`, `routes_payrun.py`); overtime from timesheets and the `pay_overtime` chat action; the web `/payroll` page (`LivePaye.tsx`); docs (HONESTY, ARCHITECTURE, ACTIONS, README). REVIEW.md has the details and what a payroll professional should check.

**Checked:** I ran the runtime tests in three chunks. Two chunks passed in full (656 and 339 tests). The third had 389 passed and 6 failed:
- One was a real bug (sick and maternity pay inputs accepted unknown fields). It is fixed in c864555; the fix passes on its own, but the full suite was not re-run afterwards.
- The other 5 timed out while the machine was overloaded (voice ffmpeg conversion, rate-limit timing, a 120 s subprocess). They have not been re-run.

ruff is clean, pyright shows 0 errors and eslint is clean.

**Left:**
- The e2e tests have never run, because `next build` was killed for lack of memory. The new `apps/web/e2e/paye.spec.ts` is untested.
- Re-run the 5 timed-out tests on a quiet machine.
- The Android card for `pay_overtime` has not been compiled (no Flutter here).
- Register `payroll_reports` with the exports registry once `claude/exports` lands.
- The branch has not been pushed: the force-push was refused by permissions.

**Test:** `cd services/runtime && python -m pytest -q` (`xmllint` is needed for the XSD checks). Web: `CI=1 E2E_WEB_PORT=3130 E2E_RUNTIME_PORT=8793 E2E_RELAY_PORT=8801 pnpm run e2e:build`, then the same with `e2e:test`.
