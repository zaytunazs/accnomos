"""The personal demo: a fictional household's books for the demo sandbox (app/demo.py), next to the company demo.

Everything here is made up and labelled so: the household is "The Patel household (fictional)" (the name every page
shows), the demo bar says "SAMPLE — FICTIONAL HOUSEHOLD", and no line names a real person. The books are personal
(`_System/profile.json` kind "personal"), so the app shows its household pages (no VAT, invoices or payroll).

What is written, all by code and in a few seconds (no model calls):
* bank lines from 1 January last year to `day`: salary, rent, council tax, energy, broadband, phone, groceries,
  coffee (rising this year), takeaways, travel, subscriptions, the gym, a monthly school-fees saving transfer and the
  odd one-off;
* the default household categories plus "Coffee & snacks", the starter merchant rules and a few of its own, and a
  monthly budget per category;
* five goals (app/goals.py) whose figures give a mix of statuses on any day: a school-fees pot behind its pace, a
  holiday pot a little behind, a rainy-day fund on pace, coffee spending against last year (well over), and
  groceries this month (usually on pace).

The same plan for the same `day`: amounts vary by month from a fixed seed, never by run.
"""

from __future__ import annotations

import calendar
import random
from datetime import date, timedelta

from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.base import StorageProvider
from app import goals as gm
from app import personal as pf
from app import profile as profile_mod
from app.bank_rules import BankRuleMatch
from app.books import Books

HOUSEHOLD = "The Patel household (fictional)"
LABEL = "SAMPLE — FICTIONAL HOUSEHOLD"
USER = "demo@accnomos.example"
STATEMENT = "SAMPLE-FICTIONAL-household-statement.csv"
COFFEE = "Coffee & snacks"

# (contains, category id) after the starter merchants; "coffee" is the id save_categories gives COFFEE.
EXTRA_RULES: list[tuple[str, str]] = [
    ("costa", "coffee_snacks"),
    ("pret a manger", "coffee_snacks"),
    ("caffe nero", "coffee_snacks"),
    ("starbucks", "coffee_snacks"),
    ("rent ", "housing"),
    ("puregym", "health"),
    ("vodafone", "utilities"),
    ("bt broadband", "utilities"),
    ("school fees saver", "savings"),
    ("holiday saver", "savings"),
]
BUDGETS = {  # pence a month
    "housing": 145_000,
    "utilities": 26_000,
    "groceries": 38_000,
    "transport": 16_000,
    "eating_out": 12_000,
    "coffee_snacks": 4_000,
    "subscriptions": 3_500,
    "health": 4_000,
}


def _month_days(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _on(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, _month_days(year, month)))


def plan_lines(day: date) -> list[tuple[date, str, int]]:
    """(date, description, pence) from 1 January last year up to and including `day`, oldest first."""
    rows: list[tuple[date, str, int]] = []
    y, m = day.year - 1, 1
    while (y, m) <= (day.year, day.month):
        rnd = random.Random(y * 100 + m)
        this_year = y == day.year
        fixed = [
            (1, "RENT HARBOUR LETTINGS", -142_500),
            (1, "SALARY NORTHFIELD SCHOOLS TRUST", 268_400),
            (3, "COUNCIL TAX LAMBETH", -16_900),
            (5, "OCTOPUS ENERGY", -(9_800 if m in (11, 12, 1, 2, 3) else 6_200)),
            (8, "BT BROADBAND", -3_800),
            (9, "VODAFONE MOBILE", -2_200),
            (12, "NETFLIX.COM", -1_099),
            (14, "SPOTIFY P1234", -1_199),
            (15, "PUREGYM MONTHLY", -2_499),
            (16, "SALARY FREELANCE TUTORING", 42_000 + rnd.randrange(0, 20_000, 500)),
            (20, "SCHOOL FEES SAVER TRANSFER", -10_000),
            (25, "HOLIDAY SAVER TRANSFER", -7_500),
        ]
        for d, desc, pence in fixed:
            rows.append((_on(y, m, d), desc, pence))
        # Groceries: a weekly shop and a top-up, about £300-£340 a month.
        for d in (2, 9, 16, 23, 30):
            if d <= _month_days(y, m):
                shop = rnd.choice(["TESCO STORES 2231", "SAINSBURYS S/MKT", "ALDI STORES"])
                rows.append((_on(y, m, d), shop, -(5_200 + rnd.randrange(0, 1_600, 10))))
        for d in (6, 19):
            rows.append((_on(y, m, d), "TESCO EXPRESS", -(1_100 + rnd.randrange(0, 900, 10))))
        # Coffee: a few a month last year, more this year, more again since the summer.
        cups = (5 + rnd.randrange(0, 3)) if not this_year else (9 if m <= 6 else 15) + rnd.randrange(0, 3)
        for i in range(cups):
            d = 1 + (i * 29) // max(1, cups)
            shop = ["COSTA COFFEE", "PRET A MANGER", "CAFFE NERO", "STARBUCKS"][i % 4]
            rows.append((_on(y, m, d), f"{shop} {d:02d}", -(325 + rnd.randrange(0, 150, 5))))
        # Takeaways and travel.
        for d in (7, 21) if not this_year else (4, 13, 27):
            rows.append((_on(y, m, d), rnd.choice(["DELIVEROO", "JUST EAT"]), -(1_800 + rnd.randrange(0, 1_400, 10))))
        for d in (2, 10, 17, 24):
            rows.append((_on(y, m, d), "TFL TRAVEL CHARGE", -(620 + rnd.randrange(0, 600, 10))))
        # The odd one-off.
        if m in (3, 8):
            rows.append((_on(y, m, 18), "BOOTS PHARMACY", -(1_450 + rnd.randrange(0, 900, 10))))
        if m == 12:
            rows.append((_on(y, m, 12), "JOHN LEWIS GIFTS", -18_500))
        if m == 9:
            rows.append((_on(y, m, 4), "SCHOOL UNIFORM SHOP", -9_650))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return sorted((r for r in rows if r[0] <= day), key=lambda r: r[0])


def statement_csv(rows: list[tuple[date, str, int]]) -> bytes:
    balance = 250_000
    out = ["Date,Description,Amount,Balance"]
    for d, desc, pence in rows:
        balance += pence
        out.append(f"{d:%d/%m/%Y},{desc},{pence / 100:.2f},{balance / 100:.2f}")
    return ("\r\n".join(out) + "\r\n").encode()


def _share(start: date, end: date, day: date) -> float:
    return max(0.0, min(1.0, ((min(day, end) - start).days + 1) / ((end - start).days + 1)))


def goal_plan(day: date) -> list[gm.GoalIn]:
    """Five household goals, with hand-recorded amounts set against today's pace so the statuses are mixed."""
    sept = date(day.year if day.month >= 9 else day.year - 1, 9, 1)
    fees_end = date(sept.year + 1, 8, 31)
    # The school-fees pot is what the monthly "SCHOOL FEES SAVER TRANSFER" lines have put aside since September
    # (£100 a month, as the statement shows), against a £2,000 target: behind its pace, so off track.
    fees_target = 200_000
    fees_saved = -sum(p for d, desc, p in plan_lines(day) if desc.startswith("SCHOOL FEES SAVER") and d >= sept)
    hol_start = date(day.year, 1, 1)
    hol_end = date(day.year + 1, 6, 30)
    hol_target = 180_000
    hol_saved = int(hol_target * _share(hol_start, hol_end, day) * 0.85) // 500 * 500  # a little behind: at risk
    month_start = day.replace(day=1)
    month_end = _on(day.year, day.month, 31)
    return [
        gm.GoalIn(
            name="School fees",
            kind="save",
            start=sept,
            end=fees_end,
            target_pence=fees_target,
            saved_pence=fees_saved,
            note="£100 a month into the school-fees saver, for the school trip and next year's fees.",
        ),
        gm.GoalIn(
            name="Summer holiday pot",
            kind="save",
            start=hol_start,
            end=hol_end,
            target_pence=hol_target,
            saved_pence=hol_saved,
        ),
        gm.GoalIn(
            name="Rainy-day fund",
            kind="save",
            start=date(day.year, 1, 1),
            end=date(day.year, 12, 31),
            target_pence=200_000,
            saved_pence=min(200_000, int(200_000 * _share(date(day.year, 1, 1), date(day.year, 12, 31), day) * 1.05)),
        ),
        gm.GoalIn(
            name="Spend less on coffee",
            kind="spend_less",
            start=date(day.year, 1, 1),
            end=date(day.year, 12, 31),
            percent=30,
            focus=COFFEE,
        ),
        gm.GoalIn(
            name="Groceries under £350 this month",
            kind="spend_cap",
            start=month_start,
            end=month_end,
            target_pence=35_000,
            focus="Groceries",
        ),
    ]


async def seed(storage: StorageProvider, day: date) -> None:
    books = Books(storage)
    await books.write_json(
        profile_mod.PROFILE,
        {"name": HOUSEHOLD, "kind": "personal", "settings": {}, "linked": [], "updated_at": f"{day}T08:00:00+00:00"},
    )
    await books.import_bank_csv(statement_csv(plan_lines(day)), STATEMENT, USER)
    cats = await pf.load_categories(books)
    body = pf.CategoriesIn(
        categories=[pf.CategoryIn(id=c.id, name=c.name) for c in cats if c.id != pf.OTHER]
        + [pf.CategoryIn(name=COFFEE)]
        + [pf.CategoryIn(id=c.id, name=c.name) for c in cats if c.id == pf.OTHER]
    )
    cats = await pf.save_categories(books, body, USER)
    coffee_id = next(c.id for c in cats if c.name == COFFEE)
    await pf.add_starter_rules(books, USER)
    for value, cat in EXTRA_RULES:
        cid = coffee_id if cat == "coffee_snacks" else cat
        await pf.add_rule(
            books,
            pf.PersonalRuleIn(
                name=value.strip().title(), match=BankRuleMatch(op="contains", value=value), category_id=cid
            ),
            USER,
        )
    budgets = {(coffee_id if k == "coffee_snacks" else k): v for k, v in BUDGETS.items()}
    await pf.save_budgets(books, pf.BudgetsIn(budgets=budgets), USER)
    for g in goal_plan(day):
        await gm.add_goal(books, g, USER, "personal")


def receipt_docs(day: date) -> list[dict]:
    """Two household receipts that arrived in the last couple of days and wait in Review (gold readings, no model):
    a supermarket shop with its items and a chemist's receipt. Fictional, and labelled so on the printed text."""
    shop_day, chem_day = day - timedelta(days=2), day - timedelta(days=1)
    items = [
        ("Semi-skimmed milk 4 pints", 1.55),
        ("Wholemeal bread", 1.40),
        ("Free-range eggs x12", 3.10),
        ("Bananas", 0.95),
        ("Ground coffee 227g", 4.50),
        ("Pasta 500g", 0.85),
        ("Cheddar 400g", 3.75),
    ]
    shop_total = round(sum(p for _n, p in items), 2)
    return [
        {
            "gold": "household tesco receipt",
            "date": shop_day,
            "file_name": f"SAMPLE {shop_day.isoformat()} Tesco receipt.png",
            "text": "TESCO STORES 2231\n"
            + "\n".join(f"{n}  £{p:.2f}" for n, p in items)
            + f"\nTOTAL  £{shop_total:.2f}\nCARD ****4417\n\nSAMPLE — FICTIONAL HOUSEHOLD",
            "extracted": {
                "doc_type": "receipt",
                "supplier_name": "Tesco Stores",
                "supplier_vat_number": None,
                "customer_name": None,
                "invoice_number": None,
                "date": shop_day.isoformat(),
                "currency": "GBP",
                "lines": [
                    {"description": n, "qty": 1, "unit_price": p, "net": p, "vat_rate": 0, "vat": 0.0} for n, p in items
                ],
                "net_total": shop_total,
                "vat_total": 0.0,
                "gross_total": shop_total,
                "payment_method": "card",
                "card_last4": "4417",
                "category_guess": "Sundry",
                "confidence": 0.97,
            },
        },
        {
            "gold": "household boots receipt",
            "date": chem_day,
            "file_name": f"SAMPLE {chem_day.isoformat()} Boots receipt.png",
            "text": "BOOTS PHARMACY\nHay fever tablets 30  £4.29\nPlasters assorted  £2.50\nTOTAL  £6.79\nCASH\n\n"
            "SAMPLE — FICTIONAL HOUSEHOLD",
            "extracted": {
                "doc_type": "receipt",
                "supplier_name": "Boots",
                "supplier_vat_number": None,
                "customer_name": None,
                "invoice_number": None,
                "date": chem_day.isoformat(),
                "currency": "GBP",
                "lines": [
                    {
                        "description": "Hay fever tablets 30",
                        "qty": 1,
                        "unit_price": 4.29,
                        "net": 4.29,
                        "vat_rate": 0,
                        "vat": 0.0,
                    },
                    {
                        "description": "Plasters assorted",
                        "qty": 1,
                        "unit_price": 2.50,
                        "net": 2.50,
                        "vat_rate": 0,
                        "vat": 0.0,
                    },
                ],
                "net_total": 6.79,
                "vat_total": 0.0,
                "gross_total": 6.79,
                "payment_method": "cash",
                "card_last4": None,
                "category_guess": "Sundry",
                "confidence": 0.95,
            },
        },
    ]


async def seed_receipts(storage: StorageProvider, day: date) -> int:
    """Put the receipts in Review the way the company demo's pre-read inbox documents are (tools/seed_demo.py
    `_propose`: the scan's own checks, the gold reading standing in for the model's)."""
    from types import SimpleNamespace

    from app import sample_books

    seed_mod = sample_books.seed_module()
    books = seed_mod.SeedBooks(storage)
    plan = SimpleNamespace(business=HOUSEHOLD, current=(day.replace(day=1), day))
    n = 0
    for r in receipt_docs(day):
        d = seed_mod.PlannedDoc(
            gold=r["gold"], date=r["date"], text=r["text"], extracted=r["extracted"], file_name=r["file_name"]
        )
        await seed_mod._propose(books, d, plan)  # noqa: SLF001 - the demo seed's own proposal path
        n += 1
    return n


async def build_storage(day: date) -> FakeStorageProvider:
    st = FakeStorageProvider()
    await seed(st, day)
    await seed_receipts(st, day)
    return st


# --------------------------------------------------------------------------- #
# The company demo's goals (added after tools/seed_demo.py's plan, from what those books contain)
# --------------------------------------------------------------------------- #


async def add_company_goals(storage: StorageProvider, day: date, user: str = USER) -> list[gm.Goal]:
    """Three business goals for the company demo, sized from its own books so one is on track, one at risk and one
    off track: this month's sales, spending in its most used purchase category this month, and a VAT pot."""
    books = Books(storage)
    month_start = day.replace(day=1)
    month_end = _on(day.year, day.month, 31)
    share = _share(month_start, month_end, day)
    probe = [
        gm.Goal(name="probe", kind="earn", start=day - timedelta(days=400), end=day, target_pence=1),
    ]
    data = await gm.load_data(books, probe, False, day)

    sales = data.income(month_start, day)
    last_month_end = month_start - timedelta(days=1)
    last_sales = data.income(last_month_end.replace(day=1), last_month_end)
    # At risk: the target is the pace that puts this month's sales at about 85% of plan.
    target = int(sales / (share * 0.85)) if sales > 0 else max(last_sales, 1_000_000)
    target = max(100_000, -(-target // 10_000) * 10_000)

    recent = [p for p in data.purchases if p.date >= day - timedelta(days=90) and p.net_pence > 0]
    counts: dict[str, int] = {}
    for p in recent:
        counts[p.category] = counts.get(p.category, 0) + 1
    category = max(counts, key=lambda k: counts[k]) if counts else None
    spent = data.spent(month_start, day, category) if category else 0
    # On track: comfortably above the pace this month's spending is on.
    cap = max(20_000, -(-int(max(spent, 1) / share * 1.4) // 5_000) * 5_000)

    q_start = date(day.year, ((day.month - 1) // 3) * 3 + 1, 1)
    # The quarter's return and payment are due a month and seven days after it ends.
    vat_end = _on(q_start.year, q_start.month + 2, 31) + timedelta(days=37)
    vat_target = 450_000
    vat_saved = int(vat_target * _share(q_start, vat_end, day) * 0.5) // 1_000 * 1_000  # off track

    plan = [
        gm.GoalIn(
            name=f"{day:%B} sales",
            kind="earn",
            start=month_start,
            end=month_end,
            target_pence=target,
        ),
        gm.GoalIn(
            name=f"Keep {category.lower() if category else 'spending'} in budget",
            kind="spend_cap",
            start=month_start,
            end=month_end,
            target_pence=cap,
            focus=category,
        ),
        gm.GoalIn(
            name="Put aside for the VAT bill",
            kind="save",
            start=q_start,
            end=vat_end,
            target_pence=vat_target,
            saved_pence=vat_saved,
        ),
    ]
    return [await gm.add_goal(books, g, user, "business") for g in plan]
