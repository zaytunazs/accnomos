"""Landlords: UK property income kept as a sub-ledger of the books, worked out by code (never a model).

What is stored, all under `_System/Property/` in the user's own OneDrive (no database):

    properties.json   the register: each let property, how it is used, who owns it and in what shares
    tags.json         {ledger event id: {property_id, category}}: which property an approved entry belongs to,
                      and optionally its SA105 category. Ledger events are immutable, so the tag lives beside
                      them; an undo (a reversal) follows the tag of the event it reverses
    settings.json     landlord mode, quarter type, consolidated expenses, finance costs brought forward per year,
                      the HMRC business id for the UK property business (never an HMRC token)
    submissions.json  what the web sent to HMRC's sandbox (or exported as a file) and HMRC's answer

Categories are HMRC's: the fields of the Property Business (MTD) API 6.0 "Create or Amend a UK Property
Cumulative Period Summary" (`ukProperty.income` / `ukProperty.expenses`) and the SA105 boxes they map to, from
HMRC's own mapping file income-tax-mtd-changelog/mapping/csv/sa105_mapping_v1.csv and the API's request schema
(github.com/hmrc/property-business-api resources/public/api/conf/6.0, both checked 28 Oct 2026). The cumulative
endpoint takes tax years from 2025-26; every update covers 6 April to the end of the period and replaces the last.

Tax rules applied here, each checked on gov.uk on 28 Oct 2026 (through gov.uk search results: this environment
cannot open gov.uk pages directly, so the review lists that as a risk):

* Residential finance costs are not an expense. Mortgage interest and loan costs on residential lets give a tax
  reduction at the basic rate on the lowest of (a) the finance costs plus any brought forward, (b) the property
  profits and (c) adjusted total income above the personal allowance; what is not used carries forward. Fully in
  force from 6 April 2020. gov.uk/guidance/changes-to-tax-relief-for-residential-landlords-how-its-worked-out-
  including-case-studies. From 2027-28 property income has its own rates and the relief is at the property basic
  rate, 22 % (gov.uk/government/publications/changes-to-tax-rates-for-property-savings-and-dividend-income).
  Non-residential (commercial) finance costs stay a normal expense (SA105 box 26).
* Replacement of domestic items relief: the cost of a like-for-like (or nearest modern equivalent) replacement of
  furniture, furnishings, appliances or kitchenware in a let dwelling, not the first purchase, not for Rent a Room.
  gov.uk/guidance/income-tax-when-you-rent-out-a-property-working-out-your-rental-income. It is an annual
  allowance (`costOfReplacingDomesticItems`, SA105 box 36), so it is left out of the quarterly expenses.
* Furnished holiday lettings: the regime was abolished from 6 April 2025 (1 April for Corporation Tax); from
  2025-26 holiday lets are taxed under the ordinary residential rules. gov.uk/guidance/letting-out-a-self-catering-
  holiday-home-in-england-rules-and-regulations; HMRC manual PIM4170-PIM4185. A property marked as a holiday let is
  therefore treated as residential, and earlier tax years are refused (they need the historic FHL submissions).
* Jointly owned property: spouses and civil partners are taxed 50:50 on income from jointly held property whatever
  their shares (ITA 2007 s836), unless both sign a Form 17 declaration of unequal beneficial interests (s837);
  others (e.g. siblings) are taxed on their actual shares. HMRC manual TSEM9812, TSEM9842-TSEM9864.
* Rent a Room: £7,500 a year, £3,750 if someone else also receives income from letting in the same home (HS223
  2026). Property allowance: £1,000 a year across all property businesses, instead of expenses
  (gov.uk/guidance/tax-free-allowances-on-property-and-trading-income); shown as a comparison only.
* Consolidated expenses (one figure instead of SA105 boxes 24-29) when property income is under £90,000 (SA105
  notes 2026). The cash basis is the default for landlords with receipts up to £150,000 (HMRC PIM1092); figures
  here are as approved (each entry on its own date), and the summary says so.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from accnomos_ledger import LedgerEvent, Line, VatCode
from app.books import Books, now
from app.journal import BANK, CASH, OWNER_LOAN
from app.paths import PROPERTY
from app.validation import LENIENT, Day, Pence, StrictBody

PROPERTIES = f"{PROPERTY}/properties.json"
TAGS = f"{PROPERTY}/tags.json"
SETTINGS = f"{PROPERTY}/settings.json"
SUBMISSIONS = f"{PROPERTY}/submissions.json"

MAX_PROPERTIES = 50
MAX_OWNERS = 6
WHOLE = 10_000  # shares are basis points: 10,000 = 100 %
MAX_PENCE = 10_000_000_000  # £100 million: a typo guard
FIRST_CUMULATIVE_TAX_YEAR = "2025-26"  # Property Business API 6.0, path parameter taxYearFrom2025
FHL_ABOLISHED = date(2025, 4, 6)
RENT_A_ROOM_LIMIT = 750_000  # £7,500 (HS223 2026)
RENT_A_ROOM_SHARED_LIMIT = 375_000  # £3,750 when another person also lets in the same home
PROPERTY_ALLOWANCE = 100_000  # £1,000
CONSOLIDATED_LIMIT = 9_000_000  # £90,000 (SA105 notes 2026)
CASH_BASIS_LIMIT = 15_000_000  # £150,000 (PIM1092)
BASIS = "As approved: each entry counts on its own date (rent when recorded, a bill when bought). Not cash basis."
CASH_BASIS_NOTE = (
    "HMRC treats most landlords with receipts up to £150,000 as using the cash basis (money in and out). These "
    "figures are by the date of each entry; check them against your bank before you send them."
)
_TAX_YEAR = re.compile(r"^(20\d{2})-(\d{2})$")
_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$")

Use = Literal["residential", "commercial", "rent_a_room"]
Joint = Literal["sole", "spouses", "other"]
Group = Literal["income", "expenses", "finance", "annual"]


class PropertyError(ValueError):
    """A change the property files cannot take (the route answers 409)."""


# --------------------------------------------------------------------------- #
# Categories: HMRC's fields, their SA105 boxes and the ledger accounts behind them
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Category:
    key: str  # our id, used in tags and the quick-entry form
    field: str  # the API field (ukProperty.income.* / ukProperty.expenses.* / annual allowance)
    group: Group
    box: str  # SA105 box
    account: str  # ledger account a quick entry posts to
    label: str


CATEGORIES: tuple[Category, ...] = (
    Category("rents", "periodAmount", "income", "20", "4700 Property: rents", "Rents received"),
    Category(
        "premiums",
        "premiumsOfLeaseGrant",
        "income",
        "22",
        "4710 Property: lease premiums",
        "Premiums for the grant of a lease (the taxable part)",
    ),
    Category(
        "reverse_premiums",
        "reversePremiums",
        "income",
        "23",
        "4720 Property: reverse premiums",
        "Reverse premiums and inducements",
    ),
    Category(
        "other_income",
        "otherIncome",
        "income",
        "20",
        "4730 Property: other income",
        "Other property income (ground rents, rent charges, other)",
    ),
    Category(
        "rent_a_room",
        "rentARoom.rentsReceived",
        "income",
        "20",
        "4740 Property: rent-a-room",
        "Rent a Room rents (a room in your own home)",
    ),
    Category(
        "premises",
        "premisesRunningCosts",
        "expenses",
        "24",
        "8500 Property: rent, rates, insurance",
        "Rent, rates, insurance and ground rents",
    ),
    Category(
        "repairs",
        "repairsAndMaintenance",
        "expenses",
        "25",
        "8510 Property: repairs and maintenance",
        "Property repairs and maintenance",
    ),
    Category(
        "finance_nonres",
        "financialCosts",
        "expenses",
        "26",
        "8520 Property: commercial finance costs",
        "Finance costs on non-residential (commercial) property",
    ),
    Category(
        "professional",
        "professionalFees",
        "expenses",
        "27",
        "8540 Property: professional fees",
        "Legal, management and other professional fees",
    ),
    Category(
        "services",
        "costOfServices",
        "expenses",
        "28",
        "8550 Property: services and wages",
        "Costs of services provided, including wages",
    ),
    Category(
        "travel",
        "travelCosts",
        "expenses",
        "29",
        "8560 Property: travel",
        "Car, van and travel costs for the letting business",
    ),
    Category("other", "other", "expenses", "29", "8570 Property: other expenses", "Other allowable expenses"),
    Category(
        "finance_res",
        "residentialFinancialCost",
        "finance",
        "44",
        "8530 Property: residential finance costs",
        "Mortgage interest and loan costs on residential lets (a tax credit, not an expense)",
    ),
    Category(
        "domestic_items",
        "costOfReplacingDomesticItems",
        "annual",
        "36",
        "8580 Property: replacement domestic items",
        "Replacing furniture, appliances or kitchenware (like for like)",
    ),
)
BY_KEY = {c.key: c for c in CATEGORIES}
BY_ACCOUNT = {c.account: c for c in CATEGORIES}
INCOME_KEYS = tuple(c.key for c in CATEGORIES if c.group == "income")
CategoryKey = Literal[
    "rents",
    "premiums",
    "reverse_premiums",
    "other_income",
    "rent_a_room",
    "premises",
    "repairs",
    "finance_nonres",
    "professional",
    "services",
    "travel",
    "other",
    "finance_res",
    "domestic_items",
]
_CODE = re.compile(r"^\s*(\d{4})\b")
# Ordinary accounts from the chart in app/journal.py, for an entry read from a receipt and tagged to a property.
GENERAL: tuple[tuple[int, int, str], ...] = (
    (4000, 4699, "rents"),  # a sale tagged to a property: rent invoiced through Invoices
    (4750, 4999, "other_income"),
    (5000, 5999, "repairs"),  # 5000 Materials, 5100 Tools & small equipment
    (6000, 6999, "other"),  # 6200 Advertising (for tenants)
    (7000, 7099, "services"),  # wages
    (7100, 7299, "premises"),  # 7100 Rent, 7200 Utilities
    (7300, 7499, "travel"),  # motor, mileage allowance, travel (7410 Subsistence is checked below)
    (7500, 7599, "other"),  # office, software, postage, telephone
    (7600, 7699, "professional"),
    (7700, 7799, "premises"),  # 7700 Insurance
    (7800, 7899, "repairs"),
    (7900, 7999, "other"),  # bank charges, sundry; interest is matched by name below
    (8000, 8499, "other"),
    (8590, 8999, "other"),
)


def category_of(account: str, use: Use) -> Category | None:
    """The category of one ledger line on a property, or None for a balance-sheet line (1xxx-3xxx)."""
    if account in BY_ACCOUNT:
        cat = BY_ACCOUNT[account]
    else:
        m = _CODE.match(account)
        if not m:
            return None
        code = int(m.group(1))
        key = next((k for lo, hi, k in GENERAL if lo <= code <= hi), None)
        if key is None:
            return None
        if re.search(r"\binterest\b|mortgage", account, re.I):
            key = "finance_res"
        if re.search(r"repair|maintenance", account, re.I):
            key = "repairs"
        cat = BY_KEY[key]
    return _for_use(cat, use)


def _for_use(cat: Category, use: Use) -> Category:
    """Finance costs follow the property: residential ones are restricted, commercial ones are an expense."""
    if cat.key == "finance_res" and use == "commercial":
        return BY_KEY["finance_nonres"]
    if cat.key == "finance_nonres" and use != "commercial":
        return BY_KEY["finance_res"]
    return cat


# --------------------------------------------------------------------------- #
# Tax years and quarters
# --------------------------------------------------------------------------- #


def tax_year_bounds(tax_year: str) -> tuple[date, date]:
    m = _TAX_YEAR.match(tax_year)
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise ValueError("a tax year is written like 2026-27")
    start = int(m.group(1))
    return date(start, 4, 6), date(start + 1, 4, 5)


def tax_year_of(day: date) -> str:
    start = day.year if day >= date(day.year, 4, 6) else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def quarter_ends(tax_year: str, kind: Literal["standard", "calendar"] = "standard") -> list[date]:
    """Ends of the four MTD update periods. Standard: 5 Jul, 5 Oct, 5 Jan, 5 Apr; calendar: 30 Jun, 30 Sep,
    31 Dec, 5 Apr (gov.uk/guidance/use-making-tax-digital-for-income-tax, quarterly periods; and the API's
    "standard" and "calendar" reporting types)."""
    y = tax_year_bounds(tax_year)[0].year
    if kind == "calendar":
        return [date(y, 6, 30), date(y, 9, 30), date(y, 12, 31), date(y + 1, 4, 5)]
    return [date(y, 7, 5), date(y, 10, 5), date(y + 1, 1, 5), date(y + 1, 4, 5)]


def finance_credit_rate(tax_year: str) -> int:
    """Percent: the basic rate (20) to 2026-27; the property basic rate (22) from 2027-28."""
    return 22 if tax_year_bounds(tax_year)[0].year >= 2027 else 20


# --------------------------------------------------------------------------- #
# The register
# --------------------------------------------------------------------------- #


class Owner(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    share_bp: int = Field(ge=0, le=WHOLE, description="beneficial share in basis points (5000 = 50 %)")
    me: bool = False  # the person whose books these are: their share is what goes to HMRC


class PropertyIn(StrictBody):
    name: str = Field(min_length=1, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    postcode: str | None = Field(default=None, max_length=10)
    use: Use = "residential"
    furnished: bool = False
    holiday_let: bool = False  # kept for the record; from 2025-26 it is taxed as residential
    joint: Joint = "sole"
    form17: bool = False  # spouses/civil partners only: a Form 17 declaration of unequal shares is in force
    rent_a_room_shared: bool = False  # someone else also lets rooms in the same home (limit halves)
    owners: list[Owner] = Field(default_factory=list, max_length=MAX_OWNERS)
    started: Day | None = None
    ended: Day | None = None

    @field_validator("postcode")
    @classmethod
    def _postcode(cls, v: str | None) -> str | None:
        v = re.sub(r"\s+", " ", (v or "").strip().upper()) or None
        if v is not None and not _POSTCODE.fullmatch(v):
            raise ValueError("a UK postcode looks like LS1 4AP")
        return v

    @model_validator(mode="after")
    def _owners(self) -> PropertyIn:
        owners = self.owners or [Owner(name="Me", share_bp=WHOLE, me=True)]
        if sum(1 for o in owners if o.me) != 1:
            raise ValueError("exactly one owner is you (me: true)")
        if self.joint == "sole":
            if len(owners) != 1:
                raise ValueError("a property you own alone has one owner; choose joint ownership for more")
            owners = [owners[0].model_copy(update={"share_bp": WHOLE})]
        else:
            if len(owners) < 2:
                raise ValueError("a jointly owned property needs at least two owners")
            if sum(o.share_bp for o in owners) != WHOLE:
                raise ValueError("owners' shares must add up to 100 %")
            if self.joint == "spouses" and len(owners) != 2:
                raise ValueError("spouses or civil partners: exactly two owners")
        if self.form17 and self.joint != "spouses":
            raise ValueError("a Form 17 declaration is only for spouses and civil partners (HMRC TSEM9844)")
        if self.started and self.ended and self.ended < self.started:
            raise ValueError("the end date is before the start date")
        self.owners = owners
        return self


class Property(PropertyIn):
    id: str
    created_at: str


def tax_shares(p: PropertyIn) -> tuple[list[tuple[Owner, int]], str | None]:
    """Each owner with the share they are TAXED on (basis points), and a note when that differs from the stated
    shares: spouses and civil partners split 50:50 unless a Form 17 declaration is in force (ITA 2007 s836-837)."""
    if p.joint == "spouses" and not p.form17:
        equal = [(o, WHOLE // 2) for o in p.owners]
        note = None
        if any(o.share_bp != WHOLE // 2 for o in p.owners):
            note = (
                f"{p.name}: spouses and civil partners are taxed 50:50 on jointly owned property unless you both "
                "sign a Form 17 declaration of your actual shares (HMRC TSEM9812). Figures use 50:50."
            )
        return equal, note
    return [(o, o.share_bp) for o in p.owners], None


def split_pence(amount: int, shares_bp: list[int]) -> list[int]:
    """Split `amount` by shares (basis points summing to 10,000) so the parts add up exactly: each part rounds
    down, then the pennies left over go to the largest remainders (ties to the earlier owner)."""
    if sum(shares_bp) != WHOLE:
        raise ValueError("shares must add up to 10,000 basis points")
    sign = -1 if amount < 0 else 1
    a = abs(amount)
    exact = [a * s for s in shares_bp]
    parts = [e // WHOLE for e in exact]
    left = a - sum(parts)
    order = sorted(range(len(shares_bp)), key=lambda i: (-(exact[i] % WHOLE), i))
    for i in order[:left]:
        parts[i] += 1
    return [sign * p for p in parts]


def _parse_list(raw: Any, model: type[BaseModel]) -> list[Any]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(model.model_validate(item, **LENIENT))
        except ValidationError:
            continue  # a hand-edited row that no longer parses is skipped, never fatal
    return out


async def load_properties(books: Books) -> list[Property]:
    return _parse_list(await books.read_json(PROPERTIES, []), Property)


async def add_property(books: Books, body: PropertyIn, user: str) -> Property:
    prop = Property(**body.model_dump(), id=uuid.uuid4().hex[:12], created_at=now().isoformat())

    def change(raw: Any) -> Any:
        rows = raw if isinstance(raw, list) else []
        if len(rows) >= MAX_PROPERTIES:
            raise PropertyError(f"at most {MAX_PROPERTIES} properties")
        return [*rows, prop.model_dump(mode="json")]

    await books._update_json(PROPERTIES, [], change)
    await books.audit(f"user:{user}", "property_added", {"property": prop.id, "name": prop.name})
    return prop


async def update_property(books: Books, property_id: str, body: PropertyIn, user: str) -> Property:
    found: list[Property] = []

    def change(raw: Any) -> Any:
        rows = raw if isinstance(raw, list) else []
        out = []
        for row in rows:
            if isinstance(row, dict) and row.get("id") == property_id:
                prop = Property(**body.model_dump(), id=property_id, created_at=str(row.get("created_at") or ""))
                found.append(prop)
                out.append(prop.model_dump(mode="json"))
            else:
                out.append(row)
        if not found:
            raise KeyError(property_id)
        return out

    await books._update_json(PROPERTIES, [], change)
    await books.audit(f"user:{user}", "property_updated", {"property": property_id, "name": found[0].name})
    return found[0]


# --------------------------------------------------------------------------- #
# Settings and tags
# --------------------------------------------------------------------------- #


class PropertySettings(BaseModel):
    landlord_mode: bool = False
    quarters: Literal["standard", "calendar"] = "standard"
    consolidated_expenses: bool = False
    rent_a_room_relief: bool = True  # claim the exempt amount on Rent a Room rents (instead of their expenses)
    # Unused residential finance costs brought into each tax year (SA105 box 45), pence, from last year's return.
    finance_brought_forward: dict[str, Pence] = Field(default_factory=dict)
    business_id: str | None = Field(default=None, pattern=r"^X[A-Z0-9]IS\d{11}$")  # HMRC's id, not a secret

    @field_validator("finance_brought_forward")
    @classmethod
    def _bf(cls, v: dict[str, int]) -> dict[str, int]:
        for year, pence in v.items():
            tax_year_bounds(year)
            if not 0 <= pence <= MAX_PENCE:
                raise ValueError("a brought-forward amount is 0 or more pence")
        return v


class PropertySettingsIn(PropertySettings, StrictBody):
    pass


async def load_settings(books: Books) -> PropertySettings:
    raw = await books.read_json(SETTINGS, {})
    try:
        return PropertySettings.model_validate(raw if isinstance(raw, dict) else {}, **LENIENT)
    except ValidationError:
        return PropertySettings()


async def save_settings(books: Books, body: PropertySettingsIn, user: str) -> PropertySettings:
    out = PropertySettings.model_validate(body.model_dump())
    await books._update_json(SETTINGS, {}, lambda _old: out.model_dump(mode="json"))
    await books.audit(f"user:{user}", "property_settings_saved", {"landlord_mode": out.landlord_mode})
    return out


class Tag(BaseModel):
    property_id: str
    category: CategoryKey | None = None  # None: from the account


async def load_tags(books: Books) -> dict[str, Tag]:
    raw = await books.read_json(TAGS, {})
    out: dict[str, Tag] = {}
    for event_id, t in (raw if isinstance(raw, dict) else {}).items():
        try:
            out[str(event_id)] = Tag.model_validate(t, **LENIENT)
        except ValidationError:
            continue
    return out


async def set_tag(books: Books, event_id: str, tag: Tag | None, user: str) -> None:
    """Tag an approved ledger entry to a property (None removes the tag). The event itself is never changed."""
    event = await books.get_event(event_id)  # FileNotFoundError → 404
    if event.kind == "reversal":
        raise PropertyError("tag the original entry; its undo follows it")
    if tag is not None and tag.property_id not in {p.id for p in await load_properties(books)}:
        raise PropertyError("no such property")

    def change(raw: Any) -> Any:
        tags = dict(raw) if isinstance(raw, dict) else {}
        if tag is None:
            tags.pop(event_id, None)
        else:
            tags[event_id] = tag.model_dump(exclude_none=True)
        return tags

    await books._update_json(TAGS, {}, change)
    refs = {"event": event_id, "property": tag.property_id if tag else None}
    await books.audit(f"user:{user}", "property_tagged" if tag else "property_untagged", refs)


# --------------------------------------------------------------------------- #
# Quick entries (landlord mode): rent in, a bill out, posted straight to the ledger by the user
# --------------------------------------------------------------------------- #


class EntryIn(StrictBody):
    property_id: str = Field(max_length=40)
    date: Day
    category: CategoryKey
    amount_pence: Pence = Field(gt=0, le=MAX_PENCE)
    description: str = Field(min_length=1, max_length=140)
    paid_via: Literal["bank", "cash", "owner"] = "bank"  # owner: paid personally, owed back (2300)
    replacing_existing_item: bool = False  # domestic items: must be a replacement, never the first purchase


async def add_entry(books: Books, body: EntryIn, user: str) -> tuple[LedgerEvent, Tag]:
    """Post one property entry as the user's own approved journal and tag it. Kept off the VAT return (code O):
    residential rent is exempt and most landlords are not VAT registered; a VAT-registered landlord records
    VAT-able lets through Invoices and Review instead (HONESTY.md)."""
    props = {p.id: p for p in await load_properties(books)}
    prop = props.get(body.property_id)
    if prop is None:
        raise PropertyError("no such property")
    cat = _for_use(BY_KEY[body.category], prop.use)
    if cat.key == "rent_a_room" and prop.use != "rent_a_room":
        raise PropertyError("Rent a Room rents are only for a room let in your own home")
    if cat.key == "domestic_items":
        if prop.use != "residential":
            raise PropertyError("replacement of domestic items relief is for residential lets only (not Rent a Room)")
        if not body.replacing_existing_item:
            raise PropertyError(
                "the relief covers replacing an item that was already there, not buying the first one (a capital cost)"
            )
    other = {"bank": BANK, "cash": CASH, "owner": OWNER_LOAN}[body.paid_via]
    memo = f"{prop.name}: {body.description}"
    if cat.group == "income":
        lines = [
            Line(account=other, debit=body.amount_pence, memo=memo),
            Line(account=cat.account, credit=body.amount_pence, vat_code=VatCode.OUT_OF_SCOPE, memo=memo),
        ]
        kind: Literal["sale", "purchase"] = "sale"
    else:
        lines = [
            Line(account=cat.account, debit=body.amount_pence, vat_code=VatCode.OUT_OF_SCOPE, memo=memo),
            Line(account=other, credit=body.amount_pence, memo=memo),
        ]
        kind = "purchase"
    event = LedgerEvent(
        kind=kind,
        date=body.date,
        lines=lines,
        approved_by=user,
        approved_at=now(),
        net=body.amount_pence,
        vat=0,
        counterparty=prop.name,
    )
    await books.post_event(event)
    tag = Tag(property_id=prop.id, category=cat.key)  # type: ignore[arg-type]
    await books._update_json(TAGS, {}, lambda raw: {**(raw or {}), event.id: tag.model_dump()})
    await books.audit(
        f"user:{user}",
        "property_entry",
        {"event": event.id, "property": prop.id, "category": cat.key, "pence": body.amount_pence},
    )
    await books.rebuild_safely(f"user:{user}")
    return event, tag


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #


class Amounts(BaseModel):
    """Pence per category key, plus the totals code adds up."""

    by_category: dict[str, int] = Field(default_factory=dict)
    income: int = 0
    expenses: int = 0  # allowable expenses that reduce the profit (boxes 24-29)
    finance_res: int = 0  # residential finance costs (box 44): a tax credit, not an expense
    domestic_items: int = 0  # replacement of domestic items (box 36): annual allowance
    rent_a_room_rents: int = 0
    profit: int = 0  # income - expenses - domestic items, before the finance credit

    def add(self, cat: Category, pence: int) -> None:
        self.by_category[cat.key] = self.by_category.get(cat.key, 0) + pence

    def close(self) -> Amounts:
        c = self.by_category
        self.income = sum(c.get(k, 0) for k in INCOME_KEYS)
        self.rent_a_room_rents = c.get("rent_a_room", 0)
        self.expenses = sum(v for k, v in c.items() if BY_KEY[k].group == "expenses")
        self.finance_res = c.get("finance_res", 0)
        self.domestic_items = c.get("domestic_items", 0)
        self.profit = self.income - self.expenses - self.domestic_items
        return self


class PropertyFigures(BaseModel):
    property_id: str
    name: str
    use: Use
    whole: Amounts  # the whole property, before splitting between owners
    my_share_bp: int
    mine: Amounts
    owners: list[dict[str, Any]]  # [{name, me, share_bp, profit, income}]
    entries: int


class FinanceCredit(BaseModel):
    rate_percent: int
    finance_costs: int  # this year's residential finance costs, my share
    brought_forward: int
    profits_limit: int  # the property profits (b): my share, not below 0
    income_limit: int | None  # (c), when the caller gave adjusted total income above the personal allowance
    relieved: int  # the lowest of the limits
    credit: int  # rate x relieved, pence (rounded down)
    carried_forward: int
    note: str


class AllowanceCheck(BaseModel):
    property_allowance_pence: int
    gross_income: int
    expenses_claimed: int  # allowable expenses + domestic items (my share)
    better: Literal["expenses", "property_allowance", "either"]
    note: str


class PropertySummary(BaseModel):
    tax_year: str
    start: date
    end: date
    basis: str = BASIS
    properties: list[PropertyFigures]
    unallocated: Amounts  # property-account entries with no property tag (counted as 100 % yours)
    mine: Amounts  # what goes to HMRC: my share of every property plus the unallocated entries
    finance: FinanceCredit
    allowance: AllowanceCheck
    rent_a_room_exempt: int  # the Rent a Room exempt amount claimed (box 37)
    warnings: list[str]


def _event_lines(
    ev: LedgerEvent, prop_use: Use, tag: Tag | None, property_accounts_only: bool = False
) -> list[tuple[Category, int]]:
    """(category, pence) for each P&L line of an event on a property, signed so income and costs are positive.
    An untagged event counts only its lines on the property accounts (47xx, 85xx)."""
    out: list[tuple[Category, int]] = []
    for ln in ev.lines:
        if property_accounts_only and ln.account not in BY_ACCOUNT:
            continue
        cat = category_of(ln.account, prop_use)
        if cat is None:
            continue
        if tag is not None and tag.category is not None:
            forced = _for_use(BY_KEY[tag.category], prop_use)
            # A tag moves a line within its side only: income stays income, a cost stays a cost.
            if (forced.group == "income") == (cat.group == "income"):
                cat = forced
        pence = (ln.credit - ln.debit) if cat.group == "income" else (ln.debit - ln.credit)
        out.append((cat, pence))
    return out


def summarise(
    events: list[LedgerEvent],
    properties: list[Property],
    tags: dict[str, Tag],
    settings: PropertySettings,
    tax_year: str,
    end: date | None = None,
    adjusted_income_above_pa: int | None = None,
) -> PropertySummary:
    """The year to `end` (default: the tax year's end): figures per property, per owner and for the user."""
    start, year_end = tax_year_bounds(tax_year)
    if start < FHL_ABOLISHED:
        raise ValueError(
            "tax years before 2025-26 used the furnished holiday lettings rules and HMRC's historic property "
            "submissions; Accnomos starts at 2025-26"
        )
    end = min(end or year_end, year_end)
    if end < start:
        raise ValueError("the period ends before the tax year starts")
    by_id = {p.id: p for p in properties}
    whole: dict[str, Amounts] = defaultdict(Amounts)
    counts: dict[str, int] = defaultdict(int)
    unallocated = Amounts()
    only = properties[0] if len(properties) == 1 else None
    warnings: list[str] = []
    for ev in events:
        if not start <= ev.date <= end:
            continue
        tag = tags.get(ev.reverses or ev.credits or ev.id)
        prop = by_id.get(tag.property_id) if tag else None
        if prop is None and tag is None:
            # untagged: only lines on the property accounts count, to the only property if there is just one
            if not any(ln.account in BY_ACCOUNT for ln in ev.lines):
                continue
            prop = only
        use: Use = prop.use if prop else "residential"
        lines = _event_lines(ev, use, tag, property_accounts_only=tag is None)
        if not lines:
            continue
        bucket = whole[prop.id] if prop else unallocated
        for cat, pence in lines:
            bucket.add(cat, pence)
        if prop:
            counts[prop.id] += 1
    unallocated.close()
    if unallocated.by_category:
        warnings.append(
            "Some property entries are not tagged to a property; they are counted as 100 % yours. Tag them on "
            "the Property page."
        )

    figures: list[PropertyFigures] = []
    mine = Amounts(by_category=dict(unallocated.by_category))
    for p in properties:
        amounts = whole[p.id].close()
        shares, note = tax_shares(p)
        if note:
            warnings.append(note)
        if p.holiday_let:
            warnings.append(
                f"{p.name}: furnished holiday lettings rules ended on 6 April 2025; it is taxed as a residential "
                "let from 2025-26."
            )
        split: dict[str, list[int]] = {
            k: split_pence(v, [s for _, s in shares]) for k, v in amounts.by_category.items()
        }
        owners_out: list[dict[str, Any]] = []
        my_share = 0
        my_amounts = Amounts()
        for i, (owner, share) in enumerate(shares):
            a = Amounts(by_category={k: parts[i] for k, parts in split.items()}).close()
            owners_out.append(
                {
                    "name": owner.name,
                    "me": owner.me,
                    "share_bp": share,
                    "income": a.income,
                    "profit": a.profit,
                    "finance_res": a.finance_res,
                }
            )
            if owner.me:
                my_share, my_amounts = share, a
        for k, v in my_amounts.by_category.items():
            mine.by_category[k] = mine.by_category.get(k, 0) + v
        figures.append(
            PropertyFigures(
                property_id=p.id,
                name=p.name,
                use=p.use,
                whole=amounts,
                my_share_bp=my_share,
                mine=my_amounts,
                owners=owners_out,
                entries=counts[p.id],
            )
        )
    mine.close()

    # Rent a Room: the exempt amount, up to the limit, instead of the expenses on those rooms.
    rar_exempt = 0
    if mine.rent_a_room_rents and settings.rent_a_room_relief:
        shared = any(p.rent_a_room_shared for p in properties if p.use == "rent_a_room")
        limit = RENT_A_ROOM_SHARED_LIMIT if shared else RENT_A_ROOM_LIMIT
        rar_exempt = min(mine.rent_a_room_rents, limit)
        rar_costs = sum(f.mine.expenses for f in figures if f.use == "rent_a_room")
        if rar_costs:
            warnings.append(
                "Rent a Room relief is claimed instead of the expenses on those rooms, so their expenses are left "
                "out of the figures sent."
            )
            for f in figures:
                if f.use == "rent_a_room":
                    for k, v in f.mine.by_category.items():
                        if BY_KEY[k].group == "expenses":
                            mine.by_category[k] = mine.by_category.get(k, 0) - v
            mine.close()
        if mine.rent_a_room_rents > limit:
            warnings.append(
                f"Rent a Room rents are over £{limit // 100:,}: only that much is exempt; you may do better "
                "claiming expenses instead (HMRC HS223)."
            )

    if mine.income > CASH_BASIS_LIMIT:
        warnings.append("Receipts over £150,000 must use traditional accounting (accruals), not the cash basis.")
    else:
        warnings.append(CASH_BASIS_NOTE)

    finance = finance_credit(
        tax_year,
        max(0, mine.finance_res),
        settings.finance_brought_forward.get(tax_year, 0),
        max(0, mine.profit - rar_exempt),
        adjusted_income_above_pa,
    )
    return PropertySummary(
        tax_year=tax_year,
        start=start,
        end=end,
        properties=figures,
        unallocated=unallocated,
        mine=mine,
        finance=finance,
        allowance=allowance_check(mine),
        rent_a_room_exempt=rar_exempt,
        warnings=warnings,
    )


def finance_credit(
    tax_year: str, finance_costs: int, brought_forward: int, profits: int, income_above_pa: int | None
) -> FinanceCredit:
    """The basic-rate tax reduction for residential finance costs (gov.uk 'how it's worked out'): rate x the
    lowest of (a) finance costs + brought forward, (b) property profits, (c) adjusted total income above the
    personal allowance. The unrelieved part of (a) carries forward. An estimate: HMRC's calculation is final."""
    rate = finance_credit_rate(tax_year)
    a = finance_costs + brought_forward
    limits = [a, profits] + ([max(0, income_above_pa)] if income_above_pa is not None else [])
    relieved = min(limits)
    credit = relieved * rate // 100
    note = (
        f"Estimate: {rate} % of the lowest of your finance costs (with any brought forward), your property profits"
        + (" and your income above the personal allowance" if income_above_pa is not None else "")
        + ". HMRC works out the final figure; the tax reduction cannot make a refund."
    )
    if income_above_pa is None:
        note += " Your other income is not in these books, so that third limit is not applied."
    return FinanceCredit(
        rate_percent=rate,
        finance_costs=finance_costs,
        brought_forward=brought_forward,
        profits_limit=profits,
        income_limit=income_above_pa,
        relieved=relieved,
        credit=credit,
        carried_forward=a - relieved,
        note=note,
    )


def allowance_check(mine: Amounts) -> AllowanceCheck:
    claimed = mine.expenses + mine.domestic_items
    gross = mine.income
    if gross <= PROPERTY_ALLOWANCE:
        better: Literal["expenses", "property_allowance", "either"] = (
            "property_allowance" if claimed < gross else "either" if claimed == gross else "expenses"
        )
        note = (
            "Gross property income of £1,000 or less is covered by the property allowance; you may not need to "
            "tell HMRC."
        )
    else:
        if claimed < PROPERTY_ALLOWANCE:
            better = "property_allowance"
        else:
            better = "expenses" if claimed > PROPERTY_ALLOWANCE else "either"
        note = (
            "You can deduct £1,000 instead of your expenses; you cannot do both, and residential finance costs then "
            "give no tax reduction."
        )
    return AllowanceCheck(
        property_allowance_pence=PROPERTY_ALLOWANCE,
        gross_income=gross,
        expenses_claimed=claimed,
        better=better,
        note=note,
    )


# --------------------------------------------------------------------------- #
# HMRC bodies (Property Business API 6.0)
# --------------------------------------------------------------------------- #


def _pounds(pence: int) -> float:
    return float(Decimal(pence) / 100)


def cumulative_body(summary: PropertySummary, settings: PropertySettings) -> dict[str, Any]:
    """The request body of "Create or Amend a UK Property Cumulative Period Summary" for 6 April to the period end,
    the user's share. Income fields 0 or more; expenses may be negative (an undo or refund larger than the costs)."""
    if summary.tax_year < FIRST_CUMULATIVE_TAX_YEAR:
        raise ValueError("the cumulative endpoint takes tax years from 2025-26")
    c = summary.mine.by_category
    income: dict[str, Any] = {}
    for key in ("premiums", "reverse_premiums", "rents", "other_income"):
        if c.get(key):
            income[BY_KEY[key].field] = _pounds(max(0, c[key]))
    if c.get("rent_a_room"):
        income["rentARoom"] = {"rentsReceived": _pounds(max(0, c["rent_a_room"]))}
    expenses: dict[str, Any] = {}
    if settings.consolidated_expenses:
        expenses["consolidatedExpenses"] = _pounds(summary.mine.expenses)
    else:
        for cat in CATEGORIES:
            if cat.group == "expenses" and c.get(cat.key):
                expenses[cat.field] = _pounds(c[cat.key])
    if summary.finance.finance_costs:
        expenses["residentialFinancialCost"] = _pounds(summary.finance.finance_costs)
    if summary.finance.brought_forward:
        expenses["residentialFinancialCostsCarriedForward"] = _pounds(summary.finance.brought_forward)
    if summary.rent_a_room_exempt:
        expenses["rentARoom"] = {"amountClaimed": _pounds(summary.rent_a_room_exempt)}
    body: dict[str, Any] = {"fromDate": summary.start.isoformat(), "toDate": summary.end.isoformat()}
    uk: dict[str, Any] = {}
    if income:
        uk["income"] = income
    if expenses:
        uk["expenses"] = expenses
    body["ukProperty"] = uk
    return body


def consolidated_allowed(summary: PropertySummary) -> bool:
    return summary.mine.income < CONSOLIDATED_LIMIT


def annual_body(summary: PropertySummary) -> dict[str, Any]:
    """ "Create and Amend a UK Property Business Annual Submission": the allowances Accnomos knows about. Only
    the replacement of domestic items relief (box 36); capital allowances are for the user's accountant."""
    allowances: dict[str, Any] = {}
    if summary.mine.domestic_items > 0:
        allowances["costOfReplacingDomesticItems"] = _pounds(summary.mine.domestic_items)
    return {"ukProperty": {"allowances": allowances}} if allowances else {"ukProperty": {}}


def sa105_boxes(summary: PropertySummary) -> list[dict[str, Any]]:
    """SA105 boxes 20-29, 36, 37, 44 and 45 for the user's share (HMRC's mapping file)."""
    c = summary.mine.by_category
    rows: dict[str, int] = defaultdict(int)
    labels = {
        "20": "Total rents and other income from property",
        "22": "Premiums for the grant of a lease",
        "23": "Reverse premiums and inducements",
        "24": "Rent, rates, insurance and ground rents",
        "25": "Property repairs and maintenance",
        "26": "Non-residential property finance costs",
        "27": "Legal, management and other professional fees",
        "28": "Costs of services provided, including wages",
        "29": "Other allowable property expenses",
        "36": "Costs of replacing domestic items",
        "37": "Rent a Room exempt amount",
        "44": "Residential property finance costs",
        "45": "Unused residential property finance costs brought forward",
    }
    for key, pence in c.items():
        rows[BY_KEY[key].box] += pence
    rows["37"] = summary.rent_a_room_exempt
    rows["44"] = summary.finance.finance_costs
    rows["45"] = summary.finance.brought_forward
    return [{"box": b, "label": labels[b], "pence": rows.get(b, 0)} for b in labels]
