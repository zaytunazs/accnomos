# Review: PAYE payroll (RTI files) and workplace pensions — branch `claude/payroll-rti`

## What changed

| Area | Files |
| --- | --- |
| 2026-27 figures, one table | `services/runtime/app/paye_rates.py` (the timesheet estimate's `payroll_rates.py` now takes its constants from it) |
| Calculation engine (pure) | `services/runtime/app/paye.py`: tax codes, cumulative and week 1/month 1 PAYE, Scottish (S) and Welsh (C), K codes and the 50 % regulatory limit, BR/D0-D8/NT/0T, weeks 53/54/56; exact-percentage Class 1 NI for all 16 letters; directors' annual and pro-rata NI; student loan plans 1/2/4/5 and postgraduate loan; SSP and SMP; State Pension age |
| Pensions | `services/runtime/app/pension_ae.py`: assessment per pay reference period, qualifying earnings or full pay, relief at source / net pay / salary sacrifice, opt-out window, provider CSVs |
| Pay runs and ledger | `services/runtime/app/payrun.py`; `approve.py`, `schemas.py` (a `payroll_run` on `Proposal`) |
| RTI and year end | `services/runtime/app/rti.py`: FPS and EPS XML, P45 and P60 figures, P32-style employer payment record |
| Reports and payslips | `services/runtime/app/payroll_reports.py`, `pdf.py` (`render_table`, `render_payslip`) |
| API | `services/runtime/app/routes_payrun.py` (`/payroll/paye/*`), `main.py`, `audit_view.py` |
| Web | `apps/web/src/components/payroll/LivePaye.tsx`, `apps/web/src/app/payroll/page.tsx`, `apps/web/src/lib/runtime.ts` (`runtime.paye`), the old timesheet estimate kept below as "Quick estimate from timesheets" |
| Overtime | `services/runtime/app/jobs.py` (`rate_multiplier` on timesheet entries, `set_rate_multiplier`), `payrun.py` (`timesheet_items`, weekly overtime rule, `PayItem` lines), `actions.py` (`pay_overtime` chat/voice action), web `ActionCard.tsx`, Android `ask_screen.dart` (card branch; not compiled here: no Flutter on this machine) |
| Docs | `docs/HONESTY.md` (Payroll), `docs/ARCHITECTURE.md` (files), `docs/ACTIONS.md` (`pay_overtime`), `README.md` (feature row) |

Flow: settings → employees → *Calculate pay run* (draft) → *Send to Review* (a proposal carrying the balanced journal; nothing posts) → approve here or in Review (posts one `adjustment` event: Dr 7000 wages, 7010 employer NI net of Employment Allowance, 7020 employer pension; Cr 2220 PAYE and NI, 2230 pension, 2240 net wages, 2250 other deductions) → payslips, FPS, EPS, pension file, reports. Undo puts the run back in Review; reject or *Back to draft* returns it to draft. Year to date builds only on posted runs, and an unposted earlier run blocks the next.

Overtime: an hourly employee linked to a timesheet name is paid from their entries dated in the pay period (hours x payroll rate x the entry's multiplier); an optional per-employee rule pays normal-rate hours over N in a Monday-Sunday week at the overtime multiplier. "Pay Andy double for last week's overtime on the Croydon job" makes a card: the model copies "double" and "last week", code finds Andy's entries for 19-25 Oct on that job, prices them (14 h x £20 x 2 = £560, £280 more) and shows them; Approve sets the multiplier on exactly those entries, and the next pay run pays them. Refused if the entries changed or an approved pay run already paid them. Holiday pay is not averaged; the card, payslip warnings and docs say regular overtime can count towards holiday pay: check with your adviser.

## Sources (all read 28 Oct 2026)

- HMRC, Rates and thresholds for employers 2026 to 2027 (published 30 Jan 2026, updated 1 Sep 2026): https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027
- HMRC, Specification for PAYE Tax Table Routines v24.0 (Feb 2026), Appendices A-C: https://www.gov.uk/government/publications/payroll-technical-specifications-income-tax — Scottish parameters "subject to parliamentary approval" at issue.
- HMRC, Tables A pay adjustment tables (free pay goldens): https://www.gov.uk/government/publications/tables-a-pay-adjustment-tables
- HMRC, NI Guidance for software developers 2026 to 2027 v1.1 (rounding, formulae, 12 worked examples): https://assets.publishing.service.gov.uk/media/6a3bc1fe4c7605ab567238ff/NI-Guidance-2026-27_v1.1.odt
- HMRC, Collection of student loans from 6 April 2026 (12 Dec 2025): https://www.gov.uk/government/publications/payroll-technical-specifications-student-loans/collection-of-student-loans-from-6-april-2026
- HMRC, RTI technical specifications 2026 to 2027 (RIM 2027 v1.0 schemas, data item guide v1.0): https://www.gov.uk/government/publications/real-time-information-internet-submissions-2026-to-2027-technical-specifications
- HMRC, How to use the Internet services: RTI v1.94 (Transaction Engine, Test-in-Live classes, TPVS/ETS/LTS, SDST credentials, recognition): https://assets.publishing.service.gov.uk/media/69b1a6ad24c6431b84f0e50e/RTI-howtouse-v1-94.odt
- HMRC, CWG2 2026 to 2027 (payments after leaving: 0T week 1/month 1): https://www.gov.uk/government/publications/cwg2-further-guide-to-paye-and-national-insurance-contributions
- DWP, AE earnings trigger and qualifying earnings band review 2026/27 (18 Dec 2025): https://www.gov.uk/government/publications/review-of-the-automatic-enrolment-earnings-trigger-and-qualifying-earnings-band-for-202627 ; TPR per-period thresholds: https://www.thepensionsregulator.gov.uk/employers/new-employers/im-an-employer-who-has-to-provide-a-pension/declare-your-compliance/ongoing-duties-for-employers/earnings-thresholds
- Pensions Act 2008 s.3 ("more than" the trigger): https://www.legislation.gov.uk/ukpga/2008/30/section/3 ; GOV.UK workplace pensions (3 %/8 %, opt-out within a month); Pensions Act 2014 notes (SPA 66 to 67).
- Acas, SSP changes 2026 (day one, no LEL, lower of 80 % AWE): https://www.acas.org.uk/statutory-sick-pay-changes-2026 ; GOV.UK pay PAYE (22nd electronic, 19th post); Employment Allowance eligibility.
- Pension layouts: Nest Employer payroll guide V13 (08/2019); The People's Pension contributions file data requirements v9 (Aug 2020); NOW: Pensions "Understanding the pension data file" (undated).

## Findings worth knowing

- **NI rounding.** HMRC (NI guidance 4.2) looks only at the third decimal place: £67.5558 is £67.55. The earlier `_ni_round` rounded to the nearest penny (giving £67.56); both now use `paye.ni_round`.
- **HMRC's NI example 3** prints a total of £47.94; its own steps (£0.44 + £47.25) make £47.69. The tests pin the steps.
- **1257L monthly free pay is £1,048.26** (Tables A and the spec), not £1,048.25 as an old comment said; fixed.
- Not published for 2026-27, so not invented: the starter-checklist code rules (A/B/C) are no longer printed in CWG2; the suggestion is marked unverified and points to HMRC's tool. No 2026-27 PAYE worked examples exist; income tax goldens are hand-worked from the spec with every step in the test.

## Tests

- Runtime: `cd services/runtime && python -m pytest -q` — see docs/reviews/payroll-finish/REVIEW.md for the full run. New: `test_paye.py` 87, `test_paye_rates.py` 9, `test_pension_ae.py` 18, `test_payrun.py` 25, `test_rti.py` 7 (FPS/EPS validated against the vendored XSDs with xmllint), `test_payroll_reports.py` 7 (every report in CSV/XLSX/PDF, routes end to end), `test_overtime.py` 12 (multipliers, weekly rule, pay run from timesheets, payslip/P11 overtime, the chat action proposing, approving, refusing changed or paid hours).
- `ruff check . && ruff format --check .` clean; `pyright services/runtime/app` 0 errors.
- Web: eslint and e2e were first run on claude/payroll-finish (see its REVIEW.md); including new `e2e/paye.spec.ts` (settings → employee → pay run figures → Review → approve → FPS/EPS/Nest CSV/payslip/P32 XLSX downloads; the filing sentence beside RTI; the RTI switch disabled).

## Risks

- Not HMRC-recognised; no submission, no IRmark, no GovTalk envelope. Basic PAYE Tools cannot import the XML: it is a checking aid. The disabled `rti_test_submission_enabled` switch is a placeholder: an ETS path needs SDST test credentials (owner work).
- HMRC's Schematron business rules in the RIM pack are not run (xmllint supports ISO Schematron only partly); the rules the generator depends on (header keys match, starter declaration with a start date, two address lines without a NINO, reduced-rate letters, Freeport postcode) are enforced in code.
- Employee records now hold NINO, date of birth, address and gender in the owner's OneDrive (`_System/Payroll/employees.json`); audit lines carry ids only.
- Reports can register with the shared export registry (branch `claude/exports`, empty when this was written): `payroll_reports.REPORTS`-style pure functions and `render()`; accounting-package journal formats are left to that framework (`journal_rows`).

## What a payroll professional should check

1. Run two or three employees (cumulative, W1/M1, Scottish, K code, director) through HMRC's PAYE calculator or Basic PAYE Tools and compare tax, NI and YTD.
2. FPS data items 58/59/58B: `PayAfterStatDedns` is taxable pay less tax, NI and loans (net-pay pension already out); relief-at-source contributions are in `DednsFromNetPay` and `EmpeePenContribnsNotPaid`. Confirm this matches HMRC's intent.
3. Salary sacrifice: AE assessment uses pay before sacrifice; contributions are on pre-sacrifice pay; employer NI savings are not passed on.
4. Statutory pay: SMP 90 % of AWE rounded up to the penny (assumed); SSP daily rates rounded up (matches HMRC's table); EPS recovery: small employers report 100 % recovered plus 9 % NIC compensation, others 92 %.
5. Directors: annual method only (not the alternative arrangements); directors with student loans are calculated per period (flagged).
6. Pension files against each provider's current template; contribution rounding (half up to the penny) against the provider's; People's Pension member contribution entered as deducted (net under RAS).
7. Overtime: weeks are Monday-Sunday and only entries dated inside the pay period count towards the weekly limit (a week split across two pay periods is counted separately in each). Holiday pay is not averaged.
8. Employment Allowance: claimed in full against employer NI until £10,500; eligibility (sole-director rule, connected companies) is the employer's call (a warning shows).
