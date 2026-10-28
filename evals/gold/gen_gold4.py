#!/usr/bin/env python3
"""Price-history gold set with Qwen3.8-27B (local vLLM on the Spark, :8000): joinery consumables that recur across
five fictional suppliers at different prices over six months, for price-history and "cheaper elsewhere" features.

    python evals/gold/gen_gold4.py [N]            # N receipts (default 120), PNGs rendered at the end
    python evals/gold/gen_gold4.py --dry-run      # stub catalogue, builds and checks the plan, writes nothing
    python evals/gold/gen_gold4.py --stub --out /tmp/g4 --no-render     # offline run (the tests use this)

What Qwen does: names the five suppliers, names each product (a made-up brand name plus a short trade-counter
wording), and writes how each supplier prints each product (wording and SKU). Each reply is checked (no real
trading name or brand, the size words present, lengths, uniqueness) and re-asked, never repaired.

What code does, so the expected answers are right by construction: which suppliers stock which products (3 or 4 of
the 5), pack sizes, every price (a base price per unit x a supplier factor x a bulk discount x a month-by-month
drift with the odd price rise, in whole pence per pack), VAT (20 %, whole pence; one till-style supplier prints
VAT-inclusive prices, one cash supplier charges no VAT and shows no VAT number), dates, quantities, invoice numbers,
VAT numbers (fictional, mod-97), the printed layout, totals, and then the expectations from the finished documents:
for every product and supplier the normalised ex-VAT unit price at each purchase (pence per roll / screw / sheet /
litre / metre ...), the latest and the mean, which supplier is cheapest, and for each line what was cheaper elsewhere
on the day. The plan is re-drawn (next seed) until every product/supplier pair has at least 3 purchases over at least
2 months and no "cheapest" is a near tie.

Writes evals/gold/ledger4/{catalogue.json, receipts/NNN_price_history.json, expectations.json, manifest.json,
README.md}. Resumable: catalogue.json is saved after each Qwen step and reused; receipts already on disk are skipped
(`--fresh` starts over). PNGs go to evals/runs/gold4_png/ (not committed), skipped when present.
Every document and file carries the label SAMPLE — FICTIONAL COMPANY (em dash, U+2014).
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EVALS = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from spark_gen import (  # noqa: E402
    BIZ,
    LABEL,
    Qwen,
    QwenError,
    StubQwen,
    ask_validated,
    centre,
    is_real,
    lr,
    m,
    read_json,
    vat_pence,
    vrn,
    write_json,
    write_text,
)

OUT = HERE / "ledger4"
PNG_DIR = EVALS / "runs" / "gold4_png"
START, END = date(2026, 4, 1), date(2026, 9, 30)
MONTHS = 6
SEED = 4
W = 46
FACTORS = [0.88, 0.96, 1.04, 1.13, 1.22]  # per-supplier price levels for one product, shuffled per product
TIE = 0.015  # "cheapest" must beat the runner-up by more than 1.5 %

# Supplier kinds, in order. style: invoice (VAT-registered, net prices), till (VAT-registered, prices include VAT),
# cash (not VAT-registered, no VAT charged).
SUPPLIER_KINDS = [
    ("builders' merchant with a trade counter", "invoice"),
    ("ironmongery and fixings wholesaler", "invoice"),
    ("timber and sheet materials yard", "invoice"),
    ("DIY-style trade shop with a till", "till"),
    ("small cash-and-carry that is not VAT-registered", "cash"),
]

# key, category, plain description for Qwen, words every name must contain, unit, plural, pack style, base pence per
# unit, pack sizes (in units), bulk discount per doubling of pack size, quantity range (packs per line)
ARCHETYPES: list[dict[str, Any]] = [
    dict(key="tape_masking_38", cat="tapes", plain="masking tape, 38 mm wide, 50 m roll", must=["masking", "38mm"],
         unit="roll", plural="rolls", style="count", base=210, packs=[1, 6, 12], bulk=0.04, qty=(2, 12)),
    dict(key="tape_double_25", cat="tapes", plain="double-sided carpet tape, 25 mm wide, roll", must=["double", "25mm"],
         unit="roll", plural="rolls", style="count", base=265, packs=[1, 6], bulk=0.04, qty=(1, 8)),
    dict(key="tape_gaffer_50", cat="tapes", plain="cloth gaffer tape, 50 mm wide, 25 m roll", must=["gaffer", "50mm"],
         unit="roll", plural="rolls", style="count", base=480, packs=[1, 4, 12], bulk=0.04, qty=(1, 8)),
    dict(key="screw_wood_40", cat="screws", plain="countersunk wood screws, 4.0 x 40 mm, zinc", must=["screw", "40mm"],
         unit="screw", plural="screws", style="count", base=3.6, packs=[100, 200, 500, 1000], bulk=0.05, qty=(1, 6)),
    dict(key="screw_wood_80", cat="screws", plain="countersunk wood screws, 5.0 x 80 mm, zinc", must=["screw", "80mm"],
         unit="screw", plural="screws", style="count", base=7.9, packs=[100, 200, 500], bulk=0.05, qty=(1, 5)),
    dict(key="screw_pocket_32", cat="screws", plain="pocket-hole screws, 32 mm, coarse thread", must=["pocket", "32mm"],
         unit="screw", plural="screws", style="count", base=5.2, packs=[100, 250, 500], bulk=0.05, qty=(1, 5)),
    dict(key="sand_sheet_120", cat="sandpaper", plain="sanding sheets, 120 grit, 230 x 280 mm", must=["120", "sheet"],
         unit="sheet", plural="sheets", style="count", base=38, packs=[10, 25, 50], bulk=0.05, qty=(1, 6)),
    dict(key="sand_disc_80", cat="sandpaper", plain="sanding discs, 125 mm, 80 grit", must=["125mm", "80"],
         unit="disc", plural="discs", style="count", base=62, packs=[10, 25, 50], bulk=0.05, qty=(1, 5)),
    dict(key="sand_sponge_fine", cat="sandpaper", plain="fine sanding sponge block", must=["sponge", "fine"],
         unit="sponge", plural="sponges", style="count", base=160, packs=[1, 4, 10], bulk=0.04, qty=(1, 6)),
    dict(key="glue_pva_d3", cat="glue", plain="PVA wood glue, D3 water-resistant, by the litre", must=["pva", "d3"],
         unit="litre", plural="litres", style="volume", base=620, packs=[1, 5], bulk=0.03, qty=(1, 6)),
    dict(key="glue_pu_310", cat="glue", plain="polyurethane construction adhesive, 310 ml cartridge",
         must=["adhesive", "310ml"], unit="cartridge", plural="cartridges", style="count", base=540,
         packs=[1, 6, 12], bulk=0.04, qty=(1, 8)),
    dict(key="filler_wood_250", cat="glue", plain="ready-mixed wood filler, 250 g tub", must=["filler", "250g"],
         unit="tub", plural="tubs", style="count", base=430, packs=[1, 3, 6], bulk=0.04, qty=(1, 6)),
    dict(key="timber_pse_44x94", cat="timber", plain="planed square-edge softwood, 44 x 94 mm", must=["44x94", "pse"],
         unit="metre", plural="metres", style="length", base=310, packs=[2.4, 3.0, 3.6], bulk=0.0, qty=(4, 24)),
    dict(key="ply_birch_18", cat="timber", plain="birch plywood sheet, 18 mm, 2440 x 1220 mm", must=["birch", "18mm"],
         unit="sheet", plural="sheets", style="count", base=5200, packs=[1], bulk=0.0, qty=(1, 8)),
    dict(key="mdf_18", cat="timber", plain="MDF sheet, 18 mm, 2440 x 1220 mm", must=["mdf", "18mm"],
         unit="sheet", plural="sheets", style="count", base=2800, packs=[1], bulk=0.0, qty=(1, 10)),
    dict(key="ppe_gloves_nitrile", cat="ppe", plain="nitrile-coated work gloves, size 9", must=["glove", "nitrile"],
         unit="pair", plural="pairs", style="count", base=42, packs=[12, 50, 100], bulk=0.05, qty=(1, 4)),
    dict(key="ppe_mask_ffp2", cat="ppe", plain="FFP2 disposable dust masks", must=["ffp2", "mask"],
         unit="mask", plural="masks", style="count", base=135, packs=[3, 10, 20], bulk=0.05, qty=(1, 5)),
    dict(key="ppe_glasses_clear", cat="ppe", plain="clear safety glasses", must=["safety", "glasses"],
         unit="pair", plural="pairs", style="count", base=290, packs=[1, 10], bulk=0.05, qty=(1, 4)),
]  # fmt: skip
CATEGORIES = ["tapes", "screws", "sandpaper", "glue", "timber", "ppe"]
BY_KEY = {a["key"]: a for a in ARCHETYPES}


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def has_all(name: str, must: list[str]) -> bool:
    n = norm(name)
    return all(t in n for t in must)


# ------------------------------------------------------------------------------------------------ Qwen stages

SUPPLIER_PROMPT = """Invent 5 fictional UK suppliers of consumables to joiners and carpenters, one of each kind: %s.
Each name must be made up (2-4 words), must not resemble any real company, and each must be in a different town in
the north of England or the Midlands. Return ONLY JSON:
{"suppliers":[{"name":str,"street":str,"town":str,"postcode":str (UK format),"phone":str (UK format)}]}
with exactly 5 entries, in the order of the kinds above."""

PRODUCT_PROMPT = """Invent fictional trade-brand product names for these joinery consumables (category: %s). For each
give "name": a made-up brand plus the product (at most 36 characters) and "alt_name": a shorter trade-counter wording
(at most 30 characters). Both must contain the listed words or figures. Never use a real brand.
Products (key: description; words that must appear):
%s
Return ONLY JSON: {"products":[{"key":str,"name":str,"alt_name":str}]} with one entry per key above."""

LISTING_PROMPT = """You are the product catalogue clerk at '%s', a %s. Write how this supplier prints each product on
invoices: "print_name" (at most 40 characters, in this supplier's house style: capitals, abbreviations or full words
as you like, but keep the size or grade figures and the brand), and "sku" (4-14 characters, letters, digits, dashes).
Products (key: name; words or figures that must stay in print_name):
%s
Return ONLY JSON: {"listings":[{"key":str,"print_name":str,"sku":str}]} with one entry per key."""


def check_suppliers(reply: dict[str, Any]) -> str | None:
    sup = reply.get("suppliers")
    if not isinstance(sup, list) or len(sup) != 5:
        return "need exactly 5 suppliers"
    seen: set[str] = set()
    for s in sup:
        if not isinstance(s, dict) or any(
            not isinstance(s.get(k), str) or not s[k].strip() for k in ("name", "street", "town", "postcode", "phone")
        ):
            return "a supplier lacks name/street/town/postcode/phone"
        name = s["name"].strip()
        if len(name) > 38 or is_real(name) or name.lower() in seen:
            return f"bad or repeated name {name!r}"
        seen.add(name.lower())
        if not re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}", s["postcode"].strip().upper()):
            return f"postcode {s['postcode']!r} is not UK format"
    return None


def check_products(keys: list[str]):
    def check(reply: dict[str, Any]) -> str | None:
        got = reply.get("products")
        if not isinstance(got, list) or sorted(p.get("key", "") for p in got if isinstance(p, dict)) != sorted(keys):
            return "keys do not match"
        for p in got:
            for field, limit in (("name", 36), ("alt_name", 30)):
                v = p.get(field)
                if not isinstance(v, str) or not v.strip() or len(v) > limit:
                    return f"{p['key']}.{field} missing or over {limit} characters"
                if is_real(v) or not has_all(v, BY_KEY[p["key"]]["must"]):
                    return f"{p['key']}.{field} {v!r} is a real name or lacks {BY_KEY[p['key']]['must']}"
        return None

    return check


def check_listings(keys: list[str], names: dict[str, str]):
    def check(reply: dict[str, Any]) -> str | None:
        got = reply.get("listings")
        if not isinstance(got, list) or sorted(p.get("key", "") for p in got if isinstance(p, dict)) != sorted(keys):
            return "keys do not match"
        seen: set[str] = set()
        for p in got:
            pn, sku = p.get("print_name"), p.get("sku")
            if not isinstance(pn, str) or not pn.strip() or len(pn) > 40 or pn.lower() in seen:
                return f"{p['key']}.print_name missing, over 40 characters or repeated"
            seen.add(pn.lower())
            if not has_all(pn, BY_KEY[p["key"]]["must"]) or is_real(pn):
                return f"{p['key']}.print_name {pn!r} lacks {BY_KEY[p['key']]['must']} or is a real name"
            if not isinstance(sku, str) or not re.fullmatch(r"[A-Za-z0-9-]{4,14}", sku):
                return f"{p['key']}.sku {sku!r} is not 4-14 letters, digits or dashes"
        return None

    return check


def build_catalogue(client: Any, path: Path, seed: int, fresh: bool) -> dict[str, Any]:
    """Qwen's names and wording, saved after each step so a stopped run resumes where it stopped."""
    cat: dict[str, Any] = {"label": LABEL, "seed": seed}
    if path.exists() and not fresh:
        cat = read_json(path)
    kinds = "; ".join(f"{i + 1}. {k}" for i, (k, _) in enumerate(SUPPLIER_KINDS))
    if "suppliers" not in cat:
        r = ask_validated(client, SUPPLIER_PROMPT % kinds, check_suppliers, kind="suppliers", seed=seed)
        cat["suppliers"] = [{k: v.strip() for k, v in s.items()} for s in r["suppliers"]]
        write_json(path, cat)
        print("catalogue: suppliers", [s["name"] for s in cat["suppliers"]], flush=True)
    cat.setdefault("products", {})
    for c in CATEGORIES:
        arch = [a for a in ARCHETYPES if a["cat"] == c]
        if all(a["key"] in cat["products"] for a in arch):
            continue
        listing = "\n".join(f"- {a['key']}: {a['plain']}; words: {', '.join(a['must'])}" for a in arch)
        r = ask_validated(
            client,
            PRODUCT_PROMPT % (c, listing),
            check_products([a["key"] for a in arch]),
            kind="products",
            hint={"category": c, "keys": [a["key"] for a in arch]},
            seed=seed + 11,
        )
        for p in r["products"]:
            cat["products"][p["key"]] = {"name": p["name"].strip(), "alt_name": p["alt_name"].strip()}
        write_json(path, cat)
        print("catalogue: products", c, flush=True)
    cat.setdefault("listings", {})
    keys = [a["key"] for a in ARCHETYPES]
    for i, s in enumerate(cat["suppliers"]):
        if str(i) in cat["listings"]:
            continue
        names = {k: cat["products"][k]["name"] for k in keys}
        listing = "\n".join(f"- {k}: {names[k]}; words: {', '.join(BY_KEY[k]['must'])}" for k in keys)
        r = ask_validated(
            client,
            LISTING_PROMPT % (s["name"], SUPPLIER_KINDS[i][0], listing),
            check_listings(keys, names),
            kind="listings",
            hint={"supplier": i, "keys": keys},
            seed=seed + 100 + i,
        )
        cat["listings"][str(i)] = {
            p["key"]: {"print_name": p["print_name"].strip(), "sku": p["sku"]} for p in r["listings"]
        }
        write_json(path, cat)
        print("catalogue: listings for", s["name"], flush=True)
    return cat


# ------------------------------------------------------------------------------------------------ code: prices


def add_code_parts(cat: dict[str, Any], seed: int) -> None:
    """Suppliers' VAT numbers and styles, who stocks what, pack sizes and the month-by-month price table."""
    rng = random.Random(f"{seed}-cat")
    for i, s in enumerate(cat["suppliers"]):
        style = SUPPLIER_KINDS[i][1]
        s["style"] = style
        s["vat_number"] = None if style == "cash" else vrn(rng)
        s["prefix"] = "".join(w[0] for w in re.findall(r"[A-Za-z]+", s["name"]))[:3].upper().ljust(3, "X")
    stock: dict[str, dict[str, list[float]]] = {}
    prices: dict[str, dict[str, dict[str, list[int]]]] = {}
    for a in ARCHETYPES:
        r = random.Random(f"{seed}-{a['key']}")
        n_sup = r.choice([3, 4, 4])
        sups = sorted(r.sample(range(5), n_sup))
        factors = FACTORS[:]
        r.shuffle(factors)
        stock[a["key"]], prices[a["key"]] = {}, {}
        for si, f in zip(sups, factors, strict=False):
            packs = sorted(r.sample(a["packs"], min(len(a["packs"]), r.choice([1, 2]))))
            stock[a["key"]][str(si)] = packs
            drift, level = [], 1.0
            rise_at = r.randint(1, MONTHS - 1) if r.random() < 0.35 else -1
            for mo in range(MONTHS):
                if mo:
                    level *= 1 + r.choice([-0.03, -0.015, 0.0, 0.0, 0.01, 0.02, 0.035])
                    if mo == rise_at:
                        level *= 1 + r.uniform(0.07, 0.12)
                drift.append(level)
            prices[a["key"]][str(si)] = {}
            small = min(a["packs"])
            for p in packs:
                disc = 1 - a["bulk"] * math.log2(p / small)
                prices[a["key"]][str(si)][f"{p:g}"] = [
                    max(1, round(a["base"] * f * disc * d * p)) for d in drift
                ]  # whole pence per pack
    cat["stock"], cat["prices"] = stock, prices


# ------------------------------------------------------------------------------------------------ plan


def pack_text(a: dict[str, Any], units: float) -> str:
    if a["style"] == "length":
        return f"{units:g} m length"
    if a["style"] == "volume":
        return f"{units:g} {a['unit'] if units == 1 else a['plural']}"
    return f"single {a['unit']}" if units == 1 else f"pack of {units:g} {a['plural']}"


def month_index(d: date) -> int:
    return (d.year - START.year) * 12 + d.month - START.month


def build_plan(cat: dict[str, Any], n: int, seed: int) -> list[dict[str, Any]]:
    """Receipts in date order: which supplier, when, and which (product, pack, quantity) lines."""
    rng = random.Random(f"{seed}-plan")
    stocked: dict[int, list[str]] = {i: [] for i in range(5)}
    for key, sups in cat["stock"].items():
        for si in sups:
            stocked[int(si)].append(key)
    total = sum(len(v) for v in stocked.values())
    counts = {i: max(4, round(n * len(v) / total)) for i, v in stocked.items()}
    while sum(counts.values()) > n:
        counts[max(counts, key=lambda i: counts[i])] -= 1
    while sum(counts.values()) < n:
        counts[min(counts, key=lambda i: counts[i])] += 1
    span = (END - START).days
    stops: list[tuple[date, int]] = []
    for si, c in counts.items():
        used: set[date] = set()
        for j in range(c):
            base = START + timedelta(days=round((j + 0.5) * span / c + rng.uniform(-0.4, 0.4) * span / c))
            d = min(max(base, START), END)
            while d in used:
                d += timedelta(days=1)
                if d > END:
                    d = START
            used.add(d)
            stops.append((d, si))
    stops.sort()
    seen: dict[tuple[str, int], int] = {}
    plan = []
    for d, si in stops:
        keys = stocked[si]
        k = min(len(keys), rng.randint(2, 6))
        weights = [(1 + max(0, 4 - seen.get((key, si), 0))) ** 3 for key in keys]
        chosen: list[str] = []
        pool = list(zip(keys, weights, strict=True))
        while len(chosen) < k:
            pick = rng.choices(pool, weights=[w for _, w in pool])[0]
            chosen.append(pick[0])
            pool.remove(pick)
        lines = []
        for key in sorted(chosen):
            a = BY_KEY[key]
            pack = rng.choice(cat["stock"][key][str(si)])
            lines.append({"key": key, "pack": pack, "qty": rng.randint(*a["qty"])})
            seen[(key, si)] = seen.get((key, si), 0) + 1
        plan.append({"date": d.isoformat(), "supplier": si, "lines": lines})
    return plan


# ------------------------------------------------------------------------------------------------ documents


def line_figures(style: str, pack_net: int, qty: int) -> dict[str, int]:
    """Whole-pence figures of a line for this supplier style."""
    if style == "invoice":
        net = qty * pack_net
        return {"net": net, "vat": vat_pence(net), "pack_shown": pack_net}
    if style == "till":
        pack_gross = (pack_net * 12 + 5) // 10  # the shelf price includes VAT (x 1.2, half up)
        gross = qty * pack_gross
        net = (gross * 100 + 60) // 120
        return {"net": net, "vat": gross - net, "pack_shown": pack_gross}
    net = qty * pack_net
    return {"net": net, "vat": 0, "pack_shown": pack_net}


def description(cat: dict[str, Any], si: int, key: str, pack: float) -> str:
    return f"{cat['listings'][str(si)][key]['print_name']} - {pack_text(BY_KEY[key], pack)}"


def make_receipt(cat: dict[str, Any], spec: dict[str, Any], number: int, rng: random.Random) -> dict[str, Any]:
    si, when = spec["supplier"], date.fromisoformat(spec["date"])
    sup = cat["suppliers"][si]
    style = sup["style"]
    mo = month_index(when)
    lines = []
    for ln in spec["lines"]:
        a = BY_KEY[ln["key"]]
        pack_net = cat["prices"][ln["key"]][str(si)][f"{ln['pack']:g}"][mo]
        f = line_figures(style, pack_net, ln["qty"])
        listing = cat["listings"][str(si)][ln["key"]]
        rate = 0 if style == "cash" else 20
        lines.append(
            {
                "description": description(cat, si, ln["key"], ln["pack"]),
                "qty": ln["qty"],
                "unit_price": round(f["net"] / ln["qty"] / 100, 4),
                "net": f["net"] / 100,
                "vat_rate": rate,
                "vat": f["vat"] / 100,
                "vat_code": "T9" if style == "cash" else "T1",
                "item_key": ln["key"],
                "sku": listing["sku"],
                "pack_units": ln["pack"],
                "pack_text": pack_text(a, ln["pack"]),
                "unit_label": a["unit"],
                "net_pence": f["net"],
                "vat_pence": f["vat"],
                "unit_net_pence": round(f["net"] / ln["qty"] / ln["pack"], 4),  # ex VAT, per normalised unit
                "_shown": f["pack_shown"],
            }
        )
    net = sum(x["net_pence"] for x in lines)
    vat = sum(x["vat_pence"] for x in lines)
    gross = net + vat
    inv_no = f"{sup['prefix']}-{rng.randint(10000, 99999)}"
    status = "proposed"
    if (vat and not sup["vat_number"]) or (gross > 25000 and not vat and not sup["vat_number"]):
        status = "needs_a_look"
    pay = {"invoice": "bank transfer", "till": "card", "cash": "cash"}[style]
    last4 = f"{rng.randint(0, 9999):04d}" if style == "till" else None
    printed = printed_text(sup, style, when, inv_no, lines, net, vat, gross, last4, rng)
    for x in lines:
        x.pop("_shown")
    return {
        "doc_type": "receipt" if style != "invoice" else "purchase_invoice",
        "supplier": {
            "name": sup["name"],
            "vat_number": sup["vat_number"],
            "address": f"{sup['street']}, {sup['town']}, {sup['postcode']}",
        },
        "customer": {"name": BIZ},
        "invoice_number": inv_no,
        "date": spec["date"],
        "currency": "GBP",
        "lines": lines,
        "net_total": net / 100,
        "vat_total": vat / 100,
        "gross_total": gross / 100,
        "net_pence": net,
        "vat_pence": vat,
        "gross_pence": gross,
        "vat_code": "T9" if style == "cash" else "T1",
        "side": "purchase",
        "expected_status": status,
        "is_credit_note": False,
        "payment_method": pay,
        "card_last4": last4,
        "category_hint": "Joinery consumables",
        "printed_text": printed,
        "notes": "",
        "gold_case": "price_history",
        "supplier_index": si,
        "label": LABEL,
    }


def printed_text(sup, style, when, inv_no, lines, net, vat, gross, last4, rng) -> str:
    out = [centre(sup["name"].upper()), centre(sup["street"]), centre(f"{sup['town']} {sup['postcode']}")]
    out.append(centre(f"Tel {sup['phone']}"))
    if sup["vat_number"]:
        out.append(centre(f"VAT Reg No: {sup['vat_number']}"))
    out.append("")
    stamp = when.strftime(rng.choice(["%d/%m/%Y", "%d %b %Y", "%d-%m-%Y"]))
    if style == "invoice":
        out += [centre("TAX INVOICE"), f"No:   {inv_no}", f"Date: {stamp}", f"To:   {BIZ}", ""]
        out += [f"{'ITEM':<24}{'QTY':>3}{'UNIT':>8}{'NET':>11}", "-" * W]
        for x in lines:
            out += [
                x["description"].rsplit(" - ", 1)[0][:W],
                pad(x["pack_text"], x["qty"], x["_shown"], x["net_pence"]),
            ]
        out += ["-" * W, lr("NET TOTAL", m(net)), lr("VAT 20%", m(vat)), lr("TOTAL DUE", "£" + m(net + vat))]
        out += ["", "Payment by bank transfer, 30 days"]
    elif style == "till":
        out += [lr(stamp, f"{rng.randint(8, 17):02d}:{rng.randint(0, 59):02d}"), f"Receipt {inv_no}", "-" * W]
        for x in lines:
            gross_line = x["net_pence"] + x["vat_pence"]
            out += [x["description"].rsplit(" - ", 1)[0][:W], pad(x["pack_text"], x["qty"], x["_shown"], gross_line)]
        out += ["-" * W, lr("TOTAL", "£" + m(net + vat)), lr(f"VAT 20%  net {m(net)}", m(vat))]
        out += [f"CARD ****{last4} CONTACTLESS", "", centre("Thank you for your custom")]
    else:
        out += [centre("CASH SALE"), lr(stamp, f"No {inv_no}"), "-" * W]
        for x in lines:
            out += [
                x["description"].rsplit(" - ", 1)[0][:W],
                pad(x["pack_text"], x["qty"], x["_shown"], x["net_pence"]),
            ]
        out += ["-" * W, lr("TOTAL", "£" + m(net)), "CASH", "", centre("Not VAT registered - no VAT charged")]
    out += ["", centre(LABEL)]
    return "\n".join(out)


def pad(pack_text_: str, qty: int, unit_pence: int, line_pence: int) -> str:
    return f"  {pack_text_:<22}{qty:>3}{m(unit_pence):>8}{m(line_pence):>11}"


# ------------------------------------------------------------------------------------------------ expectations


def build_expectations(cat: dict[str, Any], receipts: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """From the finished documents: per product and supplier the price history, plus the 'cheaper elsewhere' hints."""
    sup_name = [s["name"] for s in cat["suppliers"]]
    obs: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for fname, g in receipts:
        for n, ln in enumerate(g["lines"]):
            obs.setdefault(ln["item_key"], {}).setdefault(g["supplier"]["name"], []).append(
                {
                    "file": fname,
                    "line": n,
                    "date": g["date"],
                    "pack_units": ln["pack_units"],
                    "qty": ln["qty"],
                    "net_pence": ln["net_pence"],
                    "unit_net_pence": ln["unit_net_pence"],
                }
            )
    items: dict[str, Any] = {}
    for key in (a["key"] for a in ARCHETYPES):
        a = BY_KEY[key]
        per: dict[str, Any] = {}
        for sname, rows in obs.get(key, {}).items():
            rows.sort(key=lambda r: (r["date"], r["file"]))
            us = [r["unit_net_pence"] for r in rows]
            per[sname] = {
                "observations": rows,
                "n": len(rows),
                "latest_unit_net_pence": us[-1],
                "mean_unit_net_pence": round(sum(us) / len(us), 4),
                "min_unit_net_pence": min(us),
                "max_unit_net_pence": max(us),
            }
        latest = sorted((v["latest_unit_net_pence"], s) for s, v in per.items())
        means = sorted((v["mean_unit_net_pence"], s) for s, v in per.items())
        items[key] = {
            "name": cat["products"][key]["name"],
            "category": a["cat"],
            "unit": a["unit"],
            "suppliers": per,
            "cheapest_latest": latest[0][1],
            "cheapest_mean": means[0][1],
            "latest_runner_up_gap_pct": round(100 * (latest[1][0] / latest[0][0] - 1), 2) if len(latest) > 1 else None,
            "mean_runner_up_gap_pct": round(100 * (means[1][0] / means[0][0] - 1), 2) if len(means) > 1 else None,
        }
    # For every line: on that day, which other suppliers had a lower last-seen price (what a "cheaper elsewhere"
    # hint could know), and the cheapest of them.
    events = sorted(
        (
            (r["date"], r["file"], r["line"], key, s, r["unit_net_pence"])
            for key, v in obs.items()
            for s, rows in v.items()
            for r in rows
        )
    )
    last: dict[tuple[str, str], float] = {}
    hints = []
    for _d, fname, n, key, s, u in events:
        others = {o: last[(key, o)] for o in sup_name if o != s and (key, o) in last}
        cheaper = sorted((p, o) for o, p in others.items() if p < u * (1 - TIE))
        hints.append(
            {
                "file": fname,
                "line": n,
                "item": key,
                "supplier": s,
                "unit_net_pence": u,
                "cheaper_elsewhere": [o for _, o in cheaper],
                "cheapest_known_elsewhere": cheaper[0][1] if cheaper else None,
                "saving_pct": round(100 * (1 - cheaper[0][0] / u), 2) if cheaper else 0.0,
            }
        )
        last[(key, s)] = u
    return {
        "label": LABEL,
        "unit_note": "pence per normalised unit (roll, screw, sheet, litre, metre, pair ...), ex VAT; "
        "a till-style supplier's prices are converted to ex VAT; the cash supplier charges no VAT",
        "suppliers": sup_name,
        "period": {"from": START.isoformat(), "to": END.isoformat()},
        "items": items,
        "line_hints": hints,
    }


def plan_problems(cat: dict[str, Any], plan: list[dict[str, Any]]) -> list[str]:
    """Why this plan cannot be used: thin history for a pair, or a near tie for 'cheapest'."""
    problems = []
    seen: dict[tuple[str, int], list[int]] = {}
    for r in plan:
        for ln in r["lines"]:
            seen.setdefault((ln["key"], r["supplier"]), []).append(month_index(date.fromisoformat(r["date"])))
    for key, sups in cat["stock"].items():
        for si in sups:
            ms = seen.get((key, int(si)), [])
            if len(ms) < 3 or len(set(ms)) < 2:
                problems.append(f"{key}/{si}: {len(ms)} purchases over {len(set(ms))} months")
    return problems


def tie_problems(exp: dict[str, Any]) -> list[str]:
    out = []
    for key, it in exp["items"].items():
        for field in ("latest_runner_up_gap_pct", "mean_runner_up_gap_pct"):
            gap = it[field]
            if gap is not None and gap < TIE * 100:
                out.append(f"{key}: {field} {gap}%")
    return out


# ------------------------------------------------------------------------------------------------ stub


def stub_handlers() -> dict[str, Any]:
    towns = [("Halifax", "HX1 1AA"), ("Wakefield", "WF1 2BB"), ("Derby", "DE1 3CC"), ("Lancaster", "LA1 4DD"),
             ("Mansfield", "NG18 5EE")]  # fmt: skip
    names = ["Corbel & Hearth Supply Co", "Fennmoor Fixings Ltd", "Aldercote Timber Yard", "Pennine Joiners Mart",
             "Quillon Cash Carry"]  # fmt: skip

    def suppliers(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "suppliers": [
                {
                    "name": names[i],
                    "street": f"{i + 3} Foundry Road",
                    "town": t,
                    "postcode": pc,
                    "phone": f"01{i}2 555 01{i}",
                }
                for i, (t, pc) in enumerate(towns)
            ]
        }

    def products(h: dict[str, Any]) -> dict[str, Any]:
        out = []
        for k in h["keys"]:
            a = BY_KEY[k]
            words = " ".join(w.upper() if len(w) < 4 else w.title() for w in a["must"])
            out.append({"key": k, "name": f"Larchwell {words}", "alt_name": f"{words}"})
        return {"products": out}

    def listings(h: dict[str, Any]) -> dict[str, Any]:
        out = []
        for j, k in enumerate(h["keys"]):
            words = " ".join(BY_KEY[k]["must"])
            pn = f"LARCHWELL {words.upper()}" if h["supplier"] % 2 else f"{words.title()} (Larchwell)"
            out.append({"key": k, "print_name": pn, "sku": f"S{h['supplier']}-{j:03d}"})
        return {"listings": out}

    return {"suppliers": suppliers, "products": products, "listings": listings}


# ------------------------------------------------------------------------------------------------ main


def generate(
    client: Any, out: Path, n: int, seed: int, fresh: bool, dry: bool, max_seeds: int = 40
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    cat = build_dry_catalogue(client, seed) if dry else build_catalogue(client, out / "catalogue.json", seed, fresh)
    add_code_parts(cat, seed)
    plan = None
    for k in range(max_seeds):
        cand = build_plan(cat, n, seed + k)
        if plan_problems(cat, cand):
            continue
        plan_seed = seed + k
        rcpts = [make_receipt(cat, spec, i + 1, random.Random(f"{plan_seed}-{i}")) for i, spec in enumerate(cand)]
        files = [(f"{i + 1:03d}_price_history.json", g) for i, g in enumerate(rcpts)]
        exp = build_expectations(cat, files)
        if tie_problems(exp):
            continue
        plan = cand
        cat["plan_seed"] = plan_seed
        break
    if plan is None:
        raise SystemExit(
            f"no usable plan in {max_seeds} seeds (3+ purchases over 2+ months for every product/supplier pair needs "
            f"about 100+ receipts; N={n}); try another --seed or a larger N"
        )
    return cat, files, exp


def build_dry_catalogue(client: Any, seed: int) -> dict[str, Any]:
    """The same Qwen steps against the stub, kept in memory (nothing is saved)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        return build_catalogue(client, Path(tmp) / "catalogue.json", seed, True)


def write_all(cat, files, exp, out: Path, fresh: bool) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "receipts").mkdir(exist_ok=True)
    wrote = 0
    for fname, g in files:
        p = out / "receipts" / fname
        if p.exists() and not fresh:
            continue
        write_json(p, g)
        wrote += 1
    write_json(out / "catalogue.json", cat)
    write_json(out / "expectations.json", exp)
    manifest = {
        "generated_by": "qwen3.8-27b on DGX Spark (names, wording); prices, VAT, dates, expectations by code",
        "label": LABEL,
        "count": len(files),
        "items": [
            {"file": f"receipts/{f}", "case": "price_history", "supplier": g["supplier"]["name"], "date": g["date"],
             "gross": g["gross_total"]}
            for f, g in files
        ],
    }  # fmt: skip
    write_json(out / "manifest.json", manifest)
    write_text(
        out / "README.md",
        f"""# ledger4 gold set: price history

Fictional joinery-consumable receipts ({LABEL}) from five fictional suppliers over six months, for price-history and
"cheaper elsewhere" tests. Made by `evals/gold/gen_gold4.py`: Qwen names the suppliers and products; code sets every
price, pack size, VAT figure and date, and works out `expectations.json` from the finished documents.

- `receipts/NNN_price_history.json`: same schema as `evals/gold/receipts`, plus per line `item_key`, `sku`,
  `pack_units`, `unit_net_pence` (ex-VAT price per normalised unit).
- `expectations.json`: per product and supplier the observations, latest and mean normalised price, the cheapest
  supplier (latest and mean), and `line_hints`: for each line, which suppliers were cheaper at that date.
- `catalogue.json`: names, wording, who stocks what, and the month-by-month price table the receipts were made from.
""",
    )
    return wrote


def render_pngs(files, png_dir: Path) -> int:
    if str(EVALS) not in sys.path:
        sys.path.insert(0, str(EVALS))
    from harness.render import render_receipt

    png_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    for idx, (fname, g) in enumerate(files):
        p = png_dir / (fname.removesuffix(".json") + ".png")
        if p.exists():
            continue
        p.write_bytes(render_receipt(g["printed_text"], messy=True, seed=idx))
        made += 1
    return made


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", nargs="?", type=int, default=120, help="number of receipts (default 120)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--png-dir", type=Path, default=PNG_DIR)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="stub Qwen, build and check everything, write nothing")
    ap.add_argument("--stub", action="store_true", help="stub Qwen but write files (offline runs, tests)")
    ap.add_argument("--fresh", action="store_true", help="ignore saved catalogue and receipts and start over")
    args = ap.parse_args()
    t0 = time.time()
    client = StubQwen(stub_handlers()) if (args.dry_run or args.stub) else Qwen()
    try:
        cat, files, exp = generate(client, args.out, args.n, args.seed, args.fresh, args.dry_run)
    except QwenError as exc:
        raise SystemExit(f"Qwen step failed, run again to resume: {exc}") from exc
    pairs = sum(len(v["suppliers"]) for v in exp["items"].values())
    print(
        f"{len(files)} receipts, {len(exp['items'])} products, {pairs} product/supplier pairs, "
        f"plan seed {cat['plan_seed']}"
    )
    if args.dry_run:
        gross = sum(g["gross_pence"] for _, g in files) / 100
        print(f"dry run: nothing written. total £{gross:,.2f}; Qwen calls (stub) {client.calls}")
        return
    wrote = write_all(cat, files, exp, args.out, args.fresh)
    pngs = 0 if args.no_render else render_pngs(files, args.png_dir)
    print(f"DONE wrote {wrote} new receipts, {pngs} new PNGs in {time.time() - t0:.0f}s; Qwen calls {client.calls}")


if __name__ == "__main__":
    main()
