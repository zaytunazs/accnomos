"""/books/bank/*: import bank statement CSVs and match their lines to posted ledger entries (F7).

Matching never posts anything; it records which ledger entry each bank line pays for. Lines nothing
matches can be marked as a transfer, ignored, or turned into an expense proposal for /review.

    POST /import                       upload a CSV (multipart "file"); the same file twice is a no-op
    GET  /statements                   imported statements
    GET  /lines?status=                every line (matched|suggested|unmatched|transfer|ignored)
    GET  /suggestions                  proposed matches (amount ±1p, date ±5 days or up to 60 days later
                                       on terms, counterparty)
    GET  /unmatched                    open lines with no suggestion, each with a suggested action
    POST /lines/{id}/match             confirm: {"event_id": ...} or {"event_ids": [...]}
    POST /lines/{id}/unmatch           reopen a matched, transfer or ignored line
    POST /lines/{id}/transfer          mark as transfer
    POST /lines/{id}/ignore            ignore
    POST /lines/{id}/expense-proposal  create an expense proposal from the line
    GET  /summary                      counts and the "reconciled to" date
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from accnomos_ledger.bank import BankCsvError, BankLine, BankLineStatus, reconciled_to
from accnomos_ledger.matching import Match, settlement_pence
from app.ai.config import ai_config_from_request
from app.bank_actions import UnmatchedLine, create_expense_proposal, unmatched_lines
from app.bank_reconcile import (
    AiSuggestion,
    ReconcileRow,
    approve_line,
    reconcile_lines,
    rule_draft_from_line,
    suggest_ai,
)
from app.bank_rules import BankRule, BankRuleAction, BankRuleMatch, load_bank_rules, save_bank_rules
from app.books import BankImport, BankMatchError, BankStatement, Books
from app.routes_books import get_books, require_user
from app.schemas import Proposal
from app.validation import StrictBody, UnsafeName, check_name

router = APIRouter(prefix="/books/bank", tags=["bank"])
MAX_CSV = 5 * 1024 * 1024


class MatchBody(StrictBody):
    event_id: str | None = Field(default=None, max_length=64)
    event_ids: list[str] | None = Field(default=None, max_length=200)  # one payment covering several entries


class EventBrief(BaseModel):
    id: str
    date: date
    counterparty: str | None
    amount_pence: int  # signed bank movement: purchases negative


class Suggestion(Match):
    """A proposed match with what the review table shows: the bank line and the ledger entries."""

    line: BankLine
    events: list[EventBrief]


class BankSummary(BaseModel):
    total: int
    matched: int
    suggested: int
    unmatched: int
    transfer: int
    ignored: int
    reconciled_to: date | None  # every line on or before this date is matched, a transfer or ignored


async def _line_action[T](action: Callable[[], Awaitable[T]]) -> T:
    """Run a per-line action: a missing line is 404, a refused change 409."""
    try:
        return await action()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank line") from exc
    except BankMatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/import", response_model=BankImport)
async def import_csv(
    file: UploadFile = File(...),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> BankImport:
    try:
        name = check_name(file.filename) if file.filename else "statement.csv"
    except UnsafeName as exc:
        raise HTTPException(status_code=400, detail=f"Bad file name: {exc}") from exc
    data = await file.read(MAX_CSV + 1)
    if len(data) > MAX_CSV:
        raise HTTPException(status_code=413, detail="Bank statement CSV is over 5 MB")
    try:
        result = await books.import_bank_csv(data, name, user)
    except BankCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.duplicate_file:
        await books.rebuild_safely(f"user:{user}")
    return result


@router.get("/statements", response_model=list[BankStatement])
async def statements(books: Books = Depends(get_books)) -> list[BankStatement]:
    return await books.bank_statements()


@router.get("/lines", response_model=list[BankLine])
async def lines(status: BankLineStatus | None = None, books: Books = Depends(get_books)) -> list[BankLine]:
    return await books.list_bank_lines(status)


@router.get("/suggestions", response_model=list[Suggestion])
async def suggestions(books: Books = Depends(get_books)) -> list[Suggestion]:
    lines = await books.stored_bank_lines()
    by_line = {ln.id: ln for ln in lines}
    events = {e.id: e for e in await books.live_events()}
    return [
        Suggestion(
            **m.model_dump(),
            line=by_line[m.line_id],
            events=[
                EventBrief(id=e.id, date=e.date, counterparty=e.counterparty, amount_pence=settlement_pence(e))
                for e in (events[i] for i in m.event_ids)
            ],
        )
        for m in await books.bank_suggestions(lines)
    ]


@router.get("/unmatched", response_model=list[UnmatchedLine])
async def unmatched(books: Books = Depends(get_books)) -> list[UnmatchedLine]:
    return await unmatched_lines(books)


@router.post("/lines/{line_id}/match", response_model=BankLine)
async def match(
    line_id: str,
    body: MatchBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> BankLine:
    ids = body.event_ids or ([body.event_id] if body.event_id else [])
    return await _line_action(lambda: books.confirm_match(line_id, ids, user))


@router.post("/lines/{line_id}/unmatch", response_model=BankLine)
async def unmatch(line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> BankLine:
    return await _line_action(lambda: books.unmatch(line_id, user))


@router.post("/lines/{line_id}/transfer", response_model=BankLine)
async def transfer(line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> BankLine:
    return await _line_action(lambda: books.mark_line(line_id, "transfer", user))


@router.post("/lines/{line_id}/ignore", response_model=BankLine)
async def ignore(line_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> BankLine:
    return await _line_action(lambda: books.mark_line(line_id, "ignored", user))


@router.post("/lines/{line_id}/expense-proposal", response_model=Proposal)
async def expense_proposal(
    line_id: str,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Proposal:
    return await _line_action(lambda: create_expense_proposal(books, line_id, user))


class BankRuleIn(StrictBody):
    """Create or replace a bank rule: "when the description contains X, code it to Y"."""

    name: str = Field(default="", max_length=120)
    match: BankRuleMatch
    amount_min_pence: int | None = None
    amount_max_pence: int | None = None
    direction: Literal["in", "out", "either"] = "either"
    action: BankRuleAction


async def _check_rule_body(books: Books, body: BankRuleIn) -> None:
    """400 when the amount range, VAT code or job does not make sense."""
    if (
        body.amount_min_pence is not None
        and body.amount_max_pence is not None
        and body.amount_min_pence > body.amount_max_pence
    ):
        raise HTTPException(status_code=400, detail="The minimum amount is above the maximum amount")
    vat = (body.action.vat_code or "").strip().upper() or None
    if vat not in (None, "S", "R", "Z", "E", "O", "N"):
        raise HTTPException(status_code=400, detail=f"Unknown VAT code {body.action.vat_code!r}")
    if body.action.job_id:
        from app.jobs import load_jobs

        try:
            known = await load_jobs(books)
        except ValueError:
            known = []
        if not any(j.id == body.action.job_id for j in known):
            raise HTTPException(status_code=400, detail=f"No such job {body.action.job_id!r}")


@router.get("/rules", response_model=list[BankRule])
async def bank_rules(books: Books = Depends(get_books)) -> list[BankRule]:
    """Bank rules in evaluation order (first match wins)."""
    return await load_bank_rules(books)


@router.post("/rules", response_model=BankRule, status_code=201)
async def create_bank_rule(
    body: BankRuleIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> BankRule:
    await _check_rule_body(books, body)
    rules = await load_bank_rules(books)
    rule = BankRule(**body.model_dump(), created_by=user)
    rules.append(rule)
    await save_bank_rules(books, rules)
    await books.audit(f"user:{user}", "bank_rule_created", {"rule": rule.id})
    return rule


@router.put("/rules/{rule_id}", response_model=BankRule)
async def update_bank_rule(
    rule_id: str, body: BankRuleIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> BankRule:
    await _check_rule_body(books, body)
    rules = await load_bank_rules(books)
    for i, r in enumerate(rules):
        if r.id == rule_id:
            rules[i] = BankRule(
                **body.model_dump(), id=r.id, created_at=r.created_at, created_by=r.created_by or user
            )
            await save_bank_rules(books, rules)
            await books.audit(f"user:{user}", "bank_rule_updated", {"rule": rule_id})
            return rules[i]
    raise HTTPException(status_code=404, detail="No such bank rule")


@router.delete("/rules/{rule_id}", response_model=BankRule)
async def delete_bank_rule(
    rule_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> BankRule:
    rules = await load_bank_rules(books)
    gone = next((r for r in rules if r.id == rule_id), None)
    if gone is None:
        raise HTTPException(status_code=404, detail="No such bank rule")
    await save_bank_rules(books, [r for r in rules if r.id != rule_id])
    await books.audit(f"user:{user}", "bank_rule_deleted", {"rule": rule_id})
    return gone


class ReorderBody(StrictBody):
    ids: list[str] = Field(max_length=200)  # every id is checked against the saved rules


@router.post("/rules/reorder", response_model=list[BankRule])
async def reorder_bank_rules(
    body: ReorderBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> list[BankRule]:
    """New evaluation order: every rule id exactly once, first match wins."""
    rules = await load_bank_rules(books)
    if sorted(body.ids) != sorted(r.id for r in rules):
        raise HTTPException(status_code=400, detail="Reorder with every rule id exactly once")
    by_id = {r.id: r for r in rules}
    ordered = [by_id[i] for i in body.ids]
    await save_bank_rules(books, ordered)
    await books.audit(f"user:{user}", "bank_rules_reordered", {"ids": body.ids})
    return ordered


class ApproveBody(StrictBody):
    kind: Literal["exact", "rule", "ai"]
    ai: AiSuggestion | None = None  # the AI suggestion shown, for kind "ai" (they expire server-side)


class ApproveResult(BaseModel):
    line: BankLine
    proposal_id: str | None
    event_id: str | None


@router.get("/reconcile", response_model=list[ReconcileRow])
async def reconcile(
    request: Request,
    ai: bool = False,
    books: Books = Depends(get_books),
) -> list[ReconcileRow]:
    """One row per open line with an exact, rule or AI suggestion. `?ai=1` adds a model call per line."""
    cfg = ai_config_from_request(request) if ai else None
    return await reconcile_lines(books, await books.list_bank_lines(), with_ai=ai, cfg=cfg)


@router.get("/lines/{line_id}/ai-suggestion", response_model=AiSuggestion | None)
async def ai_suggestion(
    line_id: str, request: Request, books: Books = Depends(get_books)
) -> AiSuggestion | None:
    """Ask the user's own model to code one line; null when it cannot. Labelled "suggested by AI"."""
    from app.journal import CATEGORY_ACCOUNTS, SUNDRY

    try:
        line = await books.find_bank_line(line_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank line") from exc
    if line.resolved:
        raise HTTPException(status_code=409, detail="This bank line is already settled; undo that first")
    try:
        cfg = ai_config_from_request(request)
    except HTTPException:
        return None
    return await suggest_ai(line, cfg, sorted(set(CATEGORY_ACCOUNTS.values()) | {SUNDRY}))


@router.get("/lines/{line_id}/rule-draft", response_model=BankRule)
async def rule_draft(
    line_id: str,
    account: str | None = None,
    vat_code: str | None = None,
    contact: str | None = None,
    job_id: str | None = None,
    books: Books = Depends(get_books),
) -> BankRule:
    """Pre-fill "Create rule from this" for an approved line."""
    try:
        line = await books.find_bank_line(line_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank line") from exc
    return rule_draft_from_line(line, account=account, vat_code=vat_code, contact=contact, job_id=job_id)


@router.post("/lines/{line_id}/approve", response_model=ApproveResult)
async def reconcile_approve(
    line_id: str, body: ApproveBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ApproveResult:
    """Approve one suggestion: exact records the match; rule/AI posts through Review approval."""
    try:
        out = await approve_line(books, line_id, body.kind, user, body.ai)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank line") from exc
    except BankMatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApproveResult(**out)


class CodingOptions(BaseModel):
    accounts: list[str]
    vat_codes: list[str]


@router.get("/coding-options", response_model=CodingOptions)
async def coding_options() -> CodingOptions:
    """Valid accounts and VAT codes for bank rules and AI codings (the runtime's chart)."""
    from app.journal import CATEGORY_ACCOUNTS, SUNDRY

    return CodingOptions(accounts=sorted(set(CATEGORY_ACCOUNTS.values()) | {SUNDRY}), vat_codes=["S", "R", "Z", "E", "O", "N"])


@router.get("/summary", response_model=BankSummary)
async def summary(books: Books = Depends(get_books)) -> BankSummary:
    every = await books.list_bank_lines()
    count = {
        s: sum(ln.status == s for ln in every) for s in ("matched", "suggested", "unmatched", "transfer", "ignored")
    }
    return BankSummary(total=len(every), reconciled_to=reconciled_to(every), **count)
