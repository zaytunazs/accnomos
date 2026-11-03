"""Home's summary: facts from code, words from the user's AI, checked by code (as the month-end close summary).

Code works out every figure (app/home_overview.py `summary_facts`) and formats it. The model writes two to four
sentences of plain UK English from those facts only. Code then checks the words with Ask's number check
(`KnownNumbers`): every figure must be one of the facts, there may be no links, and a summary may not say nothing
needs doing while something does. Anything else, no AI set up, or any model trouble: code writes the summary itself
and `fallback_reason` says why. The facts go back with the summary, so the app can show what it was based on.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ai.ask import KnownNumbers, call_json_model
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.schemas import strict_json_schema

SUMMARY_MAX = 700

SYSTEM_PROMPT = (
    "You write the two to four sentence summary at the top of a UK small business owner's or household's bookkeeping "
    "home page, in plain UK English: no headings, no lists, no links, no advice about tax law. You are given FACTS as "
    "JSON, worked out by code. Rules: 1) Quote figures, counts, percentages and dates exactly as they appear in FACTS; "
    "never add, subtract, work out a percentage or calculate anything. 2) Cover, in this order and only where FACTS "
    "has them: the cash position; how the business is doing (FACTS.year_to_date against last year, using its "
    "`_vs_last_year` wording, and FACTS.monthly_trend's direction or best and weakest month; else this month against "
    "last month); what needs doing; and the next deadline. If FACTS.cash_forecast.goes_below_zero is true, say when. "
    "3) If FACTS.needs_doing has any count above zero, never say that nothing needs doing. 4) Leave out anything FACTS "
    'does not have. 5) A household (FACTS.kind is "personal") is not a business: cover, in this order, money in, '
    "money out and what was left this month against last month (FACTS.household), any budgets over or near their "
    "limit, what needs doing (receipts in Review, bank lines with no category), and the next regular bill, saying "
    "its date is an estimate; never mention VAT, turnover, profit or invoices, and never mention a count of zero "
    '("0 receipts", "0 bank lines"): leave it out. Return JSON with `summary_md`.'
)

LINK = re.compile(r"https?://|www\.", re.IGNORECASE)
ALL_CLEAR = re.compile(r"\bnothing (needs|to do|is waiting|waiting)|\ball clear\b|\bnothing outstanding\b", re.I)


class SummaryModelOutput(BaseModel):
    summary_md: str


class HomeSummary(BaseModel):
    summary_md: str
    model: str  # "code" when no AI is set up
    fallback_reason: str | None = None
    facts: dict[str, Any]  # what the summary was based on, every figure as code formatted it


def gbp(pence: int) -> str:
    """£1,234.56 from pence; a minus sign in front of the pound sign for a negative amount."""
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}£{p // 100:,}.{p % 100:02d}"


def _waiting(facts: dict[str, Any]) -> int:
    n = facts.get("needs_doing") or {}
    return sum(int(v) for v in n.values() if isinstance(v, int))


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _left(left: str) -> str:
    """ "leaving £120.00" or "£35.00 more went out than came in" from a formatted left-over figure."""
    return f"{left.lstrip('-')} more went out than came in" if left.startswith("-") else f"leaving {left}"


def household_summary(facts: dict[str, Any]) -> str:
    """A household's summary by code: the month, budgets, what needs doing and the next bill. At most four sentences."""
    out: list[str] = []
    h = facts["household"]
    t, last = h["this_month"], h["last_month"]
    out.append(
        f"{t['label']}, {t['in']} came in and {t['out']} went out, {_left(t['left'])}; in {last['label']} "
        f"{last['in']} came in and {last['out']} went out."
    )
    over = h.get("over_budget") or []
    near = h.get("near_budget") or []
    if over:
        o = over[0]
        more = f" ({_count(len(over) - 1, 'other category', 'other categories')} too)" if len(over) > 1 else ""
        out.append(f"{o['category']} is over budget: {o['spent']} spent of {o['budget']}{more}.")
    elif near:
        c = near[0]
        out.append(f"{c['category']} is close to its budget: {c['spent']} of {c['budget']}, {c['left']} left.")
    n = facts.get("needs_doing") or {}
    parts = []
    if n.get("in_review"):
        parts.append(f"{_count(n['in_review'], 'receipt')} waiting in Review")
    if n.get("uncategorised_bank_lines"):
        parts.append(_count(n["uncategorised_bank_lines"], "bank line") + " with no category")
    if parts:
        out.append("To do: " + " and ".join(parts) + ".")
    b = h.get("next_bill")
    if b:
        when = "today" if b["days_left"] == 0 else f"in {_count(b['days_left'], 'day')}"
        out.append(
            f"Next regular bill: {b['what']}, usually {b['usual_amount']}, around {b['due']} ({when}, an estimate)."
        )
    return " ".join(out[:4])


def fallback_summary(facts: dict[str, Any]) -> str:
    """Written by code from the facts alone: the same order the model is asked for, at most four sentences."""
    if facts.get("kind") == "personal" and facts.get("household"):
        return household_summary(facts)
    out: list[str] = []
    cash = facts.get("cash")
    if cash:
        low = facts.get("cash_forecast") or {}
        dip = ""
        if low.get("goes_below_zero"):
            dip = f", and the 90-day forecast goes below £0 from {low['below_zero_from']}"
        out.append(f"You had {cash['balance']} in the bank on {cash['as_of']}{dip}.")
    else:
        out.append("There is no bank balance yet: import a bank statement and match a line to see one.")
    money = facts.get("money")
    ytd = facts.get("year_to_date")
    if ytd:  # the year so far says more than one month against another; the Money card still shows the months
        np = str(ytd["net_profit"])
        result = f"a net loss of {np.lstrip('-')}" if np.startswith("-") else f"a net profit of {np}"
        text = (
            f"This year so far ({ytd['period']}, {ytd['basis']}), turnover was {ytd['turnover']} and expenses "
            f"{ytd['expenses']}: {result}"
        )
        vs = ytd.get("turnover_vs_last_year")
        if vs == "no change":
            text += f", with the same turnover as {ytd['last_year_period']}"
        elif vs:
            text += f", with turnover {vs} on {ytd['last_year_period']}"
        out.append(text + ".")
    elif money:
        t, last = money["this_month"], money["last_month"]
        out.append(
            f"{t['label']}, {t['in']} came in and {t['out']} went out, against {last['in']} in and "
            f"{last['out']} out in {last['label']}."
        )
    n = facts.get("needs_doing")
    if n is not None:
        parts = []
        if n.get("in_review"):
            parts.append(f"{_count(n['in_review'], 'item')} waiting in Review")
        if n.get("unmatched_bank_lines"):
            parts.append(_count(n["unmatched_bank_lines"], "bank line") + " to match")
        overdue = facts.get("overdue")
        if overdue:
            parts.append(f"{_count(overdue['invoices'], 'invoice')} overdue ({overdue['amount']})")
        elif n.get("overdue_invoices"):
            parts.append(_count(n["overdue_invoices"], "invoice") + " overdue")
        if parts:
            out.append("To do: " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + ".")
        else:
            out.append("Nothing is waiting for you in Review.")
    nxt = facts.get("next_deadline")
    if nxt:
        days = nxt["days_left"]
        when = "today" if days == 0 else f"{_count(-days, 'day')} late" if days < 0 else f"in {_count(days, 'day')}"
        out.append(f"Next deadline: {nxt['what']}, due {nxt['due']} ({when}).")
    return " ".join(out[:4])


def ground(text: str, facts: dict[str, Any]) -> str | None:
    """None when the model's summary passes every check, otherwise the reason it does not."""
    text = text.strip()
    if not text:
        return "The model returned an empty summary."
    if len(text) > SUMMARY_MAX:
        return "The model's summary was too long."
    if LINK.search(text):
        return "The model's summary contained a link."
    if _waiting(facts) and ALL_CLEAR.search(text):
        return "The model said nothing needs doing; something does."
    if invented := KnownNumbers(facts).unknown(text, all_tokens=False):
        return f"The model quoted figures that are not in your books ({', '.join(dict.fromkeys(invented[:3]))})."
    return None


async def summarise(facts: dict[str, Any], cfg: AiConfig | None) -> HomeSummary:
    """Never raises: the code-written summary stands in, with the reason."""
    if cfg is None:
        return HomeSummary(
            summary_md=fallback_summary(facts),
            model="code",
            fallback_reason="No AI is set up, so code wrote this.",
            facts=facts,
        )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}"},
    ]
    try:
        raw = await call_json_model(messages, cfg, strict_json_schema(SummaryModelOutput), "home_summary")
        text = SummaryModelOutput.model_validate(parse_model_json(raw)).summary_md.strip()
        reason = ground(text, facts)
    except (ExtractionError, ValidationError):
        text, reason = "", "The model's reply was not in the expected format."
    except Exception as exc:  # noqa: BLE001  any model trouble: the figures stand without the model's words
        text, reason = "", f"Your AI ({cfg.mode}) could not write the summary ({type(exc).__name__})."
    if reason:
        return HomeSummary(summary_md=fallback_summary(facts), model=cfg.model, fallback_reason=reason, facts=facts)
    return HomeSummary(summary_md=text, model=cfg.model, facts=facts)
