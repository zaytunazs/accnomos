"""Two more Ask answers the VAT-period facts pack cannot give, worked out by code and worded by the user's AI (checked
like every Ask answer: each figure must be in the facts, app/ai/ask.py KnownNumbers), or by code:

* Profit and loss for the span the question names (app/ask_router.py `pnl_span`): today, yesterday, this or last
  week, month, quarter (calendar quarters), tax year, a named month, or the year so far. Income, costs, profit and
  margin from the same P&L as the Reports page (app/reports.py `profit_and_loss`, traditional basis), in pence.
* What was bought for a job: the posted purchases tagged to the job (the same ones its Jobs page counts as
  materials), with every line of each document: description, quantity, net, supplier and date, each cited.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app import actions
from app import jobs as jobs_
from app import reports as rp
from app.ai.config import AiConfig
from app.ai.home_summary import gbp
from app.ask_more import _RULES, worded
from app.ask_router import Span, pnl_span
from app.books import EVENTS, Books
from app.paypal_reports import period_totals
from app.schemas import AskAnswer, AskPeriod, KeyNumber

# --------------------------------------------------------------------------- #
# Profit and loss
# --------------------------------------------------------------------------- #

PNL_PROMPT = (
    "You answer a UK small business owner's question about their profit, income or costs from FACTS worked out by "
    "code from their approved ledger entries (the same profit and loss as their Reports page). Say which span the "
    "figures are for (FACTS.span), then income, costs and profit (and the margin when there was income). If "
    "FACTS.entries is 0, say nothing was recorded for that span. If FACTS.paypal is there, add one sentence: the "
    "PayPal fees in those costs and the money received through PayPal. " + _RULES
)


def _uk(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def span_words(s: Span) -> str:
    dates = _uk(s.start) if s.start == s.end else f"{_uk(s.start)} – {_uk(s.end)}"
    return f"{s.name} ({dates})"


def margin_pct(profit: int, income: int) -> str | None:
    if income <= 0:
        return None
    return str((Decimal(profit) * 100 / Decimal(income)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def pnl_facts(events: list[Any], s: Span) -> dict[str, Any]:
    pl = rp.profit_and_loss(events, s.start, s.end)
    costs = pl.cost_of_sales.total_pence + pl.overheads.total_pence
    rows = sorted(pl.cost_of_sales.rows + pl.overheads.rows, key=lambda r: -r.amount_pence)
    facts: dict[str, Any] = {
        "span": span_words(s),
        "basis": "approved entries, before VAT, by the date on each document",
        "entries": pl.entries,
        "income": gbp(pl.sales.total_pence),
        "costs": gbp(costs),
        "profit": gbp(pl.net_profit_pence),
        "result": "profit" if pl.net_profit_pence >= 0 else "loss",
        "biggest_costs": [
            {"account": re.sub(r"^\d+\s+", "", r.account), "amount": gbp(r.amount_pence)} for r in rows[:3]
        ],
        "_pence": {"income": pl.sales.total_pence, "costs": costs, "profit": pl.net_profit_pence},
    }
    if (m := margin_pct(pl.net_profit_pence, pl.sales.total_pence)) is not None:
        facts["margin_percent"] = m
    pp = period_totals(e for e in events if s.start <= e.date <= s.end)
    if pp.fees_pence or pp.received_pence:  # only what the books hold: 7900 PayPal fees, money in through 1240
        facts["paypal"] = {
            "fees_in_those_costs": gbp(pp.fees_pence),
            "received_through_paypal": gbp(pp.received_pence),
        }
    return facts


def pnl_code_text(f: dict[str, Any]) -> str:
    if not f["entries"]:
        return f"Nothing was recorded for {f['span']}: no sales and no costs, so no profit or loss."
    word = "a profit" if f["result"] == "profit" else "a loss"
    out = f"For {f['span']}, income was {f['income']} and costs were {f['costs']}: {word} of {f['profit']}"
    out += f" (a {f['margin_percent']}% margin)." if "margin_percent" in f else "."
    if f["biggest_costs"]:
        c = f["biggest_costs"][0]
        out += f" The biggest cost was {c['account']} ({c['amount']})."
    if pp := f.get("paypal"):
        out += (
            f" PayPal fees in those costs were {pp['fees_in_those_costs']}; {pp['received_through_paypal']} came in "
            "through PayPal."
        )
    return out + " Figures are before VAT."


async def pnl_answer(
    question: str, books: Books, cfg: AiConfig | None, period: AskPeriod, today: date, year_start: date | None = None
) -> AskAnswer:
    s = pnl_span(question, today, year_start)
    entries = await books.list_event_entries(s.start, s.end)
    f = pnl_facts([e for _p, e in entries], s)
    shown = {k: v for k, v in f.items() if not k.startswith("_")}
    code_text = pnl_code_text(f)
    if f["entries"]:
        text, by, why = await worded(question, shown, PNL_PROMPT, code_text, cfg, "ask_pnl")
    else:
        text, by, why = code_text, "code", None
    folders = list(dict.fromkeys(p.rsplit("/", 1)[0] + "/" for p, _e in entries)) or [f"{EVENTS}/"]
    src = folders[0]
    label = s.name
    keys = [
        KeyNumber(label=f"Income, {label}", value=f["income"], source=src),
        KeyNumber(label=f"Costs, {label}", value=f["costs"], source=src),
        KeyNumber(label=f"{'Profit' if f['result'] == 'profit' else 'Loss'}, {label}", value=f["profit"],
                  source=src),
    ]  # fmt: skip
    if "margin_percent" in f:
        keys.append(KeyNumber(label="Margin", value=f"{f['margin_percent']}%", source=src))
    return AskAnswer(
        answer_md=text,
        key_numbers=keys,
        citations=folders[:6],
        suggested_actions=[],
        confidence="high" if by == "model" else "medium",
        model=cfg.model if (cfg and by == "model") else "code",
        period=AskPeriod(start=s.start, end=s.end),
        fallback_reason=why,
    )


# --------------------------------------------------------------------------- #
# What was bought for a job
# --------------------------------------------------------------------------- #

_BOUGHT = re.compile(
    r"\b(?:order(?:ed)?|bought|buy|purchas(?:e|es|ed)|materials?|items?|spen[dt] on|supplies)\b", re.IGNORECASE
)
_FOR = re.compile(r"\b(?:for|on|at)\s+(?:the\s+)?(.+?)(?:\s+job)?\s*[?.!]*\s*$", re.IGNORECASE)
_STOP = {
    "what", "which", "did", "we", "i", "our", "my", "the", "for", "on", "job", "order", "ordered", "buy", "bought",
    "items", "item", "materials", "material", "purchase", "purchased", "purchases", "have", "has", "were", "was",
    "get", "got", "colour", "color", "kind", "type", "much", "many", "how", "and", "a", "an", "of", "in", "at", "to",
}  # fmt: skip


def job_ref_in(question: str) -> str | None:
    """The words naming the job: after the last "for/on/at", without a trailing "job"."""
    if not _BOUGHT.search(question):
        return None
    if not (actions._QUESTION_START.match(question) or question.rstrip().endswith("?")):  # noqa: SLF001
        return None  # "remember to order bolts for the Hendon job" is the shopping list, not a question
    found = _FOR.findall(question)
    ref = (found[-1] if found else "").strip(" ,.?!")
    return ref or None


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP and len(w) >= 3}


async def job_items_answer(question: str, books: Books, cfg: AiConfig | None, period: AskPeriod) -> AskAnswer | None:
    """None when the question is not about what was bought for a job this business has."""
    ref = job_ref_in(question)
    if ref is None:
        return None
    options = [actions.Option(j.id, j.name, (), j) for j in await jobs_.load_jobs(books)]
    if not options:
        return None
    hit = actions.pick(ref, options, "log_timesheet", "job", "job")
    if not isinstance(hit, actions.Picked):
        # Only answer when the question plainly means a job; otherwise let the ordinary Ask path have it.
        if not re.search(r"\bjob\b", question, re.IGNORECASE):
            return None
        return AskAnswer(
            answer_md=hit.question_md, key_numbers=[], citations=[], suggested_actions=[], confidence="low",
            model="code", period=period,
        )  # fmt: skip
    job = hit.option.data
    entries = await books.list_event_entries()
    paths = {e.id: p for p, e in entries}
    proposals = [p for p in await books.list_proposals("posted") if p.job_id == job.id]
    bought = jobs_.job_purchases(job.id, proposals, [e for _p, e in entries])
    by_id = {p.id: p for p in proposals}
    docs, lines = [], []
    for b in bought:
        p = by_id[b["proposal_id"]]
        src = paths.get(b["event_id"]) or p.file_path or f"{EVENTS}/"
        doc_lines = [
            {
                "item": ln.description,
                "quantity": f"{ln.qty:g}",
                "net": gbp(round(ln.net * 100)),
            }
            for ln in p.extracted.lines
        ]
        docs.append(
            {
                "date": _uk(date.fromisoformat(b["date"])),
                "supplier": b["supplier"] or p.extracted.supplier_name,
                "net": gbp(b["net_pence"]),
                "items": doc_lines,
                "source": src,
            }
        )
        lines += [(ln, docs[-1]) for ln in doc_lines]
    total = sum(b["net_pence"] for b in bought)
    asked = _words(question) - _words(job.name)
    focus = [(ln, d) for ln, d in lines if asked & _words(ln["item"])]
    f: dict[str, Any] = {
        "job": job.name,
        "purchases": len(docs),
        "total_net": gbp(total),
        "documents": [{k: v for k, v in d.items() if k != "source"} for d in docs][:8],
    }
    if focus:
        f["asked_about"] = [{"item": ln["item"], "supplier": d["supplier"], "date": d["date"], "net": ln["net"]}
                            for ln, d in focus][:5]  # fmt: skip
    code_text = job_items_code_text(f)
    if docs:
        prompt = (
            "You answer a UK small business owner's question about what was bought for one of their jobs, from FACTS "
            "worked out by code from the purchases tagged to that job. If FACTS.asked_about is present, answer with "
            "those items first (their exact descriptions, supplier and date). Otherwise list the main items. " + _RULES
        )
        text, by, why = await worded(question, f, prompt, code_text, cfg, "ask_job_items")
    else:
        text, by, why = code_text, "code", None
    cites = list(dict.fromkeys([d["source"] for _ln, d in focus] + [d["source"] for d in docs])) or [f"{EVENTS}/"]
    keys = [KeyNumber(label=f"Bought for {job.name} (before VAT)", value=gbp(total), source=cites[0])]
    for ln, d in (focus or lines)[:3]:
        keys.append(KeyNumber(label=f"{ln['item']} · {d['supplier']}, {d['date']}"[:80], value=ln["net"],
                              source=d["source"]))  # fmt: skip
    return AskAnswer(
        answer_md=text,
        key_numbers=keys[:4],
        citations=cites[:8],
        suggested_actions=[],
        confidence="high" if by == "model" else "medium",
        model=cfg.model if (cfg and by == "model") else "code",
        period=period,
        fallback_reason=why,
    )


def job_items_code_text(f: dict[str, Any]) -> str:
    if not f["purchases"]:
        return f"No purchases are tagged to {f['job']} yet. Tag a receipt to the job when you approve it in Review."
    if f.get("asked_about"):
        parts = [f"{a['item']} from {a['supplier']} on {a['date']} ({a['net']})" for a in f["asked_about"]]
        return f"For {f['job']} you bought " + "; ".join(parts) + "."
    out = f"For {f['job']} you have {f['purchases']} purchases, {f['total_net']} before VAT: "
    out += "; ".join(
        f"{d['supplier']} on {d['date']}: " + ", ".join(i["item"] for i in d["items"]) for d in f["documents"]
    )
    return out + "."
