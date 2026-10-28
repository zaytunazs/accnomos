"""Payment chasing: step selection, opt-out, statutory interest, compensation, and drafts that send nothing."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import chasing as chase_
from app import invoicing as inv_
from app.books import AUDIT, Books
from app.contacts import CONTACTS, Contact
from app.invoicing import PROFILE, InvoiceDraft, InvoiceProfile

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}
DUE = date(2026, 9, 30)  # a Tuesday; H2 2026, so the reference date is 30 Jun 2026


def _contact(cid: str, **kw) -> Contact:
    fields: dict = {
        "kind": "customer",
        "name": "Acme Kitchens Ltd",
        "normalised_key": "acme-kitchens-ltd",
        "email": "accounts@acme.example",
    }
    fields.update(kw)
    return Contact(id=cid, **fields)


def _draft(customer: dict, due: date = DUE, total_lines: list[dict] | None = None) -> InvoiceDraft:
    lines = total_lines or [{"description": "Labour", "quantity": "1", "unit_price_pence": 100000}]
    return InvoiceDraft.model_validate(
        {
            "customer": customer,
            "issue_date": "2026-09-01",
            "due_date": due.isoformat(),
            "lines": lines,
        }
    )


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


async def _sent(books: Books, sender: FakeMailSender, customer: dict, due: date = DUE):
    inv = await inv_.create_invoice(books, _draft(customer, due), USER)
    return await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4")


def _audit_actions(fake: FakeStorageProvider) -> list[dict]:
    return [
        json.loads(x)
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]


# --------------------------------------------------------------------------- #
# Step selection by date
# --------------------------------------------------------------------------- #


async def test_steps_fall_due_in_order(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender, {"name": "Acme", "email": "a@acme.example"})
    config = await chase_.load_config(books)
    assert [s.id for s in config.steps] == ["pre-due", "due", "week-overdue", "firm", "final"]
    assert chase_.next_step(inv, date(2026, 9, 26), config) is None  # 4 days before: too early
    assert chase_.next_step(inv, date(2026, 9, 27), config).id == "pre-due"  # 3 days before
    # With nothing sent, the earliest due step is always next, however late it is.
    assert chase_.next_step(inv, date(2026, 9, 30), config).id == "pre-due"
    assert chase_.next_step(inv, date(2027, 3, 1), config).id == "pre-due"


async def test_sent_reminders_advance_the_next_step(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender, {"name": "Acme", "email": "a@acme.example"})
    config = await chase_.load_config(books)
    days = {
        "pre-due": date(2026, 9, 27),
        "due": date(2026, 9, 30),
        "week-overdue": date(2026, 10, 7),
        "firm": date(2026, 10, 14),
        "final": date(2026, 10, 30),
    }
    for want, day in days.items():  # each step falls due in turn and is chased before the next
        assert chase_.next_step(inv, day, config).id == want
        inv = await inv_.send_reminder(
            books, sender, inv.number, USER, to="a@acme.example", subject="s", body="b", pdf=None, step=want
        )
        assert chase_.next_step(inv, day, config) is None  # nothing else is due yet
    assert chase_.next_step(inv, date(2027, 3, 1), config) is None  # all five sent: nothing next
    assert [r.step for r in inv.reminders] == ["pre-due", "due", "week-overdue", "firm", "final"]
    assert len(sender.sent) == 6  # the invoice itself, then the five reminders


async def test_sends_without_a_step_id_count_as_the_earliest(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender, {"name": "Acme", "email": "a@acme.example"})
    config = await chase_.load_config(books)
    inv = await inv_.send_reminder(
        books, sender, inv.number, USER, to="a@acme.example", subject="s", body="b", pdf=None
    )
    assert chase_.next_step(inv, date(2026, 9, 27), config) is None  # the pre-due send is used up
    assert chase_.next_step(inv, date(2026, 9, 30), config).id == "due"


async def test_drafts_and_paid_invoices_have_no_step(books: Books, sender: FakeMailSender):
    inv = await inv_.create_invoice(books, _draft({"name": "Acme"}), USER)
    config = await chase_.load_config(books)
    assert chase_.next_step(inv, date(2026, 12, 1), config) is None  # still a draft


# --------------------------------------------------------------------------- #
# Opt-out
# --------------------------------------------------------------------------- #


async def test_opted_out_contact_gets_no_step(books: Books, sender: FakeMailSender, client: TestClient):
    await books.write_json(CONTACTS, [_contact("a1b2c3d4e5f60718", chasing_opt_out=True).model_dump(mode="json")])
    customer = {"contact_id": "a1b2c3d4e5f60718", "name": "Acme Kitchens Ltd", "email": "accounts@acme.example"}
    inv = await _sent(books, sender, customer)
    rows = client.get("/invoices/chasing/overdue", params={"as_of": "2026-10-30"}).json()
    assert [(x["number"], x["chasing_opted_out"], x["step"]) for x in rows] == [(inv.number, True, None)]
    # Interest still accrues for an opted-out business contact.
    assert rows[0]["interest_pence"] > 0
    r = client.get(f"/invoices/{inv.number}/chase-draft", params={"as_of": "2026-10-30"})
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# Interest
# --------------------------------------------------------------------------- #


def test_reference_dates():
    assert chase_.reference_date(date(2026, 1, 1)) == date(2025, 12, 31)
    assert chase_.reference_date(date(2026, 6, 30)) == date(2025, 12, 31)
    assert chase_.reference_date(date(2026, 7, 1)) == date(2026, 6, 30)
    assert chase_.reference_date(date(2026, 12, 31)) == date(2026, 6, 30)


def test_interest_across_a_reference_date_change():
    rates = [
        chase_.BaseRate(annual_percent=Decimal("3.50"), effective=date(2026, 1, 1)),
        chase_.BaseRate(annual_percent=Decimal("4.00"), effective=date(2026, 6, 15)),
    ]
    # Due 20 Jun 2026, as of 10 Jul: 11 days at 3.50 + 8 = 11.50%, then 9 days at 4.00 + 8 = 12.00%.
    got = chase_.interest_pence(100_000, date(2026, 6, 20), date(2026, 7, 10), rates)
    assert got == 347 + 296 == 643


def test_interest_is_zero_before_the_due_date():
    rates = [chase_.BaseRate(annual_percent=Decimal("4.00"), effective=date(2026, 8, 7))]
    assert chase_.interest_pence(100_000, DUE, DUE, rates) == 0
    assert chase_.interest_pence(100_000, DUE, date(2026, 9, 29), rates) == 0
    assert chase_.interest_pence(0, DUE, date(2026, 10, 30), rates) == 0


def test_interest_rounds_half_up_to_the_penny():
    # GBP 18.25 for one day at 2.00 + 8 = 10.00%: exactly half a penny, which rounds up to 1p.
    rates = [chase_.BaseRate(annual_percent=Decimal("2.00"), effective=date(2026, 1, 1))]
    assert chase_.interest_pence(1825, date(2026, 9, 1), date(2026, 9, 2), rates) == 1
    assert chase_.interest_pence(1824, date(2026, 9, 1), date(2026, 9, 2), rates) == 0


def test_compensation_bands():
    assert chase_.compensation_pence(99_999) == 4_000  # GBP 999.99
    assert chase_.compensation_pence(100_000) == 7_000  # GBP 1,000.00
    assert chase_.compensation_pence(999_999) == 7_000  # GBP 9,999.99
    assert chase_.compensation_pence(1_000_000) == 10_000  # GBP 10,000.00


def test_final_step_names_interest_for_business_only(books: Books, sender: FakeMailSender):
    config = chase_.ChasingConfig()
    final = next(s for s in config.steps if s.id == "final")
    assert final.mention_interest is True
    assert all(not s.mention_interest for s in config.steps if s.id != "final")


async def test_final_draft_mentions_interest_for_business_only(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender, {"name": "Acme", "email": "a@acme.example"})
    config = await chase_.load_config(books)
    final = next(s for s in config.steps if s.id == "final")
    profile = await inv_.load_profile(books)
    _, business_body = chase_.render_draft(inv, profile, final, date(2026, 10, 30), True)
    _, consumer_body = chase_.render_draft(inv, profile, final, date(2026, 10, 30), False)
    assert "Late Payment of Commercial Debts (Interest) Act 1998" in business_body
    assert "Interest" not in consumer_body


# --------------------------------------------------------------------------- #
# The overdue endpoint
# --------------------------------------------------------------------------- #


async def test_overdue_lists_interest_only_for_business(books: Books, sender: FakeMailSender, client: TestClient):
    await books.write_json(
        CONTACTS,
        [
            _contact("a1b2c3d4e5f60718", name="Acme Kitchens Ltd", normalised_key="acme").model_dump(mode="json"),
            _contact(
                "b1b2c3d4e5f60719",
                name="Jane Homeowner",
                normalised_key="jane",
                email=None,
                is_business=False,
            ).model_dump(mode="json"),
        ],
    )
    biz = await _sent(
        books, sender, {"contact_id": "a1b2c3d4e5f60718", "name": "Acme Kitchens Ltd", "email": "a@acme.example"}
    )
    home = await _sent(
        books, sender, {"contact_id": "b1b2c3d4e5f60719", "name": "Jane Homeowner", "email": "j@home.example"}
    )
    rows = {r["number"]: r for r in client.get("/invoices/chasing/overdue", params={"as_of": "2026-10-30"}).json()}
    assert rows[biz.number]["days_overdue"] == 30
    assert rows[biz.number]["business"] is True
    assert rows[biz.number]["step"]["id"] == "pre-due"
    assert rows[biz.number]["interest_pence"] > 0
    assert rows[biz.number]["compensation_pence"] == 7_000  # GBP 1,200 gross
    assert rows[home.number]["business"] is False
    assert rows[home.number]["interest_pence"] is None
    assert rows[home.number]["compensation_pence"] is None
    assert rows[home.number]["step"]["id"] == "pre-due"  # consumers are still chased, politely


async def test_typed_in_customer_is_not_b2b(books: Books, sender: FakeMailSender, client: TestClient):
    inv = await _sent(books, sender, {"name": "Walk-in Trade", "email": "w@trade.example"})
    (row,) = client.get("/invoices/chasing/overdue", params={"as_of": "2026-10-30"}).json()
    assert row["number"] == inv.number and row["business"] is False
    assert row["interest_pence"] is None


# --------------------------------------------------------------------------- #
# Drafts send nothing; approved sends are recorded
# --------------------------------------------------------------------------- #


async def test_draft_endpoints_send_nothing(books: Books, sender: FakeMailSender, client: TestClient):
    await books.write_json(CONTACTS, [_contact("a1b2c3d4e5f60718").model_dump(mode="json")])
    inv = await _sent(
        books, sender, {"contact_id": "a1b2c3d4e5f60718", "name": "Acme Kitchens Ltd", "email": "a@acme.example"}
    )
    n_sent = len(sender.sent)
    get = client.get(f"/invoices/{inv.number}/chase-draft", params={"as_of": "2026-09-27"}).json()
    assert get["step"]["id"] == "pre-due" and get["todo_id"] is None
    assert inv.number in get["subject"] or inv.number in get["body"]
    for step, day in [("pre-due", "2026-09-27"), ("due", "2026-09-30")]:
        draft = client.get(f"/invoices/{inv.number}/chase-draft", params={"as_of": day}).json()
        assert draft["step"]["id"] == step
        r = client.post(
            f"/invoices/{inv.number}/reminder-send",
            json={"confirm": True, "to": "a@acme.example", "subject": "s", "body": "b", "step": step},
            headers=H,
        )
        assert r.status_code == 200, r.text
    post = client.post(f"/invoices/{inv.number}/chase-draft", headers=H).json()
    assert post["todo_id"] and post["step"]["id"] == "week-overdue"
    assert len(sender.sent) == n_sent + 2  # only the two approved reminder-sends mailed; no draft endpoint did
    stored = await inv_.get_invoice(books, inv.number)
    assert [x.step for x in stored.reminders] == ["pre-due", "due"]  # only the approved sends recorded
    todos = await books.read_json("_System/Todos/todos.json", [])
    assert any(post["todo_id"] == t["id"] and inv.number in t["text"] for t in todos)


async def test_approved_reminder_is_recorded_on_invoice_and_audit(
    books: Books, sender: FakeMailSender, client: TestClient, fake: FakeStorageProvider
):
    inv = await _sent(books, sender, {"name": "Acme", "email": "a@acme.example"})
    r = client.post(
        f"/invoices/{inv.number}/reminder-send",
        json={"confirm": True, "to": "a@acme.example", "subject": "Overdue", "body": "Please pay", "step": "firm"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert len(sender.sent) == 2  # the invoice itself, then the reminder
    stored = await inv_.get_invoice(books, inv.number)
    assert [(x.step, x.to) for x in stored.reminders] == [("firm", "a@acme.example")]
    sent = [a for a in _audit_actions(fake) if a["action"] == "invoice_reminder_sent"]
    assert sent and sent[0]["refs"]["step"] == "firm" and sent[0]["refs"]["invoice"] == inv.number
