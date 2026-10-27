"""/payroll/runs: pay runs prepared from timesheets for the owner's payroll provider (app/payroll.py).

Estimates only — your payroll provider calculates the actual tax and NI. Nothing here files with HMRC.
Only confirm (with the actual figures typed in) posts to the ledger.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import payroll
from app import payroll_rates as R
from app.approve import ApprovalError
from app.books import Books
from app.payroll import LineEdit, PayrollConflict, PayrollError, PayRun
from app.routes_books import get_books, require_user

router = APIRouter(tags=["payroll"])


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str
    pay_date: dt.date | None = None


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[LineEdit] = Field(max_length=500)
    pay_date: dt.date | None = None


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_gross_pence: int = Field(gt=0, le=100_000_000)
    actual_er_ni_pence: int = Field(ge=0, le=100_000_000)


class ExportResult(BaseModel):
    path: str
    csv: str
    estimate: str = R.ESTIMATE_LABEL


class RunList(BaseModel):
    runs: list[PayRun]
    estimate: str = R.ESTIMATE_LABEL
    limits: list[str] = list(R.LIMITS)
    tax_year: str = R.TAX_YEAR
    source_url: str = R.SOURCE_URL


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc) or "Not found")
    return HTTPException(status_code=409 if isinstance(exc, (PayrollConflict, ApprovalError)) else 400, detail=str(exc))


@router.get("/payroll/runs", response_model=RunList)
async def runs(books: Books = Depends(get_books)) -> RunList:
    try:
        return RunList(runs=await payroll.list_runs(books))
    except ValueError as exc:  # a hand-edited run file
        raise _http(exc) from exc


@router.post("/payroll/runs/prepare", response_model=PayRun)
async def prepare(body: PrepareBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> PayRun:
    """The month's timesheet hours × hourly rates, with estimated deductions. Replaces a draft."""
    try:
        return await payroll.prepare(books, body.period, body.pay_date, user)
    except PayrollError as exc:
        raise _http(exc) from exc


@router.get("/payroll/runs/{period}", response_model=PayRun)
async def get_run(period: str, books: Books = Depends(get_books)) -> PayRun:
    try:
        return await payroll.get_run(books, period)
    except (PayrollError, FileNotFoundError) as exc:
        raise _http(exc) from exc


@router.put("/payroll/runs/{period}", response_model=PayRun)
async def edit(period: str, body: EditBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> PayRun:
    try:
        return await payroll.update(books, period, body.lines, body.pay_date, user)
    except (PayrollError, FileNotFoundError) as exc:
        raise _http(exc) from exc


@router.post("/payroll/runs/{period}/export", response_model=ExportResult)
async def export(period: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> ExportResult:
    """Saves 04 Payroll/{period}.csv and returns it, for the payroll provider."""
    try:
        path, text = await payroll.export(books, period, user)
    except (PayrollError, FileNotFoundError) as exc:
        raise _http(exc) from exc
    return ExportResult(path=path, csv=text)


@router.post("/payroll/runs/{period}/confirm", response_model=PayRun)
async def confirm(
    period: str, body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user),
) -> PayRun:
    """Posts the actual gross pay and employer NI (from the payroll provider) as staff costs."""
    try:
        return await payroll.confirm(books, period, body.actual_gross_pence, body.actual_er_ni_pence, user)
    except (PayrollError, FileNotFoundError) as exc:
        raise _http(exc) from exc


@router.post("/payroll/runs/{period}/reopen", response_model=PayRun)
async def reopen(period: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> PayRun:
    """Reverses the confirmed run's ledger entries and puts it back to draft."""
    try:
        return await payroll.reopen(books, period, user)
    except (PayrollError, FileNotFoundError, ApprovalError) as exc:
        raise _http(exc) from exc
