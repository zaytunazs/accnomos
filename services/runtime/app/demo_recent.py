"""The company demo's recent trading: a few sales and purchases dated from the start of the current VAT period up to
the demo's own "today", so Ask's "profit yesterday", "this week" and "this quarter" have real figures, and the
"Kitchen fit-out, Harrogate" job has purchases with item lines ("what did we order for the kitchen job?"); that
job is open again for its follow-on work, so hours can be logged on it.

Every date is relative to the session's day (built once a day, like the rest of the demo), and nothing is ever dated
before the current VAT period starts, so the two complete periods the seed fills (and the Jul–Sep return the HMRC
sandbox demo files) never change. Documents go through the same path as the seed's own: uploaded, proposed with the
"perfect reading", approved by the demo user; each sale is then paid in full (Record payment), so the amounts owed to
the business stay as the seed left them. Labelled "SAMPLE — FICTIONAL COMPANY" like every other demo document.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from types import ModuleType
from typing import Any

from accnomos_connectors import FakeStorageProvider


@dataclass(frozen=True)
class Item:
    description: str
    qty: float
    unit_price: float  # pounds, before VAT (20%)


@dataclass(frozen=True)
class Recent:
    key: str
    days_ago: int
    kind: str  # "sale" | "purchase"
    party: str  # the customer (sale) or supplier (purchase)
    vat_number: str | None
    items: tuple[Item, ...]
    category: str = "Materials"
    job: str | None = None  # the seed's job key ("job1": Kitchen fit-out, Harrogate)
    number: str | None = None


RECENT: tuple[Recent, ...] = (
    Recent("r01", 20, "purchase", "Northern Workwear Ltd", "GB 284 6531 70",
           (Item("Hi-vis jackets", 4, 9.5), Item("Safety boots", 2, 24.0)), category="Sundry",
           number="NW-77310"),
    Recent("r02", 12, "purchase", "Harrogate Tile & Stone Ltd", "GB 318 2290 46",
           (Item("Matt white metro tiles 300×100, 8 m²", 8, 24.5), Item("Flexible tile adhesive 20 kg", 2, 18.5),
            Item("Grout, white 5 kg", 1, 9.8)), job="job1", number="HTS-10482"),
    Recent("r03", 10, "sale", "Halloway & Sons Interiors", None,
           (Item("Kitchen fit-out, Harrogate: second fix, tiling and worktops", 1, 2400.0),), category="Sales",
           number="BRW-2026-1101"),
    Recent("r04", 8, "purchase", "Yorkshire Timber Merchants Ltd", "GB 402 7718 25",
           (Item("Oak worktop 3 m", 1, 289.0), Item("Worktop oil 1 litre", 1, 16.5)), job="job1",
           number="YTM-55021"),
    Recent("r05", 1, "purchase", "Ironmongery Direct Supplies Ltd", "GB 517 3306 92",
           (Item("Brushed brass handles ×12", 12, 6.75), Item("Soft-close hinges ×8", 8, 3.2)), job="job1",
           number="IDS-208877"),
    Recent("r06", 1, "sale", "Hartwell Property Maintenance", None,
           (Item("Office door adjustments and new ironmongery", 1, 480.0),), category="Sales",
           number="BRW-2026-1102"),
    Recent("r07", 0, "sale", "Sterling & Co. Architects", None,
           (Item("Alcove shelving, survey and drawings", 1, 350.0),), category="Sales", number="BRW-2026-1103"),
)  # fmt: skip


def _money(x: float) -> float:
    return round(x + 1e-9, 2)


def extracted(r: Recent, day: date, business: str) -> dict[str, Any]:
    lines = []
    for it in r.items:
        net = _money(it.qty * it.unit_price)
        lines.append(
            {
                "description": it.description,
                "qty": it.qty,
                "unit_price": it.unit_price,
                "net": net,
                "vat_rate": 20,
                "vat": _money(net * 0.2),
            }
        )
    net = _money(sum(ln["net"] for ln in lines))
    vat = _money(sum(ln["vat"] for ln in lines))
    sale = r.kind == "sale"
    return {
        "doc_type": "sales_invoice" if sale else ("purchase_invoice" if net + vat > 250 else "receipt"),
        "supplier_name": business if sale else r.party,
        "supplier_vat_number": "GB 123 4567 89" if sale else r.vat_number,
        "customer_name": r.party if sale else business,
        "invoice_number": r.number,
        "date": day.isoformat(),
        "currency": "GBP",
        "lines": lines,
        "net_total": net,
        "vat_total": vat,
        "gross_total": _money(net + vat),
        "payment_method": "bank_transfer" if sale else "card",
        "card_last4": None if sale else "4417",
        "category_guess": "Sales" if sale else r.category,
        "confidence": 0.99,
    }


def printed(r: Recent, day: date, business: str, label: str) -> str:
    doc = extracted(r, day, business)
    head = f"{doc['supplier_name'].upper()}\nVAT {doc['supplier_vat_number']}\n\n"
    head += f"{'INVOICE' if r.kind == 'sale' else 'RECEIPT'} No: {r.number}\nDate: {day:%d/%m/%Y}\n"
    head += f"\nBILL TO:\n{doc['customer_name']}\n\n" if r.kind == "sale" else "\n"
    rows = "\n".join(
        f"{ln['description']}  {ln['qty']:g} x {ln['unit_price']:.2f}  {ln['net']:.2f}" for ln in doc["lines"]
    )
    return (
        f"{head}{rows}\n\nNET TOTAL: {doc['net_total']:.2f}\nVAT (20%): {doc['vat_total']:.2f}\n"
        f"TOTAL: {doc['gross_total']:.2f}\n\n{label}"
    )


def planned(seed: ModuleType, plan: Any, today: date) -> list[Any]:
    """The seed's PlannedDoc for each recent document dated inside the current VAT period, oldest first."""
    out = []
    for n, r in enumerate(RECENT):
        day = today - timedelta(days=r.days_ago)
        if day < plan.current[0]:
            continue  # never inside a complete VAT period
        out.append(
            seed.PlannedDoc(
                gold=f"recent-{r.key}",
                date=day,
                text=printed(r, day, plan.business, seed.LABEL),
                extracted=extracted(r, day, plan.business),
                file_name=f"SAMPLE {day.isoformat()} {80 + n:02d}.png",
                job=r.job,
            )
        )
    return out


async def add_recent_trading(st: FakeStorageProvider, seed: ModuleType, plan: Any) -> int:
    """Post the recent documents (approved by the demo user, job-tagged) and pay each sale in full. Returns how many
    entries were posted."""
    from app import jobs, payments

    books = seed.SeedBooks(st)
    docs = planned(seed, plan, plan.today)
    if any(d.job for d in docs):  # the kitchen job has follow-on work this quarter: open again, so hours can go on it
        job = plan.jobs["job1"]
        await jobs.save_job(books, (await jobs.get_job(books, job.id)).model_copy(update={"status": "open"}))
    for d in docs:
        await seed._step_document(books, plan, d, False)  # noqa: SLF001  the seed's own upload, propose, approve
    for d in docs:
        if d.extracted["doc_type"] != "sales_invoice":
            continue
        p = await books.get_proposal(seed.proposal_id(plan, d))
        gross = round(d.extracted["gross_total"] * 100)
        await payments.record_payment(
            books,
            payments.PaymentIn(
                side="sale",
                date=d.date,
                amount_pence=gross,
                reference=d.extracted["invoice_number"],
                bank_line_id=None,
                allocations=[payments.AllocationIn(event_id=p.event_id or p.id, amount_pence=gross)],
            ),
            seed.USER,
            today=plan.today,
        )
    if docs:
        await seed._rebuild(books)  # noqa: SLF001  Books.xlsx with the new entries
    return len(docs)
