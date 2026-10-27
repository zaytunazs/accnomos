"""/books/bank/*: import bank statement CSVs and match their lines to posted ledger entries (F7).

Matching never posts anything; it records which ledger entry each bank line pays for.
"""

from __future__ import annotations

from accnomos_ledger.bank import BankCsvError, BankLine, BankLineStatus
from accnomos_ledger.matching import Match
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.books import BankImport, BankMatchError, Books
from app.routes_books import get_books, require_user
from app.validation import StrictBody, UnsafeName, check_name

router = APIRouter(prefix="/books/bank", tags=["bank"])
MAX_CSV = 5 * 1024 * 1024


class MatchBody(StrictBody):
    event_id: str | None = Field(None, max_length=64)
    event_ids: list[str] | None = Field(None, max_length=200)  # one payment covering several entries


class BankSummary(BaseModel):
    total: int
    matched: int
    suggested: int
    unmatched: int


def _not_found(exc: FileNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail="No such bank line")


@router.post("/import", response_model=BankImport)
async def import_csv(
    file: UploadFile = File(...), books: Books = Depends(get_books), user: str = Depends(require_user),
) -> BankImport:
    try:
        name = check_name(file.filename) if file.filename else "statement.csv"
    except UnsafeName as exc:
        raise HTTPException(status_code=400, detail=f"Bad file name: {exc}") from exc
    data = await file.read(MAX_CSV + 1)
    if len(data) > MAX_CSV:
        raise HTTPException(status_code=413, detail="Bank statement CSV is over 5 MB")
    try:
        result = await books.import_bank_csv(data, name, user)
    except BankCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.duplicate_file:
        await books.rebuild_safely(user)
    return result


@router.get("/lines", response_model=list[BankLine])
async def lines(status: BankLineStatus | None = None, books: Books = Depends(get_books)) -> list[BankLine]:
    return await books.list_bank_lines(status)


@router.get("/suggestions", response_model=list[Match])
async def suggestions(books: Books = Depends(get_books)) -> list[Match]:
    return await books.bank_suggestions()


@router.post("/lines/{line_id}/match", response_model=BankLine)
async def match(
    line_id: str, body: MatchBody, books: Books = Depends(get_books), user: str = Depends(require_user),
) -> BankLine:
    ids = body.event_ids or ([body.event_id] if body.event_id else [])
    try:
        return await books.confirm_match(line_id, ids, user)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except BankMatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/lines/{line_id}/unmatch", response_model=BankLine)
async def unmatch(line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> BankLine:
    try:
        return await books.unmatch(line_id, user)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    except BankMatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/summary", response_model=BankSummary)
async def summary(books: Books = Depends(get_books)) -> BankSummary:
    every = await books.list_bank_lines()
    count = {s: sum(ln.status == s for ln in every) for s in ("matched", "suggested", "unmatched")}
    return BankSummary(total=len(every), **count)
