"""Import contacts, all or a chosen few, from three places: Outlook contacts, the people the user emails, and the
phone's address book (the app sends those; the runtime never reads a phone).

    GET  /contacts/import/outlook   the user's Outlook (Microsoft 365) contacts, each marked if already in the books
    GET  /contacts/import/email     people who emailed the user lately (senders in the inbox), newsletters left out
    POST /contacts/import/check     the same marking for a list the client sends (the phone's address book)
    POST /contacts/import           save the chosen rows; ones already in the books are skipped (blanks filled in)

Read-only on every source: nothing is written to Outlook, the mailbox or the phone. Saving is idempotent: a second
import of the same rows adds nothing. Audit: `contacts_imported` with the source and the counts.

A row is "already in your books" when its name (company first), email or phone matches a contact: the name through
the same key the books use everywhere (app/autopilot.supplier_key), the email case-insensitively, the phone by its
digits (a leading 0 and +44 count as the same).
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from accnomos_connectors.base import AddressBookContact, MailMessage
from app import contacts as cb
from app.autopilot import supplier_key
from app.books import Books, now

Source = Literal["outlook", "email", "phone"]
MAX_ROWS = 500
EMAIL_DAYS = 180
EMAIL_SCAN = 300

#: Senders that are not people or businesses the user deals with: newsletters, notifications, bounces.
NOT_A_PERSON = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|newsletter|news|notifications?|notify|alerts?|mailer-daemon|postmaster|"
    r"marketing|promotions?|offers|updates|digest|bounce[s]?)([-_.+].*)?@",
    re.IGNORECASE,
)
SOURCE_NOTES = {
    "outlook": "From your Outlook contacts. Nothing is written back to Outlook.",
    "email": f"People who emailed you in the last {EMAIL_DAYS} days. Newsletters and no-reply senders are left out; "
    "nothing in your mailbox changes.",
    "phone": "From this phone's address book. Nothing is written back to the phone.",
}


class Candidate(BaseModel):
    ref: str  # a stable id for the row within this source
    source: Source
    name: str  # what the contact will be called: the company when there is one, else the person
    person: str | None = None  # the person's name when `name` is their company
    email: str | None = None
    phone: str | None = None
    messages: int | None = None  # email source: how many messages came from this address
    existing_id: str | None = None  # already in the books as this contact
    existing_name: str | None = None
    match: str | None = None  # why it counts as already there: "same name", "same email", "same phone"
    kind: cb.ContactKind = "customer"  # the suggested kind (an existing contact's own kind)


class Preview(BaseModel):
    source: Source
    note: str
    candidates: list[Candidate]
    new: int  # rows not in the books yet
    existing: int


class Row(BaseModel):
    """One row the user chose to import."""

    name: str
    person: str | None = None
    email: str | None = None
    phone: str | None = None
    kind: cb.ContactKind = "customer"


class Summary(BaseModel):
    source: Source
    requested: int
    added: int
    already: int  # already in the books (skipped; blank details filled in where the row had them)
    filled: int  # of those, how many gained an email or phone
    invalid: int  # no usable name, or an email that is not an email address
    added_names: list[str]
    already_names: list[str]
    message: str


def phone_digits(phone: str | None) -> str:
    d = re.sub(r"\D", "", phone or "")
    if d.startswith("44") and len(d) > 10:
        d = "0" + d[2:]
    return d if len(d) >= 7 else ""


def _ref(source: str, *parts: str | None) -> str:
    return hashlib.sha256("|".join([source, *(p or "" for p in parts)]).encode()).hexdigest()[:12]


class _Index:
    """The books' contacts by name key, email and phone digits."""

    def __init__(self, contacts: Iterable[cb.Contact]) -> None:
        self.contacts = list(contacts)
        self.email: dict[str, cb.Contact] = {}
        self.phone: dict[str, cb.Contact] = {}
        for c in self.contacts:
            if c.email:
                self.email.setdefault(c.email.strip().lower(), c)
            if d := phone_digits(c.phone):
                self.phone.setdefault(d, c)

    def match(self, names: Sequence[str | None], email: str | None, phone: str | None) -> tuple[cb.Contact, str] | None:
        for n in names:
            if n and (key := supplier_key(n)) and (hit := cb.find(self.contacts, key, None)):
                return hit, "same name"
        if email and (hit := self.email.get(email.strip().lower())):
            return hit, "same email"
        if (d := phone_digits(phone)) and (hit := self.phone.get(d)):
            return hit, "same phone"
        return None

    def add(self, c: cb.Contact) -> None:
        self.contacts.append(c)
        if c.email:
            self.email.setdefault(c.email.strip().lower(), c)
        if d := phone_digits(c.phone):
            self.phone.setdefault(d, c)


def _mark(cands: list[Candidate], index: _Index) -> Preview:
    source = cands[0].source if cands else "outlook"
    for c in cands:
        hit = index.match([c.name, c.person], c.email, c.phone)
        if hit:
            c.existing_id, c.existing_name, c.match, c.kind = hit[0].id, hit[0].name, hit[1], hit[0].kind
    cands.sort(key=lambda c: (c.existing_id is not None, c.name.lower()))
    existing = sum(1 for c in cands if c.existing_id)
    return Preview(source=source, note="", candidates=cands, new=len(cands) - existing, existing=existing)


def _with_note(p: Preview, source: Source) -> Preview:
    p.source, p.note = source, SOURCE_NOTES[source]
    return p


# --------------------------------------------------------------------------- #
# Reading each source
# --------------------------------------------------------------------------- #


def from_address_book(entries: Sequence[AddressBookContact]) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    for e in entries:
        person = (e.display_name or "").strip() or None
        company = (e.company_name or "").strip() or None
        name = company or person
        if not name or not supplier_key(name):
            continue
        email = e.emails[0].strip() if e.emails else None
        phone = e.business_phones[0].strip() if e.business_phones else None
        ref = _ref("outlook", e.id or name, email)
        if ref in seen:
            continue
        seen.add(ref)
        out.append(
            Candidate(
                ref=ref,
                source="outlook",
                name=name,
                person=person if company and person and person != company else None,
                email=email,
                phone=phone,
            )
        )
    return out


def from_messages(messages: Sequence[MailMessage], own: Iterable[str] = ()) -> list[Candidate]:
    """One row per sender address, most messages first; the user's own addresses and robots left out."""
    mine = {a.strip().lower() for a in own if a}
    by: dict[str, tuple[str, int]] = {}
    for m in messages:
        addr = (m.from_address or "").strip().lower()
        if not addr or "@" not in addr or addr in mine or NOT_A_PERSON.match(addr):
            continue
        name, n = by.get(addr, ((m.from_name or "").strip(), 0))
        by[addr] = (name or (m.from_name or "").strip(), n + 1)
    out = []
    for addr, (name, n) in sorted(by.items(), key=lambda kv: (-kv[1][1], kv[0])):
        label = name if name and supplier_key(name) else addr.split("@", 1)[0]
        out.append(Candidate(ref=_ref("email", addr), source="email", name=label, email=addr, messages=n))
    return out


def from_rows(rows: Sequence[Row], source: Source = "phone") -> list[Candidate]:
    out = []
    for r in rows:
        name = " ".join((r.name or "").split())
        if not name or not supplier_key(name):
            continue
        out.append(
            Candidate(
                ref=_ref(source, name, r.email, r.phone),
                source=source,
                name=name,
                person=(r.person or "").strip() or None,
                email=(r.email or "").strip() or None,
                phone=(r.phone or "").strip() or None,
                kind=r.kind,
            )
        )
    return out


async def recent_senders(mail: Any, today: datetime | None = None) -> list[MailMessage]:
    since = (today or datetime.now(UTC)) - timedelta(days=EMAIL_DAYS)
    msgs: list[MailMessage] = []
    with contextlib.suppress(NotImplementedError):
        msgs = list(await mail.list_recent(since, EMAIL_SCAN))
    with contextlib.suppress(NotImplementedError):  # messages with attachments sit in other folders too (bills)
        msgs += list(await mail.list_messages(since, EMAIL_SCAN, folder="all"))
    unique = {m.id: m for m in msgs}
    return list(unique.values())


async def preview(books: Books, cands: list[Candidate], source: Source) -> Preview:
    contacts, _ledger, _saved = await cb.contact_book(books)
    return _with_note(_mark(cands, _Index(contacts)), source)


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #


def merge_rows(
    contacts: Sequence[cb.Contact], rows: Sequence[Row], source: Source, at: datetime | None = None
) -> tuple[list[cb.Contact], Summary]:
    """Add the rows that are not in the books yet; fill a blank email/phone of the ones that are. Never overwrites."""
    at = at or now()
    book = [c.model_copy(deep=True) for c in contacts]
    index = _Index(book)
    added: list[str] = []
    already: list[str] = []
    filled = invalid = 0
    for r in rows:
        name = " ".join((r.name or "").split())
        key = supplier_key(name) if name else ""
        email = (r.email or "").strip() or None
        phone = (r.phone or "").strip() or None
        if not key or (email and not cb.EMAIL_RE.fullmatch(email)):
            invalid += 1
            continue
        if r.kind not in ("customer", "supplier", "both"):
            invalid += 1
            continue
        hit = index.match([name, r.person], email, phone)
        if hit:
            c = hit[0]
            already.append(c.name)
            changed = False
            for k, v in (("email", email), ("phone", phone)):
                if v and not getattr(c, k):
                    setattr(c, k, v)
                    changed = True
            if changed:
                c.updated_at = at
                filled += 1
            continue
        c = cb.Contact(
            id=cb.contact_id(key, None),
            kind=r.kind,
            name=name,
            normalised_key=key,
            email=email,
            phone=phone,
            source="outlook" if source == "outlook" else "phone" if source == "phone" else "import",
            created_at=at,
            updated_at=at,
        )
        book.append(c)
        index.add(c)
        added.append(name)
    msg = f"Imported {len(added)}"
    if already:
        msg += f", skipped {len(already)} already in your books"
    if invalid:
        msg += f", {invalid} without a usable name or email"
    msg += "."
    summary = Summary(
        source=source,
        requested=len(rows),
        added=len(added),
        already=len(already),
        filled=filled,
        invalid=invalid,
        added_names=added,
        already_names=already,
        message=msg,
    )
    return sorted(book, key=lambda c: c.name.lower()), summary


async def save(books: Books, rows: Sequence[Row], source: Source, user: str) -> Summary:
    ledger = await cb.load_ledger(books)
    out: list[Summary] = []

    def change(raw: Any) -> Any:
        merged, summary = merge_rows(cb.merge_ledger(cb._parse_stored(raw), ledger), rows, source)  # noqa: SLF001
        out.append(summary)
        return cb._dump(merged)  # noqa: SLF001

    await books._update_json(cb.CONTACTS, [], change)  # noqa: SLF001 - the contacts file's own writer
    s = out[-1]
    await books.audit(
        f"user:{user}",
        "contacts_imported",
        {"source": source, "requested": s.requested, "added": s.added, "already": s.already, "filled": s.filled},
    )
    return s
