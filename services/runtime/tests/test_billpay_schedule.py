"""Upcoming PayPal payments (app/billpay_schedule.py): "Approve now, pay on due date", paid by /billpay/run on or after
the due date only if nothing changed, the schedule's totals and shortfall, the .ics file and the connected calendar.
Against the fake PayPal (app/online_fakes.py) and FakeCalendarProvider; nothing here talks to PayPal or a calendar."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import test_billpay as tb  # sibling module: pytest puts tests/ on the path
from fastapi.testclient import TestClient

from accnomos_connectors import FakeCalendarProvider, FakeStorageProvider
from app import billpay as bp
from app import billpay_schedule as sched
from app import payments
from app.books import Books
from app.journal import PAYPAL_CLEARING

CID, EMAIL, H, SUPPLIER, TODAY, USER = tb.CID, tb.EMAIL, tb.H, tb.SUPPLIER, tb.TODAY, tb.USER
_audit, _bill, _payout_posts = tb._audit, tb._bill, tb._payout_posts
_fakes, books, fake = tb._fakes, tb.books, tb.fake  # shared fixtures (the first is autouse)

LATER = TODAY + timedelta(days=20)  # a bill dated 10 days ago is due in 20 (30-day terms)


async def _approved(books: Books, gross: int = 12_000) -> tuple[str, bp.Approval]:
    eid = await _bill(books, gross, days_ago=10)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    return eid, await sched.approve(books, eid, gross, EMAIL, USER, today=TODAY)


# --------------------------------------------------------------------------- approve, cancel


async def test_approve_in_advance_is_stored_and_audited(books: Books, fake: FakeStorageProvider) -> None:
    eid, a = await _approved(books)
    assert a.status == "scheduled" and a.due_date == LATER and a.amount_pence == 12_000 and a.payee_email == EMAIL
    stored = json.loads(fake.files[f"{bp.SCHEDULED}"])["approvals"][eid]
    assert (
        stored["approved_by"] == USER
        and stored["bill_version"] == a.bill_version
        and stored["due_date"] == "2026-12-01"
    )
    assert (await bp.load_settings(books)).plans[eid].plan == "paypal"
    (row,) = [x for x in _audit(fake) if x["action"] == "billpay_scheduled_approved"]
    assert row["refs"]["amount_pence"] == 12_000 and row["refs"]["receiver"] == EMAIL
    ov = await bp.bills(books, today=TODAY)
    assert ov.upcoming[0].approval is not None and ov.upcoming[0].approval.status == "scheduled"
    # Nothing is sent before the due date, however often the app opens.
    await bp.run(books, today=TODAY)
    await bp.run(books, today=LATER - timedelta(days=1))
    assert not _payout_posts()
    with pytest.raises(bp.InvoiceStateError, match="already approved"):
        await sched.approve(books, eid, 12_000, EMAIL, USER, today=TODAY)


async def test_approve_refuses_what_the_card_did_not_show(books: Books) -> None:
    eid = await _bill(books, 12_000, days_ago=10)
    with pytest.raises(bp.BillPayError, match="PayPal email first"):
        await sched.approve(books, eid, 12_000, EMAIL, USER, today=TODAY)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    with pytest.raises(bp.InvoiceStateError, match="is owed on this bill now"):
        await sched.approve(books, eid, 11_000, EMAIL, USER, today=TODAY)
    with pytest.raises(bp.InvoiceStateError, match="saved PayPal email"):
        await sched.approve(books, eid, 12_000, "someone@else.example", USER, today=TODAY)
    due = await _bill(books, 5_000, days_ago=40)
    with pytest.raises(bp.InvoiceStateError, match="due already"):
        await sched.approve(books, due, 5_000, EMAIL, USER, today=TODAY)


async def test_paid_on_or_after_due_date_by_run(books: Books, fake: FakeStorageProvider) -> None:
    eid, _ = await _approved(books)
    r = await bp.run(books, today=LATER + timedelta(days=3))  # the app was closed on the due date itself
    (p,) = r.scheduled_paid
    assert p.event_id == eid and p.amount_pence == 12_000 and p.receiver == EMAIL and p.via == "owner"
    assert p.approved_by == USER and p.id == bp.sender_batch_id(eid, 12_000, 1)
    assert not r.paid  # Autopilot is off: this was the owner's approval in advance
    r2 = await bp.run(books, today=LATER + timedelta(days=3))  # next visit: PayPal says SUCCESS, posted once
    assert r2.refreshed[0].status == "paid" and not r2.scheduled_paid
    assert len(_payout_posts()) == 1
    actions = [x["action"] for x in _audit(fake)]
    assert "billpay_scheduled_sent" in actions and "billpay_payout_posted" in actions
    view = await sched.upcoming(books, today=LATER + timedelta(days=3))
    (item,) = view.items
    assert item.status == "paid" and item.approved and view.next_30_pence == 0


async def test_autopilot_off_does_not_stop_approved_payment(books: Books) -> None:
    eid, _ = await _approved(books)  # Autopilot was never turned on: the owner's own approval still pays
    r = await bp.run(books, today=LATER)
    assert [p.event_id for p in r.scheduled_paid] == [eid]


async def test_owner_kill_switch_keeps_approved_payment_back(books: Books) -> None:
    await _approved(books)
    await bp.stop_autopilot(books, USER)
    r = await bp.run(books, today=LATER)
    assert not r.scheduled_paid and not _payout_posts() and any("kill switch" in p for p in r.problems)


async def test_changed_amount_blocks(books: Books) -> None:
    eid, _ = await _approved(books)
    body = payments.PaymentIn(
        side="purchase",
        date=TODAY,
        amount_pence=2_000,
        account=PAYPAL_CLEARING,  # type: ignore[arg-type]
        reference="part paid by hand",
        allocations=[payments.AllocationIn(event_id=eid, amount_pence=2_000)],
        bank_line_id=None,
    )
    await payments.record_payment(books, body, USER)
    r = await bp.run(books, today=LATER)
    assert not r.scheduled_paid and not _payout_posts()
    (held,) = r.scheduled_held
    assert "£100.00 is owed now, not the £120.00 you approved" in held["reasons"]
    ov = await bp.bills(books, today=LATER)
    (b,) = ov.due  # it is now in Due today, with the reason
    assert b.approval is not None and b.approval.status == "needs_you" and "£100.00" in (b.approval.reason or "")
    assert (await bp.load_state(books)).notices[-1].kind == "asked"
    view = await sched.upcoming(books, today=LATER)
    assert view.items[0].status == "needs_you"


async def test_changed_payee_blocks(books: Books, fake: FakeStorageProvider) -> None:
    eid, _ = await _approved(books)
    await bp.set_payee(books, CID, "new@timberyard.example", None, USER)
    r = await bp.run(books, today=LATER)
    assert not _payout_posts()
    assert any("new@timberyard.example" in x for x in r.scheduled_held[0]["reasons"])
    assert any(x["action"] == "billpay_scheduled_held" for x in _audit(fake))


async def test_changed_bill_blocks(books: Books, fake: FakeStorageProvider) -> None:
    eid, _ = await _approved(books)
    raw = json.loads(fake.files[bp.SCHEDULED])
    raw["approvals"][eid]["bill_version"] = "something-else"  # as if the bill's entry had changed since approval
    fake.files[bp.SCHEDULED] = json.dumps(raw).encode()
    r = await bp.run(books, today=LATER)
    assert not _payout_posts()
    assert r.scheduled_held[0]["reasons"][0] == "The bill was changed after you approved the payment"


async def test_bill_gone_blocks(books: Books) -> None:
    eid, _ = await _approved(books)
    await payments.record_payment(
        books,
        payments.PaymentIn(
            side="purchase",
            date=TODAY,
            amount_pence=12_000,
            account=PAYPAL_CLEARING,  # type: ignore[arg-type]
            reference="paid another way",
            allocations=[payments.AllocationIn(event_id=eid, amount_pence=12_000)],
            bank_line_id=None,
        ),
        USER,
    )
    view = await sched.upcoming(books, today=TODAY)
    assert view.items[0].status == "needs_you" and "no longer open" in (view.items[0].reason or "")
    r = await bp.run(books, today=LATER)
    assert not _payout_posts() and "no longer open" in r.scheduled_held[0]["reasons"][0]


async def test_cancel(books: Books, fake: FakeStorageProvider) -> None:
    eid, _ = await _approved(books)
    a = await sched.cancel(books, eid, USER)
    assert a.status == "cancelled" and a.cancelled_by == USER
    await bp.run(books, today=LATER)
    assert not _payout_posts()
    assert any(x["action"] == "billpay_scheduled_cancelled" for x in _audit(fake))
    with pytest.raises(FileNotFoundError):
        await sched.cancel(books, eid, USER)
    # Approve again after cancelling: allowed.
    assert (await sched.approve(books, eid, 12_000, EMAIL, USER, today=TODAY)).status == "scheduled"


async def test_cannot_cancel_once_sent(books: Books) -> None:
    eid, _ = await _approved(books)
    await bp.run(books, today=LATER)
    with pytest.raises(bp.InvoiceStateError, match="already sent"):
        await sched.cancel(books, eid, USER)


# --------------------------------------------------------------------------- the schedule


async def test_upcoming_totals_and_shortfall(books: Books) -> None:
    # Clearing holds £5,000 by the books (the test_billpay fixture).
    a_id, _ = await _approved(books, 12_000)  # due in 20 days, approved in advance
    planned = await _bill(books, 300_000, days_ago=25)  # due in 5 days, planned (payee saved), not approved
    far = await _bill(books, 400_000, days_ago=-10)  # due in 40 days
    other = await _bill(books, 9_999, days_ago=10, supplier="No PayPal Ltd")  # no PayPal email: not planned
    view = await sched.upcoming(books, today=TODAY)
    by = {i.event_id: i for i in view.items}
    assert by[a_id].status == "scheduled" and by[a_id].approved
    assert by[planned].status == "planned" and not by[planned].approved
    assert far in by and other not in by
    assert view.next_7_pence == 300_000
    assert view.next_30_pence == 312_000
    assert view.shortfall_7_pence == 0 and view.shortfall_30_pence == 0 and view.warning is None
    assert "not your live PayPal balance" in view.clearing_label
    assert "PayPal cannot hold a payment for a future date" in view.note
    assert by[a_id].title == f"PayPal payment: {SUPPLIER} £120.00"
    assert "Accnomos pays this the next time it is open on or after 1 Dec 2026" in by[a_id].description
    # More than the clearing balance due within 7 days: shortfall, labelled as a books figure.
    await _bill(books, 250_000, days_ago=28)
    view = await sched.upcoming(books, today=TODAY)
    assert view.next_7_pence == 550_000 and view.shortfall_7_pence == 50_000
    assert view.warning and "books figure" in view.warning and "next 7 days" in view.warning
    # A not-PayPal bill leaves the schedule.
    await bp.set_plan(books, far, "not_paypal", USER)
    assert far not in {i.event_id for i in (await sched.upcoming(books, today=TODAY)).items}


async def test_due_today_and_paying_status(books: Books) -> None:
    eid, _ = await _approved(books)
    view = await sched.upcoming(books, today=LATER)
    assert view.items[0].status == "due_today"
    await bp.run(books, today=LATER)
    view = await sched.upcoming(books, today=LATER)
    assert view.items[0].status == "paying"


# --------------------------------------------------------------------------- calendar


def test_ics_escaping_and_folding() -> None:
    assert sched.ics_escape("a\\b; c, d\ne") == "a\\\\b\\; c\\, d\\ne"
    long = "DESCRIPTION:" + "é" * 80
    folded = sched.ics_fold(long)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == long


async def test_ics_content_and_stable_uid(books: Books) -> None:
    eid, _ = await _approved(books)
    await bp.set_payee(books, CID, EMAIL, None, USER)  # same email again: the approval still holds
    view = await sched.upcoming(books, today=TODAY)
    text = sched.ics(view.items)
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and text.endswith("END:VCALENDAR\r\n")
    unfolded = text.replace("\r\n ", "")
    assert f"UID:billpay-{eid}@accnomos.com" in unfolded
    assert "DTSTART;VALUE=DATE:20261201\r\n" in unfolded and "DTEND;VALUE=DATE:20261202\r\n" in unfolded
    assert "SUMMARY:PayPal payment: Timber Yard Ltd £120.00" in unfolded
    assert "Accnomos pays this the next time it is open on or after 1 Dec 2026 — PayPal cannot hold" in unfolded
    assert "\\," in unfolded  # the description's commas are escaped
    again = sched.ics((await sched.upcoming(books, today=TODAY)).items).replace("\r\n ", "")
    assert f"UID:billpay-{eid}@accnomos.com" in again  # stable per bill: re-adding updates the same event


@pytest.fixture
def client(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books, require_user
    from app.routes_plan import get_calendar

    cal = FakeCalendarProvider()

    async def over_books() -> Books:
        return books

    async def over_calendar():
        yield cal

    monkeypatch.setattr(sched, "london_today", lambda: TODAY)
    app.dependency_overrides[get_books] = over_books
    app.dependency_overrides[require_user] = lambda: USER
    app.dependency_overrides[get_calendar] = over_calendar
    c = TestClient(app)
    c.cal = cal  # type: ignore[attr-defined]
    yield c
    app.dependency_overrides.clear()


async def test_routes_and_connected_calendar(client: TestClient, books: Books) -> None:
    cal: FakeCalendarProvider = client.cal  # type: ignore[attr-defined]
    eid = await _bill(books, 12_000, days_ago=10)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    body = {"amount_pence": 12_000, "payee_email": EMAIL, "confirm": False}
    assert client.post(f"/billpay/bills/{eid}/schedule", json=body, headers=H).status_code == 400
    r = client.post(f"/billpay/bills/{eid}/schedule", json={**body, "confirm": True}, headers=H)
    assert r.status_code == 200, r.text
    r = client.get("/billpay/upcoming", headers=H)
    assert r.status_code == 200 and r.json()["items"][0]["status"] == "scheduled"
    r = client.get(f"/billpay/calendar.ics?event_id={eid}", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert f"UID:billpay-{eid}@accnomos.com" in r.text
    # The connected calendar, only on a tap (confirm), and never twice.
    assert client.post("/billpay/calendar", json={"confirm": False}, headers=H).status_code == 400
    assert not cal.events
    r = client.post("/billpay/calendar", json={"confirm": True, "event_ids": [eid]}, headers=H)
    assert r.status_code == 200 and r.json()["added"] == 1
    r = client.post("/billpay/calendar", json={"confirm": True}, headers=H)
    assert r.json()["unchanged"] == 1 and len(cal.events) == 1
    (ev,) = cal.events
    assert ev.key == f"billpay:{eid}" and ev.is_all_day and ev.subject == "PayPal payment: Timber Yard Ltd £120.00"
    assert client.get("/billpay/upcoming", headers=H).json()["items"][0]["in_calendar"] is True
    # Cancel: the event becomes stale; removing takes it out of the calendar.
    r = client.post(f"/billpay/bills/{eid}/schedule/cancel", json={"confirm": True}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    await bp.set_plan(books, eid, "not_paypal", USER)
    assert client.get("/billpay/upcoming", headers=H).json()["calendar_stale"] == [eid]
    r = client.post("/billpay/calendar/remove", json={"confirm": True}, headers=H)
    assert r.status_code == 200 and r.json()["removed"] == 1 and not cal.events
    assert client.get("/billpay/upcoming", headers=H).json()["calendar_stale"] == []
    r = client.get(f"/billpay/calendar.ics?event_id={eid}", headers=H)
    assert r.status_code == 404


def test_kill_switch_holds_back_approvals_in_advance(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The server kill switch stops approved-in-advance payments too; they stay approved."""
    import asyncio

    from app import billpay as bp
    from app import billpay_schedule as bs

    monkeypatch.setenv("BILLPAY_AUTOPILOT_OFF", "1")
    appr = type("A", (), {"status": "scheduled", "due_date": __import__("datetime").date(2026, 1, 1)})()

    async def load_scheduled(_b):  # type: ignore[no-untyped-def]
        return type("S", (), {"approvals": {"x": appr}})()

    async def load_settings(_b):  # type: ignore[no-untyped-def]
        return bp.Settings()

    async def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("must not read bills or pay")

    monkeypatch.setattr(bp, "load_scheduled", load_scheduled)
    monkeypatch.setattr(bp, "load_settings", load_settings)
    monkeypatch.setattr(bp, "bills", boom)
    out = bp.RunResult()
    asyncio.run(bs.run_scheduled(None, out, today=__import__("datetime").date(2026, 1, 2)))  # type: ignore[arg-type]
    assert out.problems and "kill switch" in out.problems[0] and appr.status == "scheduled"
