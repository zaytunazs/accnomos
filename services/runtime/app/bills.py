"""Bills made by code: a purchase order converted to a bill, and a repeating bill.

A bill in Accnomos is a proposal in Review (app/approve.py posts it when the user approves: Dr expense, Dr 2200 VAT
control, Cr 2100 Creditors, so it is owed until paid). Normally the proposal is read from a photo or PDF by the model.
Here code writes it from lines the user already wrote and priced, so nothing is read and nothing is guessed:

    lines   -> ExtractedLine, priced by app/invoicing.price_lines (quantity x unit price, VAT per line, half up)
    totals  -> sums of those lines, in pence
    checks  -> the same checks a scanned bill gets (arithmetic, VAT number, date ...), confidence 1
    account -> the expense account to post to (a proposal's `account_override`), else the category's

The proposal is NOT posted. It waits in Review for the user to approve (or, for a repeating bill the user set to
"approve automatically", app/repeating.py approves it in advance and the audit log says so). One account per bill: a
bill with lines for different expense accounts posts them all to the first account, which the Review card shows and
the user can change before approving.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
from decimal import Decimal

from app import contacts as cb
from app.approve import final_journal
from app.books import Books, now
from app.checks import decide, normalise_vat_number, run_checks
from app.invoicing import RATES, InvoiceError, LineIn, load_profile, price_lines
from app.journal import CATEGORY_ACCOUNTS
from app.schemas import CATEGORIES, Check, ExtractedDoc, ExtractedLine, Proposal

#: Account -> the category name the Review card shows for it (the reverse of journal.CATEGORY_ACCOUNTS).
_CATEGORY_OF = {account: category for category, account in CATEGORY_ACCOUNTS.items() if category in CATEGORIES}


def proposal_id(*parts: str) -> str:
    """A proposal id that is the same every time for the same source, so making it twice finds the first."""
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:32]


def _pounds(p: int) -> float:
    return round(p / 100, 2)


def extracted_doc(
    *,
    supplier_name: str,
    supplier_vrn: str | None,
    bill_date: date,
    lines: list[LineIn],
    account: str | None,
    invoice_number: str | None = None,
) -> tuple[ExtractedDoc, int]:
    """(the bill as Review shows it, its gross in pence). Raises InvoiceError for a bill that totals nothing."""
    priced, _summary, net, vat = price_lines(lines)
    if net + vat <= 0:
        raise InvoiceError("A bill must total more than £0.00")
    return (
        ExtractedDoc(
            doc_type="purchase_invoice",
            supplier_name=supplier_name.strip(),
            supplier_vat_number=supplier_vrn,
            customer_name=None,
            invoice_number=invoice_number,
            original_invoice_number=None,
            date=bill_date.isoformat(),
            currency="GBP",
            lines=[
                ExtractedLine(
                    description=ln.description,
                    qty=float(ln.quantity),
                    unit_price=_pounds(ln.unit_price_pence),
                    net=_pounds(ln.net_pence),
                    vat_rate=RATES[ln.vat_code],
                    vat=_pounds(ln.vat_pence),
                )
                for ln in priced
            ],
            net_total=_pounds(net),
            vat_total=_pounds(vat),
            gross_total=_pounds(net + vat),
            payment_method=None,  # not paid yet: it goes on account (2100 Creditors) until a payment is recorded
            card_last4=None,
            category_guess=_CATEGORY_OF.get(account or "", "Sundry"),
            confidence=1.0,
        ),
        net + vat,
    )


async def supplier_vrn(books: Books, name: str, contact_id: str | None, given: str | None) -> str | None:
    """The VAT number to put on the bill: the one given, else the contact's, else the book's contact of that name."""
    if n := normalise_vat_number(given):
        return n
    try:
        contacts = await cb.stored_contacts(books)
    except ValueError:  # a hand-broken contacts.json
        return None
    hit = next((c for c in contacts if c.id == contact_id), None) if contact_id else None
    hit = hit or cb.find(contacts, cb.supplier_key(name), None)
    return normalise_vat_number(hit.vrn) if hit and hit.vrn else None


async def make_bill_proposal(
    books: Books,
    *,
    pid: str,
    evidence: str,
    source: str,
    note: str,
    supplier_name: str,
    contact_id: str | None,
    supplier_vat_number: str | None,
    bill_date: date,
    lines: list[LineIn],
    account: str | None,
    model: str,
) -> Proposal:
    """Save a new proposal for a bill written by code and return it (or the one already saved under `pid`)."""
    try:
        return await books.get_proposal(pid)
    except FileNotFoundError:
        pass
    vrn = await supplier_vrn(books, supplier_name, contact_id, supplier_vat_number)
    doc, gross = extracted_doc(
        supplier_name=supplier_name, supplier_vrn=vrn, bill_date=bill_date, lines=lines, account=account
    )
    sha = hashlib.sha256(evidence.encode()).hexdigest()
    profile = await load_profile(books)
    try:
        contacts = await cb.stored_contacts(books)
    except ValueError:
        contacts = []
    checks: list[Check] = run_checks(
        doc,
        known_hashes=set(),
        this_hash=sha,
        supplier=cb.supplier_knowledge(contacts, doc),
        business_vat_registered=profile.is_vat_registered,
    )
    checks.append(Check(code="MADE_BY_CODE", ok=True, severity="warn", message=note))
    status, reasons = decide(checks)
    p = Proposal(
        id=pid,
        doc_sha256=sha,
        extracted=doc,
        checks=checks,
        status=status,
        reasons=reasons,
        suggested_filename=f"{supplier_name.strip()} {bill_date.isoformat()} £{gross / 100:.2f}",
        journal_draft=[],
        model=model,
        elapsed_s=0,
        source_name=source,
        account_override=account,
        created_at=now(),
    )
    p.journal_draft = await final_journal(books, p)
    await books.save_proposal(p)
    return p


def dominant_account(lines: list[LineIn], accounts: dict[str, str]) -> str | None:
    """The expense account most of the lines' net goes to, from the catalogue accounts of the items they came from."""
    net: Counter[str] = Counter()
    for ln in lines:
        if ln.item_code and (acct := accounts.get(ln.item_code)):
            net[acct] += abs(int(Decimal(ln.quantity) * ln.unit_price_pence))
    return net.most_common(1)[0][0] if net else None
