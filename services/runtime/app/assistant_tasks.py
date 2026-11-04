"""Notes, to-dos, the calendar and the next deadline, typed or spoken, in Ask and the "Talk to Accnomos" assistant.

Who decides what:
  code   spots the request (the phrases below), reads dates and times (Europe/London), finds the note or calendar event
         meant, and writes every answer and card. No model is called here: a spoken request reaches this module as the
         text Muse Voice Transcribe heard (app/ai/stt.py), and the reply is read aloud by the device's own voice.
  the user  approves every change. Saving or deleting a note, adding a to-do, adding or removing a calendar event are
         signed cards (app/actions.py ProposedAction) that do nothing until Approve, as every other Ask action.
         Reading notes, the calendar or the next deadline changes nothing, so it is answered at once.

Notes live in the user's own books, `_System/notes/notes.json` (id, text, created, source voice|typed, optional due).
A note's due date is read by code from the note's own words ("by Friday", "in March", "on 12 Nov"); none when unclear.
Calendar reads and changes go to the user's calendar (Microsoft Graph: reading needs Calendars.Read, adding and
removing Calendars.ReadWrite); in a demo, the session's in-memory calendar.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator

from accnomos_connectors.base import CalendarEvent, CalendarProvider, NewCalendarEvent
from accnomos_connectors.msgraph import GraphError
from app.books import SYSTEM, Books, now
from app.schemas import AskAnswer, AskPeriod, Clarification, ProposedAction, SuggestedAction
from app.validation import LENIENT, StrictBody

NOTES = f"{SYSTEM}/notes/notes.json"
MAX_NOTES = 1000
MAX_EVENT_DAYS = 31  # a calendar read covers at most a month
DEFAULT_MINUTES = 60
TZ = ZoneInfo("Europe/London")

CalendarFactory = Callable[[], Any]  # () -> CalendarProvider (Graph providers are closed after use)


# --------------------------------------------------------------------------- #
# Notes
# --------------------------------------------------------------------------- #


class NoteError(ValueError):
    """The notes file cannot take this change."""


class NoteIn(StrictBody):
    text: str = Field(min_length=1, max_length=500)
    due: date | None = None
    source: Literal["voice", "typed"] = "typed"

    @field_validator("text")
    @classmethod
    def _tidy(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("the note is empty")
        return v


class Note(NoteIn):
    id: str
    created: datetime
    created_by: str | None = None


async def load_notes(books: Books) -> list[Note]:
    raw = await books.read_json(NOTES, [])
    out: list[Note] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(Note.model_validate(item, **LENIENT))
        except ValueError:
            continue
    return sorted(out, key=lambda n: n.created, reverse=True)


async def _write(books: Books, notes: list[Note]) -> None:
    payload = [n.model_dump(mode="json") for n in sorted(notes, key=lambda n: n.created)]
    await books._update_json(NOTES, [], lambda _old: payload)  # noqa: SLF001 - the same JSON writer as todos


async def add_note(books: Books, body: NoteIn, user: str) -> Note:
    notes = await load_notes(books)
    if len(notes) >= MAX_NOTES:
        raise NoteError(f"At most {MAX_NOTES} notes; delete some first")
    note = Note(**body.model_dump(), id=uuid.uuid4().hex[:12], created=now(), created_by=user)
    await _write(books, [*notes, note])
    await books.audit(f"user:{user}", "note_saved", {"note": note.id, "source": note.source})
    return note


async def delete_note(books: Books, note_id: str, user: str) -> Note:
    notes = await load_notes(books)
    gone = next((n for n in notes if n.id == note_id), None)
    if gone is None:
        raise KeyError(note_id)
    await _write(books, [n for n in notes if n.id != note_id])
    await books.audit(f"user:{user}", "note_deleted", {"note": note_id})
    return gone


# --------------------------------------------------------------------------- #
# Dates and times in what was said (future-facing: "Friday" is the next one)
# --------------------------------------------------------------------------- #

WEEKDAYS = {d: i for i, d in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]  # fmt: skip
    )
}
MONTHS |= {m[:3]: n for m, n in list(MONTHS.items())} | {"sept": 9}
_WD = "|".join(WEEKDAYS)
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_ORD = r"(?:st|nd|rd|th)?"
DAY_RE = re.compile(
    rf"\b(?:the\s+)?(?:day after tomorrow|today|tonight|tomorrow|(?:(?:on|this|next)\s+)?(?:{_WD})"
    rf"|\d{{1,2}}{_ORD}\s+(?:of\s+)?(?:{_MON})\b(?:\s+\d{{4}})?|(?:{_MON})\s+\d{{1,2}}{_ORD}\b(?:,?\s+\d{{4}})?"
    rf"|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|\d{{4}}-\d{{2}}-\d{{2}})\b",
    re.I,
)
TIME_RE = re.compile(
    r"\b(?:at\s+)?(?:(noon|midday|midnight)|(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|o'?clock)?)\b",
    re.I,
)
AT_TIME_RE = re.compile(
    r"\b(?:at|from)\s+(noon|midday|\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.|o'?clock)?)"
    r"|\b(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.))",
    re.I,
)
DURATION_RE = re.compile(
    r"\bfor\s+(?:(an?|one|half an?|\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)|(half an hour))\b", re.I
)
UNTIL_RE = re.compile(r"\b(?:to|until|till|-|–)\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?)\b", re.I)
IN_MONTH_RE = re.compile(rf"\b(?:in|by|before|during|end of)\s+({_MON})\b", re.I)


def day_in(text: str, today: date) -> tuple[date, str] | None:
    """The first day named in `text`, looking forward from `today`, with the words that named it."""
    m = DAY_RE.search(text)
    if not m:
        return None
    words = m.group(0)
    t = re.sub(r"\s+", " ", words.lower().strip())
    t = re.sub(r"^the ", "", t)
    if t in ("today", "tonight"):
        return today, words
    if t == "tomorrow":
        return today + timedelta(days=1), words
    if t == "day after tomorrow":
        return today + timedelta(days=2), words
    wd = re.fullmatch(rf"(?:(on|this|next) )?({_WD})", t)
    if wd:
        ahead = (WEEKDAYS[wd[2]] - today.weekday()) % 7
        if wd[1] == "next":  # "next Friday": the one in next week
            monday_next = today + timedelta(days=7 - today.weekday())
            return monday_next + timedelta(days=WEEKDAYS[wd[2]]), words
        return today + timedelta(days=ahead), words
    try:
        return date.fromisoformat(t), words
    except ValueError:
        pass
    day = month = year = None
    if m2 := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t):
        day, month, year = int(m2[1]), int(m2[2]), int(m2[3]) if m2[3] else None
    elif m2 := re.fullmatch(rf"(\d{{1,2}}){_ORD} (?:of )?([a-z]+)(?: (\d{{4}}))?", t):
        day, month, year = int(m2[1]), MONTHS.get(m2[2]), int(m2[3]) if m2[3] else None
    elif m2 := re.fullmatch(rf"([a-z]+) (\d{{1,2}}){_ORD}(?:,? (\d{{4}}))?", t):
        day, month, year = int(m2[2]), MONTHS.get(m2[1]), int(m2[3]) if m2[3] else None
    if not day or not month:
        return None
    if year is not None and year < 100:
        year += 2000
    try:
        found = date(year or today.year, month, day)
        if year is None and found < today:
            found = date(today.year + 1, month, day)
    except ValueError:
        return None
    return found, words


def month_in(text: str, today: date) -> date | None:
    """'in March' / 'by March': the first of the next such month (this one if we are in it)."""
    m = IN_MONTH_RE.search(text)
    if not m:
        return None
    month = MONTHS[m[1].lower()]
    year = today.year if month >= today.month else today.year + 1
    return date(year, month, 1)


def _clock(token: str) -> time | None:
    t = token.lower().replace(".", "").replace(" ", "")
    if t in ("noon", "midday"):
        return time(12)
    if t == "midnight":
        return time(0)
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?(am|pm|oclock|o'clock)?", t)
    if not m:
        return None
    hour, minute, mark = int(m[1]), int(m[2] or 0), m[3]
    if minute > 59 or hour > 23:
        return None
    if mark == "pm" and hour < 12:
        hour += 12
    elif mark == "am" and hour == 12:
        hour = 0
    elif mark in (None, "oclock", "o'clock") and 1 <= hour <= 6:  # "at 3" in working hours is 3 pm
        hour += 12
    return time(hour, minute)


def time_in(text: str) -> tuple[time, str] | None:
    """The first clock time said ('at 10', '3pm', '15:30', 'noon'), with the words."""
    m = AT_TIME_RE.search(text)
    if not m:
        return None
    token = m[1] or m[2]
    found = _clock(token)
    return (found, m.group(0)) if found else None


def duration_in(text: str) -> int | None:
    m = DURATION_RE.search(text)
    if not m:
        return None
    if m[3]:
        return 30
    n, unit = m[1].lower(), m[2].lower()
    amount = 0.5 if n.startswith("half") else 1.0 if n in ("a", "an", "one") else float(n)
    minutes = round(amount * 60) if unit.startswith(("h", "hr")) else round(amount)
    return minutes if 5 <= minutes <= 24 * 60 else None


def uk_day(d: date) -> str:
    return f"{d:%A} {d.day} {d:%B}"


def hhmm(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return f"{local:%H:%M}"


# --------------------------------------------------------------------------- #
# What was asked
# --------------------------------------------------------------------------- #


@dataclass
class NoteAdd:
    text: str


@dataclass
class NoteRead:
    start: date | None
    end: date | None
    label: str


@dataclass
class NoteDelete:
    ref: str


@dataclass
class TodoAdd:
    text: str


@dataclass
class CalRead:
    start: date
    end: date
    label: str


@dataclass
class CalAdd:
    text: str


@dataclass
class CalRemove:
    text: str


@dataclass
class NextDeadline:
    vat_only: bool


Intent = NoteAdd | NoteRead | NoteDelete | TodoAdd | CalRead | CalAdd | CalRemove | NextDeadline

_EVENT_WORDS = r"(?:meeting|appointment|event|call|visit|catch[- ]?up|lunch|dinner|session|interview|reminder|booking)"
NOTE_DELETE_RE = re.compile(
    r"^\s*(?:please\s+)?(?:delete|remove|forget|scrap|bin|clear)\s+(?:my\s+|the\s+|that\s+)?note"
    r"(?:\s+(?:about|on|for|that says|saying|re)\s+(?P<ref>.+?))?\s*[.!?]*$",
    re.I,
)
NOTE_READ_RE = re.compile(
    r"^\s*(?:(?:please\s+)?(?:read|show|list|tell me|give me)\s+(?:me\s+)?(?:my\s+|the\s+|all\s+)?"
    r"(?:\w+\s+){0,2}notes?\b"
    r"|what(?:'s| is| are| were)?\s+(?:in\s+)?(?:my\s+)?notes?\b|what\s+notes\b|(?:do|did)\s+i\s+(?:have|take|make)\s+"
    r"any\s+notes\b|any\s+notes\b)",
    re.I,
)
NOTE_ADD_RE = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+)?(?:take|make|add|write(?:\s+down)?|jot(?:\s+down)?|save|create)\s+"
    r"(?:a|this|the|my)?\s*note\b\s*(?:of\s+|that\s+|saying\s+|to say\s+)?[:,\-–]?\s*(?P<text>.+)$"
    r"|^\s*(?:please\s+)?note(?:\s+down)?(?:\s+that)?\s*[:,\-–]?\s+(?P<text2>.+)$",
    re.I | re.S,
)
TODO_ADD_RE = re.compile(
    r"^\s*(?:please\s+)?(?:remind me to|add (?:a\s+)?(?:to-?do|todo|task)(?:\s+to\s+my\s+list)?\s*(?:to|:|,|-|–)?)\s*"
    r"(?P<text>.+)$",
    re.I | re.S,
)
CAL_REMOVE_RE = re.compile(
    rf"^\s*(?:please\s+)?(?:remove|delete|cancel|clear|take off|drop)\b.*?(?:\b{_EVENT_WORDS}\b|\bfrom my "
    r"(?:calendar|diary)\b)",
    re.I,
)
CAL_ADD_RE = re.compile(
    rf"^\s*(?:please\s+|can you\s+|could you\s+)?(?:add|book|put|schedule|create|set up|arrange|make|pencil in)\b"
    rf".*?(?:\b{_EVENT_WORDS}\b|\b(?:in|to|on|into) my (?:calendar|diary)\b)",
    re.I,
)
CAL_READ_RE = re.compile(
    r"\b(?:calendar|diary|schedule|agenda|meetings?|appointments?|events?)\b"
    r"|^\s*what(?:'s| is)\s+on\b|^\s*am i (?:free|busy)\b|^\s*what(?:'s| is| do i have)\s+(?:on\s+)?(?:today|tomorrow)",
    re.I,
)
DEADLINE_RE = re.compile(
    r"\b(?:next|upcoming|coming)\b.*\b(?:deadlines?|due dates?|vat (?:return|deadline|payment))\b"
    r"|\bwhen(?:'s| is)?\b.*\b(?:vat|deadline)\b.*\bdue\b|\bwhen(?:'s| is)\b.*\bnext\b.*\b(?:vat|deadline)",
    re.I,
)
_QUESTIONISH = re.compile(
    r"^\s*(how|what|why|which|who|when|where|is|are|do|does|did|have|has|any|show|list|am)\b", re.I
)


def read_range(text: str, today: date) -> tuple[date, date, str]:
    t = text.lower()
    if "next week" in t:
        start = today + timedelta(days=7 - today.weekday())
        return start, start + timedelta(days=6), "next week"
    if "this week" in t or "the week" in t or "week ahead" in t:
        return today, today + timedelta(days=6 - today.weekday()), "this week"
    if re.search(r"\b(next|coming) (?:few|couple of)? ?days\b", t):
        return today, today + timedelta(days=6), "the next seven days"
    if found := day_in(text, today):
        d = found[0]
        label = "today" if d == today else "tomorrow" if d == today + timedelta(days=1) else uk_day(d)
        return d, d, label
    return today, today, "today"


def note_range(text: str, today: date) -> tuple[date | None, date | None, str]:
    t = text.lower()
    if "today" in t:
        return today, today, "today"
    if "yesterday" in t:
        return today - timedelta(days=1), today - timedelta(days=1), "yesterday"
    if "this week" in t:
        return today - timedelta(days=today.weekday()), today, "this week"
    if "last week" in t:
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6), "last week"
    if "this month" in t:
        return today.replace(day=1), today, "this month"
    return None, None, "latest"


def spot(question: str, today: date) -> Intent | None:
    """Which of these requests it is, if any. Order matters: deleting a note before taking one, removing an event
    before adding one, and a to-do before an event ('remind me to book a call')."""
    q = question.strip()
    if not q:
        return None
    if m := NOTE_DELETE_RE.match(q):
        return NoteDelete((m["ref"] or "").strip())
    if NOTE_READ_RE.search(q):
        start, end, label = note_range(q, today)
        return NoteRead(start, end, label)
    if m := NOTE_ADD_RE.match(q):
        text = (m["text"] or m["text2"] or "").strip()
        return NoteAdd(text) if text else None
    if m := TODO_ADD_RE.match(q):
        return TodoAdd(m["text"].strip())
    if DEADLINE_RE.search(q):
        return NextDeadline(vat_only=bool(re.search(r"\bvat\b", q, re.I)))
    if CAL_REMOVE_RE.match(q):
        return CalRemove(q)
    if CAL_ADD_RE.match(q) and not _QUESTIONISH.match(q):
        return CalAdd(q)
    if _QUESTIONISH.match(q) and CAL_READ_RE.search(q) and not re.search(r"\b(vat|invoice|owe|spent|spend)\b", q, re.I):
        start, end, label = read_range(q, today)
        return CalRead(start, end, label)
    return None


# --------------------------------------------------------------------------- #
# Pieces of the answers
# --------------------------------------------------------------------------- #


def _due_of(text: str, today: date) -> date | None:
    if found := day_in(text, today):
        return found[0]
    return month_in(text, today)


def _clean_note(text: str) -> str:
    text = text.strip().strip("\"'“”‘’").strip()
    return text[:1].upper() + text[1:] if text else text


def _answer(text: str, period: AskPeriod, **extra: Any) -> AskAnswer:
    return AskAnswer(
        answer_md=text,
        key_numbers=[],
        citations=extra.pop("citations", []),
        suggested_actions=extra.pop("suggested_actions", []),
        confidence="high",
        model="code",
        period=period,
        **extra,
    )


def _words(text: str) -> set[str]:
    stop = {"the", "a", "an", "my", "about", "with", "to", "on", "at", "in", "for", "of", "and", "meeting", "note"}
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 1 and w not in stop}


def note_matches(notes: list[Note], ref: str) -> list[Note]:
    want = _words(ref)
    if not want:
        return []
    scored = [(len(want & _words(n.text)), n) for n in notes]
    best = max((s for s, _ in scored), default=0)
    return [n for s, n in scored if s == best and s > 0]


def event_line(e: CalendarEvent) -> str:
    when = "all day" if e.is_all_day else f"{hhmm(e.start)}–{hhmm(e.end)}"
    where = f" ({e.location})" if e.location else ""
    return f"{when} {e.subject or '(no title)'}{where}"


async def events_between(cal: CalendarProvider, start: date, end: date) -> list[CalendarEvent]:
    out: list[CalendarEvent] = []
    seen: set[str] = set()
    day = start
    while day <= end and (day - start).days < MAX_EVENT_DAYS:
        for e in await cal.list_events(day):
            if e.id not in seen:
                seen.add(e.id)
                out.append(e)
        day += timedelta(days=1)
    return sorted(out, key=lambda e: e.start)


def clash_line(e: CalendarEvent) -> str:
    when = "all day" if e.is_all_day else f"{hhmm(e.start)}–{hhmm(e.end)}"
    return f"{e.subject or '(no title)'}, {when}"


async def _clashes(calendar: CalendarFactory | None, plan: EventPlan) -> list[CalendarEvent]:
    """Events the planned one clashes with, by the Calendar page's rule (app/routes_calendar.py `clashes`: timed with
    timed, all-day with all-day); none when the calendar can't be read just now (the card is still offered; adding
    needs the write permission anyway)."""
    if calendar is None:
        return []
    from app.routes_calendar import clashes  # the one rule, shared with POST /calendar/events

    first, last = plan.start.astimezone(TZ).date(), (plan.end - timedelta(seconds=1)).astimezone(TZ).date()

    async def look(cal: CalendarProvider) -> list[CalendarEvent]:
        try:
            return await cal.list_range(first, last)
        except NotImplementedError:
            return await events_between(cal, first, last)

    try:
        events = await _with_calendar(calendar, look)
    except (GraphError, LookupError, OSError):
        return []
    return clashes(plan.start, plan.end, plan.all_day, events)


def _calendar_refused(exc: GraphError) -> bool:
    return exc.status in (401, 403)


CAL_PERMISSION = (
    "I can't open your calendar yet: Accnomos needs your permission to read it. Use **Plan my day** once and "
    "accept the calendar permission, then ask again."
)


async def _with_calendar(factory: CalendarFactory | None, work: Callable[[CalendarProvider], Any]) -> Any:
    if factory is None:
        raise LookupError("no calendar")
    cal = factory()
    try:
        return await work(cal)
    finally:
        if close := getattr(cal, "aclose", None):
            await close()


async def delete_calendar_event(cal: CalendarProvider, event_id: str) -> None:
    """Remove one event. Uses the provider's own `delete_event` when it has one (the calendar work adds it);
    otherwise Graph's DELETE /me/events/{id}, or the in-memory calendar's list."""
    if (own := getattr(cal, "delete_event", None)) is not None:
        try:
            await own(event_id)
            return
        except NotImplementedError:
            pass  # the interface's default: fall through to the ways below
        except FileNotFoundError as exc:
            raise KeyError(event_id) from exc
    events = getattr(cal, "events", None)
    if isinstance(events, list):  # FakeCalendarProvider (demo, test mode)
        if not any(e.id == event_id for e in events):
            raise KeyError(event_id)
        events[:] = [e for e in events if e.id != event_id]
        return
    from accnomos_connectors.msgraph import GRAPH  # Graph: the event, by id, in the default calendar

    await cal._request("DELETE", f"{GRAPH}/me/events/{event_id}")  # type: ignore[attr-defined]  # noqa: SLF001


# --------------------------------------------------------------------------- #
# Calendar request -> event fields
# --------------------------------------------------------------------------- #


def event_subject(text: str) -> str:
    """'add a meeting with Hartwell on Friday at 10 for an hour' -> 'Meeting with Hartwell'."""
    t = re.sub(
        r"^\s*(?:please\s+|can you\s+|could you\s+)?(?:add|book|put|schedule|create|set up|arrange|make|pencil in)\s+",
        "",
        text,
        flags=re.I,
    )
    t = re.sub(r"\b(?:in|to|on|into) my (?:calendar|diary)\b", " ", t, flags=re.I)
    t = DAY_RE.sub(" ", t)
    t = AT_TIME_RE.sub(" ", t)
    t = DURATION_RE.sub(" ", t)
    t = UNTIL_RE.sub(" ", t)
    t = re.sub(r"\bat\s+(?=[A-Z])", " at ", t)  # keep "at the Hendon site" (a place) as said
    t = re.sub(r"^\s*(?:an?|the)\s+", "", t.strip(), flags=re.I)
    t = re.sub(r"\s+(?:on|at|for|from|this|next|by)\s*$", "", " ".join(t.split()), flags=re.I)
    t = t.strip(" ,.;:-–")
    return (t[:1].upper() + t[1:])[:120] if t else ""


def event_location(subject: str) -> tuple[str, str]:
    """'Visit at the Hendon site' -> ('Visit', 'the Hendon site'); otherwise no location."""
    m = re.search(r"\s+at\s+(.+)$", subject)
    if m and not re.match(r"\d", m[1]):
        return subject[: m.start()].strip(), m[1].strip()
    return subject, ""


@dataclass
class EventPlan:
    subject: str
    location: str
    start: datetime
    end: datetime
    all_day: bool


def plan_event(text: str, today: date, now_local: datetime) -> EventPlan | Clarification:
    found_day = day_in(text, today)
    found_time = time_in(text)
    subject, location = event_location(event_subject(text))
    if not subject:
        return Clarification(kind="calendar_add_event", field="subject", question_md="What should the event be called?")
    if found_day is None:
        return Clarification(
            kind="calendar_add_event",
            field="date",
            question_md=f"Which day should **{subject}** go in your calendar?",
            ref=subject,
        )
    day = found_day[0]
    if found_time is None:
        if re.search(r"\ball[- ]day\b", text, re.I):
            start = datetime.combine(day, time(0), TZ)
            return EventPlan(subject, location, start, start + timedelta(days=1), True)
        return Clarification(
            kind="calendar_add_event",
            field="time",
            question_md=f"What time on {uk_day(day)} should **{subject}** start?",
            ref=subject,
        )
    start = datetime.combine(day, found_time[0], TZ)
    minutes = duration_in(text)
    end: datetime | None = None
    until = UNTIL_RE.search(text) if minutes is None else None
    t2 = _clock(until[1]) if until else None
    if t2 is not None and t2 > found_time[0]:
        end = datetime.combine(day, t2, TZ)
    if end is None:
        end = start + timedelta(minutes=minutes or DEFAULT_MINUTES)
    if start < now_local - timedelta(minutes=5):
        return Clarification(
            kind="calendar_add_event",
            field="date",
            question_md=f"{uk_day(day)} at {start:%H:%M} has already passed. Which day did you mean?",
            ref=subject,
        )
    return EventPlan(subject, location, start, end, False)


# --------------------------------------------------------------------------- #
# The answers
# --------------------------------------------------------------------------- #


async def handle(
    question: str,
    books: Books,
    period: AskPeriod,
    today: date,
    *,
    sign: Callable[[str, str, dict[str, Any], str], ProposedAction],
    calendar: CalendarFactory | None,
    deadlines: Callable[[], Any] | None = None,
    now_local: datetime | None = None,
) -> AskAnswer | None:
    """None when the question is none of these (Ask carries on as before)."""
    intent = spot(question, today)
    if intent is None:
        return None
    if now_local is None:  # the clock on the books' day (test mode and demos pin the day, not the clock)
        clock = datetime.now(TZ)
        now_local = clock if clock.date() == today else datetime.combine(today, clock.time(), TZ)

    if isinstance(intent, NoteAdd):
        text = _clean_note(intent.text)
        due = _due_of(text, today)
        preview = {
            "text": text,
            "due": due.isoformat() if due else None,
            "rows": [{"label": "Note", "value": text}] + ([{"label": "Due", "value": uk_day(due)}] if due else []),
        }
        summary = f"Save this note: “{text}”" + (f" (due {uk_day(due)})" if due else "") + "."
        action = sign("save_note", summary, preview, "Save this note")
        return _answer(summary, period, proposed_action=action)

    if isinstance(intent, TodoAdd):
        text = _clean_note(re.sub(r"\s*[.!]+$", "", intent.text))[:200]
        due = _due_of(text, today)
        preview = {
            "text": text,
            "due": due.isoformat() if due else None,
            "rows": [{"label": "To-do", "value": text}] + ([{"label": "Due", "value": uk_day(due)}] if due else []),
        }
        summary = f"Add a to-do: “{text}”" + (f", due {uk_day(due)}" if due else "") + "."
        return _answer(summary, period, proposed_action=sign("add_todo", summary, preview, "Add this to-do"))

    if isinstance(intent, NoteRead):
        notes = await load_notes(books)
        if intent.start and intent.end:
            notes = [n for n in notes if intent.start <= n.created.astimezone(TZ).date() <= intent.end]
        if not notes:
            when = "" if intent.label == "latest" else f" from {intent.label}"
            return _answer(f"You have no notes{when}. Say “take a note” and what to write.", period)
        shown = notes[:10]
        head = "Your latest notes" if intent.label == "latest" else f"Your notes from {intent.label}"
        lines = [
            f"- {n.text}"
            + (f" (due {uk_day(n.due)})" if n.due else "")
            + f" — {n.created.astimezone(TZ).day} {n.created.astimezone(TZ):%b}"
            for n in shown
        ]
        more = f"\n\n…and {len(notes) - len(shown)} more on the Notes page." if len(notes) > len(shown) else ""
        return _answer(f"{head}:\n\n" + "\n".join(lines) + more, period, citations=[NOTES])

    if isinstance(intent, NoteDelete):
        notes = await load_notes(books)
        if not notes:
            return _answer("You have no notes to delete.", period)
        found = note_matches(notes, intent.ref) if intent.ref else notes[:1]
        if not found:
            return _answer(f"I couldn't find a note about “{intent.ref}”. Say “read my notes” to hear them.", period)
        if len(found) > 1:
            return _answer(
                "Which note should I delete?",
                period,
                clarification=Clarification(
                    kind="delete_note",
                    field="note",
                    question_md="Which note should I delete?",
                    candidates=[n.text[:80] for n in found[:5]],
                    ref=intent.ref or None,
                ),
            )
        n = found[0]
        preview = {"note_id": n.id, "text": n.text, "rows": [{"label": "Note", "value": n.text}]}
        summary = f"Delete the note “{n.text}”."
        return _answer(summary, period, proposed_action=sign("delete_note", summary, preview, "Delete this note"))

    if isinstance(intent, NextDeadline):
        found = await deadlines() if deadlines else []
        if intent.vat_only:
            found = [d for d in found if getattr(d, "key", "") == "vat"]
        upcoming = [d for d in found if d.due >= today]
        if not upcoming:
            return _answer("I don't have an upcoming deadline in your books.", period)
        d = upcoming[0]
        days = (d.due - today).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        text = f"Your next deadline is the {d.title}, due {uk_day(d.due)} ({when})."
        return _answer(
            text,
            period,
            suggested_actions=[SuggestedAction(label="Open VAT", kind="open_vat", arg=None)] if d.key == "vat" else [],
        )

    if calendar is None:
        return _answer("Your calendar isn't connected here.", period)

    try:
        if isinstance(intent, CalRead):
            start, end, label = intent.start, intent.end, intent.label

            async def read(cal: CalendarProvider) -> list[CalendarEvent]:
                return await events_between(cal, start, end)

            events = await _with_calendar(calendar, read)
            if not events:
                return _answer(f"Nothing in your calendar {_for(label)}.", period)
            if start == end:
                body = "\n".join(f"- {event_line(e)}" for e in events)
                return _answer(f"{_cap(label)} you have {_count(len(events))}:\n\n{body}", period)
            days: dict[date, list[str]] = {}
            for e in events:
                days.setdefault(e.start.astimezone(TZ).date(), []).append(event_line(e))
            body = "\n".join(f"- **{uk_day(d)}:** " + "; ".join(v) for d, v in sorted(days.items()))
            return _answer(f"{_cap(label)} you have {_count(len(events))}:\n\n{body}", period)

        if isinstance(intent, CalAdd):
            plan = plan_event(intent.text, today, now_local)
            if isinstance(plan, Clarification):
                return _answer(plan.question_md, period, clarification=plan)
            when = (
                f"{uk_day(plan.start.date())}, all day"
                if plan.all_day
                else f"{uk_day(plan.start.date())}, {plan.start:%H:%M}–{plan.end:%H:%M}"
            )
            clashes = await _clashes(calendar, plan)
            preview = {
                "subject": plan.subject,
                "start": plan.start.isoformat(),
                "end": plan.end.isoformat(),
                "all_day": plan.all_day,
                "location": plan.location,
                "rows": [{"label": "Event", "value": plan.subject}, {"label": "When", "value": when}]
                + ([{"label": "Where", "value": plan.location}] if plan.location else [])
                + [{"label": "Clashes with", "value": clash_line(c)} for c in clashes],
                "conflicts": [
                    {"id": c.id, "subject": c.subject, "start": c.start.isoformat(), "end": c.end.isoformat()}
                    for c in clashes
                ],
            }
            summary = f"Add **{plan.subject}** to your calendar: {when}" + (
                f", at {plan.location}." if plan.location else "."
            )
            if clashes:
                summary += " This clashes with " + "; ".join(clash_line(c) for c in clashes) + "."
            confirm = "Add it anyway" if clashes else "Add this to your calendar"
            return _answer(summary, period, proposed_action=sign("calendar_add_event", summary, preview, confirm))

        if isinstance(intent, CalRemove):
            text = intent.text
            found_day = day_in(text, today)
            start = found_day[0] if found_day else today
            end = start if found_day else today + timedelta(days=13)

            async def look(cal: CalendarProvider) -> list[CalendarEvent]:
                return await events_between(cal, start, end)

            events = [e for e in await _with_calendar(calendar, look) if e.end.astimezone(TZ) >= now_local]
            if (t := time_in(text)) is not None:
                events = [e for e in events if e.start.astimezone(TZ).time().replace(second=0) == t[0]]
            ref_words = _words(event_subject(re.sub(r"^\s*\S+\s+", "add ", text)))
            ref_words -= {"remove", "delete", "cancel", "calendar", "diary", "from", "off"}
            if ref_words:
                named = [e for e in events if ref_words & _words(e.subject)]
                events = named or ([] if not t else events)
            scope = uk_day(start) if found_day else "the next two weeks"
            if not events:
                return _answer(f"I couldn't find that event in your calendar for {scope}.", period)
            if len(events) > 1:
                return _answer(
                    "Which event should I remove?",
                    period,
                    clarification=Clarification(
                        kind="calendar_remove_event",
                        field="event",
                        question_md="Which event should I remove?",
                        candidates=[f"{uk_day(e.start.astimezone(TZ).date())} {event_line(e)}" for e in events[:6]],
                    ),
                )
            e = events[0]
            when = f"{uk_day(e.start.astimezone(TZ).date())}, {'all day' if e.is_all_day else hhmm(e.start)}"
            preview = {
                "event_id": e.id,
                "subject": e.subject,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
                "rows": [{"label": "Event", "value": e.subject or "(no title)"}, {"label": "When", "value": when}],
            }
            summary = f"Remove **{e.subject or '(no title)'}** ({when}) from your calendar."
            return _answer(
                summary,
                period,
                proposed_action=sign("calendar_remove_event", summary, preview, "Remove this event"),
            )
    except GraphError as exc:
        if _calendar_refused(exc):
            return _answer(CAL_PERMISSION, period)
        raise
    return None


def _count(n: int) -> str:
    return "1 event" if n == 1 else f"{n} events"


def _for(label: str) -> str:
    if label in ("today", "tomorrow", "this week", "next week"):
        return label
    return f"on {label}" if label[0].isupper() else f"for {label}"


def _cap(label: str) -> str:
    out = label if label in ("today", "tomorrow") else f"On {label}" if label[0].isupper() else f"For {label}"
    return out[:1].upper() + out[1:]


# --------------------------------------------------------------------------- #
# Running an approved card (called from app/actions.py)
# --------------------------------------------------------------------------- #


async def run_save_note(action: ProposedAction, books: Books, user: str) -> tuple[str, dict[str, Any]]:
    p = action.preview
    due = date.fromisoformat(p["due"]) if p.get("due") else None
    note = await add_note(
        books, NoteIn(text=p["text"], due=due, source="voice" if action.transcribed_by else "typed"), user
    )
    return f"Saved your note: “{note.text}”.", {"note_id": note.id}


async def run_delete_note(action: ProposedAction, books: Books, user: str) -> tuple[str, dict[str, Any]]:
    try:
        gone = await delete_note(books, action.preview["note_id"], user)
    except KeyError as exc:
        raise LookupError("That note has already been deleted.") from exc
    return f"Deleted the note “{gone.text}”.", {"note_id": gone.id}


async def run_add_todo(action: ProposedAction, books: Books, user: str) -> tuple[str, dict[str, Any]]:
    from app.todos import TodoIn, add_todo

    p = action.preview
    todo, created = await add_todo(
        books, TodoIn(text=p["text"], due=date.fromisoformat(p["due"]) if p.get("due") else None), user
    )
    word = "Added" if created else "Already on your list:"
    return f"{word} “{todo.text}” to your to-dos.", {"todo_id": todo.id, "created": created}


async def run_calendar_add(action: ProposedAction, calendar: CalendarFactory | None) -> tuple[str, dict[str, Any]]:
    if calendar is None:
        raise LookupError("Your calendar isn't connected here.")
    p = action.preview
    start, end = datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])

    async def add(cal: CalendarProvider) -> str:
        # Approving the card is the user's say-so, clashes included (the card named them): no conflict check here.
        try:
            made = await cal.add_event(
                NewCalendarEvent(
                    subject=p["subject"],
                    start=start,
                    end=end,
                    location=p.get("location") or "",
                    body="Added by Accnomos.",
                    key=f"event:{action.id}",
                )
            )
            return made.id
        except NotImplementedError:
            return await cal.create_event(p["subject"], start, end, p.get("location") or "", "Added by Accnomos.")

    try:
        event_id = await _with_calendar(calendar, add)
    except GraphError as exc:
        if _calendar_refused(exc):
            raise LookupError(CAL_PERMISSION.replace("read it", "add events to it")) from exc
        raise
    local = start.astimezone(TZ)
    return (
        f"Added **{p['subject']}** to your calendar for {uk_day(local.date())} at {local:%H:%M}.",
        {"event_id": event_id},
    )


async def run_calendar_remove(action: ProposedAction, calendar: CalendarFactory | None) -> tuple[str, dict[str, Any]]:
    if calendar is None:
        raise LookupError("Your calendar isn't connected here.")
    p = action.preview

    async def remove(cal: CalendarProvider) -> None:
        await delete_calendar_event(cal, p["event_id"])

    try:
        await _with_calendar(calendar, remove)
    except (KeyError, FileNotFoundError) as exc:
        raise LookupError("That event is no longer in your calendar.") from exc
    except GraphError as exc:
        if exc.status == 404:
            raise LookupError("That event is no longer in your calendar.") from exc
        if _calendar_refused(exc):
            raise LookupError(CAL_PERMISSION.replace("read it", "change it")) from exc
        raise
    return f"Removed **{p.get('subject') or 'the event'}** from your calendar.", {"event_id": p["event_id"]}


def utc_now() -> datetime:
    return datetime.now(UTC)
