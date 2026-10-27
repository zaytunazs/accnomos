#!/usr/bin/env python3
"""Fill a throwaway OneDrive with the fictional company's books, for a judge to click through.

    python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --dry-run    # print the plan, touch nothing
    python tools/seed_demo.py --business "Bramblewood Joinery Ltd"              # asks for a Graph token
    python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --wipe       # empty the Accnomos folder first (y/N)

Run with the runtime's venv. The token is read from ACCNOMOS_GRAPH_TOKEN or a hidden prompt, never from the
command line, and is kept in memory only. Walkthrough and how to get a token: tools/seed_demo.md.

Two halves. `build_plan` is pure and deterministic (same business, day and stagger give the same plan): it picks
gold documents from evals/gold, re-dates them, labels each "SAMPLE — FICTIONAL COMPANY" and lays out jobs,
timesheets, mileage, invoices and two bank statements. `seed` then applies it through the functions the app's own
routes call (approve(), invoicing, jobs, mileage, contacts, Books.import_bank_csv...), so every file is written
by app code; nothing here writes JSON by hand. What it posts:

* 40 approved ledger events, all inside the last two complete VAT periods: 36 documents approved in Review, one
  mileage allowance claim and three sales invoices.
* 25 more documents left in "00 Inbox", dated in the current period, for the judge to scan; two of them will land
  in "Needs a look" (an EUR invoice and a malformed VAT number).

The documents are read by nobody: their proposals carry the gold set's fields (model "seed:gold-reading"),
the same "perfect reading" test mode uses. Code still runs every check and drafts every journal.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import hashlib
import io
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# This checkout's code, whatever the venv's editable installs point at.
for _p in ("packages/connectors/src", "packages/ledger/src", "services/runtime"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from accnomos_connectors.base import MailSender, OutgoingMail, StorageProvider  # noqa: E402

from app import contacts as contacts_mod  # noqa: E402
from app import invoicing, jobs, mileage  # noqa: E402
from app.approve import approve  # noqa: E402
from app.autopilot import supplier_key  # noqa: E402
from app.books import Books, DocMeta, now  # noqa: E402
from app.checks import decide, run_checks  # noqa: E402
from app.deadlines import STAGGER_START_MONTH, add_months, period_containing, period_label, previous_period  # noqa: E402
from app.journal import BANK, VAT_CONTROL, draft_journal  # noqa: E402
from app.paths import INBOX, readme_text  # noqa: E402
from app.pdf import render_invoice  # noqa: E402
from app.pipeline import sha256_hex, suggested_filename  # noqa: E402
from app.repair import repair  # noqa: E402
from app.schemas import ExtractedDoc, JournalLine, Proposal  # noqa: E402
from app.testmode import _renderer, extracted_from_gold, gold_receipts  # noqa: E402

LABEL = "SAMPLE — FICTIONAL COMPANY"
GOLD_BUSINESS = "Bramblewood Joinery Ltd"  # the seller on the gold sales invoices
USER = "demo-seed"
ACTOR = "agent:demo-seed"
MODEL = "seed:gold-reading"
EVENTS = 40
INBOX_DOCS = 25
INBOX_NEEDS_A_LOOK = ("057_mixed.json", "010_foreign.json")  # malformed VAT number; EUR, needs converting
INBOX_SALE = "052_sales_invoice.json"
OPENING_BALANCE_PENCE = 600_000


# --------------------------------------------------------------------------- #
# The plan (pure)
# --------------------------------------------------------------------------- #


@dataclass
class PlannedDoc:
    gold: str  # evals/gold/receipts file
    date: date
    text: str  # printed text: re-dated, labelled
    extracted: dict[str, Any]  # what a perfect reading returns, after the scan's repairs
    file_name: str
    job: str | None = None  # "job1" / "job2": tagged on approval
    expect: str = "proposed"

    def doc(self) -> ExtractedDoc:
        return ExtractedDoc.model_validate(self.extracted)

    def journal(self) -> list[JournalLine]:
        return draft_journal(self.doc())


@dataclass
class PlannedInvoice:
    number: str  # INV-0001...: the sequence of a fresh folder
    customer: str
    issue: date
    due: date
    lines: list[invoicing.LineIn]
    paid_on: date | None = None
    job: str | None = None  # bills that job's timesheet hours

    @property
    def total_pence(self) -> int:
        _, _, net, vat = invoicing.price_lines(self.lines)
        return net + vat


@dataclass
class Plan:
    business: str
    today: date
    periods: list[tuple[date, date]]  # the last two complete VAT periods, oldest first
    current: tuple[date, date]
    posted: list[PlannedDoc]
    inbox: list[PlannedDoc]
    staff: list[jobs.StaffMember]
    jobs: dict[str, jobs.Job]
    timesheets: list[jobs.TimesheetEntry]
    vehicle: mileage.Vehicle
    journeys: list[mileage.MileageEntry]
    claim_day: date  # the mileage claim is dated (and covers journeys up to) this day
    invoices: list[PlannedInvoice]
    customers: dict[str, dict[str, str]]  # name -> contact edits (email, address)
    job_customers: dict[str, str]  # job key -> customer name
    statements: list[tuple[str, bytes]] = field(default_factory=list)  # (upload name, CSV bytes)

    @property
    def window(self) -> tuple[date, date]:
        return self.periods[0][0], self.periods[-1][1]

    def claim_journeys(self) -> list[mileage.MileageEntry]:
        start, _ = mileage.quarter_bounds(mileage.tax_year_of(self.claim_day), mileage.quarter_of(self.claim_day))
        return [j for j in self.journeys if start <= j.date <= self.claim_day]

    @property
    def event_count(self) -> int:
        return len(self.posted) + len(self.invoices) + (1 if self.claim_journeys() else 0)


def _hex(*parts: object, n: int = 32) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:n]


def _slug(name: str) -> str:
    return supplier_key(name) or "business"


def _spread(start: date, end: date, n: int) -> list[date]:
    """`n` days spaced evenly over [start, end], each in the middle of its share."""
    days = (end - start).days + 1
    return [start + timedelta(days=(2 * i + 1) * days // (2 * n)) for i in range(n)]


def _uk(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def rewritable(gold: dict[str, Any]) -> bool:
    """The printed text shows the date as YYYY-MM-DD or DD/MM/YYYY, so it can be re-dated."""
    d = date.fromisoformat(gold["date"])
    return d.isoformat() in gold["printed_text"] or _uk(d) in gold["printed_text"]


def _planned(file: str, gold: dict[str, Any], when: date, business: str, n: int, suffix: str = "") -> PlannedDoc:
    old = date.fromisoformat(gold["date"])
    text = gold["printed_text"].replace(old.isoformat(), when.isoformat()).replace(_uk(old), _uk(when))
    raw = extracted_from_gold(gold) | {"date": when.isoformat()}
    if suffix and raw.get("invoice_number"):  # the same bill a quarter later
        text = text.replace(raw["invoice_number"], raw["invoice_number"] + suffix)
        raw["invoice_number"] += suffix
    if business != GOLD_BUSINESS:
        for old_name, new_name in ((GOLD_BUSINESS, business), (GOLD_BUSINESS.upper(), business.upper())):
            text = text.replace(old_name, new_name)
        for k in ("supplier_name", "customer_name"):
            if raw.get(k) == GOLD_BUSINESS:
                raw[k] = business
    doc = ExtractedDoc.model_validate(raw)
    repair(doc, business)  # as the scan does: the gold "full invoices" are sales from the supplier's side
    if doc.doc_type != "sales_invoice" and doc.category_guess == "Sales":
        doc.category_guess = "Materials"  # timber and ironmongery bought by a joiner
    name = f"SAMPLE {when.isoformat()} {n:02d}.png"
    return PlannedDoc(gold=file, date=when, text=f"{text}\n\n{LABEL}", extracted=doc.model_dump(), file_name=name)


def build_plan(business: str = GOLD_BUSINESS, today: date | None = None, stagger: int = 1) -> Plan:
    """Everything the seed will write, decided up front. Raises ValueError when the gold set can't fill it."""
    today = today or date.today()
    current = period_containing(today, STAGGER_START_MONTH[stagger])
    newer = previous_period(current[0])
    older = previous_period(newer[0])
    start, end = older[0], newer[1]
    # The plan is tuned to the original hand-checked set (001-060); later generated documents (061+) are for the eval only.
    golds = {f: g for f, g in gold_receipts().items() if f[:3].isdigit() and int(f[:3]) <= 60}
    usable = {f: g for f, g in golds.items() if rewritable(g) and f not in INBOX_NEEDS_A_LOOK}
    usable = {f: g for f, g in usable.items() if _passes(g)}
    sales = sorted(f for f, g in usable.items() if g["doc_type"] == "sales_invoice" and f != INBOX_SALE
                   and (g.get("supplier") or {}).get("name") == GOLD_BUSINESS)
    utilities = sorted(f for f, g in usable.items() if g.get("payment_method") == "direct debit" and f not in sales)
    rest = sorted(f for f in usable if f not in sales and f not in utilities and f != INBOX_SALE)
    n_posted_rest = EVENTS - 1 - 3 - len(sales) - 2 * len(utilities)  # 1 mileage claim, 3 invoices
    if n_posted_rest < 0 or len(rest) - n_posted_rest != INBOX_DOCS - 1 - len(INBOX_NEEDS_A_LOOK):
        raise ValueError(f"the gold set gives {len(sales)} sales, {len(utilities)} utility bills and {len(rest)} others")

    posted: list[PlannedDoc] = []
    # Quarterly energy bills: each supplier once in each period, three months apart.
    for i, f in enumerate(utilities):
        first = add_months(start, i % 3) + timedelta(days=7 + i)
        posted.append(_planned(f, golds[f], first, business, len(posted) + 1))
        posted.append(_planned(f, golds[f], add_months(start, i % 3 + 3) + timedelta(days=7 + i), business,
                               len(posted) + 1, suffix="-2"))
    spread = sorted(sales + rest[:n_posted_rest])
    for f, when in zip(spread, _spread(start, end, len(spread)), strict=True):
        posted.append(_planned(f, golds[f], when, business, len(posted) + 1))
    posted.sort(key=lambda d: (d.date, d.gold))
    for job, (lo, hi) in (("job1", older), ("job2", newer)):  # two materials purchases per job, in its period
        materials = [d for d in posted if lo <= d.date <= hi and d.extracted["doc_type"] != "sales_invoice"
                     and d.extracted["category_guess"] in ("Materials", "Tools & small equipment")]
        for d in materials[:2]:
            d.job = job

    inbox_files = [*rest[n_posted_rest:], INBOX_SALE, *INBOX_NEEDS_A_LOOK]
    inbox = [
        _planned(f, golds[f], when, business, 50 + i)
        for i, (f, when) in enumerate(zip(inbox_files, _spread(current[0], today, len(inbox_files)), strict=True))
    ]
    for d in inbox:
        d.expect = "needs_a_look" if d.gold in INBOX_NEEDS_A_LOOK else "proposed"

    staff = [
        jobs.StaffMember(id=_hex(business, "staff", 1, n=12), name="Sam Ashdown", role="Joiner",
                         hourly_rate_pence=1850, charge_rate_pence=4200),
        jobs.StaffMember(id=_hex(business, "staff", 2, n=12), name="Priya Hale", role="Apprentice",
                         hourly_rate_pence=1100, charge_rate_pence=2800),
    ]
    customers = {
        "Halloway & Sons Interiors": {"email": "accounts@halloway-interiors.example", "address": "2 Station Road, Harrogate HG1 1AA"},
        "Hartwell Property Maintenance": {"email": "office@hartwell-pm.example", "address": "9 Canal Wharf, Leeds LS11 5AA"},
        "Sterling & Co. Architects": {"email": "studio@sterling-architects.example", "address": "41 Park Square, Leeds LS1 2NE"},
    }
    job_defs = {
        "job1": ("Kitchen fit-out, Harrogate", "Halloway & Sons Interiors", older, "closed"),
        "job2": ("Office partitions and doors", "Hartwell Property Maintenance", newer, "open"),
    }
    plan_jobs = {
        k: jobs.Job(id=_hex(business, "job", k, n=12), name=name, site_address=customers[cust]["address"], estimate_hours=8)
        for k, (name, cust, _, _) in job_defs.items()
    }
    timesheets: list[jobs.TimesheetEntry] = []
    journeys: list[mileage.MileageEntry] = []
    vehicle = mileage.Vehicle(id=_hex(business, "vehicle"), name="Director's car (own)", registration="SAMPLE",
                              kind="car", owned_by="personal")
    for k, (name, cust, (lo, hi), _) in job_defs.items():
        days = _spread(lo + timedelta(days=7), lo + timedelta(days=48) if k == "job1" else hi, 6)
        for n, day in enumerate(days):
            for s, hours in zip(staff, (7.5, 6.0 if n % 2 else 7.5), strict=True):
                timesheets.append(jobs.TimesheetEntry(id=_hex(business, "ts", k, n, s.id, n=12), staff_id=s.id,
                                                      job_id=plan_jobs[k].id, date=day, hours=hours, note=f"{name}: day {n + 1}"))
            journeys.append(mileage.MileageEntry(
                id=_hex(business, "trip", k, n), vehicle_id=vehicle.id, date=day, from_="Workshop, Leeds",
                to=customers[cust]["address"], miles=21.4 if k == "job1" else 6.8, purpose=f"{name} ({cust})",
                job_id=plan_jobs[k].id,
            ))
    journeys.append(mileage.MileageEntry(  # one late in the period, so every stagger's claim has a journey
        id=_hex(business, "trip", "supplier"), vehicle_id=vehicle.id, date=newer[1] - timedelta(days=2),
        from_="Workshop, Leeds", to="Timber merchant, Wakefield", miles=12.5, purpose="Collect oak boards for stock",
    ))

    job1_lines = jobs.invoice_lines(plan_jobs["job1"], timesheets, staff).lines
    inv1_issue = max(t.date for t in timesheets if t.job_id == plan_jobs["job1"].id) + timedelta(days=3)
    invoices = [
        PlannedInvoice("INV-0001", "Halloway & Sons Interiors", inv1_issue, inv1_issue + timedelta(days=30), [
            invoicing.LineIn(description=ln.description, quantity=Decimal(str(ln.qty)), unit="hours",
                             unit_price_pence=ln.unit_price_pence, vat_code="S") for ln in job1_lines
        ], paid_on=inv1_issue + timedelta(days=12), job="job1"),
        PlannedInvoice("INV-0002", "Sterling & Co. Architects", newer[0] + timedelta(days=20), newer[0] + timedelta(days=50), [
            invoicing.LineIn(description="Bespoke oak bookcase, 2.4 m, fitted", quantity=Decimal(1), unit="each",
                             unit_price_pence=185_000, vat_code="S"),
        ]),
        PlannedInvoice("INV-0003", "Hartwell Property Maintenance", newer[1] - timedelta(days=3), today + timedelta(days=21), [
            invoicing.LineIn(description="Sash window repairs, three windows", quantity=Decimal(3), unit="each",
                             unit_price_pence=26_500, vat_code="S"),
            invoicing.LineIn(description="Materials: draught strip and beads", quantity=Decimal(1), unit="each",
                             unit_price_pence=8_640, vat_code="S"),
        ]),
    ]
    plan = Plan(business=business, today=today, periods=[older, newer], current=current, posted=posted, inbox=inbox,
                staff=staff, jobs=plan_jobs, timesheets=timesheets, vehicle=vehicle, journeys=journeys,
                claim_day=newer[1], invoices=invoices, customers=customers,
                job_customers={k: cust for k, (_, cust, _, _) in job_defs.items()})
    plan.statements = [_statement(plan, lo, hi, n) for n, (lo, hi) in enumerate(plan.periods)]
    return plan


def _passes(gold: dict[str, Any]) -> bool:
    """Every check passes on a perfect reading (EUR and the malformed VAT number do not)."""
    doc = ExtractedDoc.model_validate(extracted_from_gold(gold))
    return gold.get("currency", "GBP") == "GBP" and decide(run_checks(doc, known_hashes=set(), this_hash=""))[0] == "proposed"


# --------------------------------------------------------------------------- #
# Bank statements (Starling layout, one per period): generated from the plan
# --------------------------------------------------------------------------- #

_TYPE = {"card": "CARD PAYMENT", "direct_debit": "DIRECT DEBIT", "bank_transfer": "FASTER PAYMENT", "cheque": "CHEQUE"}


def _bank_rows(plan: Plan) -> list[tuple[date, str, str, str, int]]:
    """(date, counter party, reference, type, signed pence) for every bank movement in the window."""
    rows: list[tuple[date, str, str, str, int]] = []
    for d in plan.posted:
        doc = d.doc()
        leg = next((j for j in d.journal() if j.account == BANK), None)
        if doc.doc_type == "sales_invoice":  # Dr Debtors: the customer pays ten days later
            rows.append((d.date + timedelta(days=10), doc.customer_name or "", doc.invoice_number or "", "FASTER PAYMENT",
                         round(doc.gross_total * 100)))
        elif leg is not None:
            ref = f"CARD {doc.card_last4}" if doc.card_last4 else (doc.invoice_number or "")
            lag = 1 if doc.payment_method == "card" else 0
            rows.append((d.date + timedelta(days=lag), doc.supplier_name, ref, _TYPE.get(doc.payment_method or "", "PAYMENT"),
                         leg.debit_pence - leg.credit_pence))
    for inv in plan.invoices:
        if inv.paid_on:
            rows.append((inv.paid_on, inv.customer, inv.number, "FASTER PAYMENT", inv.total_pence))
    for lo, _ in plan.periods:
        rows.append((add_months(lo, 1) + timedelta(days=19), "Savings Space", "Tax pot", "INTERNAL TRANSFER", -100_000))
        rows.append((add_months(lo, 3) - timedelta(days=1), "Starling Bank", "Account fee", "FEE", -500))
    return sorted(rows)


def _pounds(p: int) -> str:
    return f"{p / 100:,.2f}"


def _statement(plan: Plan, lo: date, hi: date, n: int) -> tuple[str, bytes]:
    rows = _bank_rows(plan)
    balance = OPENING_BALANCE_PENCE + sum(r[4] for r in rows if r[0] < lo)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([f"{LABEL}: {plan.business}, statement {n + 1}"])  # a preamble row; the reader skips it
    w.writerow(["Date", "Counter Party", "Reference", "Type", "Amount (GBP)", "Balance (GBP)", "Spending Category", "Notes"])
    for day, party, ref, kind, pence in rows:
        if lo <= day <= hi:
            balance += pence
            w.writerow([_uk(day), party, ref, kind, _pounds(pence), _pounds(balance), "INCOME" if pence > 0 else "GENERAL", LABEL])
    return f"SAMPLE statement {lo:%Y-%m} to {hi:%Y-%m}.csv", out.getvalue().encode()


# --------------------------------------------------------------------------- #
# Printing the plan
# --------------------------------------------------------------------------- #


def describe(plan: Plan) -> str:
    def money(p: int) -> str:
        return invoicing.money(p)

    lines = [
        f"{LABEL}: {plan.business}",
        f"Today {plan.today:%d/%m/%Y}; current VAT period {period_label(*plan.current)}; "
        f"seeded periods {' and '.join(period_label(*p) for p in plan.periods)}",
        "",
        f"{plan.event_count} approved ledger events:",
    ]
    for d in plan.posted:
        doc = d.doc()
        who = doc.customer_name if doc.doc_type == "sales_invoice" else doc.supplier_name
        tag = f"  [{plan.jobs[d.job].name}]" if d.job else ""
        lines.append(f"  {d.date:%d/%m/%Y}  {'sale    ' if doc.doc_type == 'sales_invoice' else 'purchase'}  "
                     f"{who[:34]:34} {money(round(doc.gross_total * 100)):>11}  VAT {money(round(doc.vat_total * 100)):>9}{tag}")
    claim = plan.claim_journeys()
    miles = sum(j.miles for j in claim)
    lines.append(f"  {plan.claim_day:%d/%m/%Y}  mileage   {len(claim)} journeys, {miles:.1f} miles (allowance worked out by code)")
    for inv in plan.invoices:
        state = f"paid {inv.paid_on:%d/%m/%Y}" if inv.paid_on else ("OVERDUE" if inv.due < plan.today else "not due yet")
        lines.append(f"  {inv.issue:%d/%m/%Y}  invoice   {inv.customer[:34]:34} {money(inv.total_pence):>11}  "
                     f"due {inv.due:%d/%m/%Y}, {state}")
    for lo, hi in plan.periods:
        sale_vat = sum(round(d.doc().vat_total * 100) for d in plan.posted
                       if lo <= d.date <= hi and d.doc().doc_type == "sales_invoice")
        sale_vat += sum(inv.total_pence - invoicing.price_lines(inv.lines)[2] for inv in plan.invoices if lo <= inv.issue <= hi)
        buy_vat = sum(j.debit_pence for d in plan.posted if lo <= d.date <= hi for j in d.journal()
                      if j.account == VAT_CONTROL and d.doc().doc_type != "sales_invoice")
        lines.append(f"  {period_label(lo, hi)}: VAT on sales {money(sale_vat)}, VAT reclaimed {money(buy_vat)}")
    lines += ["", f"{len(plan.inbox)} documents left in {INBOX} (dated {period_label(*plan.current)}):"]
    for d in plan.inbox:
        doc = d.doc()
        who = f"sale to {doc.customer_name}" if doc.doc_type == "sales_invoice" else doc.supplier_name
        lines.append(f"  {d.file_name}  {who[:34]:34} {doc.currency} {doc.gross_total:>9.2f}"
                     + ("  -> Needs a look" if d.expect == "needs_a_look" else ""))
    lines += [
        "",
        f"Staff: {', '.join(f'{s.name} ({s.role})' for s in plan.staff)}",
        f"Jobs: {', '.join(j.name for j in plan.jobs.values())}; {len(plan.timesheets)} timesheet entries",
        f"Vehicle: {plan.vehicle.label()}, {len(plan.journeys)} journeys",
        f"Bank statements: {', '.join(name for name, _ in plan.statements)}",
        "Then: contacts refreshed from the ledger, Books.xlsx rebuilt.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Applying the plan through the app's own functions
# --------------------------------------------------------------------------- #


class SeedBooks(Books):
    """Books whose per-action Books.xlsx rebuild waits for the end: one rebuild instead of a hundred."""

    async def rebuild_safely(self, actor: str) -> None:  # type: ignore[override]
        return None


class NotEmailed(MailSender):
    """The seed "sends" invoices to fictional customers: the app marks them sent and posts them; no email leaves."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []

    async def send(self, mail: OutgoingMail) -> None:
        self.sent.append(mail)


def render_png(text: str) -> bytes:
    return _renderer().render_receipt(text, messy=False, seed=0)


async def _upload(books: Books, d: PlannedDoc) -> tuple[str, bytes]:
    data = render_png(d.text)
    path = f"{INBOX}/{d.file_name}"
    await books.storage.write(path, data)
    return path, data


async def _propose(books: Books, d: PlannedDoc, plan: Plan) -> Proposal:
    """What scan_inbox_detailed does for one file, with the gold fields standing in for the model's reading."""
    path, data = await _upload(books, d)
    digest = sha256_hex(data)
    doc = d.doc()
    start, end = period_containing(d.date, plan.current[0].month)  # checked when it arrived, in its own period
    checks = repair(doc, plan.business) + run_checks(
        doc, known_hashes=await books.known_hashes(), this_hash=digest, period_start=start, period_end=end,
    )
    status, reasons = decide(checks)
    p = Proposal(
        id=_hex(plan.business, d.gold, d.date), doc_sha256=digest, extracted=doc, checks=checks, status=status,
        reasons=reasons, suggested_filename=suggested_filename(doc, "image/png"), journal_draft=draft_journal(doc),
        model=MODEL, elapsed_s=0, source_name=d.file_name, created_at=now(),
    )
    await books.file_document(p, path)
    await books.save_doc(DocMeta(sha256=digest, source_name=d.file_name, mime="image/png", size=len(data),
                                 proposal_id=p.id, filed_path=p.file_path))
    await books.save_proposal(p)
    await books.audit(ACTOR, "proposed", {"proposal": p.id, "doc": digest, "status": p.status, "path": p.file_path})
    return p


async def seed(storage: StorageProvider, plan: Plan, say: Callable[[str], None] = print) -> dict[str, Any]:
    books = SeedBooks(storage)
    say("Folder tree")
    await books.ensure_tree()
    await storage.write("README.txt", readme_text().encode())  # the same text the web app writes (app/paths.py)
    slug = _slug(plan.business)
    await invoicing.save_profile(books, invoicing.InvoiceProfile(
        name=plan.business, address="14 Mill Lane\nLeeds\nLS1 2AB", email=f"accounts@{slug}.example",
        vrn="GB 123 4567 89", terms_days=30, footer_note=LABEL,
    ), USER)

    say("Staff, jobs, timesheets, vehicle and journeys")
    for s in plan.staff:
        await jobs.save_staff(books, s)
    for j in plan.jobs.values():
        await jobs.save_job(books, j)
    for t in plan.timesheets:
        await jobs.add_entry(books, t)
    vehicle = await mileage.add_vehicle(books, plan.vehicle, USER)
    claim_ids = {j.id for j in plan.claim_journeys()}
    for j in plan.journeys:
        await mileage.add_entry(books, j.model_copy(update={"vehicle_id": vehicle.id}), USER)

    say(f"{len(plan.posted)} documents: upload, propose, approve")
    sales: dict[str, str] = {}  # invoice number -> event, for the customers' payments
    for n, d in enumerate(plan.posted, start=1):
        p = await _propose(books, d, plan)
        p = await approve(books, p.id, USER, {"job_id": plan.jobs[d.job].id} if d.job else None, rebuild=False)
        if p.extracted.doc_type == "sales_invoice" and p.extracted.invoice_number and p.event_id:
            sales[p.extracted.invoice_number] = p.event_id
        if n % 10 == 0:
            say(f"  {n}/{len(plan.posted)}")

    say("Contacts")
    book, _ = await contacts_mod.refresh(books, USER)
    ids: dict[str, str] = {}
    for name, edits in plan.customers.items():
        c = contacts_mod.find(book, supplier_key(name), None)
        if c is None:
            raise RuntimeError(f"{name} is not in the contact book")
        ids[name] = c.id
        await contacts_mod.edit(books, c.id, edits, USER)
    for k, j in plan.jobs.items():
        await jobs.save_job(books, j.model_copy(update={"customer_id": ids[plan.job_customers[k]]}))

    say("Sales invoices")
    sender = NotEmailed()
    profile = await invoicing.load_profile(books)
    for inv in plan.invoices:
        draft = invoicing.InvoiceDraft(customer=invoicing.InvoiceCustomer(contact_id=ids[inv.customer], name=inv.customer),
                                       issue_date=inv.issue, due_date=inv.due, lines=inv.lines, notes=LABEL)
        created = await invoicing.create_invoice(books, draft, USER)
        if created.number != inv.number:  # the bank statement quotes the number the plan expected
            raise RuntimeError(f"Invoice numbered {created.number}, expected {inv.number}: is the folder fresh?")
        await invoicing.send_invoice(books, sender, created.number, USER, render_invoice(created, profile))
        if inv.job:
            entries = [t.id for t in plan.timesheets if t.job_id == plan.jobs[inv.job].id]
            await jobs.mark_invoiced(books, entries, created.number)
            await books.audit(f"user:{USER}", "timesheets_invoiced", {"job": plan.jobs[inv.job].id, "invoice": created.number})
            await jobs.save_job(books, (await jobs.get_job(books, plan.jobs[inv.job].id)).model_copy(update={"status": "closed"}))

    say("Mileage claim")
    if claim_ids:
        claim, _ = await mileage.propose_allowance(books, mileage.tax_year_of(plan.claim_day),
                                                   mileage.quarter_of(plan.claim_day), today=plan.claim_day)
        await approve(books, claim.id, USER, rebuild=False)

    say("Bank statements")
    for name, data in plan.statements:
        await books.import_bank_csv(data, name, USER)
    lines = await books.stored_bank_lines()
    for inv in plan.invoices:
        if inv.paid_on:
            line = next(ln for ln in lines if ln.reference == inv.number and ln.date == inv.paid_on)
            await invoicing.mark_paid(books, inv.number, USER, bank_line_id=line.id)
    older_end = plan.periods[0][1]
    by_id = {ln.id: ln for ln in await books.stored_bank_lines()}
    for m in await books.bank_suggestions():  # the older statement is reconciled; the newer one is left to confirm
        if by_id[m.line_id].date <= older_end:
            await books.confirm_match(m.line_id, m.event_ids, USER)
    for ln in await books.stored_bank_lines():  # a customer payment the matcher could not place: matched by hand
        if ln.date <= older_end and ln.status == "unmatched" and ln.reference in sales:
            await books.confirm_match(ln.id, [sales[ln.reference]], USER)

    say(f"{len(plan.inbox)} documents into {INBOX}")
    for d in plan.inbox:
        await _upload(books, d)

    say("Books.xlsx")
    await Books.rebuild(books)
    events = await books.list_events()
    return {"events": len(events), "inbox": len(await books.list_files(INBOX)), "invoices": [i.number for i in plan.invoices],
            "bank_lines": len(await books.stored_bank_lines()), "emails_not_sent": len(sender.sent)}


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #


def root_is_accnomos(account: str, root_name: str) -> bool:
    """A personal account's books are in the token's app folder (Apps/<app name>), so a token from another app
    (Graph Explorer, say) would seed that app's folder. A work account's books are always /Accnomos."""
    return account == "work" or "accnomos" in root_name.lower()


async def _wipe(storage: Any, ask: Callable[[str], str] = input) -> bool:
    """Delete everything inside the Accnomos folder (OneDrive keeps it in the recycle bin). Asks first."""
    await storage.ensure_root()
    items = await storage.list("")
    if not items:
        return True
    where = storage._root_drive_path or "the Accnomos folder"
    print(f"{where} holds {len(items)} items: {', '.join(i.name for i in items[:8])}{' …' if len(items) > 8 else ''}")
    if ask(f"Delete all {len(items)} from {where}? Nothing outside it is touched. [y/N] ").strip().lower() != "y":
        return False
    from accnomos_connectors.msgraph import GRAPH

    for item in items:
        await storage._request("DELETE", f"{GRAPH}/me/drive/items/{item.id}")
    storage._folders.clear()
    return True


async def _main(args: argparse.Namespace) -> int:
    plan = build_plan(args.business, stagger=args.stagger)
    if args.dry_run:
        print(describe(plan))
        return 0
    token = (os.getenv("ACCNOMOS_GRAPH_TOKEN") or getpass.getpass("Graph access token (hidden): ")).strip()
    if not token:
        print("No token given; nothing changed.", file=sys.stderr)
        return 1
    from accnomos_connectors.msgraph import GraphError

    try:
        return await _seed_graph(args, plan, token)
    except GraphError as exc:
        hint = " The token is wrong or has expired (they last about an hour): copy a fresh one." if exc.status in (401, 403) else ""
        print(f"Microsoft Graph refused a request (HTTP {exc.status}).{hint} If the seed had started, the folder is part-filled: "
              "run again with --wipe.", file=sys.stderr)
        return 1


async def _seed_graph(args: argparse.Namespace, plan: Plan, token: str) -> int:
    from accnomos_connectors.msgraph import GraphStorageProvider

    async with GraphStorageProvider(token, args.account) as storage:
        root = await storage.ensure_root()
        print(f"Books folder: {storage._root_drive_path or root.name}")
        if not root_is_accnomos(args.account, root.name):
            print(f"That is not the Accnomos folder: for a personal account the app folder belongs to the app that issued "
                  f"the token ({root.name!r} here). Copy the token from the Accnomos web app instead (tools/seed_demo.md).",
                  file=sys.stderr)
            return 1
        if args.wipe and not await _wipe(storage):
            print("Nothing changed.")
            return 1
        if await Books(storage).list_events():
            print("This folder already has ledger entries. Use a fresh account, or --wipe.", file=sys.stderr)
            return 1
        print(describe(plan) + "\n")
        report = await seed(storage, plan)
    print(f"Done: {report['events']} ledger events, {report['inbox']} documents waiting in {INBOX}, "
          f"invoices {', '.join(report['invoices'])}, {report['bank_lines']} bank lines. No email was sent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--business", default=GOLD_BUSINESS, help="the fictional company's name")
    ap.add_argument("--account", choices=("personal", "work"), default="personal", help="Microsoft account type")
    ap.add_argument("--stagger", type=int, choices=(1, 2, 3), default=1, help="VAT stagger set in the app's Settings")
    ap.add_argument("--wipe", action="store_true", help="empty the Accnomos folder first (asks y/N)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; needs no token, writes nothing")
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
