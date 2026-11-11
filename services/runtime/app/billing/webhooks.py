"""Stripe webhook events mirrored into `accounts` (Stripe is the source of truth for payment state).

Idempotent by event id (`stripe_events`): a repeat delivery is acknowledged and ignored; an event whose handling
fails is forgotten again, so Stripe's retry gets another go.

Handled (https://docs.stripe.com/billing/subscriptions/webhooks, checked 11 Nov 2026):
  * `checkout.session.completed`: a subscription checkout links the Stripe customer and subscription and records
    the promo code redemption; a top-up checkout (`metadata.kind=topup`, paid) adds 100 documents.
  * `customer.subscription.created|updated|deleted|paused|resumed`: status, plan, interval, trial end, period end and
    cancel-at-period-end. Stripe `paused` (a trial ended without a card) is our `trial_ended` (read-only).
  * `invoice.payment_failed`: `past_due` (the subscription update that follows says the same).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.billing import plans as P
from app.billing import service as S
from app.billing import stripe_api
from app.billing.registry import Registry, Row

log = logging.getLogger("accnomos.billing")

STATUS = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "cancelled",
    "paused": "trial_ended",
}  # incomplete / incomplete_expired: the first payment never went through; the account keeps its own status


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if isinstance(value, int | float) and value else None


async def _account_for(reg: Registry, obj: dict[str, Any]) -> Row | None:
    meta = obj.get("metadata") or {}
    account_id = meta.get("account_id") or obj.get("client_reference_id")
    if account_id:
        acc = await reg.get_account(str(account_id))
        if acc is not None:
            return acc
    customer = obj.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    return await reg.get_account_by_customer(str(customer)) if customer else None


async def _plan_for_price(reg: Registry, price_id: str | None, meta: dict[str, Any]) -> str | None:
    if meta.get("plan_code") in P.PLAN_CODES:
        return str(meta["plan_code"])
    if not price_id:
        return None
    for code, plan in (await S.plans_by_code(reg)).items():
        for interval in ("month", "year"):
            if price_id in (plan.get(f"stripe_price_{interval}"), stripe_api.env_price(code, interval)):
                return code
    return None


async def handle(reg: Registry, payload: bytes) -> dict[str, Any]:
    try:
        event = json.loads(payload)
        event_id, event_type = str(event["id"]), str(event["type"])
        obj = event["data"]["object"]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, "Not a Stripe event") from exc
    if not await reg.record_stripe_event(event_id, event_type):
        return {"ok": True, "duplicate": True}
    try:
        handled = await _dispatch(reg, event_type, obj)
    except Exception:
        await reg.forget_stripe_event(event_id)
        log.exception("Stripe event %s (%s) failed; Stripe will retry", event_id, event_type)
        raise
    return {"ok": True, "handled": handled}


async def _dispatch(reg: Registry, event_type: str, obj: dict[str, Any]) -> bool:
    if event_type == "checkout.session.completed":
        return await _checkout_completed(reg, obj)
    if event_type.startswith("customer.subscription."):
        return await _subscription(reg, obj, deleted=event_type.endswith(".deleted"))
    if event_type == "invoice.payment_failed":
        acc = await _account_for(reg, obj)
        if acc is not None and acc.get("status") in ("active", "trialing"):
            await reg.update_account(acc["id"], {"status": "past_due"})
            S.forget(acc)
            return True
    return False


async def _checkout_completed(reg: Registry, obj: dict[str, Any]) -> bool:
    acc = await _account_for(reg, obj)
    if acc is None:
        log.warning("checkout.session.completed for an unknown account")
        return False
    meta = obj.get("metadata") or {}
    if meta.get("kind") == "topup":
        if obj.get("payment_status") != "paid":
            return False
        docs = int(meta.get("docs") or P.TOPUP_DOCS)
        await reg.add_topup(acc["id"], P.month_start(), docs)
        await S.emit(reg, acc, "topup_bought", {"count": docs})
        return True
    if obj.get("mode") != "subscription":
        return False
    patch: Row = {}
    if obj.get("customer") and not acc.get("stripe_customer_id"):
        patch["stripe_customer_id"] = str(obj["customer"])
    if obj.get("subscription"):
        patch["stripe_subscription_id"] = str(obj["subscription"])
    if patch:
        await reg.update_account(acc["id"], patch)
        S.forget(acc)
    if (code := meta.get("promo_code")) and await reg.claim_code(str(code), acc["id"]) is None:
        log.warning("promo code used at checkout could not be counted (expired or used up meanwhile)")
    return True


async def _subscription(reg: Registry, sub: dict[str, Any], deleted: bool) -> bool:
    acc = await _account_for(reg, sub)
    if acc is None:
        log.warning("subscription event for an unknown account")
        return False
    current = acc.get("stripe_subscription_id")
    if current and current != sub.get("id"):
        return False  # an older subscription: only the current one speaks for the account
    items = ((sub.get("items") or {}).get("data") or [{}])[0] or {}
    price = items.get("price") or {}
    meta = sub.get("metadata") or {}
    status = "cancelled" if deleted else STATUS.get(str(sub.get("status")))
    patch: Row = {
        "stripe_subscription_id": None if deleted else sub.get("id"),
        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
    }
    if sub.get("customer"):
        patch["stripe_customer_id"] = str(sub["customer"])
    if status:
        patch["status"] = status
    if plan := await _plan_for_price(reg, price.get("id"), meta):
        patch["plan_code"] = plan
    interval = (price.get("recurring") or {}).get("interval")
    if interval in ("month", "year"):
        patch["billing_interval"] = interval
    if trial_end := _ts(sub.get("trial_end")):
        patch["trial_ends_at"] = trial_end
    period_end = _ts(sub.get("current_period_end")) or _ts(items.get("current_period_end"))  # newer API: on items
    if period_end:
        patch["current_period_end"] = period_end
    if status == "active":
        patch["comp_until"] = None  # paying now: any comp is over
    before = acc.get("status")
    updated = await reg.update_account(acc["id"], patch) or {**acc, **patch}
    S.forget(acc)
    if status == "active" and before != "active":
        await S.emit(reg, updated, "subscription_active", {"plan": updated.get("plan_code"), "interval": interval})
    if status == "cancelled" and before != "cancelled":
        await S.emit(reg, updated, "subscription_cancelled", {"plan": updated.get("plan_code")})
    if status == "trial_ended" and before != "trial_ended":
        await S.emit(reg, updated, "trial_ended", {})
    return True
