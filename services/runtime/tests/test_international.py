"""Books kept outside the UK (app/region.py, app/profile.py): country, tax and currency in the profile; no HMRC pages,
checks or bank feeds; invoices at the user's own rate; and the Tax summary report with its CSV.

UK books (no `country`) behave exactly as before: test_profile.py and the rest of the suite cover that, and a few
checks here assert the UK side stays unchanged.
"""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_ledger import LedgerEvent, Line, VatCode
from app import profile, region, testmode
from app.books import Books
from app.checks import decide, run_checks
from app.exports import tax_summary
from app.invoicing import LineIn, price_lines
from app.journal import VAT_CONTROL, draft_journal
from app.routes_bankfeeds import router as bankfeeds_router
from app.routes_cis import router as cis_router
from app.routes_dashboard import router as dashboard_router
from app.routes_exports import router as exports_router
from app.routes_invoices import router as invoices_router
from app.routes_itsa import router as itsa_router
from app.routes_payroll import router as payroll_router
from app.routes_profile import router as profile_router
from app.routes_property import router as property_router
from app.routes_reports import router as reports_router
from app.routes_vat import router as vat_router
from app.routes_vat_schemes import router as vat_schemes_router
from app.schemas import ExtractedDoc, ExtractedLine

A = {"X-Graph-Token": "test-token", "X-User": "kim@kimdesign.example"}
AU = {"name": "Kim Design Pty Ltd", "kind": "company", "settings": {"country": "AU"}}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", testmode.DEFAULT_TODAY)
    monkeypatch.delenv("ACCNOMOS_TEST_AI_BASE", raising=False)
    app = FastAPI()
    for r in (
        testmode.router,
        profile_router,
        vat_router,
        vat_schemes_router,
        invoices_router,
        payroll_router,
        reports_router,
        dashboard_router,
        exports_router,
        bankfeeds_router,
        itsa_router,
        cis_router,
        property_router,
    ):
        app.include_router(r)
    app.add_middleware(testmode.TenantMiddleware)
    c = TestClient(app, headers={testmode.TENANT_HEADER: "intl"})
    assert c.post("/__test/reset", headers=A).json()["ok"]
    return c


def _books() -> Books:
    suffix = testmode.account_suffix({b"x-graph-token": b"test-token"})
    return Books(testmode.STATES[f"intl{suffix}"].storage)


# --------------------------------------------------------------------------- #
# Profile: country, tax, currency
# --------------------------------------------------------------------------- #


def test_a_country_gets_its_tax_and_currency_by_default(client: TestClient) -> None:
    r = client.put("/profile", headers=A, json=AU)
    assert r.status_code == 200, r.text
    got = client.get("/profile", headers=A).json()
    assert got["settings"] == {
        "country": "AU",
        "currency": "AUD",
        "sales_tax": {"name": "GST", "rate_percent": 10.0, "number": None},
    }
    assert got["region"] == {
        "country": "AU",
        "country_name": "Australia",
        "uk": False,
        "currency": "AUD",
        "tax_name": "GST",
        "tax_label": "GST",
        "tax_rate_percent": 10.0,
    }


def test_the_users_own_tax_and_currency_win_and_uk_only_settings_are_dropped() -> None:
    s = profile.validate_settings(
        "sole_trader",
        {
            "country": "us",
            "currency": "usd",
            "sales_tax": {"name": "Sales tax", "rate_percent": 8.875, "number": " 12-345 "},
            "utr": "not a UTR",  # UK-only: dropped, never checked
            "vat_number": "nope",
        },
    )
    assert s == {
        "country": "US",
        "currency": "USD",
        "sales_tax": {"name": "Sales tax", "rate_percent": 8.875, "number": "12-345"},
        "accounting_period_start": "04-06",
    }
    none = profile.validate_settings("company", {"country": "IE", "sales_tax": {"name": "None", "rate_percent": 23}})
    assert none["sales_tax"]["rate_percent"] == 0 and none["currency"] == "EUR"


def test_uk_books_save_exactly_as_before() -> None:
    assert profile.validate_settings("company", {"country": "GB", "currency": "EUR", "company_number": "01234567"}) == {
        "vat_number": None,
        "vat_registered": False,
        "company_number": "01234567",
    }
    p = profile.default_profile()
    assert p.region.uk and p.region.currency == "GBP" and "country" not in p.settings


@pytest.mark.parametrize(
    ("settings", "says"),
    [
        ({"country": "XX"}, "two-letter ISO code"),
        ({"country": "AU", "currency": "JPY"}, "currency"),
        ({"country": "AU", "sales_tax": {"name": "GST", "rate_percent": 120}}, "100"),
        ({"country": "AU", "sales_tax": {"name": "IVA", "rate_percent": 10}}, "sales_tax.name"),
        ({"country": "AQ"}, "choose the currency"),  # Antarctica: no default currency
    ],
)
def test_bad_country_settings_are_a_sentence(client: TestClient, settings: dict, says: str) -> None:
    r = client.put("/profile", headers=A, json={"name": "X", "kind": "company", "settings": settings})
    assert r.status_code == 400, r.text
    assert says in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Features and gated routes
# --------------------------------------------------------------------------- #


def test_features_outside_the_uk_have_no_hmrc() -> None:
    for kind in ("company", "sole_trader", "landlord", "partnership"):
        feats = profile.features_for(kind, {"country": "NZ", "vat_registered": True})
        assert not {"vat", "payroll", "self_employment"} & set(feats), kind
        assert {"review", "bank", "reports", "contacts", "invoices", "jobs", "vehicles"} <= set(feats), kind
    assert "self_employment" in profile.features_for("sole_trader", {"vat_registered": True})  # the UK keeps it


HMRC_ROUTES = [
    "/books/vat",
    "/books/vat/periods",
    "/books/deadlines",
    "/reports/vat",
    "/payroll/runs",
    "/books/vat/schemes",
    "/books/self-employment/settings",
    "/cis",
    "/property/properties",
]


def test_hmrc_routes_are_404_outside_the_uk(client: TestClient) -> None:
    assert client.put("/profile", headers=A, json=AU).status_code == 200
    for path in HMRC_ROUTES:
        r = client.get(path, headers=A)
        assert r.status_code == 404, (path, r.status_code, r.text)
        detail = r.json()["detail"]
        assert "UK books only" in detail or "no report" in detail, (path, detail)
    for path in ("/invoices", "/invoices/profile", "/reports/pl", "/exports"):
        assert client.get(path, headers=A).status_code == 200, path


def test_hmrc_routes_still_answer_for_uk_books(client: TestClient) -> None:
    for path in ("/books/vat/schemes", "/cis", "/payroll/runs", "/books/self-employment/settings"):
        assert client.get(path, headers=A).status_code == 200, path


def test_bank_feeds_are_not_offered_outside_the_uk(client: TestClient) -> None:
    uk = client.get("/books/bankfeeds", headers=A).json()
    assert client.put("/profile", headers=A, json=AU).status_code == 200
    abroad = client.get("/books/bankfeeds", headers=A).json()
    assert abroad["available"] is False and "Upload your bank statement" in abroad["reason"]
    assert uk.get("reason") != abroad["reason"]
    body = {"redirect_to": "http://localhost/bank", "binding_hash": "0" * 64}
    assert client.post("/books/bankfeeds/start", headers=A, json=body).status_code == 404


def test_home_has_no_hmrc_deadlines_outside_the_uk(client: TestClient) -> None:
    assert client.put("/profile", headers=A, json=AU).status_code == 200
    r = client.get("/books/dashboard", headers=A, params={"today": "2026-10-27"})
    assert r.status_code == 200, r.text
    assert r.json().get("vat") in (None, {}) or "vat" not in client.get("/profile", headers=A).json()["features"]


# --------------------------------------------------------------------------- #
# Checks and journal
# --------------------------------------------------------------------------- #

AU_RULES = region.rules_from_settings({"country": "AU"})


def _doc(**kw: object) -> ExtractedDoc:
    base: dict[str, object] = dict(
        doc_type="purchase_invoice",
        supplier_name="Officeworks",
        supplier_vat_number=None,
        customer_name=None,
        invoice_number="OW-1",
        date="2026-10-21",
        currency="AUD",
        lines=[ExtractedLine(description="Desk", qty=1, unit_price=400, net=400, vat_rate=10, vat=40)],
        net_total=400,
        vat_total=40,
        gross_total=440,
        payment_method="card",
        card_last4=None,
        category_guess="Office costs",
        confidence=0.95,
    )
    base.update(kw)
    return ExtractedDoc.model_validate(base)


def test_checks_do_not_ask_for_a_uk_vat_number_outside_the_uk() -> None:
    doc = _doc()
    checks = run_checks(doc, known_hashes=set(), this_hash="h", rules=AU_RULES)
    status, reasons = decide(checks)
    assert status == "proposed", reasons
    by = {c.code: c for c in checks}
    assert by["VAT_NUMBER_REQUIRED"].ok and by["VAT_NUMBER_FORMAT"].ok and by["VAT_RATE_VALID"].ok
    assert by["CURRENCY_GBP"].ok and by["CURRENCY_GBP"].message == "In AUD"
    # the same document in UK books: no VAT number, a 10% rate, and AUD all fail, as before
    uk_status, uk_reasons = decide(run_checks(doc, known_hashes=set(), this_hash="h"))
    assert uk_status == "needs_a_look"
    assert any(r.startswith("VAT_NUMBER_REQUIRED") for r in uk_reasons)
    assert any(r.startswith("CURRENCY_GBP") for r in uk_reasons)


def test_other_currencies_and_rates_outside_the_uk() -> None:
    usd = decide(run_checks(_doc(currency="USD"), known_hashes=set(), this_hash="h", rules=AU_RULES))
    assert usd[0] == "needs_a_look" and "converting to AUD" in " ".join(usd[1])
    odd = _doc(lines=[ExtractedLine(description="x", qty=1, unit_price=400, net=400, vat_rate=12.5, vat=50)])
    rate = next(
        c for c in run_checks(odd, known_hashes=set(), this_hash="h", rules=AU_RULES) if c.code == "VAT_RATE_VALID"
    )
    assert (rate.ok, rate.severity) == (False, "warn") and "GST" in rate.message


def test_tax_paid_outside_the_uk_is_claimed_back() -> None:
    journal = draft_journal(_doc(), AU_RULES)
    assert sum(j.debit_pence for j in journal if j.account == VAT_CONTROL) == 4000
    no_tax = region.rules_from_settings({"country": "AU", "sales_tax": {"name": "None", "rate_percent": 0}})
    assert not any(j.account == VAT_CONTROL for j in draft_journal(_doc(), no_tax))  # tax is part of the cost


def test_invoice_lines_use_the_users_rate() -> None:
    lines = [LineIn(description="Design", quantity=2, unit_price_pence=10_000, vat_code="S")]
    priced, summary, net, vat = price_lines(
        lines,
        region.rules_from_settings(
            {"country": "US", "sales_tax": {"name": "Sales tax", "rate_percent": 8.875}}
        ).sales_rates(),
    )
    assert (net, vat, priced[0].vat_rate, summary[0].vat_rate) == (20_000, 1775, 8.875, 8.875)
    _, _, _, uk_vat = price_lines(lines)
    assert uk_vat == 4000
    _, _, _, au = price_lines(lines, AU_RULES.sales_rates())
    assert au == 2000 and isinstance(price_lines(lines, AU_RULES.sales_rates())[0][0].vat_rate, int)


def test_invoice_can_be_sent_without_a_uk_vrn_outside_the_uk() -> None:
    from app.invoicing import InvoiceCustomer, InvoiceDraft, InvoiceProfile, build_invoice, send_problems

    draft = InvoiceDraft(
        customer=InvoiceCustomer(name="Acme", email="a@acme.example"),
        lines=[LineIn(description="Design", quantity=1, unit_price_pence=10_000, vat_code="S")],
    )
    prof = InvoiceProfile(name="Kim Design", address="1 George St, Sydney")
    inv = build_invoice("INV-0001", draft, prof, "kim", date(2026, 10, 1), rates=AU_RULES.sales_rates())
    assert inv.vat_pence == 1000
    assert not send_problems(inv, prof, "a@acme.example", abroad=True)
    assert any("VAT registration number" in p for p in send_problems(inv, prof, "a@acme.example"))


# --------------------------------------------------------------------------- #
# Tax summary report and CSV
# --------------------------------------------------------------------------- #


def _event(eid: str, kind: str, when: date, lines: list[Line], net: int, vat: int) -> LedgerEvent:
    return LedgerEvent(
        id=eid * 32,
        kind=kind,  # type: ignore[arg-type]
        date=when,
        lines=lines,
        evidence=[],
        approved_by="kim",
        approved_at="2026-10-27T09:00:00+00:00",  # type: ignore[arg-type]
        net=net,
        vat=vat,
    )


SALE = _event(
    "a",
    "sale",
    date(2026, 7, 10),
    [
        Line(account="1100 Debtors", debit=11_000),
        Line(account="4000 Sales", credit=10_000, vat_code=VatCode.STANDARD),
        Line(account=VAT_CONTROL, credit=1_000, vat_code=VatCode.STANDARD),
    ],
    10_000,
    1_000,
)
BUY = _event(
    "b",
    "purchase",
    date(2026, 8, 3),
    [
        Line(account="7500 Office costs", debit=4_000, vat_code=VatCode.STANDARD),
        Line(account=VAT_CONTROL, debit=400, vat_code=VatCode.STANDARD),
        Line(account="1200 Bank", credit=4_400),
    ],
    4_000,
    400,
)


def test_tax_summary_figures() -> None:
    rows = tax_summary.figures([SALE, BUY], date(2026, 7, 1), date(2026, 9, 30))
    assert [r["month"] for r in rows] == ["Jul 2026", "Aug 2026", "Sep 2026"]
    assert (rows[0]["sales_tax"], rows[1]["purchases_tax"], rows[2]["net_tax"]) == (1_000, 400, 0)
    assert sum(int(r["net_tax"] or 0) for r in rows) == 600


def test_tax_summary_report_and_csv(client: TestClient) -> None:
    import asyncio

    assert "tax-summary" not in [r["id"] for r in client.get("/exports", headers=A).json()["reports"]]  # UK books
    assert client.get("/exports/tax-summary", headers=A).status_code == 404
    assert client.put("/profile", headers=A, json=AU).status_code == 200

    async def post() -> None:
        books = _books()
        await books.post_event(SALE)
        await books.post_event(BUY)

    asyncio.run(post())
    ids = [r["id"] for r in client.get("/exports", headers=A).json()["reports"]]
    assert "tax-summary" in ids and not {"vat-return", "vat-detail"} & set(ids)
    span = {"from": "2026-07-01", "to": "2026-09-30"}
    preview = client.get("/exports/tax-summary", headers=A, params=span)
    assert preview.status_code == 200, preview.text
    assert preview.json()["doc"]["title"] == "GST summary"
    r = client.get("/exports/tax-summary/file", headers=A, params={**span, "format": "csv"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    text = "\n".join(",".join(row) for row in rows)
    assert "GST on sales" in text and "GST on purchases" in text
    total = next(row for row in rows if row and row[0] == "Total")
    assert total[1:6] == ["100.00", "10.00", "40.00", "4.00", "6.00"]
    assert client.get("/exports/vat-return/file", headers=A, params={**span, "format": "csv"}).status_code == 404


# --------------------------------------------------------------------------- #
# Bank statements as PDF (bank connections are UK-only)
# --------------------------------------------------------------------------- #

STATEMENT = [
    "Date Description Paid out Paid in Balance",
    "01/10/2026 Balance brought forward 1,000.00",
    "03/10/2026 Officeworks Sydney 44.00 956.00",
    "05 Oct 2026 Client payment ACME 1,100.00 2,056.00",
    "7 November 2026 Card fee 2.50 2,053.50",
]


def _statement_pdf() -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for line in STATEMENT:
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def test_statement_lines_take_the_sign_from_the_balance() -> None:
    from app.bank_pdf import statement_lines

    got = statement_lines("\n".join(STATEMENT))
    assert [(d.isoformat(), desc, p) for d, desc, p, _ in got] == [
        ("2026-10-03", "Officeworks Sydney", -4400),
        ("2026-10-05", "Client payment ACME", 110000),
        ("2026-11-07", "Card fee", -250),
    ]


def test_a_statement_pdf_imports_like_a_csv(client: TestClient) -> None:
    from app.routes_bank import router as bank_router

    client.app.include_router(bank_router)  # type: ignore[attr-defined]
    assert client.put("/profile", headers=A, json=AU).status_code == 200
    files = {"file": ("october.pdf", _statement_pdf(), "application/pdf")}
    r = client.post("/books/bank/import", headers=A, files=files)
    assert r.status_code == 200, r.text
    assert r.json()["new_lines"] == 3
    lines = client.get("/books/bank/lines", headers=A).json()
    assert sorted(ln["amount_pence"] for ln in lines) == [-4400, -250, 110000]
    bad = client.post(
        "/books/bank/import", headers=A, files={"file": ("x.pdf", b"%PDF-1.4 nothing", "application/pdf")}
    )
    assert bad.status_code == 400
