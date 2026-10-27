"""A human decides: approve (post a balanced ledger event) or reject (park the document for a look).

Agents never approve on their own: `user` is the person who tapped the button, or "autopilot" when
the scan applies a rule that person saved with "Always do this" (app/autopilot.py). Any posting can
be undone, which appends a reversal event; nothing in the ledger is ever edited or deleted.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app.autopilot import ACTOR as AUTOPILOT_ACTOR
from app.autopilot import AUTOPILOT, rule_from_proposal, save_rule
from app.books import Books, Rule, RuleMatch, now
from app.checks import decide
from app.journal import VAT_CONTROL, draft_journal, with_expense_account
from app.mileage import load_vehicles
from app.paths import NEEDS_A_LOOK, upgrade
from app.schemas import CATEGORIES, ExtractedDoc, JournalLine, Proposal

#: Edits the review screen may send; `category` maps to the document's category_guess.
DOC_EDITS = {"category", "net_total", "vat_total", "gross_total", "date", "supplier_name", "doc_type", "payment_method"}
OPEN = ("proposed", "needs_a_look")


class ApprovalError(ValueError):
    """The proposal cannot be approved as asked (bad edit, nothing to post)."""


class ProposalStateError(ApprovalError):
    """The proposal has already been decided."""


def apply_edits(p: Proposal, edits: dict[str, Any]) -> None:
    """Apply the user's corrections to the document and the expense account, then redraw the journal.
    (`job_id` and `vehicle_id` are checked against their files and applied by approve().)"""
    unknown = set(edits) - DOC_EDITS - {"account", "job_id", "vehicle_id"}
    if unknown:
        raise ApprovalError(f"Can't edit {', '.join(sorted(unknown))}")
    if p.mileage_claim and edits:
        raise ApprovalError("A mileage claim is calculated by code: change the mileage log on Vehicles instead")
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
        Line(
            account=j.account,
            debit=j.debit_pence,
            credit=j.credit_pence,
            vat_code=VatCode(j.vat_code) if j.vat_code else None,
        )
        for j in journal
        if j.debit_pence or j.credit_pence
    ]
    if len(lines) < 2:
        raise ApprovalError("Nothing to post: enter the amounts first")
    sale = doc.doc_type == "sales_invoice"
    vat = sum((j.credit_pence if sale else j.debit_pence) for j in journal if j.account == VAT_CONTROL)
    gross = sum(j.debit_pence for j in journal)
    # One event per approval: a retried approval cannot post twice. After an undo the proposal
    # can be approved again, so each later approval gets its own (still deterministic) id.
    event_id = hashlib.sha256(f"{p.id}:{len(p.undone_events)}".encode()).hexdigest()[:32] if p.undone_events else p.id
    try:
        return LedgerEvent(
            id=event_id,
            kind="sale" if sale else "purchase",
            date=when,
            lines=lines,
            evidence=[p.doc_sha256],
            approved_by=user,
            approved_at=now(),
            proposal_id=p.id,
            net=gross - vat,
            vat=vat,
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
    books: Books,
    proposal_id: str,
    user: str,
    edits: dict[str, Any] | None = None,
    always: bool = False,
    *,
    rebuild: bool = True,
) -> Proposal:
    """Post the proposal to the ledger as `user`; with `always`, remember this supplier's treatment
    (the account rule and the Autopilot rule)."""
    p = await _open_proposal(books, proposal_id)
    apply_edits(p, edits or {})
    if "job_id" in (edits or {}):
        p.job_id = await _job_tag(books, p, (edits or {})["job_id"])
    if "vehicle_id" in (edits or {}):
        p.vehicle_id = await _vehicle_tag(books, p, (edits or {})["vehicle_id"])
    always = always and p.mileage_claim is None  # Autopilot never posts a mileage claim
    p.journal_draft = final_journal(p)
    event = build_event(p, p.journal_draft, user)
    try:
        event_path = await books.post_event(event)
    except FileExistsError as exc:
        raise ProposalStateError("Already posted to the ledger") from exc
    if p.file_path and upgrade(p.file_path).startswith(f"{NEEDS_A_LOOK}/"):
        await books.file_document(p, p.file_path, books.filing_folder(p.extracted))
    p.status, p.event_id, p.decided_by, p.decided_at = "posted", event.id, user, now()
    await books.save_proposal(p)
    rule = await _remember(books, p, user) if always else None
    auto_rule = rule_from_proposal(p, user) if always else None
    if auto_rule:
        await save_rule(books, auto_rule)
    await books.audit(
        _actor(user),
        "approved",
        {
            "proposal": p.id,
            "event": event.id,
            "event_path": event_path,
            "doc": p.doc_sha256,
            "edits": sorted((edits or {}).keys()),
            "rule": rule.match.supplier_regex if rule else None,
            "autopilot_rule": auto_rule.supplier_key if auto_rule else None,
            "job": p.job_id,
            "vehicle": p.vehicle_id,
        },
    )
    if rebuild:
        await books.rebuild_safely(_actor(user))
    return p


async def _job_tag(books: Books, p: Proposal, job_id: Any) -> str | None:
    """A purchase may be tagged to a job in the jobs file (its net then counts as a job cost); None clears it."""
    if job_id in (None, ""):
        return None
    if p.extracted.doc_type == "sales_invoice":
        raise ApprovalError("Only purchases can be tagged to a job")
    from app.jobs import load_jobs

    try:
        known = await load_jobs(books)
    except ValueError as exc:  # hand-edited jobs.json: say so rather than fail the request
        raise ApprovalError("The jobs file could not be read, so the purchase can't be tagged") from exc
    if not any(j.id == job_id for j in known):
        raise ApprovalError(f"No such job {job_id!r}")
    return str(job_id)


async def _vehicle_tag(books: Books, p: Proposal, vehicle_id: Any) -> str | None:
    """A purchase may be tagged to a business vehicle (its cost then counts against that vehicle); None clears it."""
    if vehicle_id in (None, ""):
        return None
    if p.extracted.doc_type == "sales_invoice" or p.mileage_claim:
        raise ApprovalError("Only purchase receipts can be tagged to a vehicle")
    try:
        known = await load_vehicles(books)
    except ValueError as exc:  # hand-edited vehicles.json: say so rather than fail the request
        raise ApprovalError("The vehicles file could not be read, so the purchase can't be tagged") from exc
    v = next((v for v in known if v.id == vehicle_id), None)
    if v is None:
        raise ApprovalError(f"No such vehicle {vehicle_id!r}")
    if v.owned_by != "business":
        raise ApprovalError(
            f"{v.name} is a personal vehicle: the mileage allowance"
            " covers its running costs, so receipts aren't tagged to it"
        )
    return v.id


def _actor(user: str) -> str:
    return AUTOPILOT_ACTOR if user == AUTOPILOT else f"user:{user}"


async def _remember(books: Books, p: Proposal, user: str) -> Rule | None:
    """Save 'always use this account for this supplier' (purchases only)."""
    expense = next((j.account for j in p.journal_draft if j.debit_pence and j.account != VAT_CONTROL), None)
    if p.extracted.doc_type == "sales_invoice" or expense is None:
        return None
    rule = Rule(
        match=RuleMatch(supplier_regex=re.escape(p.extracted.supplier_name.strip())), account=expense, source="user"
    )
    await books.add_rule(rule)
    return rule


async def reject(books: Books, proposal_id: str, user: str, reason: str) -> Proposal:
    """Mark rejected and park the document in Needs a look. Nothing is ever deleted."""
    p = await _open_proposal(books, proposal_id)
    if p.file_path:
        await books.file_document(p, p.file_path, NEEDS_A_LOOK)
    p.status, p.reject_reason, p.decided_by, p.decided_at = "rejected", reason, user, now()
    await books.save_proposal(p)
    await books.audit(
        f"user:{user}", "rejected", {"proposal": p.id, "doc": p.doc_sha256, "reason": reason, "path": p.file_path}
    )
    await books.rebuild_safely(f"user:{user}")
    return p


def reversal_of(event: LedgerEvent, user: str) -> LedgerEvent:
    """The event that cancels `event`: every line on the other side, same date, amounts and evidence.

    Dated like the original so the VAT return for that period nets to nothing (vat.py counts
    reversals negatively). Its id is derived from the original's, so a retried undo cannot post twice.
    """
    return LedgerEvent(
        id=hashlib.sha256(f"{event.id}:undo".encode()).hexdigest()[:32],
        kind="reversal",
        date=event.date,
        lines=[
            Line(account=ln.account, debit=ln.credit, credit=ln.debit, vat_code=ln.vat_code, memo=f"Undo of {event.id}")
            for ln in event.lines
        ],
        evidence=event.evidence,
        approved_by=user,
        approved_at=now(),
        proposal_id=event.proposal_id,
        reverses=event.id,
        net=event.net,
        vat=event.vat,
        counterparty=event.counterparty,
    )


async def undo(books: Books, event_id: str, user: str) -> tuple[LedgerEvent, Proposal | None]:
    """Append a reversal of `event_id` and put its proposal back in Review. Raises FileNotFoundError
    for an unknown event, ProposalStateError when it is already undone, ApprovalError otherwise."""
    original = await books.get_event(event_id)
    if original.kind == "reversal":
        raise ApprovalError("This entry is itself an undo")
    if any(e.reverses == event_id for e in await books.list_events()):
        raise ProposalStateError("Already undone")
    if any(event_id in ln.event_ids() for ln in await books.stored_bank_lines() if ln.status == "matched"):
        raise ApprovalError("A bank line is matched to this entry; unmatch it first")
    reversal = reversal_of(original, user)
    try:
        path = await books.post_event(reversal)
    except FileExistsError as exc:
        raise ProposalStateError("Already undone") from exc
    p = await _reopen(books, original)
    await books.audit(
        f"user:{user}",
        "undone",
        {
            "event": event_id,
            "reversal": reversal.id,
            "reversal_path": path,
            "proposal": original.proposal_id,
            "originally_approved_by": original.approved_by,
        },
    )
    if original.approved_by == AUTOPILOT:
        await books.audit_autopilot(
            f"user:{user}",
            "undone",
            {
                "event": event_id,
                "reversal": reversal.id,
                "proposal": original.proposal_id,
            },
        )
    await books.rebuild_safely(f"user:{user}")
    return reversal, p


async def _reopen(books: Books, event: LedgerEvent) -> Proposal | None:
    """Back to proposed (or needs a look, if a check fails) so the user can decide again."""
    if not event.proposal_id:
        return None
    try:
        p = await books.get_proposal(event.proposal_id)
    except FileNotFoundError:
        return None
    if p.status != "posted" or p.event_id != event.id:
        return p
    p.status = decide(p.checks)[0]
    p.event_id, p.decided_by, p.decided_at = None, None, None
    p.undone_events.append(event.id)
    if p.file_path:
        await books.file_document(p, p.file_path)
    await books.save_proposal(p)
    return p
