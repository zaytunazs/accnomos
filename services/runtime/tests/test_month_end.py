"""The month-end close agent (app/month_end.py) on FakeStorageProvider: each step's detection logic, cards that wait
for Approve, the close record, post-close change detection with before/after figures, and re-close. No model."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from accnomos_ledger.bank import BankLine
from app import actions, jobs, month_end
from app import invoicing as inv_
from app.ai import close_summary
from app.ai.config import AiConfig
from app.approve import reversal_of
from app.books import BANK_LINES, EVENTS, Books
from app.paths import INBOX, REPORTS
from app.vat_cycle import VatCycle

USER = "sam@sambuilds.co.uk"
TOKEN = "graph-token-1"
TODAY = date(2026, 11, 4)
OCT = "2026-10"
CYCLE = VatCycle(start_month=1, months=3)  # calendar quarters
STATEMENT = "04 Bank statements/2026-10-31_starling.csv"
PROFILE = inv_.InvoiceProfile.model_validate({"name": "Sam Builds Ltd", "address": "1 High Street\nLeeds LS1 1AA"})


def purchase(eid: str, gross: int, when: date, who: str, account: str = "5000 Materials", settle: str = "1200 Bank"):
    net = round(gross / 1.2)
    return LedgerEvent(
        id=eid,
        kind="purchase",
        date=when,
        net=net,
        vat=gross - net,
        counterparty=who,
        approved_by=USER,
        approved_at=datetime(when.year, when.month, when.day, 12, tzinfo=UTC),
        lines=[
            Line(account=account, debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=gross - net),
            Line(account=settle, credit=gross),
        ],
    )


def line(lid: int, when: date, amount: int, balance: int | None, src: str = STATEMENT, **kw: Any) -> dict:
    return BankLine(
        id=f"{lid:016x}",
        date=when,
        amount_pence=amount,
        description=kw.pop("description", "CARD PAYMENT"),
        balance_pence=balance,
        source_file=src,
        **kw,
    ).model_dump(mode="json")


async def invoice(b: Books, number: str, issue: date, status: str, email: str | None = "acc@acme.example"):
    draft = inv_.InvoiceDraft.model_validate(
        {
            "customer": {"name": "Acme Kitchens Ltd", "email": email},
            "issue_date": issue.isoformat(),
            "lines": [{"description": "Labour", "quantity": "10", "unit": "hours", "unit_price_pence": 5000}],
        }
    )
    inv = inv_.build_invoice(number, draft, PROFILE, USER)
    if status != "draft":
        event = inv_.sale_event(inv, USER, [])
        await b.post_event(event)
        inv.event_id = event.id
    inv.status = status  # type: ignore[assignment]
    await inv_.save_invoice(b, inv)
    return inv


def ctx(b: Books, month: str = OCT, today: date = TODAY, **kw: Any) -> month_end.Ctx:
    return month_end.Ctx(books=b, month=month, today=today, cycle=CYCLE, user=USER, token=TOKEN, **kw)


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def clean(fake: FakeStorageProvider) -> Books:
    """October with nothing outstanding: one purchase, paid from the bank, its line matched; statements cover it."""
    b = Books(fake)
    ev = purchase("a" * 32, 12000, date(2026, 10, 14), "Screwfix")
    await b.post_event(ev)
    await b.write_json(
        f"{BANK_LINES}/{'1' * 64}.json",
        [
            line(1, date(2026, 10, 1), 50000, 150000, description="TRANSFER IN", status="transfer"),
            line(
                2,
                date(2026, 10, 14),
                -12000,
                138000,
                status="matched",
                matched_event_id=ev.id,
                matched_event_ids=[ev.id],
            ),
            line(3, date(2026, 10, 30), -500, 137500, description="BANK FEE", status="ignored"),
        ],
    )
    return b


# --------------------------------------------------------------------------- #
# Step detection
# --------------------------------------------------------------------------- #


def test_coverage_gaps() -> None:
    o1, o31 = date(2026, 10, 1), date(2026, 10, 31)
    assert month_end.coverage_gaps([(o1, date(2026, 10, 11))], o1, o31) == [(date(2026, 10, 12), o31)]
    # A few days without transactions at either edge are not a gap.
    assert month_end.coverage_gaps([(date(2026, 10, 3), date(2026, 10, 29))], o1, o31) == []
    # Between two statements; one that started in September still counts for October.
    got = month_end.coverage_gaps([(date(2026, 9, 20), date(2026, 10, 5)), (date(2026, 10, 20), o31)], o1, o31)
    assert got == [(date(2026, 10, 6), date(2026, 10, 19))]
    assert month_end.span(date(2026, 10, 12), o31) == "12–31 Oct"


async def test_bank_statement_missing_for_the_rest_of_the_month(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    await b.write_json(
        f"{BANK_LINES}/{'2' * 64}.json",
        [line(1, date(2026, 10, 2), -1000, 9000), line(2, date(2026, 10, 11), -1000, 8000, status="ignored")],
    )
    step = await month_end.step_bank(ctx(b))
    texts = [f.text for f in step.found]
    assert "Bank statement missing for 12–31 Oct (starling): upload it on Bank." in texts
    assert step.status == "needs_you" and step.blocking >= 2  # the gap, and one open line with no match
    assert step.data["coverage"]["starling"]["gaps"] == [{"from": "2026-10-12", "to": "2026-10-31"}]


async def test_no_bank_statements_says_what_to_upload(fake: FakeStorageProvider) -> None:
    step = await month_end.step_bank(ctx(Books(fake)))
    assert step.status == "needs_you" and step.blocking == 1
    assert "upload October's statement" in step.reason


async def test_balance_jump_between_statements_means_missing_lines(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    a, c = "04 Bank statements/2026-10-10_starling.csv", "04 Bank statements/2026-10-31_starling.csv"
    await b.write_json(
        f"{BANK_LINES}/{'3' * 64}.json",
        [
            line(1, date(2026, 10, 1), -100, 10000, a, status="ignored"),
            line(2, date(2026, 10, 10), -100, 9900, a, status="ignored"),
        ],
    )
    await b.write_json(
        f"{BANK_LINES}/{'4' * 64}.json",
        [
            line(3, date(2026, 10, 12), -100, 5000, c, status="ignored"),
            line(4, date(2026, 10, 30), -100, 4900, c, status="ignored"),
        ],
    )
    step = await month_end.step_bank(ctx(b))
    jump = [f for f in step.found if "lines are missing" in f.text]
    assert len(jump) == 1 and jump[0].level == "blocking"
    assert "£99.00 at the end of the statement to 10 Oct but £51.00" in jump[0].text


async def test_bank_suggestion_becomes_an_approve_card_and_posts_nothing(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    ev = purchase("b" * 32, 4800, date(2026, 10, 9), "Screwfix")
    await b.post_event(ev)
    await b.write_json(
        f"{BANK_LINES}/{'5' * 64}.json",
        [
            line(1, date(2026, 10, 1), 0, 10000, status="ignored"),
            line(2, date(2026, 10, 10), -4800, 5200, description="SCREWFIX DIRECT"),
            line(3, date(2026, 10, 31), 0, 5200, status="ignored"),
        ],
    )
    c = ctx(b)
    step = await month_end.step_bank(c)
    assert len(c.cards) == 1 and c.cards[0].kind == "match_bank_line" and step.proposes == [c.cards[0].id]
    assert c.cards[0].preview["event_ids"] == [ev.id]
    assert (await b.find_bank_line(f"{2:016x}")).status == "unmatched"  # nothing done until Approve
    done = await actions.approve(c.cards[0], actions.Context(books=b, user=USER, graph_token=TOKEN))
    assert done.status == "done" and (await b.find_bank_line(f"{2:016x}")).status == "matched"


async def test_overdue_invoices_get_reminder_cards_and_drafts_block(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    await invoice(b, "INV-0001", date(2026, 9, 1), "sent")  # due 1 Oct
    await invoice(b, "INV-0002", date(2026, 9, 5), "sent", email=None)
    await invoice(b, "INV-0003", date(2026, 10, 20), "draft")
    c = ctx(b)  # no AI: code writes the reminder
    step = await month_end.step_sales(c)
    assert [a.kind for a in c.cards] == ["chase_invoice"]
    card = c.cards[0]
    assert card.preview["invoice"] == "INV-0001" and card.preview["days_overdue"] == 34
    assert "£600.00" in card.preview["body"]  # the figure is code's
    texts = " ".join(f.text for f in step.found)
    assert "INV-0002" in texts and "no email address" in texts
    draft = next(f for f in step.found if f.refs.get("invoice") == "INV-0003")
    assert draft.level == "blocking" and "still a draft" in draft.text


async def test_missing_pay_run(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    assert (await month_end.step_payroll(ctx(b))).reason.startswith("Payroll is not used")
    await jobs.save_job(b, jobs.Job(id="00000000a001", name="Kitchen"))
    await jobs.save_staff(b, jobs.StaffMember(id="00000000b001", name="Alex", hourly_rate_pence=1500))
    quiet = await month_end.step_payroll(ctx(b))
    assert quiet.status == "needs_you" and quiet.blocking == 0  # no hours: maybe nobody was paid
    await jobs.add_entry(
        b, jobs.TimesheetEntry(staff_id="00000000b001", job_id="00000000a001", date=date(2026, 10, 6), hours=8)
    )
    step = await month_end.step_payroll(ctx(b))
    assert step.blocking == 1 and "No pay run for October 2026, but 8 hours were logged" in step.reason


async def test_vat_period_end_prepares_the_boxes_and_never_submits(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    await b.post_event(purchase("c" * 32, 1200, date(2026, 9, 3), "Screwfix"))
    sep = await month_end.step_vat(ctx(b, "2026-09", date(2026, 10, 5)))
    assert sep.status == "needs_you" and sep.data["label"] == "Jul–Sep 2026" and sep.data["deadline"] == "2026-11-07"
    assert [x["amount"] for x in sep.data["boxes"]][:5] == ["0.00", "0.00", "0.00", "2.00", "2.00"]
    assert sep.data["trail"][0]["event_id"] == "c" * 32
    assert "never submits" in sep.reason and "to reclaim" in sep.reason
    octo = await month_end.step_vat(ctx(b))
    assert octo.status == "ok" and "does not end a VAT period (Oct–Dec 2026 ends on 31 Dec 2026)" in octo.reason


async def test_checks_sundry_duplicates_negative_balance_and_unusual(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    for i, d in enumerate((3, 4, 5)):
        await b.post_event(purchase(f"{i + 1:032x}", 5000, date(2026, 7, d), "Howdens"))
    await b.post_event(purchase("d" * 32, 90000, date(2026, 10, 8), "Howdens"))  # 18x the usual
    await b.post_event(purchase("e" * 32, 1200, date(2026, 10, 9), "Screwfix"))
    await b.post_event(purchase("f" * 32, 1200, date(2026, 10, 9), "Screwfix"))  # entered twice
    await b.post_event(purchase("9" * 32, 600, date(2026, 10, 10), "Corner shop", account="7999 Sundry expenses"))
    await b.write_json(f"{BANK_LINES}/{'6' * 64}.json", [line(1, date(2026, 10, 20), -5000, -2500)])
    step = await month_end.step_checks(ctx(b))
    by = {f.text.split(" ")[0]: f for f in step.found}
    assert by["£5.00"].level == "blocking" and "7999 Sundry expenses" in by["£5.00"].text
    dup = next(f for f in step.found if f.text.startswith("Possible duplicate"))
    assert dup.level == "blocking" and sorted(dup.refs["events"]) == ["e" * 32, "f" * 32]
    assert any("below zero" in f.text and "-£25.00 on 20 Oct" in f.text for f in step.found)
    assert any(f.text.startswith("Howdens £900.00 on 8 Oct is more than 3 times the usual £50.00") for f in step.found)


async def test_inbox_counts_files_and_month_dated_proposals(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    fake.files[f"{INBOX}/receipt.jpg"] = b"x"
    step = await month_end.step_inbox(ctx(b))
    assert step.blocking == 1 and "1 document in 00 Inbox not read yet" in step.reason
    assert any(f.level == "note" and "Outlook intake is off" in f.text for f in step.found)


# --------------------------------------------------------------------------- #
# The whole run, the close and after
# --------------------------------------------------------------------------- #


async def test_a_blocked_run_writes_only_its_record_and_offers_no_close(fake: FakeStorageProvider) -> None:
    b = Books(fake)
    await b.post_event(purchase("a" * 32, 12000, date(2026, 10, 14), "Screwfix"))
    before = {k for k in fake.files if k.startswith(EVENTS)}
    result = await month_end.run_to_end(ctx(b))
    assert [s.id for s in result.steps] == [i for i, _ in month_end.STEPS]
    assert result.blocking >= 1 and not result.can_close
    assert result.steps[7].status == "blocked" and result.steps[8].status == "blocked"
    assert not any(a.kind == "close_month" for a in result.actions)
    assert {k for k in fake.files if k.startswith(EVENTS)} == before  # nothing posted
    assert not any(k.startswith(REPORTS) for k in fake.files)  # no report while something blocks
    record = json.loads(fake.files[month_end.record_path(OCT)])
    assert len(record["runs"]) == 1 and record["closes"] == []
    assert "actions" not in record["runs"][0]  # the signed cards stay with the app
    audit = fake.files[f"_System/audit/{datetime.now(UTC):%Y-%m}.jsonl"].decode()
    assert '"close_run"' in audit and '"agent:close"' in audit
    assert result.summary_model == "code"
    assert result.summary_md.startswith("October 2026: 1 thing needs you before the month can be closed.")


async def test_close_record_change_detection_and_reclose(clean: Books, fake: FakeStorageProvider) -> None:
    first = await month_end.run_to_end(ctx(clean))
    assert first.blocking == 0 and first.can_close, [s.reason for s in first.steps if s.status != "ok"]
    assert first.steps[7].data["path"] == f"{REPORTS}/2026-10-month-end-draft.xlsx"
    card = next(a for a in first.actions if a.kind == "close_month")
    assert card.preview["figures"]["net_profit_pence"] == -10000
    act = actions.Context(books=clean, user=USER, graph_token=TOKEN)
    done = await actions.approve(card, act)
    assert done.result["report_path"] == f"{REPORTS}/2026-10-month-end.xlsx" and not done.result["reclose"]
    status = await month_end.month_status(clean, OCT, TODAY)
    assert (
        status.closed
        and status.changes is None
        and status.headline == "October was closed on " + (f"{datetime.now(UTC).day} {datetime.now(UTC):%b}.")
    )

    # A late receipt dated in October, approved after the close.
    await clean.post_event(purchase("7" * 32, 2400, date(2026, 10, 20), "Wickes"))
    status = await month_end.month_status(clean, OCT, TODAY)
    assert not status.closed and status.changes is not None and status.changes.count == 1
    assert status.changes.items[0].startswith("A purchase from Wickes for £24.00 dated 20 Oct was approved on 20 Oct")
    moved = {f.label: (f.before, f.after) for f in status.changes.figures}
    assert moved["Net profit"] == ("-£100.00", "-£120.00")
    assert moved["VAT box 4 (this month's entries)"] == ("£20.00", "£24.00")
    assert status.headline.startswith("October was closed on") and status.headline.endswith("re-close?")
    overview = await month_end.overview(clean, TODAY)
    assert overview.target.month == OCT and overview.target.changes is not None

    # Re-run: a re-close card; approving it records a second close with what changed.
    second = await month_end.run_to_end(ctx(clean))
    recard = next(a for a in second.actions if a.kind == "close_month")
    assert recard.preview["reclose"] and recard.preview["changes"]
    again = await actions.approve(recard, act)
    assert again.result["reclose"] and again.result["report_path"] == f"{REPORTS}/2026-10-month-end (2).xlsx"
    record = await month_end.load_record(clean, OCT)
    assert len(record.closes) == 2 and record.closes[1].changes_since_previous == status.changes.items
    assert (await month_end.month_status(clean, OCT, TODAY)).closed


async def test_close_refused_when_figures_changed_after_the_run(clean: Books) -> None:
    run = await month_end.run_to_end(ctx(clean))
    card = next(a for a in run.actions if a.kind == "close_month")
    undone = await clean.get_event("a" * 32)
    await clean.post_event(reversal_of(undone, USER))  # an undo dated in October
    with pytest.raises(actions.ActionError) as exc:
        await actions.approve(card, actions.Context(books=clean, user=USER, graph_token=TOKEN))
    assert exc.value.status == 409 and "changed after this check ran" in str(exc.value)
    assert (await month_end.load_record(clean, OCT)).closes == []


async def test_a_month_not_ended_cannot_be_closed(clean: Books) -> None:
    run = await month_end.run_to_end(ctx(clean, today=date(2026, 10, 20)))
    assert run.steps[8].status == "blocked" and "has not ended yet" in run.steps[8].reason
    with pytest.raises(month_end.CloseError):
        month_end.check_month("2026-12", date(2026, 10, 20))


async def test_a_failing_step_is_reported_not_skipped(clean: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(_ctx: month_end.Ctx) -> month_end.Step:
        raise RuntimeError("payroll file unreadable")

    monkeypatch.setitem(month_end.STEP_FNS, "payroll", broken)
    run = await month_end.run_to_end(ctx(clean))
    step = run.steps[4]
    assert step.status == "blocked" and "payroll file unreadable" in step.reason and not run.can_close


# --------------------------------------------------------------------------- #
# The summary: Ask's number check
# --------------------------------------------------------------------------- #


FACTS = {
    "month": "October 2026",
    "needs_you": 3,
    "blocking": 2,
    "can_close": False,
    "closed": False,
    "steps": [{"title": "Bank", "status": "needs_you", "reason": "Bank statement missing for 12–31 Oct (starling)."}],
    "figures": {"sales": "£600.00", "net_profit": "£480.00"},
}


def test_summary_ground_rejects_invented_figures_and_false_ready() -> None:
    ok = "October 2026: 3 things need you, 2 block the close. Bank statement missing for 12–31 Oct."
    assert close_summary.ground(ok, FACTS) is None
    assert "not in the checklist" in (close_summary.ground("Net profit was £512.40.", FACTS) or "")
    assert "ready to close" in (close_summary.ground("October is ready to close.", FACTS) or "")
    assert close_summary.ground("See https://x.example", FACTS) == "The model's summary contained a link."


async def test_summary_falls_back_to_code_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai import close_summary as cs

    async def invents(*_a: Any, **_k: Any) -> str:
        return json.dumps({"summary_md": "You made £9,999.99 in October."})

    monkeypatch.setattr(cs, "call_json_model", invents)
    got = await cs.summarise(FACTS, AiConfig(mode="local", base_url="http://ollama.invalid", model="stub"))
    assert got.fallback_reason and "9,999.99" in got.fallback_reason
    assert got.summary_md.startswith("October 2026: 3 things need you, 2 of them before the month can be closed.")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(clean: Books):
    from app.main import app
    from app.routes_books import get_books

    async def over():
        yield clean

    app.dependency_overrides[get_books] = over
    yield TestClient(app)
    app.dependency_overrides.clear()


H = {"X-Graph-Token": TOKEN, "X-User": USER}


def test_routes_stream_each_step_then_the_run(client: TestClient) -> None:
    r = client.post(f"/close/{OCT}/run?stream=1&today={TODAY}", json={}, headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = [blk.split("\n")[0].removeprefix("event: ") for blk in r.text.strip().split("\n\n")]
    assert events == ["start", *["step"] * 9, "summary", "run"]
    run = json.loads(r.text.strip().split("\n\n")[-1].split("data: ", 1)[1])
    assert run["can_close"] and any(a["kind"] == "close_month" for a in run["actions"])
    card = next(a for a in run["actions"] if a["kind"] == "close_month")
    assert client.post("/actions/approve", json={"action": card}, headers=H).status_code == 200
    detail = client.get(f"/close/{OCT}?today={TODAY}", headers=H).json()
    assert detail["closed"] and detail["run"]["id"] == run["id"] and len(detail["closes"]) == 1
    home = client.get(f"/close?today={TODAY}", headers=H).json()
    assert home["target"]["month"] == OCT and home["target"]["closed"]


def test_routes_refuse_bad_months_and_need_a_user(client: TestClient) -> None:
    assert client.post("/close/2026-13/run", headers=H).status_code == 422
    assert client.post(f"/close/2027-01/run?today={TODAY}", headers=H).status_code == 422
    assert client.post(f"/close/{OCT}/run", headers={"X-Graph-Token": TOKEN}).status_code == 400
