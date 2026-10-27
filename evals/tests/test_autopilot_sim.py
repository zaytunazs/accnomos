"""Offline checks on the Autopilot L2 simulator's scoring and document classes. No model calls."""

from __future__ import annotations

import json
from datetime import date

from harness import autopilot_sim as sim
from harness.run_extraction import GOLD_DIR


def _gold(name: str) -> dict:
    return json.loads((GOLD_DIR / name).read_text(encoding="utf-8"))


def _rec(**kw: object) -> dict:
    base = {"error": None, "posted": True, "duplicate": False, "expected_status": "proposed", "should_post": True}
    return base | kw


def _extracted(gold: dict) -> dict:
    return {"doc_type": "receipt", "supplier_name": gold["supplier"]["name"], "supplier_vat_number": gold["supplier"]["vat_number"],
            "date": gold["date"], "net_total": gold["net_total"], "vat_total": gold["vat_total"], "gross_total": gold["gross_total"]}


def test_a_post_matching_gold_is_correct() -> None:
    g = _gold("001_standard.json")
    rec = _rec(extracted=_extracted(g))
    sim.grade(rec, g, {"net": 4325, "vat": 865})
    assert rec["correct_post"] and not rec["false_post"] and not rec["missed_post"]


def test_a_post_with_one_field_off_by_two_pence_is_false() -> None:
    g = _gold("001_standard.json")
    rec = _rec(extracted=_extracted(g) | {"vat_total": 8.67})
    sim.grade(rec, g, {"net": 4325, "vat": 867})
    assert rec["false_post"] and rec["diffs"] == ["vat", "event_vat"]


def test_posting_a_duplicate_or_a_needs_a_look_is_false_even_when_read_right() -> None:
    g = _gold("001_standard.json")
    for kw in ({"duplicate": True, "should_post": False}, {"expected_status": "needs_a_look", "should_post": False}):
        rec = _rec(extracted=_extracted(g), **kw)
        sim.grade(rec, g, {"net": 4325, "vat": 865})
        assert rec["false_post"] and not rec["diffs"]


def test_left_in_review_when_gold_says_post_is_a_missed_post() -> None:
    g = _gold("001_standard.json")
    rec = _rec(posted=False, extracted=_extracted(g))
    sim.grade(rec, g, None)
    assert rec["missed_post"] and not rec["false_post"] and rec["would_be_false"] is False


def test_document_classes() -> None:
    def cls(gold: dict, render: str = "messy", dup: str = "") -> str:
        return sim.Doc("x", "messy", render, bytes, gold, "x", dup=dup).cls

    assert cls(_gold("001_standard.json"), "clean") == "clean"
    assert cls(_gold("001_standard.json")) == "messy"
    assert cls(_gold("001_standard.json"), dup="new_photo") == "duplicate"
    assert cls(_gold("005_no_vat_number.json")) == "no_vrn"
    assert cls(_gold("091_edge_handwritten.json")) == "handwritten"


def test_the_seed_plan_gives_every_pass_its_documents() -> None:
    plan = sim.sd.build_plan(sim.sd.GOLD_BUSINESS, today=sim.TODAY)
    docs = sim.documents(plan, sim.gold_receipts(), list(sim.PASSES), 0)
    count = {p: sum(d.pass_ == p for d in docs) for p in sim.PASSES}
    purchases = sum(d.extracted["doc_type"] != "sales_invoice" for d in plan.posted)
    assert count == {"inbox": 25, "clean": 200, "messy": 200, "dupes": purchases + sim.EXACT_DUPES}
    assert all(sim.period_of(d, plan)[0] <= date.fromisoformat(d.gold["date"]) for d in docs)
    halves = [sim.shard_of(docs, k, 2) for k in (1, 2)]
    assert sorted(d.id for h in halves for d in h) == sorted(d.id for d in docs)
    assert sum(d.pass_ == "clean" for d in halves[0]) == 100
    seeded = {d.gold for d in plan.posted}
    assert {d.gold_file for d in docs if d.dup == "seeded_copy" and d.pass_ == "clean"} == seeded


def test_no_vat_number_receipt_charging_no_vat_is_expected_to_be_proposed() -> None:
    assert sim.gold_expected(_gold("038_no_vat_number.json")) == "proposed"  # £0 VAT: seller not VAT-registered
    assert sim.gold_expected(_gold("010_foreign.json")) == "needs_a_look"
    assert sim.gold_expected(_gold("065_r_cafe.json")) == "needs_a_look"  # explicit on 061+


def test_refusal_kinds() -> None:
    assert sim.refusal_kind("Check ARITH_LINES warned: line 1") == "ARITH_LINES warned"
    assert sim.refusal_kind("£80.00 is more than 2x the usual £38.47") == "over 2x"
    assert sim.refusal_kind("VAT number none differs from GB1 on the rule") == "VAT number differs"
