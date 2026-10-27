"""GET /audit against FakeStorageProvider: one working day in the books, read back as a timeline. No model."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import audit_view
from app.actions import ACTIONS_AUDIT
from app.books import AUDIT, AUTOPILOT_AUDIT, Books
from app.schemas import ExtractedDoc, Proposal

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok"}
DAY = "2026-10-27"


def _proposal(pid: str, supplier: str, gross: float) -> Proposal:
    doc = ExtractedDoc(
        doc_type="purchase_invoice",
        supplier_name=supplier,
        supplier_vat_number=None,
        customer_name=None,
        invoice_number=None,
        date="2026-10-01",
        currency="GBP",
        lines=[],
        net_total=gross / 1.2,
        vat_total=gross - gross / 1.2,
        gross_total=gross,
        payment_method=None,
        card_last4=None,
        category_guess="Materials",
        confidence=0.9,
    )
    return Proposal(
        id=pid,
        doc_sha256="cd" * 32,
        extracted=doc,
        checks=[],
        status="posted",
        reasons=[],
        suggested_filename="x.pdf",
        journal_draft=[],
        model="stub",
        elapsed_s=1.0,
    )


def _jsonl(*rows: dict) -> bytes:
    return "".join(json.dumps(r) + "\n" for r in rows).encode()


def _line(hhmm: str, actor: str, action: str, /, day: str = DAY, **refs) -> dict:
    return {"ts": f"{day}T{hhmm}:00+00:00", "actor": actor, "action": action, "refs": refs}


SCREWFIX, HOWDENS = "a" * 16, "b" * 16


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    """The shapes each writer uses (approve.py, inbox.py, triage.py, layout.py, actions.py), on one day."""
    b = Books(fake)
    await b.save_proposal(_proposal(SCREWFIX, "Screwfix", 12.0))
    await b.save_proposal(_proposal(HOWDENS, "Howdens Joinery Ltd", 240.0))
    fake.files[f"{AUDIT}/2026-10.jsonl"] = (
        _jsonl(
            _line("07:00", "agent:folder-layout", "folders_renamed", moved=[{"old": "Inbox", "new": "00 Inbox"}]),
            _line("07:30", "agent:triage", "mail_triaged", scanned=40, threads=6, skipped=2),
            _line("08:00", "agent:extractor", "proposed", proposal=HOWDENS, status="proposed", path="00 Inbox/h.pdf"),
            _line("08:01", "agent:autopilot", "approved", proposal=HOWDENS, event="e" * 32, event_path="x.json"),
            _line("09:00", f"user:{USER}", "approved", proposal=SCREWFIX, event="f" * 32, edits=["category"]),
            _line("09:05", f"user:{USER}", "invoice_sent", invoice="INV-0007", to="pat@example.com"),
            _line(
                "10:00",
                f"user:{USER}",
                "undone",
                event="e" * 32,
                reversal="r" * 32,
                proposal=HOWDENS,
                originally_approved_by="autopilot",
            ),
            _line("10:30", f"user:{USER}", "timesheet_added", entry="t1", action="act1"),
            _line("11:00", "agent:planner", "boiler_serviced"),  # a kind the table does not know yet
            _line("12:00", f"user:{USER}", "approved", day="2026-10-20", proposal=SCREWFIX),  # outside a one-day range
        )
        + b'not json\n{"ts": "yesterday"}\n'
    )
    fake.files[f"{AUDIT}/2026-09.jsonl"] = _jsonl(_line("16:00", f"user:{USER}", "todo_added", day="2026-09-30"))
    # Autopilot's own log repeats the 08:01 posting; the timeline must not show it twice.
    fake.files[f"{AUTOPILOT_AUDIT}/2026-10.jsonl"] = _jsonl(
        _line("08:01", "agent:autopilot", "approved", proposal=HOWDENS, event="e" * 32)
    )
    fake.files[f"{ACTIONS_AUDIT}/2026-10.jsonl"] = _jsonl(
        {"ts": f"{DAY}T10:29:00+00:00", "action_id": "act1", "kind": "log_time", "event": "approving", "user": USER},
        {
            "ts": f"{DAY}T10:30:00+00:00",
            "action_id": "act1",
            "kind": "log_time",
            "event": "executed",
            "user": USER,
            "result_md": "Logged **3 hours** on *Kitchen refit*",
        },
        {
            "ts": f"{DAY}T10:40:00+00:00",
            "action_id": "act2",
            "kind": "send_invoice",
            "event": "rejected",
            "user": USER,
            "reason": "wrong customer",
            "summary_md": "Email **INV-0008** to Pat",
        },
    )
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def over() -> Books:
        return books

    app.dependency_overrides[get_books] = over
    yield TestClient(app)
    app.dependency_overrides.clear()


def _get(client: TestClient, **q) -> dict:
    r = client.get("/audit", params={"from": DAY, "to": DAY, **q}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_one_day_newest_first_with_actors_summaries_and_refs(client: TestClient) -> None:
    page = _get(client)
    rows = [(e["ts"][11:16], e["actor_label"], e["actor_kind"], e["event"], e["summary"]) for e in page["entries"]]
    assert rows == [
        ("11:00", "Planner", "agent", "boiler_serviced", "Boiler serviced"),
        ("10:40", "You", "user", "action_rejected", "Said no in Ask: Email INV-0008 to Pat (wrong customer)"),
        ("10:30", "You", "user", "timesheet_added", "Logged time"),
        ("10:30", "You", "user", "action_done", "Approved from Ask: Logged 3 hours on Kitchen refit"),
        (
            "10:00",
            "You",
            "user",
            "undone",
            "Undid the entry for Howdens Joinery Ltd £240.00 that Autopilot posted; it is back in Review",
        ),
        ("09:05", "You", "user", "invoice_sent", "Emailed invoice INV-0007 to pat@example.com"),
        ("09:00", "You", "user", "approved", "Posted Screwfix £12.00 to the ledger"),
        ("08:01", "Autopilot", "agent", "approved", "Posted Howdens Joinery Ltd £240.00 to the ledger"),
        ("08:00", "Reader", "agent", "proposed", "Read Howdens Joinery Ltd £240.00 and proposed an entry"),
        ("07:30", "Triage", "agent", "mail_triaged", "Sorted the inbox: 6 threads from 40 messages"),
        ("07:00", "Folder tidy", "agent", "folders_renamed", "Renamed old folders: Inbox → 00 Inbox"),
    ]
    assert page["truncated"] is False
    by = {(e["ts"][11:16], e["event"]): e for e in page["entries"]}
    assert by[("09:00", "approved")]["actor"] == f"user:{USER}"
    assert by[("09:00", "approved")]["refs"] == {
        "proposal": SCREWFIX,
        "event": "f" * 32,
        "invoice": None,
        "action": None,
        "file": None,
    }
    assert by[("09:05", "invoice_sent")]["refs"]["invoice"] == "INV-0007"
    assert by[("10:30", "action_done")]["refs"]["action"] == "act1"
    assert by[("10:30", "timesheet_added")]["refs"]["action"] == "act1"
    assert by[("08:00", "proposed")]["refs"]["file"] == "00 Inbox/h.pdf"
    assert by[("07:00", "folders_renamed")]["refs"]["file"] == "00 Inbox"


def test_filters_by_actor_and_kind(client: TestClient) -> None:
    def events(**q) -> list[str]:
        return [f"{e['actor_label']}:{e['event']}" for e in _get(client, **q)["entries"]]

    assert events(actor="autopilot") == ["Autopilot:approved"]
    assert events(actor="triage") == ["Triage:mail_triaged"]
    assert events(actor="planner") == ["Planner:boiler_serviced"]
    assert set(events(actor="user")) == {
        "You:action_rejected",
        "You:timesheet_added",
        "You:action_done",
        "You:undone",
        "You:invoice_sent",
        "You:approved",
    }
    assert len(events(actor="agent")) == 5
    assert events(kind="approved") == ["You:approved", "Autopilot:approved"]
    assert events(kind="action") == ["You:action_rejected", "You:action_done"]
    assert events(kind="invoice") == ["You:invoice_sent"]
    assert events(actor="user", kind="approved") == ["You:approved"]


def test_range_spans_months_and_limit_is_capped(client: TestClient) -> None:
    page = _get(client, **{"from": "2026-09-01"})
    assert page["entries"][-1]["event"] == "todo_added"
    assert len(page["entries"]) == 13  # the day's 11, the 20 October approval, the September to-do
    two = _get(client, limit=2)
    assert [e["ts"][11:16] for e in two["entries"]] == ["11:00", "10:40"]
    assert two["truncated"] is True
    assert _get(client, limit=10_000)["truncated"] is False  # capped at 500, not refused


def test_default_range_and_bad_requests(client: TestClient) -> None:
    r = client.get("/audit", headers=H)
    assert r.status_code == 200
    page = r.json()
    assert date.fromisoformat(page["end"]) - date.fromisoformat(page["start"]) == timedelta(
        days=audit_view.DEFAULT_DAYS
    )
    assert client.get("/audit", params={"from": "2026-10-28", "to": DAY}, headers=H).status_code == 422
    assert client.get("/audit", params={"limit": 0}, headers=H).status_code == 422


def test_reading_writes_nothing(client: TestClient, fake: FakeStorageProvider) -> None:
    before = dict(fake.files)
    _get(client)
    _get(client, actor="user", kind="invoice")
    assert fake.files == before


def test_needs_a_token() -> None:
    from app.main import app

    assert TestClient(app).get("/audit").status_code == 401


async def test_unreadable_proposals_still_give_a_timeline(books: Books, fake: FakeStorageProvider) -> None:
    fake.files[f"_System/proposals/{'c' * 16}.json"] = b"{broken"
    page = await audit_view.read(books, date(2026, 10, 27), date(2026, 10, 27), kind="approved")
    assert [e.summary for e in page.entries] == ["Posted a document to the ledger"] * 2


def test_every_writer_kind_has_a_summary() -> None:
    """Each action name passed to Books.audit in app/ has its own sentence, so the table keeps up with new writers."""
    import re
    from pathlib import Path

    src = Path(audit_view.__file__).parent
    written: set[str] = set()
    for f in src.glob("*.py"):
        if f.name == "audit_view.py":  # its docstring quotes the line format
            continue
        written |= set(re.findall(r"\.audit(?:_autopilot)?\(\s*[^,\n]+,\s*\"([a-z_]+)\"\s*,", f.read_text()))
    written |= {"bank_transfer", "bank_ignored", "mileage_proposed", "mileage_refreshed"}  # built at run time
    assert written, "the scan found no audit calls"
    assert written - set(audit_view.SUMMARIES) == set()


def test_unknown_kind_and_odd_refs_fall_back_to_the_name() -> None:
    assert audit_view.summarise("vehicle_serviced", {}) == "Vehicle serviced"
    assert audit_view.summarise("bank_imported", {"new": "lots"}) == "Imported a bank statement: 0 new lines"
    assert audit_view.actor_of("agent:some_new-agent") == ("agent", "Some new agent")
    assert audit_view.actor_of("user:x@y") == ("user", "You")
