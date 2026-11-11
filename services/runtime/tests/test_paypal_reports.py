"""PayPal in the reports and summaries (app/paypal_reports.py): the 1240 PayPal clearing balance as its own line next
to the bank ("PayPal (books)"), PayPal's fees and money received for the period, what waits in Sync PayPal, open
disputes and bills due through PayPal, on Home, the dashboard, the cash flow page, the month-end summary, the profit
answers, Ask and the report downloads. Every figure is worked out by code; nothing is invented, and books that never
use PayPal see no PayPal line. PayPal itself is the fake in app/online_fakes.py or a stub; nothing here calls it."""

# ruff: noqa: F811
from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from test_dashboard import TODAY, books, client, fake  # noqa: F401  shared fixtures (pytest puts tests/ on the path)

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.events import LedgerEvent, Line
from app import ask_pnl, billpay, online_fakes, online_payments, payment_providers
from app import cashflow as cf
from app import dashboard as dash
from app import home_items as hi
from app import paypal_assistant as pa
from app import paypal_disputes as pd
from app import paypal_reports as pr
from app import paypal_sync as ps
from app import reports as rp
from app.ai import close_summary as cs
from app.ai import home_summary as hs
from app.ai.ask import KnownNumbers
from app.ask_router import Span
from app.books import Books, now
from app.contacts import contact_id, supplier_key
from app.exports import mapping
from app.exports.accounts import cash_book
from app.journal import CREDITORS, PAYPAL_CLEARING
from app.online_fakes import FAKES
from app.schemas import AskPeriod

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok"}
FEES = "7900 Bank charges"
SUPPLIER = "Timber Yard Ltd"
CID = contact_id(supplier_key(SUPPLIER), None)


def _gbp(p: int) -> str:
    return hs.gbp(p)


def _paypal_sale(when: date, gross: int, fee: int) -> list[LedgerEvent]:
    """A customer paid `gross` through PayPal; PayPal kept `fee` (Dr 7900 / Cr 1240), as Sync PayPal posts them."""
    return [
        LedgerEvent(
            kind="bank",
            date=when,
            lines=[Line(account=PAYPAL_CLEARING, debit=gross), Line(account="1100 Debtors", credit=gross)],
            approved_by=USER,
            approved_at=now(),
            counterparty="PayPal",
        ),
        online_payments.fee_event("paypal", f"PAY-{gross}", "INV-0001", when, fee, USER),
    ]


async def _post(books: Books, events: list[LedgerEvent]) -> None:
    for e in events:
        await books.post_event(e)


# --------------------------------------------------------------------------- #
# Pure pieces
# --------------------------------------------------------------------------- #


def test_no_paypal_entries_means_no_paypal_figure() -> None:
    plain = LedgerEvent(
        kind="bank",
        date=date(2026, 10, 1),
        lines=[Line(account="1200 Bank", debit=500), Line(account="1100 Debtors", credit=500)],
        approved_by=USER,
        approved_at=now(),
    )
    assert pr.clearing_balance([plain]) is None
    assert pr.period_totals([plain]) == (0, 0, 0)


def test_balance_fees_and_received() -> None:
    evs = _paypal_sale(date(2026, 10, 5), 12_000, 438) + _paypal_sale(date(2026, 10, 9), 8_000, 292)
    assert pr.clearing_balance(evs) == 12_000 - 438 + 8_000 - 292
    assert pr.clearing_balance(evs, date(2026, 10, 5)) == 11_562  # only what is dated on or before
    t = pr.period_totals(evs)
    assert (t.fees_pence, t.fee_entries, t.received_pence) == (730, 2, 20_000)
    assert pr.totals_between(evs, date(2026, 10, 6), date(2026, 10, 31)).fees_pence == 292


# --------------------------------------------------------------------------- #
# Home: figures, to-dos, summary facts
# --------------------------------------------------------------------------- #


def _home(**kw: Any) -> pr.PayPalHome:
    base: dict[str, Any] = {
        "balance_pence": 11_562,
        "this_month": pr.MonthTotals(label="November 2026 so far", fees_pence=438, received_pence=12_000),
        "last_month": pr.MonthTotals(label="October 2026", fees_pence=0, received_pence=0),
    }
    return pr.PayPalHome(**(base | kw))


def test_home_facts_are_formatted_by_code_and_leave_out_what_is_missing() -> None:
    p = _home(
        waiting=pr.Waiting(count=3, net_pence=24_100),
        disputes=pr.DisputesOpen(count=1, needs_reply=1, amount_pence=9_000, respond_by=date(2026, 11, 20)),
        bills=pr.BillPayments(
            due_now_count=0,
            due_now_pence=0,
            within_7_days_count=2,
            within_7_days_pence=30_000,
            within_30_days_count=3,
            within_30_days_pence=45_000,
        ),
    )
    f = pr.home_facts(p, _gbp)
    assert f["balance_by_your_books"] == "£115.62" and f["balance_label"] == "PayPal (books)"
    assert f["this_month"] == {"label": "November 2026 so far", "fees": "£4.38", "received": "£120.00"}
    assert "last_month" not in f  # nothing in it: no sentence about £0.00
    assert f["waiting_in_sync_paypal"] == {"payments": 3, "net": "£241.00"}
    assert f["open_disputes"]["reply_by"] == "20 Nov 2026"
    assert "due_now" not in f["bill_payments_through_paypal"]
    assert f["bill_payments_through_paypal"]["due_within_7_days"] == {"bills": 2, "amount": "£300.00"}


def test_paypal_items_only_for_counts_above_zero() -> None:
    today = date(2026, 11, 11)
    assert hi.paypal_items(None, today) == []
    assert hi.paypal_items(_home(), today) == []  # a balance alone is not a to-do
    items = {
        d.item.id: d
        for d in hi.paypal_items(
            _home(
                waiting=pr.Waiting(count=1, net_pence=11_562),
                disputes=pr.DisputesOpen(count=2, needs_reply=1, amount_pence=9_000, respond_by=date(2026, 11, 14)),
                bills=pr.BillPayments(
                    due_now_count=1,
                    due_now_pence=12_000,
                    within_7_days_count=0,
                    within_7_days_pence=0,
                    within_30_days_count=0,
                    within_30_days_pence=0,
                ),
            ),
            today,
        )
    }
    assert set(items) == {"paypal_sync", "paypal_disputes", "paypal_bills"}
    assert items["paypal_sync"].item.title == "1 PayPal payment waiting in Sync PayPal"
    assert "£115.62" in (items["paypal_sync"].item.detail or "")
    assert items["paypal_disputes"].item.priority == 1  # a reply is due within two weeks
    assert items["paypal_disputes"].item.title == "2 open PayPal disputes: £90.00"
    assert items["paypal_bills"].item.action is not None and items["paypal_bills"].item.action.route == "/purchases"
    assert "coming soon" not in repr(items).lower()


def test_home_summary_words_are_checked_against_the_paypal_facts() -> None:
    facts = {
        "kind": "company",
        "cash": {"balance": "£1,000.00", "as_of": "10 Nov 2026"},
        "paypal": pr.home_facts(_home(), _gbp),
    }
    out = hs.fallback_summary(facts)
    assert "£1,000.00 in the bank" in out and "PayPal (books) holds £115.62, counted separately." in out
    assert hs.ground("PayPal (books) holds £115.62.", facts) is None
    assert hs.ground("PayPal (books) holds £999.99.", facts) is not None  # a figure that is not in the facts
    waiting = {**facts, "paypal": pr.home_facts(_home(waiting=pr.Waiting(count=2, net_pence=100)), _gbp)}
    assert hs.ground("All clear: nothing needs doing.", waiting) is not None  # something waits in Sync PayPal
    assert "PayPal" in hs.SYSTEM_PROMPT and "never added to the bank balance" in hs.SYSTEM_PROMPT


async def test_home_for_books_without_paypal_has_no_paypal_line(client: TestClient) -> None:  # noqa: F811
    d = client.get(f"/books/home?stagger=1&today={TODAY}&summary_ai=false", headers=H).json()
    assert d["paypal"] is None and "paypal" not in d["summary"]["facts"]
    assert not any(i["id"].startswith("paypal") for i in d["summary"]["items"])
    dd = client.get(f"/books/dashboard?stagger=1&today={TODAY}", headers=H).json()
    assert dd["paypal_books_pence"] is None


async def test_home_dashboard_and_cash_flow_show_paypal_beside_the_bank(
    books: Books,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    await _post(books, _paypal_sale(TODAY - timedelta(days=2), 12_000, 438))
    q = f"stagger=1&today={TODAY}&summary_ai=false"
    home = client.get(f"/books/home?{q}", headers=H).json()
    assert home["paypal"]["balance_pence"] == 11_562
    assert (
        home["paypal"]["this_month"]["fees_pence"] == 438 and home["paypal"]["this_month"]["received_pence"] == 12_000
    )
    facts = home["summary"]["facts"]
    assert facts["paypal"]["balance_by_your_books"] == "£115.62"
    assert facts["paypal"]["this_month"]["received"] == "£120.00"
    assert (
        KnownNumbers(facts).unknown("PayPal (books) holds £115.62 and PayPal's fees were £4.38.", all_tokens=False)
        == []
    )
    dd = client.get(f"/books/dashboard?stagger=1&today={TODAY}", headers=H).json()
    assert dd["paypal_books_pence"] == 11_562
    assert dd["cash"]["balance_pence"] is not None  # the bank figure is untouched
    flow = await cf.build(books, TODAY)
    assert flow.paypal_books_pence == 11_562
    assert flow.opening_balance_pence == sum(  # the bank balance does not include PayPal
        ln.debit - ln.credit for e in await books.list_events() for ln in e.lines if ln.account.startswith("1200")
    )
    assert cf.facts(flow)["paypal_books_today"] == "£115.62"
    assert "PayPal (books)" in cf.SYSTEM_PROMPT
    assert (await dash.build(books, TODAY, 1, 3)).paypal_books_pence == 11_562


# --------------------------------------------------------------------------- #
# Waiting in Sync PayPal, open disputes, bills due through PayPal
# --------------------------------------------------------------------------- #


async def _sync_item(books: Books, tid: str, net: int, status: str = "proposed") -> None:
    state = await ps.load_state(books)
    state.items[tid] = ps.SyncItem(
        transaction_id=tid,
        date=date(2026, 11, 9),
        kind="sale",
        status=status,  # type: ignore[arg-type]
        event_code="T0006",
        name="JM Trading Ltd",
        gross_pence=net + 100,
        fee_pence=100,
        net_pence=net,
        found_at=datetime.now(UTC),
    )
    await books.write_json(ps.SYNC, state.model_dump(mode="json"))


def _dispute(status: str = "WAITING_FOR_SELLER_RESPONSE", sample: bool = False) -> pd.DisputeRow:
    return pd.DisputeRow(
        dispute_id="PP-D-1",
        sample=sample,
        reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        reason_text="Goods or service not received",
        status=status,
        amount_pence=9_000,
        respond_by=date(2026, 11, 20),
        invoice="INV-0001",
        customer="JM Trading Ltd",
        can_send_evidence=True,
    )


@pytest.fixture
def paypal_fakes(monkeypatch: pytest.MonkeyPatch):
    for k in ("ACCNOMOS_TEST_MODE", "PAYMENTS_LIVE", "PAYPAL_BASE", "PAYPAL_DIRECT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PAYPAL_CLIENT_ID", online_fakes.PAYPAL_CLIENT[0])
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", online_fakes.PAYPAL_CLIENT[1])
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", online_fakes.PAYPAL_PARTNER)
    monkeypatch.setenv("PAYPAL_PARTNER_ATTRIBUTION_ID", "ACCNOMOS_FAKE_BN")
    monkeypatch.setenv("PAYPAL_RETURN_URL", "https://api.example/payments/online/paypal/callback")
    FAKES.reset()
    FAKES.reporting = []
    online_fakes.install("https://fake.example")
    FAKES.merchants[online_fakes.PAYPAL_MERCHANT] = {"merchant_id": online_fakes.PAYPAL_MERCHANT}
    yield
    payment_providers.TRANSPORT = None


@pytest.fixture
async def paypal_books() -> Books:
    b = Books(FakeStorageProvider())
    await b.write_json(
        online_payments.PROVIDERS,
        {
            "paypal": {
                "merchant_id": online_fakes.PAYPAL_MERCHANT,
                "sandbox": True,
                "connected_at": now().isoformat(),
                "connected_by": USER,
            }
        },
    )
    return b


async def _bill(books: Books, gross: int, due_in_days: int, *, payee: bool = True) -> str:
    """A bill approved by a person, due `due_in_days` from TODAY (30-day terms)."""
    ev = LedgerEvent(
        kind="purchase",
        date=TODAY + timedelta(days=due_in_days - 30),
        lines=[
            Line(account="5000 Materials", debit=gross),
            Line(account=CREDITORS, credit=gross),
        ],
        approved_by=USER,
        approved_at=now(),
        net=gross,
        vat=0,
        counterparty=SUPPLIER,
    )
    await books.post_event(ev)
    if payee:
        await billpay.set_payee(books, CID, "accounts@timberyard.example", None, USER)
    return ev.id


async def test_bill_payments_by_due_date(paypal_books: Books, paypal_fakes) -> None:  # noqa: ANN001
    assert await pr.bill_payments(paypal_books, TODAY) is None
    await _bill(paypal_books, 12_000, 3)
    await _bill(paypal_books, 5_000, 20)
    b = await pr.bill_payments(paypal_books, TODAY)
    assert b is not None
    assert (b.due_now_count, b.within_7_days_count, b.within_7_days_pence) == (0, 1, 12_000)
    assert (b.within_30_days_count, b.within_30_days_pence) == (2, 17_000)  # the 7 days are inside the 30
    await _bill(paypal_books, 4_000, -2)
    b = await pr.bill_payments(paypal_books, TODAY)
    assert b is not None and (b.due_now_count, b.due_now_pence) == (1, 4_000)


async def test_bills_without_a_paypal_plan_are_not_listed(paypal_books: Books, paypal_fakes) -> None:  # noqa: ANN001
    await _bill(paypal_books, 12_000, 3, payee=False)  # no supplier PayPal email saved, no PayPal plan
    assert await pr.bill_payments(paypal_books, TODAY) is None


async def test_home_figures_gathers_waiting_disputes_and_bills(
    paypal_books: Books,
    paypal_fakes,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    await _post(paypal_books, _paypal_sale(TODAY - timedelta(days=1), 12_000, 438))
    await _sync_item(paypal_books, "TX1", 11_900)
    await _sync_item(paypal_books, "TX2", 5_000, status="approved")  # decided: not waiting
    await _bill(paypal_books, 12_000, 3)

    async def one(_books: Books, *, sample: bool = False) -> pd.DisputeList:
        return pd.DisputeList(connected=True, disputes=[_dispute(), _dispute("RESOLVED")])

    monkeypatch.setattr(pd, "list_disputes", one)
    p = await pr.home_figures(paypal_books, TODAY)
    assert p is not None
    assert p.balance_pence == 11_562
    assert p.waiting is not None and (p.waiting.count, p.waiting.net_pence) == (1, 11_900)
    assert p.disputes is not None and (p.disputes.count, p.disputes.needs_reply, p.disputes.amount_pence) == (
        1,
        1,
        9_000,
    )
    assert p.disputes.respond_by == date(2026, 11, 20)
    assert p.bills is not None and p.bills.within_7_days_count == 1


async def test_a_slow_or_failing_part_is_left_out_not_fatal(
    paypal_books: Books,
    paypal_fakes,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    await _post(paypal_books, _paypal_sale(TODAY - timedelta(days=1), 12_000, 438))

    async def boom(_books: Books, *, sample: bool = False) -> pd.DisputeList:
        raise RuntimeError("PayPal is down")

    monkeypatch.setattr(pd, "list_disputes", boom)
    p = await pr.home_figures(paypal_books, TODAY)
    assert p is not None and p.balance_pence == 11_562 and p.disputes is None


# --------------------------------------------------------------------------- #
# Month end
# --------------------------------------------------------------------------- #


async def test_month_end_facts_and_fallback_sentence(paypal_books: Books, paypal_fakes) -> None:  # noqa: ANN001
    await _post(paypal_books, _paypal_sale(date(2026, 10, 12), 12_000, 438))
    await _post(paypal_books, _paypal_sale(date(2026, 11, 2), 3_000, 100))  # another month: not in October's
    await _sync_item(paypal_books, "TX1", 11_900)
    f = await pr.close_facts(paypal_books, date(2026, 10, 1), date(2026, 10, 31), _gbp)
    assert f == {
        "fees": "£4.38",
        "received": "£120.00",
        "balance_at_month_end": "£115.62",
        "waiting_in_sync_paypal": 1,
    }
    assert cs.paypal_sentence(f) == (
        "PayPal charged £4.38 in fees and £120.00 came in through it; "
        "1 PayPal payment is waiting in Sync PayPal for your approval."
    )
    assert cs.paypal_sentence({}) == ""
    facts = {
        "month": "October 2026",
        "needs_you": 0,
        "blocking": 0,
        "can_close": True,
        "closed": False,
        "steps": [],
        "figures": {},
        "paypal": f,
    }
    assert "PayPal charged £4.38" in cs.fallback_summary(facts)
    assert cs.ground("PayPal charged £4.38 in fees.", facts) is None
    assert cs.ground("PayPal charged £5.00 in fees.", facts) is not None
    assert await pr.close_facts(Books(FakeStorageProvider()), date(2026, 10, 1), date(2026, 10, 31), _gbp) == {}


# --------------------------------------------------------------------------- #
# Profit answers, Ask, reports and exports
# --------------------------------------------------------------------------- #


def test_profit_answer_carries_paypal_fees_and_money_received() -> None:
    evs = _paypal_sale(date(2026, 10, 5), 12_000, 438)
    f = ask_pnl.pnl_facts(evs, Span(date(2026, 10, 1), date(2026, 10, 31), "October 2026"))
    assert f["paypal"] == {"fees_in_those_costs": "£4.38", "received_through_paypal": "£120.00"}
    assert "PayPal fees in those costs were £4.38; £120.00 came in through PayPal." in ask_pnl.pnl_code_text(f)
    none = ask_pnl.pnl_facts([], Span(date(2026, 10, 1), date(2026, 10, 31), "October 2026"))
    assert "paypal" not in none


@pytest.mark.parametrize(
    ("q", "kind"),
    [
        ("do I have any PayPal disputes?", "disputes"),
        ("is there a PayPal chargeback open", "disputes"),
        ("what is waiting in Sync PayPal?", "waiting"),
        ("which PayPal payments are waiting for me to approve?", "waiting"),
        ("which bills are due through PayPal this week?", "bills"),
        ("when was my last PayPal payout?", "held"),
        ("what did PayPal cost me this quarter?", "fees"),
        ("how much is sitting in PayPal?", "held"),
        ("send evidence for the PayPal dispute", None),  # an instruction, not a question
        ("what did I spend on fuel", None),
    ],
)
def test_ask_routes_paypal_questions(q: str, kind: str | None) -> None:
    assert pa.question_kind(q) == kind


async def test_ask_answers_from_code_figures(
    paypal_books: Books,
    paypal_fakes,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    period = AskPeriod(start=date(2026, 10, 1), end=TODAY)
    await _sync_item(paypal_books, "TX1", 11_900)
    waiting = await pa.question_answer("what is waiting in Sync PayPal?", paypal_books, None, period, TODAY)
    assert waiting is not None and waiting.model == "code"
    assert "1 PayPal payment is waiting in Sync PayPal" in waiting.answer_md and "£119.00" in waiting.answer_md
    assert [k.value for k in waiting.key_numbers] == ["1", "£119.00"]

    async def one(_books: Books, *, sample: bool = False) -> pd.DisputeList:
        return pd.DisputeList(connected=True, disputes=[_dispute()])

    monkeypatch.setattr(pd, "list_disputes", one)
    disputes = await pa.question_answer("do I have any PayPal disputes?", paypal_books, None, period, TODAY)
    assert disputes is not None and "1 open PayPal dispute, £90.00 in all" in disputes.answer_md
    assert "20 November 2026" in disputes.answer_md and "nothing is sent until you approve" in disputes.answer_md
    held = await pa.question_answer("how much is sitting in PayPal?", paypal_books, None, period, TODAY)
    assert held is not None and held.key_numbers[0].label == "PayPal (books)"

    async def none(_books: Books, *, sample: bool = False) -> pd.DisputeList:
        return pd.DisputeList(connected=True, disputes=[_dispute("RESOLVED")])

    monkeypatch.setattr(pd, "list_disputes", none)
    quiet = await pa.question_answer("any PayPal disputes?", paypal_books, None, period, TODAY)
    assert quiet is not None and quiet.answer_md == "You have no open PayPal disputes."


async def test_ask_bills_through_paypal(paypal_books: Books, paypal_fakes) -> None:  # noqa: ANN001
    period = AskPeriod(start=date(2026, 10, 1), end=TODAY)
    empty = await pa.question_answer("which bills are due through PayPal?", paypal_books, None, period, TODAY)
    assert empty is not None and "No approved bills are planned for PayPal" in empty.answer_md
    f = await pa.bills_facts(paypal_books)
    assert f["_n"] == 0


def test_the_ask_facts_pack_has_paypal_fees_per_period() -> None:
    from app.facts import _totals

    t = _totals(_paypal_sale(date(2026, 10, 5), 12_000, 438))
    assert t["paypal"] == {"fees": "4.38", "received": "120.00"}
    assert "paypal" not in _totals([])


def test_profit_and_loss_report_and_its_sheet_label_paypal() -> None:
    evs = _paypal_sale(date(2026, 10, 5), 12_000, 438)
    pl = rp.profit_and_loss(evs, date(2026, 10, 1), date(2026, 10, 31))
    assert (pl.paypal_fees_pence, pl.paypal_received_pence) == (438, 12_000)
    assert [(r.account, r.amount_pence) for r in pl.overheads.rows] == [(FEES, 438)]
    cash = rp.profit_and_loss(evs, date(2026, 10, 1), date(2026, 10, 31), basis="cash")
    assert cash.paypal_fees_pence is None  # the cash basis reads derived events: no PayPal memo
    assert rp.profit_and_loss([], date(2026, 10, 1), date(2026, 10, 31)).paypal_fees_pence is None
    data, sheets = rp.build_report_xlsx("pl", pl=pl)
    ws = load_workbook(io.BytesIO(data))["P&L"]
    cells = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert "  7900 Bank charges" in cells
    assert "  PayPal fees (in 7900 Bank charges)" in cells
    assert "  Money received through PayPal (via 1240 PayPal clearing)" in cells
    assert "Of which, through PayPal (memo; included above)" in cells


def test_balance_sheet_labels_1240() -> None:
    evs = _paypal_sale(date(2026, 10, 5), 12_000, 438)
    bs = rp.balance_sheet(evs, date(2026, 10, 31))
    assert (PAYPAL_CLEARING, 11_562) in [(r.account, r.amount_pence) for r in bs.assets.rows]
    pl = rp.profit_and_loss(evs, date(2026, 10, 1), date(2026, 10, 31))
    data, _ = rp.build_month_end_xlsx("October 2026", pl, bs, draft=True)
    ws = load_workbook(io.BytesIO(data))["Balance sheet"]
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert "1240 PayPal clearing" in text and "It is not your bank balance" not in text
    assert "it is not your bank balance" in text


def test_exports_name_1240_and_7900_for_each_package() -> None:
    m = mapping.Mappings()
    for package, pkg_name in (("xero", "Xero"), ("sage50", "Sage 50"), ("qbo", "QuickBooks")):
        got = mapping.resolve(package, PAYPAL_CLEARING, m)
        assert got.quality == "check" and f"in {pkg_name}" in got.note and "7900 Bank charges" in got.note
        assert any("1240 PayPal clearing" in line for line in mapping.problems([got]))
    assert mapping.resolve("xero", FEES, m).name == "Bank Fees"
    assert mapping.resolve("sage-accounting", FEES, m).name == "Bank Charges and Interest"


def test_cash_book_names_1240_as_what_paypal_holds() -> None:
    evs = _paypal_sale(date(2026, 10, 5), 12_000, 438)
    sec = cash_book(evs, date(2026, 10, 1), date(2026, 10, 31), {})
    assert any(r.cells.get("account") == PAYPAL_CLEARING for r in sec.rows)
    assert "1240 PayPal clearing is what PayPal holds for you by your books" in (sec.note or "")
