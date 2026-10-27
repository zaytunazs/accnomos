"""Answer a question about the user's books from a facts pack. Numbers from code, words from the model.

Code routes the question (app/ask_router.py): which sections of the facts it needs and which period it asks
about. Code picks the key numbers and citations for that route, so they can be shown at once; the model sees
only the routed pack and writes the explanation as strict JSON ({answer_md, confidence}). Then code checks
it: every figure it quotes must be in the facts, and from the period asked about (a real figure from the other
period counts as wrong unless the sentence says which period it is). If it fails either check its words are
dropped and the answer quotes the facts for the asked period directly.

Backends mirror app/ai/extract.py: Ollama `/api/chat` with `format` = schema and `think: false`;
Meta Model API `/chat/completions` with `response_format` json_schema strict. Both are streamed, with a
timeout per chunk rather than per answer, and a cap on the reply's length so a runaway cannot spin for minutes.
(Ollama 0.40's glimmer parser holds a schema-constrained reply until it is complete, so on Glimmer the
explanation arrives in one piece; OpenAI-compatible servers send it token by token.)
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.ask_router import EVERYTHING, PREV, PREV_WORDS, THIS, THIS_WORDS, Route, other, pack, period_key, route, sources_for
from app.facts import vat_sources
from app.schemas import (
    ASK_ANSWER_MAX,
    AskAnswer,
    AskExplanation,
    AskModelOutput,
    AskPeriod,
    AskTurn,
    KeyNumber,
    SuggestedAction,
    strict_json_schema,
)

TIMEOUT_S = 120.0  # whole-reply timeout for the short structured calls that are not streamed (actions, triage, reminders)
FIRST_CHUNK_S = 90.0  # loading the model and reading the prompt (and, on Glimmer, writing the whole buffered reply)
TOKEN_GAP_S = 20.0  # once it is replying, the longest silence between two chunks
ANSWER_TOKENS_MAX = 320  # Glimmer writes about 8 tokens/s here: at most ~40 s, and a good answer needs ~100
KEY_TOKENS_MAX = 1500  # key mode: OpenAI-style servers count the model's reasoning (Qwen still reasons at "low") too
KEY_NUMBERS = (2, 5)
MAX_ACTIONS = 3
LABEL_MAX = 80
ANY = "any"  # a value that belongs to no single period (changes, counts of waiting items, the question's own figures)

SYSTEM_PROMPT = (
    "You answer a UK small business owner's questions about their own books. Write in plain UK English, "
    "short and friendly, as plain markdown: one to three short sentences, no tables, no headings. "
    "The app already shows the key figures, the files used and any buttons, so do not list them again. "
    f"Keep answer_md under {ASK_ANSWER_MAX} characters. "
    "You are given FACTS as JSON, calculated by code from the owner's ledger. Every figure sits under the period it "
    "belongs to: this_period is the period the owner picked (what they mean by 'this quarter'), previous_period the "
    "one before it ('last quarter'); each has its label. FACTS.question_is_about says which one the question means. Rules: "
    "1) Quote numbers only exactly as they appear in FACTS (you may add £ and thousands commas), and only for "
    "their own period: say which period a figure is for. "
    "Never add, subtract, average or estimate anything yourself: for changes use the `derived` values. "
    "2) If FACTS do not answer the question (see not_in_these_facts), say plainly that the books you were given "
    "don't show it, and suggest what would. "
    "3) confidence: high when FACTS answer it directly, medium when partly, low otherwise. "
    "VAT boxes: box1 VAT charged on sales, box2 VAT on goods from the EU, box3 total VAT due, box4 VAT reclaimed on "
    "purchases, box5 net VAT (box3 minus box4), box6 sales before VAT, box7 purchases before VAT, box8 and box9 goods "
    "to and from the EU. Box 5 is always positive; vat_position says whether the owner pays or is repaid."
)

_NUMBER = re.compile(r"[-−]?£?\d[\d,]*(?:\.\d+)?%?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
#: Which period the values under each top-level key of the facts pack belong to (anything else: ANY).
_PERIOD_OF = {"this_period": THIS, "previous_period": PREV, "top_suppliers": THIS, "top_customers": THIS, "largest_transactions": THIS}


class AiStalled(Exception):
    """The model stopped sending: nothing for FIRST_CHUNK_S at the start, or for TOKEN_GAP_S mid-reply."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"no reply for {seconds:.0f} s")
        self.seconds = seconds


# --------------------------------------------------------------------------- #
# Numbers: what the facts contain (and from which period), and what an answer quotes
# --------------------------------------------------------------------------- #

def _parse(token: str) -> Decimal | None:
    clean = token.replace("−", "-").replace("£", "").replace(",", "").rstrip("%")
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None


def _is_plain_small(token: str) -> bool:
    """Bare small integers ("Box 5", "Q3", "7 Nov", "3 receipts") are words, not figures."""
    return re.fullmatch(r"\d{1,2}", token) is not None


def _walk(node: Any) -> Iterable[Any]:
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
    else:
        yield node


def _values(node: Any) -> Iterable[Decimal]:
    for v in _walk(node):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            yield Decimal(str(v))
        elif isinstance(v, str):
            yield from (d for t in _NUMBER.findall(v) if (d := _parse(t)) is not None)


class KnownNumbers:
    """Every number in the facts pack's values, compared by value (so 2140, 2140.00 and £2,140.00 match), with the
    period(s) it belongs to.

    `said` is the user's own question: a figure they typed ("fuel in March 2025") is not one the model made up.
    Also accepted: the absolute value (a delta of -620.00 quoted as "down £620") and whole-pound or
    whole-percent roundings ("£2,141" for 2140.56, "18%" for 18.3).
    """

    def __init__(self, facts: dict[str, Any], said: str = "") -> None:
        where: dict[Decimal, set[str]] = defaultdict(set)
        for d in _values(said):
            where[abs(d)].add(ANY)
        for key, node in facts.items():
            for d in _values(node):
                where[abs(d)].add(_PERIOD_OF.get(key, ANY))
        self._where = dict(where)
        self._rounded: dict[Decimal, set[str]] = defaultdict(set)
        for d, tags in where.items():
            for r in (d.quantize(Decimal("1"), rounding=ROUND_HALF_UP), d.to_integral_value(rounding=ROUND_DOWN)):
                self._rounded[r] |= tags
        self.exact = set(self._where)
        self.rounded = set(self._rounded)

    def periods_of(self, token: str) -> set[str]:
        """The periods a quoted figure belongs to; empty when it is in neither (invented)."""
        d = _parse(token)
        if d is None:
            return {ANY}
        d = abs(d)
        tags = set(self._where.get(d, ()))
        if d == d.to_integral_value():
            tags |= self._rounded.get(d, set())
        return tags

    def knows(self, token: str) -> bool:
        return bool(self.periods_of(token))

    def unknown(self, text: str, *, all_tokens: bool) -> list[str]:
        found = _NUMBER.findall(text)
        if not all_tokens:
            found = [t for t in found if not _is_plain_small(t.lstrip("-−"))]
        return [t for t in found if not self.knows(t)]


def _names_period(text: str, p: str, facts: dict[str, Any]) -> bool:
    """Does this sentence say which period it means ("last quarter", "Apr–Jun 2026", "26A2")?"""
    full = facts[period_key(p)]
    return bool((PREV_WORDS if p == PREV else THIS_WORDS).search(text)) or full["label"] in text or full["period_key"] in text


def wrong_period(text: str, known: KnownNumbers, facts: dict[str, Any], r: Route) -> list[tuple[str, str]]:
    """(figure, its period) for each figure that belongs only to the period the question did not ask about,
    in a sentence that does not say it is about that other period."""
    if len(r.periods) != 1:
        return []
    theirs = other(next(iter(r.periods)))
    out = []
    for sentence in _SENTENCE.split(text):
        for tok in _NUMBER.findall(sentence):
            if _is_plain_small(tok.lstrip("-−")):
                continue
            if known.periods_of(tok) == {theirs} and not _names_period(sentence, theirs, facts):
                out.append((tok, theirs))
    return out


# --------------------------------------------------------------------------- #
# What code shows: key numbers, citations and buttons for the route
# --------------------------------------------------------------------------- #

BOX_LABELS = {
    1: "VAT on sales (Box 1)", 2: "VAT on EU goods (Box 2)", 3: "Total VAT due (Box 3)", 4: "VAT reclaimed (Box 4)",
    5: "Net VAT (Box 5)", 6: "Sales before VAT (Box 6)", 7: "Purchases before VAT (Box 7)", 8: "Goods to the EU (Box 8)",
    9: "Goods from the EU (Box 9)",
}
CODE_NAMES = {"S": "standard rate", "R": "reduced rate", "Z": "zero rate", "E": "exempt", "N": "no VAT"}


def _gbp(amount: str) -> str:
    return f"£{Decimal(amount):,.2f}" if "." in amount else f"£{int(amount):,}"


def _signed(amount: str) -> str:
    return ("-" if amount.startswith("-") else "+") + _gbp(amount.lstrip("-"))


def _uk(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b %Y}"


def _fact_key_numbers(facts: dict[str, Any]) -> list[KeyNumber]:
    """The headline VAT figures, when the question names nothing more specific."""
    src = vat_sources(facts)[0]
    this, prev = facts["this_period"], facts["previous_period"]
    return [
        KeyNumber(label=f"Net VAT (Box 5), {this['period_key']}", value=_gbp(this["vat"]["box5"]), source=src),
        KeyNumber(label=f"Net VAT (Box 5), {prev['period_key']}", value=_gbp(prev["vat"]["box5"]), source=src),
        KeyNumber(label="VAT on sales (Box 1)", value=_gbp(this["vat"]["box1"]), source=src),
        KeyNumber(label="VAT reclaimed (Box 4)", value=_gbp(this["vat"]["box4"]), source=src),
    ]


def code_key_numbers(facts: dict[str, Any], r: Route) -> list[KeyNumber]:
    """The figures the question is about, for the period(s) it asks about, each labelled with its period."""
    if not r.matched:
        return _fact_key_numbers(facts)[:2]
    out: list[KeyNumber] = []
    periods = [p for p in (THIS, PREV) if p in r.periods]
    src = {p: (sources_for(facts, {p}) or vat_sources(facts))[0] for p in (THIS, PREV)}

    def tag(p: str) -> str:
        return facts[period_key(p)]["period_key"]

    def add(label: str, value: str, source: str) -> None:
        out.append(KeyNumber(label=_clip(label, LABEL_MAX), value=value, source=source))

    sides = [s for s, on in (("sales", r.sales), ("purchases", r.purchases)) if on] if "totals" in r.sections else []
    boxes = r.boxes if "vat" in r.sections else ()

    if r.compare:  # changes first: they are what a comparison asks for
        d = facts["derived"]
        for b in (boxes or ((5,) if "vat" in r.sections and not sides else ()))[:1]:
            if f"box{b}_delta_vs_prev" in d:
                add(f"Change in {BOX_LABELS[b]} vs {tag(PREV)}", _signed(d[f"box{b}_delta_vs_prev"]), src[THIS])
            if b == 5 and d["box5_change_pct_vs_prev"] is not None:
                add(f"Change in Net VAT vs {tag(PREV)}, %", f"{d['box5_change_pct_vs_prev']} %", src[THIS])
        for s in sides:
            add(f"Change in {s} before VAT vs {tag(PREV)}", _signed(d[f"{s}_net_delta_vs_prev"]), src[THIS])
            if d[f"{s}_net_change_pct_vs_prev"] is not None:
                add(f"Change in {s} before VAT vs {tag(PREV)}, %", f"{d[f'{s}_net_change_pct_vs_prev']} %", src[THIS])

    if THIS in r.periods:  # entries and contacts: the lists are for the current period only
        rows = {t["name"]: ("Spent with", t) for t in facts["top_suppliers"]} | {t["name"]: ("Sales to", t) for t in facts["top_customers"]}
        for name in r.names[:2]:
            if name in rows:
                verb, row = rows[name]
                add(f"{verb} {name}, {tag(THIS)}", _gbp(row["net"]), src[THIS])
                if r.count:
                    add(f"Entries for {name}, {tag(THIS)}", str(row["count"]), src[THIS])
            if (t := next((t for t in facts["largest_transactions"] if t["counterparty"] == name), None)) is not None:
                add(f"{name}, {_uk(t['date'])}, incl. VAT", _gbp(t["gross"]), t["source"])
                if "vat" in r.sections:
                    add(f"VAT on {name}, {_uk(t['date'])}", _gbp(t["vat"]), t["source"])
        if r.largest and facts["largest_transactions"] and not r.names:
            t = facts["largest_transactions"][0]
            add(f"Largest entry: {t['counterparty']}, {_uk(t['date'])}, incl. VAT", _gbp(t["gross"]), t["source"])
        if r.top and not r.names and not r.largest:
            customers = "customers" in r.sections and ("suppliers" not in r.sections or r.sales)
            key, word = ("top_customers", "customer") if customers else ("top_suppliers", "supplier")
            if (customers or "suppliers" in r.sections) and facts[key]:
                t = facts[key][0]
                add(f"Biggest {word}, {tag(THIS)}: {t['name']}", _gbp(t["net"]), src[THIS])

    if not r.names and not (r.top and out):
        for p in periods:
            totals = facts[period_key(p)]["totals"]
            for code in r.codes:
                s = "sales" if r.sales and not r.purchases else "purchases"
                if (row := totals["by_vat_code"].get(f"{s}:{code}")) is not None:
                    add(f"{s.capitalize()} at {CODE_NAMES[code]}, before VAT, {tag(p)}", _gbp(row["net"]), src[p])
            for s in sides if not r.codes else ():
                if r.count:
                    add(f"{s.capitalize()} entries, {tag(p)}", str(totals[s]["count"]), src[p])
                else:
                    add(f"{s.capitalize()} before VAT, {tag(p)}", _gbp(totals[s]["net"]), src[p])
            if r.entries and not sides:
                add(f"Approved entries, {tag(p)}", str(facts[period_key(p)]["entries"]), src[p])

    if "vat" in r.sections and (boxes or not out or (r.compare and not sides)):
        for p in periods:
            vat = facts[period_key(p)]["vat"]
            for b in boxes or ((5,) if r.compare else (5, 1, 4)):
                add(f"{BOX_LABELS[b]}, {tag(p)}", _gbp(vat[f"box{b}"]), src[p])

    for p in periods if r.sections else ():  # at least two figures (none for a question the facts don't cover)
        for b in (5, 1, 4):
            if len(out) >= KEY_NUMBERS[0]:
                break
            add(f"{BOX_LABELS[b]}, {tag(p)}", _gbp(facts[period_key(p)]["vat"][f"box{b}"]), src[p])
    unique: dict[str, KeyNumber] = {}
    for k in out:
        unique.setdefault(k.label, k)
    return list(unique.values())[: KEY_NUMBERS[1]]


def code_citations(facts: dict[str, Any], r: Route, key_numbers: list[KeyNumber]) -> list[str]:
    """The files behind the shown figures: single entries first, then the asked period's ledger folders."""
    if not r.matched:
        return vat_sources(facts)
    listed = set(facts["sources"])
    picked = [k.source for k in key_numbers if k.source in listed and k.source.endswith(".json")]
    return list(dict.fromkeys(picked + sources_for(facts, r.periods))) or vat_sources(facts)


def _pending(facts: dict[str, Any]) -> bool:
    p = facts.get("pending_proposals")
    return bool(p and (p["proposed"] or p["needs_a_look"]))


def code_actions(facts: dict[str, Any], r: Route) -> list[SuggestedAction]:
    actions = []
    if "vat" in r.sections:
        actions.append(SuggestedAction(label="Open the VAT return", kind="open_vat", arg=None))
    if _pending(facts):
        actions.append(SuggestedAction(label="Review waiting entries", kind="open_review", arg=None))
    return actions


def _period(facts: dict[str, Any]) -> AskPeriod:
    return AskPeriod(start=facts["this_period"]["start"], end=facts["this_period"]["end"])


def preview(facts: dict[str, Any], r: Route, model: str) -> dict[str, Any]:
    """What code can show before the model replies (the first event of a streamed answer)."""
    key_numbers = code_key_numbers(facts, r)
    return {
        "key_numbers": [k.model_dump() for k in key_numbers], "citations": code_citations(facts, r, key_numbers),
        "suggested_actions": [a.model_dump() for a in code_actions(facts, r)], "model": model,
        "period": _period(facts).model_dump(mode="json"),
    }


# --------------------------------------------------------------------------- #
# Post-validation
# --------------------------------------------------------------------------- #

def fallback_answer(facts: dict[str, Any], model: str, reason: str, r: Route = EVERYTHING) -> AskAnswer:
    """The facts for the asked period, quoted directly by code. Used when the model fails or a figure doesn't check out."""
    key_numbers = code_key_numbers(facts, r)
    this, prev, d = facts["this_period"], facts["previous_period"], facts["derived"]
    if r.matched and key_numbers:
        lines = [
            f"I couldn't check a written explanation against your books, so here are the figures for {r.label(facts)} "
            "exactly as calculated from your ledger:",
            "",
            *(f"- {k.label}: {k.value}" + (f" ({d['vat_position']})" if k.label == f"Net VAT (Box 5), {this['period_key']}" else "")
              for k in key_numbers),
        ]
    else:
        lines = [
            "I couldn't check a written explanation against your books, so here are the figures exactly as "
            "calculated from your ledger:",
            "",
            f"- Net VAT (Box 5), {_uk(this['start'])} to {_uk(this['end'])}: {_gbp(this['vat']['box5'])} "
            f"({d['vat_position']})",
            f"- Previous period ({_uk(prev['start'])} to {_uk(prev['end'])}): {_gbp(prev['vat']['box5'])}",
            f"- Sales {_gbp(this['totals']['sales']['net'])} net, purchases {_gbp(this['totals']['purchases']['net'])} net, "
            f"from {this['entries']} approved entries",
        ]
        key_numbers = _fact_key_numbers(facts)[:3]
    pending = facts.get("pending_proposals")
    if _pending(facts):
        lines.append(f"- Waiting for you: {pending['proposed']} proposed, {pending['needs_a_look']} to look at")  # type: ignore[index]
    actions = [SuggestedAction(label="Open the VAT return", kind="open_vat", arg=None)]
    if _pending(facts):
        actions.append(SuggestedAction(label="Review waiting entries", kind="open_review", arg=None))
    return AskAnswer(
        answer_md="\n".join(lines), key_numbers=key_numbers, citations=code_citations(facts, r, key_numbers),
        suggested_actions=actions, confidence="low", model=model, period=_period(facts), fallback_reason=reason,
    )


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


def _whole_sentences(text: str) -> str:
    """A reply cut off by the length cap, up to its last full sentence."""
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text.strip())]
    return text.strip()[: ends[-1]] if ends else ""


def ground(out: AskModelOutput, facts: dict[str, Any], model: str, question: str = "", r: Route | None = None) -> AskAnswer:
    """Check the model's answer against the facts (and the question's own figures, and the period it asks about);
    return it with code's key numbers and citations, or the fallback if a figure doesn't check out."""
    r = r or (route(question, facts) if question.strip() else EVERYTHING)
    known = KnownNumbers(facts, question)
    answer_md = _clip(out.answer_md, ASK_ANSWER_MAX)
    if not answer_md:
        return fallback_answer(facts, model, "The model returned an empty answer.", r)
    invented = known.unknown(answer_md, all_tokens=False)
    for kn in out.key_numbers:
        invented += known.unknown(kn.value, all_tokens=True)
    if invented:
        shown = ", ".join(dict.fromkeys(invented[:3]))
        return fallback_answer(facts, model, f"The model quoted figures that are not in your books ({shown}).", r)
    misplaced = wrong_period(answer_md, known, facts, r)
    for kn in out.key_numbers:
        misplaced += [(t, p) for t, p in wrong_period(kn.value, known, facts, r) if not _names_period(kn.label, p, facts)]
    if misplaced:
        tok, p = misplaced[0]
        return fallback_answer(
            facts, model, f"The model quoted {tok}, a figure for {facts[period_key(p)]['label']}, in an answer about {r.label(facts)}.", r,
        )

    sources = set(facts["sources"])
    default_src = vat_sources(facts)[0]
    key_numbers = code_key_numbers(facts, r)
    have = {k.value for k in key_numbers}
    for k in out.key_numbers:  # a model that still sends key numbers (older prompts, other backends): after code's
        if k.value.strip() and k.value.strip() not in have:
            key_numbers.append(KeyNumber(label=_clip(k.label, LABEL_MAX), value=k.value.strip(),
                                         source=k.source if k.source in sources else default_src))
    key_numbers = key_numbers[: KEY_NUMBERS[1]]

    citations = list(dict.fromkeys(code_citations(facts, r, key_numbers) + [c for c in out.citations if c in sources]))

    names = {t["name"].lower() for t in facts.get("top_suppliers", [])}
    names |= {t["counterparty"].lower() for t in facts.get("largest_transactions", [])}
    actions: list[SuggestedAction] = []
    for a in out.suggested_actions:
        if a.kind == "chase_supplier" and (not a.arg or a.arg.strip().lower() not in names):
            continue  # never chase a supplier the books don't know
        if a.kind == "plan_day":
            continue  # only code offers a day plan (app/routes_ask.py)
        actions.append(SuggestedAction(label=_clip(a.label, LABEL_MAX), kind=a.kind, arg=_clip(a.arg, LABEL_MAX) if a.arg else None))

    return AskAnswer(
        answer_md=answer_md, key_numbers=key_numbers, citations=citations,
        suggested_actions=(actions or code_actions(facts, r))[:MAX_ACTIONS],
        confidence=out.confidence, model=model, period=_period(facts),
    )


# --------------------------------------------------------------------------- #
# Model call
# --------------------------------------------------------------------------- #

class AnswerText:
    """Pulls the answer_md string out of a JSON reply while it streams in, unescaping as it goes."""

    _ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "\\": "\\", "/": "/"}

    def __init__(self) -> None:
        self.raw = ""
        self.text = ""
        self.done = False  # the closing quote has been seen
        self._pos: int | None = None

    def feed(self, chunk: str) -> str:
        """Add a chunk of the raw reply; return the new answer text it completes."""
        self.raw += chunk
        if self._pos is None:
            m = re.search(r'"answer_md"\s*:\s*"', self.raw)
            if m is None:
                return ""
            self._pos = m.end()
        raw, i, new = self.raw, self._pos, []
        while i < len(raw) and not self.done:
            c = raw[i]
            if c == '"':
                self.done = True
                i += 1
            elif c != "\\":
                new.append(c)
                i += 1
            elif i + 1 >= len(raw):
                break
            elif raw[i + 1] != "u":
                new.append(self._ESC.get(raw[i + 1], raw[i + 1]))
                i += 2
            else:
                width = 12 if raw[i + 2:i + 4].lower() in ("d8", "d9", "da", "db") else 6  # a surrogate pair
                if i + width > len(raw):
                    break
                try:
                    new.append(json.loads(f'"{raw[i:i + width]}"'))
                except ValueError:
                    pass
                i += width
        self._pos = i
        text = "".join(new)
        self.text += text
        return text


async def _lines(response: httpx.Response) -> AsyncIterator[str]:
    """The response's lines, with FIRST_CHUNK_S to wait for the first and TOKEN_GAP_S between the rest."""
    it = response.aiter_lines().__aiter__()
    wait = FIRST_CHUNK_S
    while True:
        try:
            line = await asyncio.wait_for(it.__anext__(), wait)
        except StopAsyncIteration:
            return
        except TimeoutError:
            raise AiStalled(wait) from None
        wait = TOKEN_GAP_S
        yield line


async def stream_json_model(
    messages: list[dict[str, str]], cfg: AiConfig, schema: dict[str, Any], name: str, max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """The reply's text as it arrives from the user's backend, constrained to `schema`. Raises httpx errors and AiStalled."""
    timeout = httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0)  # reads are timed per chunk by _lines
    async with httpx.AsyncClient(timeout=timeout) as client:
        if cfg.mode == "local":
            options: dict[str, Any] = {"temperature": 0} | ({"num_predict": max_tokens} if max_tokens else {})
            body: dict[str, Any] = {
                "model": cfg.model, "messages": messages, "format": schema, "think": False, "stream": True,
                "options": options, "keep_alive": "24h",
            }
            async with client.stream("POST", f"{cfg.base_url}/api/chat", json=body) as r:
                if r.is_error:
                    await r.aread()
                    r.raise_for_status()
                async for line in _lines(r):
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise httpx.HTTPError(str(chunk["error"]))
                    if text := chunk.get("message", {}).get("content", ""):
                        yield text
                    if chunk.get("done"):
                        return
            return
        body = {
            "model": cfg.model, "messages": messages, "stream": True,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            "reasoning_effort": "low", **({"max_tokens": max_tokens} if max_tokens else {}),
        }
        headers = {"Authorization": f"Bearer {cfg.api_key}"}
        async with client.stream("POST", f"{cfg.base_url}/chat/completions", json=body, headers=headers) as r:
            if r.is_error:
                await r.aread()
                r.raise_for_status()
            async for line in _lines(r):
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    return
                choices = json.loads(data).get("choices") or []
                content = (choices[0].get("delta") or {}).get("content") if choices else None
                if isinstance(content, list):
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                if content:
                    yield content


async def _call_model(
    messages: list[dict[str, str]], cfg: AiConfig, output: type[BaseModel] = AskExplanation, name: str = "ask_answer",
) -> str:
    """Raw JSON text from the configured backend, constrained to `output`'s schema (app/ai/plan.py uses it too).
    Streamed underneath, so it is timed per chunk; Ask's own answer is capped at ANSWER_TOKENS_MAX."""
    cap = _answer_cap(cfg) if output is AskExplanation else None
    return "".join([t async for t in stream_json_model(messages, cfg, strict_json_schema(output), name, cap)])


def _answer_cap(cfg: AiConfig) -> int:
    return ANSWER_TOKENS_MAX if cfg.mode == "local" else KEY_TOKENS_MAX


async def _stream_model(messages: list[dict[str, str]], cfg: AiConfig) -> AsyncIterator[str]:
    async for text in stream_json_model(messages, cfg, strict_json_schema(AskExplanation), "ask_answer", _answer_cap(cfg)):
        yield text


async def call_json_model(messages: list[dict[str, str]], cfg: AiConfig, schema: dict[str, Any], name: str) -> str:
    """Raw JSON text from the user's backend, constrained to `schema` (also used by app/ai/remind.py)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
        if cfg.mode == "local":
            body: dict[str, Any] = {
                "model": cfg.model, "messages": messages, "format": schema, "think": False, "stream": False,
                "options": {"temperature": 0}, "keep_alive": "24h",
            }
            r = await client.post(f"{cfg.base_url}/api/chat", json=body)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "")
        body = {
            "model": cfg.model, "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            "reasoning_effort": "low",
        }
        r = await client.post(f"{cfg.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {cfg.api_key}"})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content


def _messages(question: str, facts: dict[str, Any], history: list[AskTurn]) -> list[dict[str, str]]:
    facts_json = json.dumps(facts, separators=(",", ":"), ensure_ascii=False)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *({"role": t.role, "content": t.text[:1000]} for t in history),
        {"role": "user", "content": f"FACTS:\n{facts_json}\n\nQuestion: {question.strip()}"},
    ]


def _trouble(exc: Exception, cfg: AiConfig) -> str:
    if isinstance(exc, AiStalled):
        return f"Your AI ({cfg.mode}) stopped replying for {exc.seconds:.0f} s."
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Your AI ({cfg.mode}) returned HTTP {exc.response.status_code}."
    return f"Your AI ({cfg.mode}) could not be reached at {cfg.base_url}."


def _checked(text: str, facts: dict[str, Any], cfg: AiConfig, question: str, r: Route) -> AskAnswer:
    """Parse the reply (a reply cut off by the length cap keeps its whole sentences) and ground it."""
    try:
        data = parse_model_json(text)
        if not isinstance(data, dict):
            raise ExtractionError("not an object")
        out = AskModelOutput.model_validate({"key_numbers": [], "citations": [], "suggested_actions": [], **data})
    except (ExtractionError, ValidationError):
        partial = AnswerText()
        partial.feed(text)
        if partial.done or not (cut := _whole_sentences(partial.text)):
            return fallback_answer(facts, cfg.model, "The model's reply was not in the expected format.", r)
        out = AskModelOutput(answer_md=cut, key_numbers=[], citations=[], suggested_actions=[], confidence="medium")
    return ground(out, facts, cfg.model, question, r)


async def answer(question: str, facts: dict[str, Any], history: list[AskTurn], cfg: AiConfig) -> AskAnswer:
    """Ask the model, then check its answer against the facts. Never raises for model trouble."""
    r = route(question, facts)
    try:
        text = await _call_model(_messages(question, pack(facts, r), history), cfg)
    except (httpx.HTTPError, AiStalled) as exc:
        return fallback_answer(facts, cfg.model, _trouble(exc, cfg), r)
    return _checked(text, facts, cfg, question, r)


async def answer_stream(question: str, facts: dict[str, Any], history: list[AskTurn], cfg: AiConfig) -> AsyncIterator[tuple[str, Any]]:
    """("start", code's key numbers and citations) at once, then ("token", text) as the explanation arrives, then
    ("answer", the checked AskAnswer), which may replace the streamed words. Never raises for model trouble."""
    r = route(question, facts)
    yield "start", preview(facts, r, cfg.model)
    reader = AnswerText()
    try:
        async for chunk in _stream_model(_messages(question, pack(facts, r), history), cfg):
            if text := reader.feed(chunk):
                yield "token", text
    except (httpx.HTTPError, AiStalled) as exc:
        yield "answer", fallback_answer(facts, cfg.model, _trouble(exc, cfg), r)
        return
    yield "answer", _checked(reader.raw, facts, cfg, question, r)
