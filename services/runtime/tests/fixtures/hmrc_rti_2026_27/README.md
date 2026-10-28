# HMRC RTI schemas, tax year 2026-27

`FullPaymentSubmission-2027-v1-0.xsd` and `EmployerPaymentSummary-2027-v1-0.xsd`, unchanged, from HMRC's
"RTI RIM 2027 v1.0" pack (`RTI-RIM-2027-v1-0.zip`, sha256 `e6768cec…a389a32`), published on
<https://www.gov.uk/government/publications/real-time-information-internet-submissions-2026-to-2027-technical-specifications>
and downloaded on 28 Oct 2026.

| File | sha256 |
| --- | --- |
| FullPaymentSubmission-2027-v1-0.xsd | `0128c9b6de5f258d88193983f8bb90e12bf0aa9a3e4cde15e7cd1f008c5ad528` |
| EmployerPaymentSummary-2027-v1-0.xsd | `bdc2426bfa961a77b4123dc597de77f10185b16ef9772ad0ba871ecdc73ff0ec` |

© Crown copyright 2013-2025, published by HM Revenue & Customs on GOV.UK and used under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

`tests/test_rti.py` validates the FPS and EPS files Accnomos generates against these schemas with `xmllint` (skipped
when `xmllint` is not installed). The pack's Schematron business rules (`.sch`) are not run; the rules the generator
relies on are checked in code and listed in REVIEW.md.
