"""Quotes: written by the user, numbered and priced by code, emailed from their own Outlook, accepted or declined,
and turned into an invoice draft with the same lines.

Files, all in the user's folder:

    03 Sales/quotes/QU-0001.json        the quote (money in integer pence)
    03 Sales/quotes/QU-0001.pdf         the latest render
    03 Sales/quotes/sent/QU-0001.pdf    the exact PDF that was emailed
    _System/Invoicing/quote_sequence.json   {"prefix": "QU-", "next": 2}

A quote is priced exactly like an invoice (app/invoicing.price_lines): a line's net is quantity x unit price and its VAT
the net at the line's VAT code, each rounded half up to the penny; the totals are sums of lines. A quote posts nothing
to the books: it is an offer, not a sale.

Statuses: draft -> sent -> accepted | declined, and a sent quote past its expiry date reads as expired (worked out
from the date every time it is read; nothing runs in the background). Only a draft can be edited. Sending needs the
user's confirmation in the app (`confirm: true`), like an invoice. *Mark as sent* records a quote the user gave their
customer another way.

*Convert to invoice* makes a new invoice draft (app/invoicing.create_invoice) from a sent or accepted quote: the
same customer and lines, so net, VAT and total are exactly the quote's. The invoice is a draft; sending it is the
usual step with the usual confirmation. A quote becomes an invoice once.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from accnomos_connectors.base import MailSender, OutgoingAttachment, OutgoingMail
from app import invoicing as inv_
from app import paths
from app.books import Books, now
from app.books import today as london_today
from app.invoicing import (
    EMAIL_RE,
    INVOICING,
    Invoice,
    InvoiceCustomer,
    InvoiceDraft,
    InvoiceError,
    InvoiceLine,
    InvoiceProfile,
    InvoiceStateError,
    LineIn,
    VatSummaryRow,
    money,
    price_lines,
    uk_date,
)
from app.numbering import NUMBER_RE, allocate, safe_number
from app.pdf_docs import Party, TradeDoc, render_trade_document
from app.validation import LENIENT, Day, StrictBody

QUOTES = paths.QUOTES
QUOTES_SENT = paths.QUOTES_SENT
SEQUENCE = f"{INVOICING}/quote_sequence.json"
VALID_DAYS = 30  # a quote with no expiry date is good for this long
QuoteStatus = Literal["draft", "sent", "accepted", "declined", "expired"]


class QuoteDraft(StrictBody):
    """What the user writes. Numbers, line totals and VAT are worked out by code."""

    customer: InvoiceCustomer
    issue_date: Day | None = None  # default: today
    expiry_date: Day | None = None  # default: 30 days after the issue date
    lines: list[LineIn] = Field(min_length=1, max_length=100)
    reference: str | None = Field(None, max_length=60)  # the customer's own reference
    notes: str | None = Field(None, max_length=1000)  # printed on the quote (terms, what is excluded)


class Quote(BaseModel):
    number: str
    status: QuoteStatus = "draft"  # stored: draft | sent | accepted | declined. "expired" is worked out on read
    customer: InvoiceCustomer
    issue_date: date
    expiry_date: date
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
    sent_to: str | None = None  # None when marked as sent without an email
    sent_by: str | None = None
    pdf_sha256: str | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    invoice_number: str | None = None  # the invoice draft made from it
    converted_at: datetime | None = None

    def effective_status(self, today: date) -> QuoteStatus:
        return "expired" if self.status == "sent" and self.expiry_date < today else self.status


class QuoteRow(Quote):
    """A quote as the list shows it: `status` is what it reads as today (a sent quote past its date is expired)."""

    days_to_expiry: int | None = None


def row(q: Quote, today: date | None = None) -> QuoteRow:
    today = today or london_today()
    status = q.effective_status(today)
    d = q.model_dump()
    d["status"] = status
    return QuoteRow(**d, days_to_expiry=(q.expiry_date - today).days if status == "sent" else None)


def build_quote(number: str, draft: QuoteDraft, user: str, today: date | None = None) -> Quote:
    issue = draft.issue_date or today or london_today()
    expiry = draft.expiry_date or issue + timedelta(days=VALID_DAYS)
    if expiry < issue:
        raise InvoiceError("The expiry date is before the quote date")
    lines, summary, net, vat = price_lines(draft.lines)
    return Quote(
        number=number,
        customer=draft.customer,
        issue_date=issue,
        expiry_date=expiry,
        lines=lines,
        vat_summary=summary,
        net_pence=net,
        vat_pence=vat,
        total_pence=net + vat,
        reference=(draft.reference or "").strip() or None,
        notes=(draft.notes or "").strip() or None,
        created_by=user,
    )


def _path(number: str) -> str:
    return f"{QUOTES}/{safe_number(number)}.json"


async def get_quote(books: Books, number: str) -> Quote:
    """Raises FileNotFoundError, also for ids that could step outside the quotes folder."""
    return Quote.model_validate_json(await books.storage.read(_path(number)), **LENIENT)


async def save_quote(books: Books, q: Quote) -> None:
    q.updated_at = now()
    await books.write_json(_path(q.number), q.model_dump(mode="json"))


async def list_quotes(books: Books) -> list[Quote]:
    """Newest first."""
    files = [f for f in await books.list_files(QUOTES) if f.name.endswith(".json") and NUMBER_RE.fullmatch(f.name[:-5])]

    async def read_one(path: str) -> Quote:
        return Quote.model_validate_json(await books.storage.read(path), **LENIENT)

    out = await asyncio.gather(*(read_one(f.path) for f in files))
    return sorted(out, key=lambda q: (q.issue_date, q.number), reverse=True)


async def _fill_customer(books: Books, draft: QuoteDraft) -> QuoteDraft:
    cust = draft.customer
    if not cust.contact_id or not (known := await inv_.customer_from_contact(books, cust.contact_id)):
        return draft
    filled = cust.model_copy(update={k: getattr(known, k) for k in ("email", "address", "vrn") if not getattr(cust, k)})
    return draft.model_copy(update={"customer": filled})


async def create_quote(books: Books, draft: QuoteDraft, user: str) -> Quote:
    draft = await _fill_customer(books, draft)
    build_quote("PENDING", draft, user)  # refuse a bad draft before taking a number
    number = await allocate(books, SEQUENCE, "QU-", _path)
    q = build_quote(number, draft, user)
    await save_quote(books, q)
    await books.audit(f"user:{user}", "quote_created", {"quote": q.number, "total_pence": q.total_pence})
    return q


async def update_draft(books: Books, number: str, draft: QuoteDraft, user: str) -> Quote:
    old = await get_quote(books, number)
    if old.status != "draft":
        raise InvoiceStateError(f"Quote {number} is {old.status}; only drafts can be changed")
    q = build_quote(number, await _fill_customer(books, draft), old.created_by)
    q.created_at = old.created_at
    await save_quote(books, q)
    await books.audit(f"user:{user}", "quote_edited", {"quote": number, "total_pence": q.total_pence})
    return q


# --------------------------------------------------------------------------- #
# PDF and email
# --------------------------------------------------------------------------- #


def render_quote(q: Quote, profile: InvoiceProfile, logo: bytes | None = None) -> bytes:
    meta = [("Quote number", q.number), ("Quote date", uk_date(q.issue_date)), ("Valid until", uk_date(q.expiry_date))]
    if q.reference:
        meta.append(("Your reference", q.reference))
    stamp = {"accepted": "ACCEPTED", "declined": "DECLINED"}.get(q.status)
    if stamp and q.decided_at:
        stamp = f"{stamp} {uk_date(q.decided_at.date())}"
    return render_trade_document(
        TradeDoc(
            title="QUOTE",
            pdf_title=f"Quote {q.number}",
            meta=meta,
            parties=[
                Party(
                    "PREPARED FOR",
                    q.customer.name,
                    [*(q.customer.address or "").splitlines(), f"VAT no: {q.customer.vrn}" if q.customer.vrn else ""],
                )
            ],
            lines=q.lines,
            vat_summary=q.vat_summary,
            net_pence=q.net_pence,
            vat_pence=q.vat_pence,
            total_pence=q.total_pence,
            total_label="Total",
            stamp=stamp,
            paragraphs=[
                f"This quote is valid until {uk_date(q.expiry_date)}. Prices are in pounds sterling; VAT is shown "
                "at the rates above.",
                q.notes or "",
                profile.footer_note or "",
            ],
        ),
        profile,
        logo,
    )


def send_problems(q: Quote, profile: InvoiceProfile, to: str | None) -> list[str]:
    out = []
    if q.status != "draft":
        out.append(f"Quote {q.number} is already {q.status}")
    if not to or not EMAIL_RE.fullmatch(to):
        out.append("Add the customer's email address")
    if not profile.name.strip() or not profile.address.strip():
        out.append("Add your business name and address in the invoice profile")
    if q.vat_pence and not profile.vrn:
        out.append("Add your VAT registration number to the invoice profile before quoting VAT")
    if q.total_pence <= 0:
        out.append("The quote total must be more than £0.00")
    if q.expiry_date < london_today():
        out.append("The quote has already expired: change its expiry date")
    return out


def default_email(q: Quote, profile: InvoiceProfile) -> tuple[str, str]:
    who = profile.name.strip() or "us"
    body = "\n".join(
        [
            "Hello,",
            "",
            f"Please find attached quote {q.number} for {money(q.total_pence)}, valid until {uk_date(q.expiry_date)}.",
            "",
            "If you would like to go ahead, just reply to this email.",
            "",
            "Many thanks,",
            who,
        ]
    )
    return f"Quote {q.number} from {who}", body


async def send_quote(
    books: Books,
    sender: MailSender,
    number: str,
    user: str,
    pdf: bytes,
    *,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> Quote:
    """Email the PDF from the user's mailbox, then mark the quote sent. The email goes first, the one step that cannot
    be taken back; the quote is saved as sent straight after, so a retry never emails twice."""
    q = await get_quote(books, number)
    profile = await inv_.load_profile(books)
    to = (to or q.customer.email or "").strip()
    if problems := send_problems(q, profile, to):
        raise (InvoiceStateError if q.status != "draft" else InvoiceError)("; ".join(problems))
    d_subject, d_body = default_email(q, profile)
    await sender.send(
        OutgoingMail(
            to=to,
            subject=(subject or "").strip() or d_subject,
            body_text=(body or "").strip() or d_body,
            attachments=[OutgoingAttachment(name=f"{q.number}.pdf", content_type="application/pdf", data=pdf)],
        )
    )
    sha = hashlib.sha256(pdf).hexdigest()
    q.status, q.sent_at, q.sent_to, q.sent_by, q.pdf_sha256 = "sent", now(), to, user, sha
    await save_quote(books, q)
    await books.storage.write(f"{QUOTES_SENT}/{q.number}.pdf", pdf)
    await books.audit(f"user:{user}", "quote_sent", {"quote": q.number, "to": to, "pdf_sha256": sha})
    return q


async def sent_pdf(books: Books, number: str) -> bytes | None:
    try:
        return await books.storage.read(f"{QUOTES_SENT}/{safe_number(number)}.pdf")
    except FileNotFoundError:
        return None


async def mark_sent(books: Books, number: str, user: str) -> Quote:
    """The user gave the quote to the customer another way (by hand, post, their own email)."""
    q = await get_quote(books, number)
    if q.status != "draft":
        raise InvoiceStateError(f"Quote {number} is already {q.status}")
    q.status, q.sent_at, q.sent_by = "sent", now(), user
    await save_quote(books, q)
    await books.audit(f"user:{user}", "quote_marked_sent", {"quote": number})
    return q


# --------------------------------------------------------------------------- #
# Decisions and conversion
# --------------------------------------------------------------------------- #


async def decide(books: Books, number: str, user: str, outcome: Literal["accepted", "declined"]) -> Quote:
    """The customer's answer. A quote that has expired can still be answered (people reply late)."""
    q = await get_quote(books, number)
    if q.invoice_number:
        raise InvoiceStateError(f"Quote {number} has become invoice {q.invoice_number}")
    if q.status == "draft" and outcome == "accepted":
        raise InvoiceStateError(f"Quote {number} is a draft: send it, or mark it as sent, first")
    if q.status not in ("draft", "sent"):
        raise InvoiceStateError(f"Quote {number} is already {q.status}")
    q.status, q.decided_at, q.decided_by = outcome, now(), user
    await save_quote(books, q)
    await books.audit(f"user:{user}", f"quote_{outcome}", {"quote": number})
    return q


def invoice_draft_from(q: Quote, issue_date: date | None = None) -> InvoiceDraft:
    """The invoice draft a quote becomes: its customer and its lines, exactly (hours and descriptions included)."""
    return InvoiceDraft(
        customer=q.customer,
        issue_date=issue_date,
        due_date=None,
        lines=[
            LineIn(
                description=ln.description,
                quantity=ln.quantity,
                unit=ln.unit,
                unit_price_pence=ln.unit_price_pence,
                vat_code=ln.vat_code,
                item_code=ln.item_code,
            )
            for ln in q.lines
        ],
        reference=q.reference or f"Quote {q.number}",
        notes=q.notes,
        job_id=None,
    )


async def convert_to_invoice(
    books: Books, number: str, user: str, issue_date: date | None = None
) -> tuple[Quote, Invoice]:
    q = await get_quote(books, number)
    if q.invoice_number:
        raise InvoiceStateError(f"Quote {number} has already become invoice {q.invoice_number}")
    if q.status not in ("sent", "accepted"):
        raise InvoiceStateError(
            f"Quote {number} is {q.status}; only a sent or accepted quote can become an invoice"
            if q.status != "draft"
            else f"Quote {number} is a draft: send it, or mark it as sent, first"
        )
    inv = await inv_.create_invoice(books, invoice_draft_from(q, issue_date), user)
    # Same lines through the same pricing: the figures must agree to the penny, or something is badly wrong.
    if (inv.net_pence, inv.vat_pence, inv.total_pence) != (q.net_pence, q.vat_pence, q.total_pence):  # pragma: no cover
        raise InvoiceError(f"Invoice {inv.number} was priced differently from quote {number}; check both")
    q.invoice_number, q.converted_at = inv.number, now()
    await save_quote(books, q)
    await books.audit(
        f"user:{user}",
        "quote_converted",
        {"quote": number, "invoice": inv.number, "total_pence": inv.total_pence},
    )
    return q, inv


# --------------------------------------------------------------------------- #
# Facts for Ask
# --------------------------------------------------------------------------- #

EXPIRING_SOON_DAYS = 7


def _pounds(pence: int) -> str:
    return f"{pence // 100}.{pence % 100:02d}"


def quote_facts(quotes: list[Quote], today: date) -> dict[str, object] | None:
    """What a question about quotes may quote: figures worked out here, in pounds as strings, like the rest of the
    facts pack. None when there are no quotes at all, so a book without any adds nothing to the pack."""
    if not quotes:
        return None

    def card(q: Quote) -> dict[str, object]:
        return {
            "number": q.number,
            "customer": q.customer.name,
            "total": _pounds(q.total_pence),
            "sent": q.sent_at.date().isoformat() if q.sent_at else None,
            "valid_until": q.expiry_date.isoformat(),
            "days_left": (q.expiry_date - today).days,
        }

    def tally(qs: list[Quote]) -> dict[str, object]:
        return {"count": len(qs), "total": _pounds(sum(q.total_pence for q in qs))}

    by = {s: [q for q in quotes if q.effective_status(today) == s] for s in ("draft", "sent", "expired", "accepted")}
    waiting = sorted(by["sent"], key=lambda q: (q.expiry_date, q.number))
    soon = [q for q in waiting if (q.expiry_date - today).days <= EXPIRING_SOON_DAYS]
    expired = sorted(by["expired"], key=lambda q: (q.expiry_date, q.number), reverse=True)
    to_invoice = [q for q in by["accepted"] if not q.invoice_number]
    return {
        "as_of": today.isoformat(),
        "waiting_for_an_answer": {**tally(waiting), "quotes": [card(q) for q in waiting[:6]]},
        "expiring_within_7_days": tally(soon),
        "expired_unanswered": {**tally(expired), "quotes": [card(q) for q in expired[:4]]},
        "accepted_not_yet_invoiced": tally(to_invoice),
        "drafts": tally(by["draft"]),
    }
