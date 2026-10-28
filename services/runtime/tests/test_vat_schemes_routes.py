"""VAT schemes through the runtime: Settings (GET/PUT /books/vat/schemes), the VAT return, periods, deadlines, the VAT
report and the Ask facts, on fake storage. The scheme rules themselves are tested in packages/ledger."""

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app.books import Books
from app.facts import build_facts
from app.schemas import AskPeriod
from app.settlement import PAYMENTS
from app.vat_cycle import VatCycle
from app.vat_schemes import SCHEMES_PATH

APPROVED = dict(approved_by="sam@example.co.uk", approved_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC))
H = {"X-Graph-Token": "t", "X-User": "sam@example.co.uk"}
TODAY = "today=2026-10-27"


def sale(net: int, vat: int, day: date, eid: str, code: VatCode = VatCode.STANDARD) -> LedgerEvent:
    return LedgerEvent(
        id=eid,
        kind="sale",
        date=day,
        net=net,
        vat=vat,
        counterparty="JM Trading",
        lines=[
            Line(account="1100 Debtors", debit=net + vat),
            Line(account="4000 Sales", credit=net, vat_code=code),
            *([Line(account="2200 VAT control", credit=vat)] if vat else []),
        ],
        **APPROVED,
    )


def purchase(net: int, vat: int, day: date, eid: str, account: str = "5000 Materials") -> LedgerEvent:
    return LedgerEvent(
        id=eid,
        kind="purchase",
        date=day,
        net=net,
        vat=vat,
        counterparty="Screwfix",
        lines=[
            Line(account=account, debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=vat),
            Line(account="1200 Bank", credit=net + vat),
        ],
        **APPROVED,
    )


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.ensure_tree()
    return b


@pytest.fixture
def client(books: Books) -> Iterator[TestClient]:
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def put(client: TestClient, body: dict, query: str = TODAY):
    return client.put(f"/books/vat/schemes?{query}", json=body, headers=H)


FLAT_RATE = {
    "registered_on": "2024-01-01",
    "schemes": [
        {"from": "2024-01-01", "scheme": "standard"},
        {"from": "2026-07-01", "scheme": "flat_rate", "flat_rate": {"sector": "Photography", "limited_cost": "no"}},
    ],
}


async def test_flat_rate_saved_in_the_books_and_used_for_the_return(books: Books, client: TestClient):
    await books.post_event(sale(100_000, 20_000, date(2026, 8, 3), "s1"))
    await books.post_event(purchase(50_000, 10_000, date(2026, 8, 4), "p1"))
    r = put(client, FLAT_RATE)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["current"]["scheme"] == "flat_rate" and view["current"]["flat_rate_percent"] == "11"
    assert view["current"]["since"] == "2026-07-01"
    saved = await books.read_json(SCHEMES_PATH, None)
    assert saved["schemes"][1]["from"] == "2026-07-01" and saved["updated_by"] == "sam@example.co.uk"

    r = client.get(f"/books/vat?period=2026-Q3&{TODAY}", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    hmrc = body["hmrc_body"]
    assert (hmrc["vatDueSales"], hmrc["vatReclaimedCurrPeriod"], hmrc["totalValueSalesExVAT"]) == (132.0, 0.0, 1200)
    seg = body["scheme"]["segments"][0]
    assert seg["label"] == "Flat Rate Scheme: Photography, basic turnover"
    assert seg["calcs"] == [
        {
            "start": "2026-07-01",
            "end": "2026-09-30",
            "percent": "11",
            "turnover": "1200.00",
            "tax": "132.00",
            "first_year": False,
        }
    ]
    assert body["scheme"]["sources"]["flat_rate"].startswith("https://www.gov.uk/")
    # Before the scheme: standard accounting, unchanged.
    await books.post_event(sale(10_000, 2_000, date(2026, 5, 1), "s0"))
    q2 = client.get(f"/books/vat?period=2026-Q2&{TODAY}", headers=H).json()
    assert q2["hmrc_body"]["vatDueSales"] == 20.0 and q2["scheme"]["segments"][0]["scheme"] == "standard"


async def test_save_is_audited_and_rules_are_enforced(books: Books, client: TestClient):
    assert put(client, FLAT_RATE).status_code == 200
    audit = await books.storage.read(f"_System/audit/{datetime.now(UTC):%Y-%m}.jsonl")
    assert b'"vat_schemes_saved"' in audit and b"sam@example.co.uk" in audit

    mid = {"schemes": [{"from": "2024-01-01", "scheme": "standard"}, {"from": "2026-08-15", "scheme": "cash"}]}
    r = put(client, mid)
    assert r.status_code == 400 and "Notice 731" in r.json()["detail"]

    unknown = {"schemes": [{"from": "2026-07-01", "scheme": "flat_rate", "flat_rate": {"sector": "Wizardry"}}]}
    assert put(client, unknown).status_code == 422

    rejoin = {
        "schemes": [
            {"from": "2025-01-01", "scheme": "flat_rate", "flat_rate": {"sector": "Photography"}},
            {"from": "2025-07-01", "scheme": "standard"},
            {"from": "2026-01-01", "scheme": "flat_rate", "flat_rate": {"sector": "Photography"}},
        ]
    }
    r = put(client, rejoin)
    assert r.status_code == 400 and "12 months" in r.json()["detail"]

    stagger2 = {"schemes": [{"from": "2026-08-01", "scheme": "cash"}]}
    assert put(client, stagger2, f"{TODAY}&stagger=2").status_code == 200  # Aug starts a stagger 2 quarter
    assert put(client, {"annual": {"start": "2026-02-01"}}, TODAY).status_code == 400  # Feb: not a stagger 1 start
    # A saved flat rate without a registration date, starting in the past: allowed, with warnings.
    warned = put(client, {"schemes": [{"from": "2026-01-01", "scheme": "flat_rate", "flat_rate": {"sector": "Pubs"}}]})
    assert warned.status_code == 200
    assert any("registration date" in w for w in warned.json()["warnings"])
    assert any("in the past" in w for w in warned.json()["warnings"])


async def test_cash_accounting_counts_payments_received(books: Books, client: TestClient):
    """Notice 731 §8.1 through the runtime: £780 of a £1,200 invoice paid in Q3, the rest in Q4."""
    await books.post_event(sale(100_000, 20_000, date(2026, 7, 10), "inv1"))
    await books.write_json(
        PAYMENTS,
        [
            {
                "id": "pay1",
                "side": "sale",
                "date": "2026-08-10",
                "amount_pence": 78_000,
                "counterparty": "JM Trading",
                "allocations": [{"event_id": "inv1", "amount_pence": 78_000}],
                "created_by": "sam@example.co.uk",
                "created_at": "2026-08-10T10:00:00Z",
            },
            {
                "id": "pay2",
                "side": "sale",
                "date": "2026-10-05",
                "amount_pence": 42_000,
                "counterparty": "JM Trading",
                "allocations": [{"event_id": "inv1", "amount_pence": 42_000}],
                "created_by": "sam@example.co.uk",
                "created_at": "2026-10-05T10:00:00Z",
            },
        ],
    )
    assert put(client, {"schemes": [{"from": "2026-07-01", "scheme": "cash"}]}).status_code == 200
    q3 = client.get(f"/books/vat?period=2026-Q3&{TODAY}", headers=H).json()
    assert q3["hmrc_body"]["vatDueSales"] == 130.0 and q3["hmrc_body"]["totalValueSalesExVAT"] == 650
    assert q3["scheme"]["segments"][0]["payments"] == 1
    q4 = client.get(f"/books/vat?period=2026-Q4&{TODAY}", headers=H).json()
    assert q4["hmrc_body"]["vatDueSales"] == 70.0
    assert q4["boxes"][0]["entries"] == 1  # the invoice dated in Q3 is what Q4's box 1 counts
    deadlines = client.get(f"/books/deadlines?{TODAY}", headers=H).json()
    assert deadlines["current"]["box5"] == "70.00" and deadlines["due"]["box5"] == "130.00"


async def test_annual_accounting_periods_instalments_and_deadlines(books: Books, client: TestClient):
    for m in range(1, 11):
        await books.post_event(sale(100_000, 20_000, date(2026, m, 5), f"s{m}"))
    body = {"annual": {"start": "2026-01-01", "instalments": "monthly", "basis_pence": 1_000_000}}
    view = put(client, body).json()
    assert view["current"]["annual"] and view["current"]["annual_period"] == ["2026-01-01", "2026-12-31"]

    periods = client.get(f"/books/vat/periods?{TODAY}", headers=H).json()["periods"]
    assert periods[0]["period"] == "2026-Y01" and periods[0]["annual"] and periods[0]["deadline"] == "2027-02-28"
    assert periods[1]["period"] == "2025-Q4" and not periods[1]["annual"]  # quarters before joining

    ret = client.get(f"/books/vat?period=2026-Y01&{TODAY}", headers=H).json()
    assert ret["start"] == "2026-01-01" and ret["end"] == "2026-12-31" and ret["hmrc_body"]["netVatDue"] == 2000.0
    annual = ret["scheme"]["annual"]
    assert [i["amount"] for i in annual["instalments"]] == ["1000.00"] * 9
    assert annual["instalments"][0]["due"] == "2026-04-30" and annual["return_due"] == "2027-02-28"
    assert (annual["balancing"], annual["balancing_direction"]) == ("7000.00", "refund")  # £2,000 owed, £9,000 paid

    d = client.get(f"/books/deadlines?{TODAY}", headers=H).json()
    assert d["annual"] and d["current"]["deadline"] == "2027-02-28" and len(d["instalments"]) == 9
    assert "Notice 732" in d["rule"] and d["due"] is None  # Oct–Dec 2025 was due on 7 Feb 2026
    assert client.get(f"/books/vat?period=2026-Y02&{TODAY}", headers=H).status_code == 422


async def test_reports_and_ask_facts_use_the_scheme(books: Books, client: TestClient):
    await books.post_event(sale(100_000, 20_000, date(2026, 8, 3), "s1"))
    put(client, FLAT_RATE)
    report = client.get(f"/reports/vat?periods=2&{TODAY}", headers=H).json()
    q3 = next(p for p in report["periods"] if p["period"] == "2026-Q3")
    assert q3["vat_on_sales_pence"] == 13_200 and q3["sales_ex_vat_pounds"] == 1200
    assert report["scheme"].startswith("Flat Rate Scheme: Photography")

    facts = await build_facts(books, AskPeriod(start=date(2026, 7, 1), end=date(2026, 9, 30)), None, VatCycle())
    assert facts["this_period"]["vat"]["box1"] == "132.00"
    part = facts["vat_scheme"]["parts"][0]
    assert part["scheme"].startswith("Flat Rate Scheme") and part["rates_used"][0]["percent"] == "11"


async def test_eligibility_from_the_books(books: Books, client: TestClient):
    """Notice 733 §3.1 (£150,000 to join) from the last 12 months of sales, or the business's own estimate."""
    for m in range(1, 11):
        await books.post_event(sale(2_000_000, 400_000, date(2026, m, 5), f"big{m}"))
    view = put(client, FLAT_RATE).json()
    join = next(c for c in view["checks"] if c["scheme"] == "flat_rate" and c["limit"] == "150000.00")
    assert join["status"] == "warn" and join["basis"] == "books" and join["figure"] == "200000.00"
    view = put(client, {**FLAT_RATE, "estimates": {"taxable_turnover_pence": 12_000_000}}).json()
    join = next(c for c in view["checks"] if c["scheme"] == "flat_rate" and c["limit"] == "150000.00")
    assert join["status"] == "ok" and join["basis"] == "estimate"

    cash = put(client, {"schemes": [{"from": "2026-07-01", "scheme": "cash"}]}).json()
    assert all(c["status"] != "stop" for c in cash["checks"])  # £200,000 is well under £1.6m


async def test_flat_rate_anniversary_leaving_test(books: Books, client: TestClient):
    """Notice 733 §12.2(a): at the anniversary, income for the year over £230,000 → leave at the end of that period."""
    for m in range(1, 13):
        await books.post_event(sale(2_000_000, 400_000, date(2025, m, 5), f"y{m}"))
    body = {"schemes": [{"from": "2025-01-01", "scheme": "flat_rate", "flat_rate": {"sector": "Photography"}}]}
    view = put(client, body, "today=2026-02-10").json()
    stop = next(c for c in view["checks"] if c["status"] == "stop")
    assert stop["figure"] == "288000.00" and "31 Mar 2026" in stop["message"]


async def test_unreadable_schemes_file_means_standard_accounting(books: Books, client: TestClient):
    await books.post_event(sale(100_000, 20_000, date(2026, 8, 3), "s1"))
    await books.storage.write(SCHEMES_PATH, b"{not json")
    r = client.get(f"/books/vat?period=2026-Q3&{TODAY}", headers=H)
    assert r.status_code == 200 and r.json()["hmrc_body"]["vatDueSales"] == 200.0 and r.json()["scheme"] is None
    await books.write_json(SCHEMES_PATH, {"schemes": [{"from": "nope"}]})
    assert client.get(f"/books/vat/schemes?{TODAY}", headers=H).json()["current"]["scheme"] == "standard"


async def test_capital_goods_marked_in_settings(books: Books, client: TestClient):
    await books.post_event(sale(100_000, 20_000, date(2026, 8, 3), "s1"))
    await books.post_event(purchase(500_000, 100_000, date(2026, 8, 5), "van", "5100 Tools & small equipment"))
    view = put(client, FLAT_RATE).json()
    assert view["capital_candidates"] == [
        {
            "event_id": "van",
            "date": "2026-08-05",
            "counterparty": "Screwfix",
            "gross": "6000.00",
            "vat": "1000.00",
            "marked": False,
        }
    ]
    put(client, {**FLAT_RATE, "capital_purchases": ["van"]})
    hmrc = client.get(f"/books/vat?period=2026-Q3&{TODAY}", headers=H).json()["hmrc_body"]
    assert hmrc["vatReclaimedCurrPeriod"] == 1000.0 and hmrc["totalValuePurchasesExVAT"] == 5000


async def test_the_exported_vat_return_follows_the_scheme_like_the_vat_page(books: Books, client: TestClient):
    """Reports & exports (app/exports/vat_reports.py) gives the boxes the VAT page files, not the standard ones."""
    await books.post_event(sale(100_000, 20_000, date(2026, 8, 3), "s1"))
    await books.post_event(purchase(50_000, 10_000, date(2026, 8, 4), "p1"))
    assert put(client, FLAT_RATE).status_code == 200
    r = client.get(f"/exports/vat-return?from=2026-07-01&to=2026-09-30&{TODAY}", headers=H)
    assert r.status_code == 200, r.text
    doc = r.json()["doc"]
    rows = {row["cells"]["box"]: row["cells"] for row in doc["sections"][0]["rows"]}
    box = {str(k): v for k, v in rows.items()}
    # Flat rate 11% of £1,200.00 VAT-inclusive turnover: box 1 £132.00, box 4 £0.00, box 6 £1,200 (as the VAT page).
    assert box["Box 1"]["amount"] == 13_200 and box["Box 4"]["amount"] == 0 and box["Box 6"]["whole"] == 1200
    assert "Flat Rate Scheme" in doc["basis"][0]
    detail = client.get(f"/exports/vat-detail?from=2026-07-01&to=2026-09-30&{TODAY}", headers=H).json()["doc"]
    assert any("Flat Rate Scheme" in w and "can differ" in w for w in detail["warnings"])


async def test_the_exported_vat_return_is_unchanged_under_standard_accounting(books: Books, client: TestClient):
    await books.post_event(sale(100_000, 20_000, date(2026, 8, 3), "s1"))
    doc = client.get(f"/exports/vat-return?from=2026-07-01&to=2026-09-30&{TODAY}", headers=H).json()["doc"]
    box = {row["cells"]["box"]: row["cells"] for row in doc["sections"][0]["rows"]}
    assert box["Box 1"]["amount"] == 20_000 and "standard accounting" in doc["basis"][0]
