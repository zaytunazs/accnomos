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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app import region
from app.paths import SYSTEM

ProfileKind = Literal["company", "sole_trader", "landlord", "partnership", "personal"]
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
KIND_LABEL = {
    "company": "company",
    "sole_trader": "sole trader",
    "landlord": "landlord",
    "partnership": "partnership",
    "personal": "personal",
}
FEATURE_LABEL = {"vat": "VAT", "invoices": "invoices", "payroll": "payroll", "self_employment": "self-employment"}


def _clean(value: str | None) -> str | None:
    v = re.sub(r"\s+", "", value or "").upper()
    return v or None


class SalesTax(BaseModel):
    """Outside the UK: the tax the business charges and its one standard rate (0-100 %)."""

    model_config = ConfigDict(extra="forbid")
    name: region.TaxName = "Sales tax"
    rate_percent: float = Field(default=0, ge=0, le=100)
    number: str | None = Field(default=None, max_length=30)  # the business's GST/VAT/tax number, any format

    @field_validator("rate_percent")
    @classmethod
    def _rate(cls, v: float) -> float:
        return round(v, 3)

    @field_validator("number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        return " ".join((v or "").split()) or None


#: Settings that only mean something for UK books (Companies House, HMRC); dropped for any other country.
UK_ONLY_SETTINGS = ("company_number", "vat_number", "vat_registered", "utr")


class _Settings(BaseModel):
    """Every kind's settings. `country` is ISO 3166-1 alpha-2, "GB" unless said; only books outside the UK carry
    `sales_tax` and `currency` (and they never have the UK-only settings). A UK book's settings are saved exactly as
    before these existed: no `country`, `currency` or `sales_tax` keys (`dump_settings`)."""

    model_config = ConfigDict(extra="forbid")
    country: str = region.UK
    currency: str | None = None
    sales_tax: SalesTax | None = None

    @model_validator(mode="before")
    @classmethod
    def _by_country(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        country = str(data.get("country") or region.UK).strip().upper()
        if country not in region.COUNTRY_NAMES:
            raise ValueError("country is a two-letter ISO code, e.g. GB, IE, AU or US")
        data["country"] = country
        if country == region.UK:
            data.pop("currency", None)
            data.pop("sales_tax", None)
            return data
        for key in UK_ONLY_SETTINGS:
            data.pop(key, None)
        if key_value := data.get("currency"):
            data["currency"] = str(key_value).strip().upper()
        else:
            data["currency"] = region.default_currency(country)
            if data["currency"] is None:
                raise ValueError(f"choose the currency your books are kept in ({region.country_name(country)})")
        if data["currency"] not in region.CURRENCIES:
            raise ValueError("currency is one of the listed three-letter codes, e.g. EUR, USD or AUD")
        tax = data.get("sales_tax")
        if tax is None:
            name, rate = region.default_tax(country)
            data["sales_tax"] = {"name": name, "rate_percent": rate}
        elif isinstance(tax, dict) and tax.get("name") == "None":
            data["sales_tax"] = {**tax, "rate_percent": 0}
        return data


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


class LandlordSettings(_VatSettings):
    """A landlord's books: like a sole trader's, with an optional 10-digit UTR for Self Assessment."""

    utr: str | None = Field(default=None, max_length=14)

    @field_validator("utr")
    @classmethod
    def _utr(cls, v: str | None) -> str | None:
        v = _clean(v)
        if v is not None and not UTR_RE.fullmatch(v):
            raise ValueError("a Unique Taxpayer Reference is 10 digits")
        return v


class PartnershipSettings(_VatSettings):
    """A partnership's books: the partnership UTR is 10 digits, like a person's."""

    utr: str | None = Field(default=None, max_length=14)

    @field_validator("utr")
    @classmethod
    def _utr(cls, v: str | None) -> str | None:
        v = _clean(v)
        if v is not None and not UTR_RE.fullmatch(v):
            raise ValueError("a Unique Taxpayer Reference is 10 digits")
        return v


SETTINGS_FOR: dict[str, type[_Settings]] = {
    "company": CompanySettings,
    "sole_trader": SoleTraderSettings,
    "landlord": LandlordSettings,
    "partnership": PartnershipSettings,
    "personal": PersonalSettings,
}


#: What only UK books have: HMRC's VAT returns, payroll (PAYE/RTI) and MTD Income Tax.
UK_ONLY_FEATURES = frozenset({"vat", "payroll", "self_employment"})


def is_uk(settings: dict[str, Any] | None) -> bool:
    return str((settings or {}).get("country") or region.UK) == region.UK


class Region(BaseModel):
    """GET /profile's `region`: where the books are, worked out from the settings, so clients need no rules."""

    country: str = region.UK
    country_name: str = "United Kingdom"
    uk: bool = True
    currency: str = "GBP"
    tax_name: str = "VAT"  # "VAT", "GST", "Sales tax", or "None"
    tax_label: str = "VAT"  # what the screens call it ("Tax" when the business charges none)
    tax_rate_percent: float = 20


def region_of(settings: dict[str, Any] | None) -> Region:
    r = region.rules_from_settings(settings)
    return Region(
        country=r.country,
        country_name=region.country_name(r.country),
        uk=r.uk,
        currency=r.currency,
        tax_name=r.tax_name,
        tax_label=r.label,
        tax_rate_percent=r.rate,
    )


def dump_settings(model: _Settings) -> dict[str, Any]:
    """Settings as saved: a UK book's without the keys only other countries use, so it is byte for byte as before."""
    out = model.model_dump()
    drop = ("country", "currency", "sales_tax") if out.get("country") == region.UK else UK_ONLY_SETTINGS
    for key in drop:
        out.pop(key, None)
    return out


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
    region: Region = Field(default_factory=Region)  # always worked out from `settings`

    @model_validator(mode="after")
    def _region(self) -> Profile:
        self.region = region_of(self.settings)
        return self


def features_for(kind: str, settings: dict[str, Any]) -> list[str]:
    out = [f for f in ALL_FEATURES if not (kind == "personal" and f in NOT_PERSONAL)]
    if kind != "personal" and not settings.get("vat_registered", False):
        out.remove("vat")
    if kind != "sole_trader":
        out.remove("self_employment")
    if not is_uk(settings):
        out = [f for f in out if f not in UK_ONLY_FEATURES]
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
        return dump_settings(SETTINGS_FOR[kind].model_validate(raw))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_problem(exc)) from exc


def default_profile(name: str = "") -> Profile:
    """Books with no profile.json: a VAT-registered company, so nothing changes for anyone who had books already."""
    settings = dump_settings(CompanySettings(vat_registered=True))
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
        settings = dump_settings(SETTINGS_FOR[kind].model_validate(raw.get("settings") or {}))
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
    elif feature in UK_ONLY_FEATURES and not p.region.uk:
        why = uk_only_sentence(p)
    elif feature == "vat":
        why = f"{p.name} is not VAT-registered. Turn VAT on in Settings › Profile to see VAT pages."
    else:
        why = f"{p.name} is a {KIND_LABEL[p.kind]} profile, which has no {what}."
    return HTTPException(status_code=404, detail=why)


def uk_only_sentence(p: Profile) -> str:
    return (
        f"{p.name} keeps its books in {p.region.country_name}; HMRC filing (VAT returns, payroll, MTD Income Tax "
        "and CIS) is for UK books only."
    )


def missing_uk(p: Profile) -> HTTPException:
    return HTTPException(status_code=404, detail=uk_only_sentence(p))
