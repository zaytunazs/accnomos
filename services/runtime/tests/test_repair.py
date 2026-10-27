"""Deterministic repairs (app/repair.py) on hand-made readings shaped like the eval's failures. No model calls."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.checks import decide, run_checks  # noqa: E402
from app.repair import repair, repair_lines, repair_vat_inclusive_totals  # noqa: E402
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


def test_totals_repair_messages_are_worded_exactly() -> None:
    # The messages are shown to the user; pinned so line-wrapping in the source can't change them.
    cases = [
        (
            _doc([_ln(4, 6.50, 26.00, 5.20), _ln(4, 3.80, 15.20, 3.04)], net=41.20, vat=6.86, gross=41.20),
            "Net £41.20 was the VAT-inclusive total; net set to total £41.20 − VAT £6.86 = £34.34",
        ),
        (
            _doc([_ln(1, 50.00, 50.00, 10.00)], net=50.00, vat=1.00, gross=60.00),
            "VAT £1.00 did not fit net £50.00 and total £60.00 at 20%; VAT set to £10.00",
        ),
        (
            _doc([_ln(1, 221.50, 221.50, 36.93)], net=221.50, vat=36.93, gross=258.43),
            "VAT had been added on top of the VAT-inclusive total £221.50; total set to £221.50, net to £184.57",
        ),
    ]
    for doc, msg in cases:
        chk = repair_vat_inclusive_totals(doc)
        assert chk is not None and chk.message == msg


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


# --- 2b: quantity x unit price per line -----------------------------------------------------


def test_doubled_quantity_undone_and_net_anchored_on_the_total() -> None:
    # 005_no_vat_number: printed line totals 250.00 / 73.00 read as unit prices and multiplied by qty again.
    doc = _doc(
        [_ln(1, 45.50, 45.50, 0, None), _ln(2, 250.00, 500.00, 0, None), _ln(4, 73.00, 292.00, 0, None)],
        net=837.50,
        vat=0.00,
        gross=368.50,
    )
    chk = repair_lines(doc)
    assert chk is not None and chk.code == "LINES_REPAIRED"
    assert [ln.net for ln in doc.lines] == [45.50, 250.00, 73.00]
    assert [ln.unit_price for ln in doc.lines] == [45.50, 125.00, 18.25]
    assert doc.net_total == 368.50 and "£837.50" in chk.message


def test_only_the_doubled_lines_are_changed() -> None:
    # Line 1 (2 x 5.00 = 10.00) is right; line 2's total 30.00 was multiplied by 3 again.
    doc = _doc([_ln(2, 5.00, 10.00, 2.00), _ln(3, 30.00, 90.00, 18.00)], net=40.00, vat=8.00, gross=48.00)
    assert repair_lines(doc) is not None
    assert [(ln.net, ln.vat, ln.unit_price) for ln in doc.lines] == [(10.00, 2.00, 5.00), (30.00, 6.00, 10.00)]


def test_line_total_in_unit_column_is_not_multiplied_again() -> None:
    # 057_mixed: lines already add up; "2 x 2.50 = 2.50" means 2.50 is the line total, so unit = 1.25.
    doc = _doc([_ln(2, 2.50, 2.50, 0.00, 0), _ln(1, 4.99, 4.99, 0.00, 0)], net=7.49, vat=0.00, gross=7.49)
    chk = repair_lines(doc)
    assert chk is not None and "unit price" in chk.message
    assert doc.lines[0].unit_price == 1.25 and doc.lines[0].net == 2.50 and doc.net_total == 7.49
    assert _status(doc) == "proposed"


def test_vat_inclusive_lines_split_into_net_and_vat() -> None:
    # 081_r_cafe after the totals repair: lines add up to the gross, so each is split at its rate.
    doc = _doc([_ln(4, 6.50, 26.00, 5.20), _ln(4, 3.80, 15.20, 3.04)], net=34.34, vat=6.86, gross=41.20)
    assert repair_lines(doc) is not None
    assert [(ln.net, ln.vat) for ln in doc.lines] == [(21.67, 4.33), (12.67, 2.53)]
    assert _status(doc) == "proposed"


def test_lines_that_already_add_up_are_left_alone() -> None:
    doc = _doc([_ln(2, 5.00, 10.00, 2.00), _ln(1, 30.00, 30.00, 6.00)], net=40.00, vat=8.00, gross=48.00)
    assert repair_lines(doc) is None


def test_no_line_repair_without_an_exact_match() -> None:
    # Overshooting lines that no subset of un-doubled lines explains: report, do not guess.
    doc = _doc([_ln(2, 7.00, 14.00, 2.80), _ln(3, 9.00, 27.00, 5.40)], net=30.00, vat=6.00, gross=36.00)
    assert repair_lines(doc) is None
    assert [ln.net for ln in doc.lines] == [14.00, 27.00]


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
