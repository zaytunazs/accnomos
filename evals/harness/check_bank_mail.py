"""Sanity-check the bank CSVs and mail fixtures against the repo's own parsers and the truth files.

cd evals && python -m harness.check_bank_mail
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "ledger" / "src"))

from accnomos_ledger.bank import BankCsvError, parse_bank_csv  # noqa: E402

GOLD = REPO / "evals" / "gold"


def main() -> None:
    truth = json.loads((GOLD / "bank" / "expected_matches.json").read_text(encoding="utf-8"))
    by_file: dict[str, list[dict]] = {}
    for r in truth["rows"]:
        by_file.setdefault(r["file"], []).append(r)
    for csv_path in sorted((GOLD / "bank").glob("*.csv")):
        rows = by_file[csv_path.name]
        try:
            lines = parse_bank_csv(csv_path.read_bytes(), csv_path.name)
        except BankCsvError as exc:
            print(f"{csv_path.name}: PARSER REJECTS FILE ({exc})")
            continue
        ok = len(lines) == len(rows) and all(
            ln.amount_pence == r["amount_pence"] and ln.date.isoformat() == r["date"]
            for ln, r in zip(lines, rows, strict=True)
        )
        print(f"{csv_path.name}: {len(lines)}/{len(rows)} rows parsed, amounts and dates {'match' if ok else 'DIFFER'}")
    for p in sorted((GOLD / "mail").glob("M*.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        for a in m["attachments"]:
            f = GOLD / "mail" / a["path"]
            assert f.exists() and f.stat().st_size == a["size"], (p.name, a["name"])
            assert f.stat().st_size < 2 * 1024 * 1024
            if a["gold"]:
                assert (GOLD / "receipts" / a["gold"]).exists()
        assert {e["attachment"] for e in m["expected"]["intake"]} == {a["name"] for a in m["attachments"]}, p.name
    print("mail fixtures consistent")


if __name__ == "__main__":
    main()
