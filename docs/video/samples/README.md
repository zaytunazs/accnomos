# Ten extra sample documents (proposal, 4 Nov 2026)

`S01`–`S10` are fictional UK receipts and invoices for the demo's Bramblewood Joinery Ltd, written by hand in
`gen_samples.py` (no model involved), with English supplier and customer names. Every one prints **SAMPLE — FICTIONAL
COMPANY**. Arithmetic is done in pence in code. Supplier VAT numbers follow the gold set's fictional scheme (leading 0
block, valid mod-97 checksum, not checked against HMRC); Bramblewood keeps `GB 123 4567 89`.

| File | Case | Note |
|---|---|---|
| S01 | trade-counter receipt | 20 %, 3 lines |
| S02 | fuel receipt | diesel, 20 % |
| S03 | café receipt | small, subsistence |
| S04 | merchant invoice | over £250, VAT number printed |
| S05 | subcontractor invoice | £480, no VAT, no VAT number → `needs_a_look` ("Is the supplier VAT-registered?") |
| S06 | electricity bill | direct debit, 20 % |
| S07 | software subscription | card |
| S08 | sales invoice issued by Bramblewood | `side: sale` |
| S09 | car-park ticket | cash, no VAT (T9) |
| S10 | supplier credit note | negative amounts, as printed |

Each `.json` has the same keys as `evals/gold/receipts/061+`; each `.png` is the clean render from
`evals/harness/render.py`. `index.json` lists them.

**Not wired in.** The live demo seed is unchanged. To use them:
1. Copy them into `evals/gold/receipts/` as `201_<case>.json` … `210_<case>.json` and add their entries to
   `evals/gold/manifest.json` (everything except `printed_text`, as for 061+).
2. In `tools/seed_demo.py`, add the new file names to the inbox list `build_plan` uses (next to `INBOX_SALE` and
   `INBOX_NEEDS_A_LOOK`), or to the posted set. `services/runtime/tests/test_seed_demo.py` and `test_demo.py` will need
   their expected counts raised.
3. Run the extraction eval on them (`--gold-dir`) before demoing, so the demo shows documents the readers are known to
   get right.
