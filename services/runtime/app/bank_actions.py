"""Unmatched bank lines: the three things a person can do with one (F7).

- create expense proposal: an open proposal (needs a look) built from the line, so the payment can be
  booked even without a receipt. It is approved on /review like any other; once posted, its 1200 Bank
  leg matches the line through the normal suggestions.
- mark as transfer: money between the user's own accounts; nothing to book.
- ignore: nothing to book (zero lines, reversals, money in that isn't income).

Nothing here posts to the ledger.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from accnomos_ledger.bank import FEE_WORDS, ActionHint, BankLine, suggest_action
from pydantic import BaseModel

from app.books import BankMatchError, Books, now
from app.journal import draft_journal
from app.schemas import Check, ExtractedDoc, Proposal

MODEL = "bank-line"  # in place of the extraction model's name: no model read anything


class UnmatchedLine(BaseModel):
    line: BankLine
    suggested: ActionHint


def _payment_method(text: str) -> str:
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
        doc_type="receipt", supplier_name=line.description or "Bank payment", supplier_vat_number=None,
        customer_name=None, invoice_number=line.reference, date=line.date.isoformat(), currency="GBP", lines=[],
        net_total=gross, vat_total=0, gross_total=gross, payment_method=_payment_method(text), card_last4=None,
        category_guess="Bank charges" if FEE_WORDS.search(text) else "Sundry", confidence=0.0,
    )
    note = Check(code="bank_line", ok=False, severity="fail",
                 message=f"Made from a bank statement line, not a receipt ({line.source_file}). Check the category; "
                         "no VAT is reclaimed unless you add a VAT receipt.")
    return Proposal(
        id=uuid.uuid4().hex,
        # The evidence is the bank line itself; this hash keeps it apart from real document hashes.
        doc_sha256=hashlib.sha256(f"bank-line:{line.id}".encode()).hexdigest(),
        extracted=doc, checks=[note], status="needs_a_look", reasons=[f"{note.code}: {note.message}"],
        suggested_filename=f"{line.date.isoformat()} {line.description[:40]} £{gross:.2f}.csv",
        journal_draft=draft_journal(doc), model=MODEL, elapsed_s=0.0, source_name=line.source_file, created_at=now(),
    )


async def create_expense_proposal(books: Books, line_id: str, user: str) -> Proposal:
    """Raises FileNotFoundError / BankMatchError. Asking twice returns the first proposal."""
    line = await books.find_bank_line(line_id)
    if line.resolved:
        raise BankMatchError("This bank line is already settled; undo that first")
    if line.proposal_id:
        try:
            return await books.get_proposal(line.proposal_id)
        except FileNotFoundError:
            pass  # the proposal file was removed by hand: make a new one
    p = proposal_from_line(line)
    await books.save_proposal(p)
    await books.link_proposal(line_id, p.id)
    await books.audit(f"user:{user}", "bank_expense_proposed", {"line": line_id, "proposal": p.id})
    await books.rebuild_safely(user)
    return p


async def unmatched_lines(books: Books) -> list[UnmatchedLine]:
    """Open lines with no suggested match, each with the likeliest action."""
    return [UnmatchedLine(line=ln, suggested=suggest_action(ln)) for ln in await books.list_bank_lines("unmatched")]
