#!/usr/bin/env python3
"""CIS gold with Qwen3.8-27B (local vLLM on the Spark, OpenAI-compatible, :8000): contractors' monthly payment and
deduction statements, and subcontractors' VAT invoices under the domestic reverse charge, for app/ai/cis_read.py.

    python evals/gold/gen_gold_cis.py [--statements 30] [--invoices 30] [--seed 7]
    python evals/gold/gen_gold_cis.py --url http://127.0.0.1:8000/v1/chat/completions --model qwen3.8-27b
    python evals/gold/gen_gold_cis.py --dry-run                     # stub Qwen, builds and checks, writes nothing
    python evals/gold/gen_gold_cis.py --stub --out /tmp/cis         # offline run (the tests use this)

What Qwen does: invents the fictional businesses and words: main contractors (name, address, a short site name)
and subcontractors (trade, name, address), and a line description for each piece of work. Replies are checked
(every slot answered, no real trading name or brand, lengths) and re-asked, never repaired.

What code does, so every expected answer is right by construction: every figure, date, reference and number. A
statement's gross, materials and rate (20% net payment status, 30% unverified, 0% gross status) are drawn by code;
the deduction is app/cis.deduction (the HMRC example in CISR61230: (gross - materials) x rate, rounded down to the
penny) and the net payment is gross less the deduction. Tax months end on the 5th. An invoice's lines are priced in
pence, the VAT the customer accounts for is the net at 20% (or 5%), half up, and the amount due is the net: no VAT
is charged. UTRs, VAT numbers (valid mod-97, starting 0 like the rest of the gold set), employer references and
verification numbers are made up by code. Some documents are distractors on purpose: a statement whose printed
deduction is a slip (flagged `expect_check_fail`), and an invoice that leaves VAT off without the reverse charge
wording.

Output in evals/gold/cis/<id>/: document.txt (what the reader sees; first line the label), expected.json (the gold
reading in the shape of app/ai/cis_read.CisReading, pounds as printed, plus pence and the checks code must raise),
and evals/gold/cis/manifest.json + README.md. Every file carries the label SAMPLE — FICTIONAL COMPANY (em dash,
U+2014); `spark_gen.write_text` refuses one without it. Resumable: names.json is saved after the Qwen calls and
reused. Rules and sources: services/runtime/app/cis.py (GOV.UK, checked 28 Oct 2026).
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
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
    StubQwen,
    ask_validated,
    is_real,
    lr,
    m,
    read_json,
    vat_pence,
    vrn,
    write_json,
    write_text,
)

OUT = HERE / "cis"
TAX_MONTH_ENDS = [date(2026, mth, 5) for mth in range(5, 13)] + [date(2027, mth, 5) for mth in range(1, 5)]
REVERSE_CHARGE_WORDING = "Reverse charge: VAT Act 1994 Section 55A applies. Customer to pay the VAT to HMRC."
TRADES = ["electrician", "plumber", "plasterer", "bricklayer", "roofer", "groundworker", "joiner", "decorator", "tiler"]
STATUSES = [("net", 20)] * 6 + [("unverified", 30)] * 2 + [("gross", 0)]


def deduction(liable_pence: int, rate: int) -> int:
    """app/cis.deduction, repeated here so the generator runs without the runtime installed (the test compares them)."""
    return 0 if liable_pence <= 0 or rate <= 0 else liable_pence * rate // 100


def utr(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(10))


def employer_ref(rng: random.Random) -> str:
    letters = "ABCDEFGHJKLMNPRSTW"
    return f"{rng.randint(100, 999)}/{rng.choice(letters)}{rng.choice(letters)}{rng.randint(10000, 99999)}"


def verification(rng: random.Random, higher: bool) -> str:
    return f"V{rng.randint(10**9, 10**10 - 1)}" + (
        "".join(rng.choice("ABCDEFGHJK") for _ in range(2)) if higher else ""
    )


def uk(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ------------------------------------------------------------------------------------------------ Qwen's part


def names_prompt(n_contractors: int, n_subs: int) -> str:
    return (
        f"Invent {n_contractors} fictional UK main building contractors and {n_subs} fictional UK construction "
        "subcontractors for accounting test data. Reply as JSON: "
        '{"contractors": [{"name": "... Ltd", "address": "street, town, postcode", "site": "a short site name"}], '
        '"subcontractors": [{"name": "...", "trade": "electrician|plumber|plasterer|bricklayer|roofer|groundworker|'
        'joiner|decorator|tiler", "address": "street, town, postcode", "work": "one line describing a job, under 60 '
        'characters"}]}. Never use a real company, brand or person."'
    )


def check_names(reply: dict[str, Any], n_contractors: int, n_subs: int) -> str | None:
    cs, ss = reply.get("contractors"), reply.get("subcontractors")
    if not isinstance(cs, list) or not isinstance(ss, list) or len(cs) < n_contractors or len(ss) < n_subs:
        return "too few names"
    seen: set[str] = set()
    for item in [*cs[:n_contractors], *ss[:n_subs]]:
        if not isinstance(item, dict):
            return "an entry is not an object"
        name, addr = str(item.get("name") or ""), str(item.get("address") or "")
        if not 3 <= len(name) <= 60 or not 8 <= len(addr) <= 90:
            return f"bad length: {name!r}"
        if is_real(name):
            return f"real name: {name!r}"
        if name.lower() in seen:
            return f"duplicate name {name!r}"
        seen.add(name.lower())
    for s in ss[:n_subs]:
        if s.get("trade") not in TRADES:
            return f"unknown trade {s.get('trade')!r}"
        if not 5 <= len(str(s.get("work") or "")) <= 60:
            return "work description length"
    for c in cs[:n_contractors]:
        if not 3 <= len(str(c.get("site") or "")) <= 40:
            return "site length"
    return None


def stub_handlers() -> dict[str, Any]:
    """Offline Qwen: fixed fictional names (the tests and --stub/--dry-run)."""
    towns = ["Leeds LS2 7AB", "York YO1 6HT", "Hull HU1 2BX", "Ripon HG4 1QS", "Selby YO8 4PL", "Otley LS21 3JT"]

    def names(hint: dict[str, Any]) -> dict[str, Any]:
        nc, ns = hint["contractors"], hint["subcontractors"]
        return {
            "contractors": [
                {
                    "name": f"Fernhollow Build {i + 1} Ltd",
                    "address": f"{i + 3} Quarry Lane, {towns[i % 6]}",
                    "site": f"Plot {i + 10} Mill View",
                }
                for i in range(nc)
            ],
            "subcontractors": [
                {
                    "name": f"Wrenstone {TRADES[i % len(TRADES)].title()}s {i + 1}",
                    "trade": TRADES[i % len(TRADES)],
                    "address": f"{i + 1} Kiln Row, {towns[(i + 2) % 6]}",
                    "work": f"{TRADES[i % len(TRADES)]} works, phase {i + 1}",
                }
                for i in range(ns)
            ],
        }

    return {"names": names}


def get_names(client: Any, out: Path | None, n_contractors: int, n_subs: int, log: Any) -> dict[str, Any]:
    cached = out / "names.json" if out else None
    if cached and cached.exists():
        got = read_json(cached)
        if check_names(got, n_contractors, n_subs) is None:
            return got
    reply = ask_validated(
        client,
        names_prompt(n_contractors, n_subs),
        lambda r: check_names(r, n_contractors, n_subs),
        kind="names",
        hint={"contractors": n_contractors, "subcontractors": n_subs},
        log=log,
    )
    got = {
        "label": LABEL,
        "contractors": reply["contractors"][:n_contractors],
        "subcontractors": reply["subcontractors"][:n_subs],
    }
    if cached:
        write_json(cached, got)
    return got


# ------------------------------------------------------------------------------------------------ code's part


def make_statement(rng: random.Random, i: int, contractor: dict[str, Any], sub: dict[str, Any]) -> dict[str, Any]:
    end = rng.choice(TAX_MONTH_ENDS)
    status, rate = rng.choice(STATUSES)
    gross = rng.randrange(40_000, 900_000, 5)  # £400 to £9,000, whole 5p
    materials = 0 if rng.random() < 0.3 else rng.randrange(0, gross // 2, 1)
    cut = deduction(gross - materials, rate)
    slip = i % 9 == 8 and rate > 0  # a distractor: the printed deduction is wrong by a few pounds
    printed_cut = cut + rng.choice([-500, 300, 1_000]) if slip else cut
    printed_cut = max(0, min(printed_cut, gross - materials))
    sub_utr = utr(rng)
    vn = verification(rng, rate == 30) if rate == 30 else None
    contractor_ref = employer_ref(rng)
    lines = [
        LABEL,
        "",
        "PAYMENT AND DEDUCTION STATEMENT",
        "Construction Industry Scheme",
        "",
        contractor["name"],
        contractor["address"],
        f"Employer's tax reference: {contractor_ref}",
        "",
        lr("Tax month ending", uk(end)),
        lr("Subcontractor", sub["name"]),
        lr("Subcontractor UTR", sub_utr),
        *([lr("Verification number", vn)] if vn else []),
        lr("Site", contractor["site"]),
        "",
        lr("Gross amount paid (excl VAT)", f"£{m(gross)}"),
        lr("Less cost of materials", f"£{m(materials)}"),
        lr("Amount liable to deduction", f"£{m(gross - materials)}"),
        lr(f"Amount deducted ({rate}%)", f"£{m(printed_cut)}"),
        lr("Amount payable", f"£{m(gross - printed_cut)}"),
        "",
        "Keep this statement: you need it to claim the deduction against your tax.",
        LABEL,
    ]
    expected = {
        "kind": "cis_statement",
        "contractor_name": contractor["name"],
        "contractor_ref": contractor_ref,
        "subcontractor_name": sub["name"],
        "subcontractor_utr": sub_utr,
        "verification_number": vn,
        "tax_month_end": end.isoformat(),
        "gross_amount": gross / 100,
        "materials": materials / 100,
        "amount_liable": (gross - materials) / 100,
        "deduction": printed_cut / 100,
        "net_paid": (gross - printed_cut) / 100,
        "reverse_charge_wording": False,
    }
    return {
        "id": f"S{i + 1:03d}",
        "kind": "cis_statement",
        "status": status,
        "rate": rate,
        "text": "\n".join(lines) + "\n",
        "expected": expected,
        "pence": {"gross": gross, "materials": materials, "deduction": printed_cut, "correct_deduction": cut},
        "expect_check_fail": ["RATE"] if slip else [],
    }


def make_invoice(rng: random.Random, i: int, sub: dict[str, Any], contractor: dict[str, Any]) -> dict[str, Any]:
    day = date(2026, 4, 6) + timedelta(days=rng.randrange(0, 360))
    rate = 5 if i % 7 == 6 else 20  # reduced rate: e.g. energy-saving materials installed in a home
    hours = rng.choice([8, 16, 24, 37.5, 40, 45])
    hourly = rng.randrange(2_800, 6_500, 50)  # whole 50p, so half hours price to whole pence
    labour = int(hours * 2) * hourly // 2
    materials = 0 if rng.random() < 0.35 else rng.randrange(5_000, 150_000, 1)
    net = labour + materials
    rc_vat = vat_pence(net, rate)
    distractor = i % 10 == 9  # VAT left off with no reverse-charge wording: must be flagged, not booked
    supplier_vrn, customer_vrn = vrn(rng), vrn(rng)
    number = f"{sub['name'][:3].upper()}-{rng.randint(100, 999)}"
    lines = [
        LABEL,
        "",
        sub["name"],
        sub["address"],
        f"VAT reg no: {supplier_vrn}",
        "",
        "VAT INVOICE",
        lr("Invoice number", number),
        lr("Invoice date", uk(day)),
        "",
        "Bill to:",
        contractor["name"],
        contractor["address"],
        f"VAT no: {customer_vrn}",
        "",
        lr(f"{sub['work']} ({hours} h @ £{m(hourly)})", f"£{m(labour)}"),
        *([lr("Materials supplied", f"£{m(materials)}")] if materials else []),
        "",
        lr("Net", f"£{m(net)}"),
        *(
            [lr("VAT", "£0.00"), lr("Amount due", f"£{m(net)}")]
            if distractor
            else [
                lr(f"VAT at {rate}% to be accounted for by the customer", f"£{m(rc_vat)}"),
                lr("Amount due (no VAT charged)", f"£{m(net)}"),
                "",
                REVERSE_CHARGE_WORDING,
            ]
        ),
        LABEL,
    ]
    expected = {
        "kind": "reverse_charge_invoice",
        "supplier_name": sub["name"],
        "supplier_vat_number": supplier_vrn,
        "invoice_number": number,
        "invoice_date": day.isoformat(),
        "net": net / 100,
        "vat_rate": rate,
        "reverse_charge_vat": None if distractor else rc_vat / 100,
        "reverse_charge_wording": not distractor,
    }
    return {
        "id": f"R{i + 1:03d}",
        "kind": "reverse_charge_invoice",
        "rate": rate,
        "text": "\n".join(lines) + "\n",
        "expected": expected,
        "pence": {"labour": labour, "materials": materials, "net": net, "reverse_charge_vat": rc_vat},
        "expect_check_fail": ["RC_WORDING"] if distractor else [],
    }


def build(client: Any, n_statements: int, n_invoices: int, seed: int, out: Path | None, log: Any = print) -> list[dict]:
    rng = random.Random(seed)
    n_contractors, n_subs = max(3, n_statements // 5 + 1), max(4, n_invoices // 4 + 1)
    names = get_names(client, out, n_contractors, n_subs, log)
    cs, ss = names["contractors"], names["subcontractors"]
    docs = [make_statement(rng, i, cs[i % len(cs)], ss[i % len(ss)]) for i in range(n_statements)]
    docs += [make_invoice(rng, i, ss[i % len(ss)], cs[i % len(cs)]) for i in range(n_invoices)]
    return docs


def write_all(docs: list[dict], out: Path, seed: int, model: str) -> None:
    for d in docs:
        folder = out / d["id"]
        write_text(folder / "document.txt", d["text"])
        write_json(
            folder / "expected.json",
            {
                "label": LABEL,
                "id": d["id"],
                "expected": d["expected"],
                "pence": d["pence"],
                "expect_check_fail": d["expect_check_fail"],
                "rate": d["rate"],
            },
        )
    write_json(
        out / "manifest.json",
        {
            "label": LABEL,
            "seed": seed,
            "names_by": model,
            "figures_by": "code (gen_gold_cis.py)",
            "documents": [
                {"id": d["id"], "kind": d["kind"], "rate": d["rate"], "expect_check_fail": d["expect_check_fail"]}
                for d in docs
            ],
        },
    )
    write_text(
        out / "README.md",
        f"# CIS gold — {LABEL}\n\nMade by `evals/gold/gen_gold_cis.py` (seed {seed}). Names and words by "
        f"{model}; every figure, date and number by code. {sum(d['kind'] == 'cis_statement' for d in docs)} "
        f"payment and deduction statements (S…) and {sum(d['kind'] == 'reverse_charge_invoice' for d in docs)} "
        "reverse-charge invoices (R…). Each folder: `document.txt` (what the reader sees) and `expected.json` "
        "(the gold reading, the pence, and the checks that must fail on the distractors). All fictional.\n",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--statements", type=int, default=30)
    ap.add_argument("--invoices", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--url", default=QWEN_URL)
    ap.add_argument("--model", default=QWEN_MODEL)
    ap.add_argument("--stub", action="store_true", help="offline: fixed names, no network")
    ap.add_argument("--dry-run", action="store_true", help="stub names, build and check everything, write nothing")
    a = ap.parse_args(argv)
    offline = a.stub or a.dry_run
    client = StubQwen(stub_handlers()) if offline else Qwen(a.url, a.model)
    docs = build(client, a.statements, a.invoices, a.seed, None if a.dry_run else a.out)
    for d in docs:
        if LABEL not in d["text"]:
            raise SystemExit(f"{d['id']}: no label")
    if a.dry_run:
        print(f"dry run: {len(docs)} documents built and checked; nothing written")
        return 0
    write_all(docs, a.out, a.seed, "stub" if offline else a.model)
    print(f"wrote {len(docs)} documents to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
