"""/vehicles and /mileage: vehicles, the business mileage log and approved mileage allowance claims.

Every amount is computed by code (app/mileage.py). A claim is an ordinary expense proposal that waits
in Review for the user; nothing here posts to the ledger.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app import mileage
from app.books import Books
from app.books import today as london_today
from app.mileage import LockedError, MileageEntry, MileageError, MileageSummary, Ownership, Vehicle, VehicleKind
from app.routes_books import get_books, require_user
from app.schemas import Proposal
from app.validation import Day

router = APIRouter(tags=["vehicles"])


class VehiclePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=60)
    registration: str | None = Field(default=None, max_length=12)
    kind: VehicleKind | None = None
    owned_by: Ownership | None = None
    active: bool | None = None


class EntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    vehicle_id: str | None = Field(default=None, max_length=32)
    date: Day | None = None
    from_: str | None = Field(default=None, alias="from", max_length=120)
    to: str | None = Field(default=None, max_length=120)
    miles: float | None = None
    purpose: str | None = Field(default=None, max_length=200)
    job_id: str | None = Field(default=None, max_length=32)


class ClaimResult(BaseModel):
    proposal: Proposal
    created: bool  # false: the claim already waiting in Review for this period (brought up to date)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail="Not found")
    return HTTPException(status_code=409 if isinstance(exc, LockedError) else 400, detail=str(exc))


def _tax_year(tax_year: str | None) -> str:
    ty = tax_year or mileage.tax_year_of(london_today())
    try:
        mileage.tax_year_bounds(ty)
    except MileageError as exc:
        raise _http(exc) from exc
    return ty


# --------------------------------------------------------------------------- #
# Vehicles
# --------------------------------------------------------------------------- #


@router.get("/vehicles", response_model=list[Vehicle])
async def vehicles(books: Books = Depends(get_books)) -> list[Vehicle]:
    try:
        return await mileage.load_vehicles(books)
    except MileageError as exc:
        raise _http(exc) from exc


@router.post("/vehicles", response_model=Vehicle)
async def add_vehicle(body: Vehicle, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Vehicle:
    try:
        return await mileage.add_vehicle(books, body, user)
    except MileageError as exc:
        raise _http(exc) from exc


@router.patch("/vehicles/{vehicle_id}", response_model=Vehicle)
async def update_vehicle(
    vehicle_id: str,
    body: VehiclePatch,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Vehicle:
    try:
        return await mileage.update_vehicle(books, vehicle_id, body.model_dump(exclude_unset=True), user)
    except (MileageError, FileNotFoundError) as exc:
        raise _http(exc) from exc


@router.delete("/vehicles/{vehicle_id}", response_model=Vehicle)
async def delete_vehicle(
    vehicle_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Vehicle:
    """Only a vehicle with no journeys and no tagged receipts; otherwise mark it inactive."""
    try:
        return await mileage.delete_vehicle(books, vehicle_id, user)
    except (MileageError, FileNotFoundError) as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------------------- #
# Mileage log
# --------------------------------------------------------------------------- #


@router.get("/mileage", response_model=list[MileageEntry])
async def entries(tax_year: str | None = None, books: Books = Depends(get_books)) -> list[MileageEntry]:
    """Journeys in a tax year (default: the current one), oldest first."""
    try:
        return await mileage.load_entries(books, _tax_year(tax_year))
    except MileageError as exc:
        raise _http(exc) from exc


@router.post("/mileage", response_model=MileageEntry)
async def add_entry(
    body: MileageEntry, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> MileageEntry:
    manual = body.model_copy(update={"source": "manual"})  # only code makes journeys from proposals
    try:
        return await mileage.add_entry(books, manual, user)
    except MileageError as exc:
        raise _http(exc) from exc


@router.get("/mileage/summary", response_model=MileageSummary)
async def summary(tax_year: str | None = None, books: Books = Depends(get_books)) -> MileageSummary:
    """Miles by vehicle, the allowance so far, when cars and vans passed 10,000 miles, quarter by quarter."""
    try:
        return await mileage.summary(books, _tax_year(tax_year))
    except MileageError as exc:
        raise _http(exc) from exc


@router.post("/mileage/propose-allowance", response_model=ClaimResult)
async def propose_allowance(
    tax_year: str | None = None,
    period: str | None = Query(None, description="Q1..Q4 of the tax year; default: the current quarter"),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> ClaimResult:
    """The period's allowance as an expense proposal in Review (idempotent per period)."""
    today = london_today()
    ty = _tax_year(tax_year)
    try:
        proposal, created = await mileage.propose_allowance(books, ty, period or mileage.quarter_of(today), today)
    except MileageError as exc:
        raise _http(exc) from exc
    if created:
        await books.rebuild_safely(f"user:{user}")
    return ClaimResult(proposal=proposal, created=created)


@router.patch("/mileage/{entry_id}", response_model=MileageEntry)
async def update_entry(
    entry_id: str,
    body: EntryPatch,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> MileageEntry:
    try:
        return await mileage.update_entry(books, entry_id, body.model_dump(exclude_unset=True, by_alias=True), user)
    except (MileageError, FileNotFoundError) as exc:
        raise _http(exc) from exc


@router.delete("/mileage/{entry_id}", response_model=MileageEntry)
async def delete_entry(
    entry_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> MileageEntry:
    try:
        return await mileage.delete_entry(books, entry_id, user)
    except (MileageError, FileNotFoundError) as exc:
        raise _http(exc) from exc
