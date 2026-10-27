#!/usr/bin/env python3
"""Generate a synthetic gold set of UK receipts/invoices with Qwen3.8-27B (vLLM on the Spark).
Every document is fictional and labelled. Arithmetic is validated in code; invalid ones are dropped.
Output: ~/spark/accnomos/gold/receipts/NNN.json + manifest.json
"""

import hashlib
import json
import pathlib
import random
import sys
import time
import urllib.request

OUT = pathlib.Path.home() / "spark/accnomos/gold/receipts"
OUT.mkdir(parents=True, exist_ok=True)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
CASES = [
    ("standard", "a normal standard-rated (20%) purchase receipt under £250 with 2-5 line items"),
    ("standard", "a normal standard-rated (20%) purchase receipt under £250 with 1-3 line items"),
    ("mixed", "a supermarket receipt mixing zero-rated food (0%) and standard-rated (20%) items; VAT shown per rate"),
    ("reduced", "a domestic energy bill at the reduced 5% VAT rate"),
    ("zero", "a zero-rated purchase (books/children's clothing) with VAT £0.00 shown"),
    (
        "no_vat_number",
        "a purchase over £250 whose receipt shows NO VAT registration number (a simplified receipt) - not a valid VAT invoice",
    ),
    ("cash_no_vat", "a cash car-parking ticket or bus ticket with no VAT breakdown and no supplier VAT number"),
    (
        "full_invoice",
        "a full VAT invoice over £250 with invoice number, supplier VAT number, customer name 'Bramblewood Joinery Ltd', due date",
    ),
    (
        "sales_invoice",
        "a SALES invoice issued BY 'Bramblewood Joinery Ltd' (VAT GB 123 4567 89) TO a customer for joinery work, standard-rated",
    ),
    ("exempt", "an insurance or postage receipt that is VAT exempt"),
    (
        "arith_error",
        "a receipt where the printed VAT total is deliberately £0.10 wrong versus net*rate (an error the checker must catch)",
    ),
    ("foreign", "a EUR receipt from a Dutch supplier with reverse-charge wording"),
]
SCHEMA_HINT = """Return ONLY a JSON object:
{"doc_type":"receipt|purchase_invoice|sales_invoice","supplier":{"name":str,"vat_number":str|null,"address":str},
 "customer":{"name":str|null},"invoice_number":str|null,"date":"YYYY-MM-DD" (between 2026-07-01 and 2026-10-25),
 "currency":"GBP"|"EUR","lines":[{"description":str,"qty":number,"unit_price":number,"net":number,"vat_rate":0|5|20|null,"vat":number}],
 "net_total":number,"vat_total":number,"gross_total":number,"payment_method":"card|cash|bank transfer|direct debit",
 "card_last4":str|null,"category_hint":str,"printed_text":str (the receipt exactly as it would be printed, 8-25 lines, monospace, with totals),
 "notes":str}
All suppliers must be FICTIONAL UK trade names (never real companies). Amounts to 2 dp. net+vat=gross for every line and in totals (except the deliberate arith_error case)."""


def ask(prompt):
    body = {
        "model": "qwen3.8-27b",
        "temperature": 0.9,
        "max_tokens": 1800,
        "messages": [
            {
                "role": "system",
                "content": "You generate realistic but entirely fictional UK accounting test documents.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8000/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def valid(d, case):
    try:
        lines = d["lines"]
        net = round(sum(ln["net"] for ln in lines), 2)
        vat = round(sum(ln["vat"] for ln in lines), 2)
        ok_lines = all(abs(ln["net"] + ln["vat"] - round(ln["net"] + ln["vat"], 2)) < 0.011 for ln in lines)
        totals_ok = abs(net - d["net_total"]) < 0.011 and abs(net + vat - d["gross_total"]) < 0.011
        vat_ok = abs(vat - d["vat_total"]) < 0.011
        if case == "arith_error":
            return ok_lines and totals_ok and not vat_ok and 0.05 <= abs(vat - d["vat_total"]) <= 0.5
        return ok_lines and totals_ok and vat_ok and len(d["printed_text"]) > 80
    except Exception:
        return False


manifest = []
i = 0
t0 = time.time()
random.seed(26)
while len(manifest) < N and i < N * 3:
    i += 1
    case, desc = CASES[i % len(CASES)]
    try:
        d = ask(
            f"Generate {desc}. Case id: {case}. Vary supplier, town, date and amounts (seed {random.randint(1, 10**6)}).\n{SCHEMA_HINT}"
        )
    except Exception as e:
        print("ERR", i, e, flush=True)
        continue
    if not valid(d, case):
        print("DROP", i, case, flush=True)
        continue
    d["gold_case"] = case
    d["label"] = "SAMPLE — FICTIONAL COMPANY"
    name = f"{len(manifest) + 1:03d}_{case}.json"
    (OUT / name).write_text(json.dumps(d, indent=1, ensure_ascii=False))
    manifest.append(
        {
            "file": name,
            "case": case,
            "gross": d["gross_total"],
            "sha256": hashlib.sha256(d["printed_text"].encode()).hexdigest(),
        }
    )
    print("OK", name, d["supplier"]["name"], d["gross_total"], f"{time.time() - t0:.0f}s", flush=True)
(OUT.parent / "manifest.json").write_text(
    json.dumps({"generated_by": "qwen3.8-27b on DGX Spark", "count": len(manifest), "items": manifest}, indent=1)
)
print("DONE", len(manifest), "docs in", f"{time.time() - t0:.0f}s")
