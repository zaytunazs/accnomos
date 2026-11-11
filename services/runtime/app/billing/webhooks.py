"""Payment-provider webhook events mirrored into `accounts` (the provider is the source of truth for payment state):
Stripe first, then PayPal (`handle_paypal`, below).

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


# --------------------------------------------------------------------------- #
# PayPal (PAYMENTS_PROVIDER=paypal; app/billing/paypal_api.py)
# --------------------------------------------------------------------------- #
#
# Verified with PayPal before this runs (routes.paypal_webhook). Idempotent by event id in the same table as Stripe's
# (PayPal's ids are `WH-…`); a failed event is forgotten again so PayPal's retry gets another go.
#
#   * BILLING.SUBSCRIPTION.ACTIVATED / UPDATED: the subscription speaks for the account (`custom_id` = our account
#     id): plan and interval from the plan id (PAYPAL_PLAN_* env), period end from `billing_info.next_billing_time`.
#     ACTIVE with a `start_time` still ahead (subscribed during our trial or a comp) is `trialing` until then.
#     SUSPENDED is `past_due`; CANCELLED / EXPIRED as below.
#   * BILLING.SUBSCRIPTION.CANCELLED / EXPIRED: see service.paypal_cancelled_patch (paid-for time is kept).
#   * BILLING.SUBSCRIPTION.SUSPENDED and BILLING.SUBSCRIPTION.PAYMENT.FAILED: `past_due`.
#   * PAYMENT.SALE.COMPLETED: a payment on the subscription (`billing_agreement_id`): `active`, comp over, and the
#     period end refreshed from the subscription.
#   * CHECKOUT.ORDER.APPROVED for a top-up order (`custom_id` = `topup:<account id>`): captured here, and 100
#     documents added once the capture is COMPLETED. A second delivery (or an order already captured) adds nothing.

PAYPAL_STATUS = {"ACTIVE": "active", "SUSPENDED": "past_due"}


async def handle_paypal(reg: Registry, client: Any, payload: bytes) -> dict[str, Any]:
    try:
        event = json.loads(payload)
        event_id, event_type = str(event["id"]), str(event["event_type"])
        resource = event["resource"]
        if not isinstance(resource, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, "Not a PayPal event") from exc
    if not await reg.record_stripe_event(event_id, event_type):
        return {"ok": True, "duplicate": True}
    try:
        handled = await _paypal_dispatch(reg, client, event_type, resource)
    except Exception:
        await reg.forget_stripe_event(event_id)
        log.exception("PayPal event %s (%s) failed; PayPal will retry", event_id, event_type)
        raise
    return {"ok": True, "handled": handled}


async def _paypal_dispatch(reg: Registry, client: Any, event_type: str, res: dict[str, Any]) -> bool:
    if event_type in ("BILLING.SUBSCRIPTION.ACTIVATED", "BILLING.SUBSCRIPTION.UPDATED"):
        return await _paypal_subscription(reg, res)
    if event_type in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.EXPIRED"):
        return await _paypal_ended(reg, res, expired=event_type.endswith("EXPIRED"))
    if event_type in ("BILLING.SUBSCRIPTION.SUSPENDED", "BILLING.SUBSCRIPTION.PAYMENT.FAILED"):
        acc = await _paypal_account(reg, res, str(res.get("id") or ""))
        if acc is not None and acc.get("status") in ("active", "trialing"):
            await reg.update_account(acc["id"], {"status": "past_due"})
            S.forget(acc)
            return True
        return False
    if event_type == "PAYMENT.SALE.COMPLETED":
        return await _paypal_sale(reg, client, res)
    if event_type == "CHECKOUT.ORDER.APPROVED":
        return await _paypal_topup(reg, client, res)
    return False


async def _paypal_account(reg: Registry, res: dict[str, Any], sub_id: str) -> Row | None:
    """The account a subscription event is about: by `custom_id` (our account id), else by the subscription id. Only
    the account's current subscription speaks for it (an older one, after a re-subscribe, is ignored)."""
    acc = None
    if custom := res.get("custom_id") or res.get("custom"):
        acc = await reg.get_account(str(custom))
    if acc is None and sub_id:
        acc = await reg.get_account_by_subscription(sub_id)
    if acc is None:
        log.warning("PayPal subscription event for an unknown account")
        return None
    current = acc.get("stripe_subscription_id")
    if current and sub_id and current != sub_id:
        return None
    return acc


async def _paypal_subscription(reg: Registry, sub: dict[str, Any]) -> bool:
    from app.billing import paypal_api

    sub_id = str(sub.get("id") or "")
    status = str(sub.get("status") or "")
    if status in ("CANCELLED", "EXPIRED"):
        return await _paypal_ended(reg, sub, expired=status == "EXPIRED")
    ours = PAYPAL_STATUS.get(status)
    if not sub_id or ours is None:
        return False  # APPROVAL_PENDING / APPROVED: nothing to mirror yet
    acc = await _paypal_account(reg, sub, sub_id)
    if acc is None:
        return False
    now = S.now()
    start = paypal_api.parse_time(sub.get("start_time"))
    patch: Row = {"stripe_subscription_id": sub_id, "cancel_at_period_end": False}
    if ours == "active" and start is not None and start > now:
        patch["status"] = "trialing"  # deferred start: nothing is charged until our trial or comp ends
        patch["trial_ends_at"] = start
        patch["comp_until"] = None
    else:
        patch["status"] = ours
    if found := paypal_api.plan_for_id(sub.get("plan_id")):
        patch["plan_code"], patch["billing_interval"] = found
    if period_end := paypal_api.parse_time((sub.get("billing_info") or {}).get("next_billing_time")):
        patch["current_period_end"] = period_end
    if patch["status"] == "active":
        patch["comp_until"] = None
    before = acc.get("status")
    updated = await reg.update_account(acc["id"], patch) or {**acc, **patch}
    S.forget(acc)
    if patch["status"] == "active" and before != "active":
        interval = patch.get("billing_interval")
        await S.emit(reg, updated, "subscription_active", {"plan": updated.get("plan_code"), "interval": interval})
    return True


async def _paypal_ended(reg: Registry, sub: dict[str, Any], expired: bool) -> bool:
    sub_id = str(sub.get("id") or "")
    acc = await _paypal_account(reg, sub, sub_id)
    if acc is None or not sub_id or acc.get("stripe_subscription_id") != sub_id:
        return False  # already handled (our own cancel cleared it first), or not the current subscription
    patch: Row = {"stripe_subscription_id": None, "status": "cancelled", "cancel_at_period_end": False}
    if not expired:
        patch = S.paypal_cancelled_patch(acc, S.now())
    before = acc.get("status")
    updated = await reg.update_account(acc["id"], patch) or {**acc, **patch}
    S.forget(acc)
    if updated.get("status") == "cancelled" and before != "cancelled":
        await S.emit(reg, updated, "subscription_cancelled", {"plan": updated.get("plan_code")})
    return True


async def _paypal_sale(reg: Registry, client: Any, sale: dict[str, Any]) -> bool:
    from app.billing import paypal_api

    sub_id = str(sale.get("billing_agreement_id") or "")
    if not sub_id or str(sale.get("state") or "completed").lower() != "completed":
        return False
    acc = await reg.get_account_by_subscription(sub_id)
    if acc is None:
        log.warning("PayPal sale for an unknown subscription")
        return False
    patch: Row = {"status": "active", "comp_until": None}
    try:
        sub = await client.subscription(sub_id)
        if period_end := paypal_api.parse_time((sub.get("billing_info") or {}).get("next_billing_time")):
            patch["current_period_end"] = period_end
    except paypal_api.PayPalError:
        log.info("PayPal subscription not read after a sale; the period end waits for the next event")
    before = acc.get("status")
    updated = await reg.update_account(acc["id"], patch) or {**acc, **patch}
    S.forget(acc)
    if before != "active":
        await S.emit(reg, updated, "subscription_active", {"plan": updated.get("plan_code")})
    return True


async def _paypal_topup(reg: Registry, client: Any, order: dict[str, Any]) -> bool:
    from app.billing import paypal_api

    units = order.get("purchase_units") or [{}]
    custom = str((units[0] or {}).get("custom_id") or "")
    if not custom.startswith("topup:") or not order.get("id"):
        return False
    acc = await reg.get_account(custom.removeprefix("topup:"))
    if acc is None:
        log.warning("PayPal top-up for an unknown account")
        return False
    try:
        captured = await client.capture_order(str(order["id"]))
    except paypal_api.PayPalError as exc:
        if exc.issue == "ORDER_ALREADY_CAPTURED":
            return False  # counted when it was captured
        raise
    if captured.get("status") != "COMPLETED":
        return False
    await reg.add_topup(acc["id"], P.month_start(), P.TOPUP_DOCS)
    await S.emit(reg, acc, "topup_bought", {"count": P.TOPUP_DOCS})
    return True
