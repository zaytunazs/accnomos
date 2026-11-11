"""Notes, to-dos, calendar and deadlines by voice or typed (app/assistant_tasks.py), and spoken approval of cards."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.base import CalendarEvent
from accnomos_connectors.fake import FakeCalendarProvider
from app import assistant_tasks as t
from app.books import Books
from app.schemas import AskPeriod, Clarification

TZ = ZoneInfo("Europe/London")
TODAY = date(2026, 11, 4)  # a Wednesday
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=TZ)
TOKEN = "graph-token-1"
USER = "sam@example.co.uk"
H = {"X-Graph-Token": TOKEN, "X-User": USER}
PERIOD = AskPeriod(start=date(2026, 10, 1), end=date(2026, 12, 31))


def ev(id_: str, subject: str, day: date, hour: int, minutes: int = 60) -> CalendarEvent:
    start = datetime.combine(day, time(hour), TZ)
    return CalendarEvent(id=id_, subject=subject, start=start, end=start + timedelta(minutes=minutes))


# Spotting ------------------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("q", "kind"),
    [
        ("take a note: the van needs an MOT in March", t.NoteAdd),
        ("Note that Hartwell wants the quote by Friday", t.NoteAdd),
        ("read my notes", t.NoteRead),
        ("what notes did I take this week?", t.NoteRead),
        ("delete the note about the van", t.NoteDelete),
        ("remind me to call the accountant on Friday", t.TodoAdd),
        ("add a to-do: order more screws", t.TodoAdd),
        ("what's on my calendar tomorrow?", t.CalRead),
        ("do I have any meetings this week?", t.CalRead),
        ("add a meeting with Hartwell on Friday at 10", t.CalAdd),
        ("book a site visit at the Hendon site tomorrow at 2pm for 2 hours", t.CalAdd),
        ("remove the 3pm meeting tomorrow", t.CalRemove),
        ("cancel my call with Sterling on Thursday", t.CalRemove),
        ("when is my next VAT deadline?", t.NextDeadline),
        ("can you change it to 10 to 11?", t.CalMove),
        ("I want to change the event in my calendar.", t.CalMove),
        ("move the site visit to Friday at 2pm", t.CalMove),
        ("reschedule my meeting with Sterling", t.CalMove),
    ],
)
def test_spot(q: str, kind: type) -> None:
    assert isinstance(t.spot(q, TODAY), kind)


@pytest.mark.parametrize(
    "q",
    ["how much VAT do I owe?", "send a £100 invoice to JM Trading", "log 4 hours for Alex", "who owes me the most?"],
)
def test_other_questions_are_left_alone(q: str) -> None:
    assert t.spot(q, TODAY) is None


def test_days_and_times_look_forward() -> None:
    assert t.day_in("on Friday", TODAY)[0] == date(2026, 11, 6)
    assert t.day_in("next Friday", TODAY)[0] == date(2026, 11, 13)
    assert t.day_in("tomorrow", TODAY)[0] == date(2026, 11, 5)
    assert t.day_in("on 3 March", TODAY)[0] == date(2027, 3, 3)
    assert t.month_in("the van needs an MOT in March", TODAY) == date(2027, 3, 1)
    assert t.time_in("at 10")[0] == time(10)
    assert t.time_in("at 3")[0] == time(15)  # working hours
    assert t.time_in("at 3:30pm")[0] == time(15, 30)
    assert t.time_in("at noon")[0] == time(12)
    assert t.duration_in("for 2 hours") == 120 and t.duration_in("for half an hour") == 30


def test_plan_event_fields_and_questions() -> None:
    p = t.plan_event("add a meeting with Hartwell on Friday at 10", TODAY, NOW)
    assert isinstance(p, t.EventPlan)
    assert p.subject == "Meeting with Hartwell" and p.start == datetime(2026, 11, 6, 10, tzinfo=TZ)
    assert p.end - p.start == timedelta(hours=1)
    v = t.plan_event("book a site visit at the Hendon site tomorrow at 2pm for 2 hours", TODAY, NOW)
    assert isinstance(v, t.EventPlan) and v.location == "the Hendon site" and v.subject == "Site visit"
    assert v.end - v.start == timedelta(hours=2)
    no_time = t.plan_event("add a meeting with Hartwell on Friday", TODAY, NOW)
    assert isinstance(no_time, Clarification) and no_time.field == "time"
    no_day = t.plan_event("add a meeting with Hartwell at 10", TODAY, NOW)
    assert isinstance(no_day, Clarification) and no_day.field == "date"


# Handling ------------------------------------------------------------------------------------------------------- #


@pytest.fixture
def books() -> Books:
    return Books(FakeStorageProvider())


def signer(made: list[dict[str, Any]]):
    from app import actions

    def sign(kind: Any, summary: str, preview: dict[str, Any], confirm: str):
        made.append({"kind": kind, "preview": preview})
        return actions.new_action(actions.Draft(kind, summary, preview, confirm), TOKEN)

    return sign


async def ask(q: str, books: Books, cal: FakeCalendarProvider | None = None, deadlines=None):
    made: list[dict[str, Any]] = []
    out = await t.handle(
        q,
        books,
        PERIOD,
        TODAY,
        sign=signer(made),
        calendar=(lambda: cal) if cal is not None else None,
        deadlines=deadlines,
        now_local=NOW,
    )
    return out, made


async def test_note_card_then_read_and_delete(books: Books) -> None:
    out, _ = await ask("take a note: the van needs an MOT in March", books)
    assert out is not None and out.proposed_action is not None
    a = out.proposed_action
    assert a.kind == "save_note" and a.preview["text"] == "The van needs an MOT in March"
    assert a.preview["due"] == "2027-03-01"
    assert await t.load_notes(books) == []  # nothing saved before Approve
    await t.run_save_note(a, books, USER)
    read, _ = await ask("read my notes", books)
    assert read is not None and "The van needs an MOT in March" in read.answer_md and read.model == "code"
    gone, _ = await ask("delete the note about the van", books)
    assert gone is not None and gone.proposed_action is not None and gone.proposed_action.kind == "delete_note"
    await t.run_delete_note(gone.proposed_action, books, USER)
    assert await t.load_notes(books) == []
    none, _ = await ask("delete the note about the boat", books)
    assert none is not None and "no notes" in none.answer_md


async def test_ambiguous_note_delete_asks(books: Books) -> None:
    await t.add_note(books, t.NoteIn(text="Van MOT in March"), USER)
    await t.add_note(books, t.NoteIn(text="Van insurance renewal"), USER)
    out, _ = await ask("delete the note about the van", books)
    assert out is not None and out.clarification is not None and len(out.clarification.candidates) == 2


async def test_todo_card_and_run(books: Books) -> None:
    out, _ = await ask("remind me to call the accountant on Friday", books)
    assert out is not None and out.proposed_action is not None
    a = out.proposed_action
    assert a.kind == "add_todo" and a.preview["due"] == "2026-11-06"
    text, result = await t.run_add_todo(a, books, USER)
    assert result["created"] and "to-dos" in text


async def test_calendar_read_add_remove(books: Books) -> None:
    cal = FakeCalendarProvider(
        [ev("e1", "Meeting with Sterling", date(2026, 11, 5), 15), ev("e2", "Dentist", date(2026, 11, 5), 11)]
    )
    read, _ = await ask("what's on my calendar tomorrow?", books, cal)
    assert read is not None and "2 events" in read.answer_md and "15:00–16:00 Meeting with Sterling" in read.answer_md
    add, _ = await ask("add a meeting with Hartwell on Friday at 10", books, cal)
    assert add is not None and add.proposed_action is not None and add.proposed_action.kind == "calendar_add_event"
    assert cal.created == []  # nothing until Approve
    msg, _ = await t.run_calendar_add(add.proposed_action, lambda: cal)
    assert cal.created[0].subject == "Meeting with Hartwell" and "Added" in msg
    rm, _ = await ask("remove the 3pm meeting tomorrow", books, cal)
    assert rm is not None and rm.proposed_action is not None and rm.proposed_action.preview["event_id"] == "e1"
    await t.run_calendar_remove(rm.proposed_action, lambda: cal)
    assert all(e.id != "e1" for e in cal.events)
    twice = await ask("cancel the meeting with Sterling tomorrow", books, cal)
    assert twice[0] is not None and "couldn't find" in twice[0].answer_md


async def test_calendar_remove_ambiguous_asks(books: Books) -> None:
    cal = FakeCalendarProvider(
        [ev("a", "Site meeting", date(2026, 11, 5), 10), ev("b", "Site meeting", date(2026, 11, 5), 14)]
    )
    out, _ = await ask("cancel the site meeting tomorrow", books, cal)
    assert out is not None and out.clarification is not None and len(out.clarification.candidates) == 2


async def test_next_deadline(books: Books) -> None:
    class D:
        key, title, due = "vat", "VAT return Jul–Sep 2026", date(2026, 11, 7)

    async def deadlines():
        return [D()]

    out, _ = await ask("when is my next VAT deadline?", books, deadlines=deadlines)
    assert out is not None and "due Saturday 7 November (in 3 days)" in out.answer_md


# Routes: Ask end to end and spoken approval --------------------------------------------------------------------- #


@pytest.fixture
def client(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app import routes_actions, routes_ask
    from app.main import app
    from app.routes_books import get_books

    # The routes read the real clock, so "tomorrow" here must be the real tomorrow, not TODAY + 1.
    cal = FakeCalendarProvider([ev("e1", "Meeting with Sterling", date.today() + timedelta(days=1), 15)])

    async def override():
        yield books

    monkeypatch.setattr(routes_ask, "calendar_factory", lambda request: lambda: cal)
    monkeypatch.setattr(routes_actions, "calendar_factory", lambda request: lambda: cal)
    app.dependency_overrides[get_books] = override
    try:
        yield TestClient(app), cal
    finally:
        app.dependency_overrides.clear()


def test_ask_note_then_voice_yes_approves(client) -> None:
    c, _cal = client
    r = c.post("/books/ask", json={"question": "take a note: buy a new drill bit set"}, headers=H)
    assert r.status_code == 200, r.text
    card = r.json()["proposed_action"]
    assert card["kind"] == "save_note"
    unclear = c.post("/actions/approve", json={"action": card, "via": "voice", "heard": "hmm maybe"}, headers=H)
    assert unclear.status_code == 422
    ok = c.post("/actions/approve", json={"action": card, "via": "voice", "heard": "Yes please"}, headers=H)
    assert ok.status_code == 200, ok.text
    notes = c.get("/notes", headers=H).json()
    assert notes[0]["text"] == "Buy a new drill bit set"
    gone = c.delete(f"/notes/{notes[0]['id']}", headers=H)
    assert gone.status_code == 200 and c.get("/notes", headers=H).json() == []


def test_calendar_add_by_ask_and_tap(client) -> None:
    c, cal = client
    r = c.post("/books/ask", json={"question": "add a meeting with Hartwell tomorrow at 10"}, headers=H)
    card = r.json()["proposed_action"]
    assert card["kind"] == "calendar_add_event"
    ok = c.post("/actions/approve", json={"action": card}, headers=H)
    assert ok.status_code == 200, ok.text
    assert cal.created and cal.created[0].subject == "Meeting with Hartwell"
    read = c.post("/books/ask", json={"question": "what's on my calendar tomorrow?"}, headers=H).json()
    assert "Meeting with Hartwell" in read["answer_md"] and "Meeting with Sterling" in read["answer_md"]


@pytest.mark.parametrize(
    ("kind", "preview", "tap"),
    [
        ("pay_overtime", {}, True),
        ("match_bank_line", {}, True),
        ("close_month", {}, True),
        ("chase_invoice", {}, True),  # emails a payment reminder
        ("create_invoice", {"send": True}, True),  # emailed to the customer
        ("create_invoice", {"send": False}, False),  # a draft
        ("create_quote", {}, False),
        ("convert_quote_to_invoice", {}, False),  # a draft invoice
        ("log_timesheet", {}, False),
        ("log_timesheet", {"overtime_multiplier": "2", "overtime_hours": "1"}, True),  # overtime changes pay
        ("log_mileage", {}, False),
        ("add_to_shopping_list", {}, False),
        ("save_note", {}, False),
        ("delete_note", {}, False),
        ("add_todo", {}, False),
        ("calendar_add_event", {}, False),
        ("calendar_remove_event", {}, False),
        ("calendar_move_event", {}, False),
        ("remind_unpaid", {}, True),  # sends PayPal or email reminders
        ("payment_link_message", {}, False),  # a message the user sends from their own phone
    ],
)
def test_which_cards_need_a_tap(kind: str, preview: dict[str, Any], tap: bool) -> None:
    """The one classification (app/actions.py needs_tap); every action kind is listed here."""

    from app import actions

    assert actions.needs_tap(kind, preview) is tap
    card = actions.new_action(actions.Draft(kind, "x", preview, "Do it"), TOKEN)
    assert card.tap_only is tap
    actions.verify(card, TOKEN)  # tap_only is signed with the rest
    if not tap:
        assert "tap_only" not in actions._payload(card).decode()  # noqa: SLF001 - other cards sign as before


def test_every_action_kind_is_classified() -> None:
    from typing import get_args

    from app.schemas import ActionKind

    listed = {
        "pay_overtime", "match_bank_line", "close_month", "chase_invoice", "create_invoice", "create_quote",
        "convert_quote_to_invoice", "log_timesheet", "log_mileage", "add_to_shopping_list", "save_note",
        "delete_note", "add_todo", "calendar_add_event", "calendar_remove_event", "calendar_move_event",
        "remind_unpaid", "payment_link_message",
    }  # fmt: skip
    assert set(get_args(ActionKind)) == listed, "a new action kind: decide in needs_tap and add it to the test above"


def test_money_cards_need_a_tap() -> None:
    from app import actions

    assert "pay_overtime" in actions.TAP_ONLY
    for said in ("yes", "Yes please.", "go ahead", "do it", "approve", "confirm"):
        assert actions.YES_WORDS.match(said), said
    for said in ("no", "cancel", "yes but change the time", "not yet", ""):
        assert not actions.YES_WORDS.match(said), said


async def test_voice_approval_of_a_money_card_is_refused(books: Books) -> None:
    from app import actions

    a = actions.new_action(actions.Draft("pay_overtime", "Pay", {}, "Pay it"), TOKEN)
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN, via="voice", approval_heard="yes")
    with pytest.raises(actions.ActionError) as exc:
        await actions.approve(a, ctx)
    assert exc.value.status == 403


async def test_voice_approval_of_a_sent_invoice_is_refused_but_tap_is_not_checked(books: Books) -> None:
    from app import actions

    a = actions.new_action(actions.Draft("create_invoice", "Invoice", {"send": True}, "Send it"), TOKEN)
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN, via="voice", approval_heard="go ahead")
    with pytest.raises(actions.ActionError) as exc:
        await actions.approve(a, ctx)
    assert exc.value.status == 403 and "Approve button" in str(exc.value)


async def test_calendar_add_names_a_clash_and_adds_anyway(books: Books) -> None:
    cal = FakeCalendarProvider([ev("v1", "Site visit, Hartwell", date(2026, 11, 6), 10)])
    out, _ = await ask("add a call with Sterling on Friday at 10:30", books, cal)
    assert out is not None and out.proposed_action is not None
    a = out.proposed_action
    assert a.preview["conflicts"][0]["subject"] == "Site visit, Hartwell"
    assert "clashes with Site visit, Hartwell, 10:00–11:00" in a.summary_md and a.confirm_text == "Add it anyway"
    assert {"label": "Clashes with", "value": "Site visit, Hartwell, 10:00–11:00"} in a.preview["rows"]
    await t.run_calendar_add(a, lambda: cal)
    assert cal.created[-1].subject == "Call with Sterling" and cal.created[-1].key == f"event:{a.id}"
    free, _ = await ask("add a call with Sterling on Friday at 2pm", books, cal)
    assert free is not None and free.proposed_action is not None and free.proposed_action.preview["conflicts"] == []


def test_voice_yes_is_audited_as_spoken(client, books: Books) -> None:
    import asyncio
    import json

    c, _cal = client
    card = c.post("/books/ask", json={"question": "take a note: ring the scaffolder"}, headers=H).json()[
        "proposed_action"
    ]
    assert (
        c.post("/actions/approve", json={"action": card, "via": "voice", "heard": "do it"}, headers=H).status_code
        == 200
    )
    path = f"_System/audit/actions/{card['created_at'][:7]}.jsonl"
    rows = [json.loads(x) for x in asyncio.run(books.storage.read(path)).decode().splitlines()]
    claimed = [r for r in rows if r.get("via") == "voice"]
    assert claimed and claimed[0]["approval_heard"] == "do it"


def test_transcribe_only_hears(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai import stt, voice
    from app.schemas import Transcription

    c, cal = client

    class Heard:
        text = "yes please"
        by = Transcription(provider="muse", label="the hosted speech-to-text model", model="muse-voice-transcribe-1.0")

    async def fake_transcribe(wav, providers, **_):
        return Heard()

    async def fake_wav(data, ctype, name):
        return b"RIFF"

    monkeypatch.setattr(stt, "chain", lambda cfg: ["muse"])
    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(voice, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(voice, "to_wav", fake_wav)
    r = c.post("/books/ask/transcribe", files={"audio": ("reply.webm", b"\x1a\x45", "audio/webm")}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["transcript"] == "yes please"
    assert cal.created == []


# Moving an event, and times as speech-to-text writes them ------------------------------------------------------- #


@pytest.mark.parametrize(
    ("said", "written"),
    [
        ("can you change it to ten to eleven?", "can you change it to 10 to 11?"),
        ("a meeting ten o'clock tomorrow", "a meeting 10 o'clock tomorrow"),
        ("call at half past two", "call at 2:30"),
        ("lunch at twelve thirty", "lunch at 12:30"),
        ("book it for one hour", "book it for one hour"),  # a length, not a time
    ],
)
def test_spoken_times_become_digits(said: str, written: str) -> None:
    assert t.normalise_spoken(said) == written


async def test_move_the_event_just_talked_about(books: Books) -> None:
    visit = ev("v1", "Site visit, Harbour Lane kitchen", date(2026, 11, 5), 9)
    cal = FakeCalendarProvider([visit, ev("d1", "Dentist", date(2026, 11, 6), 15)])
    made: list[dict[str, Any]] = []
    out = await t.handle(
        "can you change it to ten to eleven?",
        books,
        PERIOD,
        TODAY,
        sign=signer(made),
        calendar=lambda: cal,
        now_local=NOW,
        history=["Tomorrow you have 1 event:\n\n- 09:00–10:00 Site visit, Harbour Lane kitchen"],
    )
    assert out is not None and out.proposed_action is not None
    a = out.proposed_action
    assert a.kind == "calendar_move_event" and a.preview["event_id"] == "v1"
    assert a.preview["start"].startswith("2026-11-05T10:00") and a.preview["end"].startswith("2026-11-05T11:00")
    assert "Thursday 5 November, 09:00–10:00" in out.answer_md and "10:00–11:00" in out.answer_md
    assert cal.events[0].start.hour == 9  # nothing changes before Approve
    msg, _ = await t.run_calendar_move(a, lambda: cal)
    moved = next(e for e in cal.events if e.id == "v1")
    assert moved.start.astimezone(TZ).hour == 10 and moved.subject == visit.subject and "Moved" in msg


async def test_move_by_name_to_another_day_keeps_its_length_and_names_a_clash(books: Books) -> None:
    cal = FakeCalendarProvider(
        [ev("s1", "Meeting with Sterling", date(2026, 11, 5), 15, 90), ev("x", "Dentist", date(2026, 11, 6), 14)]
    )
    out, _ = await ask("move the meeting with Sterling to Friday at 2pm", books, cal)
    assert out is not None and out.proposed_action is not None
    p = out.proposed_action.preview
    assert p["start"].startswith("2026-11-06T14:00") and p["end"].startswith("2026-11-06T15:30")
    assert p["conflicts"] and p["conflicts"][0]["id"] == "x" and out.proposed_action.confirm_text == "Move it anyway"


async def test_move_without_a_time_asks_when_and_unknown_asks_which(books: Books) -> None:
    cal = FakeCalendarProvider([ev("v1", "Site visit", date(2026, 11, 5), 9)])
    out, _ = await ask("I want to change the event in my calendar.", books, cal)
    assert out is not None and out.clarification is not None and out.clarification.field == "time"
    assert "Site visit" in out.answer_md
    cal2 = FakeCalendarProvider(
        [ev("a", "Site visit", date(2026, 11, 5), 9), ev("b", "Dentist", date(2026, 11, 6), 11)]
    )
    which, _ = await ask("move it to 3pm", books, cal2)
    assert which is not None and which.clarification is not None and len(which.clarification.candidates) == 2


async def test_spoken_meeting_at_ten_oclock_is_planned(books: Books) -> None:
    cal = FakeCalendarProvider([])
    out, _ = await ask("add to my calendar that I have a meeting ten o'clock tomorrow", books, cal)
    assert out is not None and out.proposed_action is not None
    p = out.proposed_action.preview
    assert p["subject"] == "Meeting" and p["start"].startswith("2026-11-05T10:00")


async def test_all_day_bill_keeps_a_clean_title(books: Books) -> None:
    cal = FakeCalendarProvider([])
    out, _ = await ask("put the BT Broadband bill in my calendar on 8 November, all day", books, cal)
    assert out is not None and out.proposed_action is not None
    p = out.proposed_action.preview
    assert p["subject"] == "BT Broadband bill" and p["all_day"] is True
