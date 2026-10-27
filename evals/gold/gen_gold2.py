#!/usr/bin/env python3
# ruff: noqa: E501, UP031  (the prompts are kept verbatim as they were sent to Qwen)
"""Ledger2 gold set with Qwen3.8-27B (local vLLM on the Spark, :8000): supplier credit notes, part-paid / overpaid
sales invoices and overlapping bank statement pairs, for part payments, credit notes and bank reconciliation.

    python evals/gold/gen_gold2.py [N]      # N credit notes and N part-paid invoices (default 40), N/4 bank pairs

Qwen invents the fictional businesses and lines; code checks every line's VAT (net x rate, rounded), the totals,
the payment cases (part / part_open / over / exact) and works out the bank balances and the overlap itself, so the
expected answers are right by construction. Every document is labelled SAMPLE — FICTIONAL COMPANY.
Run on 27 Oct 2026: 90 items kept, 4 dropped by the checks, about 81 minutes. Writes evals/gold/ledger2/.
"""

import csv
import io
import json
import pathlib
import random
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent / "ledger2"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
LABEL = "SAMPLE — FICTIONAL COMPANY"
BIZ = "Bramblewood Joinery Ltd"
QWEN = "http://127.0.0.1:8000/v1/chat/completions"


def ask(prompt: str, max_tokens: int = 2200) -> dict:
    body = {
        "model": "qwen3.8-27b",
        "temperature": 0.9,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": "You generate realistic but entirely fictional UK accounting test documents. "
                "Never use real company names.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(QWEN, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def lines_ok(d: dict, sign: int) -> bool:
    ls = d["lines"]
    net = round(sum(x["net"] for x in ls), 2)
    vat = round(sum(x["vat"] for x in ls), 2)
    rate_ok = all(
        x["vat_rate"] in (0, 5, 20) and abs(round(x["net"] * x["vat_rate"] / 100, 2) - x["vat"]) < 0.011 for x in ls
    )
    signs = all((x["net"] < 0) if sign < 0 else (x["net"] > 0) for x in ls)
    return (
        rate_ok
        and signs
        and abs(net - d["net_total"]) < 0.011
        and abs(vat - d["vat_total"]) < 0.011
        and abs(net + vat - d["gross_total"]) < 0.011
    )


CN = """Generate a SUPPLIER CREDIT NOTE received by '%s' from a fictional UK trade supplier: %s.
Return ONLY JSON: {"doc_type":"credit_note","supplier":{"name":str,"vat_number":"GB + 9 digits","address":str},"customer":{"name":"%s"},
"credit_note_number":str,"original_invoice_number":str,"original_invoice_date":"YYYY-MM-DD","date":"YYYY-MM-DD" (2026-07-01..2026-10-25, after the original),
"reason":str,"lines":[{"description":str,"qty":number,"unit_price":number (negative),"net":number (negative),"vat_rate":0|5|20,"vat":number (negative)}],
"net_total":number (negative),"vat_total":number (negative),"gross_total":number (negative),"printed_text":str (8-25 lines as printed)}
Amounts 2 dp; vat = net*rate/100 rounded per line."""
CN_CASES = [
    "a full credit for goods returned, 20%% VAT, 1-3 lines",
    "a partial credit for one damaged item out of an earlier invoice",
    "a price-adjustment credit (overcharge) of a few pounds",
    "a credit note mixing 20%% and 0%% lines",
]
PP = """Generate a SALES invoice issued BY '%s' (VAT GB 123 4567 89) to a fictional UK customer, plus how it was paid: %s.
Return ONLY JSON: {"doc_type":"sales_invoice","invoice_number":"INV-" + 4 digits,"date":"YYYY-MM-DD" (2026-06-01..2026-09-30),"due_days":14|30,
"customer":{"name":str,"address":str},"lines":[{"description":str,"qty":number,"unit_price":number,"net":number,"vat_rate":20,"vat":number}],
"net_total":number,"vat_total":number,"gross_total":number,
"payments":[{"date":"YYYY-MM-DD","amount":number,"reference":str,"bank_description":str (as a UK bank statement would show it)}]}"""
PP_CASES = [
    ("part", "paid in two instalments that add up to the gross total"),
    ("part_open", "one part payment of roughly half; the rest still unpaid"),
    ("over", ""),  # filled per document with a random overpayment
    ("exact", "paid in full in one payment with the invoice number as reference"),
]
STATUS = {"part": "paid", "part_open": "part_paid", "over": "overpaid", "exact": "paid"}
BK = """Generate %d bank statement transactions for the business current account of '%s' (a joiner) between %s and %s.
Mix: card purchases at fictional trade suppliers, fuel, phone/broadband direct debits, HMRC VAT payment, customer receipts (Faster Payment) citing INV-#### numbers,
bank charges. Return ONLY JSON: {"transactions":[{"date":"YYYY-MM-DD","description":str (UPPERCASE like a UK bank export),"amount":number (negative = money out)}]} in date order."""


def gen_credit_notes(n: int, log: list) -> None:
    out = ROOT / "credit_notes"
    out.mkdir(parents=True, exist_ok=True)
    k = tries = 0
    while k < n and tries < n * 3:
        tries += 1
        try:
            d = ask(CN % (BIZ, random.choice(CN_CASES), BIZ))
            ok = lines_ok(d, -1)
        except Exception as e:  # a bad answer is dropped, never fixed up
            print("ERR cn", e, flush=True)
            continue
        if not ok:
            print("DROP cn", flush=True)
            continue
        k += 1
        d["label"], d["gold_case"] = LABEL, "credit_note"
        name = f"{k:03d}_credit_note.json"
        (out / name).write_text(json.dumps(d, indent=1, ensure_ascii=False))
        log.append({"file": f"credit_notes/{name}", "case": "credit_note", "gross": d["gross_total"]})
        print("OK cn", k, d["supplier"]["name"], d["gross_total"], flush=True)


def gen_part_paid(n: int, log: list) -> None:
    out = ROOT / "part_paid"
    out.mkdir(parents=True, exist_ok=True)
    k = tries = 0
    while k < n and tries < n * 3:
        tries += 1
        case, desc = random.choice(PP_CASES)
        if case == "over":
            desc = "paid once, by mistake %d pounds more than the gross total" % random.randint(5, 60)
        try:
            d = ask(PP % (BIZ, desc))
            paid = round(sum(p["amount"] for p in d["payments"]), 2)
            g = d["gross_total"]
            ok = (
                lines_ok(d, 1)
                and {
                    "part": abs(paid - g) < 0.011 and len(d["payments"]) >= 2,
                    "part_open": 0 < paid < g - 1,
                    "over": paid > g + 1,
                    "exact": abs(paid - g) < 0.011 and len(d["payments"]) == 1,
                }[case]
            )
        except Exception as e:
            print("ERR pp", e, flush=True)
            continue
        if not ok:
            print("DROP pp", case, flush=True)
            continue
        k += 1
        d["label"], d["gold_case"] = LABEL, case
        d["expected"] = {"paid": paid, "outstanding": round(g - paid, 2), "status": STATUS[case]}
        name = f"{k:03d}_{case}.json"
        (out / name).write_text(json.dumps(d, indent=1, ensure_ascii=False))
        log.append({"file": f"part_paid/{name}", "case": case, "gross": g, "paid": paid})
        print("OK pp", k, case, g, paid, flush=True)


def to_csv(rows: list, opening: float) -> tuple[str, float]:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Date", "Description", "Amount", "Balance"])
    bal = opening
    for r in rows:
        bal = round(bal + r["amount"], 2)
        w.writerow([r["date"], r["description"], f"{r['amount']:.2f}", f"{bal:.2f}"])
    return buf.getvalue(), bal


def gen_bank_pairs(n: int, log: list) -> None:
    out = ROOT / "bank_pairs"
    out.mkdir(parents=True, exist_ok=True)
    k = tries = 0
    while k < n and tries < n * 3:
        tries += 1
        m = random.choice([7, 8, 9])
        try:
            d = ask(BK % (40, BIZ, f"2026-{m:02d}-01", f"2026-{m:02d}-28"), 4000)
            tx = [
                t
                for t in d["transactions"]
                if isinstance(t["amount"], (int, float)) and t["date"].startswith(f"2026-{m:02d}")
            ]
            tx.sort(key=lambda t: t["date"])
        except Exception as e:
            print("ERR bk", e, flush=True)
            continue
        if len(tx) < 24:
            print("DROP bk", len(tx), flush=True)
            continue
        k += 1
        # The second statement repeats the last `overlap` lines of the first, as a re-export would.
        cut = len(tx) * 2 // 3
        overlap = random.randint(4, 8)
        opening = round(random.uniform(2000, 15000), 2)
        a_rows, b_rows = tx[:cut], tx[cut - overlap :]
        a_csv, _ = to_csv(a_rows, opening)
        b_open = round(opening + sum(t["amount"] for t in tx[: cut - overlap]), 2)
        b_csv, closing = to_csv(b_rows, b_open)
        (out / f"{k:03d}_a.csv").write_text(a_csv)
        (out / f"{k:03d}_b.csv").write_text(b_csv)
        meta = {
            "label": LABEL,
            "first": f"{k:03d}_a.csv",
            "second": f"{k:03d}_b.csv",
            "lines_a": len(a_rows),
            "lines_b": len(b_rows),
            "overlap": overlap,
            "expected_unique_lines": len(tx),
            "closing_balance": closing,
        }
        (out / f"{k:03d}_meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        log.append({"file": f"bank_pairs/{k:03d}_meta.json", "case": "bank_overlap", **meta})
        print("OK bk", k, len(tx), overlap, flush=True)


if __name__ == "__main__":
    random.seed(27)
    log: list = []
    t0 = time.time()
    gen_credit_notes(N, log)
    gen_part_paid(N, log)
    gen_bank_pairs(max(10, N // 4), log)
    manifest = {"generated_by": "qwen3.8-27b on DGX Spark", "label": LABEL, "count": len(log), "items": log}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print("DONE", len(log), "items in", f"{time.time() - t0:.0f}s")
