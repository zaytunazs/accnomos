#!/usr/bin/env python3
"""Generate 140 more synthetic gold documents (receipts 061-200) with Qwen3.8-27B (local vLLM).

    python evals/gold/gen_gold_v2.py [--dry-run]

Qwen invents the fictional businesses, addresses, people and line items (seeded per document). Code does
everything that must be right: VAT registration numbers (mod-97 checksum, fictional), dates, invoice
numbers, arithmetic in integer pence, printed layouts and the gold fields. So the gold is correct by
construction and the manifest is deterministic for a given set of Qwen answers (the committed
receipts/*.json are the artefact; re-running Qwen will give different names).

Writes evals/gold/receipts/NNN_<case>.json and extends evals/gold/manifest.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "receipts"
SEED = 2026
FIRST_NO = 61
W = 46
LABEL = "SAMPLE — FICTIONAL COMPANY"
BRAMBLEWOOD = {
    "name": "Bramblewood Joinery Ltd",
    "vat_number": "GB 123 4567 89",
    "address": "14 Mill Lane, Leeds, LS1 2AB",
}

# Real trading names Qwen must not reuse (case-insensitive substring match on the supplier name).
REAL = [
    "screwfix",
    "toolstation",
    "wickes",
    "b&q",
    "jewson",
    "travis",
    "perkins",
    "selco",
    "howdens",
    "homebase",
    "halfords",
    "tesco",
    "asda",
    "sainsbury",
    "morrisons",
    "aldi",
    "lidl",
    "waitrose",
    "greggs",
    "costa",
    "starbucks",
    "pret",
    "nero",
    "shell",
    "bp",
    "esso",
    "texaco",
    "jet",
    "gulp",
    "murco",
    "ncp",
    "ringgo",
    "justpark",
    "british",
    "gas",
    "octopus",
    "edf",
    "e.on",
    "eon",
    "scottish",
    "power",
    "sse",
    "bulb",
    "ovo",
    "bt",
    "vodafone",
    "o2",
    "three",
    "sky",
    "virgin",
    "talktalk",
    "plusnet",
    "thames",
    "water",
    "severn",
    "trent",
    "united",
    "utilities",
    "yorkshire",
    "water",
    "microsoft",
    "adobe",
    "xero",
    "slack",
    "zoom",
    "google",
    "amazon",
    "dropbox",
    "quickbooks",
    "sage",
    "github",
    "atlassian",
    "notion",
    "canva",
    "apple",
    "stripe",
    "paypal",
    "royal",
    "mail",
    "barclays",
    "starling",
    "tide",
    "lloyds",
]
REAL_PHRASES = (
    "travis perkins",
    "british gas",
    "scottish power",
    "thames water",
    "severn trent",
    "united utilities",
    "yorkshire water",
    "royal mail",
)

TOWNS = [
    "Leeds",
    "Sheffield",
    "Harrogate",
    "York",
    "Wakefield",
    "Bradford",
    "Huddersfield",
    "Halifax",
    "Skipton",
    "Ripon",
    "Doncaster",
    "Barnsley",
    "Hull",
    "Lincoln",
    "Chester",
    "Preston",
    "Lancaster",
    "Carlisle",
    "Durham",
    "Newcastle",
]

# ---------------------------------------------------------------- document plan


def plan() -> list[dict]:
    s: list[dict] = []

    def add(n: int, **kw):
        s.extend(dict(kw) for _ in range(n))

    add(
        10,
        case="r_fuel",
        doc_type="receipt",
        sub="petrol station forecourt operator (a small independent chain or motorway-services style brand)",
        vrn=0.9,
        pay="card",
    )
    add(
        12,
        case="r_trade",
        doc_type="receipt",
        sub="trade counter (timber yard, plumbers' merchant, electrical wholesaler, ironmongers or hardware counter)",
        vrn=1.0,
        pay="card",
        items=(2, 6),
    )
    add(
        10, case="r_cafe", doc_type="receipt", sub="independent café or sandwich bar", vrn=0.7, pay="card", items=(2, 5)
    )
    add(8, case="r_parking", doc_type="receipt", sub="private car park or pay-and-display", vrn=0.6, pay="card")
    add(
        12,
        case="pi_merchant",
        doc_type="purchase_invoice",
        sub="builders' or timber merchant supplying a joinery workshop",
        vrn=1.0,
        pay="bank_transfer",
        items=(3, 7),
    )
    add(
        10,
        case="pi_subcontractor",
        doc_type="purchase_invoice",
        sub="self-employed subcontractor (labour: fitting, French polishing, electrics, plastering, delivery driver)",
        vrn=1.0,
        pay="bank_transfer",
        items=(1, 4),
    )
    add(
        8,
        case="pi_software",
        doc_type="purchase_invoice",
        sub="software subscription (fictional SaaS: CAD, accounts, stock control, CRM, cloud storage)",
        vrn=1.0,
        pay="card",
        items=(1, 3),
    )
    add(
        30,
        case="sales",
        doc_type="sales_invoice",
        sub="joinery work (bespoke furniture, kitchens, staircases, doors, fitted wardrobes, restoration)",
        vrn=1.0,
        pay="bank_transfer",
        items=(1, 5),
    )
    for sub, rate, n in (
        ("business electricity supply (usage, standing charge, climate change levy)", 20, 4),
        ("domestic-rate gas supply at a home office, reduced rate", 5, 2),
        ("broadband and phone line", 20, 3),
        ("business mobile contract (several lines)", 20, 3),
        ("business water and sewerage (zero-rated)", 0, 2),
        ("landline and call charges", 20, 1),
    ):
        add(
            n,
            case="utility",
            doc_type="purchase_invoice",
            sub=sub,
            vrn=1.0,
            pay="direct_debit",
            items=(2, 4),
            rate=rate,
        )
    add(
        6,
        case="credit_note",
        doc_type="purchase_invoice",
        sub="builders' merchant credit note (returned or damaged goods)",
        vrn=1.0,
        pay="bank_transfer",
        items=(1, 3),
        credit=True,
    )
    add(
        2,
        case="credit_note",
        doc_type="purchase_invoice",
        sub="subcontractor or software credit note (overcharge, cancelled service)",
        vrn=1.0,
        pay="bank_transfer",
        items=(1, 2),
        credit=True,
    )
    add(
        2,
        case="credit_note",
        doc_type="sales_invoice",
        sub="joinery work credited to a customer (cancelled item or price adjustment)",
        vrn=1.0,
        pay="bank_transfer",
        items=(1, 3),
        credit=True,
    )
    add(
        3,
        case="edge_multi_rate",
        doc_type="receipt",
        sub="small general store or garden centre selling standard-rated goods, zero-rated food or books, and one reduced-rate (5%) item such as a child car seat",
        vrn=1.0,
        pay="card",
        items=(4, 7),
        rate="mixed",
    )
    add(
        3,
        case="edge_zero",
        doc_type="receipt",
        sub="shop selling only zero-rated goods (books, children's clothes, cold food)",
        vrn=0.0,
        pay="card",
        items=(1, 4),
        rate=0,
    )
    add(
        2,
        case="edge_reverse_charge",
        doc_type="purchase_invoice",
        sub="labour-only construction subcontractor (groundworks, roofing, bricklaying, plastering, scaffolding) invoicing services under the domestic reverse charge, so VAT is not charged",
        vrn=1.0,
        pay="bank_transfer",
        items=(1, 3),
        rate="rc",
    )
    add(
        3,
        case="edge_foreign_gbp",
        doc_type="receipt",
        sub="foreign supplier (Ireland, USA, Germany) of a cloud service, hotel stay or trade-show ticket, charged to a UK card in GBP",
        vrn=0.0,
        pay="card",
        items=(1, 1),
        rate="foreign",
    )
    add(
        2,
        case="edge_handwritten",
        doc_type="receipt",
        sub="market trader or yard selling non-food goods (firewood, timber offcuts, plants, second-hand tools) who writes the items and total by hand",
        vrn=0.5,
        pay="cash",
        items=(2, 4),
        rate="hand",
    )
    add(
        2,
        case="edge_torn_faded",
        doc_type="receipt",
        sub="trade counter",
        vrn=1.0,
        pay="card",
        items=(2, 5),
        rate="damage",
    )
    assert len(s) == 140, len(s)
    return s


# ---------------------------------------------------------------- Qwen


def ask(prompt: str, seed: int) -> dict:
    body = {
        "model": "qwen3.8-27b",
        "temperature": 0.8,
        "max_tokens": 1200,
        "seed": seed,
        "messages": [
            {
                "role": "system",
                "content": "You invent entirely fictional UK businesses and people for accounting test documents. Never use real company names.",
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


def is_real(name: str) -> bool:
    low = name.lower()
    words = set(re.findall(r"[a-z0-9&.]+", low))
    return any(p in low for p in REAL_PHRASES) or any(w in words for w in REAL if " " not in w)


def persona(spec: dict, rng: random.Random, i: int, taken: set[str]) -> dict:
    lo, hi = spec.get("items", (1, 3))
    n = rng.randint(lo, hi)
    foreign = spec.get("rate") == "foreign"
    town = rng.choice(("Dublin", "Cork", "Munich", "Hamburg", "Austin", "Amsterdam") if foreign else TOWNS)
    price_note = "shelf prices INCLUDING VAT" if spec["doc_type"] == "receipt" else "prices EXCLUDING VAT"
    for attempt in range(6):
        prompt = (
            f"Invent a fictional UK supplier: {spec['sub']}, based in or near {town}{' (outside the UK: local-style address)' if foreign else ''}. Its name must be made up and must not "
            f"resemble any real company. Also invent a customer business name (a small UK firm, not a person) and a contact person.\n"
            f"List exactly {n} line item(s) it would sell, with realistic UK {price_note} in pounds for one unit (qty 1-12).\n"
            'Return ONLY JSON: {"supplier_name":str,"street":str,"postcode":str,"phone":str,"customer_name":str,'
            '"contact":str,"category_hint":str,"reason":str,"items":[{"description":str,"qty":int,"unit_price":number'
            + (',"vat_rate":0|5|20' if spec.get("rate") == "mixed" else "")
            + "}]}"
            "\n(reason = a short reason for a credit note, else an empty string.) "
            f"Variation seed {rng.randint(1, 10**6)}."
        )
        try:
            d = ask(prompt, seed=SEED * 1000 + i * 7 + attempt)
            name = str(d["supplier_name"]).strip()
            if not name or is_real(name) or name.lower() in taken or len(d["items"]) < 1:
                continue
            d["items"] = [it for it in d["items"] if float(it["unit_price"]) > 0 and int(it["qty"]) >= 1][:n]
            if d["items"]:
                d["town"] = town
                return d
        except Exception as exc:  # noqa: BLE001 - retry with the next seed
            print("retry", i, type(exc).__name__, exc, file=sys.stderr)
    raise RuntimeError(f"no usable persona for doc {i}")


# ---------------------------------------------------------------- numbers


def vrn(rng: random.Random) -> str:
    """Fictional-looking GB VRN: leading 0 block, valid mod-97 checksum (old 9-digit scheme)."""
    d = [0, rng.randint(0, 9), rng.randint(0, 9)] + [rng.randint(0, 9) for _ in range(4)]
    s = sum(x * w for x, w in zip(d, (8, 7, 6, 5, 4, 3, 2)))
    chk = 97 - (s % 97)
    digits = "".join(map(str, d)) + f"{chk:02d}"
    return f"GB {digits[:3]} {digits[3:7]} {digits[7:]}"


def m(p: int) -> str:
    return f"{p / 100:,.2f}"


def gross_line(desc: str, qty: float, unit_gross: float, rate: int) -> dict:
    g = round(qty * unit_gross * 100)
    net = round(g / (1 + rate / 100))
    return {
        "description": desc,
        "qty": qty,
        "unit_price": round(net / qty / 100, 4),
        "net": net,
        "vat_rate": rate,
        "vat": g - net,
    }


def net_line(desc: str, qty: float, unit_net: float, rate: int) -> dict:
    net = round(qty * unit_net * 100)
    return {
        "description": desc,
        "qty": qty,
        "unit_price": round(unit_net, 2),
        "net": net,
        "vat_rate": rate,
        "vat": round(net * rate / 100),
    }


def vat_code(rate: int | None, kind: str = "") -> str:
    return {20: "T1", 5: "T5", 0: "T0"}.get(rate, "T0")


def date_fmt(d: date, rng: random.Random) -> str:
    return rng.choice((d.strftime("%d/%m/%Y"), d.strftime("%d/%m/%y"), d.strftime("%d %b %Y"), d.strftime("%d-%m-%Y")))


def addr_lines(p: dict, rng: random.Random) -> list[str]:
    return [p["street"], f"{p['town']} {p['postcode']}"]


def center(s: str) -> str:
    return s.center(W).rstrip()


def lr(left: str, right: str, w: int = W) -> str:
    left = left[: max(1, w - len(right) - 1)]
    return left + " " * (w - len(left) - len(right)) + right


# ---------------------------------------------------------------- printed layouts


def vat_summary(lines: list[dict], sign: int = 1) -> list[str]:
    out: dict[int, list[int]] = {}
    for ln in lines:
        a = out.setdefault(ln["vat_rate"], [0, 0])
        a[0] += ln["net"]
        a[1] += ln["vat"]
    return [lr(f"VAT {r:g}%  net {m(sign * a[0])}", m(sign * a[1])) for r, a in sorted(out.items(), reverse=True)]


def text_receipt(d: dict, lines: list[dict], t: dict, rng: random.Random) -> str:
    out = (
        [center(t["supplier"]["name"].upper())]
        + [center(x) for x in addr_lines(d, rng)]
        + [center(f"Tel {d['phone']}")]
    )
    if t["supplier"]["vat_number"]:
        out.append(center(f"VAT No {t['supplier']['vat_number']}"))
    out += ["", lr(date_fmt(t["date_obj"], rng), f"{rng.randint(8, 18):02d}:{rng.randint(0, 59):02d}"), "-" * W]
    for ln in lines:
        q = f"{ln['qty']:g} x " if ln["qty"] != 1 else ""
        out.append(lr(f"{q}{ln['description']}", m(ln["net"] + ln["vat"])))
    out += ["-" * W, lr("TOTAL", "£" + m(t["gross"]))]
    out += vat_summary(lines) if t["vat"] else []
    pay = {"card": f"CARD ****{t['card_last4']} CONTACTLESS", "cash": "CASH"}.get(t["pay"], t["pay"].upper())
    out += [pay, "", center("Thank you for your custom"), center(LABEL)]
    return "\n".join(out)


def text_fuel(d: dict, lines: list[dict], t: dict, rng: random.Random, litres: float, ppl: float) -> str:
    out = [center(t["supplier"]["name"].upper())] + [center(x) for x in addr_lines(d, rng)]
    if t["supplier"]["vat_number"]:
        out.append(center(f"VAT No {t['supplier']['vat_number']}"))
    out += [
        "",
        lr(date_fmt(t["date_obj"], rng), f"{rng.randint(6, 21):02d}:{rng.randint(0, 59):02d}"),
        f"PUMP {rng.randint(1, 12)}",
        "-" * W,
        f"{lines[0]['description']}",
        f"{litres:.2f} L @ {ppl * 100:.1f}p/L",
        lr("FUEL", "£" + m(t["gross"])),
    ]
    out += ["-" * W, lr("TOTAL", "£" + m(t["gross"]))]
    out += vat_summary(lines) if t["vat"] else []
    out += [f"CARD ****{t['card_last4']}", "", center("Drive safely"), center(LABEL)]
    return "\n".join(out)


def text_invoice(
    d: dict,
    lines: list[dict],
    t: dict,
    rng: random.Random,
    title: str = "TAX INVOICE",
    note: list[str] | None = None,
    sign: int = 1,
    ref: str | None = None,
) -> str:
    sup, cust = t["supplier"], t["customer"]
    out = [
        sup["name"].upper(),
        *(["14 Mill Lane", "Leeds LS1 2AB"] if sup["name"] == BRAMBLEWOOD["name"] else addr_lines(d, rng)),
        f"Tel {d['phone']}",
    ]
    if sup["vat_number"]:
        out.append(f"VAT Reg No: {sup['vat_number']}")
    out += ["", f"{title}".center(W).rstrip(), f"No:   {t['invoice_number']}", f"Date: {date_fmt(t['date_obj'], rng)}"]
    if ref:
        out.append(ref)
    elif t.get("due"):
        out.append(f"Due:  {t['due']}")
    out += ["", f"To: {cust['name']}", "", f"{'DESCRIPTION':<18}{'QTY':>4}{'UNIT':>9}{'NET':>10}{'VAT%':>5}", "-" * W]
    for ln in lines:
        out.append(
            f"{ln['description'][:18]:<18}{ln['qty']:>4g}{m(round(ln['unit_price'] * 100)):>9}{m(ln['net']):>10}{ln['vat_rate']:>5g}"
        )
    out += [
        "-" * W,
        lr("NET TOTAL", m(t["net"])),
        *(vat_summary(lines) if t["vat"] else [lr("VAT", m(0))]),
        lr("TOTAL DUE" if sign > 0 else "TOTAL CREDIT", "£" + m(t["gross"])),
    ]
    out += [""] + (note or [])
    out += ["", t["payment_text"], center(LABEL)]
    return "\n".join(out)


# ---------------------------------------------------------------- build one document


def build(i: int, spec: dict, taken: set[str]) -> dict:
    rng = random.Random(f"{SEED}-{i}")
    d = persona(spec, rng, i, taken)
    case, dt = spec["case"], spec["doc_type"]
    when = date(2026, 7, 1) + timedelta(days=rng.randint(0, 116))
    credit = spec.get("credit", False)
    sale = dt == "sales_invoice"
    has_vrn = rng.random() < spec["vrn"]
    supplier = (
        dict(BRAMBLEWOOD)
        if sale
        else {
            "name": d["supplier_name"],
            "vat_number": vrn(rng) if has_vrn else None,
            "address": f"{d['street']}, {d['town']}, {d['postcode']}",
        }
    )
    customer = (
        {"name": d["customer_name"]}
        if dt != "receipt" and not sale
        else ({"name": d["customer_name"]} if sale else {"name": BRAMBLEWOOD["name"]})
    )
    if dt == "purchase_invoice":
        customer = {"name": BRAMBLEWOOD["name"]}
    rate = spec.get("rate")
    items = d["items"]
    lines: list[dict] = []
    extra_notes: list[str] = []
    currency, damage, foreign = "GBP", None, None

    if case == "r_fuel":
        litres = round(rng.uniform(18, 58), 2)
        ppl = round(rng.uniform(1.39, 1.63), 3)
        lines = [gross_line(rng.choice(("UNLEADED", "DIESEL", "SUPER UNLEADED")), litres, ppl, 20)]
    elif case == "r_parking":
        hours = rng.choice((1, 2, 3, 4, 6, 10))
        lines = [
            gross_line(
                f"Parking {hours}h", 1, round(rng.choice((1.5, 2.2, 3.0, 4.5, 5.0, 7.5, 9.0, 12.0)) * hours**0.5, 2), 20
            )
        ]
    elif rate == "mixed":
        rates = [rng.choice((20, 20, 0, 5)) for _ in items]
        for k, r_ in enumerate((20, 0, 5)):
            if k < len(rates):
                rates[k] = r_
        for it, r_ in zip(items, rates):
            lines.append(gross_line(it["description"], it["qty"], float(it["unit_price"]), r_))
    elif rate == 0 or rate == 5 or rate == 20 and case == "utility":
        for it in items:
            lines.append(
                (net_line if dt != "receipt" else gross_line)(
                    it["description"], it["qty"], float(it["unit_price"]), rate
                )
            )
    elif rate == "rc":
        for it in items:
            lines.append(net_line(it["description"], it["qty"], float(it["unit_price"]) * 8, 0))
        would = round(sum(ln["net"] for ln in lines) * 0.2)
        extra_notes = [
            "REVERSE CHARGE: Customer to account to HMRC for",
            "the VAT on these services (VAT Act 1994 s55A).",
            f"VAT at 20% would be £{m(would)} - NOT charged.",
        ]
    elif rate == "foreign":
        it = items[0]
        gbp_amt = round(float(it["unit_price"]) * rng.uniform(0.9, 4.0), 2)
        cur, sym = rng.choice((("EUR", "EUR"), ("USD", "USD")))
        fx = round(rng.uniform(0.80, 0.90) if cur == "EUR" else rng.uniform(0.72, 0.80), 4)
        foreign = f"{cur} {gbp_amt / fx:,.2f} @ {fx} = GBP {gbp_amt:,.2f}"
        lines = [
            {
                "description": it["description"],
                "qty": 1,
                "unit_price": gbp_amt,
                "net": round(gbp_amt * 100),
                "vat_rate": 0,
                "vat": 0,
            }
        ]
    elif rate in ("hand", "damage"):
        for it in items:
            lines.append(gross_line(it["description"], it["qty"], float(it["unit_price"]), 20 if has_vrn else 0))
        damage = "handwritten" if rate == "hand" else rng.choice(("torn", "faded"))
    else:
        mk = net_line if dt != "receipt" else gross_line
        for it in items:
            lines.append(mk(it["description"], it["qty"], float(it["unit_price"]), 20))

    # merchants / subcontractors etc: keep invoice amounts plausible for the doc kind
    sign = -1 if credit else 1
    if sign < 0:
        for ln in lines:
            ln["net"], ln["vat"] = -ln["net"], -ln["vat"]
            ln["unit_price"] = ln["unit_price"]  # unit price stays positive; qty x unit = |net|
    net, vat = sum(ln["net"] for ln in lines), sum(ln["vat"] for ln in lines)
    gross = net + vat
    card = f"{rng.randint(1000, 9999)}" if spec["pay"] == "card" else None
    prefix = "".join(w[0] for w in re.findall(r"[A-Za-z]+", supplier["name"]))[:3].upper() or "INV"
    inv_no = None
    due = None
    if dt != "receipt":
        inv_no = f"BRW-2026-{rng.randint(571, 999):04d}" if sale else f"{prefix}-{rng.randint(10000, 99999)}"
        if credit:
            inv_no = ("CN-" + inv_no) if sale else f"CN{rng.randint(1000, 9999)}"
        due = date_fmt(when + timedelta(days=rng.choice((14, 30))), rng)
    pay_text = {
        "bank_transfer": f"Pay by BACS: Sort 40-{rng.randint(10, 99)}-{rng.randint(10, 99)}  Acc {rng.randint(10**7, 10**8 - 1)}",
        "direct_debit": f"Direct debit will be collected on {date_fmt(when + timedelta(days=10), rng)}",
        "card": "Paid by card - thank you",
        "cash": "Paid cash",
    }[spec["pay"]]
    t = {
        "supplier": supplier,
        "customer": customer,
        "date_obj": when,
        "gross": gross,
        "vat": vat,
        "net": net,
        "pay": spec["pay"],
        "card_last4": card,
        "invoice_number": inv_no,
        "due": due,
        "payment_text": pay_text,
    }

    if case == "r_fuel":
        text = text_fuel(d, lines, t, rng, lines[0]["qty"], float(lines[0]["unit_price"]) * 1.2)
    elif credit:
        ref = (
            f"Re invoice {prefix}-{rng.randint(10000, 99999)}"
            if not sale
            else f"Re invoice BRW-2026-{rng.randint(500, 570):04d}"
        )
        t["payment_text"] = "Credit to be refunded / offset on account"
        text = text_invoice(
            d,
            lines,
            t,
            rng,
            title="CREDIT NOTE",
            note=[f"Reason: {d.get('reason') or 'goods returned'}"],
            sign=-1,
            ref=ref,
        )
    elif dt == "receipt" and damage == "handwritten":
        base = text_receipt(d, lines, t, rng).splitlines()
        head = base[: base.index("-" * W) + 1]
        text = "\n".join(
            head
            + [f"~{ln['qty']:g} x {ln['description']}  {m(ln['net'] + ln['vat'])}" for ln in lines]
            + ["-" * W, f"~TOTAL  £{m(gross)}", "~" + ("VAT incl." if vat else "no VAT"), center(LABEL)]
        )
    elif dt == "receipt" and foreign:
        base = text_receipt(d, lines, t, rng).splitlines()
        k = next(j for j, x in enumerate(base) if x.startswith("TOTAL"))
        text = "\n".join(base[:k] + [foreign, "Amount charged to card (GBP)"] + base[k:])
    elif dt == "receipt":
        text = text_receipt(d, lines, t, rng)
        if damage in ("torn", "faded"):
            text += "\n\n"
    else:
        text = text_invoice(d, lines, t, rng, note=extra_notes)

    side = "sale" if sale else "purchase"
    status = "needs_a_look" if (currency != "GBP" or (vat != 0 and not supplier["vat_number"])) else "proposed"
    code = (
        "RC"
        if rate == "rc"
        else (
            "T9"
            if rate == "foreign"
            else (vat_code(lines[0]["vat_rate"]) if len({ln["vat_rate"] for ln in lines}) == 1 else "MIXED")
        )
    )
    payment_method = {"bank_transfer": "bank transfer", "direct_debit": "direct debit"}.get(spec["pay"], spec["pay"])
    to_money = lambda p: round(p / 100, 2)  # noqa: E731
    gold = {
        "doc_type": dt,
        "supplier": supplier,
        "customer": customer if dt != "receipt" else {"name": None},
        "invoice_number": inv_no,
        "date": when.isoformat(),
        "currency": currency,
        "lines": [
            {**ln, "net": to_money(ln["net"]), "vat": to_money(ln["vat"]), "vat_code": vat_code(ln["vat_rate"])}
            for ln in lines
        ],
        "net_total": to_money(net),
        "vat_total": to_money(vat),
        "gross_total": to_money(gross),
        "net_pence": net,
        "vat_pence": vat,
        "gross_pence": gross,
        "vat_code": code,
        "side": side,
        "expected_status": status,
        "is_credit_note": credit,
        "payment_method": payment_method,
        "card_last4": card,
        "category_hint": d["category_hint"],
        "printed_text": text,
        "notes": "; ".join(extra_notes + ([foreign] if foreign else [])),
        "gold_case": case,
        "label": LABEL,
    }
    if damage:
        gold["damage"] = damage
    return gold


def check(g: dict) -> None:
    assert g["net_pence"] + g["vat_pence"] == g["gross_pence"]
    assert sum(round(ln["net"] * 100) for ln in g["lines"]) == g["net_pence"], g["gold_case"]
    assert sum(round(ln["vat"] * 100) for ln in g["lines"]) == g["vat_pence"]
    assert LABEL in g["printed_text"]
    if g["is_credit_note"]:
        assert g["gross_pence"] < 0
    elif g["gross_pence"] <= 0:
        raise AssertionError("non-positive gross")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="plan only, no Qwen calls")
    args = ap.parse_args()
    specs = plan()
    random.Random(SEED).shuffle(specs)
    if args.dry_run:
        print(len(specs), "specs")
        return
    taken: set[str] = set()
    with ThreadPoolExecutor(8) as ex:
        futs = [ex.submit(build, i, s, taken) for i, s in enumerate(specs)]
        golds = [f.result() for f in futs]
    # de-duplicate supplier names across the run (sales invoices are all Bramblewood by design)
    seen: dict[str, int] = {}
    for g in golds:
        if g["doc_type"] != "sales_invoice":
            seen[g["supplier"]["name"].lower()] = seen.get(g["supplier"]["name"].lower(), 0) + 1
    dups = {n for n, c in seen.items() if c > 1}
    if dups:
        print("duplicate supplier names (kept, noted):", sorted(dups))
    manifest_path = HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["items"] = [it for it in manifest["items"] if int(it["file"][:3]) < FIRST_NO]
    for k, g in enumerate(golds):
        check(g)
        name = f"{FIRST_NO + k:03d}_{g['gold_case']}.json"
        (OUT / name).write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
        item = {k_: v for k_, v in g.items() if k_ != "printed_text"}
        manifest["items"].append(
            {
                "file": name,
                "case": g["gold_case"],
                "gross": g["gross_total"],
                "sha256": hashlib.sha256(g["printed_text"].encode()).hexdigest(),
                **item,
            }
        )
    manifest["count"] = len(manifest["items"])
    manifest["generated_by"] = "qwen3.8-27b on DGX Spark (files 001-060: gen_gold.py; 061-200: gen_gold_v2.py)"
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", len(golds), "documents; manifest count", manifest["count"])


if __name__ == "__main__":
    main()
