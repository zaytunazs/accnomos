# Extraction eval: Glimmer on 200 messy documents (muse-glimmer:30b, local)

Docs: **200** (60 original + 140 new from Qwen) | messy phone-photo renders | errors: 0 | mean 22.16 s per document (max 39.81 s)

Run: `python -m harness.run_extraction --mode local --messy --business-name 'Bramblewood Joinery Ltd'`; no extraction code was changed. Differences from the 60-document report: `side` is a new scored field, expected status is explicit per document on 061-200, and the books owner's name is passed to the pipeline so sale/purchase orientation runs.

## Headline

- All fields correct (incl. side and status): **88%** (original 60: 82%, new 140: 91%)
- Side accuracy: **100%**; status accuracy: **93%**

## Accuracy per field

| Field | all (n=200) | 001-060 (n=60) | 061-200 (n=140) |
|---|---:|---:|---:|
| supplier_name | 100% | 100% | 100% |
| vat_number | 98% | 93% | 100% |
| date | 100% | 100% | 100% |
| net_total | 93% | 97% | 91% |
| vat_total | 97% | 100% | 96% |
| gross_total | 98% | 100% | 97% |
| line_count | 100% | 100% | 99% |
| side | 100% | 100% | 100% |
| status | 93% | 90% | 94% |
| **all fields except status** | 90% | 90% | 91% |
| **all fields** | 88% | 82% | 91% |

## Side (sale vs purchase)

Side accuracy: **100%** (200/200).

| Gold side | read as sale | read as purchase |
|---|---:|---:|
| sale | 37 | 0 |
| purchase | 0 | 163 |

`DOC_TYPE_ORIENTED` fired on 35 documents (run with `--business-name 'Bramblewood Joinery Ltd'`).

## Check status

| Expected \ got | proposed | needs_a_look |
|---|---:|---:|
| proposed | 170 | 9 |
| needs_a_look | 5 | 16 |

Checks that did not pass (documents):

| Check | fail | warn |
|---|---:|---:|
| CONFIDENCE | 0 | 54 |
| ARITH_LINES | 3 | 37 |
| ARITH_TOTALS | 9 | 26 |
| VAT_NUMBER_REQUIRED | 10 | 0 |
| VAT_MATH | 6 | 0 |
| VAT_NUMBER_FORMAT | 5 | 0 |
| CURRENCY_GBP | 4 | 0 |
| VAT_RATE_VALID | 1 | 0 |

## Per gold case

| Case | n | All fields | Side | Status | Errors |
|---|---:|---:|---:|---:|---:|
| cash_no_vat | 5 | 100% | 100% | 100% | 0 |
| credit_note | 10 | 100% | 100% | 100% | 0 |
| edge_foreign_gbp | 3 | 100% | 100% | 100% | 0 |
| edge_handwritten | 2 | 0% | 100% | 50% | 0 |
| edge_multi_rate | 3 | 33% | 100% | 33% | 0 |
| edge_reverse_charge | 2 | 100% | 100% | 100% | 0 |
| edge_torn_faded | 2 | 50% | 100% | 50% | 0 |
| edge_zero | 3 | 100% | 100% | 100% | 0 |
| exempt | 5 | 100% | 100% | 100% | 0 |
| foreign | 5 | 40% | 100% | 80% | 0 |
| full_invoice | 5 | 100% | 100% | 100% | 0 |
| mixed | 6 | 83% | 100% | 83% | 0 |
| no_vat_number | 6 | 0% | 100% | 33% | 0 |
| pi_merchant | 12 | 100% | 100% | 100% | 0 |
| pi_software | 8 | 100% | 100% | 100% | 0 |
| pi_subcontractor | 10 | 100% | 100% | 100% | 0 |
| r_cafe | 10 | 80% | 100% | 90% | 0 |
| r_fuel | 10 | 90% | 100% | 100% | 0 |
| r_parking | 8 | 100% | 100% | 100% | 0 |
| r_trade | 12 | 58% | 100% | 75% | 0 |
| reduced | 6 | 100% | 100% | 100% | 0 |
| sales | 30 | 100% | 100% | 100% | 0 |
| sales_invoice | 5 | 100% | 100% | 100% | 0 |
| standard | 11 | 100% | 100% | 100% | 0 |
| utility | 15 | 100% | 100% | 100% | 0 |
| zero | 6 | 83% | 100% | 100% | 0 |

## Claude judge

Judge: claude-haiku-5-5, escalating disagreements to claude-sonnet-5-5. Judged 200, skipped 0, first-pass disagreements with the code comparison 196, escalated 196.

| Final severity | Docs |
|---|---:|
| minor | 84 |
| none | 60 |
| major | 28 |
| unparsed | 27 |
| null | 1 |

Final judge verdict agrees with the code comparison (fields only) on 79/200 documents.

Most frequent judge-flagged fields (final verdicts): lines 167, category 30, category_guess 24, doc_type 11, category_hint 11, net_total 6, invoice_number 4, vat_total 2

Caveat: the judge is noisy and not a ground truth. It flagged line-item wording and category on most documents (`lines` 167, `category*` 65) and disagreed with the code comparison on nearly every first pass, and 27 verdicts did not parse as JSON (likely the 800-token reply cap). Treat the code-scored field accuracy above as the headline; use the judge only to spot-check `major` verdicts.

## Ten worst cases

| Document | Case | Failed | Diagnosis |
|---|---|---|---|
| 085_r_trade.json | r_trade | net_total, vat_total, gross_total | Multi-quantity lines: printed line totals were multiplied by qty again, so net/VAT/gross are about 3.4x the printed TOTAL (£1,192.62 vs £353.75); the printed total was ignored. |
| 185_r_trade.json | r_trade | net_total, vat_total, gross_total | Same qty-times-line-total inflation (£677.96 vs printed £248.31); `repair_line_totals` did not fire, probably because the printed total was not what the repaired lines summed to. |
| 106_r_cafe.json | r_cafe | net_total, vat_total, gross_total | VAT-inclusive TOTAL read as the net, then 20% added on top (net £110.60, gross £132.72 vs printed £110.60). |
| 125_r_trade.json | r_trade | net_total, gross_total, status | Printed TOTAL taken as net (£221.50) and VAT added to reach £258.43; line nets also qty-multiplied, so VAT_MATH and ARITH fail and status flips to needs_a_look. |
| 159_edge_multi_rate.json | edge_multi_rate | net_total, vat_total, status | Mixed 20/5/0% receipt with VAT-inclusive prices: net £358.54 and VAT £61.31 are line sums that do not reconcile to the correct gross £280.02. |
| 114_edge_handwritten.json | edge_handwritten | net_total, vat_total, status | Handwritten (blue italic) item lines gave net 0.00 and VAT 0.00; only the gross total was read, so every line failed the arithmetic check. |
| 091_edge_handwritten.json | edge_handwritten | net_total, vat_total | Handwritten block ends with 'VAT incl.'; read as no VAT (vat 0, net = gross), and the type came back purchase_invoice for a till receipt. |
| 081_r_cafe.json | r_cafe | net_total, status | Net total set equal to the printed TOTAL (VAT-inclusive), VAT right; ARITH_TOTALS fails and status wrongly goes to needs_a_look. |
| 095_r_trade.json | r_trade | net_total, status | Same net = gross slip on a VAT-inclusive trade receipt; VAT and gross correct, status wrongly needs_a_look. |
| 123_edge_torn_faded.json | edge_torn_faded | net_total, status | Faded thermal paper reads fine (supplier, VRN, VAT, gross all right) but net is again the VAT-inclusive total. |

## Suggested fixes

Not applied: this task did not change extraction code.

1. **VAT-inclusive receipts: net read as the printed TOTAL.** The dominant error: 8 of 200 documents have `net_total` equal to the printed gross where VAT was charged, and 6 more have other net errors. `r_trade` is the weakest case (58 % all fields), then `r_cafe` (80 %). Receipts print VAT-inclusive totals and a "VAT 20% net X / VAT Y" summary. Add a deterministic repair next to `repair_line_totals`: when `net + vat != gross` but `gross - vat` matches the VAT summary rate, set `net = gross - vat` and record a `Check`. Also tell the extraction prompt that `net_total` is *excluding* VAT and that the TOTAL line is the gross.
2. **Qty applied twice (085, 185, 125).** `repair_line_totals` only fires when the repaired lines reconcile exactly; inflated totals (about 3x) get through. Prefer the printed TOTAL as the anchor and rebuild lines to it, or flag the document `needs_a_look` instead of `proposed` when lines overshoot the total by more than one line.
3. **Handwritten totals (091, 114).** Reads gross only. A second pass or a fallback that derives net and VAT from gross and the printed rate, plus a `needs_a_look` for handwriting, would be safer than silently returning 0.00 VAT.
4. **Reverse-charge and foreign GBP documents** are read correctly (reverse-charge VAT is 0.00 on both; all 3 foreign-GBP documents are correct), so no change is suggested there.
5. **Foreign VAT numbers** (054, 021, 043): one missed entirely (054, which was also read as GBP, so it was `proposed` instead of `needs_a_look`), two have a character slip (`B01` read as `801`, a digit dropped). Low priority, since the status is `needs_a_look` anyway.
6. **Bank CSV parser** (`packages/ledger/src/accnomos_ledger/bank.py`): the Tide-style export header `Transaction Information` is not an accepted description alias, so both Tide fixtures are rejected. Add it (and `transaction type` as a fallback) to `HEADERS["description"]`. *Done in review: `transaction information` added; all six fixtures now parse.*
7. **Gold-set housekeeping (not pipeline).** The original 60 have inconsistent labels: four `no_vat_number` documents (016, 038, 049, 060) expect `needs_a_look` but have `vat_total` 0.00, which the checks (correctly) pass; four `full_invoice` documents carry `doc_type: sales_invoice` although Bramblewood is the customer. Consider fixing the gold, or treat those 4 status misses as gold errors.

