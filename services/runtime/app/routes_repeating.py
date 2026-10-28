"""/repeating/*: repeating invoices and bills (app/repeating.py).

Same headers as /invoices/*. There is nothing running for the user between visits, so a schedule is worked through
when `POST /repeating/process` is called: the app calls it when the Sales, Purchases or Repeating page opens, and a
timer of the user's own (a Power Automate flow, say) can call it with their token. It is safe to call repeatedly.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from accnomos_connectors.base import MailSender
from app import repeating as rp_
from app.books import Books
from app.invoicing import InvoiceError
from app.repeating import Frequency, ProcessResult, RepeatingIn, TemplateRow
from app.routes_books import get_books, require_user
from app.routes_invoices import get_sender
from app.validation import Day

router = APIRouter(prefix="/repeating", tags=["repeating"])


async def _get(books: Books, tid: str) -> rp_.Template:
    try:
        t = await rp_.get_template(books, tid)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such repeating item") from exc
    if t.deleted_at is not None:
        raise HTTPException(status_code=404, detail="No such repeating item")
    return t


@router.get("", response_model=list[TemplateRow])
async def list_templates(books: Books = Depends(get_books)) -> list[TemplateRow]:
    return [rp_.row(t) for t in await rp_.list_templates(books)]


@router.get("/dates", response_model=list[date])
async def dates(
    frequency: Frequency,
    start: Day,
    every: int = Query(1, ge=1, le=52),
    count: int = Query(6, ge=1, le=24),
    end: Day | None = None,
) -> list[date]:
    """The next `count` occurrence dates of a schedule, for the form to show before it is saved."""
    out = []
    for n in range(count):
        d = rp_.occurrence(start, frequency, every, n)
        if end is not None and d > end:
            break
        out.append(d)
    return out


@router.post("/process", response_model=ProcessResult)
async def process(
    books: Books = Depends(get_books),
    _user: str = Depends(require_user),
    sender: MailSender = Depends(get_sender),
) -> ProcessResult:
    """Make everything that has come due: drafts, or approved items for templates set to approve automatically."""
    return await rp_.process_due(books, sender)


@router.post("", response_model=TemplateRow)
async def create(
    body: RepeatingIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> TemplateRow:
    try:
        return rp_.row(await rp_.create_template(books, body, user))
    except InvoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{tid}", response_model=TemplateRow)
async def get(tid: str, books: Books = Depends(get_books)) -> TemplateRow:
    return rp_.row(await _get(books, tid))


@router.put("/{tid}", response_model=TemplateRow)
async def update(
    tid: str, body: RepeatingIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> TemplateRow:
    await _get(books, tid)
    try:
        return rp_.row(await rp_.update_template(books, tid, body, user))
    except InvoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{tid}", status_code=204)
async def delete(tid: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    """Stop the schedule. What it already made stays."""
    await _get(books, tid)
    await rp_.delete_template(books, tid, user)
