"""Sales invoices: written by the user, numbered and priced by code, sent from their own Outlook, chased, paid.

Files, all in the user's folder:

    03 Sales/invoices/INV-0001.json       the invoice (money in integer pence)
    03 Sales/invoices/INV-0001.pdf        the latest render
    03 Sales/invoices/sent/INV-0001.pdf   the exact PDF that was emailed
    _System/Invoicing/sequence.json       {"prefix": "INV-", "next": 2}
    _System/Invoicing/profile.json        the business as its invoices show it (name, address, VRN, bank, logo, terms)

Money is code's job. A line's net is quantity × unit price and its VAT is the net at the line's VAT code, each
rounded half up to the penny; the VAT summary and the totals are sums of lines. Totals a client sends are ignored.

Statuses: draft -> sent -> paid, and draft or sent -> void. Only a draft can be edited. Becoming `sent` posts the
sale (Dr 1100 Debtors gross, Cr 4000 Sales net per VAT code, Cr 2200 VAT control) with an id derived from the
invoice number, so it can never post twice. Voiding a sent invoice appends a reversal; nothing is deleted.
Paid posts nothing, like matching a bank line (app/books.py): it records that the debt is settled, and links
the bank line when one is chosen.

An invoice written from a job's hours keeps the job id and, per line, the timesheet entries it bills. Becoming
`sent` marks those entries invoiced on its number (app/jobs.py), so they are never proposed again.

Sending and chasing need the user's explicit confirmation in the app (`confirm: true`); nothing is sent on its own.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from accnomos_connectors.base import MailSender, OutgoingAttachment, OutgoingMail
from accnomos_ledger.bank import BankLine
from accnomos_ledger.events import LedgerEvent, Line, VatCode
from pydantic import BaseModel, Field, field_validator

from app import jobs
from app.approve import reversal_of
from app.books import SYSTEM, BankMatchError, Books, now
from app.checks import normalise_vat_number
from app.journal import DEBTORS, SALES, VAT_CONTROL

INVOICES = "03 Sales/invoices"
SENT = f"{INVOICES}/sent"
INVOICING = f"{SYSTEM}/Invoicing"
SEQUENCE = f"{INVOICING}/sequence.json"
PROFILE = f"{INVOICING}/profile.json"
CONTACTS = f"{SYSTEM}/Contacts/contacts.json"  # app/contacts.py (claude/contacts) owns this file; read-only here

InvoiceStatus = Literal["draft", "sent", "paid", "void"]
SalesVatCode = Literal["S", "R", "Z", "E", "O"]
RATES: dict[str, int] = {"S": 20, "R": 5, "Z": 0, "E": 0, "O": 0}
VAT_LABELS = {"S": "Standard 20%", "R": "Reduced 5%", "Z": "Zero rated", "E": "Exempt", "O": "Outside the scope of VAT"}
ON_RETURN = {"S", "R", "Z", "E"}  # O stays off the VAT return, so it is left out of the event's VAT-able net
ID_RE = re.compile(r"[A-Z0-9][A-Z0-9-]{0,23}")
PREFIX_RE = re.compile(r"[A-Z0-9-]{0,10}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
DEFAULT_SEQUENCE = {"prefix": "INV-", "next": 1}


class InvoiceError(ValueError):
    """The invoice cannot be saved, sent or changed as asked."""


class InvoiceStateError(InvoiceError):
    """The invoice's status does not allow this (e.g. editing a sent invoice)."""


def pence(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(p: int) -> str:
    """'£1,234.50' from pence, exactly (no floats)."""
    sign = "-" if p < 0 else ""
    pounds, pennies = divmod(abs(p), 100)
    return f"{sign}£{pounds:,}.{pennies:02d}"


def uk_date(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


# --------------------------------------------------------------------------- #
# Business profile
# --------------------------------------------------------------------------- #


class BankDetails(BaseModel):
    account_name: str = ""
    sort_code: str = ""  # stored as 12-34-56
    account_number: str = ""  # 8 digits
    iban: str | None = None

    @field_validator("sort_code")
    @classmethod
    def _sort_code(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if not digits:
            return ""
        if len(digits) != 6:
            raise ValueError("Sort code has 6 digits, e.g. 12-34-56")
        return f"{digits[:2]}-{digits[2:4]}-{digits[4:]}"

    @field_validator("account_number")
    @classmethod
    def _account_number(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if digits and len(digits) != 8:
            raise ValueError("Account number has 8 digits")
        return digits

    def is_set(self) -> bool:
        return bool(self.sort_code and self.account_number) or bool(self.iban)


class InvoiceProfile(BaseModel):
    """The business as its invoices show it. Stored in _System/Invoicing/profile.json."""

    name: str = ""
    address: str = ""  # several lines
    email: str | None = None
    phone: str | None = None
    vrn: str | None = None  # VAT registration number; without it an invoice cannot charge VAT
    company_number: str | None = None
    bank: BankDetails = Field(default_factory=BankDetails)
    logo_path: str | None = None  # relative to the books root, e.g. _System/Invoicing/logo.png
    terms_days: int = Field(30, ge=0, le=120)
    footer_note: str | None = None

    @field_validator("vrn")
    @classmethod
    def _vrn(cls, v: str | None) -> str | None:
        n = normalise_vat_number(v)
        if n and not re.fullmatch(r"GB(\d{9}|\d{12}|GD\d{3}|HA\d{3})", n):
            raise ValueError("Check the VAT number, e.g. GB 123 4567 89")
        return n

    @field_validator("email", "phone", "company_number", "footer_note")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


async def load_profile(books: Books) -> InvoiceProfile:
    return InvoiceProfile.model_validate(await books.read_json(PROFILE, {}))


async def save_profile(books: Books, profile: InvoiceProfile, user: str) -> InvoiceProfile:
    if profile.logo_path and not profile.logo_path.startswith(f"{INVOICING}/"):
        raise InvoiceError(f"The logo must be a file in {INVOICING}")
    payload = profile.model_dump(mode="json")
    await books._update_json(PROFILE, {}, lambda _old: payload)
    await books.audit(f"user:{user}", "invoice_profile_saved", {"path": PROFILE})
    return profile


# --------------------------------------------------------------------------- #
# Invoices
# --------------------------------------------------------------------------- #


class InvoiceCustomer(BaseModel):
    contact_id: str | None = None  # an id in _System/Contacts/contacts.json, when picked from the contact book
    name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    address: str | None = None
    vrn: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and not EMAIL_RE.fullmatch(v):
            raise ValueError(f"{v!r} is not an email address")
        return v or None


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    quantity: Decimal = Field(gt=0, le=1_000_000, decimal_places=3)
    unit: str | None = Field(None, max_length=20)  # "hours", "days", "each"
    unit_price_pence: int = Field(ge=-100_000_000, le=100_000_000)  # negative for a discount line
    vat_code: SalesVatCode = "S"
    timesheet_entry_ids: list[str] = Field(default_factory=list, max_length=1000)  # hours this line bills (jobs)


class InvoiceLine(LineIn):
    vat_rate: int
    net_pence: int
    vat_pence: int


class VatSummaryRow(BaseModel):
    vat_code: SalesVatCode
    vat_rate: int
    net_pence: int
    vat_pence: int


class InvoiceDraft(BaseModel):
    """What the user writes. Numbers, line totals and VAT are worked out by code."""

    customer: InvoiceCustomer
    issue_date: date | None = None  # default: today
    due_date: date | None = None  # default: issue date + the profile's terms
    lines: list[LineIn] = Field(min_length=1, max_length=100)
    reference: str | None = Field(None, max_length=60)  # the customer's PO or job number
    notes: str | None = Field(None, max_length=1000)
    job_id: str | None = Field(None, max_length=12)  # set when the lines came from a job's hours


class Reminder(BaseModel):
    sent_at: datetime
    sent_by: str
    to: str
    subject: str


class Invoice(BaseModel):
    number: str
    status: InvoiceStatus = "draft"
    customer: InvoiceCustomer
    issue_date: date
    due_date: date
    lines: list[InvoiceLine]
    vat_summary: list[VatSummaryRow]
    net_pence: int
    vat_pence: int
    total_pence: int
    reference: str | None = None
    notes: str | None = None
    created_by: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    sent_at: datetime | None = None
    sent_to: str | None = None
    sent_by: str | None = None
    pdf_sha256: str | None = None  # of the PDF that was emailed (also the ledger event's evidence)
    event_id: str | None = None  # the sale in the ledger
    paid_at: date | None = None
    payment_ref: str | None = None
    bank_line_id: str | None = None
    voided_at: datetime | None = None
    void_reason: str | None = None
    reversal_event_id: str | None = None
    reminders: list[Reminder] = []
    job_id: str | None = None
    timesheets_marked: bool = False  # the lines' timesheet entries were marked invoiced on this number when sent

    def timesheet_entry_ids(self) -> list[str]:
        return [i for ln in self.lines for i in ln.timesheet_entry_ids]

    def overdue_days(self, today: date) -> int | None:
        """Days past the due date while unpaid (0 or less: not due yet); None when not awaiting payment."""
        return (today - self.due_date).days if self.status == "sent" else None


def price_lines(lines: list[LineIn]) -> tuple[list[InvoiceLine], list[VatSummaryRow], int, int]:
    """(priced lines, VAT summary by code, net, VAT), all in pence. VAT is rounded per line."""
    out: list[InvoiceLine] = []
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for ln in lines:
        rate = RATES[ln.vat_code]
        net = pence(ln.quantity * ln.unit_price_pence)
        vat = pence(Decimal(net) * rate / 100)
        out.append(InvoiceLine(**ln.model_dump(), vat_rate=rate, net_pence=net, vat_pence=vat))
        groups[ln.vat_code][0] += net
        groups[ln.vat_code][1] += vat
    order = list(RATES)
    summary = [
        VatSummaryRow(vat_code=code, vat_rate=RATES[code], net_pence=n, vat_pence=v)  # type: ignore[arg-type]
        for code, (n, v) in sorted(groups.items(), key=lambda kv: order.index(kv[0]))
    ]
    return out, summary, sum(ln.net_pence for ln in out), sum(ln.vat_pence for ln in out)


def build_invoice(number: str, draft: InvoiceDraft, profile: InvoiceProfile, user: str, today: date | None = None) -> Invoice:
    issue = draft.issue_date or today or now().date()
    due = draft.due_date or issue + timedelta(days=profile.terms_days)
    if due < issue:
        raise InvoiceError("The due date is before the invoice date")
    lines, summary, net, vat = price_lines(draft.lines)
    return Invoice(
        number=number, customer=draft.customer, issue_date=issue, due_date=due, lines=lines, vat_summary=summary,
        net_pence=net, vat_pence=vat, total_pence=net + vat, reference=(draft.reference or "").strip() or None,
        notes=(draft.notes or "").strip() or None, created_by=user, job_id=draft.job_id,
    )


def _path(number: str) -> str:
    if not ID_RE.fullmatch(number):
        raise FileNotFoundError(number)
    return f"{INVOICES}/{number}.json"


async def get_invoice(books: Books, number: str) -> Invoice:
    """Raises FileNotFoundError, also for ids that could step outside the invoices folder."""
    return Invoice.model_validate_json(await books.storage.read(_path(number)))


async def save_invoice(books: Books, inv: Invoice) -> None:
    inv.updated_at = now()
    await books.write_json(_path(inv.number), inv.model_dump(mode="json"))


async def list_invoices(books: Books, status: InvoiceStatus | None = None) -> list[Invoice]:
    """Newest number first."""
    out: list[Invoice] = []
    for f in await books.list_files(INVOICES):
        if f.name.endswith(".json") and ID_RE.fullmatch(f.name.removesuffix(".json")):
            inv = Invoice.model_validate_json(await books.storage.read(f.path))
            if status is None or inv.status == status:
                out.append(inv)
    return sorted(out, key=lambda i: (i.issue_date, i.number), reverse=True)


async def allocate_number(books: Books) -> str:
    """The next number in the sequence, written back before it is used, so two drafts never share one.

    A number is never reused: unwanted drafts are voided, not deleted, which keeps the sequence unbroken.
    """
    for _ in range(50):
        got: dict[str, Any] = {}

        def bump(seq: dict[str, Any]) -> dict[str, Any]:
            prefix = str(seq.get("prefix", DEFAULT_SEQUENCE["prefix"])).upper()
            if not PREFIX_RE.fullmatch(prefix):
                prefix = DEFAULT_SEQUENCE["prefix"]
            n = max(1, int(seq.get("next", 1)))
            got["number"] = f"{prefix}{n:04d}"
            return {**seq, "prefix": prefix, "next": n + 1}

        await books._update_json(SEQUENCE, dict(DEFAULT_SEQUENCE), bump)
        if not await books.exists(_path(got["number"])):  # sequence.json reset or hand-edited backwards
            return got["number"]
    raise InvoiceError(f"Could not find a free invoice number; check {SEQUENCE}")


async def customer_from_contact(books: Books, contact_id: str) -> InvoiceCustomer | None:
    for c in await books.read_json(CONTACTS, []):
        if isinstance(c, dict) and c.get("id") == contact_id:
            return InvoiceCustomer(
                contact_id=contact_id, name=c.get("name") or "?", email=c.get("email") or None,
                address=c.get("address") or None, vrn=c.get("vrn") or None,
            )
    return None


async def customers(books: Books) -> list[InvoiceCustomer]:
    """Customers in the contact book (kind customer or both), for the picker. Empty when there is none yet."""
    out = []
    for c in await books.read_json(CONTACTS, []):
        if isinstance(c, dict) and c.get("id") and c.get("name") and c.get("kind") in ("customer", "both"):
            try:
                out.append(InvoiceCustomer(
                    contact_id=c["id"], name=c["name"], email=c.get("email") or None,
                    address=c.get("address") or None, vrn=c.get("vrn") or None,
                ))
            except ValueError:  # a hand-edited contact with a bad email still shows, without the email
                out.append(InvoiceCustomer(contact_id=c["id"], name=c["name"], address=c.get("address") or None))
    return sorted(out, key=lambda c: c.name.lower())


async def _fill_customer(books: Books, draft: InvoiceDraft) -> InvoiceDraft:
    """Blank customer fields are taken from the contact book when the customer was picked from it."""
    cust = draft.customer
    if not cust.contact_id or not (known := await customer_from_contact(books, cust.contact_id)):
        return draft
    filled = cust.model_copy(update={k: getattr(known, k) for k in ("email", "address", "vrn") if not getattr(cust, k)})
    return draft.model_copy(update={"customer": filled})


async def _check_hours(books: Books, draft: InvoiceDraft, number: str | None = None) -> None:
    """Timesheet entries on the lines must be this job's billable hours, each once, not billed on another invoice."""
    ids = [i for ln in draft.lines for i in ln.timesheet_entry_ids]
    if not ids:
        return
    if not draft.job_id:
        raise InvoiceError("Lines with timesheet hours need the job they came from")
    if len(set(ids)) != len(ids):
        raise InvoiceError("A timesheet entry is on more than one line")
    try:
        await jobs.get_job(books, draft.job_id)
    except jobs.NotFound as exc:
        raise InvoiceError("No such job") from exc
    known = {e.id: e for e in await jobs.load_entries(books)}
    for i in ids:
        e = known.get(i)
        if e is None or e.job_id != draft.job_id:
            raise InvoiceError(f"Timesheet entry {i} is not on this job")
        if not e.billable:
            raise InvoiceError(f"Timesheet entry {i} is not billable")
        if e.invoiced_in and e.invoiced_in != number:
            raise InvoiceError(f"Timesheet entry {i} is already on invoice {e.invoiced_in}")


async def create_invoice(books: Books, draft: InvoiceDraft, user: str) -> Invoice:
    profile = await load_profile(books)
    draft = await _fill_customer(books, draft)
    build_invoice("PENDING", draft, profile, user)  # refuse a bad draft before taking a number
    await _check_hours(books, draft)
    inv = build_invoice(await allocate_number(books), draft, profile, user)
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "invoice_created", {"invoice": inv.number, "total_pence": inv.total_pence})
    return inv


async def update_draft(books: Books, number: str, draft: InvoiceDraft, user: str) -> Invoice:
    old = await get_invoice(books, number)
    if old.status != "draft":
        raise InvoiceStateError(f"Invoice {number} is {old.status}; only drafts can be changed")
    draft = await _fill_customer(books, draft)
    await _check_hours(books, draft, number)
    inv = build_invoice(number, draft, await load_profile(books), old.created_by)
    inv.created_at = old.created_at
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "invoice_edited", {"invoice": number, "total_pence": inv.total_pence})
    return inv


# --------------------------------------------------------------------------- #
# Sending and posting
# --------------------------------------------------------------------------- #


def sale_event_id(number: str) -> str:
    return hashlib.sha256(f"invoice:{number}".encode()).hexdigest()[:32]


def sale_event(inv: Invoice, user: str, evidence: list[str]) -> LedgerEvent:
    """Dr 1100 Debtors gross; Cr 4000 Sales net per VAT code; Cr 2200 VAT control. Dated on the invoice date."""
    memo = f"Invoice {inv.number}"
    lines = [Line(account=DEBTORS, debit=inv.total_pence, memo=memo)]
    for row in inv.vat_summary:  # send_problems refuses negative rows
        if row.net_pence:
            lines.append(Line(account=SALES, credit=row.net_pence, vat_code=VatCode(row.vat_code), memo=memo))
    if inv.vat_pence:
        biggest = max(inv.vat_summary, key=lambda r: r.vat_pence)
        lines.append(Line(account=VAT_CONTROL, credit=inv.vat_pence, vat_code=VatCode(biggest.vat_code), memo=memo))
    return LedgerEvent(
        id=sale_event_id(inv.number), kind="sale", date=inv.issue_date, lines=lines, evidence=evidence,
        approved_by=user, approved_at=now(), net=sum(r.net_pence for r in inv.vat_summary if r.vat_code in ON_RETURN),
        vat=inv.vat_pence, counterparty=inv.customer.name,
    )


def send_problems(inv: Invoice, profile: InvoiceProfile, to: str | None) -> list[str]:
    """Why this invoice cannot be sent yet (empty when it can)."""
    out = []
    if inv.status != "draft":
        out.append(f"Invoice {inv.number} is already {inv.status}")
    if not to or not EMAIL_RE.fullmatch(to):
        out.append("Add the customer's email address")
    if not profile.name.strip() or not profile.address.strip():
        out.append("Add your business name and address in the invoice profile")
    if inv.vat_pence and not profile.vrn:
        out.append("Add your VAT registration number to the invoice profile before charging VAT")
    if inv.total_pence <= 0:
        out.append("The invoice total must be more than £0.00")
    if inv.vat_pence < 0 or any(r.net_pence < 0 for r in inv.vat_summary):
        out.append("Discounts cannot be bigger than the lines at the same VAT rate; use a credit note")
    return out


def default_email(inv: Invoice, profile: InvoiceProfile) -> tuple[str, str]:
    """(subject, body) the confirmation dialog starts from; the user can change both."""
    who = profile.name.strip() or "us"
    lines = [
        "Hello,", "",
        f"Please find attached invoice {inv.number} for {money(inv.total_pence)}, due on {uk_date(inv.due_date)}.",
    ]
    if profile.bank.is_set():
        lines += ["", "Payment details are on the invoice; please use the invoice number as the reference."]
    lines += ["", "Many thanks,", who]
    return f"Invoice {inv.number} from {who}", "\n".join(lines)


async def post_sale(books: Books, inv: Invoice, user: str) -> str:
    """Post the sale for a sent invoice (once: a retry finds the event already there)."""
    event = sale_event(inv, user, [inv.pdf_sha256] if inv.pdf_sha256 else [])
    try:
        path = await books.post_event(event)
    except FileExistsError:
        path = None
    inv.event_id = event.id
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "invoice_posted", {"invoice": inv.number, "event": event.id, "event_path": path})
    await books.rebuild_safely(user)
    return event.id


async def mark_hours(books: Books, inv: Invoice, user: str) -> None:
    """Mark the timesheet entries on a sent invoice's lines as invoiced on its number (jobs.mark_invoiced).

    The email has already gone, so this never fails the send. Entries removed, made unbillable or billed on
    another invoice since the draft was saved are skipped and listed in the audit log; the rest are marked.
    Marking again with the same number changes nothing, so a retried send is safe.
    """
    ids = inv.timesheet_entry_ids()
    if inv.status != "sent" or inv.timesheets_marked or not ids:
        return
    known = {e.id: e for e in await jobs.load_entries(books)}
    ok = [i for i in ids if (e := known.get(i)) and e.job_id == inv.job_id and e.billable
          and e.invoiced_in in (None, inv.number)]
    if ok:
        try:
            await jobs.mark_invoiced(books, ok, inv.number)
        except jobs.JobsError as exc:  # changed between the read and the write: sending again retries
            await books.audit(f"user:{user}", "timesheets_not_invoiced", {"invoice": inv.number, "reason": str(exc)})
            return
    inv.timesheets_marked = True
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "timesheets_invoiced", {
        "job": inv.job_id, "invoice": inv.number, "entries": ok, "skipped": [i for i in ids if i not in ok],
    })


async def send_invoice(
    books: Books, sender: MailSender, number: str, user: str, pdf: bytes,
    *, to: str | None = None, subject: str | None = None, body: str | None = None,
) -> Invoice:
    """Email the PDF from the user's mailbox, mark the invoice sent, then post the sale.

    Order matters. The email goes first, because it is the one step that cannot be taken back; if it fails
    nothing has changed. The invoice is saved as sent straight after, so a retry never emails twice. Then the
    job hours on its lines are marked invoiced on its number, then the sale is posted. If either of those
    fails, sending again finishes them without emailing (the invoice is sent with no event, or hours unmarked).
    """
    inv = await get_invoice(books, number)
    if inv.status == "sent" and (not inv.event_id or (inv.timesheet_entry_ids() and not inv.timesheets_marked)):
        await mark_hours(books, inv, user)
        if inv.event_id:
            await books.rebuild_safely(user)
        else:
            await post_sale(books, inv, user)
        return inv
    profile = await load_profile(books)
    to = (to or inv.customer.email or "").strip()
    if problems := send_problems(inv, profile, to):
        raise (InvoiceStateError if inv.status != "draft" else InvoiceError)("; ".join(problems))
    d_subject, d_body = default_email(inv, profile)
    await sender.send(OutgoingMail(
        to=to, subject=(subject or "").strip() or d_subject, body_text=(body or "").strip() or d_body,
        attachments=[OutgoingAttachment(name=f"{inv.number}.pdf", content_type="application/pdf", data=pdf)],
    ))
    sha = hashlib.sha256(pdf).hexdigest()
    inv.status, inv.sent_at, inv.sent_to, inv.sent_by, inv.pdf_sha256 = "sent", now(), to, user, sha
    await save_invoice(books, inv)
    await books.storage.write(f"{SENT}/{inv.number}.pdf", pdf)
    await books.audit(f"user:{user}", "invoice_sent", {"invoice": inv.number, "to": to, "pdf_sha256": sha})
    await mark_hours(books, inv, user)  # before posting, so a failed post cannot leave the hours billable twice
    await post_sale(books, inv, user)
    return inv


async def send_reminder(
    books: Books, sender: MailSender, number: str, user: str, *, to: str, subject: str, body: str, pdf: bytes | None,
) -> Invoice:
    """Send the reminder text the user approved (and may have edited), with the invoice attached."""
    inv = await get_invoice(books, number)
    if inv.status != "sent":
        raise InvoiceStateError(f"Invoice {number} is {inv.status}; only unpaid sent invoices can be chased")
    to = to.strip()
    if not EMAIL_RE.fullmatch(to):
        raise InvoiceError("Add the customer's email address")
    if not subject.strip() or not body.strip():
        raise InvoiceError("The reminder needs a subject and a message")
    attachments = [OutgoingAttachment(name=f"{inv.number}.pdf", content_type="application/pdf", data=pdf)] if pdf else []
    await sender.send(OutgoingMail(to=to, subject=subject.strip(), body_text=body.strip(), attachments=attachments))
    inv.reminders.append(Reminder(sent_at=now(), sent_by=user, to=to, subject=subject.strip()))
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "invoice_reminder_sent", {"invoice": number, "to": to, "count": len(inv.reminders)})
    return inv


async def sent_pdf(books: Books, number: str) -> bytes | None:
    try:
        return await books.storage.read(f"{SENT}/{number}.pdf")
    except FileNotFoundError:
        return None


# --------------------------------------------------------------------------- #
# Paid and void
# --------------------------------------------------------------------------- #


async def bank_candidates(books: Books, inv: Invoice) -> list[BankLine]:
    """Unmatched money in for exactly the invoice total, on or after the invoice date."""
    if inv.status != "sent":
        return []
    return [
        ln for ln in await books.list_bank_lines()
        if ln.status != "matched" and ln.amount_pence == inv.total_pence and ln.date >= inv.issue_date
    ]


async def mark_paid(
    books: Books, number: str, user: str, *, payment_ref: str | None = None, paid_on: date | None = None,
    bank_line_id: str | None = None,
) -> Invoice:
    inv = await get_invoice(books, number)
    if inv.status != "sent":
        raise InvoiceStateError(f"Invoice {number} is {inv.status}; only a sent invoice can be marked paid")
    if not inv.event_id:
        raise InvoiceStateError(f"Invoice {number} is not in the ledger yet; send it again to post it")
    if bank_line_id:
        try:
            line = await books.confirm_match(bank_line_id, [inv.event_id], user)
        except FileNotFoundError as exc:
            raise InvoiceError("No such bank line") from exc
        except BankMatchError as exc:
            raise InvoiceStateError(str(exc)) from exc
        paid_on = paid_on or line.date
        payment_ref = payment_ref or line.reference or line.description
    inv.status, inv.paid_at = "paid", paid_on or now().date()
    inv.payment_ref, inv.bank_line_id = (payment_ref or "").strip() or None, bank_line_id
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "invoice_paid", {
        "invoice": number, "event": inv.event_id, "bank_line": bank_line_id, "payment_ref": inv.payment_ref,
    })
    return inv


async def void_invoice(books: Books, number: str, user: str, reason: str) -> Invoice:
    """A draft is just marked void. A sent invoice also gets a reversal in the ledger (refused while a bank line is
    matched to it). Paid invoices cannot be voided: issue a credit note (not built yet)."""
    inv = await get_invoice(books, number)
    if inv.status not in ("draft", "sent"):
        raise InvoiceStateError(f"Invoice {number} is {inv.status} and cannot be voided")
    if not reason.strip():
        raise InvoiceError("Say why the invoice is void")
    if inv.status == "sent" and inv.event_id:
        if any(inv.event_id in ln.event_ids() for ln in await books.stored_bank_lines() if ln.status == "matched"):
            raise InvoiceStateError("A bank line is matched to this invoice; unmatch it first")
        reversal = reversal_of(await books.get_event(inv.event_id), user)
        try:
            await books.post_event(reversal)
        except FileExistsError:
            pass
        inv.reversal_event_id = reversal.id
    inv.status, inv.voided_at, inv.void_reason = "void", now(), reason.strip()
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "invoice_voided", {
        "invoice": number, "reason": inv.void_reason, "reversal": inv.reversal_event_id,
    })
    if inv.reversal_event_id:
        await books.rebuild_safely(user)
    return inv
