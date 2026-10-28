"""/close/*: the month-end close agent (app/month_end.py). Same headers as /books/*.

* GET  /close                    the month that ended last (and any closed month changed since), for the Home card
* GET  /close/{yyyy-mm}          that month: its status, the last run, the close records, changes since the close
* POST /close/{yyyy-mm}/run      run the checklist (needs X-User). `?stream=1` answers as server-sent events:
                                 `start` (the nine steps), `step` (each one as it finishes), `summary`, then `run`
                                 (the whole run, with the signed cards); `error` if the run itself failed.

VAT settings are the usual query parameters (app/vat_cycle.py). The AI headers are optional: without them code
writes the summary and the reminders. Body `{"outlook": true}` when the app has Outlook intake on and asked for
`Mail.Read`: the mailbox is then read in a dry run (nothing copied). Cards are approved through /actions/approve.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from accnomos_connectors.base import MailProvider
from app import month_end as me
from app.ai.config import AiConfig, is_test_mode
from app.books import Books
from app.books import today as current_date
from app.routes_actions import graph_token
from app.routes_books import get_books, require_user
from app.routes_plan import optional_ai
from app.validation import StrictBody
from app.vat_cycle import VatCycle, vat_cycle

log = logging.getLogger(__name__)
router = APIRouter(prefix="/close", tags=["month-end"])
TODAY = Query(None, description="for previews and tests; defaults to today (London)")
MONTH = Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="yyyy-mm")


class RunBody(StrictBody):
    outlook: bool = False  # Outlook intake is on in the app, and the token carries Mail.Read


def _check(month: str, today: date) -> None:
    try:
        me.check_month(month, today)
    except me.CloseError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("", response_model=me.CloseOverview)
async def close_overview(today: date | None = TODAY, books: Books = Depends(get_books)) -> me.CloseOverview:
    """Reads only: the close record files and, for closed months, the month's events and bank lines."""
    return await me.overview(books, today or current_date())


@router.get("/{month}", response_model=me.MonthDetail)
async def close_detail(
    month: str = MONTH, today: date | None = TODAY, books: Books = Depends(get_books)
) -> me.MonthDetail:
    """Reads only."""
    day = today or current_date()
    _check(month, day)
    return await me.month_status(books, month, day)


def _mail(token: str) -> MailProvider:
    if is_test_mode():
        from app import testmode

        return testmode.current().mail
    from accnomos_connectors.msgraph import GraphMailProvider

    return GraphMailProvider(token)


async def _close_mail(ctx: me.Ctx) -> None:
    if ctx.mail is not None and not is_test_mode() and hasattr(ctx.mail, "aclose"):  # the fake mailbox is shared
        await ctx.mail.aclose()  # type: ignore[attr-defined]


def _sse(event: str, data: Any) -> str:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def _events(ctx: me.Ctx) -> AsyncIterator[str]:
    try:
        async for event, data in me.run(ctx):
            yield _sse(event, data)
    except Exception as exc:  # noqa: BLE001  the stream has started: say what failed instead of a broken stream
        log.exception("month-end run failed")
        yield _sse("error", {"detail": f"The close could not finish ({type(exc).__name__}). Run it again."})
    finally:
        await _close_mail(ctx)


@router.post("/{month}/run", response_model=me.CloseRun)
async def close_run(
    body: RunBody | None = None,
    month: str = MONTH,
    stream: bool = Query(False, description="1: server-sent events (start, step…, summary, run)"),
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    token: str = Depends(graph_token),
    cfg: AiConfig | None = Depends(optional_ai),
) -> Any:
    """Work through the checklist. Posts nothing: what needs the user comes back as cards to approve."""
    body = body or RunBody()
    day = today or current_date()
    _check(month, day)
    ctx = me.Ctx(
        books=books,
        month=month,
        today=day,
        cycle=cycle,
        user=user,
        token=token,
        cfg=cfg,
        mail=_mail(token) if body.outlook else None,
        outlook=body.outlook,
    )
    if stream:
        return StreamingResponse(
            _events(ctx),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        return await me.run_to_end(ctx)
    finally:
        await _close_mail(ctx)
