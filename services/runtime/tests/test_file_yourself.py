"""File it yourself (app/file_yourself.py, app/routes_file_yourself.py): the VAT bridging file, the Income Tax
quarterly figures and the SA103S / SA103F pages, as JSON, CSV and XLSX, cell by cell."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app import file_yourself as fy
from app import itsa
from app.books import Books
from app.main import app
from app.paths import REPORTS
from app.routes_books import get_books
from app.routes_file_yourself import quarter_end

H = {"X-Graph-Token": "t", "X-User": "sam@sambuilds.example"}
AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def ev(id_: str, day: date, kind: str, *lines: Line, net: int | None = None, vat: int | None = None) -> LedgerEvent:
    return LedgerEvent(
        id=id_ * 32,
        kind=kind,
        date=day,
        lines=list(lines),
        net=net,
        vat=vat,
        counterparty="Someone",
        approved_by="sam",
        approved_at=AT,
    )


def sale(id_: str, day: date, net: int, vat: int = 0, account: str = "4000 Sales") -> LedgerEvent:
    ls = [Line(account="1100 Debtors", debit=net + vat), Line(account=account, credit=net, vat_code=VatCode.STANDARD)]
    if vat:
        ls.append(Line(account="2200 VAT control", credit=vat, vat_code=VatCode.STANDARD))
    return ev(id_, day, "sale", *ls, net=net, vat=vat)


def cost(id_: str, day: date, account: str, net: int, vat: int = 0) -> LedgerEvent:
    ls = [Line(account=account, debit=net, vat_code=VatCode.STANDARD), Line(account="1200 Bank", credit=net + vat)]
    if vat:
        ls.append(Line(account="2200 VAT control", debit=vat))
    return ev(id_, day, "purchase", *ls, net=net, vat=vat)


BOOKS = [
    sale("a", date(2026, 7, 10), 1_000_00, 200_00),
    cost("b", date(2026, 8, 3), "5000 Materials", 320_65, 64_13),
    cost("c", date(2026, 6, 1), "7100 Rent", 400_00),
    cost("d", date(2026, 6, 2), "7900 Bank charges", 5_00),
    cost("e", date(2026, 6, 3), "7920 Loan interest", 7_50),
    cost("f", date(2026, 6, 4), "6200 Advertising", 80_00),
    cost("g", date(2026, 6, 5), "7999 Client entertaining", 45_00),
    cost("h", date(2026, 6, 6), "7400 Travel", 12_34),
    cost("i", date(2026, 4, 5), "7500 Office supplies", 999_00),  # last tax year
    cost("j", date(2026, 10, 6), "7500 Office supplies", 777_00),  # after the 5 Oct quarter end
]


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.ensure_tree()
    for e in BOOKS:
        await b.post_event(e)
    return b


@pytest.fixture
def client(books: Books):
    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def grid(data: bytes) -> list[list[str]]:
    assert not data.startswith(b"\xef\xbb\xbf"), "no byte-order mark: some bridging tools read it into A1"
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


# --- VAT bridging file --------------------------------------------------------------------------------------------


def test_vat_bridging_cells_csv_and_xlsx(client: TestClient) -> None:
    q = "period_start=2026-07-01&period_end=2026-09-30&period_key=26A3&vrn=GB%20123%204567%2089&today=2026-10-02"
    j = client.get(f"/books/file-it-yourself/vat?{q}", headers=H).json()
    assert j["kind"] == "vat-bridging" and j["quickbooks_csv"] is False and j["warnings"] == []
    assert [r[0] for r in j["rows"][:9]] == list(range(1, 10))
    assert [r[1] for r in j["rows"][:9]] == [200.0, 0.0, 200.0, 64.13, 135.87, 1000, 320, 0, 0]
    assert any("digital-links" in g for g in j["guidance"]) and any("1 November 2022" in g for g in j["guidance"])

    rows = grid(client.get(f"/books/file-it-yourself/vat?{q}&format=csv", headers=H).content)
    assert rows[:9] == [
        ["1", "200.00", "VAT due in the period on sales and other outputs", "vatDueSales"],
        ["2", "0.00", rows[1][2], "vatDueAcquisitions"],
        ["3", "200.00", "Total VAT due", "totalVatDue"],
        ["4", "64.13", rows[3][2], "vatReclaimedCurrPeriod"],
        ["5", "135.87", "Net VAT to pay to HMRC or reclaim", "netVatDue"],
        ["6", "1000", rows[5][2], "totalValueSalesExVAT"],
        ["7", "320", rows[6][2], "totalValuePurchasesExVAT"],  # £320.65: pence dropped
        ["8", "0", rows[7][2], "totalValueGoodsSuppliedExVAT"],
        ["9", "0", rows[8][2], "totalAcquisitionsExVAT"],
    ]
    assert rows[9:] == [
        ["Period start", "2026-07-01", "", "periodStart"],
        ["Period end", "2026-09-30", "", "periodEnd"],
        ["Period key", "26A3", "", "periodKey"],
        ["VAT registration number", "123456789", "", "vrn"],
        ["Box 5 is", "To pay HMRC", "", ""],
    ]

    r = client.get(f"/books/file-it-yourself/vat?{q}&format=xlsx", headers=H)
    assert r.headers["content-disposition"] == 'attachment; filename="vat-bridging-26A3-2026-07-01-to-2026-09-30.xlsx"'
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["VAT return"]
    ws = wb.active
    assert [ws[f"B{i}"].value for i in range(1, 10)] == [200, 0, 200, 64.13, 135.87, 1000, 320, 0, 0]
    assert [ws[f"B{i}"].number_format for i in range(1, 10)] == ["0.00"] * 5 + ["0"] * 4
    assert isinstance(ws["B6"].value, int)
    assert ws["A1"].value == 1 and ws["D5"].value == "netVatDue" and ws["B12"].value == "26A3"
    assert ws["B13"].value == "123456789" and ws.max_row == 14


def test_vat_bridging_reclaim_and_rounding_rules() -> None:
    labels = dict.fromkeys(range(1, 10), "x")
    s = fy.vat_bridging(
        {1: "10.004", 2: "0.00", 3: "10.00", 4: "250.50", 5: "-240.50", 6: "50.99", 7: "1252.70", 8: "0", 9: "0"},
        labels,
        date(2026, 1, 1),
        date(2026, 3, 31),
        "26A1",
        None,
        "reclaim",
    )
    vals = [r[1] for r in s.rows[:9]]
    assert vals == [
        Decimal("10.00"),
        Decimal("0.00"),
        Decimal("10.00"),
        Decimal("250.50"),
        Decimal("240.50"),
        50,
        1252,
        0,
        0,
    ]
    assert s.rows[13][1] == "To reclaim from HMRC" and s.rows[12][1] is None
    assert any("rounded to the penny" in w for w in s.warnings)
    assert any("Box 5 did not equal" in w for w in s.warnings)
    assert any("No VAT registration number" in w for w in s.warnings)
    assert grid(fy.to_csv(s))[4][1] == "240.50"  # box 5 never negative


def test_vat_bridging_bad_vrn_and_save(client: TestClient, books: Books) -> None:
    q = "period_start=2026-07-01&period_end=2026-09-30&period_key=26A3&today=2026-10-02"
    assert client.get(f"/books/file-it-yourself/vat?{q}&vrn=12345", headers=H).status_code == 422
    r = client.post(f"/books/file-it-yourself/vat/save?{q}&format=csv", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["path"] == f"{REPORTS}/vat-bridging-26A3-2026-07-01-to-2026-09-30.csv"
    again = client.post(f"/books/file-it-yourself/vat/save?{q}&format=csv", headers=H).json()
    assert again["path"] != r.json()["path"]  # never overwrites
    assert client.post(f"/books/file-it-yourself/vat/save?{q}&format=pdf", headers=H).status_code == 422


# --- Income Tax quarterly figures ---------------------------------------------------------------------------------


def test_quarter_end_defaults() -> None:
    assert quarter_end(date(2026, 6, 1)) == ("2025-26", date(2026, 4, 5))
    assert quarter_end(date(2026, 7, 5)) == ("2026-27", date(2026, 7, 5))
    assert quarter_end(date(2026, 11, 11)) == ("2026-27", date(2026, 10, 5))
    assert quarter_end(date(2027, 1, 6)) == ("2026-27", date(2027, 1, 5))
    assert quarter_end(date(2027, 4, 5)) == ("2026-27", date(2027, 4, 5))


def test_itsa_quarterly_is_cumulative_with_api_fields_and_boxes(client: TestClient) -> None:
    q = "today=2026-11-11&basis=traditional"
    j = client.get(f"/books/file-it-yourself/itsa-quarterly?{q}", headers=H).json()
    assert (j["tax_year"], j["period_start"], j["period_end"]) == ("2026-27", "2026-04-06", "2026-10-05")
    assert j["consolidated_eligible"] is True and j["turnover"] == 1000.0
    rows = grid(client.get(f"/books/file-it-yourself/itsa-quarterly?{q}&format=csv", headers=H).content)
    assert rows[0] == ["HMRC field", "Value (£)", "Description", "SA103F box", "Group"]
    by = {r[0]: r for r in rows if r}
    assert by["periodIncome.turnover"][1:2] + by["periodIncome.turnover"][3:] == ["1000.00", "15", "periodIncome"]
    assert by["periodIncome.other"][1] == "0.00" and by["periodIncome.taxTakenOffTradingIncome"][1] == ""
    assert by["periodExpenses.costOfGoods"][1] == "320.65" and by["periodExpenses.costOfGoods"][3] == "17"
    assert by["periodExpenses.premisesRunningCosts"][1] == "400.00"
    assert by["periodExpenses.financeCharges"][1:4:2] == ["5.00", "26"]
    assert by["periodExpenses.interestOnBankOtherLoans"][1:4:2] == ["7.50", "25"]
    assert by["periodExpenses.businessEntertainmentCosts"][1:4:2] == ["45.00", "24"]
    assert by["periodDisallowableExpenses.businessEntertainmentCostsDisallowable"][1:4:2] == ["45.00", "39"]
    # 6 Apr to 5 Oct only: neither 5 Apr's nor 6 Oct's office supplies
    assert by["periodExpenses.adminCosts"][1] == "0.00"
    # every API field present, in HMRC's names, rows 2-34 as documented
    assert [r[0] for r in rows[1:4]] == [
        "periodIncome.turnover",
        "periodIncome.other",
        "periodIncome.taxTakenOffTradingIncome",
    ]
    assert {r[0].split(".")[1] for r in rows[4:19]} == {f.key for f in itsa.FIELDS if f.group == "expenses"}
    assert all(r[0].endswith("Disallowable") for r in rows[19:34]) and rows[34] == []
    total = 320_65 + 400_00 + 5_00 + 7_50 + 80_00 + 45_00 + 12_34
    assert rows[35][0] == "periodExpenses.consolidatedExpenses" and rows[35][1] == f"{(total - 45_00) / 100:.2f}"
    assert by["Period start"][1] == "2026-04-06" and by["Consolidated expenses allowed"][1] == "yes"

    later = client.get(f"/books/file-it-yourself/itsa-quarterly?{q}&period_end=2026-10-06&format=json", headers=H)
    assert next(r for r in later.json()["rows"] if r[0] == "periodExpenses.adminCosts")[1] == 777.0

    wb = load_workbook(
        io.BytesIO(client.get(f"/books/file-it-yourself/itsa-quarterly?{q}&format=xlsx", headers=H).content)
    )
    ws = wb.active
    assert ws.title == "Quarterly update" and ws["A2"].value == "periodIncome.turnover" and ws["B2"].value == 1000
    assert ws["B2"].number_format == "0.00" and ws["D5"].value == "17"


def test_itsa_consolidated_not_eligible_at_90000() -> None:
    events = [sale("a", date(2026, 5, 1), 90_000_00)]
    s = fy.itsa_quarterly(itsa.se_summary(events, "2026-27", date(2026, 7, 5)))
    assert s.extra["consolidated_eligible"] is False
    assert next(r for r in s.rows if r and r[0] == "Consolidated expenses allowed")[1] == "no"
    just_under = fy.itsa_quarterly(
        itsa.se_summary([sale("a", date(2026, 5, 1), 89_999_99)], "2026-27", date(2026, 7, 5))
    )
    assert just_under.extra["consolidated_eligible"] is True


# --- SA103S / SA103F ----------------------------------------------------------------------------------------------


def test_sa103_short_by_default_under_90000(client: TestClient) -> None:
    q = "tax_year=2026-27&basis=traditional&today=2027-05-01"
    j = client.get(f"/books/file-it-yourself/sa103?{q}", headers=H).json()
    assert j["form"] == "short" and j["suggested_form"] == "short"
    rows = grid(client.get(f"/books/file-it-yourself/sa103?{q}&format=csv", headers=H).content)
    assert rows[0] == ["Box", "Description", "£ and pence", "Whole £", "HMRC field"]
    by = {r[0]: r for r in rows if r}
    assert by["9"][2:4] == ["1000.00", "1000"]
    assert by["11"][2:4] == ["320.65", "320"]
    assert by["12"][2:4] == ["12.34", "12"]
    assert by["14"][2:4] == ["400.00", "400"]
    assert by["17"][2:4] == ["12.50", "12"]  # interest and bank charges together
    assert by["18"][2:4] == ["777.00", "777"]  # the whole year: 6 Oct counts
    assert by["19"][2:4] == ["80.00", "80"]  # advertising; client entertaining is never allowable
    allowable = 320_65 + 12_34 + 400_00 + 12_50 + 777_00 + 80_00
    assert by["20"][2:4] == [f"{allowable / 100:.2f}", str(320 + 12 + 400 + 12 + 777 + 80)]
    assert by["21"][2] == "0.00" and by["22"][2] == f"{(allowable - 1_000_00) / 100:.2f}"
    assert by["22"][3] == str(320 + 12 + 400 + 12 + 777 + 80 - 1000)  # whole pounds add up from the whole boxes
    assert "not worked out by Accnomos" in by["23"][1] and by["23"][2] == ""
    assert by["Form"][1] == "Self-employment (short), SA103S" and by["Tax year"][1] == "2026-27"


def test_sa103_full_toggle_and_auto_full_at_90000(client: TestClient) -> None:
    q = "tax_year=2026-27&basis=traditional&form=full"
    j = client.get(f"/books/file-it-yourself/sa103?{q}", headers=H).json()
    assert j["form"] == "full" and j["suggested_form"] == "short"
    by = {r[0]: r for r in j["rows"] if r}
    assert by["15"][2] == 1000.0 and by["24"][2] == 125.0  # advertising and business entertainment together
    assert by["25"][2] == 7.5 and by["26"][2] == 5.0
    assert by["39"][2] == 45.0 and by["46"][2] == 45.0
    total = 320_65 + 12_34 + 400_00 + 125_00 + 7_50 + 5_00 + 777_00
    assert by["31"][2] == total / 100
    assert by["48"][2] == round((total - 1_000_00) / 100, 2) and by["47"][2] == 0.0
    wb = load_workbook(io.BytesIO(client.get(f"/books/file-it-yourself/sa103?{q}&format=xlsx", headers=H).content))
    assert wb.active.title == "SA103F" and wb.active["A2"].value == "15"

    big = itsa.se_summary([sale("a", date(2026, 5, 1), 90_000_00)], "2026-27", date(2027, 4, 5))
    assert fy.sa103(big).extra["form"] == "full"
    short_anyway = fy.sa103(big, "short")
    assert any("HMRC expects the full pages" in w for w in short_anyway.warnings)


def test_sa103_default_tax_year_is_the_last_one_ended(client: TestClient) -> None:
    j = client.get("/books/file-it-yourself/sa103?today=2026-11-11&basis=traditional", headers=H).json()
    assert j["tax_year"] == "2025-26"
    assert next(r for r in j["rows"] if r and r[0] == "18")[2] == 999.0  # 5 Apr 2026 is in 2025-26
