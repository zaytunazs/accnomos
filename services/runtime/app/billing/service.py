"""Accounts, plan status, limits and the per-request usage meter.

* **Registration.** The first authenticated call from a verified identity (app/identity.py) creates the account:
  status `trialing`, plan `comprehensive`, trial 90 days. The key is (auth_kind, auth_subject): the Graph `/me` id or
  Google's `sub`, falling back to `email:<address>` when the provider gives no id. `last_seen_at` is written at most
  once an hour.
* **Status.** Stripe is the source of truth for paying accounts (webhooks, app/billing/webhooks.py). Two expiries are
  ours: a trial with no subscription past `trial_ends_at`, and a comp past `comp_until`; both become `trial_ended`
  (read-only) the first time the account is seen after the date.
* **Limits.** A trial gets Comprehensive's limits; `comped` and paying accounts their `plan_code`'s. `trial_ended` and
  `cancelled` are read-only. Own-AI requests (the user's own Meta key or their own local model) do not count AI-read
  documents or Ask questions.
* **The meter** rides in a context variable for the request (and any background job it starts), so the document reader
  (app/pipeline.py) charges a document without knowing about billing. No meter: nothing is limited.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.billing import plans as P
from app.billing.registry import Registry, Row

log = logging.getLogger("accnomos.billing")

STATUSES = ("trialing", "active", "past_due", "trial_ended", "cancelled", "comped")
READ_ONLY = frozenset({"trial_ended", "cancelled"})
TOUCH_EVERY = timedelta(hours=1)
ACCOUNT_TTL_S = 60.0
PLANS_TTL_S = 60.0

LABELS = {
    "docs": "AI-read documents this month",
    "ask": "Ask questions this month",
    "invoices": "sales invoices and quotes this month",
    "bank_feeds": "live bank feeds",
    "marketplaces": "marketplace connections",
    "users": "users",
    "autopilot_rules": "Autopilot rules",
    "payroll_employees": "payroll employees",
}


def now() -> datetime:
    return datetime.now(UTC)


def topup_balance(usage: Row) -> int:
    """Unexpired top-up documents on a usage row."""
    expires = usage.get("topup_expires_at")
    return int(usage.get("topup_docs_remaining") or 0) if isinstance(expires, datetime) and expires > now() else 0


def upgrade_url() -> str:
    from app.billing.stripe_api import settings

    return settings().return_url


# --------------------------------------------------------------------------- #
# Errors the routes turn into 402
# --------------------------------------------------------------------------- #


class PlanLimit(Exception):
    """An action that would pass the plan's limit. Rendered as HTTP 402 `{code: "plan_limit", ...}`."""

    def __init__(self, counter: str, limit: int, used: int) -> None:
        super().__init__(f"plan limit {counter}: {used}/{limit}")
        self.counter, self.limit, self.used = counter, limit, used

    def body(self) -> dict[str, Any]:
        what = LABELS.get(self.counter, self.counter)
        if self.counter == "docs":
            hint = "Buy a top-up of 100 documents for £3, upgrade your plan, or use your own AI (Settings › AI)."
        elif self.counter in P.MONTHLY:
            hint = "Upgrade your plan, or wait until the 1st when the count starts again."
        else:
            hint = "Upgrade your plan to add more."
        detail = (
            f"Your plan doesn't include {what}. {hint}"
            if self.limit == 0
            else f"You've used {self.used} of {self.limit} {what}. {hint}"
        )
        return {
            "code": "plan_limit",
            "counter": self.counter,
            "limit": self.limit,
            "used": self.used,
            "upgrade_url": upgrade_url(),
            "detail": detail,
        }


class ReadOnly(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(f"account is read-only ({status})")
        self.status = status

    def body(self) -> dict[str, Any]:
        detail = (
            "Your free trial has ended, so your books are read-only. Everything is still there: you can view and "
            "export it. Choose a plan to carry on adding and changing things."
            if self.status == "trial_ended"
            else "Your subscription has ended, so your books are read-only. Everything is still there: you can view "
            "and export it. Choose a plan to carry on."
        )
        return {"code": "read_only", "status": self.status, "upgrade_url": upgrade_url(), "detail": detail}


# --------------------------------------------------------------------------- #
# Caches (per process): accounts by identity, the plans table
# --------------------------------------------------------------------------- #

_accounts: dict[tuple[str, str], tuple[float, Row]] = {}
_plans: tuple[float, dict[str, Row]] | None = None


def forget(account: Row | None = None) -> None:
    """Drop cached copies (after a write here; a webhook's write elsewhere shows within ACCOUNT_TTL_S)."""
    global _plans
    if account is None:
        _accounts.clear()
        _plans = None
        return
    _accounts.pop((account.get("auth_kind", ""), account.get("auth_subject", "")), None)


def _cache(account: Row) -> Row:
    _accounts[(account["auth_kind"], account["auth_subject"])] = (time.monotonic() + ACCOUNT_TTL_S, account)
    if len(_accounts) > 5000:
        _accounts.clear()
    return account


async def plans_by_code(reg: Registry) -> dict[str, Row]:
    global _plans
    if _plans is not None and _plans[0] > time.monotonic():
        return _plans[1]
    rows = {p["code"]: p for p in await reg.list_plans()}
    _plans = (time.monotonic() + PLANS_TTL_S, rows)
    return rows


# --------------------------------------------------------------------------- #
# Who, and their account
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Who:
    email: str
    name: str
    kind: str  # personal | work | google
    subject: str


def who_from(identity: Any, kind: str) -> Who:
    email = str(getattr(identity, "email", "") or "").strip().lower()
    subject = str(getattr(identity, "subject", "") or "").strip() or f"email:{email}"
    return Who(email=email, name=str(getattr(identity, "name", "") or ""), kind=kind, subject=subject)


def effective_status(acc: Row, at: datetime) -> str:
    status = acc.get("status") or "trialing"
    if status == "trialing" and not acc.get("stripe_subscription_id"):
        ends = acc.get("trial_ends_at")
        if isinstance(ends, datetime) and ends <= at:
            return "trial_ended"
    if status == "comped":
        until = acc.get("comp_until")
        if isinstance(until, datetime) and until <= at:
            return "trial_ended"
    return status


async def ensure_account(reg: Registry, who: Who) -> Row:
    """The caller's account: registered on the first call, `last_seen_at` refreshed at most hourly, an expired trial
    or comp moved to `trial_ended`."""
    key = (who.kind, who.subject)
    hit = _accounts.get(key)
    t = now()
    if hit is not None and hit[0] > time.monotonic():
        acc = hit[1]
        if effective_status(acc, t) == acc.get("status"):
            return acc
    acc = await reg.find_account(who.kind, who.subject)
    if acc is None:
        acc = await reg.create_account(
            {
                "email": who.email,
                "display_name": who.name or None,
                "auth_kind": who.kind,
                "auth_subject": who.subject,
                "plan_code": P.TRIAL_PLAN,
                "status": "trialing",
                "trial_ends_at": t + timedelta(days=P.TRIAL_DAYS),
                "last_seen_at": t,
            }
        )
        if abs((acc.get("created_at") or t) - t) < timedelta(minutes=1):
            await emit(reg, acc, "signup", {"kind": who.kind})
        return _cache(acc)
    patch: Row = {}
    seen = acc.get("last_seen_at")
    if not isinstance(seen, datetime) or t - seen >= TOUCH_EVERY:
        patch["last_seen_at"] = t
    if who.email and who.email != acc.get("email"):
        patch["email"] = who.email
    status = effective_status(acc, t)
    if status != acc.get("status"):
        patch["status"] = status
    if patch:
        acc = await reg.update_account(acc["id"], patch) or {**acc, **patch}
        if patch.get("status") == "trial_ended":
            await emit(reg, acc, "trial_ended", {})
    return _cache(acc)


def limits_for(acc: Row, plans: Mapping[str, Row]) -> dict[str, Any]:
    status = acc.get("status")
    code = P.TRIAL_PLAN if status == "trialing" else (acc.get("plan_code") or P.TRIAL_PLAN)
    plan = plans.get(code) or plans.get(P.TRIAL_PLAN) or {}
    return dict(plan.get("limits") or {})


# --------------------------------------------------------------------------- #
# Own AI: the user's own key or own local model
# --------------------------------------------------------------------------- #


def own_ai(headers: Mapping[str, str]) -> bool:
    """True when the request's AI runs on the user's own account or machine, so it costs us nothing:

    * `X-AI-Mode: key` with the user's own `X-Meta-Api-Key`, unless `X-AI-Route` puts the server's local model first
      (`local_first`, `local_only`);
    * `X-AI-Mode: local` with an `X-AI-Base-Url` that is not the server's own model (OLLAMA_BASE, or one of the
      server's AI_PROVIDERS), unless `X-AI-Route: meta_first` puts the server's Meta key first.

    Anything else, including no AI headers (the server's provider chain), is our AI and counts."""
    get = lambda k: (headers.get(k) or headers.get(k.lower()) or "").strip()  # noqa: E731
    mode, route = get("X-AI-Mode").lower(), get("X-AI-Route").lower()
    if mode == "key":
        return bool(get("X-Meta-Api-Key")) and route not in ("local_first", "local_only")
    if mode == "local":
        base = get("X-AI-Base-Url").rstrip("/").lower()
        if not base or route == "meta_first":
            return False
        server = {os.getenv("OLLAMA_BASE", "").strip().rstrip("/").lower()}
        with contextlib.suppress(Exception):
            from app.ai import providers

            server |= {c.base_url.rstrip("/").lower() for c in providers.chain_config().chain()}
        return base not in {s for s in server if s}
    return False


# --------------------------------------------------------------------------- #
# Events (first-party analytics)
# --------------------------------------------------------------------------- #


async def emit(reg: Registry, acc: Row | None, name: str, props: dict[str, Any], app: str = "api") -> None:
    """Record a server-side event, unless the account opted out. Never raises."""
    if acc is not None and acc.get("analytics_opt_out"):
        return
    try:
        await reg.add_event(
            {
                "account_id": acc["id"] if acc else None,
                "name": name,
                "props": props,
                "app": app,
                "version": os.getenv("ACCNOMOS_VERSION") or None,
            }
        )
    except Exception:  # noqa: BLE001  analytics must never break the request
        log.warning("event %s not recorded", name, exc_info=True)


# --------------------------------------------------------------------------- #
# The meter
# --------------------------------------------------------------------------- #


@dataclass
class Meter:
    reg: Registry
    account: Row
    limits: dict[str, Any]
    own_ai: bool
    notices: list[str] = field(default_factory=list)  # limits met without refusing (X-Plan-Limit)

    @property
    def month(self) -> date:
        return P.month_start()

    def limit(self, counter: str) -> int | None:
        return P.limit_of(self.limits, counter)

    def exempt(self, counter: str) -> bool:
        return self.own_ai and counter in ("docs", "ask")

    async def precheck(self, counter: str) -> None:
        """Refuse before starting when a monthly counter is already used up (a document batch, an Ask question)."""
        limit = self.limit(counter)
        if limit is None or self.exempt(counter):
            return
        usage = await self.reg.get_usage(self.account["id"], self.month)
        used = int(usage.get(counter) or 0)
        if counter == "docs":
            if used >= limit and topup_balance(usage) <= 0:
                raise PlanLimit(counter, limit, used)
        elif used >= limit:
            raise PlanLimit(counter, limit, used)

    async def charge_document(self) -> None:
        """One AI-read document, before the model is called: refused (PlanLimit) when the month's allowance and any
        top-up are used up. Own-AI documents are not counted."""
        if not self.exempt("docs"):
            limit = self.limit("docs")
            ok, row = await self.reg.bump_usage(self.account["id"], self.month, "docs", 1, limit)
            if not ok:
                raise PlanLimit("docs", limit or 0, int(row.get("docs") or 0))
        await emit(self.reg, self.account, "document_scanned", {"own_ai": self.own_ai})

    async def record(self, counter: str, n: int = 1) -> None:
        """Count a finished action (after it succeeded): Ask questions, invoices and quotes."""
        if n <= 0 or self.exempt(counter):
            return
        try:
            await self.reg.bump_usage(self.account["id"], self.month, counter, n, None)
        except Exception:  # noqa: BLE001  the user's action already happened; a lost count is ours to absorb
            log.warning("usage %s not recorded", counter, exc_info=True)

    def require_room(self, counter: str, in_use: int) -> None:
        """For what is set up rather than used up (bank feeds, marketplaces, Autopilot rules): refuse adding one more
        when `in_use` already reaches the limit."""
        limit = self.limit(counter)
        if limit is not None and in_use >= limit:
            raise PlanLimit(counter, limit, in_use)

    def has_room(self, counter: str, in_use: int) -> bool:
        limit = self.limit(counter)
        return limit is None or in_use < limit


_meter: ContextVar[Meter | None] = ContextVar("billing_meter", default=None)


def current() -> Meter | None:
    return _meter.get()


@contextlib.contextmanager
def metering(meter: Meter | None) -> Iterator[None]:
    token = _meter.set(meter)
    try:
        yield
    finally:
        _meter.reset(token)


async def charge_document() -> None:
    """app/pipeline.py: one AI read is about to happen. A no-op without billing."""
    m = _meter.get()
    if m is not None:
        await m.charge_document()


def require_room(counter: str, in_use: int) -> None:
    m = _meter.get()
    if m is not None:
        m.require_room(counter, in_use)


def has_room(counter: str, in_use: int) -> bool:
    """False (and noted for the X-Plan-Limit header) when one more `counter` would pass the limit."""
    m = _meter.get()
    if m is None or m.has_room(counter, in_use):
        return True
    m.notices.append(counter)
    return False


# --------------------------------------------------------------------------- #
# The customer view (GET /account)
# --------------------------------------------------------------------------- #


async def account_view(reg: Registry, acc: Row, own: bool, gauges: Mapping[str, int | None]) -> dict[str, Any]:
    plans = await plans_by_code(reg)
    usage = await reg.get_usage(acc["id"], P.month_start())
    topup = topup_balance(usage)
    expires = usage.get("topup_expires_at")
    return {
        "configured": True,
        "id": acc["id"],
        "email": acc.get("email"),
        "display_name": acc.get("display_name"),
        "plan_code": acc.get("plan_code"),
        "status": acc.get("status"),
        "read_only": acc.get("status") in READ_ONLY,
        "trial_ends_at": acc.get("trial_ends_at"),
        "comp_until": acc.get("comp_until"),
        "billing_interval": acc.get("billing_interval"),
        "current_period_end": acc.get("current_period_end"),
        "cancel_at_period_end": bool(acc.get("cancel_at_period_end")),
        "has_payment_account": bool(acc.get("stripe_customer_id")),
        "analytics_opt_out": bool(acc.get("analytics_opt_out")),
        "usage": {
            "docs": int(usage.get("docs") or 0),
            "ask": int(usage.get("ask") or 0),
            "invoices": int(usage.get("invoices") or 0),
            "bank_feeds": gauges.get("bank_feeds"),
            "users": gauges.get("users"),
            "marketplaces": gauges.get("marketplaces"),
            "autopilot_rules": gauges.get("autopilot_rules"),
            "topup_docs_remaining": topup,
            "topup_expires_at": expires if topup else None,
        },
        "limits": limits_for(acc, plans),
        "own_ai": own,
        "upgrade_url": upgrade_url(),
    }


def not_configured_view() -> dict[str, Any]:
    return {
        "configured": False,
        "detail": "Billing is not configured on this server: every feature is available without limits.",
    }
