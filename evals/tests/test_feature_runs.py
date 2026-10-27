"""The feature evals that need no model: bank matching on the six gold statements, mail intake and the triage
filters on the 20 mailbox fixtures. Floors, not targets."""

from __future__ import annotations

import asyncio

from harness import mail_intake
from harness.bank_match import run


def test_bank_matching_makes_no_wrong_suggestion_and_finds_the_whole_payments() -> None:
    res = asyncio.run(run())
    assert res["wrong"] == [] and res["precision"] == 1.0
    assert res["correct_pairs"] >= 83  # 106 truth pairs; the 20 part-payment rows are not supported
    assert res["by_row_kind"]["direct debit"]["found"] == res["by_row_kind"]["direct debit"]["truth"]


def test_mail_intake_drops_every_decoy_and_saves_a_resent_document_once() -> None:
    res = asyncio.run(mail_intake.run(use_model=False))
    i, t = res["intake"], res["triage"]
    assert i["decoys_dropped"] == i["decoys"] and i["duplicates_caught"] == i["duplicates"] == 1
    assert i["documents_kept"] >= 12 and i["errors"] == []  # 17 documents; colleague-forwarded photos score 0.3
    assert t["keep_drop_agree"] == t["scored"] == 13
