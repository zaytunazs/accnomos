"""Budgets: a monthly amount per profit and loss account for twelve months, and the Budget Summary and Budget
Variance reports. Stored as `_System/Accounting/budgets/<yyyy-mm>.json`, named by the budget's first month.

Amounts follow the P&L's signs (app/reports.py): income positive as income, costs positive as spending. The actuals
are the P&L's, as approved, month by month. Variance is actual − budget; it is favourable when income beats its
budget or a cost comes in under it. Code only; nothing posts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field, ValidationError

from accnomos_ledger.events import LedgerEvent
from app.books import Books, now
from app.chart import ACCOUNTING, ChartError, active_account, load_chart
from app.deadlines import add_months  # noqa: F401  (routes_reports uses bg.add_months)
from app.reports import _amounts, account_code, section_of
from app.validation import LENIENT, Pence, StrictBody

BUDGETS = f"{ACCOUNTING}/budgets"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_PENCE = 10_000_000_000


class BudgetError(ValueError):
    """The budget cannot be saved or reported as asked."""


class BudgetLineIn(StrictBody):
    account: str = Field(min_length=4, max_length=90)
    months: list[Pence] = Field(min_length=12, max_length=12)


class BudgetIn(StrictBody):
    name: str = Field("Budget", min_length=1, max_length=80)
    lines: list[BudgetLineIn] = Field(max_length=300)


class BudgetLine(BaseModel):
    account: str
    months: list[int]


class Budget(BaseModel):
    start: str  # "2026-04": the first of its twelve months
    name: str = "Budget"
    lines: list[BudgetLine] = []
    updated_by: str | None = None
    updated_at: datetime | None = None

    def first_day(self) -> date:
        return date(int(self.start[:4]), int(self.start[5:]), 1)

    def month_starts(self) -> list[date]:
        return [add_months(self.first_day(), i) for i in range(12)]


def check_start(start: str) -> str:
    if not MONTH_RE.fullmatch(start):
        raise BudgetError("A budget starts on a month, written YYYY-MM")
    return start


def _path(start: str) -> str:
    return f"{BUDGETS}/{check_start(start)}.json"


async def list_budgets(books: Books) -> list[Budget]:
    out = []
    for f in await books.list_files(BUDGETS):
        start = f.name.removesuffix(".json")
        if f.name.endswith(".json") and MONTH_RE.fullmatch(start) and (b := await get_budget(books, start)):
            out.append(b)
    return sorted(out, key=lambda b: b.start, reverse=True)


async def get_budget(books: Books, start: str) -> Budget | None:
    raw = await books.read_json(_path(start), None)
    if raw is None:
        return None
    try:
        return Budget.model_validate({**raw, "start": start}, **LENIENT)
    except ValidationError as exc:
        raise BudgetError(f"The budget file for {start} could not be read") from exc


async def save_budget(books: Books, start: str, body: BudgetIn, user: str) -> Budget:
    try:
        chart, _ = await load_chart(books)
    except ChartError as exc:
        raise BudgetError(str(exc)) from exc
    lines: dict[str, BudgetLine] = {}
    for ln in body.lines:
        try:
            acc = active_account(chart, ln.account)
        except ChartError as exc:
            raise BudgetError(str(exc)) from exc
        if section_of(acc.label) is None:
            raise BudgetError(f"{acc.label} is not a profit and loss account; budgets are for income and costs")
        if acc.label in lines:
            raise BudgetError(f"{acc.label} is in the budget twice")
        if any(abs(m) > MAX_PENCE for m in ln.months):
            raise BudgetError(f"{acc.label}: an amount is too big")
        lines[acc.label] = BudgetLine(account=acc.label, months=list(ln.months))
    budget = Budget(
        start=check_start(start),
        name=" ".join(body.name.split()) or "Budget",
        lines=sorted((ln for ln in lines.values() if any(ln.months)), key=lambda ln: account_code(ln.account) or 0),
        updated_by=user,
        updated_at=now(),
    )
    await books.storage.ensure_folder(BUDGETS)
    await books.write_json(_path(start), budget.model_dump(mode="json", exclude={"start"}))
    await books.audit(f"user:{user}", "budget_saved", {"start": start, "accounts": len(budget.lines)})
    return budget


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

SECTIONS = ("sales", "cost_of_sales", "overheads")


class SummaryRow(BaseModel):
    account: str
    section: str
    months: list[int]
    total_pence: int


class BudgetSummary(BaseModel):
    start: str
    name: str
    months: list[str]  # "Apr 2026" …
    rows: list[SummaryRow]
    section_totals: dict[str, list[int]]  # section -> 12 months
    net_profit: list[int]
    net_profit_total_pence: int


def summary(b: Budget) -> BudgetSummary:
    rows = [
        SummaryRow(
            account=ln.account, section=section_of(ln.account) or "", months=ln.months, total_pence=sum(ln.months)
        )
        for ln in b.lines
    ]
    totals = {s: [sum(r.months[i] for r in rows if r.section == s) for i in range(12)] for s in SECTIONS}
    net = [totals["sales"][i] - totals["cost_of_sales"][i] - totals["overheads"][i] for i in range(12)]
    return BudgetSummary(
        start=b.start,
        name=b.name,
        months=[f"{d:%b %Y}" for d in b.month_starts()],
        rows=rows,
        section_totals=totals,
        net_profit=net,
        net_profit_total_pence=sum(net),
    )


class VarianceRow(BaseModel):
    account: str
    section: str
    budget_pence: int
    actual_pence: int
    variance_pence: int  # actual − budget
    variance_percent: float | None  # of the budget, 1 dp; None when the budget is 0
    favourable: bool | None  # None when actual equals budget


class BudgetVariance(BaseModel):
    start: str
    name: str
    period_start: date
    period_end: date
    months: int
    rows: list[VarianceRow]
    totals: dict[str, VarianceRow]  # sales, cost_of_sales, overheads, net_profit
    basis: str = (
        "Actuals as approved (the profit and loss), against the budget for the same months; worked out by code."
    )


def _row(account: str, section: str, budget: int, actual: int) -> VarianceRow:
    var = actual - budget
    income = section in ("sales", "net_profit")
    return VarianceRow(
        account=account,
        section=section,
        budget_pence=budget,
        actual_pence=actual,
        variance_pence=var,
        variance_percent=round(var * 100 / abs(budget), 1) if budget else None,
        favourable=None if var == 0 else (var > 0) == income,
    )


def variance(b: Budget, events: Sequence[LedgerEvent], through: str | None = None) -> BudgetVariance:
    """Budget against actual for the budget's months up to and including `through` (YYYY-MM; default all twelve)."""
    starts = b.month_starts()
    n = 12
    if through:
        check_start(through)
        last = date(int(through[:4]), int(through[5:]), 1)
        if not starts[0] <= last <= starts[-1]:
            raise BudgetError(f"{through} is not one of this budget's months")
        n = starts.index(last) + 1
    period_start = starts[0]
    period_end = add_months(starts[n - 1], 1) - timedelta(days=1)
    actual = _amounts(e for e in events if period_start <= e.date <= period_end)
    budget = {ln.account: sum(ln.months[:n]) for ln in b.lines}
    accounts = sorted(
        {a for a in budget} | {a for a, v in actual.items() if v and section_of(a)},
        key=lambda a: (account_code(a) or 0, a),
    )
    rows = [_row(a, section_of(a) or "", budget.get(a, 0), actual.get(a, 0)) for a in accounts]
    totals = {
        s: _row(
            s,
            s,
            sum(r.budget_pence for r in rows if r.section == s),
            sum(r.actual_pence for r in rows if r.section == s),
        )
        for s in SECTIONS
    }
    net_b = totals["sales"].budget_pence - totals["cost_of_sales"].budget_pence - totals["overheads"].budget_pence
    net_a = totals["sales"].actual_pence - totals["cost_of_sales"].actual_pence - totals["overheads"].actual_pence
    totals["net_profit"] = _row("Net profit", "net_profit", net_b, net_a)
    return BudgetVariance(
        start=b.start, name=b.name, period_start=period_start, period_end=period_end, months=n, rows=rows, totals=totals
    )
