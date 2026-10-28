"""Unmatched bank lines: what a person can do with one (F7).

- create expense proposal: an open proposal (needs a look) built from the line, so the payment can be
  booked even without a receipt. It is approved on /review like any other; once posted, its 1200 Bank
  leg matches the line through the normal suggestions.
- mark as private: personal spending (a sole trader's Drawings, a company's Director's loan), also an
  open proposal approved on /review. It posts nothing to expenses and never touches VAT.
- mark as transfer: money between the user's own accounts; nothing to book.
- ignore: nothing to book (zero lines, reversals, money in that isn't income).

Nothing here posts to the ledger.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import uuid

from pydantic import BaseModel

from accnomos_ledger.bank import FEE_WORDS, ActionHint, BankLine, suggest_action
from app.books import BankMatchError, Books, now
from app.journal import draft_journal
from app.schemas import Check, ExtractedDoc, PaymentMethod, Proposal, ProposalStatus

MODEL = "bank-line"  # in place of the extraction model's name: no model read anything
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def suggested_filename_for_line(line: BankLine) -> str:
    """'2026-10-21 Screwfix': the date and a filesystem-safe description. A bank line has no receipt file of
    its own, so the name carries no extension (and never .csv)."""
    desc = re.sub(r"\s+", " ", _UNSAFE_FILENAME.sub(" ", line.description or line.reference or "")).strip(" .")
    return f"{line.date.isoformat()} {desc[:60] or 'Bank payment'}"


class UnmatchedLine(BaseModel):
    line: BankLine
    suggested: ActionHint
    # Status of the expense proposal made from this line (line.proposal_id); None when there is none.
    # After "rejected" the user may create a fresh one.
    proposal_status: ProposalStatus | None = None


def _payment_method(text: str) -> PaymentMethod:
    if re.search(r"\b(dd|direct debit|directdeb)\b", text, re.IGNORECASE):
        return "direct_debit"
    if re.search(r"\b(card|cd|clp|pos|visa|contactless)\b", text, re.IGNORECASE):
        return "card"
    return "bank_transfer"


def proposal_from_line(line: BankLine) -> Proposal:
    """An expense proposal for money out with no receipt. No VAT is claimed: without a VAT invoice
    the gross is the cost (code N); attach the receipt and edit the VAT on /review if there is one."""
    if line.amount_pence >= 0:
        raise BankMatchError("Only money out can become an expense")
    text = f"{line.description} {line.reference or ''}"
    gross = -line.amount_pence / 100
    doc = ExtractedDoc(
        doc_type="receipt",
        supplier_name=line.description or "Bank payment",
        supplier_vat_number=None,
        customer_name=None,
        invoice_number=line.reference,
        date=line.date.isoformat(),
        currency="GBP",
        lines=[],
        net_total=gross,
        vat_total=0,
        gross_total=gross,
        payment_method=_payment_method(text),
        card_last4=None,
        category_guess="Bank charges" if FEE_WORDS.search(text) else "Sundry",
        confidence=0.0,
    )
    note = Check(
        code="bank_line",
        ok=False,
        severity="fail",
        message=f"Made from a bank statement line, not a receipt ({line.source_file}). Check the category; "
        "no VAT is reclaimed unless you add a VAT receipt.",
    )
    return Proposal(
        id=uuid.uuid4().hex,
        # The evidence is the bank line itself; this hash keeps it apart from real document hashes.
        doc_sha256=hashlib.sha256(f"bank-line:{line.id}".encode()).hexdigest(),
        extracted=doc,
        checks=[note],
        status="needs_a_look",
        reasons=[f"{note.code}: {note.message}"],
        suggested_filename=suggested_filename_for_line(line),
        journal_draft=draft_journal(doc),
        model=MODEL,
        elapsed_s=0.0,
        source_name=line.source_file,
        created_at=now(),
    )


async def _open_proposal(books: Books, line_id: str) -> Proposal | None:
    """The line's live proposal, if it still has one (a rejection frees the line for a fresh one)."""
    line = await books.find_bank_line(line_id)
    if line.resolved:
        raise BankMatchError("This bank line is already settled; undo that first")
    if not line.proposal_id:
        return None
    try:
        earlier = await books.get_proposal(line.proposal_id)
    except FileNotFoundError:
        return None  # the proposal file was removed by hand: make a new one
    return earlier if earlier.status != "rejected" else None


async def create_expense_proposal(books: Books, line_id: str, user: str) -> Proposal:
    """Raises FileNotFoundError / BankMatchError. Asking twice returns the first proposal, unless the
    user rejected it on /review: then a fresh one is made."""
    if (earlier := await _open_proposal(books, line_id)) is not None:
        return earlier
    p = proposal_from_line(await books.find_bank_line(line_id))
    await books.save_proposal(p)
    await books.link_proposal(line_id, p.id)
    await books.audit(f"user:{user}", "bank_expense_proposed", {"line": line_id, "proposal": p.id})
    await books.rebuild_safely(f"user:{user}")
    return p


async def create_private_proposal(books: Books, line_id: str, user: str) -> Proposal:
    """Mark the line's money as personal spending through the proposal/approve flow: an open proposal
    with 0 % business use, approved on /review like any other. Approving posts Dr Drawings (sole trader)
    or Dr Director's loan (company, read from the invoice profile) against Cr 1200 Bank: nothing to
    expenses, never any VAT. Raises FileNotFoundError / BankMatchError; asking twice returns the first."""
    from app.invoicing import load_profile  # local: invoicing imports approve, not this module
    from app.journal import private_account, split_business_use

    if (earlier := await _open_proposal(books, line_id)) is not None:
        return earlier
    line = await books.find_bank_line(line_id)
    if line.amount_pence >= 0:
        raise BankMatchError("Only money out can be marked private")
    profile = await load_profile(books)
    account = private_account(profile.company_number)
    p = proposal_from_line(line)
    p.business_use_percent = 0
    p.checks = [
        Check(
            code="bank_line",
            ok=False,
            severity="fail",
            message=f"Marked as private spending, not a business cost ({line.source_file}). Approving posts it "
            f"to {account}, with no VAT; reject it to code it as a business expense instead.",
        )
    ]
    p.reasons = [f"{p.checks[0].code}: {p.checks[0].message}"]
    p.journal_draft = split_business_use(p.journal_draft, 0, account)
    await books.save_proposal(p)
    await books.link_proposal(line_id, p.id)
    await books.audit(f"user:{user}", "bank_private_proposed", {"line": line_id, "proposal": p.id})
    await books.rebuild_safely(f"user:{user}")
    return p


async def unmatched_lines(books: Books) -> list[UnmatchedLine]:
    """Open lines with no suggested match, each with the likeliest action and its proposal's status."""
    out = []
    for ln in await books.list_bank_lines("unmatched"):
        status = None
        if ln.proposal_id:
            with contextlib.suppress(FileNotFoundError):
                status = (await books.get_proposal(ln.proposal_id)).status
        out.append(UnmatchedLine(line=ln, suggested=suggest_action(ln), proposal_status=status))
    return out
