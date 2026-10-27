"""Autopilot L1: "Always do this for <supplier>" rules, and auto-approval only when nothing looks off.

A rule is written only when a person approves a proposal with "Always do this" ticked; it lives in the
user's own folder at _System/Rules/rules.json, one rule per supplier key. On a later scan a proposal
is auto-approved only when every one of these holds; otherwise it waits in Review like any other
proposal, with the reasons recorded on it:

- Autopilot is switched on (the app sends `X-Autopilot: off` to skip it);
- a rule exists for the supplier's normalised name, and the document is a purchase like the rule's;
- every code check passed: no failure and no warning;
- the supplier's VAT number is the one on the rule (no number on either counts as the same);
- the VAT treatment (VAT codes on the expense lines) is the rule's;
- the gross is above zero and no more than 2x the rule's typical amount.

The typical amount is the gross of the approval that created the rule; Autopilot never moves it.
Pure decisions here; the scan (app/inbox.py) posts through the same `approve()` as the Approve button.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.books import AUTOPILOT_RULES, Books, now
from app.checks import gbp, normalise_vat_number
from app.checks import p as pence
from app.journal import VAT_CONTROL
from app.schemas import AutopilotDecision, JournalLine, Proposal

AUTOPILOT = "autopilot"  # approved_by on events Autopilot posts
ACTOR = "agent:autopilot"  # its audit lines
MAX_TIMES_TYPICAL = 2
KEY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TRAILING = {"ltd", "limited", "plc", "llp", "uk", "co"}
log = logging.getLogger(__name__)


class AutopilotRule(BaseModel):
    supplier_key: str
    supplier_name: str = ""  # as printed on the document the rule was made from
    category: str
    account: str | None = None  # expense account used on that approval
    vat_code: str | None = None  # VAT codes on the expense lines, e.g. "S" or "S,Z"
    side: Literal["purchase", "sale"] = "purchase"
    typical_gross_pence: int
    vrn: str | None = None
    created_at: datetime = Field(default_factory=now)
    created_from_proposal_id: str
    created_by: str | None = None
    hits: int = 0


def supplier_key(name: str) -> str:
    """'Screwfix Direct Ltd.' -> 'screwfix-direct'; "Sainsbury's" -> 'sainsburys'; 'B&Q' -> 'b-and-q'."""
    s = re.sub(r"['’]", "", name.lower().replace("&", " and "))
    words = re.sub(r"[^a-z0-9]+", " ", s).split()
    while len(words) > 1 and words[-1] in _TRAILING:
        words.pop()
    if len(words) > 1 and words[0] == "the":
        words.pop(0)
    return "-".join(words)


def side_of(p: Proposal) -> Literal["purchase", "sale"]:
    return "sale" if p.extracted.doc_type == "sales_invoice" else "purchase"


def expense_vat_codes(journal: list[JournalLine]) -> str | None:
    codes = sorted({j.vat_code for j in journal if j.debit_pence and j.account != VAT_CONTROL and j.vat_code})
    return ",".join(codes) or None


def expense_account(journal: list[JournalLine]) -> str | None:
    return next((j.account for j in journal if j.debit_pence and j.account != VAT_CONTROL), None)


def rule_from_proposal(p: Proposal, user: str) -> AutopilotRule | None:
    """The rule an approval of `p` teaches, or None. Purchases only: on a sales invoice the
    "supplier" is the user's own business, so a rule would match every sale."""
    key = supplier_key(p.extracted.supplier_name)
    gross = pence(p.extracted.gross_total)
    if side_of(p) != "purchase" or not key or gross <= 0:
        return None
    return AutopilotRule(
        supplier_key=key,
        supplier_name=p.extracted.supplier_name.strip(),
        category=p.extracted.category_guess,
        account=expense_account(p.journal_draft),
        vat_code=expense_vat_codes(p.journal_draft),
        side="purchase",
        typical_gross_pence=gross,
        vrn=normalise_vat_number(p.extracted.supplier_vat_number),
        created_from_proposal_id=p.id,
        created_by=user,
    )


# --------------------------------------------------------------------------- #
# Storage: _System/Rules/rules.json in the user's folder
# --------------------------------------------------------------------------- #


async def load_rules(books: Books) -> list[AutopilotRule]:
    out: list[AutopilotRule] = []
    for raw in await books.read_json(AUTOPILOT_RULES, []):
        try:
            out.append(AutopilotRule.model_validate(raw))
        except ValidationError:  # a hand-edited rules.json must not break scanning
            log.warning("skipping invalid Autopilot rule %r", raw)
    return out


async def save_rule(books: Books, rule: AutopilotRule) -> None:
    """Append `rule`, replacing any rule with the same supplier key."""
    new = rule.model_dump(mode="json")

    def change(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [*(r for r in rules if r.get("supplier_key") != rule.supplier_key), new]

    await books._update_json(AUTOPILOT_RULES, [], change)


async def remove_rule(books: Books, key: str) -> AutopilotRule | None:
    """Delete the rule for `key`; returns it, or None when there was none."""
    gone = next((r for r in await load_rules(books) if r.supplier_key == key), None)
    if gone is not None:
        await books._update_json(AUTOPILOT_RULES, [], lambda rules: [r for r in rules if r.get("supplier_key") != key])
    return gone


async def record_hit(books: Books, key: str) -> None:
    def change(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "hits": int(r.get("hits", 0)) + 1} if r.get("supplier_key") == key else r for r in rules]

    await books._update_json(AUTOPILOT_RULES, [], change)


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #


def match(p: Proposal, rules: list[AutopilotRule]) -> AutopilotRule | None:
    key = supplier_key(p.extracted.supplier_name)
    return next((r for r in reversed(rules) if r.supplier_key == key), None) if key else None


def evaluate(p: Proposal, rule: AutopilotRule | None, enabled: bool = True) -> AutopilotDecision:
    """auto_approve only when every condition in the module docstring holds; `reasons` says why (not)."""
    key = rule.supplier_key if rule else None
    if not enabled:
        return AutopilotDecision(auto_approve=False, reasons=["Autopilot is switched off"], supplier_key=key)
    if rule is None:
        return AutopilotDecision(auto_approve=False, reasons=["No Autopilot rule for this supplier"])
    doc = p.extracted
    refusals: list[str] = []
    if side_of(p) != rule.side:
        refusals.append(f"This is a {side_of(p)}; the rule is for {rule.side}s")
    for c in p.checks:
        if not c.ok:
            refusals.append(f"Check {c.code} {'failed' if c.severity == 'fail' else 'warned'}: {c.message}")
    if p.status != "proposed" and not any(not c.ok for c in p.checks):
        refusals.append(f"Proposal is {p.status}")
    vrn = normalise_vat_number(doc.supplier_vat_number)
    if vrn != rule.vrn:
        refusals.append(f"VAT number {vrn or 'none'} differs from {rule.vrn or 'none'} on the rule")
    codes = expense_vat_codes(p.journal_draft)
    if codes != rule.vat_code:
        refusals.append(f"VAT treatment {codes or 'none'} differs from {rule.vat_code or 'none'} on the rule")
    gross = pence(doc.gross_total)
    if gross <= 0:
        refusals.append("Nothing to post: the total is zero")
    elif gross > MAX_TIMES_TYPICAL * rule.typical_gross_pence:
        refusals.append(f"{gbp(gross)} is more than {MAX_TIMES_TYPICAL}x the usual {gbp(rule.typical_gross_pence)}")
    if refusals:
        return AutopilotDecision(auto_approve=False, reasons=refusals, supplier_key=key)
    ok = [
        f"Rule for {rule.supplier_name or rule.supplier_key}: {rule.category}",
        f"All {len(p.checks)} code checks passed",
        f"VAT number {vrn or 'none'} and VAT treatment {codes or 'none'} as on the rule",
        f"{gbp(gross)} is within {MAX_TIMES_TYPICAL}x the usual {gbp(rule.typical_gross_pence)}",
    ]
    return AutopilotDecision(auto_approve=True, reasons=ok, supplier_key=key)


def edits_for(rule: AutopilotRule) -> dict[str, Any]:
    """The edits that make an auto-approval 'do the same' as the approval that made the rule."""
    return {"category": rule.category, **({"account": rule.account} if rule.account else {})}
