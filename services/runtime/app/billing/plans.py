"""Plans and their limits (docs/billing/PLANS_AND_CONTRACT.md). The `plans` table is the live copy, editable in the
admin; `DEFAULT_PLANS` is its seed (supabase/migrations/0001_accounts.sql) and what the in-memory registry starts with.

A limit is an integer (0: not on this plan) or None (unlimited). Feature flags are booleans; `support` is a word.
Monthly counters (`docs`, `ask`, `invoices`) reset on the 1st of each month, UTC; the others are counts of what the
user has set up (bank feeds, marketplaces, users, Autopilot rules, payroll employees).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

PlanCode = Literal["starter", "comprehensive", "ultimate"]
PLAN_CODES: tuple[str, ...] = ("starter", "comprehensive", "ultimate")
TRIAL_PLAN = "comprehensive"  # what a trial account gets, whatever it later buys
TRIAL_DAYS = 90

MONTHLY = ("docs", "ask", "invoices")  # reset on the 1st (UTC); kept in `usage`
GAUGES = ("bank_feeds", "marketplaces", "users", "autopilot_rules", "payroll_employees")  # what is set up now
COUNTERS = MONTHLY + GAUGES
FEATURES = ("multi_currency", "projects")

TOPUP_DOCS = 100
TOPUP_PRICE_PENCE = 300  # ex VAT
TOPUP_VALID_MONTHS = 12

DEFAULT_PLANS: list[dict[str, Any]] = [
    {
        "code": "starter",
        "name": "Starter",
        "price_month_pence": 1000,
        "price_year_pence": 10000,
        "stripe_price_month": None,
        "stripe_price_year": None,
        "active": True,
        "sort": 1,
        "limits": {
            "users": 1,
            "docs": 50,
            "ask": 100,
            "bank_feeds": 1,
            "invoices": 20,
            "marketplaces": 0,
            "payroll_employees": 0,
            "autopilot_rules": 5,
            "multi_currency": False,
            "projects": False,
            "support": "email",
        },
    },
    {
        "code": "comprehensive",
        "name": "Comprehensive",
        "price_month_pence": 2000,
        "price_year_pence": 20000,
        "stripe_price_month": None,
        "stripe_price_year": None,
        "active": True,
        "sort": 2,
        "limits": {
            "users": 3,
            "docs": 300,
            "ask": 500,
            "bank_feeds": 3,
            "invoices": None,
            "marketplaces": 1,
            "payroll_employees": 3,
            "autopilot_rules": None,
            "multi_currency": False,
            "projects": False,
            "support": "email",
        },
    },
    {
        "code": "ultimate",
        "name": "Ultimate",
        "price_month_pence": 5000,
        "price_year_pence": 50000,
        "stripe_price_month": None,
        "stripe_price_year": None,
        "active": True,
        "sort": 3,
        "limits": {
            "users": 10,
            "docs": 1500,
            "ask": 3000,
            "bank_feeds": None,
            "invoices": None,
            "marketplaces": None,
            "payroll_employees": 20,
            "autopilot_rules": None,
            "multi_currency": True,
            "projects": True,
            "support": "priority_email",
        },
    },
]


def month_start(now: datetime | None = None) -> date:
    """The 1st of this month in UTC: the key of the `usage` row."""
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).date().replace(day=1)


def limit_of(limits: dict[str, Any], counter: str) -> int | None:
    """The numeric limit for `counter` (None: unlimited). A missing or malformed value counts as unlimited, so a
    hand-edited `plans` row never locks anyone out."""
    value = limits.get(counter)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, value)


def validate_limits(limits: dict[str, Any]) -> dict[str, Any]:
    """Admin edits: counters are non-negative integers or null, features booleans, support a short word."""
    out: dict[str, Any] = {}
    for key, value in limits.items():
        if key in COUNTERS:
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{key} must be a whole number of 0 or more, or null for unlimited")
        elif key in FEATURES:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
        elif key == "support":
            if value not in ("email", "priority_email"):
                raise ValueError("support must be 'email' or 'priority_email'")
        else:
            raise ValueError(f"unknown limit {key!r}")
        out[key] = value
    return out
