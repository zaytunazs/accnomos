"""Apply an approved day plan: create its new items as events in the user's calendar.

    _System/Planner/applied.json   {plan_hash: {date, event_ids, created_at}}   (the last 60 plans)

Idempotent per date + plan hash: a plan already applied returns the same event ids without touching the
calendar. A retry after a half-finished apply reuses the events it finds with the same subject and times.
Every event's subject starts with "[Accnomos]"; a visit's body carries "Accnomos job <id>", which is also
how a later plan for that day knows the job is already booked.

Mileage: only when the books have vehicles (`_System/Vehicles/vehicles.json`, written by the Vehicles page), each visit
gets a mileage *proposal* in the response: route and job filled in, miles left for the user (no maps API).
Nothing is written for mileage.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from accnomos_connectors import CalendarEvent, CalendarProvider
from pydantic import BaseModel

from app.books import SYSTEM, Books, now
from app.planner import NOT_BUSY, SUBJECT_PREFIX, TZ, PlanItem, overlaps, plan_hash, postcode_district

APPLIED = f"{SYSTEM}/Planner/applied.json"
VEHICLES = f"{SYSTEM}/Vehicles/vehicles.json"
KEEP_APPLIED = 60
MAX_ITEMS = 40


class PlanError(ValueError):
    """The plan cannot be applied as sent."""


class PlanConflict(PlanError):
    """The calendar has changed since the plan was made."""


class CreatedEvent(BaseModel):
    title: str
    start: datetime
    event_id: str
    reused: bool = False  # already in the calendar from an earlier, unfinished apply


class MileageProposal(BaseModel):
    date: date
    vehicle_id: str
    job_id: str
    from_district: str | None
    to_district: str | None
    miles: float | None = None  # for the user to fill in
    status: str = "proposed"
    note: str = "Proposed from your day plan. Add the miles: Accnomos does not measure distances."


class ApplyResult(BaseModel):
    date: date
    plan_hash: str
    event_ids: list[str]
    created: list[CreatedEvent]
    already_applied: bool = False
    mileage_proposals: list[MileageProposal] = []


def subject(item: PlanItem) -> str:
    return f"{SUBJECT_PREFIX} {item.title}"[:255]


def body(item: PlanItem, day: date, h: str) -> str:
    lines = [f"Accnomos job {item.job_id}"] if item.job_id else []
    lines.append(f"Planned with Accnomos for {day.isoformat()} (plan {h[:12]}).")
    return "\n".join(lines)


def validate(day: date, items: Sequence[PlanItem]) -> list[PlanItem]:
    """The items to create (everything but `existing`), checked to sit inside `day` and not overlap each other."""
    if len(items) > MAX_ITEMS:
        raise PlanError(f"A plan can have at most {MAX_ITEMS} items")
    start = datetime.combine(day, datetime.min.time(), TZ)
    end = start + timedelta(days=1)
    new = sorted((i for i in items if i.kind != "existing"), key=lambda i: i.start)
    for i in new:
        if i.start < start or i.end > end:
            raise PlanError(f"“{i.title}” is not on {day.isoformat()}")
    for a, b in zip(new, new[1:]):
        if overlaps((a.start, a.end), (b.start, b.end)):
            raise PlanError(f"“{a.title}” and “{b.title}” overlap")
    return new


def _same(ev: CalendarEvent, item: PlanItem) -> bool:
    return ev.subject == subject(item) and ev.start == item.start and ev.end == item.end


async def vehicles(books: Books) -> list[dict[str, Any]]:
    rows = await books.read_json(VEHICLES, [])
    return [v for v in rows if isinstance(v, dict) and v.get("id") and v.get("active", True)] if isinstance(rows, list) else []


def mileage(day: date, new: Sequence[PlanItem], fleet: Sequence[dict[str, Any]]) -> list[MileageProposal]:
    if not fleet:
        return []
    out: list[MileageProposal] = []
    last: str | None = None
    for i in new:
        if i.kind != "visit" or not i.job_id:
            continue
        here = postcode_district(i.location)
        out.append(MileageProposal(date=day, vehicle_id=str(fleet[0]["id"]), job_id=i.job_id, from_district=last, to_district=here))
        last = here
    return out


async def apply_plan(books: Books, calendar: CalendarProvider, day: date, items: Sequence[PlanItem], user: str) -> ApplyResult:
    new = validate(day, items)
    h = plan_hash(day, items)
    applied = await books.read_json(APPLIED, {})
    if not isinstance(applied, dict):
        applied = {}  # hand-edited or damaged: treat as nothing applied (a retry still reuses matching events)
    if isinstance(prior := applied.get(h), dict):
        return ApplyResult(
            date=day, plan_hash=h, event_ids=list(prior.get("event_ids", [])), created=[], already_applied=True,
            mileage_proposals=mileage(day, new, await vehicles(books)),
        )

    current = await calendar.list_events(day)
    for item in new:
        if any(_same(ev, item) for ev in current):
            continue
        clash = next(
            (ev for ev in current
             if not ev.is_all_day and ev.show_as not in NOT_BUSY and overlaps((ev.start, ev.end), (item.start, item.end))),
            None,
        )
        if clash is not None:
            raise PlanConflict(
                f"Your calendar has changed: “{clash.subject or 'an event'}” now overlaps “{item.title}”. Plan the day again."
            )

    created: list[CreatedEvent] = []
    for item in new:
        found = next((ev for ev in current if _same(ev, item)), None)
        if found is not None:
            created.append(CreatedEvent(title=item.title, start=item.start, event_id=found.id, reused=True))
            continue
        event_id = await calendar.create_event(subject(item), item.start, item.end, item.location or "", body(item, day, h))
        created.append(CreatedEvent(title=item.title, start=item.start, event_id=event_id))

    ids = [c.event_id for c in created]

    def record(rows: Any) -> dict[str, Any]:
        rows = {k: v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}
        rows = {**rows, h: {"date": day.isoformat(), "event_ids": ids, "created_at": now().isoformat()}}
        return dict(sorted(rows.items(), key=lambda kv: kv[1].get("created_at", ""))[-KEEP_APPLIED:])

    await books._update_json(APPLIED, {}, record)
    await books.audit(f"user:{user}", "plan_applied", {
        "date": day.isoformat(), "plan": h[:12], "events": len(ids), "created": sum(not c.reused for c in created),
    })
    return ApplyResult(date=day, plan_hash=h, event_ids=ids, created=created,
                       mileage_proposals=mileage(day, new, await vehicles(books)))
