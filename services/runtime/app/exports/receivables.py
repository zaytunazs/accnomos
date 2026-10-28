"""Payables and receivables: aged balances (detail and summary), invoice and bill registers (detail and summary),
contact transactions, income and expenses by contact, customer invoice and supplier bill activity, supplier days
to pay.

Documents and money owed come from app/contacts.py unchanged (documents, assign, aged, payments_for, outstanding), so
these reports agree with the Contacts page and GET /reports/aged. "Outstanding" is what is still owed now, after
every payment and credit note recorded so far; the aged reports are as at their date.
"""

from __future__ import annotations

from datetime import date

from app import reports as rp
from app.contacts import (
    BUCKETS,
    AgedTable,
    Contact,
    Doc,
    Ledger,
    aged,
    assign,
    documents,
    due_date,
    outstanding,
    payments_for,
)
from app.exports.accounts import BUCKET_LABELS, aged_detail
from app.exports.registry import (
    Column,
    ExportContext,
    ExportSpec,
    ReportDoc,
    Row,
    Section,
    columns,
    doc_from,
    register,
    span_label,
    uk_day,
)

KIND = {"invoice": "Invoice", "credit_note": "Credit note"}


def aged_summary(table: AgedTable, title: str) -> Section:
    cols = [Column(key="name", label="Name")]
    cols += [Column(key=b, label=BUCKET_LABELS[b], kind="money") for b in BUCKETS]
    cols.append(Column(key="total", label="Total", kind="money"))
    rows = [Row(cells={"name": r.name, **r.buckets, "total": r.total_pence}) for r in table.rows]
    rows.append(Row(cells={"name": "Total", **table.buckets, "total": table.total_pence}, style="total"))
    return Section(title=title, columns=cols, rows=rows)


def _by_contact(contacts: list[Contact], ledger: Ledger) -> list[tuple[Contact, list[Doc]]]:
    by_id = {c.id: c for c in contacts}
    pairs = [(by_id[cid], docs) for cid, docs in assign(contacts, documents(ledger)).items() if cid in by_id]
    return sorted(pairs, key=lambda p: p[0].name.lower())


def _signed_gross(d: Doc) -> int:
    return d.sign * (d.gross if d.kind == "invoice" else -d.gross)


# --------------------------------------------------------------------------- #
# Invoice and bill registers
# --------------------------------------------------------------------------- #

SUMMARY_COLUMNS = columns(
    ("number", "Number"),
    ("contact", "Contact"),
    ("kind", "Type"),
    ("date", "Date", "date"),
    ("due", "Due", "date"),
    ("net", "Net", "money"),
    ("vat", "VAT", "money"),
    ("gross", "Total", "money"),
    ("owed", "Outstanding now", "money"),
)
DETAIL_COLUMNS = columns(
    ("number", "Number"),
    ("contact", "Contact"),
    ("date", "Date", "date"),
    ("account", "Account"),
    ("vat_code", "VAT code"),
    ("net", "Net", "money"),
    ("vat", "VAT", "money"),
    ("gross", "Total", "money"),
    ("owed", "Outstanding now", "money"),
)


def _docs_in(ctx_docs: list[tuple[Contact, list[Doc]]], side: str, start: date, end: date) -> list[tuple[Contact, Doc]]:
    out = [(c, d) for c, docs in ctx_docs for d in docs if d.side == side and start <= d.event.date <= end]
    return sorted(out, key=lambda cd: (cd[1].event.date, cd[1].event.id))


def register_summary(pairs: list[tuple[Contact, Doc]], ledger: Ledger, title: str) -> Section:
    rows: list[Row] = []
    t = [0, 0, 0, 0]
    for c, d in pairs:
        sign = 1 if _signed_gross(d) >= 0 else -1
        net, vat, gross, owed = (
            sign * (d.event.net or 0),
            sign * (d.event.vat or 0),
            _signed_gross(d),
            outstanding(d, ledger),
        )
        kind = KIND[d.kind] + (" (undo)" if d.undo else "")
        rows.append(
            Row(
                cells={
                    "number": d.reference or d.event.id[:8],
                    "contact": c.name,
                    "kind": kind,
                    "date": d.event.date.isoformat(),
                    "due": due_date(d, c).isoformat() if d.kind == "invoice" and not d.undo else "",
                    "net": net,
                    "vat": vat,
                    "gross": gross,
                    "owed": owed,
                }
            )
        )
        for i, v in enumerate((net, vat, gross, owed)):
            t[i] += v
    rows.append(Row(cells={"number": "Total", "net": t[0], "vat": t[1], "gross": t[2], "owed": t[3]}, style="total"))
    return Section(title=title, columns=SUMMARY_COLUMNS, rows=rows, note="Credit notes and undos are negative.")


def register_detail(pairs: list[tuple[Contact, Doc]], ledger: Ledger, title: str, side: str) -> Section:
    rows: list[Row] = []
    for c, d in pairs:
        number = d.reference or d.event.id[:8]
        sign = 1 if _signed_gross(d) >= 0 else -1
        for ln in d.event.lines:
            k = rp.section_of(ln.account)
            if (side == "sale" and k == "sales") or (side == "purchase" and k in ("cost_of_sales", "overheads")):
                amount = (ln.credit - ln.debit) if side == "sale" else (ln.debit - ln.credit)
                rows.append(
                    Row(
                        cells={
                            "number": number,
                            "contact": c.name,
                            "date": d.event.date.isoformat(),
                            "account": ln.account,
                            "vat_code": ln.vat_code.value if ln.vat_code else "",
                            "net": amount,
                        }
                    )
                )
        rows.append(
            Row(
                cells={
                    "number": f"{number} total",
                    "contact": c.name,
                    "net": sign * (d.event.net or 0),
                    "vat": sign * (d.event.vat or 0),
                    "gross": _signed_gross(d),
                    "owed": outstanding(d, ledger),
                },
                style="subtotal",
            )
        )
    return Section(
        title=title,
        columns=DETAIL_COLUMNS,
        rows=rows,
        note="Lines are the sales or expense legs of each document. VAT that cannot be reclaimed (codes N, O) is in "
        "the "
        "line amount, as the ledger posts it.",
    )


# --------------------------------------------------------------------------- #
# Per contact
# --------------------------------------------------------------------------- #

CONTACT_COLUMNS = columns(
    ("contact", "Contact"),
    ("invoiced", "Invoiced", "money"),
    ("billed", "Billed", "money"),
    ("credits", "Credit notes", "money"),
    ("received", "Payments received", "money"),
    ("paid", "Payments made", "money"),
    ("owed_to_you", "Owed to you now", "money"),
    ("you_owe", "You owe now", "money"),
)


def _paid_in(docs: list[Doc], ledger: Ledger, side: str, start: date, end: date) -> int:
    mine = [d for d in docs if d.side == side]
    return sum(amount for p, amount in payments_for(mine, ledger) if start <= p.date <= end) if mine else 0


def contact_transactions(pairs: list[tuple[Contact, list[Doc]]], ledger: Ledger, start: date, end: date) -> Section:
    rows: list[Row] = []
    keys = ("invoiced", "billed", "credits", "received", "paid", "owed_to_you", "you_owe")
    tot = dict.fromkeys(keys, 0)
    for c, docs in pairs:
        inside = [d for d in docs if start <= d.event.date <= end]
        row = {
            "invoiced": sum(_signed_gross(d) for d in inside if d.side == "sale" and d.kind == "invoice"),
            "billed": sum(_signed_gross(d) for d in inside if d.side == "purchase" and d.kind == "invoice"),
            "credits": sum(-_signed_gross(d) for d in inside if d.kind == "credit_note"),
            "received": _paid_in(docs, ledger, "sale", start, end),
            "paid": _paid_in(docs, ledger, "purchase", start, end),
            "owed_to_you": sum(outstanding(d, ledger) for d in docs if d.side == "sale"),
            "you_owe": sum(outstanding(d, ledger) for d in docs if d.side == "purchase"),
        }
        if not any(row.values()):
            continue
        rows.append(Row(cells={"contact": c.name, **row}))
        for k in keys:
            tot[k] += row[k]
    rows.append(Row(cells={"contact": "Total", **tot}, style="total"))
    return Section(
        title="Contact transactions summary",
        columns=CONTACT_COLUMNS,
        rows=rows,
        note="Documents and payments dated in the period; balances as they stand now.",
    )


IE_COLUMNS = columns(
    ("contact", "Contact"),
    ("income", "Income (net)", "money"),
    ("expenses", "Expenses (net)", "money"),
    ("net", "Net", "money"),
)


def income_expenses(pairs: list[tuple[Contact, list[Doc]]], start: date, end: date) -> Section:
    rows: list[Row] = []
    ti = te = 0
    for c, docs in pairs:
        inside = [d for d in docs if start <= d.event.date <= end]
        inc = sum((1 if _signed_gross(d) >= 0 else -1) * (d.event.net or 0) for d in inside if d.side == "sale")
        exp = sum((1 if _signed_gross(d) >= 0 else -1) * (d.event.net or 0) for d in inside if d.side == "purchase")
        if inc or exp:
            rows.append(Row(cells={"contact": c.name, "income": inc, "expenses": exp, "net": inc - exp}))
            ti, te = ti + inc, te + exp
    rows.append(Row(cells={"contact": "Total", "income": ti, "expenses": te, "net": ti - te}, style="total"))
    return Section(
        title="Income and expenses by contact",
        columns=IE_COLUMNS,
        rows=rows,
        note="Net of VAT; credit notes reduce the figure.",
    )


ACTIVITY_COLUMNS = columns(
    ("contact", "Contact"),
    ("count", "Documents", "int"),
    ("raised", "Raised", "money"),
    ("credits", "Credit notes", "money"),
    ("money", "Paid in the period", "money"),
    ("owed", "Outstanding now", "money"),
    ("overdue", "Overdue now", "money"),
)


def activity(
    pairs: list[tuple[Contact, list[Doc]]], ledger: Ledger, side: str, start: date, end: date, today: date, title: str
) -> Section:
    rows: list[Row] = []
    keys = ("count", "raised", "credits", "money", "owed", "overdue")
    tot = dict.fromkeys(keys, 0)
    for c, docs in pairs:
        mine = [d for d in docs if d.side == side]
        if not mine:
            continue
        inside = [d for d in mine if start <= d.event.date <= end]
        row = {
            "count": sum(1 for d in inside if d.kind == "invoice" and not d.undo),
            "raised": sum(_signed_gross(d) for d in inside if d.kind == "invoice"),
            "credits": sum(-_signed_gross(d) for d in inside if d.kind == "credit_note"),
            "money": _paid_in(mine, ledger, side, start, end),
            "owed": sum(outstanding(d, ledger) for d in mine),
            "overdue": sum(outstanding(d, ledger) for d in mine if due_date(d, c) < today),
        }
        if not any(row.values()):
            continue
        rows.append(Row(cells={"contact": c.name, **row}))
        for k in keys:
            tot[k] += row[k]
    rows.append(Row(cells={"contact": "Total", **tot}, style="total"))
    return Section(title=title, columns=ACTIVITY_COLUMNS, rows=rows)


DAYS_COLUMNS = columns(
    ("contact", "Supplier"),
    ("bills", "Bills paid", "int"),
    ("paid", "Amount paid", "money"),
    ("days", "Average days to pay", "int"),
    ("late", "Average days after due", "int"),
)


def supplier_days(pairs: list[tuple[Contact, list[Doc]]], ledger: Ledger, start: date, end: date) -> Section:
    """Payments made in the period, against the bills they paid: days from bill date (and from due date) to payment,
    weighted by the amount allocated."""
    rows: list[Row] = []
    all_w = all_days = all_late = all_bills = 0
    for c, docs in pairs:
        bills = {d.event.id: d for d in docs if d.side == "purchase" and d.kind == "invoice" and not d.undo}
        if not bills:
            continue
        w = days = late = 0
        paid_bills: set[str] = set()
        for p, _ in payments_for(list(bills.values()), ledger):
            if not start <= p.date <= end:
                continue
            for a in p.allocations:
                d = bills.get(a.event_id)
                if d is None:
                    continue
                w += a.amount_pence
                days += a.amount_pence * (p.date - d.event.date).days
                late += a.amount_pence * (p.date - due_date(d, c)).days
                paid_bills.add(a.event_id)
        if w:
            rows.append(
                Row(
                    cells={
                        "contact": c.name,
                        "bills": len(paid_bills),
                        "paid": w,
                        "days": round(days / w),
                        "late": round(late / w),
                    }
                )
            )
            all_w, all_days, all_late, all_bills = (
                all_w + w,
                all_days + days,
                all_late + late,
                all_bills + len(paid_bills),
            )
    rows.append(
        Row(
            cells={
                "contact": "All suppliers",
                "bills": all_bills,
                "paid": all_w,
                "days": round(all_days / all_w) if all_w else None,
                "late": round(all_late / all_w) if all_w else None,
            },
            style="total",
        )
    )
    return Section(
        title="Supplier days to pay", columns=DAYS_COLUMNS, rows=rows, note="Negative days after due means paid early."
    )


# --------------------------------------------------------------------------- #
# Registered reports
# --------------------------------------------------------------------------- #


async def _setup(ctx: ExportContext) -> tuple[Ledger, list[tuple[Contact, list[Doc]]]]:
    ledger = await ctx.ledger()
    return ledger, _by_contact(await ctx.contacts(), ledger)


def _aged_builder(spec_id: str, title: str, side: str, detail: bool):
    async def build(ctx: ExportContext) -> ReportDoc:
        ledger = await ctx.ledger()
        balances = aged(await ctx.contacts(), ledger, ctx.as_of)
        table = balances.debtors if side == "sale" else balances.creditors
        section = aged_detail(table, title) if detail else aged_summary(table, title)
        return doc_from(
            spec_id,
            title,
            f"at {uk_day(ctx.as_of)}",
            [section],
            basis=[
                "What is still owed on each document after payments and credit notes, by days past its due date "
                "(the invoice's own due date, else the contact's terms, else 30 days)."
            ],
            sample=rp.is_sample(ledger.events),
        )

    return build


def _register_builder(spec_id: str, title: str, side: str, detail: bool):
    async def build(ctx: ExportContext) -> ReportDoc:
        ledger, pairs = await _setup(ctx)
        inside = _docs_in(pairs, side, ctx.start, ctx.end)
        section = register_detail(inside, ledger, title, side) if detail else register_summary(inside, ledger, title)
        return doc_from(spec_id, title, span_label(ctx.start, ctx.end), [section], sample=rp.is_sample(ledger.events))

    return build


async def build_contact_transactions(ctx: ExportContext) -> ReportDoc:
    ledger, pairs = await _setup(ctx)
    return doc_from(
        "contact-transactions",
        "Contact transactions summary",
        span_label(ctx.start, ctx.end),
        [contact_transactions(pairs, ledger, ctx.start, ctx.end)],
        sample=rp.is_sample(ledger.events),
    )


async def build_income_expenses(ctx: ExportContext) -> ReportDoc:
    ledger, pairs = await _setup(ctx)
    return doc_from(
        "income-expenses-by-contact",
        "Income and expenses by contact",
        span_label(ctx.start, ctx.end),
        [income_expenses(pairs, ctx.start, ctx.end)],
        sample=rp.is_sample(ledger.events),
    )


async def build_customer_activity(ctx: ExportContext) -> ReportDoc:
    ledger, pairs = await _setup(ctx)
    return doc_from(
        "customer-invoice-activity",
        "Customer invoice activity",
        span_label(ctx.start, ctx.end),
        [activity(pairs, ledger, "sale", ctx.start, ctx.end, ctx.today, "Customer invoice activity")],
        sample=rp.is_sample(ledger.events),
    )


async def build_supplier_activity(ctx: ExportContext) -> ReportDoc:
    ledger, pairs = await _setup(ctx)
    return doc_from(
        "supplier-bill-activity",
        "Supplier bill activity",
        span_label(ctx.start, ctx.end),
        [activity(pairs, ledger, "purchase", ctx.start, ctx.end, ctx.today, "Supplier bill activity")],
        sample=rp.is_sample(ledger.events),
    )


async def build_supplier_days(ctx: ExportContext) -> ReportDoc:
    ledger, pairs = await _setup(ctx)
    return doc_from(
        "supplier-days-to-pay",
        "Supplier days to pay",
        span_label(ctx.start, ctx.end),
        [supplier_days(pairs, ledger, ctx.start, ctx.end)],
        sample=rp.is_sample(ledger.events),
    )


for _spec in (
    ExportSpec(
        "aged-receivables-detail",
        "payables",
        "Aged receivables detail",
        "Each unpaid sales invoice by age.",
        _aged_builder("aged-receivables-detail", "Aged receivables detail", "sale", True),
        params=("as_of",),
    ),
    ExportSpec(
        "aged-receivables-summary",
        "payables",
        "Aged receivables summary",
        "What each customer owes, by age band.",
        _aged_builder("aged-receivables-summary", "Aged receivables summary", "sale", False),
        params=("as_of",),
    ),
    ExportSpec(
        "aged-payables-detail",
        "payables",
        "Aged payables detail",
        "Each unpaid bill by age.",
        _aged_builder("aged-payables-detail", "Aged payables detail", "purchase", True),
        params=("as_of",),
    ),
    ExportSpec(
        "aged-payables-summary",
        "payables",
        "Aged payables summary",
        "What you owe each supplier, by age band.",
        _aged_builder("aged-payables-summary", "Aged payables summary", "purchase", False),
        params=("as_of",),
    ),
    ExportSpec(
        "receivable-invoice-detail",
        "payables",
        "Receivable invoice detail",
        "Sales invoices and credit notes, line by line.",
        _register_builder("receivable-invoice-detail", "Receivable invoice detail", "sale", True),
    ),
    ExportSpec(
        "receivable-invoice-summary",
        "payables",
        "Receivable invoice summary",
        "One row per sales invoice or credit note.",
        _register_builder("receivable-invoice-summary", "Receivable invoice summary", "sale", False),
    ),
    ExportSpec(
        "payable-invoice-detail",
        "payables",
        "Payable invoice detail",
        "Bills, receipts and supplier credit notes, line by line.",
        _register_builder("payable-invoice-detail", "Payable invoice detail", "purchase", True),
    ),
    ExportSpec(
        "payable-invoice-summary",
        "payables",
        "Payable invoice summary",
        "One row per bill, receipt or supplier credit note.",
        _register_builder("payable-invoice-summary", "Payable invoice summary", "purchase", False),
    ),
    ExportSpec(
        "contact-transactions",
        "payables",
        "Contact transactions summary",
        "Invoiced, billed, credited and paid per contact.",
        build_contact_transactions,
    ),
    ExportSpec(
        "income-expenses-by-contact",
        "payables",
        "Income and expenses by contact",
        "Net income and spending per contact.",
        build_income_expenses,
    ),
    ExportSpec(
        "customer-invoice-activity",
        "payables",
        "Customer invoice activity",
        "Invoices raised, payments received and what is overdue, per customer.",
        build_customer_activity,
    ),
    ExportSpec(
        "supplier-bill-activity",
        "payables",
        "Supplier bill activity",
        "Bills received, payments made and what is overdue, per supplier.",
        build_supplier_activity,
    ),
    ExportSpec(
        "supplier-days-to-pay",
        "payables",
        "Supplier days to pay",
        "How long you take to pay each supplier.",
        build_supplier_days,
    ),
):
    register(_spec)
