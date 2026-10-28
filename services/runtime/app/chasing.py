"""Payment chasing: reminder sequences, editable drafts, and statutory late-payment interest.

Reminder steps live in the user's books (`_System/chasing.json`), so the sequence survives a reinstall.
Each step renders an editable email draft (subject + body, UK English, polite) from the invoice. Nothing is
ever sent automatically: a draft becomes a to-do for the user to approve, and only the existing
`POST /invoices/{number}/reminder-send` (with `confirm: true`) sends anything. Every approved reminder is
recorded on the invoice and in the audit trail (app/invoicing.py `send_reminder`).

Late-payment interest follows the Late Payment of Commercial Debts (Interest) Act 1998 for business-to-business
invoices only: statutory interest is the Bank of England base rate on the reference date (31 December for debts
in 1 January-30 June, 30 June for debts in 1 July-31 December) plus 8%, simple daily interest on the gross
amount, with fixed compensation of GBP 40 (under GBP 1,000), GBP 70 (GBP 1,000 to under GBP 10,000) or GBP 100
(GBP 10,000 and over). Source: https://www.gov.uk/late-commercial-payments-charging-interest-debt-recovery
(date checked 28 Oct 2026).

The Bank base rate is a config value with its effective date in `_System/chasing.json` (it is not fetched live).
TODO: when the Bank of England changes Bank Rate, add a new entry to `base_rates` in `_System/chasing.json`
with the new rate and the date it takes effect; older entries must be kept, because debts in earlier half-years
still use the rate from their own reference date.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.books import SYSTEM, Books
from app.invoicing import Invoice, InvoiceProfile, money, uk_date
from app.validation import LENIENT

CHASING = f"{SYSTEM}/chasing.json"

# Fixed denominator: the legislation's daily rate is the annual rate over a 365-day year, every year.
DAYS_IN_YEAR = 365
STATUTORY_UPLIFT_BPS = 800  # the Act's 8% over base, in basis points
COMPENSATION: tuple[tuple[int, int], ...] = (
    (100_000, 4_000),  # under GBP 1,000 -> GBP 40
    (1_000_000, 7_000),  # GBP 1,000 to under GBP 10,000 -> GBP 70
    # GBP 10,000 and over -> GBP 100 (the fall-through below)
)
COMPENSATION_TOP_PENCE = 10_000


class ChasingStep(BaseModel):
    id: str
    offset_days: int  # days overdue at which this step falls due (negative: before the due date)
    title: str  # shown in the app, e.g. "Friendly reminder"
    mention_interest: bool = False  # the final step names statutory interest and compensation


DEFAULT_STEPS: tuple[ChasingStep, ...] = (
    ChasingStep(id="pre-due", offset_days=-3, title="Friendly reminder"),
    ChasingStep(id="due", offset_days=0, title="Due today"),
    ChasingStep(id="week-overdue", offset_days=7, title="One week overdue"),
    ChasingStep(id="firm", offset_days=14, title="Firm reminder"),
    ChasingStep(id="final", offset_days=30, title="Final reminder", mention_interest=True),
)


class BaseRate(BaseModel):
    """One Bank of England base rate. Rates are kept as history, never overwritten."""

    annual_percent: Decimal  # e.g. 4.00 means 4%
    effective: date  # first day this rate applies
    source: str = "Bank of England official Bank Rate"


DEFAULT_BASE_RATES: tuple[BaseRate, ...] = (
    BaseRate(annual_percent=Decimal("4.00"), effective=date(2026, 8, 7)),
    # TODO: append a new BaseRate here (and in the user's _System/chasing.json) when Bank Rate changes.
)


class ChasingConfig(BaseModel):
    steps: list[ChasingStep] = Field(default_factory=lambda: [s.model_copy() for s in DEFAULT_STEPS])
    base_rates: list[BaseRate] = Field(default_factory=lambda: [r.model_copy() for r in DEFAULT_BASE_RATES])
    checked: str = "https://www.gov.uk/late-commercial-payments-charging-interest-debt-recovery (checked 28 Oct 2026)"


async def load_config(books: Books) -> ChasingConfig:
    """The user's chasing settings, or the defaults when nothing is saved yet."""
    return ChasingConfig.model_validate(await books.read_json(CHASING, {}), **LENIENT)


async def save_config(books: Books, config: ChasingConfig, user: str) -> ChasingConfig:
    await books._update_json(CHASING, {}, lambda _old: config.model_dump(mode="json"))
    await books.audit(f"user:{user}", "chasing_config_saved", {"path": CHASING})
    return config


def next_step(inv: Invoice, today: date, config: ChasingConfig) -> ChasingStep | None:
    """The next reminder step: the earliest step whose day has come and which has not been sent yet.

    Steps fall due in order and are chased in order. A send records its step id (app/invoicing.py
    `send_reminder`); sends from before step ids existed (`step` None) count as the earliest steps in order.
    Returns None when it is too early for the first step or every due step has been sent.
    """
    days = inv.overdue_days(today)
    if days is None:
        return None  # not awaiting payment (draft, paid or void)
    due = [s for s in config.steps if s.offset_days <= days]
    sent_ids = {r.step for r in inv.reminders if r.step}
    unknown = sum(1 for r in inv.reminders if not r.step)
    candidates = [s for s in due[unknown:] if s.id not in sent_ids]
    return candidates[0] if candidates else None


def render_draft(
    inv: Invoice, profile: InvoiceProfile, step: ChasingStep, today: date, business: bool
) -> tuple[str, str]:
    """(subject, body): the step's editable email draft, in polite UK English. Sends nothing."""
    days = inv.overdue_days(today) or 0
    amount, due = money(inv.total_pence), uk_date(inv.due_date)
    name = profile.name.strip() or "us"
    if step.id == "pre-due":
        subject = f"Gentle reminder: invoice {inv.number} ({amount}) due {due}"
        body = (
            f"Hello,\n\nJust a friendly note that invoice {inv.number} for {amount} is due on {due}.\n\n"
            "The payment details are on the attached invoice. Thank you in advance.\n\n"
            f"Kind regards,\n{name}"
        )
    elif step.id == "due":
        subject = f"Reminder: invoice {inv.number} ({amount}) due today"
        body = (
            f"Hello,\n\nThis is a quick reminder that invoice {inv.number} for {amount} is due today ({due}).\n\n"
            "The payment details are on the attached invoice. Thank you in advance.\n\n"
            f"Kind regards,\n{name}"
        )
    elif step.id == "week-overdue":
        subject = f"Following up: invoice {inv.number} ({amount}) now overdue"
        body = (
            f"Hello,\n\nFollowing up on my earlier email: invoice {inv.number} for {amount} was due on {due} "
            f"and is now {days} day{'s' if days != 1 else ''} overdue.\n\n"
            "Could you let me know when it will be paid? "
            "If it is already on its way, thank you, and please ignore this.\n\n"
            f"Kind regards,\n{name}"
        )
    elif step.id == "firm":
        subject = f"Overdue invoice {inv.number} ({amount}) — please advise payment date"
        body = (
            f"Hello,\n\nInvoice {inv.number} for {amount} was due on {due} "
            f"and is now {days} day{'s' if days != 1 else ''} overdue.\n\n"
            "Please let me know when I can expect payment, or reply if there is a problem with the invoice.\n\n"
            f"Kind regards,\n{name}"
        )
    else:
        subject = f"Final reminder: invoice {inv.number} ({amount})"
        line = (
            f"Hello,\n\nInvoice {inv.number} for {amount} was due on {due} "
            f"and is still unpaid {days} day{'s' if days != 1 else ''} later. Please pay it now, "
            "or reply if there is a problem."
        )
        interest = (
            " Under the Late Payment of Commercial Debts (Interest) Act 1998 we may claim statutory interest "
            "at 8% over the Bank of England base rate plus fixed compensation, and we would rather not do so."
            if business
            else ""
        )
        body = f"{line}{interest}\n\nThe payment details are on the attached invoice.\n\nKind regards,\n{name}"
    return subject, body


# --------------------------------------------------------------------------- #
# Statutory interest and compensation (business-to-business only)
# --------------------------------------------------------------------------- #


def reference_date(day: date) -> date:
    """The Act's reference date for a day of delay: 31 Dec (for 1 Jan-30 Jun) or 30 Jun (for 1 Jul-31 Dec)."""
    return date(day.year - 1, 12, 31) if day.month <= 6 else date(day.year, 6, 30)


def base_bps_for(day: date, rates: list[BaseRate]) -> int:
    """Bank base rate in basis points in force on the reference date for `day`.

    Falls back to the earliest configured rate when the reference date predates every entry, so old debts still
    get a figure rather than an error.
    """
    ref = reference_date(day)
    prior = [r for r in rates if r.effective <= ref]
    chosen = max(prior, key=lambda r: r.effective) if prior else min(rates, key=lambda r: r.effective)
    return int(chosen.annual_percent * 100)


def interest_pence(gross_pence: int, due: date, as_of: date, rates: list[BaseRate]) -> int:
    """Simple daily statutory interest on the gross amount for (as_of - due) days, in pence.

    Rounding: each half-year segment is rounded half up to the penny, and the segments are added. The daily rate
    is the segment's statutory annual rate (base + 8%) over a fixed 365-day year; all maths is integer pence and
    basis points, no floats.
    """
    if as_of <= due or gross_pence <= 0 or not rates:
        return 0
    total = 0
    start = due
    while start < as_of:
        # End of the half-year holding `start`: 1 July after a January-June start, else 1 January next year.
        boundary = date(start.year, 7, 1) if start.month <= 6 else date(start.year + 1, 1, 1)
        end = min(boundary, as_of)
        days = (end - start).days
        annual_bps = base_bps_for(start, rates) + STATUTORY_UPLIFT_BPS
        # gross * rate * days / 365, in pence from basis points: round half up with integer maths.
        total += (gross_pence * annual_bps * days + (DAYS_IN_YEAR * 10_000) // 2) // (DAYS_IN_YEAR * 10_000)
        start = end
    return total


def compensation_pence(gross_pence: int) -> int:
    """Fixed compensation per qualifying debt: GBP 40 (< 1,000), GBP 70 (1,000 to < 10,000), else GBP 100."""
    for threshold_pence, amount_pence in COMPENSATION:
        if gross_pence < threshold_pence:
            return amount_pence
    return COMPENSATION_TOP_PENCE
