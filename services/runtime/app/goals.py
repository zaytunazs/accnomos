"""Goals: targets the owner sets for the business or the household, tracked by code against their own books.

Kept in the user's own folder, `_System/goals.json`. Four kinds:

* save        put aside a sum by a date ("£1,000 for the school fee by 1 September"). Progress is either the
              amount the owner says is put aside (`measure="manual"`), or money in minus money out on the
              imported bank lines since the goal started (`measure="net_cash"`), plus anything put aside by hand.
* spend_cap   keep spending (all, or one focus such as "Groceries" or "coffee") under a limit for the goal's dates.
* spend_less  cut spending (all, or one focus) by a percentage against the same span a year earlier, or the span
              just before the goal when there is no year-earlier spending.
* earn        reach a sales figure (business: sales in the P&L, as approved; household: money in on the bank lines).

Rules of the house, as everywhere else:
* Money is whole pence and every figure, status and suggestion figure is worked out here, in code. A model, when one
  is set up, only words the suggestions from these facts, and code checks its numbers (app/ai/goals.py).
* A goal never posts, changes or approves anything in the books; it only reads them.
* Spending is: business books, approved purchases before VAT (app/purchases.py, the Spending page's own figures);
  household books, money out on the bank lines (transfers and ignored lines left out), categorised by the
  household rules (app/personal.py). A focus matches a category name exactly (any case), else any category,
  supplier, receipt item or bank-line description that contains it.
* Status is pace against a straight-line plan from the goal's start to its end: what an even pace would have
  reached by today. It is a plain comparison, not a forecast; the run-rate figure is labelled an estimate.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from accnomos_ledger import LedgerEvent
from accnomos_ledger.bank import BankLine
from app import personal as pf
from app import reports as rp
from app.books import SYSTEM, Books, now
from app.facts import pounds
from app.purchases import Purchase, load_purchases
from app.validation import LENIENT, Day, Pence, StrictBody

GOALS = f"{SYSTEM}/goals.json"
MAX_GOALS = 30
MAX_PENCE = 10_000_000_000

GoalKind = Literal["save", "spend_cap", "spend_less", "earn"]
GoalScope = Literal["business", "personal"]
Measure = Literal["manual", "net_cash"]
Status = Literal["not_started", "on_track", "at_risk", "off_track", "reached", "missed", "over_limit", "no_data"]

STATUS_LABELS: dict[str, str] = {
    "not_started": "Not started",
    "on_track": "On track",
    "at_risk": "At risk",
    "off_track": "Off track",
    "reached": "Reached",
    "missed": "Missed",
    "over_limit": "Over limit",
    "no_data": "Not enough data",
}
# How a status should look: favourable / warning / negative / neutral (the web maps these to badge styles).
TONE: dict[str, str] = {
    "not_started": "neutral",
    "on_track": "positive",
    "at_risk": "warning",
    "off_track": "negative",
    "reached": "positive",
    "missed": "negative",
    "over_limit": "negative",
    "no_data": "neutral",
}
KIND_LABELS = {
    "save": "Savings goal",
    "spend_cap": "Spending limit",
    "spend_less": "Spend less",
    "earn": "Sales target",
}

ON_TRACK_SHARE = 0.95  # save / earn: at least 95% of the even-pace amount
AT_RISK_SHARE = 0.75  # at least 75%: at risk; below: off track
OVER_PACE_SLACK = 1.15  # spending: up to 15% over the even pace is "at risk"
MIN_SHARE_FOR_RUN_RATE = 0.1  # a run-rate is only shown once a tenth of the period has gone
DRIVERS = 4


class GoalError(ValueError):
    """A goal that cannot be saved; the message is shown to the user."""


def _tidy(v: str | None) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())
    return v or None


class GoalIn(StrictBody):
    name: str = Field(min_length=1, max_length=80)
    kind: GoalKind
    scope: GoalScope | None = None  # defaults from the books: a household's goals are personal
    start: Day
    end: Day
    target_pence: Pence | None = Field(default=None, gt=0, le=MAX_PENCE)  # save / spend_cap / earn
    percent: int | None = Field(default=None, ge=1, le=90)  # spend_less: cut by this many per cent
    focus: str | None = Field(default=None, max_length=60)  # spend goals: a category or a word ("coffee")
    measure: Measure = "manual"  # save only
    saved_pence: Pence = Field(default=0, ge=0, le=MAX_PENCE)  # save: put aside by hand so far
    note: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        t = _tidy(v)
        if not t:
            raise ValueError("name is empty")
        return t

    @field_validator("focus", "note")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _tidy(v)

    @model_validator(mode="after")
    def _shape(self) -> GoalIn:
        check_shape(self)
        return self


def check_shape(g: GoalIn) -> None:
    if g.end < g.start:
        raise ValueError("the end date is before the start date")
    if (g.end - g.start).days > 3 * 366:
        raise ValueError("a goal can run for at most three years")
    if g.kind == "spend_less":
        if g.percent is None:
            raise ValueError("say by how many per cent to cut spending")
    elif g.target_pence is None:
        raise ValueError("give the target amount")
    if g.kind not in ("spend_cap", "spend_less") and g.focus:
        raise ValueError("only spending goals take a focus")


class GoalPatch(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    start: Day | None = None
    end: Day | None = None
    target_pence: Pence | None = Field(default=None, gt=0, le=MAX_PENCE)
    percent: int | None = Field(default=None, ge=1, le=90)
    focus: str | None = Field(default=None, max_length=60)
    measure: Measure | None = None
    saved_pence: Pence | None = Field(default=None, ge=0, le=MAX_PENCE)
    note: str | None = Field(default=None, max_length=200)


class Goal(GoalIn):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=now)
    created_by: str | None = None


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


async def load_goals(books: Books) -> list[Goal]:
    out: list[Goal] = []
    raw = await books.read_json(GOALS, [])
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(Goal.model_validate(item, **LENIENT))
        except ValueError:
            continue  # one hand-edited goal that no longer reads must not hide the rest
    return out


async def _write(books: Books, goals: list[Goal]) -> None:
    payload = [g.model_dump(mode="json") for g in goals]
    await books._update_json(GOALS, [], lambda _old: payload)  # noqa: SLF001 - the same JSON writer as personal.py


async def add_goal(books: Books, body: GoalIn, user: str, scope: GoalScope) -> Goal:
    goals = await load_goals(books)
    if len(goals) >= MAX_GOALS:
        raise GoalError(f"At most {MAX_GOALS} goals")
    goal = Goal(**{**body.model_dump(), "scope": body.scope or scope}, created_by=user)
    await _write(books, [*goals, goal])
    await books.audit(f"user:{user}", "goal_saved", {"goal": goal.id, "change": "added", "kind": goal.kind})
    return goal


async def patch_goal(books: Books, goal_id: str, patch: GoalPatch, user: str) -> Goal:
    goals = await load_goals(books)
    for i, g in enumerate(goals):
        if g.id == goal_id:
            try:
                new = Goal.model_validate({**g.model_dump(), **patch.model_dump(exclude_unset=True)})
            except ValueError as exc:
                raise GoalError(_first_error(exc)) from exc
            goals[i] = new
            await _write(books, goals)
            await books.audit(f"user:{user}", "goal_saved", {"goal": goal_id, "change": "edited"})
            return new
    raise KeyError(goal_id)


async def delete_goal(books: Books, goal_id: str, user: str) -> None:
    goals = await load_goals(books)
    kept = [g for g in goals if g.id != goal_id]
    if len(kept) == len(goals):
        raise KeyError(goal_id)
    await _write(books, kept)
    await books.audit(f"user:{user}", "goal_saved", {"goal": goal_id, "change": "deleted"})


def _first_error(exc: ValueError) -> str:
    if isinstance(exc, ValidationError) and exc.errors():
        return str(exc.errors()[0].get("msg", exc)).removeprefix("Value error, ")
    return str(exc)


# --------------------------------------------------------------------------- #
# What the books say: spending, income and cash, in pence, by code
# --------------------------------------------------------------------------- #


class Spend(BaseModel):
    """One spending item for a span: its name and kind ("category", "item", "supplier")."""

    name: str
    kind: Literal["category", "item", "supplier"]
    pence: int


class Ledgerish:
    """Everything the goals read, loaded once: purchases, ledger events, bank lines and household rules."""

    def __init__(
        self,
        *,
        household: bool,
        purchases: Sequence[Purchase] = (),
        events: Sequence[LedgerEvent] = (),
        lines: Sequence[BankLine] = (),
        categories: Sequence[pf.Category] = (),
        rules: Sequence[pf.PersonalRule] = (),
        overrides: dict[str, str] | None = None,
    ) -> None:
        self.household = household
        self.purchases = list(purchases)
        self.events = list(events)
        self.lines = [ln for ln in lines if pf.counts(ln)]
        self.categories = list(categories)
        self.rules = list(rules)
        self.overrides = overrides or {}
        self._names = {c.id: c.name for c in self.categories}
        self._known = set(self._names)
        self._regular: set[str] | None = None

    def regular_payees(self) -> set[str]:
        """Household payees paid on a regular cycle (rent, bills, subscriptions; app/personal.py detect_recurring).
        They are left out of the biggest movers only: a monthly payment falling inside one span and not the other
        looks like a change in spending when it is only timing. Totals still count them."""
        if self._regular is None:
            if not (self.household and self.lines):
                self._regular = set()
            else:
                last = max(ln.date for ln in self.lines)
                found = pf.detect_recurring(self.lines, self.categories, self.rules, self.overrides, last)
                self._regular = {r.key for r in found}
        return self._regular

    # -- the spending rows a focus is matched against --------------------------------------------------------- #

    def _bank_rows(self, start: date, end: date) -> list[tuple[str, str, int]]:
        """(category name, description, pence out) for money out on the bank lines in [start, end]."""
        rows = []
        for ln in self.lines:
            if start <= ln.date <= end and ln.amount_pence < 0:
                cat, _how = pf.categorise(ln, self.rules, self.overrides, self._known)
                rows.append((self._names.get(cat, "Other"), ln.description, -ln.amount_pence))
        return rows

    def spent(self, start: date, end: date, focus: str | None) -> int:
        """Spending in [start, end], all of it or the focus's share."""
        f = (focus or "").casefold()
        if self.household:
            rows = self._bank_rows(start, end)
            if not f:
                return sum(p for _c, _d, p in rows)
            exact = [p for c, _d, p in rows if c.casefold() == f]
            if exact:
                return sum(exact)
            return sum(p for c, d, p in rows if f in c.casefold() or f in d.casefold())
        total = 0
        inside = [p for p in self.purchases if start <= p.date <= end]
        if not f:
            return sum(p.net_pence for p in inside)
        exact_cat = any(p.category.casefold() == f for p in inside)
        for p in inside:
            if exact_cat:
                total += p.net_pence if p.category.casefold() == f else 0
            elif f in p.category.casefold() or f in p.supplier.casefold():
                total += p.net_pence
            else:
                total += sum(i.net_pence for i in p.lines if f in i.description.casefold())
        return total

    def breakdown(self, start: date, end: date, focus: str | None) -> list[Spend]:
        """Where the money went in [start, end]: categories, then receipt items and suppliers (largest first).
        With a focus, only rows inside it."""
        f = (focus or "").casefold()
        cats: dict[str, int] = defaultdict(int)
        items: dict[str, int] = defaultdict(int)
        sups: dict[str, int] = defaultdict(int)
        if self.household:
            regular = self.regular_payees()
            for c, d, p in self._bank_rows(start, end):
                if f and not (f in c.casefold() or f in d.casefold()):
                    continue
                if pf.payee_key(d) in regular:
                    continue
                cats[c] += p
                sups[_payee(d)] += p
        for p in self.purchases:
            if not start <= p.date <= end:
                continue
            hit = not f or f in p.category.casefold() or f in p.supplier.casefold()
            if not self.household and hit:
                cats[p.category] += p.net_pence
                sups[p.supplier] += p.net_pence
            for i in p.lines:
                if hit or f in i.description.casefold():
                    items[_item_name(i.description)] += i.net_pence
        out = [Spend(name=k, kind="category", pence=v) for k, v in cats.items() if v > 0]
        out += [Spend(name=k, kind="item", pence=v) for k, v in items.items() if v > 0]
        out += [Spend(name=k, kind="supplier", pence=v) for k, v in sups.items() if v > 0]
        return out

    def income(self, start: date, end: date) -> int:
        if self.household:
            return sum(ln.amount_pence for ln in self.lines if start <= ln.date <= end and ln.amount_pence > 0)
        return rp.profit_and_loss(self.events, start, end).sales.total_pence

    def net_cash(self, start: date, end: date) -> int:
        return sum(ln.amount_pence for ln in self.lines if start <= ln.date <= end)

    def has_spending_before(self, day: date) -> bool:
        if self.household:
            return any(ln.date < day and ln.amount_pence < 0 for ln in self.lines)
        return any(p.date < day for p in self.purchases)

    def latest(self) -> date | None:
        """The last day the books have anything on (bank line or approved purchase or ledger entry)."""
        days = [ln.date for ln in self.lines] + [p.date for p in self.purchases] + [e.date for e in self.events]
        return max(days) if days else None


def _payee(description: str) -> str:
    words = pf.payee_key(description).split()
    return " ".join(words[:3]).title() if words else description[:30]


def _item_name(description: str) -> str:
    return " ".join(description.split())[:40]


# --------------------------------------------------------------------------- #
# Progress against a goal
# --------------------------------------------------------------------------- #


class Driver(BaseModel):
    """A spending row that moved: this span against the span before it (same length)."""

    name: str
    kind: Literal["category", "item", "supplier"]
    this_pence: int
    before_pence: int
    change_pence: int


class GoalProgress(BaseModel):
    goal: Goal
    kind_label: str
    status: Status
    status_label: str
    tone: Literal["positive", "warning", "negative", "neutral"]
    period_label: str  # "1 Nov 2026 – 30 Nov 2026"
    current_pence: int  # saved / spent / earned so far
    target_pence: int | None  # the target or limit (for spend_less: the baseline less the cut)
    target_label: str  # "£1,000.00 target", "£400.00 spending limit"
    baseline_pence: int | None = None  # spend_less: what the comparison span cost
    baseline_label: str | None = None
    plan_to_date_pence: int | None  # what an even pace would have reached by today
    percent: int | None  # current as a whole percentage of the target or limit (may pass 100)
    variance_pence: int | None  # + ahead of plan (save/earn) or under plan (spend); - behind / over
    variance_text: str  # "£40.00 behind plan to date."
    needed_text: str | None = None  # "About £120.00 a month to go." (save/earn) or "£85.00 left to spend."
    run_rate_pence: int | None = None  # at the same daily pace, by the end (an estimate)
    days_left: int
    as_of: date | None  # the last day the books have anything on
    source_text: str  # where the figure comes from
    drivers: list[Driver] = []
    suggestions: list[str] = []  # written by code from the figures above


def gbp(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    return f"{sign}£{abs(pence) / 100:,.2f}"


def day_label(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def _share(goal: Goal, today: date) -> float:
    total = (goal.end - goal.start).days + 1
    gone = (min(today, goal.end) - goal.start).days + 1
    return max(0.0, min(1.0, gone / total))


def _a_year_earlier(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year - 1, day=28)


def comparison_span(goal: Goal, data: Ledgerish, today: date) -> tuple[date, date, str]:
    """The span a spend_less goal is measured against, up to the same point: a year earlier when the books have
    spending then, else the same number of days just before the goal started."""
    upto = min(today, goal.end)
    ys, ye = _a_year_earlier(goal.start), _a_year_earlier(upto)
    if data.has_spending_before(ys + timedelta(days=1)) or data.spent(ys, ye, None) > 0:
        return ys, ye, "the same dates a year earlier"
    span = (upto - goal.start).days
    pe = goal.start - timedelta(days=1)
    return pe - timedelta(days=span), pe, "the same number of days just before"


def drivers(data: Ledgerish, goal: Goal, start: date, end: date) -> list[Driver]:
    """The rows that grew most against the same-length span just before, then the largest rows."""
    if end < start:
        return []
    days = (end - start).days
    pe = start - timedelta(days=1)
    ps = pe - timedelta(days=days)
    focus = goal.focus if goal.kind in ("spend_cap", "spend_less") else None
    now_rows: dict[tuple[Literal["category", "item", "supplier"], str], int] = {
        (s.kind, s.name): s.pence for s in data.breakdown(start, end, focus)
    }
    before = {(s.kind, s.name): s.pence for s in data.breakdown(ps, pe, focus)}
    rows = [
        Driver(name=n, kind=k, this_pence=p, before_pence=before.get((k, n), 0), change_pence=p - before.get((k, n), 0))
        for (k, n), p in now_rows.items()
    ]
    # Items and suppliers say more than a category the focus already names.
    rank = {"item": 0, "category": 1, "supplier": 2} if focus else {"category": 0, "item": 1, "supplier": 2}
    grew = sorted((r for r in rows if r.change_pence > 0), key=lambda r: (-r.change_pence, rank[r.kind]))
    big = sorted(rows, key=lambda r: (-r.this_pence, rank[r.kind]))
    out: list[Driver] = []
    seen: set[str] = set()
    for r in [*grew, *big]:
        key = r.name.casefold()
        if key in seen or (focus and key == focus.casefold()):
            continue
        seen.add(key)
        out.append(r)
        if len(out) == DRIVERS:
            break
    return out


def _status_up(current: int, target: int, plan: int, goal: Goal, today: date) -> Status:
    """save / earn: more is better."""
    if current >= target:
        return "reached"
    if today > goal.end:
        return "missed"
    if plan <= 100 or current >= plan * ON_TRACK_SHARE:  # under £1 of plan so far: too early to call
        return "on_track"
    return "at_risk" if current >= plan * AT_RISK_SHARE else "off_track"


def _status_down(current: int, limit: int, plan: int, goal: Goal, today: date) -> Status:
    """spend_cap / spend_less: less is better."""
    if current > limit:
        return "over_limit"
    if today > goal.end:
        return "reached"
    if current <= plan:
        return "on_track"
    return "at_risk" if current <= plan * OVER_PACE_SLACK else "off_track"


def progress(goal: Goal, data: Ledgerish, today: date) -> GoalProgress:
    share = _share(goal, today)
    upto = min(today, goal.end)
    days_left = max(0, (goal.end - today).days)
    period = f"{day_label(goal.start)} – {day_label(goal.end)}"
    as_of = data.latest()
    focus_words = f" on {goal.focus}" if goal.focus else ""
    base: dict[str, Any] = {
        "goal": goal,
        "kind_label": KIND_LABELS[goal.kind],
        "period_label": period,
        "days_left": days_left,
        "as_of": as_of,
    }
    started = today >= goal.start
    current = 0
    if goal.kind == "save":
        cash = data.net_cash(goal.start, upto) if goal.measure == "net_cash" and started else 0
        current = goal.saved_pence + max(0, cash)
        source = (
            f"Put aside by hand {gbp(goal.saved_pence)}, plus money in less money out on your bank lines since "
            f"{day_label(goal.start)}"
            if goal.measure == "net_cash"
            else "The amount you have recorded as put aside"
        )
    elif goal.kind == "earn":
        current = data.income(goal.start, upto) if started else 0
        source = (
            "Money in on your bank lines" if data.household else "Sales in your approved ledger, before VAT"
        ) + f" from {day_label(goal.start)}"
    else:
        current = data.spent(goal.start, upto, goal.focus) if started else 0
        source = (
            f"Money out on your bank lines{focus_words}, transfers left out"
            if data.household
            else f"Approved purchases{focus_words}, before VAT"
        ) + f", from {day_label(goal.start)}"
    if as_of:
        source += f"; books through {day_label(as_of)}"

    baseline = baseline_label = None
    if goal.kind == "spend_less":
        bs, be, how = comparison_span(goal, data, today)
        baseline = data.spent(bs, be, goal.focus)
        baseline_label = f"{gbp(baseline)} spent{focus_words} over {how} ({day_label(bs)} – {day_label(be)})"
        if baseline <= 0:
            return GoalProgress(
                **base,
                status="no_data",
                status_label=STATUS_LABELS["no_data"],
                tone="neutral",
                current_pence=current,
                target_pence=None,
                target_label=f"Cut by {goal.percent}%",
                baseline_pence=0,
                baseline_label="No spending to compare against yet",
                plan_to_date_pence=None,
                percent=None,
                variance_pence=None,
                variance_text="There is no earlier spending to compare with yet.",
                source_text=source,
                drivers=drivers(data, goal, goal.start, upto) if started else [],
            )
        # The limit is the comparison span cut by the percentage; that span already runs only to today, so the
        # plan to date is the limit itself.
        limit = baseline * (100 - (goal.percent or 0)) // 100
        target = limit
        plan = limit
        target_label = f"Cut by {goal.percent}%: at most {gbp(limit)} so far"
    else:
        target = goal.target_pence or 0
        plan = round(target * share)
        target_label = {
            "save": f"{gbp(target)} target",
            "earn": f"{gbp(target)} sales target",
            "spend_cap": f"{gbp(target)} spending limit{focus_words}",
        }[goal.kind]

    if not started:
        status: Status = "not_started"
    elif goal.kind in ("save", "earn"):
        status = _status_up(current, target, plan, goal, today)
    else:
        status = _status_down(current, target, plan, goal, today)

    up = goal.kind in ("save", "earn")
    variance = (current - plan) if up else (plan - current)
    if not started:
        vtext = f"Starts {day_label(goal.start)}."
    elif status == "reached" and up:
        vtext = f"Target reached: {gbp(current)} of {gbp(target)}."
    elif up:
        vtext = f"{gbp(variance)} ahead of plan to date." if variance >= 0 else f"{gbp(-variance)} behind plan to date."
    elif status == "over_limit":
        vtext = f"{gbp(current - target)} over the limit."
    else:
        vtext = f"{gbp(variance)} under plan to date." if variance >= 0 else f"{gbp(-variance)} above plan to date."

    needed = None
    if started and today <= goal.end:
        months_left = max(1.0, days_left / 30.4375)
        if up and current < target:
            per_month = -(-(target - current) * 100 // round(months_left * 100))  # rounded up to the penny
            needed = (
                f"{gbp(target - current)} still to go: about {gbp(per_month)} a month."
                if days_left > 31
                else f"{gbp(target - current)} still to go by {day_label(goal.end)}."
            )
        elif not up and goal.kind == "spend_cap" and current <= target:
            needed = f"{gbp(target - current)} left to spend by {day_label(goal.end)}."

    run_rate = None
    estimable = goal.kind not in ("spend_less",) and not (goal.kind == "save" and goal.measure == "manual")
    if started and today < goal.end and share >= MIN_SHARE_FOR_RUN_RATE and estimable:
        run_rate = round(current / share)

    drv = drivers(data, goal, goal.start, upto) if started and goal.kind != "earn" else []
    prog = GoalProgress(
        **base,
        status=status,
        status_label=STATUS_LABELS[status],
        tone=TONE[status],  # type: ignore[arg-type]
        current_pence=current,
        target_pence=target,
        target_label=target_label,
        baseline_pence=baseline,
        baseline_label=baseline_label,
        plan_to_date_pence=plan if started else None,
        percent=(current * 100 // target) if target else None,
        variance_pence=variance if started else None,
        variance_text=vtext,
        needed_text=needed,
        run_rate_pence=run_rate,
        source_text=source,
        drivers=drv,
    )
    prog.suggestions = suggestions(prog)
    return prog


def suggestions(p: GoalProgress) -> list[str]:
    """Plain, figure-checked suggestions written by code. Nothing here is advice beyond what the figures show."""
    g = p.goal
    out: list[str] = []
    if p.status in ("not_started", "reached") and g.kind in ("save", "earn"):
        return out
    worried = p.status in ("at_risk", "off_track", "over_limit", "missed")
    grew = [d for d in p.drivers if d.change_pence > 0]
    if g.kind in ("spend_cap", "spend_less", "save"):
        for d in grew[:2]:
            what = {"item": "on", "category": "on", "supplier": "with"}[d.kind]
            line = f"You have spent {gbp(d.this_pence)} {what} {d.name} so far, {gbp(d.change_pence)} more than the "
            line += "same number of days before."
            if worried and p.variance_pence is not None and p.variance_pence < 0:
                gap = -p.variance_pence
                share = "would cover the gap" if d.change_pence >= gap else "would close part of the gap"
                line += f" Bringing it back to {gbp(d.before_pence)} {share} of {gbp(gap)}."
            out.append(line)
        if not grew and p.drivers and worried:
            d = p.drivers[0]
            out.append(f"Your largest spending here is {d.name}: {gbp(d.this_pence)} so far.")
    if g.kind == "save" and g.measure == "manual" and p.status != "reached":
        out.append("Record what you put aside as you go, so the progress stays current.")
    if g.kind == "earn" and worried and p.needed_text:
        out.append(p.needed_text)
    if g.kind == "save" and worried and p.needed_text:
        out.append(p.needed_text)
    if g.kind == "spend_cap" and p.status == "over_limit":
        out.append(f"This goal is over its limit by {gbp((p.current_pence or 0) - (p.target_pence or 0))}.")
    return out[:3]


# --------------------------------------------------------------------------- #
# Everything the Goals page and Home need, in one go
# --------------------------------------------------------------------------- #


async def load_data(books: Books, goals: Sequence[Goal], household: bool, today: date) -> Ledgerish:
    if not goals:
        return Ledgerish(household=household)
    earliest = min(g.start for g in goals)
    # Comparison spans reach back a year before the earliest goal, and drivers a span before that.
    longest = max((g.end - g.start).days for g in goals)
    since = _a_year_earlier(earliest) - timedelta(days=longest + 1)
    lines = await books.stored_bank_lines()
    purchases = await load_purchases(books, since, today)
    events = [] if household else await books.list_events(since, today)
    if household:
        return Ledgerish(
            household=True,
            purchases=purchases,
            lines=lines,
            categories=await pf.load_categories(books),
            rules=await pf.load_rules(books),
            overrides=await pf.load_overrides(books),
        )
    return Ledgerish(household=False, purchases=purchases, events=events, lines=lines)


def facts(progress_list: Sequence[GoalProgress], today: date) -> dict[str, Any]:
    """What the model may word: every figure as pounds strings, exactly as code worked it out."""
    out = []
    for p in progress_list:
        g = p.goal
        out.append(
            {
                "name": g.name,
                "kind": p.kind_label,
                "focus": g.focus,
                "dates": p.period_label,
                "status": p.status_label,
                "so_far": pounds(p.current_pence),
                "target_or_limit": pounds(p.target_pence) if p.target_pence is not None else None,
                "plan_to_date": pounds(p.plan_to_date_pence) if p.plan_to_date_pence is not None else None,
                "difference_from_plan": pounds(p.variance_pence) if p.variance_pence is not None else None,
                "cut_percent": g.percent,
                "comparison": pounds(p.baseline_pence) if p.baseline_pence is not None else None,
                "days_left": p.days_left,
                "still_needed": p.needed_text,
                "biggest_movers": [
                    {
                        "name": d.name,
                        "this_span": pounds(d.this_pence),
                        "span_before": pounds(d.before_pence),
                        "change": pounds(d.change_pence),
                    }
                    for d in p.drivers
                ],
                "code_suggestions": p.suggestions,
            }
        )
    return {"today": today.isoformat(), "money": "GBP pounds", "goals": out}
