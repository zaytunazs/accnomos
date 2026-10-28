"""Purchase orders: written by the user, numbered and priced by code, approved, emailed to the supplier from their own
Outlook, turned into a bill for the user to approve, and matched to the bill the supplier sends.

Files, all in the user's folder:

    _System/PurchaseOrders/PO-0001.json         the order (money in integer pence)
    _System/PurchaseOrders/PO-0001.pdf          the latest render
    _System/PurchaseOrders/sent/PO-0001.pdf     the exact PDF that was emailed
    _System/PurchaseOrders/sequence.json        {"prefix": "PO-", "next": 2}

Priced exactly like an invoice (app/invoicing.price_lines). An order posts nothing to the books: it is a commitment,
not a cost. The cost arrives with the supplier's bill.

Statuses: draft -> approved -> sent -> billed, and cancelled from draft, approved or sent.
  * Only a draft can be edited. *Approve* is the user's decision that the order may go out (it is recorded in the
    audit log and cannot be edited afterwards). *Send* needs `confirm: true` like an invoice.
  * *Convert to bill* writes a proposal (app/bills.py) with the order's supplier and lines and the expense account,
    which waits in Review for the user to approve. Nothing is posted until they do.
  * *Match a bill* links a bill that has arrived (a proposal waiting in Review, or already posted) to the order. The
    supplier must be the same; an amount that differs is shown as a variance, not refused: suppliers do add
    delivery. The link is a pointer; it changes nothing in the ledger.
  Either way the order is `billed`. A link to a bill that was rejected, or is still only a proposal, can be removed.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from accnomos_connectors.base import MailSender, OutgoingAttachment, OutgoingMail
from app import bills
from app import invoicing as inv_
from app.autopilot import supplier_key
from app.books import Books, now
from app.books import today as london_today
from app.invoicing import (
    EMAIL_RE,
    InvoiceCustomer,
    InvoiceError,
    InvoiceLine,
    InvoiceProfile,
    InvoiceStateError,
    LineIn,
    VatSummaryRow,
    money,
    price_lines,
    uk_date,
)
from app.items import load_items
from app.numbering import NUMBER_RE, allocate, safe_number
from app.paths import SYSTEM
from app.pdf_docs import Party, TradeDoc, render_trade_document
from app.schemas import Proposal
from app.validation import LENIENT, Day, StrictBody

ORDERS = f"{SYSTEM}/PurchaseOrders"
ORDERS_SENT = f"{ORDERS}/sent"
SEQUENCE = f"{ORDERS}/sequence.json"
CONTACTS = inv_.CONTACTS
POStatus = Literal["draft", "approved", "sent", "billed", "cancelled"]
EDITABLE = ("draft",)
BILLABLE = ("approved", "sent")
CANCELLABLE = ("draft", "approved", "sent")


class PurchaseOrderDraft(StrictBody):
    supplier: InvoiceCustomer  # the same fields as a customer: name, email, address, VAT number, contact id
    issue_date: Day | None = None  # default: today
    delivery_date: Day | None = None
    delivery_address: str | None = Field(None, max_length=500)
    lines: list[LineIn] = Field(min_length=1, max_length=100)  # unit prices are what you expect to pay, ex VAT
    reference: str | None = Field(None, max_length=60)  # your own reference or job
    notes: str | None = Field(None, max_length=1000)
    account: str | None = Field(None, max_length=60)  # the expense account the bill proposes (e.g. 5000 Materials)


class BillLink(BaseModel):
    proposal_id: str
    kind: Literal["converted", "matched"]
    linked_at: datetime
    linked_by: str


class PurchaseOrder(BaseModel):
    number: str
    status: POStatus = "draft"
    supplier: InvoiceCustomer
    issue_date: date
    delivery_date: date | None = None
    delivery_address: str | None = None
    lines: list[InvoiceLine]
    vat_summary: list[VatSummaryRow]
    net_pence: int
    vat_pence: int
    total_pence: int
    reference: str | None = None
    notes: str | None = None
    account: str | None = None
    created_by: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    approved_at: datetime | None = None
    approved_by: str | None = None
    sent_at: datetime | None = None
    sent_to: str | None = None
    sent_by: str | None = None
    pdf_sha256: str | None = None
    bill: BillLink | None = None
    conversions: int = 0  # bills made from it so far (a rejected bill can be made again; each gets its own id)
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None


def build_order(number: str, draft: PurchaseOrderDraft, user: str, today: date | None = None) -> PurchaseOrder:
    issue = draft.issue_date or today or london_today()
    if draft.delivery_date and draft.delivery_date < issue:
        raise InvoiceError("The delivery date is before the order date")
    if draft.account is not None and not _expense(draft.account):
        raise InvoiceError('The expense account is a 5000-8999 account, e.g. "5000 Materials"')
    lines, summary, net, vat = price_lines(draft.lines)
    return PurchaseOrder(
        number=number,
        supplier=draft.supplier,
        issue_date=issue,
        delivery_date=draft.delivery_date,
        delivery_address=(draft.delivery_address or "").strip() or None,
        lines=lines,
        vat_summary=summary,
        net_pence=net,
        vat_pence=vat,
        total_pence=net + vat,
        reference=(draft.reference or "").strip() or None,
        notes=(draft.notes or "").strip() or None,
        account=(draft.account or "").strip() or None,
        created_by=user,
    )


def _expense(account: str) -> bool:
    from app.items import EXPENSE_RE

    return bool(EXPENSE_RE.fullmatch(account.strip()))


def _path(number: str) -> str:
    return f"{ORDERS}/{safe_number(number)}.json"


async def get_order(books: Books, number: str) -> PurchaseOrder:
    """Raises FileNotFoundError, also for ids that could step outside the orders folder."""
    return PurchaseOrder.model_validate_json(await books.storage.read(_path(number)), **LENIENT)


async def save_order(books: Books, po: PurchaseOrder) -> None:
    po.updated_at = now()
    await books.write_json(_path(po.number), po.model_dump(mode="json"))


async def list_orders(books: Books) -> list[PurchaseOrder]:
    """Newest first."""
    files = [f for f in await books.list_files(ORDERS) if f.name.endswith(".json") and NUMBER_RE.fullmatch(f.name[:-5])]
    files = [f for f in files if f.name != "sequence.json"]

    async def read_one(path: str) -> PurchaseOrder:
        return PurchaseOrder.model_validate_json(await books.storage.read(path), **LENIENT)

    out = await asyncio.gather(*(read_one(f.path) for f in files))
    return sorted(out, key=lambda p: (p.issue_date, p.number), reverse=True)


async def suppliers(books: Books) -> list[InvoiceCustomer]:
    """Suppliers in the contact book (kind supplier or both), for the picker."""
    out = []
    for c in await books.read_json(CONTACTS, []):
        if isinstance(c, dict) and c.get("id") and c.get("name") and c.get("kind") in ("supplier", "both"):
            try:
                out.append(
                    InvoiceCustomer(
                        contact_id=c["id"],
                        name=c["name"],
                        email=c.get("email") or None,
                        address=c.get("address") or None,
                        vrn=c.get("vrn") or None,
                    )
                )
            except ValueError:
                out.append(
                    InvoiceCustomer(
                        contact_id=c["id"], name=c["name"], address=c.get("address") or None, email=None, vrn=None
                    )
                )
    return sorted(out, key=lambda c: c.name.lower())


async def _fill_supplier(books: Books, draft: PurchaseOrderDraft) -> PurchaseOrderDraft:
    s = draft.supplier
    if not s.contact_id or not (known := await inv_.customer_from_contact(books, s.contact_id)):
        return draft
    filled = s.model_copy(update={k: getattr(known, k) for k in ("email", "address", "vrn") if not getattr(s, k)})
    return draft.model_copy(update={"supplier": filled})


async def create_order(books: Books, draft: PurchaseOrderDraft, user: str) -> PurchaseOrder:
    draft = await _fill_supplier(books, draft)
    build_order("PENDING", draft, user)  # refuse a bad draft before taking a number
    po = build_order(await allocate(books, SEQUENCE, "PO-", _path), draft, user)
    await save_order(books, po)
    await books.audit(f"user:{user}", "purchase_order_created", {"order": po.number, "total_pence": po.total_pence})
    return po


async def update_draft(books: Books, number: str, draft: PurchaseOrderDraft, user: str) -> PurchaseOrder:
    old = await get_order(books, number)
    if old.status not in EDITABLE:
        raise InvoiceStateError(f"Purchase order {number} is {old.status}; only drafts can be changed")
    po = build_order(number, await _fill_supplier(books, draft), old.created_by)
    po.created_at = old.created_at
    await save_order(books, po)
    await books.audit(f"user:{user}", "purchase_order_edited", {"order": number, "total_pence": po.total_pence})
    return po


# --------------------------------------------------------------------------- #
# Approve, PDF and email
# --------------------------------------------------------------------------- #


async def approve_order(books: Books, number: str, user: str) -> PurchaseOrder:
    po = await get_order(books, number)
    if po.status != "draft":
        raise InvoiceStateError(f"Purchase order {number} is {po.status}; only a draft can be approved")
    if po.total_pence <= 0:
        raise InvoiceError("The order total must be more than £0.00")
    po.status, po.approved_at, po.approved_by = "approved", now(), user
    await save_order(books, po)
    await books.audit(f"user:{user}", "purchase_order_approved", {"order": number, "total_pence": po.total_pence})
    return po


def render_order(po: PurchaseOrder, profile: InvoiceProfile, logo: bytes | None = None) -> bytes:
    meta = [("Order number", po.number), ("Order date", uk_date(po.issue_date))]
    if po.delivery_date:
        meta.append(("Delivery date", uk_date(po.delivery_date)))
    if po.reference:
        meta.append(("Our reference", po.reference))
    parties = [
        Party(
            "SUPPLIER",
            po.supplier.name,
            [*(po.supplier.address or "").splitlines(), f"VAT no: {po.supplier.vrn}" if po.supplier.vrn else ""],
        )
    ]
    if po.delivery_address:
        parties.append(Party("DELIVER TO", profile.name or "", po.delivery_address.splitlines()))
    return render_trade_document(
        TradeDoc(
            title="PURCHASE ORDER",
            pdf_title=f"Purchase order {po.number}",
            meta=meta,
            parties=parties,
            lines=po.lines,
            vat_summary=po.vat_summary,
            net_pence=po.net_pence,
            vat_pence=po.vat_pence,
            total_pence=po.total_pence,
            total_label="Order total",
            paragraphs=[
                f"Please quote {po.number} on your invoice and delivery note.",
                po.notes or "",
                profile.footer_note or "",
            ],
        ),
        profile,
        logo,
    )


def send_problems(po: PurchaseOrder, profile: InvoiceProfile, to: str | None) -> list[str]:
    out = []
    if po.status != "approved":
        out.append(
            f"Purchase order {po.number} is {po.status}" + ("; approve it first" if po.status == "draft" else "")
        )
    if not to or not EMAIL_RE.fullmatch(to):
        out.append("Add the supplier's email address")
    if not profile.name.strip() or not profile.address.strip():
        out.append("Add your business name and address in the invoice profile")
    return out


def default_email(po: PurchaseOrder, profile: InvoiceProfile) -> tuple[str, str]:
    who = profile.name.strip() or "us"
    when = f", for delivery by {uk_date(po.delivery_date)}" if po.delivery_date else ""
    body = "\n".join(
        [
            "Hello,",
            "",
            f"Please find attached purchase order {po.number} for {money(po.total_pence)}{when}.",
            f"Please quote {po.number} on your invoice.",
            "",
            "Many thanks,",
            who,
        ]
    )
    return f"Purchase order {po.number} from {who}", body


async def send_order(
    books: Books,
    sender: MailSender,
    number: str,
    user: str,
    pdf: bytes,
    *,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> PurchaseOrder:
    """Email the approved order to the supplier, then mark it sent (the email first: it cannot be taken back)."""
    po = await get_order(books, number)
    profile = await inv_.load_profile(books)
    to = (to or po.supplier.email or "").strip()
    if problems := send_problems(po, profile, to):
        raise (InvoiceStateError if po.status != "approved" else InvoiceError)("; ".join(problems))
    d_subject, d_body = default_email(po, profile)
    await sender.send(
        OutgoingMail(
            to=to,
            subject=(subject or "").strip() or d_subject,
            body_text=(body or "").strip() or d_body,
            attachments=[OutgoingAttachment(name=f"{po.number}.pdf", content_type="application/pdf", data=pdf)],
        )
    )
    sha = hashlib.sha256(pdf).hexdigest()
    po.status, po.sent_at, po.sent_to, po.sent_by, po.pdf_sha256 = "sent", now(), to, user, sha
    await save_order(books, po)
    await books.storage.write(f"{ORDERS_SENT}/{po.number}.pdf", pdf)
    await books.audit(f"user:{user}", "purchase_order_sent", {"order": po.number, "to": to, "pdf_sha256": sha})
    return po


async def mark_sent(books: Books, number: str, user: str) -> PurchaseOrder:
    """The order was given to the supplier another way (phone, their portal)."""
    po = await get_order(books, number)
    if po.status != "approved":
        raise InvoiceStateError(f"Purchase order {number} is {po.status}; only an approved order can be marked as sent")
    po.status, po.sent_at, po.sent_by = "sent", now(), user
    await save_order(books, po)
    await books.audit(f"user:{user}", "purchase_order_marked_sent", {"order": number})
    return po


async def sent_pdf(books: Books, number: str) -> bytes | None:
    try:
        return await books.storage.read(f"{ORDERS_SENT}/{safe_number(number)}.pdf")
    except FileNotFoundError:
        return None


async def cancel_order(books: Books, number: str, user: str, reason: str) -> PurchaseOrder:
    po = await get_order(books, number)
    if po.status not in CANCELLABLE:
        raise InvoiceStateError(
            f"Purchase order {number} is {po.status}"
            + ("; unlink its bill first" if po.status == "billed" else " and cannot be cancelled")
        )
    if not reason.strip():
        raise InvoiceError("Say why the order is cancelled")
    po.status, po.cancelled_at, po.cancel_reason = "cancelled", now(), reason.strip()
    await save_order(books, po)
    await books.audit(f"user:{user}", "purchase_order_cancelled", {"order": number, "reason": po.cancel_reason})
    return po


# --------------------------------------------------------------------------- #
# Bills: convert, match, unlink
# --------------------------------------------------------------------------- #


def lines_in(po: PurchaseOrder) -> list[LineIn]:
    return [
        LineIn(
            description=ln.description,
            quantity=ln.quantity,
            unit=ln.unit,
            unit_price_pence=ln.unit_price_pence,
            vat_code=ln.vat_code,
            item_code=ln.item_code,
        )
        for ln in po.lines
    ]


async def convert_to_bill(
    books: Books, number: str, user: str, bill_date: date | None = None
) -> tuple[PurchaseOrder, Proposal]:
    """Write the bill proposal for an approved or sent order. It waits in Review; nothing is posted."""
    po = await get_order(books, number)
    if po.status == "billed" and po.bill:
        raise InvoiceStateError(
            f"Purchase order {number} already has a bill ({po.bill.proposal_id[:8]}…); unlink it first"
        )
    if po.status not in BILLABLE:
        raise InvoiceStateError(
            f"Purchase order {number} is {po.status}; only an approved or sent order can become a bill"
        )
    lines = lines_in(po)
    accounts = {i.code: i.expense_account for i in await load_items(books)}
    account = po.account or bills.dominant_account(lines, accounts)
    p = await bills.make_bill_proposal(
        books,
        pid=bills.proposal_id("purchase_order", po.number, str(po.conversions)),
        evidence=f"purchase_order:{po.number}:{po.conversions}",
        source=f"Purchase order {po.number}",
        note=f"Made by code from purchase order {po.number}: lines, VAT and total are the order's. "
        "Check them against the supplier's bill before approving.",
        supplier_name=po.supplier.name,
        contact_id=po.supplier.contact_id,
        supplier_vat_number=po.supplier.vrn,
        bill_date=bill_date or london_today(),
        lines=lines,
        account=account,
        model="code:purchase-order",
    )
    po.conversions += 1
    po.status, po.bill = "billed", BillLink(proposal_id=p.id, kind="converted", linked_at=now(), linked_by=user)
    await save_order(books, po)
    await books.audit(
        f"user:{user}",
        "purchase_order_converted",
        {"order": number, "proposal": p.id, "total_pence": po.total_pence, "account": account},
    )
    return po, p


class BillCandidate(BaseModel):
    proposal_id: str
    status: str  # proposed | needs_a_look | posted
    supplier: str
    date: str
    invoice_number: str | None
    gross_pence: int
    variance_pence: int  # the bill minus the order (0: an exact match)
    exact: bool
    linked_to: str | None = None  # another order already points at it


def _gross(p: Proposal) -> int:
    return round(p.extracted.gross_total * 100)


async def _linked(books: Books) -> dict[str, str]:
    return {po.bill.proposal_id: po.number for po in await list_orders(books) if po.bill and po.status == "billed"}


async def bill_candidates(books: Books, number: str) -> list[BillCandidate]:
    """Bills from this order's supplier that could be the one: proposals waiting in Review or posted, exact totals
    first, then nearest in amount. A bill another order already points at is listed but marked."""
    po = await get_order(books, number)
    who = supplier_key(po.supplier.name)
    taken = await _linked(books)
    out = []
    for p in await books.list_proposals():
        d = p.extracted
        if p.status not in ("proposed", "needs_a_look", "posted") or d.doc_type != "purchase_invoice":
            continue
        if p.mileage_claim or supplier_key(d.supplier_name) != who:
            continue
        gross = _gross(p)
        out.append(
            BillCandidate(
                proposal_id=p.id,
                status=p.status,
                supplier=d.supplier_name,
                date=d.date,
                invoice_number=d.invoice_number,
                gross_pence=gross,
                variance_pence=gross - po.total_pence,
                exact=gross == po.total_pence,
                linked_to=taken.get(p.id) if taken.get(p.id) != po.number else None,
            )
        )
    return sorted(out, key=lambda c: (c.linked_to is not None, abs(c.variance_pence), c.date))[:30]


async def match_bill(books: Books, number: str, proposal_id: str, user: str) -> PurchaseOrder:
    po = await get_order(books, number)
    if po.bill:
        raise InvoiceStateError(f"Purchase order {number} already has a bill; unlink it first")
    if po.status not in BILLABLE:
        raise InvoiceStateError(
            f"Purchase order {number} is {po.status}; only an approved or sent order can be matched"
        )
    try:
        p = await books.get_proposal(proposal_id)
    except FileNotFoundError as exc:
        raise InvoiceError("No such bill") from exc
    d = p.extracted
    if p.status == "rejected" or d.doc_type != "purchase_invoice" or p.mileage_claim:
        raise InvoiceError("That is not a bill that can be matched")
    if supplier_key(d.supplier_name) != supplier_key(po.supplier.name):
        raise InvoiceError(f"That bill is from {d.supplier_name}, not {po.supplier.name}")
    if other := (await _linked(books)).get(p.id):
        raise InvoiceStateError(f"That bill is already matched to {other}")
    po.status, po.bill = "billed", BillLink(proposal_id=p.id, kind="matched", linked_at=now(), linked_by=user)
    await save_order(books, po)
    await books.audit(
        f"user:{user}",
        "purchase_order_matched",
        {"order": number, "proposal": p.id, "variance_pence": _gross(p) - po.total_pence},
    )
    return po


async def unlink_bill(books: Books, number: str, user: str) -> PurchaseOrder:
    """Take the link back so the order can be matched or converted again. A bill already posted stays in the books;
    undo it from Review if it was wrong."""
    po = await get_order(books, number)
    if po.status != "billed" or po.bill is None:
        raise InvoiceStateError(f"Purchase order {number} has no bill linked")
    try:
        p = await books.get_proposal(po.bill.proposal_id)
        if p.status == "posted":
            raise InvoiceStateError(
                f"The bill for {number} is posted to your books; undo it in Review first, then unlink it"
            )
    except FileNotFoundError:
        pass
    was = po.bill.proposal_id
    po.status, po.bill = ("sent" if po.sent_at else "approved"), None
    await save_order(books, po)
    await books.audit(f"user:{user}", "purchase_order_unlinked", {"order": number, "proposal": was})
    return po


class OrderBill(BaseModel):
    """The linked bill as it stands now (worked out on every read)."""

    proposal_id: str
    kind: Literal["converted", "matched"]
    status: str  # proposed | needs_a_look | posted | rejected | missing
    gross_pence: int | None
    variance_pence: int | None
    invoice_number: str | None
    event_id: str | None


class OrderRow(PurchaseOrder):
    bill_now: OrderBill | None = None
    overdue_days: int | None = None  # past its delivery date and not yet billed


def row(po: PurchaseOrder, proposals: dict[str, Proposal], today: date | None = None) -> OrderRow:
    today = today or london_today()
    now_bill = None
    if po.bill:
        p = proposals.get(po.bill.proposal_id)
        now_bill = OrderBill(
            proposal_id=po.bill.proposal_id,
            kind=po.bill.kind,
            status=p.status if p else "missing",
            gross_pence=_gross(p) if p else None,
            variance_pence=_gross(p) - po.total_pence if p else None,
            invoice_number=p.extracted.invoice_number if p else None,
            event_id=p.event_id if p else None,
        )
    late = (
        (today - po.delivery_date).days
        if po.delivery_date and po.status in BILLABLE and po.delivery_date < today
        else None
    )
    return OrderRow(**po.model_dump(), bill_now=now_bill, overdue_days=late)


async def rows(books: Books) -> list[OrderRow]:
    orders = await list_orders(books)
    proposals = {p.id: p for p in await books.list_proposals()} if any(o.bill for o in orders) else {}
    return [row(o, proposals) for o in orders]
