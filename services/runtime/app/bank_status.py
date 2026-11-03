"""How far the bank lines are sorted: one definition, used by the Bank page's statements and summary, Home's
"lines to match" tile and the bank lines list, so the three can never disagree.

Two bases, chosen by the books' profile:
* ledger (a business): a line is resolved when it is matched to the books, a transfer between the owner's own
  accounts, or ignored (`BankLine.resolved`). Open = everything else, whether or not a match is suggested.
* household (personal books): there is no ledger to match against. A line is sorted when it is money in (income),
  a transfer or ignored, or money out in a household category by a rule or by hand (app/personal.py `categorise`).
  Open = money out that no rule recognises yet ("Other", uncategorised): the same lines the Budget page counts as
  uncategorised.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from accnomos_ledger.bank import BankLine
from app import personal as pf
from app.books import Books

Basis = Literal["ledger", "household"]
HouseholdSource = Literal["rule", "hand", "income", "excluded", "none"]


class BankStatus(BaseModel):
    basis: Basis
    total: int
    resolved: int  # ledger: matched, transfer or ignored; household: sorted (see the module docstring)
    open: int  # total - resolved: Home's "lines to match" (ledger) or "lines with no category" (household)
    matched: int
    suggested: int
    unmatched: int
    transfer: int
    ignored: int
    label: str  # "9 of 25 lines resolved" / "760 of 770 lines sorted"
    open_label: str  # "16 lines to match" / "All matched" / "3 lines with no category" / "All sorted"


class HouseholdLine(BaseModel):
    category_id: str | None  # None for money in and for transfers / ignored lines
    category: str | None
    source: HouseholdSource
    sorted: bool


class Household:
    """The household rules, loaded once, to sort lines with."""

    def __init__(
        self, categories: Sequence[pf.Category], rules: Sequence[pf.PersonalRule], overrides: dict[str, str]
    ) -> None:
        self.categories = list(categories)
        self.rules = list(rules)
        self.overrides = overrides
        self._names = {c.id: c.name for c in self.categories}
        self._known = set(self._names)

    def line(self, ln: BankLine) -> HouseholdLine:
        if not pf.counts(ln):
            return HouseholdLine(category_id=None, category=None, source="excluded", sorted=True)
        if ln.amount_pence >= 0:
            return HouseholdLine(category_id=None, category="Income", source="income", sorted=True)
        cat, how = pf.categorise(ln, self.rules, self.overrides, self._known)
        source: HouseholdSource = "hand" if how == "hand" else "rule" if how == "rule" else "none"
        return HouseholdLine(
            category_id=cat, category=self._names.get(cat, "Other"), source=source, sorted=source != "none"
        )


async def load_household(books: Books) -> Household:
    return Household(await pf.load_categories(books), await pf.load_rules(books), await pf.load_overrides(books))


def _count(lines: Sequence[BankLine], status: str) -> int:
    return sum(ln.status == status for ln in lines)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def status(lines: Sequence[BankLine], household: Household | None = None) -> BankStatus:
    """The status of `lines`: by the household's rules when `household` is given, else against the ledger."""
    total = len(lines)
    counts = {s: _count(lines, s) for s in ("matched", "suggested", "unmatched", "transfer", "ignored")}
    if household is None:
        resolved = sum(ln.resolved for ln in lines)
        open_ = total - resolved
        return BankStatus(
            basis="ledger",
            total=total,
            resolved=resolved,
            open=open_,
            **counts,
            label=f"{resolved} of {_plural(total, 'line')} resolved",
            open_label=f"{_plural(open_, 'line')} to match" if open_ else "All matched",
        )
    resolved = sum(household.line(ln).sorted for ln in lines)
    open_ = total - resolved
    return BankStatus(
        basis="household",
        total=total,
        resolved=resolved,
        open=open_,
        **counts,
        label=f"{resolved} of {_plural(total, 'line')} sorted",
        open_label=f"{_plural(open_, 'line')} with no category" if open_ else "All sorted",
    )


async def household_for(books: Books, kind: str | None = None) -> Household | None:
    """The household rules for personal books, else None (a business is matched against its ledger)."""
    if kind is None:
        from app.dashboard import _profile_or_default  # a lazy import keeps dashboard and this module apart

        kind = (await _profile_or_default(books)).kind
    return await load_household(books) if kind == "personal" else None
