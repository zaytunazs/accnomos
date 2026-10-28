"""Spending summary: where the money went in a period, worked out by code from the user's approved purchases.

Code computes every figure: spend by category and by supplier, the top items (from receipt line items), the change
on the previous period of the same length, recurring costs (subscriptions, utilities, anything bought in most
months) and unusual one-offs. The model then writes a short plain-English summary from those facts only, and the
Ask pipeline's number check (app/ai/ask.py KnownNumbers / wrong_period) runs on its words: a figure that is not in
the facts, or one from the previous period quoted as this one's, and code's own summary is shown instead.

Money is pounds as strings ("1234.56"), before VAT, as in the Ask facts pack.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel

from app.books import Books
from app.facts import period_label, pounds, previous_period
from app.prices import normalise
from app.purchases import Purchase, load_purchases
from app.schemas import AskPeriod

TOP_N = 6
LOOKBACK_MONTHS = 6  # recurring costs and "usual" purchase sizes look this far back before the period
RECURRING_MONTHS = 3  # bought in at least this many different months: a regular cost
RECURRING_CATEGORIES = {
    "Software & subscriptions": "subscription",
    "Utilities": "utility",
    "Telephone & internet": "utility",
    "Rent": "regular",
    "Insurance": "regular",
}
UNUSUAL_MIN_PENCE = 10_000  # a one-off must be at least £100 before VAT
UNUSUAL_TIMES = Decimal(3)  # and at least this many times the usual (median) purchase


_SUMMARY = re.compile(
    r"\b(?:spending|spend) summary\b|\bsummar(?:y|ise|ize)\b.{0,20}\b(?:spending|spend|costs|purchases)\b|"
    r"\bwhere (?:did|does|has) (?:my|the) money go(?:ne)?\b|\bwhat did i spend (?:my money |it )?on\b",
    re.IGNORECASE,
)


def asks_for_summary(question: str) -> bool:
    """ "Summarise my spending this month", "where did my money go": the spending summary, not the VAT facts."""
    return bool(_SUMMARY.search(question))


def _pct(now: int, before: int) -> str | None:
    return None if before == 0 else f"{(Decimal(now - before) / abs(Decimal(before)) * 100):.1f}"


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _months_back(d: date, n: int) -> date:
    first = d.replace(day=1)
    for _ in range(n):
        first = (first - timedelta(days=1)).replace(day=1)
    return first


def _ranked(rows: dict[str, int], counts: dict[str, int], prev: dict[str, int], n: int) -> list[dict[str, Any]]:
    names = sorted(rows, key=lambda k: (-rows[k], k))[:n]
    return [
        {
            "name": k,
            "net": pounds(rows[k]),
            "count": counts[k],
            "change_vs_previous": pounds(rows[k] - prev.get(k, 0)),
            "change_pct": _pct(rows[k], prev.get(k, 0)),
        }
        for k in names
    ]


def _top_items(purchases: list[Purchase]) -> list[dict[str, Any]]:
    """Line items by what was spent on them in the period, the same product (code's key) counted together."""
    spent: dict[str, int] = defaultdict(int)
    qty: dict[str, Decimal] = defaultdict(Decimal)
    name: dict[str, str] = {}
    suppliers: dict[str, set[str]] = defaultdict(set)
    for p in purchases:
        for ln in p.lines:
            if ln.net_pence <= 0:
                continue
            key = normalise(ln.description).key
            spent[key] += ln.net_pence
            qty[key] += Decimal(str(ln.qty))
            name[key] = ln.description
            suppliers[key].add(p.supplier)
    keys = sorted(spent, key=lambda k: (-spent[k], k))[:TOP_N]
    return [
        {
            "item": name[k],
            "net": pounds(spent[k]),
            "quantity": format(qty[k].normalize(), "f"),
            "suppliers": sorted(suppliers[k]),
        }
        for k in keys
    ]


def recurring(history: list[Purchase], period: AskPeriod) -> list[dict[str, Any]]:
    """Suppliers bought from in RECURRING_MONTHS or more different months (two for a subscription, utility, rent or
    insurance), up to the end of the period, with what a usual month costs and what this period cost."""
    by_supplier: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    category: dict[str, str] = {}
    for p in history:
        if p.net_pence > 0:
            by_supplier[p.supplier][_month(p.date)] += p.net_pence
            category[p.supplier] = p.category
    out = []
    for supplier, months in by_supplier.items():
        kind = RECURRING_CATEGORIES.get(category[supplier])
        if len(months) < RECURRING_MONTHS and not (kind and len(months) >= 2):
            continue
        in_period = sum(p.net_pence for p in history if p.supplier == supplier and period.start <= p.date <= period.end)
        typical = int(Decimal(str(statistics.median(months.values()))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        out.append(
            {
                "supplier": supplier,
                "kind": kind or "regular",
                "category": category[supplier],
                "months_seen": len(months),
                "usual_month": pounds(typical),
                "this_period": pounds(in_period),
            }
        )
    return sorted(out, key=lambda r: (-Decimal(r["usual_month"]), r["supplier"]))[:TOP_N]


def unusual(history: list[Purchase], period: AskPeriod, regular: set[str]) -> list[dict[str, Any]]:
    """Single purchases in the period from a supplier that is not a regular cost, at least £100 and at least
    UNUSUAL_TIMES the usual (median) purchase before the period. No history before it: none are flagged."""
    before = [p.net_pence for p in history if p.date < period.start and p.net_pence > 0]
    if not before:
        return []
    usual = Decimal(str(statistics.median(before)))
    out = []
    for p in history:
        if not (period.start <= p.date <= period.end) or p.supplier in regular or p.net_pence < UNUSUAL_MIN_PENCE:
            continue
        times = Decimal(p.net_pence) / usual if usual else Decimal(0)
        if times < UNUSUAL_TIMES:
            continue
        seen = any(q.supplier == p.supplier and q.date < period.start for q in history)
        out.append(
            {
                "date": p.date.isoformat(),
                "supplier": p.supplier,
                "category": p.category,
                "net": pounds(p.net_pence),
                "times_usual_purchase": f"{times:.1f}",
                "why": "larger than your usual purchase" + ("" if seen else ", from a supplier new to your books"),
                "source": p.source,
            }
        )
    return sorted(out, key=lambda r: -Decimal(r["net"]))[:TOP_N]


def _side(purchases: list[Purchase]) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    cat: dict[str, int] = defaultdict(int)
    cat_n: dict[str, int] = defaultdict(int)
    sup: dict[str, int] = defaultdict(int)
    sup_n: dict[str, int] = defaultdict(int)
    for p in purchases:
        cat[p.category] += p.net_pence
        cat_n[p.category] += 1
        sup[p.supplier] += p.net_pence
        sup_n[p.supplier] += 1
    return cat, cat_n, sup, sup_n


def summary_facts(history: list[Purchase], period: AskPeriod, business: str | None = None) -> dict[str, Any]:
    """Every figure the summary may quote. `history` must cover LOOKBACK_MONTHS before the previous period."""
    prev = previous_period(period)
    this = [p for p in history if period.start <= p.date <= period.end]
    before = [p for p in history if prev.start <= p.date <= prev.end]
    cat, cat_n, sup, sup_n = _side(this)
    pcat, pcat_n, psup, psup_n = _side(before)
    net, pnet = sum(p.net_pence for p in this), sum(p.net_pence for p in before)
    label, plabel = period_label(period), period_label(prev)
    regular = recurring(history, period)
    return {
        "business": business,
        "money": "GBP pounds before VAT; negative = a credit note or a fall",
        "this_period": {
            "label": label,
            "period_key": label,
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "spent": pounds(net),
            "vat": pounds(sum(p.vat_pence for p in this)),
            "purchases": len(this),
            "by_category": _ranked(cat, cat_n, pcat, TOP_N),
            "by_supplier": _ranked(sup, sup_n, psup, TOP_N),
            "top_items": _top_items(this),
            "with_line_items": sum(1 for p in this if p.lines),
        },
        "previous_period": {
            "label": plabel,
            "period_key": plabel,
            "start": prev.start.isoformat(),
            "end": prev.end.isoformat(),
            "spent": pounds(pnet),
            "purchases": len(before),
            "by_category": [
                {"name": k, "net": pounds(v), "count": pcat_n[k]}
                for k, v in sorted(pcat.items(), key=lambda kv: -kv[1])
            ][:TOP_N],
        },
        "change": {"spent_vs_previous": pounds(net - pnet), "spent_change_pct": _pct(net, pnet)},
        "recurring": regular,
        "unusual": unusual(history, period, {r["supplier"] for r in regular}),
        "sources": sorted({p.source.rsplit("/", 1)[0] + "/" for p in this}),
    }


async def build(books: Books, period: AskPeriod, business: str | None = None) -> dict[str, Any]:
    prev = previous_period(period)
    history = await load_purchases(books, _months_back(prev.start, LOOKBACK_MONTHS), period.end)
    return summary_facts(history, period, business)


def code_summary(facts: dict[str, Any]) -> str:
    """The summary written by code, quoting the facts exactly: used when the model's words do not check out."""
    t, prev, ch = facts["this_period"], facts["previous_period"], facts["change"]
    if not t["purchases"]:
        return f"No approved purchases in {t['label']} yet."
    word = "up" if Decimal(ch["spent_vs_previous"]) > 0 else "down"
    lines = [f"You spent £{Decimal(t['spent']):,.2f} before VAT in {t['label']} across {t['purchases']} purchases"]
    if Decimal(prev["spent"]):
        lines[0] += f", {word} £{abs(Decimal(ch['spent_vs_previous'])):,.2f} on {prev['label']}" + (
            f" ({ch['spent_change_pct'].lstrip('-')}%)" if ch["spent_change_pct"] else ""
        )
    lines[0] += "."
    if t["by_category"]:
        c = t["by_category"][0]
        lines.append(f"Most went on {c['name']} (£{Decimal(c['net']):,.2f}).")
    if facts["recurring"]:
        r = facts["recurring"][0]
        usual = f"£{Decimal(r['usual_month']):,.2f}"
        lines.append(f"Your largest regular cost is {r['supplier']}, usually {usual} a month.")
    if facts["unusual"]:
        u = facts["unusual"][0]
        lines.append(f"One-off: £{Decimal(u['net']):,.2f} with {u['supplier']}.")
    return " ".join(lines)


class SpendingSummary(BaseModel):
    """GET /books/spending."""

    period: AskPeriod
    previous: AskPeriod
    facts: dict[str, Any]
    summary_md: str
    summary_by: str  # "model" (checked against the facts) or "code"
    fallback_reason: str | None = None
    model: str
