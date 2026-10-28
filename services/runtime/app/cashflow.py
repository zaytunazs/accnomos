"""Short-term cash flow: the next 30, 60 and 90 days from the bank balance, open invoices and open bills, by code.

- **Opening balance**: the ledger balance today of every bank-type account in the chart (1200 Bank, 1210 Cash, and
  any you add), debit − credit, entries dated up to today.
- **Money in**: what is still owed on each open sales invoice, on its due date (app/contacts.py `aged`, the same
  figures as Contacts and the Aged report). **Money out**: what is still owed on each bill on account.
- **Overdue** items are counted as due now, in the first 30 days, and shown separately.
- **Repeating items**: Accnomos has no repeating invoices or bills yet, so none are included (`repeating` is empty).
  Payroll, VAT payments and card spending are not forecast either; the page says so.

The model may add one plain-English line (`explain`); every figure in it must be one of these (the Ask number
check, app/ai/ask.py `KnownNumbers`) or the line is dropped.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from accnomos_ledger.events import LedgerEvent
from app.chart import Account
from app.contacts import AgedBalances
from app.invoicing import money

HORIZONS = (30, 60, 90)
NOT_INCLUDED = (
    "Repeating invoices and bills (Accnomos has none yet), pay runs, VAT payments and card spending are not "
    "included: only open invoices and bills on account."
)


class CashItem(BaseModel):
    direction: Literal["in", "out"]
    contact: str
    reference: str | None
    due_date: date
    amount_pence: int
    overdue: bool
    event_id: str


class CashBucket(BaseModel):
    label: str  # "Overdue", "Next 30 days", "31–60 days", "61–90 days"
    start: date | None
    end: date
    money_in_pence: int
    money_out_pence: int
    net_pence: int


class CashPoint(BaseModel):
    days: int
    date: date
    money_in_pence: int  # cumulative from today, overdue included
    money_out_pence: int
    balance_pence: int  # opening + in − out


class CashFlow(BaseModel):
    as_of: date
    opening_balance_pence: int
    bank_accounts: list[str]
    buckets: list[CashBucket]
    points: list[CashPoint]
    items: list[CashItem]
    later_in_pence: int  # due after 90 days, not in the forecast
    later_out_pence: int
    repeating: list[CashItem] = []
    not_included: str = NOT_INCLUDED
    lowest_balance_pence: int
    lowest_on: date


def bank_balance(events: Iterable[LedgerEvent], chart: Sequence[Account], as_of: date) -> tuple[int, list[str]]:
    banks = {a.label for a in chart if a.type == "bank"}
    total = sum(ln.debit - ln.credit for e in events if e.date <= as_of for ln in e.lines if ln.account in banks)
    return total, sorted(banks)


def forecast(aged: AgedBalances, opening: int, banks: list[str], as_of: date) -> CashFlow:
    items: list[CashItem] = []
    for direction, table in (("in", aged.debtors), ("out", aged.creditors)):
        for row in table.rows:
            for d in row.documents:
                items.append(
                    CashItem(
                        direction=direction,  # type: ignore[arg-type]
                        contact=row.name,
                        reference=d.reference,
                        due_date=d.due_date,
                        amount_pence=d.amount_pence,
                        overdue=d.due_date < as_of,
                        event_id=d.event_id,
                    )
                )
    items.sort(key=lambda i: (i.due_date, i.direction, i.contact))
    end90 = as_of + timedelta(days=90)

    def total(direction: str, lo: date | None, hi: date) -> int:
        return sum(
            i.amount_pence
            for i in items
            if i.direction == direction and (lo is None or i.due_date >= lo) and i.due_date <= hi
        )

    bounds: list[tuple[str, date | None, date]] = [("Overdue", None, as_of - timedelta(days=1))]
    prev = as_of
    for n, label in zip(HORIZONS, ("Next 30 days", "31–60 days", "61–90 days"), strict=True):
        bounds.append((label, prev, as_of + timedelta(days=n)))
        prev = as_of + timedelta(days=n + 1)
    buckets = [
        CashBucket(
            label=label,
            start=lo,
            end=hi,
            money_in_pence=(i := total("in", lo, hi)),
            money_out_pence=(o := total("out", lo, hi)),
            net_pence=i - o,
        )
        for label, lo, hi in bounds
    ]
    points = []
    for n in HORIZONS:
        day = as_of + timedelta(days=n)
        i, o = total("in", None, day), total("out", None, day)
        points.append(CashPoint(days=n, date=day, money_in_pence=i, money_out_pence=o, balance_pence=opening + i - o))
    # The lowest running balance over the 90 days, item by item (overdue items land today).
    running, lowest, lowest_on = opening, opening, as_of
    for it in (i for i in items if i.due_date <= end90):
        running += it.amount_pence if it.direction == "in" else -it.amount_pence
        if running < lowest:
            lowest, lowest_on = running, max(it.due_date, as_of)
    return CashFlow(
        as_of=as_of,
        opening_balance_pence=opening,
        bank_accounts=banks,
        buckets=buckets,
        points=points,
        items=[i for i in items if i.due_date <= end90],
        later_in_pence=sum(i.amount_pence for i in items if i.direction == "in" and i.due_date > end90),
        later_out_pence=sum(i.amount_pence for i in items if i.direction == "out" and i.due_date > end90),
        lowest_balance_pence=lowest,
        lowest_on=lowest_on,
    )


# --------------------------------------------------------------------------- #
# One plain-English line from the model, checked by code
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = (
    "You write ONE short plain-English sentence (under 40 words) for a UK small business owner about their cash "
    "over the next 90 days. You are given FACTS as JSON, worked out by code. Quote amounts and dates exactly as "
    "they appear in FACTS; never calculate, never advise on borrowing or tax. Return JSON with `line`."
)


class LineOut(BaseModel):
    line: str


class CashLine(BaseModel):
    line: str | None
    model: str | None
    reason: str | None = None  # why there is no line


def facts(cf: CashFlow) -> dict[str, Any]:
    return {
        "today": f"{cf.as_of:%d %B %Y}",
        "bank_balance_today": money(cf.opening_balance_pence),
        **{f"balance_in_{p.days}_days": money(p.balance_pence) for p in cf.points},
        **{f"money_in_within_{p.days}_days": money(p.money_in_pence) for p in cf.points},
        **{f"money_out_within_{p.days}_days": money(p.money_out_pence) for p in cf.points},
        "overdue_from_customers": money(cf.buckets[0].money_in_pence),
        "overdue_to_suppliers": money(cf.buckets[0].money_out_pence),
        "lowest_balance": money(cf.lowest_balance_pence),
        "lowest_balance_on": f"{cf.lowest_on:%d %B %Y}",
    }


def check_line(text: str, known: dict[str, Any]) -> str | None:
    """The line when every figure in it is one of the facts; None otherwise."""
    from app.ai.ask import KnownNumbers

    text = " ".join(text.split())
    if not text or len(text) > 300 or "http" in text.lower():
        return None
    if KnownNumbers(known).unknown(text, all_tokens=False):
        return None
    return text


async def explain(cf: CashFlow, cfg: Any) -> CashLine:
    """Never raises for model trouble: no line, with the reason."""
    from app.ai.ask import call_json_model
    from app.ai.extract import parse_model_json
    from app.schemas import strict_json_schema

    known = facts(cf)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"FACTS:\n{json.dumps(known, ensure_ascii=False)}"},
    ]
    try:
        out = LineOut.model_validate(
            parse_model_json(await call_json_model(messages, cfg, strict_json_schema(LineOut), "cash_flow_line"))
        )
    except Exception as exc:  # noqa: BLE001  any model trouble (HTTP, format): the forecast stands without a line
        return CashLine(
            line=None,
            model=getattr(cfg, "model", None),
            reason=f"Your AI could not write a line ({type(exc).__name__}).",
        )
    line = check_line(out.line, known)
    if line is None:
        return CashLine(
            line=None,
            model=cfg.model,
            reason="The model's line quoted figures that are not in the forecast, so it was left out.",
        )
    return CashLine(line=line, model=cfg.model)
