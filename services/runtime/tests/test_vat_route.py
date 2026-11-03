from datetime import date, datetime

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app.books import Books


async def test_list_events_and_vat_route():
    fake = FakeStorageProvider()
    books = Books(fake)
    await books.ensure_tree()
    approved = dict(approved_by="sam@example.co.uk", approved_at=datetime(2026, 9, 21, 12, 0))
    ev = LedgerEvent(
        kind="purchase",
        date=date(2026, 9, 21),
        net=3206,
        vat=641,
        lines=[
            Line(account="5100 Tools", debit=3206, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=641),
            Line(account="1200 Bank", credit=3847),
        ],
        **approved,
    )
    outside = ev.model_copy(update={"id": "x" * 32, "date": date(2026, 10, 2)})
    await books.post_event(ev)
    await books.post_event(outside)
    assert [e.id for e in await books.list_events(date(2026, 7, 1), date(2026, 9, 30))] == [ev.id]
    assert len(await books.list_events()) == 2

    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        r = TestClient(app).get(
            "/books/vat?start=2026-07-01&end=2026-09-30&period_key=26A3", headers={"X-Graph-Token": "t"}
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["boxes"][3]["amount"] == "6.41" and body["boxes"][6]["amount"] == "32"
    assert body["hmrc_body"]["netVatDue"] == 6.41 and body["events_in_period"] == 1


async def test_reversal_counts_against_the_box_it_reverses():
    from datetime import UTC

    from app.approve import reversal_of

    fake = FakeStorageProvider()
    books = Books(fake)
    await books.ensure_tree()
    approved = dict(approved_by="sam@example.co.uk", approved_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC))
    sale = LedgerEvent(
        kind="sale",
        date=date(2026, 9, 21),
        net=10000,
        vat=2000,
        lines=[
            Line(account="1100 Debtors", debit=12000),
            Line(account="4000 Sales", credit=10000, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", credit=2000, vat_code=VatCode.STANDARD),
        ],
        **approved,
    )
    purchase = LedgerEvent(
        kind="purchase",
        date=date(2026, 9, 22),
        net=3206,
        vat=641,
        lines=[
            Line(account="5100 Tools", debit=3206, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=641),
            Line(account="1200 Bank", credit=3847),
        ],
        **approved,
    )
    await books.post_event(sale)
    await books.post_event(purchase)
    await books.post_event(reversal_of(purchase, "sam@example.co.uk"))

    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        r = TestClient(app).get(
            "/books/vat?start=2026-07-01&end=2026-09-30&period_key=26A3", headers={"X-Graph-Token": "t"}
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    by_box = {b["box"]: b for b in body["boxes"]}
    assert by_box[1]["entries"] == by_box[3]["entries"] == by_box[6]["entries"] == 1
    assert by_box[4]["entries"] == by_box[7]["entries"] == 2  # the purchase and its reversal
    assert by_box[5]["entries"] == 3
    assert by_box[4]["amount"] == "0.00"  # the reversal nets the purchase off
    assert body["events_in_period"] == 3 and body["undone_in_period"] == 1


async def test_box5_says_reclaim_and_the_due_period_is_named():
    """Box 4 larger than Box 3: Box 5 reads as money back, not "to pay"; the ended period still to file is named."""
    books = Books(FakeStorageProvider())
    await books.ensure_tree()
    ev = LedgerEvent(
        kind="purchase",
        date=date(2026, 9, 21),
        net=10500,
        vat=2100,
        lines=[
            Line(account="5100 Tools", debit=10500, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=2100),
            Line(account="1200 Bank", credit=12600),
        ],
        approved_by="sam@example.co.uk",
        approved_at=datetime(2026, 9, 21, 12, 0),
    )
    await books.post_event(ev)
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        c = TestClient(app)
        q3 = c.get("/books/vat?period=2026-Q3&today=2026-10-05&stagger=1", headers={"X-Graph-Token": "t"}).json()
        q4 = c.get("/books/vat?today=2026-10-05&stagger=1", headers={"X-Graph-Token": "t"}).json()
        late = c.get("/books/vat?today=2026-11-20&stagger=1", headers={"X-Graph-Token": "t"}).json()
    finally:
        app.dependency_overrides.clear()
    assert q3["box5_direction"] == "reclaim" and q3["boxes"][4]["label"] == "Net VAT to reclaim from HMRC (4 − 3)"
    assert q3["boxes"][4]["amount"] == "21.00"
    assert q4["box5_direction"] == "nil" and "nothing to pay or reclaim" in q4["boxes"][4]["label"]
    assert q4["due_period"] == {
        "period": "2026-Q3",
        "start": "2026-07-01",
        "end": "2026-09-30",
        "label": "Jul–Sep 2026",
        "deadline": "2026-11-07",
    }
    assert late["due_period"] is None  # past its deadline: nothing "due next" to open on
