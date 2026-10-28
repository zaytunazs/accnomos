"""Self-employment figures for Making Tax Digital for Income Tax, from the approved ledger. Code, never a model.

HMRC's Self-Employment Business API 5.0 takes a *cumulative* period summary for tax years from 2025-26: every
update covers 6 April (the start of the tax year) to the end of the period being reported, and replaces the one
before it. `se_summary` adds up the approved ledger lines dated in that window into the API's fields:

    periodIncome                 turnover (SA103F box 15), other (box 16)
    periodExpenses               TOTAL expenses per category (boxes 17-30), allowable and disallowable together
    periodDisallowableExpenses   the part of each category that cannot be claimed (boxes 32-45)

That expenses are totals and disallowables a subset is HMRC's own mapping: income-tax-mtd-changelog
mapping/csv/sa103f_mapping_v3.csv ("Business Expenses (total expenses)" boxes 17-30 → periodExpenses,
"(disallowable expenses)" boxes 32-45 → periodDisallowableExpenses), checked 28 Oct 2026.

Accounts are placed by their four-digit code (the chart in app/journal.py), with a few name words that override the
code because they decide the tax treatment (entertainment, depreciation, subcontractors, bad debts, interest,
repairs). Balance-sheet accounts (1xxx-3xxx: bank, debtors, VAT control, owner's loan) never count, so on a
VAT-registered business the figures are net of VAT. Disallowable: business entertainment and depreciation in full,
plus any account whose name says "disallowable", "private" or "personal" (Accnomos has no private-use split yet).

Basis: as approved, like the P&L in app/reports.py (an invoice counts when raised, a receipt when bought). From
6 April 2024 the cash basis is HMRC's default for sole traders (gov.uk/simpler-income-tax-cash-basis), so the
summary says which basis it used and warns; it never converts one into the other.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from accnomos_ledger import LedgerEvent

Group = Literal["income", "expenses"]

TAX_YEAR = re.compile(r"^(20\d{2})-(\d{2})$")
#: The cumulative endpoint's first tax year (Self-Employment Business API 5.0, path parameter `taxYearFrom2025`).
FIRST_CUMULATIVE_TAX_YEAR = "2025-26"
BASIS = "As approved: an invoice counts on the day it was raised, a receipt on the day it was bought. Not cash basis."
CASH_BASIS_WARNING = (
    "Since 6 April 2024 HMRC treats sole traders as using the cash basis unless they opt out. These figures are "
    "as approved (invoice and receipt dates), not money in and out of the bank. If you use the cash basis, check "
    "them before you submit."
)


@dataclass(frozen=True)
class Field:
    key: str  # the API field name, e.g. "costOfGoods"
    group: Group
    box: int  # SA103F box: 15-16 income, 17-30 expenses
    disallowable_box: int | None  # SA103F box 32-45 for the disallowable part
    label: str


FIELDS: tuple[Field, ...] = (
    Field("turnover", "income", 15, None, "Turnover: takings, fees, sales"),
    Field("other", "income", 16, None, "Any other business income"),
    Field("costOfGoods", "expenses", 17, 32, "Cost of goods bought for resale or goods used"),
    Field("paymentsToSubcontractors", "expenses", 18, 33, "Construction industry: payments to subcontractors"),
    Field("wagesAndStaffCosts", "expenses", 19, 34, "Wages, salaries and other staff costs"),
    Field("carVanTravelExpenses", "expenses", 20, 35, "Car, van and travel expenses"),
    Field("premisesRunningCosts", "expenses", 21, 36, "Rent, rates, power and insurance costs"),
    Field("maintenanceCosts", "expenses", 22, 37, "Repairs and maintenance of property and equipment"),
    Field("adminCosts", "expenses", 23, 38, "Phone, fax, stationery and other office costs"),
    Field("advertisingCosts", "expenses", 24, 39, "Advertising costs"),
    Field("businessEntertainmentCosts", "expenses", 24, 39, "Business entertainment costs"),
    Field("interestOnBankOtherLoans", "expenses", 25, 40, "Interest on bank and other loans"),
    Field("financeCharges", "expenses", 26, 41, "Bank, credit card and other financial charges"),
    Field("irrecoverableDebts", "expenses", 27, 42, "Irrecoverable debts written off"),
    Field("professionalFees", "expenses", 28, 43, "Accountancy, legal and other professional fees"),
    Field("depreciation", "expenses", 29, 44, "Depreciation and loss or profit on sale of assets"),
    Field("otherExpenses", "expenses", 30, 45, "Other business expenses"),
)
BY_KEY = {f.key: f for f in FIELDS}
#: Not allowable, so the whole amount is also disallowable. gov.uk/expenses-if-youre-self-employed (checked 28 Oct
#: 2026): "You cannot claim for ... depreciation of equipment"; "You cannot usually claim the cost of entertaining
#: clients, suppliers or customers". Entertaining your own staff is a staff cost (the name rule below).
ALWAYS_DISALLOWABLE = frozenset({"businessEntertainmentCosts", "depreciation"})

# Four-digit code ranges -> field (inclusive). The chart is app/journal.py; reports.py uses the same code sections.
RANGES: tuple[tuple[int, int, str], ...] = (
    (4000, 4899, "turnover"),
    (4900, 4999, "other"),
    (5000, 5999, "costOfGoods"),
    (6000, 6999, "advertisingCosts"),  # 6200 Advertising
    (7000, 7099, "wagesAndStaffCosts"),  # 7000 Gross wages, 7010 Employer's NI
    (7100, 7299, "premisesRunningCosts"),  # 7100 Rent, 7200 Utilities
    (7300, 7499, "carVanTravelExpenses"),  # 7300 Motor, 7310 mileage allowance, 7400 Travel, 7410 Subsistence
    (7500, 7599, "adminCosts"),  # office supplies, software, postage, telephone
    (7600, 7699, "professionalFees"),
    (7700, 7799, "premisesRunningCosts"),  # 7700 Insurance: box 21 is "rent, rates, power and insurance"
    (7800, 7899, "maintenanceCosts"),
    (7900, 7909, "financeCharges"),  # 7900 Bank charges
    (7910, 7949, "interestOnBankOtherLoans"),
    (7950, 7989, "irrecoverableDebts"),
    (7990, 7999, "otherExpenses"),  # 7999 Sundry expenses
    (8000, 8099, "depreciation"),
    (8100, 8999, "otherExpenses"),
)
# Words in an account name that decide the treatment whatever the code (first match wins).
NAME_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"staff entertain", re.I), "wagesAndStaffCosts"),
    (re.compile(r"entertain", re.I), "businessEntertainmentCosts"),
    (re.compile(r"depreciat", re.I), "depreciation"),
    (re.compile(r"sub-?contract", re.I), "paymentsToSubcontractors"),
    (re.compile(r"bad debt|irrecoverable", re.I), "irrecoverableDebts"),
    (re.compile(r"\binterest\b", re.I), "interestOnBankOtherLoans"),
    (re.compile(r"repair|maintenance", re.I), "maintenanceCosts"),
)
DISALLOWABLE_NAME = re.compile(r"disallowable|\bprivate\b|\bpersonal\b", re.I)
_CODE = re.compile(r"^\s*(\d{4})\b")

#: HMRC's final declaration, verbatim from the Income Tax MTD end-to-end service guide, "Agreeing to the declaration"
#: (developer.service.hmrc.gov.uk/guides/income-tax-mtd-end-to-end-service-guide/documentation/
#: make-updates-at-tax-year-end.html, checked 28 Oct 2026). The relay and the web page carry the same text.
FINAL_DECLARATION = (
    "I declare that the information and tax return I have submitted are (taken together) correct and complete to "
    "the best of my knowledge. I understand that I may have to pay financial penalties and face prosecution if I "
    "give false information."
)


def tax_year_of(day: date) -> str:
    """'2026-27' for any day from 6 April 2026 to 5 April 2027."""
    start = day.year if day >= date(day.year, 4, 6) else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def tax_year_bounds(tax_year: str) -> tuple[date, date]:
    """'2026-27' -> (6 Apr 2026, 5 Apr 2027). ValueError for '2026-28' or '2026/27'."""
    m = TAX_YEAR.fullmatch(tax_year)
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise ValueError(f"tax year must look like 2026-27, not {tax_year!r}")
    start = int(m.group(1))
    return date(start, 4, 6), date(start + 1, 4, 5)


def field_for(account: str) -> str | None:
    """The API field an account feeds, or None for a balance-sheet account (or one without a code)."""
    m = _CODE.match(account)
    if not m:
        return None
    code = int(m.group(1))
    if not 4000 <= code <= 8999:
        return None
    if code >= 5000:  # a name rule never turns an expense into income, or income into an expense
        for pattern, key in NAME_RULES:
            if pattern.search(account):
                return key
    return next(key for lo, hi, key in RANGES if lo <= code <= hi)


def is_disallowable(account: str, key: str) -> bool:
    return BY_KEY[key].group == "expenses" and (key in ALWAYS_DISALLOWABLE or bool(DISALLOWABLE_NAME.search(account)))


class Contribution(BaseModel):
    """One ledger line behind a figure, so every number can be traced to the entries that made it."""

    event_id: str
    date: date
    kind: str  # purchase / sale / bank / adjustment / reversal
    counterparty: str | None
    account: str
    memo: str | None
    pence: int  # signed: what this line adds to the figure (a reversal or credit note subtracts)
    disallowable: bool


class SeFigure(BaseModel):
    key: str
    group: Group
    box: int
    disallowable_box: int | None
    label: str
    pence: int  # total for the period (income, or all expenses in this category)
    disallowable_pence: int  # expenses only: the part that cannot be claimed
    lines: list[Contribution]


class SeSummary(BaseModel):
    tax_year: str
    period_start: date  # always 6 April: the API is cumulative
    period_end: date
    basis: str = BASIS
    income_pence: int
    expenses_pence: int  # total expenses, allowable and disallowable
    disallowable_pence: int
    allowable_pence: int
    net_profit_pence: int  # income - allowable expenses: the figure before HMRC's adjustments and allowances
    figures: list[SeFigure]
    event_ids: list[str]
    unmapped_accounts: list[str]  # P&L-looking names without a code: left out, listed so nothing goes missing quietly
    warnings: list[str]
    can_submit: bool
    blockers: list[str]  # why can_submit is false
    hmrc_body: dict  # the request body for PUT .../cumulative/{taxYear}, exactly as the relay sends it


def pounds(pence: int) -> float:
    """Integer pence -> pounds as a JSON number with at most 2 dp (Decimal first: no float drift)."""
    return float(Decimal(pence) / 100)


def se_summary(events: list[LedgerEvent], tax_year: str, period_end: date) -> SeSummary:
    """The cumulative figures from 6 April of `tax_year` to `period_end`, with the lines behind each one."""
    start, year_end = tax_year_bounds(tax_year)
    if not start <= period_end <= year_end:
        raise ValueError(f"period end {period_end} is outside the {tax_year} tax year ({start} to {year_end})")

    totals: dict[str, int] = defaultdict(int)
    disallowed: dict[str, int] = defaultdict(int)
    lines: dict[str, list[Contribution]] = defaultdict(list)
    unmapped: set[str] = set()
    used: set[str] = set()
    for event in sorted(events, key=lambda e: (e.date, e.id)):
        if not start <= event.date <= period_end:
            continue
        for line in event.lines:
            key = field_for(line.account)
            if key is None:
                if not _CODE.match(line.account) and not re.search(
                    r"bank|cash|vat|debtor|creditor|loan", line.account, re.I
                ):
                    unmapped.add(line.account)
                continue
            f = BY_KEY[key]
            pence = (line.credit - line.debit) if f.group == "income" else (line.debit - line.credit)
            dis = is_disallowable(line.account, key)
            totals[key] += pence
            if dis:
                disallowed[key] += pence
            lines[key].append(
                Contribution(
                    event_id=event.id,
                    date=event.date,
                    kind=event.kind,
                    counterparty=event.counterparty,
                    account=line.account,
                    memo=line.memo,
                    pence=pence,
                    disallowable=dis,
                )
            )
            used.add(event.id)

    figures = [
        SeFigure(
            key=f.key,
            group=f.group,
            box=f.box,
            disallowable_box=f.disallowable_box,
            label=f.label,
            pence=totals[f.key],
            disallowable_pence=disallowed[f.key],
            lines=lines[f.key],
        )
        for f in FIELDS
    ]
    income = sum(totals[f.key] for f in FIELDS if f.group == "income")
    expenses = sum(totals[f.key] for f in FIELDS if f.group == "expenses")
    disallowable = sum(disallowed.values())

    warnings = [CASH_BASIS_WARNING]
    if unmapped:
        warnings.append(
            "Some accounts have no four-digit code, so they are left out: " + ", ".join(sorted(unmapped)) + "."
        )
    if any(disallowed.values()):
        warnings.append(
            "Disallowable amounts are client entertainment and depreciation (counted in full) and accounts named "
            "disallowable, private or personal. They stay in the expense totals and are also listed as disallowable, "
            "as HMRC's form does."
        )
    blockers = []
    if tax_year < FIRST_CUMULATIVE_TAX_YEAR:
        blockers.append(f"HMRC takes cumulative updates from the {FIRST_CUMULATIVE_TAX_YEAR} tax year only.")
    for f in FIELDS:
        if f.group == "income" and totals[f.key] < 0:
            blockers.append(
                f"{f.label} is below zero (more credited back than sold). HMRC accepts 0 or more: check the entries."
            )

    return SeSummary(
        tax_year=tax_year,
        period_start=start,
        period_end=period_end,
        income_pence=income,
        expenses_pence=expenses,
        disallowable_pence=disallowable,
        allowable_pence=expenses - disallowable,
        net_profit_pence=income - (expenses - disallowable),
        figures=figures,
        event_ids=sorted(used),
        unmapped_accounts=sorted(unmapped),
        warnings=warnings,
        can_submit=not blockers,
        blockers=blockers,
        hmrc_body=hmrc_body(start, period_end, totals, disallowed),
    )


def hmrc_body(start: date, end: date, totals: dict[str, int], disallowed: dict[str, int]) -> dict:
    """Self-Employment Business API 5.0, Create or Amend a Self-Employment Cumulative Period Summary request
    (schemas/createAmendCumulativePeriodSummary/request.json). HMRC: "Submissions must include values for income
    and expenses, even if the values are zero", so every income and expense field is sent; the disallowable
    object only when something is disallowable."""
    body: dict = {
        "periodDates": {"periodStartDate": start.isoformat(), "periodEndDate": end.isoformat()},
        "periodIncome": {f.key: pounds(totals.get(f.key, 0)) for f in FIELDS if f.group == "income"},
        "periodExpenses": {f.key: pounds(totals.get(f.key, 0)) for f in FIELDS if f.group == "expenses"},
    }
    if any(disallowed.values()):
        body["periodDisallowableExpenses"] = {
            f"{f.key}Disallowable": pounds(disallowed.get(f.key, 0)) for f in FIELDS if f.group == "expenses"
        }
    return body
