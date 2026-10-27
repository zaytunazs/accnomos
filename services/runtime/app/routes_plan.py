"""/plan/day: propose a working day from the calendar and open jobs; /plan/day/apply: put it in the calendar.

Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`). The token also needs `Calendars.Read` for
/plan/day and `Calendars.ReadWrite` for /plan/day/apply (which also needs `X-User`); the app asks for each
only when it is first used. /plan/day never writes anything. AI headers are optional: without them, or if the
model fails, the rationale is written by code. Ordering and times are always code (app/planner.py).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime

from accnomos_connectors import CalendarProvider
from accnomos_connectors.msgraph import GraphCalendarProvider
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import jobs
from app.ai import plan as plan_ai
from app.ai.config import AiConfig, is_test_mode
from app.books import Books
from app.plan_apply import ApplyResult, PlanConflict, PlanError, apply_plan
from app.planner import TZ, Constraints, PlanItem, VatSettings, build_plan, plan_hash, vat_due
from app.routes_books import get_books, require_user

router = APIRouter(prefix="/plan", tags=["plan"])


async def get_calendar(request: Request) -> AsyncIterator[CalendarProvider]:
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    if is_test_mode():
        from app import testmode

        yield (await testmode.state()).calendar
        return
    provider = GraphCalendarProvider(token)
    try:
        yield provider
    finally:
        await provider.aclose()


def optional_ai(request: Request) -> AiConfig | None:
    """The caller's AI, or None when none is set up (the plan works without one)."""
    try:
        return AiConfig.from_headers(request.headers)
    except ValueError:
        return None


class PlanRequest(BaseModel):
    date: date
    constraints: Constraints | None = None
    vat: VatSettings | None = None
    job_ids: list[str] | None = Field(None, max_length=200, description="only these jobs (default: every open job)")


class PlanResponse(BaseModel):
    date: date
    plan: list[PlanItem]
    rationale_md: str
    warnings: list[str]
    plan_hash: str
    model: str | None = None
    fallback_reason: str | None = None


class ApplyRequest(BaseModel):
    date: date
    plan: list[PlanItem] = Field(max_length=40)


@router.post("/day", response_model=PlanResponse)
async def plan_day(
    body: PlanRequest,
    books: Books = Depends(get_books),
    calendar: CalendarProvider = Depends(get_calendar),
    cfg: AiConfig | None = Depends(optional_ai),
) -> PlanResponse:
    """Propose the day. Reads the calendar and jobs.json; writes nothing."""
    wanted = set(body.job_ids) if body.job_ids is not None else None
    open_jobs = [j for j in await jobs.load_jobs(books) if j.status == "open" and (wanted is None or j.id in wanted)]
    existing = await calendar.list_events(body.date)
    plan = build_plan(body.date, open_jobs, existing, vat_due(body.date, body.vat), body.constraints,
                      today=datetime.now(TZ).date())
    text, model, reason = await plan_ai.rationale(plan, cfg)
    return PlanResponse(
        date=body.date, plan=plan.items, rationale_md=text, warnings=plan.warnings,
        plan_hash=plan_hash(body.date, plan.items), model=model, fallback_reason=reason,
    )


@router.post("/day/apply", response_model=ApplyResult)
async def plan_day_apply(
    body: ApplyRequest,
    books: Books = Depends(get_books),
    calendar: CalendarProvider = Depends(get_calendar),
    user: str = Depends(require_user),
) -> ApplyResult:
    """Create the plan's new items as calendar events (never the `existing` ones). Idempotent per date + plan."""
    try:
        return await apply_plan(books, calendar, body.date, body.plan, user)
    except PlanConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
