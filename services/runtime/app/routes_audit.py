"""GET /audit: the audit trail as a timeline, newest first (app/audit_view.py). Reads only; it never edits a line."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app import audit_view
from app.books import Books, now
from app.routes_books import get_books

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=audit_view.AuditPage)
async def get_audit(
    start: date | None = Query(None, alias="from", description="first day, inclusive; defaults to 31 days before `to`"),
    end: date | None = Query(None, alias="to", description="last day, inclusive; defaults to today (London)"),
    actor: str | None = Query(None, description='"user", "agent", an agent name such as "autopilot", or a full actor'),
    kind: str | None = Query(None, description='an event such as "approved", or a family such as "invoice"'),
    limit: int = Query(200, ge=1, description="at most this many lines; capped at 500"),
    books: Books = Depends(get_books),
) -> audit_view.AuditPage:
    """Every line in _System/audit and _System/audit/actions for the range, with who did it (you or an agent) and a
    plain-English summary. Autopilot's own log is not repeated: its postings are already in the main one."""
    end = end or now().date()
    start = start or end - timedelta(days=audit_view.DEFAULT_DAYS)
    if start > end:
        raise HTTPException(status_code=422, detail="`from` must be on or before `to`")
    if (end - start).days > audit_view.MAX_DAYS:
        # each month in the range is two storage reads; a century-long range would be thousands
        raise HTTPException(status_code=422, detail=f"at most {audit_view.MAX_DAYS} days at a time")
    return await audit_view.read(books, start, end, actor, kind, limit)
