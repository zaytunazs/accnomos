"""/items/*: the products and services catalogue (app/items.py). Same headers as /invoices/*."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import items as it_
from app.books import Books
from app.books import today as london_today
from app.items import Item, ItemError, ItemFill, ItemIn, ItemNotFound
from app.routes_books import get_books, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/items", tags=["items"])


def _http(exc: ItemError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, ItemNotFound) else 400, detail=str(exc))


@router.get("", response_model=list[Item])
async def list_items(archived: bool = False, books: Books = Depends(get_books)) -> list[Item]:
    """The catalogue by code; archived items only with `?archived=true`."""
    return await it_.load_items(books, include_archived=archived)


class CsvExport(BaseModel):
    filename: str
    csv: str


@router.get("/export", response_model=CsvExport)
async def export(books: Books = Depends(get_books)) -> CsvExport:
    """Every item, archived too, as CSV text (exact pounds and pence) for the browser to save."""
    return CsvExport(
        filename=f"accnomos-items-{london_today().isoformat()}.csv", csv=it_.export_csv(await it_.load_items(books))
    )


class CsvImport(StrictBody):
    csv: str = Field(max_length=it_.MAX_CSV_BYTES)
    update_existing: bool = True


@router.post("/import", response_model=it_.ImportResult)
async def import_items(
    body: CsvImport, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> it_.ImportResult:
    """Add items from CSV text: our own columns or Xero's inventory export. Bad rows are skipped and listed."""
    try:
        return await it_.import_csv(books, body.csv, user, update_existing=body.update_existing)
    except ItemError as exc:
        raise _http(exc) from exc


@router.post("", response_model=Item)
async def create(body: ItemIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Item:
    try:
        return await it_.create_item(books, body, user)
    except ItemError as exc:
        raise _http(exc) from exc


@router.get("/{code}", response_model=Item)
async def get(code: str, books: Books = Depends(get_books)) -> Item:
    try:
        return await it_.get_item(books, code)
    except ItemError as exc:
        raise _http(exc) from exc


@router.put("/{code}", response_model=Item)
async def update(code: str, body: ItemIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Item:
    try:
        return await it_.update_item(books, code, body, user)
    except ItemError as exc:
        raise _http(exc) from exc


@router.delete("/{code}", response_model=Item)
async def archive(code: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Item:
    """Archive (nothing is deleted; documents already written keep their lines). PUT with archived=false restores it."""
    try:
        return await it_.archive_item(books, code, user)
    except ItemError as exc:
        raise _http(exc) from exc


@router.get("/{code}/line", response_model=ItemFill)
async def line(
    code: str,
    side: it_.Side = "sale",
    quantity: str = Query("1", max_length=12),
    books: Books = Depends(get_books),
) -> ItemFill:
    """What picking the item puts on a line: sale price for invoices and quotes, purchase price for purchase orders."""
    try:
        qty = Decimal(quantity)
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail="quantity is a number") from exc
    if not (0 < qty <= 1_000_000) or qty != qty.quantize(Decimal("0.001")):
        raise HTTPException(status_code=400, detail="quantity is above 0, with up to 3 decimals")
    try:
        return it_.fill_line(await it_.get_item(books, code), side, format(qty.normalize(), "f"))
    except ItemError as exc:
        raise _http(exc) from exc
