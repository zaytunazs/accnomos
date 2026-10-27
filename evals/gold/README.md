# Synthetic gold set

200 fictional UK receipts and invoices used to grade the extraction pipeline (Glimmer / Spark 1.3) in `evals/harness`, plus
bank statements and mailbox fixtures built from the 140 newest. Every supplier, customer, address and person is invented and
every document carries the label `SAMPLE — FICTIONAL COMPANY` (in the `label` field for 001-060, and also printed on the
document for 061-200).

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

- `expected_status` follows the checks in `services/runtime/app/checks.py`: `needs_a_look` when VAT is charged and no VAT number is printed, or when the currency is not GBP. 001-060 keep the older rule in `run_extraction.expected_status`.
- `edge_foreign_gbp`: the printed document shows EUR or USD and the rate, but the amount charged and the gold totals are in GBP, with no UK VAT (`T9`).
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
