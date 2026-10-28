"""Chat and voice actions: "send a £100 invoice to JM Trading for this month's work" -> a card -> approve -> done.

Who decides what (docs/ACTIONS.md):
  the model  turns the user's words into a structured intent (IntentModelOutput, strict JSON, enumerated kinds);
             it quotes amounts, hours, miles and dates exactly as said and never works anything out.
  code       parses those quotes (and refuses a figure the user did not say), finds the customer, job, staff
             member or vehicle by fuzzy match against the user's own lists (difflib >= 0.8, otherwise it asks),
             picks the VAT code, prices every line in pence, and builds the preview.
  the user   approves the card. Nothing is created, logged or sent before POST /actions/approve.

The proposal is not stored anywhere: the client keeps it and posts it back. It is signed with an HMAC whose key
is derived from the runtime's key and a hash of the caller's Graph token, so a changed amount, recipient or
expiry, or a proposal replayed from another sign-in, is refused. Approving writes an audit line first
(_System/audit/actions/<yyyy-mm>.jsonl, the month the action was proposed), so the same action id executes once.

If the runtime dies between that `approving` line and the result, the action is never run again on its own (the
first run may have emailed already). After APPROVING_STALE the user is told to check, and POST /actions/reject
with the same card clears it (a `rejected` line with `cleared: "stale approving"`); then they ask again.
"""

from __future__ import annotations

import calendar
import datetime as dt
import difflib
import hashlib
import hmac
import importlib
import json
import os
import re
import secrets
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app import contacts as contacts_
from app import jobs as jobs_
from app.ai import ask as ask_ai
from app.ai.config import AiConfig, is_test_mode
from app.ai.extract import ExtractionError, parse_model_json
from app.autopilot import supplier_key
from app.books import AUDIT, SYSTEM, Books, now
from app.books import today as london_today
from app.schemas import ActionKind, Clarification, ProposedAction, strict_json_schema

ACTIONS_AUDIT = f"{AUDIT}/actions"
VEHICLES = f"{SYSTEM}/Vehicles/vehicles.json"  # vehicles & mileage contract (app/mileage.py when it lands)
INVOICE_PROFILE = f"{SYSTEM}/Invoicing/profile.json"  # app/invoicing.py owns it; read-only here
TTL = timedelta(minutes=15)
APPROVING_STALE = timedelta(minutes=10)  # an `approving` line this old belongs to a run that died (see the docstring)
MATCH_AT = 0.8  # difflib ratio a name must reach to be picked without asking
NEAR_AT = 0.5  # shown as "did you mean" when nothing reaches MATCH_AT
CLEAR_LEAD = 0.1  # several reach MATCH_AT: the best is picked only this far ahead of the next, otherwise ask
DEFAULT_TERMS_DAYS = 30
RATES: dict[str, int] = {"S": 20, "R": 5, "Z": 0, "E": 0, "O": 0}  # same table as app/invoicing.py
VatCode = Literal["S", "R", "Z", "E", "O"]
IntentKind = Literal["create_invoice", "chase_invoice", "log_mileage", "log_timesheet", "add_to_shopping_list", "none"]

# Only questions that might be an instruction cost a second model call.
_ACTION_WORDS = re.compile(
    r"\b(invoice|bill|send|chase|remind|reminder|log|record|add|book|miles?|mileage|drove|driven|hours?|timesheet|"
    r"shopping|buy|order|remember)\b",
    re.I,
)
_QUESTION_START = re.compile(
    r"^\s*(how|what|why|which|who|whose|when|where|did|was|were|is|are|does|do|have|has)\b", re.I
)


class ActionError(ValueError):
    """The action cannot be approved as posted (bad signature, expired, changed since it was proposed)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# What the model returns
# --------------------------------------------------------------------------- #

INTENT_PROMPT = (
    "You turn a UK small business owner's instruction into JSON for their bookkeeping app. You never do maths "
    "and never invent anything. kind: create_invoice (bill a customer), chase_invoice (remind a customer about an "
    "unpaid invoice), log_mileage (a business journey), log_timesheet (hours someone worked on a job), "
    "add_to_shopping_list (put something on their shopping list to buy), or none "
    "(a question about the books, or anything else). Copy names exactly as the user said them into customer_ref, "
    "invoice_ref, job_ref, staff_ref and vehicle_ref. Copy figures exactly as said, as text: amount_text ('£100', "
    "'1,250.50'), hours_text ('7.5'), miles_text ('42'), and in lines quantity_text and unit_price_text. "
    "amount_includes_vat: true only if the user said the amount includes VAT. vat_code only if the user named "
    "one (S standard 20%, R reduced 5%, Z zero, E exempt, O outside scope). due_days only if the user gave "
    "payment terms in days. send: true if the user asked to send or email it. "
    "For add_to_shopping_list: item_text is the item exactly as said, with any sizes or colour but without "
    "the quantity or the job ('packing tape', 'tape 48mm x 66m', '2-inch bolts'); "
    "'remember to order X' and 'I need X' are add_to_shopping_list too; "
    "quantity_text how many as said ('6') or null; job_ref the job it is for, "
    "as said ('Hendon' for 'the Hendon job'). date_text: the day as said "
    "('yesterday', 'Monday', '3 Oct') or null. description: what the invoice is for, in the user's words "
    '(e.g. "this month\'s work"); for a timesheet, any note. Leave every field that does not apply null.'
)


class IntentLine(BaseModel):
    description: str
    quantity_text: str
    unit_price_text: str


class IntentModelOutput(BaseModel):
    """One flat object for every kind, so the strict schema stays simple; fields that do not apply are null."""

    kind: IntentKind
    customer_ref: str | None
    invoice_ref: str | None
    description: str | None
    amount_text: str | None
    amount_includes_vat: bool | None
    lines: list[IntentLine] | None
    vat_code: VatCode | None
    due_days: int | None
    send: bool | None
    miles_text: str | None
    from_place: str | None
    to_place: str | None
    job_ref: str | None
    vehicle_ref: str | None
    staff_ref: str | None
    hours_text: str | None
    date_text: str | None
    item_text: str | None
    quantity_text: str | None


# --------------------------------------------------------------------------- #
# Intents, after code has parsed the model's quotes
# --------------------------------------------------------------------------- #


class LineIntent(BaseModel):
    description: str
    quantity: Decimal
    unit_price_pence: int


class CreateInvoiceIntent(BaseModel):
    kind: Literal["create_invoice"] = "create_invoice"
    customer_ref: str
    description: str
    amount_pence: int | None = None
    amount_includes_vat: bool = False
    lines: list[LineIntent] | None = None
    vat_code: VatCode | None = None
    due_days: int | None = Field(default=None, ge=0, le=120)
    send: bool = False


class ChaseInvoiceIntent(BaseModel):
    kind: Literal["chase_invoice"] = "chase_invoice"
    customer_ref: str | None = None
    invoice_ref: str | None = None


class LogMileageIntent(BaseModel):
    kind: Literal["log_mileage"] = "log_mileage"
    miles: Decimal
    from_place: str
    to_place: str
    job_ref: str | None = None
    vehicle_ref: str | None = None
    date: dt.date | None = None


class LogTimesheetIntent(BaseModel):
    kind: Literal["log_timesheet"] = "log_timesheet"
    staff_ref: str
    job_ref: str
    hours: Decimal
    date: dt.date | None = None
    note: str = ""


class ShoppingIntent(BaseModel):
    kind: Literal["add_to_shopping_list"] = "add_to_shopping_list"
    item_text: str
    quantity: Decimal = Decimal(1)
    job_ref: str | None = None  # "the Hendon job": found among the open jobs by code


Intent = CreateInvoiceIntent | ChaseInvoiceIntent | LogMileageIntent | LogTimesheetIntent | ShoppingIntent


@dataclass
class NotAvailable:
    """The user asked for something this version cannot do yet (its module has not landed)."""

    kind: ActionKind
    message: str


# --------------------------------------------------------------------------- #
# Numbers and dates the user said
# --------------------------------------------------------------------------- #

_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.I)
_MONTHS = (
    {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
    | {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
    | {"sept": 9}
)
_WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}


def _decimal(digits: str, k: str | None) -> Decimal | None:
    try:
        value = Decimal(digits.replace(",", ""))
    except InvalidOperation:
        return None
    return value * 1000 if k else value


def number_in(text: str | None) -> Decimal | None:
    """The first number in `text` ('£1,250.50' -> 1250.50, '1.2k' -> 1200), or None."""
    m = _NUM.search(text or "")
    return _decimal(m.group(1), m.group(2)) if m else None


def numbers_said(text: str) -> set[Decimal]:
    return {d for m in _NUM.finditer(text) if (d := _decimal(m.group(1), m.group(2))) is not None}


def to_pence(pounds: Decimal) -> int:
    return int((pounds * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_day(text: str | None, today: date) -> date | None:
    """'today', 'yesterday', 'Monday' (the latest one, today included), '3 Oct', 'October 3rd', '3/10', '2026-10-03'.

    A day without a year is the latest one not after today. None when it cannot be read.
    """
    t = re.sub(r"\b(on|last|this|the|of)\b", " ", (text or "").strip().lower()).strip(" ,.")
    t = re.sub(r"\s+", " ", t)
    if t in ("", "today", "now"):
        return today
    if t == "yesterday":
        return today - timedelta(days=1)
    if t in _WEEKDAYS:
        return today - timedelta(days=(today.weekday() - _WEEKDAYS[t]) % 7)
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    day = month = year = None
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t):
        day, month = int(m[1]), int(m[2])
        year = int(m[3]) if m[3] else None
    elif m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]+)(?: (\d{4}))?", t):
        day, month = int(m[1]), _MONTHS.get(m[2])
        year = int(m[3]) if m[3] else None
    elif m := re.fullmatch(r"([a-z]+) (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?", t):
        day, month = int(m[2]), _MONTHS.get(m[1])
        year = int(m[3]) if m[3] else None
    if not day or not month:
        return None
    if year is not None and year < 100:
        year += 2000
    try:
        found = date(year or today.year, month, day)
        if year is None and found > today:
            found = date(today.year - 1, month, day)
    except ValueError:
        return None
    return found


def month_words(description: str, today: date) -> str:
    """'this month's work' -> 'Work for October 2026'. Only the words change; no dates or hours are looked up."""
    this = f"{calendar.month_name[today.month]} {today.year}"
    prev_day = today.replace(day=1) - timedelta(days=1)
    last = f"{calendar.month_name[prev_day.month]} {prev_day.year}"
    text = description.strip()
    text = re.sub(r"\bthis month'?s work\b", f"work for {this}", text, flags=re.I)
    text = re.sub(r"\blast month'?s work\b", f"work for {last}", text, flags=re.I)
    text = re.sub(r"\bthis month\b", this, text, flags=re.I)
    text = re.sub(r"\blast month\b", last, text, flags=re.I)
    return text[:1].upper() + text[1:]


def parse_intent(out: IntentModelOutput, question: str, today: date) -> Intent | Clarification | None:
    """Typed intent from the model's quotes. Every figure must be one the user said; otherwise ask."""
    said = numbers_said(question)

    def figure(text: str | None, kind: ActionKind, field: str, ask: str) -> Decimal | Clarification | None:
        if text is None or not text.strip():
            return None
        value = number_in(text)
        if value is None or value not in said or value <= 0:
            return Clarification(kind=kind, field=field, question_md=ask)
        return value

    def day(kind: ActionKind) -> date | Clarification | None:
        if not out.date_text:
            return None
        d = parse_day(out.date_text, today)
        if d is None or d > today:
            return Clarification(
                kind=kind, field="date", question_md=f"Which day was that? I couldn't read “{out.date_text}”."
            )
        return d

    if out.kind == "create_invoice":
        if not (out.customer_ref or "").strip():
            return Clarification(kind="create_invoice", field="customer", question_md="Who is the invoice for?")
        lines: list[LineIntent] = []
        for ln in out.lines or []:
            qty = figure(
                ln.quantity_text,
                "create_invoice",
                "amount",
                "How many of each line? I couldn't match the quantities to what you said.",
            )
            price = figure(
                ln.unit_price_text,
                "create_invoice",
                "amount",
                "What's the price of each line? I couldn't match the prices to what you said.",
            )
            if isinstance(qty, Clarification):
                return qty
            if isinstance(price, Clarification):
                return price
            if price is None:
                continue
            lines.append(
                LineIntent(
                    description=ln.description.strip() or "Work",
                    quantity=qty or Decimal(1),
                    unit_price_pence=to_pence(price),
                )
            )
        amount = figure(
            out.amount_text,
            "create_invoice",
            "amount",
            "How much should the invoice be for? Say the amount, e.g. “£100”.",
        )
        if isinstance(amount, Clarification):
            return amount
        if not lines and amount is None:
            return Clarification(
                kind="create_invoice", field="amount", question_md="How much should the invoice be for?"
            )
        terms = out.due_days  # terms the user did not say fall back to the profile's, like any other unsaid figure
        if terms is None or not 0 <= terms <= 120 or Decimal(terms) not in said:
            terms = None
        return CreateInvoiceIntent(
            customer_ref=(out.customer_ref or "").strip(),  # checked non-empty above
            description=month_words(out.description or "Work", today),  # type: ignore[union-attr]
            amount_pence=to_pence(amount) if amount is not None else None,
            amount_includes_vat=bool(out.amount_includes_vat),
            lines=lines or None,
            vat_code=out.vat_code,
            due_days=terms,
            send=bool(out.send),
        )
    if out.kind == "chase_invoice":
        if not (out.customer_ref or out.invoice_ref):
            return Clarification(
                kind="chase_invoice", field="invoice", question_md="Which invoice, or which customer, should I chase?"
            )
        return ChaseInvoiceIntent(customer_ref=out.customer_ref, invoice_ref=out.invoice_ref)
    if out.kind == "log_mileage":
        miles = figure(out.miles_text, "log_mileage", "miles", "How many miles was the journey?")
        if miles is None:
            return Clarification(kind="log_mileage", field="miles", question_md="How many miles was the journey?")
        if isinstance(miles, Clarification):
            return miles
        if not (out.from_place and out.to_place):
            return Clarification(
                kind="log_mileage", field="route", question_md="Where did the journey start and finish?"
            )
        d = day("log_mileage")
        if isinstance(d, Clarification):
            return d
        return LogMileageIntent(
            miles=miles,
            from_place=out.from_place.strip(),
            to_place=out.to_place.strip(),
            job_ref=out.job_ref,
            vehicle_ref=out.vehicle_ref,
            date=d,
        )
    if out.kind == "log_timesheet":
        hours = figure(out.hours_text, "log_timesheet", "hours", "How many hours?")
        if hours is None:
            return Clarification(kind="log_timesheet", field="hours", question_md="How many hours?")
        if isinstance(hours, Clarification):
            return hours
        if not out.staff_ref:
            return Clarification(kind="log_timesheet", field="staff", question_md="Who worked the hours?")
        if not out.job_ref:
            return Clarification(kind="log_timesheet", field="job", question_md="Which job were the hours on?")
        d = day("log_timesheet")
        if isinstance(d, Clarification):
            return d
        return LogTimesheetIntent(
            staff_ref=out.staff_ref.strip(),
            job_ref=out.job_ref.strip(),
            hours=hours,
            date=d,
            note=(out.description or "").strip()[:500],
        )
    if out.kind == "add_to_shopping_list":
        item = " ".join((out.item_text or "").split())[:120]
        if not item:
            return Clarification(
                kind="add_to_shopping_list", field="item", question_md="What should I add to your shopping list?"
            )
        qty = figure(out.quantity_text, "add_to_shopping_list", "quantity", "How many should I add?")
        if isinstance(qty, Clarification):
            return qty
        return ShoppingIntent(item_text=item, quantity=qty or Decimal(1), job_ref=(out.job_ref or "").strip() or None)
    return None


# --------------------------------------------------------------------------- #
# Finding things by name
# --------------------------------------------------------------------------- #


@dataclass
class Option:
    id: str
    name: str
    aliases: Sequence[str] = ()
    data: Any = None


@dataclass
class Picked:
    option: Option
    score: float


def _norm(name: str) -> str:
    """'J. M. Trading Ltd' and 'JM Trading' are both 'jmtrading'."""
    return supplier_key(name).replace("-", "") or name.strip().lower()


PART_WEIGHT = 0.99  # "Alex" for "Alex Green" or "Oak Lane" for "Bathroom, 4 Oak Lane": a match, just below a full one


def similarity(ref: str, name: str) -> float:
    """difflib ratio against the whole name, or against a run of the name's words as long as `ref`."""
    ratio = difflib.SequenceMatcher(None, _norm(ref), _norm(name)).ratio()
    want, words = supplier_key(ref).split("-"), supplier_key(name).split("-")
    if len(want) < len(words) and len("".join(want)) >= 3:
        for i in range(len(words) - len(want) + 1):
            part = "".join(words[i : i + len(want)])
            ratio = max(ratio, PART_WEIGHT * difflib.SequenceMatcher(None, "".join(want), part).ratio())
    return ratio


def pick(ref: str, options: Sequence[Option], kind: ActionKind, field: str, noun: str) -> Picked | Clarification:
    """The one option whose name (or alias) is at least MATCH_AT like `ref`; otherwise ask, with the candidates."""
    scored = sorted(
        (Picked(o, max(similarity(ref, n) for n in (o.name, *o.aliases))) for o in options),
        key=lambda p: (-p.score, p.option.name.lower()),
    )
    good = [p for p in scored if p.score >= MATCH_AT]
    exact = [p for p in good if p.score == 1.0]
    if len(exact) == 1 or len(good) == 1 or (len(good) > 1 and good[0].score - good[1].score >= CLEAR_LEAD):
        return (exact or good)[0]
    if good:
        names = [p.option.name for p in good[:5]]
        return Clarification(
            kind=kind,
            field=field,
            candidates=names,
            ref=ref,
            question_md=f"Which {noun} did you mean: {', '.join(names)}?",
        )
    near = [p.option.name for p in scored if p.score >= NEAR_AT][:3]
    if not options:
        return Clarification(kind=kind, field=field, question_md=f"You don't have any {noun}s set up yet.")
    ask = f"I couldn't find a {noun} called “{ref}”."
    if near:
        ask += f" Did you mean {', '.join(near)}?"
    return Clarification(kind=kind, field=field, candidates=near, ref=ref, question_md=ask)


async def customer_options(books: Books) -> list[Option]:
    """Customers from the contact book (stored contacts merged with the ledger's customers)."""
    book, _ledger, _stored = await contacts_.contact_book(books)
    return [Option(c.id, c.name, c.aliases, c) for c in book if c.kind in ("customer", "both")]


async def job_options(books: Books) -> list[Option]:
    return [Option(j.id, j.name, (), j) for j in await jobs_.load_jobs(books) if j.status == "open"]


async def staff_options(books: Books) -> list[Option]:
    return [Option(s.id, s.name, (s.role,) if s.role else (), s) for s in await jobs_.load_staff(books) if s.active]


async def vehicle_options(books: Books) -> list[Option]:
    out = []
    for v in await books.read_json(VEHICLES, []):
        if isinstance(v, dict) and v.get("id") and v.get("name") and v.get("active", True):
            out.append(Option(str(v["id"]), str(v["name"]), tuple(x for x in [v.get("registration")] if x), v))
    return out


# --------------------------------------------------------------------------- #
# Money (pence, by code; the same rules as app/invoicing.py)
# --------------------------------------------------------------------------- #


def _half_up(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_vat(net_pence: int, code: str) -> int:
    return _half_up(Decimal(net_pence) * RATES[code] / 100)


def net_from_gross(gross_pence: int, code: str) -> int:
    """The net whose net + VAT is exactly `gross_pence` when one exists (VAT rounded half up per line)."""
    base = _half_up(Decimal(gross_pence) * 100 / (100 + RATES[code]))
    return next((n for n in (base, base - 1, base + 1) if n + line_vat(n, code) == gross_pence), base)


def price_lines(lines: Sequence[tuple[str, Decimal, int, str]]) -> dict[str, Any]:
    """[(description, quantity, unit price pence, VAT code)] -> priced lines, VAT summary by code and totals."""
    priced, summary = [], {}
    for desc, qty, unit, code in lines:
        net = _half_up(qty * unit)
        vat = line_vat(net, code)
        priced.append(
            {
                "description": desc,
                "quantity": format(qty.normalize(), "f"),  # 10 -> "10", not "1E+1"
                "unit_price_pence": unit,
                "vat_code": code,
                "vat_rate": RATES[code],
                "net_pence": net,
                "vat_pence": vat,
            }
        )
        row = summary.setdefault(code, {"vat_code": code, "vat_rate": RATES[code], "net_pence": 0, "vat_pence": 0})
        row["net_pence"] += net
        row["vat_pence"] += vat
    net = sum(p["net_pence"] for p in priced)
    vat = sum(p["vat_pence"] for p in priced)
    order = list(RATES)
    return {
        "lines": priced,
        "vat_summary": sorted(summary.values(), key=lambda r: order.index(r["vat_code"])),
        "net_pence": net,
        "vat_pence": vat,
        "total_pence": net + vat,
    }


def money(p: int) -> str:
    sign = "-" if p < 0 else ""
    pounds, pennies = divmod(abs(p), 100)
    return f"{sign}£{pounds:,}.{pennies:02d}"


def uk_date(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def _md(text: str) -> str:
    """User-supplied text inside markdown: no emphasis, links or HTML from a contact's name."""
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", text)


# --------------------------------------------------------------------------- #
# Features that may not have landed yet
# --------------------------------------------------------------------------- #


def _module(name: str, *attrs: str) -> ModuleType | None:
    try:
        mod = importlib.import_module(name)
    except ImportError:
        return None
    return mod if all(hasattr(mod, a) for a in attrs) else None


def invoicing() -> ModuleType | None:
    """app/invoicing.py (claude/invoicing) when it is on this build."""
    return _module(
        "app.invoicing",
        "create_invoice",
        "send_invoice",
        "send_reminder",
        "list_invoices",
        "InvoiceDraft",
        "InvoiceCustomer",
        "LineIn",
        "price_lines",
        "load_profile",
        "sent_pdf",
    )


def mileage() -> ModuleType | None:
    """app/mileage.py (vehicles & mileage) when it is on this build, with an add_entry(books, MileageEntry)."""
    return _module("app.mileage", "MileageEntry", "add_entry")


UNAVAILABLE = {
    "create_invoice": "I can't create invoices from Ask yet: sales invoicing isn't in this version of Accnomos.",
    "chase_invoice": "I can't chase invoices from Ask yet: sales invoicing isn't in this version of Accnomos.",
    "log_mileage": "I can't log mileage yet: the mileage log isn't in this version of Accnomos.",
}


def available(kind: ActionKind) -> bool:
    if kind in ("create_invoice", "chase_invoice"):
        return invoicing() is not None
    if kind == "log_mileage":
        return mileage() is not None
    return True


# --------------------------------------------------------------------------- #
# Resolving an intent into a proposal
# --------------------------------------------------------------------------- #


@dataclass
class Draft:
    kind: ActionKind
    summary_md: str
    preview: dict[str, Any]
    confirm_text: str


async def resolve_invoice(books: Books, intent: CreateInvoiceIntent, today: date) -> Draft | Clarification:
    hit = pick(intent.customer_ref, await customer_options(books), "create_invoice", "customer", "customer")
    if isinstance(hit, Clarification):
        return hit
    contact = hit.option.data
    profile = await books.read_json(INVOICE_PROFILE, {})
    profile = profile if isinstance(profile, dict) else {}
    warnings: list[str] = []
    code = intent.vat_code or ("S" if profile.get("vrn") else "O")
    if not intent.vat_code and code == "O":
        warnings.append("No VAT charged: your invoice profile has no VAT registration number.")
    if intent.lines:
        rows = [(ln.description, ln.quantity, ln.unit_price_pence, code) for ln in intent.lines]
    else:
        amount = intent.amount_pence or 0
        unit = net_from_gross(amount, code) if intent.amount_includes_vat else amount
        rows = [(intent.description, Decimal(1), unit, code)]
    priced = price_lines(rows)
    if intent.amount_includes_vat and intent.amount_pence and priced["total_pence"] != intent.amount_pence:
        warnings.append(
            f"{money(intent.amount_pence)} can't be split exactly into"
            f" net and VAT; the total is {money(priced['total_pence'])}."
        )
    terms = intent.due_days if intent.due_days is not None else int(profile.get("terms_days") or DEFAULT_TERMS_DAYS)
    due = today + timedelta(days=terms)
    email = contact.email or None
    send = intent.send and bool(email)
    if intent.send and not email:
        warnings.append(
            f"{contact.name} has no email address in your contacts, so the invoice will be saved as a draft, not sent."
        )
    preview = {
        "customer": {
            "contact_id": contact.id,
            "name": contact.name,
            "email": email,
            "address": contact.address,
            "vrn": contact.vrn,
        },
        "issue_date": today.isoformat(),
        "due_date": due.isoformat(),
        "terms_days": terms,
        "reference": None,
        **priced,
        "send": send,
        "send_to": email if send else None,
        "warnings": warnings,
    }
    vat_words = f"VAT {money(priced['vat_pence'])}" if priced["vat_pence"] else "no VAT"
    head = "Send" if send else "Create"
    summary = (
        f"**{head} an invoice to {_md(contact.name)}** for **{money(priced['total_pence'])}** "
        f"({money(priced['net_pence'])} + {vat_words}), due {uk_date(due)}."
        + (
            f"\n\n- {_md(intent.description)}"
            if not intent.lines
            else "".join(f"\n- {_md(ln['description'])}" for ln in priced["lines"])
        )
    )
    confirm = f"Create the invoice and email it to {email}" if send else "Create the invoice as a draft (not sent)"
    return Draft("create_invoice", summary, preview, confirm)


async def resolve_chase(books: Books, intent: ChaseInvoiceIntent, cfg: AiConfig, today: date) -> Draft | Clarification:
    inv_mod = invoicing()
    assert inv_mod is not None
    unpaid = await inv_mod.list_invoices(books, "sent")
    if intent.invoice_ref:
        digits = re.sub(r"\D", "", intent.invoice_ref)
        found = [
            i
            for i in unpaid
            if i.number.upper() == intent.invoice_ref.strip().upper()
            or (digits and re.sub(r"\D", "", i.number).lstrip("0") == digits.lstrip("0"))
        ]
        if not found:
            return Clarification(
                kind="chase_invoice",
                field="invoice",
                candidates=[i.number for i in unpaid[:5]],
                question_md=f"I couldn't find an unpaid invoice “{intent.invoice_ref}”.",
            )
    else:
        options = [Option(i.number, i.customer.name, (), i) for i in unpaid]
        hit = pick(intent.customer_ref or "", options, "chase_invoice", "customer", "customer with an unpaid invoice")
        if isinstance(hit, Clarification):
            return hit
        found = [i for i in unpaid if _norm(i.customer.name) == _norm(hit.option.name)]
    if len(found) > 1:
        names = [f"{i.number} ({money(i.total_pence)})" for i in found[:5]]
        return Clarification(
            kind="chase_invoice",
            field="invoice",
            candidates=[i.number for i in found[:5]],
            question_md=f"Which invoice should I chase: {', '.join(names)}?",
        )
    return await chase_draft(books, found[0], cfg, today)


async def chase_draft(books: Books, inv: Any, cfg: AiConfig | None, today: date) -> Draft | Clarification:
    """The reminder card for one unpaid invoice: the words from the user's AI (checked by code), or from code when
    no AI is set up. Used by Ask's "chase" and by the month-end close (app/month_end.py)."""
    inv_mod = invoicing()
    assert inv_mod is not None
    from app.ai import remind  # only with invoicing

    draft = await remind.draft_reminder(inv, await inv_mod.load_profile(books), cfg, today)
    if not draft.to:
        return Clarification(
            kind="chase_invoice",
            field="customer",
            question_md=f"{_md(inv.customer.name)} has no email address on invoice {inv.number}; add one first.",
        )
    overdue = (today - inv.due_date).days
    when = f"{overdue} days overdue" if overdue > 0 else f"due {uk_date(inv.due_date)}"
    preview = {
        "invoice": inv.number,
        "customer": inv.customer.name,
        "total_pence": inv.total_pence,
        "due_date": inv.due_date.isoformat(),
        "days_overdue": max(overdue, 0),
        "to": draft.to,
        "subject": draft.subject,
        "body": draft.body,
        "warnings": [f"The message was written by code: {draft.fallback_reason}"] if draft.fallback_reason else [],
    }
    summary = (
        f"**Chase {_md(inv.customer.name)}** about invoice **{inv.number}** for **{money(inv.total_pence)}** "
        f"({when}).\n\n> " + _md(draft.body).replace("\n", "\n> ")
    )
    return Draft("chase_invoice", summary, preview, f"Email this reminder to {draft.to}")


async def resolve_timesheet(books: Books, intent: LogTimesheetIntent, today: date) -> Draft | Clarification:
    staff = pick(intent.staff_ref, await staff_options(books), "log_timesheet", "staff", "staff member")
    if isinstance(staff, Clarification):
        return staff
    job = pick(intent.job_ref, await job_options(books), "log_timesheet", "job", "open job")
    if isinstance(job, Clarification):
        return job
    try:
        hours = jobs_.round_hours(intent.hours)
    except jobs_.JobsError as exc:
        return Clarification(kind="log_timesheet", field="hours", question_md=str(exc))
    warnings = [] if hours == intent.hours else [f"{intent.hours} hours rounded to the nearest quarter: {hours}."]
    day = intent.date or today
    preview = {
        "staff_id": staff.option.id,
        "staff_name": staff.option.name,
        "job_id": job.option.id,
        "job_name": job.option.name,
        "date": day.isoformat(),
        "hours": str(hours),
        "note": intent.note,
        "warnings": warnings,
    }
    summary = f"**Log {hours} hours** for **{_md(staff.option.name)}** on **{_md(job.option.name)}**, {uk_date(day)}."
    return Draft("log_timesheet", summary, preview, "Add the hours to the timesheet")


async def resolve_mileage(books: Books, intent: LogMileageIntent, today: date) -> Draft | Clarification:
    vehicles = await vehicle_options(books)
    if intent.vehicle_ref:
        hit = pick(intent.vehicle_ref, vehicles, "log_mileage", "vehicle", "vehicle")
        if isinstance(hit, Clarification):
            return hit
        vehicle = hit.option
    elif len(vehicles) == 1:
        vehicle = vehicles[0]
    elif not vehicles:
        return Clarification(
            kind="log_mileage", field="vehicle", question_md="Add a vehicle on the Vehicles page first."
        )
    else:
        names = [v.name for v in vehicles[:5]]
        return Clarification(
            kind="log_mileage", field="vehicle", candidates=names, question_md=f"Which vehicle: {', '.join(names)}?"
        )
    job = None
    if intent.job_ref:
        hit = pick(intent.job_ref, await job_options(books), "log_mileage", "job", "open job")
        if isinstance(hit, Clarification):
            return hit
        job = hit.option
    miles = intent.miles.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    day = intent.date or today
    preview = {
        "vehicle_id": vehicle.id,
        "vehicle_name": vehicle.name,
        "date": day.isoformat(),
        "from": intent.from_place,
        "to": intent.to_place,
        "miles": str(miles),
        "job_id": job.id if job else None,
        "job_name": job.name if job else None,
        "warnings": [],
    }
    summary = (
        f"**Log {miles} miles** in **{_md(vehicle.name)}**,"
        f" {_md(intent.from_place)} to {_md(intent.to_place)}, {uk_date(day)}"
        + (f", for {_md(job.name)}." if job else ".")
    )
    return Draft("log_mileage", summary, preview, "Add the journey to the mileage log")


async def shopping_draft(books: Books, body: Any, today: date) -> Draft:
    """The card for adding one item (a shopping.ShoppingIn): code picks the cheapest supplier in the history."""
    from app import shopping

    r = await shopping.resolve(books, body, today)
    s = r["suggested"]
    where = (
        f" Cheapest in your books: £{s['unit_price']} from {_md(s['supplier'])}"
        f" ({uk_date(date.fromisoformat(s['date']))})."
        if s
        else " Nothing like it in your receipts yet, so no supplier is suggested."
    )
    live = r["live_offer"]
    if live:
        where += f" Live offer: £{live['unit_price']} from {_md(live['supplier'])} (found by {_md(live['source'])})."
    preview = {**r, "option_key": r["item_key"]}
    job = f" for **{_md(r['job_name'])}**" if r.get("job_name") else ""
    summary = f"**Add {r['quantity']} × {_md(r['description'])}** to your shopping list{job}.{where}"
    return Draft("add_to_shopping_list", summary, preview, "Add it to the shopping list")


async def resolve_shopping(books: Books, intent: ShoppingIntent, today: date) -> Draft | Clarification:
    from app import shopping

    job_id = job_name = None
    if intent.job_ref:  # "for the Hendon job": the job first, so a re-ask with a picked item keeps it
        hit = pick(intent.job_ref, await job_options(books), "add_to_shopping_list", "job", "open job")
        if isinstance(hit, Clarification):
            return hit
        job_id, job_name = hit.option.id, hit.option.name
    found = await shopping.lookup(books, intent.item_text, today)
    qty = format(intent.quantity.normalize(), "f")
    if len(found.options) == 1:
        body = shopping.ShoppingIn(
            text=intent.item_text, option_key=found.options[0].key, quantity=intent.quantity, job_id=job_id
        )
        return await shopping_draft(books, body, today)
    for_job = f" (for {_md(job_name)})" if job_name else ""
    if found.options:
        return Clarification(
            kind="add_to_shopping_list",
            field="item",
            candidates=[o.description for o in found.options],
            ref=intent.item_text,
            question_md=found.question_md + for_job,
            extra={"job_id": job_id, "job_name": job_name} if job_id else {},
        )
    fields = [f.model_dump() | ({"value": qty} if f.name == "quantity" else {}) for f in found.fields]
    return Clarification(
        kind="add_to_shopping_list",
        field="spec",
        ref=intent.item_text,
        question_md=found.question_md + for_job,
        spec_fields=fields,
        extra={"job_id": job_id, "job_name": job_name} if job_id else {},
    )


# --------------------------------------------------------------------------- #
# Signing (no server state: the client keeps the proposal)
# --------------------------------------------------------------------------- #

_RUNTIME_KEY = os.environ.get("ACTIONS_SIGNING_KEY", "").encode() or secrets.token_bytes(32)


def _key(graph_token: str) -> bytes:
    token_hash = hashlib.sha256(graph_token.encode() + _tenant()).digest()
    return hmac.new(_RUNTIME_KEY, token_hash, hashlib.sha256).digest()


def _tenant() -> bytes:
    """Test mode only: the X-Test-Tenant (one fake OneDrive each, whatever token is sent), so a proposal made in
    one tenant cannot be approved in another. Empty in production, where the token alone picks the OneDrive."""
    if not is_test_mode():
        return b""
    from app import testmode

    return b"\x00tenant:" + testmode.tenant().encode()


def _payload(action: ProposedAction) -> bytes:
    return json.dumps(
        action.model_dump(mode="json", exclude={"signature"}), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def sign(action: ProposedAction, graph_token: str) -> ProposedAction:
    return action.model_copy(
        update={"signature": hmac.new(_key(graph_token), _payload(action), hashlib.sha256).hexdigest()}
    )


def verify(action: ProposedAction, graph_token: str, at: datetime | None = None, check_expiry: bool = True) -> None:
    want = hmac.new(_key(graph_token), _payload(action), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, action.signature):
        raise ActionError("This proposal was changed, or made in another session; ask again.", 403)
    if check_expiry and (at or now()) > action.expires_at:
        raise ActionError("This proposal has expired; ask again.", 410)


def new_action(draft: Draft, graph_token: str, at: datetime | None = None) -> ProposedAction:
    created = (at or now()).astimezone(UTC).replace(microsecond=0)
    action = ProposedAction(
        id=uuid.uuid4().hex,
        kind=draft.kind,
        summary_md=draft.summary_md,
        preview=draft.preview,
        confirm_text=draft.confirm_text,
        created_at=created,
        expires_at=created + TTL,
    )
    return sign(action, graph_token)


# --------------------------------------------------------------------------- #
# From a question to a proposal
# --------------------------------------------------------------------------- #


def looks_like_action(question: str) -> bool:
    """Cheap gate before the intent call: an action word, and not phrased as a question about the books."""
    return bool(_ACTION_WORDS.search(question)) and not _QUESTION_START.match(question)


async def read_intent(question: str, cfg: AiConfig) -> IntentModelOutput | None:
    """The model's structured reading of the instruction; None when the model is unreachable or off-format."""
    messages = [{"role": "system", "content": INTENT_PROMPT}, {"role": "user", "content": question.strip()}]
    try:
        text = await ask_ai.call_json_model(messages, cfg, strict_json_schema(IntentModelOutput), "action_intent")
        return IntentModelOutput.model_validate(parse_model_json(text))
    except (ExtractionError, ValidationError):
        return None
    except Exception:  # noqa: BLE001  any model trouble: answer the question the ordinary way instead
        return None


async def propose(
    question: str,
    books: Books,
    cfg: AiConfig,
    graph_token: str,
    today: date | None = None,
) -> ProposedAction | Clarification | NotAvailable | None:
    """None when the question is not an instruction (Ask answers it as usual)."""
    if not looks_like_action(question):
        return None
    out = await read_intent(question, cfg)
    if out is None or out.kind == "none":
        return None
    if not available(out.kind):
        return NotAvailable(out.kind, UNAVAILABLE[out.kind])
    today = today or london_today()
    intent = parse_intent(out, question, today)
    if intent is None or isinstance(intent, Clarification):
        return intent
    if isinstance(intent, CreateInvoiceIntent):
        draft = await resolve_invoice(books, intent, today)
    elif isinstance(intent, ChaseInvoiceIntent):
        draft = await resolve_chase(books, intent, cfg, today)
    elif isinstance(intent, LogTimesheetIntent):
        draft = await resolve_timesheet(books, intent, today)
    elif isinstance(intent, ShoppingIntent):
        draft = await resolve_shopping(books, intent, today)
    else:
        draft = await resolve_mileage(books, intent, today)
    if isinstance(draft, Clarification):
        return draft
    return new_action(draft, graph_token)


# --------------------------------------------------------------------------- #
# Approve and reject
# --------------------------------------------------------------------------- #


class ActionResult(BaseModel):
    action_id: str
    kind: ActionKind
    status: Literal["done", "already_done"]
    summary_md: str
    result: dict[str, Any]


@dataclass
class Context:
    books: Books
    user: str
    graph_token: str
    mail_sender: Callable[[], Any] | None = None  # () -> MailSender; built only when something is emailed


class _Stop(Exception):
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row


def _audit_path(action: ProposedAction) -> str:
    return f"{ACTIONS_AUDIT}/{action.created_at:%Y-%m}.jsonl"


def _rows(raw: bytes | None) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in (raw or b"").decode().splitlines() if ln.strip()]


def _line(row: dict[str, Any]) -> bytes:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


async def _append(books: Books, action: ProposedAction, row: dict[str, Any]) -> None:
    full = {"ts": now().isoformat(), "action_id": action.id, "kind": action.kind, **row}
    await books._update(_audit_path(action), lambda old: (old or b"") + _line(full))


async def _claim(books: Books, action: ProposedAction, user: str) -> dict[str, Any] | None:
    """Mark the action as being approved. Returns the earlier result when it was already done."""
    row = {
        "ts": now().isoformat(),
        "action_id": action.id,
        "kind": action.kind,
        "event": "approving",
        "user": user,
        "summary_md": action.summary_md,
        "preview": action.preview,
    }

    def change(raw: bytes | None) -> bytes:
        events = [r for r in _rows(raw) if r.get("action_id") == action.id]
        last = events[-1] if events else None
        if last and last.get("event") == "executed":
            raise _Stop(last)
        if last and last.get("event") == "rejected":
            raise ActionError("You rejected this proposal; ask again to make a new one.", 409)
        if last and last.get("event") == "approving":
            if _stale(last):
                raise ActionError(
                    "The earlier approval of this action did not finish, so it may or may not have happened. "
                    "Check, then reject this card and ask again if it is still needed.",
                    409,
                )
            raise ActionError(
                "This action is already being approved. If nothing happened, check before asking again.", 409
            )
        return (raw or b"") + _line(row)  # a failed attempt may be retried

    try:
        await books._update(_audit_path(action), change)
    except _Stop as stop:
        return stop.row
    return None


def _stale(row: dict[str, Any], at: datetime | None = None) -> bool:
    try:
        return (at or now()) - datetime.fromisoformat(row["ts"]) > APPROVING_STALE
    except (KeyError, TypeError, ValueError):
        return False


Executor = Callable[[ProposedAction, Context], Awaitable[tuple[str, dict[str, Any]]]]


async def run_timesheet(action: ProposedAction, ctx: Context) -> tuple[str, dict[str, Any]]:
    p = action.preview
    entry = jobs_.TimesheetEntry(
        id=action.id[:12],
        staff_id=p["staff_id"],
        job_id=p["job_id"],
        date=date.fromisoformat(p["date"]),
        hours=p["hours"],
        note=p.get("note") or "",
    )
    await jobs_.add_entry(ctx.books, entry)
    await ctx.books.audit(f"user:{ctx.user}", "timesheet_added", {"entry": entry.id, "action": action.id})
    return (
        f"Logged {p['hours']} hours for {_md(p['staff_name'])} on {_md(p['job_name'])}.",
        {"entry_id": entry.id, "hours": p["hours"], "date": p["date"]},
    )


async def run_mileage(action: ProposedAction, ctx: Context) -> tuple[str, dict[str, Any]]:
    mod = mileage()
    if mod is None:
        raise ActionError(UNAVAILABLE["log_mileage"], 501)
    p = action.preview
    # Fields as in the vehicles & mileage contract: {id, vehicle_id, date, from, to, miles, purpose, job_id, source}
    try:
        entry = mod.MileageEntry.model_validate(
            {
                "id": action.id[:12],
                "vehicle_id": p["vehicle_id"],
                "date": p["date"],
                "from": p["from"],
                "to": p["to"],
                "miles": p["miles"],
                "purpose": p.get("job_name") or f"{p['from']} to {p['to']}"[:200],
                "job_id": p.get("job_id"),
                "source": "manual",
            }
        )
    except (ValidationError, AttributeError) as exc:
        raise ActionError("The mileage log in this version doesn't accept journeys from Ask yet.", 501) from exc
    entry = await mod.add_entry(ctx.books, entry, ctx.user)  # audited as user:<X-User>
    return (f"Logged {p['miles']} miles in {_md(p['vehicle_name'])}.", {"entry_id": entry.id, "miles": p["miles"]})


async def _invoice_pdf(books: Books, inv_mod: ModuleType, inv: Any) -> bytes:
    from app.pdf import render_invoice  # only with invoicing

    profile = await inv_mod.load_profile(books)
    return render_invoice(inv, profile, await inv_mod.load_logo(books, profile))


async def run_invoice(action: ProposedAction, ctx: Context) -> tuple[str, dict[str, Any]]:
    inv_mod = invoicing()
    if inv_mod is None:
        raise ActionError(UNAVAILABLE["create_invoice"], 501)
    p = action.preview
    lines = [
        inv_mod.LineIn(
            description=ln["description"],
            quantity=Decimal(ln["quantity"]),
            unit_price_pence=ln["unit_price_pence"],
            vat_code=ln["vat_code"],
        )
        for ln in p["lines"]
    ]
    _, _, net, vat = inv_mod.price_lines(lines)
    if (net, vat) != (p["net_pence"], p["vat_pence"]):  # the invoice module is the authority on money
        raise ActionError("The invoice totals no longer match what you approved; ask again.", 409)
    draft = inv_mod.InvoiceDraft(
        customer=inv_mod.InvoiceCustomer(**p["customer"]),
        issue_date=date.fromisoformat(p["issue_date"]),
        due_date=date.fromisoformat(p["due_date"]),
        lines=lines,
        notes=None,
    )
    inv = await inv_mod.create_invoice(ctx.books, draft, ctx.user)
    result: dict[str, Any] = {
        "invoice": inv.number,
        "total_pence": inv.total_pence,
        "status": inv.status,
        "sent_to": None,
    }
    if not p.get("send"):
        return f"Invoice **{inv.number}** for {money(inv.total_pence)} saved as a draft.", result
    try:
        pdf = await _invoice_pdf(ctx.books, inv_mod, inv)
        sender = ctx.mail_sender() if ctx.mail_sender else None
        if sender is None:
            raise RuntimeError("email is not available")
        try:
            inv = await inv_mod.send_invoice(ctx.books, sender, inv.number, ctx.user, pdf, to=p["send_to"])
        finally:
            if hasattr(sender, "aclose"):
                await sender.aclose()
    except Exception as exc:  # noqa: BLE001  the invoice exists either way; say why it was not sent
        result["send_error"] = str(exc)[:300]
        return (
            f"Invoice **{inv.number}** for {money(inv.total_pence)} was saved as a draft but **not sent**: "
            f"{_md(str(exc)[:200])}. Open Invoices to send it.",
            result,
        )
    result.update(status=inv.status, sent_to=inv.sent_to)
    return f"Invoice **{inv.number}** for {money(inv.total_pence)} sent to {_md(inv.sent_to or '')}.", result


async def run_chase(action: ProposedAction, ctx: Context) -> tuple[str, dict[str, Any]]:
    inv_mod = invoicing()
    if inv_mod is None:
        raise ActionError(UNAVAILABLE["chase_invoice"], 501)
    p = action.preview
    sender = ctx.mail_sender() if ctx.mail_sender else None
    if sender is None:
        raise ActionError("Email is not available on this runtime.", 501)
    try:
        inv = await inv_mod.send_reminder(
            ctx.books,
            sender,
            p["invoice"],
            ctx.user,
            to=p["to"],
            subject=p["subject"],
            body=p["body"],
            pdf=await inv_mod.sent_pdf(ctx.books, p["invoice"]),
        )
    finally:
        if hasattr(sender, "aclose"):
            await sender.aclose()
    return (
        f"Reminder for invoice **{inv.number}** sent to {_md(p['to'])}.",
        {"invoice": inv.number, "sent_to": p["to"], "reminders": len(inv.reminders)},
    )


async def run_bank_match(action: ProposedAction, ctx: Context) -> tuple[str, dict[str, Any]]:
    """A match the month-end close suggested (code, app/month_end.py): the same as confirming it on the Bank page.
    Matching posts nothing; Books.confirm_match refuses a line or entry that has changed since."""
    p = action.preview
    line = await ctx.books.confirm_match(p["line_id"], list(p["event_ids"]), ctx.user)
    return (
        f"Matched the bank line of {money(line.amount_pence)} on {uk_date(line.date)}"
        f" to {_md(p.get('to') or 'the entry')}.",
        {"line_id": line.id, "event_ids": list(p["event_ids"])},
    )


async def run_close(action: ProposedAction, ctx: Context) -> tuple[str, dict[str, Any]]:
    """Mark a month closed (app/month_end.py): refused when the month's figures differ from the ones on the card."""
    from app import month_end  # month_end builds these cards with this module

    rec = await month_end.lock(ctx.books, action.preview, ctx.user, action_id=action.id)
    verb = "Re-closed" if rec.reclose else "Closed"
    return (
        f"{verb} **{_md(action.preview.get('label') or rec.month)}**. Snapshot {rec.snapshot_hash[:12]}"
        + (f"; reports saved to {_md(rec.report_path)}." if rec.report_path else "."),
        {
            "month": rec.month,
            "snapshot_hash": rec.snapshot_hash,
            "report_path": rec.report_path,
            "reclose": rec.reclose,
        },
    )


async def run_shopping(action: ProposedAction, ctx: Context) -> tuple[str, dict[str, Any]]:
    from app import shopping

    p = action.preview
    spec = p.get("spec") or {}
    body = shopping.ShoppingIn(
        text=p["text"],
        option_key=p.get("option_key"),
        spec=None
        if p.get("option_key")
        else shopping.ShoppingSpec(**{k: v for k, v in spec.items() if v and not (k == "pack" and v == 1)}),
        quantity=Decimal(p["quantity"]),
        note=p.get("note") or "",
        job_id=p.get("job_id"),
    )
    item = await shopping.add_item(ctx.books, body, ctx.user, london_today())
    job = f" for {_md(item.job_name)}" if item.job_name else ""
    return (
        f"Added {item.quantity} × {_md(item.description)} to your shopping list{job}.",
        {"item_id": item.id, "description": item.description, "quantity": str(item.quantity), "job_id": item.job_id},
    )


EXECUTORS: dict[str, Executor] = {
    "create_invoice": run_invoice,
    "chase_invoice": run_chase,
    "log_mileage": run_mileage,
    "log_timesheet": run_timesheet,
    "match_bank_line": run_bank_match,
    "close_month": run_close,
    "add_to_shopping_list": run_shopping,
}


async def approve(action: ProposedAction, ctx: Context) -> ActionResult:
    """Check the signature and expiry, claim the action id, execute, and record the result. Executes once."""
    verify(action, ctx.graph_token)
    earlier = await _claim(ctx.books, action, ctx.user)
    if earlier is not None:
        return ActionResult(
            action_id=action.id,
            kind=action.kind,
            status="already_done",
            summary_md=earlier.get("result_md", ""),
            result=earlier.get("result", {}),
        )
    try:
        summary, result = await EXECUTORS[action.kind](action, ctx)
    except Exception as exc:
        await _append(ctx.books, action, {"event": "failed", "user": ctx.user, "error": str(exc)[:300]})
        raise
    await _append(ctx.books, action, {"event": "executed", "user": ctx.user, "result_md": summary, "result": result})
    return ActionResult(action_id=action.id, kind=action.kind, status="done", summary_md=summary, result=result)


async def reject(action: ProposedAction, ctx: Context, reason: str | None = None) -> None:
    """Record that the user said no. Nothing else happens; a rejected action cannot be approved later.

    An expired proposal can still be rejected (it is only audited); one already approved cannot. Rejecting is
    also how an `approving` line older than APPROVING_STALE is cleared (the run that wrote it died).
    """
    verify(action, ctx.graph_token, check_expiry=False)
    row = {
        "ts": now().isoformat(),
        "action_id": action.id,
        "kind": action.kind,
        "event": "rejected",
        "user": ctx.user,
        "reason": (reason or "").strip()[:300] or None,
        "summary_md": action.summary_md,
    }

    def change(raw: bytes | None) -> bytes:
        events = [r for r in _rows(raw) if r.get("action_id") == action.id]
        last = events[-1] if events else None
        if last and last.get("event") == "approving" and _stale(last):
            return (raw or b"") + _line({**row, "cleared": "stale approving"})
        if last and last.get("event") in ("approving", "executed"):
            raise ActionError("This action was already approved.", 409)
        return (raw or b"") + _line(row)

    await ctx.books._update(_audit_path(action), change)
