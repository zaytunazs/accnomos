"""Suggest which posted ledger event each bank line pays for. Deterministic scoring, no model.

Score (0-1): amount within ±1p required (0.5 exact, 0.45 a penny out), date 0.3 on the day falling
0.05 a day to ±5 days, counterparty similarity up to 0.2 (share of the counterparty's words found in the
description; near-spellings such as "toolstn"/"toolstation" count), card last 4 digits +0.1.
≥0.9 is an "exact" suggestion, 0.6-0.9 "suggested", anything lower is dropped.

Money paid on terms comes later than the document: an invoice posted to debtors or creditors, or a bank
line that is a direct debit / faster payment / BACS, may be up to 60 days after the document date (the
usual ceiling for UK business payment terms). Past 5 days the date adds nothing, so the counterparty's
name has to carry the match and it is never "exact"; the nearer date still wins a tie.
One bank line may also pay 2-3 same-counterparty events dated the same day. No event is used twice.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, PrivateAttr

from accnomos_ledger.bank import BankLine
from accnomos_ledger.events import LedgerEvent

EXACT, SUGGEST = 0.9, 0.6
MAX_DAYS = 5
TERMS_DAYS = 60  # how long after the document a payment on terms may come
#: Settlement accounts that mean "not paid yet": the payment comes later, on terms.
ON_TERMS_PREFIXES = ("1100", "2100")
#: Bank lines that are not card payments at the till: collected or sent after the bill.
ON_TERMS_LINE = re.compile(r"\b(dd|direct debit|fp|fpi|fpo|faster payment|bacs|bgc|standing order)\b", re.IGNORECASE)
PENNY = 1  # amount tolerance in pence: card terminals and some invoices round differently
#: Accounts whose movement is the money that actually left or arrived (the settlement leg).
SETTLEMENT_PREFIXES = ("1200", "1210", "2100", "1100")
NOISE_PHRASES = ("card payment", "contactless", "direct debit", "faster payment", "standing order")
NOISE_WORDS = {"visa", "pos", "card", "payment", "to", "from", "the", "ltd", "limited", "plc", "uk", "gb", "gbr",
               "dd", "so", "fpi", "fpo", "bgc", "deb", "cr", "dr", "on", "ref", "co", "and", "www", "com", "london"}

MatchKind = Literal["exact", "suggested"]


class Match(BaseModel):
    line_id: str
    event_id: str  # the first (or only) event
    event_ids: list[str]
    score: float
    kind: MatchKind
    reasons: list[str]
    _days: int = PrivateAttr(0)  # days between line and event: the nearer one wins a tie


def settlement_pence(event: LedgerEvent) -> int:
    """Signed bank movement of an event: purchases negative, sales positive (debit - credit on settlement legs)."""
    legs = [ln for ln in event.lines if ln.account.startswith(SETTLEMENT_PREFIXES)]
    return sum(ln.debit - ln.credit for ln in legs)


def tokens(text: str | None) -> set[str]:
    s = (text or "").lower()
    for phrase in NOISE_PHRASES:
        s = s.replace(phrase, " ")
    words = re.findall(r"[a-z]+", re.sub(r"\d+", " ", s))
    return {w for w in words if len(w) > 1 and w not in NOISE_WORDS}


def _kind(score: float) -> MatchKind | None:
    return "exact" if score >= EXACT else "suggested" if score >= SUGGEST else None


def on_terms(line: BankLine, event: LedgerEvent) -> bool:
    """The payment may come well after the document: an invoice on terms, or a DD / transfer line."""
    if any(ln.account.startswith(ON_TERMS_PREFIXES) for ln in event.lines):
        return True
    return bool(ON_TERMS_LINE.search(f"{line.description} {line.reference or ''}"))


def _date_score(line: BankLine, event: LedgerEvent) -> tuple[float, str, int] | None:
    signed = (line.date - event.date).days
    days = abs(signed)
    if days > MAX_DAYS and not (0 < signed <= TERMS_DAYS and on_terms(line, event)):
        return None
    why = "same day" if days == 0 else f"{days} day{'s' if days > 1 else ''} apart"
    if days > MAX_DAYS:
        why = f"paid {days} days after the document"
    return max(0.0, 0.3 - 0.05 * days), why, days


def _abbreviates(short: str, long: str) -> bool:
    """'toolstn' abbreviates 'toolstation': same first four letters, the rest in order."""
    rest = iter(long)
    return short[:4] == long[:4] and all(c in rest for c in short)


def _similar(word: str, words: set[str]) -> bool:
    """`word` is in `words`, or (4+ letters) abbreviates / is abbreviated by / is a near-spelling of one."""
    if word in words:
        return True
    if len(word) < 4:
        return False
    return any(len(w) >= 4 and (_abbreviates(word, w) or _abbreviates(w, word)
                                or SequenceMatcher(None, word, w).ratio() >= 0.85) for w in words)


def _name_score(line: BankLine, counterparty: str | None) -> tuple[float, str | None]:
    want = tokens(counterparty)
    have = tokens(f"{line.description} {line.reference or ''}")
    common = {w for w in want if _similar(w, have)}
    if not want or not common:
        return 0.0, None
    return 0.2 * len(common) / len(want), f"name: {' '.join(sorted(common))}"


def _score(line: BankLine, events: Sequence[LedgerEvent], card_last4: dict[str, str]) -> tuple[float, list[str], int] | None:
    """Score a line against one event or a same-day group; None when amount or date rule out a match."""
    off = abs(sum(settlement_pence(e) for e in events) - line.amount_pence)
    if line.amount_pence == 0 or off > PENNY:
        return None
    dated = _date_score(line, events[0])
    if dated is None:
        return None
    amount = "exact amount" if len(events) == 1 else f"sum of {len(events)} events"
    reasons = [f"{amount}, 1p out" if off else amount, dated[1]]
    name, why = _name_score(line, events[0].counterparty)
    if why:
        reasons.append(why)
    last4 = {card_last4.get(e.id) for e in events} - {None}
    text = f"{line.description} {line.reference or ''}"
    card = 0.1 if any(d and re.search(rf"(?<!\d){re.escape(d)}(?!\d)", text) for d in last4) else 0.0
    if card:
        reasons.append("card last 4 digits")
    return round(min(1.0, 0.5 - 0.05 * off + dated[0] + name + card), 3), reasons, dated[2]


def _match(line: BankLine, group: Sequence[LedgerEvent], scored: tuple[float, list[str], int]) -> Match | None:
    kind = _kind(scored[0])
    if kind is None:
        return None
    ids = [e.id for e in group]
    m = Match(line_id=line.id, event_id=ids[0], event_ids=ids, score=scored[0], kind=kind, reasons=scored[1])
    m._days = scored[2]
    return m


def _singles(lines: Iterable[BankLine], events: Sequence[LedgerEvent], card_last4: dict[str, str]) -> list[Match]:
    out: list[Match] = []
    for line in lines:
        for ev in events:
            scored = _score(line, [ev], card_last4)
            if scored and (m := _match(line, [ev], scored)):
                out.append(m)
    return out


def _groups(events: Sequence[LedgerEvent]) -> list[list[LedgerEvent]]:
    """All 2-3 event combinations sharing a counterparty and a date."""
    buckets: dict[tuple[str, object], list[LedgerEvent]] = defaultdict(list)
    for ev in events:
        if ev.counterparty:
            buckets[(" ".join(sorted(tokens(ev.counterparty))), ev.date)].append(ev)
    out: list[list[LedgerEvent]] = []
    for bucket in buckets.values():
        for size in (2, 3):
            out += [list(c) for c in combinations(bucket, size)]
    return out


def _assign(candidates: list[Match], used_events: set[str], taken_lines: set[str]) -> list[Match]:
    """Greedy, best score first: each line once, each event once."""
    chosen: list[Match] = []
    for m in sorted(candidates, key=lambda m: (-m.score, m._days, len(m.event_ids), m.line_id, m.event_ids)):
        if m.line_id in taken_lines or used_events.intersection(m.event_ids):
            continue
        chosen.append(m)
        taken_lines.add(m.line_id)
        used_events.update(m.event_ids)
    return chosen


def suggest_matches(
    lines: Sequence[BankLine], events: Sequence[LedgerEvent], card_last4: dict[str, str] | None = None
) -> list[Match]:
    """Best match per open bank line. Lines already matched keep their events out of play;
    lines marked as a transfer or ignored are not matched at all.

    `card_last4` optionally maps event id -> last four card digits from the evidence document.
    """
    hints = card_last4 or {}
    used = {eid for ln in lines if ln.status == "matched" for eid in ln.event_ids()}
    taken = {ln.id for ln in lines if ln.resolved}
    open_lines = [ln for ln in lines if ln.id not in taken]
    free = [e for e in events if e.id not in used and settlement_pence(e)]
    chosen = _assign(_singles(open_lines, free, hints), used, taken)

    rest_lines = [ln for ln in open_lines if ln.id not in taken]
    rest_events = [e for e in free if e.id not in used]
    groups: list[Match] = []
    for line in rest_lines:
        for group in _groups(rest_events):
            scored = _score(line, group, hints)
            if scored and (m := _match(line, group, scored)):
                groups.append(m)
    return chosen + _assign(groups, used, taken)
