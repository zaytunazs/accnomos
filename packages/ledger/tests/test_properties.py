"""Property-based tests for the ledger's money maths (Hypothesis).

Inputs are built with the real Pydantic models (LedgerEvent, Line, BankLine) and checked through the real
functions (compute_vat_return, parse_amount, parse_bank_csv, suggest_matches, reconciled_to). Every figure is
integer pence; the only Decimals are the VAT boxes 1-5 that HMRC wants in pounds to 2 dp.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from accnomos_ledger import LedgerEvent, Line, VatCode, compute_vat_return
from accnomos_ledger.bank import BankLine, parse_amount, parse_bank_csv, reconciled_to
from accnomos_ledger.matching import PENNY, settlement_pence, suggest_matches

APPROVED = {"approved_by": "owner@example.test", "approved_at": datetime(2026, 10, 21, 18, 0)}
PERIOD = (date(2026, 7, 1), date(2026, 9, 30))
ON_RETURN_CODES = [VatCode.STANDARD, VatCode.REDUCED, VatCode.ZERO, VatCode.EXEMPT, VatCode.NO_VAT]

pence = st.integers(min_value=1, max_value=50_000_000)  # 1p to £500k
days = st.dates(min_value=date(2026, 5, 1), max_value=date(2026, 11, 30))


# --------------------------------------------------------------------------- #
# Strategies: real events
# --------------------------------------------------------------------------- #


@st.composite
def split(draw: st.DrawFn, total: int, max_parts: int = 4) -> list[int]:
    """`total` pence split into 1..max_parts positive parts."""
    n = draw(st.integers(1, min(max_parts, total)))
    cuts = draw(st.lists(st.integers(1, total - 1), min_size=n - 1, max_size=n - 1, unique=True)) if n > 1 else []
    cuts.sort()
    bounds = [0, *cuts, total]
    return [b - a for a, b in zip(bounds, bounds[1:], strict=False)]


@st.composite
def balanced_lines(draw: st.DrawFn) -> list[Line]:
    total = draw(pence)
    debits = draw(split(total))
    credits = draw(split(total))
    accounts = st.sampled_from(["1200 Bank", "1100 Debtors", "2100 Creditors", "4000 Sales", "5000 Materials"])
    return [Line(account=draw(accounts), debit=d) for d in debits] + [
        Line(account=draw(accounts), credit=c) for c in credits
    ]


@st.composite
def sale(draw: st.DrawFn, day: date | None = None) -> LedgerEvent:
    net, vat = draw(pence), draw(st.integers(0, 10_000_000))
    code = draw(st.sampled_from(ON_RETURN_CODES))
    return LedgerEvent(
        kind="sale",
        date=day or draw(days),
        net=net,
        vat=vat,
        lines=[
            Line(account="1100 Debtors", debit=net + vat),
            Line(account="4000 Sales", credit=net, vat_code=code),
            *([Line(account="2200 VAT control", credit=vat, vat_code=code)] if vat else []),
        ],
        counterparty="Acme Kitchens Ltd",
        **APPROVED,
    )


@st.composite
def purchase(draw: st.DrawFn) -> LedgerEvent:
    net, vat = draw(pence), draw(st.integers(0, 10_000_000))
    code = draw(st.sampled_from(ON_RETURN_CODES))
    settle = draw(st.sampled_from(["1200 Bank", "2100 Creditors", "1210 Cash"]))
    return LedgerEvent(
        kind="purchase",
        date=draw(days),
        net=net,
        vat=vat,
        lines=[
            Line(account="5000 Materials", debit=net, vat_code=code),
            *([Line(account="2200 VAT control", debit=vat, vat_code=code)] if vat else []),
            Line(account=settle, credit=net + vat),
        ],
        counterparty="Howdens Joinery",
        **APPROVED,
    )


def turned_round(ev: LedgerEvent, **update: object) -> LedgerEvent:
    """`ev` with every line on the other side: the shape of an undo or a credit note (app/approve.reversal_of)."""
    lines = [Line(account=ln.account, debit=ln.credit, credit=ln.debit, vat_code=ln.vat_code) for ln in ev.lines]
    return LedgerEvent.model_validate(
        {**ev.model_dump(), "id": ev.id + "r", "kind": "reversal", "lines": lines, "reverses": ev.id, **update}
    )


# --------------------------------------------------------------------------- #
# Every event balances, in whole pence
# --------------------------------------------------------------------------- #


@given(balanced_lines())
def test_any_balanced_set_of_lines_is_a_valid_event_and_stays_integer_pence(lines: list[Line]):
    ev = LedgerEvent(kind="adjustment", date=date(2026, 9, 1), lines=lines, **APPROVED)
    assert sum(ln.debit for ln in ev.lines) == sum(ln.credit for ln in ev.lines)
    for ln in ev.lines:
        assert type(ln.debit) is int and type(ln.credit) is int
    # The JSON stored in the user's folder reads back to the same event, still in integer pence
    back = LedgerEvent.model_validate_json(ev.model_dump_json())
    assert back == ev
    assert all(type(ln.debit) is int and type(ln.credit) is int for ln in back.lines)


@given(balanced_lines(), st.integers(-1_000, 1_000).filter(bool))
def test_any_imbalance_is_refused(lines: list[Line], off: int):
    first = lines[0]
    nudged = first.debit + off
    assume(nudged > 0)
    lines = [first.model_copy(update={"debit": nudged}), *lines[1:]]
    with pytest.raises(ValidationError, match="unbalanced"):
        LedgerEvent(kind="adjustment", date=date(2026, 9, 1), lines=lines, **APPROVED)


@given(pence, st.sampled_from([0.5, 0.25, 0.1, 0.01, 0.999]))
def test_fractional_pence_are_refused(amount: int, fraction: float):
    with pytest.raises(ValidationError):
        Line(account="1200 Bank", debit=amount + fraction)  # type: ignore[arg-type]


@given(st.one_of(sale(), purchase()))
def test_an_event_and_its_reversal_put_every_account_back_to_zero(ev: LedgerEvent):
    back = turned_round(ev)
    balances: dict[str, int] = {}
    for e in (ev, back):
        for ln in e.lines:
            balances[ln.account] = balances.get(ln.account, 0) + ln.debit - ln.credit
    assert set(balances.values()) == {0}


# --------------------------------------------------------------------------- #
# VAT 9-box
# --------------------------------------------------------------------------- #


def _whole_pounds_towards_zero(p: int) -> int:
    return int(Decimal(p) / 100)  # int() truncates towards zero, like ROUND_DOWN


@given(st.lists(st.one_of(sale(), purchase()), max_size=25), st.booleans())
def test_nine_box_identities_hold_and_match_the_events_in_the_period(events: list[LedgerEvent], with_credits: bool):
    if with_credits:  # credit notes against some of them, dated in the period
        events += [turned_round(e, reverses=None, date=date(2026, 8, 15)) for e in events[::3]]
    ret = compute_vat_return(events, "26C3", *PERIOD)

    # Box 3 = box 1 + box 2; box 5 = |box 3 - box 4|; boxes 1-5 to the penny
    assert ret.total_vat_due == ret.vat_due_sales + ret.vat_due_acquisitions
    assert ret.net_vat_due == abs(ret.total_vat_due - ret.vat_reclaimed) >= 0
    for box in (ret.vat_due_sales, ret.vat_due_acquisitions, ret.total_vat_due, ret.vat_reclaimed, ret.net_vat_due):
        assert box == box.quantize(Decimal("0.01"))
    # Boxes 6-9 whole pounds
    for box in (ret.total_sales_ex_vat, ret.total_purchases_ex_vat, ret.goods_supplied_ni_eu, ret.acquisitions_ni_eu):
        assert type(box) is int

    # ...and consistent with the events dated in the period, worked out here from the events alone
    inside = [e for e in events if PERIOD[0] <= e.date <= PERIOD[1]]
    sales = [e for e in inside if e.kind == "sale" or (e.kind == "reversal" and "4000 Sales" in _debited(e))]
    buys = [e for e in inside if e not in sales]
    sign = {"sale": 1, "purchase": 1, "reversal": -1}
    assert ret.vat_due_sales == Decimal(sum(sign[e.kind] * (e.vat or 0) for e in sales)) / 100
    assert ret.vat_reclaimed == Decimal(sum(sign[e.kind] * (e.vat or 0) for e in buys)) / 100
    assert ret.total_sales_ex_vat == _whole_pounds_towards_zero(sum(sign[e.kind] * (e.net or 0) for e in sales))
    assert ret.total_purchases_ex_vat == _whole_pounds_towards_zero(sum(sign[e.kind] * (e.net or 0) for e in buys))
    assert sorted(ret.event_ids) == sorted(e.id for e in inside)


def _debited(e: LedgerEvent) -> set[str]:
    return {ln.account for ln in e.lines if ln.debit}


@given(st.lists(st.one_of(sale(), purchase()), min_size=1, max_size=15))
def test_undoing_everything_empties_every_box(events: list[LedgerEvent]):
    ret = compute_vat_return(events + [turned_round(e) for e in events], "26C3", *PERIOD)
    assert ret.vat_due_sales == ret.vat_reclaimed == ret.net_vat_due == Decimal("0")
    assert ret.total_sales_ex_vat == ret.total_purchases_ex_vat == 0


@given(st.lists(st.one_of(sale(), purchase()), max_size=15))
def test_the_hmrc_body_carries_the_boxes_exactly(events: list[LedgerEvent]):
    ret = compute_vat_return(events, "26C3", *PERIOD)
    body = ret.to_hmrc()
    # HMRC's JSON numbers are floats; each must read back to the same 2 dp Decimal (no binary drift)
    for key, box in [
        ("vatDueSales", ret.vat_due_sales),
        ("vatDueAcquisitions", ret.vat_due_acquisitions),
        ("totalVatDue", ret.total_vat_due),
        ("vatReclaimedCurrPeriod", ret.vat_reclaimed),
        ("netVatDue", ret.net_vat_due),
    ]:
        assert Decimal(repr(body[key])).quantize(Decimal("0.01")) == box
    assert body["totalVatDue"] == pytest.approx(body["vatDueSales"] + body["vatDueAcquisitions"], abs=0.001)
    for key in ("totalValueSalesExVAT", "totalValuePurchasesExVAT", "totalValueGoodsSuppliedExVAT"):
        assert type(body[key]) is int


@given(st.lists(st.one_of(sale(), purchase()), max_size=20), days)
def test_adjacent_periods_split_the_events_between_them(events: list[LedgerEvent], cut: date):
    """Two back-to-back periods together hold what one period spanning both holds (pence never lost at a cut)."""
    start, end = date(2026, 5, 1), date(2026, 11, 30)
    a = compute_vat_return(events, "a", start, cut - timedelta(days=1))
    b = compute_vat_return(events, "b", cut, end)
    whole = compute_vat_return(events, "w", start, end)
    assert a.vat_due_sales + b.vat_due_sales == whole.vat_due_sales
    assert a.vat_reclaimed + b.vat_reclaimed == whole.vat_reclaimed
    assert sorted(a.event_ids + b.event_ids) == sorted(whole.event_ids)


# --------------------------------------------------------------------------- #
# Bank statements: amounts and ids
# --------------------------------------------------------------------------- #


def _pounds_text(p: int) -> str:
    pounds, pennies = divmod(abs(p), 100)
    return f"{pounds:,}.{pennies:02d}"


@given(st.integers(-10_000_000_000, 10_000_000_000))
def test_every_way_banks_print_an_amount_reads_back_to_the_same_pence(p: int):
    body = _pounds_text(p)
    signed = [f"-{body}", f"(£{body})", f"{body} DR", f"-£{body}"] if p < 0 else [body, f"£{body}", f"{body}CR"]
    for text in [*signed, f" {signed[0]} "]:
        assert parse_amount(text) == p, text
    assert parse_amount(body.replace(",", "")) == abs(p)


ROWS = st.lists(
    st.tuples(
        st.dates(min_value=date(2024, 1, 1), max_value=date(2027, 12, 31)),
        st.integers(-5_000_000, 5_000_000).filter(bool),
        st.sampled_from(["SCREWFIX", "TOOLSTATION 1234", "HMRC VAT", "ACME KITCHENS", "TFR TO SAVINGS"]),
    ),
    min_size=1,
    max_size=30,
)


@given(ROWS)
def test_a_tide_style_export_reads_back_line_for_line_with_unique_ids(rows: list[tuple[date, int, str]]):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date", "Transaction ID", "Transaction Type", "Name/Description", "Reference", "Paid in", "Paid out"])
    for n, (d, p, desc) in enumerate(rows):
        paid_in, paid_out = (_pounds_text(p), "") if p > 0 else ("", _pounds_text(p))
        w.writerow([d.strftime("%d/%m/%Y"), f"T{n}", "Card", desc, "", paid_in, paid_out])
    lines = parse_bank_csv(out.getvalue().encode(), "tide.csv")
    assert [(ln.date, ln.amount_pence, ln.description) for ln in lines] == rows
    assert len({ln.id for ln in lines}) == len(lines)  # repeated rows are still separate payments


# --------------------------------------------------------------------------- #
# Bank matching: one line, one match; one event, one line
# --------------------------------------------------------------------------- #

NAMES = ["Screwfix", "Toolstation", "Acme Kitchens Ltd", "Howdens Joinery"]


@st.composite
def bank_case(draw: st.DrawFn) -> tuple[list[BankLine], list[LedgerEvent]]:
    base = date(2026, 9, 1)
    amounts = st.sampled_from([1000, 1001, 2400, 4999, 5000, 12000])  # few distinct amounts: many collisions
    events: list[LedgerEvent] = []
    for i in range(draw(st.integers(0, 10))):
        gross = draw(amounts)
        who = draw(st.sampled_from(NAMES))
        when = base + timedelta(days=draw(st.integers(0, 6)))
        if draw(st.booleans()):  # a purchase paid from the bank or on account
            acct = draw(st.sampled_from(["1200 Bank", "2100 Creditors"]))
            lines = [Line(account="5000 Materials", debit=gross), Line(account=acct, credit=gross)]
            kind = "purchase"
        else:  # a sale on account
            lines = [Line(account="1100 Debtors", debit=gross), Line(account="4000 Sales", credit=gross)]
            kind = "sale"
        events.append(
            LedgerEvent(id=f"e{i:02d}", kind=kind, date=when, lines=lines, counterparty=who, net=gross, **APPROVED)
        )
    lines: list[BankLine] = []
    for i in range(draw(st.integers(0, 10))):
        amount = draw(amounts) * draw(st.sampled_from([1, -1, 2, -2])) + draw(st.sampled_from([0, 0, 1, -1]))
        status = draw(st.sampled_from(["unmatched", "unmatched", "unmatched", "matched", "transfer", "ignored"]))
        taken = [e.id for e in events][: draw(st.integers(0, 1))] if status == "matched" else []
        lines.append(
            BankLine(
                id=f"l{i:02d}",
                date=base + timedelta(days=draw(st.integers(0, 70))),
                amount_pence=amount,
                description=f"CARD PAYMENT TO {draw(st.sampled_from(NAMES)).upper()} DD",
                source_file="x.csv",
                status=status,  # type: ignore[arg-type]
                matched_event_ids=taken,
            )
        )
    return lines, events


@given(bank_case())
@settings(max_examples=150)
def test_matching_never_uses_a_bank_line_or_an_event_twice(case: tuple[list[BankLine], list[LedgerEvent]]):
    lines, events = case
    matches = suggest_matches(lines, events)
    by_id = {e.id: e for e in events}
    line_by_id = {ln.id: ln for ln in lines}

    assert len({m.line_id for m in matches}) == len(matches)  # a line matched once
    used = [eid for m in matches for eid in m.event_ids]
    assert len(set(used)) == len(used)  # an event paid by one line
    already = {eid for ln in lines if ln.status == "matched" for eid in ln.event_ids()}
    assert not already & set(used)  # an event a line already pays is out of play
    for m in matches:
        line = line_by_id[m.line_id]
        assert not line.resolved  # matched, transfer and ignored lines are never suggested again
        assert m.event_id == m.event_ids[0] and 1 <= len(m.event_ids) <= 3
        paid = sum(settlement_pence(by_id[i]) for i in m.event_ids)
        assert abs(paid - line.amount_pence) <= PENNY  # the right way round, within a penny
        assert 0.6 <= m.score <= 1.0 and m.kind == ("exact" if m.score >= 0.9 else "suggested")


@given(
    st.lists(
        st.tuples(st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 3, 31)), st.booleans()),
        max_size=30,
    )
)
def test_reconciled_to_is_the_last_day_before_anything_is_open(spec: list[tuple[date, bool]]):
    lines = [
        BankLine(
            id=f"l{i}",
            date=d,
            amount_pence=100,
            description="x",
            source_file="x.csv",
            status="matched" if done else "unmatched",
        )
        for i, (d, done) in enumerate(spec)
    ]
    upto = reconciled_to(lines)
    first_open = min((ln.date for ln in lines if not ln.resolved), default=date.max)
    done_before = [ln.date for ln in lines if ln.resolved and ln.date < first_open]
    assert upto == max(done_before, default=None)
    if upto is not None:  # every line up to that day is settled, whatever order the file listed them in
        assert all(ln.resolved for ln in lines if ln.date <= upto)
