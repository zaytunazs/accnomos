"""/sales/overview, /purchases/overview and /statements/*: figures worked out by code (app/overview.py,
app/statements.py). Sending a statement needs `Mail.Send` and a body with `confirm: true`."""

from __future__ import annotations

import base64
import hashlib
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from accnomos_connectors.base import MailSender
from app import invoicing as inv_
from app import overview as ov_
from app import statements as st_
from app.books import Books
from app.invoicing import InvoiceError
from app.routes_books import get_books, require_user
from app.routes_invoices import EmailDraft, SendBody, _confirmed, get_sender

router = APIRouter(tags=["overview"])


@router.get("/sales/overview", response_model=ov_.SalesOverview)
async def sales(books: Books = Depends(get_books)) -> ov_.SalesOverview:
    return await ov_.load_sales(books)


@router.get("/purchases/overview", response_model=ov_.PurchasesOverview)
async def purchases(books: Books = Depends(get_books)) -> ov_.PurchasesOverview:
    return await ov_.load_purchases(books)


async def _view(books: Books, contact_id: str, start: date | None, end: date | None) -> st_.StatementView:
    try:
        return await st_.build_statement(books, contact_id, start, end)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such contact") from exc
    except InvoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/statements/{contact_id}", response_model=st_.StatementView)
async def statement(
    contact_id: str, start: date | None = None, end: date | None = None, books: Books = Depends(get_books)
) -> st_.StatementView:
    return await _view(books, contact_id, start, end)


class StatementPdf(BaseModel):
    size: int
    sha256: str
    data_url: str
    email: EmailDraft
    problems: list[str]


@router.post("/statements/{contact_id}/pdf", response_model=StatementPdf)
async def statement_pdf(
    contact_id: str, start: date | None = None, end: date | None = None, books: Books = Depends(get_books)
) -> StatementPdf:
    view = await _view(books, contact_id, start, end)
    profile = await inv_.load_profile(books)
    data = st_.render(view, profile, await inv_.load_logo(books, profile))
    subject, body = st_.default_email(view, profile)
    return StatementPdf(
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data_url=f"data:application/pdf;base64,{base64.b64encode(data).decode()}",
        email=EmailDraft(to=view.email, subject=subject, body=body),
        problems=st_.send_problems(view, view.email or ""),
    )


@router.post("/statements/{contact_id}/send", response_model=st_.StatementView)
async def statement_send(
    contact_id: str,
    body: SendBody,
    start: date | None = None,
    end: date | None = None,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    sender: MailSender = Depends(get_sender),
) -> st_.StatementView:
    _confirmed(body.confirm)
    await _view(books, contact_id, start, end)
    try:
        return await st_.send_statement(
            books, sender, contact_id, user, start=start, end=end, to=body.to, subject=body.subject, body=body.body
        )
    except InvoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
