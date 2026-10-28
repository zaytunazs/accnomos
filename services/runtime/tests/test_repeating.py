"""Repeating invoices and bills: schedule dates (month ends, leap years), drafts versus approve-automatically,
claiming an occurrence so it is made once, and the audit trail (app/repeating.py, /repeating/*)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import invoicing as inv_
from app import repeating as rp_
from app.books import AUDIT, Books
from app.books import today as london_today
from app.invoicing import PROFILE, InvoiceProfile
from app.journal import CREDITORS
from app.repeating import RepeatingIn, occurrence

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {"name": "Sam Builds Ltd", "address": "1 High Street\nLeeds LS1 1AA", "vrn": "GB 123 4567 89"}
CUSTOMER = {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example", "address": "2 Low Road\nYork"}
SUPPLIER = {"name": "Landlord Properties Ltd", "vrn": "GB 220 4301 82"}
LINES = [
    {"description": "Retainer", "quantity": "1", "unit_price_pence": 25000, "vat_code": "S"},
    {"description": "Hosting", "quantity": "3", "unit_price_pence": 333, "vat_code": "S"},
]
TODAY = london_today()


def _tmpl(kind: str = "invoice", **kw) -> RepeatingIn:
    base = {
        "kind": kind,
        "frequency": "monthly",
        "start_date": date(2026, 1, 31).isoformat(),
        "party": CUSTOMER if kind == "invoice" else SUPPLIER,
        "lines": LINES,
    }
    return RepeatingIn.model_validate({**base, **kw})


def _d(s: str) -> date:
    return date.fromisoformat(s)


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await b.write_json(PROFILE, InvoiceProfile.model_validate(PROFILE_JSON).model_dump(mode="json"))
    return b


@pytest.fixture
def sender() -> FakeMailSender:
    return FakeMailSender()


@pytest.fixture
def client(books: Books, sender: FakeMailSender):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_invoices import get_sender

    async def over_books() -> Books:
        return books

    async def over_sender() -> FakeMailSender:
        return sender

    app.dependency_overrides[get_books] = over_books
    app.dependency_overrides[get_sender] = over_sender
    yield TestClient(app)
    app.dependency_overrides.clear()


def _audit(fake: FakeStorageProvider) -> list[dict]:
    return [
        json.loads(x)
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]


# --------------------------------------------------------------------------- #
# Schedule dates
# --------------------------------------------------------------------------- #


def _dates(start: str, frequency: str, every: int, n: int) -> list[str]:
    return [occurrence(_d(start), frequency, every, i).isoformat() for i in range(n)]  # type: ignore[arg-type]


def test_monthly_from_the_31st_uses_each_months_last_day_without_drifting():
    assert _dates("2026-01-31", "monthly", 1, 6) == [
        "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30",
    ]  # fmt: skip


def test_monthly_leap_year_february():
    assert _dates("2027-12-31", "monthly", 1, 4) == ["2027-12-31", "2028-01-31", "2028-02-29", "2028-03-31"]
    assert _dates("2028-01-30", "monthly", 1, 3) == ["2028-01-30", "2028-02-29", "2028-03-30"]


def test_quarterly_and_every_n_months():
    assert _dates("2026-11-30", "quarterly", 1, 4) == ["2026-11-30", "2027-02-28", "2027-05-30", "2027-08-30"]
    assert _dates("2026-01-15", "monthly", 2, 4) == ["2026-01-15", "2026-03-15", "2026-05-15", "2026-07-15"]
    assert _dates("2026-12-31", "quarterly", 2, 3) == ["2026-12-31", "2027-06-30", "2027-12-31"]


def test_yearly_from_29_february():
    assert _dates("2028-02-29", "yearly", 1, 5) == [
        "2028-02-29",
        "2029-02-28",
        "2030-02-28",
        "2031-02-28",
        "2032-02-29",
    ]


def test_weekly_and_fortnightly():
    assert _dates("2026-10-28", "weekly", 1, 3) == ["2026-10-28", "2026-11-04", "2026-11-11"]
    assert _dates("2026-12-30", "weekly", 2, 3) == ["2026-12-30", "2027-01-13", "2027-01-27"]


async def test_next_run_and_the_end_date(books: Books):
    t = await rp_.create_template(books, _tmpl(start_date="2026-01-31", end_date="2026-03-15"), USER)
    assert t.next_run() == date(2026, 1, 31) and t.id == "RP-0001"
    t.next_index = 2
    assert t.next_run() is None  # 31 March is after the end date
    assert rp_.row(t, date(2026, 5, 1)).finished is True
    with pytest.raises(ValueError, match="end date is before"):
        _tmpl(start_date="2026-05-01", end_date="2026-04-01")


# --------------------------------------------------------------------------- #
# Invoices
# --------------------------------------------------------------------------- #


async def test_due_occurrences_become_drafts_dated_on_their_schedule_days(books: Books, fake: FakeStorageProvider):
    t = await rp_.create_template(books, _tmpl(), USER)
    res = await rp_.process_due(books, None, today=date(2026, 4, 30))
    assert [(m.date.isoformat(), m.outcome, m.number) for m in res.made] == [
        ("2026-01-31", "draft", "INV-0001"),
        ("2026-02-28", "draft", "INV-0002"),
        ("2026-03-31", "draft", "INV-0003"),
        ("2026-04-30", "draft", "INV-0004"),
    ]
    invs = {i.number: i for i in await inv_.list_invoices(books)}
    assert [invs[f"INV-000{n}"].issue_date.isoformat() for n in (1, 2, 3, 4)] == [
        "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30",
    ]  # fmt: skip
    one = invs["INV-0001"]
    assert one.status == "draft" and one.repeating == "RP-0001#0" and one.due_date == date(2026, 3, 2)  # +30 days
    assert (one.net_pence, one.vat_pence, one.total_pence) == (25999, 5200, 31199)  # 3 x 3.33 = 9.99; 20% of 259.99
    assert await books.list_events() == []  # drafts post nothing
    got = await rp_.get_template(books, t.id)
    assert got.next_index == 4 and got.next_run() == date(2026, 5, 31) and got.pending is None
    assert [h.number for h in got.history] == ["INV-0001", "INV-0002", "INV-0003", "INV-0004"]
    gen = [e for e in _audit(fake) if e["action"] == "repeating_generated"]
    assert len(gen) == 4 and gen[0]["actor"] == "agent:repeating" and gen[0]["refs"]["created_by"] == USER
    # asking again the same day makes nothing
    assert (await rp_.process_due(books, None, today=date(2026, 4, 30))).made == []
    assert len(await inv_.list_invoices(books)) == 4


async def test_nothing_is_made_before_the_start_date_or_while_paused_or_after_it_is_stopped(books: Books):
    t = await rp_.create_template(books, _tmpl(start_date="2026-06-10"), USER)
    assert (await rp_.process_due(books, None, today=date(2026, 6, 9))).made == []
    await rp_.update_template(books, t.id, _tmpl(start_date="2026-06-10", paused=True), USER)
    assert (await rp_.process_due(books, None, today=date(2026, 7, 1))).made == []
    await rp_.update_template(books, t.id, _tmpl(start_date="2026-06-10"), USER)
    assert [m.date.isoformat() for m in (await rp_.process_due(books, None, today=date(2026, 7, 1))).made] == [
        "2026-06-10"
    ]
    await rp_.delete_template(books, t.id, USER)
    assert await rp_.list_templates(books) == []
    assert (await rp_.process_due(books, None, today=date(2027, 7, 1))).made == []


async def test_a_long_gap_is_caught_up_twelve_at_a_time(books: Books):
    await rp_.create_template(books, _tmpl(frequency="weekly", start_date="2026-01-05"), USER)
    first = await rp_.process_due(books, None, today=date(2026, 6, 1))  # 22 weekly occurrences are due
    assert len(first.made) == 12 and first.more_due == 10
    second = await rp_.process_due(books, None, today=date(2026, 6, 1))
    assert len(second.made) == 10 and second.more_due == 0
    assert len(await inv_.list_invoices(books)) == 22


async def test_approve_automatically_emails_and_posts_the_invoice_as_the_standing_approval(
    books: Books, sender: FakeMailSender, fake: FakeStorageProvider
):
    await rp_.create_template(books, _tmpl(approve_automatically=True, start_date="2026-10-01"), USER)
    res = await rp_.process_due(books, sender, today=date(2026, 10, 15))
    (m,) = res.made
    assert m.outcome == "sent" and m.number == "INV-0001" and m.note is None
    inv = await inv_.get_invoice(books, "INV-0001")
    assert inv.status == "sent" and inv.sent_by == "repeating:RP-0001" and inv.sent_to == "accounts@acme.example"
    (mail,) = sender.sent
    assert mail.to == "accounts@acme.example" and mail.attachments[0].name == "INV-0001.pdf"
    (event,) = await books.list_events()
    assert event.approved_by == "repeating:RP-0001" and event.date == date(2026, 10, 1)
    assert sum(ln.debit for ln in event.lines) == inv.total_pence
    gen = next(e for e in _audit(fake) if e["action"] == "repeating_generated")
    assert gen["refs"]["outcome"] == "sent" and gen["refs"]["approve_automatically"] is True


async def test_approve_automatically_stays_a_draft_and_says_why_when_it_cannot_send(
    books: Books, sender: FakeMailSender
):
    t = await rp_.create_template(
        books, _tmpl(approve_automatically=True, start_date="2026-10-01", party={"name": "No Email Ltd"}), USER
    )
    res = await rp_.process_due(books, sender, today=date(2026, 10, 15))
    assert [(m.outcome, m.note) for m in res.made] == [("draft", "Not sent: Add the customer's email address")]
    assert sender.sent == [] and (await inv_.get_invoice(books, "INV-0001")).status == "draft"
    assert (await rp_.get_template(books, t.id)).last_error == "Not sent: Add the customer's email address"
    assert (await rp_.process_due(books, sender, today=date(2026, 10, 15))).made == []  # not retried or duplicated


async def test_a_mail_failure_leaves_a_draft_and_nothing_posted(books: Books):
    class Failing:
        async def send(self, mail) -> None:
            raise RuntimeError("Graph said no")

    await rp_.create_template(books, _tmpl(approve_automatically=True, start_date="2026-10-01"), USER)
    res = await rp_.process_due(books, Failing(), today=date(2026, 10, 15))  # type: ignore[arg-type]
    assert res.made[0].outcome == "draft" and "Graph said no" in (res.made[0].note or "")
    assert (await inv_.get_invoice(books, "INV-0001")).status == "draft" and await books.list_events() == []


async def test_an_occurrence_claimed_before_a_crash_is_finished_once_without_a_duplicate(books: Books):
    t = await rp_.create_template(books, _tmpl(start_date="2026-10-01"), USER)
    assert await rp_._claim(books, t.id, 0, date(2026, 10, 1)) is True
    assert await rp_._claim(books, t.id, 0, date(2026, 10, 1)) is False  # a second tab does not also make it
    # the first run got as far as the invoice, then died before recording it
    draft = inv_.InvoiceDraft.model_validate({"customer": CUSTOMER, "issue_date": "2026-10-01", "lines": LINES})
    inv = await inv_.create_invoice(books, draft, USER)
    inv.repeating = "RP-0001#0"
    await inv_.save_invoice(books, inv)
    res = await rp_.process_due(books, None, today=date(2026, 10, 15))
    assert [m.number for m in res.made] == ["INV-0001"]
    assert len(await inv_.list_invoices(books)) == 1
    assert (await rp_.get_template(books, t.id)).next_index == 1


# --------------------------------------------------------------------------- #
# Bills
# --------------------------------------------------------------------------- #


async def test_a_repeating_bill_waits_in_review_as_a_proposal_dated_on_its_day(books: Books):
    await rp_.create_template(
        books, _tmpl("bill", start_date="2026-09-30", account="7100 Rent", frequency="monthly"), USER
    )
    res = await rp_.process_due(books, None, today=date(2026, 10, 31))
    assert [(m.date.isoformat(), m.outcome) for m in res.made] == [
        ("2026-09-30", "proposed"),
        ("2026-10-30", "proposed"),
    ]
    props = {p.id: p for p in await books.list_proposals()}
    first = props[res.made[0].proposal_id or ""]
    assert first.status == "proposed" and first.extracted.date == "2026-09-30" and first.account_override == "7100 Rent"
    assert first.extracted.supplier_name == "Landlord Properties Ltd" and first.model == "code:repeating"
    assert round(first.extracted.gross_total * 100) == 31199
    assert await books.list_events() == []
    # asked again: the same two proposals, not four
    await rp_.process_due(books, None, today=date(2026, 10, 31))
    assert len(await books.list_proposals()) == 2


async def test_a_repeating_bill_set_to_approve_automatically_posts_with_the_standing_approval(
    books: Books, fake: FakeStorageProvider
):
    await rp_.create_template(
        books, _tmpl("bill", start_date="2026-10-01", account="7100 Rent", approve_automatically=True), USER
    )
    res = await rp_.process_due(books, None, today=date(2026, 10, 15))
    assert [m.outcome for m in res.made] == ["posted"]
    (event,) = await books.list_events()
    assert event.approved_by == "repeating:RP-0001" and event.date == date(2026, 10, 1)
    assert next(ln.credit for ln in event.lines if ln.account == CREDITORS) == 31199  # owed until paid
    assert "approved" in [e["action"] for e in _audit(fake)]
    assert next(e for e in _audit(fake) if e["action"] == "approved")["actor"] == "user:repeating:RP-0001"
    (p,) = await books.list_proposals("posted")
    assert p.decided_by == "repeating:RP-0001"


async def test_a_bill_that_needs_a_look_is_not_approved_automatically(books: Books):
    await rp_.create_template(
        books,
        _tmpl("bill", start_date="2026-10-01", party={"name": "Cash Merchant"}, approve_automatically=True),
        USER,
    )
    res = await rp_.process_due(books, None, today=date(2026, 10, 15))
    assert res.made[0].outcome == "proposed" and "Waiting in Review" in (res.made[0].note or "")
    assert await books.list_events() == []
    assert (await books.list_proposals())[0].status == "needs_a_look"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def test_routes_create_list_process_pause_delete(client: TestClient, sender: FakeMailSender):
    start = (TODAY - timedelta(days=3)).isoformat()
    body = _tmpl(start_date=start, frequency="weekly").model_dump(mode="json")
    made = client.post("/repeating", json=body, headers=H)
    assert made.status_code == 200
    got = made.json()
    assert got["id"] == "RP-0001" and got["next_date"] == start and got["due_now"] is True and got["finished"] is False
    assert got["totals"] == [25999, 5200, 31199]

    done = client.post("/repeating/process", headers=H).json()
    assert [m["outcome"] for m in done["made"]] == ["draft"] and done["problems"] == [] and done["more_due"] == 0
    row = client.get("/repeating/RP-0001", headers=H).json()
    assert row["next_date"] == (TODAY - timedelta(days=3) + timedelta(weeks=1)).isoformat() and row["due_now"] is False
    assert client.get("/invoices", headers=H).json()[0]["number"] == "INV-0001"
    assert client.post("/repeating/process", headers=H).json()["made"] == []

    paused = client.put("/repeating/RP-0001", json={**body, "paused": True}, headers=H)
    assert paused.status_code == 200 and paused.json()["paused"] is True
    assert client.put("/repeating/RP-0001", json={**body, "kind": "bill"}, headers=H).status_code == 400
    assert client.delete("/repeating/RP-0001", headers=H).status_code == 204
    assert client.get("/repeating/RP-0001", headers=H).status_code == 404
    assert client.get("/repeating", headers=H).json() == []
    assert sender.sent == []


def test_routes_dates_preview_and_validation(client: TestClient):
    r = client.get("/repeating/dates?frequency=monthly&start=2026-01-31&count=4", headers=H)
    assert r.json() == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]
    r = client.get("/repeating/dates?frequency=yearly&start=2028-02-29&count=3&end=2029-12-31", headers=H)
    assert r.json() == ["2028-02-29", "2029-02-28"]
    bad = _tmpl().model_dump(mode="json")
    assert client.post("/repeating", json={**bad, "frequency": "daily"}, headers=H).status_code == 422
    assert client.post("/repeating", json={**bad, "lines": []}, headers=H).status_code == 422
    assert client.post("/repeating", json={**bad, "account": "1200 Bank"}, headers=H).status_code == 422
