"""Deterministic UK VAT return (9 boxes) from approved ledger events.

Rules follow the HMRC VAT (MTD) API 1.0 submit schema (checked 26 Oct 2026):
- Boxes 1–5 are pounds to 2 dp; box 5 (netVatDue) is the ABSOLUTE value of box 3 − box 4.
- Boxes 6–9 are whole pounds (we truncate pence, as HMRC VAT Notice 700/12 allows rounding down).
- No model is involved anywhere in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

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


def compute_vat_return(
    events: list[LedgerEvent], period_key: str, start: date, end: date
) -> VatReturn:
    """Sum approved events dated within [start, end] into the 9 boxes."""
    ret = VatReturn(period_key=period_key, start=start, end=end)
    sales_net = purchases_net = sales_vat = purchases_vat = 0
    for ev in events:
        if ev.date < start or ev.date > end or ev.kind not in {"sale", "purchase", "reversal"}:
            continue
        if ev.net is None:
            ret.warnings.append(f"event {ev.id}: no net amount recorded; excluded")
            continue
        codes = {ln.vat_code for ln in ev.lines if ln.vat_code is not None}
        if not codes & ON_RETURN:
            continue  # out of scope
        vat = ev.vat or 0
        sign = -1 if ev.kind == "reversal" else 1
        is_sale = ev.kind == "sale" or (ev.kind == "reversal" and any(ln.credit and "Sales" in ln.account for ln in ev.lines))
        if is_sale:
            sales_net += sign * ev.net
            sales_vat += sign * vat
        else:
            purchases_net += sign * ev.net
            purchases_vat += sign * vat
        ret.event_ids.append(ev.id)
    ret.vat_due_sales = _pounds(sales_vat)
    ret.vat_reclaimed = _pounds(purchases_vat)
    ret.total_sales_ex_vat = _whole_pounds(sales_net)
    ret.total_purchases_ex_vat = _whole_pounds(purchases_net)
    return ret
