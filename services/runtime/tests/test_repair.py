"""Deterministic repairs (app/repair.py) on hand-made readings shaped like the eval's failures. No model calls."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.checks import decide, run_checks  # noqa: E402
from app.repair import repair, repair_vat_inclusive_totals  # noqa: E402
from app.schemas import ExtractedDoc, ExtractedLine  # noqa: E402

H = "b" * 64


def _ln(qty: float, unit: float, net: float, vat: float, rate: float | None = 20) -> ExtractedLine:
    return ExtractedLine(description="item", qty=qty, unit_price=unit, net=net, vat_rate=rate, vat=vat)


def _doc(lines: list[ExtractedLine], net: float, vat: float, gross: float, **kw: object) -> ExtractedDoc:
    base: dict[str, object] = dict(
        doc_type="receipt",
        supplier_name="Corner Cafe",
        supplier_vat_number="GB123456789",
        customer_name=None,
        invoice_number=None,
        date="2026-10-21",
        currency="GBP",
        lines=lines,
        net_total=net,
        vat_total=vat,
        gross_total=gross,
        payment_method="card",
        card_last4=None,
        category_guess="Sundry",
        confidence=0.6,
    )
    base.update(kw)
    return ExtractedDoc.model_validate(base)


def _status(doc: ExtractedDoc) -> str:
    return decide(repair(doc, None) + run_checks(doc, known_hashes=frozenset(), this_hash=H))[0]


# --- 2a: VAT-inclusive totals ---------------------------------------------------------------


def test_net_read_as_inclusive_total_is_repaired() -> None:
    # 081_r_cafe: net == printed TOTAL, VAT right, gross right.
    doc = _doc([_ln(4, 6.50, 26.00, 5.20), _ln(4, 3.80, 15.20, 3.04)], net=41.20, vat=6.86, gross=41.20)
    chk = repair_vat_inclusive_totals(doc)
    assert chk is not None and chk.code == "TOTALS_REPAIRED" and chk.ok
    assert (doc.net_total, doc.vat_total, doc.gross_total) == (34.34, 6.86, 41.20)
    assert "£41.20" in chk.message and "£34.34" in chk.message


def test_vat_added_on_top_of_inclusive_total_is_repaired() -> None:
    # 125_r_trade: printed TOTAL 221.50 taken as net and VAT (its 1/6 share) added on top.
    doc = _doc([_ln(1, 221.50, 221.50, 36.93)], net=221.50, vat=36.93, gross=258.43)
    assert repair_vat_inclusive_totals(doc) is not None
    assert (doc.net_total, doc.vat_total, doc.gross_total) == (184.57, 36.93, 221.50)


def test_misread_vat_fixed_when_net_and_gross_agree_at_the_rate() -> None:
    doc = _doc([_ln(1, 50.00, 50.00, 10.00)], net=50.00, vat=1.00, gross=60.00)
    assert repair_vat_inclusive_totals(doc) is not None
    assert doc.vat_total == 10.00


def test_consistent_reading_is_left_alone() -> None:
    doc = _doc([_ln(1, 50.00, 50.00, 10.00)], net=50.00, vat=10.00, gross=60.00)
    assert repair_vat_inclusive_totals(doc) is None
    assert (doc.net_total, doc.vat_total, doc.gross_total) == (50.00, 10.00, 60.00)


def test_no_repair_when_vat_would_not_fit_the_rate() -> None:
    # net == gross, but gross - VAT = 30.00 and 20% of that is 6.00, not 20.00: nothing to trust, leave it.
    doc = _doc([_ln(1, 50.00, 50.00, 10.00)], net=50.00, vat=20.00, gross=50.00)
    assert repair_vat_inclusive_totals(doc) is None
    assert doc.net_total == 50.00


def test_genuine_arithmetic_error_is_not_repaired() -> None:
    doc = _doc([_ln(1, 50.00, 50.00, 10.00)], net=51.00, vat=10.00, gross=60.00)
    assert repair_vat_inclusive_totals(doc) is None
    assert _status(doc) == "needs_a_look"


def test_no_vat_means_no_totals_repair() -> None:
    doc = _doc([_ln(1, 50.00, 50.00, 0.00, rate=None)], net=50.00, vat=0.00, gross=55.00)
    assert repair_vat_inclusive_totals(doc) is None


def test_repaired_reading_then_passes_with_a_note() -> None:
    doc = _doc([_ln(4, 6.50, 26.00, 5.20), _ln(4, 3.80, 15.20, 3.04)], net=41.20, vat=6.86, gross=41.20)
    notes = repair(doc, None)
    assert [n.code for n in notes][0] == "TOTALS_REPAIRED"
    assert decide(notes + run_checks(doc, known_hashes=frozenset(), this_hash=H))[0] == "proposed"


async def test_pipeline_records_repaired_by_code(monkeypatch) -> None:
    from app import pipeline
    from app.ai.config import AiConfig

    async def fake_extract(image_bytes, mime, cfg):
        doc = _doc([_ln(4, 6.50, 26.00, 5.20), _ln(4, 3.80, 15.20, 3.04)], net=41.20, vat=6.86, gross=41.20)
        return doc, {"backend": "local", "model": "stub"}

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    monkeypatch.setenv("VERIFIER", "off")
    p = await pipeline.process_image(b"img", "image/jpeg", AiConfig(mode="local", base_url="http://x", model="m"))
    assert p.extracted.net_total == 34.34
    assert len(p.repaired_by_code) >= 1 and "VAT-inclusive total" in p.repaired_by_code[0]
    assert any(c.code == "TOTALS_REPAIRED" and c.ok for c in p.checks)
