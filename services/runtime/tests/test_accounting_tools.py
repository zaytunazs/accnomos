"""Accounting tools: chart of accounts, manual journals, fixed assets, find and recode, tracking, budgets, cash flow.

Worked figures (pence) are in each test. The trial balance (Σ debit = Σ credit over every event) is checked after
each thing that posts.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode, compute_vat_return
from app import budgets as bg
from app import cashflow as cf
from app import chart as ch
from app.books import Books
from app.paths import RECEIPTS, VAT_RETURNS

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
S, Z, N = VatCode.STANDARD, VatCode.ZERO, VatCode.NO_VAT
Q3 = (date(2026, 7, 1), date(2026, 9, 30))


def _ev(eid: str, kind: str, when: date, lines: list[Line], net=None, vat=None, who=None) -> LedgerEvent:
    return LedgerEvent(
        id=eid * 32,
        kind=kind,  # type: ignore[arg-type]
        date=when,
        lines=lines,
        net=net,
        vat=vat,
        counterparty=who,
        approved_by=USER,
        approved_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def purchase(eid: str, when: date, account: str, net: int, vat: int, settle="1200 Bank", who="Screwfix"):
    lines = [Line(account=account, debit=net, vat_code=S if vat else N)]
    if vat:
        lines.append(Line(account="2200 VAT control", debit=vat, vat_code=S))
    lines.append(Line(account=settle, credit=net + vat))
    return _ev(eid, "purchase", when, lines, net, vat, who)


def sale(eid: str, when: date, net: int, settle="1100 Debtors", who="Acme Kitchens Ltd"):
    vat = net // 5
    lines = [
        Line(account=settle, debit=net + vat),
        Line(account="4000 Sales", credit=net, vat_code=S),
        Line(account="2200 VAT control", credit=vat, vat_code=S),
    ]
    return _ev(eid, "sale", when, lines, net, vat, who)


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await b.ensure_tree()
    for ev in (
        purchase("1", date(2026, 8, 20), "7500 Office supplies", 10_000, 2_000),
        purchase("2", date(2026, 8, 21), "5000 Materials", 50_000, 10_000, "2100 Creditors", "Howdens Joinery"),
        sale("3", date(2026, 8, 25), 100_000),
        purchase("4", date(2026, 9, 2), "7300 Motor expenses", 6_000, 0, "1210 Cash", "Shell"),
    ):
        await b.post_event(ev)
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


async def trial_balance_ok(books: Books) -> None:
    events = await books.list_events()
    assert sum(ln.debit for e in events for ln in e.lines) == sum(ln.credit for e in events for ln in e.lines)


async def balance(books: Books, account: str, start: date | None = None, end: date | None = None) -> int:
    return sum(
        ln.debit - ln.credit for e in await books.list_events(start, end) for ln in e.lines if ln.account == account
    )


async def submit_q3(fake: FakeStorageProvider) -> None:
    await fake.write(
        f"{VAT_RETURNS}/18A3/return.json",
        json.dumps({"periodKey": "18A3", "obligation": {"start": "2026-07-01", "end": "2026-09-30"}}).encode(),
    )


# --------------------------------------------------------------------------- #
# Chart of accounts
# --------------------------------------------------------------------------- #


def test_default_chart_holds_every_account_the_code_posts_to():
    labels = {a.label for a in ch.default_chart()}
    assert labels >= ch.SYSTEM_ACCOUNTS
    assert all(ch.type_fits(a.code, a.type) for a in ch.default_chart())
    assert len(labels) == len(ch.default_chart())


def test_chart_add_edit_archive_delete(client: TestClient, books: Books):
    r = client.get("/accounting/accounts", headers=H).json()
    assert r["saved"] is False
    office = next(a for a in r["accounts"] if a["code"] == "7500")
    assert office["postings"] == 1 and office["balance_pence"] == 10_000 and office["system"] is True

    r = client.post(
        "/accounting/accounts",
        json={"code": "7650", "name": "Training", "type": "overhead", "vat_default": "E"},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["saved"] is True
    bad = client.post("/accounting/accounts", json={"code": "7651", "name": "Grants", "type": "revenue"}, headers=H)
    assert bad.status_code == 400 and "4000 to 4999" in bad.json()["detail"]
    dup = client.post("/accounting/accounts", json={"code": "7650", "name": "X", "type": "overhead"}, headers=H)
    assert dup.status_code == 400

    # Unused: rename and delete. Used or system: refuse with a sentence.
    assert client.patch("/accounting/accounts/7650", json={"name": "Staff training"}, headers=H).status_code == 200
    r = client.patch("/accounting/accounts/7500", json={"name": "Stationery"}, headers=H)
    assert r.status_code == 400 and "keep the name" in r.json()["detail"]
    r = client.patch("/accounting/accounts/7500", json={"archived": True}, headers=H)
    assert r.status_code == 400 and "can't be archived" in r.json()["detail"]
    r = client.delete("/accounting/accounts/7500", headers=H)
    assert r.status_code == 400
    assert client.patch("/accounting/accounts/7650", json={"archived": True}, headers=H).json()["accounts"]
    assert client.delete("/accounting/accounts/7650", headers=H).status_code == 200
    assert not any(a["code"] == "7650" for a in client.get("/accounting/accounts", headers=H).json()["accounts"])


def test_chart_csv_round_trip_and_all_or_nothing_import(client: TestClient):
    text = client.get("/accounting/accounts/export.csv", headers=H).text
    assert text.startswith("﻿code,name,type,vat_default,archived,description")
    assert "7500,Office supplies,overhead,S,no," in text
    ok = client.post(
        "/accounting/accounts/import",
        json={
            "csv": "code,name,type,vat_default\n"
            "7660,Subscriptions to trade bodies,Overhead,E\n4100,Rental income,revenue,E\n"
        },
        headers=H,
    ).json()
    assert ok["result"]["added"] == ["4100 Rental income", "7660 Subscriptions to trade bodies"] or sorted(
        ok["result"]["added"]
    ) == ["4100 Rental income", "7660 Subscriptions to trade bodies"]
    bad = client.post(
        "/accounting/accounts/import",
        json={"csv": "code,name,type\n7670,Fine,overhead\n9500,Nope,overhead\n"},
        headers=H,
    ).json()
    assert bad["result"]["errors"] and bad["result"]["errors"][0].startswith("Row 3:")
    assert not any(a["code"] == "7670" for a in bad["chart"]["accounts"])  # nothing saved


# --------------------------------------------------------------------------- #
# Manual journals
# --------------------------------------------------------------------------- #


def _journal(**over):
    body = {
        "date": "2026-10-31",
        "narration": "Accrue October electricity",
        "lines": [
            {"account": "7200 Utilities", "debit_pence": 12_345},
            {"account": "2400 Accruals", "credit_pence": 12_345},
        ],
    }
    return {**body, **over}


def test_unbalanced_journal_refused_in_plain_words(client: TestClient):
    body = _journal(lines=[{"account": "7200", "debit_pence": 10_000}, {"account": "2400", "credit_pence": 9_999}])
    r = client.post("/accounting/journals", json=body, headers=H)
    assert r.status_code == 400
    assert r.json()["detail"] == "Debits are £100.00 and credits are £99.99: they must be equal, and are £0.01 apart"
    both = _journal(
        lines=[{"account": "7200", "debit_pence": 1, "credit_pence": 1}, {"account": "2400", "credit_pence": 0}]
    )
    assert "not both or neither" in client.post("/accounting/journals", json=both, headers=H).json()["detail"]
    control = _journal(lines=[{"account": "1100", "debit_pence": 5}, {"account": "4000", "credit_pence": 5}])
    assert "kept by invoices" in client.post("/accounting/journals", json=control, headers=H).json()["detail"]
    unknown = _journal(lines=[{"account": "7777", "debit_pence": 5}, {"account": "2400", "credit_pence": 5}])
    assert "not in your chart" in client.post("/accounting/journals", json=unknown, headers=H).json()["detail"]


async def test_journal_drafts_post_only_on_approval_with_auto_reversal(client: TestClient, books: Books):
    before = len(await books.list_events())
    j = client.post("/accounting/journals", json=_journal(auto_reverse_on="2026-11-01"), headers=H).json()
    assert j["status"] == "draft" and j["number"] == "MJ-0001"
    assert len(await books.list_events()) == before  # a draft posts nothing
    posted = client.post(f"/accounting/journals/{j['id']}/approve", headers=H).json()
    assert posted["status"] == "posted" and posted["reversal_event_id"]
    assert await balance(books, "2400 Accruals", end=date(2026, 10, 31)) == -12_345
    assert await balance(books, "2400 Accruals") == 0  # reversed on 1 Nov
    assert await balance(books, "7200 Utilities", date(2026, 11, 1), date(2026, 11, 30)) == -12_345
    await trial_balance_ok(books)
    again = client.post(f"/accounting/journals/{j['id']}/approve", headers=H)
    assert again.status_code == 409
    listed = client.get("/accounting/journals?status=posted&account=7200", headers=H).json()["journals"]
    assert [x["number"] for x in listed] == ["MJ-0001"]
    assert client.get("/accounting/journals?q=nothing-like-it", headers=H).json()["journals"] == []

    void = client.post(f"/accounting/journals/{j['id']}/void", headers=H).json()
    assert void["status"] == "voided" and len(void["void_event_ids"]) == 2
    assert await balance(books, "7200 Utilities") == 0
    await trial_balance_ok(books)


async def test_journal_with_vat_reaches_the_return_and_the_document_is_evidence(client: TestClient, books: Books, fake):
    await fake.write(f"{RECEIPTS}/2026-10/note.pdf", b"%PDF-1.4 note")
    body = _journal(
        date="2026-10-05",
        narration="Missed fuel receipt",
        vat_box="purchases",
        document_path=f"{RECEIPTS}/2026-10/note.pdf",
        lines=[
            {"account": "7300", "debit_pence": 5_000, "vat_code": "S"},
            {"account": "2200 VAT control", "debit_pence": 1_000},
            {"account": "1200 Bank", "credit_pence": 6_000},
        ],
    )
    j = client.post("/accounting/journals", json=body, headers=H).json()
    assert (j["net_pence"], j["vat_pence"], j["warnings"]) == (5_000, 1_000, [])
    assert j["document_sha256"] and len(j["document_sha256"]) == 64
    client.post(f"/accounting/journals/{j['id']}/approve", headers=H)
    ret = compute_vat_return(await books.list_events(), "Q4", date(2026, 10, 1), date(2026, 12, 31))
    assert ret.vat_reclaimed == 10 and ret.total_purchases_ex_vat == 50
    event = next(e for e in await books.list_events() if e.id == j["event_id"] or e.vat_box)
    assert event.evidence == [j["document_sha256"]]

    no_side = _journal(
        lines=[
            {"account": "7300", "debit_pence": 100},
            {"account": "2200", "debit_pence": 20},
            {"account": "1200", "credit_pence": 120},
        ]
    )
    assert "sales or on purchases" in client.post("/accounting/journals", json=no_side, headers=H).json()["detail"]
    odd = client.post(
        "/accounting/journals",
        json={
            **body,
            "lines": [
                {"account": "7300", "debit_pence": 5_000, "vat_code": "S"},
                {"account": "2200", "debit_pence": 700},
                {"account": "1200", "credit_pence": 5_700},
            ],
            "document_path": None,
        },
        headers=H,
    ).json()
    assert odd["warnings"] and "£7.00" in odd["warnings"][0]


async def test_journals_with_vat_show_on_the_vat_page_in_their_boxes(client: TestClient, books: Books):
    """The VAT page (GET /books/vat) and the HMRC body count a journal on the side it names: a sales journal in
    boxes 1 and 6, a purchases journal in boxes 4 and 7, each listed as an adjustment with its entries counted.
    A void nets it off; an automatic reversal in the next period counts there, with the opposite sign."""
    q4 = {"period_start": "2026-10-01", "period_end": "2026-12-31", "today": "2026-11-10"}
    before = client.get("/books/vat", params=q4, headers=H).json()
    assert [b["entries"] for b in before["boxes"]] == [0] * 9

    def post(body: dict) -> dict:
        j = client.post("/accounting/journals", json=body, headers=H).json()
        r = client.post(f"/accounting/journals/{j['id']}/approve", headers=H)
        assert r.status_code == 200, r.text
        return r.json()

    sale = post(
        _journal(
            date="2026-10-05",
            narration="Cash sale not invoiced",
            vat_box="sales",
            lines=[
                {"account": "1200 Bank", "debit_pence": 12_000},
                {"account": "4000", "credit_pence": 10_000, "vat_code": "S"},
                {"account": "2200", "credit_pence": 2_000},
            ],
        )
    )
    fuel = post(
        _journal(
            date="2026-10-06",
            narration="Missed fuel receipt",
            vat_box="purchases",
            auto_reverse_on="2027-01-04",  # into Jan–Mar 2027: counted there, the other way
            lines=[
                {"account": "7300", "debit_pence": 5_000, "vat_code": "S"},
                {"account": "2200 VAT control", "debit_pence": 1_000},
                {"account": "1200 Bank", "credit_pence": 6_000},
            ],
        )
    )
    v = client.get("/books/vat", params=q4, headers=H).json()
    boxes = {b["box"]: (b["amount"], b["entries"]) for b in v["boxes"]}
    assert boxes[1] == ("20.00", 1) and boxes[6] == ("100", 1)  # the sales journal
    assert boxes[4] == ("10.00", 1) and boxes[7] == ("50", 1)  # the purchases journal
    assert boxes[3] == ("20.00", 1) and boxes[5] == ("10.00", 2)
    assert (v["hmrc_body"]["vatDueSales"], v["hmrc_body"]["vatReclaimedCurrPeriod"]) == (20.0, 10.0)
    assert (v["hmrc_body"]["totalValueSalesExVAT"], v["hmrc_body"]["totalValuePurchasesExVAT"]) == (100, 50)
    assert [(a["name"], a["side"], a["net_pence"], a["vat_pence"], a["note"]) for a in v["adjustments"]] == [
        (f"Journal {sale['number']}", "sales", 10_000, 2_000, "Cash sale not invoiced"),
        (f"Journal {fuel['number']}", "purchases", 5_000, 1_000, "Missed fuel receipt"),
    ]
    next_q = {"period_start": "2027-01-01", "period_end": "2027-03-31", "today": "2027-01-10"}
    n = client.get("/books/vat", params=next_q, headers=H).json()
    nboxes = {b["box"]: (b["amount"], b["entries"]) for b in n["boxes"]}
    assert (nboxes[4], nboxes[5]) == (("-10.00", 1), ("10.00", 1))  # box 5 is absolute; see REVIEW (negative box 4)
    assert [(a["side"], a["net_pence"], a["vat_pence"]) for a in n["adjustments"]] == [("purchases", -5_000, -1_000)]
    assert n["hmrc_body"]["vatReclaimedCurrPeriod"] == -10.0

    # Void the sales journal: its mirror is dated like it (the period is open), so Q4 nets back to nothing on sales.
    client.post(f"/accounting/journals/{sale['id']}/void", headers=H)
    v = client.get("/books/vat", params=q4, headers=H).json()
    boxes = {b["box"]: (b["amount"], b["entries"]) for b in v["boxes"]}
    assert boxes[1] == ("0.00", 2) and boxes[6] == ("0", 2)  # the journal and its void, both shown
    assert [a["net_pence"] for a in v["adjustments"] if a["side"] == "sales"] == [10_000, -10_000]
    await trial_balance_ok(books)


async def test_ask_counts_journals_with_vat_on_their_side(client: TestClient, books: Books):
    """Ask's facts (app/facts.py) total each side with the same rule as the boxes, journals included."""
    from app import facts

    body = _journal(
        date="2026-10-05",
        vat_box="sales",
        lines=[
            {"account": "1200 Bank", "debit_pence": 12_000},
            {"account": "4000", "credit_pence": 10_000, "vat_code": "S"},
            {"account": "2200", "credit_pence": 2_000},
        ],
    )
    j = client.post("/accounting/journals", json=body, headers=H).json()
    j = client.post(f"/accounting/journals/{j['id']}/approve", headers=H).json()
    event = next(e for e in await books.list_events() if e.id == j["event_id"])
    assert facts.side(event) == ("sales", 1)


async def test_journal_with_vat_refused_in_a_submitted_period(client: TestClient, books: Books, fake):
    await submit_q3(fake)
    body = _journal(
        date="2026-09-15",
        vat_box="purchases",
        lines=[
            {"account": "7300", "debit_pence": 500, "vat_code": "S"},
            {"account": "2200", "debit_pence": 100},
            {"account": "1200", "credit_pence": 600},
        ],
    )
    j = client.post("/accounting/journals", json=body, headers=H).json()
    r = client.post(f"/accounting/journals/{j['id']}/approve", headers=H)
    assert r.status_code == 400
    assert r.json()["detail"].startswith("The VAT return for Jul–Sep 2026 has been submitted")


# --------------------------------------------------------------------------- #
# Fixed assets
# --------------------------------------------------------------------------- #


async def _laptop(client: TestClient, books: Books, **over):
    # The purchase, coded to the asset account: £1,200 + VAT on 15 Apr 2026.
    await books.post_event(purchase("5", date(2026, 4, 15), "0050 Computer equipment", 120_000, 24_000))
    body = {
        "name": "Laptop",
        "asset_type": "computer",
        "purchase_date": "2026-04-15",
        "cost_pence": 120_000,
        "method": "straight_line",
        "life_years": 3,
        "frequency": "monthly",
        **over,
    }
    r = client.post("/accounting/assets", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


async def test_run_depreciation_proposes_a_journal_and_reconciles(client: TestClient, books: Books):
    asset = await _laptop(client, books)
    assert asset["cost_account"] == "0050 Computer equipment"
    assert asset["accumulated_account"] == "0051 Computer equipment depreciation"
    run = client.post("/accounting/assets/depreciation", json={"to": "2026-06-10"}, headers=H).json()
    j = run["journal"]
    # Apr, May, Jun at 120,000 / 36 = 3,333.33: cumulative 3,333, 6,667, 10,000.
    assert j["source"] == "depreciation" and j["asset_charges"][0]["amount_pence"] == 10_000
    assert j["asset_charges"][0]["periods"] == 3 and j["date"] == "2026-06-30"
    again = client.post("/accounting/assets/depreciation", json={"to": "2026-07-31"}, headers=H)
    assert again.status_code == 400 and "waiting for approval" in again.json()["detail"]
    client.post(f"/accounting/journals/{j['id']}/approve", headers=H)
    view = client.get("/accounting/assets", headers=H).json()
    row = view["assets"][0]
    assert row["book_value_pence"] == 110_000 and row["state"]["depreciated_to"] == "2026-06-30"
    assert "Capital allowances" in view["note"]
    assert all(r["difference_pence"] == 0 for r in view["reconciliation"])
    assert (
        client.post("/accounting/assets/depreciation", json={"to": "2026-06-30"}, headers=H).json()["journal"] is None
    )
    sched = client.get(f"/accounting/assets/{asset['id']}/schedule", headers=H).json()["periods"]
    assert len(sched) == 36 and sched[2]["posted"] and not sched[3]["posted"]
    assert sum(p["charge_pence"] for p in sched) == 120_000
    assert await balance(books, "8000 Depreciation") == 10_000
    await trial_balance_ok(books)


async def test_disposal_with_catch_up_and_a_loss(client: TestClient, books: Books):
    asset = await _laptop(client, books)
    j = client.post("/accounting/assets/depreciation", json={"to": "2026-06-30"}, headers=H).json()["journal"]
    client.post(f"/accounting/journals/{j['id']}/approve", headers=H)
    # Sold 20 Aug 2026 for £900 + £180 VAT. Catch-up: July (cumulative 13,333 → 3,333). Accumulated 13,333.
    # Book value 120,000 − 13,333 = 106,667; proceeds 90,000: loss 16,667.
    d = client.post(
        f"/accounting/assets/{asset['id']}/dispose",
        json={"date": "2026-08-20", "proceeds_pence": 90_000, "vat_pence": 18_000},
        headers=H,
    ).json()
    assert d["disposal"]["gain_pence"] == -16_667 and d["disposal"]["catch_up"]["amount_pence"] == 3_333
    assert (d["vat_box"], d["net_pence"], d["vat_pence"]) == ("sales", 90_000, 18_000)
    client.post(f"/accounting/journals/{d['id']}/approve", headers=H)
    assert await balance(books, "0050 Computer equipment") == 0
    assert await balance(books, "0051 Computer equipment depreciation") == 0
    assert await balance(books, "8010 Profit or loss on disposal of assets") == 16_667
    view = client.get("/accounting/assets", headers=H).json()
    assert view["assets"][0]["status"] == "disposed"
    assert all(r["difference_pence"] == 0 for r in view["reconciliation"])
    await trial_balance_ok(books)
    # The earlier depreciation journal can't be voided now the asset has been disposed of.
    assert client.post(f"/accounting/journals/{j['id']}/void", headers=H).status_code == 400


async def test_reducing_balance_yearly_and_bad_policies(client: TestClient, books: Books):
    a = await _laptop(client, books, method="reducing_balance", life_years=None, rate_percent=25, frequency="yearly")
    j = client.post("/accounting/assets/depreciation", json={"to": "2027-03-31"}, headers=H).json()["journal"]
    assert j["asset_charges"][0]["amount_pence"] == 30_000  # 25 % of 120,000 for Apr 2026–Mar 2027
    assert a["number"] == "FA-0001"
    bad = client.post(
        "/accounting/assets",
        json={
            "name": "Van",
            "asset_type": "motor",
            "purchase_date": "2026-01-01",
            "cost_pence": 100,
            "method": "reducing_balance",
        },
        headers=H,
    )
    assert bad.status_code == 400 and "rate" in bad.json()["detail"]


# --------------------------------------------------------------------------- #
# Find and recode
# --------------------------------------------------------------------------- #


async def test_account_recode_adds_an_adjusting_entry_and_keeps_history(client: TestClient, books: Books):
    found = client.get("/accounting/recode/search?account=7500", headers=H).json()["lines"]
    assert len(found) == 1 and found[0]["recodable"] and found[0]["debit_pence"] == 10_000
    ref = {"event_id": found[0]["event_id"], "line": found[0]["line"]}
    before = [e.model_dump() for e in await books.list_events()]
    preview = client.post(
        "/accounting/recode", json={"lines": [ref], "account": "0030 Office equipment"}, headers=H
    ).json()
    assert preview["posted"] is False and len(await books.list_events()) == len(before)
    assert preview["events"][0]["lines"][0] == {
        "account": "0030 Office equipment",
        "debit_pence": 10_000,
        "credit_pence": 0,
        "vat_code": "S",
    }
    done = client.post(
        "/accounting/recode", json={"lines": [ref], "account": "0030", "confirm": True}, headers=H
    ).json()
    assert done["posted"] is True
    events = await books.list_events()
    assert [e.model_dump() for e in events if not e.recodes] == before  # nothing edited
    assert await balance(books, "7500 Office supplies") == 0
    assert await balance(books, "0030 Office equipment") == 10_000
    await trial_balance_ok(books)
    ret = compute_vat_return(events, "Q3", *Q3)
    assert ret.vat_reclaimed == 120 and ret.total_purchases_ex_vat == 660  # unchanged by an account recode
    # The line now shows on its new account; recoding it again moves it from there.
    now = client.get("/accounting/recode/search?account=0030", headers=H).json()["lines"]
    assert now[0]["recoded"] is True and now[0]["account"] == "0030 Office equipment"
    income = client.post("/accounting/recode", json={"lines": [ref], "account": "4000"}, headers=H)
    assert income.status_code == 400 and "can't move to" in income.json()["detail"]


async def test_vat_recode_keeps_the_gross_and_corrects_the_return(client: TestClient, books: Books):
    line = next(x for x in client.get("/accounting/recode/search?account=5000", headers=H).json()["lines"])
    assert line["vat_recodable"]
    body = {"lines": [{"event_id": line["event_id"], "line": line["line"]}], "vat_code": "Z", "confirm": True}
    r = client.post("/accounting/recode", json=body, headers=H).json()
    ev = r["events"][0]
    # Gross 60,000 at zero rate: net 60,000, no VAT. Net +10,000, VAT −10,000 on the purchases side.
    assert (ev["vat_box"], ev["net_change_pence"], ev["vat_change_pence"]) == ("purchases", 10_000, -10_000)
    assert await balance(books, "5000 Materials") == 60_000
    assert await balance(books, "2100 Creditors") == -60_000  # what is owed to Howdens is unchanged
    ret = compute_vat_return(await books.list_events(), "Q3", *Q3)
    assert ret.vat_reclaimed == 20 and ret.total_purchases_ex_vat == 760
    await trial_balance_ok(books)
    # And back to standard rate: 60,000 × 20/120 = 10,000 VAT again.
    back = client.post("/accounting/recode", json={**body, "vat_code": "S"}, headers=H).json()["events"][0]
    assert back["vat_change_pence"] == 10_000
    assert compute_vat_return(await books.list_events(), "Q3", *Q3).vat_reclaimed == 120


async def test_recode_refused_for_submitted_periods_and_control_accounts(client: TestClient, books: Books, fake):
    lines = client.get("/accounting/recode/search?from=2026-08-01&to=2026-08-31", headers=H).json()["lines"]
    bank = next(x for x in lines if x["account"] == "1200 Bank")
    assert not bank["recodable"] and "can't be recoded" in bank["reason"]
    await submit_q3(fake)
    office = next(x for x in client.get("/accounting/recode/search?account=7500", headers=H).json()["lines"])
    assert not office["recodable"]
    r = client.post(
        "/accounting/recode",
        json={"lines": [{"event_id": office["event_id"], "line": 0}], "account": "7510", "confirm": True},
        headers=H,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "The VAT return for Jul–Sep 2026 has been submitted, so entries dated in it can't be recoded"
    )


# --------------------------------------------------------------------------- #
# Tracking
# --------------------------------------------------------------------------- #


async def test_tracking_categories_journal_lines_and_summary(client: TestClient, books: Books):
    cfg = client.post("/accounting/tracking/categories", json={"name": "Department"}, headers=H).json()
    dept = cfg["categories"][0]["id"]
    client.post("/accounting/tracking/categories", json={"name": "Project"}, headers=H)
    third = client.post("/accounting/tracking/categories", json={"name": "Region"}, headers=H)
    assert third.status_code == 400 and "2 tracking categories" in third.json()["detail"]
    cfg = client.post(f"/accounting/tracking/categories/{dept}/options", json={"name": "Kitchens"}, headers=H).json()
    cfg = client.post(f"/accounting/tracking/categories/{dept}/options", json={"name": "Bathrooms"}, headers=H).json()
    kitchens, bathrooms = (o["id"] for o in cfg["categories"][0]["options"])
    j = client.post(
        "/accounting/journals",
        json={
            "date": "2026-09-30",
            "narration": "Split the sundry costs",
            "lines": [
                {"account": "7999", "debit_pence": 3_000, "tracking": {dept: kitchens}},
                {"account": "7999", "debit_pence": 1_000, "tracking": {dept: bathrooms}},
                {"account": "1200", "credit_pence": 4_000},
            ],
        },
        headers=H,
    ).json()
    client.post(f"/accounting/journals/{j['id']}/approve", headers=H)
    s = client.get(f"/reports/tracking?category={dept}&from=2026-07-01&to=2026-09-30", headers=H).json()
    sundry = next(r for r in s["rows"] if r["account"] == "7999 Sundry expenses")
    assert sundry["by_option"] == {kitchens: 3_000, bathrooms: 1_000, "unassigned": 0}
    assert s["totals"]["sales"]["unassigned"] == 100_000
    assert s["totals"]["net_profit"][kitchens] == -3_000
    assert [c["name"] for c in s["columns"]] == ["Kitchens", "Bathrooms", "Unassigned"]
    # In use: the category can't be deleted; an archived option can't tag new lines.
    assert client.delete(f"/accounting/tracking/categories/{dept}", headers=H).status_code == 400
    client.patch(f"/accounting/tracking/categories/{dept}/options/{kitchens}", json={"archived": True}, headers=H)
    r = client.post(
        "/accounting/journals",
        json={
            "date": "2026-09-30",
            "narration": "x",
            "lines": [
                {"account": "7999", "debit_pence": 1, "tracking": {dept: kitchens}},
                {"account": "1200", "credit_pence": 1},
            ],
        },
        headers=H,
    )
    assert r.status_code == 400 and "archived" in r.json()["detail"]


def test_invoice_lines_carry_tracking_into_the_sale():
    from decimal import Decimal

    from app.invoicing import InvoiceCustomer, InvoiceDraft, InvoiceProfile, LineIn, build_invoice, sale_event

    draft = InvoiceDraft(
        customer=InvoiceCustomer(name="Acme"),
        issue_date=date(2026, 10, 1),
        lines=[
            LineIn(description="Kitchen", quantity=Decimal(1), unit_price_pence=10_000, tracking={"d": "k"}),
            LineIn(description="Bathroom", quantity=Decimal(1), unit_price_pence=5_000, tracking={"d": "b"}),
            LineIn(description="Untagged", quantity=Decimal(1), unit_price_pence=2_000),
        ],
    )
    ev = sale_event(build_invoice("INV-0009", draft, InvoiceProfile(), USER), USER, [])
    sales = [(ln.credit, ln.tracking) for ln in ev.lines if ln.account == "4000 Sales"]
    assert sales == [(10_000, {"d": "k"}), (5_000, {"d": "b"}), (2_000, None)]
    assert ev.net == 17_000 and ev.vat == 3_400


async def test_bill_approval_tags_its_cost_lines():
    from app.approve import with_tracking

    ev = with_tracking(purchase("6", date(2026, 9, 1), "5000 Materials", 100, 20), {"d": "k"})
    assert [ln.tracking for ln in ev.lines] == [{"d": "k"}, None, None]


# --------------------------------------------------------------------------- #
# Budgets
# --------------------------------------------------------------------------- #


def test_budget_summary_and_variance(client: TestClient):
    months = [0] * 12
    body = {
        "name": "FY 2026-27",
        "lines": [
            {"account": "4000", "months": [0, 0, 0, 0, 90_000, 0, 0, 0, 0, 0, 0, 0]},  # Aug: 90,000
            {"account": "7500", "months": [0, 0, 0, 0, 12_000, 0, 0, 0, 0, 0, 0, 0]},
            {"account": "7300", "months": months},
        ],
    }
    r = client.put("/reports/budgets/2026-04", json=body, headers=H)
    assert r.status_code == 200 and [ln["account"] for ln in r.json()["lines"]] == [
        "4000 Sales",
        "7500 Office supplies",
    ]
    bs = client.put("/reports/budgets/2026-04", json={"lines": [{"account": "1200", "months": months}]}, headers=H)
    assert bs.status_code == 400 and "not a profit and loss account" in bs.json()["detail"]
    s = client.get("/reports/budgets/2026-04/summary", headers=H).json()
    assert s["months"][0] == "Apr 2026" and s["net_profit"][4] == 78_000 and s["net_profit_total_pence"] == 78_000
    v = client.get("/reports/budgets/2026-04/variance?through=2026-09", headers=H).json()
    rows = {x["account"]: x for x in v["rows"]}
    # Sales: actual 100,000 vs 90,000 → +10,000 (11.1 %), favourable. Office: 10,000 vs 12,000 → −2,000, favourable.
    assert (
        rows["4000 Sales"]["variance_pence"],
        rows["4000 Sales"]["variance_percent"],
        rows["4000 Sales"]["favourable"],
    ) == (10_000, 11.1, True)
    assert (rows["7500 Office supplies"]["variance_pence"], rows["7500 Office supplies"]["favourable"]) == (
        -2_000,
        True,
    )
    # Unbudgeted costs show with a budget of 0: Materials 50,000 and Motor 6,000 are adverse.
    assert rows["5000 Materials"]["favourable"] is False and rows["5000 Materials"]["variance_percent"] is None
    net = v["totals"]["net_profit"]
    assert (net["budget_pence"], net["actual_pence"]) == (78_000, 100_000 - 50_000 - 10_000 - 6_000)
    assert v["months"] == 6 and v["period_end"] == "2026-09-30"
    assert client.get("/reports/budgets/2026-04/variance?through=2027-06", headers=H).status_code == 400


def test_budget_variance_pure():
    b = bg.Budget(start="2026-01", lines=[bg.BudgetLine(account="7500 Office supplies", months=[1_000] * 12)])
    v = bg.variance(b, [], "2026-03")
    assert v.rows[0].budget_pence == 3_000 and v.rows[0].variance_pence == -3_000 and v.rows[0].favourable is True


# --------------------------------------------------------------------------- #
# Short-term cash flow
# --------------------------------------------------------------------------- #


async def test_cash_flow_by_due_date(client: TestClient, books: Books):
    # Open: Acme invoice 120,000 dated 25 Aug (due + 30 days = 24 Sep: overdue on 10 Oct); Howdens bill 60,000 dated
    # 21 Aug (due 20 Sep: overdue). A new invoice dated 1 Oct is due 31 Oct (21 days on).
    await books.post_event(sale("7", date(2026, 10, 1), 50_000))
    r = client.get("/reports/cashflow?today=2026-10-10", headers=H).json()
    # Bank: −12,000 (office) ; cash −6,000 → opening −18,000.
    assert r["opening_balance_pence"] == -18_000 and r["bank_accounts"] == ["1200 Bank", "1210 Cash"]
    overdue, next30 = r["buckets"][0], r["buckets"][1]
    assert (overdue["money_in_pence"], overdue["money_out_pence"]) == (120_000, 60_000)
    assert next30["money_in_pence"] == 60_000 and next30["start"] == "2026-10-10" and next30["end"] == "2026-11-09"
    p30 = r["points"][0]
    assert (p30["date"], p30["balance_pence"]) == ("2026-11-09", -18_000 + 180_000 - 60_000)
    assert r["repeating"] == [] and "repeating invoices and bills not made yet" in r["not_included"]
    assert r["lowest_balance_pence"] == -18_000 - 60_000 and r["lowest_on"] == "2026-10-10"


def test_cash_line_is_dropped_when_it_quotes_a_figure_not_in_the_forecast():
    facts = {"bank_balance_today": "£1,200.00", "balance_in_30_days": "£800.00"}
    assert cf.check_line("Your bank is £1,200.00 today and £800.00 in 30 days.", facts)
    assert cf.check_line("You will have £950.00 in 30 days.", facts) is None


async def test_undoing_a_recoded_entry_unwinds_its_recodes_and_journals_are_voided_not_undone(
    client: TestClient, books: Books
):
    from app.approve import ApprovalError, undo

    line = client.get("/accounting/recode/search?account=7500", headers=H).json()["lines"][0]
    body = {"lines": [{"event_id": line["event_id"], "line": 0}], "account": "7510", "confirm": True}
    client.post("/accounting/recode", json=body, headers=H)
    await undo(books, line["event_id"], USER)
    assert await balance(books, "7500 Office supplies") == 0
    assert await balance(books, "7510 Software & subscriptions") == 0
    await trial_balance_ok(books)
    assert client.get("/accounting/recode/search?account=751", headers=H).json()["lines"] == []

    j = client.post("/accounting/journals", json=_journal(), headers=H).json()
    j = client.post(f"/accounting/journals/{j['id']}/approve", headers=H).json()
    with pytest.raises(ApprovalError, match="void it on Manual journals"):
        await undo(books, j["event_id"], USER)
    client.post(f"/accounting/journals/{j['id']}/void", headers=H)
    assert client.get("/accounting/recode/search?account=7200", headers=H).json()["lines"] == []
