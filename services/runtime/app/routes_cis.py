"""/cis/*: the Construction Industry Scheme and the VAT domestic reverse charge (app/cis.py, app/cis_readings.py).

Same headers as /books/*. Every write needs `X-User`; reading a document also uses the AI headers
(`X-AI-Mode`, ...), like scanning a receipt. Nothing here talks to HMRC: verification and the monthly return are
filed by the user through HMRC's CIS online service or CIS software (the return says so).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import cis
from app import cis_readings as cr
from app import invoicing as inv_
from app.ai.config import ai_config_from_request
from app.ai.extract import ExtractionError
from app.books import Books
from app.books import today as london_today
from app.formats import FormatError
from app.invoicing import InvoiceDraft, InvoiceError
from app.paths import INBOX, SALES
from app.pdf import render_invoice
from app.reports import is_sample
from app.routes_books import get_books, require_user
from app.validation import StrictBody, UnsafeName

router = APIRouter(prefix="/cis", tags=["cis"])
QUOTES = f"{SALES}/quotes"


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail="Not found")
    if isinstance(exc, inv_.InvoiceStateError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


class Deadline(BaseModel):
    tax_month_start: date
    tax_month_end: date
    statements_due: date
    return_due: date
    payment_due: date


class Overview(BaseModel):
    settings: cis.CisSettings
    rate: int
    status_label: str
    rates: dict[str, int] = cis.RATES
    tax_month: Deadline  # the tax month we are in
    last_tax_month: Deadline  # the one whose return and statements are due now
    tax_year: str
    pending_readings: int
    source_url: str = cis.SOURCE_URL
    checked: str = cis.CHECKED
    not_submitted: str = cis.NOT_SUBMITTED


def _deadline(day: date) -> Deadline:
    start, end = cis.tax_month(day)
    return Deadline(
        tax_month_start=start,
        tax_month_end=end,
        statements_due=cis.return_due(end),
        return_due=cis.return_due(end),
        payment_due=cis.payment_due(end),
    )


@router.get("", response_model=Overview)
async def overview(
    today: date | None = Query(None, description="for tests; defaults to today"), books: Books = Depends(get_books)
) -> Overview:
    day = today or london_today()
    settings = await cis.load_settings(books)
    this = _deadline(day)
    return Overview(
        settings=settings,
        rate=settings.rate,
        status_label=cis.STATUS_LABELS[settings.status],
        tax_month=this,
        last_tax_month=_deadline(this.tax_month_start.replace(day=5)),
        tax_year=cis.tax_year_label(day),
        pending_readings=len(await cr.list_readings(books, "pending")),
    )


@router.put("/settings", response_model=cis.CisSettings)
async def put_settings(
    body: cis.CisSettings, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cis.CisSettings:
    return await cis.save_settings(books, body, user)


# --------------------------------------------------------------------------- subcontractor side


@router.get("/statements", response_model=list[cis.StatementView])
async def list_statements(books: Books = Depends(get_books)) -> list[cis.StatementView]:
    settings = await cis.load_settings(books)
    return cis.statement_views(await cis.statements(books), await books.list_events(), settings)


@router.post("/statements", response_model=cis.Statement)
async def add_statement(
    body: cis.StatementIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cis.Statement:
    try:
        return await cis.add_statement(books, body, user)
    except cis.CisError as exc:
        raise _http(exc) from exc


@router.delete("/statements/{statement_id}")
async def remove_statement(
    statement_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, bool]:
    try:
        await cis.remove_statement(books, statement_id, user)
    except FileNotFoundError as exc:
        raise _http(exc) from exc
    return {"ok": True}


class ReadBody(StrictBody):
    name: str = Field(min_length=1, max_length=200)  # a file in 00 Inbox


@router.post("/read", response_model=cr.Reading)
async def read_document(
    body: ReadBody, request: Request, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cr.Reading:
    """Read a CIS statement or a reverse-charge invoice in 00 Inbox with the user's AI; the result waits for them."""
    try:
        return await cr.read_document(books, body.name, ai_config_from_request(request), user)
    except (UnsafeName, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=f"No such file in {INBOX}") from exc
    except FormatError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ExtractionError as exc:
        raise HTTPException(status_code=502, detail=f"Your AI could not read it: {exc}") from exc


@router.get("/readings", response_model=list[cr.Reading])
async def list_readings(
    status: cr.ReadingStatus | None = Query(None), books: Books = Depends(get_books)
) -> list[cr.Reading]:
    return await cr.list_readings(books, status)


@router.post("/readings/{reading_id}/approve", response_model=cr.Reading)
async def approve_reading(
    reading_id: str, body: cr.DecideBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cr.Reading:
    try:
        return await cr.approve(books, reading_id, body, user)
    except (FileNotFoundError, cis.CisError) as exc:
        raise _http(exc) from exc


@router.post("/readings/{reading_id}/reject", response_model=cr.Reading)
async def reject_reading(
    reading_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cr.Reading:
    try:
        return await cr.reject(books, reading_id, user)
    except (FileNotFoundError, cis.CisError) as exc:
        raise _http(exc) from exc


class Posted(BaseModel):
    event_id: str
    reverse_charge_vat_pence: int


@router.post("/reverse-charge/bills", response_model=Posted)
async def add_reverse_charge_bill(
    body: cr.ReverseChargeBillIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Posted:
    """A subcontractor's reverse-charge invoice typed in: posted once (same supplier, number, date and net)."""
    try:
        event_id = await cr.post_bill(books, body, user, cr.typed_bill_key(body), [])
    except cis.CisError as exc:
        raise _http(exc) from exc
    return Posted(event_id=event_id, reverse_charge_vat_pence=body.reverse_charge_vat_pence)


@router.get("/year", response_model=cis.YearTotals)
async def year(
    tax_year: str | None = Query(None, max_length=7, description="e.g. 2026-27; default: the one we are in"),
    books: Books = Depends(get_books),
) -> cis.YearTotals:
    label = tax_year or cis.tax_year_label(london_today())
    try:
        cis.tax_year_bounds(label)
    except cis.CisError as exc:
        raise _http(exc) from exc
    return cis.year_totals(
        label,
        await cis.statements(books),
        await books.list_events(),
        await cis.load_settings(books),
        await live_payments(books),
    )


# --------------------------------------------------------------------------- invoices and quotes


class QuoteBody(StrictBody):
    draft: InvoiceDraft
    valid_days: int = Field(30, ge=1, le=365)


@router.post("/quote", response_class=Response)
async def quote(body: QuoteBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Response:
    """A quote PDF priced like an invoice (CIS deduction on labour, reverse charge wording), saved in
    03 Sales/quotes. A quote posts nothing and takes no invoice number."""
    profile = await inv_.load_profile(books)
    issue = body.draft.issue_date or london_today()
    draft = body.draft.model_copy(
        update={"issue_date": issue, "due_date": date.fromordinal(issue.toordinal() + body.valid_days)}
    )
    number = f"Q-{issue:%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"
    try:
        inv = inv_.build_invoice(number, draft, profile, user, cis_status=await inv_.cis_status_for(books, draft))
    except InvoiceError as exc:
        raise _http(exc) from exc
    pdf = render_invoice(inv, profile, await inv_.load_logo(books, profile), quote=True)
    path = f"{QUOTES}/{number}.pdf"
    await books.storage.ensure_folder(QUOTES)
    await books.storage.write(path, pdf)
    await books.audit(f"user:{user}", "quote_saved", {"quote": number, "path": path, "total_pence": inv.total_pence})
    return Response(pdf, media_type="application/pdf", headers={"X-Quote-Path": path, "X-Quote-Number": number})


class ReverseChargeGuide(BaseModel):
    applies_when: list[str]
    not_when: list[str]
    end_user_wording: str
    invoice_wording: str
    boxes_supplier: str
    boxes_customer: str
    schemes: list[str]
    source_urls: list[str]
    checked: str = cis.CHECKED


@router.get("/reverse-charge", response_model=ReverseChargeGuide)
async def reverse_charge_guide() -> ReverseChargeGuide:
    """What the app tells the user about the reverse charge, from HMRC's guidance (no account needed)."""
    return ReverseChargeGuide(
        applies_when=[
            "You and your customer are both VAT-registered in the UK",
            "The work is standard- or reduced-rated and reported under CIS (building and construction services)",
            "Your customer has not told you in writing that they are an end user or an intermediary supplier",
        ],
        not_when=[
            "Private (non-VAT-registered) customers, and end users or intermediaries who told you so in writing",
            "Zero-rated work (for example most new-build housing)",
            "Supplies of staff by an employment business, and work CIS leaves out (architects, surveyors, carpet "
            "fitting, delivering materials, signwriting, security systems, seating, blinds and shutters)",
            "When the CIS part of a single supply is 5% or less of its value, if both sides agreed from the start",
        ],
        end_user_wording=(
            "We are an end user for the purposes of section 55A VAT Act 1994 reverse charge for building and "
            "construction services. Issue us with a normal VAT invoice, with VAT charged at the appropriate rate. "
            "We will not account for the reverse charge."
        ),
        invoice_wording=inv_.REVERSE_CHARGE_WORDING,
        boxes_supplier="Supplier: the net in box 6; no output VAT in box 1.",
        boxes_customer=(
            "Customer: the VAT in box 1 and again in box 4 (if fully recoverable); the net in box 7, never in box 6."
        ),
        schemes=[
            "Flat Rate Scheme: reverse-charge sales are left out of the flat-rate turnover; on reverse-charge "
            "purchases account for and reclaim the VAT on the same return.",
            "Cash Accounting Scheme: cannot be used for reverse-charge supplies made or received.",
        ],
        source_urls=[
            "https://www.gov.uk/guidance/vat-domestic-reverse-charge-for-building-and-construction-services",
            "https://www.gov.uk/guidance/vat-reverse-charge-technical-guide",
        ],
    )


# --------------------------------------------------------------------------- contractor side


@router.get("/subcontractors", response_model=list[cis.Subcontractor])
async def list_subcontractors(books: Books = Depends(get_books)) -> list[cis.Subcontractor]:
    return sorted(await cis.subcontractors(books), key=lambda s: s.name.lower())


@router.post("/subcontractors", response_model=cis.Subcontractor)
async def add_subcontractor(
    body: cis.SubcontractorIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cis.Subcontractor:
    try:
        return await cis.save_subcontractor(books, body, user)
    except cis.CisError as exc:
        raise _http(exc) from exc


@router.put("/subcontractors/{sub_id}", response_model=cis.Subcontractor)
async def edit_subcontractor(
    sub_id: str, body: cis.SubcontractorIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cis.Subcontractor:
    try:
        return await cis.save_subcontractor(books, body, user, sub_id)
    except (FileNotFoundError, cis.CisError) as exc:
        raise _http(exc) from exc


async def live_payments(books: Books) -> list[cis.ContractorPayment]:
    """The contractor's payments, with one removed on the Invoices or Contacts page shown as removed here too."""
    from app.payments import _records

    gone = {r.id: r for r in await _records(books) if r.removed_at}
    out = []
    for p in await cis.contractor_payments(books):
        if not p.removed_at and p.payment_record_id in gone:
            r = gone[p.payment_record_id]
            p = p.model_copy(
                update={
                    "removed_at": r.removed_at,
                    "removed_by": r.removed_by,
                    "reversal_event_id": r.reversal_event_id,
                }
            )
        out.append(p)
    return out


@router.get("/payments", response_model=list[cis.ContractorPayment])
async def list_payments(books: Books = Depends(get_books)) -> list[cis.ContractorPayment]:
    return await live_payments(books)


@router.post("/payments", response_model=cis.ContractorPayment)
async def record_payment(
    body: cis.ContractorPaymentIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cis.ContractorPayment:
    try:
        return await cis.record_contractor_payment(books, body, user)
    except (cis.CisError, InvoiceError) as exc:
        raise _http(exc) from exc


@router.delete("/payments/{payment_id}", response_model=cis.ContractorPayment)
async def remove_payment(
    payment_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> cis.ContractorPayment:
    try:
        return await cis.remove_contractor_payment(books, payment_id, user)
    except (FileNotFoundError, cis.CisError, InvoiceError) as exc:
        raise _http(exc) from exc


def _end(tax_month_end: date) -> date:
    try:
        return cis.tax_month_of_end(tax_month_end)[1]
    except cis.CisError as exc:
        raise _http(exc) from exc


class ReturnView(cis.MonthlyReturn):
    owed_to_hmrc_pence: int  # 2220 at the tax month's end
    sample: bool = False


@router.get("/returns/{tax_month_end}", response_model=ReturnView)
async def get_return(tax_month_end: date, books: Books = Depends(get_books)) -> ReturnView:
    end = _end(tax_month_end)
    ret = cis.monthly_return(end, await cis.load_settings(books), await live_payments(books))
    events = await books.list_events()
    return ReturnView(**ret.model_dump(), owed_to_hmrc_pence=cis.owed_to_hmrc(events, end), sample=is_sample(events))


class Exported(BaseModel):
    paths: list[str]
    csv: str


@router.post("/returns/{tax_month_end}/export", response_model=Exported)
async def export_return(
    tax_month_end: date, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Exported:
    """Save the CIS300 figures as CSV and JSON in 07 Reports/CIS for filing elsewhere. Never submits."""
    end = _end(tax_month_end)
    ret = cis.monthly_return(end, await cis.load_settings(books), await live_payments(books))
    sample = is_sample(await books.list_events())
    paths = await cis.export_return(books, ret, user, sample)
    return Exported(paths=paths, csv=cis.return_csv(ret, sample))
