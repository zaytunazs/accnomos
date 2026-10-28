"""/accounting/*: chart of accounts, manual journals, fixed assets, find and recode, tracking categories.

Same headers as /books/*. Every write needs `X-User` (the person who tapped the button). What posts to the ledger:
approving a journal (`POST /accounting/journals/{id}/approve`, also depreciation and disposal journals), voiding one,
and a recode sent with `confirm: true`. Everything else only changes settings files in `_System/Accounting/`.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import chart as ch
from app import fixed_assets as fa
from app import manual_journals as mj
from app import recode as rc
from app import tracking as tr
from app.books import Books
from app.books import today as current_date
from app.routes_books import get_books, require_user
from app.validation import Day, StrictBody

router = APIRouter(prefix="/accounting", tags=["accounting"])
STATE_ERRORS = (mj.JournalStateError,)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc) or "Not found")
    return HTTPException(status_code=409 if isinstance(exc, STATE_ERRORS) else 400, detail=str(exc))


ERRORS = (
    ch.ChartError,
    mj.JournalError,
    fa.AssetError,
    rc.RecodeError,
    tr.TrackingError,
    FileNotFoundError,
)

# --------------------------------------------------------------------------- #
# Chart of accounts
# --------------------------------------------------------------------------- #


class AccountRow(ch.Account):
    postings: int
    balance_pence: int  # debit − credit over every posted entry


class ChartView(BaseModel):
    accounts: list[AccountRow]
    saved: bool  # false: the standard chart, not saved to the books yet
    unlisted: list[str]  # accounts named on posted lines that are not in the chart
    types: dict[str, str] = ch.TYPE_LABELS
    ranges: dict[str, tuple[int, int]] = ch.RANGES


async def _chart_view(books: Books) -> ChartView:
    try:
        accounts, saved = await ch.load_chart(books)
    except ch.ChartError as exc:
        raise _http(exc) from exc
    events = await books.list_events()
    counts = ch.posting_counts(events)
    balance: dict[str, int] = {}
    for e in events:
        for ln in e.lines:
            balance[ln.account] = balance.get(ln.account, 0) + ln.debit - ln.credit
    labels = {a.label for a in accounts}
    return ChartView(
        accounts=[
            AccountRow(
                **a.model_dump(exclude={"label"}),
                postings=counts.get(a.label, 0),
                balance_pence=balance.get(a.label, 0),
            )
            for a in accounts
        ],
        saved=saved,
        unlisted=sorted(a for a in counts if a not in labels),
    )


@router.get("/accounts", response_model=ChartView)
async def accounts(books: Books = Depends(get_books)) -> ChartView:
    """The chart (the standard UK chart until you change it), with each account's postings and balance."""
    return await _chart_view(books)


async def _change_chart(books: Books, user: str, action: str, refs: dict, fn) -> ChartView:
    try:
        accounts, _ = await ch.load_chart(books)
        counts = ch.posting_counts(await books.list_events())
        result = fn(accounts, counts)
    except ERRORS as exc:
        raise _http(exc) from exc
    await ch.save_chart(books, accounts, user, action, {**refs, **(result or {})})
    return await _chart_view(books)


@router.post("/accounts", response_model=ChartView)
async def add_account(
    body: ch.AccountIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ChartView:
    return await _change_chart(
        books, user, "account_added", {"code": body.code}, lambda accs, _c: (ch.add_account(accs, body), None)[1]
    )


@router.patch("/accounts/{code}", response_model=ChartView)
async def edit_account(
    code: str, body: ch.AccountEdit, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ChartView:
    """Rename (only while unused), change type within its code range, VAT default, archive or restore."""
    return await _change_chart(
        books,
        user,
        "account_edited",
        {"code": code, "fields": sorted(body.model_dump(exclude_unset=True))},
        lambda accs, counts: (ch.edit_account(accs, code, body, counts), None)[1],
    )


@router.delete("/accounts/{code}", response_model=ChartView)
async def delete_account(code: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> ChartView:
    """Only an account with no postings that Accnomos does not post to itself."""
    return await _change_chart(
        books,
        user,
        "account_deleted",
        {"code": code},
        lambda accs, counts: (ch.delete_account(accs, code, counts), None)[1],
    )


@router.get("/accounts/export.csv")
async def export_accounts(books: Books = Depends(get_books)) -> Response:
    try:
        accounts, _ = await ch.load_chart(books)
    except ch.ChartError as exc:
        raise _http(exc) from exc
    return Response(
        "﻿" + ch.to_csv(accounts),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="chart-of-accounts.csv"'},
    )


class ImportBody(StrictBody):
    csv: str = Field(min_length=1, max_length=200_000)


class ImportView(BaseModel):
    result: ch.ImportResult
    chart: ChartView


@router.post("/accounts/import", response_model=ImportView)
async def import_accounts(
    body: ImportBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ImportView:
    """Add and update accounts from a CSV (code, name, type, vat_default, archived, description). All or nothing."""
    try:
        accounts, _ = await ch.load_chart(books)
    except ch.ChartError as exc:
        raise _http(exc) from exc
    result = ch.import_csv(accounts, body.csv, ch.posting_counts(await books.list_events()))
    if not result.errors and (result.added or result.updated):
        await ch.save_chart(
            books, accounts, user, "accounts_imported", {"added": len(result.added), "updated": len(result.updated)}
        )
    return ImportView(result=result, chart=await _chart_view(books))


# --------------------------------------------------------------------------- #
# Manual journals
# --------------------------------------------------------------------------- #


class JournalList(BaseModel):
    journals: list[mj.ManualJournal]


@router.get("/journals", response_model=JournalList)
async def journals(
    status: mj.JournalStatus | None = None,
    source: mj.JournalSource | None = None,
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    account: str | None = Query(None, max_length=90),
    q: str | None = Query(None, max_length=100),
    books: Books = Depends(get_books),
) -> JournalList:
    """Newest first, filtered by status, source (manual, depreciation, disposal), date, account code or text."""
    try:
        rows = await mj.list_journals(books)
    except mj.JournalError as exc:
        raise _http(exc) from exc
    rows = [j for j in rows if mj.matches(j, status=status, source=source, start=start, end=end, account=account, q=q)]
    return JournalList(journals=sorted(rows, key=lambda j: (j.date, j.number), reverse=True))


@router.post("/journals", response_model=mj.ManualJournal)
async def create_journal(
    body: mj.ManualJournalIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> mj.ManualJournal:
    """Save a draft (debits must equal credits). Posts nothing until approved."""
    try:
        return await mj.create_draft(books, body, user)
    except ERRORS as exc:
        raise _http(exc) from exc


@router.post("/journals/{journal_id}/approve", response_model=mj.ManualJournal)
async def approve_journal(
    journal_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> mj.ManualJournal:
    """Post the journal (and its auto-reversal, if it has a reversal date)."""
    try:
        return await mj.approve_journal(books, journal_id, user)
    except ERRORS as exc:
        raise _http(exc) from exc


@router.post("/journals/{journal_id}/discard", response_model=mj.ManualJournal)
async def discard_journal(
    journal_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> mj.ManualJournal:
    try:
        return await mj.discard_draft(books, journal_id, user)
    except ERRORS as exc:
        raise _http(exc) from exc


@router.post("/journals/{journal_id}/void", response_model=mj.ManualJournal)
async def void_journal(
    journal_id: str,
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> mj.ManualJournal:
    """Cancel a posted journal by appending its mirror entry; nothing is deleted."""
    try:
        return await mj.void_journal(books, journal_id, user, today or current_date())
    except ERRORS as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------------------- #
# Fixed assets
# --------------------------------------------------------------------------- #


class AssetList(BaseModel):
    assets: list[fa.AssetRow]
    reconciliation: list[fa.ReconRow]
    note: str = fa.CAPITAL_ALLOWANCES_NOTE
    types: dict[str, tuple[str, str]] = fa.TYPE_ACCOUNTS


@router.get("/assets", response_model=AssetList)
async def assets(books: Books = Depends(get_books)) -> AssetList:
    """The register with book values (from the posted journals), and the register-to-ledger reconciliation."""
    try:
        rows, journals = await fa.list_assets(books), await mj.list_journals(books)
    except ERRORS as exc:
        raise _http(exc) from exc
    return AssetList(
        assets=fa.rows(rows, journals), reconciliation=fa.reconciliation(rows, journals, await books.list_events())
    )


@router.post("/assets", response_model=fa.Asset)
async def register_asset(
    body: fa.AssetIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> fa.Asset:
    """Add an asset to the register. Posts nothing: its purchase is already in the books."""
    try:
        return await fa.register(books, body, user)
    except ERRORS as exc:
        raise _http(exc) from exc


@router.delete("/assets/{asset_id}", response_model=fa.Asset)
async def remove_asset(asset_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> fa.Asset:
    try:
        return await fa.remove(books, asset_id, user)
    except ERRORS as exc:
        raise _http(exc) from exc


class ScheduleView(BaseModel):
    asset: fa.AssetRow
    periods: list[dict]
    note: str = fa.CAPITAL_ALLOWANCES_NOTE


@router.get("/assets/{asset_id}/schedule", response_model=ScheduleView)
async def asset_schedule(asset_id: str, books: Books = Depends(get_books)) -> ScheduleView:
    """Every depreciation period for the asset's life, marked posted or not."""
    try:
        rows = fa.rows(await fa.list_assets(books), await mj.list_journals(books))
    except ERRORS as exc:
        raise _http(exc) from exc
    row = next((r for r in rows if r.id == asset_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="No such asset")
    return ScheduleView(asset=row, periods=fa.schedule_rows(row, row.state))


class RunBody(StrictBody):
    to: Day  # depreciation for every period ending by the end of this date's month


class RunResult(BaseModel):
    journal: mj.ManualJournal | None
    message: str


@router.post("/assets/depreciation", response_model=RunResult)
async def run_depreciation(
    body: RunBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> RunResult:
    """Propose the depreciation journal; it posts only when approved on Manual journals."""
    try:
        j = await fa.run_depreciation(books, body.to, user)
    except ERRORS as exc:
        raise _http(exc) from exc
    if j is None:
        return RunResult(journal=None, message="No depreciation is due to that date.")
    return RunResult(journal=j, message=f"Journal {j.number} is ready for you to approve.")


@router.post("/assets/{asset_id}/dispose", response_model=mj.ManualJournal)
async def dispose_asset(
    asset_id: str, body: fa.DisposeIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> mj.ManualJournal:
    """Propose the disposal journal (gain or loss worked out by code); it posts only when approved."""
    try:
        return await fa.dispose(books, asset_id, body, user)
    except ERRORS as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------------------- #
# Find and recode
# --------------------------------------------------------------------------- #


@router.get("/recode/search", response_model=rc.SearchResult)
async def recode_search(
    account: str | None = Query(None, max_length=90),
    contact: str | None = Query(None, max_length=120),
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    min_pence: int | None = Query(None, ge=0),
    max_pence: int | None = Query(None, ge=0),
    vat_code: Literal["S", "R", "Z", "E", "O", "N"] | None = None,
    books: Books = Depends(get_books),
) -> rc.SearchResult:
    try:
        return await rc.search(
            books,
            account=account,
            contact=contact,
            start=start,
            end=end,
            min_pence=min_pence,
            max_pence=max_pence,
            vat_code=vat_code,
        )
    except ERRORS as exc:
        raise _http(exc) from exc


@router.post("/recode", response_model=rc.RecodeResult)
async def recode(
    body: rc.RecodeIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> rc.RecodeResult:
    """Preview (`confirm: false`) or post the adjusting entries (`confirm: true`)."""
    try:
        return await rc.recode(books, body, user)
    except ERRORS as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------------------- #
# Tracking categories
# --------------------------------------------------------------------------- #


class TrackingView(tr.TrackingConfig):
    max_categories: int = tr.MAX_CATEGORIES
    used: list[tuple[str, str]] = []


async def _tracking_view(books: Books) -> TrackingView:
    try:
        cfg = await tr.load_tracking(books)
    except tr.TrackingError as exc:
        raise _http(exc) from exc
    return TrackingView(**cfg.model_dump(), used=sorted(tr.used_tags(await books.list_events())))


@router.get("/tracking", response_model=TrackingView)
async def tracking(books: Books = Depends(get_books)) -> TrackingView:
    return await _tracking_view(books)


async def _change_tracking(books: Books, user: str, action: str, refs: dict, fn) -> TrackingView:
    try:
        cfg = await tr.load_tracking(books)
        fn(cfg, tr.used_tags(await books.list_events()))
    except ERRORS as exc:
        raise _http(exc) from exc
    await tr.save_tracking(books, cfg, user, action, refs)
    return await _tracking_view(books)


@router.post("/tracking/categories", response_model=TrackingView)
async def add_category(
    body: tr.TrackingIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> TrackingView:
    return await _change_tracking(
        books, user, "tracking_category_added", {"name": body.name}, lambda cfg, _u: tr.add_category(cfg, body.name)
    )


@router.patch("/tracking/categories/{category_id}", response_model=TrackingView)
async def rename_category(
    category_id: str, body: tr.TrackingIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> TrackingView:
    return await _change_tracking(
        books,
        user,
        "tracking_category_renamed",
        {"category": category_id},
        lambda cfg, _u: tr.rename_category(cfg, category_id, body.name),
    )


@router.delete("/tracking/categories/{category_id}", response_model=TrackingView)
async def delete_category(
    category_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> TrackingView:
    return await _change_tracking(
        books,
        user,
        "tracking_category_deleted",
        {"category": category_id},
        lambda cfg, used: tr.delete_category(cfg, category_id, used),
    )


@router.post("/tracking/categories/{category_id}/options", response_model=TrackingView)
async def add_option(
    category_id: str, body: tr.TrackingIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> TrackingView:
    return await _change_tracking(
        books,
        user,
        "tracking_option_added",
        {"category": category_id, "name": body.name},
        lambda cfg, _u: tr.add_option(cfg, category_id, body.name),
    )


@router.patch("/tracking/categories/{category_id}/options/{option_id}", response_model=TrackingView)
async def edit_option(
    category_id: str,
    option_id: str,
    body: tr.OptionEdit,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> TrackingView:
    return await _change_tracking(
        books,
        user,
        "tracking_option_edited",
        {"category": category_id, "option": option_id},
        lambda cfg, _u: tr.edit_option(cfg, category_id, option_id, body.name, body.archived),
    )
