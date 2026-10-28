"""Customer statements: what a customer was charged and paid between two dates, and what they still owe.

Built only from the books (app/contacts.statement, the same figures as the contact page), then drawn as a PDF
(app/pdf_docs.render_statement) and, if the user confirms, emailed from their own Outlook. Customer side only: purchase
documents of a contact who is also a supplier are left out, so a statement never shows what the user owes.

    activity     invoices, credit notes, payments and refunds dated in the period, with a running balance
    outstanding  invoices with something left to pay, with days past due. Shown when the statement runs to today or
                 later, because open items describe the books now, not on an earlier date
    credit       money on the customer's account (an overpayment or a credit note larger than the debt)

Sending needs `confirm: true` from the app, like an invoice. The PDF that was emailed is kept in 03 Sales/statements
and the audit log records who it went to and the closing balance.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

from pydantic import BaseModel

from accnomos_connectors.base import MailSender, OutgoingAttachment, OutgoingMail
from app import contacts as cb
from app import invoicing as inv_
from app.books import Books
from app.books import today as london_today
from app.invoicing import EMAIL_RE, InvoiceError, InvoiceProfile, money, uk_date
from app.paths import STATEMENTS
from app.pdf_docs import OpenRow, StatementRow, render_statement


class StatementView(BaseModel):
    contact: cb.Contact
    start: date | None
    end: date
    opening_balance_pence: int
    closing_balance_pence: int
    credit_pence: int
    lines: list[cb.StatementLine]
    open_documents: list[cb.OpenItem]
    owed_pence: int  # the sum of open_documents; what the customer owes today (0 when open items are not shown)
    shows_outstanding: bool
    email: str | None = None  # where to send it: the contact's, else the one on their latest invoice


def _customer_docs(contacts: list[cb.Contact], ledger: cb.Ledger, contact_id: str) -> list[cb.Doc]:
    return [d for d in cb.assign(contacts, cb.documents(ledger)).get(contact_id, []) if d.side == "sale"]


async def build_statement(
    books: Books, contact_id: str, start: date | None = None, end: date | None = None, today: date | None = None
) -> StatementView:
    today = today or london_today()
    end = end or today
    if start and start > end:
        raise InvoiceError("The start date must not be after the end date")
    contacts, ledger, _ = await cb.contact_book(books)
    contact = next((c for c in contacts if c.id == contact_id), None)
    if contact is None:
        raise FileNotFoundError(contact_id)
    st = cb.statement(contact, _customer_docs(contacts, ledger, contact_id), ledger, start, end)
    shows = end >= today
    email = contact.email
    if not email:  # contacts made from the ledger carry no address; the invoices do
        mine = [
            i
            for i in await inv_.list_invoices(books)
            if i.customer.email
            and (i.customer.contact_id == contact.id or i.customer.name.lower() == contact.name.lower())
        ]
        email = max(mine, key=lambda i: i.issue_date).customer.email if mine else None
    open_docs = st.open_documents if shows else []
    return StatementView(
        contact=contact,
        start=start,
        end=end,
        opening_balance_pence=st.opening_balance_pence,
        closing_balance_pence=st.closing_balance_pence,
        credit_pence=st.credit_pence if shows else 0,
        lines=st.lines,
        open_documents=open_docs,
        owed_pence=sum(o.outstanding_pence for o in open_docs),
        shows_outstanding=shows,
        email=email,
    )


def _rows(view: StatementView) -> list[StatementRow]:
    out: list[StatementRow] = []
    for ln in view.lines:
        out.append(
            StatementRow(
                date=ln.date,
                details=ln.details,
                reference=ln.reference or "",
                charge_pence=max(ln.amount_pence, 0) + max(ln.paid_pence, 0),
                credit_pence=max(-ln.amount_pence, 0) + max(-ln.paid_pence, 0),
                balance_pence=ln.balance_pence,
            )
        )
    return out


def _open_rows(view: StatementView) -> list[OpenRow]:
    return [
        OpenRow(
            reference=o.reference or "",
            date=o.date,
            due=o.due_date,
            total_pence=o.gross_pence,
            owed_pence=o.outstanding_pence,
            days_overdue=(view.end - o.due_date).days,
        )
        for o in view.open_documents
    ]


def render(view: StatementView, profile: InvoiceProfile, logo: bytes | None = None) -> bytes:
    address = [p.strip() for p in re.split(r"[\n,]", view.contact.address or "") if p.strip()]
    return render_statement(
        name=view.contact.name,
        address=address,
        start=view.start,
        end=view.end,
        opening_pence=view.opening_balance_pence,
        closing_pence=view.closing_balance_pence,
        rows=_rows(view),
        open_items=_open_rows(view),
        credit_pence=view.credit_pence,
        profile=profile,
        logo=logo,
    )


def default_email(view: StatementView, profile: InvoiceProfile) -> tuple[str, str]:
    who = profile.name.strip() or "us"
    owed = view.owed_pence if view.shows_outstanding else view.closing_balance_pence
    lines = ["Hello,", "", f"Please find attached your statement up to {uk_date(view.end)}."]
    if owed > 0:
        lines.append(f"The amount due is {money(owed)}.")
    elif owed == 0:
        lines.append("Nothing is due. Thank you.")
    lines += ["", "If anything looks wrong, just reply to this email.", "", "Many thanks,", who]
    return f"Statement from {who}", "\n".join(lines)


def send_problems(view: StatementView, to: str) -> list[str]:
    out: list[str] = []
    if not EMAIL_RE.fullmatch(to):
        out.append("Add a valid email address for the customer")
    if not view.lines and not view.open_documents and not view.opening_balance_pence:
        out.append("There is nothing on this statement to send")
    return out


async def send_statement(
    books: Books,
    sender: MailSender,
    contact_id: str,
    user: str,
    *,
    start: date | None = None,
    end: date | None = None,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> StatementView:
    """Email the statement PDF. The email goes first (it cannot be taken back); the copy and the audit line follow."""
    view = await build_statement(books, contact_id, start, end)
    to = (to or view.email or "").strip()
    if problems := send_problems(view, to):
        raise InvoiceError("; ".join(problems))
    profile = await inv_.load_profile(books)
    data = render(view, profile, await inv_.load_logo(books, profile))
    d_subject, d_body = default_email(view, profile)
    name = f"Statement {view.end.isoformat()}.pdf"
    await sender.send(
        OutgoingMail(
            to=to,
            subject=(subject or "").strip() or d_subject,
            body_text=(body or "").strip() or d_body,
            attachments=[OutgoingAttachment(name=name, content_type="application/pdf", data=data)],
        )
    )
    sha = hashlib.sha256(data).hexdigest()
    await books.storage.write(f"{STATEMENTS}/{view.contact.id}-{view.end.isoformat()}.pdf", data)
    await books.audit(
        f"user:{user}",
        "statement_sent",
        {"contact": view.contact.name, "to": to, "closing_pence": view.closing_balance_pence, "pdf_sha256": sha},
    )
    return view
