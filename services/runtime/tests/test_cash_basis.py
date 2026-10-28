"""Cash basis for sole traders (app/cash_basis.py), against traditional accounting (accruals) on the same ledger.

gov.uk/simpler-income-tax-cash-basis (checked 28 Oct 2026): "With cash basis you only record income or expenses
when you receive money or pay a bill"; "You invoiced someone on 15 March 2024 but did not receive the money until 30
April 2024. Record this income as received on 30 April 2024." Capital: s33A ITTOIA 2005 / BIM70035.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app import cash_basis as cb
from app import itsa
from app import reports as rp
from app.books import Books
from app.contacts import Ledger
from app.main import app
from app.routes_books import get_books
from app.settlement import Allocation, CreditUse, PaymentRecord

AT = datetime(2026, 10, 1, 12, 0)
H = {"X-Graph-Token": "t", "X-User": "sam@sambuilds.example"}
TY = "2026-27"
Q1, Q2, Q3 = date(2026, 7, 5), date(2026, 10, 5), date(2027, 1, 5)  # cumulative period ends


def ev(id_: str, day: date, kind: str, *lines: Line, credits: str | None = None, reverses: str | None = None):
    return LedgerEvent(
        id=id_ * 32 if len(id_) == 1 else id_,
        kind=kind,  # type: ignore[arg-type]
        date=day,
        lines=list(lines),
        counterparty="Acme Ltd" if kind != "purchase" else "Timber Co",
        approved_by="sam",
        approved_at=AT,
        credits=credits,
        reverses=reverses,
    )


def invoice(id_: str, day: date, net: int, vat: int = 0) -> LedgerEvent:
    ls = [
        Line(account="1100 Debtors", debit=net + vat),
        Line(account="4000 Sales", credit=net, vat_code=VatCode.STANDARD),
    ]
    if vat:
        ls.append(Line(account="2200 VAT control", credit=vat))
    return ev(id_, day, "sale", *ls)


def bill(id_: str, day: date, account: str, net: int, vat: int = 0) -> LedgerEvent:
    ls = [Line(account=account, debit=net, vat_code=VatCode.STANDARD), Line(account="2100 Creditors", credit=net + vat)]
    if vat:
        ls.append(Line(account="2200 VAT control", debit=vat))
    return ev(id_, day, "purchase", *ls)


def receipt(id_: str, day: date, account: str, pence: int) -> LedgerEvent:
    """Paid at the till: no creditor, the money went out the day it was bought."""
    return ev(id_, day, "purchase", Line(account=account, debit=pence), Line(account="1200 Bank", credit=pence))


def credit_note(id_: str, day: date, of: str, net: int) -> LedgerEvent:
    return ev(
        id_,
        day,
        "reversal",
        Line(account="4000 Sales", debit=net),
        Line(account="1100 Debtors", credit=net),
        credits=of * 32,
    )


def paid(id_: str, day: date, side: str, *alloc: tuple[str, int], amount: int | None = None) -> PaymentRecord:
    return PaymentRecord(
        id=id_,
        side=side,  # type: ignore[arg-type]
        date=day,
        amount_pence=amount or sum(a for _, a in alloc),
        counterparty="Acme Ltd",
        allocations=[Allocation(event_id=e * 32, amount_pence=a) for e, a in alloc],
        created_by="sam",
        created_at=AT,
    )


def summary(ledger: Ledger, end: date, basis: cb.Basis) -> itsa.SeSummary:
    if basis == "traditional":
        return itsa.se_summary(ledger.events, TY, end)
    view = cb.cash_view(ledger)
    return itsa.se_summary(view.events, TY, end, "cash", view.refs, view.left_out)


def figure(s: itsa.SeSummary, key: str) -> itsa.SeFigure:
    return next(f for f in s.figures if f.key == key)


def turnover(ledger: Ledger, end: date, basis: cb.Basis) -> int:
    return figure(summary(ledger, end, basis), "turnover").pence


# --- the cases asked for --------------------------------------------------------------------------------------


def test_invoice_raised_in_one_period_and_paid_in_the_next() -> None:
    ledger = Ledger(
        events=[invoice("a", date(2026, 6, 20), 1_000_00, 200_00)],
        records=[paid("p1", date(2026, 7, 20), "sale", ("a", 1_200_00))],
    )
    # traditional: the first period (raised 20 June); cash: the second (paid 20 July)
    assert turnover(ledger, Q1, "traditional") == 1_000_00
    assert turnover(ledger, Q1, "cash") == 0
    assert turnover(ledger, Q2, "cash") == 1_000_00  # net of VAT, as the traditional figure
    s = summary(ledger, Q2, "cash")
    assert s.accounting_basis == "cash" and s.basis_label == "Cash basis"
    assert s.hmrc_body["periodIncome"]["turnover"] == 1000.0
    [line] = figure(s, "turnover").lines  # the drill-down names the payment and the invoice it paid
    assert line.date == date(2026, 7, 20) and line.source == "payment" and line.payment_id == "p1"
    assert line.event_id == line.document_event_id == "a" * 32
    assert line.money_pence == line.document_gross_pence == 1_200_00
    assert s.event_ids == ["a" * 32]


def test_part_payments_count_pro_rata_and_add_up_exactly() -> None:
    # £100.01 net + £20.00 VAT = £120.01, paid in three uneven parts: no penny lost to rounding
    ledger = Ledger(
        events=[invoice("a", date(2026, 5, 1), 100_01, 20_00)],
        records=[
            paid("p1", date(2026, 5, 10), "sale", ("a", 40_00)),
            paid("p2", date(2026, 8, 10), "sale", ("a", 40_00)),
            paid("p3", date(2026, 11, 10), "sale", ("a", 40_01)),
        ],
    )
    assert turnover(ledger, Q1, "cash") == 33_33  # 40.00 / 120.01 of £100.01
    assert turnover(ledger, Q2, "cash") == 66_67
    assert turnover(ledger, Q3, "cash") == 100_01  # fully paid: exactly the invoice's net
    assert turnover(ledger, Q1, "traditional") == 100_01
    shares = [c.pence for c in figure(summary(ledger, Q3, "cash"), "turnover").lines]
    assert shares == [33_33, 33_34, 33_34] and sum(shares) == 100_01


def test_a_part_paid_invoice_counts_only_what_was_received() -> None:
    ledger = Ledger(
        events=[invoice("a", date(2026, 5, 1), 1_000_00)],
        records=[paid("p1", date(2026, 6, 1), "sale", ("a", 400_00))],
    )
    assert turnover(ledger, Q3, "cash") == 400_00
    assert turnover(ledger, Q3, "traditional") == 1_000_00


def test_bill_paid_later() -> None:
    ledger = Ledger(
        events=[bill("b", date(2026, 6, 1), "5000 Materials", 300_00, 60_00)],
        records=[paid("p1", date(2026, 8, 15), "purchase", ("b", 360_00))],
    )
    s1, s2 = summary(ledger, Q1, "cash"), summary(ledger, Q2, "cash")
    assert figure(s1, "costOfGoods").pence == 0
    assert figure(s2, "costOfGoods").pence == 300_00
    assert figure(summary(ledger, Q1, "traditional"), "costOfGoods").pence == 300_00
    [line] = figure(s2, "costOfGoods").lines
    assert line.paid_how == "Payment made" and line.date == date(2026, 8, 15)


def test_a_receipt_paid_when_bought_counts_on_its_date_on_both_bases() -> None:
    ledger = Ledger(events=[receipt("r", date(2026, 6, 3), "7400 Travel", 12_34)])
    for basis in ("cash", "traditional"):
        assert figure(summary(ledger, Q1, basis), "carVanTravelExpenses").pence == 12_34  # type: ignore[arg-type]
    [line] = figure(summary(ledger, Q1, "cash"), "carVanTravelExpenses").lines
    assert line.source == "on_its_date" and line.paid_how == "Paid when bought"


def test_refund_counts_when_the_money_goes_back() -> None:
    # Paid in full in May; a £100 credit note in June leaves a credit on the account; refunded in August.
    ledger = Ledger(
        events=[invoice("a", date(2026, 5, 1), 500_00), credit_note("c", date(2026, 6, 10), "a", 100_00)],
        records=[paid("p1", date(2026, 5, 20), "sale", ("a", 500_00))],
        uses=[
            CreditUse(
                id="u1",
                kind="refund",
                side="sale",
                date=date(2026, 8, 1),
                amount_pence=100_00,
                credit="credit_note:" + "c" * 32,
                created_by="sam",
                created_at=AT,
            )
        ],
    )
    assert turnover(ledger, Q1, "traditional") == 400_00  # the credit note counts on its own date
    assert turnover(ledger, Q1, "cash") == 500_00  # no money went back yet
    assert turnover(ledger, Q2, "cash") == 400_00  # the refund, on 1 August
    refund = [c for c in figure(summary(ledger, Q2, "cash"), "turnover").lines if c.source == "refund"]
    assert [(c.date, c.pence, c.paid_how) for c in refund] == [(date(2026, 8, 1), -100_00, "Refund paid")]


def test_a_credit_note_before_payment_counts_through_what_is_paid() -> None:
    ledger = Ledger(
        events=[invoice("a", date(2026, 5, 1), 1_000_00), credit_note("c", date(2026, 5, 5), "a", 200_00)],
        records=[paid("p1", date(2026, 6, 1), "sale", ("a", 800_00))],
    )
    assert turnover(ledger, Q1, "cash") == 800_00
    assert turnover(ledger, Q1, "traditional") == 800_00


def test_overpayment_is_listed_not_counted_until_applied() -> None:
    ledger = Ledger(
        events=[invoice("a", date(2026, 5, 1), 100_00), invoice("b", date(2026, 9, 1), 50_00)],
        records=[paid("p1", date(2026, 5, 20), "sale", ("a", 100_00), amount=130_00)],
    )
    s = summary(ledger, Q1, "cash")
    assert figure(s, "turnover").pence == 100_00
    assert [(x.pence, x.description) for x in s.left_out] == [(30_00, "Money received not matched to an invoice")]
    ledger.uses = [
        CreditUse(
            id="u1",
            kind="apply",
            side="sale",
            date=date(2026, 9, 2),
            amount_pence=30_00,
            credit="payment:p1",
            doc_event_id="b" * 32,
            created_by="sam",
            created_at=AT,
        )
    ]
    ledger._settled = None
    s = summary(ledger, Q1, "cash")
    assert figure(s, "turnover").pence == 130_00  # counted on 20 May, when the money came in
    assert not s.left_out


def test_bank_line_matched_to_an_invoice_counts_on_the_bank_date() -> None:
    from accnomos_ledger.bank import BankLine

    line = BankLine.model_validate(
        {
            "id": "0123456789abcdef",
            "date": "2026-07-30",
            "description": "FASTER PAYMENT ACME",
            "amount_pence": 250_00,
            "status": "matched",
            "source_file": "statement.csv",
            "matched_event_ids": ["a" * 32],
        }
    )
    ledger = Ledger(events=[invoice("a", date(2026, 6, 1), 250_00)], bank_lines=[line])
    assert turnover(ledger, Q1, "cash") == 0
    [c] = figure(summary(ledger, Q2, "cash"), "turnover").lines
    assert c.source == "bank_line" and c.paid_how == "Bank: FASTER PAYMENT ACME"


def test_undone_invoice_and_its_payment_count_nothing() -> None:
    a = invoice("a", date(2026, 5, 1), 100_00)
    undo = ev(
        "u",
        date(2026, 5, 2),
        "reversal",
        Line(account="1100 Debtors", credit=100_00),
        Line(account="4000 Sales", debit=100_00),
        reverses="a" * 32,
    )
    ledger = Ledger(events=[a, undo], records=[paid("p1", date(2026, 5, 3), "sale", ("a", 100_00))])
    assert turnover(ledger, Q1, "cash") == 0


# --- capital, depreciation and journals --------------------------------------------------------------------------


def test_capital_purchases_follow_the_cash_basis_rules() -> None:
    ledger = Ledger(
        events=[
            receipt("e", date(2026, 5, 1), "0030 Office equipment", 1_200_00),  # a laptop: an expense on cash basis
            receipt("v", date(2026, 5, 2), "0050 Motor car", 9_000_00),  # a car: capital allowances only
            ev(  # depreciation is not money paid
                "d",
                date(2026, 6, 30),
                "adjustment",
                Line(account="8000 Depreciation", debit=100_00),
                Line(account="0031 Office equipment depreciation", credit=100_00),
            ),
        ]
    )
    cash, trad = summary(ledger, Q1, "cash"), summary(ledger, Q1, "traditional")
    assert figure(cash, "otherExpenses").pence == 1_200_00 and figure(cash, "otherExpenses").box == 30
    assert figure(cash, "depreciation").pence == 0
    assert {x.description for x in cash.left_out} == {
        "0050 Motor car",
        "8000 Depreciation",
        "0031 Office equipment depreciation",
    }
    assert any("capital allowances" in x.reason for x in cash.left_out)
    assert any("Equipment bought" in w for w in cash.warnings)
    # traditional: an asset is balance sheet (capital allowances, not built); depreciation is disallowable
    assert figure(trad, "otherExpenses").pence == 0
    assert figure(trad, "depreciation").disallowable_pence == 100_00
    assert itsa.capital_excluded("0040 Freehold building") and not itsa.capital_excluded("0030 Office equipment")


def test_a_bad_debt_journal_is_not_an_expense_on_the_cash_basis() -> None:
    write_off = ev(
        "w",
        date(2026, 6, 1),
        "adjustment",
        Line(account="7950 Bad debts", debit=100_00),
        Line(account="1100 Debtors", credit=100_00),
    )
    ledger = Ledger(events=[invoice("a", date(2026, 5, 1), 100_00), write_off])
    assert figure(summary(ledger, Q1, "traditional"), "irrecoverableDebts").pence == 100_00
    s = summary(ledger, Q1, "cash")
    assert figure(s, "irrecoverableDebts").pence == 0 and figure(s, "turnover").pence == 0
    assert [x.event_id for x in s.left_out] == ["w" * 32]


def test_cash_view_never_changes_the_ledger() -> None:
    events = [invoice("a", date(2026, 5, 1), 100_00, 20_00)]
    before = [e.model_dump() for e in events]
    ledger = Ledger(events=events, records=[paid("p1", date(2026, 5, 3), "sale", ("a", 60_00))])
    view = cb.cash_view(ledger)
    assert [e.model_dump() for e in ledger.events] == before
    assert all(e.id.startswith("cash-") for e in view.events if e.id not in {"a" * 32})
    assert not any(ln.account == "2200 VAT control" for e in view.events for ln in e.lines)  # excluding VAT


def test_cash_pl_uses_the_same_view() -> None:
    ledger = Ledger(
        events=[
            invoice("a", date(2026, 6, 20), 1_000_00),
            receipt("r", date(2026, 6, 21), "7500 Office supplies", 5_00),
        ],
        records=[paid("p1", date(2026, 7, 20), "sale", ("a", 1_000_00))],
    )
    view = cb.cash_view(ledger)
    june = rp.profit_and_loss(view.events, date(2026, 6, 1), date(2026, 6, 30), basis="cash")
    july = rp.profit_and_loss(view.events, date(2026, 7, 1), date(2026, 7, 31), basis="cash")
    assert june.sales.total_pence == 0 and june.overheads.total_pence == 5_00 and june.accounting_basis == "cash"
    assert july.sales.total_pence == 1_000_00 and "Cash basis" in july.basis
    assert rp.profit_and_loss(ledger.events, date(2026, 6, 1), date(2026, 6, 30)).sales.total_pence == 1_000_00


# --- routes: the setting, and switching it changes nothing but the presentation ----------------------------------


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.ensure_tree()
    await b.post_event(invoice("a", date(2026, 6, 20), 1_000_00, 200_00))
    await b.post_event(receipt("r", date(2026, 6, 21), "7500 Office supplies", 9_99))
    return b


@pytest.fixture
def client(books: Books):
    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _figures(client: TestClient, end: str, extra: str = "") -> dict:
    r = client.get(f"/books/self-employment/summary?tax_year={TY}&period_end={end}{extra}", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_switching_basis_changes_only_the_presentation(client: TestClient, books: Books) -> None:
    pay = {
        "side": "sale",
        "date": "2026-07-20",
        "amount_pence": 1_200_00,
        "allocations": [{"event_id": "a" * 32, "amount_pence": 1_200_00}],
    }
    assert client.post("/payments", json=pay, headers=H).status_code == 200

    settings = client.get("/books/self-employment/settings", headers=H).json()
    assert settings == {"accounting_basis": "cash", "label": "Cash basis", "default": "cash", "saved": False}
    cash_q1 = _figures(client, "2026-07-05")
    assert cash_q1["accounting_basis"] == "cash" and cash_q1["income_pence"] == 0
    assert _figures(client, "2026-10-05")["income_pence"] == 1_000_00

    storage = books.storage
    assert isinstance(storage, FakeStorageProvider)
    ledger_files = {p: d for p, d in storage.files.items() if "/Ledger/" in p or "/Payments/" in p}

    r = client.put("/books/self-employment/settings", json={"accounting_basis": "traditional"}, headers=H)
    assert r.status_code == 200 and r.json()["saved"] is True
    trad_q1 = _figures(client, "2026-07-05")
    assert trad_q1["accounting_basis"] == "traditional" and trad_q1["income_pence"] == 1_000_00
    assert _figures(client, "2026-07-05", "&basis=cash")["income_pence"] == 0  # a look, not a change
    assert client.get("/books/self-employment/settings", headers=H).json()["accounting_basis"] == "traditional"

    client.put("/books/self-employment/settings", json={"accounting_basis": "cash"}, headers=H)
    assert _figures(client, "2026-07-05") == cash_q1
    assert {p: d for p, d in storage.files.items() if "/Ledger/" in p or "/Payments/" in p} == ledger_files

    audit = client.get("/audit?kind=itsa_basis_changed", headers=H).json()["entries"]
    assert [e["summary"] for e in audit] == [
        "Changed the self-employment accounting basis to the cash basis",
        "Changed the self-employment accounting basis to traditional accounting",
    ]
    assert (
        client.put("/books/self-employment/settings", json={"accounting_basis": "accruals"}, headers=H).status_code
        == 422
    )
    no_user = client.put(
        "/books/self-employment/settings", json={"accounting_basis": "cash"}, headers={"X-Graph-Token": "t"}
    )
    assert no_user.status_code == 400


def test_receipt_and_report_record_the_basis(client: TestClient) -> None:
    body = _figures(client, "2026-10-05")
    receipt_in = {
        "kind": "cumulative",
        "tax_year": TY,
        "nino": "TC663795B",
        "business_id": "XAIS12345678910",
        "period_end": "2026-10-05",
        "sent": body["hmrc_body"],
        "hmrc": {"hmrc": None, "correlation_id": "corr-1"},
        "confirmed_at": "2026-10-28T09:00:00Z",
    }
    r = client.post("/books/self-employment/receipts", json=receipt_in, headers=H)
    assert r.status_code == 201 and r.json()["matches_books"] is True
    listed = client.get(f"/books/self-employment/receipts?tax_year={TY}", headers=H).json()["receipts"]
    assert listed[0]["accounting_basis"] == "cash"
    quarterly = client.get(
        f"/books/self-employment/reports/quarterly?tax_year={TY}&path={r.json()['path']}", headers=H
    ).json()
    assert ["Accounting basis", "Cash basis"] in quarterly["sections"][1]["rows"]
    # the same body checked as traditional does not match: there the unpaid invoice counts on the day it was raised
    wrong = client.post("/books/self-employment/receipts", json={**receipt_in, "basis": "traditional"}, headers=H)
    assert wrong.json()["matches_books"] is False

    report = client.get(f"/books/self-employment/reports/sa103?tax_year={TY}&period_end=2026-10-05", headers=H).json()
    assert report["notes"][0] == "Accounting basis: Cash basis."
    assert [s["title"] for s in report["sections"]][-2:] == [
        "Payments behind each box",
        "Not counted on the cash basis",
    ]
    trad = client.get(
        f"/books/self-employment/reports/sa103?tax_year={TY}&period_end=2026-10-05&basis=traditional", headers=H
    ).json()
    assert trad["sections"][-1]["title"] == "Ledger lines behind each box"


def test_pl_route_has_a_cash_basis_option(client: TestClient) -> None:
    pay = {
        "side": "sale",
        "date": "2026-07-20",
        "amount_pence": 600_00,
        "allocations": [{"event_id": "a" * 32, "amount_pence": 600_00}],
    }
    assert client.post("/payments", json=pay, headers=H).status_code == 200
    june = "/reports/pl?from=2026-06-01&to=2026-06-30"
    july = "/reports/pl?from=2026-07-01&to=2026-07-31"
    assert client.get(june, headers=H).json()["sales"]["total_pence"] == 1_000_00
    assert client.get(june, headers=H).json()["accounting_basis"] == "traditional"
    cash_june = client.get(june + "&basis=cash", headers=H).json()
    assert cash_june["sales"]["total_pence"] == 0 and cash_june["overheads"]["total_pence"] == 9_99
    assert client.get(july + "&basis=cash", headers=H).json()["sales"]["total_pence"] == 500_00  # half of the net
    export = client.post(
        "/reports/export", json={"report": "pl", "from": "2026-07-01", "to": "2026-07-31", "basis": "cash"}, headers=H
    )
    assert export.status_code == 200, export.text
