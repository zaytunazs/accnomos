#!/usr/bin/env python3
"""Personal (household) bank statement gold with Qwen3.8-27B (local vLLM on the Spark, :8000): six months of a
fictional household's current account, for recurring-bill detection and category totals.

    python evals/gold/gen_personal.py [--layout starling|tide|barclays] [--households 2]
    python evals/gold/gen_personal.py --dry-run                       # stub Qwen, builds and checks, writes nothing
    python evals/gold/gen_personal.py --stub --out /tmp/p --households 1   # offline run (the tests use this)

What Qwen does: names the household's payees (employer, letting agent, council, energy and water firms, phone and
broadband, subscriptions, supermarkets, fuel, cafés ...) and gives each a short payment reference. Replies are
checked (every slot answered, no real trading name, lengths, unique names) and re-asked, never repaired.

What code does, so the expected answers are right by construction: every amount, date and recurrence. There are
about 25 recurring series (monthly direct debits and standing orders, a weekly cleaner, a four-weekly groomer,
salary, a savings transfer; some with a price rise part-way, one cancelled in June, one started in July, one whose
reference changes every month) and distractors that must NOT be flagged (cafés and supermarkets visited often with
varying amounts, an annual insurance paid once, a quarterly bill with only two payments in the window). Weekend and
bank-holiday dates move to the next working day for direct debits and standing orders. The opening balance is set
so the account never goes overdrawn; the Balance column is computed. Then the expectations are written from the
finished transaction list: each recurring series (dates, amounts, changes), the monthly committed total, totals per
category and month, and the category of every statement row.

Output per household in evals/gold/personal/<name>/: statement.csv (the first line is the label, a preamble the bank
importer skips), expectations.json, README.md. Resumable: names.json is saved after each Qwen batch and reused.
Every file carries the label SAMPLE — FICTIONAL COMPANY (em dash, U+2014). Period 2026-04-01 to 2026-09-30.
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from spark_gen import (  # noqa: E402
    LABEL,
    Qwen,
    QwenError,
    StubQwen,
    ask_validated,
    is_real,
    read_json,
    write_json,
    write_text,
)

OUT = HERE / "personal"
START, END = date(2026, 4, 1), date(2026, 9, 30)
MONTHS = [f"2026-{m:02d}" for m in range(4, 10)]
# England and Wales bank holidays in the window (direct debits and standing orders move to the next working day).
BANK_HOLIDAYS = {date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4), date(2026, 5, 25), date(2026, 8, 31)}
CITIES = ["LEEDS", "YORK", "HARROGATE", "WAKEFIELD", "SHEFFIELD", "BRADFORD", "HULL", "LONDON", "MANCHESTER"]

# Slots Qwen names, in batches (one Qwen call each).
BATCHES: dict[str, list[tuple[str, str]]] = {
    "income and housing": [
        ("employer", "the employer that pays the salary (a mid-sized UK firm)"),
        ("client", "a small business that pays the household for occasional freelance work"),
        ("landlord", "the letting agent that collects the rent"),
        ("council", "a fictional borough council, for council tax"),
    ],
    "utilities, phones and insurance": [
        ("energy", "an electricity and gas supplier"),
        ("water", "a water company"),
        ("broadband", "a broadband provider"),
        ("mobile_a", "a mobile network"),
        ("mobile_b", "a second, budget mobile network"),
        ("car_insurance", "a car insurer paid monthly"),
        ("travel_insurance", "an insurer for one annual travel policy"),
        ("water_sewer", "a regional utility that bills quarterly for drainage"),
    ],
    "subscriptions": [
        ("video", "a video streaming service"),
        ("music", "a music streaming service"),
        ("cloud", "a cloud storage service"),
        ("gym", "a gym or leisure centre"),
        ("news", "a digital newspaper subscription (cancelled in June)"),
        ("mealkit", "a recipe-box delivery service (started in July)"),
        ("charity", "a small charity taking a monthly donation"),
        ("cleaner", "a domestic cleaning firm paid every week"),
        ("groomer", "a dog groomer visited every four weeks"),
    ],
    "food shops and eating out": [
        ("super_a", "a supermarket chain"),
        ("super_b", "a second, discount supermarket chain"),
        ("corner", "a corner shop or convenience store"),
        ("coffee", "a coffee shop"),
        ("takeaway", "a takeaway restaurant"),
        ("restaurant", "a casual restaurant"),
        ("pub", "a pub"),
    ],
    "transport": [
        ("fuel_a", "a petrol station chain"),
        ("fuel_b", "a motorway services or independent fuel station"),
        ("rail", "a train operator"),
        ("taxi", "a taxi firm"),
        ("carpark", "a car park operator"),
        ("bus", "a bus company"),
    ],
    "shopping and health": [
        ("clothes", "a clothes shop"),
        ("homestore", "a home and furniture store"),
        ("pharmacy", "a pharmacy"),
        ("books", "a bookshop"),
        ("garden", "a garden centre"),
        ("online", "an online marketplace for general shopping"),
    ],
}
SLOTS = {slot: desc for group in BATCHES.values() for slot, desc in group}

NAMES_PROMPT = """Invent fictional UK businesses for a bank statement. Group: %s. For each slot give a made-up
trading "name" (1-4 words, at most 28 characters, not resembling any real company or brand) and a short payment
"reference" (4-16 characters: an account number or customer code as it would appear, letters, digits, spaces, dashes).
Slots (slot: what it is):
%s
Return ONLY JSON: {"payees":[{"slot":str,"name":str,"reference":str}]} with one entry per slot, names all different."""
HOUSEHOLD_PROMPT = """Invent a fictional UK household of two adults: give a surname (not famous), and a short URL-safe
nickname for the account (letters only, at most 12 characters). Return ONLY JSON: {"surname":str,"nickname":str}."""


def check_payees(slots: list[str]):
    def check(reply: dict[str, Any]) -> str | None:
        got = reply.get("payees")
        if not isinstance(got, list) or sorted(p.get("slot", "") for p in got if isinstance(p, dict)) != sorted(slots):
            return "slots do not match"
        names = set()
        for p in got:
            name, ref = p.get("name"), p.get("reference")
            if not isinstance(name, str) or not name.strip() or len(name) > 28 or is_real(name):
                return f"{p['slot']}: bad or real name {name!r}"
            if name.strip().lower() in names:
                return f"{p['slot']}: repeated name {name!r}"
            names.add(name.strip().lower())
            if not isinstance(ref, str) or not (4 <= len(ref.strip()) <= 16):
                return f"{p['slot']}: reference {ref!r} is not 4-16 characters"
        return None

    return check


def check_household(reply: dict[str, Any]) -> str | None:
    nick = reply.get("nickname")
    if not isinstance(reply.get("surname"), str) or not reply["surname"].strip():
        return "no surname"
    if not isinstance(nick, str) or not nick.isalpha() or not (2 <= len(nick) <= 12):
        return f"nickname {nick!r} is not 2-12 letters"
    return None


def build_names(client: Any, path: Path, seed: int, fresh: bool, label_ok: bool = True) -> dict[str, Any]:
    """Qwen's names for this household, saved after each batch so a stopped run resumes where it stopped."""
    data: dict[str, Any] = {"label": LABEL, "seed": seed, "payees": {}}
    if path.exists() and not fresh:
        data = read_json(path)
    if "household" not in data:
        r = ask_validated(client, HOUSEHOLD_PROMPT, check_household, kind="household", hint={"seed": seed}, seed=seed)
        data["household"] = {"surname": r["surname"].strip(), "nickname": r["nickname"].strip().lower()}
        write_json(path, data)
    used = {p["name"].lower() for p in data["payees"].values()}
    for group, slots in BATCHES.items():
        keys = [s for s, _ in slots]
        if all(k in data["payees"] for k in keys):
            continue
        listing = "\n".join(f"- {s}: {d}" for s, d in slots)

        def check(reply: dict[str, Any], keys: list[str] = keys, used: set[str] = used) -> str | None:
            problem = check_payees(keys)(reply)
            if problem:
                return problem
            clash = [p["name"] for p in reply["payees"] if p["name"].strip().lower() in used]
            return f"name already used in another batch: {clash}" if clash else None

        r = ask_validated(
            client,
            NAMES_PROMPT % (group, listing),
            check,
            kind="payees",
            hint={"slots": keys, "seed": seed},
            seed=seed + len(data["payees"]),
        )
        for p in r["payees"]:
            data["payees"][p["slot"]] = {"name": p["name"].strip(), "reference": p["reference"].strip()}
            used.add(p["name"].strip().lower())
        write_json(path, data)
        print("names:", group, flush=True)
    return data


# ------------------------------------------------------------------------------------------------ the household

# id, slot, category, cadence, method, amount range in pence (fixed per household), day of month (or weekday for
# weekly), first and last month index (0 = April), changes [(month index, "factor"|"add", value)], ref_noise
SERIES: list[dict[str, Any]] = [
    dict(id="salary", slot="employer", cat="income", cadence="monthly", method="faster_payment", amt=(190000, 340000),
         day="last", months=(0, 5), direction="in"),
    dict(id="rent", slot="landlord", cat="rent", cadence="monthly", method="standing_order", amt=(85000, 125000),
         day=1, months=(0, 5)),
    dict(id="council_tax", slot="council", cat="council_tax", cadence="monthly", method="direct_debit",
         amt=(13500, 21000), day=15, months=(0, 5)),
    dict(id="energy", slot="energy", cat="utilities", cadence="monthly", method="direct_debit", amt=(7200, 11800),
         day=12, months=(0, 5), changes=[(3, "factor", 1.09)]),
    dict(id="water", slot="water", cat="utilities", cadence="monthly", method="direct_debit", amt=(2600, 3900),
         day=20, months=(0, 5)),
    dict(id="broadband", slot="broadband", cat="telecoms", cadence="monthly", method="direct_debit",
         amt=(2699, 3999), day=8, months=(0, 5), changes=[(2, "add", 300)]),
    dict(id="mobile_a", slot="mobile_a", cat="telecoms", cadence="monthly", method="direct_debit", amt=(1500, 2800),
         day=5, months=(0, 5)),
    dict(id="mobile_b", slot="mobile_b", cat="telecoms", cadence="monthly", method="direct_debit", amt=(800, 1200),
         day=5, months=(0, 5)),
    dict(id="car_insurance", slot="car_insurance", cat="insurance", cadence="monthly", method="direct_debit",
         amt=(3400, 6200), day=18, months=(0, 5)),
    dict(id="video", slot="video", cat="subscriptions", cadence="monthly", method="card", amt=(799, 1299), day=9,
         months=(0, 5), changes=[(4, "add", 200)]),
    dict(id="music", slot="music", cat="subscriptions", cadence="monthly", method="card", amt=(999, 1299), day=23,
         months=(0, 5), noise=True),
    dict(id="cloud", slot="cloud", cat="subscriptions", cadence="monthly", method="card", amt=(99, 299), day=3,
         months=(0, 5)),
    dict(id="gym", slot="gym", cat="health_fitness", cadence="monthly", method="direct_debit", amt=(2499, 4499),
         day=1, months=(0, 5)),
    dict(id="news", slot="news", cat="subscriptions", cadence="monthly", method="card", amt=(999, 1999), day=14,
         months=(0, 2)),
    dict(id="mealkit", slot="mealkit", cat="subscriptions", cadence="monthly", method="card", amt=(2599, 4299),
         day=27, months=(3, 5)),
    dict(id="charity", slot="charity", cat="charity", cadence="monthly", method="direct_debit", amt=(500, 1500),
         day=28, months=(0, 5)),
    dict(id="savings", slot=None, cat="savings", cadence="monthly", method="internal_transfer", amt=(10000, 30000),
         day=26, months=(0, 5)),
    dict(id="cleaner", slot="cleaner", cat="household_services", cadence="weekly", method="faster_payment",
         amt=(3500, 6000), day=4, months=(0, 5)),  # day = weekday, 4 = Friday
    dict(id="groomer", slot="groomer", cat="pets", cadence="four_weekly", method="card", amt=(3800, 6500), day=0,
         months=(0, 5)),
]  # fmt: skip
# Not recurring bills: paid once or twice in the window, or varying and irregular.
ONE_OFFS: list[dict[str, Any]] = [
    dict(id="travel_insurance_annual", slot="travel_insurance", cat="insurance", method="direct_debit",
         amt=(9000, 16000), months=[1], reason="annual policy: paid once in the six months"),
    dict(id="drainage_quarterly", slot="water_sewer", cat="utilities", method="direct_debit", amt=(4200, 6800),
         months=[0, 3], reason="quarterly: only two payments in the six months, fewer than three"),
    dict(id="freelance_income", slot="client", cat="income", method="faster_payment", amt=(25000, 90000),
         months=[1, 4], reason="occasional freelance income: two irregular payments of different amounts",
         direction="in"),
]  # fmt: skip
# Varying spend: (id, slot, category, method, visits per month, amount range in pence). Often at the same payee but
# with different amounts and irregular dates, so never a recurring bill.
VARIABLE: list[dict[str, Any]] = [
    dict(id="super_a", slot="super_a", cat="groceries", method="card", per_month=(5, 8), amt=(1250, 11800)),
    dict(id="super_b", slot="super_b", cat="groceries", method="card", per_month=(3, 6), amt=(900, 7400)),
    dict(id="corner", slot="corner", cat="groceries", method="card", per_month=(3, 7), amt=(180, 1650)),
    dict(id="coffee", slot="coffee", cat="eating_out", method="card", per_month=(6, 11), amt=(280, 790)),
    dict(id="takeaway", slot="takeaway", cat="eating_out", method="card", per_month=(2, 4), amt=(1450, 3600)),
    dict(id="restaurant", slot="restaurant", cat="eating_out", method="card", per_month=(1, 2), amt=(3200, 9500)),
    dict(id="pub", slot="pub", cat="eating_out", method="card", per_month=(2, 4), amt=(1100, 4800)),
    dict(id="fuel_a", slot="fuel_a", cat="transport", method="card", per_month=(2, 4), amt=(3500, 7200)),
    dict(id="fuel_b", slot="fuel_b", cat="transport", method="card", per_month=(0, 2), amt=(3000, 6500)),
    dict(id="rail", slot="rail", cat="transport", method="card", per_month=(1, 3), amt=(1250, 8900)),
    dict(id="taxi", slot="taxi", cat="transport", method="card", per_month=(0, 2), amt=(900, 2800)),
    dict(id="carpark", slot="carpark", cat="transport", method="card", per_month=(1, 3), amt=(250, 1450)),
    dict(id="bus", slot="bus", cat="transport", method="card", per_month=(0, 3), amt=(220, 640)),
    dict(id="clothes", slot="clothes", cat="shopping", method="card", per_month=(0, 2), amt=(1800, 8900)),
    dict(id="homestore", slot="homestore", cat="shopping", method="card", per_month=(0, 2), amt=(1500, 14000)),
    dict(id="pharmacy", slot="pharmacy", cat="health_fitness", method="card", per_month=(0, 2), amt=(350, 2400)),
    dict(id="books", slot="books", cat="shopping", method="card", per_month=(0, 1), amt=(700, 2200)),
    dict(id="garden", slot="garden", cat="shopping", method="card", per_month=(0, 1), amt=(1200, 6500)),
    dict(id="online", slot="online", cat="shopping", method="card", per_month=(1, 3), amt=(800, 9900)),
]  # fmt: skip
CATEGORY_TYPE = {"income": "income", "savings": "transfer"}
TYPE_NAMES = {
    "direct_debit": "DIRECT DEBIT",
    "standing_order": "STANDING ORDER",
    "faster_payment": "FASTER PAYMENT",
    "card": "CARD PAYMENT",
    "internal_transfer": "INTERNAL TRANSFER",
}


def next_working_day(d: date) -> date:
    while d.weekday() >= 5 or d in BANK_HOLIDAYS:
        d += timedelta(days=1)
    return d


def month_bounds(mi: int) -> tuple[date, date]:
    first = date(2026, 4 + mi, 1)
    last = (date(2026, 5 + mi, 1) if 4 + mi < 12 else date(2027, 1, 1)) - timedelta(days=1)
    return first, last


def series_dates(spec: dict[str, Any], mi_from: int, mi_to: int) -> list[date]:
    out: list[date] = []
    if spec["cadence"] == "monthly":
        for mi in range(mi_from, mi_to + 1):
            first, last = month_bounds(mi)
            if spec["day"] == "last":
                d = last
                while d.weekday() >= 5 or d in BANK_HOLIDAYS:
                    d -= timedelta(days=1)  # salary arrives the working day before
            else:
                d = first + timedelta(days=spec["day"] - 1)
                if spec["method"] in ("direct_debit", "standing_order", "internal_transfer"):
                    d = next_working_day(d)
            out.append(d)
        return out
    step = 7 if spec["cadence"] == "weekly" else 28
    first, _ = month_bounds(mi_from)
    d = first
    if spec["cadence"] == "weekly":
        while d.weekday() != spec["day"]:
            d += timedelta(days=1)
    else:
        d += timedelta(days=9)  # an arbitrary but fixed first visit
    last = month_bounds(mi_to)[1]
    while d <= last:
        out.append(d)
        d += timedelta(days=step)
    return out


def apply_changes(spec: dict[str, Any], base: int, when: date) -> int:
    amount = base
    for mi, kind, value in spec.get("changes", []):
        if (when.year - 2026) * 12 + when.month - 4 >= mi:
            amount = round(base * value) if kind == "factor" else base + value
    return amount


def card_text(text: str, rng: random.Random) -> str:
    return f"{text} {rng.choice(CITIES)}"


def simulate(names: dict[str, Any], seed: int) -> dict[str, Any]:
    """Every transaction of the six months and the truth about it. Pure code, seeded; Qwen's names only label it."""
    rng = random.Random(f"{seed}-household")
    payees = names["payees"]
    tx: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    not_recurring: list[dict[str, Any]] = []

    def payee(slot: str | None) -> dict[str, str]:
        if slot is None:
            return {"name": "Savings pot", "reference": "Monthly saving"}
        return payees[slot]

    def add(when: date, slot: str | None, cat: str, method: str, amount: int, series_id: str | None, text: str) -> None:
        p = payee(slot)
        direction = -1 if CATEGORY_TYPE.get(cat) != "income" else 1
        tx.append(
            {
                "date": when,
                "slot": slot,
                "payee": p["name"],
                "text": text,
                "reference": p["reference"],
                "method": method,
                "category": cat,
                "amount_pence": direction * amount,
                "series": series_id,
            }
        )

    for spec in SERIES:
        base = rng.randint(*spec["amt"])
        if spec["cadence"] == "monthly" and spec["id"] != "salary":
            base = base // 100 * 100 + rng.choice((0, 0, 49, 99)) if spec["amt"][1] > 5000 else base
        dates = series_dates(spec, *spec["months"])
        amounts, dts = [], []
        for d in dates:
            amount = apply_changes(spec, base, d)
            slot = spec["slot"]
            name = payee(slot)["name"].upper()[:24]
            text = f"{name}*{rng.randint(10000, 99999)}" if spec.get("noise") else name
            add(d, slot, spec["cat"], spec["method"], amount, spec["id"], text)
            amounts.append(amount)
            dts.append(d)
        series.append(
            {
                "id": spec["id"],
                "payee": payee(spec["slot"])["name"],
                "category": spec["cat"],
                "cadence": spec["cadence"],
                "method": spec["method"],
                "direction": spec.get("direction", "out"),
                "count": len(dts),
                "first_date": dts[0].isoformat(),
                "last_date": dts[-1].isoformat(),
                "dates": [d.isoformat() for d in dts],
                "amounts_pence": amounts,
                "amount_changes": [
                    {"from_date": d.isoformat(), "old_pence": o, "new_pence": n}
                    for d, o, n in zip(dts[1:], amounts, amounts[1:], strict=False)
                    if n != o
                ],
                "reference_varies": bool(spec.get("noise")),
                "is_bill": spec["cat"] in ("rent", "council_tax", "utilities", "telecoms", "insurance"),
                "is_subscription": spec["cat"] in ("subscriptions", "health_fitness", "charity"),
                "ended_early": spec["months"][1] < 5,
                "started_late": spec["months"][0] > 0,
            }
        )
    for spec in ONE_OFFS:
        dates = []
        for mi in spec["months"]:
            first, last = month_bounds(mi)
            d = first + timedelta(days=rng.randint(2, (last - first).days - 3))
            d = next_working_day(d)
            dates.append(d)
            add(
                d,
                spec["slot"],
                spec["cat"],
                spec["method"],
                rng.randint(*spec["amt"]),
                None,
                payee(spec["slot"])["name"].upper()[:24],
            )
        not_recurring.append(
            {"id": spec["id"], "payee": payee(spec["slot"])["name"], "category": spec["cat"], "reason": spec["reason"],
             "count": len(dates)}
        )  # fmt: skip
    for spec in VARIABLE:
        n_total = 0
        for mi in range(6):
            first, last = month_bounds(mi)
            for _ in range(rng.randint(*spec["per_month"])):
                d = first + timedelta(days=rng.randint(0, (last - first).days))
                amount = rng.randint(*spec["amt"])
                name = payee(spec["slot"])["name"].upper()[:20]
                add(d, spec["slot"], spec["cat"], "card", amount, None, card_text(name, rng))
                n_total += 1
        if n_total:
            not_recurring.append(
                {
                    "id": spec["id"],
                    "payee": payee(spec["slot"])["name"],
                    "category": spec["cat"],
                    "reason": "varying amounts on irregular dates: spending, not a recurring bill",
                    "count": n_total,
                }
            )
    tx.sort(key=lambda t: (t["date"], t["series"] or "z", t["payee"], t["amount_pence"]))
    return {"tx": tx, "series": series, "not_recurring": not_recurring}


def with_balances(tx: list[dict[str, Any]], rng: random.Random) -> tuple[int, int]:
    """Opening balance chosen so the account never dips below £150; running balance filled in. Returns (open, close)."""
    run, low = 0, 0
    for t in tx:
        run += t["amount_pence"]
        low = min(low, run)
    opening = max(50000, -low + 15000 + rng.randint(0, 40000))
    opening = opening // 100 * 100 + rng.choice((0, 37, 62))
    bal = opening
    for t in tx:
        bal += t["amount_pence"]
        t["balance_pence"] = bal
    return opening, bal


def expectations(
    world: dict[str, Any], names: dict[str, Any], layout: str, opening: int, closing: int
) -> dict[str, Any]:
    tx = world["tx"]
    totals: dict[str, dict[str, Any]] = {}
    for t in tx:
        c = totals.setdefault(
            t["category"],
            {"type": CATEGORY_TYPE.get(t["category"], "spending"), "total_pence": 0, "by_month": {}, "count": 0},
        )
        c["total_pence"] += abs(t["amount_pence"])
        c["count"] += 1
        key = t["date"].strftime("%Y-%m")
        c["by_month"][key] = c["by_month"].get(key, 0) + abs(t["amount_pence"])
    spending = sum(c["total_pence"] for c in totals.values() if c["type"] == "spending")
    income = sum(c["total_pence"] for c in totals.values() if c["type"] == "income")
    savings = sum(c["total_pence"] for c in totals.values() if c["type"] == "transfer")
    committed = sum(
        s["amounts_pence"][-1] for s in world["series"] if s["cadence"] == "monthly" and s["direction"] == "out"
        and s["category"] != "savings" and not s["ended_early"]
    )  # fmt: skip
    return {
        "label": LABEL,
        "household": names["household"],
        "layout": layout,
        "period": {"from": START.isoformat(), "to": END.isoformat()},
        "opening_balance_pence": opening,
        "closing_balance_pence": closing,
        "rule": "a recurring series is one payee with 3 or more payments at a fixed cadence (monthly on the same "
        "day, moved to the next working day for direct debits and standing orders; weekly; every 28 days). "
        "A price rise inside a series keeps it one series. Variable spending and fewer than 3 payments are "
        "not recurring.",
        "recurring": world["series"],
        "not_recurring": world["not_recurring"],
        "monthly_committed_outgoings_pence": committed,
        "committed_note": "sum of the latest amount of every monthly outgoing series still running in September, "
        "savings transfer excluded",
        "totals": {
            "income_pence": income,
            "spending_pence": spending,
            "savings_transfers_pence": savings,
            "net_change_pence": closing - opening,
        },
        "categories": dict(sorted(totals.items())),
        "rows": [
            {
                "row": i,
                "date": t["date"].isoformat(),
                "payee": t["payee"],
                "amount_pence": t["amount_pence"],
                "balance_pence": t["balance_pence"],
                "category": t["category"],
                "recurring_id": t["series"],
            }
            for i, t in enumerate(tx, start=1)
        ],
    }


# ------------------------------------------------------------------------------------------------ CSV layouts


TIDE_HEADER = ["Transaction ID", "Transaction Date", "Transaction Type", "Transaction Information", "Paid In",
               "Paid Out", "Balance"]  # fmt: skip
TIDE_KIND = {
    "card": "Card Transaction",
    "direct_debit": "Direct Debit",
    "standing_order": "Standing Order",
    "faster_payment": "Faster Payment",
    "internal_transfer": "Domestic Transfer",
}
BARCLAYS_SUB = {
    "card": "PAYMENT",
    "direct_debit": "DIRECTDEBIT",
    "standing_order": "STANDINGORDER",
    "faster_payment": "FP",
    "internal_transfer": "TRANSFER",
}


def money(p: int) -> str:
    return f"{abs(p) / 100:.2f}"


def write_csv(tx: list[dict[str, Any]], layout: str, opening: int, rng: random.Random) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([LABEL])  # a preamble row: the bank importer skips everything above the header
    if layout == "starling":
        w.writerow(["Date", "Counter Party", "Reference", "Type", "Amount (GBP)", "Balance (GBP)", "Spending Category"])
        for t in tx:
            ref = (
                f"Card payment {t['date']:%d %b} ****{rng.randint(1000, 9999)}".upper()
                if t["method"] == "card"
                else f"{t['reference']}"
            )
            cp = t["text"].title() if t["method"] == "card" else t["payee"]
            amount, balance = f"{t['amount_pence'] / 100:.2f}", f"{t['balance_pence'] / 100:.2f}"
            w.writerow([f"{t['date']:%d/%m/%Y}", cp, ref, TYPE_NAMES[t["method"]], amount, balance, "GENERAL"])
    elif layout == "tide":
        w.writerow(TIDE_HEADER)
        for t in tx:
            info = t["text"] if t["method"] == "card" else f"{t['payee'].upper()} {t['reference']}".strip()
            inn, out = (money(t["amount_pence"]), "") if t["amount_pence"] > 0 else ("", money(t["amount_pence"]))
            tid = f"TD{rng.randint(10**9, 10**10 - 1)}"
            w.writerow(
                [tid, t["date"].isoformat(), TIDE_KIND[t["method"]], info, inn, out, f"{t['balance_pence'] / 100:.2f}"]
            )
    elif layout == "barclays":
        w.writerow(["Number", "Date", "Account", "Amount", "Subcategory", "Memo"])
        for i, t in enumerate(tx, start=1):
            memo = t["text"] if t["method"] == "card" else f"{t['payee'].upper()} {t['reference']}"
            amount = f"{t['amount_pence'] / 100:.2f}"
            w.writerow([i, f"{t['date']:%d/%m/%Y}", "20-45-31 40291178", amount, BARCLAYS_SUB[t["method"]], memo])
    else:
        raise SystemExit(f"unknown layout {layout!r}")
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ stub


def stub_handlers() -> dict[str, Any]:
    def household(h: dict[str, Any]) -> dict[str, Any]:
        return {
            "surname": ["Ashdown", "Pemberley", "Corrigan", "Wetherby"][h["seed"] % 4],
            "nickname": f"hh{'abcdef'[h['seed'] % 6]}",
        }

    def payees(h: dict[str, Any]) -> dict[str, Any]:
        adj = ["Marlowe", "Kettering", "Larkfield", "Oakhaven", "Brindle", "Thistledown", "Wrenford", "Calder"]
        out = []
        for i, slot in enumerate(h["slots"]):
            name = f"{adj[(i + h['seed']) % 8]} {slot.replace('_', ' ').title()} {i + 1}"[:28]
            out.append({"slot": slot, "name": name, "reference": f"{slot[:3].upper()}-{4400 + i * 7}"})
        return {"payees": out}

    return {"household": household, "payees": payees}


# ------------------------------------------------------------------------------------------------ main


def make_household(client: Any, out: Path, seed: int, layout: str, fresh: bool, dry: bool) -> dict[str, Any]:
    """Names (Qwen) then everything else (code). Returns the pieces to write."""
    if dry:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            names = build_names(client, Path(tmp) / "names.json", seed, True)
    else:
        names = build_names(client, out / "names.json", seed, fresh)
    world = simulate(names, seed)
    rng = random.Random(f"{seed}-csv")
    opening, closing = with_balances(world["tx"], rng)
    exp = expectations(world, names, layout, opening, closing)
    csv_text = write_csv(world["tx"], layout, opening, rng)
    return {"names": names, "world": world, "exp": exp, "csv": csv_text}


def write_household(h: dict[str, Any], out: Path) -> None:
    write_text(out / "statement.csv", h["csv"])
    write_json(out / "expectations.json", h["exp"])
    write_json(out / "names.json", h["names"])
    exp = h["exp"]
    write_text(
        out / "README.md",
        f"""# Personal statement gold: the {exp["household"]["surname"]} household

Fictional household ({LABEL}), six months of a current account in the {exp["layout"]} export layout. The first line
of `statement.csv` is the label (a preamble row the bank importer skips). `expectations.json` lists the recurring
series (dates, amounts, price rises), what must not be flagged, the monthly committed total, totals per category
and month, and the category of every row. Made by `evals/gold/gen_personal.py`: Qwen names the payees; code sets
every amount, date and recurrence.
""",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--households", type=int, default=2, help="how many different households (default 2)")
    ap.add_argument("--layout", choices=("starling", "tide", "barclays"), default="starling")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry-run", action="store_true", help="stub Qwen, build and check everything, write nothing")
    ap.add_argument("--stub", action="store_true", help="stub Qwen but write files (offline runs, tests)")
    ap.add_argument("--fresh", action="store_true", help="ignore saved names and start over")
    args = ap.parse_args()
    client = StubQwen(stub_handlers()) if (args.dry_run or args.stub) else Qwen()
    t0 = time.time()
    for i in range(args.households):
        seed = args.seed + i
        done = sorted(args.out.glob(f"{seed:02d}_*/statement.csv")) if args.out.exists() else []
        if done and not args.fresh and not args.dry_run:
            print(f"household {seed}: {done[0].parent.name} already written, skipped")
            continue
        pending = args.out / f"_pending_{seed}"  # names.json lives here until the household has its nickname
        try:
            h = make_household(client, pending, seed, args.layout, args.fresh, args.dry_run)
        except QwenError as exc:
            raise SystemExit(f"Qwen step failed, run again to resume: {exc}") from exc
        exp = h["exp"]
        print(
            f"household {exp['household']['surname']}: {len(exp['rows'])} rows, "
            f"{len(exp['recurring'])} recurring series, {len(exp['not_recurring'])} not-recurring payees, "
            f"committed £{exp['monthly_committed_outgoings_pence'] / 100:,.2f}/month"
        )
        if args.dry_run:
            continue
        write_household(h, args.out / f"{seed:02d}_{exp['household']['nickname']}")
        (pending / "names.json").unlink(missing_ok=True)
        pending.rmdir()
    print(
        ("dry run: nothing written. " if args.dry_run else "DONE ")
        + f"{time.time() - t0:.0f}s, Qwen calls {client.calls}"
    )


if __name__ == "__main__":
    main()
