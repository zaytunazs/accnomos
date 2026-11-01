# Bank-rule AI coding eval

Model `muse-glimmer:30b` at `http://localhost:11434`; 2026-10-28T07:44:04+00:00. Code under test: `app.bank_reconcile.suggest_ai`.

- Lines asked: **459** (285 scored, 174 with no expense account, reported but not scored)
- **Accuracy: 91.6%** of scored lines (a refusal counts as wrong); 91.6% of those it answered; primary-account-only 78.2%
- Refusals (no suggestion): **0** (0.0%): {}
- Invalid JSON / shape: 0; account outside the list: 0; bad VAT code: 0; transport errors: 0
- Latency per line: mean 4.52 s, p50 4.463 s, p95 5.775 s, max 6.764 s (total 2074.6 s)

## By statement set

| Set | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| hand-written | 13 | 13 | 100.0% |
| ledger2 | 189 | 189 | 100.0% |
| two-month | 83 | 59 | 71.1% |

## By expected account

| Expected | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| 5000 Materials | 62 | 62 | 100.0% |
| 5100 Tools & small equipment | 50 | 50 | 100.0% |
| 7100 Rent | 6 | 6 | 100.0% |
| 7200 Utilities | 5 | 4 | 80.0% |
| 7300 Motor expenses | 60 | 60 | 100.0% |
| 7400 Travel | 6 | 2 | 33.3% |
| 7410 Subsistence | 10 | 6 | 60.0% |
| 7510 Software & subscriptions | 6 | 4 | 66.7% |
| 7550 Telephone & internet | 36 | 31 | 86.1% |
| 7600 Professional fees | 8 | 0 | 0.0% |
| 7700 Insurance | 5 | 5 | 100.0% |
| 7900 Bank charges | 31 | 31 | 100.0% |

## Top confusions

- expected 7600 Professional fees -> got 5000 Materials: 8
- expected 7550 Telephone & internet -> got 7999 Sundry expenses: 4
- expected 7410 Subsistence -> got 5000 Materials: 4
- expected 7400 Travel -> got 6200 Advertising: 2
- expected 7510 Software & subscriptions -> got 7600 Professional fees: 2
- expected 7550 Telephone & internet -> got 7510 Software & subscriptions: 1
- expected 7200 Utilities -> got 5000 Materials: 1
- expected 7400 Travel -> got 5000 Materials: 1
- expected 7400 Travel -> got 7300 Motor expenses: 1

## Lines with no expense account (not scored): what the model did

{'5000 Materials': 125, '7999 Sundry expenses': 40, '7900 Bank charges': 3, '7600 Professional fees': 2, '7200 Utilities': 2, '7410 Subsistence': 1, '7100 Rent': 1}

## Misses (scored lines the model answered wrongly, first 25)

| Description | Amount | Expected | Got | Reason |
|---|---:|---|---|---|
| WRENWOOD FINISHING & FIT-OUT WFF-99650 FP 06 JUL | -252.00 | 7600 Professional fees | 5000 Materials | Payment to WRENWOOD FINISHING & FIT-OUT for fit-ou |
| THORNFIELD COMMS DD REF 3341213 | -64.20 | 7550 Telephone & internet | 7999 Sundry expenses | Direct debit from THORNFIELD COMMS with no clear e |
| HARROGATE MOBILE SOLUT DD REF 4039946 | -135.55 | 7550 Telephone & internet | 7510 Software & subscriptions | Direct debit from HARROGATE MOBILE SOLUT suggests  |
| HOLLOWAY & FINCH TRADES HFT-67164 FP 19 AUG 4019 | -1104.00 | 7600 Professional fees | 5000 Materials | Trade supplier reference HFT-67164 with FP 19 AUG  |
| HARROWGATE PRECISION TRADES HPT-43872 FP 25 AUG  | -1308.00 | 7600 Professional fees | 5000 Materials | Payment to HARROWGATE PRECISION TRADES with refere |
| WHITBY WOOD & WIRE SERVICES WWW-84471 FP 29 AUG  | -750.00 | 7600 Professional fees | 5000 Materials | Payment to WHITBY WOOD & WIRE SERVICES for invoice |
| HARROWGATE TRADES LTD HTL-22328 (PART) FP 05 SEP | -410.40 | 7600 Professional fees | 5000 Materials | Trade supplier name in description with invoice re |
| HIGHLAND MOBILE SOLUTI DD REF 5983849 | -148.20 | 7550 Telephone & internet | 7999 Sundry expenses | Description is 'HIGHLAND MOBILE SOLUTI DD REF 5983 |
| HARROWGATE TRADES LTD HTL-22328 (PART) FP 17 SEP | -957.60 | 7600 Professional fees | 5000 Materials | Payment to HARROWGATE TRADES LTD with invoice HTL- |
| HAREWOOD LINE SOLUTION DD REF 7418473 | -115.20 | 7550 Telephone & internet | 7999 Sundry expenses | Description 'HAREWOOD LINE SOLUTION DD REF 7418473 |
| THORNBURY FLOW SYSTEMS DD REF 8174373 | -2430.75 | 7200 Utilities | 5000 Materials | Direct debit from THORNBURY FLOW SYSTEMS suggests  |
| ALDERGATE CRAFT SERVICES ACS-93436 FP 15 OCT 651 | -222.00 | 7600 Professional fees | 5000 Materials | Craft services supplier name in description sugges |
| J. OATES & SONS JOS-83537 FP 17 OCT 202655 | -828.00 | 7600 Professional fees | 5000 Materials | Payment to J. OATES & SONS, likely materials purch |
| SHEFFIELD VOICELINK LT DD REF 4873464 | -147.00 | 7550 Telephone & internet | 7999 Sundry expenses | Direct debit payment to SHEFFIELD VOICELINK LT; de |
| The Crumb & Crust Collective | -60.85 | 7410 Subsistence | 5000 Materials | Payment to The Crumb & Crust Collective likely for |
| Huddersfield Valet & Display Services Ltd | -3.00 | 7400 Travel | 6200 Advertising | Payment to Huddersfield Valet & Display Services L |
| Wakefield Wheel & Watch Ltd | -8.66 | 7400 Travel | 5000 Materials | Description is Wakefield Wheel & Watch Ltd, a supp |
| Thornbury Digital Solutions Ltd | -1078.79 | 7510 Software & subscriptions | 7600 Professional fees | Card payment to Thornbury Digital Solutions Ltd, l |
| Lincolnshire Logic Labs | -540.00 | 7510 Software & subscriptions | 7600 Professional fees | Card payment to Lincolnshire Logic Labs on 13 AUG, |
| Chesterfield Car Parks Ltd | -3.11 | 7400 Travel | 7300 Motor expenses | Car park charge is a vehicle-related expense; desc |
| Saltmarsh Pantry | -189.77 | 7410 Subsistence | 5000 Materials | Card payment to Saltmarsh Pantry looks like a purc |
| Durham Display Solutions Ltd | -18.37 | 7400 Travel | 6200 Advertising | Card payment to Durham Display Solutions Ltd, like |
| Preston Piquant Pantry | -110.60 | 7410 Subsistence | 5000 Materials | Card payment to Preston Piquant Pantry looks like  |
| Salt & Sesame Ltd | -239.40 | 7410 Subsistence | 5000 Materials | Payment to Salt & Sesame Ltd; description gives no |

## Refusals (first 15)

| Description | Outcome | Raw reply (start) |
|---|---|---|

How the expectation is derived: see the module docstring of `evals/harness/bank_ai.py` (gold document category, statement kind, or an ordered keyword table; sets of defensible accounts).
