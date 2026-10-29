"""The new-user set-up wizard: one question per step, saved as you go into `_System/profile.json`.

The wizard never files anything: it only writes the account's own profile.json (under a `"setup"` key next to
`name`/`kind`/`settings`, which `app/profile.py` ignores) plus, on confirm, the profile itself. Companies House and
HMRC look-ups happen through the existing `/lookup/*` routes; the wizard stores what the user confirmed from them
(the company details, the VAT check answer) and judges the answers with the rules below.

Thresholds and their sources (all HMRC, all UK English):

* VAT registration: taxable turnover over £90,000 in the last 12 months (or expected to go over in the next 30
  days) — "Register for VAT" (gov.uk) and VAT Notice 700/1; £90,000 from 1 April 2024.
* Cash basis the default for sole traders from 6 April 2024 — docs/HMRC.md lines 170-183.
* Making Tax Digital for Income Tax: turnover over £50,000 from 6 April 2026, over £30,000 from April 2027 —
  "Use Making Tax Digital for Income Tax" (gov.uk).
* Flat Rate Scheme: join at £150,000 or less, leave over £230,000; limited-cost trader (under 2% relevant goods,
  or under £1,000 a year) pays 16.5%; new registrations get a 1% discount in the first year — VAT Notice 733
  (see also `packages/ledger/src/accnomos_ledger/vat_schemes.py`).
* Cash Accounting and Annual Accounting Schemes: join at £1.35m or less — VAT Notices 731 and 732. The Flat Rate
  Scheme cannot be combined with cash accounting — VAT Notice 733.

A VAT check that names a different business from the company/trading name is a hard stop: the wizard status
answers `can_continue: false` until the number is fixed or the user explicitly confirms the number is theirs
anyway (recorded, never silent).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import profile as profile_mod

SETUP_KEY = "setup"

BusinessType = Literal["limited_company", "sole_trader", "landlord", "partnership", "personal"]

#: The five answers to "What are you?", each with its one-line explanation.
BUSINESS_TYPES: tuple[tuple[BusinessType, str, str], ...] = (
    ("limited_company", "Limited company", "A company registered at Companies House, separate from you."),
    ("sole_trader", "Sole trader (self-employed)", "You run the business yourself and keep all the profit."),
    ("landlord", "Landlord", "You rent out one or more properties for income."),
    ("partnership", "Partnership", "Two or more people share a business that is not a company."),
    ("personal", "Personal finances only", "Just your own money in and out; no business, no tax returns."),
)

#: Profile kind each business type confirms into.
KIND_FOR: dict[str, profile_mod.ProfileKind] = {
    "limited_company": "company",
    "sole_trader": "sole_trader",
    "landlord": "landlord",
    "partnership": "partnership",
    "personal": "personal",
}

VAT_REG_THRESHOLD_PENCE = 9_000_000  # £90,000 taxable turnover, from 1 April 2024
MTD_ITSA_FROM_2026_PENCE = 5_000_000  # £50,000 turnover, mandated from 6 April 2026
MTD_ITSA_FROM_2027_PENCE = 3_000_000  # £30,000 turnover, mandated from April 2027
CASH_BASIS_DEFAULT_SINCE = "2024-04-06"  # cash basis the default for sole traders since this date
FIRST_YEAR_DISCOUNT_PCT = 1  # flat-rate first-year discount for newly VAT-registered businesses

VatScheme = Literal["standard", "flat_rate", "cash", "annual"]
AccountingBasis = Literal["cash", "traditional"]

#: Steps in order. The company step only applies to limited companies; VAT detail only when registered; the
#: income-tax, CIS, payroll and property steps only apply to non-personal books.
STEPS: tuple[str, ...] = (
    "business_type",
    "company",
    "vat",
    "income_tax",
    "cis",
    "payroll",
    "property",
    "summary",
)

PAYE_REF_RE = re.compile(r"^\d{3}/[A-Z0-9]{1,10}$")  # e.g. 123/AB45678
ACCOUNTS_OFFICE_REF_RE = re.compile(r"^\d{3}P[A-Z]\d{8}$")  # e.g. 123PA00045678

_SUFFIXES = ("LTD", "LIMITED", "PLC", "LLP", "LP", "CIC", "LLC", "INC")


def _tokens(name: str) -> set[str]:
    """Name words worth comparing: upper-cased, accents off, punctuation and company suffixes gone."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Z0-9&]+", ascii_name.upper())
    return {w for w in words if w not in _SUFFIXES and not (len(w) == 1 and w != "&")}


def names_match(trading_name: str, registered_name: str) -> bool:
    """Do these names plausibly name the same business? True when every significant word of the shorter name
    appears in the longer one, or the two strings are near-identical (ratio 0.85 or more)."""
    ours, theirs = _tokens(trading_name), _tokens(registered_name)
    if not ours or not theirs:
        return False
    if ours <= theirs or theirs <= ours:
        return True

    def plain(s: str) -> str:
        scrubbed = re.sub(r"[^A-Z0-9 ]", "", (s or "").upper())
        return re.sub(r"\s+", " ", scrubbed).strip()

    a, b = plain(trading_name), plain(registered_name)
    return bool(a and b) and SequenceMatcher(None, a, b).ratio() >= 0.85


class SetupIssue(BaseModel):
    """One thing the summary page shows: what looks off, and which step fixes it."""

    code: str
    message: str
    fix_step: str
    blocking: bool = False


class SetupState(BaseModel):
    """The wizard's answers, kept under profile.json's `"setup"` key. Every step is optional until confirm."""

    business_type: BusinessType | None = None
    business_name: str = ""
    company: dict[str, Any] = Field(default_factory=dict)
    vat: dict[str, Any] = Field(default_factory=dict)
    income_tax: dict[str, Any] = Field(default_factory=dict)
    cis: dict[str, Any] = Field(default_factory=dict)
    payroll: dict[str, Any] = Field(default_factory=dict)
    property: dict[str, Any] = Field(default_factory=dict)
    confirmed_at: str | None = None

    model_config = {"extra": "ignore"}


def blank_setup() -> dict[str, Any]:
    return SetupState().model_dump()


def steps_for(business_type: str | None) -> list[str]:
    """Which steps this business answers. Personal books only name themselves; everyone else answers all but
    the company step (limited companies only)."""
    if business_type == "personal":
        return ["business_type", "summary"]
    steps = [s for s in STEPS if s != "company" or business_type == "limited_company"]
    return steps


def first_incomplete(setup: dict[str, Any]) -> str:
    """The step the wizard should show next: the first unanswered one for this business type."""
    state = SetupState.model_validate(setup)
    bt = state.business_type
    if bt is None or not state.business_name.strip():
        return "business_type"
    if bt == "personal":
        return "summary"
    if bt == "limited_company" and not state.company.get("confirmed"):
        return "company"
    vat = state.vat
    if not vat.get("asked"):
        return "vat"
    if vat.get("registered"):
        if not vat.get("scheme"):
            return "vat"
        if vat.get("scheme") == "flat_rate" and not vat.get("flat_rate", {}).get("sector"):
            return "vat"
        if not vat.get("period_start"):
            return "vat"
    if not state.income_tax.get("asked"):
        return "income_tax"
    if not state.cis.get("asked"):
        return "cis"
    if not state.payroll.get("asked"):
        return "payroll"
    if bt == "landlord" and not state.property.get("asked"):
        return "property"
    return "summary"


def evaluate(setup: dict[str, Any]) -> list[SetupIssue]:
    """Every inconsistency in the answers so far: blocking ones stop the wizard, the rest warn on the summary."""
    state = SetupState.model_validate(setup)
    issues: list[SetupIssue] = []
    vat = state.vat
    if vat.get("registered"):
        check = vat.get("vat_check") or {}
        if check.get("registered") is False:
            issues.append(
                SetupIssue(
                    code="vat_not_registered",
                    message="HMRC says this VAT number is not registered. Check the number and try again.",
                    fix_step="vat",
                    blocking=True,
                )
            )
        elif (
            check.get("registered")
            and not vat.get("mismatch_acknowledged")
            and not names_match(state.business_name, str(check.get("name") or ""))
        ):
            issues.append(
                SetupIssue(
                    code="vat_name_mismatch",
                    message=(
                        f"HMRC has this VAT number down as {check.get('name')!r}, which does not look like "
                        f"{state.business_name!r}. The wizard stops here: fix the VAT number, fix the "
                        "business name, or tick the box confirming the number is yours anyway."
                    ),
                    fix_step="vat",
                    blocking=True,
                )
            )
        schemes = vat.get("schemes") or ([vat.get("scheme")] if vat.get("scheme") else [])
        if "flat_rate" in schemes and "cash" in schemes:
            issues.append(
                SetupIssue(
                    code="flat_rate_cash",
                    message="The Flat Rate Scheme cannot be combined with cash accounting (VAT Notice 733). "
                    "Pick one of the two.",
                    fix_step="vat",
                    blocking=True,
                )
            )
        if vat.get("scheme") == "flat_rate":
            fr = vat.get("flat_rate") or {}
            goods_share = fr.get("relevant_goods_share_pct")
            goods_value = fr.get("relevant_goods_pence")
            low_goods = (goods_share is not None and goods_share < 2) or (
                goods_value is not None and goods_value < 100_000
            )
            if low_goods and fr.get("limited_cost") is not True:
                issues.append(
                    SetupIssue(
                        code="limited_cost_trader",
                        message="With under 2% relevant goods (or under £1,000 a year) this is a limited-cost "
                        "trader and the flat rate is 16.5% — confirm the limited-cost box.",
                        fix_step="vat",
                        blocking=False,
                    )
                )
    else:
        turnover = (state.income_tax.get("turnover_pence") or 0) if state.income_tax.get("asked") else 0
        if turnover and turnover > VAT_REG_THRESHOLD_PENCE:
            issues.append(
                SetupIssue(
                    code="vat_threshold",
                    message="Turnover is over the £90,000 VAT registration threshold, but this business is not "
                    "VAT-registered. Register for VAT or explain why not.",
                    fix_step="vat",
                    blocking=False,
                )
            )
    it = state.income_tax
    if (
        it.get("asked")
        and (it.get("turnover_pence") or 0) > 0
        and state.business_type
        in (
            "sole_trader",
            "landlord",
        )
    ):
        turnover = it["turnover_pence"]
        if turnover > MTD_ITSA_FROM_2026_PENCE:
            issues.append(
                SetupIssue(
                    code="mtd_itsa_2026",
                    message="Turnover is over £50,000, so Making Tax Digital for Income Tax applies from "
                    "6 April 2026: quarterly updates plus a final declaration.",
                    fix_step="income_tax",
                    blocking=False,
                )
            )
        elif turnover > MTD_ITSA_FROM_2027_PENCE:
            issues.append(
                SetupIssue(
                    code="mtd_itsa_2027",
                    message="Turnover is over £30,000, so Making Tax Digital for Income Tax applies from "
                    "April 2027: quarterly updates plus a final declaration.",
                    fix_step="income_tax",
                    blocking=False,
                )
            )
    pay = state.payroll
    if pay.get("asked") and pay.get("has_employees"):
        ref = (pay.get("paye_reference") or "").strip().upper()
        if ref and not PAYE_REF_RE.fullmatch(ref):
            issues.append(
                SetupIssue(
                    code="paye_format",
                    message=f"{ref!r} does not look like an Employer PAYE reference (3 digits, a slash, then "
                    "letters and digits, e.g. 123/AB45678).",
                    fix_step="payroll",
                    blocking=False,
                )
            )
        ao = (pay.get("accounts_office_reference") or "").strip().upper()
        if ao and not ACCOUNTS_OFFICE_REF_RE.fullmatch(ao):
            issues.append(
                SetupIssue(
                    code="ao_format",
                    message=f"{ao!r} does not look like an Accounts Office reference (e.g. 123PA00045678).",
                    fix_step="payroll",
                    blocking=False,
                )
            )
    return issues


def planned_returns(setup: dict[str, Any]) -> list[dict[str, str]]:
    """What the app will do with these answers: which returns, and when each is due. Plain words, no filing."""
    state = SetupState.model_validate(setup)
    out: list[dict[str, str]] = []
    vat = state.vat
    if vat.get("registered"):
        stagger = vat.get("stagger") or "quarterly"
        out.append(
            {
                "return": "VAT return (9 boxes)",
                "when": f"Every {stagger} VAT period; due 1 month and 7 days after the period ends, paid the same day.",
            }
        )
        if vat.get("scheme") == "annual":
            out.append(
                {
                    "return": "Annual accounting advance payments",
                    "when": "Nine monthly instalments through the year, balancing payment with the annual return.",
                }
            )
    if state.business_type in ("sole_trader", "landlord"):
        it = state.income_tax
        turnover = it.get("turnover_pence") or 0 if it.get("asked") else 0
        mandated = turnover > MTD_ITSA_FROM_2026_PENCE or (
            datetime.now(UTC).date().isoformat() >= "2027-04-06" and turnover > MTD_ITSA_FROM_2027_PENCE
        )
        if mandated:
            out.append(
                {
                    "return": "Making Tax Digital quarterly updates",
                    "when": "Quarterly updates through the year, plus a final declaration by the next 31 January.",
                }
            )
        else:
            out.append(
                {
                    "return": "Self Assessment tax return",
                    "when": "Due 31 January after the tax year ends (SA103S for self-employment, SA105 for property).",
                }
            )
    if state.business_type == "limited_company":
        out.append(
            {
                "return": "Company accounts and confirmation statement",
                "when": "Accounts to Companies House 9 months after the year end; confirmation statement every year.",
            }
        )
        out.append(
            {
                "return": "Corporation Tax return (CT600)",
                "when": "Due 12 months after the accounting period ends; the bill itself 9 months and 1 day after.",
            }
        )
    cis = state.cis
    if cis.get("is_contractor"):
        out.append(
            {
                "return": "CIS300 monthly return",
                "when": "Due within 14 days after each tax month ends on the 5th; deductions paid by the 19th.",
            }
        )
    if state.payroll.get("has_employees"):
        out.append(
            {
                "return": "Full Payment Submission (FPS)",
                "when": "On or before every payday; an EPS for months with no pay, and the P32 bill each month.",
            }
        )
    if state.business_type == "personal":
        out.append({"return": "Nothing to file", "when": "Personal books keep budgets and spending only."})
    return out


def summary(setup: dict[str, Any]) -> dict[str, Any]:
    """The final wizard page: what the app will do, and everything that looks inconsistent, each with a fix link."""
    issues = evaluate(setup)
    blocking = [i for i in issues if i.blocking]
    return {
        "returns": planned_returns(setup),
        "issues": [i.model_dump() for i in issues],
        "blocking": [i.model_dump() for i in blocking],
        "can_continue": not blocking,
        "filed": [],
        "filing_note": "Nothing is filed with HMRC or Companies House by the set-up wizard.",
    }


def get_setup(raw: Any) -> dict[str, Any]:
    """The saved wizard answers from a profile.json dict (missing or hand-edited file gives a blank wizard)."""
    if not isinstance(raw, dict):
        return blank_setup()
    saved = raw.get(SETUP_KEY)
    if not isinstance(saved, dict):
        return blank_setup()
    try:
        return SetupState.model_validate(saved).model_dump()
    except Exception:
        return blank_setup()


def profile_settings_for(setup: dict[str, Any]) -> dict[str, Any]:
    """The /profile settings these answers confirm into (validated by app/profile.py on confirm)."""
    state = SetupState.model_validate(setup)
    settings: dict[str, Any] = {}
    company = state.company
    if state.business_type == "limited_company" and company.get("number"):
        settings["company_number"] = company["number"]
    vat = state.vat
    if vat.get("registered") and vat.get("vat_number"):
        settings["vat_number"] = vat["vat_number"]
        settings["vat_registered"] = True
    elif state.business_type != "personal":
        settings["vat_registered"] = bool(vat.get("registered", False))
    utr = state.income_tax.get("utr")
    if utr and state.business_type in ("sole_trader", "landlord", "partnership"):
        settings["utr"] = utr
    start = state.income_tax.get("accounting_period_start")
    if start and state.business_type == "sole_trader":
        settings["accounting_period_start"] = start
    return settings


def confirm_note() -> str:
    return "Set-up wizard confirmed. Nothing was filed with HMRC or Companies House."
