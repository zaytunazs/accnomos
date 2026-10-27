"""Sales invoices against FakeStorageProvider and FakeMailSender: pence and VAT per line, numbering, status
transitions and the ledger, PDF smoke, sending only with `confirm: true`, and Muse reminders checked by code."""

from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from accnomos_ledger.vat import compute_vat_return
from app import invoicing as inv_
from app import jobs
from app.ai import remind
from app.ai.config import AiConfig
from app.approve import reversal_of
from app.books import AUDIT, Books
from app.invoicing import (
    PROFILE,
    SENT,
    SEQUENCE,
    InvoiceCustomer,
    InvoiceDraft,
    InvoiceError,
    InvoiceProfile,
    InvoiceStateError,
    LineIn,
    money,
    price_lines,
)
from app.pdf import render_invoice

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}
CUSTOMER = {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example", "address": "2 Low Road\nYork"}
TODAY = date(2026, 10, 27)


def _draft(lines: list[dict] | None = None, **kw) -> InvoiceDraft:
    lines = lines or [
        {"description": "Kitchen refit labour", "quantity": "7.5", "unit": "hours", "unit_price_pence": 4500}
    ]
    return InvoiceDraft.model_validate({"customer": CUSTOMER, "issue_date": TODAY.isoformat(), "lines": lines, **kw})


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


def _audit(fake: FakeStorageProvider) -> list[str]:
    return [
        json.loads(x)["action"]
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]


async def _sent(books: Books, sender: FakeMailSender, draft: InvoiceDraft | None = None):
    inv = await inv_.create_invoice(books, draft or _draft(), USER)
    pdf = render_invoice(inv, await inv_.load_profile(books))
    return await inv_.send_invoice(books, sender, inv.number, USER, pdf)


# --------------------------------------------------------------------------- #
# Money: pence, VAT per line
# --------------------------------------------------------------------------- #


def test_lines_priced_in_pence_with_vat_rounded_per_line():
    lines, summary, net, vat = price_lines(
        [
            LineIn(
                description="Labour", quantity=Decimal("7.5"), unit_price_pence=4500, vat_code="S"
            ),  # 337.50 + 67.50
            LineIn(
                description="Fixings", quantity=Decimal("3"), unit_price_pence=333, vat_code="S"
            ),  # 9.99 + 2.00 (1.998)
            LineIn(
                description="Fuel", quantity=Decimal("1"), unit_price_pence=1999, vat_code="R"
            ),  # 19.99 + 1.00 (0.9995)
            LineIn(description="Book", quantity=Decimal("2"), unit_price_pence=1250, vat_code="Z"),
            LineIn(description="Insurance", quantity=Decimal("1"), unit_price_pence=5000, vat_code="E"),
            LineIn(
                description="Discount", quantity=Decimal("1"), unit_price_pence=-1000, vat_code="S"
            ),  # -10.00 - 2.00
            LineIn(description="Thirds", quantity=Decimal("0.333"), unit_price_pence=100, vat_code="O"),  # 33.3p -> 33p
        ]
    )
    assert [(ln.net_pence, ln.vat_pence) for ln in lines] == [
        (33750, 6750),
        (999, 200),
        (1999, 100),
        (2500, 0),
        (5000, 0),
        (-1000, -200),
        (33, 0),
    ]
    assert [(r.vat_code, r.net_pence, r.vat_pence) for r in summary] == [
        ("S", 33749, 6750),
        ("R", 1999, 100),
        ("Z", 2500, 0),
        ("E", 5000, 0),
        ("O", 33, 0),
    ]
    assert net == sum(ln.net_pence for ln in lines) == 43281 and vat == 6850


def test_totals_sent_by_a_client_are_refused_and_code_prices_the_lines():
    with pytest.raises(ValidationError) as exc:
        InvoiceDraft.model_validate(
            {
                "customer": CUSTOMER,
                "lines": [
                    {"description": "x", "quantity": 1, "unit_price_pence": 1000, "net_pence": 1, "vat_pence": 1}
                ],
                "total_pence": 5,
            }
        )
    assert {e["type"] for e in exc.value.errors()} == {"extra_forbidden"}
    draft = InvoiceDraft.model_validate(
        {"customer": CUSTOMER, "lines": [{"description": "x", "quantity": 1, "unit_price_pence": 1000}]}
    )
    inv = inv_.build_invoice("INV-0001", draft, InvoiceProfile(), USER, TODAY)
    assert (inv.net_pence, inv.vat_pence, inv.total_pence) == (1000, 200, 1200)
    assert inv.due_date == TODAY + timedelta(days=30)


def test_money_is_exact():
    assert money(121460) == "£1,214.60" and money(5) == "£0.05" and money(-1999) == "-£19.99"


def test_bad_lines_and_dates_refused():
    with pytest.raises(ValueError):
        _draft([{"description": "x", "quantity": 0, "unit_price_pence": 100}])
    with pytest.raises(ValueError):
        _draft([{"description": "x", "quantity": "1.2345", "unit_price_pence": 100}])
    with pytest.raises(ValueError):
        _draft([{"description": "x", "quantity": 1, "unit_price_pence": 100, "vat_code": "N"}])
    with pytest.raises(InvoiceError):
        inv_.build_invoice("INV-0001", _draft(due_date="2026-10-01"), InvoiceProfile(), USER)


# --------------------------------------------------------------------------- #
# Numbering
# --------------------------------------------------------------------------- #


async def test_numbers_are_sequential_and_never_reused(books: Books, fake: FakeStorageProvider):
    a = await inv_.create_invoice(books, _draft(), USER)
    b = await inv_.create_invoice(books, _draft(), USER)
    assert (a.number, b.number) == ("INV-0001", "INV-0002")
    await inv_.void_invoice(books, a.number, USER, "typo")
    assert (await inv_.create_invoice(books, _draft(), USER)).number == "INV-0003"
    assert json.loads(fake.files[SEQUENCE]) == {"prefix": "INV-", "next": 4}
    # sequence.json wound back by hand: taken numbers are skipped, not overwritten
    await books.write_json(SEQUENCE, {"prefix": "INV-", "next": 2})
    assert (await inv_.create_invoice(books, _draft(), USER)).number == "INV-0004"


async def test_bad_draft_takes_no_number(books: Books, fake: FakeStorageProvider):
    with pytest.raises(InvoiceError):
        await inv_.create_invoice(books, _draft(due_date="2026-01-01"), USER)
    assert SEQUENCE not in fake.files


async def test_customer_details_filled_from_the_contact_book(books: Books):
    await books.write_json(
        inv_.CONTACTS,
        [
            {
                "id": "c0ffee0000000001",
                "kind": "customer",
                "name": "Acme Kitchens Ltd",
                "email": "ap@acme.example",
                "address": "Unit 4\nYork",
                "vrn": "GB987654321",
            },
            {"id": "c0ffee0000000002", "kind": "supplier", "name": "Screwfix", "email": None},
        ],
    )
    assert [c.name for c in await inv_.customers(books)] == ["Acme Kitchens Ltd"]
    draft = InvoiceDraft(
        customer=InvoiceCustomer(contact_id="c0ffee0000000001", name="Acme Kitchens Ltd"),
        lines=[LineIn(description="x", quantity=Decimal(1), unit_price_pence=100)],
    )
    inv = await inv_.create_invoice(books, draft, USER)
    assert (inv.customer.email, inv.customer.vrn) == ("ap@acme.example", "GB987654321")


async def test_bad_ids_cannot_leave_the_invoices_folder(books: Books):
    for bad in ("../_System/rules", "inv-0001", "INV 1", ""):
        with pytest.raises(FileNotFoundError):
            await inv_.get_invoice(books, bad)


# --------------------------------------------------------------------------- #
# Status transitions and the ledger
# --------------------------------------------------------------------------- #


async def test_send_posts_the_sale_once_and_it_reaches_the_vat_return(
    books: Books, sender: FakeMailSender, fake: FakeStorageProvider
):
    inv = await _sent(
        books,
        sender,
        _draft(
            [
                {"description": "Labour", "quantity": 10, "unit_price_pence": 5000, "vat_code": "S"},
                {"description": "Kids' books", "quantity": 1, "unit_price_pence": 2000, "vat_code": "Z"},
                {"description": "Fee paid on their behalf", "quantity": 1, "unit_price_pence": 3000, "vat_code": "O"},
            ]
        ),
    )
    assert inv.status == "sent" and inv.sent_to == CUSTOMER["email"] and inv.event_id == inv_.sale_event_id("INV-0001")
    (event,) = await books.list_events()
    assert event.kind == "sale" and event.date == TODAY and event.counterparty == "Acme Kitchens Ltd"
    assert [(ln.account, ln.debit, ln.credit, ln.vat_code) for ln in event.lines] == [
        ("1100 Debtors", 65000, 0, None),
        ("4000 Sales", 0, 50000, "S"),
        ("4000 Sales", 0, 2000, "Z"),
        ("4000 Sales", 0, 3000, "O"),
        ("2200 VAT control", 0, 10000, "S"),
    ]
    assert event.evidence == [inv.pdf_sha256] and event.approved_by == USER
    ret = compute_vat_return([event], "x", date(2026, 10, 1), date(2026, 12, 31))
    assert str(ret.vat_due_sales) == "100.00" and ret.total_sales_ex_vat == 520  # outside-scope fee not in Box 6
    assert fake.files[f"{SENT}/INV-0001.pdf"].startswith(b"%PDF")
    assert {"invoice_created", "invoice_sent", "invoice_posted"} <= set(_audit(fake))


async def test_only_drafts_can_be_edited_or_sent(books: Books, sender: FakeMailSender):
    inv = await inv_.create_invoice(books, _draft(), USER)
    edited = await inv_.update_draft(
        books, inv.number, _draft([{"description": "y", "quantity": 2, "unit_price_pence": 100}]), USER
    )
    assert edited.total_pence == 240 and edited.created_at == inv.created_at
    await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4")
    with pytest.raises(InvoiceStateError):
        await inv_.update_draft(books, inv.number, _draft(), USER)
    with pytest.raises(InvoiceStateError):
        await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4")
    assert len(sender.sent) == 1 and len(await books.list_events()) == 1


async def test_failed_email_changes_nothing(books: Books, sender: FakeMailSender, fake: FakeStorageProvider):
    inv = await inv_.create_invoice(books, _draft(), USER)
    sender.fail = RuntimeError("Graph 503")
    with pytest.raises(RuntimeError):
        await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4")
    assert (await inv_.get_invoice(books, inv.number)).status == "draft"
    assert await books.list_events() == [] and f"{SENT}/{inv.number}.pdf" not in fake.files


async def test_retry_after_a_failed_post_posts_without_emailing_again(
    books: Books, sender: FakeMailSender, monkeypatch
):
    inv = await inv_.create_invoice(books, _draft(), USER)
    real = books.post_event

    async def broken(_event):
        raise OSError("OneDrive hiccup")

    monkeypatch.setattr(books, "post_event", broken)
    with pytest.raises(OSError):
        await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4")
    half = await inv_.get_invoice(books, inv.number)
    assert half.status == "sent" and half.event_id is None and len(sender.sent) == 1
    monkeypatch.setattr(books, "post_event", real)
    done = await inv_.send_invoice(books, sender, inv.number, USER, b"")
    assert done.event_id and len(sender.sent) == 1 and len(await books.list_events()) == 1


async def test_cannot_send_without_what_an_invoice_needs(books: Books, sender: FakeMailSender):
    await books.write_json(PROFILE, {"name": "Sam Builds Ltd", "address": "1 High St"})  # no VAT number
    inv = await inv_.create_invoice(
        books,
        InvoiceDraft.model_validate(
            {
                "customer": {"name": "No Email Ltd"},
                "lines": [{"description": "x", "quantity": 1, "unit_price_pence": 100}],
            }
        ),
        USER,
    )
    with pytest.raises(InvoiceError) as err:
        await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF")
    assert "email" in str(err.value) and "VAT registration number" in str(err.value)
    assert sender.sent == []


async def test_mark_paid_and_void_rules(books: Books, sender: FakeMailSender):
    draft = await inv_.create_invoice(books, _draft(), USER)
    with pytest.raises(InvoiceStateError):
        await inv_.mark_paid(books, draft.number, USER, payment_ref="x")
    sent = await _sent(books, sender)
    paid = await inv_.mark_paid(books, sent.number, USER, payment_ref="FPS ACME 0002", paid_on=date(2026, 11, 3))
    assert (paid.status, paid.paid_at, paid.payment_ref) == ("paid", date(2026, 11, 3), "FPS ACME 0002")
    assert (paid.paid_pence, paid.balance_pence, paid.payment_status) == (40500, 0, "paid")
    with pytest.raises(InvoiceStateError, match="Remove it first"):
        await inv_.void_invoice(books, paid.number, USER, "changed my mind")
    with pytest.raises(InvoiceStateError):
        await inv_.mark_paid(books, paid.number, USER)
    voided = await inv_.void_invoice(books, draft.number, USER, "duplicate")
    assert voided.status == "void" and voided.reversal_event_id is None
    events = await books.list_events()
    assert [e.kind for e in events] == ["sale", "bank"]  # Mark paid posts the payment; voiding a draft posts nothing
    lines = {ln.account: (ln.debit, ln.credit) for ln in events[1].lines}
    assert lines == {"1200 Bank": (40500, 0), "1100 Debtors": (0, 40500)}


async def test_voiding_a_sent_invoice_reverses_the_sale(books: Books, sender: FakeMailSender):
    sent = await _sent(books, sender)
    voided = await inv_.void_invoice(books, sent.number, USER, "wrong customer")
    events = await books.list_events()
    assert [e.kind for e in events] == ["sale", "reversal"] and events[1].reverses == sent.event_id
    assert voided.reversal_event_id == events[1].id
    ret = compute_vat_return(events, "x", date(2026, 10, 1), date(2026, 12, 31))
    assert str(ret.vat_due_sales) == "0.00" and ret.total_sales_ex_vat == 0 and str(ret.vat_reclaimed) == "0.00"


async def test_voiding_after_the_reversal_was_already_posted_does_not_post_it_twice(
    books: Books, sender: FakeMailSender
):
    # A void that posted its reversal and then failed before saving the invoice: the retry must still finish.
    sent = await _sent(books, sender)
    await books.post_event(reversal_of(await books.get_event(sent.event_id), USER))
    voided = await inv_.void_invoice(books, sent.number, USER, "wrong customer")
    events = await books.list_events()
    assert [e.kind for e in events] == ["sale", "reversal"]
    assert voided.status == "void" and voided.reversal_event_id == events[1].id


async def test_mark_paid_links_a_bank_line(books: Books, sender: FakeMailSender):
    sent = await _sent(books, sender)  # £405.00
    csv = (
        b"Date,Description,Amount\n"
        b"03/11/2026,ACME KITCHENS INV-0001,405.00\n"
        b"04/11/2026,OTHER,405.00\n"
        b"02/11/2026,COFFEE,-2.50\n"
    )
    await books.import_bank_csv(csv, "nov.csv", USER)
    cands = await inv_.bank_candidates(books, sent)
    assert [c.description for c in cands] == ["ACME KITCHENS INV-0001", "OTHER"]
    paid = await inv_.mark_paid(books, sent.number, USER, bank_line_id=cands[0].id)
    assert (paid.paid_at, paid.payment_ref, paid.bank_line_id, paid.status) == (
        date(2026, 11, 3),
        "ACME KITCHENS INV-0001",
        cands[0].id,
        "paid",
    )
    payment = next(e for e in await books.list_events() if e.kind == "bank")  # Dr 1200 Bank / Cr 1100 Debtors
    line = next(ln for ln in await books.stored_bank_lines() if ln.id == cands[0].id)
    assert line.status == "matched" and line.event_ids() == [payment.id]  # the statement line reconciles to it


# --------------------------------------------------------------------------- #
# Job hours: lines from a job's timesheets, marked invoiced when the invoice is sent
# --------------------------------------------------------------------------- #

JOB = jobs.Job(id="00000000a001", name="Kitchen refit, 12 Elm Road", customer_id="c1")
OTHER_JOB = jobs.Job(id="00000000a002", name="Bathroom, 3 Ash Lane")
SAM = jobs.StaffMember(
    id="00000000b001", name="Sam", role="Electrician", hourly_rate_pence=2000, charge_rate_pence=4500
)


async def _hours(books: Books, *specs: tuple[float, bool]) -> list[jobs.TimesheetEntry]:
    for job in (JOB, OTHER_JOB):
        await jobs.save_job(books, job)
    await jobs.save_staff(books, SAM)
    return [
        await jobs.add_entry(
            books, jobs.TimesheetEntry(staff_id=SAM.id, job_id=JOB.id, date=date(2026, 10, 3 + n), hours=h, billable=b)
        )
        for n, (h, b) in enumerate(specs)
    ]


def _job_draft(proposal: jobs.InvoiceProposal, **kw) -> InvoiceDraft:
    """What the web's invoice form sends after reading the job's proposed lines."""
    lines = [
        {
            "description": ln.description,
            "quantity": str(ln.qty),
            "unit": ln.unit,
            "unit_price_pence": ln.unit_price_pence,
            "vat_code": ln.vat_code,
            "timesheet_entry_ids": ln.entry_ids,
        }
        for ln in proposal.lines
    ]
    return _draft(lines, job_id=proposal.job_id, **kw)


async def _proposal(books: Books) -> jobs.InvoiceProposal:
    return jobs.invoice_lines(JOB, await jobs.load_entries(books), await jobs.load_staff(books))


async def test_sending_an_invoice_from_job_hours_marks_them_with_its_number(
    books: Books, sender: FakeMailSender, fake: FakeStorageProvider
):
    a, b = await _hours(books, (3, True), (1.5, True))
    inv = await inv_.create_invoice(books, _job_draft(await _proposal(books)), USER)
    assert inv.job_id == JOB.id and inv.timesheet_entry_ids() == [a.id, b.id] and inv.net_pence == 20250  # 4.5h × £45
    assert all(e.invoiced_in is None for e in await jobs.load_entries(books))  # a draft marks nothing

    sent = await inv_.send_invoice(books, sender, inv.number, USER, render_invoice(inv, await inv_.load_profile(books)))
    assert sent.timesheets_marked and sent.event_id
    assert {e.invoiced_in for e in await jobs.load_entries(books)} == {inv.number}
    assert (await _proposal(books)).lines == []  # never proposed again
    assert "timesheets_invoiced" in _audit(fake)


async def test_job_hours_on_a_draft_are_checked(books: Books):
    a, unbillable = await _hours(books, (3, True), (1, False))
    other = await jobs.add_entry(
        books, jobs.TimesheetEntry(staff_id=SAM.id, job_id=OTHER_JOB.id, date=date(2026, 10, 9), hours=2)
    )
    billed = await jobs.add_entry(
        books, jobs.TimesheetEntry(staff_id=SAM.id, job_id=JOB.id, date=date(2026, 10, 9), hours=2)
    )
    await jobs.mark_invoiced(books, [billed.id], "INV-0042")

    def line(*ids: str) -> dict:
        return {"description": "Labour", "quantity": "1", "unit_price_pence": 4500, "timesheet_entry_ids": list(ids)}

    for lines, job_id, why in [
        ([line(a.id)], None, "need the job"),
        ([line(a.id)], "00000000ffff", "No such job"),
        ([line(other.id)], JOB.id, "not on this job"),
        ([line("00000000eeee")], JOB.id, "not on this job"),
        ([line(unbillable.id)], JOB.id, "not billable"),
        ([line(billed.id)], JOB.id, "already on invoice INV-0042"),
        ([line(a.id), line(a.id)], JOB.id, "more than one line"),
    ]:
        with pytest.raises(InvoiceError, match=why):
            await inv_.create_invoice(books, _draft(lines, job_id=job_id), USER)
    inv = await inv_.create_invoice(books, _draft([line(a.id)], job_id=JOB.id), USER)
    with pytest.raises(InvoiceError, match="not billable"):
        await inv_.update_draft(books, inv.number, _draft([line(unbillable.id)], job_id=JOB.id), USER)


async def test_hours_changed_after_the_draft_are_skipped_not_fatal(
    books: Books, sender: FakeMailSender, fake: FakeStorageProvider
):
    a, b = await _hours(books, (3, True), (2, True))
    inv = await inv_.create_invoice(books, _job_draft(await _proposal(books)), USER)
    await jobs.delete_entry(books, b.id)  # still allowed: the draft has not been sent
    sent = await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4")
    assert sent.status == "sent" and sent.timesheets_marked and len(sender.sent) == 1
    assert (await jobs.get_entry(books, a.id)).invoiced_in == inv.number
    (row,) = [
        json.loads(x)
        for p, d in fake.files.items()
        if p.startswith(f"{AUDIT}/")
        for x in d.decode().splitlines()
        if json.loads(x)["action"] == "timesheets_invoiced"
    ]
    assert row["refs"]["entries"] == [a.id] and row["refs"]["skipped"] == [b.id]


async def test_a_second_draft_of_the_same_hours_is_refused_before_it_is_emailed(books: Books, sender: FakeMailSender):
    (a,) = await _hours(books, (3, True))
    first = await inv_.create_invoice(books, _job_draft(await _proposal(books)), USER)
    second = await inv_.create_invoice(
        books, _job_draft(await _proposal(books)), USER
    )  # both drafts: nothing marked yet
    await inv_.send_invoice(books, sender, first.number, USER, b"%PDF-1.4")
    with pytest.raises(InvoiceError, match=f"already on invoice {first.number}"):
        await inv_.send_invoice(books, sender, second.number, USER, b"%PDF-1.4")
    assert len(sender.sent) == 1 and (await inv_.get_invoice(books, second.number)).status == "draft"
    assert (await jobs.get_entry(books, a.id)).invoiced_in == first.number


async def test_hours_are_marked_before_the_sale_posts_and_a_retry_does_not_email_again(
    books: Books,
    sender: FakeMailSender,
    monkeypatch,
):
    (a,) = await _hours(books, (3, True))
    inv = await inv_.create_invoice(books, _job_draft(await _proposal(books)), USER)
    real = books.post_event

    async def broken(_event):
        raise OSError("OneDrive hiccup")

    monkeypatch.setattr(books, "post_event", broken)
    with pytest.raises(OSError):
        await inv_.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4")
    assert (await jobs.get_entry(books, a.id)).invoiced_in == inv.number  # not billable twice while the post is retried
    monkeypatch.setattr(books, "post_event", real)
    done = await inv_.send_invoice(books, sender, inv.number, USER, b"")
    assert done.event_id and done.timesheets_marked and len(sender.sent) == 1


def test_job_hours_round_trip_through_the_routes(client: TestClient, books: Books, sender: FakeMailSender):
    import asyncio

    (a,) = asyncio.run(_hours(books, (2, True)))
    proposal = client.post(f"/jobs/{JOB.id}/invoice-lines", headers=H).json()
    draft = _job_draft(jobs.InvoiceProposal.model_validate(proposal)).model_dump(mode="json")
    r = client.post("/invoices", json=draft, headers=H)
    assert r.status_code == 200, r.text
    number = r.json()["number"]
    assert r.json()["job_id"] == JOB.id and r.json()["lines"][0]["timesheet_entry_ids"] == [a.id]
    assert (
        client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H).json()["timesheets_marked"] is True
    )
    entries = client.get(f"/timesheets?job_id={JOB.id}", headers=H).json()
    assert [e["invoiced_in"] for e in entries] == [number]
    assert client.post("/invoices", json=draft, headers=H).status_code == 400  # the same hours cannot be billed again


# --------------------------------------------------------------------------- #
# Routes: PDF smoke, send gated behind confirm: true
# --------------------------------------------------------------------------- #


def test_pdf_route_renders_and_saves(client: TestClient, fake: FakeStorageProvider):
    number = client.post("/invoices", json=_draft().model_dump(mode="json"), headers=H).json()["number"]
    r = client.post(f"/invoices/{number}/pdf", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    data = base64.b64decode(body["data_url"].removeprefix("data:application/pdf;base64,"))
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF") and body["size"] == len(data)
    assert fake.files[f"03 Sales/invoices/{number}.pdf"] == data
    assert body["problems"] == [] and body["email"]["to"] == CUSTOMER["email"] and number in body["email"]["subject"]


def test_send_needs_confirm_true(client: TestClient, sender: FakeMailSender, books: Books):
    number = client.post("/invoices", json=_draft().model_dump(mode="json"), headers=H).json()["number"]
    for body in ({}, {"confirm": False}, {"confirm": "yes"}):
        r = client.post(f"/invoices/{number}/send", json=body, headers=H)
        assert r.status_code in (400, 422), body
    assert sender.sent == []
    assert client.get(f"/invoices/{number}", headers=H).json()["status"] == "draft"

    r = client.post(f"/invoices/{number}/send", json={"confirm": True, "subject": "Your invoice"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent" and r.json()["days_overdue"] is not None
    (mail,) = sender.sent
    assert mail.to == CUSTOMER["email"] and mail.subject == "Your invoice" and number in mail.body_text
    assert mail.attachments[0].name == f"{number}.pdf" and mail.attachments[0].data.startswith(b"%PDF")
    assert client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H).status_code == 409
    assert len(sender.sent) == 1


def test_list_filters_by_status_and_profile_round_trip(client: TestClient, fake: FakeStorageProvider):
    for _ in range(2):
        client.post("/invoices", json=_draft().model_dump(mode="json"), headers=H)
    client.post("/invoices/INV-0001/send", json={"confirm": True}, headers=H)
    assert [i["number"] for i in client.get("/invoices?status=draft", headers=H).json()] == ["INV-0002"]
    assert len(client.get("/invoices", headers=H).json()) == 2
    assert client.get("/invoices/INV-9999", headers=H).status_code == 404

    prof = client.get("/invoices/profile", headers=H).json()
    assert prof["vrn"] == "GB123456789" and prof["bank"]["sort_code"] == "12-34-56"
    assert client.put("/invoices/profile", json={**prof, "vrn": "123"}, headers=H).status_code == 422
    assert client.put("/invoices/profile", json={**prof, "logo_path": "../x.png"}, headers=H).status_code == 400
    assert (
        client.put(
            "/invoices/profile", json={**prof, "logo_path": "_System/Invoicing/profile.json"}, headers=H
        ).status_code
        == 400
    )
    r = client.post("/invoices/profile/logo", files={"file": ("logo.png", _png(60, 20), "image/png")}, headers=H)
    assert r.status_code == 200 and r.json()["logo_path"] == "_System/Invoicing/logo.png"
    assert (
        client.post("/invoices/profile/logo", files={"file": ("l.gif", b"GIF89a", "image/gif")}, headers=H).status_code
        == 415
    )
    # a logo that went bad in the user's folder does not stop the PDF
    fake.files["_System/Invoicing/logo.png"] = b"\x89PNG not really"
    assert client.post("/invoices/INV-0002/pdf", headers=H).status_code == 200


# --------------------------------------------------------------------------- #
# Reminders: Muse drafts, code checks, the user sends
# --------------------------------------------------------------------------- #

CFG = AiConfig(mode="local", base_url="http://localhost:11434", model="muse-glimmer:30b")


async def _overdue(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender, _draft(issue_date="2026-09-01", due_date="2026-10-01"))
    return inv, await inv_.load_profile(books)


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (
            {
                "subject": "Invoice INV-0001",
                "body": "Hi, invoice INV-0001 for £405.00 was due on 1 October 2026. Thanks, Sam Builds Ltd",
            },
            None,
        ),
        (
            {"subject": "Invoice INV-0001", "body": "Invoice INV-0001 for £450.00 is overdue."},
            "figures that are not on the invoice",
        ),
        ({"subject": "Invoice INV-0001", "body": "Pay INV-0001 for £405.00 at https://pay.example/x"}, "link"),
        ({"subject": "Hello", "body": "Please pay £405.00."}, "invoice number"),
        ("not json", "expected format"),
    ],
)
async def test_reminder_draft_is_checked(books: Books, sender: FakeMailSender, monkeypatch, reply, reason):
    inv, profile = await _overdue(books, sender)

    async def fake_model(messages, cfg):
        facts = json.loads(messages[1]["content"].removeprefix("FACTS:\n"))
        assert facts["amount_due"] == "£405.00" and facts["days_overdue"] == 26 and facts["status"] == "overdue"
        assert "sort_code" not in messages[1]["content"]  # bank details never go to the model
        return reply if isinstance(reply, str) else json.dumps(reply)

    monkeypatch.setattr(remind, "_call_model", fake_model)
    d = await remind.draft_reminder(inv, profile, CFG, TODAY)
    assert d.to == CUSTOMER["email"] and d.days_overdue == 26 and sender.sent[1:] == []
    if reason is None:
        assert d.fallback_reason is None and d.body == reply["body"]
    else:
        assert reason in d.fallback_reason
        assert "INV-0001" in d.subject and "£405.00" in d.body and "26 days overdue" in d.body


def test_reminder_routes_draft_then_send_only_when_confirmed(client: TestClient, sender: FakeMailSender, monkeypatch):
    async def fake_model(messages, cfg):
        return json.dumps(
            {"subject": "Reminder INV-0001", "body": "Hello, a reminder about invoice INV-0001 for £405.00."}
        )

    monkeypatch.setattr(remind, "_call_model", fake_model)
    client.post("/invoices", json=_draft().model_dump(mode="json"), headers=H)
    assert client.post("/invoices/INV-0001/reminder-draft", headers=H).status_code == 409  # still a draft
    client.post("/invoices/INV-0001/send", json={"confirm": True}, headers=H)

    d = client.post("/invoices/INV-0001/reminder-draft", headers=H).json()
    assert d["fallback_reason"] is None and len(sender.sent) == 1  # drafting sent nothing
    send = {"to": d["to"], "subject": d["subject"], "body": d["body"] + "\n\nSam"}
    assert client.post("/invoices/INV-0001/reminder-send", json=send, headers=H).status_code == 400
    r = client.post("/invoices/INV-0001/reminder-send", json={**send, "confirm": True}, headers=H)
    assert r.status_code == 200 and len(r.json()["reminders"]) == 1
    mail = sender.sent[-1]
    assert mail.body_text.endswith("Sam") and mail.attachments[0].data == sender.sent[0].attachments[0].data


def test_fallback_reminder_reads_as_sentences():
    inv = inv_.build_invoice("INV-0001", _draft(issue_date="2026-10-01", due_date="2026-11-10"), InvoiceProfile(), USER)
    inv.status = "sent"
    profile = InvoiceProfile.model_validate(PROFILE_JSON)
    _, body = remind.fallback_draft(remind.reminder_facts(inv, profile, TODAY))  # not due yet
    assert "\nThis is a quick reminder that invoice INV-0001" in body and body.endswith("Sam Builds Ltd")
    _, body = remind.fallback_draft(remind.reminder_facts(inv, profile, date(2026, 11, 11)))
    assert "\nInvoice INV-0001 for £405.00 was due on 10 November 2026 and is now 1 day overdue." in body
    inv.reminders.append(inv_.Reminder(sent_at=inv.created_at, sent_by=USER, to="a@b.example", subject="x"))
    _, body = remind.fallback_draft(remind.reminder_facts(inv, InvoiceProfile(), date(2026, 11, 20)))
    assert "\nFollowing up on my earlier email: invoice INV-0001" in body and body.endswith("Kind regards,")


def test_pdf_survives_unicode_text_and_any_logo():
    import io

    from PIL import Image

    png = io.BytesIO()
    Image.new("RGB", (60, 20), (13, 110, 110)).save(png, format="PNG")
    draft = _draft(
        [{"description": "Café refit — “phase 2” 日本", "quantity": "1", "unit_price_pence": 10000}],
        notes="Thanks – see you soon…",
    )
    inv = inv_.build_invoice("INV-0001", draft, InvoiceProfile.model_validate(PROFILE_JSON), USER)
    for logo in (png.getvalue(), b"not an image", None):
        assert render_invoice(inv, InvoiceProfile.model_validate(PROFILE_JSON), logo).startswith(b"%PDF")


def test_logo_over_1_mb_refused(client: TestClient, fake: FakeStorageProvider):
    big = b"\x89PNG" + b"0" * (1024 * 1024)
    assert (
        client.post("/invoices/profile/logo", files={"file": ("l.png", big, "image/png")}, headers=H).status_code == 413
    )
    assert "_System/Invoicing/logo.png" not in fake.files


def _png(w: int, h: int, fmt: str = "PNG") -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (w, h), (13, 110, 110)).save(out, format=fmt)
    return out.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "declared", "status"),
    [
        ("logo.png", b"GIF89a" + b"\x00" * 64, "image/png", 415),  # a GIF calling itself a PNG
        ("logo.png", b"<svg onload=alert(1)>", "image/png", 415),  # markup, not an image
        ("logo.jpg", "png-bytes", "image/jpeg", 415),  # declared type disagrees with the bytes
        ("logo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 200, "image/png", 415),  # right magic, not a picture
        ("logo.png", "wide", "image/png", 413),  # 5000 px wide: small file, huge to decode
    ],
)
def test_logo_is_sniffed_decoded_and_size_checked(
    client: TestClient, fake: FakeStorageProvider, name, data, declared, status
):
    data = {"png-bytes": _png(10, 10), "wide": _png(5000, 1)}.get(data, data)  # type: ignore[call-overload]
    r = client.post("/invoices/profile/logo", files={"file": (name, data, declared)}, headers=H)
    assert r.status_code == status, r.text
    assert not any(p.startswith("_System/Invoicing/logo") for p in fake.files)


def test_logo_over_1_mb_is_refused_by_the_route_inside_the_2_mb_body_cap(client: TestClient, fake: FakeStorageProvider):
    from app.routes_invoices import LOGO_MAX

    data = _png(10, 10) + b"\x00" * LOGO_MAX  # a real PNG with trailing bytes: past the file limit, under the body cap
    r = client.post("/invoices/profile/logo", files={"file": ("logo.png", data, "image/png")}, headers=H)
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    assert not any(p.startswith("_System/Invoicing/logo") for p in fake.files)


def test_jpeg_logo_is_named_from_its_bytes(client: TestClient, fake: FakeStorageProvider):
    r = client.post("/invoices/profile/logo", files={"file": ("x.png", _png(30, 30, "JPEG"), "image/jpeg")}, headers=H)
    assert r.status_code == 200 and r.json()["logo_path"] == "_System/Invoicing/logo.jpg"


async def test_a_hand_edited_logo_path_is_not_read(books: Books, fake: FakeStorageProvider):
    fake.files["_System/secret.txt"] = b"not for the PDF"
    profile = InvoiceProfile.model_validate({"logo_path": "_System/secret.txt"})  # as if typed into profile.json
    assert await inv_.load_logo(books, profile) is None


def test_pdf_text_cannot_use_fpdfs_page_count_alias():
    """fpdf2 swaps "{nb}" for the page count everywhere in the document; typed-in text must come out as typed."""
    import zlib

    draft = _draft([{"description": "Ref {nb} and {nb}", "quantity": "1", "unit_price_pence": 100}])
    inv = inv_.build_invoice("INV-0001", draft, InvoiceProfile(name="{nb} Ltd"), USER)
    pdf = render_invoice(inv, InvoiceProfile(name="{nb} Ltd"))
    streams = b"".join(
        zlib.decompress(s) for s in __import__("re").findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, flags=16)
    )
    assert b"{nb} Ltd" in streams and b"Ref {nb} and {nb}" in streams
    assert b"(Page 1 of ) Tj (1) Tj" in streams and b"\x1enb" not in streams  # the footer's own alias still works


def test_routes_need_a_token():
    from app.main import app

    assert TestClient(app).get("/invoices").status_code == 401


def test_days_overdue():
    inv = inv_.build_invoice("INV-0001", _draft(issue_date="2026-10-01", due_date="2026-10-20"), InvoiceProfile(), USER)
    assert inv.overdue_days(TODAY) is None  # a draft is not awaiting payment
    inv.status = "sent"
    assert inv.overdue_days(TODAY) == 7 and inv.overdue_days(date(2026, 10, 1)) == -19
