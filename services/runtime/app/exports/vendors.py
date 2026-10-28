"""Import files for Xero, QuickBooks Online, Sage 50, Sage Accounting and FreeAgent, from the books.

Every file's headings, order, date and number format follow the vendor's published import template; `SOURCES` gives
the page each was checked against and when (28 October 2026). None of these files has been test-imported into the
real package (docs/HONESTY.md). Accounts and VAT codes come from app/exports/mapping.py.

Journals carry no VAT code (Xero "No VAT", Sage 50 T9, Sage Accounting "Include on VAT/Tax Return?" No): the VAT
on those entries is already on the returns Accnomos worked out, and must not reach the new package's return twice.
Invoices and bills carry their VAT rates, since the package needs them to show what each document charged.

Two ways to move the books, never both for the same period (the pack README says so):
- every entry as a journal (mode "entries"), or the balances at a cut-off date as one journal (mode "balances");
- then, for open items, the unpaid invoices and bills (mode "open") with their contacts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from accnomos_ledger import LedgerEvent
from app import reports as rp
from app.contacts import Contact, Doc, due_date, outstanding, reversed_ids
from app.exports.accounts import RETAINED, details, is_pl, klass, period_balances, split_account
from app.exports.mapping import (
    JOURNAL_TAX,
    PACKAGES,
    RATES,
    SAGE_ACCOUNTING_CONTROL,
    XERO,
    XERO_RANGES,
    Mapped,
    problems,
    resolve,
    target_code,
    target_name,
    vat_name,
)
from app.exports.receivables import _by_contact
from app.exports.registry import (
    Column,
    ExportContext,
    ExportSpec,
    Format,
    ImportFile,
    ReportDoc,
    Row,
    Section,
    doc_from,
    register,
    span_label,
    uk_day,
)
from app.journal import BANK, VAT_CONTROL

CHECKED = "checked 28 October 2026"

# --------------------------------------------------------------------------- #
# The templates: headings exactly as published, and where they were checked
# --------------------------------------------------------------------------- #

XERO_JOURNAL = [
    "*Narration",
    "*Date",
    "Description",
    "*AccountCode",
    "*TaxRate",
    "*Amount",
    "TrackingName1",
    "TrackingOption1",
    "TrackingName2",
    "TrackingOption2",
]
XERO_CONTACTS = [
    "*ContactName",
    "AccountNumber",
    "EmailAddress",
    "FirstName",
    "LastName",
    "POAttentionTo",
    "POAddressLine1",
    "POAddressLine2",
    "POAddressLine3",
    "POAddressLine4",
    "POCity",
    "PORegion",
    "POPostalCode",
    "POCountry",
    "PhoneNumber",
    "MobileNumber",
    "TaxNumber",
    "CompanyNumber",
    "DueDateBillDay",
    "DueDateBillTerm",
    "DueDateSalesDay",
    "DueDateSalesTerm",
]
XERO_INVOICES = [
    "*ContactName",
    "EmailAddress",
    "POAddressLine1",
    "POAddressLine2",
    "POAddressLine3",
    "POAddressLine4",
    "POCity",
    "PORegion",
    "POPostalCode",
    "POCountry",
    "*InvoiceNumber",
    "Reference",
    "*InvoiceDate",
    "*DueDate",
    "Total",
    "InventoryItemCode",
    "*Description",
    "*Quantity",
    "*UnitAmount",
    "Discount",
    "*AccountCode",
    "*TaxType",
    "TaxAmount",
    "TrackingName1",
    "TrackingOption1",
    "TrackingName2",
    "TrackingOption2",
    "Currency",
    "BrandingTheme",
]
XERO_BILLS = [
    "*ContactName",
    "EmailAddress",
    "POAddressLine1",
    "POAddressLine2",
    "POAddressLine3",
    "POAddressLine4",
    "POCity",
    "PORegion",
    "POPostalCode",
    "POCountry",
    "*InvoiceNumber",
    "*InvoiceDate",
    "*DueDate",
    "Total",
    "InventoryItemCode",
    "Description",
    "*Quantity",
    "*UnitAmount",
    "*AccountCode",
    "*TaxType",
    "TaxAmount",
    "TrackingName1",
    "TrackingOption1",
    "TrackingName2",
    "TrackingOption2",
    "Currency",
]
XERO_BANK = ["*Date", "*Amount", "Payee", "Description", "Reference", "Cheque Number"]
XERO_ACCOUNTS = [
    "*Code",
    "*Name",
    "*Type",
    "*Tax Code",
    "Description",
    "Dashboard",
    "Expense Claims",
    "Enable Payments",
    "Balance",
]

QBO_JOURNAL = ["Journal No.", "Journal Date", "Account Name", "Debits", "Credits", "Description", "Name"]
QBO_CONTACTS = ["Name", "Company", "Email", "Phone", "Mobile", "Street", "City", "County", "Postcode", "Country"]
QBO_INVOICES = [
    "*InvoiceNo",
    "*Customer",
    "*InvoiceDate",
    "*DueDate",
    "Terms",
    "Memo",
    "Item(Product/Service)",
    "ItemDescription",
    "ItemQuantity",
    "ItemRate",
    "*ItemAmount",
    "*ItemTaxCode",
    "ItemTaxAmount",
    "Currency",
]
QBO_BANK = ["Date", "Description", "Amount"]
QBO_ACCOUNTS = ["Account Number", "Account Name", "Type", "Detail Type"]

SAGE50_AUDIT = [
    "Type",
    "Account Reference",
    "Nominal A/C Ref",
    "Department Code",
    "Date",
    "Reference",
    "Details",
    "Net Amount",
    "Tax Code",
    "Tax Amount",
    "Exchange Rate",
    "Extra Reference",
    "User Name",
]
SAGE50_CONTACTS = [
    "Account Reference",
    "Account Name",
    "Street1",
    "Street2",
    "Town",
    "County",
    "Post Code",
    "Contact Name",
    "Telephone",
]
SAGE50_NOMINALS = ["N/C", "Name"]

SAGE_ACC_JOURNAL = [
    "Reference",
    "Date",
    "Description",
    "Nominal Code",
    "Details",
    "Include on VAT/Tax Return?",
    "Debit",
    "Credit",
    "Analysis Type 1",
    "Analysis Type 2",
    "Analysis Type 3",
    "Exchange Rate",
]
SAGE_ACC_CONTACTS = [
    "Reference",
    "Company Name",
    "Currency",
    "Credit Limit",
    "Main Address Type",
    "Main Address Line 1",
    "Main Address Line 2",
    "Main Address Town",
    "Main Address County",
    "Main Address Post Code",
    "Main Address Country",
    "Main Contact Name",
    "Main Contact Phone",
    "Main Contact Type",
    "Main Contact Mobile",
    "Main Contact Email",
    "Main Contact Fax",
    "Address 2 Type",
    "Address 2 Line 1",
    "Address 2 Line 2",
    "Address 2 Town",
    "Address 2 County",
    "Address 2 Post Code",
    "Address 2 Country",
    "VAT Number",
    "Ledger Account",
    "Payment terms",
    "Notes",
    "Bank Account Name",
    "Bank Account Sort Code",
    "Bank Account Number",
    "Bank Account IBAN",
    "Bank Account BIC",
    "Statement Run",
    "Active",
]
SAGE_ACC_ACCOUNTS = ["NOMINAL CODE", "LEDGER NAME", "CONTROL ACCOUNT", "CATEGORY", "TAX RATE"]

FREEAGENT_BANK = ["date", "amount", "description"]  # no header row in the file
FREEAGENT_CONTACTS = [
    "First Name",
    "Last Name",
    "Company",
    "E-mail Address",
    "E-mail 2 Address",
    "Business Street",
    "Business Street 2",
    "Business Street 3",
    "Business City",
    "Business State",
    "Business Postal Code",
    "Business Country",
    "Business Phone",
    "Mobile Phone",
]
FREEAGENT_INVOICES = [
    "mark_as",
    "contact",
    "dated_on",
    "reference",
    "payment_terms_in_days",
    "description",
    "quantity",
    "price",
    "sales_tax_rate",
    "sales_tax_status",
]

_XC = "https://central.xero.com/0/article/"
SOURCES: dict[str, str] = {
    "xero-manual-journals": "Xero Central's manual journal article is behind a login; headings as Xero's template, "
    "copied in docs.sequencehq.com/revenue-recognition/journal-report and corroborated by Business Importer and "
    f"PostTrans (debits positive, credits negative), {CHECKED}. Secondary sources: check before relying on it.",
    "xero-contacts": f"{_XC}Import-contacts-into-Xero ({CHECKED}): column names and rules; the full heading row is "
    "in the template Xero downloads, which this file follows for the columns it uses.",
    "xero-sales-invoices": f"{_XC}Import-customer-invoices-UK ({CHECKED}): DD/MM/YYYY, tax rate display names, one "
    "row per line. Heading row as Xero's SalesInvoiceTemplate.csv, copied in notestoself.dev (2020) and "
    "syslumelab.com (2026).",
    "xero-bills": f"Heading row as Xero's BillTemplate.csv (kedgework.com, 12 Oct 2026; gigsorted.com example), "
    f"{CHECKED}. Rules as {_XC}Import-customer-invoices-UK.",
    "xero-bank-statement": f"{_XC}Import-a-CSV-bank-statement ({CHECKED}): one signed Amount column (money out "
    "negative), DD/MM/YYYY; Xero maps the columns at import, and the template's headings vary by browser language.",
    "xero-chart-of-accounts": "Heading row as Xero's chart of accounts template (ChartOfAccounts.csv, copied at "
    f"accountantmaster.com and in Xero training material), {CHECKED}; UK codes and tax names from the default chart.",
    "qbo-journal-entries": "quickbooks.intuit.com/learn-support/en-us/help-article/import-export-data-files/"
    f"import-journal-entries-quickbooks-online/L4tQBwbs7_US_en_US ({CHECKED}): Journal No., Journal Date, Account "
    "Name, Debits, Credits, description and Name; QuickBooks maps the columns at import. Turn off account numbers "
    "before importing, as the article says.",
    "qbo-customers": "quickbooks.intuit.com/learn-support/en-global/help-article/import-export-files/import-data-"
    f"software-quickbooks-online/L6LbxyKFZ_ROW_en ({CHECKED}); QuickBooks maps the columns at import.",
    "qbo-suppliers": "quickbooks.intuit.com/learn-support/en-global/help-article/import-export-files/import-data-"
    f"software-quickbooks-online/L6LbxyKFZ_ROW_en ({CHECKED}); QuickBooks maps the columns at import.",
    "qbo-invoices": "quickbooks.intuit.com/learn-support/en-uk/help-article/import-export-files/import-multiple-"
    f"invoices/L7E9Xrd8l_GB_en_GB ({CHECKED}): invoice number, customer, dates, item amount and item tax code on "
    "every line; no credit notes; up to 100 invoices per file. Headings as Intuit's sample file.",
    "qbo-bank-transactions": "quickbooks.intuit.com/learn-support/en-us/help-article/import-transactions/manually-"
    f"upload-transactions-quickbooks-online/L0rE9OXBz_US_en_US ({CHECKED}): the 3-column format (Date, "
    "Description, Amount), dd/mm/yyyy.",
    "qbo-chart-of-accounts": "quickbooks.intuit.com/learn-support/en-uk/help-article/import-export-files/import-"
    f"chart-accounts-quickbooks-online/L9Res1eb1_GB_en_GB ({CHECKED}): Account Number, Account Name, Type, Detail "
    "Type; UK type names from the en-uk 'Choosing the right account types' article.",
    "sage50-audit-trail": "gb-kb.sage.com 'Audit trail transactions data fields you can import' (solution "
    f"250321114601443, 21 Mar 2025) and 'Import journals' (200427112601918), {CHECKED}: JD/JC lines, nominal code, "
    "DD/MM/YYYY, tax code T9 and tax 0.00 on journals.",
    "sage50-customers": "Sage 50 Customer Record template, first nine columns (A-I), as gb-kb.sage.com solution "
    f"220225121155067 and import.makingithappen.co.uk list them, {CHECKED}. Account references are 8 characters.",
    "sage50-suppliers": "Sage 50 Supplier Record template, first nine columns (A-I), as gb-kb.sage.com solution "
    f"220225121155067 lists them, {CHECKED}.",
    "sage50-nominals": f"gb-kb.sage.com 'Nominal record data fields you can import' (250321114606157), {CHECKED}.",
    "sage-accounting-journals": "gb-kb.sage.com 'Import journal entries' (222001000100916, modified 13 Feb 2025), "
    f"{CHECKED}: columns A-L, day/month/year dates, one reference per journal.",
    "sage-accounting-customers": "gb-kb.sage.com 'Format your customers and suppliers import file' (240701101019900, "
    f"modified 8 Oct 2026), {CHECKED}; column N (Main Contact Type) from help.sbc.sage.com.",
    "sage-accounting-suppliers": "gb-kb.sage.com 'Format your customers and suppliers import file' "
    f"(240701101019900), {CHECKED}.",
    "sage-accounting-chart-of-accounts": "Headings from ie-kb.sage.com 'Import your chart of accounts' "
    "(222001000100819); the UK page (gb-kb 222001000100820, modified 16 Oct 2026) names the same five columns and "
    f"control-account text (222001000100121). The UK tax-rate words are not printed there; {CHECKED}.",
    "freeagent-bank-statement": f"support.freeagent.com/hc/en-gb/articles/115001222564 ({CHECKED}): three columns, "
    "no header row, dd/mm/yyyy, money out negative, no commas or quote marks.",
    "freeagent-contacts": f"support.freeagent.com/hc/en-us/articles/115001222864 ({CHECKED}): these 14 headers, in "
    "this order.",
    "freeagent-invoices": f"support.freeagent.com/hc/en-gb/articles/36670919996050 ({CHECKED}): the simple template "
    "plus sales_tax_rate and sales_tax_status from the complete one. FreeAgent's invoice importer is for Practice "
    "Partners (accountants) only.",
}

# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #


def amt(pence: int) -> str:
    """'1234.56', '-43.25': no £, no thousands separator (every template asks for plain numbers)."""
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}{p // 100}.{p % 100:02d}"


def dmy(d: date) -> str:
    return f"{d:%d/%m/%Y}"


_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.IGNORECASE)


@dataclass
class Address:
    lines: list[str] = field(default_factory=list)
    town: str = ""
    postcode: str = ""


def parse_address(text: str | None) -> Address:
    """A free-text UK address: street lines, the town (the line before the postcode) and the postcode."""
    parts = [p.strip() for p in re.split(r"[\n,]", text or "") if p.strip()]
    out = Address()
    if parts and (m := _POSTCODE.search(parts[-1])):
        out.postcode = m.group(1).upper()
        rest = _POSTCODE.sub("", parts[-1]).strip()
        parts = parts[:-1] + ([rest] if rest else [])
    if len(parts) > 1:
        out.town = parts[-1]
        parts = parts[:-1]
    out.lines = parts
    return out


def short_ref(name: str, taken: set[str], size: int = 8) -> str:
    """'Acme Kitchens Ltd' -> 'ACMEKI01': letters and digits, unique, at most `size` long (Sage 50 takes 8)."""
    stem = re.sub(r"[^A-Z0-9]", "", name.upper())[: size - 2] or "CONTACT"
    for n in range(1, 100):
        ref = f"{stem[: size - 2]}{n:02d}"
        if ref not in taken:
            taken.add(ref)
            return ref
    raise ValueError("too many contacts with the same name")


def _ascii(value: str) -> str:
    """Import files get plain separators: ' - ' for the reports' ' · ' and '-' for '–'."""
    return value.replace(" · ", " - ").replace("–", "-").replace("—", "-").replace("…", "...")


def _section(spec_id: str, headings: list[str], rows: list[list[str]]) -> Section:
    rows = [[_ascii(v) for v in r] for r in rows]
    cols = [Column(key=f"c{i}", label=h) for i, h in enumerate(headings)]
    for r in rows:
        if len(r) != len(headings):  # a builder bug, never a user error: the file would shift every column
            raise RuntimeError(f"{spec_id}: a row has {len(r)} cells for {len(headings)} headings")
    return Section(
        title=spec_id,
        columns=cols,
        rows=[Row(cells={f"c{i}": v for i, v in enumerate(r)}) for r in rows],
    )


# --------------------------------------------------------------------------- #
# What goes in the files
# --------------------------------------------------------------------------- #


@dataclass
class JLine:
    account: str
    debit: int
    credit: int
    memo: str = ""


@dataclass
class Journal:
    ref: str
    day: date
    narration: str
    counterparty: str
    lines: list[JLine]


def journals(events: Sequence[LedgerEvent], start: date, end: date, mode: str | None) -> list[Journal]:
    if mode == "balances":
        bal = period_balances(events, end + timedelta(days=1), end)
        lines = [
            JLine(a, v if v > 0 else 0, -v if v < 0 else 0, "Balance at " + uk_day(end))
            for a, v in sorted(bal.items(), key=lambda kv: (rp.account_code(kv[0]) or 99_999, kv[0]))
        ]
        return (
            [Journal(f"ACC-OB-{end:%Y%m%d}", end, f"Opening balances from Accnomos at {uk_day(end)}", "", lines)]
            if lines
            else []
        )
    out = []
    for e in sorted((e for e in events if start <= e.date <= end), key=lambda e: (e.date, e.approved_at, e.id)):
        out.append(
            Journal(
                ref=f"ACC-{e.id[:8]}",
                day=e.date,
                narration=f"{details(e)} (Accnomos {e.id[:8]})",
                counterparty=e.counterparty or "",
                lines=[JLine(ln.account, ln.debit, ln.credit, ln.memo or "") for ln in e.lines],
            )
        )
    return out


@dataclass
class DocLine:
    account: str
    net: int
    vat: int
    code: str


@dataclass
class Document:
    contact: Contact
    number: str
    day: date
    due: date
    lines: list[DocLine]
    owed: int

    @property
    def gross(self) -> int:
        return sum(ln.net + ln.vat for ln in self.lines)


def _lines(e: LedgerEvent, side: str) -> list[DocLine]:
    """The sales (or expense) legs of a document, with its VAT shared out by rate (the remainder of rounding on the
    biggest line), so the lines add up to the document exactly."""
    legs: list[DocLine] = []
    for ln in e.lines:
        k = rp.section_of(ln.account)
        if side == "sale" and k == "sales":
            legs.append(DocLine(ln.account, ln.credit - ln.debit, 0, ln.vat_code.value if ln.vat_code else "O"))
        elif side == "purchase" and k in ("cost_of_sales", "overheads"):
            legs.append(DocLine(ln.account, ln.debit - ln.credit, 0, ln.vat_code.value if ln.vat_code else "N"))
    vat = sum(
        (ln.credit - ln.debit) if side == "sale" else (ln.debit - ln.credit)
        for ln in e.lines
        if ln.account == VAT_CONTROL
    )
    if legs and vat:
        for leg in legs:
            leg.vat = round(leg.net * RATES.get(leg.code, 0) / 100)
        biggest = max(legs, key=lambda leg: (leg.vat, leg.net))
        biggest.vat += vat - sum(leg.vat for leg in legs)
    return legs


async def documents_for(ctx: ExportContext, side: str) -> list[Document]:
    """Invoices (side 'sale') or bills on account ('purchase'): raised in the period (mode 'period') or still unpaid
    now (mode 'open'). Credit notes, undone documents and purchases paid at once are left out (warned)."""
    ledger = await ctx.ledger()
    undone = reversed_ids(ledger.events)
    out: list[Document] = []
    for c, docs in _by_contact(await ctx.contacts(), ledger):
        for d in docs:
            if d.side != side or d.kind != "invoice" or d.undo or d.event.id in undone:
                continue
            if side == "purchase" and not d.on_account:
                continue
            owed = outstanding(d, ledger)
            if (ctx.mode == "open" and owed <= 0) or (ctx.mode != "open" and not ctx.start <= d.event.date <= ctx.end):
                continue
            out.append(Document(c, _number(d), d.event.date, due_date(d, c), _lines(d.event, side), owed))
    return sorted(out, key=lambda doc: (doc.day, doc.number))


def _number(d: Doc) -> str:
    return (d.reference or f"ACC-{d.event.id[:8]}")[:50]


def bank_entries(events: Sequence[LedgerEvent], start: date, end: date) -> list[tuple[LedgerEvent, int]]:
    out = []
    for e in sorted((e for e in events if start <= e.date <= end), key=lambda e: (e.date, e.approved_at, e.id)):
        v = sum(ln.debit - ln.credit for ln in e.lines if ln.account == BANK)
        if v:
            out.append((e, v))
    return out


def chart(events: Sequence[LedgerEvent]) -> list[str]:
    accounts = {ln.account for e in events for ln in e.lines}
    if any(is_pl(a) for a in accounts):
        accounts.add(RETAINED)
    return sorted(accounts, key=lambda a: (rp.account_code(a) or 99_999, a))


# --------------------------------------------------------------------------- #
# The builders
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Template:
    id: str
    package: str  # mapping key
    title: str
    template: str
    headings: list[str]
    instructions: str
    header: bool = True
    bom: bool = False
    modes: tuple[tuple[str, str], ...] = ()
    formats: tuple[Format, ...] = ("csv",)


JOURNAL_MODES = (("entries", "Every entry in the period"), ("balances", "Balances at the period end, as one journal"))
DOC_MODES = (("period", "Raised in the period"), ("open", "Still unpaid now"))


async def _doc(
    ctx: ExportContext, t: Template, rows: list[list[str]], warnings: list[str], period: str | None = None
) -> ReportDoc:
    events = await ctx.events()
    imp = ImportFile(
        package=PACKAGES[t.package],
        template=t.template,
        header=t.header,
        bom=t.bom,
        source=SOURCES[t.id],
        instructions=t.instructions,
    )
    section = _section(t.title, t.headings, rows)
    section.note = f"{len(rows)} rows. {t.instructions}"
    return doc_from(
        t.id,
        t.title,
        period or span_label(ctx.start, ctx.end),
        [section],
        warnings=warnings,
        sample=rp.is_sample(events),
        import_file=imp,
        basis=[f"{PACKAGES[t.package]} import file: {t.template}. Not test-imported into {PACKAGES[t.package]}."],
    )


async def _mapper(ctx: ExportContext, package: str) -> tuple[dict[str, Mapped], list[str]]:
    mappings = await ctx.mappings()
    accounts = chart(await ctx.events())
    mapped = {a: resolve(package, a, mappings) for a in accounts}
    return mapped, problems(mapped.values())


def _journal_period(ctx: ExportContext) -> str:
    return f"balances at {uk_day(ctx.end)}" if ctx.mode == "balances" else span_label(ctx.start, ctx.end)


async def xero_journals(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "xero")
    rows = []
    for j in journals(await ctx.events(), ctx.start, ctx.end, ctx.mode):
        for ln in j.lines:
            m = mapped.get(ln.account) or resolve("xero", ln.account, await ctx.mappings())
            rows.append(
                [
                    j.narration,
                    dmy(j.day),
                    ln.memo or ln.account,
                    target_code(m),
                    JOURNAL_TAX["xero"],
                    amt(ln.debit - ln.credit),
                    "",
                    "",
                    "",
                    "",
                ]
            )
    return await _doc(ctx, t, rows, warn, _journal_period(ctx))


def _xero_address(c: Contact) -> list[str]:
    a = parse_address(c.address)
    lines = (a.lines + ["", "", "", ""])[:4]
    return [*lines, a.town, "", a.postcode, "United Kingdom" if a.postcode else ""]


async def xero_contacts(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = []
    for c in sorted(await ctx.contacts(), key=lambda c: c.name.lower()):
        terms = str(c.terms_days) if c.terms_days is not None else ""
        sales = c.kind in ("customer", "both")
        bills = c.kind in ("supplier", "both")
        rows.append(
            [
                c.name,
                "",
                c.email or "",
                "",
                "",
                "",
                *_xero_address(c),
                c.phone or "",
                "",
                c.vrn or "",
                c.company_number or "",
                terms if bills else "",
                "Days After" if bills and terms else "",
                terms if sales else "",
                "Days After" if sales and terms else "",
            ]
        )
    return await _doc(ctx, t, rows, [])


async def xero_invoices(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "xero")
    rows = []
    for d in await documents_for(ctx, "sale"):
        for ln in d.lines:
            m = mapped.get(ln.account) or resolve("xero", ln.account, await ctx.mappings())
            rows.append(
                [
                    d.contact.name,
                    d.contact.email or "",
                    *_xero_address(d.contact)[:8],
                    d.number,
                    "",
                    dmy(d.day),
                    dmy(d.due),
                    "",
                    "",
                    split_account(ln.account)[1],
                    "1",
                    amt(ln.net),
                    "",
                    target_code(m),
                    vat_name("xero", "sales", ln.code),
                    amt(ln.vat),
                    "",
                    "",
                    "",
                    "",
                    "GBP",
                    "",
                ]
            )
    warn.append("Amounts are tax exclusive: choose 'Tax exclusive' when Xero asks. Credit notes are not in this file.")
    return await _doc(ctx, t, rows, warn)


async def xero_bills(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "xero")
    rows = []
    for d in await documents_for(ctx, "purchase"):
        for ln in d.lines:
            m = mapped.get(ln.account) or resolve("xero", ln.account, await ctx.mappings())
            rows.append(
                [
                    d.contact.name,
                    d.contact.email or "",
                    *_xero_address(d.contact)[:8],
                    d.number,
                    dmy(d.day),
                    dmy(d.due),
                    "",
                    "",
                    split_account(ln.account)[1],
                    "1",
                    amt(ln.net),
                    target_code(m),
                    vat_name("xero", "purchases", ln.code),
                    amt(ln.vat),
                    "",
                    "",
                    "",
                    "",
                    "GBP",
                ]
            )
    warn.append(
        "Bills on account only: purchases paid at once are in the bank statement file. Amounts are tax exclusive."
    )
    return await _doc(ctx, t, rows, warn)


async def xero_bank(ctx: ExportContext, t: Template) -> ReportDoc:
    refs = (await ctx.ledger()).refs
    rows = [
        [dmy(e.date), amt(v), e.counterparty or "", details(e), refs.get(e.id, e.id[:8]), ""]
        for e, v in bank_entries(await ctx.events(), ctx.start, ctx.end)
    ]
    return await _doc(ctx, t, rows, [f"Lines are the books' {BANK} entries, not the bank's own statement."])


XERO_TYPES = {
    "fixed_assets": "Fixed Asset",
    "current_assets": "Current Asset",
    "current_liabilities": "Current Liability",
    "capital": "Equity",
    "sales": "Revenue",
    "cost_of_sales": "Direct Costs",
    "overheads": "Overhead",
}
#: Codes in Xero's UK default chart (every default above is one) and the bank account code: Xero has these
#: already, so the chart file lists only the accounts it lacks.
XERO_DEFAULT_CODES = {d[0] for d in XERO.values() if d[0]} | {d[0] for _, d in XERO_RANGES} | {"090"}


async def xero_accounts(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "xero")
    rows, seen = [], set()
    for account, m in mapped.items():
        code = target_code(m)
        k = klass(account) if account != RETAINED else "capital"
        if code in XERO_DEFAULT_CODES or code in seen or k == "unclassified":
            continue
        seen.add(code)
        tax = (
            "20% (VAT on Income)"
            if k == "sales"
            else "20% (VAT on Expenses)"
            if k in ("cost_of_sales", "overheads")
            else "No VAT"
        )
        rows.append([code, target_name(m), XERO_TYPES[k], tax, f"From Accnomos {account}", "No", "No", "No", ""])
    warn.append("Only accounts Xero's default UK chart lacks are listed; the rest map onto Xero's own accounts.")
    return await _doc(ctx, t, rows, warn)


async def qbo_journals(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "qbo")
    rows = []
    for j in journals(await ctx.events(), ctx.start, ctx.end, ctx.mode):
        for ln in j.lines:
            m = mapped.get(ln.account) or resolve("qbo", ln.account, await ctx.mappings())
            name = j.counterparty if rp.account_code(ln.account) in (1100, 2100) else ""
            rows.append(
                [
                    j.ref,
                    dmy(j.day),
                    target_name(m),
                    amt(ln.debit) if ln.debit else "",
                    amt(ln.credit) if ln.credit else "",
                    j.narration,
                    name,
                ]
            )
    return await _doc(ctx, t, rows, warn, _journal_period(ctx))


def _qbo_contact(c: Contact) -> list[str]:
    a = parse_address(c.address)
    return [
        c.name,
        c.name,
        c.email or "",
        c.phone or "",
        "",
        ", ".join(a.lines),
        a.town,
        "",
        a.postcode,
        "United Kingdom" if a.postcode else "",
    ]


async def qbo_customers(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = [
        _qbo_contact(c)
        for c in sorted(await ctx.contacts(), key=lambda c: c.name.lower())
        if c.kind in ("customer", "both")
    ]
    return await _doc(ctx, t, rows, [])


async def qbo_suppliers(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = [
        _qbo_contact(c)
        for c in sorted(await ctx.contacts(), key=lambda c: c.name.lower())
        if c.kind in ("supplier", "both")
    ]
    return await _doc(ctx, t, rows, [])


async def qbo_invoices(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = []
    docs = await documents_for(ctx, "sale")
    for d in docs:
        for ln in d.lines:
            rows.append(
                [
                    d.number,
                    d.contact.name,
                    dmy(d.day),
                    dmy(d.due),
                    "",
                    "",
                    "Sales",
                    split_account(ln.account)[1],
                    "1",
                    amt(ln.net),
                    amt(ln.net),
                    vat_name("qbo", "sales", ln.code),
                    amt(ln.vat),
                    "GBP",
                ]
            )
    warn = [
        "Choose the date format D/M/YYYY and 'Exclusive' VAT when QuickBooks asks. Credit notes are not in this file."
    ]
    if len(docs) > 100:
        warn.append(f"{len(docs)} invoices: QuickBooks imports at most 100 at a time, so split the file.")
    return await _doc(ctx, t, rows, warn)


async def qbo_bank(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = [[dmy(e.date), details(e), amt(v)] for e, v in bank_entries(await ctx.events(), ctx.start, ctx.end)]
    warn = [f"Lines are the books' {BANK} entries, not the bank's own statement."]
    if len(rows) > 1000:
        warn.append("More than 1,000 lines: QuickBooks takes 1,000 per upload, so split the file.")
    return await _doc(ctx, t, rows, warn)


QBO_TYPES = {
    "fixed_assets": ("Fixed Assets", "Other fixed assets"),
    "current_assets": ("Current Assets", "Other current assets"),
    "current_liabilities": ("Current Liabilities", "Current Liabilities"),
    "capital": ("Equity", "Owner's Equity"),
    "sales": ("Income", "Sales of Product Income"),
    "cost_of_sales": ("Cost of Sales", "Supplies and materials - COS"),
    "overheads": ("Expenses", "Office/General Administrative Expenses"),
}
QBO_SPECIAL = {
    1200: ("Cash at bank and in hand", "Current"),
    1210: ("Cash at bank and in hand", "Cash on hand"),
    2200: ("Current Liabilities", "Current Tax Liability"),
    2210: ("Current Liabilities", "Tax and National Insurance"),
    2300: ("Current Liabilities", "Short term borrowing from related parties"),
}


async def qbo_accounts(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "qbo")
    rows = []
    for account, m in mapped.items():
        code = rp.account_code(account)
        k = klass(account) if account != RETAINED else "capital"
        if code in (1100, 2100) or k == "unclassified":
            continue  # QuickBooks creates Debtors and Creditors itself
        typ, detail = QBO_SPECIAL.get(code or 0, QBO_TYPES[k])
        rows.append([split_account(account)[0], target_name(m), typ, detail])
    warn.append("Debtors and Creditors are left out: QuickBooks creates them. Check each detail type before importing.")
    return await _doc(ctx, t, rows, warn)


async def sage50_audit(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "sage50")
    rows = []
    for j in journals(await ctx.events(), ctx.start, ctx.end, ctx.mode):
        for ln in j.lines:
            m = mapped.get(ln.account) or resolve("sage50", ln.account, await ctx.mappings())
            kind, value = ("JD", ln.debit) if ln.debit else ("JC", ln.credit)
            rows.append(
                [
                    kind,
                    "",
                    target_code(m),
                    "0",
                    dmy(j.day),
                    j.ref[:30],
                    j.narration[:60],
                    amt(value),
                    JOURNAL_TAX["sage50"],
                    "0.00",
                    "1",
                    "",
                    "",
                ]
            )
    return await _doc(ctx, t, rows, warn, _journal_period(ctx))


def _sage50_contacts(contacts: list[Contact], kinds: tuple[str, ...]) -> list[list[str]]:
    taken: set[str] = set()
    rows = []
    for c in sorted(contacts, key=lambda c: c.name.lower()):
        if c.kind not in kinds:
            continue
        a = parse_address(c.address)
        lines = (a.lines + ["", ""])[:2]
        rows.append([short_ref(c.name, taken), c.name[:60], *lines, a.town, "", a.postcode, "", c.phone or ""])
    return rows


async def sage50_customers(ctx: ExportContext, t: Template) -> ReportDoc:
    return await _doc(ctx, t, _sage50_contacts(await ctx.contacts(), ("customer", "both")), [])


async def sage50_suppliers(ctx: ExportContext, t: Template) -> ReportDoc:
    return await _doc(ctx, t, _sage50_contacts(await ctx.contacts(), ("supplier", "both")), [])


async def sage50_nominals(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "sage50")
    rows, seen = [], set()
    for m in mapped.values():
        code = target_code(m)
        if code not in seen and code.isdigit():
            seen.add(code)
            rows.append([code, target_name(m)[:60]])
    warn.append(
        "Import bank accounts as nominal records, then convert them to bank accounts in Sage (Sage's own advice)."
    )
    return await _doc(ctx, t, rows, warn)


async def sage_acc_journals(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "sage-accounting")
    rows = []
    for j in journals(await ctx.events(), ctx.start, ctx.end, ctx.mode):
        for ln in j.lines:
            m = mapped.get(ln.account) or resolve("sage-accounting", ln.account, await ctx.mappings())
            rows.append(
                [
                    j.ref,
                    dmy(j.day),
                    j.narration[:200],
                    target_code(m),
                    (ln.memo or ln.account)[:200],
                    JOURNAL_TAX["sage-accounting"],
                    amt(ln.debit) if ln.debit else "0.00",
                    amt(ln.credit) if ln.credit else "0.00",
                    "",
                    "",
                    "",
                    "",
                ]
            )
    return await _doc(ctx, t, rows, warn, _journal_period(ctx))


def _sage_acc_contacts(contacts: list[Contact], kinds: tuple[str, ...]) -> list[list[str]]:
    taken: set[str] = set()
    rows = []
    for c in sorted(contacts, key=lambda c: c.name.lower()):
        if c.kind not in kinds:
            continue
        a = parse_address(c.address)
        lines = (a.lines + ["", ""])[:2]
        terms = str(c.terms_days) if c.terms_days else ""
        row = [
            short_ref(c.name, taken),
            c.name[:100],
            "",
            "",
            "",
            *lines,
            a.town,
            "",
            a.postcode,
            "GB" if a.postcode else "",
            "",
            c.phone or "",
            "",
            "",
            c.email or "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            (c.vrn or "").replace(" ", "")[:11],
            "",
            terms,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
        rows.append(row)
    return rows


async def sage_acc_customers(ctx: ExportContext, t: Template) -> ReportDoc:
    return await _doc(ctx, t, _sage_acc_contacts(await ctx.contacts(), ("customer", "both")), [])


async def sage_acc_suppliers(ctx: ExportContext, t: Template) -> ReportDoc:
    return await _doc(ctx, t, _sage_acc_contacts(await ctx.contacts(), ("supplier", "both")), [])


SAGE_ACC_CATEGORY = {
    "fixed_assets": "FIXED_ASSETS",
    "current_assets": "CURRENT_ASSETS",
    "current_liabilities": "CURRENT_LIABILITY",
    "capital": "EQUITY",
    "sales": "SALES",
    "cost_of_sales": "DIRECT_EXPENSES",
    "overheads": "OVERHEADS",
}


async def sage_acc_accounts(ctx: ExportContext, t: Template) -> ReportDoc:
    mapped, warn = await _mapper(ctx, "sage-accounting")
    rows, seen = [], set()
    for account, m in mapped.items():
        code = target_code(m)
        k = klass(account) if account != RETAINED else "capital"
        if code in seen or k == "unclassified" or not code.isdigit():
            continue
        seen.add(code)
        c = rp.account_code(account)
        category = "BANK" if c in (1200, 1210) else SAGE_ACC_CATEGORY[k]
        control = SAGE_ACCOUNTING_CONTROL.get(code, "BANK_CURRENT" if c == 1200 else "BANK_CASH" if c == 1210 else "")
        tax = "Standard" if k in ("sales", "cost_of_sales", "overheads") else "No VAT"
        rows.append([code, target_name(m), control, category, tax])
    warn.append("Sage Accounting imports a chart only into a new business with no transactions, and only once.")
    return await _doc(ctx, t, rows, warn)


async def freeagent_bank(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = [[dmy(e.date), amt(v), details(e)] for e, v in bank_entries(await ctx.events(), ctx.start, ctx.end)]
    return await _doc(ctx, t, rows, [f"Lines are the books' {BANK} entries, not the bank's own statement."])


async def freeagent_contacts(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = []
    for c in sorted(await ctx.contacts(), key=lambda c: c.name.lower()):
        a = parse_address(c.address)
        lines = (a.lines + ["", "", ""])[:3]
        rows.append(
            [
                "",
                "",
                c.name,
                c.email or "",
                "",
                *lines,
                a.town,
                "",
                a.postcode,
                "United Kingdom" if a.postcode else "",
                c.phone or "",
                "",
            ]
        )
    return await _doc(ctx, t, rows, [])


async def freeagent_invoices(ctx: ExportContext, t: Template) -> ReportDoc:
    rows = []
    warn = ["Prices are net; FreeAgent adds the VAT from sales_tax_rate. Credit notes are not in this file."]
    for d in await documents_for(ctx, "sale"):
        terms = str(max(0, (d.due - d.day).days))
        for i, ln in enumerate(d.lines):
            head = ["Sent", d.contact.name, dmy(d.day), d.number, terms] if i == 0 else ["", "", "", "", ""]
            status = "Exempt" if ln.code == "E" else ""
            if ln.code == "O":
                warn.append(
                    f"{d.number}: outside the scope of VAT; set {d.contact.name} to never charge VAT "
                    "in FreeAgent first."
                )
            rows.append(
                [*head, split_account(ln.account)[1], "1", amt(ln.net), vat_name("freeagent", "sales", ln.code), status]
            )
    return await _doc(ctx, t, rows, warn)


TEMPLATES: tuple[tuple[Template, object], ...] = (
    (
        Template(
            "xero-manual-journals",
            "xero",
            "Xero: manual journals",
            "Manual journal import (CSV)",
            XERO_JOURNAL,
            "Accounting › Manual journals › Import.",
            modes=JOURNAL_MODES,
        ),
        xero_journals,
    ),
    (
        Template(
            "xero-contacts",
            "xero",
            "Xero: contacts",
            "ContactTemplate.csv",
            XERO_CONTACTS,
            "Contacts › All contacts › Import.",
        ),
        xero_contacts,
    ),
    (
        Template(
            "xero-sales-invoices",
            "xero",
            "Xero: sales invoices",
            "SalesInvoiceTemplate.csv",
            XERO_INVOICES,
            "Sales › Invoices › Import; they arrive as drafts to approve.",
            modes=DOC_MODES,
        ),
        xero_invoices,
    ),
    (
        Template(
            "xero-bills",
            "xero",
            "Xero: bills",
            "BillTemplate.csv",
            XERO_BILLS,
            "Purchases › Bills › Import.",
            modes=DOC_MODES,
        ),
        xero_bills,
    ),
    (
        Template(
            "xero-bank-statement",
            "xero",
            "Xero: bank statement",
            "Bank statement CSV",
            XERO_BANK,
            "Accounting › Bank accounts › Import a Statement.",
        ),
        xero_bank,
    ),
    (
        Template(
            "xero-chart-of-accounts",
            "xero",
            "Xero: chart of accounts",
            "ChartOfAccounts.csv",
            XERO_ACCOUNTS,
            "Accounting › Chart of accounts › Import.",
        ),
        xero_accounts,
    ),
    (
        Template(
            "qbo-journal-entries",
            "qbo",
            "QuickBooks: journal entries",
            "Journal entries import",
            QBO_JOURNAL,
            "Settings › Import data › Journal entries.",
            modes=JOURNAL_MODES,
            formats=("csv", "xlsx"),
        ),
        qbo_journals,
    ),
    (
        Template(
            "qbo-customers",
            "qbo",
            "QuickBooks: customers",
            "Customers import",
            QBO_CONTACTS,
            "Settings › Import data › Customers.",
            formats=("csv", "xlsx"),
        ),
        qbo_customers,
    ),
    (
        Template(
            "qbo-suppliers",
            "qbo",
            "QuickBooks: suppliers",
            "Suppliers import",
            QBO_CONTACTS,
            "Settings › Import data › Suppliers.",
            formats=("csv", "xlsx"),
        ),
        qbo_suppliers,
    ),
    (
        Template(
            "qbo-invoices",
            "qbo",
            "QuickBooks: invoices",
            "Invoices import",
            QBO_INVOICES,
            "Settings › Import data › Invoices.",
            modes=DOC_MODES,
        ),
        qbo_invoices,
    ),
    (
        Template(
            "qbo-bank-transactions",
            "qbo",
            "QuickBooks: bank transactions",
            "Bank transactions (3-column CSV)",
            QBO_BANK,
            "Bank transactions › Link account › Upload from file.",
        ),
        qbo_bank,
    ),
    (
        Template(
            "qbo-chart-of-accounts",
            "qbo",
            "QuickBooks: chart of accounts",
            "Chart of accounts import",
            QBO_ACCOUNTS,
            "Settings › Import data › Chart of accounts.",
            formats=("csv", "xlsx"),
        ),
        qbo_accounts,
    ),
    (
        Template(
            "sage50-audit-trail",
            "sage50",
            "Sage 50: journals (audit trail transactions)",
            "Audit Trail Transaction template",
            SAGE50_AUDIT,
            "File › Import › Audit Trail Transactions (back up first).",
            modes=JOURNAL_MODES,
        ),
        sage50_audit,
    ),
    (
        Template(
            "sage50-customers",
            "sage50",
            "Sage 50: customers",
            "Customer Record template",
            SAGE50_CONTACTS,
            "File › Import › Customer Records.",
        ),
        sage50_customers,
    ),
    (
        Template(
            "sage50-suppliers",
            "sage50",
            "Sage 50: suppliers",
            "Supplier Record template",
            SAGE50_CONTACTS,
            "File › Import › Supplier Records.",
        ),
        sage50_suppliers,
    ),
    (
        Template(
            "sage50-nominals",
            "sage50",
            "Sage 50: nominal accounts",
            "Nominal Record template",
            SAGE50_NOMINALS,
            "File › Import › Nominal Records.",
        ),
        sage50_nominals,
    ),
    (
        Template(
            "sage-accounting-journals",
            "sage-accounting",
            "Sage Accounting: journals",
            "Journal import template",
            SAGE_ACC_JOURNAL,
            "Adjustments › Journals › New Journal › Import Journals.",
            modes=JOURNAL_MODES,
        ),
        sage_acc_journals,
    ),
    (
        Template(
            "sage-accounting-customers",
            "sage-accounting",
            "Sage Accounting: customers",
            "Contacts import template",
            SAGE_ACC_CONTACTS,
            "Contacts › New Customer › Import Customers.",
        ),
        sage_acc_customers,
    ),
    (
        Template(
            "sage-accounting-suppliers",
            "sage-accounting",
            "Sage Accounting: suppliers",
            "Contacts import template",
            SAGE_ACC_CONTACTS,
            "Contacts › New Supplier › Import Suppliers.",
        ),
        sage_acc_suppliers,
    ),
    (
        Template(
            "sage-accounting-chart-of-accounts",
            "sage-accounting",
            "Sage Accounting: chart of accounts",
            "Chart of accounts template",
            SAGE_ACC_ACCOUNTS,
            "Settings › Business Settings › Chart of accounts › Import accounts.",
        ),
        sage_acc_accounts,
    ),
    (
        Template(
            "freeagent-bank-statement",
            "freeagent",
            "FreeAgent: bank statement",
            "Bank statement CSV",
            FREEAGENT_BANK,
            "Banking › your account › Upload Statement.",
            header=False,
        ),
        freeagent_bank,
    ),
    (
        Template(
            "freeagent-contacts",
            "freeagent",
            "FreeAgent: contacts",
            "Contacts CSV template",
            FREEAGENT_CONTACTS,
            "Contacts › Import contacts.",
        ),
        freeagent_contacts,
    ),
    (
        Template(
            "freeagent-invoices",
            "freeagent",
            "FreeAgent: invoices",
            "Invoices simple template",
            FREEAGENT_INVOICES,
            "Work › Invoicing › Import invoices (Practice Partners only).",
            modes=DOC_MODES,
        ),
        freeagent_invoices,
    ),
)


def _spec(t: Template, fn: object) -> ExportSpec:
    async def build(ctx: ExportContext) -> ReportDoc:
        return await fn(ctx, t)  # type: ignore[operator]

    params = ("period", "mode") if t.modes else ("period",)
    return ExportSpec(
        id=t.id,
        group="export",
        title=t.title,
        description=f"{t.template}. {t.instructions}",
        build=build,
        formats=t.formats,
        params=params,
        modes=t.modes,
        package=t.package,  # type: ignore[arg-type]
    )


for _t, _fn in TEMPLATES:
    register(_spec(_t, _fn))
