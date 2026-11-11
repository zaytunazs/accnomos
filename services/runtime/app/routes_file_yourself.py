"""/books/file-it-yourself/*: the "File it yourself" files (app/file_yourself.py) for the VAT and Income Tax pages.

    GET  /books/file-it-yourself/vat                ?period=…&vrn=…&format=json|csv|xlsx  the VAT bridging file
    GET  /books/file-it-yourself/itsa-quarterly     ?tax_year=…&period_end=…&format=…     Income Tax quarterly figures
    GET  /books/file-it-yourself/sa103              ?tax_year=…&form=auto|short|full&format=…  SA103S / SA103F
    POST /books/file-it-yourself/{kind}/save        same query; the file saved in 07 Reports (never overwriting),
                                                    audited. Needs X-User

`format=json` is what the page shows on screen (the same cells, the guidance and the layout). The VAT figures are
the VAT page's own (app/routes_vat.py, under the saved VAT scheme); the Income Tax figures are app/routes_itsa.py's
cumulative summary on the basis in Settings. Nothing here calls HMRC or posts to the ledger.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app import cash_basis as cb
from app import file_yourself as fy
from app import itsa
from app.books import Books
from app.books import today as current_date
from app.paths import REPORTS
from app.routes_books import get_books, require_feature, require_uk, require_user
from app.routes_itsa import _summary
from app.routes_vat import vat_return
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/books/file-it-yourself", tags=["file-it-yourself"])

Fmt = Literal["json", "csv", "xlsx"]
FileFmt = Literal["csv", "xlsx"]
Kind = Literal["vat", "itsa-quarterly", "sa103"]
VRN = re.compile(r"^(?:GB)?(\d{9})$")
TODAY = Query(None, description="for previews and tests; defaults to today")
PeriodQuery = Query(
    None,
    pattern=r"^\d{4}-(Q[1-4]|\d{2}|Y\d{2})$",
    description="2026-Q4 (quarterly), 2026-11 (monthly) or 2026-Y01 (annual), as /books/vat takes it",
)
TaxYearQuery = Query(None, pattern=r"^20\d{2}-\d{2}$")


class Saved(BaseModel):
    path: str
    name: str
    size: int
    web_url: str | None
    format: str


def clean_vrn(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    m = VRN.fullmatch(re.sub(r"[\s.\-]", "", raw.upper()))
    if not m:
        raise HTTPException(422, "vrn must be a UK VAT registration number: 9 digits, GB optional")
    return m.group(1)


def quarter_end(today: date) -> tuple[str, date]:
    """The latest standard MTD quarter end (5 Jul, 5 Oct, 5 Jan, 5 Apr) on or before `today`, and its tax year."""
    ty = itsa.tax_year_of(today)
    start, end = itsa.tax_year_bounds(ty)
    ends = [date(start.year, 7, 5), date(start.year, 10, 5), date(end.year, 1, 5), end]
    done = [e for e in ends if e <= today]
    if done:
        return ty, done[-1]
    prev = itsa.tax_year_of(start.replace(day=5))  # before the first quarter ends: last year's whole year
    return prev, itsa.tax_year_bounds(prev)[1]


async def vat_sheet(
    books: Books,
    cycle: VatCycle,
    period: str | None,
    start: date | None,
    end: date | None,
    period_key: str | None,
    vrn: str | None,
    today: date | None,
) -> fy.Sheet:
    view = await vat_return(
        period_start=start,
        period_end=end,
        period=period,
        start=None,
        end=None,
        period_key=period_key,
        today=today,
        cycle=cycle,
        books=books,
    )
    from app.exports.vat_reports import BOXES  # HMRC's own box headings (VAT Notice 700/12)

    return fy.vat_bridging(
        {b.box: b.amount for b in view.boxes},
        dict(BOXES),
        view.start,
        view.end,
        view.period_key,
        clean_vrn(vrn),
        view.box5_direction,
    )


async def itsa_sheet(
    books: Books, tax_year: str | None, period_end: date | None, basis: cb.Basis | None, today: date | None
) -> fy.Sheet:
    if tax_year is None and period_end is None:
        tax_year, period_end = quarter_end(today or current_date())
    elif tax_year is None:
        assert period_end is not None
        tax_year = itsa.tax_year_of(period_end)
    elif period_end is None:
        _, year_end = _bounds(tax_year)
        period_end = min(year_end, today or current_date())
    return fy.itsa_quarterly(await _summary(books, tax_year, period_end, basis))


async def sa_sheet(
    books: Books,
    tax_year: str | None,
    period_end: date | None,
    form: fy.FormChoice,
    basis: cb.Basis | None,
    today: date | None,
) -> fy.Sheet:
    day = today or current_date()
    if tax_year is None:
        tax_year = itsa.tax_year_of(period_end or itsa.tax_year_bounds(itsa.tax_year_of(day))[0].replace(day=5))
    _, year_end = _bounds(tax_year)
    return fy.sa103(await _summary(books, tax_year, period_end or year_end, basis), form)


def _bounds(tax_year: str) -> tuple[date, date]:
    try:
        return itsa.tax_year_bounds(tax_year)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


def _out(sheet: fy.Sheet, fmt: Fmt) -> Any:
    if fmt == "json":
        return sheet.as_json()
    data = fy.render(sheet, fmt)
    return Response(
        data,
        media_type=fy.MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{sheet.filename}.{fmt}"', "Cache-Control": "no-store"},
    )


async def _save(books: Books, user: str, kind: Kind, sheet: fy.Sheet, fmt: FileFmt) -> Saved:
    data = fy.render(sheet, fmt)
    await books.storage.ensure_folder(REPORTS)
    path = await books.free_path(REPORTS, f"{sheet.filename}.{fmt}")
    ref = await books.storage.write(path, data)
    await books.audit(
        f"user:{user}",
        "report_saved",
        {"report": f"file-it-yourself-{kind}", "format": fmt, "path": path, "file": path},
    )
    return Saved(path=path, name=path.rsplit("/", 1)[1], size=ref.size, web_url=ref.web_url, format=fmt)


# --- VAT ---------------------------------------------------------------------------------------------------------


@router.get("/vat", dependencies=[require_feature("vat")])
async def vat_file(
    period: str | None = PeriodQuery,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    period_key: str | None = Query(None, pattern=r"^[A-Za-z0-9#]{4}$"),
    vrn: str | None = Query(None, max_length=20),
    format: Fmt = "json",
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> Any:
    """The VAT bridging file for a period: B1:B9 hold boxes 1-9 (layout in app/file_yourself.py)."""
    return _out(await vat_sheet(books, cycle, period, period_start, period_end, period_key, vrn, today), format)


@router.post("/vat/save", response_model=Saved, dependencies=[require_feature("vat")])
async def vat_save(
    format: FileFmt = Query(...),
    period: str | None = PeriodQuery,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    period_key: str | None = Query(None, pattern=r"^[A-Za-z0-9#]{4}$"),
    vrn: str | None = Query(None, max_length=20),
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Saved:
    sheet = await vat_sheet(books, cycle, period, period_start, period_end, period_key, vrn, today)
    return await _save(books, user, "vat", sheet, format)


# --- Income Tax --------------------------------------------------------------------------------------------------


@router.get("/itsa-quarterly", dependencies=[require_uk()])
async def itsa_file(
    tax_year: str | None = TaxYearQuery,
    period_end: date | None = Query(None, description="default: the latest quarter end (5 Jul, 5 Oct, 5 Jan, 5 Apr)"),
    basis: cb.Basis | None = Query(None),
    format: Fmt = "json",
    today: date | None = TODAY,
    books: Books = Depends(get_books),
) -> Any:
    """Cumulative figures from 6 April to `period_end` under HMRC's API field names, with the SA103F boxes."""
    return _out(await itsa_sheet(books, tax_year, period_end, basis, today), format)


@router.post("/itsa-quarterly/save", response_model=Saved, dependencies=[require_uk()])
async def itsa_save(
    format: FileFmt = Query(...),
    tax_year: str | None = TaxYearQuery,
    period_end: date | None = Query(None),
    basis: cb.Basis | None = Query(None),
    today: date | None = TODAY,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Saved:
    return await _save(
        books, user, "itsa-quarterly", await itsa_sheet(books, tax_year, period_end, basis, today), format
    )


@router.get("/sa103", dependencies=[require_uk()])
async def sa103_file(
    tax_year: str | None = Query(None, pattern=r"^20\d{2}-\d{2}$", description="default: the last tax year ended"),
    period_end: date | None = Query(None, description="default: 5 April, the end of the tax year"),
    form: fy.FormChoice = Query("auto", description="auto (short under £90,000 turnover), short or full"),
    basis: cb.Basis | None = Query(None),
    format: Fmt = "json",
    today: date | None = TODAY,
    books: Books = Depends(get_books),
) -> Any:
    """The SA103S or SA103F boxes for a tax year, for typing into HMRC's online Self Assessment."""
    return _out(await sa_sheet(books, tax_year, period_end, form, basis, today), format)


@router.post("/sa103/save", response_model=Saved, dependencies=[require_uk()])
async def sa103_save(
    format: FileFmt = Query(...),
    tax_year: str | None = Query(None, pattern=r"^20\d{2}-\d{2}$"),
    period_end: date | None = Query(None),
    form: fy.FormChoice = Query("auto"),
    basis: cb.Basis | None = Query(None),
    today: date | None = TODAY,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Saved:
    return await _save(books, user, "sa103", await sa_sheet(books, tax_year, period_end, form, basis, today), format)
