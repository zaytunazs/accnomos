"""The profile of one set of books: `_System/profile.json` in the account's own OneDrive.

One Microsoft account is one profile: a company, a sole-trader business or personal finances. A user with
several links several accounts in the app (the web keeps them all signed in, MSAL's multi-account cache) and
switches between them; every request carries the chosen account's own `X-Graph-Token`, so the books, the request
memo and the per-user cache (app/cache.py, keyed by a hash of the token) never mix. There is no user database:
which accounts are linked is kept in the browser, and each profile.json may list the other linked accounts
(`linked`, by sign-in name; never a token) so a new browser can offer to add them.

    {"name": "Acme Ltd", "kind": "company",
     "settings": {"company_number": "01234567", "vat_number": "GB123456789", "vat_registered": true},
     "linked": [{"username": "jo@example.com", "name": "Jo's personal", "kind": "personal"}],
     "updated_at": "2026-10-28T09:00:00+00:00"}

Books with no profile.json yet are a VAT-registered company, which is what the app did before profiles existed.
The kind decides which features the books have (`features`): personal books have no VAT, invoices or payroll;
VAT pages need `vat_registered`; sole traders also get `self_employment`. The gated routes answer 404 with a
sentence (routes_books.require_feature).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.paths import SYSTEM

ProfileKind = Literal["company", "sole_trader", "personal"]
PROFILE = f"{SYSTEM}/profile.json"

COMPANY_NUMBER_RE = re.compile(r"(?:\d{8}|[A-Z]{2}\d{6})")  # 01234567, SC123456, NI…, OC…
VAT_NUMBER_RE = re.compile(r"(?:GB)?\d{9}(?:\d{3})?")
UTR_RE = re.compile(r"\d{10}")
MONTH_DAY_RE = re.compile(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")

#: Everything a set of books can show; the web and Android hide nav items for features a profile lacks.
ALL_FEATURES: tuple[str, ...] = (
    "review",
    "ask",
    "files",
    "bank",
    "reports",
    "contacts",
    "jobs",
    "vehicles",
    "invoices",
    "payroll",
    "vat",
    "self_employment",
)
NOT_PERSONAL = frozenset({"invoices", "payroll", "vat"})
KIND_LABEL = {"company": "company", "sole_trader": "sole trader", "personal": "personal"}
FEATURE_LABEL = {"vat": "VAT", "invoices": "invoices", "payroll": "payroll", "self_employment": "self-employment"}


def _clean(value: str | None) -> str | None:
    v = re.sub(r"\s+", "", value or "").upper()
    return v or None


class _Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _VatSettings(_Settings):
    vat_number: str | None = Field(default=None, max_length=20)
    vat_registered: bool = False  # VAT pages show only when this is on

    @field_validator("vat_number")
    @classmethod
    def _vat(cls, v: str | None) -> str | None:
        v = _clean(v)
        if v is not None and not VAT_NUMBER_RE.fullmatch(v):
            raise ValueError("a UK VAT number is 9 digits, optionally after GB (e.g. GB123456789)")
        return v


class CompanySettings(_VatSettings):
    company_number: str | None = Field(default=None, max_length=12)

    @field_validator("company_number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        v = _clean(v)
        if v is not None and not COMPANY_NUMBER_RE.fullmatch(v):
            raise ValueError("a Companies House number is 8 characters, e.g. 01234567 or SC123456")
        return v


class SoleTraderSettings(_VatSettings):
    utr: str | None = Field(default=None, max_length=14)
    #: Start of the accounting year as MM-DD; 04-06 (6 April, the tax year) unless the business uses another date.
    accounting_period_start: str = "04-06"

    @field_validator("utr")
    @classmethod
    def _utr(cls, v: str | None) -> str | None:
        v = _clean(v)
        if v is not None and not UTR_RE.fullmatch(v):
            raise ValueError("a Unique Taxpayer Reference is 10 digits")
        return v

    @field_validator("accounting_period_start")
    @classmethod
    def _start(cls, v: str) -> str:
        if not MONTH_DAY_RE.fullmatch(v.strip()):
            raise ValueError("the accounting period start is MM-DD, e.g. 04-06 for 6 April")
        return v.strip()


class PersonalSettings(_Settings):
    pass


SETTINGS_FOR: dict[str, type[_Settings]] = {
    "company": CompanySettings,
    "sole_trader": SoleTraderSettings,
    "personal": PersonalSettings,
}


class LinkedAccount(BaseModel):
    """Another account the user linked, by its sign-in name (no id the app could sign in with, never a token)."""

    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+$")
    name: str = Field(default="", max_length=80)
    kind: ProfileKind | None = None


class Profile(BaseModel):
    """GET /profile."""

    name: str
    kind: ProfileKind
    settings: dict[str, Any]
    linked: list[LinkedAccount] = []
    updated_at: datetime | None = None
    exists: bool = True  # False: no profile.json yet, these are the defaults
    features: list[str] = []


def features_for(kind: str, settings: dict[str, Any]) -> list[str]:
    out = [f for f in ALL_FEATURES if not (kind == "personal" and f in NOT_PERSONAL)]
    if kind != "personal" and not settings.get("vat_registered", False):
        out.remove("vat")
    if kind != "sole_trader":
        out.remove("self_employment")
    return out


def _problem(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", ()))
    msg = str(first.get("msg", "")).removeprefix("Value error, ")
    return f"{where}: {msg}" if where else msg


def validate_settings(kind: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Settings for `kind`, checked; 400 with the first problem as a sentence. VAT-registered defaults to having a
    VAT number when it is not said."""
    raw = dict(raw or {})
    if kind != "personal" and "vat_registered" not in raw:
        raw["vat_registered"] = bool(_clean(raw.get("vat_number")))
    try:
        return SETTINGS_FOR[kind].model_validate(raw).model_dump()
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_problem(exc)) from exc


def default_profile(name: str = "") -> Profile:
    """Books with no profile.json: a VAT-registered company, so nothing changes for anyone who had books already."""
    settings = CompanySettings(vat_registered=True).model_dump()
    return Profile(
        name=name or "My books",
        kind="company",
        settings=settings,
        exists=False,
        features=features_for("company", settings),
    )


def from_file(raw: Any, fallback_name: str = "") -> Profile:
    """profile.json as a Profile. A missing or unreadable (hand-edited) file gives the defaults; never raises."""
    if not isinstance(raw, dict) or raw.get("kind") not in SETTINGS_FOR:
        return default_profile(fallback_name)
    kind = str(raw["kind"])
    try:
        settings = SETTINGS_FOR[kind].model_validate(raw.get("settings") or {}).model_dump()
    except ValidationError:
        return default_profile(fallback_name)
    linked: list[LinkedAccount] = []
    for item in raw.get("linked") or []:
        try:
            linked.append(LinkedAccount.model_validate(item))
        except ValidationError:
            continue
    try:
        updated = datetime.fromisoformat(str(raw["updated_at"])) if raw.get("updated_at") else None
    except ValueError:
        updated = None
    return Profile(
        name=str(raw.get("name") or fallback_name or "My books")[:80],
        kind=kind,  # type: ignore[arg-type]
        settings=settings,
        linked=linked[:20],
        updated_at=updated,
        features=features_for(kind, settings),
    )


async def load(books: Any, fallback_name: str = "") -> Profile:
    return from_file(await books.read_json(PROFILE, None), fallback_name)


def to_file(p: Profile) -> dict[str, Any]:
    return {
        "name": p.name,
        "kind": p.kind,
        "settings": p.settings,
        "linked": [a.model_dump() for a in p.linked],
        "updated_at": (p.updated_at or datetime.now(UTC)).isoformat(),
    }


def missing_feature(p: Profile, feature: str) -> HTTPException:
    what = FEATURE_LABEL.get(feature, feature)
    if p.kind == "personal" and feature in NOT_PERSONAL:
        why = f"{p.name} is a personal profile, and personal books have no {what}."
    elif feature == "vat":
        why = f"{p.name} is not VAT-registered. Turn VAT on in Settings › Profile to see VAT pages."
    else:
        why = f"{p.name} is a {KIND_LABEL[p.kind]} profile, which has no {what}."
    return HTTPException(status_code=404, detail=why)
