"""Day planner: the user's calendar + open jobs + VAT deadlines -> a proposed day. Pure code, no model, no I/O.

    visits     open jobs whose site address has a UK postcode, grouped by postcode district (the outward
               code, "LS6" of "LS6 2AB"); no maps API, so districts stand in for distance
    blocks     the job's estimate_hours, else 2 h
    travel     30 min before a visit in the same district as the last one (and before the first visit),
               60 min when the district changes
    lunch      30 min starting 12:00-13:30: before the first visit that would otherwise push it past 14:00,
               else the first free slot once the visits are placed
    admin      60 min for a VAT return due within 7 days, after the last visit if it fits
    existing   the calendar's own events: never moved, never overlapped (unless shown as free)

Which jobs: whole districts first, biggest first, until `max_visits`; then they are visited in district
order (LS1, LS6, LS7, ...), so the route sweeps rather than zig-zags. The model only writes the rationale
(app/ai/plan.py). Applying a plan (app/plan_apply.py) creates the non-existing items as calendar events.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from accnomos_connectors import CalendarEvent
from pydantic import BaseModel, Field, field_validator, model_validator

from app.deadlines import STAGGER_START_MONTH, filing_deadline, period_containing, period_label, previous_period
from app.jobs import Job

TZ = ZoneInfo("Europe/London")
DEFAULT_START, DEFAULT_END = "08:00", "17:30"
DEFAULT_MAX_VISITS = 5
MAX_VISITS = 12
DEFAULT_VISIT_MIN = 120
TRAVEL_SAME_MIN, TRAVEL_OTHER_MIN = 30, 60
LUNCH_MIN = 30
LUNCH_FROM, LUNCH_LAST_START = time(12, 0), time(13, 30)
ADMIN_MIN = 60
DUE_SOON_DAYS = 7
STEP_MIN = 15  # blocks start on the quarter hour
SUBJECT_PREFIX = "[Accnomos]"
NOT_BUSY = {"free", "workingElsewhere"}

# Outward code + inward code; the outward code is the district. Matched on the upper-cased address.
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")
HHMM_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
JOB_IN_BODY_RE = re.compile(r"Accnomos job ([0-9a-f]{12})")

Kind = Literal["visit", "travel", "lunch", "admin", "existing"]


# --------------------------------------------------------------------------- #
# Wire models
# --------------------------------------------------------------------------- #


class Constraints(BaseModel):
    start: str | None = Field(None, description="HH:MM, start of the working day (default 08:00)")
    end: str | None = Field(None, description="HH:MM, end of the working day (default 17:30)")
    max_visits: int | None = Field(None, ge=1, le=MAX_VISITS)

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        if v is not None and not HHMM_RE.fullmatch(v):
            raise ValueError("times are HH:MM, e.g. 08:00")
        return v

    @model_validator(mode="after")
    def _ordered(self) -> Constraints:
        if (self.start or DEFAULT_START) >= (self.end or DEFAULT_END):
            raise ValueError("the working day must end after it starts")
        return self


class VatSettings(BaseModel):
    """The business's VAT periods, as kept in the app (Settings); same meaning as GET /books/deadlines."""

    stagger: int | None = Field(None, ge=1, le=3)
    start_month: int | None = Field(None, ge=1, le=12)
    months: Literal[1, 3] = 3


class PlanItem(BaseModel):
    kind: Kind
    start: datetime
    end: datetime
    job_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    location: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _times(self) -> PlanItem:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end need a time zone offset")
        if self.end <= self.start:
            raise ValueError("an item must end after it starts")
        return self


class Due(BaseModel):
    title: str
    due: date


class Plan(BaseModel):
    """What the code worked out; facts for the rationale."""

    date: date
    window: tuple[datetime, datetime]
    items: list[PlanItem]
    warnings: list[str]
    districts: list[str]  # visit order
    skipped_already_planned: list[str]  # job ids that already have an [Accnomos] event that day


# --------------------------------------------------------------------------- #
# Postcodes
# --------------------------------------------------------------------------- #


def postcode_district(address: str | None) -> str | None:
    """'12 Elm Road, Leeds LS6 2AB' -> 'LS6'. The last postcode in the address wins; None if there is none."""
    hits = POSTCODE_RE.findall((address or "").upper())
    return hits[-1][0] if hits else None


def district_key(district: str) -> tuple[str, int, str]:
    """Sort districts by area letters, then number: LS1 < LS6 < LS7 < LS12 < M1 (and SW1A after SW1)."""
    m = re.fullmatch(r"([A-Z]+)(\d+)([A-Z]?)", district)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (district, 0, "")


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #


def _at(day: date, hhmm: str | time) -> datetime:
    t = hhmm if isinstance(hhmm, time) else time.fromisoformat(hhmm)
    return datetime.combine(day, t, TZ)


def _ceil_step(dt: datetime) -> datetime:
    local = dt.astimezone(TZ)
    over = (local.minute % STEP_MIN) * 60 + local.second + local.microsecond / 1e6
    return local if over == 0 else local + timedelta(seconds=STEP_MIN * 60 - over)


def _minutes(hours: float | None) -> int:
    if not hours:
        return DEFAULT_VISIT_MIN
    return max(STEP_MIN, round(hours * 60 / STEP_MIN) * STEP_MIN)


def find_slot(
    busy: Sequence[tuple[datetime, datetime]], earliest: datetime, length: timedelta, latest_end: datetime,
) -> datetime | None:
    """Earliest quarter-hour start >= `earliest` such that [start, start + length) misses every busy interval."""
    t = _ceil_step(earliest)
    for s, e in sorted(busy):
        if e <= t:
            continue
        if s >= t + length:
            break
        t = _ceil_step(max(t, e))
    return t if t + length <= latest_end else None


def overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def hhmm(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%H:%M")


def uk_day(d: date) -> str:
    return f"{d:%A} {d.day} {d:%B}"


# --------------------------------------------------------------------------- #
# Deadlines
# --------------------------------------------------------------------------- #


def vat_due(day: date, vat: VatSettings | None) -> list[Due]:
    """The VAT return due within DUE_SOON_DAYS of `day` (or on it), if any."""
    if vat is None:
        return []
    first = vat.start_month or STAGGER_START_MONTH[vat.stagger or 1]
    cur_start, cur_end = period_containing(day, first, vat.months)
    prev_start, prev_end = previous_period(cur_start, vat.months)
    for start, end in ((prev_start, prev_end), (cur_start, cur_end)):
        deadline = filing_deadline(end)
        if 0 <= (deadline - day).days <= DUE_SOON_DAYS:
            return [Due(title=f"VAT return {period_label(start, end)}", due=deadline)]
    return []


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #


def build_plan(
    day: date,
    jobs: Sequence[Job],
    existing: Sequence[CalendarEvent],
    dues: Sequence[Due] = (),
    constraints: Constraints | None = None,
    today: date | None = None,
) -> Plan:
    c = constraints or Constraints()
    win_start, win_end = _at(day, c.start or DEFAULT_START), _at(day, c.end or DEFAULT_END)
    max_visits = c.max_visits or DEFAULT_MAX_VISITS
    warnings: list[str] = []
    items: list[PlanItem] = []

    if today and day < today:
        warnings.append(f"{uk_day(day)} has already passed.")
    if day.weekday() >= 5:
        warnings.append(f"{uk_day(day)} is a {day:%A}.")

    busy: list[tuple[datetime, datetime]] = []
    already: list[str] = []
    for ev in existing:
        if m := JOB_IN_BODY_RE.search(ev.body_preview):
            already.append(m.group(1))
        if ev.is_all_day:
            if ev.show_as == "oof":
                warnings.append(f"You are out of office all day ({ev.subject or 'all-day event'}), so nothing is planned.")
                return Plan(date=day, window=(win_start, win_end), items=[], warnings=warnings, districts=[],
                            skipped_already_planned=already)
            warnings.append(f"All-day event: {ev.subject or '(no subject)'}.")
            continue
        items.append(PlanItem(
            kind="existing", start=ev.start.astimezone(TZ), end=ev.end.astimezone(TZ), job_id=None,
            title=(ev.subject or "(no subject)")[:255], location=ev.location[:500] or None,
        ))
        if ev.show_as not in NOT_BUSY:
            busy.append((ev.start, ev.end))

    lunch_open = win_start <= _at(day, LUNCH_LAST_START) and win_end >= _at(day, LUNCH_FROM) + timedelta(minutes=LUNCH_MIN)
    lunch_latest_end = min(win_end, _at(day, LUNCH_LAST_START) + timedelta(minutes=LUNCH_MIN))

    def place_lunch(earliest: datetime) -> None:
        nonlocal lunch_open
        lunch_open = False
        length = timedelta(minutes=LUNCH_MIN)
        if at := find_slot(busy, max(earliest, win_start, _at(day, LUNCH_FROM)), length, lunch_latest_end):
            items.append(PlanItem(kind="lunch", start=at, end=at + length, title="Lunch"))
            busy.append((at, at + length))
        else:
            warnings.append("No room for a lunch break between 12:00 and 14:00.")

    # Which jobs, in which order.
    groups: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        if job.status != "open" or job.id in already:
            continue
        district = postcode_district(job.site_address)
        if district is None:
            warnings.append(f"“{job.name}” has no postcode in its site address, so it is not planned.")
            continue
        groups[district].append(job)
    chosen: dict[str, list[Job]] = {}
    left = max_visits
    for district in sorted(groups, key=lambda d: (-len(groups[d]), district_key(d))):
        if left <= 0:
            break
        members = sorted(groups[district], key=lambda j: (j.name.lower(), j.id))
        chosen[district] = members[:left]
        left -= len(chosen[district])
    not_chosen = sum(len(g) for g in groups.values()) - sum(len(g) for g in chosen.values())
    if not_chosen:
        warnings.append(f"{not_chosen} more open job{'s' if not_chosen != 1 else ''} not planned (limit {max_visits} visits).")

    cursor, last_district = win_start, None
    districts: list[str] = []
    for district in sorted(chosen, key=district_key):
        for job in chosen[district]:
            travel = TRAVEL_SAME_MIN if last_district in (None, district) else TRAVEL_OTHER_MIN
            visit = _minutes(job.estimate_hours)
            block = timedelta(minutes=travel + visit)
            at = find_slot(busy, cursor, block, win_end)
            if lunch_open and (at is None or at + block > lunch_latest_end - timedelta(minutes=LUNCH_MIN)):
                mark = (len(items), len(busy), len(warnings))
                place_lunch(cursor)  # lunch before this visit, or it would slip past 14:00
                after_lunch = find_slot(busy, cursor, block, win_end)
                if after_lunch is None and at is not None:  # a long visit only fits without lunch: keep the visit
                    del items[mark[0]:], busy[mark[1]:], warnings[mark[2]:]
                    warnings.append("No room for a lunch break between 12:00 and 14:00.")
                else:
                    at = after_lunch
            if at is None:
                warnings.append(f"“{job.name}” ({district}) does not fit in the day.")
                continue
            arrive = at + timedelta(minutes=travel)
            leave = arrive + timedelta(minutes=visit)
            items.append(PlanItem(kind="travel", start=at, end=arrive, title=f"Travel to {district}"))
            items.append(PlanItem(
                kind="visit", start=arrive, end=leave, job_id=job.id, title=job.name[:255],
                location=(job.site_address or "")[:500] or None,
            ))
            busy += [(at, leave)]
            cursor, last_district = leave, district
            if district not in districts:
                districts.append(district)

    if lunch_open:
        place_lunch(win_start)

    for due in dues:
        length = timedelta(minutes=ADMIN_MIN)
        at = find_slot(busy, cursor, length, win_end) or find_slot(busy, win_start, length, win_end)
        if at is None:
            warnings.append(f"No hour free for {due.title} (due {due.due.day} {due.due:%b}).")
            continue
        items.append(PlanItem(kind="admin", start=at, end=at + length, title=f"{due.title} (due {due.due.day} {due.due:%b})"))
        busy.append((at, at + length))

    items.sort(key=lambda i: (i.start, i.kind != "existing"))
    return Plan(date=day, window=(win_start, win_end), items=items, warnings=warnings, districts=districts,
                skipped_already_planned=already)


def plan_hash(day: date, items: Sequence[PlanItem]) -> str:
    """Stable id of a plan: the same day and items (in any order, any UTC offset spelling) hash the same."""
    rows = sorted(
        [i.kind, i.start.astimezone(UTC).isoformat(), i.end.astimezone(UTC).isoformat(), i.job_id or "", i.title,
         i.location or ""]
        for i in items
    )
    return hashlib.sha256(json.dumps([day.isoformat(), rows], ensure_ascii=False).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# "Plan my Thursday"
# --------------------------------------------------------------------------- #

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_INTENT_RE = re.compile(r"\b(plan|schedule|organi[sz]e)\b", re.I)


def plan_intent(text: str, today: date) -> date | None:
    """The day a "plan my …" request is about, or None when the text is not asking for a day plan.

    'plan my day' / 'plan today' -> today; 'plan tomorrow'; 'plan my Thursday' -> the next Thursday on or
    after today; 'plan next Thursday' -> strictly after today; 'plan 2026-11-05'.
    """
    if not _INTENT_RE.search(text):
        return None
    low = text.lower()
    if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low):
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    if re.search(r"\btomorrow\b", low):
        return today + timedelta(days=1)
    for i, name in enumerate(WEEKDAYS):
        if m := re.search(rf"\b(next\s+)?{name}\b", low):
            ahead = (i - today.weekday()) % 7
            if m.group(1) and ahead == 0:
                ahead = 7
            return today + timedelta(days=ahead)
    if re.search(r"\b(today|my day|the day)\b", low):
        return today
    return None
