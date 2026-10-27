"""/credit-notes/* and /payments/*: credit notes to customers (app/credit_notes.py) and payments against sales
invoices and bills (app/payments.py).

Same headers as /invoices/*. Creating a credit note posts it, so the body must carry `confirm: true`, which the app
sets only after the user ticked the confirmation; emailing one needs `Mail.Send` and `confirm: true` too.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool

from accnomos_connectors.base import MailSender
from app import credit_notes as cn_
from app import invoicing as inv_
from app import payments as pay_
from app.books import Books
from app.credit_notes import CreditLineIn, CreditNote, CreditNoteDraft
from app.invoicing import InvoiceError, InvoiceStateError
from app.pdf import render_invoice
from app.routes_books import get_books, require_user
from app.routes_invoices import EmailDraft, SendBody, VoidBody, get_sender
from app.settlement import Payment, PaymentRecord, Side
from app.validation import Day, StrictBody

router = APIRouter(tags=["credit notes", "payments"])


def _http(exc: InvoiceError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, InvoiceStateError) else 400, detail=str(exc))


def _confirmed(confirm: bool) -> None:
    if confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was done: confirm in the app first (confirm: true)")


async def _get(books: Books, number: str) -> CreditNote:
    try:
        return await cn_.get_credit_note(books, number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such credit note") from exc


class CreditNoteCreate(StrictBody):
    confirm: StrictBool = False
    lines: list[CreditLineIn] | None = Field(None, min_length=1, max_length=100)  # None: the whole invoice
    issue_date: Day | None = None
    reason: str = Field(min_length=1, max_length=300)


@router.post("/invoices/{number}/credit-notes", response_model=CreditNote)
async def create(
    number: str, body: CreditNoteCreate, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> CreditNote:
    """Credit all of a sent invoice, or chosen lines and quantities. Posted at once (a reversal of that part of the
    sale with the same VAT codes, dated on the credit note's date)."""
    _confirmed(body.confirm)
    try:
        await inv_.get_invoice(books, number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such invoice") from exc
    draft = CreditNoteDraft(lines=body.lines, issue_date=body.issue_date, reason=body.reason)
    try:
        return await cn_.create_credit_note(books, number, draft, user)
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.get("/credit-notes", response_model=list[CreditNote])
async def list_credit_notes(
    invoice: str | None = Query(None, max_length=24), books: Books = Depends(get_books)
) -> list[CreditNote]:
    return await cn_.list_credit_notes(books, invoice)


@router.get("/credit-notes/{number}", response_model=CreditNote)
async def get(number: str, books: Books = Depends(get_books)) -> CreditNote:
    return await _get(books, number)


class CreditNotePdf(BaseModel):
    path: str
    size: int
    sha256: str
    data_url: str
    email: EmailDraft


async def _render(books: Books, cn: CreditNote) -> bytes:
    profile = await inv_.load_profile(books)
    return render_invoice(cn.as_invoice(), profile, await inv_.load_logo(books, profile), credit_for=cn.invoice)


@router.post("/credit-notes/{number}/pdf", response_model=CreditNotePdf)
async def pdf(number: str, books: Books = Depends(get_books)) -> CreditNotePdf:
    """Render (or, once emailed, return the emailed copy) and save it in 03 Sales/credit-notes."""
    cn = await _get(books, number)
    data = await cn_.sent_pdf(books, number)
    path = f"{cn_.CREDIT_NOTES_SENT}/{number}.pdf"
    if data is None:
        data, path = await _render(books, cn), f"{cn_.CREDIT_NOTES}/{number}.pdf"
        await books.storage.write(path, data)
    subject, body = cn_.default_email(cn, await inv_.load_profile(books))
    return CreditNotePdf(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data_url=f"data:application/pdf;base64,{base64.b64encode(data).decode()}",
        email=EmailDraft(to=cn.customer.email, subject=subject, body=body),
    )


@router.post("/credit-notes/{number}/send", response_model=CreditNote)
async def send(
    number: str,
    body: SendBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    sender: MailSender = Depends(get_sender),
) -> CreditNote:
    """Email the credit note from the user's Outlook (it is already in the books)."""
    _confirmed(body.confirm)
    cn = await _get(books, number)
    try:
        return await cn_.send_credit_note(
            books, sender, number, user, await _render(books, cn), to=body.to, subject=body.subject, body=body.body
        )
    except InvoiceError as exc:
        raise _http(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/credit-notes/{number}/void", response_model=CreditNote)
async def void(
    number: str, body: VoidBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> CreditNote:
    await _get(books, number)
    try:
        return await cn_.void_credit_note(books, number, user, body.reason)
    except InvoiceError as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------------------- #
# Payments: sales invoices and bills alike
# --------------------------------------------------------------------------- #


@router.get("/payments", response_model=list[Payment])
async def list_payments(side: Side | None = None, books: Books = Depends(get_books)) -> list[Payment]:
    """Every payment (recorded, or a bank line matched to documents) and what it paid, oldest first."""
    ledger = await pay_.load_ledger(books)
    return sorted(
        (p for p in ledger.settlement().payments if side is None or p.side == side), key=lambda p: (p.date, p.id)
    )


@router.get("/payments/open", response_model=list[pay_.OpenDocument])
async def open_documents(side: Side = "purchase", books: Books = Depends(get_books)) -> list[pay_.OpenDocument]:
    """Sales invoices or bills on account with something left to pay: what a payment can be split across."""
    return pay_.open_documents(await pay_.load_ledger(books), side)


@router.post("/payments", response_model=PaymentRecord)
async def record(
    body: pay_.PaymentIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> PaymentRecord:
    """Record a payment and its split (Dr 1200 Bank / Cr 1100 Debtors, or Dr 2100 Creditors / Cr 1200 Bank)."""
    try:
        return await pay_.record_payment(books, body, user)
    except InvoiceError as exc:
        raise _http(exc) from exc


class Removed(BaseModel):
    documents: list[str]


@router.delete("/payments/{payment_id}", response_model=Removed)
async def remove(payment_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Removed:
    """Reverse a recorded payment's entry, or unmatch a bank line matched straight to documents."""
    try:
        return Removed(documents=await pay_.remove_payment(books, payment_id, user))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such payment") from exc
    except InvoiceError as exc:
        raise _http(exc) from exc
