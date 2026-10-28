#!/usr/bin/env python3
"""Landlord gold with Qwen3.8-27B (local vLLM on the Spark, :8000): letting agents' monthly statements and the
property bills of a fictional landlord with two lets, for the property pages (services/runtime/app/property.py).

    python evals/gold/gen_gold_landlord.py [--landlords 2] [--seed 7]
    python evals/gold/gen_gold_landlord.py --dry-run                    # stub Qwen, builds and checks, writes nothing
    python evals/gold/gen_gold_landlord.py --stub --out /tmp/l --landlords 1   # offline run (the tests use this)
    python evals/gold/gen_gold_landlord.py --url http://spark:8000/v1/chat/completions --model qwen3.8-27b

What Qwen does: names things. The landlord, the joint owner (a spouse), two property addresses, the letting agent,
two tenants, and the firms behind the bills (insurer, mortgage lender, plumber, gas engineer, appliance shop,
managing agent of the flat's block). Replies are checked (every slot answered, no real trading name, lengths, unique
names, a UK-looking postcode) and re-asked, never repaired.

What code does, so the expected answers are right by construction: every figure and date. Rents (whole pounds),
the agent's 10 % management fee plus VAT at 20 % on the fee, repairs the agent paid and deducted, the net sent to
the landlord, an annual landlord insurance premium, a mortgage statement split into capital and interest (only
the interest is a finance cost, and a restricted one), a gas safety check, a boiler repair, a like-for-like
replacement washing machine with its disposal charge and a trade-in (relief = cost + disposal − proceeds), and the
flat's ground rent and service charge. Then the expectations: per document, the HMRC category of each figure
(Property Business API 6.0 field and SA105 box, the same keys as app/property.py), per property and per owner
for the tax year to 5 October 2026 (the first two quarterly updates), with the jointly owned house split 50:50
(spouses without a Form 17 declaration, ITA 2007 s836).

Output per landlord in evals/gold/landlord/<name>/: statements/<yyyy-mm>_<property>.txt, bills/<n>_<kind>.txt,
expectations.json, names.json, README.md. Every file carries the label SAMPLE — FICTIONAL COMPANY (em dash,
U+2014). Tax year 2026-27, documents dated 6 April to 5 October 2026.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from spark_gen import (  # noqa: E402
    LABEL,
    QWEN_MODEL,
    QWEN_URL,
    Qwen,
    QwenError,
    StubQwen,
    ask_validated,
    is_real,
    lr,
    m,
    read_json,
    vat_pence,
    write_json,
    write_text,
)

OUT = HERE / "landlord"
TAX_YEAR = "2026-27"
START, PERIOD_END = date(2026, 4, 6), date(2026, 10, 5)
MONTHS = [(2026, mo) for mo in range(4, 10)]  # statements for April to September, each dated the 28th
FEE_PERCENT = 10
POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$")

# The keys of app/property.py CATEGORIES: (API field, SA105 box).
CATEGORY = {
    "rents": ("periodAmount", "20"),
    "premises": ("premisesRunningCosts", "24"),
    "repairs": ("repairsAndMaintenance", "25"),
    "professional": ("professionalFees", "27"),
    "other": ("other", "29"),
    "finance_res": ("residentialFinancialCost", "44"),
    "domestic_items": ("costOfReplacingDomesticItems", "36"),
}

SLOTS: list[tuple[str, str]] = [
    ("landlord", "the landlord, a person (first name and surname)"),
    ("spouse", "the landlord's spouse, a person (first name and the same surname)"),
    ("agent", "a residential letting and management agency"),
    ("tenant_flat", "the tenant of the flat, a person"),
    ("tenant_house", "the tenant of the house, a person"),
    ("insurer", "a landlord insurance company"),
    ("lender", "a buy-to-let mortgage lender"),
    ("plumber", "a plumbing and heating firm"),
    ("gas", "a gas safety engineer (sole trader trading name)"),
    ("appliances", "an electrical appliance shop"),
    ("block", "the managing agent of a block of flats"),
]
NAMES_PROMPT = """Invent fictional UK names for a landlord's paperwork. For each slot give a made-up "name" (2-4 words,
at most 32 characters, not resembling any real company, brand or famous person).
Slots (slot: what it is):
%s
Also invent two fictional property addresses in one English town: "flat" (a flat in a small block, like "Flat 3,
Orchard House, 12 Station Road") and "house" (a terraced house, like "27 Mill Lane"), each with a "town" and a UK
"postcode" in the normal format (e.g. LS6 2AB).
Return ONLY JSON: {"names":[{"slot":str,"name":str}],"flat":{"address":str,"town":str,"postcode":str},
"house":{"address":str,"town":str,"postcode":str}} with one entry per slot, all names different."""


def check_names(reply: dict[str, Any]) -> str | None:
    got = reply.get("names")
    slots = [s for s, _ in SLOTS]
    if not isinstance(got, list) or sorted(str(p.get("slot", "")) for p in got if isinstance(p, dict)) != sorted(slots):
        return "slots do not match"
    seen: set[str] = set()
    for p in got:
        name = p.get("name")
        if not isinstance(name, str) or not 3 <= len(name.strip()) <= 32 or is_real(name):
            return f"{p.get('slot')}: bad or real name {name!r}"
        if name.strip().lower() in seen:
            return f"duplicate name {name!r}"
        seen.add(name.strip().lower())
    for key in ("flat", "house"):
        a = reply.get(key)
        if not isinstance(a, dict):
            return f"{key}: missing"
        if not isinstance(a.get("address"), str) or not 5 <= len(a["address"]) <= 60 or is_real(a["address"]):
            return f"{key}: bad address"
        if not isinstance(a.get("town"), str) or not 2 <= len(a["town"]) <= 30:
            return f"{key}: bad town"
        if not isinstance(a.get("postcode"), str) or not POSTCODE.fullmatch(a["postcode"].strip().upper()):
            return f"{key}: bad postcode {a.get('postcode')!r}"
    return None


def build_names(client: Any, path: Path | None, seed: int, fresh: bool) -> dict[str, Any]:
    """Qwen's names, saved to names.json (with the label) so a re-run reuses them."""
    if path is not None and path.exists() and not fresh:
        return read_json(path)
    prompt = NAMES_PROMPT % "\n".join(f"- {s}: {d}" for s, d in SLOTS)
    reply = ask_validated(client, prompt, check_names, kind="names", hint={"seed": seed}, seed=seed)
    names = {
        "label": LABEL,
        "seed": seed,
        "people": {p["slot"]: p["name"].strip() for p in reply["names"]},
        "flat": {**reply["flat"], "postcode": reply["flat"]["postcode"].strip().upper()},
        "house": {**reply["house"], "postcode": reply["house"]["postcode"].strip().upper()},
    }
    if path is not None:
        write_json(path, names)
    return names


# ------------------------------------------------------------------------------------------------ figures


def _doc(kind: str, day: date, prop: str, title: str, lines: list[tuple[str, int]], figures: list[dict]) -> dict:
    return {"kind": kind, "date": day.isoformat(), "property": prop, "title": title, "lines": lines, "figures": figures}


def _fig(category: str, pence: int, what: str) -> dict:
    field, box = CATEGORY[category]
    return {"category": category, "field": field, "box": box, "pence": pence, "what": what}


def simulate(names: dict[str, Any], seed: int) -> dict[str, Any]:
    """Every document and figure, by code. Rents are whole pounds and multiples of £10, so 10 % is whole pence."""
    rng = random.Random(seed * 7919 + 17)
    p = names["people"]
    rent = {"flat": rng.randrange(650, 1000, 10) * 100, "house": rng.randrange(950, 1500, 10) * 100}
    docs: list[dict] = []

    # Monthly agent statements, one per property, with one repair the agent paid on the house in July.
    agent_repair = {("house", 7): rng.randrange(80, 260) * 100 + rng.choice([0, 50, 99])}
    for y, mo in MONTHS:
        for prop in ("flat", "house"):
            day = date(y, mo, 28)
            r = rent[prop]
            fee = r * FEE_PERCENT // 100
            fee_vat = vat_pence(fee)
            repair = agent_repair.get((prop, mo), 0)
            net = r - fee - fee_vat - repair
            lines = [
                (f"Rent received from {p[f'tenant_{prop}']}", r),
                (f"Management fee {FEE_PERCENT}%", -fee),
                ("VAT on management fee at 20%", -fee_vat),
            ]
            figs = [_fig("rents", r, "rent"), _fig("professional", fee + fee_vat, "management fee incl. VAT")]
            if repair:
                lines.append((f"Repair paid to {p['plumber']}: kitchen tap and waste", -repair))
                figs.append(_fig("repairs", repair, "repair paid by the agent"))
            lines.append(("Paid to landlord", net))
            docs.append(_doc("letting_statement", day, prop, f"Landlord statement {day:%B %Y}", lines, figs))

    # Bills (the landlord pays these directly).
    ins = rng.randrange(180, 420) * 100 + rng.choice([0, 25, 50, 75])
    ipt = ins * 12 // 112  # premium includes Insurance Premium Tax at 12 %: shown, not reclaimable
    docs.append(
        _doc(
            "insurance",
            date(2026, 4, 20),
            "house",
            f"Landlord buildings and contents insurance, {names['house']['address']}",
            [("Annual premium including Insurance Premium Tax", ins), ("of which Insurance Premium Tax", ipt)],
            [_fig("premises", ins, "annual landlord insurance")],
        )
    )
    payment = rng.randrange(520, 880) * 100
    interest = [payment * rng.randrange(52, 68) // 100 for _ in range(6)]
    capital = [payment - i for i in interest]
    docs.append(
        _doc(
            "mortgage_statement",
            date(2026, 10, 5),
            "house",
            "Mortgage statement, 6 April to 5 October 2026",
            [
                ("Monthly payments made (6)", payment * 6),
                ("of which interest", sum(interest)),
                ("of which capital repaid", sum(capital)),
            ],
            [_fig("finance_res", sum(interest), "mortgage interest only; capital repaid is not a cost")],
        )
    )
    gas = rng.randrange(60, 95) * 100
    docs.append(
        _doc(
            "invoice",
            date(2026, 5, 14),
            "flat",
            "Landlord gas safety record (CP12)",
            [("Annual gas safety check and certificate", gas)],
            [_fig("other", gas, "gas safety certificate")],
        )
    )
    boiler = rng.randrange(140, 380) * 100 + rng.choice([0, 50])
    boiler_vat = vat_pence(boiler)
    docs.append(
        _doc(
            "invoice",
            date(2026, 8, 3),
            "house",
            "Boiler repair",
            [
                ("Replace diverter valve, labour and parts", boiler),
                ("VAT at 20%", boiler_vat),
                ("Total", boiler + boiler_vat),
            ],
            [_fig("repairs", boiler + boiler_vat, "repair incl. VAT (landlord not VAT registered)")],
        )
    )
    machine = rng.randrange(299, 549) * 100 - 1  # e.g. £348.99
    disposal, trade_in = 2000, rng.choice([0, 1500, 2500])
    relief = machine + disposal - trade_in
    docs.append(
        _doc(
            "invoice",
            date(2026, 6, 22),
            "flat",
            "Replacement washing machine (like for like)",
            [
                ("Washing machine, 8 kg", machine),
                ("Removal and disposal of the old machine", disposal),
                ("Trade-in allowance", -trade_in),
            ],
            [_fig("domestic_items", relief, "replacement relief: cost + disposal − proceeds")],
        )
    )
    ground, service = rng.randrange(150, 300) * 100, rng.randrange(600, 1100) * 100
    docs.append(
        _doc(
            "invoice",
            date(2026, 6, 24),
            "flat",
            "Ground rent and service charge, half year to 28 September 2026",
            [("Ground rent", ground), ("Service charge", service)],
            [_fig("premises", ground + service, "ground rent and service charge")],
        )
    )

    # Expectations: per property (whole), per owner, and the landlord's own share, to the period end.
    whole: dict[str, dict[str, int]] = {"flat": defaultdict(int), "house": defaultdict(int)}
    for d in docs:
        if START <= date.fromisoformat(d["date"]) <= PERIOD_END:
            for f in d["figures"]:
                whole[d["property"]][f["category"]] += f["pence"]
    owners = {
        "flat": [{"name": p["landlord"], "me": True, "share_bp": 10_000}],
        "house": [
            {"name": p["landlord"], "me": True, "share_bp": 5_000},
            {"name": p["spouse"], "me": False, "share_bp": 5_000},
        ],
    }
    mine: dict[str, int] = defaultdict(int)
    per_owner: dict[str, dict[str, dict[str, int]]] = {}
    for prop, cats in whole.items():
        per_owner[prop] = {}
        for i, o in enumerate(owners[prop]):
            share = {}
            for cat, pence in cats.items():
                parts = split_pence(pence, [x["share_bp"] for x in owners[prop]])
                share[cat] = parts[i]
                if o["me"]:
                    mine[cat] += parts[i]
            per_owner[prop][o["name"]] = share
    expenses = sum(v for k, v in mine.items() if k in ("premises", "repairs", "professional", "other"))
    profit = mine["rents"] - expenses - mine["domestic_items"]
    finance = mine["finance_res"]
    relieved = min(finance, max(0, profit))
    return {
        "rent": rent,
        "documents": docs,
        "owners": owners,
        "expectations": {
            "tax_year": TAX_YEAR,
            "period": {"from": START.isoformat(), "to": PERIOD_END.isoformat()},
            "whole": {k: dict(v) for k, v in whole.items()},
            "per_owner": per_owner,
            "mine": dict(mine),
            "mine_expenses": expenses,
            "mine_profit": profit,
            "finance_credit_pence": relieved * 20 // 100,
            "cumulative_body": cumulative_body(mine),
            "annual_body": {
                "ukProperty": {"allowances": {"costOfReplacingDomesticItems": mine["domestic_items"] / 100}}
            },
        },
    }


def split_pence(amount: int, shares_bp: list[int]) -> list[int]:
    """The same rule as app/property.split_pence: round down, leftover pennies to the largest remainders."""
    exact = [amount * s for s in shares_bp]
    parts = [e // 10_000 for e in exact]
    for i in sorted(range(len(parts)), key=lambda i: (-(exact[i] % 10_000), i))[: amount - sum(parts)]:
        parts[i] += 1
    return parts


def cumulative_body(mine: dict[str, int]) -> dict[str, Any]:
    """Property Business API 6.0 cumulative body for the landlord's share, itemised (as app/property.py makes it)."""
    expenses = {CATEGORY[k][0]: mine[k] / 100 for k in ("premises", "repairs", "professional", "other") if mine.get(k)}
    if mine.get("finance_res"):
        expenses["residentialFinancialCost"] = mine["finance_res"] / 100
    return {
        "fromDate": START.isoformat(),
        "toDate": PERIOD_END.isoformat(),
        "ukProperty": {"income": {"periodAmount": mine["rents"] / 100}, "expenses": expenses},
    }


# ------------------------------------------------------------------------------------------------ rendering


def render(doc: dict, names: dict[str, Any]) -> str:
    p = names["people"]
    prop = names[doc["property"]]
    issuer = {
        "letting_statement": p["agent"],
        "insurance": p["insurer"],
        "mortgage_statement": p["lender"],
    }.get(doc["kind"])
    if issuer is None:
        issuer = {
            "Landlord gas safety record (CP12)": p["gas"],
            "Boiler repair": p["plumber"],
            "Replacement washing machine (like for like)": p["appliances"],
        }.get(doc["title"], p["block"])
    out = [LABEL, "", issuer, "", doc["title"], f"Date: {date.fromisoformat(doc['date']):%d/%m/%Y}"]
    out += [f"To: {p['landlord']} and {p['spouse']}" if doc["property"] == "house" else f"To: {p['landlord']}"]
    out += [f"Property: {prop['address']}, {prop['town']} {prop['postcode']}", ""]
    for text, pence in doc["lines"]:
        out.append(lr(text, ("-£" if pence < 0 else "£") + m(abs(pence)), 72))
    out += ["", LABEL, ""]
    return "\n".join(out)


def readme(names: dict[str, Any], world: dict[str, Any]) -> str:
    e = world["expectations"]
    p = names["people"]
    return "\n".join(
        [
            f"# {LABEL}: landlord {p['landlord']}",
            "",
            f"Two lets: {names['flat']['address']} (owned alone) and {names['house']['address']} (owned with "
            f"{p['spouse']}, taxed 50:50). {len(world['documents'])} documents, tax year {TAX_YEAR}, "
            f"{e['period']['from']} to {e['period']['to']}.",
            "",
            "Every figure was fixed by code (gen_gold_landlord.py); Qwen only invented the names. expectations.json "
            "holds each property's totals by HMRC category, the per-owner split, the landlord's share and the "
            "Property Business API 6.0 bodies app/property.py should produce.",
            "",
            f"Landlord's share: rents £{m(e['mine']['rents'])}, expenses £{m(e['mine_expenses'])}, profit "
            f"£{m(e['mine_profit'])}, residential finance costs £{m(e['mine'].get('finance_res', 0))}.",
            "",
        ]
    )


def write_landlord(names: dict[str, Any], world: dict[str, Any], out: Path) -> None:
    for i, d in enumerate(world["documents"], 1):
        if d["kind"] == "letting_statement":
            path = out / "statements" / f"{d['date'][:7]}_{d['property']}.txt"
        else:
            path = out / "bills" / f"{i:02d}_{d['kind']}.txt"
        write_text(path, render(d, names))
    write_json(
        out / "expectations.json",
        {"label": LABEL, "owners": world["owners"], "documents": world["documents"], **world["expectations"]},
    )
    write_text(out / "README.md", readme(names, world))
    if not (out / "names.json").exists():
        write_json(out / "names.json", names)


# ------------------------------------------------------------------------------------------------ stub and main


def stub_handlers() -> dict[str, Any]:
    def names(h: dict[str, Any]) -> dict[str, Any]:
        s = h.get("seed", 0)
        surname = ["Ashworth", "Penhallow", "Kettlewell", "Ormsby"][s % 4]
        people = {
            "landlord": f"Morgan {surname}",
            "spouse": f"Robin {surname}",
            "agent": f"Larkfield Lettings {s}",
            "tenant_flat": "Jordan Featherstone",
            "tenant_house": "Casey Underhill",
            "insurer": "Bramcote Landlord Cover",
            "lender": "Wrenford Home Lending",
            "plumber": "Calder Valley Heating",
            "gas": "Thistle Gas Checks",
            "appliances": "Oakhaven Appliances",
            "block": "Harrowgate Block Management",
        }
        return {
            "names": [{"slot": k, "name": v} for k, v in people.items()],
            "flat": {"address": "Flat 3, Orchard House, 12 Kiln Road", "town": "Wetherfield", "postcode": "WF9 2QT"},
            "house": {"address": "27 Tanner Lane", "town": "Wetherfield", "postcode": "WF9 4LB"},
        }

    return {"names": names}


def make_landlord(client: Any, out: Path | None, seed: int, fresh: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    names = build_names(client, out / "names.json" if out else None, seed, fresh)
    return names, simulate(names, seed)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--landlords", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--url", default=QWEN_URL)
    ap.add_argument("--model", default=QWEN_MODEL)
    ap.add_argument("--stub", action="store_true", help="answer from the offline stub instead of Qwen")
    ap.add_argument("--dry-run", action="store_true", help="stub Qwen, build and check everything, write nothing")
    ap.add_argument("--fresh", action="store_true", help="ask Qwen again even if names.json exists")
    args = ap.parse_args(argv)
    client = StubQwen(stub_handlers()) if args.stub or args.dry_run else Qwen(args.url, args.model)
    try:
        for i in range(args.landlords):
            seed = args.seed + i
            if args.dry_run:
                names, world = make_landlord(client, None, seed, True)
                print(f"landlord {seed}: {len(world['documents'])} documents (dry run, nothing written)")
                continue
            target = args.out / f"landlord_{seed}"
            names, world = make_landlord(client, target, seed, args.fresh)
            write_landlord(names, world, target)
            print(f"landlord {seed}: {len(world['documents'])} documents -> {target}")
    except QwenError as exc:
        print(f"Qwen failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
