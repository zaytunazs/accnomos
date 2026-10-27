"""The books folder layout: the only place its folder names are written down.

Every runtime module imports them from here. tools/gen_folders.py writes the same names (and the README.txt text
built below) to packages/connectors/folders.json, apps/web/src/lib/folders.ts and apps/mobile/lib/services/graph.dart;
tests/test_paths.py fails when any of those files differs from what this module generates, or when a folder name
appears as a string literal in other Python source.

Older versions of the app used other names. RENAMED maps each old name to the current one; app/layout.py moves an
old-named folder to its new name once, on first contact.
"""

from __future__ import annotations

from typing import NamedTuple


class Folder(NamedTuple):
    key: str  # stable identifier for code (web/Android use it too)
    name: str  # the folder name in the user's OneDrive
    note: str  # one line for README.txt and the Files page


INBOX = "00 Inbox"
RECEIPTS = "01 Receipts"
NEEDS_A_LOOK = "02 Needs a look"
SALES = "03 Sales"
INVOICES = f"{SALES}/invoices"
SENT = f"{INVOICES}/sent"
CREDIT_NOTES = f"{SALES}/credit-notes"  # app/credit_notes.py; created when the first credit note is saved
CREDIT_NOTES_SENT = f"{CREDIT_NOTES}/sent"
BANK = "04 Bank statements"
PAYROLL = "05 Payroll"
VAT_RETURNS = "06 VAT returns"
REPORTS = "07 Reports"

SYSTEM = "_System"
DOCS = f"{SYSTEM}/docs"
PROPOSALS = f"{SYSTEM}/proposals"
AUDIT = f"{SYSTEM}/audit"
EVENTS = f"{SYSTEM}/Ledger/events"
BANK_LINES = f"{SYSTEM}/bank"

TOP: tuple[Folder, ...] = (
    Folder(
        "inbox",
        INBOX,
        "drop receipts, invoices or statements here (photo, PDF, email attachment) and Accnomos will read them.",
    ),
    Folder(
        "receipts",
        RECEIPTS,
        'purchase documents Accnomos has filed, by month, renamed like "2026-10-21 Screwfix £38.47.pdf".',
    ),
    Folder(
        "needs_a_look",
        NEEDS_A_LOOK,
        "anything odd (duplicates, missing VAT number, unreadable), with a reason. Nothing in here is posted.",
    ),
    Folder(
        "sales",
        SALES,
        "sales documents. Invoices you write in Accnomos are in invoices/, and the exact PDF "
        "each customer was sent is in invoices/sent/.",
    ),
    Folder("bank", BANK, "the bank statement files you imported."),
    Folder("payroll", PAYROLL, "pay run exports for your payroll provider, one per month."),
    Folder("vat_returns", VAT_RETURNS, "the 9-box calculation and HMRC receipt for each period."),
    Folder("reports", REPORTS, "reports you asked Accnomos to save."),
)

# Every folder created when the books are set up (web onboarding, the runtime's first scan, the demo seed).
TREE: tuple[str, ...] = (*(f.name for f in TOP), INVOICES, SENT, SYSTEM, AUDIT, DOCS, PROPOSALS, EVENTS, BANK_LINES)

# Old top-level name -> current name. Never reuse a name in both columns.
RENAMED: dict[str, str] = {
    "02 Sales invoices": SALES,
    "03 Bank statements": BANK,
    "04 Needs a look": NEEDS_A_LOOK,
    "04 Payroll": PAYROLL,
    "05 VAT returns": VAT_RETURNS,
    "06 Reports": REPORTS,
}


def upgrade(path: str) -> str:
    """A path recorded under an old folder name, as it reads after the rename: '04 Needs a look/a.pdf' ->
    '02 Needs a look/a.pdf'. Other paths come back unchanged. OneDrive names are case-insensitive."""
    head, sep, rest = path.partition("/")
    for old, new in RENAMED.items():
        if head.casefold() == old.casefold():
            return f"{new}{sep}{rest}"
    return path


def readme_text() -> str:
    """README.txt at the top of the books folder."""
    rows = "\n".join(f"- {f.name}: {f.note}" for f in TOP)
    return f"""These are your books.

This folder was created by Accnomos. Everything the app knows about your business is in here, in plain files:
{rows}
- Books.xlsx: a spreadsheet of your books, rebuilt from the files in {SYSTEM}. Do not edit it; it is overwritten.
- {SYSTEM}: the ledger events and the audit log (never edited: a correction is a new entry that reverses
  the old one), plus rules you approved, contacts, jobs, staff, timesheets, vehicles and your mileage log.

You can open all of this without the app. If you disconnect Accnomos, the files stay yours.
Sample data is labelled "SAMPLE — FICTIONAL COMPANY".
"""
