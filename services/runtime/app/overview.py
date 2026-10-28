"""The Sales and Purchases overview pages: money in and out, drafts, awaiting payment, overdue, all worked out by code
from the user's own files and ledger (nothing stored, nothing estimated by a model).

Sales
    drafts           draft invoices (not yet sent, so not in the books)
    awaiting payment sent invoices with something still owed: what is left after payments and credit notes
    overdue          the same, past their due date (the day after it)
    due soon         due today or within the next 7 days
    money in         payments received in the last 30 days
    invoiced         invoices sent with an invoice date in the last 30 days (gross)
    quotes           drafts, sent and waiting, expired, accepted and not yet invoiced
    aged             what is owed by days past due (current, 0-30, 31-60, 61-90, 90+), the same buckets as Contacts

Purchases
    in review        bills and receipts waiting for the user's approval in Review (nothing is owed until approved)
    awaiting payment bills posted on account (Cr 2100 Creditors) with something still to pay
    overdue / due soon / money out / aged  as for sales
    orders           purchase orders: drafts, approved or sent and not yet billed, past their delivery date

"Due" for a bill is the supplier's terms (Contacts, else 30 days) from the bill's date, as on the aged creditors report.
A day count is `today - due date`: 1 means it fell due yesterday. "Money in" and "money out" are recorded payments and
bank lines matched to documents (app/settlement.py), by the date of the payment.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from app import contacts as cb
from app import payments as pay_
from app import purchase_orders as po_
from app import quotes as q_
from app import repeating as rp_
from app.books import Books
from app.books import today as london_today
from app.invoicing import Invoice

WINDOW_DAYS = 30
SOON_DAYS = 7


class Bucket(BaseModel):
    count: int = 0
    total_pence: int = 0

    def add(self, pence: int) -> None:
        self.count += 1
        self.total_pence += pence


class OwedRow(BaseModel):
    reference: str  # the invoice number, or the bill's reference / date
    name: str  # the customer or supplier
    contact_id: str | None = None
    owed_pence: int
    due_date: date
    days_overdue: int  # negative: not due yet
    number: str | None = None  # a sales invoice's number (the page links it)
    event_id: str | None = None


class RepeatingSummary(BaseModel):
    active: int = 0
    due_now: int = 0
    next_date: date | None = None


class SalesOverview(BaseModel):
    as_of: date
    window_days: int = WINDOW_DAYS
    money_in_pence: int = 0
    invoiced_pence: int = 0
    drafts: Bucket
    awaiting_payment: Bucket
    overdue: Bucket
    due_soon: Bucket
    aged: dict[str, int]
    owed_most: list[OwedRow]  # the biggest few amounts overdue, then due soonest
    customer_credit_pence: int = 0
    quote_drafts: Bucket
    quotes_waiting: Bucket  # sent, within their expiry date
    quotes_expired: Bucket
    quotes_to_invoice: Bucket  # accepted, not yet an invoice
    repeating: RepeatingSummary


class PurchasesOverview(BaseModel):
    as_of: date
    window_days: int = WINDOW_DAYS
    money_out_pence: int = 0
    in_review: Bucket  # bills and receipts waiting in Review
    needs_a_look: int = 0  # of those, the ones with a check that failed
    awaiting_payment: Bucket
    overdue: Bucket
    due_soon: Bucket
    aged: dict[str, int]
    owed_most: list[OwedRow]
    supplier_credit_pence: int = 0
    order_drafts: Bucket
    orders_open: Bucket  # approved or sent, no bill yet
    orders_late: Bucket  # of those, past their delivery date
    orders_billed_in_review: Bucket  # billed, the bill still waiting for approval
    repeating: RepeatingSummary


def _repeating(templates: list[rp_.Template], kind: str, today: date) -> RepeatingSummary:
    mine = [t for t in templates if t.kind == kind]
    live = [t for t in mine if not t.paused and t.next_run() is not None]
    dates = [d for t in live if (d := t.next_run()) is not None]
    return RepeatingSummary(
        active=len(live),
        due_now=sum(1 for t in live if (d := t.next_run()) is not None and d <= today),
        next_date=min(dates) if dates else None,
    )


def _in_window(d: date, today: date) -> bool:
    return today - timedelta(days=WINDOW_DAYS) < d <= today


def _owed_sort(rows: list[OwedRow]) -> list[OwedRow]:
    late = sorted((r for r in rows if r.days_overdue > 0), key=lambda r: (-r.owed_pence, r.reference))
    soon = sorted((r for r in rows if r.days_overdue <= 0), key=lambda r: (r.due_date, r.reference))
    return [*late, *soon][:5]


def sales_overview(
    invoices: list[Invoice],
    quotes: list[q_.Quote],
    ledger: cb.Ledger,
    templates: list[rp_.Template],
    today: date,
) -> SalesOverview:
    s = ledger.settlement()
    out = SalesOverview(
        as_of=today,
        drafts=Bucket(),
        awaiting_payment=Bucket(),
        overdue=Bucket(),
        due_soon=Bucket(),
        aged=dict.fromkeys(cb.BUCKETS, 0),
        owed_most=[],
        quote_drafts=Bucket(),
        quotes_waiting=Bucket(),
        quotes_expired=Bucket(),
        quotes_to_invoice=Bucket(),
        repeating=_repeating(templates, "invoice", today),
    )
    rows: list[OwedRow] = []
    for inv in invoices:
        if inv.status == "draft":
            out.drafts.add(inv.total_pence)
        if inv.status in ("sent", "paid") and _in_window(inv.issue_date, today):
            out.invoiced_pence += inv.total_pence
        if inv.status != "sent":
            continue
        m = pay_.invoice_money(inv, ledger)
        owed = m.balance_pence if m is not None else inv.total_pence
        if owed <= 0:
            continue
        late = (today - inv.due_date).days
        out.awaiting_payment.add(owed)
        out.aged[cb.bucket(late)] += owed
        if late > 0:
            out.overdue.add(owed)
        elif late >= -SOON_DAYS:
            out.due_soon.add(owed)
        rows.append(
            OwedRow(
                reference=inv.number,
                number=inv.number,
                name=inv.customer.name,
                contact_id=inv.customer.contact_id,
                owed_pence=owed,
                due_date=inv.due_date,
                days_overdue=late,
                event_id=inv.event_id,
            )
        )
    out.owed_most = _owed_sort(rows)
    out.money_in_pence = sum(p.amount_pence for p in s.payments if p.side == "sale" and _in_window(p.date, today))
    out.customer_credit_pence = sum(c.amount_pence for c in s.credits if c.side == "sale")
    for q in quotes:
        status = q.effective_status(today)
        if status == "draft":
            out.quote_drafts.add(q.total_pence)
        elif status == "sent":
            out.quotes_waiting.add(q.total_pence)
        elif status == "expired":
            out.quotes_expired.add(q.total_pence)
        elif status == "accepted" and not q.invoice_number:
            out.quotes_to_invoice.add(q.total_pence)
    return out


def purchases_overview(
    contacts: list[cb.Contact],
    ledger: cb.Ledger,
    orders: list[po_.PurchaseOrder],
    templates: list[rp_.Template],
    today: date,
) -> PurchasesOverview:
    s = ledger.settlement()
    out = PurchasesOverview(
        as_of=today,
        in_review=Bucket(),
        awaiting_payment=Bucket(),
        overdue=Bucket(),
        due_soon=Bucket(),
        aged=dict.fromkeys(cb.BUCKETS, 0),
        owed_most=[],
        order_drafts=Bucket(),
        orders_open=Bucket(),
        orders_late=Bucket(),
        orders_billed_in_review=Bucket(),
        repeating=_repeating(templates, "bill", today),
    )
    rows: list[OwedRow] = []
    for row in cb.aged(contacts, ledger, today).creditors.rows:
        for d in row.documents:
            out.awaiting_payment.add(d.amount_pence)
            out.aged[d.bucket] += d.amount_pence
            if d.age_days > 0:
                out.overdue.add(d.amount_pence)
            elif d.age_days >= -SOON_DAYS:
                out.due_soon.add(d.amount_pence)
            rows.append(
                OwedRow(
                    reference=d.reference or f"Bill of {d.date:%d/%m/%Y}",
                    name=row.name,
                    contact_id=row.contact_id,
                    owed_pence=d.amount_pence,
                    due_date=d.due_date,
                    days_overdue=d.age_days,
                    event_id=d.event_id,
                )
            )
    out.owed_most = _owed_sort(rows)
    out.money_out_pence = sum(p.amount_pence for p in s.payments if p.side == "purchase" and _in_window(p.date, today))
    out.supplier_credit_pence = sum(c.amount_pence for c in s.credits if c.side == "purchase")
    for p in ledger.proposals.values():
        d = p.extracted
        if (
            p.status in ("proposed", "needs_a_look")
            and d.doc_type in ("purchase_invoice", "receipt")
            and not p.mileage_claim
        ):
            out.in_review.add(round(d.gross_total * 100))
            out.needs_a_look += p.status == "needs_a_look"
    for o in orders:
        if o.status == "draft":
            out.order_drafts.add(o.total_pence)
        elif o.status in ("approved", "sent"):
            out.orders_open.add(o.total_pence)
            if o.delivery_date and o.delivery_date < today:
                out.orders_late.add(o.total_pence)
        elif o.status == "billed" and o.bill:
            p = ledger.proposals.get(o.bill.proposal_id)
            if p is not None and p.status in ("proposed", "needs_a_look"):
                out.orders_billed_in_review.add(o.total_pence)
    return out


async def load_sales(books: Books, today: date | None = None) -> SalesOverview:
    from app.invoicing import list_invoices

    today = today or london_today()
    invoices = await list_invoices(books)
    ledger = await cb.load_ledger(books)
    return sales_overview(invoices, await q_.list_quotes(books), ledger, await rp_.list_templates(books), today)


async def load_purchases(books: Books, today: date | None = None) -> PurchasesOverview:
    today = today or london_today()
    contacts, ledger, _ = await cb.contact_book(books)
    return purchases_overview(contacts, ledger, await po_.list_orders(books), await rp_.list_templates(books), today)
