"""Online payments: linking the user's own Stripe / PayPal account, payment links on invoices, and payments found
through them (app/online_payments.py). Same headers as /books/*.

    GET    /payments/online/providers                  what this server offers and what the user has linked
    POST   /payments/online/{stripe|paypal}/start      {redirect_to, binding_hash} -> {url} to send the browser to
    GET    /payments/online/{stripe|paypal}/callback   the provider sends the browser here (no token); checks the
                                                       state and forwards to Settings with code/state in the fragment
    POST   /payments/online/stripe/connect             {code, state, binding}: exchange and save the account id
    POST   /payments/online/paypal/connect             {merchant_id, state, binding}: confirm with PayPal and save
    PUT    /payments/online/paypalme                   {username}
    POST   /payments/online/{provider}/disconnect      {confirm: true}
    GET    /payments/online/check                      payments found through links (reads only; the poll on open)
    POST   /invoices/{number}/payment-link             {provider}: make (or replace) the link for what is owed
    DELETE /invoices/{number}/payment-link             remove it (switched off at the provider)
    POST   /invoices/{number}/payment-link/approve     {payment_id, confirm: true, fee_pence?}: post it
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field, StrictBool

from app import online_payments as op
from app import payments as pay_
from app.books import Books
from app.invoicing import InvoiceError, InvoiceStateError
from app.routes_books import get_books, require_user
from app.routes_invoices import InvoiceRow, _row
from app.validation import Pence, StrictBody

router = APIRouter(tags=["online payments"])


def _http(exc: InvoiceError) -> HTTPException:
    if isinstance(exc, op.NotConfigured):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=409 if isinstance(exc, InvoiceStateError) else 400, detail=str(exc))


async def _fresh(books: Books, number: str) -> InvoiceRow:
    from app.invoicing import get_invoice

    return _row(await get_invoice(books, number), await pay_.load_ledger(books))


@router.get("/payments/online/providers", response_model=list[op.ProviderStatus])
async def providers(books: Books = Depends(get_books)) -> list[op.ProviderStatus]:
    return await op.status(books)


class StartBody(StrictBody):
    redirect_to: str = Field(max_length=500)  # Settings on this app's origin
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$", max_length=64)  # sha256 of a secret only this browser keeps


class StartResult(BaseModel):
    url: str


@router.post("/payments/online/{provider}/start", response_model=StartResult)
async def start(
    provider: Literal["stripe", "paypal"],
    body: StartBody,
    books: Books = Depends(get_books),  # signed in to their books: no anonymous sign-ups
    user: str = Depends(require_user),
) -> StartResult:
    try:
        if provider == "stripe":
            return StartResult(url=op.stripe_authorize_url(body.redirect_to, body.binding_hash, user))
        return StartResult(url=await op.paypal_signup_url(body.redirect_to, body.binding_hash, user))
    except InvoiceError as exc:
        raise _http(exc) from exc


def _expired(provider: str) -> PlainTextResponse:
    return PlainTextResponse(
        f"This {op.provider_label(provider)} sign-in link has expired or was already used. "
        "Go back to Accnomos, Settings › Online payments, and connect again.",
        status_code=400,
    )


@router.get("/payments/online/stripe/callback", include_in_schema=False, response_model=None)
async def stripe_callback(
    state: str = "", code: str | None = None, error: str | None = None, error_description: str | None = None
) -> RedirectResponse | PlainTextResponse:
    """Stripe sends the browser here (docs/connect/oauth-reference: `code`, `scope`, `state`, or `error`)."""
    try:
        st = op.read_state(state, "stripe", use="callback")
    except (op.StateError, InvoiceError):
        return _expired("stripe")
    frag = {"pay": "stripe", "state": state}
    frag |= (
        {"code": code}
        if code and not error
        else {"error": error or "missing_code", "error_description": error_description or ""}
    )
    return RedirectResponse(f"{st.redirect_to}#{urlencode(frag)}", status_code=303)


@router.get("/payments/online/paypal/callback", include_in_schema=False, response_model=None)
async def paypal_callback(
    state: str = "",
    merchantIdInPayPal: str | None = None,  # noqa: N803  PayPal's own query parameter names
    permissionsGranted: str | None = None,  # noqa: N803
    consentStatus: str | None = None,  # noqa: N803
    isEmailConfirmed: str | None = None,  # noqa: N803
) -> RedirectResponse | PlainTextResponse:
    """PayPal sends the seller here after sign-up (docs/multiparty/seller-onboarding/before-payment)."""
    try:
        st = op.read_state(state, "paypal", use="callback")
    except (op.StateError, InvoiceError):
        return _expired("paypal")
    frag = {"pay": "paypal", "state": state}
    if merchantIdInPayPal and permissionsGranted == "true" and consentStatus == "true":
        frag["merchant_id"] = merchantIdInPayPal
        if isEmailConfirmed == "false":
            frag["email_unconfirmed"] = "1"
    else:
        frag |= {
            "error": "access_denied",
            "error_description": "PayPal sign-up was not finished, or permission was not given",
        }
    return RedirectResponse(f"{st.redirect_to}#{urlencode(frag)}", status_code=303)


class StripeConnectBody(StrictBody):
    code: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=2048)
    binding: str = Field(min_length=16, max_length=200)


class PayPalConnectBody(StrictBody):
    merchant_id: str = Field(min_length=1, max_length=40)
    state: str = Field(min_length=1, max_length=2048)
    binding: str = Field(min_length=16, max_length=200)


@router.post("/payments/online/stripe/connect", response_model=list[op.ProviderStatus])
async def stripe_connect(
    body: StripeConnectBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> list[op.ProviderStatus]:
    try:
        await op.connect_stripe(books, body.code, body.state, body.binding, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return await op.status(books)


@router.post("/payments/online/paypal/connect", response_model=list[op.ProviderStatus])
async def paypal_connect(
    body: PayPalConnectBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> list[op.ProviderStatus]:
    try:
        await op.connect_paypal(books, body.merchant_id, body.state, body.binding, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return await op.status(books)


class PayPalMeBody(StrictBody):
    username: str = Field(min_length=1, max_length=60)


@router.put("/payments/online/paypalme", response_model=list[op.ProviderStatus])
async def paypalme(
    body: PayPalMeBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> list[op.ProviderStatus]:
    try:
        await op.set_paypalme(books, body.username, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return await op.status(books)


class ConfirmBody(StrictBody):
    confirm: StrictBool = False


class DisconnectResult(BaseModel):
    providers: list[op.ProviderStatus]
    warning: str | None = None


@router.post("/payments/online/{provider}/disconnect", response_model=DisconnectResult)
async def disconnect(
    provider: op.Provider, body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> DisconnectResult:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was changed: confirm in the app first (confirm: true)")
    try:
        warning = await op.disconnect(books, provider, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
    return DisconnectResult(providers=await op.status(books), warning=warning)


@router.get("/payments/online/check", response_model=op.CheckResult)
async def check(books: Books = Depends(get_books)) -> op.CheckResult:
    """Payments found through invoices' links, for the user to approve. Reads only; posts nothing."""
    return await op.check(books)


class LinkBody(StrictBody):
    provider: op.Provider


class LinkResult(BaseModel):
    invoice: InvoiceRow
    warning: str | None = None  # the old link could not be switched off at the provider


@router.post("/invoices/{number}/payment-link", response_model=LinkResult)
async def add_link(
    number: str, body: LinkBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> LinkResult:
    try:
        _inv, warning = await op.add_link(books, number, body.provider, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such invoice") from exc
    except (InvoiceError, ValueError) as exc:
        raise (_http(exc) if isinstance(exc, InvoiceError) else HTTPException(400, str(exc))) from exc
    return LinkResult(invoice=await _fresh(books, number), warning=warning)


@router.delete("/invoices/{number}/payment-link", response_model=LinkResult)
async def remove_link(number: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> LinkResult:
    try:
        _inv, warning = await op.remove_link(books, number, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such invoice") from exc
    except InvoiceError as exc:
        raise _http(exc) from exc
    return LinkResult(invoice=await _fresh(books, number), warning=warning)


class ApproveBody(StrictBody):
    payment_id: str = Field(min_length=1, max_length=100)
    confirm: StrictBool = False  # set by the app only after the user said yes
    fee_pence: Pence | None = Field(default=None, ge=0, le=pay_.MAX_PENCE)  # only when the provider has not said


class ApproveResult(BaseModel):
    invoice: InvoiceRow
    payment: op.FoundPayment


@router.post("/invoices/{number}/payment-link/approve", response_model=ApproveResult)
async def approve(
    number: str, body: ApproveBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ApproveResult:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was posted: approve in the app first (confirm: true)")
    try:
        _inv, found = await op.approve(books, number, body.payment_id, user, fee_pence=body.fee_pence)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such invoice") from exc
    except InvoiceError as exc:
        raise _http(exc) from exc
    return ApproveResult(invoice=await _fresh(books, number), payment=found)
