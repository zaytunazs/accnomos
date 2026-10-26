"""Accnomos ledger: immutable events, projections, deterministic VAT.

Invariants (PRD §8):
- Σ debits == Σ credits for every event.
- Posted events are never edited; corrections are reversal events.
- VAT boxes are computed here, by code — never by a model.
"""

from accnomos_ledger.events import Line, LedgerEvent, VatCode
from accnomos_ledger.vat import VatReturn, compute_vat_return

__all__ = ["Line", "LedgerEvent", "VatCode", "VatReturn", "compute_vat_return"]
