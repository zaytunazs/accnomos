"""/quotes/*: quotes to customers (app/quotes.py), their PDFs (app/pdf_docs.py) and email from the user's Outlook.

Same headers as /invoices/*. Sending needs `Mail.Send` on the token and a body with `confirm: true`, which the app
sets only after the user ticked the confirmation in a dialog. Nothing is ever sent otherwise.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from accnomos_connectors.base import MailSender
from app import invoicing as inv_
from app import quotes as q_
from app.books import Books
from app.invoicing import InvoiceError, InvoiceStateError
from app.quotes import Quote, QuoteDraft, QuoteRow
from app.routes_books import get_books, require_user
from app.routes_invoices import EmailDraft, InvoiceRow, SendBody, _confirmed, get_sender
from app.validation import Day, StrictBody

router = APIRouter(prefix="/quotes", tags=["quotes"])


def _http(exc: InvoiceError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, InvoiceStateError) else 400, detail=str(exc))


async def _get(books: Books, number: str) -> Quote:
    try:
        return await q_.get_quote(books, number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such quote") from exc


@router.get("", response_model=list[QuoteRow])
async def list_quotes(books: Books = Depends(get_books)) -> list[QuoteRow]:
    return [q_.row(q) for q in await q_.list_quotes(books)]


@router.post("", response_model=QuoteRow)
async def create(body: QuoteDraft, books: Books = Depends(get_books), user: str = Depends(require_user)) -> QuoteRow:
    try:
        return q_.row(await q_.create_quote(books, body, user))
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.get("/{number}", response_model=QuoteRow)
async def get(number: str, books: Books = Depends(get_books)) -> QuoteRow:
    return q_.row(await _get(books, number))


@router.put("/{number}", response_model=QuoteRow)
async def update(
    number: str, body: QuoteDraft, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> QuoteRow:
    await _get(books, number)
    try:
        return q_.row(await q_.update_draft(books, number, body, user))
    except InvoiceError as exc:
        raise _http(exc) from exc


class QuotePdf(BaseModel):
    path: str
    size: int
    sha256: str
    data_url: str
    email: EmailDraft
    problems: list[str]


async def _render(books: Books, q: Quote) -> bytes:
    profile = await inv_.load_profile(books)
    return q_.render_quote(q, profile, await inv_.load_logo(books, profile))


@router.post("/{number}/pdf", response_model=QuotePdf)
async def pdf(number: str, books: Books = Depends(get_books)) -> QuotePdf:
    """Render the PDF and save it as 03 Sales/quotes/<number>.pdf for the preview. Once sent, the PDF that was
    emailed is returned as it was."""
    q = await _get(books, number)
    data = await q_.sent_pdf(books, number) if q.status != "draft" and q.sent_to else None
    path = f"{q_.QUOTES_SENT}/{number}.pdf"
    if data is None:
        data, path = await _render(books, q), f"{q_.QUOTES}/{number}.pdf"
        await books.storage.write(path, data)
    profile = await inv_.load_profile(books)
    subject, body = q_.default_email(q, profile)
    return QuotePdf(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data_url=f"data:application/pdf;base64,{base64.b64encode(data).decode()}",
        email=EmailDraft(to=q.customer.email, subject=subject, body=body),
        problems=q_.send_problems(q, profile, q.customer.email) if q.status == "draft" else [],
    )


@router.post("/{number}/send", response_model=QuoteRow)
async def send(
    number: str,
    body: SendBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    sender: MailSender = Depends(get_sender),
) -> QuoteRow:
    """Email the quote from the user's Outlook with the PDF attached."""
    _confirmed(body.confirm)
    q = await _get(books, number)
    data = await _render(books, q) if q.status == "draft" else b""
    try:
        return q_.row(
            await q_.send_quote(books, sender, number, user, data, to=body.to, subject=body.subject, body=body.body)
        )
    except InvoiceError as exc:
        raise _http(exc) from exc
    except ValueError as exc:  # e.g. the attachment is too big for one message
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{number}/mark-sent", response_model=QuoteRow)
async def mark_sent(number: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> QuoteRow:
    await _get(books, number)
    try:
        return q_.row(await q_.mark_sent(books, number, user))
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.post("/{number}/accept", response_model=QuoteRow)
async def accept(number: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> QuoteRow:
    await _get(books, number)
    try:
        return q_.row(await q_.decide(books, number, user, "accepted"))
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.post("/{number}/decline", response_model=QuoteRow)
async def decline(number: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> QuoteRow:
    await _get(books, number)
    try:
        return q_.row(await q_.decide(books, number, user, "declined"))
    except InvoiceError as exc:
        raise _http(exc) from exc


class ConvertBody(StrictBody):
    issue_date: Day | None = None  # the invoice's date; default today


class Converted(BaseModel):
    quote: QuoteRow
    invoice: InvoiceRow


@router.post("/{number}/convert", response_model=Converted)
async def convert(
    number: str, body: ConvertBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Converted:
    """Make an invoice draft with the quote's customer and lines. The draft is sent the usual way, with the usual
    confirmation; nothing is emailed or posted here."""
    await _get(books, number)
    try:
        q, inv = await q_.convert_to_invoice(books, number, user, body.issue_date)
    except InvoiceError as exc:
        raise _http(exc) from exc
    from app.routes_invoices import _row

    return Converted(quote=q_.row(q), invoice=_row(inv))
