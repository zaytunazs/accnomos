"""Deterministic UK VAT return (9 boxes) from approved ledger events.

Rules follow the HMRC VAT (MTD) API 1.0 submit schema (checked 26 Oct 2026):
- Boxes 1–5 are pounds to 2 dp; box 5 (netVatDue) is the ABSOLUTE value of box 3 − box 4.
- Boxes 6–9 are whole pounds (we truncate pence, as HMRC VAT Notice 700/12 allows rounding down).
- An `adjustment` counts only when it carries `vat_box` (a manual journal with VAT, a VAT recode): its signed
  `net` and `vat` go on that side as they are.
- No model is involved anywhere in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from accnomos_ledger.events import LedgerEvent, VatCode

ON_RETURN = {VatCode.STANDARD, VatCode.REDUCED, VatCode.ZERO, VatCode.EXEMPT, VatCode.NO_VAT}


@dataclass
class VatReturn:
    period_key: str
    start: date
    end: date
    vat_due_sales: Decimal = Decimal("0.00")  # box 1
    vat_due_acquisitions: Decimal = Decimal("0.00")  # box 2 (NI/EU; 0 for GB-only traders)
    vat_reclaimed: Decimal = Decimal("0.00")  # box 4
    total_sales_ex_vat: int = 0  # box 6, whole pounds
    total_purchases_ex_vat: int = 0  # box 7, whole pounds
    goods_supplied_ni_eu: int = 0  # box 8
    acquisitions_ni_eu: int = 0  # box 9
    event_ids: list[str] = field(default_factory=list)
    sales_event_ids: list[str] = field(default_factory=list)  # behind boxes 1 and 6
    purchase_event_ids: list[str] = field(default_factory=list)  # behind boxes 4 and 7
    warnings: list[str] = field(default_factory=list)

    @property
    def total_vat_due(self) -> Decimal:  # box 3
        return self.vat_due_sales + self.vat_due_acquisitions

    @property
    def net_vat_due(self) -> Decimal:  # box 5, absolute value
        return abs(self.total_vat_due - self.vat_reclaimed)

    def to_hmrc(self, finalised: bool = False) -> dict:
        """Body for POST /organisations/vat/{vrn}/returns (all 11 fields required by HMRC)."""
        return {
            "periodKey": self.period_key,
            "vatDueSales": float(self.vat_due_sales),
            "vatDueAcquisitions": float(self.vat_due_acquisitions),
            "totalVatDue": float(self.total_vat_due),
            "vatReclaimedCurrPeriod": float(self.vat_reclaimed),
            "netVatDue": float(self.net_vat_due),
            "totalValueSalesExVAT": self.total_sales_ex_vat,
            "totalValuePurchasesExVAT": self.total_purchases_ex_vat,
            "totalValueGoodsSuppliedExVAT": self.goods_supplied_ni_eu,
            "totalAcquisitionsExVAT": self.acquisitions_ni_eu,
            "finalised": finalised,
        }


def _pounds(pence: int) -> Decimal:
    return (Decimal(pence) / 100).quantize(Decimal("0.01"))


def _whole_pounds(pence: int) -> int:
    return int((Decimal(pence) / 100).quantize(Decimal("1"), rounding=ROUND_DOWN))


def reverses_sale(ev: LedgerEvent) -> bool:
    """True for a reversal of a sale. A reversal swaps every line, so undoing a sale *debits* Sales."""
    return ev.kind == "reversal" and any(ln.debit and "Sales" in ln.account for ln in ev.lines)


def _restores_cost(account: str, debit: int) -> bool:
    """A debit to an expense account (codes 5000-8999) or to VAT control."""
    code = account[:4]
    return bool(debit) and code.isdigit() and (5000 <= int(code) <= 8999 or code == "2200")


def vat_side(ev: LedgerEvent) -> tuple[Literal["sales", "purchases"], int] | None:
    """("sales"|"purchases", sign) for an event that can reach the VAT return; None otherwise.

    Worked out from the event alone, so it needs no other event:
    - a sale or purchase counts +1;
    - an adjustment with `vat_box` (a manual journal with VAT, its auto-reversal or void, a VAT recode) is on that
      side, +1: its `net` and `vat` are already signed;
    - a reversal touching Sales is on the sales side: -1 when it debits Sales (an undo of a sale, or a credit note
      to a customer), +1 when it credits Sales (the undo of such a credit note); one with no Sales line (a VAT-only
      sale) is on the sales side when it touches 1100 Debtors: -1 when it credits Debtors, +1 when it debits it;
    - any other reversal with a VAT code is on the purchases side: -1 when it credits the cost (an undo of a
      purchase, or a supplier's credit note), +1 when it debits an expense or VAT control again (the undo of a
      supplier's credit note).
    """
    if ev.kind == "sale":
        return "sales", 1
    if ev.kind == "purchase":
        return "purchases", 1
    if ev.kind == "adjustment":
        return (ev.vat_box, 1) if ev.vat_box else None
    if ev.kind != "reversal" or not any(ln.vat_code is not None for ln in ev.lines):
        return None
    sales = [ln for ln in ev.lines if "Sales" in ln.account]
    if sales:
        return "sales", -1 if any(ln.debit for ln in sales) else 1
    debtors = [ln for ln in ev.lines if ln.account.startswith("1100")]
    if debtors:  # a VAT-only sale (net £0.00 posts no Sales line): only sales go through 1100 Debtors
        return "sales", -1 if any(ln.credit for ln in debtors) else 1
    return "purchases", 1 if any(_restores_cost(ln.account, ln.debit) for ln in ev.lines) else -1


def compute_vat_return(events: list[LedgerEvent], period_key: str, start: date, end: date) -> VatReturn:
    """Sum approved events dated within [start, end] into the 9 boxes."""
    ret = VatReturn(period_key=period_key, start=start, end=end)
    sales_net = purchases_net = sales_vat = purchases_vat = 0
    for ev in events:
        if ev.date < start or ev.date > end:
            continue
        if ev.kind not in {"sale", "purchase", "reversal"} and not (ev.kind == "adjustment" and ev.vat_box):
            continue
        if ev.net is None:
            ret.warnings.append(f"event {ev.id}: no net amount recorded; excluded")
            continue
        codes = {ln.vat_code for ln in ev.lines if ln.vat_code is not None}
        if not codes & ON_RETURN:
            continue  # out of scope
        vat = ev.vat or 0
        side, sign = vat_side(ev) or ("purchases", -1)
        if side == "sales":
            sales_net += sign * ev.net
            sales_vat += sign * vat
            ret.sales_event_ids.append(ev.id)
        else:
            purchases_net += sign * ev.net
            purchases_vat += sign * vat
            ret.purchase_event_ids.append(ev.id)
        ret.event_ids.append(ev.id)
    ret.vat_due_sales = _pounds(sales_vat)
    ret.vat_reclaimed = _pounds(purchases_vat)
    ret.total_sales_ex_vat = _whole_pounds(sales_net)
    ret.total_purchases_ex_vat = _whole_pounds(purchases_net)
    return ret
