"""POST /books/export: everything as one zip in 07 Reports/Exports, on fake storage.

Seeds one of every table, exports, and checks the zip holds them all, the CSVs
parse, the README lists every file, a second run the same day gets " (2)", the
caps refuse with 413, and the run is audited.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app import data_export
from app.books import AUDIT, Books

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
TODAY = date(2026, 10, 27)
S = VatCode.STANDARD


def _event() -> LedgerEvent:
    return LedgerEvent(
        id="e" * 32,
        kind="purchase",
        date=date(2026, 8, 14),
        lines=[
            Line(account="5000 Materials", debit=4_325, vat_code=S),
            Line(account="2200 VAT control", debit=865),
            Line(account="1200 Bank", credit=5_190),
        ],
        net=4_325,
        vat=865,
        counterparty="Novex Office Supplies Ltd",
        approved_by=USER,
        approved_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


@pytest.fixture
async def books() -> Books:
    fake = FakeStorageProvider()
    books = Books(fake)
    await books.post_event(_event())
    await fake.write(
        "_System/proposals/ab12cd34ef56ab78.json", json.dumps({"id": "ab12cd34ef56ab78", "status": "posted"}).encode()
    )
    await fake.write(
        "_System/Contacts/contacts.json",
        json.dumps(
            [{"id": "c1", "kind": "supplier", "name": "Novex Office Supplies Ltd", "source": "ledger"}]
        ).encode(),
    )
    await fake.write(
        "03 Sales/invoices/INV-0001.json",
        json.dumps(
            {
                "number": "INV-0001",
                "status": "sent",
                "issue_date": "2026-09-02",
                "customer": {"name": "JM Trading"},
                "net_pence": 10_000,
                "vat_pence": 2_000,
                "total_pence": 12_000,
            }
        ).encode(),
    )
    await fake.write("03 Sales/invoices/sent/INV-0001.pdf", b"%PDF-1.4 fake invoice")
    await fake.write(
        "_System/Payments/payments.json",
        json.dumps(
            [
                {
                    "id": "p1",
                    "side": "sale",
                    "date": "2026-09-10",
                    "amount_pence": 12_000,
                    "account": "1200 Bank",
                    "counterparty": "JM Trading",
                    "allocations": [{"event_id": "e" * 32, "amount_pence": 12_000}],
                    "event_id": "f" * 32,
                }
            ]
        ).encode(),
    )
    await fake.write(
        "_System/bank/" + "b" * 64 + ".json",
        json.dumps(
            [
                {
                    "id": "c" * 16,
                    "date": "2026-09-10",
                    "amount_pence": 12_000,
                    "description": "JM TRADING INV-0001",
                    "source_file": "04 Bank statements/2026-09-10_bank.csv",
                    "status": "unmatched",
                }
            ]
        ).encode(),
    )
    await fake.write(
        "_System/rules.json", json.dumps([{"match": {"supplier_regex": "Novex"}, "account": "5000 Materials"}]).encode()
    )
    await fake.write("_System/Rules/rules.json", json.dumps([]).encode())
    await fake.write("_System/bank_rules.json", json.dumps([]).encode())
    await books.audit(f"user:{USER}", "approved", {"proposal": "ab12cd34ef56ab78"})
    await fake.write("06 VAT returns/26A3/return.json", json.dumps({"periodKey": "26A3", "box5": "12.00"}).encode())
    await fake.write("06 VAT returns/26A3/receipt.json", json.dumps({"periodKey": "26A3"}).encode())
    return books


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_export_holds_every_table_csvs_parse_and_readme_lists_each_file(client: TestClient, books: Books) -> None:
    r = client.post(f"/books/export?today={TODAY}", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == "07 Reports/Exports/accnomos-export-2026-10-27.zip"
    assert body["name"] == "accnomos-export-2026-10-27.zip"

    raw = books.storage.files[body["path"]]  # type: ignore[attr-defined]
    assert body["size"] == len(raw)
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()

    event_files = [n for n in names if n.startswith("ledger-events/")]
    assert len(event_files) == 1 and event_files[0].endswith(".json")
    assert "proposals/ab12cd34ef56ab78.json" in names
    assert "contacts.json" in names
    assert "invoices/INV-0001.json" in names
    pdf_index = json.loads(zipfile.ZipFile(io.BytesIO(raw)).read("invoices/invoice-pdfs-index.json"))
    assert [e["path"] for e in pdf_index] == ["03 Sales/invoices/sent/INV-0001.pdf"]
    assert "payments.json" in names and "credit-uses.json" in names
    assert "bank-lines.json" in names
    assert {"rules.json", "autopilot-rules.json", "bank-rules.json"} <= set(names)
    assert any(n.startswith("audit/") and n.endswith(".jsonl") for n in names)
    assert "vat-returns/26A3/return.json" in names and "vat-returns/26A3/receipt.json" in names
    assert {"ledger-lines.csv", "contacts.csv", "invoices.csv", "payments.csv"} <= set(names)
    assert body["files"] == len(names)

    zf = zipfile.ZipFile(io.BytesIO(raw))
    assert json.loads(zf.read("contacts.json"))[0]["name"] == "Novex Office Supplies Ltd"
    assert len(json.loads(zf.read("bank-lines.json"))) == 1

    def rows(name: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(zf.read(name).decode("utf-8-sig"))))

    ledger = rows("ledger-lines.csv")
    assert len(ledger) == 3  # one row per line of the one event
    assert {r["account"] for r in ledger} == {"5000 Materials", "2200 VAT control", "1200 Bank"}
    assert [r["name"] for r in rows("contacts.csv")] == ["Novex Office Supplies Ltd"]
    assert [(r["number"], r["total_pence"]) for r in rows("invoices.csv")] == [("INV-0001", "12000")]
    assert [(r["id"], r["amount_pence"]) for r in rows("payments.csv")] == [("p1", "12000")]

    readme = zf.read("README.txt").decode()
    assert "opens in Excel" in readme
    for name in names:
        if name != "README.txt":
            assert name in readme, name


def test_second_run_the_same_day_gets_2(client: TestClient) -> None:
    first = client.post(f"/books/export?today={TODAY}", headers=H).json()
    second = client.post(f"/books/export?today={TODAY}", headers=H).json()
    assert first["path"] == "07 Reports/Exports/accnomos-export-2026-10-27.zip"
    assert second["path"] == "07 Reports/Exports/accnomos-export-2026-10-27 (2).zip"


def test_export_is_audited(client: TestClient, books: Books) -> None:
    body = client.post(f"/books/export?today={TODAY}", headers=H).json()
    audit = b"".join(d for p, d in books.storage.files.items() if p.startswith(AUDIT))  # type: ignore[attr-defined]
    assert audit.count(b'"data_exported"') == 1
    assert body["path"].encode() in audit


def test_size_and_file_caps_refuse_with_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_export, "MAX_EXPORT_BYTES", 10)
    assert client.post(f"/books/export?today={TODAY}", headers=H).status_code == 413
    monkeypatch.setattr(data_export, "MAX_EXPORT_BYTES", data_export.MAX_EXPORT_BYTES)
    monkeypatch.setattr(data_export, "MAX_EXPORT_FILES", 0)
    assert client.post(f"/books/export?today={TODAY}", headers=H).status_code == 413


def test_export_needs_x_user(client: TestClient) -> None:
    assert client.post(f"/books/export?today={TODAY}", headers={"X-Graph-Token": "tok"}).status_code == 400


def test_csv_quotes_text_excel_would_run_as_a_formula() -> None:
    from app.data_export import _csv

    out = _csv([{"name": '=HYPERLINK("http://x")', "amount": "-12.50", "note": "@SUM(A1)"}], ["name", "amount", "note"])
    text = out.decode("utf-8")
    assert "'=HYPERLINK" in text and "'@SUM" in text
    assert ",-12.50," in text  # a plain negative number stays a number
