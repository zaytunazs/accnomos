"""Chat/voice actions: intent parsing with a stubbed model, name resolution (and asking when unsure), pence maths,
signatures, approve-once and reject, and the /books/ask + /actions routes, over FakeStorageProvider."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from accnomos_connectors import FakeStorageProvider
from fastapi.testclient import TestClient

from app import actions, jobs
from app.actions import IntentModelOutput
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.books import Books
from app.contacts import CONTACTS, Contact
from app.jobs import Job, StaffMember
from app.schemas import Clarification, ProposedAction

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
TODAY = date(2026, 10, 27)  # a Tuesday
TOKEN = "graph-token-1"
USER = "sam@example.co.uk"
H = {"X-Graph-Token": TOKEN, "X-User": USER, "X-AI-Mode": "local", "X-AI-Model": "stub-model"}


def contact(name: str, email: str | None = None, kind: str = "customer", aliases: list[str] | None = None) -> dict[str, Any]:
    from app.autopilot import supplier_key

    key = supplier_key(name)
    return Contact(id=key.replace("-", "")[:16].ljust(16, "0"), kind=kind, name=name, normalised_key=key,  # type: ignore[arg-type]
                   email=email, aliases=aliases or []).model_dump(mode="json")


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.write_json(CONTACTS, [
        contact("JM Trading Ltd", "accounts@jmtrading.example"),
        contact("Hartley Builders", "pay@hartley.example"),
        contact("Moss & Co", None),
        contact("Hartley Bros", "bros@hartley.example"),
        contact("Screwfix", kind="supplier"),
    ])
    await b.write_json("_System/Invoicing/profile.json", {"name": "Sam Electrical", "vrn": "GB123456789", "terms_days": 14})
    await jobs.save_job(b, Job(id="00000000a001", name="Kitchen refit, 12 Elm Road"))
    await jobs.save_job(b, Job(id="00000000a002", name="Bathroom, 4 Oak Lane"))
    await jobs.save_staff(b, StaffMember(id="00000000b001", name="Sam Taylor", role="Electrician", hourly_rate_pence=2000))
    await jobs.save_staff(b, StaffMember(id="00000000b002", name="Alex Green", role="Apprentice", hourly_rate_pence=1200))
    return b


def out(kind: str, **kw: Any) -> IntentModelOutput:
    fields = {f: None for f in IntentModelOutput.model_fields if f != "kind"}
    return IntentModelOutput(kind=kind, **{**fields, **kw})  # type: ignore[arg-type]


def stub_model(monkeypatch: pytest.MonkeyPatch, reply: IntentModelOutput | str, seen: list | None = None) -> None:
    async def fake(messages: list[dict], cfg: AiConfig, output: Any = None, name: str = "") -> str:
        if seen is not None:
            seen.append((messages, output, name))
        return reply if isinstance(reply, str) else reply.model_dump_json()

    monkeypatch.setattr(ask_ai, "_call_model", fake)


def with_invoicing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend app/invoicing.py is on this build, for proposals (which only read files)."""
    monkeypatch.setattr(actions, "invoicing", lambda: SimpleNamespace())


# --------------------------------------------------------------------------- #
# Intent parsing (the model's quotes -> typed intent)
# --------------------------------------------------------------------------- #


def test_invoice_intent_from_the_users_words():
    q = "send a £100 invoice to JM Trading for this month's work"
    got = actions.parse_intent(out("create_invoice", customer_ref="JM Trading", description="this month's work",
                                   amount_text="£100", send=True), q, TODAY)
    assert isinstance(got, actions.CreateInvoiceIntent)
    assert got.amount_pence == 10_000 and got.send and not got.amount_includes_vat
    assert got.description == "Work for October 2026"  # words only: no dates or hours looked up


def test_a_figure_the_user_did_not_say_is_refused():
    q = "send an invoice to JM Trading for this month's work"
    got = actions.parse_intent(out("create_invoice", customer_ref="JM Trading", amount_text="£1,000"), q, TODAY)
    assert isinstance(got, Clarification) and got.field == "amount"


@pytest.mark.parametrize(("said", "pence"), [("£1,250.50", 125_050), ("1.2k", 120_000), ("£99.999", 10_000)])
def test_amounts_are_parsed_by_code(said: str, pence: int):
    got = actions.parse_intent(out("create_invoice", customer_ref="JM", amount_text=said), f"invoice JM {said}", TODAY)
    assert isinstance(got, actions.CreateInvoiceIntent) and got.amount_pence == pence


def test_timesheet_and_mileage_intents():
    t = actions.parse_intent(out("log_timesheet", staff_ref="Sam", job_ref="Elm Road", hours_text="7.5", date_text="yesterday"),
                             "log 7.5 hours for Sam on Elm Road yesterday", TODAY)
    assert isinstance(t, actions.LogTimesheetIntent) and t.hours == Decimal("7.5") and t.date == date(2026, 10, 26)
    m = actions.parse_intent(out("log_mileage", miles_text="42", from_place="Leeds", to_place="York", date_text="Monday"),
                             "log 42 miles Leeds to York on Monday", TODAY)
    assert isinstance(m, actions.LogMileageIntent) and m.miles == 42 and m.date == date(2026, 10, 26)
    missing = actions.parse_intent(out("log_timesheet", staff_ref="Sam", hours_text="3"), "log 3 hours for Sam", TODAY)
    assert isinstance(missing, Clarification) and missing.field == "job"


@pytest.mark.parametrize(("text", "want"), [
    ("today", date(2026, 10, 27)), ("Tuesday", date(2026, 10, 27)), ("last Friday", date(2026, 10, 23)),
    ("3 Oct", date(2026, 10, 3)), ("October 3rd", date(2026, 10, 3)), ("3/10", date(2026, 10, 3)),
    ("25 December", date(2025, 12, 25)), ("2026-09-01", date(2026, 9, 1)), ("someday", None), ("31/02", None),
])
def test_days_are_read_by_code(text: str, want: date | None):
    assert actions.parse_day(text, TODAY) == want


async def test_propose_with_stubbed_model(books: Books, monkeypatch: pytest.MonkeyPatch):
    seen: list = []
    with_invoicing(monkeypatch)
    stub_model(monkeypatch, out("create_invoice", customer_ref="JM Trading", description="this month's work",
                                amount_text="£100", send=True), seen)
    got = await actions.propose("send a £100 invoice to JM Trading for this month's work", books, CFG, TOKEN, TODAY)
    assert isinstance(got, ProposedAction) and got.kind == "create_invoice"
    messages, schema_model, name = seen[0]
    assert schema_model is IntentModelOutput and name == "action_intent"
    assert "JM Trading Ltd" not in json.dumps(messages)  # the contact list never goes to the model
    p = got.preview
    assert p["customer"]["name"] == "JM Trading Ltd" and p["send_to"] == "accounts@jmtrading.example"
    assert (p["net_pence"], p["vat_pence"], p["total_pence"]) == (10_000, 2_000, 12_000)
    assert p["due_date"] == "2026-11-10"  # the profile's 14 days
    assert "£120.00" in got.summary_md and got.signature


async def test_questions_skip_the_intent_call(books: Books, monkeypatch: pytest.MonkeyPatch):
    seen: list = []
    stub_model(monkeypatch, out("create_invoice", customer_ref="JM", amount_text="1"), seen)
    assert await actions.propose("How much did I invoice JM Trading last month?", books, CFG, TOKEN, TODAY) is None
    assert seen == []


@pytest.mark.parametrize("reply", ['{"kind": "none"', out("none").model_dump_json()])
async def test_none_or_garbage_falls_back_to_an_answer(books: Books, monkeypatch: pytest.MonkeyPatch, reply: str):
    stub_model(monkeypatch, reply)
    assert await actions.propose("send me a summary", books, CFG, TOKEN, TODAY) is None


async def test_missing_module_says_so(books: Books, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(actions, "mileage", lambda: None)
    stub_model(monkeypatch, out("log_mileage", miles_text="12", from_place="A", to_place="B"))
    got = await actions.propose("log 12 miles from A to B", books, CFG, TOKEN, TODAY)
    assert isinstance(got, actions.NotAvailable) and "mileage" in got.message


# --------------------------------------------------------------------------- #
# Finding things by name
# --------------------------------------------------------------------------- #


async def test_customer_resolution(books: Books):
    opts = await actions.customer_options(books)
    assert "Screwfix" not in [o.name for o in opts]  # suppliers are never invoiced
    hit = actions.pick("J.M. Trading", opts, "create_invoice", "customer", "customer")
    assert isinstance(hit, actions.Picked) and hit.option.name == "JM Trading Ltd"
    ambiguous = actions.pick("Hartley", opts, "create_invoice", "customer", "customer")
    assert isinstance(ambiguous, Clarification) and set(ambiguous.candidates) == {"Hartley Builders", "Hartley Bros"}
    unknown = actions.pick("Moss and Sons", opts, "create_invoice", "customer", "customer")
    assert isinstance(unknown, Clarification) and "Moss & Co" in unknown.candidates


async def test_aliases_count(books: Books):
    opts = [actions.Option("1", "Johnson Mechanical Trading", ("jm-trading",))]
    assert isinstance(actions.pick("JM Trading", opts, "create_invoice", "customer", "customer"), actions.Picked)


async def test_timesheet_resolution_and_quarter_hours(books: Books):
    intent = actions.LogTimesheetIntent(staff_ref="sam taylor", job_ref="Kitchen refit 12 Elm Rd", hours=Decimal("7.4"))
    got = await actions.resolve_timesheet(books, intent, TODAY)
    assert isinstance(got, actions.Draft)
    assert got.preview["staff_id"] == "00000000b001" and got.preview["job_id"] == "00000000a001"
    assert got.preview["hours"] == "7.5" and got.preview["warnings"]
    bad = await actions.resolve_timesheet(books, intent.model_copy(update={"job_ref": "Garage"}), TODAY)
    assert isinstance(bad, Clarification) and bad.field == "job"


async def test_invoice_without_email_is_a_draft(books: Books):
    intent = actions.CreateInvoiceIntent(customer_ref="Moss and Co", description="Work", amount_pence=5_000, send=True)
    got = await actions.resolve_invoice(books, intent, TODAY)
    assert isinstance(got, actions.Draft)
    assert got.preview["send"] is False and "no email" in got.preview["warnings"][0]
    assert "draft" in got.confirm_text


async def test_vehicle_resolution(books: Books):
    intent = actions.LogMileageIntent(miles=Decimal("12.34"), from_place="Leeds", to_place="York")
    none = await actions.resolve_mileage(books, intent, TODAY)
    assert isinstance(none, Clarification) and none.field == "vehicle"
    await books.write_json(actions.VEHICLES, [{"id": "v1", "name": "Transit van", "registration": "AB12 CDE", "active": True}])
    one = await actions.resolve_mileage(books, intent, TODAY)
    assert isinstance(one, actions.Draft) and one.preview["vehicle_id"] == "v1" and one.preview["miles"] == "12.3"


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def test_vat_per_line_half_up_and_summary_by_code():
    got = actions.price_lines([
        ("Labour", Decimal("2.5"), 4_500, "S"), ("Cable", Decimal(3), 333, "S"), ("Book", Decimal(1), 1_000, "Z"),
        ("Fuel", Decimal(1), 1_001, "R"),
    ])
    assert [ln["net_pence"] for ln in got["lines"]] == [11_250, 999, 1_000, 1_001]
    assert [ln["vat_pence"] for ln in got["lines"]] == [2_250, 200, 0, 50]  # 199.8 -> 200; 50.05 -> 50
    assert [(r["vat_code"], r["net_pence"], r["vat_pence"]) for r in got["vat_summary"]] == [
        ("S", 12_249, 2_450), ("R", 1_001, 50), ("Z", 1_000, 0),
    ]
    assert (got["net_pence"], got["vat_pence"], got["total_pence"]) == (14_250, 2_500, 16_750)


@pytest.mark.parametrize(("gross", "code", "net"), [(12_000, "S", 10_000), (10_000, "S", 8_333), (10_500, "R", 10_000), (999, "Z", 999)])
def test_net_from_gross_adds_back_exactly(gross: int, code: str, net: int):
    assert actions.net_from_gross(gross, code) == net
    assert net + actions.line_vat(net, code) == gross


async def test_vat_inclusive_amount_and_unregistered_business(books: Books):
    intent = actions.CreateInvoiceIntent(customer_ref="JM Trading", description="Work", amount_pence=10_000, amount_includes_vat=True)
    got = await actions.resolve_invoice(books, intent, TODAY)
    assert isinstance(got, actions.Draft) and got.preview["total_pence"] == 10_000 and got.preview["vat_pence"] == 1_667
    await books.write_json("_System/Invoicing/profile.json", {"name": "Sam Electrical"})
    plain = await actions.resolve_invoice(books, intent.model_copy(update={"amount_includes_vat": False}), TODAY)
    assert isinstance(plain, actions.Draft) and plain.preview["vat_pence"] == 0 and plain.preview["lines"][0]["vat_code"] == "O"
    assert "no VAT registration" in plain.preview["warnings"][0]


# --------------------------------------------------------------------------- #
# Signing, approve once, reject
# --------------------------------------------------------------------------- #


async def timesheet_action(books: Books, token: str = TOKEN) -> ProposedAction:
    intent = actions.LogTimesheetIntent(staff_ref="Alex", job_ref="Bathroom Oak Lane", hours=Decimal(3), date=date(2026, 10, 26))
    draft = await actions.resolve_timesheet(books, intent, TODAY)
    assert isinstance(draft, actions.Draft)
    return actions.new_action(draft, token)


async def test_tampered_or_foreign_or_expired_actions_are_refused(books: Books):
    action = await timesheet_action(books)
    actions.verify(action, TOKEN)
    more = action.model_copy(update={"preview": {**action.preview, "hours": "30"}})
    with pytest.raises(actions.ActionError) as exc:
        actions.verify(more, TOKEN)
    assert exc.value.status == 403
    with pytest.raises(actions.ActionError):
        actions.verify(action, "someone-elses-token")
    with pytest.raises(actions.ActionError) as exc:
        actions.verify(action, TOKEN, at=datetime.now(UTC) + timedelta(minutes=16))
    assert exc.value.status == 410
    later = action.model_copy(update={"expires_at": action.expires_at + timedelta(days=1)})
    with pytest.raises(actions.ActionError):
        actions.verify(later, TOKEN)


async def test_round_trip_through_json_keeps_the_signature(books: Books):
    action = await timesheet_action(books)
    actions.verify(ProposedAction.model_validate_json(action.model_dump_json()), TOKEN)


async def test_approve_executes_once(books: Books):
    action = await timesheet_action(books)
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN)
    first = await actions.approve(action, ctx)
    again = await actions.approve(action, ctx)
    assert first.status == "done" and again.status == "already_done" and again.result == first.result
    entries = await jobs.load_entries(books)
    assert len(entries) == 1 and entries[0].hours == 3 and entries[0].id == action.id[:12]
    log = (await books.storage.read(f"_System/audit/actions/{action.created_at:%Y-%m}.jsonl")).decode().splitlines()
    assert [json.loads(ln)["event"] for ln in log] == ["approving", "executed"]


async def test_a_failed_approval_can_be_retried(books: Books, monkeypatch: pytest.MonkeyPatch):
    action = await timesheet_action(books)
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN)
    calls: list[str] = []

    async def flaky(a: ProposedAction, c: actions.Context) -> tuple[str, dict]:
        calls.append(a.id)
        if len(calls) == 1:
            raise jobs.JobsConflict("Job is closed")
        return "ok", {}

    monkeypatch.setitem(actions.EXECUTORS, "log_timesheet", flaky)
    with pytest.raises(jobs.JobsConflict):
        await actions.approve(action, ctx)
    assert (await actions.approve(action, ctx)).status == "done"
    assert (await actions.approve(action, ctx)).status == "already_done"
    assert len(calls) == 2


async def test_reject_audits_and_blocks_approval(books: Books):
    action = await timesheet_action(books)
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN)
    await actions.reject(action, ctx, "wrong job")
    with pytest.raises(actions.ActionError) as exc:
        await actions.approve(action, ctx)
    assert exc.value.status == 409
    assert await jobs.load_entries(books) == []
    row = json.loads((await books.storage.read(f"_System/audit/actions/{action.created_at:%Y-%m}.jsonl")).decode().splitlines()[0])
    assert row["event"] == "rejected" and row["reason"] == "wrong job" and row["user"] == USER


async def test_approved_cannot_be_rejected(books: Books):
    action = await timesheet_action(books)
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN)
    await actions.approve(action, ctx)
    with pytest.raises(actions.ActionError):
        await actions.reject(action, ctx)


async def test_invoice_approval_uses_the_invoicing_module(books: Books):
    """Runs only on a build with app/invoicing.py (claude/invoicing)."""
    pytest.importorskip("app.invoicing")
    from accnomos_connectors import FakeMailSender  # type: ignore[attr-defined]

    intent = actions.CreateInvoiceIntent(customer_ref="JM Trading", description="Work for October 2026", amount_pence=10_000, send=True)
    draft = await actions.resolve_invoice(books, intent, TODAY)
    assert isinstance(draft, actions.Draft)
    action = actions.new_action(draft, TOKEN)
    await books.write_json("_System/Invoicing/profile.json", {"name": "Sam Electrical", "address": "1 High St", "vrn": "GB123456789"})
    sender = FakeMailSender()
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN, mail_sender=lambda: sender)
    done = await actions.approve(action, ctx)
    again = await actions.approve(action, ctx)
    assert done.result["status"] == "sent" and done.result["total_pence"] == 12_000
    assert again.status == "already_done" and len(sender.sent) == 1


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def test_ask_returns_a_card_and_approve_executes(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    stub_model(monkeypatch, out("log_timesheet", staff_ref="Alex", job_ref="Oak Lane", hours_text="4"))
    app.dependency_overrides[get_books] = override
    try:
        client = TestClient(app)
        r = client.post("/books/ask", json={"question": "log 4 hours for Alex on Oak Lane"}, headers=H)
        assert r.status_code == 200, r.text
        card = r.json()["proposed_action"]
        assert card["kind"] == "log_timesheet" and card["preview"]["hours"] == "4"
        assert r.json()["answer_md"] == card["summary_md"]
        other = client.post("/actions/approve", json={"action": card}, headers={**H, "X-Graph-Token": "another"})
        changed = client.post("/actions/approve", json={"action": {**card, "preview": {**card["preview"], "hours": "40"}}}, headers=H)
        ok = client.post("/actions/approve", json={"action": card}, headers=H)
        twice = client.post("/actions/approve", json={"action": card}, headers=H)
        late = client.post("/actions/reject", json={"action": card}, headers=H)
    finally:
        app.dependency_overrides.clear()
    assert other.status_code == 403 and changed.status_code == 403
    assert ok.status_code == 200 and ok.json()["status"] == "done", ok.text
    assert twice.json()["status"] == "already_done"
    assert late.status_code == 409


def test_ask_asks_when_unsure(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    with_invoicing(monkeypatch)
    stub_model(monkeypatch, out("create_invoice", customer_ref="Hartley", amount_text="£250"))
    app.dependency_overrides[get_books] = override
    try:
        r = TestClient(app).post("/books/ask", json={"question": "invoice Hartley £250"}, headers=H)
    finally:
        app.dependency_overrides.clear()
    body = r.json()
    assert body["proposed_action"] is None and body["clarification"]["field"] == "customer"
    assert set(body["clarification"]["candidates"]) == {"Hartley Builders", "Hartley Bros"}


async def test_reject_route(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    card = (await timesheet_action(books)).model_dump(mode="json")
    app.dependency_overrides[get_books] = override
    try:
        client = TestClient(app)
        missing = client.post("/actions/reject", json={"action": {}}, headers=H)
        no = client.post("/actions/reject", json={"action": card, "reason": "not now"}, headers=H)
        after = client.post("/actions/approve", json={"action": card}, headers=H)
    finally:
        app.dependency_overrides.clear()
    assert missing.status_code == 422
    assert no.status_code == 200 and no.json() == {"action_id": card["id"], "status": "rejected"}
    assert after.status_code == 409 and await jobs.load_entries(books) == []
