"""A human decides: approve (post a balanced ledger event) or reject (park the document for a look).

Agents never approve: `user` is always the person who tapped the button.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from accnomos_ledger.events import LedgerEvent, Line, VatCode

from app.books import NEEDS_A_LOOK, Books, Rule, RuleMatch, now
from app.journal import VAT_CONTROL, draft_journal, with_expense_account
from app.schemas import CATEGORIES, ExtractedDoc, JournalLine, Proposal

#: Edits the review screen may send; `category` maps to the document's category_guess.
DOC_EDITS = {"category", "net_total", "vat_total", "gross_total", "date", "supplier_name", "doc_type", "payment_method"}
OPEN = ("proposed", "needs_a_look")


class ApprovalError(ValueError):
    """The proposal cannot be approved as asked (bad edit, nothing to post)."""


class ProposalStateError(ApprovalError):
    """The proposal has already been decided."""


def apply_edits(p: Proposal, edits: dict[str, Any]) -> None:
    """Apply the user's corrections to the document and the expense account, then redraw the journal."""
    unknown = set(edits) - DOC_EDITS - {"account"}
    if unknown:
        raise ApprovalError(f"Can't edit {', '.join(sorted(unknown))}")
    if "category" in edits and edits["category"] not in CATEGORIES:
        raise ApprovalError(f"Unknown category {edits['category']!r}")
    updates = {("category_guess" if k == "category" else k): v for k, v in edits.items() if k in DOC_EDITS}
    if updates:
        try:
            p.extracted = ExtractedDoc.model_validate({**p.extracted.model_dump(), **updates})
        except ValueError as exc:
            raise ApprovalError(str(exc)) from exc
    if edits.get("account"):
        p.account_override = str(edits["account"]).strip()


def final_journal(p: Proposal) -> list[JournalLine]:
    """Journal rebuilt from the (possibly edited) document, with any account override applied."""
    journal = draft_journal(p.extracted)
    return with_expense_account(journal, p.account_override) if p.account_override else journal


def build_event(p: Proposal, journal: list[JournalLine], user: str) -> LedgerEvent:
    """Balanced LedgerEvent in pence. Raises ApprovalError when there is nothing sensible to post."""
    doc = p.extracted
    if doc.currency != "GBP":
        raise ApprovalError(f"Convert {doc.currency} to GBP before posting")
    try:
        when = date.fromisoformat(doc.date)
    except ValueError as exc:
        raise ApprovalError(f"Date {doc.date!r} is not YYYY-MM-DD") from exc
    lines = [
        Line(account=j.account, debit=j.debit_pence, credit=j.credit_pence,
             vat_code=VatCode(j.vat_code) if j.vat_code else None)
        for j in journal if j.debit_pence or j.credit_pence
    ]
    if len(lines) < 2:
        raise ApprovalError("Nothing to post: enter the amounts first")
    sale = doc.doc_type == "sales_invoice"
    vat = sum((j.credit_pence if sale else j.debit_pence) for j in journal if j.account == VAT_CONTROL)
    gross = sum(j.debit_pence for j in journal)
    try:
        return LedgerEvent(
            id=p.id,  # one event per proposal: a retried approval cannot post twice
            kind="sale" if sale else "purchase", date=when, lines=lines, evidence=[p.doc_sha256],
            approved_by=user, approved_at=now(), proposal_id=p.id, net=gross - vat, vat=vat,
            counterparty=(doc.customer_name if sale else None) or doc.supplier_name,
        )
    except ValueError as exc:  # e.g. unbalanced; draft_journal should make this impossible
        raise ApprovalError(str(exc)) from exc


async def _open_proposal(books: Books, proposal_id: str) -> Proposal:
    p = await books.get_proposal(proposal_id)
    if p.status not in OPEN:
        raise ProposalStateError(f"Proposal is already {p.status}")
    return p


async def approve(
    books: Books, proposal_id: str, user: str, edits: dict[str, Any] | None = None, always: bool = False
) -> Proposal:
    """Post the proposal to the ledger as `user`; with `always`, remember the supplier's account."""
    p = await _open_proposal(books, proposal_id)
    apply_edits(p, edits or {})
    p.journal_draft = final_journal(p)
    event = build_event(p, p.journal_draft, user)
    try:
        event_path = await books.post_event(event)
    except FileExistsError as exc:
        raise ProposalStateError("Already posted to the ledger") from exc
    if p.file_path and p.file_path.startswith(f"{NEEDS_A_LOOK}/"):
        await books.file_document(p, p.file_path, books.filing_folder(p.extracted))
    p.status, p.event_id, p.decided_by, p.decided_at = "posted", event.id, user, now()
    await books.update_proposal(p)
    rule = await _remember(books, p, user) if always else None
    await books.audit(f"user:{user}", "approved", {
        "proposal": p.id, "event": event.id, "event_path": event_path, "doc": p.doc_sha256,
        "edits": sorted((edits or {}).keys()), "rule": rule.match.supplier_regex if rule else None,
    })
    return p


async def _remember(books: Books, p: Proposal, user: str) -> Rule | None:
    """Save 'always use this account for this supplier' (purchases only)."""
    expense = next((j.account for j in p.journal_draft if j.debit_pence and j.account != VAT_CONTROL), None)
    if p.extracted.doc_type == "sales_invoice" or expense is None:
        return None
    rule = Rule(match=RuleMatch(supplier_regex=re.escape(p.extracted.supplier_name.strip())), account=expense, source="user")
    await books.add_rule(rule)
    return rule


async def reject(books: Books, proposal_id: str, user: str, reason: str) -> Proposal:
    """Mark rejected and park the document in "04 Needs a look". Nothing is ever deleted."""
    p = await _open_proposal(books, proposal_id)
    if p.file_path:
        await books.file_document(p, p.file_path, NEEDS_A_LOOK)
    p.status, p.reject_reason, p.decided_by, p.decided_at = "rejected", reason, user, now()
    await books.update_proposal(p)
    await books.audit(f"user:{user}", "rejected", {"proposal": p.id, "doc": p.doc_sha256, "reason": reason, "path": p.file_path})
    return p
