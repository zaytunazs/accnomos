"""The company demo's recent trading: a few sales and purchases dated from the start of the current VAT period up to
the demo's own "today", so Ask's "profit yesterday", "this week" and "this quarter" have real figures, and the
"Kitchen fit-out, Harrogate" job has purchases with item lines ("what did we order for the kitchen job?"); that
job is open again for its follow-on work, so hours can be logged on it.

Every date is relative to the session's day (built once a day, like the rest of the demo), and nothing is ever dated
before the current VAT period starts, so the two complete periods the seed fills (and the Jul–Sep return the HMRC
sandbox demo files) never change. Documents go through the same path as the seed's own: uploaded, proposed with the
"perfect reading", approved by the demo user; each sale is then paid in full (Record payment: into the bank, or two
of them into 1240 PayPal clearing, as if paid through a PayPal link), so the amounts owed to the business stay as the
seed left them. Labelled "SAMPLE — FICTIONAL COMPANY" like every other demo document.

Bill pay (`add_bill_pay`): three supplier bills to pay through PayPal, one due today, one approved in advance and one
planned, with the suppliers' PayPal emails saved. Nothing is paid and PayPal is not connected.
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
    paid_into: str = "1200 Bank"  # a sale's payment: the bank, or "1240 PayPal clearing" (paid through a PayPal link)


RECENT: tuple[Recent, ...] = (
    Recent("r01", 20, "purchase", "Northern Workwear Ltd", "GB 284 6531 70",
           (Item("Hi-vis jackets", 4, 9.5), Item("Safety boots", 2, 24.0)), category="Sundry",
           number="NW-77310"),
    Recent("r02", 12, "purchase", "Harrogate Tile & Stone Ltd", "GB 318 2290 46",
           (Item("Matt white metro tiles 300×100, 8 m²", 8, 24.5), Item("Flexible tile adhesive 20 kg", 2, 18.5),
            Item("Grout, white 5 kg", 1, 9.8)), job="job1", number="HTS-10482"),
    Recent("r03", 10, "sale", "Halloway & Sons Interiors", None,
           (Item("Kitchen fit-out, Harrogate: second fix, tiling and worktops", 1, 2400.0),), category="Sales",
           number="BRW-2026-1101", paid_into="1240 PayPal clearing"),
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
           (Item("Alcove shelving, survey and drawings", 1, 350.0),), category="Sales", number="BRW-2026-1103",
           paid_into="1240 PayPal clearing"),
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
    paid_into = {r.number: r.paid_into for r in RECENT}
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
                account=paid_into.get(d.extracted["invoice_number"], "1200 Bank"),  # type: ignore[arg-type]
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


#: The demo's customer with about £500 overdue, settled through PayPal (the sample history pays it in full three days
#: before "today", online_fakes.sample_transactions): "did that client pay all the arrears? check PayPal" in Ask.
ARREARS_LINE = ("Reception desk repair and new cabinet doors", 41_000)  # £410.00 + VAT = £492.00
ARREARS_DAYS_AGO = 40  # issued; 30 days to pay, so about ten days overdue


async def add_arrears_invoice(st: FakeStorageProvider, seed: ModuleType, plan: Any) -> str | None:
    """Create and "send" (nothing is emailed) one invoice to the arrears customer, unpaid in the books. Dated inside
    the current VAT period only, like every recent document; None when that would fall before it."""
    from decimal import Decimal

    from app import invoicing
    from app.online_fakes import SAMPLE_ARREARS_CUSTOMER

    issue = plan.today - timedelta(days=ARREARS_DAYS_AGO)
    if issue < plan.current[0]:
        return None
    books = seed.SeedBooks(st)
    desc, unit = ARREARS_LINE
    draft = invoicing.InvoiceDraft(
        customer=invoicing.InvoiceCustomer(
            contact_id=None,
            name=SAMPLE_ARREARS_CUSTOMER,
            email="accounts@wrenfield-dental.example",
            address="4 Mill Lane, Harrogate",
            vrn=None,
        ),
        issue_date=issue,
        due_date=issue + timedelta(days=30),
        lines=[invoicing.LineIn(description=desc, quantity=Decimal(1), unit="each", unit_price_pence=unit)],
        reference=None,
        notes=seed.LABEL,
        job_id=None,
    )
    created = await invoicing.create_invoice(books, draft, seed.USER)
    profile = await invoicing.load_profile(books)
    await invoicing.send_invoice(
        books, seed.NotEmailed(), created.number, seed.USER, seed.render_invoice(created, profile)
    )
    await seed._rebuild(books)  # noqa: SLF001  Books.xlsx with the new entry
    return created.number


# --------------------------------------------------------------------------- #
# Bill pay: three open supplier bills to pay through PayPal
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DemoBill:
    """An unpaid supplier bill on account (Cr 2100 Creditors) with the supplier's PayPal email saved by the owner.
    `state`: "due" (due today: Purchases › Bill pay › Due today › Approve payment), "approved" (approved in advance,
    paid on its due date, which is days after a demo session ends), "planned" (Pay with PayPal ticked, not approved)."""

    key: str
    supplier: str
    vat_number: str
    number: str
    items: tuple[Item, ...]
    days_ago: int  # the bill's date
    due_in: int  # days from the demo's today to the due date
    state: str
    paypal_email: str  # example.com is reserved (RFC 2606): no one can own it, so a sandbox payout stays UNCLAIMED
    category: str = "Materials"


BILLS: tuple[DemoBill, ...] = (
    DemoBill("b1", "Pennine Glazing Supplies Ltd", "GB 611 4083 27", "PGS-4471",
             (Item("Toughened glass panels for cabinet doors", 4, 23.75),), 14, 0, "due",
             "accounts.pennine-glazing@example.com"),
    DemoBill("b2", "Calder Valley Fixings Ltd", "GB 703 5528 61", "CVF-20916",
             (Item("Stainless wood screws, assorted boxes", 6, 12.5), Item("Wall plugs and frame anchors", 1, 53.0)),
             9, 5, "approved", "payments.calder-fixings@example.com"),
    DemoBill("b3", "Nidderdale Saw Sharpening Ltd", "GB 829 1174 36", "NSS-0388",
             (Item("Saw blade sharpening", 6, 14.0), Item("Router cutter regrind", 3, 7.0)), 18, 12, "planned",
             "nidderdale-saws@example.com", category="Repairs"),
)  # fmt: skip


def bill_extracted(b: DemoBill, day: date, business: str) -> dict[str, Any]:
    r = Recent(b.key, b.days_ago, "purchase", b.supplier, b.vat_number, b.items, category=b.category, number=b.number)
    # A supplier's invoice, not yet paid: on account (no payment method), so it posts Cr 2100 Creditors.
    return extracted(r, day, business) | {"doc_type": "purchase_invoice", "payment_method": None, "card_last4": None}


def bill_printed(b: DemoBill, day: date, terms: int, business: str, label: str) -> str:
    doc = bill_extracted(b, day, business)
    rows = "\n".join(
        f"{ln['description']}  {ln['qty']:g} x {ln['unit_price']:.2f}  {ln['net']:.2f}" for ln in doc["lines"]
    )
    return (
        f"{b.supplier.upper()}\nVAT {b.vat_number}\n\nINVOICE No: {b.number}\nDate: {day:%d/%m/%Y}\n\n"
        f"BILL TO:\n{business}\n\n{rows}\n\nNET TOTAL: {doc['net_total']:.2f}\nVAT (20%): {doc['vat_total']:.2f}\n"
        f"TOTAL: {doc['gross_total']:.2f}\n\nPayment terms: {terms} days. Pay by PayPal to {b.paypal_email}\n\n{label}"
    )


def bill_dates(b: DemoBill, today: date, period_start: date) -> tuple[date, int]:
    """(the bill's date, the supplier's payment terms in days): never before the current VAT period (like every
    recent document), and due exactly `due_in` days from today whatever day the demo is built."""
    days_ago = max(0, min(b.days_ago, (today - period_start).days))
    return today - timedelta(days=days_ago), days_ago + b.due_in


async def add_bill_pay(st: FakeStorageProvider, seed: ModuleType, plan: Any) -> list[str]:
    """Post the three bills (uploaded, read, approved by the demo user, as every recent document), set each
    supplier's payment terms and the PayPal email the owner typed, tick Pay with PayPal, and approve one payment in
    advance. Pays nothing and connects nothing: PayPal stays unconnected, and Autopilot stays off. Returns the bills'
    entry ids, in BILLS order."""
    from app import billpay as bp
    from app import contacts as cb
    from app.books import now

    books = seed.SeedBooks(st)
    today = plan.today
    dated = [(b, *bill_dates(b, today, plan.current[0])) for b in BILLS]
    docs = []
    for n, (b, day, terms) in enumerate(dated):
        d = seed.PlannedDoc(
            gold=f"billpay-{b.key}",
            date=day,
            text=bill_printed(b, day, terms, plan.business, seed.LABEL),
            extracted=bill_extracted(b, day, plan.business),
            file_name=f"SAMPLE {day.isoformat()} {90 + n:02d}.png",
        )
        await seed._step_document(books, plan, d, False)  # noqa: SLF001  the seed's own upload, propose, approve
        docs.append(d)
    ids = []
    for d in docs:
        p = await books.get_proposal(seed.proposal_id(plan, d))
        ids.append(p.event_id or p.id)
    contacts, ledger, _ = await cb.contact_book(books)
    for (b, _day, terms), event_id in zip(dated, ids, strict=True):
        cid = next(
            cid for cid, docs_ in cb.assign(contacts, cb.documents(ledger)).items()
            if any(x.event.id == event_id for x in docs_)
        )  # fmt: skip
        await cb.edit(books, cid, {"terms_days": terms}, seed.USER)
        await bp.set_payee(books, cid, b.paypal_email, None, seed.USER)
        await bp.set_plan(books, event_id, "paypal", seed.USER)
    # "Approve now, pay on due date" for the approved one, exactly as the card would keep it. Written here rather
    # than through billpay_schedule.approve(), which refuses while PayPal is not connected (the demo never is until
    # the visitor connects it). Its due date is days away, so POST /billpay/run never pays it in a demo session.
    ov = await bp.bills(books, today=today, read_documents=False)
    by_id = {x.event_id: x for x in [*ov.due, *ov.upcoming]}
    for (b, _day, _terms), event_id in zip(dated, ids, strict=True):
        if b.state != "approved":
            continue
        bill = by_id[event_id]
        at = now()
        approval = bp.Approval(
            event_id=event_id,
            contact_id=bill.contact_id,
            supplier=bill.supplier,
            reference=bill.reference,
            amount_pence=bill.owed_pence,
            payee_email=b.paypal_email,
            due_date=bill.due_date,
            bill_version=bill.version,
            approved_by=seed.USER,
            approved_at=at,
            updated_at=at,
        )

        def change(s: bp.Scheduled, a: bp.Approval = approval) -> None:
            s.approvals[a.event_id] = a

        await bp.update_scheduled(books, change)
        await books.audit(
            f"user:{seed.USER}",
            "billpay_scheduled_approved",
            {
                "bill": event_id,
                "supplier": bill.supplier,
                "amount_pence": bill.owed_pence,
                "receiver": b.paypal_email,
                "due_date": bill.due_date.isoformat(),
                "bill_version": bill.version,
                "acknowledged_changed_details": False,
            },
        )
    await seed._rebuild(books)  # noqa: SLF001  Books.xlsx with the new entries
    return ids
