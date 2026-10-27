"""/books/bank/*: import bank statement CSVs and match their lines to posted ledger entries (F7).

Matching never posts anything; it records which ledger entry each bank line pays for. Lines nothing
matches can be marked as a transfer, ignored, or turned into an expense proposal for /review.

    POST /import                       upload a CSV (multipart "file"); the same file twice is a no-op
    GET  /statements                   imported statements
    GET  /lines?status=                every line (matched|suggested|unmatched|transfer|ignored)
    GET  /suggestions                  proposed matches (amount ±1p, date ±5 days, counterparty)
    GET  /unmatched                    open lines with no suggestion, each with a suggested action
    POST /lines/{id}/match             confirm: {"event_id": ...} or {"event_ids": [...]}
    POST /lines/{id}/unmatch           reopen a matched, transfer or ignored line
    POST /lines/{id}/transfer          mark as transfer
    POST /lines/{id}/ignore            ignore
    POST /lines/{id}/expense-proposal  create an expense proposal from the line
    GET  /summary                      counts and the "reconciled to" date
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date

from accnomos_ledger.bank import BankCsvError, BankLine, BankLineStatus, reconciled_to
from accnomos_ledger.matching import Match, settlement_pence
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.bank_actions import UnmatchedLine, create_expense_proposal, unmatched_lines
from app.books import BankImport, BankMatchError, Books, BankStatement
from app.routes_books import get_books, require_user
from app.schemas import Proposal

router = APIRouter(prefix="/books/bank", tags=["bank"])
MAX_CSV = 5 * 1024 * 1024


class MatchBody(BaseModel):
    event_id: str | None = None
    event_ids: list[str] | None = None  # one payment covering several entries


class EventBrief(BaseModel):
    id: str
    date: date
    counterparty: str | None
    amount_pence: int  # signed bank movement: purchases negative


class Suggestion(Match):
    """A proposed match with what the review table shows: the bank line and the ledger entries."""

    line: BankLine
    events: list[EventBrief]


class BankSummary(BaseModel):
    total: int
    matched: int
    suggested: int
    unmatched: int
    transfer: int
    ignored: int
    reconciled_to: date | None  # every line on or before this date is matched, a transfer or ignored


async def _line_action[T](action: Callable[[], Awaitable[T]]) -> T:
    """Run a per-line action: a missing line is 404, a refused change 409."""
    try:
        return await action()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank line") from exc
    except BankMatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/import", response_model=BankImport)
async def import_csv(
    file: UploadFile = File(...), books: Books = Depends(get_books), user: str = Depends(require_user),
) -> BankImport:
    data = await file.read(MAX_CSV + 1)
    if len(data) > MAX_CSV:
        raise HTTPException(status_code=413, detail="Bank statement CSV is over 5 MB")
    try:
        result = await books.import_bank_csv(data, file.filename or "statement.csv", user)
    except BankCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.duplicate_file:
        await books.rebuild_safely(user)
    return result


@router.get("/statements", response_model=list[BankStatement])
async def statements(books: Books = Depends(get_books)) -> list[BankStatement]:
    return await books.bank_statements()


@router.get("/lines", response_model=list[BankLine])
async def lines(status: BankLineStatus | None = None, books: Books = Depends(get_books)) -> list[BankLine]:
    return await books.list_bank_lines(status)


@router.get("/suggestions", response_model=list[Suggestion])
async def suggestions(books: Books = Depends(get_books)) -> list[Suggestion]:
    lines = await books.stored_bank_lines()
    by_line = {ln.id: ln for ln in lines}
    events = {e.id: e for e in await books.live_events()}
    return [
        Suggestion(**m.model_dump(), line=by_line[m.line_id], events=[
            EventBrief(id=e.id, date=e.date, counterparty=e.counterparty, amount_pence=settlement_pence(e))
            for e in (events[i] for i in m.event_ids)
        ])
        for m in await books.bank_suggestions(lines)
    ]


@router.get("/unmatched", response_model=list[UnmatchedLine])
async def unmatched(books: Books = Depends(get_books)) -> list[UnmatchedLine]:
    return await unmatched_lines(books)


@router.post("/lines/{line_id}/match", response_model=BankLine)
async def match(
    line_id: str, body: MatchBody, books: Books = Depends(get_books), user: str = Depends(require_user),
) -> BankLine:
    ids = body.event_ids or ([body.event_id] if body.event_id else [])
    return await _line_action(lambda: books.confirm_match(line_id, ids, user))


@router.post("/lines/{line_id}/unmatch", response_model=BankLine)
async def unmatch(line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> BankLine:
    return await _line_action(lambda: books.unmatch(line_id, user))


@router.post("/lines/{line_id}/transfer", response_model=BankLine)
async def transfer(line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> BankLine:
    return await _line_action(lambda: books.mark_line(line_id, "transfer", user))


@router.post("/lines/{line_id}/ignore", response_model=BankLine)
async def ignore(line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> BankLine:
    return await _line_action(lambda: books.mark_line(line_id, "ignored", user))


@router.post("/lines/{line_id}/expense-proposal", response_model=Proposal)
async def expense_proposal(
    line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user),
) -> Proposal:
    return await _line_action(lambda: create_expense_proposal(books, line_id, user))


@router.get("/summary", response_model=BankSummary)
async def summary(books: Books = Depends(get_books)) -> BankSummary:
    every = await books.list_bank_lines()
    count = {s: sum(ln.status == s for ln in every) for s in ("matched", "suggested", "unmatched", "transfer", "ignored")}
    return BankSummary(total=len(every), reconciled_to=reconciled_to(every), **count)
