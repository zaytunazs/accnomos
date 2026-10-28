"""Reports and exports for accountants: one registry of report -> formats, one download route, saved to 07 Reports.

    registry.py     ReportDoc (the shape every report and import file is built as), ExportSpec, register(), CATALOGUE
    writers.py      ReportDoc -> CSV, XLSX, PDF (and a vendor import file -> CSV in that vendor's dialect)
    accounts.py     trial balance (and by date range), general ledger detail and summary, ledger exceptions,
                    journal report, account transactions, audit trail of postings, cash book
    statements.py   balance sheet, P&L with comparatives, cash flows (direct), changes in equity, executive
                    summary, cash summary, management report
    receivables.py  aged receivables and payables (detail, summary), invoice and bill registers, per-contact reports
    reconciliation.py  account summary, bank reconciliation, bank summary, uncoded and duplicate statement lines
    vat_reports.py  the 9-box VAT return laid out like HMRC's, the VAT detail behind each box,
                    the MTD digital-links trail, the VAT reconciliation
    mapping.py      the books' accounts and VAT codes -> each package's codes; user overrides in
                    _System/exports/mappings.json
    vendors.py      Xero, QuickBooks Online, Sage 50, Sage Accounting and FreeAgent import files
    pack.py         the Accountant pack zip, the open ledger JSON, the contact list, one zip per package

Every figure is worked out by code from the approved ledger events; nothing here posts to the ledger. The routes are
app/routes_exports.py. Other features register their own reports with `registry.register(...)` and add their module
to `registry.OPTIONAL_PLUGINS` so the catalogue imports it.
"""
