"""Overtime: pay multipliers on timesheet entries, a per-employee weekly rule, pay runs paying hourly staff from their
timesheets, and the "pay Andy double for last week's overtime" chat action (code finds the hours and prices them)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from accnomos_connectors import FakeStorageProvider
from app import actions, jobs
from app import approve as AP
from app import payroll_reports as REP
from app import payrun as PR
from app.actions import IntentModelOutput
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.books import Books
from app.jobs import Job, StaffMember, TimesheetEntry
from app.schemas import Clarification, ProposedAction

USER = "owner@example.co.uk"
TOKEN = "graph-token-1"
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
TODAY = date(2026, 10, 27)  # Tuesday; "last week" is Mon 19 - Sun 25 Oct


def entry(day: str, hours: float, mult: float = 1.0, job: str = "j1", staff: str = "s1") -> TimesheetEntry:
    return TimesheetEntry(staff_id=staff, job_id=job, date=date.fromisoformat(day), hours=hours, rate_multiplier=mult)


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await jobs.save_job(b, Job(id="00000000a001", name="Croydon job, 3 Park Lane"))
    await jobs.save_job(b, Job(id="00000000a002", name="Bathroom, 4 Oak Lane"))
    await jobs.save_staff(b, StaffMember(id="00000000b001", name="Andy Smith", role="Joiner", hourly_rate_pence=2000))
    await PR.save_employer(
        b,
        PR.EmployerSettings(paye_office="123", paye_reference="AB45678", accounts_office_ref="123PA00045678"),
        USER,
    )
    await PR.save_employee(
        b,
        PR.Employee(
            payroll_id="E010",
            forenames="Andy",
            surname="Smith",
            nino="AB123456C",
            dob=date(1985, 3, 3),
            gender="M",
            start_date=date(2020, 1, 1),
            staff_id="00000000b001",
            pay_type="hourly",
            hourly_rate_pence=2000,
            frequency="weekly",
            pension_exempt=True,
        ),  # fmt: skip
        USER,
    )
    for day, hours, job in (
        ("2026-10-20", 8, "00000000a001"),
        ("2026-10-21", 6, "00000000a001"),
        ("2026-10-22", 4, "00000000a002"),
    ):
        await jobs.add_entry(
            b, TimesheetEntry(staff_id="00000000b001", job_id=job, date=date.fromisoformat(day), hours=hours)
        )
    return b


# --------------------------------------------------------------------------- #
# Entries and the calculation
# --------------------------------------------------------------------------- #


def test_entry_multiplier_validation() -> None:
    assert entry("2026-10-20", 1).rate_multiplier == 1.0
    assert entry("2026-10-20", 1, 1.5).rate_multiplier == 1.5
    for bad in (0.5, 1.3, 3.5):
        with pytest.raises(ValueError):
            entry("2026-10-20", 1, bad)


def test_explicit_multipliers() -> None:
    items = PR.timesheet_items([entry("2026-10-20", 8), entry("2026-10-21", 3, 2.0)], 2000, None, 1.5)
    assert [(i.label, i.hours, i.pence) for i in items] == [
        ("Basic hours", 8.0, 16_000),
        ("Overtime at double time", 3.0, 12_000),
    ]


def test_weekly_rule_splits_hours_over_the_limit() -> None:
    # 40 hours a week at normal rate, then time and a half: 44.5 hours in one week -> 4.5 at 1.5x.
    week = [entry(f"2026-10-{d}", h) for d, h in (("19", 9), ("20", 9), ("21", 9), ("22", 9), ("23", 8.5))]
    items = PR.timesheet_items(week, 2000, 40, 1.5)
    assert [(i.hours, i.multiplier, i.pence) for i in items] == [(40.0, 1.0, 80_000), (4.5, 1.5, 13_500)]
    # The next week starts again at zero.
    two = [*week, entry("2026-10-26", 10)]
    assert PR.timesheet_items(two, 2000, 40, 1.5)[0].hours == 50.0


def test_entries_already_premium_count_towards_the_week_but_keep_their_rate() -> None:
    premium = [entry(f"2026-10-{d}", 9.5, 2.0) for d in ("19", "20", "21", "22")]  # 38 hours at double time
    items = PR.timesheet_items([*premium, entry("2026-10-23", 4)], 1000, 40, 1.5)
    assert [(i.hours, i.multiplier) for i in items] == [(2.0, 1.0), (2.0, 1.5), (38.0, 2.0)]


async def test_pay_run_pays_hourly_staff_from_timesheets_with_overtime(books: Books) -> None:
    sheet = await jobs.load_entries(books)
    await jobs.set_rate_multiplier(books, [sheet[1].id], 2.0)  # the 6 hours on 21 Oct at double time
    run = await PR.prepare(books, "weekly", date(2026, 10, 23), USER)  # tax week 29: 19-25 Oct
    (ln,) = run.lines
    assert [(i.label, i.hours, i.pence) for i in ln.pay_items] == [
        ("Basic hours", 12.0, 24_000),
        ("Overtime at double time", 6.0, 24_000),
    ]
    assert (ln.basic_pence, ln.overtime_pence, ln.gross_pence) == (24_000, 24_000, 48_000)
    assert PR.HOLIDAY_PAY_NOTE in ln.warnings
    from app.routes_payrun import payslip_pdf

    assert payslip_pdf(run, ln, None, "Acme")[:5] == b"%PDF-"
    run, p = await PR.propose(books, run.id, USER)
    await AP.approve(books, p.id, USER)
    p11 = REP.p11((await PR.load_employees(books))[0], await PR.list_runs(books))
    assert p11.rows[0]["overtime"] == 24_000
    assert REP.payroll_summary(await PR.get_run(books, run.id)).rows[0]["overtime"] == 24_000


async def test_employee_weekly_rule_in_a_pay_run(books: Books) -> None:
    emp = (await PR.load_employees(books))[0]
    await PR.save_employee(books, emp.model_copy(update={"overtime_after_hours_week": 10.0}), USER)
    (ln,) = (await PR.prepare(books, "weekly", date(2026, 10, 23), USER)).lines
    assert [(i.hours, i.multiplier) for i in ln.pay_items] == [(10.0, 1.0), (8.0, 1.5)]


async def test_typed_hours_override_the_timesheet(books: Books) -> None:
    run = await PR.prepare(books, "weekly", date(2026, 10, 23), USER)
    eid = run.lines[0].employee_id
    run = await PR.update(books, run.id, [PR.LineInputs(employee_id=eid, hours=10)], USER)
    assert run.lines[0].gross_pence == 20_000 and run.lines[0].overtime_pence == 0


# --------------------------------------------------------------------------- #
# The chat action
# --------------------------------------------------------------------------- #


def out(**kw: Any) -> IntentModelOutput:
    fields = {f: None for f in IntentModelOutput.model_fields if f != "kind"}
    return IntentModelOutput(kind="pay_overtime", **{**fields, **kw})  # type: ignore[arg-type]


def test_multiplier_and_week_words() -> None:
    said = actions.numbers_said("pay him 1.5 times")
    assert actions.multiplier_in("double", set()) == 2
    assert actions.multiplier_in("time and a half", set()) == Decimal("1.5")
    assert actions.multiplier_in("1.5", said) == Decimal("1.5")
    assert actions.multiplier_in("1.75", said) is None  # not a figure the user said
    assert actions.multiplier_in("a lot", said) is None
    assert actions.parse_week("last week", TODAY) == date(2026, 10, 19)
    assert actions.parse_week("this week", TODAY) == date(2026, 10, 26)
    assert actions.parse_week("Wednesday", TODAY) == date(2026, 10, 19)  # Wed 21 Oct
    assert actions.parse_week(None, TODAY) is None


def test_parse_overtime_intent_asks_for_what_is_missing() -> None:
    q = "Pay Andy double for last week's overtime on the Croydon job"
    got = actions.parse_intent(
        out(staff_ref="Andy", job_ref="Croydon job", multiplier_text="double", date_text="last week"), q, TODAY
    )
    assert isinstance(got, actions.PayOvertimeIntent)
    assert (got.multiplier, got.week_start, got.job_ref) == (Decimal(2), date(2026, 10, 19), "Croydon job")
    no_rate = actions.parse_intent(out(staff_ref="Andy", multiplier_text="more", date_text="last week"), q, TODAY)
    assert isinstance(no_rate, Clarification) and no_rate.field == "amount"
    no_week = actions.parse_intent(out(staff_ref="Andy", multiplier_text="double"), q, TODAY)
    assert isinstance(no_week, Clarification) and no_week.field == "date"


async def test_propose_and_approve_pay_double(books: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    reply = out(staff_ref="Andy", job_ref="Croydon job", multiplier_text="double", date_text="last week")

    async def fake(messages: list[dict], cfg: AiConfig, schema: dict, name: str) -> str:
        assert "multiplier_text" in schema["properties"]
        return reply.model_dump_json()

    monkeypatch.setattr(ask_ai, "call_json_model", fake)
    action = await actions.propose(
        "Pay Andy double for last week's overtime on the Croydon job", books, CFG, TOKEN, TODAY
    )
    assert isinstance(action, ProposedAction) and action.kind == "pay_overtime"
    p = action.preview
    # Code found the 14 hours on the Croydon job (not the 4 on the bathroom) and priced them: 14 x £20 x 2.
    assert (p["hours"], p["pay_pence"], p["extra_pence"], len(p["entries"])) == ("14", 56_000, 28_000, 2)
    assert "£560.00" in action.summary_md and "check with your adviser" in " ".join(p["warnings"]).lower()
    assert all(e.rate_multiplier == 1.0 for e in await jobs.load_entries(books))  # nothing changes before Approve
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN)
    res = await actions.approve(action, ctx)
    assert res.status == "done"
    mults = {e.date.isoformat(): e.rate_multiplier for e in await jobs.load_entries(books)}
    assert mults == {"2026-10-20": 2.0, "2026-10-21": 2.0, "2026-10-22": 1.0}
    # The next pay run pays it.
    (ln,) = (await PR.prepare(books, "weekly", date(2026, 10, 23), USER)).lines
    assert ln.overtime_pence == 56_000 and ln.basic_pence == 8_000


async def test_overtime_refused_when_hours_changed_or_already_paid(books: Books) -> None:
    intent = actions.PayOvertimeIntent(
        staff_ref="Andy", job_ref="Croydon", multiplier=Decimal(2), week_start=date(2026, 10, 19)
    )
    draft = await actions.resolve_overtime(books, intent, TODAY)
    assert isinstance(draft, actions.Draft)
    action = actions.new_action(draft, TOKEN)
    first = (await jobs.load_entries(books))[0]
    await jobs.update_entry(books, first.id, {"hours": 9})
    with pytest.raises(actions.ActionError, match="changed"):
        await actions.approve(action, actions.Context(books=books, user=USER, graph_token=TOKEN))
    run = await PR.prepare(books, "weekly", date(2026, 10, 23), USER)
    run, p = await PR.propose(books, run.id, USER)
    await AP.approve(books, p.id, USER)
    again = await actions.resolve_overtime(books, intent, TODAY)
    assert isinstance(again, Clarification) and "approved pay run" in again.question_md


async def test_overtime_needs_a_linked_hourly_employee(books: Books) -> None:
    await jobs.save_staff(books, StaffMember(id="00000000b009", name="Bea Jones", hourly_rate_pence=1500))
    intent = actions.PayOvertimeIntent(staff_ref="Bea Jones", multiplier=Decimal("1.5"), week_start=date(2026, 10, 19))
    got = await actions.resolve_overtime(books, intent, TODAY)
    assert isinstance(got, Clarification) and "Payroll page" in got.question_md
