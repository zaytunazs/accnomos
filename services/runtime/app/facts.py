"""The facts pack for "Ask your books": every number the model may quote, computed here by code.

The pack is compact JSON (about 6 KB at most), built per request from the user's own ledger
events and thrown away with the response. Money is pounds as strings ("1234.56"); boxes 6-9 are
whole pounds, as HMRC receives them. `sources` lists the only paths an answer may cite.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from accnomos_ledger import LedgerEvent, SchemeBooks, compute_vat_return, vat_side
from app.books import EVENTS, PROPOSALS, WORKBOOK, Books
from app.paths import VAT_RETURNS
from app.routes_vat import box_amounts, period_key_for
from app.schemas import AskPeriod
from app.vat_cycle import VatCycle
from app.vat_schemes import SchemeContext, scheme_books, scheme_context, scheme_return, scheme_view

Schemes = tuple[SchemeContext, SchemeBooks]

FACTS_MAX_BYTES = 6 * 1024
TOP_N = 8
PROPOSALS_CHEAP = 40  # read proposal files to count pending ones only when there are this few


def pounds(pence: int) -> str:
    return f"{Decimal(pence) / 100:.2f}"


def _month_end(d: date) -> date:
    nxt = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def default_period(today: date, cycle: VatCycle = VatCycle()) -> AskPeriod:
    """The VAT period we are in now, by the saved VAT settings (the same default as GET /books/vat)."""
    start, end = cycle.current(today)
    return AskPeriod(start=start, end=end)


def previous_period(p: AskPeriod) -> AskPeriod:
    """The same span just before `p`: whole months when `p` is whole months, else the same number of days."""
    if p.start.day == 1 and p.end == _month_end(p.end):
        months = (p.end.year - p.start.year) * 12 + p.end.month - p.start.month + 1
        end = p.start - timedelta(days=1)
        first = end.year * 12 + end.month - months  # zero-based month index of the new start
        return AskPeriod(start=date(first // 12, first % 12 + 1, 1), end=end)
    span = p.end - p.start
    end = p.start - timedelta(days=1)
    return AskPeriod(start=end - span, end=end)


def period_label(p: AskPeriod) -> str:
    """ "Jul–Sep 2026" for whole months (the way the app names VAT periods), else "10 Sep–19 Sep 2026"."""
    if p.start.day == 1 and p.end == _month_end(p.end):
        first = f"{p.start:%b}" if p.start.year == p.end.year else f"{p.start:%b %Y}"
        return (
            f"{p.end:%b %Y}" if (p.start.year, p.start.month) == (p.end.year, p.end.month) else f"{first}–{p.end:%b %Y}"
        )
    first = f"{p.start.day} {p.start:%b}" if p.start.year == p.end.year else f"{p.start.day} {p.start:%b %Y}"
    return f"{first}–{p.end.day} {p.end:%b %Y}"


def side(ev: LedgerEvent) -> tuple[str, int] | None:
    """("sales"|"purchases", sign) for events that reach the VAT return, mirroring accnomos_ledger.vat."""
    return vat_side(ev)


def vat_code(ev: LedgerEvent) -> str:
    """The code on the event's largest coded line ("-" when no line carries one)."""
    coded = [ln for ln in ev.lines if ln.vat_code is not None]
    if not coded:
        return "-"
    return max(coded, key=lambda ln: ln.debit + ln.credit).vat_code.value  # type: ignore[union-attr]


def _boxes(events: list[LedgerEvent], p: AskPeriod, schemes: Schemes | None = None) -> dict[str, str]:
    if schemes is not None:
        ret = scheme_return(schemes[1], schemes[0], period_key_for(p.start), p.start, p.end).ret
    else:
        ret = compute_vat_return(events, period_key_for(p.start), p.start, p.end)
    return {f"box{i}": v for i, v in box_amounts(ret).items()}


def _scheme_facts(ctx: SchemeContext, sb: SchemeBooks, p: AskPeriod) -> dict[str, Any]:
    """How this period's boxes were worked out under the business's VAT scheme(s), for questions like "what flat rate
    am I on?" or "when is my next instalment?". Every figure is code's."""
    out = scheme_return(sb, ctx, period_key_for(p.start), p.start, p.end)
    view = scheme_view(ctx, out, p.start, p.end)
    parts = []
    for seg in view.segments:
        part: dict[str, Any] = {"from": seg.start.isoformat(), "to": seg.end.isoformat(), "scheme": seg.label}
        if seg.scheme == "flat_rate":
            part |= {
                "flat_rate_turnover_incl_vat": seg.turnover,
                "rates_used": [{"from": c.start.isoformat(), "percent": c.percent, "tax": c.tax} for c in seg.calcs],
                "limited_cost_business": seg.limited_cost,
                "relevant_goods": seg.relevant_goods,
                "capital_goods_vat_claimed": seg.capital_vat,
            }
        if seg.cash_basis:
            part |= {"payments_counted": seg.payments, "vat_on_unpaid_brought_in": seg.unpaid_brought_in_vat}
        parts.append(part)
    facts: dict[str, Any] = {"summary": view.summary, "parts": parts}
    if view.annual is not None:
        facts["annual_accounting"] = {
            "return_due": view.annual.return_due.isoformat(),
            "instalments": [{"due": i.due.isoformat(), "amount": i.amount} for i in view.annual.instalments],
            "balancing_payment": view.annual.balancing,
            "balancing_direction": view.annual.balancing_direction,
        }
    return facts


def _totals(events: list[LedgerEvent]) -> dict[str, Any]:
    sides: dict[str, dict[str, int]] = {s: {"net": 0, "vat": 0, "count": 0} for s in ("sales", "purchases")}
    codes: dict[str, dict[str, int]] = defaultdict(lambda: {"net": 0, "vat": 0, "count": 0})
    for ev in events:
        if (sd := side(ev)) is None or ev.net is None:
            continue
        name, sign = sd
        for bucket in (sides[name], codes[f"{name}:{vat_code(ev)}"]):
            bucket["net"] += sign * ev.net
            bucket["vat"] += sign * (ev.vat or 0)
            bucket["count"] += 1
    fmt = lambda b: {"net": pounds(b["net"]), "vat": pounds(b["vat"]), "count": b["count"]}  # noqa: E731
    return {
        **{name: fmt(b) for name, b in sides.items()},
        "by_vat_code": {k: fmt(b) for k, b in sorted(codes.items())},
    }


def _top(events: list[LedgerEvent], which: str) -> list[dict[str, Any]]:
    nets: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        if (sd := side(ev)) and sd[0] == which and ev.net is not None:
            name = (ev.counterparty or "").strip() or "(no name)"
            nets[name] += sd[1] * ev.net
            counts[name] += 1
    ranked = sorted(nets, key=lambda n: (-nets[n], n))[:TOP_N]
    return [{"name": n, "net": pounds(nets[n]), "count": counts[n]} for n in ranked]


def _largest(entries: list[tuple[str, LedgerEvent]]) -> list[dict[str, Any]]:
    priced = [(path, ev) for path, ev in entries if ev.net is not None and side(ev)]
    priced.sort(key=lambda pe: -abs((pe[1].net or 0) + (pe[1].vat or 0)))
    return [
        {
            "date": ev.date.isoformat(),
            "kind": ev.kind,
            "counterparty": ev.counterparty or "(no name)",
            "net": pounds(ev.net or 0),
            "vat": pounds(ev.vat or 0),
            "gross": pounds((ev.net or 0) + (ev.vat or 0)),
            "vat_code": vat_code(ev),
            "source": path,
        }
        for path, ev in priced[:TOP_N]
    ]


def _delta(now: str, before: str) -> str:
    return f"{Decimal(now) - Decimal(before):.2f}" if "." in now else str(int(now) - int(before))


def _pct(now: str, before: str) -> str | None:
    b = Decimal(before)
    return None if b == 0 else f"{(Decimal(now) - b) / abs(b) * 100:.1f}"


def _derived(this: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for i in (1, 3, 4, 5, 6, 7):
        out[f"box{i}_delta_vs_prev"] = _delta(this["vat"][f"box{i}"], prev["vat"][f"box{i}"])
    out["box5_change_pct_vs_prev"] = _pct(this["vat"]["box5"], prev["vat"]["box5"])
    for s in ("sales", "purchases"):
        out[f"{s}_net_delta_vs_prev"] = _delta(this["totals"][s]["net"], prev["totals"][s]["net"])
        out[f"{s}_net_change_pct_vs_prev"] = _pct(this["totals"][s]["net"], prev["totals"][s]["net"])
    # Box 5 is the absolute value of 3 - 4; say which way the money goes.
    owed = Decimal(this["vat"]["box3"]) - Decimal(this["vat"]["box4"])
    out["vat_position"] = "pay HMRC" if owed > 0 else "HMRC repays you" if owed < 0 else "nothing due"
    return out


async def _pending(books: Books) -> dict[str, int] | None:
    """Counts of proposals awaiting a decision, or None when there are too many files to read cheaply."""
    files = [f for f in await books.list_files(PROPOSALS) if f.name.endswith(".json")]
    if len(files) > PROPOSALS_CHEAP:
        return None
    raw = await asyncio.gather(*(books.storage.read(f.path) for f in files))
    statuses = [json.loads(r).get("status") for r in raw]
    return {"proposed": statuses.count("proposed"), "needs_a_look": statuses.count("needs_a_look")}


def _month_folders(entries: list[tuple[str, LedgerEvent]]) -> list[str]:
    return sorted({path.rsplit("/", 1)[0] + "/" for path, _ev in entries})


def _size(facts: dict[str, Any]) -> int:
    return len(json.dumps(facts, separators=(",", ":"), ensure_ascii=False).encode())


def _trim(facts: dict[str, Any]) -> None:
    """Shorten the lists until the pack fits FACTS_MAX_BYTES (VAT boxes and totals always stay)."""
    for n in (6, 4, 2, 0):
        if _size(facts) <= FACTS_MAX_BYTES:
            return
        for key in ("largest_transactions", "top_suppliers", "top_customers"):
            facts[key] = facts[key][:n]
        keep = {t["source"] for t in facts["largest_transactions"]}
        facts["sources"] = [s for s in facts["sources"] if not s.endswith(".json") or s in keep]
        for name in ("this_period", "previous_period"):
            codes = facts[name]["totals"]["by_vat_code"]
            if n < 4 and len(codes) > 4:
                facts[name]["totals"]["by_vat_code"] = dict(
                    sorted(codes.items(), key=lambda kv: -abs(Decimal(kv[1]["net"])))[:4]
                )


async def build_facts(
    books: Books, period: AskPeriod, business_name: str | None = None, cycle: VatCycle | None = None
) -> dict[str, Any]:
    """Everything an answer may quote about `period` and the period before it (VAT boxes under the saved schemes)."""
    prev = previous_period(period)
    entries = await books.list_event_entries(prev.start, period.end)
    ctx = await scheme_context(books, cycle or VatCycle())
    schemes: Schemes | None = None
    if ctx.settings.in_use:
        sb = await scheme_books(books, ctx, prev.start, period.end)
        if not ctx.needs_ledger:
            sb.events = [e for _p, e in entries]
        schemes = (ctx, sb)
    this_entries = [(p, e) for p, e in entries if period.start <= e.date <= period.end]
    prev_entries = [(p, e) for p, e in entries if prev.start <= e.date <= prev.end]

    def summarise(p: AskPeriod, ents: list[tuple[str, LedgerEvent]]) -> dict[str, Any]:
        evs = [e for _p, e in ents]
        return {
            "start": p.start.isoformat(),
            "end": p.end.isoformat(),
            "period_key": period_key_for(p.start),
            "label": period_label(p),
            "entries": len(evs),
            "vat": _boxes(evs, p, schemes),
            "totals": _totals(evs),
        }

    this, before = summarise(period, this_entries), summarise(prev, prev_entries)
    largest = _largest(this_entries)
    pending = await _pending(books)

    sources = _month_folders(this_entries + prev_entries) + [t["source"] for t in largest]
    returns = await books.list_files(VAT_RETURNS)
    sources += [f.path for f in returns if this["period_key"] in f.name or before["period_key"] in f.name][:4]
    if await books.workbook_ref():
        sources.append(WORKBOOK)
    if pending and (pending["proposed"] or pending["needs_a_look"]):
        sources.append(f"{PROPOSALS}/")

    facts: dict[str, Any] = {
        "business": business_name or None,
        "money": "GBP pounds; boxes 1-5 to 2 dp, boxes 6-9 whole pounds; negative = money back or a fall",
        "this_period": this,
        "previous_period": before,
        "derived": _derived(this, before),
        "top_suppliers": _top([e for _p, e in this_entries], "purchases"),
        "top_customers": _top([e for _p, e in this_entries], "sales"),
        "largest_transactions": largest,
        "pending_proposals": pending,
        **({"vat_scheme": _scheme_facts(*schemes, period)} if schemes else {}),
        "sources": list(dict.fromkeys(sources)) or [f"{EVENTS}/"],
    }
    _trim(facts)
    return facts


def vat_sources(facts: dict[str, Any]) -> list[str]:
    """The paths behind the VAT figures: the ledger folders (and any filed return)."""
    picked = [s for s in facts["sources"] if (s.startswith(EVENTS) and s.endswith("/")) or s.startswith(VAT_RETURNS)]
    return picked or facts["sources"][:1]
