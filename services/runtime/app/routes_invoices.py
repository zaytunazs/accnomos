"""/invoices/*: sales invoices in the user's own folder (app/invoicing.py), PDFs (app/pdf.py), reminders
(app/ai/remind.py).

Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`, `X-User`). Sending an invoice or a reminder also
needs `Mail.Send` on the token, which the app asks for only when the user first sends, and a body with
`confirm: true`, which the app sets only after the user confirmed in a dialog. Nothing is ever sent otherwise.
"""

from __future__ import annotations

import base64
import hashlib
import io
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, StrictBool

from accnomos_connectors.base import MailSender
from accnomos_connectors.msgraph import GraphMailSender
from accnomos_ledger.bank import BankLine
from app import invoicing as inv_
from app.ai import remind
from app.ai.config import AiConfig, ai_config_from_request, is_test_mode
from app.books import Books, now
from app.invoicing import (
    Invoice,
    InvoiceCustomer,
    InvoiceDraft,
    InvoiceError,
    InvoiceProfile,
    InvoiceStateError,
    InvoiceStatus,
)
from app.pdf import render_invoice
from app.routes_books import get_books, require_user
from app.validation import Day, StrictBody

router = APIRouter(prefix="/invoices", tags=["invoices"])
LOGO_MAX = 1024 * 1024
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg"}
LOGO_MAGIC = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
LOGO_MAX_SIDE = 4000  # pixels; a 1 MB PNG can declare 30,000 x 30,000 and take gigabytes to decode in the PDF


async def get_sender(request: Request) -> AsyncIterator[MailSender]:
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    if is_test_mode():  # recorded in memory, listed by GET /__test/state
        from app import testmode

        yield (await testmode.state()).sender
        return
    sender = GraphMailSender(token)
    try:
        yield sender
    finally:
        await sender.aclose()


def _http(exc: InvoiceError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, InvoiceStateError) else 400, detail=str(exc))


async def _get(books: Books, number: str) -> Invoice:
    try:
        return await inv_.get_invoice(books, number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such invoice") from exc


def _confirmed(confirm: bool) -> None:
    if confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was sent: confirm in the app first (confirm: true)")


async def _render(books: Books, inv: Invoice) -> bytes:
    profile = await inv_.load_profile(books)
    return render_invoice(inv, profile, await inv_.load_logo(books, profile))


# --------------------------------------------------------------------------- #
# Profile and customers (before /{number}, so these paths are not read as invoice numbers)
# --------------------------------------------------------------------------- #


@router.get("/profile", response_model=InvoiceProfile)
async def get_profile(books: Books = Depends(get_books)) -> InvoiceProfile:
    return await inv_.load_profile(books)


@router.put("/profile", response_model=InvoiceProfile)
async def put_profile(
    body: InvoiceProfile, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> InvoiceProfile:
    try:
        return await inv_.save_profile(books, body, user)
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.post("/profile/logo", response_model=InvoiceProfile)
async def upload_logo(
    file: UploadFile = File(...),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> InvoiceProfile:
    """PNG or JPEG up to 1 MB and 4000 pixels a side, saved as _System/Invoicing/logo.png|jpg in the user's folder.

    The type is read from the bytes (and must agree with the declared one); the image is decoded once here so
    what the PDF renderer later opens is known to be a real, reasonably sized picture."""
    data = await file.read(LOGO_MAX + 1)
    if len(data) > LOGO_MAX:
        raise HTTPException(status_code=413, detail="The logo is over 1 MB")
    sniffed = next((kind for magic, kind in LOGO_MAGIC.items() if data.startswith(magic)), None)
    if sniffed is None or (file.content_type or "").lower() not in (sniffed, "application/octet-stream"):
        raise HTTPException(status_code=415, detail="The logo must be a PNG or JPEG")
    _check_logo_image(data)
    path = f"{inv_.INVOICING}/logo.{LOGO_TYPES[sniffed]}"
    await books.storage.write(path, data)
    profile = (await inv_.load_profile(books)).model_copy(update={"logo_path": path})
    return await inv_.save_profile(books, profile, user)


def _check_logo_image(data: bytes) -> None:
    from PIL import Image  # fpdf2's own dependency

    try:
        with Image.open(io.BytesIO(data)) as img:
            if max(img.size) > LOGO_MAX_SIDE:
                raise HTTPException(status_code=413, detail=f"The logo is over {LOGO_MAX_SIDE} pixels wide or tall")
            img.verify()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001  truncated, corrupt, or a decompression bomb
        raise HTTPException(status_code=415, detail="The logo could not be read as an image") from exc


@router.get("/customers", response_model=list[InvoiceCustomer])
async def customers(books: Books = Depends(get_books)) -> list[InvoiceCustomer]:
    """Customers from the contact book (_System/Contacts/contacts.json), for the picker."""
    return await inv_.customers(books)


# --------------------------------------------------------------------------- #
# Invoices
# --------------------------------------------------------------------------- #


class InvoiceRow(Invoice):
    days_overdue: int | None = None  # worked out for today; not stored


def _row(inv: Invoice) -> InvoiceRow:
    return InvoiceRow(**inv.model_dump(), days_overdue=inv.overdue_days(now().date()))


@router.get("", response_model=list[InvoiceRow])
async def list_invoices(status: InvoiceStatus | None = None, books: Books = Depends(get_books)) -> list[InvoiceRow]:
    return [_row(i) for i in await inv_.list_invoices(books, status)]


@router.post("", response_model=InvoiceRow)
async def create(
    body: InvoiceDraft, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> InvoiceRow:
    try:
        return _row(await inv_.create_invoice(books, body, user))
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.get("/{number}", response_model=InvoiceRow)
async def get(number: str, books: Books = Depends(get_books)) -> InvoiceRow:
    return _row(await _get(books, number))


@router.put("/{number}", response_model=InvoiceRow)
async def update(
    number: str, body: InvoiceDraft, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> InvoiceRow:
    await _get(books, number)
    try:
        return _row(await inv_.update_draft(books, number, body, user))
    except InvoiceError as exc:
        raise _http(exc) from exc


class EmailDraft(BaseModel):
    to: str | None
    subject: str
    body: str


class PdfResult(BaseModel):
    path: str
    size: int
    sha256: str
    data_url: str  # data:application/pdf;base64,... for the preview
    email: EmailDraft  # what "Send via Outlook" would send; the confirmation dialog starts from it
    problems: list[str]  # why it cannot be sent yet (empty when it can)


@router.post("/{number}/pdf", response_model=PdfResult)
async def pdf(number: str, books: Books = Depends(get_books)) -> PdfResult:
    """Render the PDF, save it as 03 Sales/invoices/<number>.pdf and return it for the preview.

    Once sent, the PDF that was emailed is returned as it was, so the preview always shows what the customer got.
    """
    inv = await _get(books, number)
    data = await inv_.sent_pdf(books, number) if inv.status != "draft" else None
    path = f"{inv_.SENT}/{number}.pdf"
    if data is None:
        data, path = await _render(books, inv), f"{inv_.INVOICES}/{number}.pdf"
        await books.storage.write(path, data)
    profile = await inv_.load_profile(books)
    subject, body = inv_.default_email(inv, profile)
    return PdfResult(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data_url=f"data:application/pdf;base64,{base64.b64encode(data).decode()}",
        email=EmailDraft(to=inv.customer.email, subject=subject, body=body),
        problems=inv_.send_problems(inv, profile, inv.customer.email) if inv.status == "draft" else [],
    )


class SendBody(StrictBody):
    confirm: StrictBool = False  # set by the app only after the user confirmed in the dialog; "yes" or 1 is not true
    to: str | None = Field(None, max_length=254)
    subject: str | None = Field(None, max_length=200)
    body: str | None = Field(None, max_length=5000)


@router.post("/{number}/send", response_model=InvoiceRow)
async def send(
    number: str,
    body: SendBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    sender: MailSender = Depends(get_sender),
) -> InvoiceRow:
    """Email the invoice from the user's Outlook with the PDF attached, then post the sale to the ledger."""
    _confirmed(body.confirm)
    inv = await _get(books, number)
    data = await _render(books, inv) if inv.status == "draft" else b""  # a sent one without its event only posts
    try:
        return _row(
            await inv_.send_invoice(books, sender, number, user, data, to=body.to, subject=body.subject, body=body.body)
        )
    except InvoiceError as exc:
        raise _http(exc) from exc
    except ValueError as exc:  # e.g. the attachment is too big for one message
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class PaidBody(StrictBody):
    payment_ref: str | None = Field(None, max_length=120)
    paid_on: Day | None = None
    bank_line_id: str | None = Field(
        None, max_length=64, pattern=r"^[0-9a-f]+$"
    )  # link the bank line this payment came in on (GET /{number}/bank-candidates)


@router.post("/{number}/mark-paid", response_model=InvoiceRow)
async def mark_paid(
    number: str, body: PaidBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> InvoiceRow:
    await _get(books, number)
    try:
        return _row(
            await inv_.mark_paid(
                books,
                number,
                user,
                payment_ref=body.payment_ref,
                paid_on=body.paid_on,
                bank_line_id=body.bank_line_id,
            )
        )
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.get("/{number}/bank-candidates", response_model=list[BankLine])
async def bank_candidates(number: str, books: Books = Depends(get_books)) -> list[BankLine]:
    """Unmatched money in for exactly this invoice's total, on or after its date."""
    return await inv_.bank_candidates(books, await _get(books, number))


class VoidBody(StrictBody):
    reason: str = Field(min_length=1, max_length=300)


@router.post("/{number}/void", response_model=InvoiceRow)
async def void(
    number: str, body: VoidBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> InvoiceRow:
    await _get(books, number)
    try:
        return _row(await inv_.void_invoice(books, number, user, body.reason))
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.post("/{number}/reminder-draft", response_model=remind.ReminderDraft)
async def reminder_draft(
    number: str,
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
) -> remind.ReminderDraft:
    """A chase email for the user to read, edit and approve. Drafting sends nothing."""
    inv = await _get(books, number)
    if inv.status != "sent":
        raise HTTPException(
            status_code=409, detail=f"Invoice {number} is {inv.status}; only unpaid sent invoices can be chased"
        )
    return await remind.draft_reminder(inv, await inv_.load_profile(books), cfg, now().date())


class ReminderSendBody(StrictBody):
    confirm: StrictBool = False
    to: str = Field(max_length=254)
    subject: str = Field(max_length=200)
    body: str = Field(max_length=5000)


@router.post("/{number}/reminder-send", response_model=InvoiceRow)
async def reminder_send(
    number: str,
    body: ReminderSendBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    sender: MailSender = Depends(get_sender),
) -> InvoiceRow:
    """Send the reminder exactly as the user approved it, with the invoice that was sent attached."""
    _confirmed(body.confirm)
    await _get(books, number)
    try:
        return _row(
            await inv_.send_reminder(
                books,
                sender,
                number,
                user,
                to=body.to,
                subject=body.subject,
                body=body.body,
                pdf=await inv_.sent_pdf(books, number),
            )
        )
    except InvoiceError as exc:
        raise _http(exc) from exc
