"""VAT schemes against HMRC's worked examples (Notices 733, 731 and 732, read on gov.uk 28 Oct 2026)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from accnomos_ledger import LedgerEvent, Line, VatCode, compute_vat_return
from accnomos_ledger.vat_schemes import (
    AnnualAccounting,
    DocPayment,
    FlatRate,
    SchemeBooks,
    SchemeSpan,
    annual_period_containing,
    annual_periods,
    annual_return_due,
    balancing_payment,
    compute_scheme_return,
    instalment_amount,
    instalment_schedule,
    is_limited_cost,
    limited_cost_cap,
    sector_rate,
    validate_spans,
)

APPROVED = dict(approved_by="owner@example.test", approved_at=datetime(2026, 10, 21, 18, 0))
Q1 = (date(2026, 1, 1), date(2026, 3, 31))
Q2 = (date(2026, 4, 1), date(2026, 6, 30))
Q3 = (date(2026, 7, 1), date(2026, 9, 30))


def sale(net: int, vat: int, day: date, *, zero: int = 0, code: VatCode = VatCode.STANDARD, eid: str | None = None):
    lines = [Line(account="1100 Debtors", debit=net + zero + vat)]
    if net:
        lines.append(Line(account="4000 Sales", credit=net, vat_code=code))
    if zero:
        lines.append(Line(account="4000 Sales", credit=zero, vat_code=VatCode.ZERO))
    if vat:
        lines.append(Line(account="2200 VAT control", credit=vat))
    return LedgerEvent(
        kind="sale", date=day, net=net + zero, vat=vat, lines=lines, **({"id": eid} if eid else {}), **APPROVED
    )


def purchase(net: int, vat: int, day: date, account: str = "5000 Materials", eid: str | None = None, paid=False):
    return LedgerEvent(
        kind="purchase",
        date=day,
        net=net,
        vat=vat,
        lines=[
            Line(account=account, debit=net, vat_code=VatCode.STANDARD),
            *([Line(account="2200 VAT control", debit=vat)] if vat else []),
            Line(account="1200 Bank" if paid else "2100 Creditors", credit=net + vat),
        ],
        **({"id": eid} if eid else {}),
        **APPROVED,
    )


def credit_note(of: LedgerEvent, net: int, vat: int, day: date) -> LedgerEvent:
    return LedgerEvent(
        kind="reversal",
        date=day,
        net=net,
        vat=vat,
        credits=of.id,
        lines=[
            Line(account="4000 Sales", debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=vat),
            Line(account="1100 Debtors", credit=net + vat),
        ],
        **APPROVED,
    )


def undo(ev: LedgerEvent, day: date) -> LedgerEvent:
    return LedgerEvent(
        kind="reversal",
        date=day,
        net=ev.net,
        vat=ev.vat,
        reverses=ev.id,
        lines=[Line(account=ln.account, debit=ln.credit, credit=ln.debit, vat_code=ln.vat_code) for ln in ev.lines],
        **APPROVED,
    )


def frs(sector="Photography", start=date(2025, 1, 1), end=None, **kw) -> SchemeSpan:
    return SchemeSpan(start, end, "flat_rate", FlatRate(sector, **kw))


def boxes(books: SchemeBooks, spans, period=Q1):
    out = compute_scheme_return(books, spans, "26A1", *period)
    return out, out.ret.to_hmrc()


# --- no scheme: identical to the standard engine ------------------------------------------------------------------


def test_no_scheme_matches_standard_engine():
    s1, p1 = sale(100_000, 20_000, date(2026, 2, 1)), purchase(40_000, 8_000, date(2026, 3, 1))
    events = [s1, p1, credit_note(s1, 10_000, 2_000, date(2026, 3, 5)), undo(p1, date(2026, 3, 20))]
    out, body = boxes(SchemeBooks(events), [])
    assert body == compute_vat_return(events, "26A1", *Q1).to_hmrc()
    assert [s.scheme for s in out.segments] == ["standard"]


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.booleans(), st.integers(0, 5_000_000), st.integers(0, 1_000_000), st.integers(0, 200), st.booleans()
        ),
        max_size=12,
    )
)
def test_property_standard_spans_change_nothing(rows):
    """A timeline of standard spans (or none) gives exactly the boxes compute_vat_return does."""
    events = []
    for is_sale, net, vat, day, undone in rows:
        d = date(2026, 1, 1) + (date(2026, 1, 2) - date(2026, 1, 1)) * day
        if net + vat == 0 or (net == 0 and not is_sale):
            continue  # a purchase line needs a debit (Line refuses a zero line); a VAT-only sale is still built
        ev = sale(net, vat, d) if is_sale else purchase(net, vat, d)
        events.append(ev)
        if undone:
            events.append(undo(ev, d))
    want = compute_vat_return(events, "26A1", *Q1).to_hmrc()
    spans = [
        SchemeSpan(date(2025, 1, 1), date(2026, 2, 14), "standard"),
        SchemeSpan(date(2026, 2, 15), None, "standard"),
    ]
    assert boxes(SchemeBooks(events), [])[1] == want
    assert boxes(SchemeBooks(events), spans)[1] == want


# --- flat rate scheme ---------------------------------------------------------------------------------------------


def test_photographer_example():
    """gov.uk/vat-flat-rate-scheme/how-much-you-pay: £1,000 + 20% VAT = £1,200; photographer 11% → £132."""
    events = [sale(100_000, 20_000, date(2026, 2, 3)), purchase(50_000, 10_000, date(2026, 2, 4))]
    out, body = boxes(SchemeBooks(events, relevant_goods_accounts=("9999",)), [frs(limited_cost="no")])
    assert body["vatDueSales"] == 132.0
    assert body["vatReclaimedCurrPeriod"] == 0.0  # no input tax on the scheme (Notice 733 §2.4)
    assert body["totalValueSalesExVAT"] == 1200  # box 6: the VAT inclusive turnover (Notice 700/12 §4.1)
    assert body["totalValuePurchasesExVAT"] == 0  # box 7: only capital goods claimed in box 4
    assert body["netVatDue"] == 132.0
    seg = out.segments[0]
    assert seg.scheme == "flat_rate" and seg.calcs[0].percent == Decimal("11")


def test_turnover_includes_zero_rated_and_exempt_sales():
    """Notice 733 §6.2 / 700/12 §4.1: standard, reduced, zero-rated and exempt supplies, VAT inclusive."""
    events = [
        sale(10_000, 2_000, date(2026, 1, 5), zero=5_000),
        sale(3_000, 0, date(2026, 1, 6), code=VatCode.EXEMPT),
        sale(9_999, 0, date(2026, 1, 7), code=VatCode.OUT_OF_SCOPE),  # not on the return at all
    ]
    out, body = boxes(SchemeBooks(events), [frs(limited_cost="no")])
    assert out.segments[0].turnover_pence == 20_000
    assert body["vatDueSales"] == 22.0  # 11% of £200


@pytest.mark.parametrize(
    ("turnover", "goods", "limited"),
    [
        (10_000_00, 260_00, False),  # Example 1: over 2% and over £250 → sector rate
        (20_000_00, 325_00, True),  # Example 2: over £250 but under 2% → 16.5%
        (10_000_00, 225_00, True),  # Example 3: over 2% but under £250 → 16.5%
    ],
)
def test_limited_cost_examples(turnover, goods, limited):
    """Notice 733 §4.4 Examples 1-3 (a quarter: the pro rata £1,000 is £250)."""
    assert is_limited_cost(goods, turnover, limited_cost_cap(*Q1)) is limited
    vat = goods // 6  # goods are VAT inclusive: £260 = £216.67 + £43.33
    events = [sale(0, 0, date(2026, 1, 2), zero=turnover), purchase(goods - vat, vat, date(2026, 2, 2))]
    out, body = boxes(SchemeBooks(events), [frs("Photography")])
    seg = out.segments[0]
    assert seg.relevant_goods_pence == goods and seg.limited_cost is limited
    rate = Decimal("16.5") if limited else Decimal("11")
    assert seg.calcs[0].percent == rate
    assert body["vatDueSales"] == float(Decimal(turnover) * rate / 100 / 100)


def test_limited_cost_cap_pro_rata():
    """Notice 733 §4.5: £83 for one month, £166 for two, £250 a quarter; £1,000 a year."""
    assert limited_cost_cap(date(2017, 4, 1), date(2017, 4, 30)) == 83_00
    assert limited_cost_cap(date(2017, 4, 1), date(2017, 5, 31)) == 166_00
    assert limited_cost_cap(*Q1) == 250_00
    assert limited_cost_cap(date(2026, 1, 1), date(2026, 12, 31)) == 1_000_00
    assert limited_cost_cap(date(2026, 2, 15), date(2026, 3, 31)) == 123_00  # 45 days of 365, truncated


def test_services_food_and_motor_are_not_relevant_goods():
    """Notice 733 §4.6: services, food and drink for you or staff, vehicle costs (outside transport) are excluded."""
    events = [
        sale(0, 0, date(2026, 1, 2), zero=10_000_00),
        purchase(50_000, 10_000, date(2026, 1, 3), "7510 Software & subscriptions"),
        purchase(50_000, 10_000, date(2026, 1, 3), "7410 Subsistence"),
        purchase(50_000, 10_000, date(2026, 1, 3), "7300 Motor expenses"),
    ]
    assert boxes(SchemeBooks(events), [frs()])[0].segments[0].relevant_goods_pence == 0
    taxi = frs("Transport or storage, including couriers, freight, removals and taxis")
    assert boxes(SchemeBooks(events), [taxi])[0].segments[0].relevant_goods_pence == 60_000  # fuel for a taxi


def test_first_year_discount_examples():
    """Notice 733 §4.7 Example 1: limited cost 16.5% → 15.5% in the first year of registration; it ends the day
    before the anniversary of *registration*, so a quarter across it gets two calculations (§4.12)."""
    events = [sale(0, 0, date(2026, 1, 10), zero=1_000_00), sale(0, 0, date(2026, 3, 10), zero=1_000_00)]
    books = SchemeBooks(events, registered_on=date(2025, 2, 1))
    out, body = boxes(books, [frs(limited_cost="yes")])
    calcs = out.segments[0].calcs
    assert [(c.start, c.end, c.percent, c.first_year) for c in calcs] == [
        (date(2026, 1, 1), date(2026, 1, 31), Decimal("15.5"), True),
        (date(2026, 2, 1), date(2026, 3, 31), Decimal("16.5"), False),
    ]
    assert body["vatDueSales"] == 155.0 + 165.0
    # Example 3: registered for more than 12 months before joining: no reduction.
    old = boxes(SchemeBooks(events, registered_on=date(2024, 3, 1)), [frs(limited_cost="yes")])[1]
    assert old["vatDueSales"] == 330.0


def test_sector_rate_change_mid_period_two_calculations():
    """Catering went from 12.5% to 4.5% on 15 July 2020: a quarter across it is two calculations (§4.11-4.12)."""
    assert sector_rate("Catering services including restaurants and takeaways", date(2020, 7, 14)) == Decimal("12.5")
    events = [sale(10_000, 2_000, date(2020, 7, 1)), sale(10_000, 2_000, date(2020, 8, 1))]
    q = (date(2020, 7, 1), date(2020, 9, 30))
    out = compute_scheme_return(
        SchemeBooks(events),
        [frs("Catering services including restaurants and takeaways", date(2019, 1, 1), limited_cost="no")],
        "20A3",
        *q,
    )
    assert [(c.percent, c.turnover_pence, c.tax_pence) for c in out.segments[0].calcs] == [
        (Decimal("12.5"), 12_000, 1_500),
        (Decimal("4.5"), 12_000, 540),
    ]
    assert out.ret.to_hmrc()["vatDueSales"] == 20.40


def test_capital_goods_of_2000_or_more_claimed_outside_the_scheme():
    """Notice 733 §15.2: VAT on a single capital purchase of £2,000 or more including VAT goes in box 4 (net in
    box 7, Notice 700/12 §4.1); under £2,000, or not marked as capital, nothing is claimed."""
    van = purchase(500_000, 100_000, date(2026, 2, 1), "5100 Tools & small equipment", eid="van")
    laptop = purchase(150_000, 30_000, date(2026, 2, 1), "5100 Tools & small equipment", eid="laptop")
    unmarked = purchase(300_000, 60_000, date(2026, 2, 1), "5100 Tools & small equipment", eid="unmarked")
    books = SchemeBooks([sale(100_000, 20_000, date(2026, 2, 3)), van, laptop, unmarked], capital={"van", "laptop"})
    out, body = boxes(books, [frs(limited_cost="no")])
    assert body["vatReclaimedCurrPeriod"] == 1000.0
    assert body["totalValuePurchasesExVAT"] == 5000
    assert body["netVatDue"] == abs(132.0 - 1000.0)  # HMRC repays the difference


def test_joining_flat_rate_mid_period_two_calculations():
    """Notice 733 §12.7 / 732 §9.8: one calculation per scheme, added together."""
    events = [sale(100_000, 20_000, date(2026, 1, 20)), purchase(10_000, 2_000, date(2026, 1, 21))]
    events += [sale(100_000, 20_000, date(2026, 3, 1)), purchase(10_000, 2_000, date(2026, 3, 2))]
    spans = [
        SchemeSpan(date(2025, 1, 1), date(2026, 2, 14), "standard"),
        frs(start=date(2026, 2, 15), limited_cost="no"),
    ]
    out, body = boxes(SchemeBooks(events), spans)
    assert [s.scheme for s in out.segments] == ["standard", "flat_rate"]
    assert body["vatDueSales"] == 200.0 + 132.0
    assert body["vatReclaimedCurrPeriod"] == 20.0  # the standard part only
    assert body["totalValueSalesExVAT"] == 1000 + 1200
    assert body["totalValuePurchasesExVAT"] == 100
    assert any("one calculation per scheme" in w for w in out.warnings)


# --- cash accounting ----------------------------------------------------------------------------------------------

CASH = SchemeSpan(date(2025, 1, 1), None, "cash")


def test_part_payment_example_8_1():
    """Notice 731 §8.1: £780 of a £1,200 invoice is 65%, so £130 of the £200 VAT; the £70 follows the rest."""
    inv = sale(100_000, 20_000, date(2026, 1, 10), eid="A")
    books = SchemeBooks([inv], [DocPayment("A", date(2026, 2, 10), 78_000), DocPayment("A", date(2026, 4, 5), 42_000)])
    _, q1 = boxes(books, [CASH])
    assert q1["vatDueSales"] == 130.0 and q1["totalValueSalesExVAT"] == 650
    _, q2 = boxes(books, [CASH], Q2)
    assert q2["vatDueSales"] == 70.0 and q2["totalValueSalesExVAT"] == 350


def test_one_payment_two_invoices_example_8_2():
    """Notice 731 §8.2: £2,730 against invoices B (£1,200) and C (£3,400, with zero-rated goods): £380 of VAT."""
    b = sale(100_000, 20_000, date(2026, 1, 5), eid="B")
    c = sale(200_000, 40_000, date(2026, 1, 6), zero=100_000, eid="C")
    pays = [DocPayment("B", date(2026, 2, 1), 120_000), DocPayment("C", date(2026, 2, 1), 153_000)]
    _, body = boxes(SchemeBooks([b, c], pays), [CASH])
    assert body["vatDueSales"] == 380.0
    assert body["totalValueSalesExVAT"] == 1000 + 1350  # 45% of C's £3,000 net


def test_purchases_reclaimed_when_paid_and_cash_sales_on_their_date():
    """Notice 731 §4.5: input tax is reclaimed in the period you pay; a document paid at the time is paid that day."""
    bill = purchase(50_000, 10_000, date(2026, 3, 20), eid="bill")
    receipt = purchase(5_000, 1_000, date(2026, 3, 21), paid=True, eid="card")
    books = SchemeBooks([bill, receipt], [DocPayment("bill", date(2026, 4, 2), 60_000)], on_account={"bill"})
    assert boxes(books, [CASH])[1]["vatReclaimedCurrPeriod"] == 10.0
    assert boxes(books, [CASH], Q2)[1]["vatReclaimedCurrPeriod"] == 100.0


def test_joining_cash_accounting_never_counts_vat_twice():
    """Notice 731 §3.1: payments for invoices already accounted for under normal accounting are left out."""
    before = sale(100_000, 20_000, date(2026, 3, 15), eid="old")
    after = sale(50_000, 10_000, date(2026, 4, 15), eid="new")
    pays = [DocPayment("old", date(2026, 4, 20), 120_000), DocPayment("new", date(2026, 5, 20), 60_000)]
    spans = [SchemeSpan(date(2026, 4, 1), None, "cash")]
    books = SchemeBooks([before, after], pays)
    assert boxes(books, spans)[1]["vatDueSales"] == 200.0  # Q1, invoice basis
    assert boxes(books, spans, Q2)[1]["vatDueSales"] == 100.0  # Q2: only the invoice made on the scheme


def test_leaving_cash_accounting_brings_unpaid_vat_to_account():
    """Notice 731 §6.4: unpaid VAT is accounted for in the period you stop using the scheme, or (the 6-month option)
    as it is paid over the next 6 months with what is left at the end of them."""
    inv = sale(100_000, 20_000, date(2026, 2, 1), eid="X")
    pays = [DocPayment("X", date(2026, 5, 1), 60_000), DocPayment("X", date(2026, 11, 1), 60_000)]
    books = SchemeBooks([inv], pays)
    now = [SchemeSpan(date(2025, 1, 1), date(2026, 3, 31), "cash")]
    out, q1 = boxes(books, now)
    assert q1["vatDueSales"] == 200.0 and out.segments[0].exit_vat == 20_000
    assert boxes(books, now, Q2)[1]["vatDueSales"] == 0.0  # not counted again when paid
    later = [SchemeSpan(date(2025, 1, 1), date(2026, 3, 31), "cash", cash_exit="six_months")]
    assert boxes(books, later)[1]["vatDueSales"] == 0.0
    assert boxes(books, later, Q2)[1]["vatDueSales"] == 100.0  # paid 1 May, within the 6 months
    assert boxes(books, later, Q3)[1]["vatDueSales"] == 100.0  # the rest at 30 Sep, the end of the 6 months


def test_credit_note_reduces_a_cash_invoice_and_an_undo_cancels_it():
    inv = sale(100_000, 20_000, date(2026, 1, 10), eid="I")
    cn = credit_note(inv, 50_000, 10_000, date(2026, 1, 20))
    books = SchemeBooks([inv, cn], [DocPayment("I", date(2026, 2, 1), 60_000)])
    assert boxes(books, [CASH])[1]["vatDueSales"] == 100.0  # £600 pays the whole £600 left
    gone = sale(100_000, 20_000, date(2026, 1, 11), eid="G")
    assert boxes(SchemeBooks([gone, undo(gone, date(2026, 1, 12))]), [CASH])[1]["vatDueSales"] == 0.0


def test_long_credit_terms_are_outside_cash_accounting():
    """Notice 731 §2.7: an invoice not due in full within 6 months uses the normal rules."""
    inv = sale(100_000, 20_000, date(2026, 1, 10), eid="L")
    out, body = boxes(SchemeBooks([inv], due={"L": date(2026, 9, 1)}), [CASH])
    assert body["vatDueSales"] == 200.0
    assert any("not due within 6 months" in w for w in out.warnings)


def test_flat_rate_cash_turnover_and_moving_from_cash_accounting():
    """Notice 733 §9.1: the cash based method taxes what you are paid; §9.3: coming from cash accounting, money
    received on the flat rate scheme for earlier invoices goes into flat rate turnover; §9.6: leaving the cash
    based method, unpaid supplies are brought into turnover in the period you stop."""
    earlier = sale(100_000, 20_000, date(2026, 3, 1), eid="E")  # made under cash accounting
    later = sale(100_000, 20_000, date(2026, 4, 10), eid="F")  # made on the flat rate, cash based
    pays = [DocPayment("E", date(2026, 4, 20), 120_000), DocPayment("F", date(2026, 7, 3), 120_000)]
    spans = [
        SchemeSpan(date(2025, 1, 1), date(2026, 3, 31), "cash"),
        frs(start=date(2026, 4, 1), end=date(2026, 6, 30), turnover_method="cash", limited_cost="no"),
    ]
    books = SchemeBooks([earlier, later], pays)
    assert boxes(books, spans)[1]["vatDueSales"] == 0.0
    q2 = boxes(books, spans, Q2)[0]
    assert q2.segments[0].turnover_pence == 240_000  # E paid on the scheme, F unpaid when the method stopped
    assert q2.ret.to_hmrc()["vatDueSales"] == 264.0
    assert boxes(books, spans, Q3)[1]["vatDueSales"] == 0.0


def test_overlapping_spans_rejected():
    with pytest.raises(ValueError, match="overlap"):
        validate_spans([CASH, frs(start=date(2026, 1, 1))])
    with pytest.raises(ValueError, match="business types"):
        validate_spans([SchemeSpan(date(2026, 1, 1), None, "flat_rate", FlatRate("Wizardry"))])


# --- annual accounting --------------------------------------------------------------------------------------------


def test_instalments_example():
    """Notice 732 §4.5: last year £10,000 → 9 monthly instalments of £1,000, or 3 quarterly of £2,500."""
    year = (date(2026, 1, 1), date(2026, 12, 31))
    monthly = instalment_schedule(*year, 10_000_00, "monthly")
    assert [i.amount_pence for i in monthly] == [1_000_00] * 9
    assert [i.due for i in monthly][:2] == [date(2026, 4, 30), date(2026, 5, 31)]  # end of months 4..12
    assert monthly[-1].due == date(2026, 12, 31)
    quarterly = instalment_schedule(*year, 10_000_00, "quarterly")
    assert [(i.due, i.amount_pence) for i in quarterly] == [
        (date(2026, 4, 30), 2_500_00),
        (date(2026, 7, 31), 2_500_00),
        (date(2026, 10, 31), 2_500_00),
    ]


def test_instalments_round_down_to_5_and_short_periods():
    assert instalment_amount(12_345_00, "monthly") == 1_230_00  # £1,234.50 → £1,230 (VATAAS4100)
    assert instalment_schedule(date(2026, 1, 1), date(2026, 3, 31), 10_000_00, "monthly") == []  # under 4 months
    six = instalment_schedule(date(2026, 7, 1), date(2026, 12, 31), 10_000_00, "monthly")
    assert [i.due for i in six] == [date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31)]
    assert instalment_schedule(*Q1, None, "monthly") == []


def test_balancing_payment_example():
    """Notice 732 §6.2: 9 × £3,000 paid, £32,000 for the year → £5,000 with the return."""
    paid = instalment_schedule(date(2026, 1, 1), date(2026, 12, 31), 30_000_00, "monthly")
    assert balancing_payment(32_000_00, paid) == 5_000_00
    assert balancing_payment(20_000_00, paid) == -7_000_00  # refunded


def test_annual_return_due_and_periods():
    """Notice 732 §3.3-3.6: periods end on a month end ≤ 12 months on; return due 2 months after (1 if < 4)."""
    assert annual_return_due(date(2026, 1, 1), date(2026, 12, 31)) == date(2027, 2, 28)
    assert annual_return_due(date(2026, 5, 1), date(2027, 4, 30)) == date(2027, 6, 30)
    assert annual_return_due(date(2026, 10, 1), date(2026, 12, 31)) == date(2027, 1, 31)
    # §3.4 example: joined in the quarter from 1 July, asked for a 31 December year end.
    aas = AnnualAccounting(date(2026, 7, 1), first_year_end=date(2026, 12, 31))
    assert annual_periods(aas, date(2027, 3, 1)) == [
        (date(2026, 7, 1), date(2026, 12, 31)),
        (date(2027, 1, 1), date(2027, 12, 31)),
    ]
    assert annual_period_containing(aas, date(2026, 6, 30)) is None
    with pytest.raises(ValueError, match="12 months"):
        annual_periods(AnnualAccounting(date(2026, 7, 1), first_year_end=date(2027, 12, 31)), date(2027, 1, 1))
    left = AnnualAccounting(date(2025, 1, 1), end=date(2026, 6, 30))
    assert annual_periods(left, date(2027, 1, 1)) == [
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 6, 30)),
    ]


def test_annual_return_boxes_are_the_normal_ones_for_the_year():
    """Notice 700/12 §4.3: fill every box in the normal way for the year; box 5 ignores the instalments."""
    events = [sale(100_000, 20_000, date(2026, m, 5)) for m in range(1, 13)]
    out = compute_scheme_return(SchemeBooks(events), [], "26Y1", date(2026, 1, 1), date(2026, 12, 31))
    assert out.ret.to_hmrc()["netVatDue"] == 2400.0
