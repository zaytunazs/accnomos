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
from app.home_items import DETAIL_MAX, TITLE_MAX, Draft, SummaryItem, headline
from app.schemas import strict_json_schema

SUMMARY_MAX = 700

SYSTEM_PROMPT = (
    "You write the two to four sentence summary at the top of a UK small business owner's or household's bookkeeping "
    "home page, in plain UK English: no headings, no lists, no links, no advice about tax law. You are given FACTS as "
    "JSON, worked out by code. Rules: 1) Quote figures, counts, percentages and dates exactly as they appear in FACTS; "
    "never add, subtract, work out a percentage or calculate anything. 2) Cover, in this order and only where FACTS "
    'has them: the cash position (the bank balance and, when FACTS.paypal.balance_by_your_books is there, "PayPal '
    '(books)" as its own figure, never added to the bank balance); how the business is doing '
    "(FACTS.year_to_date against last year, using its `_vs_last_year` wording, and FACTS.monthly_trend's direction "
    "or best and weakest month; else this month against last month; and, only if FACTS.paypal has them, PayPal's "
    "fees and the money received through PayPal for the month); what needs doing (including "
    "FACTS.paypal.waiting_in_sync_paypal and open_disputes); and the next "
    "deadline. If FACTS.cash_forecast.goes_below_zero is true, say when. "
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
    summary_md: str  # one line above `items` when there are any; otherwise the summary paragraph, as before
    model: str  # "code" when no AI is set up
    fallback_reason: str | None = None
    facts: dict[str, Any]  # what the summary was based on, every figure as code formatted it
    items: list[SummaryItem] = []  # what needs the owner, most urgent first, each with a link (app/home_items.py)


ITEMS_PROMPT = (
    "You reword the to-do list at the top of a UK small business owner's or household's bookkeeping home page. "
    "Code has already chosen the items, their order and their figures. For each item in ITEMS you get its id, code's "
    "title and detail, and its FACTS. Return JSON {headline, items:[{id, title, detail}]} with every id once, in the "
    "same order. Rules: 1) title is at most 60 characters, a short plain statement of the matter (no full stop); "
    "detail is at most 140 characters, one sentence of context or why it matters, or null. 2) Quote figures, counts, "
    "dates and percentages exactly as they appear in that item's FACTS or code's words; never calculate, round or add "
    'a figure. 3) No links, no advice about tax law, no promises; say "coming up", never "soon". '
    "4) A household (KIND is personal) is never told "
    "about VAT, turnover, profit or invoices. 5) headline is one short sentence (at most 100 characters) saying how "
    "many things need attention now and soon, from COUNTS; never say nothing needs doing when COUNTS.now or "
    "COUNTS.soon is above zero. Plain, friendly UK English."
)


class _ItemWords(BaseModel):
    id: str
    title: str
    detail: str | None


class ItemsOutput(BaseModel):
    headline: str
    items: list[_ItemWords]


NOT_YET = re.compile(r"\b(?:soon|coming next|not yet available)\b", re.I)


def item_problem(title: str, detail: str | None, draft: Draft) -> str | None:
    """Why the model's words for one item cannot be shown, or None when they check out."""
    if not title.strip() or len(title) > TITLE_MAX:
        return "title missing or too long"
    if detail is not None and len(detail) > DETAIL_MAX:
        return "detail too long"
    text = f"{title} {detail or ''}"
    if LINK.search(text):
        return "contains a link"
    if NOT_YET.search(text):
        return "promises something for later"
    known = {**draft.facts, "code_title": draft.item.title, "code_detail": draft.item.detail or ""}
    if invented := KnownNumbers(known).unknown(text, all_tokens=False):
        return f"figures not in the books ({', '.join(dict.fromkeys(invented[:3]))})"
    return None


def counts(items: list[SummaryItem]) -> dict[str, int]:
    return {
        "now": sum(1 for i in items if i.priority == 1),
        "soon": sum(1 for i in items if i.priority == 2),
        "for_information": sum(1 for i in items if i.priority == 3),
    }


def gbp(pence: int) -> str:
    """£1,234.56 from pence; a minus sign in front of the pound sign for a negative amount."""
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}£{p // 100:,}.{p % 100:02d}"


def _waiting(facts: dict[str, Any]) -> int:
    n = facts.get("needs_doing") or {}
    pp = facts.get("paypal") or {}
    paypal = int((pp.get("waiting_in_sync_paypal") or {}).get("payments", 0)) + int(
        (pp.get("open_disputes") or {}).get("count", 0)
    )
    return sum(int(v) for v in n.values() if isinstance(v, int)) + paypal


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
    if held := (facts.get("paypal") or {}).get("balance_by_your_books"):
        out[0] += f" PayPal (books) holds {held}, counted separately."
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


async def summarise(facts: dict[str, Any], cfg: AiConfig | None, drafts: list[Draft] | None = None) -> HomeSummary:
    """Never raises: the code-written summary stands in, with the reason. With `drafts` (app/home_items.py), the summary
    is a headline plus those items; the model may reword each item, and each is checked on its own."""
    if drafts:
        return await summarise_items(facts, cfg, drafts)
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


async def summarise_items(facts: dict[str, Any], cfg: AiConfig | None, drafts: list[Draft]) -> HomeSummary:
    items = [d.item for d in drafts]
    head = headline(items)
    every = {**facts, "items": [d.facts for d in drafts], "counts": counts(items)}
    if cfg is None:
        return HomeSummary(
            summary_md=head,
            model="code",
            fallback_reason="No AI is set up, so code wrote this.",
            facts=every,
            items=items,
        )
    payload = {
        "KIND": facts.get("kind"),
        "COUNTS": counts(items),
        "ITEMS": [{"id": d.item.id, "title": d.item.title, "detail": d.item.detail, "facts": d.facts} for d in drafts],
    }
    messages = [
        {"role": "system", "content": ITEMS_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = await call_json_model(messages, cfg, strict_json_schema(ItemsOutput), "home_summary_items")
        out = ItemsOutput.model_validate(parse_model_json(raw))
    except (ExtractionError, ValidationError):
        return HomeSummary(
            summary_md=head,
            model=cfg.model,
            fallback_reason="The model's reply was not in the expected format, so code wrote this.",
            facts=every,
            items=items,
        )
    except Exception as exc:  # noqa: BLE001  any model trouble: code's list stands
        return HomeSummary(
            summary_md=head,
            model=cfg.model,
            fallback_reason=f"Your AI ({cfg.mode}) could not word the list ({type(exc).__name__}), so code wrote it.",
            facts=every,
            items=items,
        )
    words = {w.id: w for w in out.items}
    kept: list[str] = []
    worded: list[SummaryItem] = []
    for d in drafts:
        w = words.get(d.item.id)
        if w is None or item_problem(w.title.strip(), (w.detail or "").strip() or None, d):
            kept.append(d.item.id)
            worded.append(d.item)
            continue
        worded.append(d.item.model_copy(update={"title": w.title.strip(), "detail": (w.detail or "").strip() or None}))
    line = out.headline.strip()
    head_facts = {"counts": counts(items), "items": [d.facts for d in drafts]}
    if (
        not line
        or len(line) > 120
        or LINK.search(line)
        or NOT_YET.search(line)
        or ((head_facts["counts"]["now"] or head_facts["counts"]["soon"]) and ALL_CLEAR.search(line))
        or KnownNumbers(head_facts).unknown(line, all_tokens=False)
    ):
        line = head
    reason = (
        None
        if not kept
        else f"Code's words kept for {len(kept)} of {len(drafts)} items: the model's did not check out."
    )
    return HomeSummary(summary_md=line, model=cfg.model, fallback_reason=reason, facts=every, items=worded)
