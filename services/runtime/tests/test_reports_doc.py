"""docs/REPORTS.md stays complete: every registered export is documented, and the reports the set-up wizard
promises (VAT boxes 1-9, VAT detail, P&L, balance sheet, aged debtors/creditors, vendor bundles) all exist.
"""

from __future__ import annotations

from pathlib import Path

from app.exports.registry import catalogue

ROOT = Path(__file__).resolve().parents[3]
DOC = (ROOT / "docs" / "REPORTS.md").read_text(encoding="utf-8")

REQUIRED = {
    "vat-return",  # the 9 boxes, HMRC's own names and numbers
    "vat-detail",
    "profit-and-loss",
    "balance-sheet",
    "aged-receivables-detail",
    "aged-receivables-summary",
    "aged-payables-detail",
    "aged-payables-summary",
    "xero-all",
    "qbo-all",
    "sage50-all",
    "sage-accounting-all",
    "freeagent-all",
}


def test_every_registered_export_is_documented() -> None:
    missing = [spec_id for spec_id in catalogue() if f"`{spec_id}`" not in DOC]
    assert not missing, f"exports missing from docs/REPORTS.md: {missing}"


def test_every_spec_has_a_title_group_and_formats() -> None:
    for spec_id, spec in catalogue().items():
        assert spec.title.strip(), spec_id
        assert spec.group.strip(), spec_id
        assert spec.formats, spec_id


def test_the_wizard_s_reports_all_exist() -> None:
    assert set(catalogue()) >= REQUIRED


def test_vat_return_has_nine_hmrc_boxes() -> None:
    from app.exports import vat_reports

    numbers = [n for n, _ in vat_reports.BOXES]
    assert numbers == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert all(label.strip() for _, label in vat_reports.BOXES)
    assert "70012" in vat_reports.GUIDANCE
