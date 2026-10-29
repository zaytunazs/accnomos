"""Import history and opening balances (app/import_formats.py, app/import_history.py, app/routes_import.py).

The sample exports in tests/fixtures/import/ are one fictional company (Hollybank Joinery Ltd, SAMPLE — FICTIONAL
COMPANY) as at 31 March 2026 in each vendor's layout; their figures are in tests/fixtures/import/README.md:

    trial balance 66,185.10 each side; debtors 4,560.00 = INV-0101 2,400.00 + INV-0104 1,560.00 + INV-0098 600.00
    (of 1,200.00); creditors 2,130.50 = H-5521 1,250.50 + SF-7781 880.00; bank 12,450.37.

Conversion date 1 April 2026, so the opening entry is dated 31 March 2026.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode, compute_vat_return
from app import contacts as cb
from app import import_formats as fmt
from app import import_history as ih
from app.books import AUDIT, EVENTS, Books
from app.paths import REPORTS

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
FIX = Path(__file__).parent / "fixtures" / "import"
CONVERSION = "2026-04-01"
BALANCE = date(2026, 3, 31)
TOTAL = 6_618_510

#: vendor -> [(file, form fields)]; every set gives the same books.
SETS: dict[str, list[tuple[str, dict[str, str]]]] = {
    "xero": [
        ("trial_balance.csv", {}),
        ("chart_of_accounts.csv", {}),
        ("contacts.csv", {}),
        ("invoices.csv", {}),
        ("bills.csv", {"kind": "open_items", "side": "purchase"}),
        ("bank_balances.csv", {}),
    ],
    "quickbooks": [
        ("trial_balance.csv", {}),
        ("chart_of_accounts.csv", {}),
        ("open_invoices.csv", {}),
        ("unpaid_bills.csv", {}),
    ],
    "sage50": [("trial_balance.csv", {}), ("aged_debtors.csv", {}), ("aged_creditors.csv", {})],
    "sage_accounting": [("trial_balance.csv", {}), ("aged_debtors.csv", {}), ("aged_creditors.csv", {})],
    "freeagent": [("trial_balance.csv", {}), ("../spreadsheet/open_items.csv", {})],
    "spreadsheet": [
        ("trial_balance.csv", {}),
        ("contacts.csv", {}),
        ("open_items.csv", {}),
        ("bank_balances.csv", {}),
    ],
}


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client: TestClient, vendor: str, name: str, form: dict[str, str] | None = None) -> dict:
    path = FIX / vendor / name
    r = client.post(
        "/import/files",
        files={"file": (path.name, path.read_bytes(), "text/csv")},
        data={"vendor": vendor, **(form or {})},
        headers=H,
    )
    assert r.status_code == 200, r.text
    return r.json()


def load_set(client: TestClient, vendor: str) -> dict:
    for name, form in SETS[vendor]:
        upload(client, vendor, name, form)
    r = client.put("/import", json={"vendor": vendor, "conversion_date": CONVERSION}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def balances(events: list[LedgerEvent]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in events:
        for ln in e.lines:
            out[ln.account] = out.get(ln.account, 0) + ln.debit - ln.credit
    return {a: n for a, n in out.items() if n}


# --------------------------------------------------------------------------- #
# Cells and files
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "pence"),
    [
        ("1,234.56", 123_456),
        ("£1,234.56", 123_456),
        ("(12.00)", -1_200),
        ("-12", -1_200),
        ("12.00 CR", -1_200),
        ("12.00 DR", 1_200),
        ("12.00-", -1_200),
        ("", 0),
        ("-", 0),
        ("0.1", 10),
        ("1.50", 150),
        ("1.500", 150),
    ],
)
def test_money_is_read_exactly(raw: str, pence: int) -> None:
    assert fmt.pence(raw) == pence


@pytest.mark.parametrize("raw", ["12.345", "abc", "1.2.3", "NaN"])
def test_money_never_rounds_or_guesses(raw: str) -> None:
    with pytest.raises(fmt.ImportFormatError):
        fmt.pence(raw)


@pytest.mark.parametrize(
    ("raw", "day"),
    [
        ("31/03/2026", date(2026, 3, 31)),
        ("1/4/26", date(2026, 4, 1)),
        ("31-Mar-2026", date(2026, 3, 31)),
        ("31 March 2026", date(2026, 3, 31)),
        ("2026-03-31", date(2026, 3, 31)),
        ("2026-03-31T00:00:00", date(2026, 3, 31)),
        ("31.03.2026", date(2026, 3, 31)),
    ],
)
def test_dates_are_uk_day_first(raw: str, day: date) -> None:
    assert fmt.parse_date(raw) == day


def test_impossible_dates_are_refused() -> None:
    for raw in ("31/02/2026", "03/31/2026", "next Tuesday"):
        with pytest.raises(fmt.ImportFormatError):
            fmt.parse_date(raw)


@pytest.mark.parametrize("vendor", sorted(SETS))
def test_every_sample_trial_balance_reads_and_balances(vendor: str) -> None:
    data = (FIX / vendor / "trial_balance.csv").read_bytes()
    p = fmt.parse(data, "trial_balance.csv")
    assert p.kind == "trial_balance"
    assert len(p.accounts) == 16, [a.name for a in p.accounts]
    assert sum(a.debit_pence for a in p.accounts) == sum(a.credit_pence for a in p.accounts) == TOTAL
    assert not p.skipped


def test_vendor_is_guessed_from_the_headers() -> None:
    guess = {v: fmt.parse((FIX / v / "trial_balance.csv").read_bytes(), "tb.csv").vendor for v in SETS}
    assert guess["xero"] == "xero" and guess["sage50"] == "sage50" and guess["freeagent"] == "freeagent"
    assert guess["sage_accounting"] == "sage_accounting"
    assert fmt.parse((FIX / "quickbooks" / "chart_of_accounts.csv").read_bytes(), "coa.csv").vendor == "quickbooks"


def test_kinds_are_told_apart() -> None:
    kinds = {
        p.relative_to(FIX).as_posix(): fmt.parse(p.read_bytes(), p.name, side="purchase").kind
        for p in sorted(FIX.glob("*/*.csv"))
    }
    assert kinds == {
        "freeagent/trial_balance.csv": "trial_balance",
        "quickbooks/chart_of_accounts.csv": "chart_of_accounts",
        "quickbooks/open_invoices.csv": "open_items",
        "quickbooks/trial_balance.csv": "trial_balance",
        "quickbooks/unpaid_bills.csv": "open_items",
        "sage50/aged_creditors.csv": "open_items",
        "sage50/aged_debtors.csv": "open_items",
        "sage50/trial_balance.csv": "trial_balance",
        "sage_accounting/aged_creditors.csv": "open_items",
        "sage_accounting/aged_debtors.csv": "open_items",
        "sage_accounting/trial_balance.csv": "trial_balance",
        "spreadsheet/bank_balances.csv": "bank_balances",
        "spreadsheet/contacts.csv": "contacts",
        "spreadsheet/open_items.csv": "open_items",
        "spreadsheet/trial_balance.csv": "trial_balance",
        "xero/bank_balances.csv": "bank_balances",
        "xero/bills.csv": "open_items",
        "xero/chart_of_accounts.csv": "chart_of_accounts",
        "xero/contacts.csv": "contacts",
        "xero/invoices.csv": "open_items",
        "xero/trial_balance.csv": "trial_balance",
    }


def test_xero_prefers_the_year_to_date_columns() -> None:
    p = fmt.parse((FIX / "xero" / "trial_balance.csv").read_bytes(), "tb.csv")
    bank = next(a for a in p.accounts if a.code == "090")
    assert bank.balance_pence == 1_245_037  # YTD, not March's 1,020.00


def test_open_items_skip_receipts_and_keep_part_paid_balances() -> None:
    p = fmt.parse((FIX / "sage50" / "aged_debtors.csv").read_bytes(), "ad.csv")
    assert [(i.number, i.total_pence, i.due_pence) for i in p.items] == [
        ("INV-0101", 240_000, 240_000),
        ("INV-0104", 156_000, 156_000),
        ("INV-0098", 120_000, 60_000),
    ]
    assert p.skipped == ["Row 5 (Carter & Sons): a 'SR' is not an invoice or bill; left out"]


def test_xlsx_with_title_rows_and_date_cells() -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Hollybank Joinery Ltd (SAMPLE — FICTIONAL COMPANY)"])
    ws.append(["Open Invoices"])
    ws.append([])
    ws.append(["Date", "Transaction type", "Num", "Customer", "Due date", "Amount", "Open balance"])
    ws.append([datetime(2026, 2, 15), "Invoice", "INV-0101", "Acme Kitchens Ltd", datetime(2026, 3, 17), 2400, 2400])
    ws.append([datetime(2026, 1, 10), "Invoice", "INV-0098", "Carter & Sons", datetime(2026, 2, 9), 1200, 600.5])
    buf = io.BytesIO()
    wb.save(buf)
    p = fmt.parse(buf.getvalue(), "open.xlsx")
    assert p.kind == "open_items"
    assert [(i.date, i.due_pence, i.side) for i in p.items] == [
        (date(2026, 2, 15), 240_000, "sale"),
        (date(2026, 1, 10), 60_050, "sale"),
    ]


def test_unreadable_files_say_why() -> None:
    with pytest.raises(fmt.ImportFormatError, match="No header row found|could not tell"):
        fmt.parse(b"foo,bar\n1,2\n", "x.csv")
    with pytest.raises(fmt.ImportFormatError, match="empty"):
        fmt.parse(b"\n\n", "x.csv")
    with pytest.raises(fmt.ImportFormatError, match="CSV or .xlsx"):
        fmt.parse(b"\xd0\xcf\x11\xe0", "old.xls")
    with pytest.raises(fmt.ImportFormatError, match="over 5 MB"):
        fmt.parse(b"a" * (fmt.MAX_FILE + 1), "big.csv")


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #

EXPECTED_TARGETS = {
    "1200 Bank": 1_245_037,
    "1210 Cash": 8_500,
    "1100 Debtors": 456_000,
    "2100 Creditors": -213_050,
    "2200 VAT control": -184_220,
    "2210 Payroll liabilities": -91_240,
    "2300 Owner / director loan": -300_000,
    "3000 Capital": -10_000,
    "3200 Retained profit": -1_000_000,
    "4000 Sales": -4_820_000,
    "5000 Materials": 1_934_000,
    "7000 Gross wages": 1_200_000,
    "7100 Rent": 480_000,
    "7700 Insurance": 115_073,
}


@pytest.mark.parametrize("vendor", sorted(SETS))
def test_suggestions_map_every_sample_account(vendor: str) -> None:
    p = fmt.parse((FIX / vendor / "trial_balance.csv").read_bytes(), "tb.csv")
    got: dict[str, int] = {}
    for a, s in zip(p.accounts, ih.suggest(vendor, p.accounts), strict=True):  # type: ignore[arg-type]
        assert s.target, f"{a.name} unmapped"
        got[s.target] = got.get(s.target, 0) + a.balance_pence
    for target, pence in EXPECTED_TARGETS.items():
        assert got.pop(target) == pence, target
    # What is left: the vehicles (a new fixed asset) and motor expenses (ours, or a new overhead).
    fixed = {t: n for t, n in got.items() if ih.account_klass(t) == "fixed_assets"}
    assert list(fixed.values()) == [950_000]
    assert sum(n for t, n in got.items() if ih.account_klass(t) == "overheads") == 229_900


def test_an_account_we_cannot_place_is_left_unmapped() -> None:
    accounts = [fmt.SourceAccount(name="Suspense XYZ", debit_pence=100)]
    assert ih.suggest("quickbooks", accounts)[0].target is None


def test_second_bank_account_gets_its_own_code() -> None:
    accounts = [
        fmt.SourceAccount(code="090", name="Business Current", type="Bank", debit_pence=100),
        fmt.SourceAccount(code="091", name="Business Savings", type="Bank", debit_pence=200),
    ]
    assert [s.target for s in ih.suggest("xero", accounts)] == ["1200 Bank", "1220 Business Savings"]


# --------------------------------------------------------------------------- #
# The wizard, end to end
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vendor", sorted(SETS))
async def test_import_posts_one_balanced_entry_and_reconciles(
    vendor: str, client: TestClient, books: Books, fake: FakeStorageProvider
) -> None:
    v = load_set(client, vendor)
    assert v["can_post"], [c for c in v["checks"] if not c["ok"]]
    assert v["balance_date"] == "2026-03-31"
    assert v["debits_pence"] == v["credits_pence"] == TOTAL
    assert len(v["items"]) == 5 and not any(a["target"] is None for a in v["accounts"])
    accept = v["needs_accept"]  # FreeAgent and Sage have no bank balances file; the others agree to the penny
    assert not accept, [c for c in v["checks"] if not c["ok"]]
    assert not [k for k in fake.files if k.startswith(EVENTS)], "nothing posted before approval"

    r = client.post("/import/post", json={}, headers=H)
    assert r.status_code == 200, r.text
    record = r.json()
    events = await books.list_events()
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "adjustment" and ev.date == BALANCE and ev.approved_by == USER
    assert all(ln.vat_code is None for ln in ev.lines)
    assert sum(ln.debit for ln in ev.lines) == sum(ln.credit for ln in ev.lines) == TOTAL
    assert len(ev.evidence) == len(SETS[vendor])
    got = balances(events)
    for target, pence in EXPECTED_TARGETS.items():
        assert got[target] == pence, target

    # The reconciliation proves the books equal the source, and is saved in 07 Reports.
    rec = client.get("/import/opening", headers=H).json()["reconciliation"]
    assert rec["proved"], [c for c in rec["checks"] if not c["ok"]]
    assert rec["accnomos_debits_pence"] == rec["source_debits_pence"] == TOTAL
    assert record["report_path"].startswith(f"{REPORTS}/") and record["report_path"] in fake.files
    csv_text = client.get("/import/opening/report.csv", headers=H).text
    assert "Proved,yes" in csv_text

    # No VAT return counts it.
    q = compute_vat_return(events, "26A1", date(2026, 1, 1), date(2026, 3, 31))
    assert (q.vat_due_sales, q.vat_reclaimed, q.total_sales_ex_vat, q.total_purchases_ex_vat) == (0, 0, 0, 0)
    assert not q.warnings

    # Aged debtors and creditors are right from day one.
    contacts, ledger, _ = await cb.contact_book(books)
    aged = cb.aged(contacts, ledger, date(2026, 4, 1))
    assert aged.debtors.total_pence == 456_000 and aged.creditors.total_pence == 213_050
    assert aged.debtors.buckets == {"current": 156_000, "0-30": 240_000, "31-60": 60_000, "61-90": 0, "90+": 0}
    names = {c.name for c in contacts}
    assert {"Brook Lane Builders", "Carter & Sons", "Screwfix (sample)"} <= names

    audit = b"".join(v for k, v in fake.files.items() if k.startswith(AUDIT + "/2")).decode()
    assert '"opening_balances_posted"' in audit and '"import_file_added"' in audit


async def test_contacts_carry_their_details(client: TestClient, books: Books) -> None:
    load_set(client, "xero")
    assert client.post("/import/post", json={}, headers=H).status_code == 200
    contacts = {c.name: c for c in await cb.stored_contacts(books)}
    acme = contacts["Acme Kitchens Ltd (SAMPLE — FICTIONAL COMPANY)"]
    assert acme.email == "accounts@acme-kitchens.example" and acme.vrn == "GB999999973"
    assert acme.address == "1 Sample Street, Leeds, LS1 1AA" and acme.source == "import" and acme.kind == "customer"
    assert contacts["Howdens Joinery (sample)"].kind == "supplier"


async def test_a_payment_against_an_opening_invoice_clears_it(client: TestClient, books: Books) -> None:
    load_set(client, "spreadsheet")
    assert client.post("/import/post", json={}, headers=H).status_code == 200
    open_sales = client.get("/payments/open?side=sale", headers=H).json()
    carter = next(d for d in open_sales if d["reference"] == "INV-0098")
    r = client.post(
        "/payments",
        json={
            "side": "sale",
            "date": "2026-04-03",
            "amount_pence": 60_000,
            "allocations": [{"event_id": carter["event_id"], "amount_pence": 60_000}],
        },
        headers=H,
    )
    assert r.status_code == 200, r.text
    events = await books.list_events()
    assert balances(events)["1100 Debtors"] == 396_000  # 4,560.00 − 600.00
    contacts, ledger, _ = await cb.contact_book(books)
    assert cb.aged(contacts, ledger, date(2026, 4, 3)).debtors.total_pence == 396_000

    # Undo is refused while the payment stands, and works once it is removed.
    r = client.post("/import/undo", headers=H)
    assert r.status_code == 409 and "payment" in r.json()["detail"]
    assert client.delete(f"/payments/{r_payment_id(client)}", headers=H).status_code == 200
    r = client.post("/import/undo", headers=H)
    assert r.status_code == 200, r.text
    assert balances(await books.list_events()) == {}
    contacts, ledger, _ = await cb.contact_book(books)
    assert cb.aged(contacts, ledger, date(2026, 4, 3)).debtors.total_pence == 0
    assert client.get("/import/opening", headers=H).json()["reconciliation"]["undone"] is True

    # And the books can take a fresh import afterwards.
    v = load_set(client, "spreadsheet")
    assert v["can_post"], [c for c in v["checks"] if not c["ok"]]


def r_payment_id(client: TestClient) -> str:
    return next(p["id"] for p in client.get("/payments?side=sale", headers=H).json() if p["source"] == "recorded")


def test_warnings_must_be_accepted(client: TestClient) -> None:
    upload(client, "spreadsheet", "trial_balance.csv")
    upload(client, "quickbooks", "open_invoices.csv")  # debtors only: no bills list against 2,130.50 creditors
    v = client.put("/import", json={"vendor": "spreadsheet", "conversion_date": CONVERSION}, headers=H).json()
    assert v["can_post"] and v["needs_accept"]
    creditors = next(c for c in v["checks"] if c["id"] == "creditors_match")
    assert not creditors["ok"] and "no open bills" in creditors["message"]
    r = client.post("/import/post", json={}, headers=H)
    assert r.status_code == 409 and "Accept the warnings" in r.json()["detail"]
    r = client.post("/import/post", json={"accept_warnings": True}, headers=H)
    assert r.status_code == 200
    assert r.json()["accepted_warnings"]
    rec = client.get("/import/opening", headers=H).json()["reconciliation"]
    assert not rec["proved"] and next(c for c in rec["checks"] if c["id"] == "totals")["ok"]


def test_a_debtors_list_that_does_not_add_up_is_flagged(client: TestClient) -> None:
    upload(client, "spreadsheet", "trial_balance.csv")
    upload(client, "sage50", "aged_creditors.csv")
    data = (FIX / "spreadsheet" / "open_items.csv").read_text().replace("2400.00,2400.00", "2400.00,2300.00")
    client.post("/import/files", files={"file": ("open.csv", data.encode(), "text/csv")}, headers=H)
    v = client.put("/import", json={"conversion_date": CONVERSION}, headers=H).json()
    debtors = next(c for c in v["checks"] if c["id"] == "debtors_match")
    assert not debtors["ok"] and debtors["expected_pence"] == 456_000 and debtors["actual_pence"] == 446_000


def test_an_unbalanced_trial_balance_cannot_be_posted(client: TestClient) -> None:
    data = (FIX / "sage50" / "trial_balance.csv").read_text().replace("7100,Rent,4800.00", "7100,Rent,4800.01")
    client.post(
        "/import/files", files={"file": ("tb.csv", data.encode(), "text/csv")}, data={"vendor": "sage50"}, headers=H
    )
    v = client.put("/import", json={"conversion_date": CONVERSION}, headers=H).json()
    check = next(c for c in v["checks"] if c["id"] == "tb_balanced")
    assert not check["ok"] and "out by £0.01" in check["message"] and not v["can_post"]
    r = client.post("/import/post", json={"accept_warnings": True}, headers=H)
    assert r.status_code == 409 and "out by" in r.json()["detail"]


def test_unmapped_accounts_block_until_the_user_maps_them(client: TestClient, books: Books) -> None:
    data = (FIX / "quickbooks" / "trial_balance.csv").read_text().replace("Rent or lease payments", "Suspense XYZ")
    client.post(
        "/import/files", files={"file": ("tb.csv", data.encode(), "text/csv")}, data={"vendor": "quickbooks"}, headers=H
    )
    v = client.put("/import", json={"conversion_date": CONVERSION}, headers=H).json()
    row = next(a for a in v["accounts"] if a["name"] == "Suspense XYZ")
    assert row["target"] is None and not v["can_post"]
    assert client.put("/import", json={"mapping": {row["key"]: "Rent"}}, headers=H).status_code == 422
    v = client.put("/import", json={"mapping": {row["key"]: "7100 Rent"}}, headers=H).json()
    row = next(a for a in v["accounts"] if a["name"] == "Suspense XYZ")
    assert row["target"] == "7100 Rent" and row["how"] == "user" and v["can_post"]
    # Putting the suggestion back (null) unmaps it again.
    v = client.put("/import", json={"mapping": {row["key"]: None}}, headers=H).json()
    assert not v["can_post"]


async def test_books_with_earlier_entries_are_refused(client: TestClient, books: Books) -> None:
    await books.post_event(
        LedgerEvent(
            kind="purchase",
            date=date(2026, 3, 1),
            lines=[
                Line(account="7500 Office supplies", debit=1_000, vat_code=VatCode.STANDARD),
                Line(account="2200 VAT control", debit=200),
                Line(account="1200 Bank", credit=1_200),
            ],
            approved_by=USER,
            approved_at=datetime(2026, 3, 1, tzinfo=UTC),
            net=1_000,
            vat=200,
        )
    )
    v = load_set(client, "sage50")
    assert not v["can_post"] and any(c["id"] == "books_empty_before" for c in v["checks"])
    v = client.put("/import", json={"conversion_date": "2026-03-01"}, headers=H).json()
    assert v["can_post"], [c for c in v["checks"] if not c["ok"]]


def test_a_second_import_waits_for_the_first_to_be_undone(client: TestClient) -> None:
    load_set(client, "sage50")
    assert client.post("/import/post", json={}, headers=H).status_code == 200
    v = load_set(client, "sage50")
    assert any(c["id"] == "no_active_import" and not c["ok"] for c in v["checks"])
    assert client.post("/import/post", json={}, headers=H).status_code == 409


async def test_year_end_conversion_folds_profit_and_loss_into_retained_profit(client: TestClient, books: Books) -> None:
    load_set(client, "freeagent")
    v = client.put("/import", json={"pl_treatment": "retained"}, headers=H).json()
    accounts = {j["account"]: j["debit_pence"] - j["credit_pence"] for j in v["journal"]}
    # 48,200.00 − 19,340.00 − 12,000.00 − 4,800.00 − 1,150.73 − 2,299.00 = 8,610.27 profit, credit
    assert accounts["3200 Retained profit"] == -1_000_000 - 861_027
    assert not any(ih.account_klass(a) in ih.PL_CLASSES for a in accounts)
    assert client.post("/import/post", json={}, headers=H).status_code == 200
    rec = client.get("/import/opening", headers=H).json()["reconciliation"]
    assert rec["proved"], rec["checks"]


def test_a_new_trial_balance_replaces_the_old_and_files_can_be_removed(client: TestClient, fake: FakeStorageProvider):
    upload(client, "sage50", "trial_balance.csv")
    v = upload(client, "spreadsheet", "trial_balance.csv")
    assert [f["kind"] for f in v["draft"]["files"]] == ["trial_balance"]
    assert len([k for k in fake.files if k.startswith(ih.SOURCES)]) == 2  # both uploads kept as they came
    fid = v["draft"]["files"][0]["id"]
    v = client.delete(f"/import/files/{fid}", headers=H).json()
    assert v["draft"]["files"] == [] and not v["can_post"]
    assert client.delete(f"/import/files/{fid}", headers=H).status_code == 404


def test_upload_errors_and_templates(client: TestClient) -> None:
    r = client.post("/import/files", files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")}, headers=H)
    assert r.status_code == 400 and "header" in r.json()["detail"].lower() or "tell" in r.json()["detail"]
    r = client.post("/import/files", files={"file": ("../x.csv", b"a", "text/csv")}, headers=H)
    assert r.status_code == 400
    r = client.post("/import/files", files={"file": ("x.csv", b"a", "text/csv")}, headers={"X-Graph-Token": "t"})
    assert r.status_code == 400  # X-User required
    for kind in fmt.KINDS:
        t = client.get(f"/import/templates/{kind}.csv", headers=H)
        assert t.status_code == 200
        assert fmt.parse(t.content, "t.csv").kind == kind  # our own templates read back as what they are


def test_discard_starts_again(client: TestClient) -> None:
    load_set(client, "sage50")
    v = client.delete("/import", headers=H).json()
    assert v["draft"]["files"] == [] and v["draft"]["conversion_date"] is None


def test_mapping_only_takes_accounts_in_the_trial_balance(client: TestClient) -> None:
    upload(client, "sage50", "trial_balance.csv")
    r = client.put("/import", json={"mapping": {"code:9999": "7100 Rent"}}, headers=H)
    assert r.status_code == 422 and "not in the trial balance" in r.json()["detail"]


def test_a_broken_csv_is_a_sentence_not_a_crash() -> None:
    huge = b'Code,Account,Debit,Credit\n1,"' + b"x" * 200_000 + b'",1,\n'
    with pytest.raises(fmt.ImportFormatError, match="not a CSV we can read"):
        fmt.parse(huge, "tb.csv")
