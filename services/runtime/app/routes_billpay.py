"""Paying suppliers' bills through PayPal on their due date (app/billpay.py). Same headers as /books/*.

GET    /billpay                              the due queue, other open bills, payees, payouts, Autopilot
POST   /billpay/run                          on opening the app: follow payouts, then Autopilot pays what its
                                             rules allow (everything else waits for the owner)
PUT    /billpay/payees/{contact_id}          {paypal_email, bank?, confirm: true}: typed or confirmed by the owner
DELETE /billpay/payees/{contact_id}
PUT    /billpay/bills/{event_id}/plan        {plan: "paypal" | "not_paypal" | null}
POST   /billpay/bills/{event_id}/pay         {amount_pence, confirm: true, acknowledge_changed_details?}
POST   /billpay/bills/{event_id}/details     {text, source}: payment details printed on the bill, to compare
POST   /billpay/flags/{flag_id}/clear        {confirm: true}: the owner checked the details with the supplier
PUT    /billpay/autopilot                    {enabled, rules: [...]}
POST   /billpay/autopilot/stop               the kill switch
POST   /billpay/notices/seen                 {ids}
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool

from app import billpay as bp
from app import demo
from app.books import Books
from app.invoicing import InvoiceError, InvoiceStateError
from app.routes_books import get_books, require_user
from app.validation import Pence, StrictBody

router = APIRouter(tags=["bill pay"])
ID = r"^[0-9a-f]{8,64}$"
CONTACT = r"^[0-9a-f]{16}$"


def _no_real_money_in_demo(request: Request) -> None:
    """A demo sandbox pays only where nothing real moves: the fakes (test mode) or the server's own PayPal sandbox."""
    if not bp.demo_allowed():
        demo.refuse_external("Paying bills through PayPal")(request)


def _http(exc: InvoiceError) -> HTTPException:
    if isinstance(exc, bp.NotConnected):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=409 if isinstance(exc, InvoiceStateError) else 400, detail=str(exc))


@router.get("/billpay", response_model=bp.Overview)
async def overview(books: Books = Depends(get_books)) -> bp.Overview:
    return await bp.bills(books)


@router.post("/billpay/run", response_model=bp.RunResult, dependencies=[Depends(_no_real_money_in_demo)])
async def run(books: Books = Depends(get_books), _user: str = Depends(require_user)) -> bp.RunResult:
    return await bp.run(books)


class PayeeBody(StrictBody):
    paypal_email: str = Field(min_length=3, max_length=127)
    bank: str | None = Field(None, max_length=60)
    confirm: StrictBool  # the owner typed or checked it; never filled from a document


@router.put("/billpay/payees/{contact_id}", response_model=bp.Payee)
async def set_payee(
    contact_id: str, body: PayeeBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> bp.Payee:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirm the PayPal email first")
    if not re.fullmatch(CONTACT, contact_id):
        raise HTTPException(status_code=404, detail="No such contact")
    try:
        return await bp.set_payee(books, contact_id, body.paypal_email, body.bank, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such contact") from exc
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.delete("/billpay/payees/{contact_id}", status_code=204)
async def remove_payee(contact_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    try:
        await bp.remove_payee(books, contact_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No PayPal email saved for that contact") from exc


class PlanBody(StrictBody):
    plan: Literal["paypal", "not_paypal"] | None


class PlanResult(BaseModel):
    plan: Literal["paypal", "not_paypal"] | None


@router.put("/billpay/bills/{event_id}/plan", response_model=PlanResult)
async def set_plan(
    event_id: str, body: PlanBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> PlanResult:
    if not re.fullmatch(ID, event_id):
        raise HTTPException(status_code=404, detail="No such bill")
    return PlanResult(plan=await bp.set_plan(books, event_id, body.plan, user))


class PayBody(StrictBody):
    amount_pence: Pence = Field(gt=0, le=10_000_000_000)  # what the card showed as owed; must still be owed
    confirm: StrictBool
    acknowledge_changed_details: StrictBool = False


@router.post("/billpay/bills/{event_id}/pay", response_model=bp.Payout, dependencies=[Depends(_no_real_money_in_demo)])
async def pay(
    event_id: str, body: PayBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> bp.Payout:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirm the payment first")
    if not re.fullmatch(ID, event_id):
        raise HTTPException(status_code=404, detail="No such bill")
    try:
        return await bp.pay(
            books, event_id, body.amount_pence, user, acknowledge_changed_details=body.acknowledge_changed_details
        )
    except InvoiceError as exc:
        raise _http(exc) from exc


class DetailsBody(StrictBody):
    text: str = Field(max_length=20_000)
    source: str = Field("typed", max_length=60)


class DetailsResult(BaseModel):
    seen: bp.SeenDetails
    changed: list[str]


@router.post("/billpay/bills/{event_id}/details", response_model=DetailsResult)
async def details(
    event_id: str, body: DetailsBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> DetailsResult:
    """Payment details printed on a bill (e.g. its email), read by code and compared with the saved ones. Never saved
    as the supplier's payee."""
    ov = await bp.bills(books, read_documents=False)
    bill = next((b for b in [*ov.due, *ov.upcoming] if b.event_id == event_id), None)
    if bill is None:
        raise HTTPException(status_code=404, detail="No unpaid bill with that id")
    payee = (await bp.load_payees(books)).get(bill.contact_id)
    seen, changed = await bp.record_seen(
        books, event_id, bill.contact_id, bill.supplier, body.text, body.source, payee, f"user:{user}"
    )
    return DetailsResult(seen=seen, changed=changed)


class ConfirmBody(StrictBody):
    confirm: StrictBool


@router.post("/billpay/flags/{flag_id}/clear", response_model=bp.Flag)
async def clear_flag(
    flag_id: str, body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> bp.Flag:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirm you checked the details with the supplier")
    try:
        return await bp.clear_flag(books, flag_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No open flag with that id") from exc


class RuleIn(StrictBody):
    contact_id: str = Field(pattern=CONTACT, max_length=16)
    enabled: StrictBool = True
    max_per_bill_pence: Pence = Field(gt=0, le=10_000_000)
    monthly_cap_pence: Pence = Field(gt=0, le=100_000_000)
    min_days_unchanged: int = Field(default=bp.DEFAULT_UNCHANGED_DAYS, ge=0, le=365)
    only_person_approved: StrictBool = True


class AutopilotBody(StrictBody):
    enabled: StrictBool
    rules: list[RuleIn] = Field(default_factory=list, max_length=200)


@router.put("/billpay/autopilot", response_model=bp.AutopilotSettings)
async def save_autopilot(
    body: AutopilotBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> bp.AutopilotSettings:
    try:
        rules = [bp.SupplierRule.model_validate(r.model_dump()) for r in body.rules]
        return await bp.save_autopilot(books, body.enabled, rules, user)
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.post("/billpay/autopilot/stop", response_model=bp.AutopilotSettings)
async def stop(books: Books = Depends(get_books), user: str = Depends(require_user)) -> bp.AutopilotSettings:
    return await bp.stop_autopilot(books, user)


class SeenBody(StrictBody):
    ids: list[Annotated[str, Field(max_length=40)]] = Field(max_length=100)


@router.post("/billpay/notices/seen", status_code=204)
async def notices_seen(body: SeenBody, books: Books = Depends(get_books), _user: str = Depends(require_user)) -> None:
    await bp.mark_seen(books, body.ids)
