"""AI search in Ask: "was there a PayPal payment last month, around £100 for stationery? how much exactly?" and
"did that client pay all the arrears? check PayPal".

The house rule holds: the AI proposes, code decides.

* **Intent, by code** (`intent`): a question that asks to find a payment or whether a customer paid ("did … pay",
  "how much exactly", "was there a payment", "check PayPal", "arrears"). PayPal's fee, balance, payout, dispute,
  Sync PayPal and bills questions (app/paypal_assistant.py), instructions, and "who owes me" stay where they were.
* **Words to a query, by the user's AI** (`read_query`): one strict-JSON call (the schema below, as
  app/ai/grid_filter.py does it). Code then checks every field: the kind and direction from a short list; an amount
  only when it is one the question itself says; the tolerance clamped to 0-50% (20% by default); a counterparty only
  when its words are in the question or the conversation; dates never from the model (it may only pick a named range
  such as last_month, which code turns into dates from today in Europe/London); keywords cleaned and capped. When no
  AI is set up, or its reply does not parse, code reads the question itself (`code_query`).
* **The search, by code** (`search`): approved ledger entries that moved money (bank, card, PayPal clearing 1240),
  the payments Sync PayPal is holding (including those waiting for the user's approval), and, when PayPal is
  connected (or the demo's sample history), PayPal's own Transaction Search for the window, 31 days per call. Each
  candidate is ranked by how close its amount is, then name and keyword matches, then date.
* **The answer, by code**: exact figures in pence with date, payee or payer, where it was found (the books, PayPal or
  both) and whether it is in the books yet, its VAT and account when posted; two or three close matches are listed
  with the closest named; nothing found says what was searched. "Did they pay" resolves the customer (from the
  conversation, a name, or the one customer whose overdue balance is close to the amount said; otherwise it asks
  which, listing up to three), and compares what is outstanding by the books with the payments found since.
  Nothing is posted: a PayPal payment not yet in the books is approved by the user in Sync PayPal.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.books import Books
from app.schemas import AskAnswer, AskPeriod, AskTurn, KeyNumber, strict_json_schema

log = logging.getLogger("accnomos.ai_search")
TZ = ZoneInfo("Europe/London")
_I = re.IGNORECASE

Kind = Literal["payment_search", "customer_paid_check"]
Direction = Literal["in", "out", "any"]
Sources = Literal["books", "paypal", "both"]
RangeName = Literal[
    "none",
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "last_30_days",
    "last_90_days",
    "this_year",
]
DEFAULT_TOLERANCE = 20
MAX_TOLERANCE = 50
DEFAULT_DAYS = 90  # the window when the question names none
MAX_SPAN_DAYS = 366
MAX_KEYWORDS = 8
MAX_LISTED = 3
PAYPAL_SYNC = "/invoices#paypal-sync"
LATE_NOTE = "PayPal can take up to three hours to list a new transaction."

# --------------------------------------------------------------------------- #
# Intent (code)
# --------------------------------------------------------------------------- #

_PAY = re.compile(r"\bpa(?:y|id|ys|ying|yments?)\b|\btransactions?\b|\barrears\b|\bsettled?\b|\bcleared\b", _I)
_STRONG = re.compile(
    r"\bcheck (?:in |on |with )?(?:my |our |the )?pay\s?pal\b|\bhow much exactly\b|\bexact(?:ly)? how much\b|"
    r"\bexact (?:amount|figure|sum)\b|\bhow much (?:exactly )?was (?:it|that|the payment)\b|"
    r"\bw(?:as|ere) there (?:a|any) (?:pay\s?pal )?(?:payments?|transactions?)\b|"
    r"\bthere was a (?:pay\s?pal )?payment\b|"
    r"\barrears\b|\bdid (?:\S+\s){0,5}?pay\b|\bha(?:s|ve) (?:\S+\s){0,5}?paid\b|"
    r"\bfind (?:the|a|that|my) (?:pay\s?pal )?(?:payment|transaction)\b|"
    r"\bpaid (?:it |them |that )?(?:all|in full|off)\b|"
    r"\bwhen did (?:\S+\s){0,4}?pay\b|\bwhich payment\b|\blook (?:up|for) (?:the|a|that) payment\b",
    _I,
)
_CUSTOMER = re.compile(
    r"\bclient\b|\bcustomer\b|\barrears\b|\boverdue\b|\bow(?:e|es|ed|ing)\b|\binvoices?\b|\bpaid (?:me|us)\b|"
    r"\bpay (?:me|us)\b|\b(?:they|he|she|them)\b.*\bpa(?:y|id)\b|"
    r"\b(?:has|have|did)\s+(?!i\b|we\b|you\b)\S+(?:\s\S+){0,4}?\s+pa(?:y|id)\b(?!\s+(?:for|to|out)\b)",
    _I,
)
_WE_PAID = re.compile(r"\bdid (?:i|we)\b|\b(?:i|we) paid\b|\bha(?:ve) (?:i|we) paid\b|\bpaid (?:to|for)\b", _I)
_PAYPAL = re.compile(r"\bpay\s?pal\b", _I)


def intent(question: str) -> Kind | None:
    """A search question, and which kind; None for anything else (left to the routes it always went to)."""
    from app import actions
    from app import paypal_assistant as pa

    if not _PAY.search(question) or not _STRONG.search(question):
        return None
    if actions.looks_like_action(question) or pa.question_kind(question) is not None:
        return None
    if _CUSTOMER.search(question) and not _WE_PAID.search(question):
        return "customer_paid_check"
    return "payment_search"


# --------------------------------------------------------------------------- #
# The query: the model's reading, checked by code; or code's own reading
# --------------------------------------------------------------------------- #


class ModelQuery(BaseModel):
    """What the model returns (strict JSON). Every field is checked by code before use."""

    kind: Kind
    counterparty_hint: str = Field(max_length=120)  # "" when the question names no one
    amount_pence: int | None
    amount_tolerance_pct: int | None
    direction: Direction
    date_range: RangeName
    month: int | None  # 1-12 when the question names a month ("in October"); code works out the year
    keywords: list[str] = Field(max_length=MAX_KEYWORDS * 2)
    sources: Sources


@dataclass
class Query:
    kind: Kind
    counterparty: str | None
    amount_pence: int | None
    tolerance_pct: int
    direction: Direction
    start: date
    end: date
    span: str  # "October 2026", "the last 90 days"
    keywords: list[str]
    sources: Sources
    read_by: Literal["model", "code"]
    fallback_reason: str | None = None


SEARCH_PROMPT = (
    "You turn a UK small business owner's question about a payment into a search query for their own books and their "
    "PayPal account. You never answer the question and never invent figures: you only say what to look for.\n"
    "Fields:\n"
    "- kind: customer_paid_check when they ask whether a customer or client paid (arrears, an overdue invoice); "
    "otherwise payment_search.\n"
    "- counterparty_hint: the business or person named in QUESTION or HISTORY that the payment is from or to, "
    'exactly as written there; "" if none ("that client" alone names no one unless HISTORY names them).\n'
    "- amount_pence: the amount the question says, in pence (around £100 is 10000); null if none.\n"
    "- amount_tolerance_pct: how far off the amount may be, 0-50; 20 for around/about/probably, 5 for exactly; "
    "null for the default.\n"
    "- direction: in for money received, out for money paid, any if unclear.\n"
    "- date_range: one of none, today, yesterday, this_week, last_week, this_month, last_month, this_quarter, "
    "last_quarter, last_30_days, last_90_days, this_year. Never write dates.\n"
    '- month: 1-12 only when a month is named ("in October"), else null.\n'
    "- keywords: up to 8 short words for what was bought or sold, with close alternatives a ledger or a shop would "
    "use (stationery: stationery, office supplies, paper, pens, printer); [] if none. No names, no amounts.\n"
    "- sources: paypal when the question says PayPal, books when it says bank or books, else both.\n"
    "Return JSON with exactly these fields."
)

_AMOUNT = re.compile(
    r"£\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?(k\b)?|\b(\d+(?:\.\d{1,2})?)\s?(?:pounds|quid)\b", _I
)
_HEDGE = re.compile(r"\b(?:around|about|roughly|approx(?:imately)?|probably|maybe|ish|or so|something like)\b|~", _I)
_EXACT = re.compile(r"\bexactly £|\bprecisely £", _I)
_SPAN_SAID = re.compile(
    r"\b(?:yesterday|today|this week|last week|previous week|past week|this month|last month|previous month|"
    r"past month|this quarter|last quarter|previous quarter|tax year|this year|last year)\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b|\b(?:in|for) may\b",
    _I,
)
_LAST_N_DAYS = re.compile(r"\b(?:last|past) (\d{1,3}) days\b", _I)
_IN = re.compile(r"\b(?:receiv\w*|came in|paid (?:me|us)|from (?:a |the |my |our )?(?:client|customer))\b", _I)
_OUT = re.compile(
    r"\b(?:bought|buy|purchase\w*|spent|paid (?:for|to)|did (?:i|we) pay|for (?:the |some )?\w+ supplies)\b", _I
)
_FILLER = frozenset(
    [
        "a",
        "an",
        "the",
        "was",
        "were",
        "is",
        "it",
        "that",
        "this",
        "there",
        "via",
        "through",
        "on",
        "in",
        "of",
        "for",
        "from",
        "to",
        "by",
        "with",
        "my",
        "our",
        "me",
        "us",
        "i",
        "we",
        "they",
        "them",
        "did",
        "does",
        "do",
        "has",
        "have",
        "had",
        "pay",
        "paid",
        "payment",
        "payments",
        "paypal",
        "how",
        "much",
        "exactly",
        "exact",
        "around",
        "about",
        "roughly",
        "probably",
        "last",
        "month",
        "week",
        "year",
        "quarter",
        "check",
        "please",
        "find",
        "what",
        "which",
        "when",
        "who",
        "client",
        "customer",
        "arrears",
        "all",
        "overdue",
        "any",
        "money",
        "pounds",
        "quid",
        "it's",
        "its",
        "be",
        "been",
        "some",
    ]
)
SYNONYMS: dict[str, tuple[str, ...]] = {
    "stationery": ("stationery", "office supplies", "office", "paper", "pens", "printer", "files"),
    "office": ("office supplies", "stationery", "paper"),
    "software": ("software", "subscription", "plan", "licence"),
    "fuel": ("fuel", "petrol", "diesel"),
    "timber": ("timber", "wood", "materials"),
    "tools": ("tools", "small equipment", "hardware"),
    "postage": ("postage", "royal mail", "courier", "delivery"),
}
_NAMED_SPAN: dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "this_week": "this week",
    "last_week": "last week",
    "this_month": "this month",
    "last_month": "last month",
    "this_quarter": "this quarter",
    "last_quarter": "last quarter",
    "this_year": "this year",
}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]  # fmt: skip


def amounts_said(text: str) -> list[int]:
    """Every amount the words say, in pence ("around £100" 10000, "£1.5k" 150000, "250 pounds" 25000)."""
    out = []
    for m in _AMOUNT.finditer(text):
        if m.group(4):
            pounds, pence = m.group(4).split(".") if "." in m.group(4) else (m.group(4), "0")
            v = int(pounds) * 100 + int(pence.ljust(2, "0")[:2])
        else:
            v = int(m.group(1).replace(",", "")) * 100 + int((m.group(2) or "0").ljust(2, "0"))
            if m.group(3):
                v *= 1000
        if 0 < v <= 10_000_000_000:
            out.append(v)
    return out


def span_for(question: str, today: date, named: str | None = None, month: int | None = None) -> tuple[date, date, str]:
    """[start, end] and its words. The question's own words first (code), then the model's named range or month, then
    the last 90 days. Months and weeks are whole calendar ones in Europe/London; a span in progress ends today."""
    from app.ask_pnl import span_words
    from app.ask_router import pnl_span

    if m := _LAST_N_DAYS.search(question):
        n = max(1, min(int(m.group(1)), MAX_SPAN_DAYS))
        return today - timedelta(days=n - 1), today, f"the last {n} days"
    if _SPAN_SAID.search(question):
        s = pnl_span(question, today)
        return s.start, s.end, span_words(s)
    if named in ("last_30_days", "last_90_days"):
        n = 30 if named == "last_30_days" else 90
        return today - timedelta(days=n - 1), today, f"the last {n} days"
    if named in _NAMED_SPAN:
        s = pnl_span(_NAMED_SPAN[named], today)
        return s.start, s.end, span_words(s)
    if month is not None and 1 <= month <= 12:
        s = pnl_span(f"in {_MONTHS[month - 1]}", today)
        return s.start, s.end, span_words(s)
    return today - timedelta(days=DEFAULT_DAYS - 1), today, f"the last {DEFAULT_DAYS} days"


def _clean_keywords(words: list[str]) -> list[str]:
    out: list[str] = []
    for w in words:
        w = re.sub(r"[^a-z0-9 &'-]+", " ", str(w).lower()).strip()
        w = re.sub(r"\s+", " ", w)[:30]
        if len(w) < 3 or w in _FILLER or re.fullmatch(r"[\d .,]+", w):
            continue
        for x in (w, *SYNONYMS.get(w, ())):
            if x not in out:
                out.append(x)
    return out[:MAX_KEYWORDS]


def _words_of(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z'&-]+", text.lower()) if w not in _FILLER and len(w) >= 3]


_FOR_THING = re.compile(
    r"\bfor (?:the |some |our |my )?([a-z][a-z &'-]{2,40}?)"
    r"(?:\s*(?:[,.?!—–-]|$| how| and| last| in | on ))"
)


def code_keywords(question: str) -> list[str]:
    """Words after "for" ("for stationery"), else none: code's own reading never guesses what was bought."""
    m = _FOR_THING.search(question.lower())
    return _clean_keywords(_words_of(m.group(1))) if m else []


def code_query(question: str, kind: Kind, today: date, reason: str | None = None) -> Query:
    """Code's own reading: amounts, a hedge for the tolerance, relative months and dates, PayPal, "for <thing>"."""
    amounts = amounts_said(question)
    start, end, span = span_for(question, today)
    direction: Direction = "in" if kind == "customer_paid_check" else "any"
    if kind == "payment_search":
        if _OUT.search(question) or (code_keywords(question) and not _IN.search(question)):
            direction = "out"
        elif _IN.search(question):
            direction = "in"
    return Query(
        kind=kind,
        counterparty=None,
        amount_pence=amounts[0] if amounts else None,
        tolerance_pct=5 if _EXACT.search(question) and not _HEDGE.search(question) else DEFAULT_TOLERANCE,
        direction=direction,
        start=start,
        end=end,
        span=span,
        keywords=code_keywords(question),
        sources="paypal" if _PAYPAL.search(question) else "both",
        read_by="code",
        fallback_reason=reason,
    )


def _said(hint: str, text: str) -> bool:
    """The hint's distinctive words all appear in the text (case and punctuation ignored)."""
    words = [w for w in re.findall(r"[a-z0-9]+", hint.lower()) if w not in {"ltd", "limited", "the", "and", "co"}]
    hay = set(re.findall(r"[a-z0-9]+", text.lower()))
    return bool(words) and all(w in hay for w in words)


def check_query(out: ModelQuery, question: str, history_text: str, kind: Kind, today: date) -> Query:
    """The model's reading, kept only where code can stand behind it."""
    said = amounts_said(question)
    amount = out.amount_pence if out.amount_pence in said else (said[0] if said else None)
    tol = out.amount_tolerance_pct if out.amount_tolerance_pct is not None else DEFAULT_TOLERANCE
    tol = max(0, min(int(tol), MAX_TOLERANCE))
    hint = out.counterparty_hint.strip()[:120]
    counterparty = hint if hint and _said(hint, f"{question}\n{history_text}") else None
    start, end, span = span_for(question, today, out.date_range, out.month)
    sources: Sources = out.sources
    if _PAYPAL.search(question) and sources == "books":
        sources = "both"
    return Query(
        kind=out.kind if out.kind == kind or kind == "payment_search" else kind,
        counterparty=counterparty,
        amount_pence=amount,
        tolerance_pct=tol,
        direction=out.direction if kind == "payment_search" else "in",
        start=start,
        end=end,
        span=span,
        keywords=_clean_keywords([*out.keywords, *code_keywords(question)]),
        sources=sources,
        read_by="model",
    )


async def read_query(question: str, history: list[AskTurn], kind: Kind, cfg: AiConfig | None, today: date) -> Query:
    """The model's reading, checked; code's own when there is no AI or its reply does not parse. Never raises."""
    from app.ai.ask import _trouble, call_json_model  # noqa: PLC2701

    history_text = "\n".join(t.text for t in history[-6:])
    if cfg is None:
        return code_query(question, kind, today, "No AI is set up, so code read your question.")
    user = (
        f"TODAY: {today.isoformat()}\nHISTORY: {json.dumps([t.text[:400] for t in history[-6:]], ensure_ascii=False)}\n"
        f"QUESTION: {question}"
    )
    messages = [{"role": "system", "content": SEARCH_PROMPT}, {"role": "user", "content": user}]
    try:
        raw = await call_json_model(messages, cfg, strict_json_schema(ModelQuery), "ai_search")
        out = ModelQuery.model_validate(parse_model_json(raw))
    except (ExtractionError, ValidationError):
        return code_query(question, kind, today, "The AI's reply was not in the expected format, so code read it.")
    except Exception as exc:  # noqa: BLE001  any model trouble: code's reading still searches
        return code_query(question, kind, today, f"{_trouble(exc, cfg)} Code read your question instead.")
    return check_query(out, question, history_text, kind, today)


# --------------------------------------------------------------------------- #
# Searching (code)
# --------------------------------------------------------------------------- #

Where = Literal["books", "sync_waiting", "sync_posted", "sync_rejected", "sync_shown", "paypal", "paypal_pending"]


@dataclass
class Hit:
    date: date
    amount_pence: int  # signed: money in is positive
    name: str
    where: Where
    detail: str = ""  # item names, memo
    account: str | None = None
    vat_pence: int | None = None
    citation: str | None = None
    via_paypal: bool = False
    tid: str | None = None
    invoice: str | None = None
    event_ids: list[str] = field(default_factory=list)
    also_paypal: bool = False  # a books entry PayPal lists too
    score: float = 0.0
    off_pence: int = 0

    @property
    def in_books(self) -> bool:
        return self.where in ("books", "sync_posted")


def _money_account(acct: str) -> bool:
    return acct[:2] == "12"  # 1200 Bank, 1210 Card, 1240 PayPal clearing, 1250 Stripe…: money held or moving


async def books_hits(books: Books, start: date, end: date) -> list[Hit]:
    """Approved entries that moved money in [start, end]: in = debits to a money account, out = credits from one.
    Undone entries (and their undo) are left out."""
    from app.journal import PAYPAL_CLEARING, VAT_CONTROL

    entries = await books.list_event_entries(start, end)
    undone = {e.reverses for _p, e in entries if e.reverses}
    out: list[Hit] = []
    for path, e in entries:
        if e.reverses or e.id in undone or e.kind == "adjustment":
            continue
        money_in = sum(ln.debit for ln in e.lines if _money_account(ln.account))
        money_out = sum(ln.credit for ln in e.lines if _money_account(ln.account))
        net = money_in - money_out
        if not net:
            continue
        others = [ln for ln in e.lines if not _money_account(ln.account) and ln.account != VAT_CONTROL]
        main = max(others, key=lambda ln: ln.debit + ln.credit, default=None)
        memo = " ".join(dict.fromkeys(ln.memo for ln in e.lines if ln.memo))
        out.append(
            Hit(
                date=e.date,
                amount_pence=net,
                name=(e.counterparty or memo or (main.account if main else "")).strip()[:120] or "Unnamed entry",
                where="books",
                detail=memo[:200],
                account=main.account if main else None,
                vat_pence=e.vat if e.vat else None,
                citation=path,
                via_paypal=any(ln.account == PAYPAL_CLEARING for ln in e.lines),
                event_ids=[e.id],
            )
        )
    return out


async def sync_hits(books: Books, start: date, end: date) -> list[Hit]:
    """What Sync PayPal holds for [start, end]: waiting for approval, posted, rejected, or shown only."""
    from app import paypal_sync as ps

    state = await ps.load_state(books)
    known = await ps.already_in_books(books) if state.items else set()
    out = []
    for it in state.items.values():
        if not start <= it.date <= end or it.currency != "GBP" or not it.gross_pence:
            continue
        where: Where = {"proposed": "sync_waiting", "posted": "sync_posted", "rejected": "sync_rejected"}.get(
            it.status, "sync_shown"
        )  # type: ignore[assignment]
        if it.status in ("already",) or it.transaction_id in known:
            where = "sync_posted"
        out.append(
            Hit(
                date=it.date,
                amount_pence=it.gross_pence,
                name=it.name,
                where=where,
                detail="; ".join(it.items),
                account=it.account,
                vat_pence=None,
                citation=f"paypal:{it.transaction_id}",
                via_paypal=True,
                tid=it.transaction_id,
                invoice=it.invoice,
                event_ids=list(it.event_ids),
            )
        )
    return out


async def paypal_hits(books: Books, start: date, end: date, demo: bool) -> tuple[list[Hit], str | None, int]:
    """PayPal's Transaction Search for [start, end] (31 days per call): (rows as hits, why not searched, calls).
    The demo with no PayPal connected searches its sample history instead."""
    from app import paypal_sync as ps
    from app.books import now
    from app.payment_providers import ProviderError

    try:
        source, merchant, why = await ps.source_for(books, demo)
    except Exception as exc:  # noqa: BLE001  a connection file that will not read: books only
        return [], f"PayPal could not be checked ({type(exc).__name__})", 0
    if source is None:
        return [], why or "PayPal is not connected", 0
    if source == "paypal":
        fetch = ps.paypal_fetch(merchant)
    else:
        hint, more = await ps.sample_hints(books)
        fetch = ps.sample_fetch(_today(), hint, more)
    a = datetime.combine(start, time.min, TZ).astimezone(UTC)
    b = min(datetime.combine(end + timedelta(days=1), time.min, TZ).astimezone(UTC), now())
    rows: list[dict[str, Any]] = []
    calls = 0
    try:
        for x, y in ps.windows(a, b):
            got, n = await fetch(x, y)
            rows += got
            calls += n
    except ProviderError as exc:
        return [], f"PayPal did not answer ({exc.message})", calls
    except Exception as exc:  # noqa: BLE001
        return [], f"PayPal could not be checked ({type(exc).__name__})", calls
    out = []
    for p in (ps.parse(r) for r in rows):
        if p is None or p["gross"] is None or p["when"] is None or p["status"] not in ("S", "V", "P"):
            continue
        if ps.kind_of(p["code"], p["gross"]) in ("withdrawal", "deposit", "fee"):
            continue
        out.append(
            Hit(
                date=p["when"].astimezone(TZ).date(),
                amount_pence=p["gross"],
                name=p["name"],
                where="paypal_pending" if p["status"] == "P" else "paypal",
                detail="; ".join(p["items"]) or re.sub(r"\s+", " ", p["hay"].replace(p["invoice_id"], "", 1)).strip(),
                citation=f"paypal:{p['tid']}",
                via_paypal=True,
                tid=p["tid"],
                invoice=p["invoice_id"] or None,
            )
        )
    return out, ("the sample PayPal history (demo)" if source == "sample" else None), calls


def _today() -> date:
    from app.books import today

    return today(TZ)


def merge(book: list[Hit], synced: list[Hit], live: list[Hit]) -> list[Hit]:
    """One hit per real payment: a Sync PayPal item posted to the books is that books entry (marked as PayPal too);
    a live PayPal row already in Sync PayPal is that item."""
    by_event = {eid: h for h in book for eid in h.event_ids}
    out = list(book)
    tids: set[str] = set()
    for s in synced:
        tids.add(s.tid or "")
        linked = [by_event[e] for e in s.event_ids if e in by_event]
        if linked:
            linked[0].also_paypal = True
            linked[0].tid = s.tid
            continue
        out.append(s)
    for h in live:
        if h.tid in tids:
            continue
        out.append(h)
    return out


def _norm_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in {"ltd", "limited", "the", "and", "co", "plc"}}


def name_match(hint: str | None, name: str) -> bool:
    if not hint:
        return False
    a, b = _norm_words(hint), _norm_words(name)
    if not a or not b:
        return False
    return a <= b or b <= a or len(a & b) >= max(1, min(len(a), len(b)) - 0)


def keyword_hits(keywords: list[str], h: Hit) -> int:
    hay = f"{h.name} {h.detail} {h.account or ''}".lower()
    return sum(1 for k in keywords if k in hay)


def rank(hits: list[Hit], q: Query) -> list[Hit]:
    """Candidates that fit the query, best first. An amount, when said, must be within the tolerance; a name, when
    said and no amount was, must match."""
    out = []
    for h in hits:
        if q.direction == "in" and h.amount_pence <= 0 or q.direction == "out" and h.amount_pence >= 0:
            continue
        if q.sources == "paypal" and not h.via_paypal:
            continue
        if q.sources == "books" and not h.in_books:
            continue
        size = abs(h.amount_pence)
        named = name_match(q.counterparty, h.name)
        words = keyword_hits(q.keywords, h)
        score = 0.0
        if q.amount_pence:
            h.off_pence = size - q.amount_pence
            room = q.amount_pence * q.tolerance_pct / 100
            if abs(h.off_pence) > room:
                continue
            score += 3.0 * (1 - (abs(h.off_pence) / room if room else 0))
        elif q.counterparty and not named or not q.counterparty and q.keywords and not words:
            continue
        score += 2.0 * named + 1.0 * min(words, 2)
        score += 0.3 * (1 - min((q.end - h.date).days, 366) / 366)
        h.score = score
        out.append(h)
    return sorted(out, key=lambda h: (-h.score, abs(h.off_pence), -h.date.toordinal()))


# --------------------------------------------------------------------------- #
# Words (code)
# --------------------------------------------------------------------------- #


def gbp(p: int) -> str:
    return f"£{abs(p) / 100:,.2f}"


def uk(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _md(text: str) -> str:
    return re.sub(r"[*_`\[\]<>#|]", "", text).strip()


def status_words(h: Hit) -> str:
    if h.where == "books":
        return "in your books" + (" (PayPal lists it too)" if h.also_paypal else "")
    if h.where == "sync_posted":
        return "in your books (approved from Sync PayPal)"
    if h.where == "sync_waiting":
        return f"not in your books yet: it is in [Sync PayPal]({PAYPAL_SYNC}), waiting for your approval"
    if h.where == "sync_rejected":
        return "not in your books: you rejected it in Sync PayPal"
    if h.where == "sync_shown":
        return "shown in Sync PayPal but not posted (PayPal's own movement)"
    if h.where == "paypal_pending":
        return "still pending at PayPal, so not in your books"
    return f"not in your books yet: [Sync PayPal]({PAYPAL_SYNC}) will bring it in for your approval"


def describe(h: Hit) -> str:
    """One hit in a sentence: amount, date, to/from whom, how, what, where it stands, VAT and account."""
    to_from = "from" if h.amount_pence > 0 else "to"
    how = " through PayPal" if h.via_paypal else ""
    what = f" ({_md(h.detail)[:120]})" if h.detail and h.detail.lower() != h.name.lower() else ""
    out = f"**{gbp(h.amount_pence)}** on {uk(h.date)} {to_from} {_md(h.name)}{how}{what}, {status_words(h)}"
    posted = []
    if h.in_books and h.account:
        posted.append(f"posted to {_md(h.account)}")
    if h.in_books and h.vat_pence:
        posted.append(f"VAT {gbp(h.vat_pence)}")
    elif h.in_books and h.vat_pence is None and h.where == "books":
        posted.append("no VAT")
    return out + (f"; {', '.join(posted)}" if posted else "") + "."


def searched_words(q: Query, paypal_note: str | None, searched_paypal: bool) -> str:
    where = ["your books"]
    if q.sources != "books":
        where.append("Sync PayPal")
        if searched_paypal:
            where.append(paypal_note or "PayPal's transaction history")
    amount = ""
    if q.amount_pence:
        lo = q.amount_pence * (100 - q.tolerance_pct) // 100
        hi = -(-q.amount_pence * (100 + q.tolerance_pct) // 100)
        amount = f", {gbp(lo)} to {gbp(hi)} (within {q.tolerance_pct}% of {gbp(q.amount_pence)})"
    who = f", {_md(q.counterparty)}" if q.counterparty else ""
    words = f", words: {', '.join(q.keywords[:5])}" if q.keywords else ""
    way = {"in": "money in", "out": "money out", "any": "money in or out"}[q.direction]
    listed = where[0] if len(where) == 1 else f"{', '.join(where[:-1])} and {where[-1]}"
    return f"Searched {listed} for {way}, {uk(q.start)} to {uk(q.end)}{amount}{who}{words}."


def _cites(hits: list[Hit]) -> list[str]:
    return list(dict.fromkeys(h.citation for h in hits if h.citation))


# --------------------------------------------------------------------------- #
# The two answers
# --------------------------------------------------------------------------- #


@dataclass
class Found:
    q: Query
    hits: list[Hit]
    paypal_note: str | None
    paypal_why_not: str | None
    searched_paypal: bool


async def search(books: Books, q: Query, demo: bool) -> Found:
    book = await books_hits(books, q.start, q.end)
    synced: list[Hit] = []
    live: list[Hit] = []
    note = why_not = None
    searched = False
    if q.sources != "books":
        try:
            synced = await sync_hits(books, q.start, q.end)
        except Exception as exc:  # noqa: BLE001  a sync file that will not read: the rest still searches
            log.info("sync state unreadable (%s)", type(exc).__name__)
        live, note, calls = await paypal_hits(books, q.start, q.end, demo)
        searched = calls > 0
        if not searched:
            why_not, note = note, None
    return Found(q, rank(merge(book, synced, live), q), note, why_not, searched)


def _base(period: AskPeriod, q: Query, cfg: AiConfig | None) -> dict[str, Any]:
    return {
        "suggested_actions": [],
        "confidence": "high",
        "model": "code",
        "period": period,
        "fallback_reason": q.fallback_reason,
    }


def payment_answer(f: Found, period: AskPeriod, cfg: AiConfig | None) -> AskAnswer:
    q, hits = f.q, f.hits
    searched = searched_words(q, f.paypal_note, f.searched_paypal)
    caveat = []
    if f.paypal_why_not and q.sources != "books":
        caveat.append(f"PayPal itself was not searched: {f.paypal_why_not.rstrip('.')}.")
    if f.searched_paypal and q.end >= _today() - timedelta(days=1):
        caveat.append(LATE_NOTE)
    tail = "\n\n" + " ".join([searched, *caveat])
    keys: list[KeyNumber] = []
    if not hits:
        text = "I found no payment that fits." + tail + " Try a wider date range or amount, or a name."
        return AskAnswer(answer_md=text, key_numbers=[], citations=[], **_base(period, q, cfg))
    top = hits[0]
    src = top.citation or "Ledger"
    if len(hits) == 1:
        text = f"It was {describe(top)}"
        keys = [KeyNumber(label=f"{_md(top.name)[:60]}, {uk(top.date)}", value=gbp(top.amount_pence), source=src)]
    else:
        shown = hits[:MAX_LISTED]
        more = len(hits) - len(shown)
        lines = "\n".join(f"- {describe(h)}" for h in shown)
        closest = (
            f"The closest is the first: {gbp(top.amount_pence)} to {_md(top.name)}."
            if top.score > hits[1].score + 0.05
            else "They fit equally well: check the names and dates."
        )
        text = f"{len(hits)} payments fit{f'; the {len(shown)} best' if more else ''}:\n\n{lines}\n\n{closest}"
        keys = [
            KeyNumber(
                label=f"{_md(h.name)[:60]}, {uk(h.date)}", value=gbp(h.amount_pence), source=h.citation or "Ledger"
            )
            for h in shown
        ]
    return AskAnswer(
        answer_md=text + tail, key_numbers=keys, citations=_cites(hits[:MAX_LISTED]), **_base(period, q, cfg)
    )


# ---- "Did that client pay?" ------------------------------------------------ #


@dataclass
class Customer:
    name: str
    outstanding_pence: int
    overdue_pence: int
    docs: list[Any]  # contacts.AgedDoc


async def _customers(books: Books, today: date) -> tuple[list[Customer], list[str]]:
    """(customers with something owed, by the aged balances Home shows), and every customer name in the books."""
    from app import contacts as cb

    contacts, ledger, _ = await cb.contact_book(books)
    table = cb.aged(contacts, ledger, today).debtors
    owed = [
        Customer(r.name, r.total_pence, r.total_pence - r.buckets.get("current", 0), list(r.documents))
        for r in table.rows
    ]
    names = [c.name for c in contacts if c.kind in ("customer", "both")] if contacts else []
    return owed, list(dict.fromkeys([*(c.name for c in owed), *names]))


async def _named_contact(books: Books, question: str) -> str | None:
    from app import contacts as cb

    try:
        names = [c.name for c in await cb.stored_contacts(books)]
    except Exception:  # noqa: BLE001  no contact book: no name
        return None
    return mentioned(names, question)


_COMMON = frozenset(
    [
        "interiors",
        "interior",
        "architects",
        "property",
        "maintenance",
        "services",
        "supplies",
        "office",
        "building",
        "builders",
        "joinery",
        "dental",
        "studio",
        "trading",
        "direct",
        "group",
        "holdings",
        "solutions",
        "systems",
        "design",
        "designs",
        "company",
        "limited",
        "partners",
        "associates",
        "consulting",
        "construction",
        "electrical",
        "plumbing",
        "timber",
        "hardware",
    ]
)


def mentioned(names: list[str], text: str) -> str | None:
    """The one name the text says: all its words, else a distinctive word of it ("Sterling" for Sterling & Co.
    Architects) when exactly one name has it."""
    full = [n for n in names if _said(n, text)]
    if full:
        return max(full, key=len)
    hay = set(re.findall(r"[a-z0-9]+", text.lower()))
    part = [
        n for n in names
        if any(len(w) >= 4 and w not in _COMMON and w in hay for w in re.findall(r"[a-z0-9]+", n.lower()))
    ]  # fmt: skip
    return part[0] if len(set(part)) == 1 else None


def from_history(history: list[AskTurn], names: list[str]) -> str | None:
    """The customer named most recently in the conversation (newest turn first)."""
    for t in reversed(history[-10:]):
        if found := mentioned(names, t.text):
            return found
    return None


async def customer_answer(
    question: str,
    history: list[AskTurn],
    books: Books,
    q: Query,
    period: AskPeriod,
    cfg: AiConfig | None,
    today: date,
    demo: bool,
) -> AskAnswer:
    owed, names = await _customers(books, today)
    by_name = {c.name: c for c in owed}
    who: str | None = None
    picked_note = ""
    if q.counterparty:
        who = next((n for n in names if name_match(q.counterparty, n)), None)
    if who is None:
        who = mentioned(names, question)
    if who is None:
        who = from_history(history, names)
    if who is None and (want := q.amount_pence):
        room = want * q.tolerance_pct / 100
        near = sorted(
            (c for c in owed if abs(c.overdue_pence - want) <= room),
            key=lambda c: abs(c.overdue_pence - want),
        )
        if len(near) == 1 or (
            len(near) > 1
            and abs(near[0].overdue_pence - want) * 2 <= abs(near[1].overdue_pence - want)
            and abs(near[0].overdue_pence - want) <= want / 10
        ):
            who = near[0].name
            others = "; ".join(f"{_md(c.name)} has {gbp(c.overdue_pence)} overdue" for c in near[1:MAX_LISTED])
            picked_note = (
                f"I took that client to be {_md(who)}, whose {gbp(near[0].overdue_pence)} overdue is closest to the "
                f"{gbp(want)} you mentioned{f' ({others})' if others else ''}.\n\n"
            )
        elif near:
            return _which(near[:MAX_LISTED], q, period, cfg)
    if who is None:
        late = sorted((c for c in owed if c.overdue_pence > 0), key=lambda c: -c.overdue_pence)[:MAX_LISTED]
        return _which(late, q, period, cfg)
    cust = by_name.get(who) or Customer(who, 0, 0, [])
    refs = {d.reference for d in cust.docs if d.reference}
    pay_q = Query(
        kind="customer_paid_check",
        counterparty=who,
        amount_pence=None,
        tolerance_pct=q.tolerance_pct,
        direction="in",
        start=min(q.start, today - timedelta(days=DEFAULT_DAYS - 1)),
        end=today,
        span=f"the last {DEFAULT_DAYS} days",
        keywords=[],
        sources="both" if q.sources == "paypal" else q.sources,
        read_by=q.read_by,
        fallback_reason=q.fallback_reason,
    )
    found = await search(books, pay_q, demo)
    paid = [h for h in found.hits if name_match(who, h.name) or (h.invoice and h.invoice in refs)]
    for h in found.hits:  # a PayPal payment that names one of their invoices counts even under another name
        if h not in paid and h.invoice and h.invoice in refs:
            paid.append(h)
    paid.sort(key=lambda h: h.date)
    waiting = [h for h in paid if not h.in_books and h.where in ("sync_waiting", "paypal")]
    pending = [h for h in paid if h.where == "paypal_pending"]
    in_books = [h for h in paid if h.in_books]
    not_yet = sum(h.amount_pence for h in waiting)
    open_refs = ", ".join(_md(d.reference or "an invoice") for d in cust.docs) or None
    late_refs = ", ".join(_md(d.reference or "an invoice") for d in cust.docs if d.age_days > 0) or open_refs
    name = _md(who)
    lines = []
    if cust.outstanding_pence <= 0:
        verdict = f"Yes: by your books {name} owes you nothing now."
        if in_books:
            last = in_books[-1]
            verdict += f" Their last payment in the books: {describe(last)}"
    elif waiting and not_yet >= cust.overdue_pence > 0:
        rest = cust.outstanding_pence - not_yet
        w = waiting[-1] if len(waiting) == 1 else None
        verdict = (
            f"Yes, the arrears look paid in full: {describe(w)}" if w else
            f"Yes, the arrears look paid in full: PayPal shows {len(waiting)} payments from {name} totalling "
            f"**{gbp(not_yet)}**, not in your books yet."
        )  # fmt: skip
        verdict += (
            f" Your books still show {gbp(cust.outstanding_pence)} outstanding on {open_refs} until you approve it"
            f"{f'; {gbp(rest)} of that is not yet due' if rest > 0 else ''}."
        )
    elif waiting:
        verdict = (
            f"Partly: PayPal shows {gbp(not_yet)} from {name}, not in your books yet, against "
            f"{gbp(cust.overdue_pence or cust.outstanding_pence)} overdue on {late_refs}; "
            f"{gbp(max(0, (cust.overdue_pence or cust.outstanding_pence) - not_yet))} would still be overdue."
        )
        lines = [f"- {describe(h)}" for h in waiting[:MAX_LISTED]]
    elif cust.overdue_pence > 0:
        verdict = f"No: {gbp(cust.overdue_pence)} is still overdue from {name} on {late_refs}"
        verdict += (
            f" ({gbp(cust.outstanding_pence)} outstanding in all)." if cust.outstanding_pence != cust.overdue_pence
            else "."
        )  # fmt: skip
        verdict += (
            f" I found no payment from them in your books or PayPal since {uk(pay_q.start)} that is not already "
            "counted."
        )
    else:
        verdict = (
            f"Nothing from {name} is overdue: {gbp(cust.outstanding_pence)} is outstanding on {open_refs}, not yet due."
        )
    if pending:
        verdict += f" PayPal also has {gbp(sum(h.amount_pence for h in pending))} from them still pending."
    if in_books and cust.outstanding_pence > 0:
        lines.append(("\n" if lines else "") + f"Already in your books since {uk(pay_q.start)}: " + "; ".join(
            f"{gbp(h.amount_pence)} on {uk(h.date)}" for h in in_books[-MAX_LISTED:]) + ".")  # fmt: skip
    if waiting:
        verdict += (
            " Nothing is posted until you approve it."
            if PAYPAL_SYNC in verdict
            else f" Nothing is posted until you approve it in [Sync PayPal]({PAYPAL_SYNC})."
        )
    searched = searched_words(pay_q, found.paypal_note, found.searched_paypal)
    caveat = [f"PayPal itself was not searched: {found.paypal_why_not.rstrip('.')}."] if found.paypal_why_not else []
    if found.searched_paypal:
        caveat.append(LATE_NOTE)
    body = picked_note + verdict + ("\n\n" + "\n".join(lines) if lines else "") + "\n\n" + " ".join([searched, *caveat])
    src = "_System/Ledger/events/"
    keys = [
        KeyNumber(label=f"Outstanding by your books, {name[:50]}", value=gbp(cust.outstanding_pence), source=src),
        KeyNumber(label="Overdue by your books", value=gbp(cust.overdue_pence), source=src),
    ]
    if not_yet:
        keys.append(KeyNumber(label="Paid through PayPal, not in your books yet", value=gbp(not_yet),
                              source=waiting[0].citation or "PayPal"))  # fmt: skip
    cites = [*(_cites(paid[-MAX_LISTED:])), *(f"invoice:{d.reference}" for d in cust.docs if d.reference)]
    return AskAnswer(answer_md=body, key_numbers=keys, citations=list(dict.fromkeys(cites)), **_base(period, q, cfg))


def _which(cands: list[Customer], q: Query, period: AskPeriod, cfg: AiConfig | None) -> AskAnswer:
    if not cands:
        text = "Which customer do you mean? Nobody owes you anything overdue by your books, so I can't tell from that."
    else:
        listed = "; ".join(f"{_md(c.name)} ({gbp(c.overdue_pence)} overdue)" for c in cands)
        text = f"Which customer do you mean? {listed}. Say the name and I'll check their payments, PayPal included."
    return AskAnswer(
        answer_md=text,
        key_numbers=[],
        citations=[],
        **{**_base(period, q, cfg), "confidence": "medium"},
    )


async def answer(
    question: str,
    history: list[AskTurn],
    books: Books,
    cfg: AiConfig | None,
    period: AskPeriod,
    today: date,
    demo: bool = False,
) -> AskAnswer | None:
    """The search answer, or None when the question is not a search (Ask carries on as before)."""
    kind = intent(question)
    if kind is None:
        return None
    q = await read_query(question, history, kind, cfg, today)
    if q.counterparty is None and q.kind == "payment_search":  # a contact the question names, by code
        q.counterparty = await _named_contact(books, question)
    if q.kind == "customer_paid_check":
        return await customer_answer(question, history, books, q, period, cfg, today, demo)
    return payment_answer(await search(books, q, demo), period, cfg)
