"""Switching from Xero, QuickBooks Online, Sage, FreeAgent or a spreadsheet: opening balances, contacts, open items.

The wizard (web /import) works on a **draft** kept in the user's books, because the runtime keeps nothing between
requests:

1. Upload the old system's exports (app/import_formats.py): the trial balance at the conversion date (required), and
   optionally its chart of accounts, contacts, open (unpaid) invoices and bills, and bank balances. Each file is
   saved as it came to `_System/Import/sources/<sha256>-<name>` and its rows into `_System/Import/draft.json`.
2. Map accounts. Each source account gets a suggested Accnomos account (`suggest`): the same code for Sage 50 (its
   default nominal codes are the Accnomos layout), else by name ("Accounts Receivable" -> 1100 Debtors), else a new
   account in the right range for its type ("Motor vehicles", FIXED -> 0010 Motor vehicles). An account whose type
   cannot be told is **unmapped** and blocks posting until the user picks one. Every suggestion can be changed.
3. Check. `view()` works out the opening journal and every check (below) on each request.
4. Post, after the user approves: one balanced ledger event, kind "adjustment", dated the day before the conversion
   date (the trial balance is "as at" the close of that day), one line per Accnomos account, no VAT code on any line
   (so no VAT return ever counts it: accnomos_ledger.vat only counts sales, purchases and reversals with a VAT code,
   and opening balances are not supplies). Its `evidence` is the sha256 of every source file. The record of the
   import, with the open items, goes to `_System/Import/opening.json`, contacts are added to the contact book, and a
   reconciliation CSV is saved in `07 Reports`.

**Open items.** The trial balance carries debtors and creditors as one balance each. The unpaid invoices and bills
behind them are kept in `opening.json`, not posted: `app.contacts.documents` shows each one as a document on account
(a sale owed by a customer, a bill owed to a supplier), so aged debtors and creditors, contact statements and
*Record payment* work from the first day. A payment recorded against one posts Dr 1200 Bank / Cr 1100 Debtors as for
any invoice, which takes it out of the opening debtors balance. They cannot be matched straight to a bank line on
the Bank page (matching needs a posted entry): record the payment instead.

**Profit and loss accounts.** A trial balance part way through a year holds this year's income and costs so far.
`pl_treatment` "keep" posts them as they are, so this year's P&L is complete (as one entry on the balance date);
"retained" folds their net into 3200 Retained profit, for a conversion at a year end.

**Checks** (`Check.severity`): "error" blocks posting; "warning" needs `accept_warnings`:
- trial balance uploaded and balanced (debits = credits to the penny), in error otherwise;
- every account mapped (error), each new account listed (info);
- a conversion date, nothing already in the books on or before the balance date, no import already posted (error);
- open invoices total = the debtors balance, open bills total = the creditors balance (warning when they differ,
  or when there is a balance and no list); bank balances = the bank accounts' balances (warning);
- open items dated after the balance date (warning).

**Reconciliation** (`reconcile`): after posting, the Accnomos trial balance at the balance date is worked out from
the ledger again (app.projection.trial_balance over every event on or before that date) and compared, account by
account, with what the source trial balance says each Accnomos account should hold, plus the totals, the debtors
and creditors (from the aged balances) and the bank balances. `proved` is true only when every row agrees.

**Undo** posts the reversal of the opening entry and marks the import undone, which takes the open items away;
it is refused while a payment, credit note or credit use points at one of them. Contacts it added stay.

Nothing here is a tax rule: opening balances are bookkeeping. The VAT treatment above (not on any return) follows
from VAT Notice 700/12 section 3, which puts on the return the supplies made and received in the period
(https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012, checked 28 Oct 2026 by web
search; the page could not be opened from the build machine).
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from accnomos_ledger import LedgerEvent, Line
from app import import_formats as fmt
from app.books import SYSTEM, Books, now
from app.journal import (
    BANK,
    CASH,
    CATEGORY_ACCOUNTS,
    CREDITORS,
    DEBTORS,
    OWNER_LOAN,
    SALES,
    SUNDRY,
    VAT_CONTROL,
)
from app.paths import REPORTS
from app.validation import LENIENT

IMPORT_DIR = f"{SYSTEM}/Import"
DRAFT = f"{IMPORT_DIR}/draft.json"
OPENING = f"{IMPORT_DIR}/opening.json"
SOURCES = f"{IMPORT_DIR}/sources"
MAX_FILES = 12

CAPITAL = "3000 Capital"
RETAINED = "3200 Retained profit"
DRAWINGS = "3300 Drawings"
OPENING_ITEMS = "3900 Opening balances (open items)"  # the other leg of an open item; never posted
WAGES = "7000 Gross wages"
EMPLOYER_NI = "7010 Employer's NI"
PAYROLL_LIABILITIES = "2210 Payroll liabilities"

Klass = Literal[
    "fixed_assets", "current_assets", "bank", "liabilities", "capital", "sales", "cost_of_sales", "overheads"
]
How = Literal["code", "name", "type", "user"]
Severity = Literal["error", "warning", "info"]
PlTreatment = Literal["keep", "retained"]

#: First code for a new account of each class, and the top of its range.
RANGES: dict[Klass, tuple[int, int]] = {
    "fixed_assets": (10, 999),
    "current_assets": (1300, 1999),
    "bank": (1220, 1299),
    "liabilities": (2400, 2999),
    "capital": (3400, 3899),
    "sales": (4100, 4999),
    "cost_of_sales": (5200, 5999),
    "overheads": (8000, 8999),
}
PL_CLASSES: set[str] = {"sales", "cost_of_sales", "overheads"}

#: The accounts Accnomos posts to itself (app/journal.py, app/payroll.py) plus the capital accounts this module adds.
CHART: tuple[str, ...] = tuple(
    sorted(
        {
            DEBTORS,
            BANK,
            CASH,
            CREDITORS,
            VAT_CONTROL,
            PAYROLL_LIABILITIES,
            OWNER_LOAN,
            CAPITAL,
            RETAINED,
            DRAWINGS,
            SALES,
            WAGES,
            EMPLOYER_NI,
            SUNDRY,
            *CATEGORY_ACCOUNTS.values(),
        }
    )
)
_ACCOUNT_RE = re.compile(r"^(\d{4}) \S.{0,79}$")


def klass_of_code(code: int) -> Klass:
    """Where an Accnomos four-digit code sits (app/reports.py places 4000-8999 on the P&L)."""
    if code < 1000:
        return "fixed_assets"
    if 1200 <= code <= 1299:
        return "bank"
    if code < 2000:
        return "current_assets"
    if code < 3000:
        return "liabilities"
    if code < 4000:
        return "capital"
    if code < 5000:
        return "sales"
    if code < 6000:
        return "cost_of_sales"
    return "overheads"


def is_bank_account(account: str) -> bool:
    """A bank account (1200-1299), not 1210 Cash: what a bank balances file is compared with."""
    return account_klass(account) == "bank" and account != CASH


def account_klass(account: str) -> Klass | None:
    m = _ACCOUNT_RE.match(account)
    return klass_of_code(int(m.group(1))) if m else None


# --------------------------------------------------------------------------- #
# Suggesting an Accnomos account for each source account
# --------------------------------------------------------------------------- #

#: Source account types (Xero, QuickBooks Online, Sage, FreeAgent wording, lower case) -> class.
TYPE_CLASSES: dict[str, Klass] = {
    # Xero
    "bank": "bank",
    "current": "current_assets",
    "currasset": "current_assets",
    "fixed": "fixed_assets",
    "inventory": "current_assets",
    "noncurrent": "fixed_assets",
    "prepayment": "current_assets",
    "currliab": "liabilities",
    "liability": "liabilities",
    "termliab": "liabilities",
    "paygliability": "liabilities",
    "superannuationliability": "liabilities",
    "equity": "capital",
    "revenue": "sales",
    "sales": "sales",
    "otherincome": "sales",
    "directcosts": "cost_of_sales",
    "expense": "overheads",
    "overheads": "overheads",
    "depreciatn": "overheads",
    "wagesexpense": "overheads",
    "current asset": "current_assets",
    "fixed asset": "fixed_assets",
    "current liability": "liabilities",
    "non-current liability": "liabilities",
    "direct costs": "cost_of_sales",
    "other income": "sales",
    "depreciation": "overheads",
    # QuickBooks Online
    "accounts receivable (a/r)": "current_assets",
    "other current assets": "current_assets",
    "fixed assets": "fixed_assets",
    "other assets": "fixed_assets",
    "accounts payable (a/p)": "liabilities",
    "credit card": "liabilities",
    "other current liabilities": "liabilities",
    "long term liabilities": "liabilities",
    "income": "sales",
    "cost of goods sold": "cost_of_sales",
    "cost of sales": "cost_of_sales",
    "expenses": "overheads",
    "other expense": "overheads",
    "other expenses": "overheads",
    # Sage / FreeAgent / spreadsheet
    "current assets": "current_assets",
    "current liabilities": "liabilities",
    "liabilities": "liabilities",
    "capital": "capital",
    "capital & reserves": "capital",
    "capital and reserves": "capital",
    "reserves": "capital",
    "purchases": "cost_of_sales",
    "direct expenses": "cost_of_sales",
    "overhead": "overheads",
    "admin expenses": "overheads",
    "assets": "current_assets",
    "asset": "current_assets",
}

#: Name patterns -> a fixed Accnomos account, tried in order. Each is checked against the class when one is known.
NAME_RULES: tuple[tuple[str, str], ...] = (
    (
        r"\b(paye|p\.a\.y\.e|national insurance|nic|payroll|wages payable|net wages|pension liabilit\w*)\b",
        PAYROLL_LIABILITIES,
    ),
    (r"\b(vat|sales tax|purchase tax|gst|output tax|input tax)\b", VAT_CONTROL),
    (r"\b(accounts? receivable|trade debtors|debtors? control|debtors|receivables?)\b", DEBTORS),
    (r"\b(accounts? payable|trade creditors|creditors? control|creditors|payables?)\b", CREDITORS),
    (r"\b(petty cash|cash in hand|cash)\b", CASH),
    (r"\b(directors?'?|director's|owners?'?|owner's|shareholders?'?)\s+(loan|current account)\b", OWNER_LOAN),
    (r"\bdrawings\b", DRAWINGS),
    (
        r"\b(retained (earnings|profits?)|profit (and|&) loss account|p ?& ?l reserve|current year earnings|"
        r"accumulated (profits?|surplus))\b",
        RETAINED,
    ),
    (r"\b(share capital|capital introduced|opening balance equity|owner'?s? (equity|capital)|^capital)\b", CAPITAL),
    (r"^(sales|revenue|turnover|income|sales income|fees|fee income|general sales)$", SALES),
    (r"\b(gross wages|wages|salaries)\b", WAGES),
    (r"\bemployer'?s? (ni|n\.i\.|national insurance)\b", EMPLOYER_NI),
    (r"\b(materials?|purchases|cost of (goods )?(sales|sold)|stock purchases)\b", CATEGORY_ACCOUNTS["Materials"]),
    (r"\btools\b", CATEGORY_ACCOUNTS["Tools & small equipment"]),
    (r"\b(rent|rates)\b", CATEGORY_ACCOUNTS["Rent"]),
    (r"\b(utilities|electricity|gas|water|light and heat|heat (and|&) light)\b", CATEGORY_ACCOUNTS["Utilities"]),
    (r"\binsurance\b", CATEGORY_ACCOUNTS["Insurance"]),
    (r"\b(motor|vehicle|fuel|mileage)\b", CATEGORY_ACCOUNTS["Motor expenses"]),
    (r"\b(travel|travelling)\b", CATEGORY_ACCOUNTS["Travel"]),
    (r"\b(subsistence|meals)\b", CATEGORY_ACCOUNTS["Subsistence"]),
    (r"\b(software|subscriptions?|computer)\b", CATEGORY_ACCOUNTS["Software & subscriptions"]),
    (r"\b(telephone|phone|internet|broadband|mobile)\b", CATEGORY_ACCOUNTS["Telephone & internet"]),
    (r"\b(advertising|marketing|promotion)\b", CATEGORY_ACCOUNTS["Advertising"]),
    (r"\b(postage|courier|carriage)\b", CATEGORY_ACCOUNTS["Postage"]),
    (r"\bbank (charges|fees|interest paid)\b", CATEGORY_ACCOUNTS["Bank charges"]),
    (r"\b(accountancy|legal|professional|audit)\b", CATEGORY_ACCOUNTS["Professional fees"]),
    (r"\b(office|stationery|printing)\b", CATEGORY_ACCOUNTS["Office supplies"]),
    (r"\b(general expenses|sundry|sundries|miscellaneous)\b", SUNDRY),
)
_BANK_NAME = re.compile(r"\b(bank|current account|business account|savings|deposit account|instant access)\b", re.I)
_FIXED_NAME = re.compile(
    r"\b(motor vehicles?|plant|machinery|equipment|fixtures|fittings|computers?|"
    r"property|freehold|leasehold|furniture)\b(?!.*\b(expenses?|repairs?|hire)\b)",
    re.I,
)


def source_klass(vendor: fmt.Vendor | None, code: str | None, name: str, type_: str | None) -> Klass | None:
    """The class of a source account: its type when we know the word, else its code (Sage 50's layout), else None."""
    if type_:
        t = type_.strip().lower()
        if t in TYPE_CLASSES:
            return TYPE_CLASSES[t]
        head = t.split(":")[0].split("(")[0].strip()
        if head in TYPE_CLASSES:
            return TYPE_CLASSES[head]
    if vendor in ("sage50", "sage_accounting", "spreadsheet") and code and code.isdigit() and len(code) == 4:
        return klass_of_code(int(code))
    if _BANK_NAME.search(name) and not re.search(r"\b(charges|fees|interest)\b", name, re.I):
        return "bank"
    return None


class Suggestion(BaseModel):
    target: str | None
    how: How | None
    new: bool = False  # an account Accnomos does not post to itself, made from the source name


def _fits_klass(target: str, klass: Klass | None) -> bool:
    k = account_klass(target)
    if klass is None or k is None:
        return True
    group = {"bank": "assets", "current_assets": "assets", "fixed_assets": "assets"}
    return group.get(k, k) == group.get(klass, klass)


def suggest(
    vendor: fmt.Vendor | None,
    accounts: Sequence[fmt.SourceAccount],
    known: Iterable[str] = (),
) -> list[Suggestion]:
    """One suggestion per source account, in order. `known` are the accounts already in the user's ledger."""
    taken: set[int] = {int(a[:4]) for a in (*CHART, *known) if _ACCOUNT_RE.match(a)}
    out: list[Suggestion] = []
    bank_used = False
    for acc in accounts:
        k = source_klass(vendor, acc.code, acc.name, acc.type)
        # 1. Sage keeps its four-digit nominal codes (the same layout as ours): our account when we have that code,
        # else ours by name (2202 VAT Liability -> 2200 VAT control), else its own code and name.
        sage_code = vendor in ("sage50", "sage_accounting") and acc.code and acc.code.isdigit() and len(acc.code) == 4
        if sage_code and acc.code:
            same = next((a for a in CHART if a.startswith(acc.code + " ")), None)
            if same is None:
                same = next((t for pat, t in NAME_RULES if re.search(pat, acc.name, re.I) and _fits_klass(t, k)), None)
                if same is None and k == "bank" and re.search(r"\bcash\b", acc.name, re.I):
                    same = CASH
            target = same or f"{acc.code} {acc.name.strip()[:80]}"
            bank_used = bank_used or same == BANK
            out.append(
                Suggestion(
                    target=target, how="code" if same is None or same.startswith(acc.code) else "name", new=same is None
                )
            )
            taken.add(int(acc.code))
            continue
        # 2. By name, when the name says what it is and the class (if known) agrees. The first bank account is
        # 1200 Bank; any other gets an account of its own (1220, 1230, ...).
        hit: str | None = None
        not_bank = re.search(r"\b(charges|fees|interest)\b", acc.name, re.I)
        if k == "bank" or (k in (None, "current_assets") and _BANK_NAME.search(acc.name) and not not_bank):
            k = "bank"
            if re.search(r"\b(petty cash|cash in hand|cash)\b", acc.name, re.I) and not _BANK_NAME.search(acc.name):
                hit = CASH
            elif not bank_used:
                hit, bank_used = BANK, True
        else:
            if k is None and _FIXED_NAME.search(acc.name):
                k = "fixed_assets"  # "Motor vehicles" is an asset, not 7300 Motor expenses
            for pattern, target in NAME_RULES:
                if re.search(pattern, acc.name, re.I) and _fits_klass(target, k):
                    hit = target
                    break
        if hit:
            out.append(Suggestion(target=hit, how="name"))
            continue
        # 3. A new account in the range for its class.
        if k is None:
            out.append(Suggestion(target=None, how=None))
            continue
        lo, hi = RANGES[k]
        code = lo
        while code in taken and code <= hi:
            code += 10
        if code > hi:
            out.append(Suggestion(target=None, how=None))
            continue
        taken.add(code)
        out.append(Suggestion(target=f"{code:04d} {acc.name.strip()[:80]}", how="type", new=True))
    return out


# --------------------------------------------------------------------------- #
# The draft
# --------------------------------------------------------------------------- #


class DraftFile(BaseModel):
    id: str  # sha256 of the bytes, first 16 hex
    sha256: str
    name: str
    path: str  # where the upload was saved
    kind: fmt.FileKind
    vendor: fmt.Vendor | None = None
    rows: int
    skipped: list[str] = []
    uploaded_at: datetime
    uploaded_by: str
    parsed: fmt.Parsed


class Draft(BaseModel):
    vendor: fmt.Vendor | None = None
    conversion_date: date | None = None  # the first day in Accnomos; balances are as at the day before
    pl_treatment: PlTreatment = "keep"
    files: list[DraftFile] = []
    mapping: dict[str, str] = {}  # source account key -> Accnomos account, set by the user
    updated_at: datetime | None = None
    updated_by: str | None = None


def account_key(acc: fmt.SourceAccount) -> str:
    """Stable key for a source account: its code if it has one, else its name."""
    return f"code:{acc.code.strip().lower()}" if acc.code else f"name:{acc.name.strip().lower()}"


async def load_draft(books: Books) -> Draft:
    raw = await books.read_json(DRAFT, None)
    return Draft.model_validate(raw, **LENIENT) if raw else Draft()


async def save_draft(books: Books, draft: Draft, user: str) -> Draft:
    draft.updated_at, draft.updated_by = now(), user
    await books.write_json(DRAFT, draft.model_dump(mode="json"))
    return draft


async def add_file(
    books: Books,
    data: bytes,
    name: str,
    user: str,
    kind: fmt.FileKind | None = None,
    vendor: fmt.Vendor | None = None,
    side: fmt.Side | None = None,
) -> tuple[Draft, DraftFile]:
    """Read one export, save it as it came and add its rows to the draft. A second trial balance replaces the
    first; the same file again replaces itself. Raises ImportFormatError."""
    draft = await load_draft(books)
    parsed = fmt.parse(data, name, kind, vendor or draft.vendor, side)
    sha = hashlib.sha256(data).hexdigest()
    path = f"{SOURCES}/{sha[:16]}-{name}"
    if not await books.exists(path):
        await books.storage.write(path, data)
    rows = len(parsed.accounts) + len(parsed.contacts) + len(parsed.items) + len(parsed.banks)
    f = DraftFile(
        id=sha[:16],
        sha256=sha,
        name=name,
        path=path,
        kind=parsed.kind,
        vendor=parsed.vendor,
        rows=rows,
        skipped=parsed.skipped[:50],
        uploaded_at=now(),
        uploaded_by=user,
        parsed=parsed,
    )
    draft.files = [
        x for x in draft.files if x.id != f.id and not (f.kind == "trial_balance" and x.kind == "trial_balance")
    ]
    if len(draft.files) >= MAX_FILES:
        raise fmt.ImportFormatError(f"At most {MAX_FILES} files in one import; remove one first")
    draft.files.append(f)
    if draft.vendor is None and parsed.vendor:
        draft.vendor = parsed.vendor
    await save_draft(books, draft, user)
    await books.audit(
        f"user:{user}", "import_file_added", {"file": path, "kind": f.kind, "vendor": f.vendor, "rows": rows}
    )
    return draft, f


# --------------------------------------------------------------------------- #
# Working it out: mapping, journal, checks
# --------------------------------------------------------------------------- #


class MappingRow(BaseModel):
    key: str
    code: str | None
    name: str
    type: str | None
    klass: Klass | None
    balance_pence: int  # debit positive
    target: str | None  # the Accnomos account it goes to (None: unmapped)
    how: How | None
    new: bool = False
    suggested: str | None = None


class JournalRow(BaseModel):
    account: str
    debit_pence: int = 0
    credit_pence: int = 0
    sources: list[str] = []  # source account names


class Check(BaseModel):
    id: str
    severity: Severity
    ok: bool
    message: str
    expected_pence: int | None = None
    actual_pence: int | None = None


class OpenItem(BaseModel):
    """An unpaid invoice or bill carried over (`side` "sale": a customer owes it; "purchase": owed to a supplier)."""

    id: str  # 32 hex; the document's id everywhere a ledger event id would be (payments, statements, aged)
    side: fmt.Side
    contact: str
    number: str | None = None
    date: date
    due_date: date | None = None
    total_pence: int
    due_pence: int = Field(gt=0)


class DraftView(BaseModel):
    draft: Draft
    balance_date: date | None
    accounts: list[MappingRow]
    journal: list[JournalRow]
    debits_pence: int
    credits_pence: int
    contacts: int
    items: list[OpenItem]
    banks: list[fmt.BankBalanceRow]
    checks: list[Check]
    can_post: bool
    needs_accept: bool  # warnings to accept before posting
    chart: list[str]  # accounts to choose from


def _merged_accounts(draft: Draft) -> list[fmt.SourceAccount]:
    """The trial balance's accounts, with types filled in from a chart of accounts (by code, then by name)."""
    tb = next((f for f in draft.files if f.kind == "trial_balance"), None)
    if tb is None:
        return []
    types_by_code: dict[str, str] = {}
    types_by_name: dict[str, str] = {}
    for f in draft.files:
        if f.kind == "chart_of_accounts":
            for a in f.parsed.accounts:
                if a.type:
                    if a.code:
                        types_by_code[a.code.strip().lower()] = a.type
                    types_by_name[a.name.strip().lower()] = a.type
    out = []
    for a in tb.parsed.accounts:
        t = a.type or types_by_code.get((a.code or "").strip().lower()) or types_by_name.get(a.name.strip().lower())
        out.append(a.model_copy(update={"type": t}))
    return out


def open_items(draft: Draft, import_id: str = "draft") -> list[OpenItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[OpenItem] = []
    for f in draft.files:
        if f.kind != "open_items":
            continue
        for i, it in enumerate(f.parsed.items):
            key = (it.side, it.contact.lower(), (it.number or f"#{f.id}:{i}").lower())
            if key in seen:
                continue
            seen.add(key)
            oid = hashlib.sha256(f"{import_id}|{key}".encode()).hexdigest()[:32]
            out.append(OpenItem(id=oid, **it.model_dump()))
    return sorted(out, key=lambda x: (x.date, x.contact.lower(), x.number or ""))


def _contacts(draft: Draft) -> list[fmt.ContactRow]:
    by_name: dict[str, fmt.ContactRow] = {}
    for f in draft.files:
        if f.kind == "contacts":
            for c in f.parsed.contacts:
                by_name.setdefault(c.name.strip().lower(), c)
    return list(by_name.values())


def _banks(draft: Draft) -> list[fmt.BankBalanceRow]:
    return [b for f in draft.files if f.kind == "bank_balances" for b in f.parsed.banks]


def mapping_rows(draft: Draft, known: Iterable[str] = ()) -> list[MappingRow]:
    accounts = _merged_accounts(draft)
    rows = []
    for acc, s in zip(accounts, suggest(draft.vendor, accounts, known), strict=True):
        key = account_key(acc)
        chosen = draft.mapping.get(key)
        klass = source_klass(draft.vendor, acc.code, acc.name, acc.type)
        if chosen:
            target, how, new = chosen, "user", chosen not in CHART and chosen not in set(known)
        else:
            target, how, new = s.target, s.how, s.new
        if klass is None and target:
            klass = account_klass(target)
        rows.append(
            MappingRow(
                key=key,
                code=acc.code,
                name=acc.name,
                type=acc.type,
                klass=klass,
                balance_pence=acc.balance_pence,
                target=target,
                how=how,
                new=new,
                suggested=s.target,
            )
        )
    return rows


def journal_rows(rows: Sequence[MappingRow], pl_treatment: PlTreatment) -> list[JournalRow]:
    """One row per Accnomos account: the net of the source accounts mapped to it, on its own side."""
    net: dict[str, int] = defaultdict(int)
    sources: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r.target is None or r.balance_pence == 0:
            continue
        target = r.target
        if pl_treatment == "retained" and (account_klass(target) in PL_CLASSES or r.klass in PL_CLASSES):
            target = RETAINED
        net[target] += r.balance_pence
        sources[target].append(r.name)
    return [
        JournalRow(account=a, debit_pence=max(n, 0), credit_pence=max(-n, 0), sources=sources[a])
        for a, n in sorted(net.items())
        if n
    ]


def _balance_of(rows: Sequence[MappingRow], pred: Any) -> int:
    return sum(r.balance_pence for r in rows if r.target and pred(r.target))


async def _blocking_state(books: Books, balance_date: date | None) -> tuple[list[LedgerEvent], dict[str, Any] | None]:
    """Entries already on or before the balance date (an entry and its undo cancel out, so neither counts), and the
    import in force, if any."""
    events = await books.list_events(None, balance_date) if balance_date else []
    gone = {e.reverses for e in events if e.reverses}
    record = await books.read_json(OPENING, None)
    live = [e for e in events if e.id not in gone and not e.reverses]
    return live, record if record and not record.get("undone_at") else None


def checks_for(
    draft: Draft,
    rows: Sequence[MappingRow],
    journal: Sequence[JournalRow],
    items: Sequence[OpenItem],
    banks: Sequence[fmt.BankBalanceRow],
    earlier: Sequence[LedgerEvent],
    active: dict[str, Any] | None,
) -> list[Check]:
    out: list[Check] = []
    tb = next((f for f in draft.files if f.kind == "trial_balance"), None)
    out.append(
        Check(
            id="tb_present",
            severity="error",
            ok=tb is not None and bool(rows),
            message="Trial balance uploaded" if tb else "Upload the trial balance at the conversion date",
        )
    )
    dr = sum(max(r.balance_pence, 0) for r in rows)
    cr = sum(max(-r.balance_pence, 0) for r in rows)
    out.append(
        Check(
            id="tb_balanced",
            severity="error",
            ok=bool(rows) and dr == cr,
            message="Debits equal credits"
            if dr == cr
            else f"The trial balance is out by £{abs(dr - cr) / 100:,.2f}: "
            "export it again from the old system (all accounts, no rounding)",
            expected_pence=dr,
            actual_pence=cr,
        )
    )
    unmapped = [
        r.name for r in rows if r.target is None and not (draft.pl_treatment == "retained" and r.klass in PL_CLASSES)
    ]
    out.append(
        Check(
            id="all_mapped",
            severity="error",
            ok=not unmapped,
            message="Every account has an Accnomos account"
            if not unmapped
            else f"{len(unmapped)} account(s) need an Accnomos account: " + ", ".join(unmapped[:8]),
        )
    )
    bad = [r.target for r in rows if r.target and not _ACCOUNT_RE.match(r.target)]
    if bad:
        out.append(
            Check(
                id="targets_valid",
                severity="error",
                ok=False,
                message="An account must be a four-digit code and a name: " + ", ".join(bad[:5]),
            )
        )
    new = sorted({r.target for r in rows if r.new and r.target})
    if new:
        out.append(
            Check(
                id="new_accounts",
                severity="info",
                ok=True,
                message=f"{len(new)} new account(s) will be added: " + ", ".join(new[:8]),
            )
        )
    out.append(
        Check(
            id="conversion_date",
            severity="error",
            ok=draft.conversion_date is not None,
            message="Conversion date set" if draft.conversion_date else "Choose the conversion date",
        )
    )
    if earlier:
        out.append(
            Check(
                id="books_empty_before",
                severity="error",
                ok=False,
                message=f"The books already have {len(earlier)} entr{'y' if len(earlier) == 1 else 'ies'} on or before "
                "the balance date; choose a conversion date after them",
            )
        )
    if active:
        out.append(
            Check(
                id="no_active_import",
                severity="error",
                ok=False,
                message="Opening balances are already posted; undo that import first",
            )
        )
    # Debtors and creditors against the open items.
    for side, target, label, word in (
        ("sale", DEBTORS, "debtors", "invoices"),
        ("purchase", CREDITORS, "creditors", "bills"),
    ):
        balance = _balance_of(rows, lambda t, target=target: t == target)
        if side == "purchase":
            balance = -balance
        listed = sum(i.due_pence for i in items if i.side == side)
        have_list = any(i.side == side for i in items)
        if not balance and not have_list:
            continue
        ok = balance == listed
        msg = (
            f"Open {word} add up to the {label} balance"
            if ok
            else f"Open {word} total £{listed / 100:,.2f}; the {label} balance is £{balance / 100:,.2f}"
            if have_list
            else f"The {label} balance is £{balance / 100:,.2f} but no open {word} were uploaded: "
            f"aged {label} will not show them"
        )
        out.append(
            Check(
                id=f"{label}_match", severity="warning", ok=ok, message=msg, expected_pence=balance, actual_pence=listed
            )
        )
    if banks:
        tb_bank = _balance_of(rows, is_bank_account)
        stated = sum(b.balance_pence for b in banks)
        out.append(
            Check(
                id="bank_match",
                severity="warning",
                ok=tb_bank == stated,
                message="Bank balances agree with the trial balance"
                if tb_bank == stated
                else f"Bank balances total £{stated / 100:,.2f}; the bank accounts in the trial balance hold "
                f"£{tb_bank / 100:,.2f}",
                expected_pence=tb_bank,
                actual_pence=stated,
            )
        )
    if draft.conversion_date:
        late = [i for i in items if i.date >= draft.conversion_date]
        if late:
            out.append(
                Check(
                    id="items_dated_after",
                    severity="warning",
                    ok=False,
                    message=f"{len(late)} open item(s) are dated on or after the conversion date",
                )
            )
    if journal and sum(j.debit_pence for j in journal) != sum(j.credit_pence for j in journal):
        out.append(
            Check(id="journal_balanced", severity="error", ok=False, message="The opening entry does not balance")
        )
    return out


async def view(books: Books, draft: Draft | None = None) -> DraftView:
    draft = draft or await load_draft(books)
    balance_date = draft.conversion_date - timedelta(days=1) if draft.conversion_date else None
    earlier, active = await _blocking_state(books, balance_date)
    known = sorted({ln.account for e in await books.list_events() for ln in e.lines})
    rows = mapping_rows(draft, known)
    journal = journal_rows(rows, draft.pl_treatment)
    items = open_items(draft)
    banks = _banks(draft)
    checks = checks_for(draft, rows, journal, items, banks, earlier, active)
    return DraftView(
        draft=draft,
        balance_date=balance_date,
        accounts=rows,
        journal=journal,
        debits_pence=sum(j.debit_pence for j in journal),
        credits_pence=sum(j.credit_pence for j in journal),
        contacts=len(_contacts(draft)),
        items=items,
        banks=banks,
        checks=checks,
        can_post=not any(c.severity == "error" and not c.ok for c in checks),
        needs_accept=any(c.severity == "warning" and not c.ok for c in checks),
        chart=sorted({*CHART, *known}),
    )


class ImportPlanError(ValueError):
    """Posting refused: the message says why."""


def validate_target(target: str) -> str:
    target = re.sub(r"\s+", " ", target).strip()
    if not _ACCOUNT_RE.match(target):
        raise ImportPlanError("An account is a four-digit code, a space and a name, like '0010 Motor vehicles'")
    return target


# --------------------------------------------------------------------------- #
# Posting, the record, undo
# --------------------------------------------------------------------------- #


class OpeningRecord(BaseModel):
    """_System/Import/opening.json: what was imported, and the open items app.contacts reads."""

    id: str
    vendor: fmt.Vendor | None
    conversion_date: date
    balance_date: date
    pl_treatment: PlTreatment
    event_id: str
    posted_at: datetime
    posted_by: str
    files: list[dict[str, Any]]  # name, kind, sha256, path
    accounts: list[MappingRow]
    source_debits_pence: int
    source_credits_pence: int
    items: list[OpenItem]
    banks: list[fmt.BankBalanceRow]
    contacts_added: list[str] = []
    contacts_updated: list[str] = []
    accepted_warnings: list[str] = []
    report_path: str | None = None
    undone_at: datetime | None = None
    undone_by: str | None = None
    reversal_event_id: str | None = None


async def load_record(books: Books) -> OpeningRecord | None:
    raw = await books.read_json(OPENING, None)
    return OpeningRecord.model_validate(raw, **LENIENT) if raw else None


async def live_open_items(books: Books) -> list[OpenItem]:
    """The open items of the import in force (none once it is undone). Read by app.contacts.load_ledger."""
    try:
        rec = await load_record(books)
    except ValueError:  # a hand-edited file that no longer parses: show nothing rather than fail every page
        return []
    return [] if rec is None or rec.undone_at else rec.items


def opening_event(v: DraftView, user: str, at: datetime) -> LedgerEvent:
    if v.balance_date is None:
        raise ImportPlanError("Choose the conversion date")
    source = v.draft.vendor and fmt.VENDOR_NAMES[v.draft.vendor] or "the old system"
    return LedgerEvent(
        kind="adjustment",
        date=v.balance_date,
        lines=[
            Line(
                account=j.account,
                debit=j.debit_pence,
                credit=j.credit_pence,
                memo=f"Opening balance from {source}: " + ", ".join(j.sources)[:300],
            )
            for j in v.journal
        ],
        evidence=sorted({f.sha256 for f in v.draft.files}),
        approved_by=user,
        approved_at=at,
        net=0,
        vat=0,
        counterparty=None,
    )


async def _merge_contacts(
    books: Books, draft: Draft, items: Sequence[OpenItem], at: datetime
) -> tuple[list[str], list[str]]:
    from app.autopilot import supplier_key
    from app.checks import normalise_vat_number
    from app.contacts import CONTACTS, Contact, _dump, _parse_stored, contact_id, find

    rows = _contacts(draft)
    sides: dict[str, set[str]] = defaultdict(set)
    for it in items:
        sides[supplier_key(it.contact)].add(it.side)
    names = {supplier_key(c.name): c for c in rows}
    for it in items:
        names.setdefault(supplier_key(it.contact), fmt.ContactRow(name=it.contact))
    added: list[str] = []
    updated: list[str] = []

    def change(raw: Any) -> Any:
        added.clear()
        updated.clear()
        book = _parse_stored(raw)
        for key, row in names.items():
            if not key:
                continue
            vrn = normalise_vat_number(row.vat_number) if row.vat_number else None
            kind = row.kind or (
                "both" if len(sides[key]) > 1 else "supplier" if "purchase" in sides[key] else "customer"
            )
            c = find(book, key, vrn)
            if c is None:
                book.append(
                    Contact(
                        id=contact_id(key, vrn),
                        kind=kind,
                        name=row.name,
                        normalised_key=key,
                        vrn=vrn,
                        email=row.email,
                        phone=row.phone,
                        address=row.address,
                        terms_days=row.terms_days,
                        source="import",
                        created_at=at,
                        updated_at=at,
                    )
                )
                added.append(row.name)
                continue
            changed = False
            for f, v in (
                ("email", row.email),
                ("phone", row.phone),
                ("address", row.address),
                ("vrn", vrn),
                ("terms_days", row.terms_days),
            ):
                if v is not None and getattr(c, f) in (None, "") and f not in c.edited:
                    setattr(c, f, v)
                    changed = True
            if c.kind != kind and c.kind != "both" and "kind" not in c.edited and row.kind is None and sides[key]:
                c.kind = "both"
                changed = True
            if changed:
                c.updated_at = at
                updated.append(c.name)
        return _dump(sorted(book, key=lambda c: c.name.lower()))

    await books._update_json(CONTACTS, [], change)
    return added, updated


async def post(books: Books, user: str, accept_warnings: bool) -> OpeningRecord:
    """Post the opening entry, record the import, add the contacts, save the reconciliation. Raises
    ImportPlanError when a check fails or warnings were not accepted."""
    v = await view(books)
    errors = [c.message for c in v.checks if c.severity == "error" and not c.ok]
    if errors:
        raise ImportPlanError(errors[0])
    warnings = [c.message for c in v.checks if c.severity == "warning" and not c.ok]
    if warnings and not accept_warnings:
        raise ImportPlanError("Accept the warnings first: " + warnings[0])
    assert v.draft.conversion_date and v.balance_date
    at = now()
    event = opening_event(v, user, at)
    items = open_items(v.draft, event.id)
    await books.post_event(event)
    added, updated = await _merge_contacts(books, v.draft, items, at)
    record = OpeningRecord(
        id=event.id,
        vendor=v.draft.vendor,
        conversion_date=v.draft.conversion_date,
        balance_date=v.balance_date,
        pl_treatment=v.draft.pl_treatment,
        event_id=event.id,
        posted_at=at,
        posted_by=user,
        files=[{"name": f.name, "kind": f.kind, "sha256": f.sha256, "path": f.path} for f in v.draft.files],
        accounts=v.accounts,
        source_debits_pence=sum(max(r.balance_pence, 0) for r in v.accounts),
        source_credits_pence=sum(max(-r.balance_pence, 0) for r in v.accounts),
        items=items,
        banks=v.banks,
        contacts_added=added,
        contacts_updated=updated,
        accepted_warnings=warnings,
    )
    await books.write_json(OPENING, record.model_dump(mode="json"))
    report = await reconcile(books, record)
    record.report_path = await _save_report(books, report)
    await books.write_json(OPENING, record.model_dump(mode="json"))
    await books.storage.write(DRAFT, b"null")
    await books.audit(
        f"user:{user}",
        "opening_balances_posted",
        {
            "event": event.id,
            "vendor": record.vendor,
            "conversion_date": record.conversion_date.isoformat(),
            "accounts": len(record.accounts),
            "open_items": len(items),
            "contacts_added": len(added),
            "proved": report.proved,
            "file": record.report_path,
        },
    )
    await books.rebuild_safely(f"user:{user}")
    return record


class ImportUndoError(ValueError):
    pass


async def undo(books: Books, user: str) -> OpeningRecord:
    from app.approve import reversal_of
    from app.contacts import load_ledger

    rec = await load_record(books)
    if rec is None or rec.undone_at:
        raise FileNotFoundError("no opening balances to undo")
    ids = {i.id for i in rec.items}
    ledger = await load_ledger(books)
    if any(a.event_id in ids for r in ledger.records if not r.removed_at for a in r.allocations):
        raise ImportUndoError("A payment is recorded against an opening invoice or bill; remove it first")
    if any(u.doc_event_id in ids or u.credit_doc_event_id in ids for u in ledger.uses if not u.removed_at):
        raise ImportUndoError("A credit is applied to an opening invoice or bill; remove it first")
    if any(e.credits in ids for e in ledger.events):
        raise ImportUndoError("A credit note was raised against an opening invoice or bill; undo it first")
    original = await books.get_event(rec.event_id)
    reversal = reversal_of(original, user)
    with contextlib.suppress(FileExistsError):  # a retried undo
        await books.post_event(reversal)
    rec.undone_at, rec.undone_by, rec.reversal_event_id = now(), user, reversal.id
    await books.write_json(OPENING, rec.model_dump(mode="json"))
    await books.audit(f"user:{user}", "opening_balances_undone", {"event": rec.event_id, "reversal": reversal.id})
    await books.rebuild_safely(f"user:{user}")
    return rec


# --------------------------------------------------------------------------- #
# Reconciliation: the imported trial balance against the source
# --------------------------------------------------------------------------- #


class ReconRow(BaseModel):
    account: str
    sources: list[str]
    source_pence: int  # what the source TB says this account holds (debit positive)
    accnomos_pence: int  # what the Accnomos ledger holds at the balance date
    ok: bool


class Reconciliation(BaseModel):
    import_id: str
    vendor: fmt.Vendor | None
    balance_date: date
    rows: list[ReconRow]
    source_debits_pence: int
    source_credits_pence: int
    accnomos_debits_pence: int
    accnomos_credits_pence: int
    checks: list[Check]
    proved: bool
    undone: bool = False


async def reconcile(books: Books, record: OpeningRecord | None = None) -> Reconciliation:
    from app import contacts as cb
    from app.projection import trial_balance

    rec = record or await load_record(books)
    if rec is None:
        raise FileNotFoundError("no opening balances imported")
    expected: dict[str, int] = defaultdict(int)
    names: dict[str, list[str]] = defaultdict(list)
    for r in rec.accounts:
        if r.target is None or r.balance_pence == 0:
            continue
        target = (
            RETAINED
            if rec.pl_treatment == "retained" and (account_klass(r.target) in PL_CLASSES or r.klass in PL_CLASSES)
            else r.target
        )
        expected[target] += r.balance_pence
        names[target].append(f"{r.code + ' ' if r.code else ''}{r.name}")
    events = await books.list_events(None, rec.balance_date)
    actual = {a: dr - cr for a, dr, cr in trial_balance(events)}
    rows = [
        ReconRow(
            account=a,
            sources=names.get(a, []),
            source_pence=expected.get(a, 0),
            accnomos_pence=actual.get(a, 0),
            ok=expected.get(a, 0) == actual.get(a, 0),
        )
        for a in sorted(set(expected) | {a for a, n in actual.items() if n})
    ]
    adr = sum(max(n, 0) for n in actual.values())
    acr = sum(max(-n, 0) for n in actual.values())
    checks: list[Check] = []
    # Totals: with "retained" the P&L accounts fold into one, so compare the account balances, not the sums.
    checks.append(
        Check(
            id="totals",
            severity="error",
            ok=adr == acr and all(r.ok for r in rows),
            message="Every account agrees with the source trial balance"
            if all(r.ok for r in rows)
            else f"{sum(not r.ok for r in rows)} account(s) differ from the source trial balance",
            expected_pence=rec.source_debits_pence,
            actual_pence=adr,
        )
    )
    contacts, ledger, _ = await cb.contact_book(books)
    aged = cb.aged(contacts, ledger, rec.balance_date)
    for side, label, table, account in (
        ("sale", "debtors", aged.debtors, DEBTORS),
        ("purchase", "creditors", aged.creditors, CREDITORS),
    ):
        ids = {i.id for i in rec.items if i.side == side}
        if not ids and not expected.get(account):
            continue
        opening_total = sum(d.amount_pence for row in table.rows for d in row.documents if d.event_id in ids)
        listed = sum(i.due_pence for i in rec.items if i.side == side)
        balance = expected.get(account, 0) * (1 if side == "sale" else -1)
        ok = opening_total == listed == balance
        checks.append(
            Check(
                id=f"aged_{label}",
                severity="warning",
                ok=ok,
                message=f"Aged {label} at the balance date equal the source {label}"
                if ok
                else f"Aged {label} from the opening items £{opening_total / 100:,.2f}; source {label} balance "
                f"£{balance / 100:,.2f}",
                expected_pence=balance,
                actual_pence=opening_total,
            )
        )
    if rec.banks:
        bank_actual = sum(n for a, n in actual.items() if is_bank_account(a))
        stated = sum(b.balance_pence for b in rec.banks)
        checks.append(
            Check(
                id="bank",
                severity="warning",
                ok=bank_actual == stated,
                message="Bank accounts equal the bank balances uploaded"
                if bank_actual == stated
                else f"Bank accounts hold £{bank_actual / 100:,.2f}; "
                f"the bank balances uploaded say £{stated / 100:,.2f}",
                expected_pence=stated,
                actual_pence=bank_actual,
            )
        )
    return Reconciliation(
        import_id=rec.id,
        vendor=rec.vendor,
        balance_date=rec.balance_date,
        rows=rows,
        source_debits_pence=rec.source_debits_pence,
        source_credits_pence=rec.source_credits_pence,
        accnomos_debits_pence=adr,
        accnomos_credits_pence=acr,
        checks=checks,
        proved=all(c.ok for c in checks),
        undone=rec.undone_at is not None,
    )


def report_csv(r: Reconciliation, sample: bool = False) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    if sample:
        from app.projection import SAMPLE_LABEL

        w.writerow([SAMPLE_LABEL])
    source = fmt.VENDOR_NAMES[r.vendor] if r.vendor else "the old system"
    w.writerow([f"Opening balances from {source}: reconciliation at {r.balance_date.isoformat()}"])
    w.writerow(["Account", "Source accounts", "Source £", "Accnomos £", "Agrees"])
    for row in r.rows:
        w.writerow(
            [
                row.account,
                "; ".join(row.sources),
                f"{row.source_pence / 100:.2f}",
                f"{row.accnomos_pence / 100:.2f}",
                "yes" if row.ok else "NO",
            ]
        )
    w.writerow([])
    w.writerow(
        [
            "Source debits £",
            f"{r.source_debits_pence / 100:.2f}",
            "Source credits £",
            f"{r.source_credits_pence / 100:.2f}",
        ]
    )
    w.writerow(
        [
            "Accnomos debits £",
            f"{r.accnomos_debits_pence / 100:.2f}",
            "Accnomos credits £",
            f"{r.accnomos_credits_pence / 100:.2f}",
        ]
    )
    for c in r.checks:
        w.writerow([c.id, c.message, "ok" if c.ok else "CHECK"])
    w.writerow(["Proved", "yes" if r.proved else "NO"])
    return buf.getvalue().encode("utf-8-sig")


async def _save_report(books: Books, r: Reconciliation) -> str:
    from app.reports import is_sample

    path = await books.free_path(REPORTS, f"{now().date().isoformat()}-opening-balances-reconciliation.csv")
    await books.storage.write(path, report_csv(r, sample=is_sample(await books.list_events())))
    return path
