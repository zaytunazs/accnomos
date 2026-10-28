# Synthetic gold set

200 fictional UK receipts and invoices used to grade the extraction pipeline (Glimmer / Spark 1.3) in `evals/harness`, plus
bank statements and mailbox fixtures built from the 140 newest. Every supplier, customer, address and person is invented and
every document carries the label `SAMPLE — FICTIONAL COMPANY` (in the `label` field for 001-060, and also printed on the
document for 061-200).

- Generated during the hackathon by gen_gold.py (Qwen3.8-27B on our DGX Spark as a *test-data generator*; it is not part of the product runtime). Arithmetic is validated in code; invalid outputs were dropped.
- Cases: standard, mixed-rate, reduced (5%), zero-rated, exempt, cash/no VAT, no VAT number over GBP 250, full VAT invoice, sales invoice, deliberate arithmetic error, EUR reverse-charge.
- Every supplier and company is fictional. label = "SAMPLE - FICTIONAL COMPANY". Day 2 renders printed_text to receipt images (clean + messy photos) for the vision tests.

## Bank statements (`bank/`)

Four October 2026 statement CSVs for fictional businesses (label "SAMPLE - FICTIONAL COMPANY" in `expected.json`; the account numbers, customers, references and amounts are made up, while card-payment payees such as Screwfix or Shell are real UK merchants named only as they would appear on a statement) in the three layouts the bank reader handles (see `packages/ledger/src/accnomos_ledger/bank.py`): `barclays.csv` and `monzo.csv` (one signed Amount column), `starling.csv` (signed amount + counter party + balance), `tide.csv` (Paid in / Paid out). Hand-written, not generated. `expected.json` lists the posted ledger events they are matched against and, per line, the expected match (exact/suggested) or the suggested action for an unmatched line. Graded by `packages/ledger/tests/test_bank_gold.py` and `services/runtime/tests/test_bank_gold.py`. Column layouts are modelled on the banks' public export formats; check them against a real export before relying on the bank name.
The generated data is for tests only. Qwen3.8-27B (local vLLM on the DGX Spark) is a *test-data generator*, not a product model.

## Layout

| Path | What |
|---|---|
| `receipts/NNN_<case>.json` | One gold document: supplier, date, lines, totals, `printed_text` (what the renderer draws) |
| `manifest.json` | One entry per document. 061+ carry the full gold fields (pence, VAT code, side, expected status) minus `printed_text` |
| `gen_gold.py` | Generator for 001-060 (Qwen writes whole documents; arithmetic validated in code) |
| `gen_gold_v2.py` | Generator for 061-200 (Qwen invents names, addresses and items; **code** does VRNs, dates, arithmetic in pence, layouts) |
| `gen_bank_mail.py` | Builds `bank/` and `mail/` from the gold documents (pure code, seeded) |
| `bank/` | 6 statement CSVs + `expected_matches.json` (the truth: which row pays which document) |
| `mail/MNN.json`, `mail/attachments/` | 20 Graph-style mailbox fixtures and their attachment files |

## Documents 001-060

standard, mixed-rate, reduced (5 %), zero-rated, exempt, cash / no VAT, no VAT number over £250, full VAT invoice, sales
invoice, deliberate arithmetic error, EUR reverse-charge. Arithmetic validated in code; invalid outputs were dropped.

## Documents 061-200 (140)

| `gold_case` | n | What |
|---|---:|---|
| `r_fuel` / `r_trade` / `r_cafe` / `r_parking` | 10 / 12 / 10 / 8 | Purchase receipts (40): forecourts, trade counters, cafés, car parks |
| `pi_merchant` / `pi_subcontractor` / `pi_software` | 12 / 10 / 8 | Purchase invoices (30) to Bramblewood Joinery Ltd |
| `sales` | 30 | Sales invoices **issued by** Bramblewood Joinery Ltd (`side: sale`), the side-orientation test |
| `utility` | 15 | Business electricity (20 %), reduced-rate gas (5 %), broadband, mobile, water (0 %), landline |
| `credit_note` | 10 | 8 supplier credit notes (purchase side) and 2 Bramblewood credit notes (sale side). **Amounts are negative, as printed** |
| `edge_multi_rate` / `edge_zero` / `edge_reverse_charge` / `edge_foreign_gbp` / `edge_handwritten` / `edge_torn_faded` | 3 / 3 / 2 / 3 / 2 / 2 | Edge cases (15) |

Gold fields added in 061+: `net_pence`, `vat_pence`, `gross_pence`, `vat_code` (`T1` 20 %, `T5` 5 %, `T0` zero, `T9` outside scope,
`RC` reverse charge, `MIXED`), `side` (`purchase` / `sale`), `expected_status` (`proposed` / `needs_a_look`), `is_credit_note`,
per-line `vat_code`, and `damage` (`handwritten` / `faded` / `torn`, used by the renderer).

- `expected_status` follows the checks in `services/runtime/app/checks.py`, for a VAT-registered business whose books do not know the supplier yet (the eval has no books): `needs_a_look` when VAT is charged and no VAT number is printed, when a purchase over £250 charges no VAT and shows no VAT number ("Is <supplier> VAT-registered?", owner's rule of 27 Oct 2026), or when the currency is not GBP. 001-060 keep the older rule in `run_extraction.expected_status`; under it, `no_vat_number` 005, 016, 027 and 049 (over £250) expect `needs_a_look` and so does the new check, while 038 and 060 (under £250, no VAT) also expect it although the check passes them, as the owner's rule says.
- `edge_foreign_gbp`: the printed document shows EUR or USD and the rate, but the amount charged and the gold totals are in GBP, with no UK VAT (`T9`). 176 and 184 are over £250 with no VAT number, so they expect `needs_a_look` since 27 Oct 2026 (they were `proposed`): the reading has no supplier address, so code cannot tell an overseas supplier from a UK one, and the user answers the question once per supplier.
- `edge_reverse_charge`: UK labour-only construction invoice, VAT not charged. The note says what VAT *would* have been (a trap for readers that grab any "VAT" figure). Gold VAT is 0.
- `edge_handwritten`: lines drawn with `~` are rendered in blue italic as stand-in handwriting. `edge_torn_faded`: faded thermal paper, or a torn bottom edge and corner.
- Duplicate supplier names: Qwen reused one name (a supplier appears twice); kept and left in the manifest.

### VAT numbers

New suppliers get a fictional VRN: a leading `0` block and a valid mod-97 checksum, so they pass format validation. They were not
checked against HMRC, only chosen to be unlikely to be live numbers. Bramblewood's `GB 123 4567 89` is kept from the first set for
continuity; it is *not* checksum-valid.

## Rendering

`harness/render.py` turns `printed_text` into images (clean scan, or a messy phone photo: rotation, shear, uneven lighting, the
odd fold). `python -m harness.render_gold OUT_DIR` writes all of them; `run_extraction --messy` renders the same images in
memory (seed = position in the sorted gold directory). PNGs are not committed, except the ones used as mail attachments.
Five long builders' merchant invoices (102, 105, 150, 170, 175) come out just over 300 KB as messy photos (so
`render_gold` exits non-zero on a full run); none of those are committed or used as attachments.

## Bank statements (`bank/`)

Three layouts, two statements each (Jul-Aug and Sep-Oct 2026): `barclays_*` (`Number,Date,Account,Amount,Subcategory,Memo`),
`starling_*` (`Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP),Spending Category`) and `tide_*`
(`Transaction ID,Transaction Date,Transaction Type,Transaction Information,Paid In,Paid Out,Balance`). Header sets are modelled on
those banks' exports from memory, not on real files. Card payments go to Starling, BACS and direct debits to Barclays, money in
from customers and credit-note refunds to Tide.

96 of 140 documents (69 %) have a payment line. Noise: truncated upper-case merchant names with card refs, payment lag, 10 invoices
paid in two parts, 2 card payments 1p off (rounding), cash receipts never appear, and 6-8 unrelated lines per statement (wages,
HMRC, rent, transfers...). `expected_matches.json` lists every row's document (or `null`), the split and rounding documents and the
documents with no payment.

`python -m harness.check_bank_mail` checks the CSVs against `accnomos_ledger.bank.parse_bank_csv`; all six parse (the Tide
`Transaction Information` header was added to the parser in review). `pytest evals/tests` runs the same checks offline.

## Mailbox fixtures (`mail/`)

Microsoft Graph shapes (`id`, `receivedDateTime`, `from.emailAddress`, `hasAttachments`, `attachments[]` with `contentType`,
`size`, `isInline`), plus `path` / `gold` per attachment and `expected.intake` (what intake should do with each one).
M01-M09 one document each (PNG photo or image-only PDF), M10-M12 two documents, M13-M14 the same file twice (duplicate),
M15 newsletter (inline images, tracking pixel), M16 marketing PDF, M17 calendar invite, M18 signature images, M19 invoice plus
signature logo, M20 unsupported zip with no invoice.

## Spark-generated sets (made on the DGX Spark, not committed until generated)

- `ledger2/`: credit notes, part-paid invoices and overlapping bank pairs (`gen_gold2.py`).
- `ledger4/` (`gen_gold4.py`): about 120 price-history receipts from five fictional suppliers over six months, with
  `expectations.json` (normalised unit prices, cheapest supplier, "cheaper elsewhere" hints).
- `personal/` (`gen_personal.py`): six-month household bank statements with recurring-bill and category-total
  expectations.
- `landlord/` (`gen_gold_landlord.py`): a fictional landlord with two lets (a flat owned alone, a house owned with a
  spouse, taxed 50:50): six months of letting agent statements (rent, 10 % fee plus VAT, a repair deducted) and the
  property bills (insurance, a mortgage statement split into capital and interest, gas safety, a boiler repair, a
  like-for-like washing machine, ground rent and service charge), with expectations by HMRC property category, per
  owner, and the Property Business API 6.0 bodies `app/property.py` should produce. Not generated yet: run
  `python evals/gold/gen_gold_landlord.py` on the Spark; `evals/tests/test_gen_gold_landlord.py` runs it on the stub.

Qwen only names things; code sets every figure. See `evals/README.md` for the commands and `spark_gen.py` for the label
guard (every generated file must contain the exact label with the em dash, U+2014).
