"""Basic personal finances, kept in the user's own books folder under `_System/personal/`.

What this is: household categories, a monthly budget per category, spend against budget from the bank
statements already imported (app/routes_bank.py), recurring bills and subscriptions found by code, savings
goals, and a monthly summary. What it is not: investment advice, a credit score or a tax calculation.

Rules of the house (same as the business side):

* Money is whole pence. Every figure is worked out here, in code; nothing here calls a model.
* Anything that is a guess is labelled one: the recurring list and goal plans say "estimate".
* Personal categorisation is its own rule set (`_System/personal/rules.json`). It reuses the bank-rule matcher
  (`app/bank_rules.py`: contains / equals / safe regex, amount range) but never touches the business bank rules
  or the ledger. Only money *out* is categorised; money in is "income". A line the rules do not recognise is
  "Other" and is counted and shown as uncategorised, never hidden.
* Lines marked as a transfer or ignored on the Bank page are left out of every total here.
"""

from __future__ import annotations

import calendar
import math
import re
import statistics
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from accnomos_ledger.bank import BankLine
from app.bank_rules import BankRule, BankRuleAction, BankRuleMatch, normalise_description, rule_matches
from app.books import SYSTEM, Books, now
from app.validation import LENIENT, Day, Pence, StrictBody

FOLDER = f"{SYSTEM}/personal"
CATEGORIES = f"{FOLDER}/categories.json"
BUDGETS = f"{FOLDER}/budgets.json"
RULES = f"{FOLDER}/rules.json"
GOALS = f"{FOLDER}/goals.json"
OVERRIDES = f"{FOLDER}/overrides.json"  # {bank line id: category id}, set by hand on one line

OTHER = "other"
MAX_CATEGORIES = 40
MAX_RULES = 300
MAX_GOALS = 50
MAX_PENCE = 10_000_000_000  # £100 million: a typo guard, not a limit anyone meets

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("housing", "Housing"),
    ("utilities", "Utilities"),
    ("groceries", "Groceries"),
    ("transport", "Transport"),
    ("insurance", "Insurance"),
    ("subscriptions", "Subscriptions"),
    ("eating_out", "Eating out"),
    ("health", "Health"),
    ("children", "Children"),
    ("savings", "Savings"),
    ("debt", "Debt repayments"),
    (OTHER, "Other"),
]


class PersonalError(ValueError):
    """A change the personal finance files cannot take (the route answers 409)."""


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #


class Category(BaseModel):
    id: str
    name: str


class CategoryIn(StrictBody):
    id: str | None = Field(default=None, max_length=40)  # absent for a new category
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _tidy(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is empty")
        return v


class CategoriesIn(StrictBody):
    categories: list[CategoryIn] = Field(max_length=MAX_CATEGORIES)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "category"


def default_categories() -> list[Category]:
    return [Category(id=i, name=n) for i, n in DEFAULT_CATEGORIES]


async def load_categories(books: Books) -> list[Category]:
    """The user's list, or the defaults. "Other" is always there, home of anything unrecognised."""
    out: list[Category] = []
    for raw in await books.read_json(CATEGORIES, None) or []:
        try:
            out.append(Category.model_validate(raw, **LENIENT))
        except ValueError:
            continue
    if not out:
        return default_categories()
    if all(c.id != OTHER for c in out):
        out.append(Category(id=OTHER, name="Other"))
    return out


async def save_categories(books: Books, body: CategoriesIn, user: str) -> list[Category]:
    """Replace the list. Ids are kept for existing categories (so budgets and rules follow a rename); a new one
    gets an id from its name. A category cannot be removed while a rule or a hand-set line still points at it."""
    old = {c.id: c for c in await load_categories(books)}
    taken: set[str] = set()
    names: set[str] = set()
    out: list[Category] = []
    for item in body.categories:
        if item.name.lower() in names:
            raise PersonalError(f"There are two categories called {item.name!r}")
        names.add(item.name.lower())
        if item.id is not None:
            if item.id not in old:
                raise PersonalError(f"No such category: {item.id}")
            cid = item.id
        else:
            base = cid = _slug(item.name)
            n = 2
            while cid in old or cid in taken:
                cid, n = f"{base}_{n}", n + 1
        if cid in taken:
            raise PersonalError("A category is listed twice")
        taken.add(cid)
        out.append(Category(id=cid, name=item.name))
    if OTHER not in taken:
        raise PersonalError('"Other" stays: it is where anything the rules do not recognise goes')
    removed = set(old) - taken
    if removed:
        used = {r.category_id for r in await load_rules(books)} | set((await load_overrides(books)).values())
        stuck = sorted(old[c].name for c in removed & used)
        if stuck:
            raise PersonalError(f"Still used by a rule or a line you categorised by hand: {', '.join(stuck)}")
        budgets = await load_budgets(books)
        await _write_budgets(books, {k: v for k, v in budgets.items() if k not in removed})
    await books._update_json(CATEGORIES, [], lambda _old: [c.model_dump() for c in out])
    await books.audit(f"user:{user}", "personal_categories_saved", {"count": len(out)})
    return out


# --------------------------------------------------------------------------- #
# Budgets: a monthly amount per category
# --------------------------------------------------------------------------- #


class BudgetsIn(StrictBody):
    budgets: dict[str, Pence]  # category id -> pence a month; 0 or absent = no budget


async def load_budgets(books: Books) -> dict[str, int]:
    raw = await books.read_json(BUDGETS, {})
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, int) and v > 0}


async def _write_budgets(books: Books, budgets: dict[str, int]) -> None:
    await books._update_json(BUDGETS, {}, lambda _old: budgets)


async def save_budgets(books: Books, body: BudgetsIn, user: str) -> dict[str, int]:
    known = {c.id for c in await load_categories(books)}
    for cid, pence in body.budgets.items():
        if cid not in known:
            raise PersonalError(f"No such category: {cid}")
        if not 0 <= pence <= MAX_PENCE:
            raise PersonalError("A budget is between £0 and £100,000,000 a month")
    out = {k: v for k, v in body.budgets.items() if v > 0}
    await _write_budgets(books, out)
    await books.audit(f"user:{user}", "personal_budgets_saved", {"count": len(out)})
    return out


# --------------------------------------------------------------------------- #
# Categorisation rules (a separate rule set from the business bank rules)
# --------------------------------------------------------------------------- #


class PersonalRuleIn(StrictBody):
    name: str = Field(default="", max_length=120)
    match: BankRuleMatch
    category_id: str = Field(min_length=1, max_length=40)
    amount_min_pence: int | None = None
    amount_max_pence: int | None = None


class PersonalRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    match: BankRuleMatch
    category_id: str
    amount_min_pence: int | None = None
    amount_max_pence: int | None = None
    created_at: datetime = Field(default_factory=now)


def _as_bank_rule(rule: PersonalRule) -> BankRule:
    """The shared matcher takes a BankRule; the category rides in `action.account`. Money out only."""
    return BankRule(
        id=rule.id,
        match=rule.match,
        direction="out",
        amount_min_pence=rule.amount_min_pence,
        amount_max_pence=rule.amount_max_pence,
        action=BankRuleAction(account=rule.category_id),
    )


async def load_rules(books: Books) -> list[PersonalRule]:
    out: list[PersonalRule] = []
    for raw in await books.read_json(RULES, []):
        try:
            out.append(PersonalRule.model_validate(raw, **LENIENT))
        except ValueError:
            continue
    return out


async def _write_rules(books: Books, rules: list[PersonalRule]) -> None:
    payload = [r.model_dump(mode="json") for r in rules]
    await books._update_json(RULES, [], lambda _old: payload)


async def add_rule(books: Books, body: PersonalRuleIn, user: str) -> PersonalRule:
    if body.category_id not in {c.id for c in await load_categories(books)}:
        raise PersonalError(f"No such category: {body.category_id}")
    rules = await load_rules(books)
    if len(rules) >= MAX_RULES:
        raise PersonalError(f"At most {MAX_RULES} rules")
    rule = PersonalRule(**body.model_dump())
    await _write_rules(books, [*rules, rule])
    await books.audit(f"user:{user}", "personal_rule_added", {"rule": rule.id, "category": rule.category_id})
    return rule


async def delete_rule(books: Books, rule_id: str, user: str) -> None:
    rules = await load_rules(books)
    if all(r.id != rule_id for r in rules):
        raise KeyError(rule_id)
    await _write_rules(books, [r for r in rules if r.id != rule_id])
    await books.audit(f"user:{user}", "personal_rule_deleted", {"rule": rule_id})


#: Well-known UK names, offered by "Add common UK merchants". Each only fills a category the user has.
STARTER_RULES: list[tuple[str, str]] = [
    ("tesco", "groceries"),
    ("sainsbury", "groceries"),
    ("asda", "groceries"),
    ("morrisons", "groceries"),
    ("aldi", "groceries"),
    ("lidl", "groceries"),
    ("waitrose", "groceries"),
    ("netflix", "subscriptions"),
    ("spotify", "subscriptions"),
    ("disney", "subscriptions"),
    ("amazon prime", "subscriptions"),
    ("tfl", "transport"),
    ("trainline", "transport"),
    ("uber", "transport"),
    ("octopus energy", "utilities"),
    ("british gas", "utilities"),
    ("thames water", "utilities"),
    ("council tax", "housing"),
    ("mcdonald", "eating_out"),
    ("nando", "eating_out"),
    ("deliveroo", "eating_out"),
    ("just eat", "eating_out"),
    ("boots", "health"),
    ("aviva", "insurance"),
]


async def add_starter_rules(books: Books, user: str) -> list[PersonalRule]:
    """Append the starter merchants the user does not already have a rule for. Returns the ones added."""
    cats = {c.id for c in await load_categories(books)}
    rules = await load_rules(books)
    have = {(r.match.op, r.match.value.lower()) for r in rules}
    added = [
        PersonalRule(name=value.title(), match=BankRuleMatch(op="contains", value=value), category_id=cat)
        for value, cat in STARTER_RULES
        if cat in cats and ("contains", value) not in have
    ]
    added = added[: max(0, MAX_RULES - len(rules))]
    if added:
        await _write_rules(books, [*rules, *added])
        await books.audit(f"user:{user}", "personal_rule_added", {"starter": len(added)})
    return added


async def load_overrides(books: Books) -> dict[str, str]:
    raw = await books.read_json(OVERRIDES, {})
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


async def set_override(books: Books, line_id: str, category_id: str | None, user: str) -> None:
    """Put one line in a category by hand (or, with None, hand it back to the rules)."""
    if category_id is not None and category_id not in {c.id for c in await load_categories(books)}:
        raise PersonalError(f"No such category: {category_id}")
    await books.find_bank_line(line_id)  # FileNotFoundError -> 404

    def change(old: dict[str, str]) -> dict[str, str]:
        new = dict(old)
        if category_id is None:
            new.pop(line_id, None)
        else:
            new[line_id] = category_id
        return new

    await books._update_json(OVERRIDES, {}, change)
    await books.audit(f"user:{user}", "personal_line_categorised", {"line": line_id, "category": category_id})


CategorySource = Literal["hand", "rule", "none"]


def categorise(
    line: BankLine,
    rules: list[PersonalRule],
    overrides: dict[str, str],
    known: set[str],
) -> tuple[str, CategorySource]:
    """(category id, how). Only money out is categorised. A hand-set line wins, then the first rule in order
    that matches; a category that no longer exists falls back to Other. Anything else is Other / "none"."""
    if line.amount_pence >= 0:
        return OTHER, "none"
    hand = overrides.get(line.id)
    if hand is not None and hand in known:
        return hand, "hand"
    for rule in rules:
        if rule.category_id in known and rule_matches(
            _as_bank_rule(rule), description=line.description, amount_pence=line.amount_pence
        ):
            return rule.category_id, "rule"
    return OTHER, "none"


# --------------------------------------------------------------------------- #
# Spend against budget, and the monthly summary
# --------------------------------------------------------------------------- #

BudgetState = Literal["none", "ok", "near", "over"]
NEAR_PERCENT = 80


class CategorySpend(BaseModel):
    id: str
    name: str
    spent_pence: int
    budget_pence: int | None
    remaining_pence: int | None  # negative when over budget
    percent: int | None  # spent as a whole percentage of the budget; may exceed 100
    state: BudgetState


class MonthlySummary(BaseModel):
    month: str  # YYYY-MM
    lines: int  # bank lines in the month that count (transfers and ignored lines left out)
    income_pence: int
    spent_pence: int
    left_pence: int  # income - spent; negative when more went out than came in
    budget_total_pence: int
    categories: list[CategorySpend]
    uncategorised_count: int
    uncategorised_pence: int
    notes: list[str]


def spend_vs_budget(spent: int, budget: int | None) -> tuple[int | None, int | None, BudgetState]:
    """(remaining, percent, state) for one category. Whole pence; percent rounded down."""
    if not budget:
        return None, None, "none"
    state: BudgetState = "over" if spent > budget else "near" if spent * 100 >= budget * NEAR_PERCENT else "ok"
    return budget - spent, spent * 100 // budget, state


def counts(line: BankLine) -> bool:
    return line.status not in ("transfer", "ignored")


def summarise_month(
    month: str,
    lines: list[BankLine],
    categories: list[Category],
    budgets: dict[str, int],
    rules: list[PersonalRule],
    overrides: dict[str, str],
) -> MonthlySummary:
    known = {c.id for c in categories}
    spent: dict[str, int] = defaultdict(int)
    income = unc_count = unc_pence = n = 0
    for line in lines:
        if not counts(line) or line.date.strftime("%Y-%m") != month:
            continue
        n += 1
        if line.amount_pence > 0:
            income += line.amount_pence
            continue
        cat, how = categorise(line, rules, overrides, known)
        spent[cat] += -line.amount_pence
        if how == "none":
            unc_count += 1
            unc_pence += -line.amount_pence
    rows: list[CategorySpend] = []
    for c in categories:
        budget = budgets.get(c.id)
        remaining, percent, state = spend_vs_budget(spent[c.id], budget)
        rows.append(
            CategorySpend(
                id=c.id,
                name=c.name,
                spent_pence=spent[c.id],
                budget_pence=budget,
                remaining_pence=remaining,
                percent=percent,
                state=state,
            )
        )
    total_spent = sum(spent.values())
    notes: list[str] = []
    if n == 0:
        notes.append("No bank lines for this month yet. Import a statement on the Bank page.")
    if unc_count:
        notes.append(
            f"{unc_count} payment{'s' if unc_count != 1 else ''} did not match a rule and sit under Other. "
            "Add a rule to sort them."
        )
    notes.append("Totals come from the bank lines you imported; cash and anything not in a statement is not counted.")
    return MonthlySummary(
        month=month,
        lines=n,
        income_pence=income,
        spent_pence=total_spent,
        left_pence=income - total_spent,
        budget_total_pence=sum(budgets.get(c.id, 0) for c in categories),
        categories=rows,
        uncategorised_count=unc_count,
        uncategorised_pence=unc_pence,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Recurring bills and subscriptions, found by code (an estimate)
# --------------------------------------------------------------------------- #

Cadence = Literal["weekly", "fortnightly", "monthly", "quarterly", "annually"]
RecurringStatus = Literal["upcoming", "overdue", "stopped"]

#: cadence -> (lowest, highest) days between payments that count as it.
BANDS: dict[Cadence, tuple[int, int]] = {
    "weekly": (5, 9),
    "fortnightly": (11, 17),
    "monthly": (25, 35),
    "quarterly": (84, 98),
    "annually": (350, 380),
}
NOMINAL_DAYS: dict[Cadence, int] = {"weekly": 7, "fortnightly": 14, "monthly": 30, "quarterly": 91, "annually": 365}
PER_YEAR: dict[Cadence, float] = {
    "weekly": 365.25 / 7,
    "fortnightly": 365.25 / 14,
    "monthly": 12,
    "quarterly": 4,
    "annually": 1,
}
MIN_OCCURRENCES: dict[Cadence, int] = {"weekly": 4, "fortnightly": 3, "monthly": 3, "quarterly": 3, "annually": 2}
REGULAR_SHARE = 0.75  # this share of the gaps (and of the amounts) must fit
STEADY_TOLERANCE = 0.10  # an amount within 10% (or £1) of the usual is "the same"
VARIES_TOLERANCE = 0.30  # monthly and quarterly bills that move more than that are not called recurring
_BANK_WORDS = (
    "on cd clp dd card payment pymt to bgc sto direct debit ref visa pos the faster fpo fpi purchase "
    "contactless apple pay google gb gbr ltd limited"
)
_DATE_WORDS = (
    "jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july august "
    "september october november december mon tue wed thu fri sat sun"
)
STOPWORDS = frozenset(f"{_BANK_WORDS} {_DATE_WORDS}".split())


class RecurringItem(BaseModel):
    key: str
    label: str  # the payee as the latest statement line wrote it
    category_id: str
    category_name: str
    cadence: Cadence
    amount_pence: int  # the usual amount (median), positive
    amount_varies: bool
    occurrences: int
    first_seen: date
    last_date: date
    next_due: date  # an estimate: the last payment plus one cadence
    days_until: int  # negative when the estimate has passed
    status: RecurringStatus
    monthly_equivalent_pence: int  # an estimate, for comparing a weekly with an annual bill
    estimate: bool = True


def payee_key(description: str) -> str:
    """The stable part of a statement description: no dates, card numbers or reference digits.

    "NETFLIX.COM 12345 ON 03 OCT CD 1234" and "NETFLIX.COM 67890 ON 03 NOV CD 1234" both give "netflix com".
    """
    tokens = re.sub(r"[^a-z0-9]+", " ", normalise_description(description)).split()
    tokens = [t for t in tokens if t not in STOPWORDS and not any(ch.isdigit() for ch in t)]
    return " ".join(tokens[:3])


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _step(d: date, cadence: Cadence) -> date:
    if cadence == "weekly":
        return d + timedelta(days=7)
    if cadence == "fortnightly":
        return d + timedelta(days=14)
    return add_months(d, {"monthly": 1, "quarterly": 3, "annually": 12}[cadence])


def _cadence_of(dates: list[date]) -> Cadence | None:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
    if not gaps:
        return None
    mid = statistics.median(gaps)
    for cadence, (lo, hi) in BANDS.items():
        if lo <= mid <= hi:
            if len(dates) < MIN_OCCURRENCES[cadence]:
                return None
            fits = sum(lo <= g <= hi for g in gaps)
            return cadence if fits / len(gaps) >= REGULAR_SHARE else None
    return None


def _within(amount: int, usual: int, tolerance: float) -> bool:
    return abs(amount - usual) <= max(round(usual * tolerance), 100)


def detect_recurring(
    lines: list[BankLine],
    categories: list[Category],
    rules: list[PersonalRule],
    overrides: dict[str, str],
    today: date,
) -> list[RecurringItem]:
    """Payees paid at a regular interval for a similar amount. Needs at least three payments (two for a
    yearly one) and, for the amount, 75% of them within 10% or £1 of the usual. Monthly and quarterly bills
    that move up to 30% (energy, say) are kept and marked "varies". It is a guess from the statements you
    imported, so every item is marked an estimate and the next due date is the last payment plus one cycle.
    """
    names = {c.id: c.name for c in categories}
    known = set(names)
    groups: dict[str, list[BankLine]] = defaultdict(list)
    for line in lines:
        if counts(line) and line.amount_pence < 0 and (key := payee_key(line.description)):
            groups[key].append(line)
    out: list[RecurringItem] = []
    for key, group in groups.items():
        by_day: dict[date, BankLine] = {}
        for line in group:  # two payments on one day count once (the larger)
            if line.date not in by_day or line.amount_pence < by_day[line.date].amount_pence:
                by_day[line.date] = line
        days = sorted(by_day)
        cadence = _cadence_of(days)
        if cadence is None:
            continue
        amounts = [-by_day[d].amount_pence for d in days]
        usual = round(statistics.median(amounts))
        steady = sum(_within(a, usual, STEADY_TOLERANCE) for a in amounts) / len(amounts) >= REGULAR_SHARE
        loose = sum(_within(a, usual, VARIES_TOLERANCE) for a in amounts) / len(amounts) >= REGULAR_SHARE
        if not steady and not (loose and cadence in ("monthly", "quarterly")):
            continue
        latest = by_day[days[-1]]
        nxt = _step(days[-1], cadence)
        late = (today - nxt).days
        status: RecurringStatus = "upcoming" if late <= 0 else "overdue" if late <= NOMINAL_DAYS[cadence] else "stopped"
        cat, _how = categorise(latest, rules, overrides, known)
        out.append(
            RecurringItem(
                key=key,
                label=" ".join(latest.description.split())[:60],
                category_id=cat,
                category_name=names.get(cat, "Other"),
                cadence=cadence,
                amount_pence=usual,
                amount_varies=not steady,
                occurrences=len(days),
                first_seen=days[0],
                last_date=days[-1],
                next_due=nxt,
                days_until=(nxt - today).days,
                status=status,
                monthly_equivalent_pence=round(usual * PER_YEAR[cadence] / 12),
            )
        )
    order = {"overdue": 0, "upcoming": 1, "stopped": 2}
    out.sort(key=lambda r: (order[r.status], r.next_due, r.key))
    return out


# --------------------------------------------------------------------------- #
# Savings goals: the user sets the target and the date, code works out the monthly amount
# --------------------------------------------------------------------------- #

GoalStatus = Literal["reached", "on_track", "behind", "plan_needed", "date_passed"]
DAYS_PER_MONTH = 30.4375


class GoalIn(StrictBody):
    name: str = Field(min_length=1, max_length=80)
    target_pence: Pence = Field(gt=0, le=MAX_PENCE)
    target_date: Day
    saved_pence: Pence = Field(default=0, ge=0, le=MAX_PENCE)  # put aside so far, by your own count
    planned_monthly_pence: Pence | None = Field(default=None, ge=0, le=MAX_PENCE)

    @field_validator("name")
    @classmethod
    def _tidy(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is empty")
        return v


class GoalPatch(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target_pence: Pence | None = Field(default=None, gt=0, le=MAX_PENCE)
    target_date: Day | None = None
    saved_pence: Pence | None = Field(default=None, ge=0, le=MAX_PENCE)
    planned_monthly_pence: Pence | None = Field(default=None, ge=0, le=MAX_PENCE)


class Goal(GoalIn):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=now)


class GoalPlan(BaseModel):
    goal: Goal
    remaining_pence: int
    percent: int  # saved as a whole percentage of the target, capped at 100
    months_left: int  # monthly payments still to make, counting a part month as one; 0 once reached
    monthly_needed_pence: int  # remaining / months_left, rounded up to the penny
    status: GoalStatus
    projected_date: date | None  # when the planned monthly amount would reach it
    estimate: bool = True


def months_between(today: date, target: date) -> int:
    """Monthly payments still to make: days to the date over 30.4375, a part month counting as one, at least one."""
    return max(1, math.ceil((target - today).days / DAYS_PER_MONTH))


def plan_goal(goal: Goal, today: date) -> GoalPlan:
    remaining = max(0, goal.target_pence - goal.saved_pence)
    if remaining == 0:
        return GoalPlan(
            goal=goal,
            remaining_pence=0,
            percent=100,
            months_left=0,
            monthly_needed_pence=0,
            status="reached",
            projected_date=None,
        )
    passed = goal.target_date <= today
    months = 1 if passed else months_between(today, goal.target_date)
    needed = math.ceil(remaining / months)
    planned = goal.planned_monthly_pence
    projected = add_months(today, math.ceil(remaining / planned)) if planned else None
    status: GoalStatus = (
        "date_passed" if passed else "plan_needed" if not planned else "on_track" if planned >= needed else "behind"
    )
    return GoalPlan(
        goal=goal,
        remaining_pence=remaining,
        percent=min(100, goal.saved_pence * 100 // goal.target_pence),
        months_left=months,
        monthly_needed_pence=needed,
        status=status,
        projected_date=projected,
    )


async def load_goals(books: Books) -> list[Goal]:
    out: list[Goal] = []
    for raw in await books.read_json(GOALS, []):
        try:
            out.append(Goal.model_validate(raw, **LENIENT))
        except ValueError:
            continue
    return out


async def _write_goals(books: Books, goals: list[Goal]) -> None:
    payload = [g.model_dump(mode="json") for g in goals]
    await books._update_json(GOALS, [], lambda _old: payload)


async def add_goal(books: Books, body: GoalIn, user: str) -> Goal:
    goals = await load_goals(books)
    if len(goals) >= MAX_GOALS:
        raise PersonalError(f"At most {MAX_GOALS} goals")
    goal = Goal(**body.model_dump())
    await _write_goals(books, [*goals, goal])
    await books.audit(f"user:{user}", "personal_goal_saved", {"goal": goal.id, "change": "added"})
    return goal


async def patch_goal(books: Books, goal_id: str, patch: GoalPatch, user: str) -> Goal:
    goals = await load_goals(books)
    for i, g in enumerate(goals):
        if g.id == goal_id:
            try:
                new = Goal.model_validate({**g.model_dump(), **patch.model_dump(exclude_unset=True)})
            except ValidationError as exc:
                raise PersonalError(exc.errors()[0]["msg"]) from exc
            goals[i] = new
            await _write_goals(books, goals)
            await books.audit(f"user:{user}", "personal_goal_saved", {"goal": goal_id, "change": "edited"})
            return new
    raise KeyError(goal_id)


async def delete_goal(books: Books, goal_id: str, user: str) -> None:
    goals = await load_goals(books)
    if all(g.id != goal_id for g in goals):
        raise KeyError(goal_id)
    await _write_goals(books, [g for g in goals if g.id != goal_id])
    await books.audit(f"user:{user}", "personal_goal_deleted", {"goal": goal_id})
