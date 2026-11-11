"""Paying suppliers' bills through PayPal (Payouts v1) on their due date: the owner approves each payment, or turns on
bill-pay Autopilot with strict limits.

No database (docs/ARCHITECTURE.md), so everything lives in the user's own books, beside payments.json:

* `_System/Payments/billpay-payees.json` -- a supplier's PayPal email, **only ever typed or confirmed by the owner** in
  the app (`set_payee`). Never read from a bill, an invoice or an email: changed payment details on a bill are the
  classic bill fraud, so code never moves them into the payee. Each change is kept in `history`, and the date it was
  last confirmed is what Autopilot's "unchanged for N days" counts from.
* `_System/Payments/billpay-settings.json` -- per-bill plans ("Pay with PayPal on due date", or "not through PayPal")
  and the Autopilot settings: off by default, a global switch (and kill switch), and per-supplier rules.
* `_System/Payments/billpay-payouts.json` -- every payout tried, its PayPal ids and status, the payment details read
  from bills (code only, `details_in_text`), loud flags when they differ, and notices for the owner.

**The due queue** is worked out by code each time: bills approved in Review (so posted on account, Cr 2100 Creditors)
that are still owed (app/settlement.py, in pence), due today or earlier (the contact's terms, else 30 days:
contacts.due_date), whose supplier has a confirmed PayPal email, and which the owner has not marked "not through
PayPal". Nothing is paid by looking.

**Paying** (`pay`) re-reads what is owed, refuses an amount that is not exactly that, writes a claim for the payout
*before* calling PayPal (an ETag-guarded write, so two tabs cannot both claim it), then sends one payout. The
`sender_batch_id` is derived from the bill, the amount and the attempt number, so a retry after a lost answer is the
same id and PayPal pays it once (PayPal keeps sender_batch_ids for 30 days). A new attempt number is only used after
PayPal has said FAILED (or similar): money that never left. On SUCCESS code posts the payment through
app/payments.record_payment -- Dr 2100 Creditors / Cr 1240 PayPal clearing, the same clearing account the payment
links use (app/online_payments.py) -- and PayPal's payout fee, if it says one, as Dr 7900 Bank charges (exempt) /
Cr 1240. PENDING, ONHOLD and UNCLAIMED wait (unclaimed: PayPal holds it for 30 days for the recipient to sign up, then
returns it); FAILED, BLOCKED, RETURNED, DENIED and the like are shown with PayPal's reason and post nothing.

**Autopilot** has no scheduler of its own: writing to OneDrive needs the user's sign-in token, which only exists
while the app is open. So `run` is called when the app opens (Purchases), and a bill is paid the next time Accnomos is
open on or after its due date. Every rule must hold, else the bill waits for the owner with the reasons (`ask`):
see `autopilot_reasons`. Every automatic payment leaves an audit line (also in the Autopilot audit) and a notice.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
import uuid
from datetime import date, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app import contacts as cb
from app.ai.config import is_test_mode
from app.books import SYSTEM, Books, now
from app.books import today as london_today
from app.invoicing import InvoiceError, InvoiceStateError, money
from app.journal import CATEGORY_ACCOUNTS, PAYPAL_CLEARING
from app.payment_providers import PayPalApi, ProviderError, client, pence_from_payout

PAYEES = f"{SYSTEM}/Payments/billpay-payees.json"
SETTINGS = f"{SYSTEM}/Payments/billpay-settings.json"
PAYOUTS = f"{SYSTEM}/Payments/billpay-payouts.json"
FEES = CATEGORY_ACCOUNTS["Bank charges"]  # 7900 Bank charges
ACTOR = "agent:billpay-autopilot"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAX_DOCS_READ = 8  # bill files read for payment details per request (the rest on later visits)
DEFAULT_UNCHANGED_DAYS = 7
log = logging.getLogger(__name__)

Plan = Literal["paypal", "not_paypal"]
#: Our status for a payout: `sending` (claimed, PayPal's answer not yet kept), then PayPal's word for the item.
PayoutStatus = Literal["sending", "pending", "unclaimed", "paid", "failed", "unknown"]
WAITING: tuple[PayoutStatus, ...] = ("sending", "pending", "unclaimed", "unknown")
_PAYPAL_STATUS: dict[str, PayoutStatus] = {
    "SUCCESS": "paid",
    "PENDING": "pending",
    "ONHOLD": "pending",
    "UNCLAIMED": "unclaimed",
    "FAILED": "failed",
    "BLOCKED": "failed",
    "RETURNED": "failed",
    "REFUNDED": "failed",
    "REVERSED": "failed",
}


class BillPayError(InvoiceError):
    """Cannot pay or set this up as asked (a 400)."""


class AutopilotDeclined(BillPayError):
    """A rule does not hold for this bill: it waits for the owner."""

    def __init__(self, bill: Bill) -> None:
        super().__init__(bill.autopilot[0])
        self.bill = bill


class NotConnected(BillPayError):
    """PayPal is not set up on this server, or not linked to these books (a 503 / 400)."""


# --------------------------------------------------------------------------- #
# What is stored
# --------------------------------------------------------------------------- #


class PayeeChange(BaseModel):
    paypal_email: str | None
    bank: str | None = None
    at: datetime
    by: str


class Payee(BaseModel):
    """A supplier's payment details as the OWNER typed or confirmed them. Nothing else ever writes here."""

    contact_id: str
    name: str
    paypal_email: str
    bank: str | None = None  # "12-34-56 12345678" or "IBAN GB…", typed by the owner, to compare bills against
    confirmed_at: datetime
    confirmed_by: str
    history: list[PayeeChange] = []


class BillPlanRow(BaseModel):
    plan: Plan
    set_at: datetime
    set_by: str


class SupplierRule(BaseModel):
    contact_id: str
    enabled: bool = True
    max_per_bill_pence: int = Field(gt=0, le=10_000_000)  # £100,000 at most
    monthly_cap_pence: int = Field(gt=0, le=100_000_000)
    min_days_unchanged: int = Field(default=DEFAULT_UNCHANGED_DAYS, ge=0, le=365)
    # Only bills a person approved in Review: not ones Autopilot (L1) or a repeating schedule approved by itself.
    only_person_approved: bool = True


class AutopilotSettings(BaseModel):
    enabled: bool = False
    rules: list[SupplierRule] = []
    changed_at: datetime | None = None
    changed_by: str | None = None
    stopped_at: datetime | None = None  # the kill switch was pressed (enabled is then False)


class Settings(BaseModel):
    plans: dict[str, BillPlanRow] = {}  # bill event id -> plan
    autopilot: AutopilotSettings = AutopilotSettings()


class Payout(BaseModel):
    id: str  # = sender_batch_id
    event_id: str  # the bill
    contact_id: str
    supplier: str
    reference: str | None = None
    amount_pence: int
    receiver: str
    attempt: int = 1
    via: Literal["owner", "autopilot"]
    approved_by: str
    status: PayoutStatus = "sending"
    paypal_status: str | None = None  # PayPal's own word (transaction_status, or batch_status before items exist)
    detail: str | None = None  # PayPal's reason, or what went wrong
    batch_id: str | None = None
    item_id: str | None = None
    transaction_id: str | None = None
    fee_pence: int | None = None
    payment_id: str | None = None  # app/payments.py record, once posted
    fee_event_id: str | None = None
    problem: str | None = None  # paid at PayPal but could not be posted: the owner must look
    created_at: datetime
    updated_at: datetime


class SeenDetails(BaseModel):
    """Payment details printed on a bill, found by code (`details_in_text`). Only ever compared, never paid to."""

    event_id: str
    contact_id: str
    paypal_emails: list[str] = []
    bank: list[str] = []
    source: str  # "document" (the filed PDF/text) or what the caller said
    read_at: datetime
    unreadable: bool = False  # a photo has no text layer: nothing could be checked


class Flag(BaseModel):
    id: str
    contact_id: str
    supplier: str
    event_id: str
    reason: str
    at: datetime
    cleared_at: datetime | None = None
    cleared_by: str | None = None


class Notice(BaseModel):
    id: str
    at: datetime
    text: str
    kind: Literal["paid", "asked", "flag", "problem"]
    seen: bool = False


class Ledgerish(BaseModel):
    payouts: list[Payout] = []
    seen: dict[str, SeenDetails] = {}
    flags: list[Flag] = []
    notices: list[Notice] = []


def _load(model: type[Any], raw: Any) -> Any:
    try:
        return model.model_validate(raw or {})
    except ValueError:  # a hand-broken file: start empty rather than refuse every page
        log.warning("billpay: %s did not read; treated as empty", model.__name__)
        return model()


async def load_payees(books: Books) -> dict[str, Payee]:
    raw = await books.read_json(PAYEES, {})
    out: dict[str, Payee] = {}
    for cid, row in (raw if isinstance(raw, dict) else {}).items():
        with contextlib.suppress(ValueError, TypeError):
            out[cid] = Payee.model_validate(row)
    return out


async def load_settings(books: Books) -> Settings:
    return cast(Settings, _load(Settings, await books.read_json(SETTINGS, {})))


async def load_state(books: Books) -> Ledgerish:
    return cast(Ledgerish, _load(Ledgerish, await books.read_json(PAYOUTS, {})))


async def _update_state(books: Books, change: Any) -> Ledgerish:
    """Read-modify-write billpay-payouts.json (ETag-guarded); `change(state)` mutates it and may raise to refuse."""
    out: list[Ledgerish] = []

    def apply(raw: Any) -> Any:
        st = cast(Ledgerish, _load(Ledgerish, raw))
        change(st)
        out.append(st)
        return st.model_dump(mode="json")

    await books._update_json(PAYOUTS, {}, apply)
    return out[-1]


async def _update_settings(books: Books, change: Any) -> Settings:
    out: list[Settings] = []

    def apply(raw: Any) -> Any:
        st = cast(Settings, _load(Settings, raw))
        change(st)
        out.append(st)
        return st.model_dump(mode="json")

    await books._update_json(SETTINGS, {}, apply)
    return out[-1]


def _notice(st: Ledgerish, kind: Any, text: str) -> None:
    st.notices = [*st.notices, Notice(id=uuid.uuid4().hex[:12], at=now(), text=text, kind=kind)][-50:]


# --------------------------------------------------------------------------- #
# Payment details on a bill (code only; compared, never used to pay)
# --------------------------------------------------------------------------- #

_SORT = re.compile(r"\b(\d{2})[- ]?(\d{2})[- ]?(\d{2})\b")
_ACCOUNT = re.compile(r"(?<![\d-])(\d{8})(?![\d-])")
_IBAN = re.compile(r"\bGB\s?\d{2}\s?[A-Z]{4}(?:\s?\d){14}\b")


def normalise_email(v: str) -> str:
    return v.strip().lower()


def details_in_text(text: str) -> tuple[list[str], list[str]]:
    """(PayPal emails, bank details) printed on a bill. An email counts only on a line that says PayPal (or the line
    after one), so the supplier's ordinary contact address is not taken for a payment address. Bank details are a
    sort code on a line that says "sort" with an 8-digit account number on it or the next two lines, or a UK IBAN."""
    lines = text.splitlines()
    emails: list[str] = []
    bank: list[str] = []
    for i, line in enumerate(lines):
        low = line.lower()
        if "paypal" in low:
            for cand in EMAIL_RE.findall(" ".join(lines[i : i + 2])):
                e = normalise_email(cand)
                if e not in emails:
                    emails.append(e)
        if "sort" in low and (m := _SORT.search(line.split(":", 1)[-1] if ":" in line else line)):
            near = " ".join(lines[i : i + 3])
            acct = _ACCOUNT.search(near.replace(m.group(0), " "))
            if acct:
                v = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {acct.group(1)}"
                if v not in bank:
                    bank.append(v)
    for m in _IBAN.finditer(text.upper()):
        v = "IBAN " + re.sub(r"\s", "", m.group(0))
        if v not in bank:
            bank.append(v)
    return emails, bank


def normalise_bank(v: str | None) -> str | None:
    """The owner's typed bank details in the form `details_in_text` gives; None for blank. Raises BillPayError."""
    if not v or not v.strip():
        return None
    s = v.strip().upper()
    if s.replace(" ", "").startswith("GB") and (m := _IBAN.search(s)):
        return "IBAN " + re.sub(r"\s", "", m.group(0))
    digits = re.sub(r"\D", "", s)
    if len(digits) == 14:
        return f"{digits[0:2]}-{digits[2:4]}-{digits[4:6]} {digits[6:]}"
    raise BillPayError("Bank details are a sort code and an 8-digit account number, or a UK IBAN")


def changed_details(seen: SeenDetails, payee: Payee | None, earlier: list[SeenDetails]) -> list[str]:
    """Why the details on this bill are not the ones the owner saved (or that this supplier's earlier bills showed)."""
    out: list[str] = []
    if payee:
        other = [e for e in seen.paypal_emails if e != normalise_email(payee.paypal_email)]
        if other:
            out.append(
                f"The bill asks for payment by PayPal to {', '.join(other)}, not {payee.paypal_email} as you saved"
            )
        if payee.bank and seen.bank and payee.bank not in seen.bank:
            out.append(f"The bill shows bank details {', '.join(seen.bank)}, not {payee.bank} as you saved")
    if seen.bank and not (payee and payee.bank):
        before = {b for e in earlier for b in e.bank}
        if before and not set(seen.bank) & before:
            out.append(
                f"The bill shows bank details {', '.join(seen.bank)}; earlier bills from this supplier showed "
                f"{', '.join(sorted(before))}"
            )
    return out


async def _document_text(books: Books, event: LedgerEvent, ledger: cb.Ledger) -> tuple[str | None, str]:
    """(the filed bill's own text, where it came from). "document": a PDF text layer or a text file. "no document":
    a bill written by code (an order converted, a repeating bill) or posted by hand, so nothing printed to compare.
    "photo": a document with no text code can read (None text: it could not be checked)."""
    from app import formats

    p = ledger.proposals.get(event.proposal_id or "")
    if p is None or not p.file_path:
        return "", "no document"
    try:
        data = await books.storage.read(p.file_path)
        hint = formats.TEXT_MIME if p.file_path.lower().endswith(".txt") else p.file_path  # an email body, .eml.txt
        prepared = await asyncio.to_thread(formats.prepare, data, hint)
    except (FileNotFoundError, formats.FormatError, OSError, ValueError):
        return None, "photo"
    texts = prepared.page_texts or ([prepared.text] if prepared.text else [])
    text = "\n".join(t for t in texts if t)
    return (text, "document") if text.strip() else (None, "photo")


async def record_seen(
    books: Books,
    event_id: str,
    contact_id: str,
    supplier: str,
    text: str | None,
    source: str,
    payee: Payee | None,
    actor: str,
) -> tuple[SeenDetails, list[str]]:
    """Keep what the bill shows; raise a loud flag (blocking Autopilot for the supplier) when it differs."""
    emails, bank = details_in_text(text or "")
    seen = SeenDetails(
        event_id=event_id,
        contact_id=contact_id,
        paypal_emails=emails,
        bank=bank,
        source=source,
        read_at=now(),
        unreadable=text is None,
    )
    reasons: list[str] = []

    def change(st: Ledgerish) -> None:
        earlier = [s for s in st.seen.values() if s.contact_id == contact_id and s.event_id != event_id]
        reasons.extend(changed_details(seen, payee, earlier))
        st.seen[event_id] = seen
        if reasons and not any(f.event_id == event_id and f.cleared_at is None for f in st.flags):
            st.flags.append(
                Flag(
                    id=uuid.uuid4().hex[:12],
                    contact_id=contact_id,
                    supplier=supplier,
                    event_id=event_id,
                    reason="; ".join(reasons),
                    at=now(),
                )
            )
            _notice(
                st,
                "flag",
                f"Payment details on a bill from {supplier} differ from the ones you saved. Automatic payments to "
                f"{supplier} are stopped until you check them with the supplier (by phone, from a number you already "
                "had).",
            )

    await _update_state(books, change)
    if reasons:
        await books.audit(
            actor, "billpay_details_changed", {"bill": event_id, "contact": contact_id, "reasons": reasons}
        )
    return seen, reasons


# --------------------------------------------------------------------------- #
# Payees: typed or confirmed by the owner, nothing else
# --------------------------------------------------------------------------- #


async def set_payee(books: Books, contact_id: str, paypal_email: str, bank: str | None, user: str) -> Payee:
    """The owner's PayPal email (and optionally bank details) for a supplier, typed or confirmed in the app."""
    email = normalise_email(paypal_email)
    if not EMAIL_RE.fullmatch(email) or len(email) > 127:  # Payouts: receiver up to 127 characters
        raise BillPayError(f"{paypal_email} doesn't look like an email address")
    bank_n = normalise_bank(bank)
    contacts, _ledger, _ = await cb.contact_book(books)
    c = next((c for c in contacts if c.id == contact_id), None)
    if c is None:
        raise FileNotFoundError(contact_id)
    at = now()
    out: list[Payee] = []

    def change(raw: Any) -> Any:
        cur = dict(raw) if isinstance(raw, dict) else {}
        old = None
        with contextlib.suppress(ValueError, TypeError):
            old = Payee.model_validate(cur[contact_id]) if contact_id in cur else None
        history = [*(old.history if old else []), PayeeChange(paypal_email=email, bank=bank_n, at=at, by=user)]
        p = Payee(
            contact_id=contact_id,
            name=c.name,
            paypal_email=email,
            bank=bank_n,
            confirmed_at=at,
            confirmed_by=user,
            history=history[-20:],
        )
        cur[contact_id] = p.model_dump(mode="json")
        out.append(p)
        return cur

    await books._update_json(PAYEES, {}, change)
    await books.audit(
        f"user:{user}",
        "billpay_payee_set",
        {"contact": contact_id, "supplier": c.name, "paypal_email": email, "bank_set": bank_n is not None},
    )
    return out[-1]


async def remove_payee(books: Books, contact_id: str, user: str) -> None:
    def change(raw: Any) -> Any:
        cur = dict(raw) if isinstance(raw, dict) else {}
        if contact_id not in cur:
            raise FileNotFoundError(contact_id)
        cur.pop(contact_id)
        return cur

    await books._update_json(PAYEES, {}, change)
    await books.audit(f"user:{user}", "billpay_payee_removed", {"contact": contact_id})


async def clear_flag(books: Books, flag_id: str, user: str) -> Flag:
    """The owner checked the details with the supplier: lift the block. Autopilot still waits N days after any
    change of the saved PayPal email."""
    done: list[Flag] = []

    def change(st: Ledgerish) -> None:
        f = next((f for f in st.flags if f.id == flag_id and f.cleared_at is None), None)
        if f is None:
            raise FileNotFoundError(flag_id)
        f.cleared_at, f.cleared_by = now(), user
        done.append(f)

    await _update_state(books, change)
    f = done[-1]
    await books.audit(
        f"user:{user}", "billpay_flag_cleared", {"flag": f.id, "contact": f.contact_id, "bill": f.event_id}
    )
    return f


async def set_plan(books: Books, event_id: str, plan: Plan | None, user: str) -> Plan | None:
    def change(st: Settings) -> None:
        if plan is None:
            st.plans.pop(event_id, None)
        else:
            st.plans[event_id] = BillPlanRow(plan=plan, set_at=now(), set_by=user)

    await _update_settings(books, change)
    await books.audit(f"user:{user}", "billpay_plan_set", {"bill": event_id, "plan": plan})
    return plan


async def save_autopilot(books: Books, enabled: bool, rules: list[SupplierRule], user: str) -> AutopilotSettings:
    if len({r.contact_id for r in rules}) != len(rules):
        raise BillPayError("One rule per supplier")
    for r in rules:
        if r.max_per_bill_pence > r.monthly_cap_pence:
            raise BillPayError("A supplier's limit per bill cannot be more than its monthly cap")

    def change(st: Settings) -> None:
        st.autopilot = AutopilotSettings(
            enabled=enabled,
            rules=rules,
            changed_at=now(),
            changed_by=user,
            stopped_at=None if enabled else st.autopilot.stopped_at,
        )

    st = await _update_settings(books, change)
    await books.audit(
        f"user:{user}",
        "billpay_autopilot_settings",
        {"enabled": enabled, "rules": [r.model_dump(mode="json") for r in rules]},
    )
    return st.autopilot


async def stop_autopilot(books: Books, user: str) -> AutopilotSettings:
    """The kill switch: nothing is paid automatically until the owner turns it on again. Rules are kept."""

    def change(st: Settings) -> None:
        st.autopilot.enabled = False
        st.autopilot.stopped_at = st.autopilot.changed_at = now()
        st.autopilot.changed_by = user

    st = await _update_settings(books, change)
    await books.audit(f"user:{user}", "billpay_autopilot_stopped", {})
    await books.audit_autopilot(f"user:{user}", "billpay_autopilot_stopped", {})
    return st.autopilot


def server_kill_switch() -> bool:
    """`BILLPAY_AUTOPILOT_OFF=1` on the server stops every automatic bill payment for every user."""
    return os.getenv("BILLPAY_AUTOPILOT_OFF", "").strip() == "1"


# --------------------------------------------------------------------------- #
# The bills: what is owed, when it is due, and whether it can be paid
# --------------------------------------------------------------------------- #


class Bill(BaseModel):
    event_id: str
    contact_id: str
    supplier: str
    reference: str | None
    bill_date: date
    due_date: date
    days_overdue: int  # negative: not due yet
    gross_pence: int
    owed_pence: int
    approved_by: str
    person_approved: bool
    plan: Plan | None = None
    payee_email: str | None = None
    payee_confirmed_at: datetime | None = None
    due_now: bool  # due today or earlier
    can_pay: bool  # the owner can approve a payout now
    blocks: list[str] = []  # why it cannot be paid now
    warnings: list[str] = []  # shown loudly; `changed_details` must be acknowledged to pay
    changed_details: list[str] = []
    details_checked: Literal["checked", "nothing to check", "unreadable", "not yet"] = "not yet"
    autopilot: list[str] = []  # why Autopilot would not pay it (empty: it would)
    payout: Payout | None = None  # the latest payout for this bill


class Overview(BaseModel):
    today: date
    available: bool  # this server can send payouts
    reason: str | None = None
    connected: bool  # PayPal linked to these books
    test_mode: bool
    clearing_pence: int  # what 1240 PayPal clearing holds by the books
    due: list[Bill]  # due today or earlier, PayPal planned (not "not through PayPal")
    upcoming: list[Bill]  # every other open bill, soonest first
    payees: list[Payee]
    payouts: list[Payout]  # newest first
    flags: list[Flag]  # open ones
    notices: list[Notice]  # not yet seen
    autopilot: AutopilotSettings
    autopilot_note: str


AUTOPILOT_NOTE = (
    "Accnomos has no server that can write to your books while you are away: it needs your sign-in. So an automatic "
    "payment is made the next time Accnomos is open on or after the bill's due date, never before."
)


def person_approved(approved_by: str) -> bool:
    return approved_by != "autopilot" and not approved_by.startswith("repeating:")


def sender_batch_id(event_id: str, amount_pence: int, attempt: int) -> str:
    """Deterministic per bill, amount and attempt: a retry is the same id, which PayPal pays once (30 days)."""
    return "acc-" + hashlib.sha256(f"billpay:{event_id}:{amount_pence}:{attempt}".encode()).hexdigest()[:28]


def _paypal() -> tuple[Any, str | None]:
    from app import online_payments as op

    return op.paypal_config()


def month_paid(payouts: list[Payout], contact_id: str, today: date) -> int:
    """Paid (or on its way) by Autopilot to this supplier in the London month of `today`."""
    return sum(
        p.amount_pence
        for p in payouts
        if p.contact_id == contact_id
        and p.via == "autopilot"
        and p.status in ("sending", "pending", "unclaimed", "paid", "unknown")
        and p.created_at.date().replace(day=1) == today.replace(day=1)
    )


def autopilot_reasons(
    bill: Bill,
    settings: AutopilotSettings,
    payee: Payee | None,
    flags: list[Flag],
    payouts: list[Payout],
    clearing_pence: int,
    today: date,
) -> list[str]:
    """Every reason Autopilot would NOT pay this bill now; empty means every rule holds."""
    out: list[str] = []
    if server_kill_switch():
        out.append("Automatic bill payments are switched off on this server")
    if not settings.enabled:
        out.append("Bill-pay Autopilot is off" + (" (stopped with the kill switch)" if settings.stopped_at else ""))
    rule = next((r for r in settings.rules if r.contact_id == bill.contact_id), None)
    if rule is None or not rule.enabled:
        out.append(f"No Autopilot rule for {bill.supplier}")
    if bill.plan == "not_paypal":
        out.append("You marked this bill not to be paid through PayPal")
    if not bill.due_now:
        out.append(f"Not due until {bill.due_date:%d/%m/%Y}")
    if payee is None:
        out.append(f"No PayPal email saved for {bill.supplier}")
    elif rule is not None:
        since = (today - payee.confirmed_at.date()).days
        if since < rule.min_days_unchanged:
            out.append(
                f"The PayPal email was set or changed {since} day{'s' if since != 1 else ''} ago; the rule waits "
                f"{rule.min_days_unchanged}"
            )
    if any(f.contact_id == bill.contact_id and f.cleared_at is None for f in flags):
        out.append(f"Payment details on a bill from {bill.supplier} differ from the saved ones")
    if bill.details_checked == "not yet":
        out.append("The payment details printed on this bill have not been checked yet")
    elif bill.details_checked == "unreadable":
        out.append("This bill is a photo, so code could not check the payment details printed on it")
    if rule is not None and rule.only_person_approved and not bill.person_approved:
        out.append("The bill was approved automatically, not by a person")
    if rule is not None:
        if bill.owed_pence > rule.max_per_bill_pence:
            out.append(f"{money(bill.owed_pence)} is over the limit of {money(rule.max_per_bill_pence)} per bill")
        spent = month_paid(payouts, bill.contact_id, today)
        if spent + bill.owed_pence > rule.monthly_cap_pence:
            out.append(
                f"{money(spent)} already paid this month; this would pass the monthly cap of "
                f"{money(rule.monthly_cap_pence)}"
            )
    if bill.owed_pence > clearing_pence:
        out.append(f"1240 PayPal clearing holds {money(max(clearing_pence, 0))} by your books, less than the bill")
    mine = [p for p in payouts if p.event_id == bill.event_id]
    if any(p.status in WAITING or p.status == "paid" for p in mine):
        out.append("A payout for this bill is already on its way")
    elif any(p.status == "failed" for p in mine):
        out.append("An earlier payout for this bill failed; you decide whether to try again")
    out += [b for b in bill.blocks if b not in out and "on its way" not in b]
    return out


async def bills(books: Books, *, today: date | None = None, read_documents: bool = True) -> Overview:
    """The due queue, the other open bills and everything the panels show. Reads bill files for payment details
    (at most MAX_DOCS_READ new ones per call), which may write a flag; pays nothing."""
    from app import online_payments as op

    today = today or london_today()
    contacts, ledger, _ = await cb.contact_book(books)
    by_id = {c.id: c for c in contacts}
    payees = await load_payees(books)
    settings = await load_settings(books)
    st = await load_state(books)
    cfg, why = _paypal()
    conns = await op.load_connections(books)
    connected = conns.paypal is not None
    clearing = await op.clearing_balance(books, "paypal")
    raw: list[tuple[cb.Doc, str]] = []
    for cid, docs in cb.assign(contacts, cb.documents(ledger)).items():
        for d in cb.open_docs(docs, ledger):
            if d.side == "purchase" and d.kind == "invoice" and not d.undo and d.on_account:
                raw.append((d, cid))
    # Payment details printed on bills not read yet (suppliers with a saved PayPal email first, oldest first).
    if read_documents:
        todo = [
            (d, cid)
            for d, cid in sorted(raw, key=lambda x: (x[1] not in payees, x[0].event.date))
            if d.event.id not in st.seen and not d.opening
        ][:MAX_DOCS_READ]
        for d, cid in todo:
            text, source = await _document_text(books, d.event, ledger)
            await record_seen(books, d.event.id, cid, d.name, text, source, payees.get(cid), "agent:billpay")
        if todo:
            st = await load_state(books)
    open_flags = [f for f in st.flags if f.cleared_at is None]
    out: list[Bill] = []
    for d, cid in raw:
        c = by_id[cid]
        owed = cb.outstanding(d, ledger)
        due = cb.due_date(d, c)
        payee = payees.get(cid)
        plan_row = settings.plans.get(d.event.id)
        mine = sorted((p for p in st.payouts if p.event_id == d.event.id), key=lambda p: p.created_at)
        latest = mine[-1] if mine else None
        seen = st.seen.get(d.event.id)
        changed = [f.reason for f in open_flags if f.event_id == d.event.id]
        blocks: list[str] = []
        warnings: list[str] = []
        if cfg is None:
            blocks.append(why or "PayPal is not set up on this server")
        elif not connected:
            blocks.append("Connect PayPal in Settings › Online payments first")
        if payee is None:
            blocks.append(f"Add {c.name}'s PayPal email first (you type it; it is never read from a bill)")
        if latest and latest.status in WAITING:
            blocks.append("A payout for this bill is already on its way")
        if latest and latest.status == "paid":
            blocks.append("Paid through PayPal; the payment is in your books")
        if changed:
            warnings += changed
        elif any(f.contact_id == cid for f in open_flags):
            warnings.append(f"Another bill from {c.name} shows payment details that differ from the saved ones")
        if seen and seen.unreadable:
            warnings.append("This bill is a photo: code could not read payment details from it to compare")
        if owed > clearing:
            warnings.append(
                f"1240 PayPal clearing holds {money(max(clearing, 0))} by your books, less than {money(owed)}. "
                "PayPal pays from your PayPal balance (or its linked funding); check it has the money"
            )
        if not person_approved(d.event.approved_by):
            warnings.append("This bill was approved automatically, not by a person")
        bill = Bill(
            event_id=d.event.id,
            contact_id=cid,
            supplier=c.name,
            reference=d.reference,
            bill_date=d.event.date,
            due_date=due,
            days_overdue=(today - due).days,
            gross_pence=d.gross,
            owed_pence=owed,
            approved_by=d.event.approved_by,
            person_approved=person_approved(d.event.approved_by),
            plan=plan_row.plan if plan_row else None,
            payee_email=payee.paypal_email if payee else None,
            payee_confirmed_at=payee.confirmed_at if payee else None,
            due_now=due <= today,
            can_pay=not blocks,
            blocks=blocks,
            warnings=warnings,
            changed_details=changed,
            details_checked=(
                "not yet"
                if seen is None
                else "unreadable"
                if seen.unreadable
                else "nothing to check"
                if seen.source == "no document"
                else "checked"
            ),
            payout=latest,
        )
        bill.autopilot = autopilot_reasons(bill, settings.autopilot, payee, open_flags, st.payouts, clearing, today)
        out.append(bill)
    out.sort(key=lambda b: (b.due_date, b.supplier.lower()))
    due_list = [b for b in out if b.due_now and b.plan != "not_paypal" and (b.payee_email or b.plan == "paypal")]
    due_ids = {b.event_id for b in due_list}
    return Overview(
        today=today,
        available=cfg is not None,
        reason=why,
        connected=connected,
        test_mode=bool(cfg.test_mode) if cfg else True,
        clearing_pence=clearing,
        due=due_list,
        upcoming=[b for b in out if b.event_id not in due_ids],
        payees=sorted(payees.values(), key=lambda p: p.name.lower()),
        payouts=sorted(st.payouts, key=lambda p: p.created_at, reverse=True)[:50],
        flags=open_flags,
        notices=[n for n in st.notices if not n.seen],
        autopilot=settings.autopilot,
        autopilot_note=AUTOPILOT_NOTE,
    )


# --------------------------------------------------------------------------- #
# Paying, and following a payout until PayPal says how it ended
# --------------------------------------------------------------------------- #


def _api_parts() -> tuple[Any, Any]:
    cfg, why = _paypal()
    if cfg is None:
        raise NotConnected(why or "PayPal is not set up on this server")
    return cfg, why


async def _merchant(books: Books) -> str:
    from app import online_payments as op

    c = await op.load_connections(books)
    if c.paypal is None:
        raise NotConnected("Connect PayPal in Settings › Online payments first")
    return c.paypal.merchant_id


async def pay(
    books: Books,
    event_id: str,
    amount_pence: int,
    user: str,
    *,
    via: Literal["owner", "autopilot"] = "owner",
    acknowledge_changed_details: bool = False,
    today: date | None = None,
) -> Payout:
    """Send one payout for what is owed on the bill. `amount_pence` must be what code says is owed now (the card
    showed it; anything else means the bill changed). Refuses a second payout while one is on its way or paid."""
    today = today or london_today()
    ov = await bills(books, today=today, read_documents=False)
    bill = next((b for b in [*ov.due, *ov.upcoming] if b.event_id == event_id), None)
    if bill is None:
        raise InvoiceStateError("No unpaid bill on account with that id (it may be paid or undone)")
    if amount_pence != bill.owed_pence:
        raise InvoiceStateError(
            f"{money(bill.owed_pence)} is owed on this bill now, not {money(amount_pence)}; look again before paying"
        )
    if bill.blocks:
        raise InvoiceStateError(bill.blocks[0])
    if via == "owner" and bill.changed_details and not acknowledge_changed_details:
        raise BillPayError(
            "The payment details on this bill differ from the ones you saved. Check with the supplier, then confirm"
        )
    if via == "autopilot" and bill.autopilot:
        raise AutopilotDeclined(bill)
    payees = await load_payees(books)
    payee = payees.get(bill.contact_id)
    assert payee is not None  # blocks covered it
    cfg, _ = _api_parts()
    merchant = await _merchant(books)
    claimed: list[Payout] = []

    def claim(st: Ledgerish) -> None:
        mine = [p for p in st.payouts if p.event_id == event_id]
        if any(p.status in WAITING or p.status == "paid" for p in mine):
            raise InvoiceStateError("A payout for this bill is already on its way")
        attempt = 1 + len([p for p in mine if p.amount_pence == amount_pence])
        sid = sender_batch_id(event_id, amount_pence, attempt)
        at = now()
        p = Payout(
            id=sid,
            event_id=event_id,
            contact_id=bill.contact_id,
            supplier=bill.supplier,
            reference=bill.reference,
            amount_pence=amount_pence,
            receiver=payee.paypal_email,
            attempt=attempt,
            via=via,
            approved_by=user,
            created_at=at,
            updated_at=at,
        )
        st.payouts.append(p)
        claimed.append(p)

    await _update_state(books, claim)
    p = claimed[-1]
    actor = ACTOR if via == "autopilot" else f"user:{user}"
    refs = {
        "bill": event_id,
        "payout": p.id,
        "supplier": bill.supplier,
        "receiver": p.receiver,
        "amount_pence": amount_pence,
        "via": via,
        "attempt": p.attempt,
        "acknowledged_changed_details": bool(bill.changed_details and acknowledge_changed_details),
    }
    await books.audit(actor, "billpay_payout_approved", refs)
    if via == "autopilot":
        await books.audit_autopilot(actor, "billpay_payout_approved", refs)
    return await _send(books, p, cfg, merchant, actor)


async def _send(books: Books, p: Payout, cfg: Any, merchant: str, actor: str) -> Payout:
    """POST the payout (same sender_batch_id every time for this claim), keep PayPal's answer, then read its status."""
    what = f"Bill {p.reference}" if p.reference else "Bill"
    note = f"{what} from {p.supplier}, paid by Accnomos"
    try:
        async with client() as http:
            answer = await PayPalApi(cfg, http).create_payout(
                merchant,
                sender_batch_id=p.id,
                receiver=p.receiver,
                amount_pence=p.amount_pence,
                note=note,
                sender_item_id=(p.reference or p.event_id)[:40] + f"-{p.attempt}",
                email_subject=f"Payment for {what.lower()}",
            )
    except ProviderError as exc:
        # 5xx or no answer: PayPal may or may not have it; the same sender_batch_id is safe to send again.
        # 4xx: refused (nothing was paid); the owner can try again after fixing the cause.
        unsure = exc.status == 0 or exc.status >= 500
        return await _set(
            books,
            p.id,
            actor,
            status="unknown" if unsure else "failed",
            detail=(
                f"PayPal did not answer ({exc.message}); Accnomos will ask again with the same payout id, which "
                "PayPal pays once"
                if unsure
                else f"PayPal refused it: {exc.message}"
            ),
        )
    header = answer.get("batch_header") or {}
    batch = str(header.get("payout_batch_id") or "") or None
    p = await _set(books, p.id, actor, status="pending", batch_id=batch, paypal_status=header.get("batch_status"))
    return await refresh_one(books, p, cfg=cfg, merchant=merchant, actor=actor)


async def _set(books: Books, pid: str, actor: str, **fields: Any) -> Payout:
    out: list[Payout] = []
    before: list[str] = []

    def change(st: Ledgerish) -> None:
        p = next(x for x in st.payouts if x.id == pid)
        before.append(p.status)
        for k, v in fields.items():
            setattr(p, k, v)
        p.updated_at = now()
        out.append(p)

    await _update_state(books, change)
    p = out[-1]
    if before and before[-1] != p.status:
        await books.audit(
            actor,
            "billpay_payout_status",
            {
                "payout": p.id,
                "bill": p.event_id,
                "status": p.status,
                "paypal_status": p.paypal_status,
                "detail": p.detail,
            },
        )
    return p


def _item_reading(batch: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """(PayPal's word, the one item) from GET /v1/payments/payouts/{id}; before items exist, the batch status."""
    header = batch.get("batch_header") or {}
    items = [i for i in batch.get("items") or [] if isinstance(i, dict)]
    item = items[0] if items else None
    if item and item.get("transaction_status"):
        return str(item["transaction_status"]), item
    status = str(header.get("batch_status") or "") or None
    return status, item


async def refresh_one(
    books: Books, p: Payout, *, cfg: Any = None, merchant: str | None = None, actor: str = "agent:billpay"
) -> Payout:
    """Ask PayPal how a payout stands; on SUCCESS post it (once). Re-sends a payout whose first answer was lost."""
    if p.status not in WAITING:
        return p
    if cfg is None:
        cfg, _ = _api_parts()
    merchant = merchant or await _merchant(books)
    if p.batch_id is None:
        return await _send(books, p, cfg, merchant, actor)
    try:
        async with client() as http:
            batch = await PayPalApi(cfg, http).payout_batch(merchant, p.batch_id)
    except ProviderError as exc:
        return await _set(books, p.id, actor, detail=f"PayPal could not be asked just now ({exc.message})")
    word, item = _item_reading(batch)
    fields: dict[str, Any] = {"paypal_status": word}
    if item:
        fields["item_id"] = item.get("payout_item_id") or p.item_id
        fields["transaction_id"] = item.get("transaction_id") or p.transaction_id
        fee = pence_from_payout(item.get("payout_item_fee"))
        if fee is not None:
            fields["fee_pence"] = fee
    if word in _PAYPAL_STATUS:
        status = _PAYPAL_STATUS[word]
    elif word in ("DENIED", "CANCELED"):
        status = "failed"
    else:  # PENDING / PROCESSING batch with no item status yet
        status = "pending"
    if status == "failed":
        err = (item or {}).get("errors") or {}
        reason = err.get("message") or err.get("name") or word
        fields["detail"] = f"PayPal says {word}: {reason}. Nothing was posted"
    elif status == "unclaimed":
        fields["detail"] = (
            f"{p.receiver} has no PayPal account yet. PayPal holds the money for 30 days for them to claim it, "
            "then returns it to you. Nothing is posted until they do"
        )
    elif status == "pending":
        fields["detail"] = "PayPal is processing it"
    else:
        fields["detail"] = None
    fields["status"] = status
    p = await _set(books, p.id, actor, **fields)
    if status == "paid":
        p = await post_paid(books, p, actor)
    return p


async def post_paid(books: Books, p: Payout, actor: str) -> Payout:
    """Post a successful payout once: Dr 2100 Creditors / Cr 1240 PayPal clearing (app/payments.record_payment),
    and PayPal's fee as Dr 7900 Bank charges (exempt) / Cr 1240."""
    from app import payments

    if p.payment_id:
        return p
    reference = f"PayPal payout {p.item_id or p.batch_id or p.id}"[:120]
    user = p.approved_by if p.via == "owner" else "autopilot"
    already = [r for r in await payments._records(books) if r.reference == reference and r.removed_at is None]
    try:
        if already:
            record_id = already[0].id
        else:
            body = payments.PaymentIn(
                side="purchase",
                date=london_today(),
                amount_pence=p.amount_pence,
                account=cast(payments.PaymentAccount, PAYPAL_CLEARING),
                reference=reference,
                allocations=[payments.AllocationIn(event_id=p.event_id, amount_pence=p.amount_pence)],
                bank_line_id=None,
            )
            record_id = (await payments.record_payment(books, body, user)).id
    except InvoiceError as exc:
        problem = (
            f"PayPal paid {money(p.amount_pence)} to {p.receiver}, but it could not be posted: {exc}. Record the "
            "payment by hand (from 1240 PayPal clearing), or ask the supplier to refund it"
        )
        p = await _set(books, p.id, actor, problem=problem)

        def note(st: Ledgerish) -> None:
            _notice(st, "problem", problem)

        await _update_state(books, note)
        return p
    fee_id = None
    if p.fee_pence:
        ev = fee_event(p, user)
        with contextlib.suppress(FileExistsError):
            await books.post_event(ev)
        fee_id = ev.id
    p = await _set(books, p.id, actor, payment_id=record_id, fee_event_id=fee_id)
    refs = {
        "payout": p.id,
        "bill": p.event_id,
        "payment": record_id,
        "fee_event": fee_id,
        "amount_pence": p.amount_pence,
        "fee_pence": p.fee_pence,
        "via": p.via,
    }
    await books.audit(actor, "billpay_payout_posted", refs)
    if p.via == "autopilot":
        await books.audit_autopilot(actor, "billpay_payout_posted", refs)

        def note_paid(st: Ledgerish) -> None:
            _notice(
                st,
                "paid",
                f"Autopilot paid {money(p.amount_pence)} to {p.supplier} ({p.receiver}) through PayPal"
                + (f" for bill {p.reference}" if p.reference else "")
                + ". It is in your books.",
            )

        await _update_state(books, note_paid)
    with contextlib.suppress(Exception):
        await books.rebuild_safely(actor)
    return p


def fee_event(p: Payout, user: str) -> LedgerEvent:
    memo = f"PayPal payout fee, {p.supplier}" + (f" bill {p.reference}" if p.reference else "")
    fee = p.fee_pence or 0
    return LedgerEvent(
        id=hashlib.sha256(f"billpay-fee:{p.id}".encode()).hexdigest()[:32],
        kind="purchase",
        date=london_today(),
        lines=[
            Line(account=FEES, debit=fee, vat_code=VatCode.EXEMPT, memo=memo),
            Line(account=PAYPAL_CLEARING, credit=fee, memo=memo),
        ],
        approved_by=user,
        approved_at=now(),
        net=fee,
        vat=0,
        counterparty="PayPal",
    )


class RunResult(BaseModel):
    refreshed: list[Payout] = []
    paid: list[Payout] = []  # sent by Autopilot this run (see each one's status)
    asked: list[dict[str, Any]] = []  # due bills Autopilot left for the owner, with the reasons
    problems: list[str] = []


async def run(books: Books, *, today: date | None = None) -> RunResult:
    """When the app opens: follow every payout still waiting, then let Autopilot pay what every rule allows. A bill a
    rule does not cover is left for the owner with its reasons (audited once per bill and day)."""
    today = today or london_today()
    out = RunResult()
    cfg, _ = _paypal()
    st = await load_state(books)
    waiting = [p for p in st.payouts if p.status in WAITING]
    if waiting and cfg is not None:
        try:
            merchant = await _merchant(books)
        except NotConnected as exc:
            out.problems.append(str(exc))
        else:
            for p in waiting:
                try:
                    out.refreshed.append(await refresh_one(books, p, cfg=cfg, merchant=merchant))
                except InvoiceError as exc:
                    out.problems.append(f"{p.supplier}: {exc}")
    settings = await load_settings(books)
    if not settings.autopilot.enabled or server_kill_switch():
        return out
    ov = await bills(books, today=today)
    for b in ov.due:
        if not any(r.contact_id == b.contact_id for r in settings.autopilot.rules):
            continue
        if b.payout and b.payout.status in (*WAITING, "paid"):
            continue  # already on its way (followed above)
        try:
            if b.autopilot:
                raise AutopilotDeclined(b)
            # pay() works the bill out again, so an earlier payment this run counts towards the monthly cap.
            out.paid.append(await pay(books, b.event_id, b.owed_pence, "autopilot", via="autopilot", today=today))
        except AutopilotDeclined as exc:
            d = exc.bill
            out.asked.append(
                {"bill": d.event_id, "supplier": d.supplier, "owed_pence": d.owed_pence, "reasons": d.autopilot}
            )
            await _asked_once(books, d, today)
        except InvoiceError as exc:
            out.problems.append(f"{b.supplier}: {exc}")
    return out


async def _asked_once(books: Books, b: Bill, today: date) -> None:
    key = f"asked:{b.event_id}:{today.isoformat()}"
    fresh: list[bool] = []

    def change(st: Ledgerish) -> None:
        if any(n.id == key for n in st.notices):
            return
        st.notices = [
            *st.notices,
            Notice(
                id=key,
                at=now(),
                kind="asked",
                text=f"Autopilot did not pay {b.supplier} {money(b.owed_pence)}: {b.autopilot[0]}. It is waiting "
                "for you in Due today.",
            ),
        ][-50:]
        fresh.append(True)

    await _update_state(books, change)
    if fresh:
        refs = {"bill": b.event_id, "supplier": b.supplier, "owed_pence": b.owed_pence, "reasons": b.autopilot}
        await books.audit(ACTOR, "billpay_autopilot_asked", refs)
        await books.audit_autopilot(ACTOR, "billpay_autopilot_asked", refs)


async def mark_seen(books: Books, ids: list[str]) -> None:
    def change(st: Ledgerish) -> None:
        for n in st.notices:
            if n.id in ids:
                n.seen = True

    await _update_state(books, change)


def demo_allowed() -> bool:
    """A demo sandbox may send payouts only where nothing real can move: the fakes (test mode) or the server's own
    PayPal sandbox account (direct mode)."""
    from app import online_payments as op

    return is_test_mode() or op.direct_mode("paypal")
