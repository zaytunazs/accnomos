"""Home's summary as a short, ordered to-do list: what needs the owner first, each with a link to act on it.

Code decides everything here: which items exist (none for a count of zero), their figures, how urgent each is and the
order. Order: priority (1 act now, 2 soon, 3 for information), then the soonest date, then the most money at stake. At
most MAX_ITEMS. Each item carries its own facts, so the user's AI may reword one item's title and detail and code can
check that item's figures on their own (app/ai/home_summary.py); an item whose words do not check out keeps code's.

Routes are the web app's paths; the Android app maps the same paths to its screens.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

MAX_ITEMS = 6
TITLE_MAX = 60
DETAIL_MAX = 140
DEADLINE_WINDOW_DAYS = 14
BILL_WINDOW_DAYS = 7

Tone = Literal["negative", "warning", "positive", "neutral"]


class SummaryAction(BaseModel):
    label: str
    route: str


class SummaryItem(BaseModel):
    id: str
    priority: Literal[1, 2, 3]
    tone: Tone
    title: str
    detail: str | None = None
    action: SummaryAction | None = None


@dataclass
class Draft:
    """An item as code wrote it, with the facts its words may quote and how it sorts."""

    item: SummaryItem
    facts: dict[str, Any]
    when: date | None = None  # the date that makes it urgent (a deadline, a bill, a cash dip)
    money: int = 0  # pence at stake, for ties
    extra: dict[str, Any] = field(default_factory=dict)


def gbp(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}£{p // 100:,}.{p % 100:02d}"


def day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def short_day(d: date) -> str:
    return f"{d.day} {d:%b}"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def payee(label: str) -> str:
    """A bank payee in readable case: "BT BROADBAND" → "BT Broadband" (short words stay capitals: BT, EE, O2)."""
    words: list[str] = []
    for w in label.split():
        if sum(c.isdigit() for c in w) >= 3 and words:
            break  # bank reference noise: "NETFLIX.COM 44444 ON 03 OCT" → "NETFLIX.COM"
        words.append(w)
    name = " ".join(words) or label
    if name != name.upper():
        return name
    return " ".join(w if len(w) <= 3 else w.capitalize() for w in name.split())


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _item(
    id: str,
    priority: Literal[1, 2, 3],
    tone: Tone,
    title: str,
    detail: str | None,
    action: tuple[str, str] | None,
    facts: dict[str, Any],
    *,
    when: date | None = None,
    money: int = 0,
) -> Draft:
    return Draft(
        item=SummaryItem(
            id=id,
            priority=priority,
            tone=tone,
            title=clip(title, TITLE_MAX),
            detail=clip(detail, DETAIL_MAX) if detail else None,
            action=SummaryAction(label=action[0], route=action[1]) if action else None,
        ),
        facts=facts,
        when=when,
        money=money,
    )


def order(drafts: Sequence[Draft]) -> list[Draft]:
    """Priority, then soonest date (undated last), then most money at stake; at most MAX_ITEMS."""
    far = date.max
    ranked = sorted(drafts, key=lambda d: (d.item.priority, d.when or far, -abs(d.money)))
    return ranked[:MAX_ITEMS]


# --------------------------------------------------------------------------- #
# Items shared by both kinds of books
# --------------------------------------------------------------------------- #


def review_item(proposed: int, needs_a_look: int, household: bool) -> Draft | None:
    n = proposed + needs_a_look
    if n <= 0:
        return None
    what = "receipt" if household else "item"
    title = f"{plural(n, what)} waiting for your approval"
    detail = f"{needs_a_look} {'needs' if needs_a_look == 1 else 'need'} a closer look." if needs_a_look else None
    return _item(
        "review",
        1,
        "warning",
        title,
        detail,
        ("Review", "/review"),
        {"waiting": n, "needs_a_look": needs_a_look},
    )


MAX_GOAL_ITEMS = 2


def goal_items(goals: Sequence[Any]) -> list[Draft]:
    """Goals that are off track, over their limit or missed (app/goals.py GoalProgress); at most MAX_GOAL_ITEMS, the
    most money adrift first, so goals never crowd out the rest of the list (the Goals card lists them all)."""
    out: list[Draft] = []
    for p in goals:
        if p.status not in ("off_track", "over_limit", "missed"):
            continue
        name = clip(p.goal.name, 36)
        out.append(
            _item(
                f"goal:{p.goal.id}",
                2,
                "negative",
                f"{name}: {p.status_label.lower()}",
                p.variance_text,
                ("See goal", "/goals"),
                {"goal": p.goal.name, "status": p.status_label, "difference": p.variance_text},
                money=abs(p.variance_pence or 0),
            )
        )
    return sorted(out, key=lambda d: -d.money)[:MAX_GOAL_ITEMS]


# --------------------------------------------------------------------------- #
# A business
# --------------------------------------------------------------------------- #


def business_items(
    *,
    today: date,
    proposed: int,
    needs_a_look: int,
    unmatched_bank_lines: int,
    overdue_invoices: int,
    overdue_pence: int,
    deadlines: Sequence[Any],
    below_zero_on: date | None,
    lowest_pence: int | None,
    lowest_on: date | None,
    bills_overdue_pence: int,
    unclosed_month: tuple[str, str] | None,
    goals: Sequence[Any],
    ytd: dict[str, Any] | None,
    cash: tuple[int, date] | None,
) -> list[Draft]:
    """`deadlines`: home_overview.Due items; `unclosed_month`: (YYYY-MM, "October 2026") when last month is not closed;
    `ytd`: {"turnover": pence, "change_pct": int | None, "period": "1 Jan – 3 Nov 2026"}; `cash`: (balance, as_of)."""
    out: list[Draft] = []
    for due in deadlines:
        if due.days_left > DEADLINE_WINDOW_DAYS:
            continue
        late = due.days_left < 0
        when_words = (
            "today"
            if due.days_left == 0
            else plural(-due.days_left, "day") + " late"
            if late
            else "in " + plural(due.days_left, "day")
        )
        label = "File it" if due.key == "vat" else "Open"
        out.append(
            _item(
                f"{due.key}_due",
                1 if due.days_left <= 7 else 2,
                "negative" if late else "warning",
                f"{due.title} due {short_day(due.due)}",
                f"Due {day(due.due)}, {when_words}.",
                (label, due.href),
                {"what": due.title, "due": day(due.due), "days_left": due.days_left},
                when=due.due,
            )
        )
    if r := review_item(proposed, needs_a_look, household=False):
        out.append(r)
    if overdue_invoices > 0:
        out.append(
            _item(
                "overdue_invoices",
                1,
                "negative",
                f"{plural(overdue_invoices, 'invoice')} overdue: {gbp(overdue_pence)}",
                "Customers are late paying; a reminder usually helps.",
                ("Chase", "/invoices?filter=overdue"),
                {"invoices": overdue_invoices, "amount": gbp(overdue_pence)},
                money=overdue_pence,
            )
        )
    if below_zero_on is not None:
        lowest = (
            f"Lowest point {gbp(lowest_pence)} on {day(lowest_on)} in the 90-day forecast."
            if lowest_pence is not None and lowest_on is not None
            else "From the 90-day cash forecast."
        )
        out.append(
            _item(
                "cash_dip",
                1,
                "negative",
                f"Cash may go below £0 from {short_day(below_zero_on)}",
                lowest,
                ("See forecast", "/reports/cashflow"),
                {
                    "below_zero_from": day(below_zero_on),
                    **({"lowest": gbp(lowest_pence)} if lowest_pence is not None else {}),
                    **({"lowest_on": day(lowest_on)} if lowest_on is not None else {}),
                },
                when=below_zero_on,
                money=abs(lowest_pence or 0),
            )
        )
    if unmatched_bank_lines > 0:
        out.append(
            _item(
                "bank_unmatched",
                2,
                "warning",
                f"{plural(unmatched_bank_lines, 'bank line')} to match",
                "Matching keeps your cash figure and VAT right.",
                ("Match", "/bank/reconcile"),
                {"lines": unmatched_bank_lines},
            )
        )
    if bills_overdue_pence > 0:
        out.append(
            _item(
                "bills_overdue",
                2,
                "warning",
                f"{gbp(bills_overdue_pence)} of bills overdue",
                "Suppliers you owe past their due date.",
                ("See suppliers", "/contacts"),
                {"amount": gbp(bills_overdue_pence)},
                money=bills_overdue_pence,
            )
        )
    if unclosed_month is not None:
        out.append(
            _item(
                "month_end",
                2,
                "neutral",
                f"{unclosed_month[1]} is not closed yet",
                "The close checks the month and lists anything left to do.",
                ("Close it", "/month-end"),
                {"month": unclosed_month[1]},
            )
        )
    out.extend(goal_items(goals))
    if ytd is not None:
        pct = ytd.get("change_pct")
        trend = "" if pct is None else ", no change" if pct == 0 else f", {'up' if pct > 0 else 'down'} {abs(pct)}%"
        out.append(
            _item(
                "trend",
                3,
                "positive" if (pct or 0) > 0 else "neutral",
                f"Turnover {gbp(ytd['turnover'])} this year{trend}",
                f"{ytd['period']}, against the same dates last year." if pct is not None else ytd["period"] + ".",
                None,
                {"turnover": gbp(ytd["turnover"]), "change_pct": pct, "period": ytd["period"]},
            )
        )
    elif cash is not None:
        out.append(
            _item(
                "cash",
                3,
                "neutral",
                f"{gbp(cash[0])} in the bank",
                f"On {day(cash[1])}, from your latest matched statement.",
                None,
                {"balance": gbp(cash[0]), "as_of": day(cash[1])},
            )
        )
    return order(out)


# --------------------------------------------------------------------------- #
# A household
# --------------------------------------------------------------------------- #


def household_items(
    *,
    today: date,
    proposed: int,
    needs_a_look: int,
    household: Any,  # home_overview.Household
    this_month_label: str,
    last_month_label: str,
    goals: Sequence[Any],
) -> list[Draft]:
    out: list[Draft] = []
    if r := review_item(proposed, needs_a_look, household=True):
        out.append(r)
    if household is not None:
        m = household.this_month
        for c in m.categories:
            if c.state == "over" and c.budget_pence:
                over = -(c.remaining_pence or 0)
                out.append(
                    _item(
                        f"budget_over:{c.id}",
                        1,
                        "negative",
                        f"{clip(c.name, 28)} over budget by {gbp(over)}",
                        f"{gbp(c.spent_pence)} spent of {gbp(c.budget_pence)} this month.",
                        ("See budget", "/personal"),
                        {
                            "category": c.name,
                            "spent": gbp(c.spent_pence),
                            "budget": gbp(c.budget_pence),
                            "over_by": gbp(over),
                        },
                        money=over,
                    )
                )
            elif c.state == "near" and c.budget_pence:
                left = c.remaining_pence or 0
                out.append(
                    _item(
                        f"budget_near:{c.id}",
                        2,
                        "warning",
                        f"{clip(c.name, 28)}: {gbp(left)} left this month",
                        f"{gbp(c.spent_pence)} spent of {gbp(c.budget_pence)}.",
                        ("See budget", "/personal"),
                        {
                            "category": c.name,
                            "spent": gbp(c.spent_pence),
                            "budget": gbp(c.budget_pence),
                            "left": gbp(left),
                        },
                        money=c.spent_pence,
                    )
                )
        b = household.next_bill
        if b is not None and 0 <= b.days_until <= BILL_WINDOW_DAYS:
            when = "today" if b.days_until == 0 else "in " + plural(b.days_until, "day")
            out.append(
                _item(
                    "bill_due",
                    2,
                    "neutral",
                    f"{clip(payee(b.label), 26)}, about {gbp(b.amount_pence)}, due {short_day(b.next_due)}",
                    f"Around {day(b.next_due)} ({when}): an estimate from your statements.",
                    ("See bills", "/personal"),
                    {
                        "what": b.label,
                        "usual_amount": gbp(b.amount_pence),
                        "due": day(b.next_due),
                        "days": b.days_until,
                    },
                    when=b.next_due,
                    money=b.amount_pence,
                )
            )
        if m.uncategorised_count:
            out.append(
                _item(
                    "uncategorised",
                    2,
                    "warning",
                    f"{plural(m.uncategorised_count, 'bank line')} with no category",
                    f"{gbp(m.uncategorised_pence)} this month is not in any budget yet.",
                    ("Sort them", "/personal"),
                    {"lines": m.uncategorised_count, "amount": gbp(m.uncategorised_pence)},
                )
            )
    out.extend(goal_items(goals))
    if household is not None:
        t, last = household.this_month, household.last_month
        out.append(
            _item(
                "trend",
                3,
                "positive" if t.left_pence >= 0 else "warning",
                f"{this_month_label}: {gbp(t.income_pence)} in, {gbp(t.spent_pence)} out",
                f"{last_month_label}: {gbp(last.income_pence)} in, {gbp(last.spent_pence)} out.",
                None,
                {
                    "this_month": this_month_label,
                    "in": gbp(t.income_pence),
                    "out": gbp(t.spent_pence),
                    "last_month": last_month_label,
                    "last_in": gbp(last.income_pence),
                    "last_out": gbp(last.spent_pence),
                },
            )
        )
    return order(out)


# --------------------------------------------------------------------------- #
# Calendar clashes (either kind of books)
# --------------------------------------------------------------------------- #

CALENDAR_DAYS = 14


def clashes(events: Sequence[Any]) -> list[tuple[Any, Any]]:
    """Pairs of timed events that overlap (connectors' CalendarEvent: start, end aware datetimes). All-day events and
    ones shown as free never clash; touching end-to-start is not a clash. Earliest first."""
    timed = sorted(
        (e for e in events if not e.is_all_day and e.show_as != "free" and e.end > e.start),
        key=lambda e: (e.start, e.end),
    )
    out: list[tuple[Any, Any]] = []
    for i, a in enumerate(timed):
        for b in timed[i + 1 :]:
            if b.start >= a.end:
                break
            out.append((a, b))
    return out


def calendar_items(by_day: dict[date, list[Any]], tz: Any) -> list[Draft]:
    """One item per day in the window with a clash; a clash between events that span days is shown on its first day."""
    out: list[Draft] = []
    seen: set[tuple[str, str]] = set()
    for d in sorted(by_day):
        pairs = [(a, b) for a, b in clashes(by_day[d]) if (a.id, b.id) not in seen]
        if not pairs:
            continue
        seen.update((a.id, b.id) for a, b in pairs)
        a, b = pairs[0]

        def span(e: Any) -> str:
            return f"{e.start.astimezone(tz):%H:%M}–{e.end.astimezone(tz):%H:%M}"

        name_a, name_b = (a.subject or "An event").strip(), (b.subject or "an event").strip()
        when = f"{d:%a} {d.day} {d:%b}"
        title = f"Two events clash on {when}" if len(pairs) == 1 else f"{len(pairs)} clashes on {when}"
        detail = f"{name_a} {span(a)} and {name_b} {span(b)}"
        if len(pairs) > 1:
            detail += f", and {plural(len(pairs) - 1, 'more')}"
        out.append(
            _item(
                f"calendar_conflict:{d.isoformat()}",
                2,
                "warning",
                title,
                detail,
                ("Open calendar", "/calendar"),
                {
                    "day": when,
                    "date": day(d),
                    "clashes": len(pairs),
                    "events": [
                        {
                            "subject": e.subject,
                            "from": f"{e.start.astimezone(tz):%H:%M}",
                            "to": f"{e.end.astimezone(tz):%H:%M}",
                        }
                        for e in (a, b)
                    ],
                },
                when=d,
            )
        )
    return out


def headline(items: Sequence[SummaryItem]) -> str:
    """One line above the list, by code."""
    urgent = sum(1 for i in items if i.priority == 1)
    soon = sum(1 for i in items if i.priority == 2)
    if urgent:
        return f"{plural(urgent, 'thing needs', 'things need')} you now" + (f", {soon} coming up." if soon else ".")
    if soon:
        return f"Nothing urgent; {plural(soon, 'thing')} coming up."
    return "You're up to date."
