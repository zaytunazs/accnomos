from datetime import date, datetime

import pytest
from accnomos_ledger import LedgerEvent, Line, VatCode, compute_vat_return

APPROVED = dict(approved_by="owner@example.test", approved_at=datetime(2026, 10, 21, 18, 0))


def purchase(net: int, vat: int, day: date, code=VatCode.STANDARD) -> LedgerEvent:
    return LedgerEvent(
        kind="purchase",
        date=day,
        net=net,
        vat=vat,
        lines=[
            Line(account="5100 Tools", debit=net, vat_code=code),
            *([Line(account="2200 VAT control", debit=vat)] if vat else []),
            Line(account="1200 Bank", credit=net + vat),
        ],
        **APPROVED,
    )


def sale(net: int, vat: int, day: date) -> LedgerEvent:
    return LedgerEvent(
        kind="sale",
        date=day,
        net=net,
        vat=vat,
        lines=[
            Line(account="1100 Debtors", debit=net + vat),
            Line(account="4000 Sales", credit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", credit=vat),
        ],
        **APPROVED,
    )


def test_unbalanced_event_rejected():
    with pytest.raises(ValueError):
        LedgerEvent(
            kind="purchase",
            date=date(2026, 9, 1),
            lines=[Line(account="a", debit=100), Line(account="b", credit=99)],
            **APPROVED,
        )


def test_screwfix_receipt_boxes():
    # Synthetic receipt from the Day-0 Glimmer test: net 32.06, VAT 6.41, total 38.47
    ev = purchase(3206, 641, date(2026, 9, 21))
    ret = compute_vat_return([ev], "26A3", date(2026, 7, 1), date(2026, 9, 30))
    assert str(ret.vat_reclaimed) == "6.41"
    assert ret.total_purchases_ex_vat == 32  # whole pounds, rounded down
    assert str(ret.net_vat_due) == "6.41"  # absolute value of (0 - 6.41)
    assert ret.event_ids == [ev.id]


def test_net_due_and_rounding():
    evs = [sale(3_190_000, 638_000, date(2026, 8, 15)), purchase(2_285_050, 424_000, date(2026, 9, 2))]
    ret = compute_vat_return(evs, "26A3", date(2026, 7, 1), date(2026, 9, 30))
    assert str(ret.vat_due_sales) == "6380.00"
    assert str(ret.total_vat_due) == "6380.00"
    assert str(ret.vat_reclaimed) == "4240.00"
    assert str(ret.net_vat_due) == "2140.00"
    assert ret.total_sales_ex_vat == 31900
    assert ret.total_purchases_ex_vat == 22850  # 22850.50 -> 22850
    body = ret.to_hmrc()
    assert body["netVatDue"] == 2140.0 and body["totalValuePurchasesExVAT"] == 22850
    assert set(body) == {
        "periodKey", "vatDueSales", "vatDueAcquisitions", "totalVatDue", "vatReclaimedCurrPeriod",
        "netVatDue", "totalValueSalesExVAT", "totalValuePurchasesExVAT",
        "totalValueGoodsSuppliedExVAT", "totalAcquisitionsExVAT", "finalised",
    }


def test_outside_period_and_no_vat_receipt():
    outside = purchase(1000, 200, date(2026, 10, 1))
    parking = purchase(400, 0, date(2026, 9, 9), code=VatCode.NO_VAT)
    ret = compute_vat_return([outside, parking], "26A3", date(2026, 7, 1), date(2026, 9, 30))
    assert ret.event_ids == [parking.id]
    assert str(ret.vat_reclaimed) == "0.00" and ret.total_purchases_ex_vat == 4
