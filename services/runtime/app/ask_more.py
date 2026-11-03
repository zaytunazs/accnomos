"""Two Ask answers the VAT-period facts pack cannot give, each worked out by code from the same figures the app shows
elsewhere, worded by the user's AI and checked (every figure must be in the facts, as app/ai/ask.py KnownNumbers):

* Who owes me / who do I owe: the aged balances Home's "Owed to you" card and the Aged report use
  (app/contacts.py `aged`), not the VAT quarter's totals.
* A household's question (profile kind "personal"): money in and out this month and last, by category, and what was
  spent on a thing the question names ("coffee", "Tesco"), from the household's own bank lines and categories
  (app/personal.py). A household has no VAT return, so its questions never fall back to VAT boxes.

Code writes the answer when no AI is set up, when the model's words do not check out, or when there is nothing to say.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import ValidationError

from accnomos_ledger.bank import BankLine
from app import contacts as cb
from app import personal as pf
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.ai.home_summary import LINK, gbp
from app.books import EVENTS, Books
from app.schemas import AskAnswer, AskExplanation, AskPeriod, KeyNumber, strict_json_schema

ANSWER_MAX = 900
_I = re.IGNORECASE

_TAX = re.compile(r"\bvat\b|\bhmrc\b|\btax\b|\breturn\b", _I)
_OWED_TO_ME = re.compile(
    r"\bowes? me\b|\bowed to me\b|\bowing me\b|\bowed to (?:us|the business)\b|\bowes? us\b|\bdebtors?\b|"
    r"\b(?:has|have)n'?t paid\b|\bha(?:s|ve) not paid\b|\bunpaid invoices?\b|\boutstanding invoices?\b|"
    r"\boverdue invoices?\b|\bwho (?:still )?(?:needs to|has to) pay me\b|\bmoney (?:i'?m|i am) owed\b",
    _I,
)
_I_OWE = re.compile(
    r"\bwho do (?:i|we) owe\b|\b(?:i|we) owe (?:the most|most|money|suppliers?)\b|\bcreditors?\b|"
    r"\bunpaid bills?\b|\boverdue bills?\b|\bbills? (?:to pay|outstanding|i owe)\b|\bowe(?:d)? to suppliers?\b",
    _I,
)

Side = Literal["debtors", "creditors"]


def owed_intent(question: str) -> Side | None:
    """Which side of the aged balances a question asks about, or None. A VAT question ("how much VAT do I owe")
    stays with the VAT facts."""
    if _TAX.search(question):
        return None
    if _OWED_TO_ME.search(question):
        return "debtors"
    if _I_OWE.search(question):
        return "creditors"
    return None


# --------------------------------------------------------------------------- #
# Words: the model's, checked; else code's
# --------------------------------------------------------------------------- #


def check(text: str, facts: dict[str, Any]) -> str | None:
    """Why the model's words cannot be shown, or None."""
    if not text.strip():
        return "The model returned an empty answer."
    if LINK.search(text):
        return "The model's answer contained a link."
    if invented := ask_ai.KnownNumbers(facts).unknown(text, all_tokens=False):
        return f"The model quoted figures that are not in your books ({', '.join(dict.fromkeys(invented[:3]))})."
    return None


async def worded(
    question: str, facts: dict[str, Any], system: str, code_text: str, cfg: AiConfig | None, name: str
) -> tuple[str, str, str | None]:
    """(answer, "model"|"code", why code wrote it). Never raises for model trouble."""
    if cfg is None:
        return code_text, "code", "No AI is set up, so code wrote this."
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"QUESTION: {question}\nFACTS:\n" + json.dumps(facts, ensure_ascii=False, separators=(",", ":")),
        },
    ]
    try:
        raw = await ask_ai.call_json_model(messages, cfg, strict_json_schema(AskExplanation), name)
        out = AskExplanation.model_validate(parse_model_json(raw))
    except (ExtractionError, ValidationError):
        return code_text, "code", "The model's reply was not in the expected format."
    except Exception as exc:  # noqa: BLE001  model trouble of any kind: code's answer instead
        return code_text, "code", ask_ai._trouble(exc, cfg)  # noqa: SLF001
    text = ask_ai._clip(out.answer_md, ANSWER_MAX)  # noqa: SLF001
    if (why := check(text, facts)) is not None:
        return code_text, "code", why
    return text, "model", None


_RULES = (
    "Rules: 1) Quote figures exactly as they appear in FACTS (they already carry £ and commas); never add, subtract, "
    "average or estimate anything yourself. 2) Two to four short sentences of plain UK English markdown, no headings, "
    "no tables, no links. 3) If FACTS has nothing that answers the question, say what FACTS does show. "
    "Return JSON with answer_md and confidence."
)


def _answer(
    text: str, by: str, why: str | None, cfg: AiConfig | None, period: AskPeriod, keys: list[KeyNumber]
) -> AskAnswer:
    return AskAnswer(
        answer_md=text,
        key_numbers=keys[:4],
        citations=[f"{EVENTS}/"],
        suggested_actions=[],
        confidence="high" if by == "model" else "medium",
        model=cfg.model if (cfg and by == "model") else "code",
        period=period,
        fallback_reason=why,
    )


# --------------------------------------------------------------------------- #
# Who owes me / who do I owe
# --------------------------------------------------------------------------- #

OWED_PROMPT = (
    "You answer a UK small business owner's question about who owes them money, or whom they owe, from FACTS worked "
    "out by code from their own approved invoices and bills (the same aged balances as their Home page). Name the "
    "contact with the most outstanding first, say how much of it is overdue, then give the total. " + _RULES
)


def owed_facts(table: cb.AgedTable, side: Side, as_of: date) -> dict[str, Any]:
    rows = sorted(table.rows, key=lambda r: (-r.total_pence, r.name))
    current = table.buckets.get("current", 0)

    def row(r: cb.AgedRow) -> dict[str, Any]:
        late = [d for d in r.documents if d.age_days > 0]
        out: dict[str, Any] = {
            "name": r.name,
            "outstanding": gbp(r.total_pence),
            "overdue": gbp(r.total_pence - r.buckets.get("current", 0)),
            "documents": len(r.documents),
        }
        if late:
            out["most_days_overdue"] = max(d.age_days for d in late)
        return out

    return {
        "as_of": f"{as_of.day} {as_of:%b %Y}",
        "side": "customers who owe you" if side == "debtors" else "suppliers you owe",
        "total_outstanding": gbp(table.total_pence),
        "total_overdue": gbp(table.total_pence - current),
        "documents": sum(len(r.documents) for r in rows),
        "contacts": [row(r) for r in rows[:6]],
    }


def owed_code_text(f: dict[str, Any], side: Side) -> str:
    if not f["contacts"]:
        return (
            "No customer owes you anything on your approved invoices."
            if side == "debtors"
            else ("You owe no supplier anything on your approved bills.")
        )
    top = f["contacts"][0]
    late = f" ({top['most_days_overdue']} days overdue at most)" if top.get("most_days_overdue") else ""
    if side == "debtors":
        first = f"{top['name']} owes you the most: {top['outstanding']}, of which {top['overdue']} is overdue{late}."
        total = f"In all, customers owe you {f['total_outstanding']}, {f['total_overdue']} of it overdue"
    else:
        first = f"You owe {top['name']} the most: {top['outstanding']}, of which {top['overdue']} is overdue{late}."
        total = f"In all, you owe suppliers {f['total_outstanding']}, {f['total_overdue']} of it overdue"
    others = [c for c in f["contacts"][1:3]]
    more = ""
    if others:
        more = " Next: " + "; ".join(f"{c['name']} {c['outstanding']}" for c in others) + "."
    return f"{first} {total} (as at {f['as_of']}).{more}"


async def owed_answer(
    question: str, side: Side, books: Books, cfg: AiConfig | None, period: AskPeriod, as_of: date
) -> AskAnswer:
    contacts, ledger, _ = await cb.contact_book(books)
    balances = cb.aged(contacts, ledger, as_of)
    table = balances.debtors if side == "debtors" else balances.creditors
    f = owed_facts(table, side, as_of)
    code_text = owed_code_text(f, side)
    if f["contacts"]:
        text, by, why = await worded(question, f, OWED_PROMPT, code_text, cfg, "ask_owed")
    else:
        text, by, why = code_text, "code", None
    label = "Owed to you" if side == "debtors" else "You owe"
    keys = [
        KeyNumber(label=label, value=f["total_outstanding"], source=f"{EVENTS}/"),
        KeyNumber(label="Overdue", value=f["total_overdue"], source=f"{EVENTS}/"),
    ]
    if f["contacts"]:
        top = f["contacts"][0]
        keys.append(KeyNumber(label=top["name"], value=top["outstanding"], source=f"{EVENTS}/"))
    return _answer(text, by, why, cfg, period, keys)


# --------------------------------------------------------------------------- #
# A household's questions
# --------------------------------------------------------------------------- #

HOUSEHOLD_PROMPT = (
    "You answer a question about a UK household's own money from FACTS worked out by code from their bank statements "
    "and their spending categories. This is a household, not a business: never mention VAT, HMRC, turnover, profit "
    "or invoices. If FACTS.asked_about is present, answer with its figures first (this month so far and last "
    "month). Otherwise answer from the months and categories. " + _RULES
)

_FOCUS = re.compile(
    r"\b(?:on|at|for|with|in)\s+([a-z][a-z0-9 &'.-]{1,40}?)(?=\s+(?:this|last|in|so|over|during)\b|[?.!,]|$)", _I
)
_STOP = {
    "the",
    "a",
    "an",
    "my",
    "our",
    "me",
    "it",
    "this",
    "that",
    "month",
    "week",
    "year",
    "total",
    "average",
    "money",
    "things",
    "stuff",
    "budget",
    "budgets",
    "november",
    "october",
    "december",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "today",
    "now",
    "so",
    "far",
}


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _label(d: date, so_far: bool) -> str:
    return f"{d:%B %Y}" + (" so far" if so_far else "")


def focus_of(question: str, category_names: list[str]) -> str | None:
    """The thing a household question asks about: a category it names, else the words after "on/at/for"."""
    q = question.casefold()
    for name in sorted(category_names, key=len, reverse=True):
        if name.casefold() in q and name.casefold() not in ("other",):
            return name
    for m in _FOCUS.finditer(question):
        words = [w for w in re.split(r"\s+", m.group(1).strip(" .'")) if w.casefold() not in _STOP]
        if words:
            return " ".join(words)
    return None


def household_facts(
    question: str,
    lines: list[BankLine],
    categories: list[pf.Category],
    budgets: dict[str, int],
    rules: list[pf.PersonalRule],
    overrides: dict[str, str],
    today: date,
) -> dict[str, Any]:
    last_day = today.replace(day=1) - timedelta(days=1)
    this = pf.summarise_month(_month_key(today), lines, categories, budgets, rules, overrides)
    last = pf.summarise_month(_month_key(last_day), lines, categories, budgets, rules, overrides)
    last_by = {c.id: c.spent_pence for c in last.categories}

    def month(m: pf.MonthlySummary, label: str) -> dict[str, Any]:
        return {
            "label": label,
            "money_in": gbp(m.income_pence),
            "money_out": gbp(m.spent_pence),
            "left": gbp(m.left_pence),
        }

    facts: dict[str, Any] = {
        "kind": "household",
        "this_month": month(this, _label(today, True)),
        "last_month": month(last, _label(last_day, False)),
        "categories_this_month": [
            {
                "category": c.name,
                "spent": gbp(c.spent_pence),
                **({"budget": gbp(c.budget_pence)} if c.budget_pence else {}),
                "last_month": gbp(last_by.get(c.id, 0)),
            }
            for c in sorted(this.categories, key=lambda c: -c.spent_pence)
            if c.spent_pence or last_by.get(c.id)
        ][:10],
    }
    focus = focus_of(question, [c.name for c in categories])
    if focus:
        known = {c.id for c in categories}
        names = {c.id: c.name for c in categories}
        f = focus.casefold()

        def spent_on(start: date, end: date) -> tuple[int, int, dict[str, int]]:
            total = n = 0
            payees: dict[str, int] = {}
            for ln in lines:
                if not (pf.counts(ln) and start <= ln.date <= end and ln.amount_pence < 0):
                    continue
                cat, _how = pf.categorise(ln, rules, overrides, known)
                if f in names.get(cat, "").casefold() or f in ln.description.casefold():
                    total += -ln.amount_pence
                    n += 1
                    key = pf.payee_key(ln.description).title() or ln.description[:30]
                    payees[key] = payees.get(key, 0) + -ln.amount_pence
            return total, n, payees

        t_total, t_n, t_payees = spent_on(today.replace(day=1), today)
        l_total, l_n, _ = spent_on(last_day.replace(day=1), last_day)
        facts["asked_about"] = {
            "what": focus,
            "this_month": {"label": _label(today, True), "spent": gbp(t_total), "payments": t_n},
            "last_month": {"label": _label(last_day, False), "spent": gbp(l_total), "payments": l_n},
            "top_payees_this_month": [
                {"payee": k, "spent": gbp(v)} for k, v in sorted(t_payees.items(), key=lambda kv: -kv[1])[:3]
            ],
        }
    return facts


def household_code_text(f: dict[str, Any]) -> str:
    a = f.get("asked_about")
    if a:
        t, last = a["this_month"], a["last_month"]
        if not t["payments"] and not last["payments"]:
            return f"Nothing on your bank statements matches “{a['what']}” this month or last month."
        out = (
            f"You spent {t['spent']} on {a['what']} in {t['label']} ({t['payments']} payments), "
            f"against {last['spent']} in {last['label']} ({last['payments']} payments)."
        )
        if a["top_payees_this_month"]:
            p = a["top_payees_this_month"][0]
            out += f" Most of it went to {p['payee']} ({p['spent']})."
        return out
    t, last = f["this_month"], f["last_month"]
    out = (
        f"In {t['label']}, {t['money_in']} came in and {t['money_out']} went out, leaving {t['left']}; "
        f"in {last['label']} {last['money_in']} came in and {last['money_out']} went out."
    )
    cats = f["categories_this_month"]
    if cats:
        out += f" Most went on {cats[0]['category']} ({cats[0]['spent']})."
    return out


async def household_answer(
    question: str, books: Books, cfg: AiConfig | None, period: AskPeriod, today: date
) -> AskAnswer:
    lines = await books.stored_bank_lines()
    f = household_facts(
        question,
        list(lines),
        await pf.load_categories(books),
        await pf.load_budgets(books),
        await pf.load_rules(books),
        await pf.load_overrides(books),
        today,
    )
    code_text = household_code_text(f)
    text, by, why = await worded(question, f, HOUSEHOLD_PROMPT, code_text, cfg, "ask_household")
    a = f.get("asked_about")
    keys = (
        [
            KeyNumber(label=f"{a['what']}, {a['this_month']['label']}", value=a["this_month"]["spent"], source="bank"),
            KeyNumber(label=f"{a['what']}, {a['last_month']['label']}", value=a["last_month"]["spent"], source="bank"),
        ]
        if a
        else [
            KeyNumber(
                label=f"Money out, {f['this_month']['label']}", value=f["this_month"]["money_out"], source="bank"
            ),
            KeyNumber(label=f"Money in, {f['this_month']['label']}", value=f["this_month"]["money_in"], source="bank"),
        ]
    )
    out = _answer(text, by, why, cfg, period, keys)
    out.citations = ["bank statements"]
    return out
