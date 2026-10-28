"""Bank rules, Xero-style: "when the description contains X, code it to Y".

A rule matches a bank statement line on the description (contains / equals / a safe
regex subset), an optional amount range and the money direction. The action codes the
line: an expense account, a VAT code, a contact and optionally a job. Rules live in
the user's own folder at ``_System/bank_rules.json`` and are evaluated by code, in
order: the first match wins.

The regex subset refuses nested quantifiers (``(a+)+``) and backreferences
(``\\1``, ``(?P=name)``), which are the usual catastrophic-backtracking and
hard-to-read constructs; anything else the ``re`` module accepts is allowed.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.books import Books, now
from app.validation import LENIENT, StrictBody

BANK_RULES = "_System/bank_rules.json"

MatchOp = Literal["contains", "equals", "regex"]
Direction = Literal["in", "out", "either"]

MAX_VALUE_LEN = 200
MAX_ACTION_LEN = 120


class BackreferenceError(ValueError):
    """A bank rule regex uses a construct outside the safe subset."""


_BACKREF = re.compile(r"\\[1-9]|\(\?P=")


def check_regex_safe(pattern: str) -> None:
    """Compile `pattern`; raise BackreferenceError/ValueError when it is not allowed.

    Refused: anything that does not compile, backreferences (``\\1``,
    ``(?P=name)``), and a quantifier applied to a group that itself contains a
    quantifier (``(a+)+``, ``(a|b*)*`` ...). The check is syntactic: escaped
    characters and character classes never count as quantifiers or group bounds.
    """
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Not a valid pattern: {exc}") from exc
    if _BACKREF.search(pattern):
        raise BackreferenceError("Backreferences (such as \\1) are not allowed in bank rule patterns")
    if _has_nested_quantifier(pattern):
        raise BackreferenceError("Nested quantifiers (such as (a+)+) are not allowed in bank rule patterns")


def _has_nested_quantifier(pattern: str) -> bool:
    """True when a quantified group contains a quantifier of its own."""
    # Stack of groups: each entry tracks whether the group body so far holds an
    # unescaped quantifier. Character classes [...] and escapes are skipped.
    stack: list[bool] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            if i < n and pattern[i] == "]":
                i += 1
            while i < n and pattern[i] != "]":
                i += 2 if pattern[i] == "\\" else 1
            i += 1
            continue
        if c == "(":
            stack.append(False)
            i += 1
            continue
        if c == ")":
            if not stack:
                return False  # unbalanced; re.compile already refused it
            inner_has_quant = stack.pop()
            j = i + 1
            quantified = j < n and pattern[j] in "*+?"
            if not quantified and j < n and pattern[j] == "{":
                quantified = re.match(r"\{\d+(?:,\d*)?\}", pattern[j:]) is not None
            if quantified and inner_has_quant:
                return True
            if quantified and stack or not quantified and inner_has_quant and stack:
                stack[-1] = True
            i += 1
            continue
        if c in "*+?" or (c == "{" and re.match(r"\{\d+(?:,\d*)?\}", pattern[i:])):
            if stack:
                stack[-1] = True
            i += 1
            continue
        i += 1
    return False


class BankRuleMatch(StrictBody):
    op: MatchOp = "contains"
    value: str = Field(min_length=1, max_length=MAX_VALUE_LEN)

    @field_validator("value")
    @classmethod
    def _check_pattern(cls, v: str, info: Any) -> str:
        if info.data.get("op") == "regex":
            check_regex_safe(v)
        return v


class BankRuleAction(StrictBody):
    account: str = Field(min_length=1, max_length=MAX_ACTION_LEN)
    vat_code: str | None = Field(default=None, max_length=4)
    contact: str | None = Field(default=None, max_length=MAX_ACTION_LEN)
    job_id: str | None = Field(default=None, max_length=MAX_ACTION_LEN)


class BankRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = Field(default="", max_length=MAX_ACTION_LEN)
    match: BankRuleMatch
    amount_min_pence: int | None = None
    amount_max_pence: int | None = None
    direction: Direction = "either"
    action: BankRuleAction
    created_at: datetime = Field(default_factory=now)
    created_by: str | None = None


#: Built-in codings for unambiguous bank-text tokens: rail/TfL fares and car
#: parking are travel, forecourt fuel words are motor, plain cafe/restaurant words
#: are subsistence. Evaluated in order after the user's own rules
#: (app/bank_reconcile.suggest_rule), so a user rule always wins. Money out only:
#: a matching credit (a refund) is not a purchase. No supplier names: only the
#: generic words and the two network names no other merchant collides with.
BUILTIN_RULES: list[BankRule] = [
    BankRule(
        id="builtin-travel-rail",
        name="Built-in: rail and TfL fares",
        match=BankRuleMatch(op="regex", value=r"trainline|\btfl\b"),
        direction="out",
        action=BankRuleAction(account="7400 Travel"),
    ),
    BankRule(
        id="builtin-travel-parking",
        name="Built-in: car parking",
        match=BankRuleMatch(op="contains", value="parking"),
        direction="out",
        action=BankRuleAction(account="7400 Travel"),
    ),
    BankRule(
        id="builtin-motor-fuel",
        name="Built-in: forecourt fuel",
        match=BankRuleMatch(op="regex", value=r"petrol|diesel|\bfuel\b"),
        direction="out",
        action=BankRuleAction(account="7300 Motor expenses"),
    ),
    BankRule(
        id="builtin-subsistence-food",
        name="Built-in: cafe and restaurant meals",
        match=BankRuleMatch(op="regex", value=r"caf[eé]|restaurant|sandwich"),
        direction="out",
        action=BankRuleAction(account="7410 Subsistence"),
    ),
]


def normalise_description(text: str | None) -> str:
    """Lowercase with runs of whitespace collapsed, for matching and de-dup."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def rule_matches(rule: BankRule, *, description: str, amount_pence: int) -> bool:
    """Pure predicate: does `rule` match a line with this description and amount."""
    hay = description or ""
    want = rule.match.value
    if rule.match.op == "contains":
        if want.lower() not in hay.lower():
            return False
    elif rule.match.op == "equals":
        if hay.strip().lower() != want.strip().lower():
            return False
    else:
        try:
            if re.search(want, hay, re.IGNORECASE) is None:
                return False
        except re.error:  # a hand-edited bank_rules.json must not break matching
            return False
    if rule.direction == "in" and amount_pence <= 0:
        return False
    if rule.direction == "out" and amount_pence >= 0:
        return False
    if rule.amount_min_pence is not None and amount_pence < rule.amount_min_pence:
        return False
    return not (rule.amount_max_pence is not None and amount_pence > rule.amount_max_pence)


def first_match(rules: list[BankRule], *, description: str, amount_pence: int) -> BankRule | None:
    """The first rule in order that matches; None when nothing does."""
    return next(
        (r for r in rules if rule_matches(r, description=description, amount_pence=amount_pence)),
        None,
    )


async def load_bank_rules(books: Books) -> list[BankRule]:
    """Rules in evaluation order. A hand-edited file never breaks the read."""
    out: list[BankRule] = []
    for raw in await books.read_json(BANK_RULES, []):
        try:
            out.append(BankRule.model_validate(raw, **LENIENT))
        except ValueError:
            continue
    return out


async def save_bank_rules(books: Books, rules: list[BankRule]) -> None:
    payload = [r.model_dump(mode="json") for r in rules]
    await books._update_json(BANK_RULES, [], lambda _old: payload)


def describe(rule: BankRule) -> str:
    """One plain-English line for the UI: what matches and where it is coded."""
    when = {"contains": "contains", "equals": "is", "regex": "matches"}[rule.match.op]
    bits = [f"When the description {when} {rule.match.value!r}"]
    if rule.direction != "either":
        bits.append(f"money {rule.direction}")
    if rule.amount_min_pence is not None or rule.amount_max_pence is not None:
        bits.append(f"amount {rule.amount_min_pence or '…'}–{rule.amount_max_pence or '…'}p")
    action = f"code it to {rule.action.account}"
    if rule.action.vat_code:
        action += f" (VAT {rule.action.vat_code})"
    if rule.action.contact:
        action += f" for {rule.action.contact}"
    return ", ".join(bits) + f" -> {action}"
