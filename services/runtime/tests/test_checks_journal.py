"""Checks + journal on four hand-made docs: standard, arithmetic error, >£250 without
a VAT number, and EUR. No model calls."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.checks import decide, normalise_vat_number, run_checks  # noqa: E402
from app.journal import CREDITORS, VAT_CONTROL, draft_journal, is_balanced  # noqa: E402
from app.schemas import ExtractedDoc, ExtractedLine, extraction_json_schema  # noqa: E402

H = "a" * 64


def _doc(**kw: object) -> ExtractedDoc:
    base: dict[str, object] = dict(
        doc_type="receipt",
        supplier_name="Screwfix",
        supplier_vat_number="GB 232 4567 89",
        customer_name=None,
        invoice_number=None,
        date="2026-10-21",
        currency="GBP",
        lines=[
            ExtractedLine(description="Drill bits", qty=1, unit_price=12.99, net=10.83, vat_rate=20, vat=2.16),
            ExtractedLine(description="Screws", qty=2, unit_price=12.74, net=21.23, vat_rate=20, vat=4.25),
        ],
        net_total=32.06,
        vat_total=6.41,
        gross_total=38.47,
        payment_method="card",
        card_last4="1234",
        category_guess="Tools & small equipment",
        confidence=0.95,
    )
    base.update(kw)
    return ExtractedDoc.model_validate(base)


@pytest.fixture
def standard() -> ExtractedDoc:
    return _doc()


@pytest.fixture
def arith_error() -> ExtractedDoc:
    return _doc(net_total=33.06, gross_total=39.47)  # lines say 32.06


@pytest.fixture
def over_250_no_vat() -> ExtractedDoc:
    return _doc(
        doc_type="purchase_invoice",
        supplier_name="Bob's Building Supplies",
        supplier_vat_number=None,
        lines=[ExtractedLine(description="Timber", qty=1, unit_price=250.0, net=250.0, vat_rate=20, vat=50.0)],
        net_total=250.0,
        vat_total=50.0,
        gross_total=300.0,
        payment_method=None,
        card_last4=None,
        category_guess="Materials",
    )


@pytest.fixture
def eur() -> ExtractedDoc:
    return _doc(
        supplier_name="Bauhaus Köln",
        supplier_vat_number=None,
        currency="eur",
        lines=[ExtractedLine(description="Saw", qty=1, unit_price=23.80, net=20.0, vat_rate=None, vat=3.80)],
        net_total=20.0,
        vat_total=3.80,
        gross_total=23.80,
    )


def _status(doc: ExtractedDoc, **kw: object) -> tuple[str, list[str]]:
    return decide(run_checks(doc, known_hashes=set(), this_hash=H, **kw))  # type: ignore[arg-type]


def _codes(reasons: list[str]) -> set[str]:
    return {r.split(":", 1)[0] for r in reasons}


def test_standard_is_proposed(standard: ExtractedDoc) -> None:
    assert _status(standard) == ("proposed", [])


def test_arith_error_needs_a_look(arith_error: ExtractedDoc) -> None:
    status, reasons = _status(arith_error)
    assert status == "needs_a_look"
    assert "ARITH_TOTALS" in _codes(reasons)


def test_over_250_without_vat_number(over_250_no_vat: ExtractedDoc) -> None:
    status, reasons = _status(over_250_no_vat)
    assert status == "needs_a_look"
    assert _codes(reasons) == {"VAT_NUMBER_REQUIRED"}
    assert any("Over £250 needs a full VAT invoice" in r for r in reasons)


def test_eur_needs_a_look(eur: ExtractedDoc) -> None:
    assert eur.currency == "EUR"
    status, reasons = _status(eur)
    assert status == "needs_a_look"
    assert "CURRENCY_GBP" in _codes(reasons)


def test_duplicate_and_period(standard: ExtractedDoc) -> None:
    checks = run_checks(standard, known_hashes={H}, this_hash=H,
                        period_start=date(2026, 11, 1), period_end=date(2027, 1, 31))
    status, reasons = decide(checks)
    assert status == "needs_a_look"
    assert _codes(reasons) == {"DUPLICATE", "DATE_IN_PERIOD"}
    assert reasons[0].startswith("DUPLICATE")  # fails listed before warnings


def test_low_confidence_is_warning_only(standard: ExtractedDoc) -> None:
    status, reasons = _status(standard.model_copy(update={"confidence": 0.5}))
    assert status == "proposed" and _codes(reasons) == {"CONFIDENCE"}


def test_vat_number_normalising() -> None:
    assert normalise_vat_number("gb 232 4567 89") == "GB232456789"
    assert normalise_vat_number("232456789") == "GB232456789"
    assert normalise_vat_number("  ") is None
    bad = _doc(supplier_vat_number="GB12345")
    assert "VAT_NUMBER_FORMAT" in _codes(_status(bad)[1])
    assert "VAT_NUMBER_FORMAT" not in _codes(_status(_doc(supplier_vat_number="GBGD001"))[1])


@pytest.mark.parametrize("name", ["standard", "arith_error", "over_250_no_vat", "eur"])
def test_journals_balance(name: str, request: pytest.FixtureRequest) -> None:
    doc: ExtractedDoc = request.getfixturevalue(name)
    j = draft_journal(doc)
    assert is_balanced(j), j
    assert all(x.debit_pence >= 0 and x.credit_pence >= 0 for x in j)


def test_standard_journal_shape(standard: ExtractedDoc) -> None:
    j = draft_journal(standard)
    by = {x.account: x for x in j}
    assert by["5100 Tools & small equipment"].debit_pence == 3206
    assert by[VAT_CONTROL].debit_pence == 641
    assert by["1200 Bank"].credit_pence == 3847
    assert by["5100 Tools & small equipment"].vat_code == "S"


def test_no_vat_number_vat_not_reclaimed(over_250_no_vat: ExtractedDoc) -> None:
    j = draft_journal(over_250_no_vat)
    assert VAT_CONTROL not in {x.account for x in j}
    assert j[0].debit_pence == 30000 and j[0].vat_code == "N"
    assert j[-1].account == CREDITORS and j[-1].credit_pence == 30000


def test_eur_coded_outside_scope(eur: ExtractedDoc) -> None:
    j = draft_journal(eur)
    assert {x.vat_code for x in j if x.debit_pence} == {"O"}


def test_sales_invoice_journal() -> None:
    doc = _doc(doc_type="sales_invoice", customer_name="Acme Ltd", category_guess="Sales",
               lines=[ExtractedLine(description="Consultancy", qty=2, unit_price=100, net=200, vat_rate=20, vat=40)],
               net_total=200, vat_total=40, gross_total=240, payment_method=None)
    j = draft_journal(doc)
    assert is_balanced(j)
    assert (j[0].account, j[0].debit_pence) == ("1100 Debtors", 24000)
    assert {(x.account, x.credit_pence) for x in j[1:]} == {("4000 Sales", 20000), (VAT_CONTROL, 4000)}


def test_mixed_rates_split_by_code() -> None:
    doc = _doc(lines=[
        ExtractedLine(description="Sandwich", qty=1, unit_price=3.50, net=3.50, vat_rate=0, vat=0),
        ExtractedLine(description="Hot coffee", qty=1, unit_price=3.00, net=2.50, vat_rate=20, vat=0.50),
    ], net_total=6.00, vat_total=0.50, gross_total=6.50, category_guess="Subsistence")
    assert _status(doc)[0] == "proposed"
    j = draft_journal(doc)
    assert is_balanced(j)
    assert {x.vat_code for x in j if x.account == "7410 Subsistence"} == {"S", "Z"}


def test_schema_is_strict() -> None:
    def walk(node: object) -> None:
        if isinstance(node, dict):
            assert "$ref" not in node and "oneOf" not in node and "allOf" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    s = extraction_json_schema()
    walk(s)
    assert s["properties"]["supplier_vat_number"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
