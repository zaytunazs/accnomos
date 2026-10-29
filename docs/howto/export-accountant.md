# Export for your accountant

Who this is for: an owner sending a period's records to their accountant.
Exports are copies; the books stay untouched in your OneDrive.

1. Open Reports and exports (`/reports/exports`) and pick the period.
   ![step 1](../howto/img/export-accountant-1.png)
   Must be visible: the report list with the period controls and the period
   shown in the address.
   If this goes wrong: the period controls are disabled, so pick a report that
   takes a period first.
2. Export the VAT return as sent.
   ![step 2](../howto/img/export-accountant-2.png)
   Must be visible: the VAT-return export matching the boxes on `/vat` for the
   same period and scheme.
   If this goes wrong: the boxes differ, so the return was edited after
   submission; export again from the current page.
3. Export the Income Tax summary (SA103) for the period.
   ![step 3](../howto/img/export-accountant-3.png)
   Must be visible: the SA103 summary with turnover, expenses and the ledger
   lines behind each box.
   If this goes wrong: a box is empty, so that trade had no entries in the
   period; check the date range.
4. Export the full ledger and the audit trail as CSV.
   ![step 4](../howto/img/export-accountant-4.png)
   Must be visible: the ledger and audit exports with every column heading
   kept, even for an empty section.
   If this goes wrong: a file opens with missing columns, so export again;
   headings are always written.
5. Send the files from `07 Reports/` with Books.xlsx beside them.
   ![step 5](../howto/img/export-accountant-5.png)
   Must be visible: the dated files in `07 Reports/` and the current
   `Books.xlsx` on Files.
   If this goes wrong: Books.xlsx is stale, so press *Rebuild Books.xlsx* on
   Files before sending it.
