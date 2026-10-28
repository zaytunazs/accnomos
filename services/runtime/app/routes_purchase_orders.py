"""/purchase-orders/*: purchase orders to suppliers (app/purchase_orders.py), their PDFs and Outlook email.

Same headers as /invoices/*. Sending needs `Mail.Send` on the token and `confirm: true`. Converting to a bill writes a
proposal that waits in Review; nothing is posted until the user approves it there.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from accnomos_connectors.base import MailSender
from app import invoicing as inv_
from app import purchase_orders as po_
from app.books import Books
from app.invoicing import InvoiceCustomer, InvoiceError, InvoiceStateError
from app.purchase_orders import BillCandidate, OrderRow, PurchaseOrder, PurchaseOrderDraft
from app.routes_books import get_books, require_user
from app.routes_invoices import EmailDraft, SendBody, _confirmed, get_sender
from app.schemas import Proposal
from app.validation import Day, StrictBody

router = APIRouter(prefix="/purchase-orders", tags=["purchase orders"])


def _http(exc: InvoiceError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, InvoiceStateError) else 400, detail=str(exc))


async def _get(books: Books, number: str) -> PurchaseOrder:
    try:
        return await po_.get_order(books, number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such purchase order") from exc


async def _row_safe(books: Books, number: str) -> OrderRow:
    po = await _get(books, number)
    proposals = {}
    if po.bill:
        try:
            proposals = {po.bill.proposal_id: await books.get_proposal(po.bill.proposal_id)}
        except FileNotFoundError:
            proposals = {}
    return po_.row(po, proposals)


@router.get("", response_model=list[OrderRow])
async def list_orders(books: Books = Depends(get_books)) -> list[OrderRow]:
    return await po_.rows(books)


@router.get("/suppliers", response_model=list[InvoiceCustomer])
async def suppliers(books: Books = Depends(get_books)) -> list[InvoiceCustomer]:
    """Suppliers from the contact book, for the picker."""
    return await po_.suppliers(books)


@router.post("", response_model=OrderRow)
async def create(
    body: PurchaseOrderDraft, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> OrderRow:
    try:
        po = await po_.create_order(books, body, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return po_.row(po, {})


@router.get("/{number}", response_model=OrderRow)
async def get(number: str, books: Books = Depends(get_books)) -> OrderRow:
    return await _row_safe(books, number)


@router.put("/{number}", response_model=OrderRow)
async def update(
    number: str, body: PurchaseOrderDraft, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> OrderRow:
    await _get(books, number)
    try:
        return po_.row(await po_.update_draft(books, number, body, user), {})
    except InvoiceError as exc:
        raise _http(exc) from exc


class OrderPdf(BaseModel):
    path: str
    size: int
    sha256: str
    data_url: str
    email: EmailDraft
    problems: list[str]


async def _render(books: Books, po: PurchaseOrder) -> bytes:
    profile = await inv_.load_profile(books)
    return po_.render_order(po, profile, await inv_.load_logo(books, profile))


@router.post("/{number}/pdf", response_model=OrderPdf)
async def pdf(number: str, books: Books = Depends(get_books)) -> OrderPdf:
    """Render the PDF and save it for the preview. Once sent, the PDF that was emailed is returned as it was."""
    po = await _get(books, number)
    data = await po_.sent_pdf(books, number) if po.sent_to else None
    path = f"{po_.ORDERS_SENT}/{number}.pdf"
    if data is None:
        data, path = await _render(books, po), f"{po_.ORDERS}/{number}.pdf"
        await books.storage.write(path, data)
    profile = await inv_.load_profile(books)
    subject, body = po_.default_email(po, profile)
    return OrderPdf(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data_url=f"data:application/pdf;base64,{base64.b64encode(data).decode()}",
        email=EmailDraft(to=po.supplier.email, subject=subject, body=body),
        problems=po_.send_problems(po, profile, po.supplier.email) if po.status in ("draft", "approved") else [],
    )


@router.post("/{number}/approve", response_model=OrderRow)
async def approve(number: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> OrderRow:
    await _get(books, number)
    try:
        return po_.row(await po_.approve_order(books, number, user), {})
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.post("/{number}/send", response_model=OrderRow)
async def send(
    number: str,
    body: SendBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    sender: MailSender = Depends(get_sender),
) -> OrderRow:
    """Email the approved order to the supplier from the user's Outlook with the PDF attached."""
    _confirmed(body.confirm)
    po = await _get(books, number)
    data = await _render(books, po) if po.status == "approved" else b""
    try:
        return po_.row(
            await po_.send_order(books, sender, number, user, data, to=body.to, subject=body.subject, body=body.body),
            {},
        )
    except InvoiceError as exc:
        raise _http(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{number}/mark-sent", response_model=OrderRow)
async def mark_sent(number: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> OrderRow:
    await _get(books, number)
    try:
        return po_.row(await po_.mark_sent(books, number, user), {})
    except InvoiceError as exc:
        raise _http(exc) from exc


class CancelBody(StrictBody):
    reason: str = Field(min_length=1, max_length=300)


@router.post("/{number}/cancel", response_model=OrderRow)
async def cancel(
    number: str, body: CancelBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> OrderRow:
    await _get(books, number)
    try:
        return po_.row(await po_.cancel_order(books, number, user, body.reason), {})
    except InvoiceError as exc:
        raise _http(exc) from exc


class ConvertBody(StrictBody):
    bill_date: Day | None = None  # the bill's date; default today (editable in Review)


class BillMade(BaseModel):
    order: OrderRow
    proposal: Proposal


@router.post("/{number}/convert-to-bill", response_model=BillMade)
async def convert_to_bill(
    number: str, body: ConvertBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> BillMade:
    """Write the bill as a proposal in Review, pre-filled from the order. The user approves it there; nothing is
    posted here."""
    await _get(books, number)
    try:
        po, proposal = await po_.convert_to_bill(books, number, user, body.bill_date)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return BillMade(order=po_.row(po, {proposal.id: proposal}), proposal=proposal)


@router.get("/{number}/bill-candidates", response_model=list[BillCandidate])
async def bill_candidates(number: str, books: Books = Depends(get_books)) -> list[BillCandidate]:
    await _get(books, number)
    return await po_.bill_candidates(books, number)


class MatchBody(StrictBody):
    proposal_id: str = Field(pattern=r"^[0-9a-f]{8,64}$", max_length=64)


@router.post("/{number}/match-bill", response_model=OrderRow)
async def match_bill(
    number: str, body: MatchBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> OrderRow:
    await _get(books, number)
    try:
        await po_.match_bill(books, number, body.proposal_id, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return await _row_safe(books, number)


@router.delete("/{number}/bill", response_model=OrderRow)
async def unlink_bill(number: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> OrderRow:
    await _get(books, number)
    try:
        await po_.unlink_bill(books, number, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return await _row_safe(books, number)
