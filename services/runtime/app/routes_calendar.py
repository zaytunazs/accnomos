"""The user's calendar: read events, add and remove them, and keep the books' deadlines in it.

GET    /calendar/events?start=&end=     events overlapping those days (at most 62), Europe/London times
POST   /calendar/events                 add one (audited `calendar_event_added`); 201. It checks the calendar first:
                                        `check_only: true` answers {conflicts} and writes nothing; a clash without
                                        `allow_conflict: true` is a 409 {detail, conflicts}
GET    /calendar/conflicts?start=&end=  pairs of events already in the calendar that clash (default the next 14 days)
DELETE /calendar/events/{id}            remove one, body {"confirm": true} (audited `calendar_event_removed`); 204
POST   /calendar/deadlines/sync         body {"confirm": true}: put the books' upcoming deadlines into the calendar as
                                        all-day events with a reminder the day before; idempotent (audited
                                        `calendar_deadlines_synced`)
GET    /calendar/deadlines/status       {synced, keep, last_sync, count}
PUT    /calendar/deadlines/preference   {"keep": bool}: "Add all deadlines to my calendar automatically"

The calendar is Outlook through Microsoft Graph (`Calendars.Read` to read, `Calendars.ReadWrite` to write, asked for by
the app on first use); in a demo session it is the session's own in-memory calendar, and nothing reaches Microsoft.
Every event Accnomos writes carries an extended property (`ACCNOMOS_KEY_PROP` in accnomos_connectors.msgraph) with a
stable key — `deadline:…`, `invoice:<number>` or `event:<id>` — so a sync finds and updates its own events, never
duplicates them, and never touches anyone else's. Deadlines are the ones Home's Deadlines card shows
(app/home_overview.py `deadlines`: VAT, MTD Income Tax, Self Assessment, CIS, a pay run to confirm) plus sent invoices
still unpaid, due from 30 days ago to 90 days ahead. A deadline Accnomos wrote that the books no longer have (an invoice
paid, a period filed) is removed if its date is still ahead; past ones are left as a record.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from accnomos_connectors import CalendarEvent, CalendarProvider, NewCalendarEvent
from accnomos_connectors.msgraph import GraphError
from app import home_overview, invoicing, payments
from app.books import SYSTEM, Books
from app.books import today as london_today
from app.routes_books import get_books, require_user
from app.routes_plan import get_calendar
from app.validation import StrictBody
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/calendar", tags=["calendar"])

LONDON = ZoneInfo("Europe/London")
PREFS = f"{SYSTEM}/calendar.json"
MAX_DAYS = 62
REMINDER_DAY_BEFORE = 15 * 60  # an all-day event starts at midnight: 900 minutes before is 09:00 the day before
SYNC_BACK, SYNC_AHEAD = 60, 400  # days of calendar a sync looks through for its own events
INVOICE_BACK, INVOICE_AHEAD = 30, 90
OWN_PREFIXES = ("deadline:", "invoice:")  # what a deadline sync owns (manual `event:` ones are the user's)
SITE = "https://accnomos.com"


class EventOut(BaseModel):
    id: str
    subject: str
    start: datetime  # Europe/London
    end: datetime
    all_day: bool
    location: str | None = None
    accnomos: bool  # written by Accnomos (tagged)
    web_link: str | None = None


class EventIn(StrictBody):
    subject: str = Field(min_length=1, max_length=120)
    start: str = Field(max_length=40, description="YYYY-MM-DD (all day) or an ISO date-time; no zone = Europe/London")
    end: str | None = Field(None, max_length=40)
    all_day: bool | None = None
    location: str | None = Field(None, max_length=200)
    body: str | None = Field(None, max_length=2000)
    reminder_minutes: int | None = Field(None, ge=0, le=40320)
    check_only: bool = False  # only report clashes; write nothing
    allow_conflict: bool = False  # the user saw the clash and said "Add anyway"


class Clash(BaseModel):
    id: str
    subject: str
    start: datetime
    end: datetime
    all_day: bool


class ClashPair(BaseModel):
    a: Clash
    b: Clash


class Confirm(StrictBody):
    confirm: bool = False


class Preference(StrictBody):
    keep: bool


class SyncResult(BaseModel):
    added: int
    updated: int
    unchanged: int
    removed: int
    events: list[EventOut]
    conflicts: list[ClashPair] = []  # a deadline on the same day as another all-day event (said, never blocking)


class SyncStatus(BaseModel):
    synced: bool
    keep: bool
    last_sync: datetime | None = None
    count: int = 0


def out(e: CalendarEvent) -> EventOut:
    return EventOut(
        id=e.id,
        subject=e.subject,
        start=e.start.astimezone(LONDON),
        end=e.end.astimezone(LONDON),
        all_day=e.is_all_day,
        location=e.location or None,
        accnomos=e.key is not None,
        web_link=e.web_link or None,
    )


def clash(e: CalendarEvent) -> Clash:
    return Clash(
        id=e.id, subject=e.subject, start=e.start.astimezone(LONDON), end=e.end.astimezone(LONDON), all_day=e.is_all_day
    )


def clashes(start: datetime, end: datetime, all_day: bool, others: list[CalendarEvent]) -> list[CalendarEvent]:
    """Events that clash with [start, end). The rule: timed events clash with timed events they overlap; an all-day
    event (a deadline) clashes only with other all-day events on the same days, so a deadline never flags every
    meeting that day."""
    return [o for o in others if o.is_all_day == all_day and o.start < end and o.end > start]


def _deadline(e: CalendarEvent) -> bool:
    return bool(e.key and e.key.startswith(OWN_PREFIXES))


def _when(text: str) -> tuple[datetime, bool]:
    """(aware datetime, is a bare date)."""
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), time(0), LONDON), True
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, f"Not a date or time: {text!r}") from exc
    return (dt if dt.tzinfo else dt.replace(tzinfo=LONDON)), False


def new_event(body: EventIn, key: str) -> NewCalendarEvent:
    start, bare = _when(body.start)
    all_day = body.all_day if body.all_day is not None else bare
    if all_day:
        start = datetime.combine(start.astimezone(LONDON).date(), time(0), LONDON)
        end = start + timedelta(days=1)
        if body.end:
            last, _ = _when(body.end)
            last_day = last.astimezone(LONDON).date()
            # a bare end date is the last day of the event; Graph's all-day end is the midnight after it
            end = datetime.combine(last_day + timedelta(days=1) if len(body.end) == 10 else last_day, time(0), LONDON)
    else:
        end = _when(body.end)[0] if body.end else start + timedelta(hours=1)
    if end <= start:
        raise HTTPException(422, "The end is before the start.")
    return NewCalendarEvent(
        subject=body.subject.strip(),
        start=start,
        end=end,
        is_all_day=all_day,
        location=(body.location or "").strip(),
        body=(body.body or "").strip(),
        reminder_minutes=body.reminder_minutes,
        key=key,
    )


def _graph_refused(exc: GraphError) -> HTTPException:
    if exc.status in (401, 403):
        return HTTPException(
            403, "Accnomos needs permission to use your calendar. Sign in again and allow calendar access."
        )
    return HTTPException(502, "The calendar could not be reached just now; try again in a minute.")


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


@router.get("/events", response_model=list[EventOut])
async def list_events(
    start: date | None = Query(None, description="first day (default today)"),
    end: date | None = Query(None, description="last day (default start + 13 days)"),
    calendar: CalendarProvider = Depends(get_calendar),
) -> list[EventOut]:
    first = start or london_today()
    last = end or first + timedelta(days=13)
    if last < first:
        raise HTTPException(422, "end is before start")
    if (last - first).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"At most {MAX_DAYS} days at a time")
    try:
        return [out(e) for e in await calendar.list_range(first, last)]
    except GraphError as exc:
        raise _graph_refused(exc) from exc


@router.post("/events", response_model=EventOut, status_code=201)
async def add_event(
    body: EventIn,
    calendar: CalendarProvider = Depends(get_calendar),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> EventOut | JSONResponse:
    event = new_event(body, f"event:{uuid.uuid4().hex[:12]}")
    try:
        around = await calendar.list_range(event.start.astimezone(LONDON).date(), event.end.astimezone(LONDON).date())
        found = [clash(c) for c in clashes(event.start, event.end, event.is_all_day, around)]
        if body.check_only:
            return JSONResponse({"conflicts": [c.model_dump(mode="json") for c in found]})
        if found and not body.allow_conflict:
            names = ", ".join(f"‘{c.subject}’" for c in found[:3])
            return JSONResponse(
                status_code=409,
                content={
                    "detail": f"This clashes with {names}. Add it anyway, or pick another time.",
                    "conflicts": [c.model_dump(mode="json") for c in found],
                },
            )
        made = await calendar.add_event(event)
    except GraphError as exc:
        raise _graph_refused(exc) from exc
    await books.audit(
        f"user:{user}",
        "calendar_event_added",
        {
            "event": made.id,
            "subject": made.subject,
            "start": made.start.astimezone(LONDON).isoformat(),
            "clashes": len(found),
        },
    )
    return out(made)


@router.get("/conflicts", response_model=list[ClashPair])
async def list_conflicts(
    start: date | None = Query(None, description="first day (default today)"),
    end: date | None = Query(None, description="last day (default start + 13 days)"),
    calendar: CalendarProvider = Depends(get_calendar),
) -> list[ClashPair]:
    """Events already in the calendar that clash with each other (the same rule as adding one). Two of Accnomos's own
    deadlines on one day (a VAT return and its payment) are not a clash."""
    first = start or london_today()
    last = end or first + timedelta(days=13)
    if last < first or (last - first).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"Give a range of 1 to {MAX_DAYS} days")
    try:
        events = await calendar.list_range(first, last)
    except GraphError as exc:
        raise _graph_refused(exc) from exc
    pairs: list[ClashPair] = []
    for i, a in enumerate(events):
        for b in events[i + 1 :]:
            if _deadline(a) and _deadline(b):
                continue
            if clashes(a.start, a.end, a.is_all_day, [b]):
                pairs.append(ClashPair(a=clash(a), b=clash(b)))
    return pairs


@router.delete("/events/{event_id}", status_code=204)
async def remove_event(
    event_id: str,
    body: Confirm,
    calendar: CalendarProvider = Depends(get_calendar),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Response:
    if not body.confirm:
        raise HTTPException(422, 'Removing an event needs {"confirm": true}.')
    try:
        await calendar.delete_event(event_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "No such event") from exc
    except GraphError as exc:
        raise _graph_refused(exc) from exc
    await books.audit(f"user:{user}", "calendar_event_removed", {"event": event_id})
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Deadlines
# --------------------------------------------------------------------------- #


class Wanted(BaseModel):
    key: str
    title: str
    day: date
    body: str


def _short(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def _gbp(pence: int) -> str:
    return f"£{pence / 100:,.2f}"


async def wanted_deadlines(books: Books, day: date, cycle: VatCycle) -> list[Wanted]:
    """The deadlines a sync puts in the calendar, worked out from the books (no model)."""
    o = await home_overview.build(books, day, cycle.start_month, cycle.months, vat_assumed=cycle.assumed, cfg=None)
    items: list[Wanted] = []
    for d in o.deadlines:
        title = d.title if d.key == "payroll" else f"{d.title} due"
        items.append(
            Wanted(
                key=f"deadline:{d.key}:{_short(d.title)}",
                title=title,
                day=d.due,
                body=f"Added by Accnomos from your books. Open: {SITE}{d.href}"
                + (f"\nHMRC guidance: {d.source_url}" if d.source_url else ""),
            )
        )
    try:
        invoices = await invoicing.list_invoices(books, "sent")
    except Exception:  # noqa: BLE001 - no invoices folder yet: deadlines alone
        invoices = []
    if invoices:
        ledger = await payments.load_ledger(books)
        for inv in invoices:
            if not (day - timedelta(days=INVOICE_BACK) <= inv.due_date <= day + timedelta(days=INVOICE_AHEAD)):
                continue
            money = payments.invoice_money(inv, ledger)
            if money is None or money.balance_pence <= 0:
                continue
            items.append(
                Wanted(
                    key=f"invoice:{inv.number}",
                    title=f"Invoice {inv.number} due from {inv.customer.name} ({_gbp(money.balance_pence)} unpaid)",
                    day=inv.due_date,
                    body=f"Added by Accnomos from your books. Open: {SITE}/invoices",
                )
            )
    return sorted(items, key=lambda w: (w.day, w.key))


def _all_day(w: Wanted) -> NewCalendarEvent:
    start = datetime.combine(w.day, time(0), LONDON)
    return NewCalendarEvent(
        subject=w.title,
        start=start,
        end=start + timedelta(days=1),
        is_all_day=True,
        body=w.body,
        reminder_minutes=REMINDER_DAY_BEFORE,
        key=w.key,
    )


async def _prefs(books: Books) -> dict:
    raw = await books.read_json(PREFS, {})
    return raw if isinstance(raw, dict) else {}


@router.post("/deadlines/sync", response_model=SyncResult)
async def sync_deadlines(
    body: Confirm,
    cycle: VatCycle = Depends(vat_cycle),
    calendar: CalendarProvider = Depends(get_calendar),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> SyncResult:
    if not body.confirm:
        raise HTTPException(422, 'Adding deadlines to your calendar needs {"confirm": true}.')
    day = london_today()
    wanted = await wanted_deadlines(books, day, cycle)
    try:
        window = await calendar.list_range(day - timedelta(days=SYNC_BACK), day + timedelta(days=SYNC_AHEAD))
        existing = [e for e in window if _deadline(e)]
        by_key: dict[str, CalendarEvent] = {}
        extra: list[CalendarEvent] = []
        for e in existing:  # a key twice (an earlier interrupted sync): keep the first, remove the rest
            if e.key in by_key:
                extra.append(e)
            else:
                by_key[e.key or ""] = e
        others = [e for e in window if not _deadline(e)]
        added = updated = unchanged = removed = 0
        events: list[CalendarEvent] = []
        conflicts: list[ClashPair] = []
        for w in wanted:
            have = by_key.pop(w.key, None)
            if have is None:
                new = _all_day(w)
                made = await calendar.add_event(new)
                events.append(made)
                added += 1
                conflicts += [ClashPair(a=clash(made), b=clash(o)) for o in clashes(new.start, new.end, True, others)]
            elif have.start.astimezone(LONDON).date() != w.day or have.subject != w.title:
                events.append(await calendar.update_event(have.id, _all_day(w)))
                updated += 1
            else:
                events.append(have)
                unchanged += 1
        for gone in [*by_key.values(), *extra]:  # the books no longer have it: remove only if still ahead
            if gone.start.astimezone(LONDON).date() >= day:
                await calendar.delete_event(gone.id)
                removed += 1
    except GraphError as exc:
        raise _graph_refused(exc) from exc
    prefs = await _prefs(books)
    prefs.update({"last_sync": datetime.now(LONDON).isoformat(), "count": len(events)})
    await books.write_json(PREFS, prefs)
    await books.audit(
        f"user:{user}",
        "calendar_deadlines_synced",
        {"added": added, "updated": updated, "unchanged": unchanged, "removed": removed, "clashes": len(conflicts)},
    )
    return SyncResult(
        added=added,
        updated=updated,
        unchanged=unchanged,
        removed=removed,
        events=[out(e) for e in events],
        conflicts=conflicts,
    )


@router.get("/deadlines/status", response_model=SyncStatus)
async def deadlines_status(books: Books = Depends(get_books)) -> SyncStatus:
    p = await _prefs(books)
    last = p.get("last_sync")
    return SyncStatus(
        synced=bool(last),
        keep=bool(p.get("keep")),
        last_sync=datetime.fromisoformat(last) if last else None,
        count=int(p.get("count") or 0),
    )


@router.put("/deadlines/preference", response_model=SyncStatus)
async def set_preference(
    body: Preference, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> SyncStatus:
    p = await _prefs(books)
    p["keep"] = body.keep
    await books.write_json(PREFS, p)
    await books.audit(f"user:{user}", "calendar_deadlines_preference", {"keep": body.keep})
    return await deadlines_status(books)
