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

No model call happens unless the summary is asked for with an AI set up; every figure the summary quotes is in
`summary.facts`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from accnomos_connectors.msgraph import GraphError
from accnomos_ledger.bank import BankLine
from app import cis as cis_mod
from app import cis_readings as cr
from app import contacts as cb
from app import dashboard as dash
from app import payroll as payroll_mod
from app import payrun
from app import profile as profile_mod
from app import property as pr
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


class Overview(BaseModel):
    today: date
    kind: profile_mod.ProfileKind
    features: list[str]
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
    m: Money | None = o["money"]
    if m:
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
    w: Week | None = o["week"]
    if w:
        facts["this_week"] = {
            "in": gbp(w.money_in_pence),
            "out": gbp(w.money_out_pence),
            "approved": w.approved,
            "proposed": w.proposed,
        }
    att = d.attention if isinstance(d.attention, dash.Attention) else None
    if att:
        facts["needs_doing"] = {
            "in_review": att.proposed + att.needs_a_look,
            "unmatched_bank_lines": att.unmatched_bank_lines,
            "overdue_invoices": att.overdue_invoices or 0,
        }
    owed = d.owed_to_you if isinstance(d.owed_to_you, dash.OwedToYou) else None
    if owed and owed.overdue:
        facts["overdue"] = {"invoices": owed.overdue, "amount": gbp(owed.overdue_pence)}
    a: Aged | None = o["aged"]
    if a and a.creditors.overdue_pence:
        facts["bills_overdue"] = gbp(a.creditors.overdue_pence)
    ds: list[Due] = o["deadlines"]
    if ds:
        facts["next_deadline"] = {"what": ds[0].title, "due": day(ds[0].due), "days_left": ds[0].days_left}
    return facts


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

    business = prof.kind != "personal"
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
    }
    summary = await home_summary.summarise(summary_facts(d, o), cfg)
    return Overview(
        today=today,
        kind=prof.kind,
        features=features,
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
