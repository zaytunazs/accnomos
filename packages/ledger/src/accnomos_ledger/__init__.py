"""Accnomos ledger: immutable events, projections, deterministic VAT.

Invariants (PRD §8):
- Σ debits == Σ credits for every event.
- Posted events are never edited; corrections are reversal events.
- VAT boxes are computed here, by code — never by a model.
"""

from accnomos_ledger.bank import BankLine, parse_bank_csv
from accnomos_ledger.events import LedgerEvent, Line, Recode, VatCode
from accnomos_ledger.matching import Match, suggest_matches
from accnomos_ledger.vat import VatReturn, compute_vat_return, reverses_sale, vat_side
from accnomos_ledger.vat_schemes import (
    AnnualAccounting,
    DocPayment,
    FlatRate,
    SchemeBooks,
    SchemeReturn,
    SchemeSpan,
    compute_scheme_return,
)

__all__ = [
    "AnnualAccounting",
    "BankLine",
    "DocPayment",
    "FlatRate",
    "Line",
    "LedgerEvent",
    "Match",
    "Recode",
    "SchemeBooks",
    "SchemeReturn",
    "SchemeSpan",
    "VatCode",
    "VatReturn",
    "compute_scheme_return",
    "compute_vat_return",
    "parse_bank_csv",
    "reverses_sale",
    "suggest_matches",
    "vat_side",
]
