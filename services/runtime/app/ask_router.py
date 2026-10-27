"""Which parts of the facts pack a question needs, and which period it asks about. Code, no model.

A keyword router: cheap, predictable and testable. The model then sees only the sections the question needs
plus an always-on summary, so the prompt stays under PACK_TOKENS and, as importantly, the other period's figures
are not in front of it when the question is about one period. The same route tells grounding (app/ai/ask.py)
which period a quoted figure must belong to, and gives code the key numbers and citations it shows before the
model has written a word.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.books import EVENTS, PROPOSALS, WORKBOOK
from app.paths import VAT_RETURNS

THIS, PREV = "this", "previous"
SECTIONS = ("vat", "totals", "suppliers", "customers", "transactions", "pending")

#: Budget for the pack sent to the model. Measured on Glimmer: 2.8 bytes of compact facts JSON per prompt token
#: (evals/runs/ask_40/report.md), so 2.7 slightly over-counts on purpose.
PACK_TOKENS = 1500
BYTES_PER_TOKEN = 2.7

#: Asked about, but not in the facts pack at all: the model should say the books it was given don't show it.
NOT_IN_FACTS = ["bank balances", "payroll and wages", "jobs", "deadlines", "corporation tax", "contact details"]

_I = re.IGNORECASE
_KEYWORDS: dict[str, re.Pattern[str]] = {
    "vat": re.compile(r"\bvat\b|\bbox\s*[1-9]\b|\bhmrc\b|\breclaim|\bowe\b|\brepa(?:y|id)\b|\breturn\b|\b(?:input|output) tax\b", _I),
    "totals": re.compile(
        r"\bsales?\b|\bsold\b|\bturnover\b|\brevenue\b|\bincome\b|\btakings\b|\bpurchases?\b|\bspen[dt]\b|\bbought\b|"
        r"\bcosts?\b|\bexpenses?\b|\bentr(?:y|ies)\b|\breduced\b|\bzero\b|\bexempt\b|\bcode [srzne]\b|\binvoices?\b", _I),
    "suppliers": re.compile(r"\bsuppliers?\b|\bvendors?\b|\b(?:spen[dt]|spending) with\b|\bbought from\b(?! me)|\bcontacts?\b", _I),
    "customers": re.compile(r"\bcustomers?\b|\bclients?\b|\bfrom me\b|\binvoices?\b|\bcontacts?\b", _I),
    "transactions": re.compile(r"\blargest\b|\bbiggest single\b|\bsingle\b|\btransactions?\b|\breceipts?\b|\binvoice on\b|\bpurchase on\b", _I),
    "pending": re.compile(r"\breview\b|\bwaiting\b|\bpending\b|\bproposals?\b|\binbox\b|\bto approve\b|\bneeds? a look\b", _I),
}
_OUTSIDE = re.compile(r"\bbank\b|\bbalance\b|\bpayroll\b|\bwages?\b|\bsalar(?:y|ies)\b|\bjobs?\b|\bdeadlines?\b|\bdue date\b|"
                      r"\bcorporation tax\b|\bself.assessment\b|\bphone\b|\bemail address\b", _I)
_BOX = re.compile(r"\bbox\s*([1-9])\b", _I)
_RECLAIM = re.compile(r"\breclaim|\binput tax\b|\bback from hmrc\b", _I)
_CHARGED = re.compile(r"\bcharged?\b|\boutput tax\b|\bvat on (?:my )?sales\b", _I)
_SALES = re.compile(r"\bsales?\b|\bsold\b|\bturnover\b|\brevenue\b|\bincome\b|\btakings\b|\bfrom me\b", _I)
_PURCHASES = re.compile(r"\bpurchases?\b|\bspen[dt]\b|\bbought\b(?! from me)|\bcosts?\b|\bexpenses?\b", _I)
_COUNT = re.compile(r"\bhow many\b|\bnumber of\b", _I)
_ENTRIES = re.compile(r"\bentries\b", _I)
_CODES = {"R": re.compile(r"\breduced\b|\b5 ?%", _I), "Z": re.compile(r"\bzero\b", _I), "E": re.compile(r"\bexempt\b", _I),
          "N": re.compile(r"\bno vat invoice\b|\bcode n\b|\boutside the scope\b", _I)}
_LARGEST = re.compile(r"\blargest\b|\bbiggest single\b", _I)
_TOP = re.compile(r"\bbiggest\b|\btop\b|\blargest\b|\bmost\b|\bmain\b", _I)

#: Phrases that pin a figure (in a question or in an answer's sentence) to one period.
PREV_WORDS = re.compile(r"\b(?:last|previous|prior|preceding)\s+(?:vat\s+)?(?:quarter|period|return|month|three months)\b|\bbefore that\b", _I)
THIS_WORDS = re.compile(r"\b(?:this|current)\s+(?:vat\s+)?(?:quarter|period|return|month)\b|\bso far\b|\bright now\b|\btoday\b", _I)
_COMPARE = re.compile(r"\bcompared?\b|\bvs\.?\b|\bversus\b|\bsince\b|\bthan\b|\bchang(?:e|ed|es)\b|\bgr[eo]wn?\b|\bgrowth\b|"
                      r"\b(?:rise|rose|risen|fall|fell|fallen|drop(?:ped)?)\b|\bup on\b|\bdown on\b|\bdifference\b|"
                      r"\bincrease[ds]?\b|\bdecrease[ds]?\b|\bgone (?:up|down)\b|\bwent (?:up|down)\b", _I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"))}
_MONTH = re.compile(rf"\b({'|'.join(_MONTHS)}|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b(?:\s+(\d{{4}}))?", _I)


@dataclass(frozen=True)
class Route:
    sections: frozenset[str]
    periods: frozenset[str]  # THIS and/or PREV: the period(s) the question asks about
    compare: bool = False  # a change between the two periods
    boxes: tuple[int, ...] = ()  # VAT boxes asked for by number, or implied ("reclaim" = 4)
    sales: bool = False
    purchases: bool = False
    count: bool = False
    entries: bool = False
    codes: tuple[str, ...] = ()  # VAT codes asked about ("reduced rate" = R)
    largest: bool = False
    top: bool = False
    names: tuple[str, ...] = ()  # counterparties in the facts that the question names
    matched: bool = True  # False: no keyword matched, so every section is sent and code picks no specific figures

    def label(self, facts: dict[str, Any]) -> str:
        return " and ".join(facts[period_key(p)]["label"] for p in (THIS, PREV) if p in self.periods)


def period_key(p: str) -> str:
    return "this_period" if p == THIS else "previous_period"


def other(p: str) -> str:
    return PREV if p == THIS else THIS


EVERYTHING = Route(sections=frozenset(SECTIONS), periods=frozenset({THIS}), matched=False)


def _counterparties(facts: dict[str, Any]) -> list[str]:
    names = [t["name"] for t in facts.get("top_suppliers", []) + facts.get("top_customers", [])]
    names += [t["counterparty"] for t in facts.get("largest_transactions", [])]
    return list(dict.fromkeys(n for n in names if n and n != "(no name)"))


def _named(question: str, facts: dict[str, Any]) -> tuple[str, ...]:
    """Counterparties named in full, or by their first distinctive word ("Oakhurst", "Sterling")."""
    q = question.lower()
    found = []
    for name in _counterparties(facts):
        first = re.split(r"[\s&,.]+", name.lower())[0]
        if name.lower() in q or (len(first) >= 4 and re.search(rf"\b{re.escape(first)}\b", q)):
            found.append(name)
    return tuple(found)


def _month_periods(question: str, facts: dict[str, Any]) -> set[str]:
    """THIS/PREV for each month the question names ("in May", "on 19 September"), by the periods' own dates."""
    out: set[str] = set()
    spans = {p: (date.fromisoformat(facts[period_key(p)]["start"]), date.fromisoformat(facts[period_key(p)]["end"])) for p in (THIS, PREV)}
    for m in _MONTH.finditer(question):
        word = m.group(1).lower()
        if word == "may" and not re.search(r"\bin may\b|\bmay \d{4}\b|\d+(?:st|nd|rd|th)? may\b", question, _I):
            continue  # "may" the verb
        month = next(i for name, i in _MONTHS.items() if name.startswith(word[:3]))
        years = [int(m.group(2))] if m.group(2) else sorted({d.year for span in spans.values() for d in span})
        for p, (start, end) in spans.items():
            if any(start.replace(day=1) <= date(y, month, 1) <= end for y in years):
                out.add(p)
    return out


def route(question: str, facts: dict[str, Any]) -> Route:
    """The sections and period(s) a question needs. No keyword at all: every section, the current period."""
    q = question.strip()
    sections = {s for s, rx in _KEYWORDS.items() if rx.search(q)}
    names = _named(q, facts)
    suppliers = {t["name"] for t in facts.get("top_suppliers", [])}
    customers = {t["name"] for t in facts.get("top_customers", [])}
    for n in names:
        sections |= {"transactions"} | ({"suppliers"} if n in suppliers else set()) | ({"customers"} if n in customers else set())
    outside = bool(_OUTSIDE.search(q))
    matched = bool(sections) or outside
    if not matched:
        sections = set(SECTIONS)

    months = _month_periods(q, facts)
    asks_prev = bool(PREV_WORDS.search(q)) or PREV in months
    asks_this = bool(THIS_WORDS.search(q)) or THIS in months
    compare = bool(_COMPARE.search(q)) and not (asks_this and not asks_prev and THIS in months)
    if compare or (asks_prev and asks_this):
        periods = {THIS, PREV}
    elif asks_prev:
        periods = {PREV}
    else:
        periods = {THIS}

    boxes = tuple(dict.fromkeys(int(b) for b in _BOX.findall(q)))
    if not boxes and "vat" in sections:
        boxes = (4,) if _RECLAIM.search(q) else (1,) if _CHARGED.search(q) else ()
    return Route(
        sections=frozenset(sections), periods=frozenset(periods), compare=compare and periods == {THIS, PREV},
        boxes=boxes, sales=bool(_SALES.search(q)), purchases=bool(_PURCHASES.search(q)), count=bool(_COUNT.search(q)),
        entries=bool(_ENTRIES.search(q)), codes=tuple(c for c, rx in _CODES.items() if rx.search(q)),
        largest=bool(_LARGEST.search(q)), top=bool(_TOP.search(q)), names=names, matched=matched,
    )


# --------------------------------------------------------------------------- #
# The pack the model sees
# --------------------------------------------------------------------------- #

def approx_tokens(node: Any) -> int:
    return math.ceil(len(json.dumps(node, separators=(",", ":"), ensure_ascii=False).encode()) / BYTES_PER_TOKEN)


def sources_for(facts: dict[str, Any], periods: frozenset[str] | set[str]) -> list[str]:
    """The listed sources behind `periods`: their ledger month folders, any filed return for them, the workbook."""
    spans = [(facts[period_key(p)]["start"][:7], facts[period_key(p)]["end"][:7], facts[period_key(p)]["period_key"]) for p in periods]
    out = []
    for s in facts["sources"]:
        if s.startswith(EVENTS) and s.endswith("/"):
            month = s.removeprefix(f"{EVENTS}/").rstrip("/")
            if any(a <= month <= b for a, b, _k in spans):
                out.append(s)
        elif s.startswith(VAT_RETURNS) and any(k in s for _a, _b, k in spans):
            out.append(s)
        elif s == WORKBOOK:
            out.append(s)
    return out


def pack(facts: dict[str, Any], r: Route) -> dict[str, Any]:
    """The facts the model sees for this route: the summary, the routed sections for the asked period(s), within PACK_TOKENS.

    Each figure sits under the period it belongs to; the period not asked about keeps only its dates.
    """
    out: dict[str, Any] = {"business": facts["business"], "money": facts["money"]}
    for p in (THIS, PREV):
        full = facts[period_key(p)]
        part: dict[str, Any] = {k: full[k] for k in ("label", "start", "end", "period_key")}
        if p in r.periods:
            part["entries"] = full["entries"]
            if "vat" in r.sections:
                part["vat"] = full["vat"]
                if p == THIS:
                    part["vat_position"] = facts["derived"]["vat_position"]
            if "totals" in r.sections:
                part["totals"] = full["totals"]
            if p == THIS:
                for section, key in (("suppliers", "top_suppliers"), ("customers", "top_customers"), ("transactions", "largest_transactions")):
                    if section in r.sections:
                        part[key] = facts[key]
        else:
            part["figures"] = "not needed for this question"
        out[period_key(p)] = part
    if r.compare:
        keep = ("box",) * ("vat" in r.sections) + ("sales", "purchases") * ("totals" in r.sections)
        out["derived"] = {k: v for k, v in facts["derived"].items() if k != "vat_position" and k.startswith(keep)} if keep else {}
    if "pending" in r.sections and facts.get("pending_proposals") is not None:
        out["pending_proposals"] = facts["pending_proposals"]
    out["not_in_these_facts"] = NOT_IN_FACTS
    out["sources"] = _pack_sources(facts, r, out)
    _fit(out, facts, r)
    return out


def _pack_sources(facts: dict[str, Any], r: Route, out: dict[str, Any]) -> list[str]:
    txns = [t["source"] for t in out["this_period"].get("largest_transactions", [])]
    extra = [f"{PROPOSALS}/"] if "pending_proposals" in out and f"{PROPOSALS}/" in facts["sources"] else []
    return list(dict.fromkeys(sources_for(facts, r.periods) + txns + extra)) or facts["sources"][:1]


def _fit(out: dict[str, Any], facts: dict[str, Any], r: Route) -> None:
    """Shorten the lists (then drop VAT-code detail) until the pack is within PACK_TOKENS."""
    this = out["this_period"]
    for n in (6, 4, 2, 0):
        if approx_tokens(out) <= PACK_TOKENS:
            return
        for key in ("largest_transactions", "top_suppliers", "top_customers"):
            if key in this:
                this[key] = this[key][:n]
        if n <= 2:
            for p in (THIS, PREV):
                out[period_key(p)].get("totals", {}).pop("by_vat_code", None)
        out["sources"] = _pack_sources(facts, r, out)
