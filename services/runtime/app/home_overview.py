"""GET /books/home: everything the signed-in Home needs beyond GET /books/dashboard, worked out by code, plus a short
summary that the user's AI words and code checks (app/ai/home_summary.py).

Read, never written. Each section is worked out on its own, as in app/dashboard.py: one that cannot be read comes back
null and is named in `unavailable`, and the other cards still work. An auth failure (Graph 401/403) propagates.

Sections, and the rule each follows:
- money: money in and out of the bank this month so far and last month, from the imported bank lines (transfers
  between the user's own accounts and ignored lines left out), in pence.
- week: the last seven days of bank lines, and how many entries were approved and proposed (audit trail).
- aged: what customers owe and what the user owes, by age (app/contacts.py `aged`, the Aged report's own figures).
- itsa: the next Making Tax Digital for Income Tax quarterly update, for sole traders and anyone with a property
  register. Updates are due on 7 August, 7 November, 7 February and 7 May (gov.uk/guidance/use-making-tax-digital-
  for-income-tax/send-quarterly-updates, checked 28 Oct 2026 through gov.uk search results, as app/property.py).
- self_assessment: the online tax return for the previous tax year is due 31 January (the same page; also
  gov.uk/self-assessment-tax-returns/deadlines, checked 28 Oct 2026).
- payroll, cis, property: the draft or last pay run, the CIS settings and deductions suffered this tax year, the
  property register's income and costs this tax year (app/payroll.py, app/cis.py, app/property.py).
- snapshot: the year to date from app/reports.py `profit_and_loss` (turnover = sales; expenses = cost of sales +
  overheads; net profit), against the same span a year earlier, with the change as a whole percentage (null when last
  year's figure is 0), and the dashboard's own VAT figure (the next return's Box 5 and due date). The year starts on:
  a sole trader's accounting period start in Settings (profile `accounting_period_start`, 6 April unless changed);
  6 April (the tax year) for a landlord; otherwise 1 January, because no year end is saved for a company or
  partnership yet. The basis is the books' own: a sole trader's Income Tax setting (cash unless traditional is
  chosen, as app/routes_itsa.py), everyone else as approved (accruals).
- trend: app/reports.py `monthly_trend` for the 12 calendar months ending with this one, unchanged.
- cash_points: app/cashflow.py's 90-day forecast sampled weekly (`series`), null until a bank statement is imported.
Personal books get none of the three: a household has no turnover.

No model call happens unless the summary is asked for with an AI set up; every figure the summary quotes is in
`summary.facts`.
"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel

from accnomos_connectors.msgraph import GraphError
from accnomos_ledger import LedgerEvent
from accnomos_ledger.bank import BankLine
from app import cash_basis as cash_mod
from app import cashflow as cf_mod
from app import cis as cis_mod
from app import cis_readings as cr
from app import contacts as cb
from app import dashboard as dash
from app import home_items as hi
from app import payroll as payroll_mod
from app import payrun
from app import personal as pf
from app import profile as profile_mod
from app import property as pr
from app import reports as rp
from app.ai import home_summary
from app.ai.config import AiConfig
from app.books import AUDIT, Books
from app.deadlines import add_months

log = logging.getLogger(__name__)

NOT_MONEY = {"transfer", "ignored"}  # bank line statuses that are not money in or out of the business
ITSA_URL = "https://www.gov.uk/guidance/use-making-tax-digital-for-income-tax/send-quarterly-updates"
SA_URL = "https://www.gov.uk/self-assessment-tax-returns/deadlines"


class MoneyMonth(BaseModel):
    label: str  # "October 2026"
    start: date
    end: date  # today for the month we are in
    money_in_pence: int
    money_out_pence: int  # positive
    lines: int


class Money(BaseModel):
    this_month: MoneyMonth
    last_month: MoneyMonth


class Week(BaseModel):
    start: date
    end: date
    money_in_pence: int
    money_out_pence: int
    approved: int  # entries approved in the last seven days (audit trail)
    proposed: int  # entries the AI proposed in the last seven days


class AgedSide(BaseModel):
    total_pence: int
    overdue_pence: int  # past the due date (every bucket but "current")
    buckets: dict[str, int]  # "current" | "0-30" | "31-60" | "61-90" | "90+" -> pence
    documents: int


class Aged(BaseModel):
    debtors: AgedSide
    creditors: AgedSide


class Due(BaseModel):
    key: Literal["vat", "itsa", "self_assessment", "cis", "payroll"]
    title: str
    due: date
    days_left: int  # negative when late
    href: str
    source_url: str | None = None


class Itsa(BaseModel):
    tax_year: str
    period_end: date
    due: date
    days_left: int
    source_url: str = ITSA_URL


class Payroll(BaseModel):
    employees: int
    draft_period: str | None  # "2026-10": a run prepared and not confirmed yet
    draft_pay_date: date | None
    last_confirmed_period: str | None
    last_pay_date: date | None
    next_period: str  # the next month without a confirmed run


class Cis(BaseModel):
    subcontractor: bool
    contractor: bool
    status_label: str
    rate: int
    tax_year: str
    suffered_pence: int  # CIS deducted by contractors this tax year (tax paid on account)
    return_due: date | None  # contractors: the CIS300 for the last tax month
    pending_readings: int


class PropertyIncome(BaseModel):
    properties: int
    tax_year: str
    income_pence: int
    expenses_pence: int
    profit_pence: int


class YearFigures(BaseModel):
    turnover_pence: int
    expenses_pence: int
    net_profit_pence: int


class Changes(BaseModel):
    """Whole-percent change on the same span last year; null when last year's figure was 0."""

    turnover: int | None
    expenses: int | None
    net_profit: int | None


class VatPosition(BaseModel):
    """The dashboard's VAT figure (app/routes_vat.py `compute_deadlines`): the next return to file."""

    label: str  # "Jul–Sep 2026"
    amount_pence: int  # Box 5, positive
    direction: Literal["pay", "reclaim", "nil"]
    due: date
    days_left: int
    estimate: bool  # the period has not ended: Box 5 so far


class Snapshot(BaseModel):
    start: date
    end: date  # today
    period_label: str  # "6 Apr – 1 Nov 2026"
    year_start_rule: str  # how `start` was chosen, in words
    basis: str  # "accrual from approved entries" | "cash basis"
    accounting_basis: Literal["cash", "traditional"]
    turnover_pence: int  # sales (4000-4999)
    expenses_pence: int  # cost of sales + overheads (5000-8999)
    net_profit_pence: int  # negative is a loss
    last_year_start: date
    last_year_end: date
    last_year_label: str
    last_year: YearFigures
    change_pct: Changes
    vat_position: VatPosition | None  # None: not VAT registered, or the VAT tile could not be worked out
    entries: int


class Overview(BaseModel):
    today: date
    kind: profile_mod.ProfileKind
    features: list[str]
    snapshot: Snapshot | None = None  # None: personal books, or the ledger could not be read
    trend: rp.Trend | None = None
    cash_points: cf_mod.CashSeries | None = None  # None: no bank statement imported yet
    money: Money | None
    week: Week | None
    aged: Aged | None
    itsa: Itsa | None  # None: not a sole trader and no properties
    payroll: Payroll | None  # None: no payroll feature, or no employees and no runs
    cis: Cis | None  # None: CIS not used (Settings › CIS)
    property: PropertyIncome | None  # None: no properties registered
    deadlines: list[Due]  # soonest first
    summary: home_summary.HomeSummary
    unavailable: list[str]


# --------------------------------------------------------------------------- #
# Pure pieces
# --------------------------------------------------------------------------- #


def month_label(day: date) -> str:
    return f"{day:%B %Y}"


def money_between(lines: Sequence[BankLine], start: date, end: date) -> tuple[int, int, int]:
    """(in, out, lines) in pence over [start, end]; transfers between own accounts and ignored lines left out."""
    keep = [ln for ln in lines if start <= ln.date <= end and ln.status not in NOT_MONEY]
    return (
        sum(ln.amount_pence for ln in keep if ln.amount_pence > 0),
        -sum(ln.amount_pence for ln in keep if ln.amount_pence < 0),
        len(keep),
    )


def money(lines: Sequence[BankLine], today: date) -> Money:
    first = today.replace(day=1)
    last_first = add_months(first, -1)
    last_end = first - timedelta(days=1)

    def month(start: date, end: date) -> MoneyMonth:
        i, o, n = money_between(lines, start, end)
        return MoneyMonth(label=month_label(start), start=start, end=end, money_in_pence=i, money_out_pence=o, lines=n)

    return Money(this_month=month(first, today), last_month=month(last_first, last_end))


def week(lines: Sequence[BankLine], audit: Sequence[dict[str, Any]], today: date) -> Week:
    start = today - timedelta(days=6)
    i, o, _ = money_between(lines, start, today)
    recent = [x for x in audit if start <= x["ts"].date() <= today]
    return Week(
        start=start,
        end=today,
        money_in_pence=i,
        money_out_pence=o,
        approved=sum(x.get("action") == "approved" for x in recent),
        proposed=sum(x.get("action") == "proposed" for x in recent),
    )


def aged_side(table: cb.AgedTable) -> AgedSide:
    return AgedSide(
        total_pence=table.total_pence,
        overdue_pence=table.total_pence - table.buckets.get("current", 0),
        buckets=table.buckets,
        documents=sum(len(r.documents) for r in table.rows),
    )


def update_due(period_end: date) -> date:
    """MTD Income Tax quarterly update for a standard period: the 7th of the month after the period ends,
    5 Jul -> 7 Aug, 5 Oct -> 7 Nov, 5 Jan -> 7 Feb, 5 Apr -> 7 May (ITSA_URL)."""
    return add_months(date(period_end.year, period_end.month, 1), 1).replace(day=7)


def next_itsa(today: date) -> Itsa:
    """The next quarterly update not yet past its deadline (standard periods)."""
    year = pr.tax_year_of(today)
    candidates: list[tuple[str, date]] = []
    for y in (year, pr.tax_year_of(pr.tax_year_bounds(year)[1] + timedelta(days=1))):
        candidates += [(y, end) for end in pr.quarter_ends(y)]
    # The previous tax year's last update (5 Apr -> 7 May) can still be ahead early in a tax year.
    prev = pr.tax_year_of(pr.tax_year_bounds(year)[0] - timedelta(days=1))
    candidates.insert(0, (prev, pr.quarter_ends(prev)[-1]))
    tax_year, end = next((y, e) for y, e in candidates if update_due(e) >= today)
    due = update_due(end)
    return Itsa(tax_year=tax_year, period_end=end, due=due, days_left=(due - today).days)


def self_assessment_due(today: date) -> date:
    """31 January after the end of the last complete tax year (the online return)."""
    jan = date(today.year, 1, 31)
    return jan if today <= jan else date(today.year + 1, 1, 31)


def payroll_view(runs: Sequence[payroll_mod.PayRun], employees: int, today: date) -> Payroll:
    draft = next((r for r in sorted(runs, key=lambda r: r.period_start) if r.status == "draft"), None)
    confirmed = [r for r in runs if r.status == "confirmed"]
    last = max(confirmed, key=lambda r: r.period_start, default=None)
    nxt = add_months(last.period_start, 1) if last else today.replace(day=1)
    return Payroll(
        employees=employees,
        draft_period=draft.period if draft else None,
        draft_pay_date=draft.pay_date if draft else None,
        last_confirmed_period=last.period if last else None,
        last_pay_date=last.pay_date if last else None,
        next_period=f"{nxt:%Y-%m}",
    )


def deadlines(
    today: date,
    vat: Any,
    itsa: Itsa | None,
    sa: bool,
    cis: Cis | None,
    payroll: Payroll | None,
) -> list[Due]:
    out: list[Due] = []

    def add(key: Any, title: str, due: date, href: str, url: str | None = None) -> None:
        out.append(Due(key=key, title=title, due=due, days_left=(due - today).days, href=href, source_url=url))

    if vat is not None and not isinstance(vat, dash.TileError):
        nxt = vat.due or vat.current
        add("vat", f"VAT return {nxt.label}", nxt.deadline, "/vat")
    if itsa:
        add(
            "itsa",
            f"Income Tax quarterly update to {itsa.period_end.day} {itsa.period_end:%b %Y}",
            itsa.due,
            "/self-employment",
            ITSA_URL,
        )
    if sa:
        add(
            "self_assessment",
            "Self Assessment tax return and payment",
            self_assessment_due(today),
            "/self-employment",
            SA_URL,
        )
    if cis and cis.contractor and cis.return_due:
        add("cis", "CIS monthly return (CIS300)", cis.return_due, "/cis")
    if payroll and payroll.draft_pay_date:
        add("payroll", f"Pay run {payroll.draft_period} to confirm", payroll.draft_pay_date, "/payroll")
    return sorted(out, key=lambda d: d.due)


BASIS_WORDS = {"traditional": "accrual from approved entries", "cash": "cash basis"}


def _on(year: int, month: int, day: int) -> date:
    """The date, with the day clamped to the month (29 Feb in a non-leap year is 28 Feb; "02-31" is the last day)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def year_start(kind: str, settings: dict[str, Any], today: date) -> tuple[date, str]:
    """(the first day of the financial year holding `today`, how it was chosen)."""
    if kind == "sole_trader":
        mm, dd = (int(x) for x in str(settings.get("accounting_period_start") or "04-06").split("-"))
        rule = "your accounting year start in Settings" if (mm, dd) != (4, 6) else "the tax year (6 April)"
    elif kind == "landlord":
        mm, dd, rule = 4, 6, "the tax year (6 April)"
    else:
        mm, dd, rule = 1, 1, "the calendar year (no year end is saved for these books)"
    start = _on(today.year, mm, dd)
    return (start if start <= today else _on(today.year - 1, mm, dd)), rule


def a_year_earlier(day: date) -> date:
    return _on(day.year - 1, day.month, day.day)


def span_label(start: date, end: date) -> str:
    """ "6 Apr – 1 Nov 2026", or "1 Dec 2025 – 30 Nov 2026" across a new year."""
    first = f"{start.day} {start:%b}" if start.year == end.year else f"{start.day} {start:%b %Y}"
    return f"{first} – {end.day} {end:%b %Y}"


def change_pct(now: int, before: int) -> int | None:
    """Whole-percent change against `before`, rounded half up; None when `before` is 0. Against the size of last
    year's figure, so a loss that shrinks (-£1,000 to -£500) is +50%, not -50%."""
    if before == 0:
        return None
    pct = Decimal(now - before) * 100 / abs(Decimal(before))
    return int(pct.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def vat_position(vat: Any) -> VatPosition | None:
    """The dashboard's VAT tile figure, reused as it is: the return due next, or the period we are in."""
    if vat is None or isinstance(vat, dash.TileError):
        return None
    nxt = vat.due or vat.current
    return VatPosition(
        label=nxt.label,
        amount_pence=int((Decimal(nxt.box5) * 100).to_integral_value(rounding=ROUND_HALF_UP)),
        direction=nxt.box5_direction,
        due=nxt.deadline,
        days_left=nxt.days_remaining,
        estimate=nxt.days_to_end > 0,
    )


def snapshot(
    events: Sequence[LedgerEvent],
    today: date,
    kind: str,
    settings: dict[str, Any],
    basis: Literal["cash", "traditional"],
    vat: Any = None,
) -> Snapshot:
    """The year to date against the same span last year, from the P&L itself. For the cash basis, `events` is
    app/cash_basis.py's `cash_view(ledger).events`, as GET /reports/pl?basis=cash takes them."""
    start, rule = year_start(kind, settings, today)
    ly_start, ly_end = a_year_earlier(start), a_year_earlier(today)

    def figures(s: date, e: date) -> tuple[YearFigures, int]:
        pl = rp.profit_and_loss(events, s, e, basis)
        costs = pl.cost_of_sales.total_pence + pl.overheads.total_pence
        return YearFigures(
            turnover_pence=pl.sales.total_pence, expenses_pence=costs, net_profit_pence=pl.net_profit_pence
        ), pl.entries

    now, entries = figures(start, today)
    before, _ = figures(ly_start, ly_end)
    return Snapshot(
        start=start,
        end=today,
        period_label=span_label(start, today),
        year_start_rule=rule,
        basis=BASIS_WORDS[basis],
        accounting_basis=basis,
        **now.model_dump(),
        last_year_start=ly_start,
        last_year_end=ly_end,
        last_year_label=span_label(ly_start, ly_end),
        last_year=before,
        change_pct=Changes(
            turnover=change_pct(now.turnover_pence, before.turnover_pence),
            expenses=change_pct(now.expenses_pence, before.expenses_pence),
            net_profit=change_pct(now.net_profit_pence, before.net_profit_pence),
        ),
        vat_position=vat_position(vat),
        entries=entries,
    )


def _months_label(ms: Sequence[rp.TrendMonth]) -> str:
    a, b = ms[0].start, ms[-1].start
    return f"{a:%b %Y}" if a == b else f"{a:%b}–{b:%b %Y}" if a.year == b.year else f"{a:%b %Y}–{b:%b %Y}"


def trend_facts(trend: rp.Trend) -> dict[str, Any] | None:
    """Best and weakest complete month by net, and the last three complete months against the three before. The
    month we are in is left out (it is not over), and so are months with nothing in them."""
    done = trend.months[:-1]
    active = [m for m in done if m.sales_pence or m.purchases_pence]
    if len(active) < 2:
        return None

    def gbp(p: int) -> str:
        return home_summary.gbp(p)

    best = max(active, key=lambda m: (m.net_pence, m.start))
    worst = min(active, key=lambda m: (m.net_pence, m.start))
    out: dict[str, Any] = {
        "best_month": {"month": best.label, "net": gbp(best.net_pence)},
        "weakest_month": {"month": worst.label, "net": gbp(worst.net_pence)},
    }
    if len(done) >= 6:
        last3, prev3 = done[-3:], done[-6:-3]
        a, b = sum(m.net_pence for m in last3), sum(m.net_pence for m in prev3)
        out["last_3_months"] = {"months": _months_label(last3), "net": gbp(a)}
        out["previous_3_months"] = {"months": _months_label(prev3), "net": gbp(b)}
        out["direction"] = "up" if a > b else "down" if a < b else "level"
    return out


class Household(BaseModel):
    """A household's month (personal books only), from app/personal.py: this month so far and last month, budgets and
    the next regular bill code found on the statements (an estimate)."""

    this_month: pf.MonthlySummary
    last_month: pf.MonthlySummary
    next_bill: pf.RecurringItem | None = None


async def household(books: Books, lines: Sequence[BankLine], today: date) -> Household:
    cats = await pf.load_categories(books)
    budgets = await pf.load_budgets(books)
    rules = await pf.load_rules(books)
    overrides = await pf.load_overrides(books)
    every = list(lines)
    last = today.replace(day=1) - timedelta(days=1)
    bills = [
        i
        for i in pf.detect_recurring(every, cats, rules, overrides, today)
        if i.status != "stopped" and i.days_until >= 0
    ]
    return Household(
        this_month=pf.summarise_month(today.strftime("%Y-%m"), every, cats, budgets, rules, overrides),
        last_month=pf.summarise_month(last.strftime("%Y-%m"), every, cats, budgets, rules, overrides),
        next_bill=min(bills, key=lambda i: (i.days_until, i.label), default=None),
    )


def household_facts(h: Household, today: date) -> dict[str, Any]:
    """Every household figure the summary may quote, formatted by code."""

    def gbp(p: int) -> str:
        return home_summary.gbp(p)

    def month(m: pf.MonthlySummary, label: str) -> dict[str, Any]:
        return {"label": label, "in": gbp(m.income_pence), "out": gbp(m.spent_pence), "left": gbp(m.left_pence)}

    last_day = today.replace(day=1) - timedelta(days=1)
    out: dict[str, Any] = {
        "this_month": month(h.this_month, f"{month_label(today)} so far"),
        "last_month": month(h.last_month, month_label(last_day)),
        "over_budget": [
            {
                "category": c.name,
                "spent": gbp(c.spent_pence),
                "budget": gbp(c.budget_pence or 0),
                "over_by": gbp(-(c.remaining_pence or 0)),
            }
            for c in h.this_month.categories
            if c.state == "over"
        ],
        "near_budget": [
            {
                "category": c.name,
                "spent": gbp(c.spent_pence),
                "budget": gbp(c.budget_pence or 0),
                "left": gbp(c.remaining_pence or 0),
            }
            for c in h.this_month.categories
            if c.state == "near"
        ],
    }
    if h.this_month.uncategorised_count:
        out["uncategorised_lines"] = h.this_month.uncategorised_count
    b = h.next_bill
    if b:
        out["next_bill"] = {
            "what": b.label,
            "usual_amount": gbp(b.amount_pence),
            "due": f"{b.next_due.day} {b.next_due:%b %Y}",
            "days_left": b.days_until,
            "estimate": True,
        }
    return out


def summary_facts(d: dash.Dashboard, o: dict[str, Any]) -> dict[str, Any]:
    """The facts the summary may use, every figure already formatted by code (pounds to 2 dp, dates in words)."""

    def gbp(p: int | None) -> str | None:
        return None if p is None else home_summary.gbp(p)

    def day(x: date | None) -> str | None:
        return None if x is None else f"{x.day} {x:%b %Y}"  # no %-d: it is not portable to Windows

    facts: dict[str, Any] = {"today": day(d.today), "kind": o["kind"]}
    cash = d.cash if isinstance(d.cash, dash.Cash) else None
    if cash and cash.balance_pence is not None:
        facts["cash"] = {"balance": gbp(cash.balance_pence), "as_of": day(cash.as_of)}
    personal = o["kind"] == "personal"
    hh: Household | None = o.get("household")
    if personal and hh:
        facts["household"] = household_facts(hh, d.today)
    m: Money | None = o["money"]
    if m and not (personal and hh):
        facts["money"] = {
            "this_month": {
                "label": f"{m.this_month.label} so far",
                "in": gbp(m.this_month.money_in_pence),
                "out": gbp(m.this_month.money_out_pence),
            },
            "last_month": {
                "label": m.last_month.label,
                "in": gbp(m.last_month.money_in_pence),
                "out": gbp(m.last_month.money_out_pence),
            },
        }
    s: Snapshot | None = o.get("snapshot")
    if s:

        def change(pct: int | None) -> str | None:
            return None if pct is None else "no change" if pct == 0 else f"{'up' if pct > 0 else 'down'} {abs(pct)}%"

        ytd: dict[str, Any] = {"period": s.period_label, "basis": s.basis, "last_year_period": s.last_year_label}
        for key, now, before, pct in (
            ("turnover", s.turnover_pence, s.last_year.turnover_pence, s.change_pct.turnover),
            ("expenses", s.expenses_pence, s.last_year.expenses_pence, s.change_pct.expenses),
            ("net_profit", s.net_profit_pence, s.last_year.net_profit_pence, s.change_pct.net_profit),
        ):
            ytd[key] = gbp(now)
            ytd[f"{key}_last_year"] = gbp(before)
            if (words := change(pct)) is not None:
                ytd[f"{key}_vs_last_year"] = words
        facts["year_to_date"] = ytd
    t: rp.Trend | None = o.get("trend")
    if t and (tf := trend_facts(t)):
        facts["monthly_trend"] = tf
    cs: cf_mod.CashSeries | None = o.get("cash_points")
    if cs:
        facts["cash_forecast"] = {
            "days": 90,
            "lowest": gbp(cs.lowest_balance_pence),
            "lowest_on": day(cs.lowest_on),
            "goes_below_zero": cs.below_zero_on is not None,
            **({"below_zero_from": day(cs.below_zero_on)} if cs.below_zero_on else {}),
        }
    w: Week | None = o["week"]
    if w:
        facts["this_week"] = {
            "in": gbp(w.money_in_pence),
            "out": gbp(w.money_out_pence),
            "approved": w.approved,
            "proposed": w.proposed,
        }
    att = d.attention if isinstance(d.attention, dash.Attention) else None
    if att and personal:
        # A household matches no bank lines to a ledger: what waits is receipts in Review and lines with no category.
        # Only counts above zero: "there are 0 receipts in Review" is not worth a sentence in a household's summary.
        todo = {
            "in_review": att.proposed + att.needs_a_look,
            "uncategorised_bank_lines": hh.this_month.uncategorised_count if hh else 0,
        }
        if todo := {k: v for k, v in todo.items() if v}:
            facts["needs_doing"] = todo
    elif att:
        facts["needs_doing"] = {
            "in_review": att.proposed + att.needs_a_look,
            "unmatched_bank_lines": att.unmatched_bank_lines,
            "overdue_invoices": att.overdue_invoices or 0,
        }
    owed = d.owed_to_you if isinstance(d.owed_to_you, dash.OwedToYou) and not personal else None
    if owed and owed.overdue:
        facts["overdue"] = {"invoices": owed.overdue, "amount": gbp(owed.overdue_pence)}
    a: Aged | None = None if personal else o["aged"]
    if a and a.creditors.overdue_pence:
        facts["bills_overdue"] = gbp(a.creditors.overdue_pence)
    # The next deadline still ahead (today counts): a date already gone, such as a draft pay run's pay date, is not
    # what comes next (the Deadlines card still lists it).
    ds: list[Due] = [x for x in o["deadlines"] if x.days_left >= 0]
    if ds:
        facts["next_deadline"] = {"what": ds[0].title, "due": day(ds[0].due), "days_left": ds[0].days_left}
    return facts


def summary_items(
    d: dash.Dashboard,
    o: dict[str, Any],
    today: date,
    goals: Sequence[Any],
    unclosed_month: tuple[str, str] | None,
) -> list[hi.Draft]:
    """Home's to-do list (app/home_items.py), from the same figures as the tiles and cards."""
    att = d.attention if isinstance(d.attention, dash.Attention) else None
    proposed, look = (att.proposed, att.needs_a_look) if att else (0, 0)
    if o["kind"] == "personal":
        hh: Household | None = o.get("household")
        last_day = today.replace(day=1) - timedelta(days=1)
        return hi.household_items(
            today=today,
            proposed=proposed,
            needs_a_look=look,
            household=hh,
            this_month_label=f"{month_label(today)} so far",
            last_month_label=month_label(last_day),
            goals=goals,
        )
    owed = d.owed_to_you if isinstance(d.owed_to_you, dash.OwedToYou) else None
    a: Aged | None = o["aged"]
    cs: cf_mod.CashSeries | None = o.get("cash_points")
    s: Snapshot | None = o.get("snapshot")
    cash = d.cash if isinstance(d.cash, dash.Cash) else None
    return hi.business_items(
        today=today,
        proposed=proposed,
        needs_a_look=look,
        unmatched_bank_lines=att.unmatched_bank_lines if att else 0,
        overdue_invoices=(owed.overdue or 0) if owed else 0,
        overdue_pence=(owed.overdue_pence or 0) if owed else 0,
        # A late VAT, CIS or tax return stays on the list; a pay day already gone is not a deadline any more.
        deadlines=[x for x in o["deadlines"] if x.days_left >= 0 or x.key != "payroll"][:3],
        below_zero_on=cs.below_zero_on if cs else None,
        lowest_pence=cs.lowest_balance_pence if cs else None,
        lowest_on=cs.lowest_on if cs else None,
        bills_overdue_pence=a.creditors.overdue_pence if a else 0,
        unclosed_month=unclosed_month if s and s.entries else None,  # empty books have nothing to close
        goals=goals,
        ytd=(
            {"turnover": s.turnover_pence, "change_pct": s.change_pct.turnover, "period": s.period_label}
            if s and s.turnover_pence
            else None
        ),
        cash=(cash.balance_pence, cash.as_of) if cash and cash.balance_pence is not None and cash.as_of else None,
    )


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


class _Reads:
    """As app/dashboard.py: a failing read blanks its section (named in `unavailable`); auth failures propagate."""

    def __init__(self) -> None:
        self.missing: list[str] = []

    async def run[T](self, name: str, work: Callable[[], Awaitable[T]]) -> T | None:
        try:
            return await work()
        except GraphError as exc:
            if exc.status in (401, 403):
                raise
        except Exception:  # noqa: BLE001 - one section must not take Home down
            pass
        log.exception("home: %s could not be worked out", name)
        self.missing.append(name)
        return None


async def build(
    books: Books,
    today: date,
    first_vat_month: int,
    vat_months: int,
    *,
    vat_assumed: bool = False,
    cfg: AiConfig | None = None,
) -> Overview:
    reads = _Reads()
    d = await dash.build(books, today, first_vat_month, vat_months, vat_assumed=vat_assumed)
    prof = await dash._profile_or_default(books)  # noqa: SLF001 - the same lenient read Home's tiles use
    features = list(prof.features)
    lines = await reads.run("bank", books.stored_bank_lines)
    audit = await reads.run("audit", lambda: dash.read_audit(books, AUDIT, months=1)) or []

    async def aged() -> Aged:
        contacts, ledger, _ = await cb.contact_book(books)
        t = cb.aged(contacts, ledger, today)
        return Aged(debtors=aged_side(t.debtors), creditors=aged_side(t.creditors))

    async def props() -> PropertyIncome | None:
        properties = await pr.load_properties(books)
        if not properties:
            return None
        year = pr.tax_year_of(today)
        start, end = pr.tax_year_bounds(year)
        s = pr.summarise(
            await books.list_events(start, min(today, end)),
            properties,
            await pr.load_tags(books),
            await pr.load_settings(books),
            year,
            today,
            None,
        )
        return PropertyIncome(
            properties=len(properties),
            tax_year=year,
            income_pence=s.mine.income,
            expenses_pence=s.mine.expenses,
            profit_pence=s.mine.profit,
        )

    async def cis() -> Cis | None:
        settings = await cis_mod.load_settings(books)
        if not (settings.subcontractor or settings.contractor):
            return None
        year = cis_mod.tax_year_label(today)
        ys, ye = cis_mod.tax_year_bounds(year)
        suffered = cis_mod.suffered_in(await books.list_events(ys, ye), ys, ye)
        this_start, _ = cis_mod.tax_month(today)
        _, last_end = cis_mod.tax_month(this_start - timedelta(days=1))
        return Cis(
            subcontractor=settings.subcontractor,
            contractor=settings.contractor,
            status_label=cis_mod.STATUS_LABELS[settings.status],
            rate=settings.rate,
            tax_year=year,
            suffered_pence=sum(suffered.values()),
            return_due=cis_mod.return_due(last_end) if settings.contractor else None,
            pending_readings=len(await cr.list_readings(books, "pending")),
        )

    async def payroll() -> Payroll | None:
        runs = await payroll_mod.list_runs(books)
        employees = await payrun.load_employees(books)
        if not runs and not employees:
            return None
        return payroll_view(runs, len(employees), today)

    async def basis() -> Literal["cash", "traditional"]:
        if prof.kind != "sole_trader":
            return "traditional"
        from app.routes_itsa import saved_basis  # the Income Tax setting; a lazy import keeps the routers apart

        return await saved_basis(books)

    async def snap() -> Snapshot:
        b = await basis()
        events = cash_mod.cash_view(await cb.load_ledger(books)).events if b == "cash" else await books.list_events()
        return snapshot(events, today, prof.kind, prof.settings, b, d.vat if d.vat_applies else None)

    async def trend() -> rp.Trend:
        return rp.monthly_trend(await books.list_events(*rp.trend_window(today)), today)

    async def cash_points() -> cf_mod.CashSeries | None:
        if not lines:  # no bank statement imported yet: Home says how to get a forecast
            return None
        return cf_mod.series(await cf_mod.build(books, today))

    business = prof.kind != "personal"
    household_v = (
        await reads.run("household", lambda: household(books, lines or [], today))
        if not business and lines is not None
        else None
    )
    snapshot_v = await reads.run("snapshot", snap) if business else None
    trend_v = await reads.run("trend", trend) if business else None
    cash_v = await reads.run("cash forecast", cash_points) if business else None
    aged_v = await reads.run("aged", aged) if "invoices" in features or business else None
    property_v = await reads.run("property", props)
    cis_v = await reads.run("cis", cis) if business else None
    payroll_v = await reads.run("payroll", payroll) if "payroll" in features else None
    itsa_v = next_itsa(today) if "self_employment" in features or property_v else None
    sa = prof.kind == "sole_trader" or property_v is not None
    o: dict[str, Any] = {
        "kind": prof.kind,
        "money": money(lines, today) if lines is not None else None,
        "week": week(lines, audit, today) if lines is not None else None,
        "aged": aged_v,
        "deadlines": deadlines(today, d.vat, itsa_v, sa, cis_v, payroll_v),
        "snapshot": snapshot_v,
        "trend": trend_v,
        "cash_points": cash_v,
        "household": household_v,
    }

    async def goals_now() -> list[Any]:
        from app import goals as gm  # lazy: goals read purchases and bank lines only when the books have goals

        gs = await gm.load_goals(books)
        if not gs:
            return []
        data = await gm.load_data(books, gs, not business, today)
        return [gm.progress(g, data, today) for g in gs]

    async def unclosed() -> tuple[str, str] | None:
        from app import month_end as me  # lazy: keeps the routers apart

        month = me.previous_month(today)
        record = await me.load_record(books, month)
        return None if record.closes else (month, me.month_label(month))

    goals_v = await reads.run("goals", goals_now) or []
    unclosed_v = await reads.run("month-end", unclosed) if business else None
    drafts = summary_items(d, o, today, goals_v, unclosed_v)
    summary = await home_summary.summarise(summary_facts(d, o), cfg, drafts)
    return Overview(
        today=today,
        kind=prof.kind,
        features=features,
        snapshot=snapshot_v,
        trend=trend_v,
        cash_points=cash_v,
        money=o["money"],
        week=o["week"],
        aged=aged_v,
        itsa=itsa_v,
        payroll=payroll_v,
        cis=cis_v,
        property=property_v,
        deadlines=o["deadlines"],
        summary=summary,
        unavailable=reads.missing + d.unavailable,
    )
