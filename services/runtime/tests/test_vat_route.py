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
