"""Credit notes to customers: made from a sent invoice (all of it, or chosen lines and quantities), or stand-alone
with their own customer, lines and descriptions, priced and posted by code, emailed from the user's own Outlook
like an invoice.

Files, all in the user's folder:

    03 Sales/credit-notes/CN-0001.json       the credit note (money in integer pence)
    03 Sales/credit-notes/CN-0001.pdf        the latest render
    03 Sales/credit-notes/sent/CN-0001.pdf   the exact PDF that was emailed
    _System/Invoicing/credit_sequence.json   {"prefix": "CN-", "next": 2}

Money is code's job, as for invoices (app/invoicing.py): each credited line is quantity × the invoice line's unit
price at the invoice line's VAT code, rounded half up per line; totals are sums of lines.

Creating one needs the user's confirmation in the app (`confirm: true`) and posts it at once: a reversal of the
credited part of the sale, by code, with the same VAT codes (Dr 4000 Sales net per code, Dr 2200 VAT control,
Cr 1100 Debtors gross), dated on the credit note's own date, so the VAT boxes net off in the credit note's period
(VAT Notice 700, section 18: a credit note is accounted for when it is issued). The event's `credits` field names the
invoice's sale, which app/settlement.py reduces by the credit note; any excess is a credit on the customer.

Statuses: issued -> void. Voiding appends a reversal of the credit note (nothing is deleted).
"""

from __future__ import annotations

import contextlib
import hashlib
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from accnomos_connectors.base import MailSender, OutgoingAttachment, OutgoingMail
from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app import paths
from app.approve import reversal_of
from app.books import Books, now
from app.books import today as london_today
from app.invoicing import (
    EMAIL_RE,
    ID_RE,
    INVOICING,
    ON_RETURN,
    PREFIX_RE,
    Invoice,
    InvoiceCustomer,
    InvoiceError,
    InvoiceLine,
    InvoiceProfile,
    InvoiceStateError,
    LineIn,
    VatSummaryRow,
    get_invoice,
    money,
    price_lines,
    uk_date,
)
from app.journal import DEBTORS, SALES, VAT_CONTROL
from app.validation import LENIENT, Day, StrictBody

CREDIT_NOTES = paths.CREDIT_NOTES
CREDIT_NOTES_SENT = paths.CREDIT_NOTES_SENT
CN_SEQUENCE = f"{INVOICING}/credit_sequence.json"
DEFAULT_SEQUENCE = {"prefix": "CN-", "next": 1}
CreditNoteStatus = Literal["issued", "void"]


class CreditLineIn(StrictBody):
    line: int = Field(ge=0, lt=100)  # the invoice line, from 0
    quantity: Decimal | None = Field(None, gt=0, le=1_000_000, decimal_places=3)  # default: the whole line


class CreditNoteDraft(StrictBody):
    lines: list[CreditLineIn] | None = Field(None, min_length=1, max_length=100)  # None: the whole invoice
    issue_date: Day | None = None  # default: today
    reason: str = Field(min_length=1, max_length=300)


class CreditNote(BaseModel):
    number: str
    invoice: str | None = None  # the invoice number it credits (None: a stand-alone credit note)
    invoice_event_id: str | None = None  # that invoice's sale in the ledger (None: stand-alone)
    status: CreditNoteStatus = "issued"
    customer: InvoiceCustomer
    issue_date: date
    lines: list[InvoiceLine]
    source_lines: list[int] = []  # the invoice line each credited line came from (empty when stand-alone)
    vat_summary: list[VatSummaryRow]
    net_pence: int
    vat_pence: int
    total_pence: int
    reason: str
    created_by: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    event_id: str | None = None
    sent_at: datetime | None = None
    sent_to: str | None = None
    pdf_sha256: str | None = None
    voided_at: datetime | None = None
    void_reason: str | None = None
    reversal_event_id: str | None = None

    def as_invoice(self) -> Invoice:
        """The same figures in the invoice's shape, for the PDF renderer (app/pdf.py)."""
        return Invoice(
            number=self.number,
            status="sent",
            customer=self.customer,
            issue_date=self.issue_date,
            due_date=self.issue_date,
            lines=self.lines,
            vat_summary=self.vat_summary,
            net_pence=self.net_pence,
            vat_pence=self.vat_pence,
            total_pence=self.total_pence,
            reference=self.invoice,
            notes=f"Reason: {self.reason}",
            created_by=self.created_by,
        )


def _path(number: str) -> str:
    if not ID_RE.fullmatch(number):
        raise FileNotFoundError(number)
    return f"{CREDIT_NOTES}/{number}.json"


async def get_credit_note(books: Books, number: str) -> CreditNote:
    """Raises FileNotFoundError, also for ids that could step outside the folder."""
    return CreditNote.model_validate_json(await books.storage.read(_path(number)), **LENIENT)


async def save_credit_note(books: Books, cn: CreditNote) -> None:
    cn.updated_at = now()
    await books.write_json(_path(cn.number), cn.model_dump(mode="json"))


async def list_credit_notes(books: Books, invoice: str | None = None) -> list[CreditNote]:
    """Newest first; only those crediting `invoice` when given."""
    out: list[CreditNote] = []
    try:
        files = await books.list_files(CREDIT_NOTES)
    except FileNotFoundError:
        return []
    for f in files:
        if f.name.endswith(".json") and ID_RE.fullmatch(f.name.removesuffix(".json")):
            cn = CreditNote.model_validate_json(await books.storage.read(f.path), **LENIENT)
            if invoice is None or cn.invoice == invoice:
                out.append(cn)
    return sorted(out, key=lambda c: (c.issue_date, c.number), reverse=True)


async def allocate_number(books: Books) -> str:
    """The next CN- number, written back before it is used (as app/invoicing.allocate_number)."""
    for _ in range(50):
        got: dict[str, Any] = {}

        def bump(seq: dict[str, Any], got: dict[str, Any] = got) -> dict[str, Any]:
            prefix = str(seq.get("prefix", DEFAULT_SEQUENCE["prefix"])).upper()
            if not PREFIX_RE.fullmatch(prefix):
                prefix = DEFAULT_SEQUENCE["prefix"]
            n = max(1, int(seq.get("next", 1)))
            got["number"] = f"{prefix}{n:04d}"
            return {**seq, "prefix": prefix, "next": n + 1}

        await books._update_json(CN_SEQUENCE, dict(DEFAULT_SEQUENCE), bump)
        if not await books.exists(_path(got["number"])):
            return got["number"]
    raise InvoiceError(f"Could not find a free credit note number; check {CN_SEQUENCE}")


def credited_quantities(notes: list[CreditNote]) -> dict[int, Decimal]:
    """Invoice line -> quantity already credited by issued credit notes."""
    done: dict[int, Decimal] = defaultdict(Decimal)
    for cn in notes:
        if cn.status == "issued":
            for src, ln in zip(cn.source_lines, cn.lines, strict=True):
                done[src] += ln.quantity
    return done


def build_lines(inv: Invoice, draft: CreditNoteDraft, earlier: list[CreditNote]) -> tuple[list[LineIn], list[int]]:
    """The credited lines (the invoice line's price and VAT code, the credited quantity) and the invoice line each
    came from. Refuses crediting more of a line than is left on it after earlier credit notes."""
    done = credited_quantities(earlier)
    wanted = draft.lines or [
        CreditLineIn(line=i, quantity=ln.quantity - done[i]) for i, ln in enumerate(inv.lines) if ln.quantity > done[i]
    ]
    if not wanted:
        raise InvoiceError(f"Invoice {inv.number} has already been credited in full")
    seen: set[int] = set()
    ins: list[LineIn] = []
    for w in wanted:
        if w.line >= len(inv.lines):
            raise InvoiceError(f"Invoice {inv.number} has no line {w.line + 1}")
        if w.line in seen:
            raise InvoiceError(f"Line {w.line + 1} is chosen twice")
        seen.add(w.line)
        src = inv.lines[w.line]
        qty = w.quantity if w.quantity is not None else src.quantity - done[w.line]
        if qty <= 0 or qty > src.quantity - done[w.line]:
            left = src.quantity - done[w.line]
            raise InvoiceError(f"Line {w.line + 1} has {left.normalize():f} left to credit")
        ins.append(
            LineIn(
                description=src.description,
                quantity=qty,
                unit=src.unit,
                unit_price_pence=src.unit_price_pence,
                vat_code=src.vat_code,
            )
        )
    return ins, [w.line for w in wanted]


def credit_note_event_id(number: str) -> str:
    return hashlib.sha256(f"credit_note:{number}".encode()).hexdigest()[:32]


def credit_note_event(cn: CreditNote, user: str) -> LedgerEvent:
    """Dr 4000 Sales net per VAT code; Dr 2200 VAT control; Cr 1100 Debtors gross. Dated on the credit note's date.

    A stand-alone credit note credits no invoice (`credits` empty): what is left becomes a credit on the customer
    (app/settlement.py), to apply or refund from Contacts like any other credit."""
    memo = f"Credit note {cn.number} for invoice {cn.invoice}" if cn.invoice else f"Credit note {cn.number}"
    lines: list[Line] = []
    for row in cn.vat_summary:
        if row.net_pence:
            lines.append(Line(account=SALES, debit=row.net_pence, vat_code=VatCode(row.vat_code), memo=memo))
    if cn.vat_pence:
        biggest = max(cn.vat_summary, key=lambda r: r.vat_pence)
        lines.append(Line(account=VAT_CONTROL, debit=cn.vat_pence, vat_code=VatCode(biggest.vat_code), memo=memo))
    lines.append(Line(account=DEBTORS, credit=cn.total_pence, memo=memo))
    return LedgerEvent(
        id=credit_note_event_id(cn.number),
        kind="reversal",
        date=cn.issue_date,
        lines=lines,
        evidence=[cn.pdf_sha256] if cn.pdf_sha256 else [],
        approved_by=user,
        approved_at=now(),
        credits=cn.invoice_event_id,
        net=sum(r.net_pence for r in cn.vat_summary if r.vat_code in ON_RETURN),
        vat=cn.vat_pence,
        counterparty=cn.customer.name,
    )


async def create_credit_note(
    books: Books, invoice_number: str, draft: CreditNoteDraft, user: str, today: date | None = None
) -> CreditNote:
    """Price, number, save and post a credit note against a sent invoice. Raises InvoiceError / InvoiceStateError."""
    inv = await get_invoice(books, invoice_number)
    if inv.status not in ("sent", "paid") or not inv.event_id:
        raise InvoiceStateError(f"Invoice {inv.number} is {inv.status}; only a sent invoice can be credited")
    issue = draft.issue_date or today or london_today()
    if issue < inv.issue_date:
        raise InvoiceError("The credit note is dated before the invoice")
    earlier = await list_credit_notes(books, inv.number)
    ins, sources = build_lines(inv, draft, earlier)
    lines, summary, net, vat = price_lines(ins)
    if net + vat <= 0 or vat < 0 or any(r.net_pence < 0 for r in summary):
        raise InvoiceError("A credit note must credit more than £0.00 at each VAT rate; choose other lines")
    already = sum(c.total_pence for c in earlier if c.status == "issued")
    if already + net + vat > inv.total_pence:
        raise InvoiceError(f"Invoice {inv.number} is {money(inv.total_pence)} and {money(already)} is already credited")
    cn = CreditNote(
        number=await allocate_number(books),
        invoice=inv.number,
        invoice_event_id=inv.event_id,
        customer=inv.customer,
        issue_date=issue,
        lines=lines,
        source_lines=sources,
        vat_summary=summary,
        net_pence=net,
        vat_pence=vat,
        total_pence=net + vat,
        reason=draft.reason.strip(),
        created_by=user,
    )
    cn.event_id = credit_note_event_id(cn.number)
    await save_credit_note(books, cn)  # saved first: a failed post is finished by `post_credit_note` on retry
    await books.audit(
        f"user:{user}",
        "credit_note_created",
        {"credit_note": cn.number, "invoice": inv.number, "total_pence": cn.total_pence},
    )
    await post_credit_note(books, cn, user)
    return cn


async def post_credit_note(books: Books, cn: CreditNote, user: str) -> str:
    event = credit_note_event(cn, user)
    with contextlib.suppress(FileExistsError):
        await books.post_event(event)
    await books.audit(
        f"user:{user}",
        "credit_note_posted",
        {"credit_note": cn.number, "invoice": cn.invoice, "event": event.id},
    )
    from app.payments import sync_invoices  # app.payments imports app.contacts, which imports this module

    await sync_invoices(books, {cn.invoice_event_id} if cn.invoice_event_id else set())
    await books.rebuild_safely(f"user:{user}")
    return event.id


class StandaloneCreditNoteDraft(StrictBody):
    """A credit note owed to a customer, not against any invoice: its own customer, lines and descriptions."""

    customer: InvoiceCustomer
    lines: list[LineIn] = Field(min_length=1, max_length=100)
    issue_date: Day | None = None  # default: today
    reason: str = Field(min_length=1, max_length=300)


async def create_standalone_credit_note(
    books: Books, draft: StandaloneCreditNoteDraft, user: str, today: date | None = None
) -> CreditNote:
    """Price, number, save and post a stand-alone credit note: same CN- numbers and same posting as one made from
    an invoice, but crediting nobody's invoice — the amount is left as a credit on the customer. Raises InvoiceError."""
    lines, summary, net, vat = price_lines(draft.lines)
    if net + vat <= 0 or vat < 0 or any(r.net_pence < 0 for r in summary):
        raise InvoiceError("A credit note must credit more than £0.00 at each VAT rate")
    cn = CreditNote(
        number=await allocate_number(books),
        invoice=None,
        invoice_event_id=None,
        customer=draft.customer,
        issue_date=draft.issue_date or today or london_today(),
        lines=lines,
        source_lines=[],
        vat_summary=summary,
        net_pence=net,
        vat_pence=vat,
        total_pence=net + vat,
        reason=draft.reason.strip(),
        created_by=user,
    )
    cn.event_id = credit_note_event_id(cn.number)
    await save_credit_note(books, cn)  # saved first: a failed post is finished by `post_credit_note` on retry
    await books.audit(
        f"user:{user}",
        "credit_note_created",
        {"credit_note": cn.number, "invoice": None, "total_pence": cn.total_pence},
    )
    await post_credit_note(books, cn, user)
    return cn


def default_email(cn: CreditNote, profile: InvoiceProfile) -> tuple[str, str]:
    who = profile.name.strip() or "us"
    against = f", against invoice {cn.invoice}," if cn.invoice else ""
    body = "\n".join(
        [
            "Hello,",
            "",
            f"Please find attached credit note {cn.number} for {money(cn.total_pence)}{against} "
            f"dated {uk_date(cn.issue_date)}.",
            "",
            "Many thanks,",
            who,
        ]
    )
    return f"Credit note {cn.number} from {who}", body


async def send_credit_note(
    books: Books,
    sender: MailSender,
    number: str,
    user: str,
    pdf: bytes,
    *,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> CreditNote:
    """Email the credit note's PDF from the user's mailbox (it is already in the books)."""
    cn = await get_credit_note(books, number)
    if cn.status != "issued":
        raise InvoiceStateError(f"Credit note {number} is {cn.status}")
    to = (to or cn.customer.email or "").strip()
    if not EMAIL_RE.fullmatch(to):
        raise InvoiceError("Add the customer's email address")
    from app.invoicing import load_profile

    d_subject, d_body = default_email(cn, await load_profile(books))
    await sender.send(
        OutgoingMail(
            to=to,
            subject=(subject or "").strip() or d_subject,
            body_text=(body or "").strip() or d_body,
            attachments=[OutgoingAttachment(name=f"{cn.number}.pdf", content_type="application/pdf", data=pdf)],
        )
    )
    cn.sent_at, cn.sent_to, cn.pdf_sha256 = now(), to, hashlib.sha256(pdf).hexdigest()
    await save_credit_note(books, cn)
    await books.storage.write(f"{CREDIT_NOTES_SENT}/{cn.number}.pdf", pdf)
    await books.audit(f"user:{user}", "credit_note_sent", {"credit_note": cn.number, "to": to})
    return cn


async def sent_pdf(books: Books, number: str) -> bytes | None:
    try:
        return await books.storage.read(f"{CREDIT_NOTES_SENT}/{number}.pdf")
    except FileNotFoundError:
        return None


async def void_credit_note(books: Books, number: str, user: str, reason: str) -> CreditNote:
    """Reverse the credit note in the ledger (dated like it, so its VAT period nets to nothing) and mark it void."""
    cn = await get_credit_note(books, number)
    if cn.status != "issued":
        raise InvoiceStateError(f"Credit note {number} is already {cn.status}")
    if not reason.strip():
        raise InvoiceError("Say why the credit note is void")
    if cn.event_id:
        from app.credits import refuse_while_used, uses_of

        refuse_while_used(await uses_of(books, "credit_note", cn.event_id), f"credit note {number}")
    if cn.event_id:
        try:
            event = await books.get_event(cn.event_id)
        except FileNotFoundError:
            event = None
        if event is not None:
            reversal = reversal_of(event, user)
            with contextlib.suppress(FileExistsError):
                await books.post_event(reversal)
            cn.reversal_event_id = reversal.id
    cn.status, cn.voided_at, cn.void_reason = "void", now(), reason.strip()
    await save_credit_note(books, cn)
    await books.audit(
        f"user:{user}",
        "credit_note_voided",
        {"credit_note": number, "invoice": cn.invoice, "reason": cn.void_reason, "reversal": cn.reversal_event_id},
    )
    from app.payments import sync_invoices

    await sync_invoices(books, {cn.invoice_event_id} if cn.invoice_event_id else set())
    await books.rebuild_safely(f"user:{user}")
    return cn
