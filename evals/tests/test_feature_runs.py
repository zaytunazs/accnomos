"""The feature evals that need no model: bank matching on the six gold statements. Floors, not targets."""

from __future__ import annotations

import asyncio

from harness.bank_match import run


def test_bank_matching_makes_no_wrong_suggestion_and_finds_the_whole_payments() -> None:
    res = asyncio.run(run())
    assert res["wrong"] == [] and res["precision"] == 1.0
    assert res["correct_pairs"] >= 83  # 106 truth pairs; the 20 part-payment rows are not supported
    assert res["by_row_kind"]["direct debit"]["found"] == res["by_row_kind"]["direct debit"]["truth"]
