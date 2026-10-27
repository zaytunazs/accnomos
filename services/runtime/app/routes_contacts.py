"""/contacts/*: customers and suppliers from the ledger (app/contacts.py), kept in the user's own OneDrive.

Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`; `X-User` for anything that writes).
`POST /contacts/import-outlook` also needs `Contacts.Read` on the token; the app asks for it only when the
user taps *Import from Outlook*. Money is never stored: totals, statements and aged balances are worked out
from the event files and bank matches on every request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from accnomos_connectors.base import ContactsProvider
from accnomos_connectors.msgraph import GraphContactsProvider
from app import contacts as cb
from app.ai.config import is_test_mode
from app.books import Books, now
from app.routes_books import get_books, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/contacts", tags=["contacts"])


async def get_address_book(request: Request) -> AsyncIterator[ContactsProvider]:
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    if is_test_mode():
        from app import testmode

        yield (await testmode.state()).contacts
        return
    provider = GraphContactsProvider(token)
    try:
        yield provider
    finally:
        await provider.aclose()


class ContactList(BaseModel):
    year_start: date
    today: date
    saved: bool  # contacts.json exists; until then the list is derived from the ledger only
    contacts: list[cb.ContactRow]


def _year(year_start: date | None) -> tuple[date, date]:
    today = now().date()
    return year_start or cb.uk_tax_year_start(today), today


@router.get("", response_model=ContactList)
async def list_contacts(
    year_start: date | None = Query(
        None, description="Start of the year for YTD totals; default 6 April (UK tax year)"
    ),
    books: Books = Depends(get_books),
) -> ContactList:
    contacts, ledger, saved = await cb.contact_book(books)
    start, today = _year(year_start)
    return ContactList(
        year_start=start, today=today, saved=saved, contacts=cb.with_totals(contacts, ledger, start, today)
    )


@router.post("/refresh", response_model=ContactList)
async def refresh(books: Books = Depends(get_books), user: str = Depends(require_user)) -> ContactList:
    """Add every counterparty in the ledger to contacts.json; fields the user edited are kept."""
    contacts, ledger = await cb.refresh(books, user)
    start, today = _year(None)
    return ContactList(
        year_start=start, today=today, saved=True, contacts=cb.with_totals(contacts, ledger, start, today)
    )


class ContactEdit(StrictBody):
    name: str | None = Field(default=None, max_length=200)
    kind: str | None = Field(default=None, max_length=20)
    vrn: str | None = Field(
        default=None, max_length=20
    )  # format checked in contacts.edit (GB/XI + 9 or 12 digits, GD/HA)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    default_category: str | None = Field(default=None, max_length=100)
    default_vat_code: str | None = Field(default=None, max_length=10)


@router.get("/aged", response_model=cb.AgedBalances)
async def aged(as_of: date | None = None, books: Books = Depends(get_books)) -> cb.AgedBalances:
    """Debtors and creditors: unpaid documents by age (0-30, 31-60, 61-90, 90+ days from the document date)."""
    contacts, ledger, _ = await cb.contact_book(books)
    return cb.aged(contacts, ledger, as_of or now().date())


@router.put("/{contact_id}", response_model=cb.Contact)
async def edit(
    contact_id: str,
    body: ContactEdit,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> cb.Contact:
    """Change the fields sent (null clears one); refreshing from the books never overwrites them."""
    edits: dict[str, Any] = body.model_dump(include=body.model_fields_set)
    try:
        return await cb.edit(books, contact_id, edits, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such contact") from exc
    except cb.ContactEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ImportBody(StrictBody):
    add_new: bool = False  # also add address-book entries that are not in the books yet (as customers)


@router.post("/import-outlook", response_model=cb.ImportResult)
async def import_outlook(
    body: ImportBody | None = None,
    books: Books = Depends(get_books),
    address_book: ContactsProvider = Depends(get_address_book),
    user: str = Depends(require_user),
) -> cb.ImportResult:
    """Fill in emails and phone numbers from Outlook contacts (read-only; nothing is written to Outlook)."""
    entries = await address_book.list_contacts()
    return await cb.import_outlook(books, entries, (body or ImportBody()).add_new, user)


@router.get("/{contact_id}/statement", response_model=cb.Statement)
async def statement(
    contact_id: str,
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    books: Books = Depends(get_books),
) -> cb.Statement:
    contacts, ledger, _ = await cb.contact_book(books)
    contact = next((c for c in contacts if c.id == contact_id), None)
    if contact is None:
        raise HTTPException(status_code=404, detail="No such contact")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="'from' is after 'to'")
    docs = cb.assign(contacts, cb.documents(ledger)).get(contact.id, [])
    return cb.statement(contact, docs, ledger, start, end)
