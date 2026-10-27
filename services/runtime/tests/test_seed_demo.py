"""tools/seed_demo.py: the plan (counts, balance, date spread) and a full run against the fake OneDrive.

The Graph run needs a token for a throwaway account: ACCNOMOS_SEED_GRAPH_TOKEN alone only reads the folder;
with ACCNOMOS_SEED_GRAPH_WRITE=1 as well it seeds that account for real.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
from openpyxl import load_workbook

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.bank import detect_bank, parse_bank_csv, reconciled_to
from accnomos_ledger.vat import compute_vat_return
from app import autopilot, bank_rules, credit_notes, invoicing, jobs, mileage, payments, payroll, todos
from app import contacts as contacts_mod
from app.books import INBOX, NEEDS_A_LOOK, Books
from app.checks import decide, run_checks
from app.deadlines import period_containing
from app.journal import is_balanced

TOOL = Path(__file__).resolve().parents[3] / "tools" / "seed_demo.py"
TODAY = date(2026, 10, 27)


@pytest.fixture(scope="module")
def seed_demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_demo", TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = mod  # dataclasses look their module up by name
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plan(seed_demo: ModuleType):  # noqa: ANN201
    return seed_demo.build_plan("Bramblewood Joinery Ltd", TODAY)


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #


def test_counts(plan) -> None:  # noqa: ANN001
    assert (plan.event_count, plan.approved_count, plan.coded_count) == (59, 45, 14)
    assert (len(plan.posted), len(plan.supplier_docs), len(plan.invoices), bool(plan.claim_journeys())) == (
        36,
        2,
        6,
        True,
    )
    assert len(plan.inbox) == 25
    assert [d.gold for d in plan.inbox if d.expect == "needs_a_look"] == ["057_mixed.json", "010_foreign.json"]
    kinds = {d.extracted["doc_type"] for d in plan.inbox}
    assert "sales_invoice" in kinds and kinds - {"sales_invoice"}
    assert len(plan.jobs) == 2 and {t.job_id for t in plan.timesheets} == {j.id for j in plan.jobs.values()}
    assert {d.job for d in plan.posted if d.job} == {"job1", "job2"}  # materials bought for each job
    assert len(plan.statements) == 2
    assert [(i.number, i.customer, i.state(plan.today)) for i in plan.invoices] == [
        ("INV-0001", "Halloway & Sons Interiors", "paid"),
        ("INV-0002", "Sterling & Co. Architects", "sent and OVERDUE"),
        ("INV-0003", "Thornfield Interiors Ltd", "overpaid"),
        ("INV-0004", "Harlow & Finch Interiors Ltd", "paid"),
        ("INV-0005", "Oak & Ash Interiors Ltd", "part paid and OVERDUE"),
        ("INV-0006", "Hartwell Property Maintenance", "sent (not due yet)"),
    ]
    # Autopilot posts the second bill of each energy supplier; the first was approved with "Always do this".
    assert sum(d.by == "autopilot" for d in plan.posted) == sum(d.always for d in plan.posted) == 6
    assert sum(d.via == "mail" for d in plan.posted) == 2
    assert [b.doc().doc_type for b in plan.supplier_docs] == ["purchase_invoice", "credit_note"]
    assert len(plan.bank_rules) == 2 and len(plan.rule_rows) == 6 and len(plan.todos) == 2
    assert plan.payroll_period == "2026-09" and plan.export_report


def test_figures_come_from_the_ledger2_gold(plan) -> None:  # noqa: ANN001
    """Part payments, the overpayment, the exact match and the supplier credit note are the gold's own figures."""
    gold = {i.gold: i for i in plan.invoices if i.gold}
    assert sorted(gold) == ["002_exact.json", "003_part_open.json", "004_over.json"]
    assert [(gold[f].total_pence, gold[f].paid_pence) for f in sorted(gold)] == [
        (300_000, 300_000),
        (120_000, 60_000),
        (159_600, 163_700),
    ]
    assert gold["002_exact.json"].payments[0].how == "exact"
    assert gold["004_over.json"].payments[0].reference == "THORNFIELD/INV-0003"  # the gold's number replaced
    bill, cn = (d.doc() for d in plan.supplier_docs)
    assert (cn.gross_total, cn.vat_total, cn.original_invoice_number) == (-996.0, -91.0, bill.invoice_number)
    assert (bill.gross_total, bill.vat_total) == (1992.0, 182.0)  # the credit note's lines at twice the quantity
    assert plan.bill_payment is not None and plan.bill_payment.pence == -99_600  # what is left after the credit
    (credit,) = plan.credit_notes
    assert credit.invoice == "INV-0006" and sum(credit.pence(plan.invoice("INV-0006"))) == 31_800


def test_without_extras_the_first_forty(seed_demo: ModuleType) -> None:
    """build_plan(extras=False): the books the stored eval reports were run on."""
    plan = seed_demo.build_plan("Bramblewood Joinery Ltd", TODAY, extras=False)
    assert (plan.approved_count, plan.coded_count) == (40, 1)  # 1: INV-0001's payment
    assert [i.number for i in plan.invoices] == ["INV-0001", "INV-0002", "INV-0003"]
    assert not (plan.supplier_docs or plan.bank_rules or plan.todos or plan.export_report)
    assert not any(d.by == "autopilot" or d.via == "mail" for d in plan.posted)


def test_every_journal_balances(plan) -> None:  # noqa: ANN001
    for d in plan.posted + plan.inbox + plan.supplier_docs:
        journal = d.journal()
        assert is_balanced(journal), d.gold
        gross = abs(round(d.doc().gross_total * 100))
        assert sum(j.debit_pence for j in journal) == gross or d.doc().currency != "GBP"
    for inv in plan.invoices:
        _, summary, net, vat = invoicing.price_lines(inv.lines)
        assert inv.total_pence == net + vat == sum(r.net_pence + r.vat_pence for r in summary) > 0


def test_dates_spread_over_the_last_two_periods(plan) -> None:  # noqa: ANN001
    (q1_start, q1_end), (q2_start, q2_end) = plan.periods
    assert (q1_start, q1_end, q2_start, q2_end) == (
        date(2026, 4, 1),
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 9, 30),
    )
    dated = [(d.date, d.extracted["doc_type"]) for d in plan.posted + plan.supplier_docs] + [
        (i.issue, "sales_invoice") for i in plan.invoices
    ]
    dated.append((plan.claim_day, "purchase_invoice"))
    dated += [(c.day, "credit_note") for c in plan.credit_notes]
    dated += [(p.day, "payment") for i in plan.invoices for p in i.payments]
    dated += [(r[0], "rule") for r in plan.rule_rows]
    assert plan.bill_payment is not None
    dated.append((plan.bill_payment.day, "payment"))
    assert all(q1_start <= day <= q2_end for day, _ in dated)
    for lo, hi in plan.periods:
        mine = [kind for day, kind in dated if lo <= day <= hi]
        assert len(mine) >= 15
        assert "sales_invoice" in mine and len(set(mine)) > 1
        assert len({day.month for day, _ in dated if lo <= day <= hi}) == 3  # every month has entries
    assert all(plan.current[0] <= d.date <= plan.today for d in plan.inbox)
    assert all(q1_start <= t.date <= q2_end for t in plan.timesheets)
    assert all(q1_start <= j.date <= q2_end for j in plan.journeys)


@pytest.mark.parametrize("today", [date(2026, 1, 1), date(2026, 3, 31), date(2026, 12, 31), date(2027, 5, 15)])
@pytest.mark.parametrize("stagger", [1, 2, 3])
def test_other_days_and_staggers(seed_demo: ModuleType, today: date, stagger: int) -> None:
    plan = seed_demo.build_plan("Bramblewood Joinery Ltd", today, stagger)
    assert plan.event_count == 59 and len(plan.inbox) == 25
    assert plan.current == period_containing(today, stagger)
    assert plan.periods[1][1] < plan.current[0]
    states = sorted(i.state(today) for i in plan.invoices)
    assert states == ["overpaid", "paid", "paid", "part paid and OVERDUE", "sent (not due yet)", "sent and OVERDUE"]
    every_day = [p.day for i in plan.invoices for p in i.payments] + [c.day for c in plan.credit_notes]
    assert all(plan.periods[0][0] <= d <= plan.periods[1][1] for d in every_day)
    assert all(t.due and t.due > today for t in plan.todos)


def test_deterministic(seed_demo: ModuleType, plan) -> None:  # noqa: ANN001
    again = seed_demo.build_plan("Bramblewood Joinery Ltd", TODAY)
    assert seed_demo.describe(again) == seed_demo.describe(plan)
    assert again.statements == plan.statements


def test_everything_is_labelled(seed_demo: ModuleType, plan) -> None:  # noqa: ANN001
    for d in plan.posted + plan.inbox + plan.supplier_docs:
        assert d.text.endswith(seed_demo.LABEL)
        assert d.date.isoformat() in d.text or f"{d.date:%d/%m/%Y}" in d.text  # re-dated, not just in the fields
    for name, data in plan.statements:
        assert name.startswith("SAMPLE") and seed_demo.LABEL in data.decode()
        assert detect_bank(data) == "starling"
        assert parse_bank_csv(data, name)


def test_another_business_name(seed_demo: ModuleType) -> None:
    plan = seed_demo.build_plan("Hazelmere Carpentry Ltd", TODAY)
    sales = [d for d in plan.posted if d.extracted["doc_type"] == "sales_invoice"]
    assert len(sales) == 4 and all(d.extracted["supplier_name"] == "Hazelmere Carpentry Ltd" for d in sales)
    assert all("HAZELMERE" in d.text or "Hazelmere" in d.text for d in sales)


def test_refuses_another_apps_folder(seed_demo: ModuleType) -> None:
    assert seed_demo.root_is_accnomos("personal", "Accnomos")
    assert not seed_demo.root_is_accnomos("personal", "Graph Explorer")
    assert seed_demo.root_is_accnomos("work", "Accnomos")


async def test_wipe_asks_first(seed_demo: ModuleType) -> None:
    class Storage(FakeStorageProvider):
        _root_drive_path = "/Apps/Accnomos"
        _folders: dict = {}

        async def _request(self, method: str, url: str) -> None:
            raise AssertionError("deleted without a yes")

    storage = Storage()
    await storage.write("00 Inbox/a.png", b"x")
    assert await seed_demo._wipe(storage, ask=lambda _q: "") is False
    assert await seed_demo._wipe(storage, ask=lambda _q: "n") is False
    assert "00 Inbox/a.png" in storage.files


async def test_wipe_on_yes_deletes_only_inside_the_folder(seed_demo: ModuleType) -> None:
    deleted: list[str] = []

    class Storage(FakeStorageProvider):
        _root_drive_path = "/Apps/Accnomos"

        def __init__(self) -> None:
            super().__init__()
            self._folders = {"00 Inbox": {}}

        async def _request(self, method: str, url: str) -> None:
            assert method == "DELETE" and "/me/drive/items/" in url
            deleted.append(url.rsplit("/", 1)[-1])

    storage = Storage()
    await storage.write("00 Inbox/a.png", b"x")
    await storage.write("README.txt", b"x")
    top = {i.id for i in await storage.list("")}
    assert await seed_demo._wipe(storage, ask=lambda _q: "Y ") is True
    assert set(deleted) == top and storage._folders == {}


def test_no_token_changes_nothing(
    seed_demo: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ACCNOMOS_GRAPH_TOKEN", "   ")
    monkeypatch.setattr(seed_demo.getpass, "getpass", lambda _p: "")
    assert seed_demo.main([]) == 1
    assert "nothing changed" in capsys.readouterr().err


def test_expired_token_is_explained(
    seed_demo: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from accnomos_connectors.msgraph import GraphError

    async def refused(*_a: object) -> int:
        raise GraphError(401, "InvalidAuthenticationToken")

    monkeypatch.setenv("ACCNOMOS_GRAPH_TOKEN", "eyJexpired")
    monkeypatch.setattr(seed_demo, "_seed_graph", refused)
    assert seed_demo.main([]) == 1
    err = capsys.readouterr().err
    assert "HTTP 401" in err and "expired" in err and "eyJexpired" not in err


def test_dry_run_prints_the_plan(seed_demo: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert seed_demo.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "59 ledger events: 45 approved entries and 14 posted by code" in out
    assert "OVERDUE" in out and "Needs a look" in out and "[Autopilot]" in out and "[emailed in]" in out
    assert "CN-0001 against INV-0006" in out and "paid from Contacts" in out and "07 Reports" in out


# --------------------------------------------------------------------------- #
# A full run on the fake OneDrive (seeded once for the module)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def seeded(seed_demo: ModuleType) -> tuple:
    plan = seed_demo.build_plan("Bramblewood Joinery Ltd", TODAY)  # in the past from now on: journeys can't be future
    fake = FakeStorageProvider()
    report = asyncio.run(seed_demo.seed(fake, plan, say=lambda _msg: None))
    return plan, fake, report


def _audit(fake: FakeStorageProvider) -> list[dict]:
    return [
        json.loads(line)
        for path, data in sorted(fake.files.items())
        if path.startswith("_System/audit/") and path.count("/") == 2  # the main log, not audit/autopilot/
        for line in data.decode().splitlines()
    ]


async def test_ledger(seed_demo: ModuleType, seeded: tuple) -> None:
    plan, fake, report = seeded
    books = Books(fake)
    events = await books.list_events()
    assert report["events"] == len(events) == plan.event_count == 59
    assert all(sum(ln.debit for ln in e.lines) == sum(ln.credit for ln in e.lines) for e in events)
    assert all(plan.window[0] <= e.date <= plan.window[1] for e in events)
    kinds = Counter(e.kind for e in events)
    assert kinds["reversal"] == 2 and {"sale", "purchase", "bank"} <= set(kinds)  # the two credit notes
    by = Counter(e.approved_by for e in events)
    assert by == {seed_demo.USER: 53, autopilot.AUTOPILOT: 6}
    proposals = await books.list_proposals()
    assert sum(p.status == "posted" for p in proposals) == len(proposals) == 38 + 1 + 8  # docs, mileage, bank codings
    assert sum(p.job_id is not None for p in proposals) == sum(d.job is not None for d in plan.posted) >= 2
    assert len(await autopilot.load_rules(books)) == 6


async def test_vat_boxes_for_each_quarter(seeded: tuple) -> None:
    """The figures tools/seed_demo.md tells the judge to expect (run in Oct-Dec 2026, stagger 1)."""
    plan, fake, _ = seeded
    events = await Books(fake).list_events()
    boxes = [compute_vat_return(events, "X", lo, hi).to_hmrc(finalised=False) for lo, hi in plan.periods]
    keys = ("vatDueSales", "vatReclaimedCurrPeriod", "netVatDue", "totalValueSalesExVAT", "totalValuePurchasesExVAT")
    assert [tuple(b[k] for k in keys) for b in boxes] == [
        (1053.0, 452.5, 600.5, 5265, 4357),  # Apr-Jun: + the Oakfield bill (VAT £182), insurance and a fee
        (3857.63, 50.3, 3807.33, 19288, 1692),  # Jul-Sep: + 3 gold invoices, - CN-0001 and Oakfield's credit note
    ]
    current = compute_vat_return(events, "X", *plan.current).to_hmrc(finalised=False)
    assert current["vatDueSales"] == current["vatReclaimedCurrPeriod"] == 0  # the live demo's period is empty


async def test_invoices_payments_and_credit(seeded: tuple) -> None:
    _, fake, report = seeded
    books = Books(fake)
    invs = {i.number: i for i in await invoicing.list_invoices(books)}
    assert [(n, invs[n].status, invs[n].payment_status, invs[n].balance_pence) for n in sorted(invs)] == [
        ("INV-0001", "paid", "paid", 0),
        ("INV-0002", "sent", None, None),  # no payment yet: overdue
        ("INV-0003", "paid", "overpaid", 0),
        ("INV-0004", "paid", "paid", 0),  # the exact match on the Bank page, posted as a payment
        ("INV-0005", "sent", "part_paid", 60_000),
        ("INV-0006", "sent", "part_paid", 73_968),  # credited £318.00 by CN-0001
    ]
    assert [invs[n].total_pence for n in sorted(invs)] == [362_880, 222_000, 159_600, 300_000, 120_000, 105_768]
    assert [n for n in sorted(invs) if (invs[n].overdue_days(TODAY) or 0) > 0] == ["INV-0002", "INV-0005"]
    assert report["emails_not_sent"] == 6
    (cn,) = await credit_notes.list_credit_notes(books)
    assert (cn.number, cn.invoice, cn.total_pence, cn.issue_date) == ("CN-0001", "INV-0006", 31_800, date(2026, 9, 29))

    ledger = await contacts_mod.load_ledger(books)
    settled = ledger.settlement()
    credits = [(c.side, c.amount_pence, c.source) for c in settled.credits]
    assert credits == [("sale", 4_100, "payment")]  # Thornfield paid £1,637.00 on £1,596.00
    supplier_cn = next(
        e for e in ledger.events if e.kind == "reversal" and e.counterparty == "Oakfield Hardware Supplies"
    )
    assert supplier_cn.credits and settled.outstanding(supplier_cn.credits) == 0  # linked to its bill, then paid
    assert len(await payments._records(books)) == 5


async def test_aged_balances(seeded: tuple) -> None:
    _, fake, _ = seeded
    contacts, ledger, _ = await contacts_mod.contact_book(Books(fake))
    aged = contacts_mod.aged(contacts, ledger, TODAY)
    assert aged.debtors.total_pence == 1_794_978 and aged.creditors.total_pence == 0
    assert {k: v for k, v in aged.debtors.buckets.items() if v} == {
        "current": 73_968,
        "0-30": 995_220,
        "61-90": 725_790,
    }
    owed = {r.name: r.total_pence for r in aged.debtors.rows}
    assert owed["Oak & Ash Interiors Ltd"] == 60_000 and owed["Sterling & Co. Architects"] == 222_000 + 525_960
    assert (sum(c.kind == "customer" for c in contacts), sum(c.kind == "supplier" for c in contacts)) == (7, 16)


async def test_bank(seeded: tuple) -> None:
    plan, fake, report = seeded
    books = Books(fake)
    lines = await books.stored_bank_lines()
    assert len(await books.bank_statements()) == 2 and len(lines) == report["bank_lines"] == 48
    older = [ln for ln in lines if ln.date <= plan.periods[0][1]]
    assert all(ln.resolved for ln in older)  # Apr-Jun is reconciled: matched, coded by a rule, or a transfer
    assert report["reconciled_to"] == reconciled_to(lines) == date(2026, 7, 3)
    assert Counter(ln.status for ln in lines) == {"matched": 30, "unmatched": 16, "transfer": 2}
    assert len(await books.bank_suggestions()) == 16  # left for the judge to confirm
    rules = await bank_rules.load_bank_rules(books)
    coded = [
        ln for ln in lines if bank_rules.first_match(rules, description=ln.description, amount_pence=ln.amount_pence)
    ]
    assert len(coded) == 8 and all(ln.status == "matched" for ln in coded)
    accounts = {
        ln.account for ln in coded for e in [await books.get_event(ln.matched_event_id or "")] for ln in e.lines
    }
    assert {"7900 Bank charges", "7700 Insurance"} <= accounts


async def test_audit_has_user_autopilot_and_intake(seeded: tuple) -> None:
    _, fake, _ = seeded
    lines = _audit(fake)
    actors = Counter(line["actor"] for line in lines)
    assert {"user:demo-seed", "agent:autopilot", "agent:intake"} <= set(actors)
    assert sum(1 for x in lines if x["actor"] == "agent:autopilot" and x["action"] == "approved") == 6
    scanned = [x for x in lines if x["actor"] == "agent:intake" and x["action"] == "mail_scanned"]
    assert len(scanned) == 1 and scanned[0]["refs"]["saved"] == 2
    done = {x["action"] for x in lines}
    assert {"payment_recorded", "credit_note_posted", "bank_reconciled", "bank_transfer", "payroll_prepared"} <= done
    assert {"todo_added", "report_exported", "invoice_part_paid"} <= done


async def test_files_jobs_payroll_todos_reports(seed_demo: ModuleType, seeded: tuple) -> None:
    plan, fake, _ = seeded
    books = Books(fake)
    inbox = await books.list_files(INBOX)
    assert sorted(f.name for f in inbox) == sorted(d.file_name for d in plan.inbox)  # what the judge scans
    assert not await books.list_files(NEEDS_A_LOOK)
    stored = await contacts_mod.stored_contacts(books)  # what the judge's scan looks suppliers up in
    for d in plan.inbox:  # 23 proposals and 2 Needs a look, 049 included (Hargreaves & Son Hardware is known now)
        doc = d.doc()
        checks = run_checks(
            doc, known_hashes=set(), this_hash="x", supplier=contacts_mod.supplier_knowledge(stored, doc)
        )
        assert decide(checks)[0] == d.expect, d.gold
    assert (len(plan.journeys), round(sum(j.miles for j in plan.journeys), 1)) == (13, 181.7)
    assert len(await jobs.load_jobs(books)) == 2 and all(j.customer_id for j in await jobs.load_jobs(books))
    assert sum(e.invoiced_in == "INV-0001" for e in await jobs.load_entries(books)) == 12
    assert len(await mileage.load_vehicles(books)) == 1
    run = await payroll.get_run(books, "2026-09")
    assert run.status == "draft" and len(run.lines) == 2 and run.est_gross_pence > 0
    assert [t.text for t in await todos.list_todos(books)] == [t.text for t in plan.todos]

    assert "README.txt" in fake.files and "Books.xlsx" in fake.files
    wb = load_workbook(io.BytesIO(fake.files["Books.xlsx"]))
    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows(min_row=2)}
    assert summary["Entries posted"] == 59 and summary["Proposals waiting"] == 0
    (report,) = [p for p in fake.files if p.startswith("07 Reports/")]
    assert report == "07 Reports/2026-10-27-reports.xlsx"
    sheets = load_workbook(io.BytesIO(fake.files[report]))
    assert sheets.sheetnames == ["About", "P&L", "Debtors", "Creditors", "VAT summary", "Trend"]
    assert sheets["About"]["A1"].value == seed_demo.LABEL


async def test_a_second_run_changes_nothing(seed_demo: ModuleType, seeded: tuple) -> None:
    plan, fake, _ = seeded
    before = dict(fake.files)
    again = await seed_demo.seed(fake, plan, say=lambda _msg: None)
    assert again["already_seeded"] and again["events"] == 59
    assert fake.files == before


async def test_part_seeded_or_foreign_books_are_refused(seed_demo: ModuleType, seeded: tuple) -> None:
    plan, fake, _ = seeded
    part = FakeStorageProvider()
    part.files = {p: b for p, b in fake.files.items() if not p.startswith("07 Reports/")}
    part.folders = set(fake.folders)
    assert await seed_demo.seed_state(Books(part)) == "partial"
    with pytest.raises(RuntimeError, match="part-way"):
        await seed_demo.seed(part, plan, say=lambda _msg: None)
    foreign = FakeStorageProvider()
    ev = (await Books(fake).list_events())[0].model_copy(update={"approved_by": "someone@example.com", "id": "f" * 32})
    await Books(foreign).post_event(ev)
    assert await seed_demo.seed_state(Books(foreign)) == "foreign"
    with pytest.raises(RuntimeError, match="did not make"):
        await seed_demo.seed(foreign, plan, say=lambda _msg: None)
    assert await seed_demo.seed_state(Books(FakeStorageProvider())) == "empty"


# --------------------------------------------------------------------------- #
# Microsoft Graph, only with a token for a throwaway account
# --------------------------------------------------------------------------- #

GRAPH_TOKEN = os.getenv("ACCNOMOS_SEED_GRAPH_TOKEN")


@pytest.mark.skipif(not GRAPH_TOKEN, reason="set ACCNOMOS_SEED_GRAPH_TOKEN (throwaway account) to run against Graph")
async def test_graph(seed_demo: ModuleType) -> None:
    from accnomos_connectors.msgraph import GraphStorageProvider

    kind = os.getenv("ACCNOMOS_SEED_GRAPH_ACCOUNT", "personal")
    async with GraphStorageProvider(GRAPH_TOKEN or "", kind) as storage:  # type: ignore[arg-type]
        await storage.ensure_root()
        await storage.list("")
        if os.getenv("ACCNOMOS_SEED_GRAPH_WRITE") != "1":
            return
        books = Books(storage)
        if await books.list_events():
            pytest.skip("the account already has books; wipe it with tools/seed_demo.py --wipe first")
        plan = seed_demo.build_plan("Bramblewood Joinery Ltd", date.today())
        report = await seed_demo.seed(storage, plan, say=print)
        assert report["events"] == plan.event_count and report["inbox"] == 25
