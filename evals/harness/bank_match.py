"""Bank matching eval: the six two-month statements through the real matcher, scored against the truth file.

    cd evals && python -m harness.bank_match            # writes runs/bank_matching/{report.md,result.json}

The 140 gold documents (061-200) are posted into a Books on fake storage as the app would post them:
gold fields -> ExtractedDoc -> app.journal.draft_journal -> app.approve.build_event, with a posted proposal
per document so the card last-4 hints come from the same place as in the app (Books.card_hints).
Credit notes have no posting path in the app yet (doc types are receipt / purchase / sales invoice), so
their journal is drafted from the positive amounts and turned round (Dr creditors / Cr expense for a
supplier credit note, Dr sales / Cr debtors for a customer one). The CSVs go in through
Books.import_bank_csv and the suggestions come from Books.bank_suggestions, the same call the
/books/bank routes make. `expected_matches.json` is only read for scoring.

A pair is (bank row, document). Precision = suggested pairs that are in the truth / suggested pairs;
recall = truth pairs suggested / truth pairs. A part payment row is its own truth pair.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src", REPO / "packages" / "connectors" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from accnomos_connectors import FakeStorageProvider  # noqa: E402
from accnomos_ledger.bank import parse_bank_csv  # noqa: E402

from app.approve import build_event  # noqa: E402
from app.books import Books  # noqa: E402
from app.journal import draft_journal  # noqa: E402
from app.schemas import ExtractedDoc, ExtractedLine, JournalLine, Proposal  # noqa: E402

GOLD = REPO / "evals" / "gold"
USER = "eval@example.co.uk"
METHODS = {"bank transfer": "bank_transfer", "direct debit": "direct_debit", "card": "card", "cash": "cash"}
CATEGORY = {"r_fuel": "Motor expenses", "r_parking": "Travel", "r_cafe": "Subsistence", "r_trade": "Tools & small equipment",
            "pi_merchant": "Materials", "pi_subcontractor": "Professional fees", "pi_software": "Software & subscriptions",
            "utility": "Utilities", "sales": "Sales"}


def gold_docs() -> list[tuple[str, dict[str, Any]]]:
    paths = sorted((GOLD / "receipts").glob("*.json"))[60:]
    return [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in paths]


def to_extracted(g: dict[str, Any]) -> ExtractedDoc:
    """Gold fields as the vision model would return them (amounts made positive for credit notes)."""
    sign = -1 if g["is_credit_note"] else 1
    sale = g["side"] == "sale"
    return ExtractedDoc(
        doc_type="sales_invoice" if sale else ("receipt" if g["gold_case"].startswith("r_") else "purchase_invoice"),
        supplier_name=g["supplier"]["name"], supplier_vat_number=g["supplier"].get("vat_number"),
        customer_name=(g.get("customer") or {}).get("name"), invoice_number=g.get("invoice_number"), date=g["date"],
        currency="GBP",
        lines=[ExtractedLine(description=ln["description"], qty=abs(ln.get("qty") or 1), unit_price=abs(ln.get("unit_price") or 0),
                             net=sign * ln["net"], vat_rate=ln.get("vat_rate"), vat=sign * ln["vat"]) for ln in g["lines"]],
        net_total=sign * g["net_total"], vat_total=sign * g["vat_total"], gross_total=sign * g["gross_total"],
        payment_method=METHODS.get(g["payment_method"] or "", "unknown"), card_last4=g.get("card_last4"),
        category_guess=CATEGORY.get(g["gold_case"], "Sundry"), confidence=1.0,
    )


def journal_for(g: dict[str, Any], doc: ExtractedDoc) -> list[JournalLine]:
    journal = draft_journal(doc)
    if not g["is_credit_note"]:
        return journal
    return [JournalLine(account=j.account, debit_pence=j.credit_pence, credit_pence=j.debit_pence, vat_code=j.vat_code) for j in journal]


async def build_books() -> tuple[Books, dict[str, str]]:
    """Books with the 140 gold documents posted; returns it and event id -> gold file name."""
    books = Books(FakeStorageProvider())
    by_event: dict[str, str] = {}
    for name, g in gold_docs():
        doc = to_extracted(g)
        journal = journal_for(g, doc)
        p = Proposal(id=Path(name).stem, doc_sha256=hashlib.sha256(name.encode()).hexdigest(), extracted=doc, checks=[], status="posted",
                     reasons=[], suggested_filename=name, journal_draft=journal, model="gold", elapsed_s=0.0)
        event = build_event(p, journal, USER)
        p.event_id = event.id
        p.decided_by, p.decided_at = USER, datetime(2026, 10, 27, tzinfo=UTC)
        await books.post_event(event)
        await books.save_proposal(p)
        by_event[event.id] = name
    return books, by_event


async def run() -> dict[str, Any]:
    truth = json.loads((GOLD / "bank" / "expected_matches.json").read_text(encoding="utf-8"))
    books, by_event = await build_books()
    row_of: dict[str, dict[str, Any]] = {}  # bank line id -> truth row
    rows_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in truth["rows"]:
        rows_by_file[r["file"]].append(r)
    for csv_path in sorted((GOLD / "bank").glob("*_*.csv")):
        data = csv_path.read_bytes()
        lines = parse_bank_csv(data, csv_path.name)
        assert len(lines) == len(rows_by_file[csv_path.name]), csv_path.name
        for ln, r in zip(lines, rows_by_file[csv_path.name], strict=True):
            row_of[ln.id] = r
        await books.import_bank_csv(data, csv_path.name, USER)
    stored = await books.stored_bank_lines()
    assert len(stored) == len(truth["rows"]), "every row imported once"

    matches = await books.bank_suggestions()
    want = {(r["file"], r["row"], r["gold"]) for r in truth["rows"] if r["gold"]}
    got: list[dict[str, Any]] = []
    for m in matches:
        r = row_of[m.line_id]
        for eid in m.event_ids:
            got.append({"file": r["file"], "row": r["row"], "doc": by_event[eid], "gold": r["gold"], "row_kind": r["kind"],
                        "kind": m.kind, "score": m.score, "reasons": m.reasons, "ok": r["gold"] == by_event[eid]})
    hit = {(g["file"], g["row"], g["doc"]) for g in got if g["ok"]}
    missed = [r for r in truth["rows"] if r["gold"] and (r["file"], r["row"], r["gold"]) not in hit]

    by_kind: dict[str, Counter] = defaultdict(Counter)
    for r in truth["rows"]:
        if r["gold"]:
            by_kind[r["kind"]]["truth"] += 1
            by_kind[r["kind"]]["found"] += (r["file"], r["row"], r["gold"]) in hit
    for g in got:
        by_kind[g["row_kind"]]["suggested"] += 1
        by_kind[g["row_kind"]]["wrong"] += not g["ok"]
    by_match_kind = {k: {"pairs": sum(g["kind"] == k for g in got), "correct": sum(g["kind"] == k and g["ok"] for g in got)}
                     for k in ("exact", "suggested")}
    return {
        "rows": len(truth["rows"]), "events": len(by_event), "truth_pairs": len(want), "suggested_pairs": len(got),
        "correct_pairs": len(hit),
        "precision": round(len(hit) / len(got), 4) if got else None, "recall": round(len(hit) / len(want), 4),
        "by_match_kind": by_match_kind,
        "by_row_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
        "wrong": [g for g in got if not g["ok"]], "missed": missed,
    }


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f} %)" if b else "n/a"


def report_md(res: dict[str, Any]) -> str:
    out = [
        "# Bank matching: six statements through `suggest_matches`",
        "",
        "Generated by `cd evals && python -m harness.bank_match`. 140 gold documents (061-200) posted into a Books on fake",
        "storage via `draft_journal` / `build_event`; the six two-month CSVs imported with `Books.import_bank_csv`; suggestions",
        "from `Books.bank_suggestions` (same call as `/books/bank/lines`). Scored against `evals/gold/bank/expected_matches.json`.",
        "",
        f"- Bank rows: {res['rows']}, ledger events: {res['events']}, truth pairs (row → document): {res['truth_pairs']}",
        f"- **Precision {pct(res['correct_pairs'], res['suggested_pairs'])}**, "
        f"**recall {pct(res['correct_pairs'], res['truth_pairs'])}**",
        "",
        "| Match kind | Pairs | Correct |",
        "|---|---:|---:|",
    ]
    for k, v in res["by_match_kind"].items():
        out.append(f"| {k} | {v['pairs']} | {v['correct']} |")
    out += ["", "| Row kind (truth) | Truth pairs | Found | Suggested | Wrong |", "|---|---:|---:|---:|---:|"]
    for k, v in res["by_row_kind"].items():
        out.append(f"| {k} | {v.get('truth', 0)} | {v.get('found', 0)} | {v.get('suggested', 0)} | {v.get('wrong', 0)} |")
    parts = res["by_row_kind"].get("part", {})
    out += [
        "",
        "## Reading the numbers",
        "",
        "- With the matcher as it was on main at `d706f04` (±5 days for everything) the same run gave precision 51/51 and recall",
        "  51/106 (48 %): no direct debit and only 8 of 31 BACS / customer payments matched, because they arrive more than 5 days",
        "  after the document. Payments on terms may now be up to 60 days later, only when the line carries the counterparty's",
        "  name, and never as `exact`.",
        f"- Part payments are not supported: one event paid by two bank lines is never suggested ({parts.get('found', 0)}/"
        f"{parts.get('truth', 0)} part rows found). Confirming two lines against one event would also need `Books.confirm_match`"
        " to accept it.",
        "- Supplier credit-note refunds into Tide are bank-settled events with no transfer marker in the description (the parser",
        "  keeps Tide's `Transaction Information`, not its `Transaction Type`), so a refund more than 5 days after the credit note",
        "  is missed.",
        "- Credit notes cannot be posted in the app yet; this run posts them by turning the drafted journal round.",
    ]
    out += ["", "## Wrong suggestions", ""]
    out += [f"- {g['file']} row {g['row']} ({g['row_kind']}): suggested {g['doc']}, truth {g['gold'] or 'no document'} "
            f"({g['kind']}, {g['score']}; {'; '.join(g['reasons'])})" for g in res["wrong"]] or ["None."]
    out += ["", "## Missed", ""]
    out += [f"- {r['file']} row {r['row']} {r['date']} {r['amount_pence'] / 100:.2f} ({r['kind']}): {r['gold']}" for r in res["missed"]] or ["None."]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=REPO / "evals" / "runs" / "bank_matching")
    args = ap.parse_args()
    res = asyncio.run(run())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "result.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    (args.out / "report.md").write_text(report_md(res), encoding="utf-8")
    print(f"precision {pct(res['correct_pairs'], res['suggested_pairs'])}, recall {pct(res['correct_pairs'], res['truth_pairs'])}")


if __name__ == "__main__":
    main()
