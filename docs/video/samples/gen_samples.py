#!/usr/bin/env python3
# ruff: noqa: E501
"""Ten extra fictional sample documents (proposal, 4 Nov 2026), written by hand in code: no model involved.

    python3 docs/video/samples/gen_samples.py        # rewrites S01..S10 .json and .png in this folder

Every supplier, customer, address and person is invented, and every document prints "SAMPLE — FICTIONAL COMPANY".
Arithmetic is done in pence in code. VAT numbers reuse the gold set's scheme (leading 0 block, valid mod-97 checksum,
fictional). The JSON follows evals/gold/receipts/061+ (same keys), so any of these can be copied in as 201-210.
Not wired into the live demo seed; see README.md here for how that would be done.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "evals"))
LABEL = "SAMPLE — FICTIONAL COMPANY"
BRAMBLE = "Bramblewood Joinery Ltd"
BRAMBLE_VRN = "GB 123 4567 89"
CODE = {20: "T1", 5: "T5", 0: "T0", None: "T9"}


def vrn(seed: int) -> str:
    rng = random.Random(seed)
    while True:
        d = [0] + [rng.randint(0, 9) for _ in range(6)]
        s = sum(w * x for w, x in zip(range(8, 1, -1), d, strict=True))
        cd = (-s) % 97
        if cd < 97:
            return f"GB {''.join(map(str, d[:3]))} {''.join(map(str, d[3:]))} {cd:02d}"


def pounds(p: int) -> str:
    s = f"{abs(p) / 100:,.2f}"
    return f"-{s}" if p < 0 else s


DOCS = [
    # (case, doc_type, supplier, address, has_vrn, customer, number, date, pay, category, lines[(desc, qty, unit_pence, rate)], side, status)
    (
        "r_trade",
        "receipt",
        "Hartley & Sons Timber Merchants",
        "3 Mill Lane, Kendal, LA9 4QT",
        True,
        None,
        "T-20817",
        "2026-10-03",
        "card",
        "Materials",
        [("Oak board 2.4m 150x22", 6, 1895, 20), ("Wood glue 1L", 2, 849, 20), ("Screws 4x40 box 200", 3, 575, 20)],
        "purchase",
        "proposed",
    ),
    (
        "r_fuel",
        "receipt",
        "Ashcombe Road Service Station",
        "Ashcombe Road, Taunton, TA1 3RW",
        True,
        None,
        "0042-5518",
        "2026-10-06",
        "card",
        "Motor fuel",
        [("Diesel 52.14 L @ 142.9p", 1, 7451, 20)],
        "purchase",
        "proposed",
    ),
    (
        "r_cafe",
        "receipt",
        "The Copper Kettle Tearoom",
        "11 Church Street, Ludlow, SY8 1AP",
        True,
        None,
        "1187",
        "2026-10-08",
        "card",
        "Subsistence",
        [("Bacon roll", 2, 450, 20), ("Pot of tea", 2, 280, 20)],
        "purchase",
        "proposed",
    ),
    (
        "pi_merchant",
        "purchase_invoice",
        "Pennington Ironmongery Ltd",
        "Unit 7, Wharf Road, Stroud, GL5 3JA",
        True,
        BRAMBLE,
        "PIL-44120",
        "2026-10-09",
        "bank transfer",
        "Materials",
        [
            ("Brass butt hinges 100mm (pair)", 24, 735, 20),
            ("Mortice lock 3-lever", 6, 2450, 20),
            ("Delivery", 1, 1200, 20),
        ],
        "purchase",
        "proposed",
    ),
    (
        "pi_subcontractor",
        "purchase_invoice",
        "Tom Whitaker Decorating",
        "22 Elm Grove, Frome, BA11 2DD",
        False,
        BRAMBLE,
        "TW-031",
        "2026-10-12",
        "bank transfer",
        "Subcontractors",
        [("Paint finish, 4 sash windows (labour)", 1, 48000, 0)],
        "purchase",
        "needs_a_look",
    ),
    (
        "utility",
        "purchase_invoice",
        "Westmoor Energy Supply Ltd",
        "PO Box 410, Exeter, EX1 9ZZ",
        True,
        BRAMBLE,
        "WES-778213",
        "2026-10-14",
        "direct debit",
        "Light and heat",
        [("Business electricity, September 2026", 1, 18640, 20), ("Standing charge 30 days", 1, 1470, 20)],
        "purchase",
        "proposed",
    ),
    (
        "pi_software",
        "purchase_invoice",
        "Larkfield Cloud Services Ltd",
        "4 Station Approach, Woking, GU22 7UE",
        True,
        BRAMBLE,
        "LCS-2026-1009",
        "2026-10-15",
        "card",
        "Software",
        [("Job scheduling app, 3 users, monthly", 1, 4500, 20)],
        "purchase",
        "proposed",
    ),
    (
        "sales",
        "sales_invoice",
        BRAMBLE,
        "Unit 4, Brook Farm Workshops, Market Harborough, LE16 9HZ",
        True,
        "Mrs E. Fairbrother",
        "BJ-1093",
        "2026-10-17",
        "bank transfer",
        "Sales",
        [("Bespoke oak bookcase, made and fitted", 1, 165000, 20), ("Removal of old shelving", 1, 9000, 20)],
        "sale",
        "proposed",
    ),
    (
        "r_parking",
        "receipt",
        "Castlegate Car Park",
        "Castlegate, Lewes, BN7 1XX",
        False,
        None,
        "88123",
        "2026-10-20",
        "cash",
        "Parking",
        [("Parking 3 hrs", 1, 450, None)],
        "purchase",
        "proposed",
    ),
    (
        "credit_note",
        "purchase_invoice",
        "Hartley & Sons Timber Merchants",
        "3 Mill Lane, Kendal, LA9 4QT",
        True,
        BRAMBLE,
        "CN-0912",
        "2026-10-22",
        "bank transfer",
        "Materials",
        [("Returned: oak board 2.4m 150x22", -2, 1895, 20)],
        "purchase",
        "proposed",
    ),
]


def build(i: int, row: tuple) -> dict:
    case, dtype, sup, addr, has_vrn, cust, num, day, pay, cat, lines, side, status = row
    sup_vrn = BRAMBLE_VRN if sup == BRAMBLE else (vrn(1000 + i) if has_vrn else None)
    out_lines = []
    for desc, qty, unit, rate in lines:
        net = qty * unit
        vat = round(net * (rate or 0) / 100)
        out_lines.append(
            {
                "description": desc,
                "qty": qty,
                "unit_price": unit / 100,
                "net": net / 100,
                "vat_rate": rate,
                "vat": vat / 100,
                "vat_code": CODE[rate],
            }
        )
    net_p = sum(round(x["net"] * 100) for x in out_lines)
    vat_p = sum(round(x["vat"] * 100) for x in out_lines)
    rates = {x["vat_rate"] for x in out_lines}
    credit = net_p < 0
    title = "CREDIT NOTE" if credit else ("INVOICE" if dtype != "receipt" else "RECEIPT")
    dd, mm, yy = day[8:], day[5:7], day[:4]
    t = [sup.upper(), *addr.split(", ")]
    if sup_vrn:
        t.append(f"VAT Reg No: {sup_vrn}")
    t += ["", f"{title:^46}".rstrip(), f"No:   {num}", f"Date: {dd}/{mm}/{yy}"]
    if cust:
        t += ["", f"To: {cust}"]
    t += ["", f"{'DESCRIPTION':<26}{'QTY':>4}{'NET':>11}{'VAT%':>5}", "-" * 46]
    for x in out_lines:
        r = "-" if x["vat_rate"] is None else str(x["vat_rate"])
        t.append(f"{x['description'][:26]:<26}{x['qty']:>4}{pounds(round(x['net'] * 100)):>11}{r:>5}")
    t += ["-" * 46, f"{'NET':<30}{pounds(net_p):>16}"]
    for r in sorted(r for r in rates if r):
        v = sum(round(x["vat"] * 100) for x in out_lines if x["vat_rate"] == r)
        t.append(f"{'VAT ' + str(r) + '%':<30}{pounds(v):>16}")
    if rates <= {None}:
        t.append("No VAT charged")
    t += [
        f"{'TOTAL' + (' CREDIT' if credit else ''):<30}{'£' + pounds(net_p + vat_p):>16}",
        f"Paid by: {pay}",
        "",
        f"{LABEL:^46}".rstrip(),
    ]
    code = CODE[next(iter(rates))] if len(rates) == 1 else "MIXED"
    return {
        "doc_type": dtype,
        "supplier": {"name": sup, "vat_number": sup_vrn, "address": addr},
        "customer": {"name": cust},
        "invoice_number": num,
        "date": day,
        "currency": "GBP",
        "lines": out_lines,
        "net_total": net_p / 100,
        "vat_total": vat_p / 100,
        "gross_total": (net_p + vat_p) / 100,
        "net_pence": net_p,
        "vat_pence": vat_p,
        "gross_pence": net_p + vat_p,
        "vat_code": code,
        "side": side,
        "expected_status": status,
        "is_credit_note": credit,
        "payment_method": pay,
        "card_last4": None,
        "category_hint": cat,
        "printed_text": "\n".join(t),
        "notes": "",
        "gold_case": case,
        "label": LABEL,
    }


def main() -> None:
    try:
        from harness.render import render_receipt
    except Exception:  # noqa: BLE001 - rendering is optional
        render_receipt = None
    index = []
    for i, row in enumerate(DOCS, 1):
        doc = build(i, row)
        stem = f"S{i:02d}_{doc['gold_case']}"
        (HERE / f"{stem}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        if render_receipt:
            (HERE / f"{stem}.png").write_bytes(render_receipt(doc["printed_text"], messy=False, seed=i))
        index.append(
            {
                "file": f"{stem}.json",
                "gold_case": doc["gold_case"],
                "supplier": doc["supplier"]["name"],
                "gross_pence": doc["gross_pence"],
                "side": doc["side"],
                "expected_status": doc["expected_status"],
            }
        )
    (HERE / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(index)} documents written to {HERE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
