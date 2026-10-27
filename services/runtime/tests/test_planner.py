"""Day planner: postcode districts, grouping and order, no overlaps with the calendar, constraints, lunch and
admin, the rationale checks, "plan my Thursday", and the /plan/day and /plan/day/apply routes over
FakeStorageProvider + FakeCalendarProvider (apply creates only new items, once)."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pytest
from accnomos_connectors import CalendarEvent, FakeCalendarProvider, FakeStorageProvider
from fastapi.testclient import TestClient

from app import jobs, planner
from app.ai import plan as plan_ai
from app.books import Books
from app.jobs import Job
from app.plan_apply import APPLIED, VEHICLES
from app.planner import TZ, Constraints, Due, PlanItem, VatSettings, build_plan, plan_intent, postcode_district

DAY = date(2026, 10, 29)  # a Thursday, GMT
TODAY = date(2026, 10, 27)
USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}


def at(hh: int, mm: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hh, mm), TZ)


def job(n: int, address: str | None, hours: float | None = None, name: str | None = None, **kw: object) -> Job:
    return Job(id=f"{n:012x}", name=name or f"Job {n}", site_address=address, estimate_hours=hours, **kw)


def event(subject: str, start: datetime, end: datetime, **kw: object) -> CalendarEvent:
    return CalendarEvent(id=f"ev-{subject}", subject=subject, start=start, end=end, **kw)


def visits(plan: planner.Plan) -> list[PlanItem]:
    return [i for i in plan.items if i.kind == "visit"]


def assert_no_overlaps(plan: planner.Plan, existing: list[CalendarEvent] = ()) -> None:  # type: ignore[assignment]
    mine = sorted((i for i in plan.items if i.kind != "existing"), key=lambda i: i.start)
    for a, b in zip(mine, mine[1:]):
        assert a.end <= b.start, f"{a.title} overlaps {b.title}"
    for i in mine:
        for ev in existing:
            if not ev.is_all_day and ev.show_as not in planner.NOT_BUSY:
                assert not planner.overlaps((i.start, i.end), (ev.start, ev.end)), f"{i.title} overlaps {ev.subject}"


# --------------------------------------------------------------------------- #
# Postcodes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("address", "want"), [
    ("12 Elm Road, Leeds LS6 2AB", "LS6"),
    ("flat 3, 1 high st, london sw1a 1aa", "SW1A"),
    ("Unit 4, M1 1AE", "M1"),
    ("B338TH", "B33"),
    ("Old address LS1 4AP, now at LS12 3DE", "LS12"),
    ("12 Elm Road, Leeds", None),
    (None, None),
])
def test_postcode_district(address: str | None, want: str | None) -> None:
    assert postcode_district(address) == want


def test_districts_sort_by_area_then_number() -> None:
    assert sorted(["LS12", "M1", "LS6", "LS1", "SW1A", "SW1"], key=planner.district_key) == ["LS1", "LS6", "LS12", "M1", "SW1", "SW1A"]


# --------------------------------------------------------------------------- #
# Building the plan
# --------------------------------------------------------------------------- #


def test_visits_are_grouped_by_district_with_travel_rules() -> None:
    js = [job(1, "LS7 3AA"), job(2, "LS6 1AA", name="B"), job(3, "LS6 2BB", name="A"), job(4, "M1 1AE")]
    plan = build_plan(DAY, js, [], constraints=Constraints(end="20:00"))
    v = visits(plan)
    assert [postcode_district(i.location) for i in v] == ["LS6", "LS6", "LS7", "M1"]
    assert [i.title for i in v[:2]] == ["A", "B"]  # stable order inside a district
    assert plan.districts == ["LS6", "LS7", "M1"]
    travel = [int((i.end - i.start).total_seconds() // 60) for i in plan.items if i.kind == "travel"]
    assert travel == [30, 30, 60, 60]  # first visit, same district, new district, new district
    assert all(i.end - i.start == timedelta(hours=2) for i in v)  # default block
    assert v[0].start == at(8, 30)
    assert_no_overlaps(plan)


def test_whole_districts_are_preferred_when_visits_are_limited() -> None:
    js = [job(1, "LS7 3AA"), job(2, "LS6 1AA"), job(3, "LS6 2BB"), job(4, "LS6 3CC"), job(5, "M1 1AE")]
    plan = build_plan(DAY, js, [], constraints=Constraints(max_visits=3))
    assert {postcode_district(i.location) for i in visits(plan)} == {"LS6"}
    assert any("2 more open jobs not planned (limit 3 visits)" in w for w in plan.warnings)


def test_job_estimate_sets_the_block_length() -> None:
    plan = build_plan(DAY, [job(1, "LS6 1AA", hours=3.5), job(2, "LS6 2AA", hours=0.5)], [])
    lengths = sorted(i.end - i.start for i in visits(plan))
    assert lengths == [timedelta(minutes=30), timedelta(hours=3, minutes=30)]


def test_no_overlaps_with_existing_events_and_existing_are_kept() -> None:
    existing = [
        event("Site meeting", at(9, 0), at(10, 10)),
        event("School run", at(15, 0), at(15, 40)),
        event("Optional webinar", at(10, 30), at(11, 30), show_as="free"),
    ]
    js = [job(n, f"LS6 {n}AA") for n in range(1, 6)]
    plan = build_plan(DAY, js, existing)
    assert_no_overlaps(plan, existing)
    assert [i.title for i in plan.items if i.kind == "existing"] == ["Site meeting", "Optional webinar", "School run"]
    # 10:10 rounds up to the quarter hour; the "free" webinar does not block the time
    assert visits(plan)[0].start == at(10, 45)
    assert all(i.start.minute % 15 == 0 for i in plan.items if i.kind != "existing")


def test_constraints_start_end_and_max_visits_are_respected() -> None:
    js = [job(n, f"LS6 {n}AA", hours=1) for n in range(1, 9)]
    c = Constraints(start="09:30", end="15:00", max_visits=2)
    plan = build_plan(DAY, js, [], constraints=c)
    mine = [i for i in plan.items if i.kind != "existing"]
    assert len(visits(plan)) == 2
    assert min(i.start for i in mine) >= at(9, 30)
    assert max(i.end for i in mine) <= at(15, 0)


def test_jobs_that_do_not_fit_are_warned_about() -> None:
    plan = build_plan(DAY, [job(1, "LS6 1AA", hours=4), job(2, "M1 1AE", hours=4)], [],
                      constraints=Constraints(start="08:00", end="14:00"))
    assert len(visits(plan)) == 1
    assert any("does not fit" in w for w in plan.warnings)


def test_lunch_sits_between_visits_in_the_lunch_window() -> None:
    plan = build_plan(DAY, [job(n, f"LS6 {n}AA") for n in range(1, 4)], [], constraints=Constraints(end="19:00"))
    lunch = [i for i in plan.items if i.kind == "lunch"]
    assert len(lunch) == 1
    assert at(12) <= lunch[0].start <= at(13, 30) and lunch[0].end - lunch[0].start == timedelta(minutes=30)
    # the second visit runs 11:00-13:00 rather than waiting for a 12:00 lunch
    assert visits(plan)[1].start == at(11)
    assert_no_overlaps(plan)


def test_a_long_visit_is_kept_even_if_it_means_no_lunch() -> None:
    plan = build_plan(DAY, [job(1, "LS6 1AA", hours=9)], [])
    assert len(visits(plan)) == 1
    assert not [i for i in plan.items if i.kind == "lunch"]
    assert any("No room for a lunch break" in w for w in plan.warnings)


def test_admin_for_a_vat_return_due_soon() -> None:
    dues = planner.vat_due(date(2026, 11, 3), VatSettings(stagger=1))
    assert dues == [Due(title="VAT return Jul–Sep 2026", due=date(2026, 11, 7))]
    assert planner.vat_due(date(2026, 10, 20), VatSettings(stagger=1)) == []  # 18 days out
    assert planner.vat_due(DAY, None) == []
    plan = build_plan(date(2026, 11, 3), [job(1, "LS6 1AA")], [], dues)
    admin = [i for i in plan.items if i.kind == "admin"]
    assert len(admin) == 1 and admin[0].title == "VAT return Jul–Sep 2026 (due 7 Nov)"
    assert admin[0].start >= visits(plan)[0].end
    assert_no_overlaps(plan)


def test_closed_jobs_no_postcode_and_already_booked_jobs_are_left_out() -> None:
    booked = event("[Accnomos] Job 2", at(16), at(17), body_preview=f"Accnomos job {2:012x}\nPlanned with Accnomos")
    js = [job(1, "LS6 1AA", status="closed"), job(2, "LS6 2AA"), job(3, "12 Elm Road, Leeds"), job(4, "LS7 1AA")]
    plan = build_plan(DAY, js, [booked])
    assert [i.job_id for i in visits(plan)] == [f"{4:012x}"]
    assert plan.skipped_already_planned == [f"{2:012x}"]
    assert any("Job 3" in w and "no postcode" in w for w in plan.warnings)


def test_out_of_office_all_day_plans_nothing() -> None:
    oof = event("Holiday", at(0), at(0, day=DAY + timedelta(days=1)), is_all_day=True, show_as="oof")
    plan = build_plan(DAY, [job(1, "LS6 1AA")], [oof])
    assert plan.items == [] and "out of office" in plan.warnings[0]


def test_weekend_and_past_days_are_warned() -> None:
    plan = build_plan(date(2026, 10, 24), [], [], today=TODAY)
    assert any("already passed" in w for w in plan.warnings) and any("Saturday" in w for w in plan.warnings)


def test_bad_constraints_are_refused() -> None:
    with pytest.raises(ValueError):
        Constraints(start="17:00", end="09:00")
    with pytest.raises(ValueError):
        Constraints(start="9am")
    with pytest.raises(ValueError):
        Constraints(max_visits=0)


def test_plan_hash_ignores_order_and_offset_spelling() -> None:
    plan = build_plan(DAY, [job(1, "LS6 1AA"), job(2, "LS7 1AA")], [])
    utc = [i.model_copy(update={"start": i.start.astimezone(planner.UTC), "end": i.end.astimezone(planner.UTC)}) for i in plan.items]
    assert planner.plan_hash(DAY, plan.items) == planner.plan_hash(DAY, list(reversed(utc)))
    assert planner.plan_hash(DAY, plan.items) != planner.plan_hash(DAY, plan.items[1:])


# --------------------------------------------------------------------------- #
# "Plan my Thursday"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("text", "want"), [
    ("Plan my Thursday", date(2026, 10, 29)),
    ("plan my day", TODAY),
    ("Can you plan today?", TODAY),
    ("plan tomorrow please", date(2026, 10, 28)),
    ("plan Tuesday", TODAY),  # 27 Oct 2026 is a Tuesday
    ("plan next Tuesday", date(2026, 11, 3)),
    ("plan 2026-11-05", date(2026, 11, 5)),
    ("How much VAT do I owe on Thursday?", None),
    ("plan for retirement", None),
    ("Plan my day on Thursday", date(2026, 10, 29)),
    ("schedule the day", TODAY),
    # Questions about the books that happen to say plan/schedule and a day stay questions.
    ("Should I schedule the supplier payment on Friday?", None),
    ("I plan to pay HMRC tomorrow, can I afford it?", None),
    ("What did I plan to spend today?", None),
])
def test_plan_intent(text: str, want: date | None) -> None:
    assert plan_intent(text, TODAY) == want


# --------------------------------------------------------------------------- #
# Rationale: words from the model, checked by code
# --------------------------------------------------------------------------- #


def _plan() -> planner.Plan:
    return build_plan(DAY, [job(1, "LS6 1AA"), job(2, "LS7 1AA")], [])


def test_code_rationale_quotes_the_plan() -> None:
    text = plan_ai.code_rationale(_plan())
    assert "LS6, then LS7" in text and "08:30" in text and plan_ai.check(text, _plan()) is None


def test_rationale_with_invented_time_or_miles_falls_back() -> None:
    assert plan_ai.check("- Start at 08:30 in LS6.", _plan()) is None
    assert "times" in plan_ai.check("- Start at 07:45.", _plan())  # type: ignore[operator]
    assert "figures" in plan_ai.check("- About 14.5 miles of driving.", _plan())  # type: ignore[operator]


async def test_rationale_uses_the_model_when_it_checks_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(messages, cfg, output, name):  # type: ignore[no-untyped-def]
        assert name == "plan_rationale" and "PLAN:" in messages[1]["content"]
        return json.dumps({"rationale_md": "- LS6 first at 08:30, then over to LS7."})

    monkeypatch.setattr(plan_ai.ask_ai, "_call_model", fake)
    cfg = plan_ai.AiConfig(mode="local", base_url="http://x", model="m")
    text, model, reason = await plan_ai.rationale(_plan(), cfg)
    assert (text, model, reason) == ("- LS6 first at 08:30, then over to LS7.", "m", None)


async def test_rationale_without_ai_is_written_by_code() -> None:
    text, model, reason = await plan_ai.rationale(_plan(), None)
    assert model is None and "No AI" in (reason or "") and "LS6" in text


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def calendar() -> FakeCalendarProvider:
    return FakeCalendarProvider([event("Dentist", at(9), at(10))])


@pytest.fixture
def client(fake: FakeStorageProvider, calendar: FakeCalendarProvider, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_plan import get_calendar

    async def books_override():
        yield Books(fake)

    async def calendar_override():
        yield calendar

    for k in ("AI_MODE", "META_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_MODE", "key")  # no key -> no AI -> the rationale is written by code
    app.dependency_overrides[get_books] = books_override
    app.dependency_overrides[get_calendar] = calendar_override
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _seed_jobs(fake: FakeStorageProvider, *js: Job) -> None:
    books = Books(fake)
    for j in js:
        await jobs.save_job(books, j)


async def test_plan_day_route_proposes_and_writes_nothing(client: TestClient, fake: FakeStorageProvider,
                                                          calendar: FakeCalendarProvider) -> None:
    await _seed_jobs(fake, job(1, "LS6 1AA"), job(2, "LS7 1AA"))
    before = dict(fake.files)
    r = client.post("/plan/day", json={"date": DAY.isoformat(), "constraints": {"max_visits": 2}}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = [i["kind"] for i in body["plan"]]
    assert kinds.count("visit") == 2 and kinds.count("existing") == 1
    assert datetime.fromisoformat(body["plan"][0]["start"]) == at(9)  # with its offset (GMT in late October)
    assert body["rationale_md"] and body["fallback_reason"] and len(body["plan_hash"]) == 64
    assert fake.files == before and calendar.created == []


def test_plan_day_route_rejects_bad_constraints(client: TestClient) -> None:
    r = client.post("/plan/day", json={"date": DAY.isoformat(), "constraints": {"start": "18:00", "end": "08:00"}}, headers=H)
    assert r.status_code == 422


async def test_apply_creates_only_new_items_once(client: TestClient, fake: FakeStorageProvider,
                                                 calendar: FakeCalendarProvider) -> None:
    await _seed_jobs(fake, job(1, "12 Elm Road, LS6 1AA"), job(2, "LS7 1AA"))
    plan = client.post("/plan/day", json={"date": DAY.isoformat()}, headers=H).json()["plan"]
    new = [i for i in plan if i["kind"] != "existing"]

    r = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": plan}, headers=H)
    assert r.status_code == 200, r.text
    res = r.json()
    assert len(calendar.created) == len(new) == len(res["event_ids"])
    assert all(e.subject.startswith("[Accnomos] ") for e in calendar.created)
    assert "Dentist" not in [e.subject.removeprefix("[Accnomos] ") for e in calendar.created]
    visit = next(e for e in calendar.created if e.location == "12 Elm Road, LS6 1AA")
    assert f"Accnomos job {1:012x}" in visit.body_preview
    assert res["mileage_proposals"] == []  # no vehicles in the books
    assert json.loads(fake.files[APPLIED])[res["plan_hash"]]["event_ids"] == res["event_ids"]
    audit = next(v for k, v in fake.files.items() if k.startswith("_System/audit/"))
    assert b'"plan_applied"' in audit

    again = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": plan}, headers=H).json()
    assert again["already_applied"] is True and again["event_ids"] == res["event_ids"]
    assert len(calendar.created) == len(new)  # nothing created twice

    # A fresh plan for the same day sees the jobs already booked and plans neither again.
    replan = client.post("/plan/day", json={"date": DAY.isoformat()}, headers=H).json()
    assert not [i for i in replan["plan"] if i["kind"] == "visit"]


async def test_apply_after_a_half_finished_attempt_reuses_events(client: TestClient, fake: FakeStorageProvider,
                                                                  calendar: FakeCalendarProvider) -> None:
    await _seed_jobs(fake, job(1, "LS6 1AA"))
    plan = client.post("/plan/day", json={"date": DAY.isoformat()}, headers=H).json()["plan"]
    first = PlanItem.model_validate(next(i for i in plan if i["kind"] == "travel"))
    await calendar.create_event(f"[Accnomos] {first.title}", first.start, first.end, "", "")
    r = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": plan}, headers=H).json()
    assert [c["reused"] for c in r["created"]].count(True) == 1
    assert len(calendar.created) == len([i for i in plan if i["kind"] != "existing"])


async def test_apply_refuses_when_the_calendar_changed(client: TestClient, fake: FakeStorageProvider,
                                                       calendar: FakeCalendarProvider) -> None:
    await _seed_jobs(fake, job(1, "LS6 1AA"))
    plan = client.post("/plan/day", json={"date": DAY.isoformat()}, headers=H).json()["plan"]
    visit = PlanItem.model_validate(next(i for i in plan if i["kind"] == "visit"))
    calendar.events.append(event("Emergency call-out", visit.start, visit.end))
    r = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": plan}, headers=H)
    assert r.status_code == 409 and "Emergency call-out" in r.json()["detail"]
    assert calendar.created == []


def test_apply_refuses_items_off_the_day_or_overlapping(client: TestClient, calendar: FakeCalendarProvider) -> None:
    other_day = {"kind": "visit", "start": at(10, day=DAY + timedelta(days=1)).isoformat(),
                 "end": at(11, day=DAY + timedelta(days=1)).isoformat(), "title": "x", "job_id": None, "location": None}
    r = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": [other_day]}, headers=H)
    assert r.status_code == 400
    a = {"kind": "visit", "start": at(10).isoformat(), "end": at(12).isoformat(), "title": "a"}
    b = {"kind": "admin", "start": at(11).isoformat(), "end": at(13).isoformat(), "title": "b"}
    r = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": [a, b]}, headers=H)
    assert r.status_code == 400 and "overlap" in r.json()["detail"]
    assert client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": [a]},
                       headers={"X-Graph-Token": "tok"}).status_code == 400  # X-User required
    assert calendar.created == []


async def test_apply_proposes_mileage_when_vehicles_exist(client: TestClient, fake: FakeStorageProvider) -> None:
    await _seed_jobs(fake, job(1, "LS6 1AA"), job(2, "LS7 1AA"))
    fake.files[VEHICLES] = json.dumps([{"id": "van1", "name": "Transit"}]).encode()
    plan = client.post("/plan/day", json={"date": DAY.isoformat()}, headers=H).json()["plan"]
    res = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": plan}, headers=H).json()
    mp = res["mileage_proposals"]
    assert [(m["from_district"], m["to_district"], m["vehicle_id"], m["miles"], m["status"]) for m in mp] == [
        (None, "LS6", "van1", None, "proposed"), ("LS6", "LS7", "van1", None, "proposed"),
    ]


async def test_job_estimate_survives_a_status_change(client: TestClient, fake: FakeStorageProvider) -> None:
    await _seed_jobs(fake, job(1, "LS6 1AA", hours=3))
    r = client.put(f"/jobs/{1:012x}", json={"name": "Job 1", "customer_id": None, "site_address": "LS6 1AA", "status": "closed"},
                   headers=H)
    assert r.status_code == 200 and r.json()["estimate_hours"] == 3


def test_summer_days_plan_in_british_summer_time() -> None:
    summer = date(2026, 7, 2)
    plan = build_plan(summer, [job(1, "LS6 1AA")], [event("Call", at(9, day=summer), at(10, day=summer))])
    v = visits(plan)[0]
    assert v.start.utcoffset() == timedelta(hours=1)
    assert planner.hhmm(v.start) == "10:30"  # 10:00 after the call, then 30 min travel


async def test_plan_day_route_can_be_limited_to_some_jobs(client: TestClient, fake: FakeStorageProvider) -> None:
    await _seed_jobs(fake, job(1, "LS6 1AA"), job(2, "LS7 1AA"), job(3, "M1 1AE"))
    body = {"date": DAY.isoformat(), "job_ids": [f"{1:012x}", f"{3:012x}"]}
    plan = client.post("/plan/day", json=body, headers=H).json()["plan"]
    assert [i["job_id"] for i in plan if i["kind"] == "visit"] == [f"{1:012x}", f"{3:012x}"]


def _lunch() -> list[dict[str, str]]:
    return [{"kind": "lunch", "start": at(12).isoformat(), "end": at(12, 30).isoformat(), "title": "Lunch"}]


def test_missing_calendar_scope_is_a_401_so_the_app_asks_again(client: TestClient, calendar: FakeCalendarProvider,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from accnomos_connectors import GraphError

    async def forbidden(*_a: object, **_k: object) -> list[CalendarEvent]:
        raise GraphError(403, "ErrorAccessDenied")

    monkeypatch.setattr(calendar, "list_events", forbidden)
    assert client.post("/plan/day", json={"date": DAY.isoformat()}, headers=H).status_code == 401
    assert client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": _lunch()}, headers=H).status_code == 401
    assert calendar.created == []


def test_apply_needs_the_user(client: TestClient, calendar: FakeCalendarProvider) -> None:
    r = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": _lunch()}, headers={"X-Graph-Token": "tok"})
    assert r.status_code == 400 and calendar.created == []


def test_apply_survives_a_damaged_applied_file(client: TestClient, fake: FakeStorageProvider,
                                               calendar: FakeCalendarProvider) -> None:
    fake.files[APPLIED] = b'["not", "a", "map"]'
    r = client.post("/plan/day/apply", json={"date": DAY.isoformat(), "plan": _lunch()}, headers=H)
    assert r.status_code == 200, r.text
    assert len(calendar.created) == 1 and r.json()["plan_hash"] in json.loads(fake.files[APPLIED])
