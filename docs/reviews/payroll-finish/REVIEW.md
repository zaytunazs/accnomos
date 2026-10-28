# Review: finishing PAYE payroll and pensions — branch `claude/payroll-finish`

Built on `claude/payroll-rti` (not yet merged into `main`), whose own review is now at
`docs/reviews/payroll-rti/REVIEW.md` (moved from the repo root; its `HANDOVER.md` is retired: every item it left open is
closed below except the Android compile, which still needs Flutter).

## What changed

| Area | Change |
| --- | --- |
| Rates | Every 2026-27 figure re-read at source and matched (no figure changed). Citations added for SSP (GOV.UK employer guide) and the re-read noted in `app/paye_rates.py`. New test: the per-month and per-week student and postgraduate loan thresholds equal the figures printed on the GOV.UK rates page. |
| RTI files | `app/rti.py`: every FPS and EPS opens with an XML comment (`FILE_NOTICE`): not submitted to HMRC; must be filed using HMRC's Basic PAYE Tools (or a recognised provider's software); direct submission from Accnomos is not available. The files still validate against HMRC's 2026-27 XSDs. |
| Pension files | `app/pension_ae.py`: **new Smart Pension PAPDIS 1.0 file** (43 fields, net pay arrangement only: relief at source is refused with a message); **Nest** trailer now carries file version 4 (current guide) and reason codes 1 (left), 9 (opted out), 5 (insufficient earnings); **The People's Pension** file now has the details-section heading row its guide requires and drops the characters it refuses (`= ! ' [ ] " \`) instead of CSV-quoting or prefixing them; missing/partial codes 1, 4, 5. |
| API / web | `smart_pension` provider on `GET /payroll/paye/payruns/{rid}/pension/{provider}`; web button and setting; Nest payment source field (the Nest header needs it and there was no way to enter it). |
| Bugs found by the first e2e run | The Payroll settings panel was bound to "no PAYE reference yet", so it collapsed as soon as one was typed (now opens once on load, then the user controls it). Payroll amounts were shown as `£3000.00`; now `money()` (exact pence, `£3,000.00`). |
| Property tests | `tests/test_payroll_properties.py` (Hypothesis, 11 properties). |

Already present from `claude/payroll-rti` and re-checked here: cumulative and week 1/month 1 codes including Scottish
(S), Welsh (C), K codes and the 50 % limit; overtime and enhanced rates (time and a half, double time) from timesheet
lines; payslip PDF; P32-style employer payment record; FPS and EPS XML; P45 and P60 figures as reports (web, PDF, CSV,
XLSX).

## Sources (all read 28 Oct 2026)

gov.uk is outside this container's network policy, so pages were read through a web reader (Exa); the URLs are the
originals.

- HMRC, Rates and thresholds for employers 2026 to 2027 (published 30 Jan 2026, last updated 1 Sep 2026):
  https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027 — personal allowance; England/NI, Scottish
  (final: 19 % to £3,967, 20 % to £16,956, 21 % to £31,092, 42 % to £62,430, 45 % to £125,140, 48 % above) and Welsh
  bands; emergency codes; every NI threshold and letter; Class 1A 15 %; SMP and other parental pay £194.32; recovery
  92 % / 109 %; SSP £123.25 or 80 % of AWE with the daily-rate table; loans (plan 1 £26,900, plan 2 £29,385, plan 4
  £33,795, plan 5 £25,000 at 9 %; postgraduate £21,000 at 6 %); Employment Allowance £10,500. All matched the code.
- GOV.UK, Statutory Sick Pay employer guide, Eligibility and Entitlement: https://www.gov.uk/employers-sick-pay/entitlement
  — SSP from the first full day of sickness, no lower earnings limit in the eligibility list (the Employment Rights Act
  2025 changes from 6 April 2026), lower of £123.25 and 80 % of AWE. Matches `paye.ssp_amount` (no waiting days; the
  user enters the days to pay).
- The Pensions Regulator, Earnings thresholds 2026-2027:
  https://www.thepensionsregulator.gov.uk/employers/new-employers/im-an-employer-who-has-to-provide-a-pension/declare-your-compliance/ongoing-duties-for-employers/earnings-thresholds
  — £6,240 / £10,000 / £50,270 and every per-period figure: matched.
- Nest, Employer payroll guide (the edition on Nest's site), section 3.2 contribution schedule:
  https://www.nestpensions.org.uk/schemeweb/dam/nestlibrary/employer-payroll-guide.pdf — header 11 fields, detail 21,
  trailer version "4"; and the help centre page "Complete contribution CSV file using template".
- The People's Pension, Contributions file data requirements v9 (with effect from August 2020; the version it links
  today): https://uvlznp.files.cmp.optimizely.com/download/assets/contributions-file-data-requirements.pdf/15821c5c27ad11f1b359f6bb85ab62d3
- Smart Pension, CSV Specification – PAPDIS 1.0 – PAP01:
  https://uploads-ssl.webflow.com/5de10f93d41c9b7a31b7c9ca/5f461a5a33c1194026afe6e8_smart-pension-csv-data-interface-specification-papdis-1.0.pdf
  and help centre "How do I use a PAPDIS file to upload pre-assessed pension contributions?":
  https://www.smartpension.co.uk/help-centre-articles/how-do-i-use-a-papdis-file-to-upload-pre-assessed-pension-contributions

## Tests

- Runtime: `cd services/runtime && python -m pytest -q` — **1407 passed, 1 skipped** (4 min 2 s). Before this branch's changes the same suite
  was 1390 passed, 1 skipped (the five tests that timed out on `claude/payroll-rti`'s overloaded machine pass).
  New or changed here: `test_payroll_properties.py` 11 properties (≈1,000 generated cases per run), `test_pension_ae.py`
  +5 (Nest reason codes and trailer, People's Pension headings/characters/codes, Smart Pension layout, leaver/opt-out/
  sacrifice, relief-at-source refusal), `test_rti.py` (notice in FPS and EPS, still schema-valid), `test_paye_rates.py`
  +1, `test_payroll_reports.py` (Smart Pension route refuses relief at source).
- HMRC worked examples (from `claude/payroll-rti`, unchanged): Tables A free pay, all twelve 2026-27 NI examples, the
  SSP amounts table, two director examples. No 2026-27 PAYE worked examples are published.
- `ruff check . && ruff format --check .` clean; `pyright services/runtime/app` 0 errors; `pnpm exec eslint .` clean.
- e2e (`CI=1`, 3 workers): **225 passed, 58 skipped, 0 failed** in 6.8 min; the 58 skips are `shots.spec.ts`, which runs only with `SHOTS=1`. `e2e/paye.spec.ts` now also checks the notice inside the FPS and the Smart Pension refusal. Run
  locally with a throwaway Playwright config pointing at the container's Chromium (the pinned Playwright 1.64's browser
  build is not installed here); not committed.

## Risks and open items

- **Not HMRC-recognised; never submits.** Basic PAYE Tools cannot import these XML files: the user enters the figures
  there (or their provider files them). Said on the page, in every file note and inside the files.
- **Pension files never uploaded to a live account.** Smart Pension's spec does not say whether a heading row is
  expected (one is written). Nest "Tax Weekly"/"Tax Monthly" schedule frequencies are not written; the paper opt-out
  notice fields are blank; family leave, group and payment-source change codes are not produced.
- Directors' alternative NI arrangement, quarterly/annual pay, SPP/SAP/ShPP/SPBP/SNCP, benefits in kind, apprenticeship
  levy: still not covered (stated in HONESTY.md and on the page).
- **Outside this branch, worth a look:** the same GOV.UK page says mileage allowance payments for cars rose from 45p to
  55p a mile for the first 10,000 miles (update of 5 June 2026; also the NI rate). `services/runtime/app/mileage.py`
  still uses 45p. Not changed here (vehicles feature, not payroll); the effective date needs checking.
- Android `pay_overtime` card: still not compiled (no Flutter here).
