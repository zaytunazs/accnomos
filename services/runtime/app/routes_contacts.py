"""/contacts/*: customers and suppliers from the ledger (app/contacts.py), kept in the user's own OneDrive.

Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`; `X-User` for anything that writes).
`POST /contacts/import-outlook` also needs `Contacts.Read` on the token; the app asks for it only when the
user taps *Import from Outlook*. Money is never stored: totals, statements and aged balances are worked out
from the event files and bank matches on every request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from accnomos_connectors.base import ConflictError, ContactsProvider
from accnomos_connectors.msgraph import GraphContactsProvider
from app import company_lookup as lookup
from app import contacts as cb
from app.ai.config import AiConfig, is_test_mode
from app.books import Books
from app.books import today as london_today
from app.routes_books import get_books, require_user
from app.schemas import VatStatus
from app.taxyear import uk_tax_year_start
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
    today = london_today()
    return year_start or uk_tax_year_start(today), today


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


def _conflict(exc: ConflictError) -> HTTPException:
    """Two tabs wrote at the same instant twice over: ask for a reload, not a silent overwrite."""
    return HTTPException(status_code=409, detail="Someone else changed the contacts just now — reload and try again")


@router.post("/refresh", response_model=ContactList)
async def refresh(books: Books = Depends(get_books), user: str = Depends(require_user)) -> ContactList:
    """Add every counterparty in the ledger to contacts.json; fields the user edited are kept."""
    try:
        contacts, ledger = await cb.refresh(books, user)
    except ConflictError as exc:
        raise _conflict(exc) from exc
    start, today = _year(None)
    return ContactList(
        year_start=start, today=today, saved=True, contacts=cb.with_totals(contacts, ledger, start, today)
    )


class ContactEdit(StrictBody):
    name: str | None = Field(None, max_length=200)
    kind: str | None = Field(None, max_length=20)
    vrn: str | None = Field(None, max_length=20)  # format checked in contacts.edit (GB/XI + 9 or 12 digits, GD/HA)
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=500)
    default_category: str | None = Field(None, max_length=100)
    default_vat_code: str | None = Field(None, max_length=10)
    vat_status: VatStatus | None = None  # null means unknown: the VAT check asks again over £250
    terms_days: int | None = Field(None, ge=0, le=365)  # payment terms in days (ageing); null: the 30-day default
    company_number: str | None = Field(None, max_length=12)  # Companies House number, e.g. 01234567 or SC123456
    is_business: bool | None = None  # false: a consumer, so no statutory interest figures (app/chasing.py)
    chasing_opt_out: bool | None = None  # true: never draft reminders for this contact


class VatCheckBody(StrictBody):
    vrn: str = Field(min_length=9, max_length=20)
    name: str | None = Field(None, max_length=200)  # the supplier name on the receipt; default: the contact's
    contact_id: str | None = Field(None, max_length=16)
    requester: str | None = Field(None, max_length=20)  # the user's own VRN: HMRC then returns a consultation number
    refresh: bool = False  # check again even though the contact has a result for this number


class VatCheckResult(BaseModel):
    check: lookup.VatCheck
    name_differs: bool  # HMRC's registered name clearly differs from the supplier name: a warning, never a block
    contact_id: str | None  # the contact the result is now kept on (None: no contact has this number)
    cached: bool  # the contact already had this result; HMRC was not asked again


@router.post("/vat-check", response_model=VatCheckResult)
async def vat_check(
    body: VatCheckBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> VatCheckResult:
    """HMRC Check a UK VAT number (via the relay), only when the user taps *Check VAT number*. The answer is kept
    on the contact with that VAT number, so the next tap shows it without asking HMRC again."""
    try:
        digits = lookup.vat_digits(body.vrn)
    except lookup.BadQuery as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    vrn = f"GB{digits}"
    contacts, _, _ = await cb.contact_book(books)
    c = next((c for c in contacts if c.id == body.contact_id and c.vrn == vrn), None) or next(
        (c for c in contacts if c.vrn == vrn), None
    )
    name = body.name or (c.name if c else None)
    if c and c.vat_check and c.vat_check.vrn == vrn and not body.refresh:
        return VatCheckResult(
            check=c.vat_check, name_differs=lookup.names_differ(name, c.vat_check.name), contact_id=c.id, cached=True
        )
    check = await lookup.check_vat(vrn, body.requester)  # LookupFailed -> {"error", "detail"} (app/main.py)
    try:
        kept = await cb.record_vat_check(books, check, user, c.id) if c else None
    except ConflictError as exc:
        raise _conflict(exc) from exc
    differs = lookup.names_differ(name, check.name)
    return VatCheckResult(check=check, name_differs=differs, contact_id=kept.id if kept else None, cached=False)


@router.get("/aged", response_model=cb.AgedBalances)
async def aged(as_of: date | None = None, books: Books = Depends(get_books)) -> cb.AgedBalances:
    """Debtors and creditors: unpaid documents by age (0-30, 31-60, 61-90, 90+ days from the document date)."""
    contacts, ledger, _ = await cb.contact_book(books)
    return cb.aged(contacts, ledger, as_of or london_today())


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
    except ConflictError as exc:
        raise _conflict(exc) from exc


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
    try:
        return await cb.import_outlook(books, entries, (body or ImportBody()).add_new, user)
    except ConflictError as exc:
        raise _conflict(exc) from exc


class PhonePickedContact(StrictBody):
    """One contact the user picked with the phone's system picker."""

    name: str = Field(max_length=200)
    kind: Literal["customer", "supplier"] = "customer"
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=500)


class PhoneImportBody(StrictBody):
    contacts: list[PhonePickedContact] = Field(max_length=200)


@router.post("/import-phone", response_model=cb.ImportResult)
async def import_phone(
    body: PhoneImportBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> cb.ImportResult:
    """Save contacts the user picked with the phone's system contact picker
    (read-only on the phone: nothing is written back to it)."""
    try:
        return await cb.import_phone(
            books,
            [
                cb.PhonePickedContact(name=c.name, kind=c.kind, email=c.email, phone=c.phone, address=c.address)
                for c in body.contacts
            ],
            user,
        )
    except cb.ContactEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConflictError as exc:
        raise _conflict(exc) from exc


class DuplicateGroupOut(BaseModel):
    contact_ids: list[str]
    contacts: list[cb.Contact]
    evidence: list[str]
    blocked: bool = False  # different VAT numbers: code never suggests these as the same business
    ai: cb.DuplicateAI | None = None  # the model's view; null when it could not answer


class DuplicatesList(BaseModel):
    groups: list[DuplicateGroupOut]


@router.get("/duplicates", response_model=DuplicatesList)
async def duplicates(request: Request, books: Books = Depends(get_books)) -> DuplicatesList:
    """Possible duplicates by code (shared email, phone, VAT number or close name), each with the
    user's model's view alongside the code evidence. A model that cannot answer leaves `ai` unset."""
    contacts, _, _ = await cb.contact_book(books)
    groups = cb.find_duplicate_groups(contacts, await cb.load_not_same(books))
    try:
        cfg: AiConfig | None = AiConfig.from_headers(request.headers)
    except ValueError:
        cfg = None  # a bad AI setup hides the model's view, never the code evidence
    if cfg is not None:
        groups = await cb.judge_groups(groups, contacts, cfg)
    by_id = {c.id: c for c in contacts}
    return DuplicatesList(
        groups=[
            DuplicateGroupOut(
                contact_ids=g.contact_ids,
                contacts=[by_id[i] for i in g.contact_ids if i in by_id],
                evidence=g.evidence,
                blocked=g.blocked,
                ai=g.ai,
            )
            for g in groups
        ]
    )


class DismissBody(StrictBody):
    contact_ids: list[str] = Field(min_length=2, max_length=20)


@router.post("/duplicates/dismiss")
async def dismiss_duplicates(
    body: DismissBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, list[str]]:
    """Remember these contacts are not the same business; they are never suggested again."""
    try:
        await cb.remember_not_same(books, body.contact_ids, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"dismissed": sorted(set(body.contact_ids))}


class MergeBody(StrictBody):
    keep_id: str = Field(pattern=r"^[0-9a-f]{16}$", max_length=16)
    merge_ids: list[str] = Field(min_length=1, max_length=20)
    name: str | None = Field(None, max_length=200)  # the kept contact's name; blank keeps its own


class MergeOut(BaseModel):
    contact: cb.Contact
    merge_id: str  # POST /contacts/merge/{merge_id}/undo takes the merge back


@router.post("/merge", response_model=MergeOut)
async def merge_contacts(
    body: MergeBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> MergeOut:
    """Merge on approval, by code: combine details, alias the merged names, re-point references, audit."""
    try:
        kept, merge_id = await cb.merge(books, body.keep_id, body.merge_ids, (body.name or "").strip() or None, user)
    except cb.MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MergeOut(contact=kept, merge_id=merge_id)


@router.post("/merge/{merge_id}/undo", response_model=ContactList)
async def undo_merge(
    merge_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ContactList:
    """Take back a merge: the exact previous contacts.json entries and references are restored."""
    try:
        contacts = await cb.undo_merge(books, merge_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such merge (or it was already undone)") from exc
    _, ledger, saved = await cb.contact_book(books)
    start, today = _year(None)
    return ContactList(
        year_start=start, today=today, saved=saved, contacts=cb.with_totals(contacts, ledger, start, today)
    )


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
