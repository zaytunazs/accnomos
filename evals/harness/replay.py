"""Replay the current repairs + checks over a finished run's stored readings, without the model.

    cd evals && python -m harness.replay runs/glimmer_messy_200_before [--show]
    cd evals && python -m harness.replay --gold      # perfect readings: the gold fields themselves

Each stored `proposal.extracted` is re-repaired and re-checked with today's app/repair.py and
app/checks.py, then scored against gold. The stored reading already carries the repairs that were
live when the run was made, so this measures what the *new* code changes on top. Prints field
accuracy, status accuracy and false passes (proposed when gold expects needs_a_look, or proposed
with a money field wrong) before vs after.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from app.checks import decide, run_checks  # noqa: E402
from app.repair import REPAIR_CODES, repair  # noqa: E402
from app.schemas import Check, ExtractedDoc  # noqa: E402
from app.testmode import extracted_from_gold  # noqa: E402
from harness.run_extraction import FIELDS, GOLD_DIR, expected_status, score  # noqa: F401 (sets sys.path for app.*)

MONEY = ("net_total", "vat_total", "gross_total")


def false_pass(scores: dict[str, bool], proposal: dict) -> bool:
    """Passed every check, yet the status or a money figure is wrong."""
    return proposal["status"] == "proposed" and (not scores["status"] or not all(scores[m] for m in MONEY))


def replay(proposal: dict, business_name: str | None) -> dict:
    doc = ExtractedDoc.model_validate(copy.deepcopy(proposal["extracted"]))
    repairs = repair(doc, business_name)
    kept = [c for c in proposal["checks"] if c["code"] in ("CROP", "VERIFIER_AGREES")]
    checks = repairs + run_checks(doc, known_hashes=frozenset(), this_hash="x")
    status, _ = decide(checks + [Check.model_validate(c) for c in kept])
    return {
        **proposal,
        "extracted": doc.model_dump(mode="json"),
        "checks": [c.model_dump() for c in checks],
        "status": status,
        "repaired_by_code": [c.message for c in repairs if c.code in REPAIR_CODES],
    }


def gold_statuses(business_name: str | None) -> list[tuple[str, str, str, list[str]]]:
    """(file, status, expected status, reasons) for a perfect reading of every gold document: today's repairs and
    checks, a VAT-registered business and suppliers the books don't know yet (the eval has no books)."""
    out = []
    for path in sorted(GOLD_DIR.glob("[0-9]*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        doc = ExtractedDoc.model_validate(extracted_from_gold(gold))
        status, reasons = decide(repair(doc, business_name) + run_checks(doc, known_hashes=frozenset(), this_hash="x"))
        out.append((path.name, status, expected_status(gold), reasons))
    return out


def main_gold(business_name: str | None, show: bool) -> None:
    rows = gold_statuses(business_name)
    false_passes = [f[:3] for f, s, e, _ in rows if s == "proposed" and e == "needs_a_look"]
    false_alarms = [f[:3] for f, s, e, _ in rows if s == "needs_a_look" and e == "proposed"]
    print(
        f"perfect readings: status {sum(s == e for _, s, e, _ in rows)}/{len(rows)}; "
        f"false passes {len(false_passes)} ({', '.join(false_passes)}); "
        f"false alarms {len(false_alarms)} ({', '.join(false_alarms)})"
    )
    if show:
        for f, s, e, reasons in rows:
            if s != e:
                print(f"{f}: {s}, gold expects {e} | {'; '.join(reasons)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path, nargs="?")
    ap.add_argument("--gold", action="store_true", help="replay perfect readings (the gold fields) instead of a run")
    ap.add_argument("--business-name", default="Bramblewood Joinery Ltd")
    ap.add_argument("--show", action="store_true", help="print every document whose scores or status changed")
    args = ap.parse_args()
    if args.gold:
        return main_gold(args.business_name, args.show)
    if args.run is None:
        ap.error("give a run folder, or --gold")
    before: dict[str, list[bool]] = {f: [] for f in FIELDS}
    after: dict[str, list[bool]] = {f: [] for f in FIELDS}
    fps: dict[str, list[str]] = {"before": [], "after": []}
    tally = {"all_before": 0, "all_after": 0, "fp_before": 0, "fp_after": 0, "repaired": 0, "n": 0}
    for path in sorted(args.run.glob("[0-9]*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if not rec["proposal"]:
            continue
        gold = json.loads((GOLD_DIR / rec["file"]).read_text(encoding="utf-8"))
        s0 = score(gold, rec["proposal"])
        new = replay(rec["proposal"], args.business_name)
        s1 = score(gold, new)
        for f in FIELDS:
            before[f].append(s0[f])
            after[f].append(s1[f])
        tally["n"] += 1
        tally["all_before"] += all(s0.values())
        tally["all_after"] += all(s1.values())
        for when, sc, prop in (("before", s0, rec["proposal"]), ("after", s1, new)):
            if false_pass(sc, prop):
                tally[f"fp_{when}"] += 1
                fps[when].append(rec["file"][:3] + ("" if sc["status"] else " (gold expects needs_a_look)"))
        tally["repaired"] += bool(new["repaired_by_code"])
        if args.show and (s0 != s1 or new["repaired_by_code"]):
            lost = [f for f in FIELDS if s0[f] and not s1[f]]
            won = [f for f in FIELDS if s1[f] and not s0[f]]
            print(
                f"{rec['file']}: +{won} -{lost} {rec['proposal']['status']}->{new['status']} "
                f"| {new['repaired_by_code']}"
            )
    n = tally["n"]
    print("\n| Field | before | after |\n|---|---:|---:|")
    for f in FIELDS:
        print(f"| {f} | {sum(before[f]) / n:.1%} | {sum(after[f]) / n:.1%} |")
    print(f"| all fields | {tally['all_before'] / n:.1%} | {tally['all_after'] / n:.1%} |")
    print(f"| false passes | {tally['fp_before']} | {tally['fp_after']} |")
    for when, files in fps.items():
        print(f"false passes {when}: {', '.join(files)}")
    print(f"\nrepaired by code: {tally['repaired']}/{n}")


if __name__ == "__main__":
    main()
