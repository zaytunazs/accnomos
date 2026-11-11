"""Plans, the customer's account and billing (docs/billing/PLANS_AND_CONTRACT.md, "API").

GET  /plans                    public
GET  /account                  the caller's account, usage and limits (registers it on the first call)
PATCH /account                 {analytics_opt_out}: Settings › Privacy
POST /billing/checkout         {plan_code, interval, promo_code?} -> {url} (Stripe Checkout)
POST /billing/portal           -> {url} (Stripe Customer Portal)
POST /billing/redeem           {code} -> {ok, message, account}
POST /billing/topup            -> {url} (Checkout for 100 documents, £3 ex VAT)
POST /billing/stripe/webhook   Stripe only (signature checked)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import accounts, identity
from app.billing import plans as P
from app.billing import registry as R
from app.billing import service as S
from app.billing import stripe_api
from app.billing.registry import Registry, Row, add_months
from app.validation import StrictBody

log = logging.getLogger("accnomos.billing")
router = APIRouter(tags=["billing"])

CODE_RE = re.compile(r"^[A-Z0-9_-]{3,40}$")


def require_registry() -> Registry:
    reg = R.registry()
    if reg is None:
        raise HTTPException(503, "Billing is not configured on this server")
    return reg


async def caller_account(request: Request) -> Row:
    """The verified caller's account (registered on first sight)."""
    kind = accounts.kind_of(request)
    me = await identity.signed_in_identity(request)  # 401 first, whatever else is set up
    return await S.ensure_account(require_registry(), S.who_from(me, kind))


async def maybe_account(request: Request) -> Row | None:
    """Dependency: 401 without a verified sign-in; the account when billing is configured, else None."""
    kind = accounts.kind_of(request)
    me = await identity.signed_in_identity(request)
    reg = R.registry()
    return await S.ensure_account(reg, S.who_from(me, kind)) if reg is not None else None


Account = Annotated[Row, Depends(caller_account)]


def normalise_code(raw: str) -> str:
    code = raw.strip().upper()
    if not CODE_RE.fullmatch(code):
        raise HTTPException(400, "That code isn't valid")
    return code


def code_problem(row: Row | None, plan_code: str | None, at: datetime) -> str | None:
    """Why a promo code cannot be used now (for this plan), or None."""
    if row is None or not row.get("active"):
        return "That code isn't valid"
    expires = row.get("expires_at")
    if isinstance(expires, datetime) and expires <= at:
        return "That code has expired"
    cap = row.get("max_redemptions")
    if cap is not None and int(row.get("redeemed_count") or 0) >= int(cap):
        return "That code has been used up"
    allowed = row.get("plan_codes")
    if plan_code and allowed and plan_code not in allowed:
        names = " or ".join(p.capitalize() for p in allowed)
        return f"That code is for the {names} plan only"
    return None


def stripe_or_503() -> stripe_api.StripeBilling:
    from app.billing import payments

    if not payments.taking_payments():
        raise HTTPException(
            503, "Paid plans can't be bought on this server. Your free trial and promo codes work as usual."
        )
    client = stripe_api.client()
    if client is None:
        raise HTTPException(503, "Card payments are not set up on this server")
    return client


async def ensure_customer(reg: Registry, stripe: stripe_api.StripeBilling, acc: Row) -> str:
    if acc.get("stripe_customer_id"):
        return str(acc["stripe_customer_id"])
    customer = await stripe.create_customer(acc["id"], acc["email"], acc.get("display_name"))
    await reg.update_account(acc["id"], {"stripe_customer_id": customer})
    S.forget(acc)
    return customer


async def coupon_for(reg: Registry, stripe: stripe_api.StripeBilling, row: Row) -> str:
    """The Stripe coupon behind a percent/fixed code, created on first use when the admin made the code while Stripe
    was not configured."""
    if row.get("stripe_coupon_id"):
        return str(row["stripe_coupon_id"])
    coupon = await stripe.create_coupon(
        code=row["code"], kind=row["kind"], value=int(row["value"]), duration_months=row.get("duration_months")
    )
    await reg.update_code(row["code"], {"stripe_coupon_id": coupon})
    return coupon


def _stripe_http(exc: stripe_api.StripeError) -> HTTPException:
    return HTTPException(502, f"Stripe refused: {exc.message}" if exc.status else "Stripe could not be reached")


# --------------------------------------------------------------------------- #
# Public
# --------------------------------------------------------------------------- #


class PlanOut(BaseModel):
    code: str
    name: str
    price_month_pence: int
    price_year_pence: int
    limits: dict[str, Any]


@router.get("/plans", response_model=list[PlanOut])
async def list_plans() -> list[PlanOut]:
    reg = R.registry()
    rows = list((await S.plans_by_code(reg)).values()) if reg is not None else P.DEFAULT_PLANS
    return [
        PlanOut(**{k: p[k] for k in PlanOut.model_fields})
        for p in sorted(rows, key=lambda p: p.get("sort", 0))
        if p.get("active", True)
    ]


# --------------------------------------------------------------------------- #
# Customer
# --------------------------------------------------------------------------- #


async def read_gauges(request: Request) -> dict[str, int | None]:
    """Bank feeds, marketplaces and Autopilot rules from the caller's books (None each when unreadable)."""
    from app.billing import gauges
    from app.routes_books import get_books

    try:
        async for books in get_books(request):
            return await gauges.read_all(books)
    except Exception:  # noqa: BLE001  the books could not be opened: the panel shows "?"
        log.info("gauges not read", exc_info=True)
    return {"bank_feeds": None, "marketplaces": None, "autopilot_rules": None, "users": 1}


@router.get("/account")
async def get_account(request: Request, gauges: bool = True) -> dict[str, Any]:
    reg = R.registry()
    if reg is None:
        await identity.signed_in_identity(request)  # still signed-in only
        return S.not_configured_view()
    acc = await caller_account(request)
    counts = await read_gauges(request) if gauges else {}
    return await S.account_view(reg, acc, S.own_ai(request.headers), counts)


class AccountPatch(StrictBody):
    analytics_opt_out: bool | None = None


@router.patch("/account")
async def patch_account(body: AccountPatch, request: Request, acc: Account) -> dict[str, Any]:
    reg = require_registry()
    patch = body.model_dump(exclude_none=True)
    if patch:
        acc = await reg.update_account(acc["id"], patch) or acc
        S.forget(acc)
    return await S.account_view(reg, acc, S.own_ai(request.headers), await read_gauges(request))


class CheckoutIn(StrictBody):
    plan_code: Literal["starter", "comprehensive", "ultimate"]
    interval: Literal["month", "year"]
    promo_code: str | None = Field(default=None, max_length=40)


class UrlOut(BaseModel):
    url: str


def trial_end_for(acc: Row, at: datetime) -> int | None:
    """Carry the rest of our 90-day trial (or a comp) into the Stripe subscription, so a card is not charged before
    it ends. Stripe wants a trial end at least 48 hours away."""
    if acc.get("stripe_subscription_id"):
        return None
    ends = acc.get("trial_ends_at") if acc.get("status") == "trialing" else None
    if acc.get("status") == "comped":
        ends = acc.get("comp_until")
    if isinstance(ends, datetime) and ends > at + timedelta(hours=48):
        return int(ends.timestamp())
    return None


@router.post("/billing/checkout", response_model=UrlOut)
async def checkout(body: CheckoutIn, acc: Account) -> UrlOut:
    reg = require_registry()
    stripe = stripe_or_503()
    if acc.get("stripe_subscription_id") and acc.get("status") in ("active", "past_due", "trialing"):
        raise HTTPException(409, "You already have a subscription: use Manage billing to change plan")
    plan = (await S.plans_by_code(reg)).get(body.plan_code)
    if plan is None or not plan.get("active", True):
        raise HTTPException(400, "That plan is not available")
    price = stripe_api.env_price(body.plan_code, body.interval) or plan.get(f"stripe_price_{body.interval}")
    if not price:
        raise HTTPException(503, "Prices are not set up in Stripe yet")
    coupon = code = None
    if body.promo_code:
        code = normalise_code(body.promo_code)
        row = await reg.get_code(code)
        if problem := code_problem(row, body.plan_code, S.now()):
            raise HTTPException(400, problem)
        assert row is not None
        if row["kind"] == "free_months":
            raise HTTPException(400, "That code gives free months: redeem it under Billing instead")
    try:
        if code:
            row = await reg.get_code(code)
            assert row is not None
            coupon = await coupon_for(reg, stripe, row)
        customer = await ensure_customer(reg, stripe, acc)
        session = await stripe.checkout_subscription(
            customer=customer,
            account_id=acc["id"],
            price=str(price),
            plan_code=body.plan_code,
            interval=body.interval,
            trial_end=trial_end_for(acc, S.now()),
            coupon=coupon,
            promo_code=code,
        )
    except stripe_api.StripeError as exc:
        raise _stripe_http(exc) from exc
    await S.emit(reg, acc, "checkout_started", {"plan": body.plan_code, "interval": body.interval})
    return UrlOut(url=str(session["url"]))


@router.post("/billing/portal", response_model=UrlOut)
async def portal(acc: Account) -> UrlOut:
    stripe = stripe_or_503()
    if not acc.get("stripe_customer_id"):
        raise HTTPException(409, "There is no card or invoice on this account yet: choose a plan first")
    try:
        session = await stripe.portal(str(acc["stripe_customer_id"]))
    except stripe_api.StripeError as exc:
        raise _stripe_http(exc) from exc
    return UrlOut(url=str(session["url"]))


@router.post("/billing/topup", response_model=UrlOut)
async def topup(acc: Account) -> UrlOut:
    import os

    reg = require_registry()
    stripe = stripe_or_503()
    try:
        customer = await ensure_customer(reg, stripe, acc)
        session = await stripe.checkout_topup(
            customer=customer,
            account_id=acc["id"],
            price=os.getenv("STRIPE_PRICE_TOPUP", "").strip() or None,
            pence=P.TOPUP_PRICE_PENCE,
            docs=P.TOPUP_DOCS,
        )
    except stripe_api.StripeError as exc:
        raise _stripe_http(exc) from exc
    await S.emit(reg, acc, "checkout_started", {"plan": "topup"})
    return UrlOut(url=str(session["url"]))


class RedeemIn(StrictBody):
    code: str = Field(min_length=1, max_length=40)


async def apply_free_months(reg: Registry, acc: Row, row: Row) -> tuple[bool, str, Row]:
    """Claim a free-months code for `acc` and set `comp_until` (status comped). No Stripe involved."""
    if acc.get("stripe_subscription_id") and acc.get("status") in ("active", "past_due"):
        return False, "You already pay by card: contact us and we'll apply the free months to your subscription", acc
    allowed = row.get("plan_codes") or []
    plan_code = acc.get("plan_code") or P.TRIAL_PLAN
    if allowed and plan_code not in allowed:
        plan_code = allowed[0]
    claimed = await reg.claim_code(row["code"], acc["id"])
    if claimed is None:
        return False, "That code has already been used on this account, or has run out", acc
    at = S.now()
    starts = max(
        (d for d in (at, acc.get("comp_until"), acc.get("trial_ends_at")) if isinstance(d, datetime)), default=at
    )
    until = add_months(starts, int(row["value"]))
    updated = await reg.update_account(acc["id"], {"status": "comped", "comp_until": until, "plan_code": plan_code})
    S.forget(acc)
    months = int(row["value"])
    return (
        True,
        f"Done: {months} month{'s' if months != 1 else ''} free, until {until.day} {until:%B %Y}",
        updated or acc,
    )


@router.post("/billing/redeem")
async def redeem(body: RedeemIn, request: Request, acc: Account) -> dict[str, Any]:
    reg = require_registry()
    code = normalise_code(body.code)
    row = await reg.get_code(code)
    own = S.own_ai(request.headers)
    if problem := code_problem(row, None, S.now()):
        return {"ok": False, "message": problem, "account": await S.account_view(reg, acc, own, {})}
    assert row is not None
    if row["kind"] != "free_months":
        off = f"{row['value']}% off" if row["kind"] == "percent" else f"£{int(row['value']) / 100:.2f} off"
        return {
            "ok": True,
            "message": f"Code {code} gives {off}: choose a plan and it's applied at checkout",
            "code": code,
            "kind": row["kind"],
            "account": await S.account_view(reg, acc, own, {}),
        }
    ok, message, acc = await apply_free_months(reg, acc, row)
    if ok:
        await S.emit(reg, acc, "code_redeemed", {"kind": "free_months"})
    return {
        "ok": ok,
        "message": message,
        "code": code,
        "kind": row["kind"],
        "account": await S.account_view(reg, acc, own, {}),
    }


@router.post("/billing/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request) -> dict[str, Any]:
    from app.billing import webhooks

    reg = require_registry()
    payload = await request.body()
    try:
        stripe_api.verify_signature(
            payload, request.headers.get("Stripe-Signature", ""), stripe_api.settings().webhook_secret
        )
    except stripe_api.BadSignature as exc:
        raise HTTPException(400, f"Bad signature: {exc}") from exc
    return await webhooks.handle(reg, payload)
