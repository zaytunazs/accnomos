"""Customers and suppliers: a contact book built from the ledger, kept in _System/Contacts/contacts.json.

Stored: who they are (name, VAT number, email, phone, address, defaults) and where the entry came from.
Never stored: money. Statements, totals and aged balances are worked out from the event files and the
bank matches on every request, so they cannot drift from the ledger.

A ledger counterparty is the same contact when (`find`):
  1. the VAT number matches (when both have one), or else
  2. the normalised name matches ("Screwfix Direct Ltd." and "SCREWFIX DIRECT" are both "screwfix-direct",
     app.autopilot.supplier_key) or a name the contact was known by before (`aliases`), and the VAT
     numbers do not differ.
VAT numbers come from the documents behind purchases only: on a sales invoice it is the user's own.

Refreshing never overwrites a field the user edited (`edited`); renaming keeps the old name as an alias so
later entries under the old name still find the contact.

Open (unpaid) documents: a sales invoice (Dr 1100 Debtors) or a purchase on account (Cr 2100 Creditors)
until a bank line is matched to it. A receipt paid by card, cash or transfer at the time credits the bank
directly, so it is paid when posted and never open.

Signs: amounts are pence from the user's side; positive means the contact owes the user, negative means
the user owes the contact.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from accnomos_connectors.base import AddressBookContact
from accnomos_ledger.bank import BankLine
from accnomos_ledger.events import LedgerEvent, VatCode
from app.autopilot import supplier_key
from app.books import SYSTEM, Books, now
from app.checks import UNKNOWN_SUPPLIER, SupplierKnowledge, normalise_vat_number
from app.journal import CREDITORS, DEBTORS, VAT_CONTROL
from app.schemas import CATEGORIES, ExtractedDoc, Proposal, VatStatus

CONTACTS = f"{SYSTEM}/Contacts/contacts.json"
ContactKind = Literal["customer", "supplier", "both"]
ContactSource = Literal["ledger", "outlook", "manual"]
Side = Literal["sale", "purchase"]
EDITABLE = ("name", "kind", "vrn", "email", "phone", "address", "default_category", "default_vat_code", "vat_status")
VAT_STATUSES = ("registered", "not_registered", "unknown")
BUCKETS = ("0-30", "31-60", "61-90", "90+")
ID_RE = re.compile(r"[0-9a-f]{16}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class Contact(BaseModel):
    id: str
    kind: ContactKind
    name: str
    normalised_key: str
    vrn: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    default_category: str | None = None
    default_vat_code: str | None = None
    source: ContactSource = "ledger"
    vat_status: VatStatus = (
        "unknown"  # learnt on approval (`learn_vat_status`) or set on Contacts; see `supplier_knowledge`
    )
    aliases: list[str] = []  # other normalised names that mean this contact (old names, other spellings)
    edited: list[str] = []  # fields the user changed; refreshing leaves them alone
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


def contact_id(key: str, vrn: str | None) -> str:
    """Stable id, so a contact derived before contacts.json exists keeps its id once saved."""
    return hashlib.sha256(f"{key}|{vrn or ''}".encode()).hexdigest()[:16]


def uk_tax_year_start(today: date) -> date:
    """6 April on or before `today`."""
    start = date(today.year, 4, 6)
    return start if today >= start else date(today.year - 1, 4, 6)


def find(contacts: Iterable[Contact], key: str, vrn: str | None) -> Contact | None:
    contacts = list(contacts)
    if vrn and (hit := next((c for c in contacts if c.vrn == vrn), None)):
        return hit
    return next(
        (
            c
            for c in contacts
            if key and (key == c.normalised_key or key in c.aliases) and not (vrn and c.vrn and c.vrn != vrn)
        ),
        None,
    )


# --------------------------------------------------------------------------- #
# The ledger, as the contact book sees it
# --------------------------------------------------------------------------- #


@dataclass
class Ledger:
    events: list[LedgerEvent]
    proposals: dict[str, Proposal] = field(default_factory=dict)  # by id
    bank_lines: list[BankLine] = field(default_factory=list)


async def load_ledger(books: Books) -> Ledger:
    return Ledger(
        events=await books.list_events(),
        proposals={p.id: p for p in await books.list_proposals()},
        bank_lines=await books.stored_bank_lines(),
    )


@dataclass
class Doc:
    """A sale or purchase as it bears on one counterparty. Reversals carry sign -1 and the original's side."""

    event: LedgerEvent
    side: Side
    sign: int
    name: str
    key: str
    vrn: str | None
    gross: int
    on_account: bool  # debtors/creditors, so it waits for a payment
    reference: str | None
    category: str | None
    vat_code: str | None


def _expense_vat_code(e: LedgerEvent) -> str | None:
    codes = [ln.vat_code.value for ln in e.lines if ln.debit and ln.account != VAT_CONTROL and ln.vat_code]
    return Counter(codes).most_common(1)[0][0] if codes else None


def documents(ledger: Ledger) -> list[Doc]:
    """Every sale, purchase and reversal of one, oldest first."""
    by_id = {e.id: e for e in ledger.events}
    out: list[Doc] = []
    for e in ledger.events:
        original = by_id.get(e.reverses) if e.kind == "reversal" and e.reverses else None
        source = original or e
        if source.kind not in ("sale", "purchase"):
            continue
        side: Side = source.kind  # type: ignore[assignment]
        name = (e.counterparty or source.counterparty or "").strip()
        p = ledger.proposals.get(source.proposal_id or "")
        doc = p.extracted if p else None
        account = DEBTORS if side == "sale" else CREDITORS
        out.append(
            Doc(
                event=e,
                side=side,
                sign=-1 if original else 1,
                name=name,
                key=supplier_key(name) if name else "",
                vrn=normalise_vat_number(doc.supplier_vat_number) if doc and side == "purchase" else None,
                gross=sum(ln.debit for ln in source.lines),
                on_account=any(ln.account == account for ln in source.lines),
                reference=doc.invoice_number if doc else None,
                category=doc.category_guess if doc and side == "purchase" else None,
                vat_code=_expense_vat_code(source) if side == "purchase" else None,
            )
        )
    return out


def _kind(sides: set[str]) -> ContactKind:
    return "both" if len(sides) > 1 else "customer" if "sale" in sides else "supplier"


def merge_ledger(contacts: Sequence[Contact], ledger: Ledger, at: datetime | None = None) -> list[Contact]:
    """The contact book with every counterparty in the ledger in it; user-edited fields are kept as they are."""
    at = at or now()
    book = [c.model_copy(deep=True) for c in contacts]
    seen: dict[str, list[Doc]] = {}
    for d in documents(ledger):
        if not d.key or d.sign < 0:  # a reversal adds nobody new
            continue
        c = find(book, d.key, d.vrn)
        if c is None:
            c = Contact(
                id=contact_id(d.key, d.vrn),
                kind=_kind({d.side}),
                name=d.name,
                normalised_key=d.key,
                vrn=d.vrn,
                created_at=at,
                updated_at=at,
            )
            book.append(c)
        if d.vrn and not c.vrn and "vrn" not in c.edited:
            c.vrn = d.vrn
        if d.key != c.normalised_key and d.key not in c.aliases:
            c.aliases.append(d.key)
        seen.setdefault(c.id, []).append(d)
    for c in book:
        docs = seen.get(c.id)
        if not docs:
            continue
        derived: dict[str, Any] = {"kind": _kind({d.side for d in docs})}
        if cats := [d.category for d in docs if d.category]:
            derived["default_category"] = Counter(cats).most_common(1)[0][0]
        if codes := [d.vat_code for d in docs if d.vat_code]:
            derived["default_vat_code"] = Counter(codes).most_common(1)[0][0]
        changed = {k: v for k, v in derived.items() if k not in c.edited and getattr(c, k) != v}
        for k, v in changed.items():
            setattr(c, k, v)
        if changed:
            c.updated_at = at
    return sorted(book, key=lambda c: c.name.lower())


def assign(contacts: Sequence[Contact], docs: Iterable[Doc]) -> dict[str, list[Doc]]:
    """Contact id -> its documents (reversals included)."""
    out: dict[str, list[Doc]] = {}
    for d in docs:
        if d.key and (c := find(contacts, d.key, d.vrn)):
            out.setdefault(c.id, []).append(d)
    return out


# --------------------------------------------------------------------------- #
# Money: payments, statements, totals, aged balances (derived, never stored)
# --------------------------------------------------------------------------- #


def payments(bank_lines: Iterable[BankLine]) -> dict[str, BankLine]:
    """Event id -> the matched bank line that pays it."""
    return {eid: ln for ln in bank_lines if ln.status == "matched" for eid in ln.event_ids()}


def reversed_ids(events: Iterable[LedgerEvent]) -> set[str]:
    return {e.reverses for e in events if e.kind == "reversal" and e.reverses}


def _signed(d: Doc) -> int:
    """The document's effect on the balance: a sale is owed to the user, a purchase is owed by the user."""
    return d.sign * (d.gross if d.side == "sale" else -d.gross)


def open_docs(docs: Iterable[Doc], ledger: Ledger) -> list[Doc]:
    """Documents still waiting for payment: on account, not undone, no matched bank line."""
    gone, paid = reversed_ids(ledger.events), payments(ledger.bank_lines)
    return [d for d in docs if d.sign > 0 and d.on_account and d.event.id not in gone and d.event.id not in paid]


class StatementLine(BaseModel):
    date: date
    details: str
    reference: str | None = None
    event_id: str | None = None
    amount_pence: int = 0  # the document
    paid_pence: int = 0  # money that settled it, opposite sign
    balance_pence: int = 0


class Statement(BaseModel):
    contact: Contact
    start: date | None
    end: date | None
    opening_balance_pence: int
    closing_balance_pence: int
    lines: list[StatementLine]


_DETAILS = {"sale": "Sales invoice", "purchase": "Purchase"}


def _statement_lines(docs: Sequence[Doc], ledger: Ledger) -> list[StatementLine]:
    """Unsorted lines, balances not yet filled in."""
    paid = payments(ledger.bank_lines)
    out: list[StatementLine] = []
    for d in docs:
        amount = _signed(d)
        label = _DETAILS[d.side] + ("" if d.on_account else ", paid at the time")
        if d.sign < 0:
            label = f"Undo: {label[0].lower()}{label[1:]}"
        out.append(
            StatementLine(
                date=d.event.date,
                details=label,
                reference=d.reference,
                event_id=d.event.id,
                amount_pence=amount,
                paid_pence=0 if d.on_account else -amount,
            )
        )
        if d.on_account and d.sign > 0 and (ln := paid.get(d.event.id)):
            out.append(
                StatementLine(
                    date=ln.date,
                    details=f"Bank: {ln.description}",
                    reference=ln.reference,
                    event_id=d.event.id,
                    paid_pence=-amount,
                )
            )
    return out


def statement(
    contact: Contact, docs: Sequence[Doc], ledger: Ledger, start: date | None = None, end: date | None = None
) -> Statement:
    lines = sorted(
        _statement_lines(docs, ledger), key=lambda ln: (ln.date, ln.paid_pence != 0 and ln.amount_pence == 0)
    )
    opening = sum(ln.amount_pence + ln.paid_pence for ln in lines if start and ln.date < start)
    shown = [ln for ln in lines if (not start or ln.date >= start) and (not end or ln.date <= end)]
    balance = opening
    for ln in shown:
        balance += ln.amount_pence + ln.paid_pence
        ln.balance_pence = balance
    return Statement(
        contact=contact, start=start, end=end, opening_balance_pence=opening, closing_balance_pence=balance, lines=shown
    )


class ContactTotals(BaseModel):
    documents: int = 0
    ytd_sales_net_pence: int = 0
    ytd_sales_vat_pence: int = 0
    ytd_purchases_net_pence: int = 0
    ytd_purchases_vat_pence: int = 0
    open_receivable_pence: int = 0  # unpaid sales invoices
    open_payable_pence: int = 0  # unpaid purchases on account
    balance_pence: int = 0  # receivable - payable
    last_activity: date | None = None


def totals(docs: Sequence[Doc], ledger: Ledger, year_start: date, today: date) -> ContactTotals:
    t = ContactTotals(documents=sum(d.sign for d in docs))
    for d in docs:
        if year_start <= d.event.date <= today:
            net = d.event.net if d.event.net is not None else d.gross - (d.event.vat or 0)
            vat = d.event.vat or 0
            if d.side == "sale":
                t.ytd_sales_net_pence += d.sign * net
                t.ytd_sales_vat_pence += d.sign * vat
            else:
                t.ytd_purchases_net_pence += d.sign * net
                t.ytd_purchases_vat_pence += d.sign * vat
        t.last_activity = max(t.last_activity or d.event.date, d.event.date)
    for d in open_docs(docs, ledger):
        if d.side == "sale":
            t.open_receivable_pence += d.gross
        else:
            t.open_payable_pence += d.gross
    t.balance_pence = t.open_receivable_pence - t.open_payable_pence
    return t


def bucket(age_days: int) -> str:
    return "0-30" if age_days <= 30 else "31-60" if age_days <= 60 else "61-90" if age_days <= 90 else "90+"


class AgedDoc(BaseModel):
    event_id: str
    date: date
    reference: str | None
    amount_pence: int
    age_days: int
    bucket: str


class AgedRow(BaseModel):
    contact_id: str
    name: str
    buckets: dict[str, int]  # "0-30" | "31-60" | "61-90" | "90+" -> pence
    total_pence: int
    documents: list[AgedDoc]


class AgedTable(BaseModel):
    rows: list[AgedRow]
    buckets: dict[str, int]
    total_pence: int


class AgedBalances(BaseModel):
    as_of: date
    debtors: AgedTable  # customers who owe the user (unpaid sales invoices)
    creditors: AgedTable  # suppliers the user owes (unpaid purchases on account)


def aged(contacts: Sequence[Contact], ledger: Ledger, as_of: date) -> AgedBalances:
    """Unpaid documents by age from their date (no due dates are recorded): 0-30, 31-60, 61-90, 90+ days."""
    names = {c.id: c.name for c in contacts}
    tables: dict[Side, dict[str, AgedRow]] = {"sale": {}, "purchase": {}}
    for cid, docs in assign(contacts, documents(ledger)).items():
        for d in open_docs(docs, ledger):
            if d.event.date > as_of:
                continue
            age = (as_of - d.event.date).days
            row = tables[d.side].setdefault(
                cid,
                AgedRow(
                    contact_id=cid, name=names[cid], buckets=dict.fromkeys(BUCKETS, 0), total_pence=0, documents=[]
                ),
            )
            row.buckets[bucket(age)] += d.gross
            row.total_pence += d.gross
            row.documents.append(
                AgedDoc(
                    event_id=d.event.id,
                    date=d.event.date,
                    reference=d.reference,
                    amount_pence=d.gross,
                    age_days=age,
                    bucket=bucket(age),
                )
            )

    def table(rows: dict[str, AgedRow]) -> AgedTable:
        ordered = sorted(rows.values(), key=lambda r: (-r.total_pence, r.name.lower()))
        return AgedTable(
            rows=ordered,
            buckets={b: sum(r.buckets[b] for r in ordered) for b in BUCKETS},
            total_pence=sum(r.total_pence for r in ordered),
        )

    return AgedBalances(as_of=as_of, debtors=table(tables["sale"]), creditors=table(tables["purchase"]))


class ContactRow(Contact):
    totals: ContactTotals


def with_totals(contacts: Sequence[Contact], ledger: Ledger, year_start: date, today: date) -> list[ContactRow]:
    by_contact = assign(contacts, documents(ledger))
    return [
        ContactRow(**c.model_dump(), totals=totals(by_contact.get(c.id, []), ledger, year_start, today))
        for c in contacts
    ]


# --------------------------------------------------------------------------- #
# Storage and the user's actions
# --------------------------------------------------------------------------- #


async def save_contacts(books: Books, contacts: Sequence[Contact]) -> None:
    payload = [c.model_dump(mode="json") for c in sorted(contacts, key=lambda c: c.name.lower())]
    await books._update_json(CONTACTS, [], lambda _old: payload)


async def stored_contacts(books: Books) -> list[Contact]:
    """contacts.json as saved, without the ledger (cheap: one file). Raises ValueError when it is malformed."""
    return [Contact.model_validate(c) for c in await books.read_json(CONTACTS, None) or []]


async def contact_book(books: Books, ledger: Ledger | None = None) -> tuple[list[Contact], Ledger, bool]:
    """(stored contacts merged with the ledger, the ledger, whether contacts.json exists). Writes nothing."""
    ledger = ledger or await load_ledger(books)
    stored = await books.read_json(CONTACTS, None)
    contacts = [Contact.model_validate(c) for c in stored or []]
    return merge_ledger(contacts, ledger), ledger, stored is not None


async def refresh(books: Books, user: str | None = None) -> tuple[list[Contact], Ledger]:
    contacts, ledger, _ = await contact_book(books)
    await save_contacts(books, contacts)
    await books.audit(f"user:{user}" if user else "agent:contacts", "contacts_refreshed", {"contacts": len(contacts)})
    return contacts, ledger


class ContactEditError(ValueError):
    """The edit is not valid (empty name, unknown category, ...)."""


def apply_edit(c: Contact, edits: dict[str, Any], others: Sequence[Contact], at: datetime | None = None) -> Contact:
    """Apply the user's changes to `c` (in place) and remember which fields they own."""
    unknown = set(edits) - set(EDITABLE)
    if unknown:
        raise ContactEditError(f"Can't edit {', '.join(sorted(unknown))}")
    clean: dict[str, Any] = {}
    for k, v in edits.items():
        v = v.strip() or None if isinstance(v, str) else v
        if k == "name":
            if not v or not supplier_key(v):
                raise ContactEditError("Name can't be empty")
            key = supplier_key(v)
            if any(o.id != c.id and (key == o.normalised_key or key in o.aliases) for o in others):
                raise ContactEditError(f"Another contact is already called {v}")
        elif k == "kind" and v not in ("customer", "supplier", "both"):
            raise ContactEditError("Kind must be customer, supplier or both")
        elif k == "vrn":
            v = normalise_vat_number(v)
            if v and not re.fullmatch(r"(GB|XI)(\d{9}|\d{12}|GD\d{3}|HA\d{3})", v):
                raise ContactEditError(f"{v} doesn't look like a UK VAT number")
            if v and any(o.vrn == v and o.id != c.id for o in others):
                raise ContactEditError(f"Another contact already has VAT number {v}")
        elif k == "email" and v and not EMAIL_RE.fullmatch(v):
            raise ContactEditError(f"{v} doesn't look like an email address")
        elif k == "default_category" and v and v not in CATEGORIES:
            raise ContactEditError(f"Unknown category {v!r}")
        elif k == "default_vat_code" and v and v not in {code.value for code in VatCode}:
            raise ContactEditError(f"Unknown VAT code {v!r}")
        elif k == "vat_status":
            v = v or "unknown"
            if v not in VAT_STATUSES:
                raise ContactEditError("VAT status must be registered, not_registered or unknown")
        clean[k] = v
    if "name" in clean and (key := supplier_key(clean["name"])) != c.normalised_key:
        if c.normalised_key not in c.aliases:
            c.aliases.append(c.normalised_key)
        c.aliases = [a for a in c.aliases if a != key]
        c.normalised_key = key
    for k, v in clean.items():
        setattr(c, k, v)
        if k not in c.edited:
            c.edited.append(k)
    c.updated_at = at or now()
    return c


async def edit(books: Books, cid: str, edits: dict[str, Any], user: str) -> Contact:
    """Raises FileNotFoundError for an unknown id, ContactEditError for a bad edit."""
    contacts, _, _ = await contact_book(books)
    c = next((c for c in contacts if c.id == cid), None) if ID_RE.fullmatch(cid) else None
    if c is None:
        raise FileNotFoundError(cid)
    apply_edit(c, edits, contacts)
    await save_contacts(books, contacts)
    await books.audit(f"user:{user}", "contact_edited", {"contact": cid, "fields": sorted(edits)})
    return c


# --------------------------------------------------------------------------- #
# What the books know about a supplier's VAT registration
# --------------------------------------------------------------------------- #


def supplier_knowledge(contacts: Iterable[Contact], doc: ExtractedDoc) -> SupplierKnowledge:
    """The contact behind the document's supplier (by VAT number, normalised name or alias), as the VAT check needs it.
    A contact with a VAT number on file and no status yet counts as registered."""
    if doc.doc_type == "sales_invoice":
        return UNKNOWN_SUPPLIER
    c = find(contacts, supplier_key(doc.supplier_name), normalise_vat_number(doc.supplier_vat_number))
    if c is None:
        return UNKNOWN_SUPPLIER
    status: VatStatus = c.vat_status if c.vat_status != "unknown" else "registered" if c.vrn else "unknown"
    return SupplierKnowledge(vat_status=status, vrn=c.vrn)


def learnt_vat_status(doc: ExtractedDoc, not_registered_tick: bool) -> VatStatus | None:
    """What approving `doc` teaches about its supplier: a VAT number means registered; the "isn't VAT-registered"
    tick on a zero-VAT receipt with no VAT number means not registered; anything else teaches nothing."""
    if doc.doc_type == "sales_invoice" or not supplier_key(doc.supplier_name):
        return None
    if normalise_vat_number(doc.supplier_vat_number):
        return "registered"
    if not_registered_tick and doc.vat_total <= 0:
        return "not_registered"
    return None


def remember_vat_status(
    contacts: Sequence[Contact], name: str, status: VatStatus, vrn: str | None = None, at: datetime | None = None
) -> tuple[list[Contact], Contact, bool]:
    """(the book, the supplier's contact, whether anything changed). The contact is created when the book has
    no-one by that name or VAT number yet, with the id a later ledger refresh would give it."""
    at = at or now()
    book = [c.model_copy(deep=True) for c in contacts]
    key = supplier_key(name)
    c = find(book, key, vrn)
    created = c is None
    if c is None:
        c = Contact(
            id=contact_id(key, vrn),
            kind="supplier",
            name=name.strip(),
            normalised_key=key,
            created_at=at,
            updated_at=at,
        )
        book.append(c)
    before = (c.vat_status, c.vrn)
    c.vat_status = status
    if vrn and not c.vrn and "vrn" not in c.edited:
        c.vrn = vrn
    changed = created or (c.vat_status, c.vrn) != before
    if changed:
        c.updated_at = at
    return sorted(book, key=lambda x: x.name.lower()), c, changed


async def set_vat_status(
    books: Books, name: str, status: VatStatus, actor: str, vrn: str | None = None
) -> Contact | None:
    """Record a supplier's VAT status in contacts.json: one read and, only if it changes, one write (the ledger is
    not loaded). Returns the contact when it changed."""
    if not remember_vat_status(await stored_contacts(books), name, status, vrn)[2]:
        return None
    changed: list[Contact] = []

    def update(old: list[dict[str, Any]]) -> list[dict[str, Any]]:  # again on what is stored now
        book, c, _ = remember_vat_status([Contact.model_validate(x) for x in old or []], name, status, vrn)
        changed.append(c)
        return [x.model_dump(mode="json") for x in book]

    await books._update_json(CONTACTS, [], update)
    await books.audit(actor, "contact_vat_status", {"contact": changed[0].id, "vat_status": status})
    return changed[0]


async def learn_from_approval(
    books: Books, p: Proposal, actor: str, not_registered_tick: bool = False
) -> Contact | None:
    status = learnt_vat_status(p.extracted, not_registered_tick)
    if status is None:
        return None
    return await set_vat_status(
        books, p.extracted.supplier_name, status, actor, normalise_vat_number(p.extracted.supplier_vat_number)
    )


async def forget_from_undo(books: Books, p: Proposal, actor: str) -> Contact | None:
    """Undoing an approval takes back what the user's "isn't VAT-registered" tick taught (a VAT number seen on the
    receipt stays learnt: the number is evidence on its own). Returns the contact when it changed."""
    doc = p.extracted
    if (
        doc.doc_type == "sales_invoice"
        or not supplier_key(doc.supplier_name)
        or normalise_vat_number(doc.supplier_vat_number)
    ):
        return None
    try:
        c = find(await stored_contacts(books), supplier_key(doc.supplier_name), None)
    except ValueError:
        return None
    if c is None or c.vat_status != "not_registered":
        return None
    return await set_vat_status(books, doc.supplier_name, "unknown", actor)


class ImportResult(BaseModel):
    read: int
    matched: int  # address-book entries that are already contacts
    updated: int  # of those, how many gained an email or phone
    added: int
    skipped: int  # not in the books (and not added), or no usable name


def _names(entry: AddressBookContact) -> list[str]:
    return [n for n in (entry.company_name, entry.display_name) if n and supplier_key(n)]


def import_address_book(
    contacts: Sequence[Contact], entries: Sequence[AddressBookContact], add_new: bool, at: datetime | None = None
) -> tuple[list[Contact], ImportResult]:
    """Fill blank emails and phones of contacts the address book knows (by company name, then display name);
    with `add_new`, add the rest as customers (source "outlook"). Never overwrites anything already set."""
    at = at or now()
    book = [c.model_copy(deep=True) for c in contacts]
    matched = updated = added = skipped = 0
    for entry in entries:
        names = _names(entry)
        if not names:
            skipped += 1
            continue
        email = entry.emails[0] if entry.emails else None
        phone = entry.business_phones[0] if entry.business_phones else None
        c = next((hit for n in names if (hit := find(book, supplier_key(n), None))), None)
        if c is None:
            if not add_new:
                skipped += 1
                continue
            key = supplier_key(names[0])
            book.append(
                Contact(
                    id=contact_id(key, None),
                    kind="customer",
                    name=names[0],
                    normalised_key=key,
                    email=email,
                    phone=phone,
                    source="outlook",
                    created_at=at,
                    updated_at=at,
                )
            )
            added += 1
            continue
        matched += 1
        changed = False
        for k, v in (("email", email), ("phone", phone)):
            if v and not getattr(c, k):
                setattr(c, k, v)
                changed = True
        if changed:
            c.updated_at = at
            updated += 1
    result = ImportResult(read=len(entries), matched=matched, updated=updated, added=added, skipped=skipped)
    return sorted(book, key=lambda c: c.name.lower()), result


async def import_outlook(books: Books, entries: Sequence[AddressBookContact], add_new: bool, user: str) -> ImportResult:
    contacts, _, _ = await contact_book(books)
    merged, result = import_address_book(contacts, entries, add_new)
    await save_contacts(books, merged)
    await books.audit(f"user:{user}", "contacts_imported", {"source": "outlook", **result.model_dump()})
    return result
