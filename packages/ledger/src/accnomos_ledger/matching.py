"""Suggest which posted ledger event each bank line pays for. Deterministic scoring, no model.

Score (0-1): exact amount 0.5 (required), date 0.3 on the day falling 0.05 a day to ±3 days,
counterparty/description token overlap up to 0.2, card last 4 digits in the description +0.1.
≥0.9 is an "exact" suggestion, 0.6-0.9 "suggested", anything lower is dropped.
One bank line may also pay 2-3 same-counterparty events dated the same day. No event is used twice.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from itertools import combinations
from typing import Literal

from pydantic import BaseModel

from accnomos_ledger.bank import BankLine
from accnomos_ledger.events import LedgerEvent

EXACT, SUGGEST = 0.9, 0.6
MAX_DAYS = 3
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


def _date_score(line: BankLine, event: LedgerEvent) -> tuple[float, str] | None:
    days = abs((line.date - event.date).days)
    if days > MAX_DAYS:
        return None
    return 0.3 - 0.05 * days, "same day" if days == 0 else f"{days} day{'s' if days > 1 else ''} apart"


def _name_score(line: BankLine, counterparty: str | None) -> tuple[float, str | None]:
    want = tokens(counterparty)
    common = want & tokens(f"{line.description} {line.reference or ''}")
    if not want or not common:
        return 0.0, None
    return 0.2 * len(common) / len(want), f"name: {' '.join(sorted(common))}"


def _score(line: BankLine, events: Sequence[LedgerEvent], card_last4: dict[str, str]) -> tuple[float, list[str]] | None:
    """Score a line against one event or a same-day group; None when amount or date rule out a match."""
    if line.amount_pence == 0 or sum(settlement_pence(e) for e in events) != line.amount_pence:
        return None
    dated = _date_score(line, events[0])
    if dated is None:
        return None
    reasons = ["exact amount" if len(events) == 1 else f"sum of {len(events)} events", dated[1]]
    name, why = _name_score(line, events[0].counterparty)
    if why:
        reasons.append(why)
    last4 = {card_last4.get(e.id) for e in events} - {None}
    text = f"{line.description} {line.reference or ''}"
    card = 0.1 if any(d and re.search(rf"(?<!\d){re.escape(d)}(?!\d)", text) for d in last4) else 0.0
    if card:
        reasons.append("card last 4 digits")
    return round(min(1.0, 0.5 + dated[0] + name + card), 3), reasons


def _match(line: BankLine, group: Sequence[LedgerEvent], scored: tuple[float, list[str]]) -> Match | None:
    kind = _kind(scored[0])
    if kind is None:
        return None
    ids = [e.id for e in group]
    return Match(line_id=line.id, event_id=ids[0], event_ids=ids, score=scored[0], kind=kind, reasons=scored[1])


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
    for m in sorted(candidates, key=lambda m: (-m.score, len(m.event_ids), m.line_id, m.event_ids)):
        if m.line_id in taken_lines or used_events.intersection(m.event_ids):
            continue
        chosen.append(m)
        taken_lines.add(m.line_id)
        used_events.update(m.event_ids)
    return chosen


def suggest_matches(
    lines: Sequence[BankLine], events: Sequence[LedgerEvent], card_last4: dict[str, str] | None = None
) -> list[Match]:
    """Best match per open bank line. Lines already matched keep their events out of play.

    `card_last4` optionally maps event id -> last four card digits from the evidence document.
    """
    hints = card_last4 or {}
    used = {eid for ln in lines if ln.status == "matched" for eid in ln.event_ids()}
    taken = {ln.id for ln in lines if ln.status == "matched"}
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
