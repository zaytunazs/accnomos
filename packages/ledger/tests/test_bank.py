"""Bank CSV parsing (made-up UK exports) and bank-line ↔ ledger-event matching."""

from datetime import date, datetime

import pytest

from accnomos_ledger import LedgerEvent, Line, VatCode
from accnomos_ledger.bank import (
    BankCsvError,
    detect_bank,
    line_id,
    parse_amount,
    parse_bank_csv,
    parse_date,
    reconciled_to,
    suggest_action,
)
from accnomos_ledger.matching import settlement_pence, suggest_matches, tokens

STARLING = b"""Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP),Spending Category,Notes
21/10/2026,SCREWFIX DIRECT,CARD 1234,CARD PAYMENT,-38.47,961.53,SHOPPING,
22/10/2026,Acme Kitchens Ltd,INV-0042,FASTER PAYMENT,"1,200.00","2,161.53",INCOME,
"""

LLOYDS = (
    b"Transaction Date,Transaction Type,Sort Code,Account Number,Transaction Description,Debit Amount,Credit Amount,"
    b"""Balance
21/10/2026,DEB,'30-99-50,12345678,TOOLSTATION 1234 CD 1234,12.00,,988.00
23-10-2026,FPI,'30-99-50,12345678,ACME KITCHENS INV 43,,250.50,"1,238.50"
"""
)

HSBC = """Statement for SAMPLE — FICTIONAL COMPANY LTD
Account,12345678

Date,Details,Paid out,Paid in,Balance,Ref
21 Oct 2026,VISA CARD PAYMENT SCREWFIX 1234,(£38.47),,£961.53 CR,
2026-10-24,BANK CHARGES,5.00 DR,,956.53CR,FEE
24 Oct 2026,ACME KITCHENS,,£99.99,"1,056.52 CR",REF9
""".encode("cp1252")


def test_starling_signed_amount_column() -> None:
    a, b = parse_bank_csv(STARLING, "starling.csv")
    assert (a.date, a.amount_pence, a.description, a.reference, a.balance_pence) == (
        date(2026, 10, 21),
        -3847,
        "SCREWFIX DIRECT",
        "CARD 1234",
        96153,
    )
    assert (b.amount_pence, b.balance_pence, b.source_file, b.status) == (120000, 216153, "starling.csv", "unmatched")
    assert a.id == line_id(a.date, -3847, "SCREWFIX DIRECT", 96153) and len(a.id) == 16


def test_lloyds_debit_and_credit_columns() -> None:
    out, inn = parse_bank_csv(LLOYDS, "lloyds.csv")
    assert (out.amount_pence, out.description, out.balance_pence) == (-1200, "TOOLSTATION 1234 CD 1234", 98800)
    assert (inn.date, inn.amount_pence, inn.balance_pence) == (date(2026, 10, 23), 25050, 123850)


def test_hsbc_preamble_parentheses_cr_dr_and_text_dates() -> None:
    card, fee, receipt = parse_bank_csv(HSBC, "hsbc.csv")
    assert (card.date, card.amount_pence, card.balance_pence) == (date(2026, 10, 21), -3847, 96153)
    assert (fee.date, fee.amount_pence, fee.reference) == (date(2026, 10, 24), -500, "FEE")
    assert (receipt.amount_pence, receipt.balance_pence) == (9999, 105652)


def test_tide_transaction_information_and_paid_columns() -> None:
    csv = (
        b"Transaction ID,Transaction Date,Transaction Type,Transaction Information,Paid In,Paid Out,Balance\n"
        b"TD1,2026-07-01,TRANSFER,INSURANCE DIRECT DD,,64.00,5475.00\n"
        b"TD2,2026-07-06,Faster Payment In,NORTHGATE TIMBER CN8525,128.76,,5603.76\n"
    )
    out, inn = parse_bank_csv(csv, "tide.csv")
    assert (out.date, out.amount_pence, out.description, out.balance_pence) == (
        date(2026, 7, 1),
        -6400,
        "INSURANCE DIRECT DD",
        547500,
    )
    assert (inn.amount_pence, inn.description) == (12876, "NORTHGATE TIMBER CN8525")


def test_amounts_and_dates() -> None:
    assert parse_amount("£1,234.50") == 123450
    assert parse_amount("(12.00)") == parse_amount("12.00 DR") == parse_amount("-12") == -1200
    assert parse_amount("12.00CR") == 1200 and parse_amount("") is None and parse_amount("n/a") is None
    assert parse_date("21 Oct 2026") == parse_date("21-10-2026") == parse_date("2026-10-21") == date(2026, 10, 21)


def test_identical_rows_without_balance_get_distinct_ids() -> None:
    data = b"Date,Description,Amount\n21/10/2026,Coffee,-2.50\n21/10/2026,Coffee,-2.50\n"
    a, b = parse_bank_csv(data, "x.csv")
    assert a.id != b.id


def test_detect_bank_falls_back_to_bank() -> None:
    assert detect_bank(STARLING) == "starling"
    assert detect_bank(LLOYDS) == detect_bank(HSBC) == "bank"


def test_suggested_actions_for_unmatched_lines() -> None:
    csv = (
        b"Date,Description,Amount\n21/10/2026,TFR TO SAVINGS,-100.00\n21/10/2026,MONTHLY ACCOUNT FEE,-5.00\n"
        b"21/10/2026,CARD REVERSAL,0.00\n21/10/2026,COFFEE,-2.50\n21/10/2026,MYSTERY CREDIT,10.00\n"
    )
    hints = [suggest_action(ln) for ln in parse_bank_csv(csv, "s.csv")]
    assert [h.action for h in hints] == [
        "mark_transfer",
        "create_expense_proposal",
        "ignore",
        "create_expense_proposal",
        "ignore",
    ]
    assert "bank charges" in hints[1].reason


def test_reconciled_to_stops_before_the_first_open_day() -> None:
    lines = parse_bank_csv(
        b"Date,Description,Amount\n01/10/2026,A,-1.00\n03/10/2026,B,-2.00\n03/10/2026,C,-3.00\n05/10/2026,D,-4.00\n",
        "s.csv",
    )
    assert reconciled_to([]) is None and reconciled_to(lines) is None
    lines[0].status, lines[1].status, lines[3].status = "matched", "transfer", "ignored"
    assert reconciled_to(lines) == date(2026, 10, 1)  # 3 Oct is only half done
    lines[2].status = "suggested"  # a suggestion is not a decision
    assert reconciled_to(lines) == date(2026, 10, 1)
    lines[2].status = "ignored"
    assert reconciled_to(lines) == date(2026, 10, 5)


def test_not_a_statement() -> None:
    with pytest.raises(BankCsvError):
        parse_bank_csv(b"name,email\nSam,sam@example.co.uk\n", "x.csv")


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #


def _purchase(gross: int, when: date, who: str, eid: str) -> LedgerEvent:
    net = round(gross / 1.2)
    return LedgerEvent(
        id=eid,
        kind="purchase",
        date=when,
        counterparty=who,
        net=net,
        vat=gross - net,
        approved_by="sam@example.co.uk",
        approved_at=datetime(2026, 10, 25, 9, 0),
        lines=[
            Line(account="5100 Tools", debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=gross - net),
            Line(account="1200 Bank", credit=gross),
        ],
    )


def _sale(gross: int, when: date, who: str, eid: str) -> LedgerEvent:
    return LedgerEvent(
        id=eid,
        kind="sale",
        date=when,
        counterparty=who,
        net=gross,
        vat=0,
        approved_by="sam@example.co.uk",
        approved_at=datetime(2026, 10, 25, 9, 0),
        lines=[
            Line(account="1100 Debtors", debit=gross),
            Line(account="4000 Sales", credit=gross, vat_code=VatCode.ZERO),
        ],
    )


def _lines(csv: bytes) -> list:
    return parse_bank_csv(csv, "s.csv")


def test_settlement_and_tokens() -> None:
    assert settlement_pence(_purchase(3847, date(2026, 10, 21), "Screwfix", "e1")) == -3847
    assert settlement_pence(_sale(120000, date(2026, 10, 22), "Acme", "e2")) == 120000
    assert tokens("VISA CARD PAYMENT SCREWFIX 1234 POS") == {"screwfix"}


def test_exact_match_same_day_with_name_and_card() -> None:
    lines = _lines(STARLING)
    events = [
        _purchase(3847, date(2026, 10, 21), "Screwfix", "e1"),
        _sale(120000, date(2026, 10, 22), "Acme Kitchens", "e2"),
    ]
    m1, m2 = sorted(suggest_matches(lines, events, {"e1": "1234"}), key=lambda m: m.event_id)
    assert (m1.line_id, m1.event_id, m1.kind, m1.score) == (lines[0].id, "e1", "exact", 1.0)
    assert "card last 4 digits" in m1.reasons and "exact amount" in m1.reasons
    assert (m2.line_id, m2.kind) == (lines[1].id, "exact")


def test_date_window_five_days_and_closer_scores_higher() -> None:
    lines = _lines(b"Date,Description,Amount\n24/10/2026,Payment,-38.47\n")
    three = suggest_matches(lines, [_purchase(3847, date(2026, 10, 21), "Screwfix", "e1")])
    one = suggest_matches(lines, [_purchase(3847, date(2026, 10, 23), "Screwfix", "e1")])
    assert three[0].kind == one[0].kind == "suggested" and one[0].score > three[0].score
    # Five days out the date alone is too weak; the counterparty's name carries it.
    assert suggest_matches(lines, [_purchase(3847, date(2026, 10, 19), "Screwfix", "e1")]) == []
    named = _lines(b"Date,Description,Amount\n24/10/2026,SCREWFIX DIRECT,-38.47\n")
    (five,) = suggest_matches(named, [_purchase(3847, date(2026, 10, 19), "Screwfix", "e1")])
    assert five.kind == "suggested" and "5 days apart" in five.reasons
    assert suggest_matches(named, [_purchase(3847, date(2026, 10, 18), "Screwfix", "e1")]) == []


def test_payments_on_terms_may_come_later_but_need_the_name() -> None:
    dd = _lines(b"Date,Description,Amount\n05/11/2026,CUMBRIA VOLTIC GRID DD REF 7688713,-594.60\n")
    (m,) = suggest_matches(dd, [_purchase(59460, date(2026, 10, 25), "Cumbria Voltic Grid Ltd", "e1")])
    assert m.kind == "suggested" and "paid 11 days after the document" in m.reasons
    unnamed = _lines(b"Date,Description,Amount\n05/11/2026,ENERGY DD REF 7688713,-594.60\n")
    assert suggest_matches(unnamed, [_purchase(59460, date(2026, 10, 25), "Cumbria Voltic Grid Ltd", "e1")]) == []
    # Card digits alone (0.5 + 0.1) would reach "suggested": a late payment still needs the name.
    card = _lines(b"Date,Description,Amount\n05/11/2026,FP 4417 REF 7688713,-594.60\n")
    assert (
        suggest_matches(card, [_purchase(59460, date(2026, 10, 25), "Cumbria Voltic Grid Ltd", "e1")], {"e1": "4417"})
        == []
    )
    # An invoice on terms (debtors): the customer pays weeks later, never before the invoice by more than 5 days.
    paid = _lines(b"Date,Description,Amount\n20/11/2026,ACME KITCHENS INV-0042,1200.00\n")
    (s,) = suggest_matches(paid, [_sale(120000, date(2026, 10, 22), "Acme Kitchens", "e2")])
    assert s.kind == "suggested" and s.score < 0.9
    assert suggest_matches(paid, [_sale(120000, date(2026, 11, 30), "Acme Kitchens", "e2")]) == []
    assert suggest_matches(paid, [_sale(120000, date(2026, 9, 20), "Acme Kitchens", "e2")]) == []  # 61 days


def test_monthly_same_amount_bill_takes_the_nearer_document() -> None:
    dd = _lines(
        b"Date,Description,Amount\n"
        b"12/10/2026,THORNFIELD COMMS DD REF 1,-64.20\n"
        b"12/11/2026,THORNFIELD COMMS DD REF 2,-64.20\n"
    )
    events = [
        _purchase(6420, date(2026, 10, 2), "Thornfield Communications", "oct"),
        _purchase(6420, date(2026, 11, 2), "Thornfield Communications", "nov"),
    ]
    got = {m.line_id: m.event_id for m in suggest_matches(dd, events)}
    assert got == {dd[0].id: "oct", dd[1].id: "nov"}


def test_amount_within_a_penny() -> None:
    lines = _lines(b"Date,Description,Amount\n24/10/2026,SCREWFIX,-38.47\n")
    (penny,) = suggest_matches(lines, [_purchase(3848, date(2026, 10, 24), "Screwfix", "e1")])
    assert penny.kind == "exact" and "exact amount, 1p out" in penny.reasons and penny.score < 1.0
    assert suggest_matches(lines, [_purchase(3849, date(2026, 10, 24), "Screwfix", "e1")]) == []


def test_counterparty_near_spelling_counts() -> None:
    lines = _lines(b"Date,Description,Amount\n24/10/2026,TOOLSTN 0412 CD 1234,-12.00\n")
    (m,) = suggest_matches(lines, [_purchase(1200, date(2026, 10, 22), "Toolstation", "e1")])
    assert "name: toolstation" in m.reasons


def test_transfers_and_ignored_lines_are_not_matched() -> None:
    lines = _lines(b"Date,Description,Amount\n21/10/2026,Screwfix,-38.47\n")
    lines[0].status = "transfer"
    assert suggest_matches(lines, [_purchase(3847, date(2026, 10, 21), "Screwfix", "e1")]) == []
    lines[0].status = "ignored"
    assert suggest_matches(lines, [_purchase(3847, date(2026, 10, 21), "Screwfix", "e1")]) == []


def test_one_bank_line_pays_several_same_day_events() -> None:
    lines = _lines(b"Date,Description,Amount\n21/10/2026,SCREWFIX DIRECT,-60.00\n")
    events = [
        _purchase(2500, date(2026, 10, 21), "Screwfix", "a"),
        _purchase(3500, date(2026, 10, 21), "Screwfix", "b"),
        _purchase(1000, date(2026, 10, 21), "Toolstation", "c"),
    ]
    (m,) = suggest_matches(lines, events)
    assert sorted(m.event_ids) == ["a", "b"] and m.kind == "exact" and "sum of 2 events" in m.reasons


def test_never_matches_an_event_twice() -> None:
    lines = _lines(b"Date,Description,Amount\n21/10/2026,Screwfix,-38.47\n22/10/2026,Screwfix,-38.47\n")
    (m,) = suggest_matches(lines, [_purchase(3847, date(2026, 10, 21), "Screwfix", "e1")])
    assert m.line_id == lines[0].id  # the same-day line wins

    lines[0].status, lines[0].matched_event_id = "matched", "e1"
    assert suggest_matches(lines, [_purchase(3847, date(2026, 10, 21), "Screwfix", "e1")]) == []
