"""The admin API (docs/billing/PLANS_AND_CONTRACT.md, "Admin"). Allow-list: `ADMIN_EMAILS` (comma-separated),
checked against the email of the verified identity (app/identity.py), never a header the client wrote. Anyone else
gets 403. Every write is recorded in `admin_audit` with the admin's email.

    GET   /admin/metrics
    GET   /admin/users?q=&plan=&status=&page=
    GET   /admin/users/{id}
    PATCH /admin/users/{id}              {plan_code?, trial_ends_at?, comp_until?, status?, notes?}
    POST  /admin/users/{id}/actions      {action, days?, code?, docs?}
    GET   /admin/codes   POST /admin/codes   PATCH /admin/codes/{code}
    GET   /admin/plans   PATCH /admin/plans/{code}   POST /admin/plans/sync-stripe
    GET   /admin/audit?account_id=&page=
    GET   /admin/analytics?from=&to=
    GET   /admin/bug-reports?status=&page=   PATCH /admin/bug-reports/{id}   GET /admin/bug-reports/{id}/screenshot
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field

from app import identity
from app.billing import plans as P
from app.billing import registry as R
from app.billing import service as S
from app.billing import stripe_api
from app.billing.registry import Registry, RegistryError, Row
from app.billing.routes import CODE_RE, apply_free_months, code_problem, coupon_for
from app.validation import StrictBody

log = logging.getLogger("accnomos.billing")
router = APIRouter(prefix="/admin", tags=["admin"])
PER_PAGE = 25


def admin_emails() -> frozenset[str]:
    return frozenset(e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip())


async def require_admin(request: Request) -> str:
    """The verified caller's email if it is on ADMIN_EMAILS; 401 without a sign-in, 403 otherwise."""
    me = await identity.signed_in_identity(request)
    email = (me.email or "").strip().lower()
    if not email or email not in admin_emails():
        raise HTTPException(403, "Admins only")
    if R.registry() is None:
        raise HTTPException(503, "Billing is not configured on this server")
    return email


Admin = Annotated[str, Depends(require_admin)]


def reg() -> Registry:
    r = R.registry()
    assert r is not None  # require_admin checked
    return r


def _paged(rows: list[Row], total: int, page: int, per_page: int = PER_PAGE) -> dict[str, Any]:
    return {"items": rows, "page": page, "per_page": per_page, "total": total}


async def _account_or_404(account_id: str) -> Row:
    acc = await reg().get_account(account_id)
    if acc is None:
        raise HTTPException(404, "No such account")
    return acc


# --------------------------------------------------------------------------- #
# Metrics and users
# --------------------------------------------------------------------------- #


@router.get("/metrics")
async def metrics(_: Admin) -> dict[str, Any]:
    return await reg().metrics()


@router.get("/users")
async def users(
    _: Admin,
    q: str | None = Query(default=None, max_length=100),
    plan: str | None = Query(default=None, max_length=20),
    status: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1, le=10_000),
) -> dict[str, Any]:
    if plan and plan not in P.PLAN_CODES:
        raise HTTPException(400, "Unknown plan")
    if status and status not in S.STATUSES:
        raise HTTPException(400, "Unknown status")
    rows, total = await reg().list_accounts(q, plan, status, page, PER_PAGE)
    usage = await reg().usage_for([r["id"] for r in rows], P.month_start())
    for r in rows:
        u = usage.get(r["id"]) or {}
        r["usage"] = {k: int(u.get(k) or 0) for k in ("docs", "ask", "invoices", "topup_docs_remaining")}
    return _paged(rows, total, page)


async def _stripe_summary(acc: Row) -> dict[str, Any] | None:
    client = stripe_api.client()
    if client is None or not acc.get("stripe_customer_id"):
        return None
    out: dict[str, Any] = {"customer": acc["stripe_customer_id"], "subscription": None, "invoices": []}
    try:
        if acc.get("stripe_subscription_id"):
            sub = await client.subscription(str(acc["stripe_subscription_id"]))
            out["subscription"] = {
                k: sub.get(k) for k in ("id", "status", "cancel_at_period_end", "current_period_end", "trial_end")
            }
        invoices = await client.invoices(str(acc["stripe_customer_id"]))
        out["invoices"] = [
            {k: i.get(k) for k in ("id", "number", "status", "total", "currency", "created", "hosted_invoice_url")}
            for i in invoices
        ]
    except stripe_api.StripeError as exc:
        out["error"] = exc.message
    return out


@router.get("/users/{account_id}")
async def user(account_id: str, _: Admin) -> dict[str, Any]:
    acc = await _account_or_404(account_id)
    audit, _total = await reg().list_audit(account_id, 1, 50)
    return {
        "account": acc,
        "usage_history": await reg().usage_history(account_id),
        "redemptions": await reg().redemptions(account_id),
        "stripe": await _stripe_summary(acc),
        "notes": acc.get("notes"),
        "audit": audit,
    }


class UserPatch(StrictBody):
    plan_code: Literal["starter", "comprehensive", "ultimate"] | None = None
    trial_ends_at: datetime | None = None
    comp_until: datetime | None = None
    status: Literal["trialing", "active", "past_due", "trial_ended", "cancelled", "comped"] | None = None
    notes: str | None = Field(default=None, max_length=5000)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


@router.patch("/users/{account_id}")
async def patch_user(account_id: str, body: UserPatch, admin: Admin) -> Row:
    acc = await _account_or_404(account_id)
    patch = body.model_dump(exclude_unset=True)
    for k in ("trial_ends_at", "comp_until"):
        if k in patch:
            patch[k] = _aware(patch[k])
    if not patch:
        return acc
    before = {k: acc.get(k) for k in patch}
    updated = await reg().update_account(account_id, patch) or acc
    S.forget(acc)
    await reg().add_audit(admin, account_id, "update_account", {"before": before, "after": patch})
    return updated


class ActionIn(StrictBody):
    action: Literal["extend_trial", "apply_code", "cancel_at_period_end", "resume", "send_portal_link", "grant_topup"]
    days: int | None = Field(default=None, ge=1, le=366)
    code: str | None = Field(default=None, max_length=40)
    docs: int | None = Field(default=None, ge=1, le=10_000)


@router.post("/users/{account_id}/actions")
async def user_action(account_id: str, body: ActionIn, admin: Admin) -> dict[str, Any]:
    acc = await _account_or_404(account_id)
    r = reg()
    detail: dict[str, Any] = {}
    out: dict[str, Any] = {"ok": True}
    if body.action == "extend_trial":
        days = body.days or 14
        at = S.now()
        current = acc.get("trial_ends_at")
        base = current if isinstance(current, datetime) and current > at else at
        patch: Row = {"trial_ends_at": base + timedelta(days=days)}
        if acc.get("status") == "trial_ended" and not acc.get("stripe_subscription_id"):
            patch["status"] = "trialing"
        acc = await r.update_account(account_id, patch) or acc
        detail = {"days": days, "trial_ends_at": patch["trial_ends_at"]}
    elif body.action == "apply_code":
        code = (body.code or "").strip().upper()
        if not CODE_RE.fullmatch(code):
            raise HTTPException(400, "Give a code")
        row = await r.get_code(code)
        if problem := code_problem(row, None, S.now()):
            raise HTTPException(400, problem)
        assert row is not None
        if row["kind"] == "free_months":
            ok, message, acc = await apply_free_months(r, acc, row)
            if not ok:
                raise HTTPException(409, message)
            out["message"] = message
        else:
            client = _stripe()
            if not acc.get("stripe_subscription_id"):
                raise HTTPException(409, "This account has no subscription to discount yet")
            try:
                coupon = await coupon_for(r, client, row)
                await client.apply_coupon(str(acc["stripe_subscription_id"]), coupon)
            except stripe_api.StripeError as exc:
                raise HTTPException(502, f"Stripe refused: {exc.message}") from exc
            if await r.claim_code(code, account_id) is None:
                raise HTTPException(409, "That code has already been used on this account, or has run out")
        detail = {"code": code, "kind": row["kind"]}
    elif body.action in ("cancel_at_period_end", "resume"):
        client = _stripe()
        if not acc.get("stripe_subscription_id"):
            raise HTTPException(409, "This account has no subscription")
        cancel = body.action == "cancel_at_period_end"
        try:
            await client.set_cancel_at_period_end(str(acc["stripe_subscription_id"]), cancel)
        except stripe_api.StripeError as exc:
            raise HTTPException(502, f"Stripe refused: {exc.message}") from exc
        acc = await r.update_account(account_id, {"cancel_at_period_end": cancel}) or acc
    elif body.action == "send_portal_link":
        client = _stripe()
        if not acc.get("stripe_customer_id"):
            raise HTTPException(409, "This account has no Stripe customer yet")
        try:
            session = await client.portal(str(acc["stripe_customer_id"]))
        except stripe_api.StripeError as exc:
            raise HTTPException(502, f"Stripe refused: {exc.message}") from exc
        out["url"] = session.get("url")  # for the admin to send; we do not email it from here
    elif body.action == "grant_topup":
        docs = body.docs or P.TOPUP_DOCS
        await r.add_topup(account_id, P.month_start(), docs)
        detail = {"docs": docs}
    S.forget(acc)
    await r.add_audit(admin, account_id, body.action, detail)
    out["account"] = await r.get_account(account_id)
    return out


def _stripe() -> stripe_api.StripeBilling:
    client = stripe_api.client()
    if client is None:
        raise HTTPException(503, "Stripe is not configured on this server")
    return client


# --------------------------------------------------------------------------- #
# Promo codes
# --------------------------------------------------------------------------- #


@router.get("/codes")
async def codes(_: Admin) -> list[Row]:
    return await reg().list_codes()


class CodeIn(StrictBody):
    code: str = Field(min_length=3, max_length=40)
    kind: Literal["percent", "fixed", "free_months"]
    value: int = Field(ge=1, le=1_000_000)  # percent 1-100 | pence off | months free
    plan_codes: list[Literal["starter", "comprehensive", "ultimate"]] | None = Field(default=None, max_length=3)
    max_redemptions: int | None = Field(default=None, ge=1, le=1_000_000)
    expires_at: datetime | None = None
    duration_months: int | None = Field(default=None, ge=1, le=36)  # percent/fixed: repeat for N months
    active: bool = True


@router.post("/codes", status_code=201)
async def create_code(body: CodeIn, admin: Admin) -> Row:
    code = body.code.strip().upper()
    if not CODE_RE.fullmatch(code):
        raise HTTPException(400, "Codes are 3-40 capital letters, digits, - or _")
    if body.kind == "percent" and body.value > 100:
        raise HTTPException(400, "A percentage is at most 100")
    if body.kind == "free_months" and body.value > 36:
        raise HTTPException(400, "Free months are at most 36")
    row: Row = body.model_dump()
    row.update(code=code, created_by=admin, expires_at=_aware(body.expires_at), plan_codes=body.plan_codes or None)
    if body.kind != "free_months" and (client := stripe_api.client()) is not None:
        try:
            row["stripe_coupon_id"] = await client.create_coupon(
                code=code, kind=body.kind, value=body.value, duration_months=body.duration_months
            )
        except stripe_api.StripeError as exc:
            raise HTTPException(502, f"Stripe refused the coupon: {exc.message}") from exc
    try:
        created = await reg().create_code(row)
    except RegistryError as exc:
        if exc.status == 409:
            raise HTTPException(409, "A code with that name already exists") from exc
        raise
    await reg().add_audit(admin, None, "create_code", {k: v for k, v in row.items() if k != "created_by"})
    return created


class CodePatch(StrictBody):
    active: bool | None = None
    max_redemptions: int | None = Field(default=None, ge=1, le=1_000_000)
    expires_at: datetime | None = None
    plan_codes: list[Literal["starter", "comprehensive", "ultimate"]] | None = None


@router.patch("/codes/{code}")
async def patch_code(code: str, body: CodePatch, admin: Admin) -> Row:
    code = code.strip().upper()
    patch = body.model_dump(exclude_unset=True)
    if "expires_at" in patch:
        patch["expires_at"] = _aware(patch["expires_at"])
    if "plan_codes" in patch:
        patch["plan_codes"] = patch["plan_codes"] or None
    row = await reg().update_code(code, patch) if patch else await reg().get_code(code)
    if row is None:
        raise HTTPException(404, "No such code")
    await reg().add_audit(admin, None, "update_code", {"code": code, **patch})
    return row


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #


@router.get("/plans")
async def admin_plans(_: Admin) -> list[Row]:
    return await reg().list_plans()


class PlanPatch(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    limits: dict[str, Any] | None = None
    active: bool | None = None
    price_month_pence: int | None = Field(default=None, ge=0, le=1_000_000)
    price_year_pence: int | None = Field(default=None, ge=0, le=10_000_000)


async def _new_price(client: stripe_api.StripeBilling, plan: Row, interval: str, pence: int) -> str:
    product = None
    old = plan.get(f"stripe_price_{interval}") or plan.get("stripe_price_month") or plan.get("stripe_price_year")
    if old:
        product = (await client.retrieve_price(str(old))).get("product")
    if not product:
        product = await client.create_product(plan["code"], plan["name"])
    return await client.create_price(product=str(product), plan_code=plan["code"], interval=interval, pence=pence)


@router.patch("/plans/{code}")
async def patch_plan(code: str, body: PlanPatch, admin: Admin) -> Row:
    plans = {p["code"]: p for p in await reg().list_plans()}
    plan = plans.get(code)
    if plan is None:
        raise HTTPException(404, "No such plan")
    patch = body.model_dump(exclude_unset=True)
    if "limits" in patch:
        try:
            patch["limits"] = {**(plan.get("limits") or {}), **P.validate_limits(patch["limits"] or {})}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    client = stripe_api.client()
    for interval in ("month", "year"):
        key = f"price_{interval}_pence"
        if key in patch and patch[key] != plan.get(key):
            # Stripe prices cannot change: a new one for new checkouts (existing subscribers keep theirs)
            if client is not None:
                try:
                    patch[f"stripe_price_{interval}"] = await _new_price(client, plan, interval, patch[key])
                except stripe_api.StripeError as exc:
                    raise HTTPException(502, f"Stripe refused the new price: {exc.message}") from exc
            else:
                patch[f"stripe_price_{interval}"] = None
    updated = await reg().update_plan(code, patch) if patch else plan
    S.forget()
    await reg().add_audit(
        admin, None, "update_plan", {"code": code, "before": {k: plan.get(k) for k in patch}, "after": patch}
    )
    return updated or plan


@router.post("/plans/sync-stripe")
async def sync_prices(admin: Admin) -> dict[str, Any]:
    """Create the Stripe product and the monthly and yearly prices for every plan that has none yet."""
    client = _stripe()
    made: dict[str, dict[str, str]] = {}
    for plan in await reg().list_plans():
        patch: Row = {}
        for interval in ("month", "year"):
            if not plan.get(f"stripe_price_{interval}"):
                try:
                    price = await _new_price(client, {**plan, **patch}, interval, int(plan[f"price_{interval}_pence"]))
                except stripe_api.StripeError as exc:
                    raise HTTPException(502, f"Stripe refused: {exc.message}") from exc
                patch[f"stripe_price_{interval}"] = price
        if patch:
            await reg().update_plan(plan["code"], patch)
            made[plan["code"]] = patch
    S.forget()
    await reg().add_audit(admin, None, "sync_prices", {"created": made})
    return {"ok": True, "created": made}


# --------------------------------------------------------------------------- #
# Audit, analytics, bug reports
# --------------------------------------------------------------------------- #


@router.get("/audit")
async def audit(
    _: Admin, account_id: str | None = Query(default=None, max_length=40), page: int = Query(default=1, ge=1)
) -> dict[str, Any]:
    rows, total = await reg().list_audit(account_id, page, PER_PAGE)
    return _paged(rows, total, page)


@router.get("/analytics")
async def analytics(
    _: Admin,
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    end = end or today
    start = start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(400, "`from` is after `to`")
    if (end - start).days > 400:
        raise HTTPException(400, "At most 400 days at a time")
    return await reg().analytics(start, end)


@router.get("/bug-reports")
async def bug_reports(
    _: Admin,
    status: Literal["new", "triaged", "fixed", "wont_fix"] | None = None,
    page: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    rows, total = await reg().list_bug_reports(status, page, PER_PAGE)
    return _paged(rows, total, page)


class BugPatch(StrictBody):
    status: Literal["new", "triaged", "fixed", "wont_fix"] | None = None
    admin_notes: str | None = Field(default=None, max_length=5000)


@router.patch("/bug-reports/{report_id}")
async def patch_bug_report(report_id: str, body: BugPatch, admin: Admin) -> Row:
    patch: Row = body.model_dump(exclude_unset=True)
    if "status" in patch:
        patch["closed_at"] = S.now() if patch["status"] in ("fixed", "wont_fix") else None
    row = await reg().update_bug_report(report_id, patch)
    if row is None:
        raise HTTPException(404, "No such report")
    await reg().add_audit(admin, row.get("account_id"), "update_bug_report", {"id": report_id, **patch})
    return row


@router.get("/bug-reports/{report_id}/screenshot")
async def bug_screenshot(report_id: str, _: Admin) -> dict[str, Any]:
    found = await reg().get_bug_report(report_id)
    if found is None or not found.get("screenshot_path"):
        raise HTTPException(404, "No screenshot for that report")
    url = await reg().screenshot_url(str(found["screenshot_path"]))
    if not url:
        raise HTTPException(503, "The screenshot could not be fetched from storage")
    return {"url": url, "expires_in": 600}
