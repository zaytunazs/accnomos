"""The account registry: Supabase Postgres (schema `accnomos`) over PostgREST, or an in-memory fake.

Holds account metadata only (docs/billing/PLANS_AND_CONTRACT.md): who signed up, their plan and billing state, the
month's usage counts, promo codes, the admin audit log, product events and bug reports. Never books, documents,
receipts, amounts or tokens for other services.

* `SupabaseRegistry` talks to `SUPABASE_URL` with `SUPABASE_SERVICE_ROLE_KEY` (the service role bypasses row-level
  security; the tables have RLS on and no policies, so the anon and authenticated keys see nothing). Plain httpx, no
  SDK; `TRANSPORT` lets the tests answer instead of Supabase. Counters and code redemptions go through SQL functions
  (`bump_usage`, `add_topup`, `claim_code`) so two requests at once cannot both take the last unit.
* `MemoryRegistry` is the same contract in a dict, for the unit tests and test mode (`ACCNOMOS_TEST_MODE=1`).
* `registry()` is None when neither is configured: billing is off, nothing is limited, `/account` says so.
"""

from __future__ import annotations

import copy
import itertools
import os
import re
import uuid
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.billing.plans import DEFAULT_PLANS, TOPUP_VALID_MONTHS

Row = dict[str, Any]

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests: answer instead of Supabase
SCHEMA = "accnomos"
SCREENSHOT_BUCKET = "bug-screenshots"

_DT_FIELDS = frozenset(
    {
        "created_at",
        "last_seen_at",
        "trial_ends_at",
        "comp_until",
        "current_period_end",
        "expires_at",
        "redeemed_at",
        "at",
        "topup_expires_at",
        "received_at",
    }
)
FEATURE_EVENTS = (
    "document_scanned",
    "proposal_approved",
    "bank_synced",
    "ask",
    "vat_export",
    "itsa_export",
    "ebay_sync",
)


class RegistryError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"registry: {message}" + (f" (HTTP {status})" if status else ""))
        self.status = status


class StorageUnavailable(RuntimeError):
    """Screenshots need Supabase Storage; the in-memory registry keeps them only when told to."""


def _now() -> datetime:
    return datetime.now(UTC)


def parse_dt(value: Any) -> Any:
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return value


def _parse_row(row: Row) -> Row:
    out = dict(row)
    for k in _DT_FIELDS & out.keys():
        out[k] = parse_dt(out[k])
    if isinstance(out.get("month"), str):
        out["month"] = date.fromisoformat(out["month"][:10])
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def empty_usage(account_id: str, month: date) -> Row:
    return {
        "account_id": account_id,
        "month": month,
        "docs": 0,
        "ask": 0,
        "invoices": 0,
        "topup_docs_remaining": 0,
        "topup_expires_at": None,
    }


def carried_topup(prev: Row | None, now: datetime) -> tuple[int, datetime | None]:
    """Top-up documents carry over from month to month until they expire (12 months after the latest purchase)."""
    if not prev:
        return 0, None
    expires = prev.get("topup_expires_at")
    if not isinstance(expires, datetime) or expires <= now:
        return 0, None
    return int(prev.get("topup_docs_remaining") or 0), expires


def add_months(dt: datetime, months: int) -> datetime:
    y, m = divmod(dt.month - 1 + months, 12)
    year, month = dt.year + y, m + 1
    for day in (dt.day, 30, 29, 28):
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    return dt.replace(year=year, month=month, day=28)


class Registry(ABC):
    """What the billing, admin and analytics code needs from the account store."""

    storage_configured: bool = False

    # accounts
    @abstractmethod
    async def find_account(self, auth_kind: str, auth_subject: str) -> Row | None: ...
    @abstractmethod
    async def get_account(self, account_id: str) -> Row | None: ...
    @abstractmethod
    async def get_account_by_customer(self, customer_id: str) -> Row | None: ...
    @abstractmethod
    async def create_account(self, row: Row) -> Row:
        """Insert; when (auth_kind, auth_subject) already exists (two first calls at once), return that one."""

    @abstractmethod
    async def update_account(self, account_id: str, patch: Row) -> Row | None: ...
    @abstractmethod
    async def list_accounts(
        self, q: str | None, plan: str | None, status: str | None, page: int, per_page: int
    ) -> tuple[list[Row], int]: ...

    # plans
    @abstractmethod
    async def list_plans(self) -> list[Row]: ...
    @abstractmethod
    async def update_plan(self, code: str, patch: Row) -> Row | None: ...

    # usage
    @abstractmethod
    async def get_usage(self, account_id: str, month: date) -> Row: ...
    @abstractmethod
    async def usage_history(self, account_id: str, limit: int = 12) -> list[Row]: ...
    @abstractmethod
    async def usage_for(self, account_ids: list[str], month: date) -> dict[str, Row]: ...
    @abstractmethod
    async def bump_usage(self, account_id: str, month: date, field: str, n: int, limit: int | None) -> tuple[bool, Row]:
        """Add `n` to `field` unless that goes past `limit` (None: no limit). For `docs`, what is over the monthly
        allowance comes out of the top-up balance; refused when that is short too. Atomic."""

    @abstractmethod
    async def add_topup(self, account_id: str, month: date, n: int) -> Row: ...

    # promo codes
    @abstractmethod
    async def list_codes(self) -> list[Row]: ...
    @abstractmethod
    async def get_code(self, code: str) -> Row | None: ...
    @abstractmethod
    async def create_code(self, row: Row) -> Row: ...
    @abstractmethod
    async def update_code(self, code: str, patch: Row) -> Row | None: ...
    @abstractmethod
    async def claim_code(self, code: str, account_id: str) -> Row | None:
        """Count one redemption and record it, if the code is active, unexpired, under its maximum and not already
        redeemed by this account. Atomic. None when refused."""

    @abstractmethod
    async def redemptions(self, account_id: str) -> list[Row]: ...

    # admin audit
    @abstractmethod
    async def add_audit(self, admin_email: str, account_id: str | None, action: str, detail: Row) -> None: ...
    @abstractmethod
    async def list_audit(self, account_id: str | None, page: int, per_page: int) -> tuple[list[Row], int]: ...

    # events and analytics
    @abstractmethod
    async def add_event(self, row: Row) -> None: ...
    @abstractmethod
    async def metrics(self) -> Row: ...
    @abstractmethod
    async def analytics(self, start: date, end: date) -> Row: ...

    # Stripe webhook idempotency
    @abstractmethod
    async def record_stripe_event(self, event_id: str, event_type: str) -> bool:
        """True the first time this event id is seen."""

    @abstractmethod
    async def forget_stripe_event(self, event_id: str) -> None:
        """Handling failed: let Stripe's retry try again."""

    # bug reports
    @abstractmethod
    async def add_bug_report(self, row: Row) -> Row: ...
    @abstractmethod
    async def list_bug_reports(self, status: str | None, page: int, per_page: int) -> tuple[list[Row], int]: ...
    @abstractmethod
    async def get_bug_report(self, report_id: str) -> Row | None: ...
    @abstractmethod
    async def update_bug_report(self, report_id: str, patch: Row) -> Row | None: ...
    @abstractmethod
    async def upload_screenshot(self, path: str, data: bytes, content_type: str) -> None: ...
    @abstractmethod
    async def screenshot_url(self, path: str, expires_s: int = 600) -> str | None:
        """A short-lived link for an admin to view a screenshot (None when there is none)."""


# --------------------------------------------------------------------------- #
# Analytics over rows (the in-memory registry; Supabase runs the same in SQL)
# --------------------------------------------------------------------------- #


def metrics_from(accounts: list[Row], plans: list[Row], now: datetime) -> Row:
    prices = {p["code"]: p for p in plans}
    since = (now - timedelta(days=29)).date()
    by_day: Counter[str] = Counter()
    for a in accounts:
        created = a.get("created_at")
        if isinstance(created, datetime) and created.date() >= since:
            by_day[created.date().isoformat()] += 1
    days = [(since + timedelta(days=i)).isoformat() for i in range(30)]
    active_by_plan: Counter[str] = Counter()
    mrr = 0
    for a in accounts:
        if a.get("status") == "active":
            active_by_plan[a.get("plan_code") or "?"] += 1
            plan = prices.get(a.get("plan_code") or "")
            if plan:
                if a.get("billing_interval") == "year":
                    mrr += round(int(plan["price_year_pence"]) / 12)
                else:
                    mrr += int(plan["price_month_pence"])
    week = now + timedelta(days=7)
    ending = [
        a
        for a in accounts
        if a.get("status") == "trialing"
        and isinstance(a.get("trial_ends_at"), datetime)
        and now <= a["trial_ends_at"] <= week
    ]
    status = Counter(a.get("status") for a in accounts)
    return {
        "signups_by_day": [{"day": d, "count": by_day.get(d, 0)} for d in days],
        "total_accounts": len(accounts),
        "trialing": status.get("trialing", 0),
        "active_by_plan": {code: active_by_plan.get(code, 0) for code in prices},
        "active": status.get("active", 0),
        "past_due": status.get("past_due", 0),
        "cancelled": status.get("cancelled", 0),
        "trial_ended": status.get("trial_ended", 0),
        "comped": status.get("comped", 0),
        "mrr_pence": mrr,
        "trials_ending_7d": len(ending),
        "trials_ending": [
            {"id": a["id"], "email": a.get("email"), "trial_ends_at": a["trial_ends_at"]}
            for a in sorted(ending, key=lambda a: a["trial_ends_at"])[:50]
        ],
    }


def analytics_from(accounts: list[Row], events: list[Row], start: date, end: date) -> Row:
    """`start`..`end` inclusive (UTC days)."""

    def day(e: Row) -> date:
        return e["at"].astimezone(UTC).date()

    in_range = [e for e in events if start <= day(e) <= end]
    dau: dict[str, set[str]] = defaultdict(set)
    for e in in_range:
        if e.get("account_id"):
            dau[day(e).isoformat()].add(e["account_id"])
    n_days = (end - start).days + 1
    days = [(start + timedelta(days=i)).isoformat() for i in range(max(0, n_days))]
    signups = [
        a
        for a in accounts
        if isinstance(a.get("created_at"), datetime) and start <= a["created_at"].astimezone(UTC).date() <= end
    ]
    ids = {a["id"] for a in signups}
    scanned = {e["account_id"] for e in events if e["name"] == "document_scanned" and e.get("account_id") in ids}
    approved = {e["account_id"] for e in events if e["name"] == "proposal_approved" and e.get("account_id") in scanned}
    features = Counter(e["name"] for e in in_range if e["name"] in FEATURE_EVENTS)
    ended = [
        a
        for a in accounts
        if isinstance(a.get("trial_ends_at"), datetime) and start <= a["trial_ends_at"].astimezone(UTC).date() <= end
    ]
    paid_ids = {e["account_id"] for e in events if e["name"] == "subscription_active"}
    converted = [a for a in ended if a.get("status") in ("active", "past_due") or a["id"] in paid_ids]
    cancelled = {e["account_id"] for e in in_range if e["name"] == "subscription_cancelled" and e.get("account_id")}
    active_now = sum(1 for a in accounts if a.get("status") in ("active", "past_due"))
    base = active_now + len(cancelled)
    errors: Counter[str] = Counter()
    for e in in_range:
        if e["name"] == "api_error":
            props = e.get("props") or {}
            errors[f"{props.get('method', '')} {props.get('route', '?')}".strip()] += 1
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "daily_active": [{"day": d, "count": len(dau.get(d, ()))} for d in days],
        "funnel": {"signed_up": len(ids), "first_document": len(scanned), "first_approval": len(approved)},
        "features": {name: features.get(name, 0) for name in FEATURE_EVENTS},
        "trial_conversion": {
            "trials_ended": len(ended),
            "converted": len(converted),
            "rate": round(len(converted) / len(ended), 4) if ended else None,
        },
        "churn": {
            "cancelled": len(cancelled),
            "active_at_start": base,
            "rate": round(len(cancelled) / base, 4) if base else None,
        },
        "errors_by_route": [{"route": r, "count": c} for r, c in errors.most_common(20)],
    }


# --------------------------------------------------------------------------- #
# In memory
# --------------------------------------------------------------------------- #


class MemoryRegistry(Registry):
    def __init__(self, *, storage: bool = False) -> None:
        self.accounts: dict[str, Row] = {}
        self.plans: dict[str, Row] = {p["code"]: copy.deepcopy(p) for p in DEFAULT_PLANS}
        self.usage: dict[tuple[str, date], Row] = {}
        self.codes: dict[str, Row] = {}
        self.redeemed: list[Row] = []
        self.audit: list[Row] = []
        self.events: list[Row] = []
        self.stripe_events: dict[str, str] = {}
        self.bug_reports: dict[str, Row] = {}
        self.screenshots: dict[str, bytes] = {}
        self.storage_configured = storage
        self._ids = itertools.count(1)

    def clear_activity(self) -> None:
        """Test mode's /__test/reset: usage, events and webhook ids start again (accounts and codes stay)."""
        self.usage.clear()
        self.events.clear()
        self.stripe_events.clear()

    @staticmethod
    def _copy(row: Row | None) -> Row | None:
        return copy.deepcopy(row) if row is not None else None

    # accounts
    async def find_account(self, auth_kind: str, auth_subject: str) -> Row | None:
        return self._copy(
            next(
                (a for a in self.accounts.values() if (a["auth_kind"], a["auth_subject"]) == (auth_kind, auth_subject)),
                None,
            )
        )

    async def get_account(self, account_id: str) -> Row | None:
        return self._copy(self.accounts.get(account_id))

    async def get_account_by_customer(self, customer_id: str) -> Row | None:
        return self._copy(next((a for a in self.accounts.values() if a.get("stripe_customer_id") == customer_id), None))

    async def create_account(self, row: Row) -> Row:
        existing = await self.find_account(row["auth_kind"], row["auth_subject"])
        if existing:
            return existing
        base: Row = {
            "id": str(uuid.uuid4()),
            "display_name": None,
            "created_at": _now(),
            "last_seen_at": None,
            "plan_code": "comprehensive",
            "status": "trialing",
            "trial_ends_at": None,
            "comp_until": None,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "billing_interval": None,
            "current_period_end": None,
            "cancel_at_period_end": False,
            "country": None,
            "notes": None,
            "analytics_opt_out": False,
        }
        acc = {**base, **row}
        self.accounts[acc["id"]] = acc
        return copy.deepcopy(acc)

    async def update_account(self, account_id: str, patch: Row) -> Row | None:
        acc = self.accounts.get(account_id)
        if acc is None:
            return None
        acc.update(copy.deepcopy(patch))
        return copy.deepcopy(acc)

    async def list_accounts(
        self, q: str | None, plan: str | None, status: str | None, page: int, per_page: int
    ) -> tuple[list[Row], int]:
        rows = sorted(self.accounts.values(), key=lambda a: a["created_at"], reverse=True)
        if q:
            needle = q.lower()
            rows = [
                a for a in rows if needle in (a.get("email") or "").lower() or needle in (a.get("display_name") or "")
            ]
        if plan:
            rows = [a for a in rows if a.get("plan_code") == plan]
        if status:
            rows = [a for a in rows if a.get("status") == status]
        start = (page - 1) * per_page
        return copy.deepcopy(rows[start : start + per_page]), len(rows)

    # plans
    async def list_plans(self) -> list[Row]:
        return copy.deepcopy(sorted(self.plans.values(), key=lambda p: p.get("sort", 0)))

    async def update_plan(self, code: str, patch: Row) -> Row | None:
        plan = self.plans.get(code)
        if plan is None:
            return None
        plan.update(copy.deepcopy(patch))
        return copy.deepcopy(plan)

    # usage
    def _latest(self, account_id: str, before: date | None = None) -> Row | None:
        rows = [r for (a, m), r in self.usage.items() if a == account_id and (before is None or m < before)]
        return max(rows, key=lambda r: r["month"]) if rows else None

    def _row(self, account_id: str, month: date, create: bool) -> Row:
        row = self.usage.get((account_id, month))
        if row is not None:
            return row
        fresh = empty_usage(account_id, month)
        fresh["topup_docs_remaining"], fresh["topup_expires_at"] = carried_topup(
            self._latest(account_id, month), _now()
        )
        if create:
            self.usage[(account_id, month)] = fresh
        return fresh

    async def get_usage(self, account_id: str, month: date) -> Row:
        return copy.deepcopy(self._row(account_id, month, create=False))

    async def usage_history(self, account_id: str, limit: int = 12) -> list[Row]:
        rows = sorted((r for (a, _), r in self.usage.items() if a == account_id), key=lambda r: r["month"])
        return copy.deepcopy(rows[::-1][:limit])

    async def usage_for(self, account_ids: list[str], month: date) -> dict[str, Row]:
        return {a: copy.deepcopy(self._row(a, month, create=False)) for a in account_ids}

    async def bump_usage(self, account_id: str, month: date, field: str, n: int, limit: int | None) -> tuple[bool, Row]:
        if field not in ("docs", "ask", "invoices"):
            raise ValueError(field)
        row = self._row(account_id, month, create=True)
        expires = row.get("topup_expires_at")
        topup = int(row["topup_docs_remaining"]) if isinstance(expires, datetime) and expires > _now() else 0
        if limit is not None:
            if field == "docs":
                from_topup = max(0, n - max(0, limit - row["docs"]))
                if from_topup > topup:
                    return False, copy.deepcopy(row)
                row["topup_docs_remaining"] = topup - from_topup
            elif row[field] + n > limit:
                return False, copy.deepcopy(row)
        row[field] += n
        return True, copy.deepcopy(row)

    async def add_topup(self, account_id: str, month: date, n: int) -> Row:
        row = self._row(account_id, month, create=True)
        expires = row.get("topup_expires_at")
        current = int(row["topup_docs_remaining"]) if isinstance(expires, datetime) and expires > _now() else 0
        row["topup_docs_remaining"] = current + n
        row["topup_expires_at"] = add_months(_now(), TOPUP_VALID_MONTHS)
        return copy.deepcopy(row)

    # promo codes
    async def list_codes(self) -> list[Row]:
        return copy.deepcopy(sorted(self.codes.values(), key=lambda c: c["created_at"], reverse=True))

    async def get_code(self, code: str) -> Row | None:
        return self._copy(self.codes.get(code))

    async def create_code(self, row: Row) -> Row:
        if row["code"] in self.codes:
            raise RegistryError(409, "a code with that name already exists")
        base: Row = {
            "plan_codes": None,
            "max_redemptions": None,
            "redeemed_count": 0,
            "expires_at": None,
            "active": True,
            "created_by": None,
            "created_at": _now(),
            "stripe_coupon_id": None,
            "duration_months": None,
        }
        self.codes[row["code"]] = {**base, **copy.deepcopy(row)}
        return copy.deepcopy(self.codes[row["code"]])

    async def update_code(self, code: str, patch: Row) -> Row | None:
        row = self.codes.get(code)
        if row is None:
            return None
        row.update(copy.deepcopy(patch))
        return copy.deepcopy(row)

    async def claim_code(self, code: str, account_id: str) -> Row | None:
        row = self.codes.get(code)
        now = _now()
        if (
            row is None
            or not row.get("active")
            or (row.get("expires_at") is not None and row["expires_at"] <= now)
            or (row.get("max_redemptions") is not None and row["redeemed_count"] >= row["max_redemptions"])
            or any(r["code"] == code and r["account_id"] == account_id for r in self.redeemed)
        ):
            return None
        row["redeemed_count"] += 1
        self.redeemed.append({"id": next(self._ids), "code": code, "account_id": account_id, "redeemed_at": now})
        return copy.deepcopy(row)

    async def redemptions(self, account_id: str) -> list[Row]:
        return copy.deepcopy([r for r in self.redeemed if r["account_id"] == account_id])

    # audit
    async def add_audit(self, admin_email: str, account_id: str | None, action: str, detail: Row) -> None:
        self.audit.append(
            {
                "id": next(self._ids),
                "at": _now(),
                "admin_email": admin_email,
                "account_id": account_id,
                "action": action,
                "detail": copy.deepcopy(_jsonable(detail)),
            }
        )

    async def list_audit(self, account_id: str | None, page: int, per_page: int) -> tuple[list[Row], int]:
        rows = [r for r in reversed(self.audit) if account_id is None or r["account_id"] == account_id]
        start = (page - 1) * per_page
        return copy.deepcopy(rows[start : start + per_page]), len(rows)

    # events
    async def add_event(self, row: Row) -> None:
        self.events.append({"id": next(self._ids), "at": _now(), **copy.deepcopy(row)})

    async def metrics(self) -> Row:
        return metrics_from(list(self.accounts.values()), list(self.plans.values()), _now())

    async def analytics(self, start: date, end: date) -> Row:
        return analytics_from(list(self.accounts.values()), self.events, start, end)

    # Stripe
    async def record_stripe_event(self, event_id: str, event_type: str) -> bool:
        if event_id in self.stripe_events:
            return False
        self.stripe_events[event_id] = event_type
        return True

    async def forget_stripe_event(self, event_id: str) -> None:
        self.stripe_events.pop(event_id, None)

    # bug reports
    async def add_bug_report(self, row: Row) -> Row:
        rid = str(uuid.uuid4())
        rec = {"id": rid, "at": _now(), "status": "new", "admin_notes": None, **copy.deepcopy(row)}
        self.bug_reports[rid] = rec
        return copy.deepcopy(rec)

    async def list_bug_reports(self, status: str | None, page: int, per_page: int) -> tuple[list[Row], int]:
        rows = sorted(self.bug_reports.values(), key=lambda r: r["at"], reverse=True)
        if status:
            rows = [r for r in rows if r["status"] == status]
        start = (page - 1) * per_page
        return copy.deepcopy(rows[start : start + per_page]), len(rows)

    async def get_bug_report(self, report_id: str) -> Row | None:
        return self._copy(self.bug_reports.get(report_id))

    async def update_bug_report(self, report_id: str, patch: Row) -> Row | None:
        rec = self.bug_reports.get(report_id)
        if rec is None:
            return None
        rec.update(copy.deepcopy(patch))
        return copy.deepcopy(rec)

    async def upload_screenshot(self, path: str, data: bytes, content_type: str) -> None:
        if not self.storage_configured:
            raise StorageUnavailable("screenshot storage is not configured")
        self.screenshots[path] = data

    async def screenshot_url(self, path: str, expires_s: int = 600) -> str | None:
        return f"memory://{SCREENSHOT_BUCKET}/{path}" if path in self.screenshots else None


# --------------------------------------------------------------------------- #
# Supabase (PostgREST + Storage)
# --------------------------------------------------------------------------- #

_SEARCH_SAFE = re.compile(r"[^A-Za-z0-9@._+ -]")


class SupabaseRegistry(Registry):
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key
        self.storage_configured = True

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False)

    def _headers(self, write: bool = False, prefer: str | None = None) -> dict[str, str]:
        h = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Accept-Profile": SCHEMA,
        }
        if write:
            h["Content-Profile"] = SCHEMA
            h["Content-Type"] = "application/json"
        if prefer:
            h["Prefer"] = prefer
        return h

    async def _req(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        body: Any = None,
        prefer: str | None = None,
        want_count: bool = False,
    ) -> tuple[Any, int | None]:
        write = method != "GET"
        headers = self._headers(write, prefer)
        if want_count:
            headers["Prefer"] = ", ".join(filter(None, [headers.get("Prefer"), "count=exact"]))
        try:
            async with self._client() as c:
                resp = await c.request(
                    method,
                    f"{self.url}/rest/v1/{path}",
                    params=tuple(params or ()),
                    json=_jsonable(body) if body is not None else None,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise RegistryError(0, f"Supabase could not be reached ({type(exc).__name__})") from exc
        if resp.status_code == 409:
            raise RegistryError(409, "already exists")
        if resp.status_code >= 400:
            try:
                msg = str(resp.json().get("message") or resp.text[:200])
            except ValueError:
                msg = resp.text[:200]
            raise RegistryError(resp.status_code, msg[:300])
        total = None
        if want_count:
            rng = resp.headers.get("content-range", "")
            tail = rng.rsplit("/", 1)[-1] if "/" in rng else ""
            total = int(tail) if tail.isdigit() else None
        data = resp.json() if resp.content else None
        return data, total

    async def _rows(self, table: str, params: list[tuple[str, str]]) -> list[Row]:
        data, _ = await self._req("GET", table, params=[("select", "*"), *params])
        return [_parse_row(r) for r in data or []]

    async def _one(self, table: str, params: list[tuple[str, str]]) -> Row | None:
        rows = await self._rows(table, [*params, ("limit", "1")])
        return rows[0] if rows else None

    async def _page(self, table: str, params: list[tuple[str, str]], page: int, per_page: int) -> tuple[list[Row], int]:
        data, total = await self._req(
            "GET",
            table,
            params=[("select", "*"), *params, ("limit", str(per_page)), ("offset", str((page - 1) * per_page))],
            want_count=True,
        )
        rows = [_parse_row(r) for r in data or []]
        return rows, total if total is not None else len(rows)

    async def _patch(self, table: str, params: list[tuple[str, str]], patch: Row) -> Row | None:
        data, _ = await self._req("PATCH", table, params=params, body=patch, prefer="return=representation")
        return _parse_row(data[0]) if data else None

    async def _insert(self, table: str, row: Row, prefer: str = "return=representation") -> list[Row]:
        data, _ = await self._req("POST", table, body=row, prefer=prefer)
        return [_parse_row(r) for r in data or []]

    async def _rpc(self, fn: str, args: Row) -> Any:
        data, _ = await self._req("POST", f"rpc/{fn}", body=args)
        return data

    # accounts
    async def find_account(self, auth_kind: str, auth_subject: str) -> Row | None:
        return await self._one("accounts", [("auth_kind", f"eq.{auth_kind}"), ("auth_subject", f"eq.{auth_subject}")])

    async def get_account(self, account_id: str) -> Row | None:
        try:
            uuid.UUID(account_id)
        except ValueError:
            return None
        return await self._one("accounts", [("id", f"eq.{account_id}")])

    async def get_account_by_customer(self, customer_id: str) -> Row | None:
        return await self._one("accounts", [("stripe_customer_id", f"eq.{customer_id}")])

    async def create_account(self, row: Row) -> Row:
        data, _ = await self._req(
            "POST",
            "accounts",
            params=[("on_conflict", "auth_kind,auth_subject")],
            body=row,
            prefer="resolution=ignore-duplicates, return=representation",
        )
        if data:
            return _parse_row(data[0])
        found = await self.find_account(row["auth_kind"], row["auth_subject"])
        if found is None:
            raise RegistryError(0, "account was neither created nor found")
        return found

    async def update_account(self, account_id: str, patch: Row) -> Row | None:
        return await self._patch("accounts", [("id", f"eq.{account_id}")], patch)

    async def list_accounts(
        self, q: str | None, plan: str | None, status: str | None, page: int, per_page: int
    ) -> tuple[list[Row], int]:
        params: list[tuple[str, str]] = [("order", "created_at.desc")]
        if q and (needle := _SEARCH_SAFE.sub("", q).strip()):
            params.append(("or", f"(email.ilike.*{needle}*,display_name.ilike.*{needle}*)"))
        if plan:
            params.append(("plan_code", f"eq.{plan}"))
        if status:
            params.append(("status", f"eq.{status}"))
        return await self._page("accounts", params, page, per_page)

    # plans
    async def list_plans(self) -> list[Row]:
        return await self._rows("plans", [("order", "sort.asc")])

    async def update_plan(self, code: str, patch: Row) -> Row | None:
        return await self._patch("plans", [("code", f"eq.{code}")], patch)

    # usage
    async def get_usage(self, account_id: str, month: date) -> Row:
        rows = await self._rows(
            "usage",
            [("account_id", f"eq.{account_id}"), ("month", f"lte.{month.isoformat()}"), ("order", "month.desc")],
        )
        latest = rows[0] if rows else None
        if latest and latest["month"] == month:
            return latest
        row = empty_usage(account_id, month)
        row["topup_docs_remaining"], row["topup_expires_at"] = carried_topup(latest, _now())
        return row

    async def usage_history(self, account_id: str, limit: int = 12) -> list[Row]:
        return await self._rows(
            "usage", [("account_id", f"eq.{account_id}"), ("order", "month.desc"), ("limit", str(limit))]
        )

    async def usage_for(self, account_ids: list[str], month: date) -> dict[str, Row]:
        out = {a: empty_usage(a, month) for a in account_ids}
        if account_ids:
            rows = await self._rows(
                "usage", [("account_id", f"in.({','.join(account_ids)})"), ("month", f"eq.{month.isoformat()}")]
            )
            out.update({r["account_id"]: r for r in rows})
        return out

    async def bump_usage(self, account_id: str, month: date, field: str, n: int, limit: int | None) -> tuple[bool, Row]:
        out = await self._rpc(
            "bump_usage",
            {"p_account": account_id, "p_month": month.isoformat(), "p_field": field, "p_n": n, "p_limit": limit},
        )
        out = out or {}
        return bool(out.get("ok")), _parse_row(out.get("usage") or empty_usage(account_id, month))

    async def add_topup(self, account_id: str, month: date, n: int) -> Row:
        out = await self._rpc("add_topup", {"p_account": account_id, "p_month": month.isoformat(), "p_n": n})
        return _parse_row(out or empty_usage(account_id, month))

    # promo codes
    async def list_codes(self) -> list[Row]:
        return await self._rows("promo_codes", [("order", "created_at.desc")])

    async def get_code(self, code: str) -> Row | None:
        return await self._one("promo_codes", [("code", f"eq.{code}")])

    async def create_code(self, row: Row) -> Row:
        rows = await self._insert("promo_codes", row)
        return rows[0]

    async def update_code(self, code: str, patch: Row) -> Row | None:
        return await self._patch("promo_codes", [("code", f"eq.{code}")], patch)

    async def claim_code(self, code: str, account_id: str) -> Row | None:
        out = await self._rpc("claim_code", {"p_code": code, "p_account": account_id})
        return _parse_row(out) if isinstance(out, dict) else None

    async def redemptions(self, account_id: str) -> list[Row]:
        return await self._rows("redemptions", [("account_id", f"eq.{account_id}"), ("order", "redeemed_at.desc")])

    # audit
    async def add_audit(self, admin_email: str, account_id: str | None, action: str, detail: Row) -> None:
        await self._insert(
            "admin_audit",
            {"admin_email": admin_email, "account_id": account_id, "action": action, "detail": detail},
            prefer="return=minimal",
        )

    async def list_audit(self, account_id: str | None, page: int, per_page: int) -> tuple[list[Row], int]:
        params = [("order", "at.desc")] + ([("account_id", f"eq.{account_id}")] if account_id else [])
        return await self._page("admin_audit", params, page, per_page)

    # events
    async def add_event(self, row: Row) -> None:
        await self._insert("events", row, prefer="return=minimal")

    async def metrics(self) -> Row:
        out = await self._rpc("admin_metrics", {})
        return out if isinstance(out, dict) else {}

    async def analytics(self, start: date, end: date) -> Row:
        out = await self._rpc("analytics", {"p_from": start.isoformat(), "p_to": end.isoformat()})
        return out if isinstance(out, dict) else {}

    # Stripe
    async def record_stripe_event(self, event_id: str, event_type: str) -> bool:
        data, _ = await self._req(
            "POST",
            "stripe_events",
            params=[("on_conflict", "id")],
            body={"id": event_id, "type": event_type},
            prefer="resolution=ignore-duplicates, return=representation",
        )
        return bool(data)

    async def forget_stripe_event(self, event_id: str) -> None:
        await self._req("DELETE", "stripe_events", params=[("id", f"eq.{event_id}")])

    # bug reports
    async def add_bug_report(self, row: Row) -> Row:
        return (await self._insert("bug_reports", row))[0]

    async def list_bug_reports(self, status: str | None, page: int, per_page: int) -> tuple[list[Row], int]:
        params = [("order", "at.desc")] + ([("status", f"eq.{status}")] if status else [])
        return await self._page("bug_reports", params, page, per_page)

    async def get_bug_report(self, report_id: str) -> Row | None:
        try:
            uuid.UUID(report_id)
        except ValueError:
            return None
        return await self._one("bug_reports", [("id", f"eq.{report_id}")])

    async def update_bug_report(self, report_id: str, patch: Row) -> Row | None:
        try:
            uuid.UUID(report_id)
        except ValueError:
            return None
        return await self._patch("bug_reports", [("id", f"eq.{report_id}")], patch)

    async def upload_screenshot(self, path: str, data: bytes, content_type: str) -> None:
        try:
            async with self._client() as c:
                resp = await c.post(
                    f"{self.url}/storage/v1/object/{SCREENSHOT_BUCKET}/{path}",
                    content=data,
                    headers={
                        "apikey": self.key,
                        "Authorization": f"Bearer {self.key}",
                        "Content-Type": content_type,
                        "x-upsert": "false",
                    },
                )
        except httpx.HTTPError as exc:
            raise StorageUnavailable(f"Supabase Storage could not be reached ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise StorageUnavailable(f"Supabase Storage refused the screenshot (HTTP {resp.status_code})")

    async def screenshot_url(self, path: str, expires_s: int = 600) -> str | None:
        try:
            async with self._client() as c:
                resp = await c.post(
                    f"{self.url}/storage/v1/object/sign/{SCREENSHOT_BUCKET}/{path}",
                    json={"expiresIn": expires_s},
                    headers={"apikey": self.key, "Authorization": f"Bearer {self.key}"},
                )
        except httpx.HTTPError:
            return None
        if resp.status_code >= 400:
            return None
        signed = (resp.json() or {}).get("signedURL") or (resp.json() or {}).get("signedUrl")
        return f"{self.url}/storage/v1{signed}" if isinstance(signed, str) else None


# --------------------------------------------------------------------------- #
# Which one
# --------------------------------------------------------------------------- #

_override: Registry | None = None
_cached: tuple[tuple[str, str, bool], Registry | None] | None = None


def install(reg: Registry | None) -> None:
    """Tests: use `reg` (None: back to the environment)."""
    global _override, _cached
    _override, _cached = reg, None


def reset_test_mode() -> None:
    """Test mode only: a fresh month for the in-memory registry (each e2e test starts with nothing used)."""
    from app.ai.config import is_test_mode

    reg = registry()
    if is_test_mode() and isinstance(reg, MemoryRegistry):
        reg.clear_activity()


def registry() -> Registry | None:
    """The configured registry: an installed one (tests), Supabase when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are
    set, the in-memory fake in test mode, else None (billing off)."""
    global _cached
    if _override is not None:
        return _override
    from app.ai.config import is_test_mode

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    test = is_test_mode()
    sig = (url, key, test)
    if _cached is not None and _cached[0] == sig:
        return _cached[1]
    reg: Registry | None
    if url and key:
        reg = SupabaseRegistry(url, key)
    elif test:
        reg = MemoryRegistry()
    else:
        reg = None
    _cached = (sig, reg)
    return reg
