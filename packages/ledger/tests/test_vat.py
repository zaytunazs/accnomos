from datetime import UTC, date, datetime

import pytest

from accnomos_ledger import LedgerEvent, Line, VatCode, compute_vat_return, vat_side

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
        "periodKey",
        "vatDueSales",
        "vatDueAcquisitions",
        "totalVatDue",
        "vatReclaimedCurrPeriod",
        "netVatDue",
        "totalValueSalesExVAT",
        "totalValuePurchasesExVAT",
        "totalValueGoodsSuppliedExVAT",
        "totalAcquisitionsExVAT",
        "finalised",
    }


def reversal(ev: LedgerEvent) -> LedgerEvent:
    """As the runtime undoes an entry (app/approve.py reversal_of): every line on the other side."""
    return LedgerEvent(
        kind="reversal",
        date=ev.date,
        net=ev.net,
        vat=ev.vat,
        reverses=ev.id,
        lines=[Line(account=ln.account, debit=ln.credit, credit=ln.debit, vat_code=ln.vat_code) for ln in ev.lines],
        **APPROVED,
    )


def test_reversed_sale_and_purchase_net_to_nothing():
    s, p = sale(10_000, 2_000, date(2026, 8, 1)), purchase(5_000, 1_000, date(2026, 8, 2))
    ret = compute_vat_return([s, reversal(s), p, reversal(p)], "26A3", date(2026, 7, 1), date(2026, 9, 30))
    assert str(ret.vat_due_sales) == "0.00" and str(ret.vat_reclaimed) == "0.00"
    assert ret.total_sales_ex_vat == 0 and ret.total_purchases_ex_vat == 0


def test_outside_period_and_no_vat_receipt():
    outside = purchase(1000, 200, date(2026, 10, 1))
    parking = purchase(400, 0, date(2026, 9, 9), code=VatCode.NO_VAT)
    ret = compute_vat_return([outside, parking], "26A3", date(2026, 7, 1), date(2026, 9, 30))
    assert ret.event_ids == [parking.id]
    assert str(ret.vat_reclaimed) == "0.00" and ret.total_purchases_ex_vat == 4


def test_undone_sale_nets_off_sales_and_undone_purchase_nets_off_purchases():
    s, p = sale(10000, 2000, date(2026, 9, 1)), purchase(5000, 1000, date(2026, 9, 2))
    ret = compute_vat_return([s, reversal(s), p], "26A3", date(2026, 7, 1), date(2026, 9, 30))
    assert str(ret.vat_due_sales) == "0.00" and ret.total_sales_ex_vat == 0
    assert str(ret.vat_reclaimed) == "10.00" and ret.total_purchases_ex_vat == 50
    ret = compute_vat_return([s, p, reversal(p)], "26A3", date(2026, 7, 1), date(2026, 9, 30))
    assert str(ret.vat_due_sales) == "20.00" and str(ret.vat_reclaimed) == "0.00"


def _cn_event(kind: str, lines: list[Line], net: int, vat: int, **kw: object) -> LedgerEvent:
    return LedgerEvent(
        kind=kind,  # type: ignore[arg-type]
        date=date(2026, 10, 2),
        lines=lines,
        approved_by="sam@example.co.uk",
        approved_at=datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
        net=net,
        vat=vat,
        **kw,  # type: ignore[arg-type]
    )


def test_credit_notes_and_their_undo_count_on_the_right_side_with_the_right_sign():
    sales_cn = _cn_event(
        "reversal",
        [
            Line(account="4000 Sales", debit=9000, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=1800, vat_code=VatCode.STANDARD),
            Line(account="1100 Debtors", credit=10800),
        ],
        9000,
        1800,
        credits="a" * 32,
    )
    undo_sales_cn = _cn_event(
        "reversal",
        [Line(account=ln.account, debit=ln.credit, credit=ln.debit, vat_code=ln.vat_code) for ln in sales_cn.lines],
        9000,
        1800,
        reverses=sales_cn.id,
    )
    supplier_cn = _cn_event(
        "reversal",
        [
            Line(account="2100 Creditors", debit=6000),
            Line(account="5000 Materials", credit=5000, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", credit=1000, vat_code=VatCode.STANDARD),
        ],
        5000,
        1000,
    )
    undo_supplier_cn = _cn_event(
        "reversal",
        [Line(account=ln.account, debit=ln.credit, credit=ln.debit, vat_code=ln.vat_code) for ln in supplier_cn.lines],
        5000,
        1000,
        reverses=supplier_cn.id,
    )
    assert sales_cn.is_credit_note and supplier_cn.is_credit_note and not undo_sales_cn.is_credit_note
    assert [vat_side(e) for e in (sales_cn, undo_sales_cn, supplier_cn, undo_supplier_cn)] == [
        ("sales", -1),
        ("sales", 1),
        ("purchases", -1),
        ("purchases", 1),
    ]
    payment = _cn_event("bank", [Line(account="1200 Bank", debit=100), Line(account="1100 Debtors", credit=100)], 0, 0)
    assert vat_side(payment) is None
    start, end = date(2026, 10, 1), date(2026, 12, 31)
    ret = compute_vat_return([sales_cn, supplier_cn], "x", start, end)
    assert (str(ret.vat_due_sales), str(ret.vat_reclaimed), ret.total_sales_ex_vat) == ("-18.00", "-10.00", -90)
    ret = compute_vat_return([sales_cn, undo_sales_cn, supplier_cn, undo_supplier_cn], "x", start, end)
    assert (str(ret.vat_due_sales), str(ret.vat_reclaimed)) == ("0.00", "0.00")


def test_undoing_a_vat_only_sale_nets_off_box_1_not_box_4():
    """Found by the property tests: a VAT-only sales invoice (net £0.00, so no Sales line is posted) was undone
    into box 4, because the undo had no Sales line to say it was on the sales side."""
    vat_only = LedgerEvent(
        kind="sale",
        date=date(2026, 9, 1),
        net=0,
        vat=1,
        lines=[Line(account="1100 Debtors", debit=1), Line(account="2200 VAT control", credit=1, vat_code="S")],
        **APPROVED,
    )
    undo = LedgerEvent(
        kind="reversal",
        date=date(2026, 9, 1),
        net=0,
        vat=1,
        reverses=vat_only.id,
        lines=[Line(account="1100 Debtors", credit=1), Line(account="2200 VAT control", debit=1, vat_code="S")],
        **APPROVED,
    )
    assert vat_side(undo) == ("sales", -1)
    ret = compute_vat_return([vat_only, undo], "x", date(2026, 7, 1), date(2026, 9, 30))
    assert (str(ret.vat_due_sales), str(ret.vat_reclaimed), str(ret.net_vat_due)) == ("0.00", "0.00", "0.00")


def test_vat_adjustments_count_on_their_side_with_their_signed_figures():
    """A manual journal or a VAT recode is an adjustment with `vat_box`: its signed net and VAT go in the boxes."""
    day = date(2026, 8, 10)
    bill = purchase(10_000, 2_000, day)
    recode = LedgerEvent(  # the bill was zero rated after all: keep the gross, take the VAT back out of box 4
        kind="adjustment",
        date=day,
        vat_box="purchases",
        net=2_000,
        vat=-2_000,
        lines=[
            Line(account="5100 Tools", credit=10_000, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", credit=2_000, vat_code=VatCode.STANDARD),
            Line(account="5100 Tools", debit=12_000, vat_code=VatCode.ZERO),
        ],
        **APPROVED,
    )
    plain = LedgerEvent(  # no vat_box: never on the return
        kind="adjustment",
        date=day,
        lines=[
            Line(account="8000 Depreciation", debit=500),
            Line(account="0031 Office equipment depreciation", credit=500),
        ],
        **APPROVED,
    )
    r = compute_vat_return([bill, recode, plain], "26Q3", date(2026, 7, 1), date(2026, 9, 30))
    assert r.vat_reclaimed == 0
    assert r.total_purchases_ex_vat == 120
    assert plain.id not in r.event_ids and recode.id in r.event_ids
