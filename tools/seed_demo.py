#!/usr/bin/env python3
"""Fill a throwaway OneDrive with the fictional company's books, for a judge to click through.

    python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --dry-run    # print the plan, touch nothing
    python tools/seed_demo.py --business "Bramblewood Joinery Ltd"              # asks for a Graph token
    python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --wipe       # empty the Accnomos folder first (y/N)

Run with the runtime's venv. The token is read from ACCNOMOS_GRAPH_TOKEN or a hidden prompt, never from the
command line, and is kept in memory only. Walkthrough and how to get a token: tools/seed_demo.md.

Two halves. `build_plan` is pure and deterministic (same business, day and stagger give the same plan): it picks
gold documents from evals/gold (and evals/gold/ledger2 for part payments and credit notes), re-dates them, labels
each "SAMPLE — FICTIONAL COMPANY" and lays out jobs, timesheets, mileage, invoices and two bank statements. `seed`
then applies it through the functions the app's own routes call (approve(), invoicing, payments, credit notes, bank
reconcile, jobs, mileage, contacts, payroll, to-dos, the reports export...), so every file is written by app code;
nothing here writes JSON by hand. What it posts (stagger 1, run in Oct-Dec 2026; `--dry-run` prints it for any day):

* 59 ledger events, all inside the last two complete VAT periods. 45 approved entries: 38 documents (36 gold
  receipts, a supplier's bill and its credit note; two receipts arrive by email through Outlook intake, and
  Autopilot posts the second bill of each of six energy suppliers), one mileage claim and six sales invoices.
  14 posted by code for an action: five payments (one an overpayment, one part payment, one exact bank match turned
  into a payment, one bill paid from Contacts), credit note CN-0001, and eight statement lines coded by two bank rules.
* 25 more documents left in "00 Inbox", dated in the current period, for the judge to scan; two of them will land
  in "Needs a look" (an EUR invoice and a malformed VAT number).
* Before any of that, four suppliers marked "not VAT-registered" in the contacts: their receipts over £250 charge no
  VAT and show no VAT number, which for a supplier the books don't know means "Is <supplier> VAT-registered?".
* A pay-run estimate, two to-dos, Books.xlsx, and last every report in "07 Reports" (how a re-run knows the seed
  finished: it then changes nothing).

The documents are read by nobody: their proposals carry the gold set's fields (model "seed:gold-reading"),
the same "perfect reading" test mode uses. Code still runs every check and drafts every journal. No email is sent
and the user's mailbox is never read (intake reads a stand-in mailbox holding the two fictional receipts).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import hashlib
import io
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# This checkout's code, whatever the venv's editable installs point at.
for _p in ("packages/connectors/src", "packages/ledger/src", "services/runtime"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from accnomos_connectors import FakeMailProvider  # noqa: E402
from accnomos_connectors.base import MailAttachment, MailMessage, MailSender, OutgoingMail, StorageProvider  # noqa: E402
from accnomos_ledger.bank import reconciled_to  # noqa: E402
from app import (  # noqa: E402
    autopilot,
    bank_reconcile,
    bank_rules,
    credit_notes,
    intake,
    invoicing,
    jobs,
    mileage,
    payments,
    routes_reports,
)
from app import contacts as contacts_mod  # noqa: E402
from app import inbox as inbox_mod  # noqa: E402
from app import payroll as payroll_mod  # noqa: E402
from app import todos as todos_mod  # noqa: E402
from app.approve import ProposalStateError, approve  # noqa: E402
from app.autopilot import supplier_key  # noqa: E402
from app.books import Books, DocMeta, now  # noqa: E402
from app.checks import (  # noqa: E402  sys.path first
    FULL_INVOICE_THRESHOLD_GBP,
    UNKNOWN_SUPPLIER,
    SupplierKnowledge,
    decide,
    normalise_vat_number,
    run_checks,
)
from app.deadlines import STAGGER_START_MONTH, add_months, period_containing, period_label, previous_period  # noqa: E402
from app.journal import BANK, VAT_CONTROL, draft_journal  # noqa: E402
from app.paths import DOCS, INBOX, REPORTS, readme_text  # noqa: E402
from app.pdf import render_invoice  # noqa: E402
from app.pipeline import sha256_hex, suggested_filename  # noqa: E402
from app.repair import repair  # noqa: E402
from app.schemas import ExtractedDoc, JournalLine, Proposal  # noqa: E402
from app.testmode import _renderer, extracted_from_gold, gold_receipts  # noqa: E402
from app.vat_cycle import VatCycle  # noqa: E402

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

    by: str = "user"  # "autopilot": Autopilot posts it (the supplier's rule was saved on an earlier approval)
    always: bool = False  # approved with "Always do this for <supplier>" ticked: saves the Autopilot rule
    via: str = "upload"  # "mail": it arrives by email and Outlook intake copies it into 00 Inbox

    def doc(self) -> ExtractedDoc:
        return ExtractedDoc.model_validate(self.extracted)

    def journal(self) -> list[JournalLine]:
        return draft_journal(self.doc())


@dataclass
class PlannedPayment:
    day: date
    pence: int  # what reached the bank (an overpayment is more than the invoice)
    reference: str  # as on the statement line
    how: str = "recorded"  # "recorded": Record payment with the statement line; "exact": the Bank page's exact
    # invoice match, then Post as payment
    party: str = ""  # the statement's counter party; default the customer


@dataclass
class PlannedInvoice:
    number: str  # INV-0001...: the sequence of a fresh folder
    customer: str
    issue: date
    due: date
    lines: list[invoicing.LineIn]
    payments: list[PlannedPayment] = field(default_factory=list)
    job: str | None = None  # bills that job's timesheet hours
    gold: str | None = None  # evals/gold/ledger2/part_paid file its lines and payments come from
    email: str | None = None  # for a customer not yet in the contact book
    address: str | None = None

    @property
    def total_pence(self) -> int:
        _, _, net, vat = invoicing.price_lines(self.lines)
        return net + vat

    @property
    def net_pence(self) -> int:
        return invoicing.price_lines(self.lines)[2]

    @property
    def paid_pence(self) -> int:
        return sum(p.pence for p in self.payments)

    @property
    def paid_on(self) -> date | None:
        """The day it was paid in full (or over), else None."""
        return self.payments[-1].day if self.payments and self.paid_pence >= self.total_pence else None

    def state(self, today: date) -> str:
        if self.paid_pence > self.total_pence:
            return "overpaid"
        if self.paid_pence == self.total_pence:
            return "paid"
        late = " and OVERDUE" if self.due < today else ""
        return ("part paid" if self.paid_pence else "sent") + (late or " (not due yet)")


@dataclass
class PlannedCreditNote:
    invoice: str
    day: date
    line: int  # the invoice line credited
    quantity: Decimal
    reason: str

    def pence(self, inv: PlannedInvoice) -> tuple[int, int]:
        """(net, VAT) credited."""
        ln = inv.lines[self.line].model_copy(update={"quantity": self.quantity})
        _, _, net, vat = invoicing.price_lines([ln])
        return net, vat


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
    not_vat_registered: list[str]  # suppliers recorded as not VAT-registered before any document is proposed
    job_customers: dict[str, str]  # job key -> customer name
    statements: list[tuple[str, bytes]] = field(default_factory=list)  # (upload name, CSV bytes)
    # The rest of the features, from evals/gold/ledger2 where it has the figures (build_plan(extras=False): none)
    supplier_docs: list[PlannedDoc] = field(default_factory=list)  # a bill on account, then its credit note
    bill_payment: PlannedPayment | None = None  # the rest of that bill, paid from Contacts
    credit_notes: list[PlannedCreditNote] = field(default_factory=list)
    bank_rules: list[bank_rules.BankRule] = field(default_factory=list)
    rule_rows: list[tuple[date, str, str, str, int]] = field(default_factory=list)  # statement lines the rules code
    payroll_period: str | None = None  # a pay run estimated from that month's timesheets (not confirmed)
    todos: list[todos_mod.TodoIn] = field(default_factory=list)
    export_report: bool = False  # 07 Reports: every report in one spreadsheet (written last)

    @property
    def window(self) -> tuple[date, date]:
        return self.periods[0][0], self.periods[-1][1]

    def claim_journeys(self) -> list[mileage.MileageEntry]:
        start, _ = mileage.quarter_bounds(mileage.tax_year_of(self.claim_day), mileage.quarter_of(self.claim_day))
        return [j for j in self.journeys if start <= j.date <= self.claim_day]

    @property
    def approved_count(self) -> int:
        """Entries approved from documents (Review, Autopilot), the mileage claim and the invoices sent."""
        return len(self.posted) + len(self.supplier_docs) + len(self.invoices) + (1 if self.claim_journeys() else 0)

    @property
    def coded_count(self) -> int:
        """Entries code posts for an action: payments recorded, credit notes, statement lines coded by a rule."""
        payments = sum(len(i.payments) for i in self.invoices) + (1 if self.bill_payment else 0)
        return payments + len(self.credit_notes) + len(self.rule_rows) + sum(1 for r in _fee_rows(self))

    @property
    def event_count(self) -> int:
        return self.approved_count + self.coded_count

    def invoice(self, number: str) -> PlannedInvoice:
        return next(i for i in self.invoices if i.number == number)


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


def build_plan(
    business: str = GOLD_BUSINESS, today: date | None = None, stagger: int = 1, *, extras: bool = True
) -> Plan:
    """Everything the seed will write, decided up front. Raises ValueError when the gold set can't fill it.

    `extras=False` leaves out what came after the first 40 entries (part payments, credit notes, bank rules,
    Autopilot, intake, payroll, to-dos, the report export): the books the stored eval reports were run on."""
    today = today or date.today()
    current = period_containing(today, STAGGER_START_MONTH[stagger])
    newer = previous_period(current[0])
    older = previous_period(newer[0])
    start, end = older[0], newer[1]
    # The plan is tuned to the original hand-checked set (001-060); later generated documents (061+) are for the
    # eval only.
    golds = {f: g for f, g in gold_receipts().items() if f[:3].isdigit() and int(f[:3]) <= 60}
    not_registered = sorted({_supplier(g) for g in golds.values() if _charges_no_vat_over_250(g)})
    usable = {f: g for f, g in golds.items() if rewritable(g) and f not in INBOX_NEEDS_A_LOOK}
    usable = {f: g for f, g in usable.items() if _passes(g, not_registered)}
    sales = sorted(
        f
        for f, g in usable.items()
        if g["doc_type"] == "sales_invoice"
        and f != INBOX_SALE
        and (g.get("supplier") or {}).get("name") == GOLD_BUSINESS
    )
    utilities = sorted(f for f, g in usable.items() if g.get("payment_method") == "direct debit" and f not in sales)
    rest = sorted(f for f in usable if f not in sales and f not in utilities and f != INBOX_SALE)
    n_posted_rest = EVENTS - 1 - 3 - len(sales) - 2 * len(utilities)  # 1 mileage claim, 3 invoices
    if n_posted_rest < 0 or len(rest) - n_posted_rest != INBOX_DOCS - 1 - len(INBOX_NEEDS_A_LOOK):
        raise ValueError(
            f"the gold set gives {len(sales)} sales, {len(utilities)} utility bills and {len(rest)} others"
        )

    posted: list[PlannedDoc] = []
    # Quarterly energy bills: each supplier once in each period, three months apart.
    for i, f in enumerate(utilities):
        first = add_months(start, i % 3) + timedelta(days=7 + i)
        posted.append(_planned(f, golds[f], first, business, len(posted) + 1))
        posted.append(
            _planned(
                f,
                golds[f],
                add_months(start, i % 3 + 3) + timedelta(days=7 + i),
                business,
                len(posted) + 1,
                suffix="-2",
            )
        )
    spread = sorted(sales + rest[:n_posted_rest])
    for f, when in zip(spread, _spread(start, end, len(spread)), strict=True):
        posted.append(_planned(f, golds[f], when, business, len(posted) + 1))
    posted.sort(key=lambda d: (d.date, d.gold))
    for job, (lo, hi) in (("job1", older), ("job2", newer)):  # two materials purchases per job, in its period
        materials = [
            d
            for d in posted
            if lo <= d.date <= hi
            and d.extracted["doc_type"] != "sales_invoice"
            and d.extracted["category_guess"] in ("Materials", "Tools & small equipment")
        ]
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
        jobs.StaffMember(
            id=_hex(business, "staff", 1, n=12),
            name="Sam Ashdown",
            role="Joiner",
            hourly_rate_pence=1850,
            charge_rate_pence=4200,
        ),
        jobs.StaffMember(
            id=_hex(business, "staff", 2, n=12),
            name="Priya Hale",
            role="Apprentice",
            hourly_rate_pence=1100,
            charge_rate_pence=2800,
        ),
    ]
    customers = {
        "Halloway & Sons Interiors": {
            "email": "accounts@halloway-interiors.example",
            "address": "2 Station Road, Harrogate HG1 1AA",
        },
        "Hartwell Property Maintenance": {
            "email": "office@hartwell-pm.example",
            "address": "9 Canal Wharf, Leeds LS11 5AA",
        },
        "Sterling & Co. Architects": {
            "email": "studio@sterling-architects.example",
            "address": "41 Park Square, Leeds LS1 2NE",
        },
    }
    job_defs = {
        "job1": ("Kitchen fit-out, Harrogate", "Halloway & Sons Interiors", older, "closed"),
        "job2": ("Office partitions and doors", "Hartwell Property Maintenance", newer, "open"),
    }
    plan_jobs = {
        k: jobs.Job(
            id=_hex(business, "job", k, n=12), name=name, site_address=customers[cust]["address"], estimate_hours=8
        )
        for k, (name, cust, _, _) in job_defs.items()
    }
    timesheets: list[jobs.TimesheetEntry] = []
    journeys: list[mileage.MileageEntry] = []
    vehicle = mileage.Vehicle(
        id=_hex(business, "vehicle"),
        name="Director's car (own)",
        registration="SAMPLE",
        kind="car",
        owned_by="personal",
    )
    for k, (name, cust, (lo, hi), _) in job_defs.items():
        days = _spread(lo + timedelta(days=7), lo + timedelta(days=48) if k == "job1" else hi, 6)
        for n, day in enumerate(days):
            for s, hours in zip(staff, (7.5, 6.0 if n % 2 else 7.5), strict=True):
                timesheets.append(
                    jobs.TimesheetEntry(
                        id=_hex(business, "ts", k, n, s.id, n=12),
                        staff_id=s.id,
                        job_id=plan_jobs[k].id,
                        date=day,
                        hours=hours,
                        note=f"{name}: day {n + 1}",
                    )
                )
            journeys.append(
                mileage.MileageEntry(
                    id=_hex(business, "trip", k, n),
                    vehicle_id=vehicle.id,
                    date=day,
                    from_="Workshop, Leeds",
                    to=customers[cust]["address"],
                    miles=21.4 if k == "job1" else 6.8,
                    purpose=f"{name} ({cust})",
                    job_id=plan_jobs[k].id,
                )
            )
    journeys.append(
        mileage.MileageEntry(  # one late in the period, so every stagger's claim has a journey
            id=_hex(business, "trip", "supplier"),
            vehicle_id=vehicle.id,
            date=newer[1] - timedelta(days=2),
            from_="Workshop, Leeds",
            to="Timber merchant, Wakefield",
            miles=12.5,
            purpose="Collect oak boards for stock",
        )
    )

    job1_lines = jobs.invoice_lines(plan_jobs["job1"], timesheets, staff).lines
    inv1_issue = max(t.date for t in timesheets if t.job_id == plan_jobs["job1"].id) + timedelta(days=3)
    invoices = [
        PlannedInvoice(
            "INV-0001",
            "Halloway & Sons Interiors",
            inv1_issue,
            inv1_issue + timedelta(days=30),
            [
                invoicing.LineIn(
                    description=ln.description,
                    quantity=Decimal(str(ln.qty)),
                    unit="hours",
                    unit_price_pence=ln.unit_price_pence,
                    vat_code="S",
                )
                for ln in job1_lines
            ],
            payments=[PlannedPayment(inv1_issue + timedelta(days=12), 0, "INV-0001")],  # pence: set below
            job="job1",
        ),
        PlannedInvoice(
            "INV-0002",
            "Sterling & Co. Architects",
            newer[0] + timedelta(days=20),
            newer[0] + timedelta(days=50),
            [
                invoicing.LineIn(
                    description="Bespoke oak bookcase, 2.4 m, fitted",
                    quantity=Decimal(1),
                    unit="each",
                    unit_price_pence=185_000,
                    vat_code="S",
                ),
            ],
        ),
        PlannedInvoice(
            "INV-0006" if extras else "INV-0003",
            "Hartwell Property Maintenance",
            newer[1] - timedelta(days=3),
            today + timedelta(days=21),
            [
                invoicing.LineIn(
                    description="Sash window repairs, three windows",
                    quantity=Decimal(3),
                    unit="each",
                    unit_price_pence=26_500,
                    vat_code="S",
                ),
                invoicing.LineIn(
                    description="Materials: draught strip and beads",
                    quantity=Decimal(1),
                    unit="each",
                    unit_price_pence=8_640,
                    vat_code="S",
                ),
            ],
        ),
    ]
    invoices[0].payments[0].pence = invoices[0].total_pence
    if extras:
        invoices[2:2] = _gold_invoices(newer, business)
    plan = Plan(
        business=business,
        today=today,
        periods=[older, newer],
        current=current,
        posted=posted,
        inbox=inbox,
        staff=staff,
        jobs=plan_jobs,
        timesheets=timesheets,
        vehicle=vehicle,
        journeys=journeys,
        claim_day=newer[1],
        invoices=invoices,
        customers=customers,
        not_vat_registered=not_registered,
        job_customers={k: cust for k, (_, cust, _, _) in job_defs.items()},
    )
    if extras:
        _plan_extras(plan, utilities)
    plan.statements = [_statement(plan, lo, hi, n) for n, (lo, hi) in enumerate(plan.periods)]
    return plan


# --------------------------------------------------------------------------- #
# The rest of the features: figures from evals/gold/ledger2 where it has them
# --------------------------------------------------------------------------- #

LEDGER2 = ROOT / "evals" / "gold" / "ledger2"
GOLD_INVOICES = ("004_over.json", "003_part_open.json", "002_exact.json")  # overpaid, part paid, exact bank match
GOLD_SUPPLIER_CN = "001_credit_note.json"  # Oakfield Hardware Supplies credits part of bill INV-2026-0892
GOLD_JULY = date(2026, 7, 1)  # the ledger2 gold is dated July 2026: moved to the newer period, 10 days in
INSURER = "Ashworth Mutual Insurance"
INSURANCE_PENCE = -4250


def _ledger2(kind: str, file: str) -> dict[str, Any]:
    return json.loads((LEDGER2 / kind / file).read_text(encoding="utf-8"))


def _shift(newer: tuple[date, date]) -> timedelta:
    return newer[0] + timedelta(days=10) - GOLD_JULY


def _email_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _gold_invoices(newer: tuple[date, date], business: str) -> list[PlannedInvoice]:
    """INV-0003, -0004, -0005 from the ledger2 part-payment gold: its customers, lines, payment days and amounts,
    numbered by this folder's sequence (the gold's own numbers are replaced in the payment references)."""
    shift = _shift(newer)
    golds = sorted(((f, _ledger2("part_paid", f)) for f in GOLD_INVOICES), key=lambda fg: (fg[1]["date"], fg[0]))
    out: list[PlannedInvoice] = []
    for n, (f, g) in enumerate(golds, start=3):
        number = f"INV-{n:04d}"
        issue = date.fromisoformat(g["date"]) + shift
        lines = [
            invoicing.LineIn(
                description=ln["description"],
                quantity=Decimal(str(ln["qty"])),
                unit="each",
                unit_price_pence=round(Decimal(str(ln["unit_price"])) * 100),
                vat_code="S" if ln["vat_rate"] == 20 else "Z",
            )
            for ln in g["lines"]
        ]
        how = "exact" if g["gold_case"] == "exact" else "recorded"
        inv = PlannedInvoice(
            number,
            g["customer"]["name"],
            issue,
            issue + timedelta(days=g["due_days"]),
            lines,
            payments=[
                PlannedPayment(
                    date.fromisoformat(p["date"]) + shift,
                    round(Decimal(str(p["amount"])) * 100),
                    p["reference"].replace(g["invoice_number"], number),
                    how,
                )
                for p in g["payments"]
            ],
            gold=f,
            email=f"accounts@{_email_slug(g['customer']['name'])}.example",
            address=g["customer"]["address"],
        )
        want = round(Decimal(str(g["gross_total"])) * 100), round(Decimal(str(g["expected"]["paid"])) * 100)
        if (inv.total_pence, inv.paid_pence) != want:
            raise ValueError(f"ledger2 {f}: priced {inv.total_pence}p paid {inv.paid_pence}p, the gold says {want}")
        if not all(newer[0] <= p.day <= newer[1] for p in inv.payments):
            raise ValueError(f"ledger2 {f}: a payment falls outside {newer}")
        out.append(inv)
    return out


def _supplier_docs(newer: tuple[date, date], business: str) -> list[PlannedDoc]:
    """The ledger2 supplier credit note, and the bill it credits. The gold has only the credit note, so the bill is
    its lines at twice the quantity: half the goods came back damaged or mis-rated."""
    g = _ledger2("credit_notes", GOLD_SUPPLIER_CN)
    shift = _shift(newer)
    cn_day = date.fromisoformat(g["date"]) + shift
    bill_day = date.fromisoformat(g["original_invoice_date"]) + shift
    sup = g["supplier"]

    def doc(doc_type: str, number: str, when: date, k: Decimal) -> dict[str, Any]:
        lines = [
            {
                "description": ln["description"],
                "qty": float(Decimal(str(ln["qty"])) * abs(k)),
                "unit_price": float(Decimal(str(ln["unit_price"])) * (k / abs(k))),
                "net": float(Decimal(str(ln["net"])) * k),
                "vat_rate": ln["vat_rate"],
                "vat": float(Decimal(str(ln["vat"])) * k),
            }
            for ln in g["lines"]
        ]
        return ExtractedDoc.model_validate(
            {
                "doc_type": doc_type,
                "supplier_name": sup["name"],
                "supplier_vat_number": sup["vat_number"],
                "customer_name": business,
                "invoice_number": number,
                "original_invoice_number": g["original_invoice_number"] if doc_type == "credit_note" else None,
                "date": when.isoformat(),
                "currency": "GBP",
                "lines": lines,
                "net_total": float(Decimal(str(g["net_total"])) * k),
                "vat_total": float(Decimal(str(g["vat_total"])) * k),
                "gross_total": float(Decimal(str(g["gross_total"])) * k),
                "payment_method": None,  # on account: Cr 2100 Creditors
                "card_last4": None,
                "category_guess": "Materials",
                "confidence": 0.97,
            }
        ).model_dump()

    bill = doc("purchase_invoice", g["original_invoice_number"], bill_day, Decimal(-2))
    rows = "\n".join(
        f"{ln['description']} | {ln['qty']:.2f} | {ln['unit_price']:.2f} | {ln['net']:.2f} | {ln['vat']:.2f} | "
        f"{ln['net'] + ln['vat']:.2f}"
        for ln in bill["lines"]
    )
    bill_text = (
        f"{sup['name'].upper()}\n{sup['address']}\nVAT No: {sup['vat_number']}\n\nINVOICE\n\n"
        f"Date: {bill_day.isoformat()}\nInvoice No: {g['original_invoice_number']}\nCustomer: {business}\n"
        f"Terms: 30 days from invoice\n\nDescription | Qty | Unit Price | Net | VAT | Total\n{rows}\n\n"
        f"Total Net: {bill['net_total']:.2f}\nTotal VAT: {bill['vat_total']:.2f}\nTOTAL DUE: {bill['gross_total']:.2f}"
    )
    cn_text = (
        g["printed_text"]
        .replace(g["date"], cn_day.isoformat())
        .replace(g["original_invoice_date"], bill_day.isoformat())
        .replace(GOLD_BUSINESS, business)
    )
    return [
        PlannedDoc(
            gold=f"ledger2 {GOLD_SUPPLIER_CN} (the bill it credits)",
            date=bill_day,
            text=f"{bill_text}\n\n{LABEL}",
            extracted=bill,
            file_name=f"SAMPLE {bill_day.isoformat()} bill.png",
        ),
        PlannedDoc(
            gold=f"ledger2 {GOLD_SUPPLIER_CN}",
            date=cn_day,
            text=f"{cn_text}\n\n{LABEL}",
            extracted=doc("credit_note", g["credit_note_number"], cn_day, Decimal(1)),
            file_name=f"SAMPLE {cn_day.isoformat()} credit note.png",
        ),
    ]


def _fee_rows(plan: Plan) -> list[tuple[date, str, str, str, int]]:
    """The statements' account fees: coded by the first bank rule when there are rules."""
    return [r for r in _bank_rows(plan) if r[1] == "Starling Bank"] if plan.bank_rules else []


def _plan_extras(plan: Plan, utilities: list[str]) -> None:
    (start, _), newer = plan.window, plan.periods[1]
    # Autopilot: each energy supplier's first bill is approved with "Always do this" ticked, the second (a quarter
    # later, the same amount) is posted by Autopilot.
    seen: set[str] = set()
    for d in plan.posted:  # sorted by date
        if d.gold in utilities:
            if d.gold in seen:
                d.by = "autopilot"
            else:
                d.always = True
                seen.add(d.gold)
    # Outlook intake: two card receipts of the newer period arrive by email.
    mailed = [
        d
        for d in plan.posted
        if newer[0] <= d.date <= newer[1]
        and d.job is None
        and d.by == "user"
        and not d.always
        and d.extracted["doc_type"] == "receipt"
        and d.extracted.get("payment_method") == "card"
    ]
    if len(mailed) < 2:
        raise ValueError("the newer period has fewer than two card receipts to arrive by email")
    for d in mailed[:2]:
        d.via = "mail"

    plan.supplier_docs = _supplier_docs(newer, plan.business)
    bill, cn = plan.supplier_docs
    owed = round(bill.doc().gross_total * 100) - abs(round(cn.doc().gross_total * 100))
    plan.bill_payment = PlannedPayment(
        cn.date + timedelta(days=6), -owed, bill.extracted["invoice_number"], party=bill.doc().supplier_name
    )
    last = plan.invoices[-1]  # INV-0006: one of the three sash windows was left for the customer's glazier
    plan.credit_notes = [
        PlannedCreditNote(
            last.number, newer[1] - timedelta(days=1), 0, Decimal(1), "One sash window left out of the job"
        )
    ]
    plan.bank_rules = [
        bank_rules.BankRule(
            id=_hex(plan.business, "rule", "fee", n=12),
            name="Starling account fee",
            match=bank_rules.BankRuleMatch(op="contains", value="Starling Bank"),
            direction="out",
            action=bank_rules.BankRuleAction(account="7900 Bank charges", vat_code="E", contact="Starling Bank"),
            created_by=USER,
        ),
        bank_rules.BankRule(
            id=_hex(plan.business, "rule", "insurance", n=12),
            name="Business insurance",
            match=bank_rules.BankRuleMatch(op="contains", value="Ashworth Mutual"),
            direction="out",
            amount_min_pence=INSURANCE_PENCE,
            amount_max_pence=INSURANCE_PENCE,
            action=bank_rules.BankRuleAction(account="7700 Insurance", vat_code="E", contact=INSURER),
            created_by=USER,
        ),
    ]
    plan.rule_rows = [
        (add_months(start, k) + timedelta(days=2), INSURER, "POLICY BW-2231", "DIRECT DEBIT", INSURANCE_PENCE)
        for k in range(6)
    ]
    month = newer[1].replace(day=1)
    if not any(month <= t.date <= newer[1] for t in plan.timesheets):
        raise ValueError(f"no timesheet hours in {month:%B %Y} for the pay run")
    plan.payroll_period = f"{month:%Y-%m}"
    part = next(i for i in plan.invoices if i.gold and i.state(plan.today).startswith("part paid"))
    over = next(i for i in plan.invoices if i.state(plan.today) == "overpaid")
    plan.todos = [
        todos_mod.TodoIn(
            text=f"Chase {part.customer} for the {invoicing.money(part.total_pence - part.paid_pence)} "
            f"left on {part.number}",
            due=plan.today + timedelta(days=3),
        ),
        todos_mod.TodoIn(
            text=f"Ask {over.customer} whether to refund the {invoicing.money(over.paid_pence - over.total_pence)} "
            "overpayment or keep it on account",
            due=plan.today + timedelta(days=7),
        ),
    ]
    plan.export_report = True


def _supplier(gold: dict[str, Any]) -> str:
    return ExtractedDoc.model_validate(extracted_from_gold(gold)).supplier_name


def _charges_no_vat_over_250(gold: dict[str, Any]) -> bool:
    """A purchase over £250 with no VAT and no VAT number (gold 005, 016, 027, 049). From a supplier the books don't
    know, the scan asks "Is <supplier> VAT-registered?"; the fictional company knows these four aren't, so the seed
    records that in their contacts first, as ticking "isn't VAT-registered" on an earlier receipt would have."""
    doc = ExtractedDoc.model_validate(extracted_from_gold(gold))
    return (
        doc.doc_type != "sales_invoice"
        and doc.currency == "GBP"
        and doc.vat_total <= 0
        and normalise_vat_number(doc.supplier_vat_number) is None
        and doc.gross_total > FULL_INVOICE_THRESHOLD_GBP
    )


def _knowledge(doc: ExtractedDoc, not_registered: list[str]) -> SupplierKnowledge:
    return SupplierKnowledge("not_registered") if doc.supplier_name in not_registered else UNKNOWN_SUPPLIER


def _passes(gold: dict[str, Any], not_registered: list[str]) -> bool:
    """Every check passes on a perfect reading (EUR and the malformed VAT number do not)."""
    doc = ExtractedDoc.model_validate(extracted_from_gold(gold))
    checks = run_checks(doc, known_hashes=set(), this_hash="", supplier=_knowledge(doc, not_registered))
    return gold.get("currency", "GBP") == "GBP" and decide(checks)[0] == "proposed"


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
            rows.append(
                (
                    d.date + timedelta(days=10),
                    doc.customer_name or "",
                    doc.invoice_number or "",
                    "FASTER PAYMENT",
                    round(doc.gross_total * 100),
                )
            )
        elif leg is not None:
            ref = f"CARD {doc.card_last4}" if doc.card_last4 else (doc.invoice_number or "")
            lag = 1 if doc.payment_method == "card" else 0
            rows.append(
                (
                    d.date + timedelta(days=lag),
                    doc.supplier_name,
                    ref,
                    _TYPE.get(doc.payment_method or "", "PAYMENT"),
                    leg.debit_pence - leg.credit_pence,
                )
            )
    for inv in plan.invoices:
        for pay in inv.payments:
            rows.append((pay.day, pay.party or inv.customer, pay.reference, "FASTER PAYMENT", pay.pence))
    if plan.bill_payment:
        b = plan.bill_payment
        rows.append((b.day, b.party, b.reference, "FASTER PAYMENT", b.pence))
    rows += plan.rule_rows
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
    w.writerow(
        ["Date", "Counter Party", "Reference", "Type", "Amount (GBP)", "Balance (GBP)", "Spending Category", "Notes"]
    )
    for day, party, ref, kind, pence in rows:
        if lo <= day <= hi:
            balance += pence
            w.writerow(
                [
                    _uk(day),
                    party,
                    ref,
                    kind,
                    _pounds(pence),
                    _pounds(balance),
                    "INCOME" if pence > 0 else "GENERAL",
                    LABEL,
                ]
            )
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
        f"{plan.event_count} ledger events: {plan.approved_count} approved entries "
        f"and {plan.coded_count} posted by code for an action (payments, credit notes, bank-rule codings)",
    ]
    for d in sorted(plan.posted + plan.supplier_docs, key=lambda d: (d.date, d.gold)):
        doc = d.doc()
        who = (doc.customer_name if doc.doc_type == "sales_invoice" else doc.supplier_name) or ""
        kind = {"sales_invoice": "sale    ", "credit_note": "credit  "}.get(doc.doc_type, "purchase")
        tag = f"  [{plan.jobs[d.job].name}]" if d.job else ""
        tag += {"autopilot": "  [Autopilot]"}.get(d.by, "") + ("  [Always do this]" if d.always else "")
        tag += "  [emailed in]" if d.via == "mail" else ""
        lines.append(
            f"  {d.date:%d/%m/%Y}  {kind}  "
            f"{who[:34]:34} {money(round(doc.gross_total * 100)):>11}  VAT {money(round(doc.vat_total * 100)):>9}{tag}"
        )
    claim = plan.claim_journeys()
    miles = sum(j.miles for j in claim)
    lines.append(
        f"  {plan.claim_day:%d/%m/%Y}  mileage   {len(claim)} journeys, {miles:.1f} miles "
        "(allowance worked out by code)"
    )
    for inv in plan.invoices:
        lines.append(
            f"  {inv.issue:%d/%m/%Y}  {inv.number} {inv.customer[:30]:30} {money(inv.total_pence):>11}  "
            f"due {inv.due:%d/%m/%Y}, {inv.state(plan.today)}"
        )
        for pay in inv.payments:
            how = "exact match on the Bank page, then Post as payment" if pay.how == "exact" else "Record payment"
            lines.append(f"      {pay.day:%d/%m/%Y}  paid {money(pay.pence):>11}  ({how})")
    for cn in plan.credit_notes:
        net, vat = cn.pence(plan.invoice(cn.invoice))
        lines.append(f"  {cn.day:%d/%m/%Y}  CN-0001 against {cn.invoice}: {money(net + vat)} ({cn.reason})")
    if plan.bill_payment:
        b = plan.bill_payment
        lines.append(
            f"  {b.day:%d/%m/%Y}  bill {b.reference} {b.party}: the rest, {money(-b.pence)}, paid from Contacts"
        )
    for lo, hi in plan.periods:
        sale_vat = sum(
            round(d.doc().vat_total * 100)
            for d in plan.posted
            if lo <= d.date <= hi and d.doc().doc_type == "sales_invoice"
        )
        sale_vat += sum(inv.total_pence - inv.net_pence for inv in plan.invoices if lo <= inv.issue <= hi)
        sale_vat -= sum(cn.pence(plan.invoice(cn.invoice))[1] for cn in plan.credit_notes if lo <= cn.day <= hi)
        buy_vat = sum(
            j.debit_pence - j.credit_pence
            for d in plan.posted + plan.supplier_docs
            if lo <= d.date <= hi
            for j in d.journal()
            if j.account == VAT_CONTROL and d.doc().doc_type != "sales_invoice"
        )
        lines.append(f"  {period_label(lo, hi)}: VAT on sales {money(sale_vat)}, VAT reclaimed {money(buy_vat)}")
    lines += ["", f"{len(plan.inbox)} documents left in {INBOX} (dated {period_label(*plan.current)}):"]
    for d in plan.inbox:
        doc = d.doc()
        who = f"sale to {doc.customer_name}" if doc.doc_type == "sales_invoice" else doc.supplier_name
        lines.append(
            f"  {d.file_name}  {who[:34]:34} {doc.currency} {doc.gross_total:>9.2f}"
            + ("  -> Needs a look" if d.expect == "needs_a_look" else "")
        )
    lines += [
        "",
        f"Staff: {', '.join(f'{s.name} ({s.role})' for s in plan.staff)}",
        f"Jobs: {', '.join(j.name for j in plan.jobs.values())}; {len(plan.timesheets)} timesheet entries",
        f"Vehicle: {plan.vehicle.label()}, {len(plan.journeys)} journeys",
        f"Bank statements: {', '.join(name for name, _ in plan.statements)}",
        f"Not VAT-registered (recorded first): {', '.join(plan.not_vat_registered)}",
    ]
    if plan.bank_rules:
        coded = len(plan.rule_rows) + len(_fee_rows(plan))
        lines.append(
            f"Bank rules: {'; '.join(bank_rules.describe(r) for r in plan.bank_rules)}; they code {coded} lines"
        )
    if plan.payroll_period:
        lines.append(f"Pay run: an estimate for {plan.payroll_period} from the timesheets (not confirmed)")
    if plan.todos:
        lines.append(f"{len(plan.todos)} to-dos: " + "; ".join(t.text for t in plan.todos))
    lines.append(
        "Then: contacts refreshed from the ledger, Books.xlsx rebuilt"
        + (f", every report saved in {REPORTS}." if plan.export_report else ".")
    )
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


async def _propose(
    books: Books, d: PlannedDoc, plan: Plan, arrived: tuple[str, bytes] | None = None, again: bool = False
) -> Proposal:
    """What scan_inbox_detailed does for one file, with the gold fields standing in for the model's reading.
    `arrived`: (path, bytes) of a file already in 00 Inbox (Outlook intake put it there); else it is uploaded.
    `again`: a resumed seed recorded this document (its _System/docs entry) but not its proposal, so its own hash
    is not a duplicate."""
    path, data = arrived or await _upload(books, d)
    digest = sha256_hex(data)
    doc = d.doc()
    start, end = period_containing(d.date, plan.current[0].month)  # checked when it arrived, in its own period
    supplier = contacts_mod.supplier_knowledge(
        await contacts_mod.stored_contacts(books), doc
    )  # as the scan looks it up
    known = await books.known_hashes()
    if again:
        known.discard(digest)
    checks = repair(doc, plan.business) + run_checks(
        doc,
        known_hashes=known,
        this_hash=digest,
        period_start=start,
        period_end=end,
        supplier=supplier,
    )
    status, reasons = decide(checks)
    p = Proposal(
        id=_hex(plan.business, d.gold, d.date),
        doc_sha256=digest,
        extracted=doc,
        checks=checks,
        status=status,
        reasons=reasons,
        suggested_filename=suggested_filename(doc, "image/png"),
        journal_draft=draft_journal(doc),
        model=MODEL,
        elapsed_s=0,
        source_name=path.rsplit("/", 1)[-1],
        created_at=now(),
    )
    await books.file_document(p, path)
    await books.save_doc(
        DocMeta(
            sha256=digest,
            source_name=path.rsplit("/", 1)[-1],
            mime="image/png",
            size=len(data),
            proposal_id=p.id,
            filed_path=p.file_path,
        )
    )
    await books.save_proposal(p)
    await books.audit(ACTOR, "proposed", {"proposal": p.id, "doc": digest, "status": p.status, "path": p.file_path})
    return p


async def seed_state(books: Books) -> str:
    """ "empty", "complete" (seeded by this tool to the end: the report export is its last write), "partial" (seeded
    but stopped part-way) or "foreign" (entries someone else approved: never the seed's to touch). Reads only."""
    events = await books.list_events()
    if not events:
        return "empty"
    if any(e.approved_by not in (USER, autopilot.AUTOPILOT) for e in events):
        return "foreign"
    done = [f for f in await books.list_files(REPORTS) if f.name.endswith(".xlsx")]
    return "complete" if done else "partial"


async def _mail_in(books: Books, docs: list[tuple[int, PlannedDoc]], plan: Plan) -> None:
    """Outlook intake (app/intake.py scan_mail) copies these receipts from a stand-in mailbox into 00 Inbox, as it
    would from the user's own. The real mailbox is never read. `docs`: (n, document), n numbering the mails, so a
    resumed seed sends the same messages again. Intake records where each one went (_mailed reads it back)."""
    box = FakeMailProvider()
    at = datetime.now(UTC)
    for n, d in docs:
        png, who = render_png(d.text), d.doc().supplier_name
        box.add(
            MailMessage(
                id=f"sample-{n}",
                received_at=at - timedelta(hours=n + 1),
                from_address=f"receipts@{_email_slug(who)}.example",
                from_name=who,
                subject=f"Your receipt from {who} ({LABEL})",
                has_attachments=True,
            ),
            (MailAttachment(id=f"att-{n}", name=f"receipt-{n + 1}.png", content_type="image/png", size=len(png)), png),
        )
    result = await intake.scan_mail(books, box, since_days=2, user=f"accounts@{_slug(plan.business)}.example")
    if len(result.items) != len(docs):
        raise RuntimeError(f"Outlook intake copied {len(result.items)} of {len(docs)} emailed receipts")


async def _mailed(books: Books, d: PlannedDoc) -> tuple[str, bytes]:
    """(path in 00 Inbox, bytes) of an emailed receipt, from intake's record of what it saved."""
    png = render_png(d.text)
    sha = sha256_hex(png)
    for row in await books.read_json(intake.SEEN, []):
        if isinstance(row, dict) and row.get("sha256") == sha:
            return str(row["saved_as"]), png
    raise RuntimeError(f"the emailed receipt {d.file_name} is not in the intake record")


# --------------------------------------------------------------------------- #
# The seed as a list of steps
#
# `seed` runs them all in one go. The runtime's "Load sample books" (app/sample_books.py) runs the same steps one
# at a time in the background, records after each how many are done, and when it is stopped (the Graph token it
# was given expires after about an hour, or the runtime restarts) carries on from the step that was cut short. So
# every step is safe to run again after it stopped part-way: `resuming` is True for that one step, and it then
# looks at what is already there before writing. A step that has not started yet runs exactly as in one go.
# --------------------------------------------------------------------------- #


@dataclass
class Step:
    name: str  # what the person waiting sees, e.g. "Receipts and bills (3 of 38)"
    run: Callable[[Books, bool], Awaitable[None]]  # (books, resuming)


def seed_steps(plan: Plan, sender: NotEmailed | None = None) -> list[Step]:
    """Every step of the plan, in the order `seed` writes them."""
    sender = sender or NotEmailed()
    documents = sorted(plan.posted + plan.supplier_docs, key=lambda d: (d.date, d.gold))
    mailed = [(n, d) for n, d in enumerate(d for d in plan.posted if d.via == "mail")]

    def doc_step(n: int, d: PlannedDoc) -> Step:
        return Step(f"Receipts and bills ({n} of {len(documents)})", lambda b, r: _step_document(b, plan, d, r))

    steps = [
        Step("Folders and business details", lambda b, r: _step_tree(b, plan)),
        Step("Staff, jobs and timesheets", lambda b, r: _step_jobs(b, plan, r)),
        Step("Vehicle and journeys", lambda b, r: _step_vehicle(b, plan, r)),
        Step("Suppliers that aren't VAT-registered", lambda b, r: _step_not_registered(b, plan)),
    ]
    if mailed:
        steps.append(Step("Receipts emailed in (Outlook intake)", lambda b, r: _step_mail(b, plan, mailed, r)))
    steps += [doc_step(n, d) for n, d in enumerate(documents, start=1)]
    steps += [
        Step("Contacts", lambda b, r: _step_contacts(b, plan)),
        Step("Sales invoices", lambda b, r: _step_invoices(b, plan, sender, r)),
    ]
    if plan.credit_notes:
        steps.append(Step("Credit note", lambda b, r: _step_credit_notes(b, plan, r)))
    steps += [
        Step("Mileage claim", lambda b, r: _step_mileage_claim(b, plan, r)),
        Step("Bank rules and statements", lambda b, r: _step_statements(b, plan)),
        Step("Payments", lambda b, r: _step_payments(b, plan, r)),
        Step("Bank reconciliation", lambda b, r: _step_reconcile(b, plan, r)),
        Step("Pay run estimate and to-dos", lambda b, r: _step_payroll_todos(b, plan)),
        Step(f"Documents waiting in {INBOX}", lambda b, r: _step_inbox(b, plan)),
        Step("Books.xlsx", lambda b, r: _rebuild(b)),
    ]
    if plan.export_report:  # last: its file in 07 Reports is how a second run knows the seed finished
        steps.append(Step(f"Reports in {REPORTS}", lambda b, r: _step_reports(b, plan, r)))
    return steps


async def seed(storage: StorageProvider, plan: Plan, say: Callable[[str], None] = print) -> dict[str, Any]:
    """Apply the plan. On books it already seeded to the end this writes nothing and says so (`already_seeded`);
    books it seeded part-way, or anyone else's, are refused (RuntimeError)."""
    books = SeedBooks(storage)
    state = await seed_state(books)
    if state == "complete":
        say("Already seeded: nothing to do")
        return await _report(books, plan, already_seeded=True)
    if state != "empty":
        raise RuntimeError(
            "These books were seeded part-way (start again with --wipe)"
            if state == "partial"
            else "These books have entries the seed did not make; it only fills an empty folder"
        )
    sender = NotEmailed()
    for step in seed_steps(plan, sender):
        say(step.name)
        await step.run(books, False)
    return await _report(books, plan, emails=len(sender.sent))


def proposal_id(plan: Plan, d: PlannedDoc) -> str:
    return _hex(plan.business, d.gold, d.date)


async def _proposal_or_none(books: Books, pid: str) -> Proposal | None:
    try:
        return await books.get_proposal(pid)
    except FileNotFoundError:
        return None


async def _event_exists(books: Books, event_id: str) -> bool:
    try:
        await books.get_event(event_id)
    except FileNotFoundError:
        return False
    return True


async def _step_tree(books: Books, plan: Plan) -> None:
    await books.ensure_tree()
    await books.storage.write("README.txt", readme_text().encode())  # the same text the web app writes (app/paths.py)
    slug = _slug(plan.business)
    await invoicing.save_profile(
        books,
        invoicing.InvoiceProfile(
            name=plan.business,
            address="14 Mill Lane\nLeeds\nLS1 2AB",
            email=f"accounts@{slug}.example",
            vrn="GB 123 4567 89",
            terms_days=30,
            footer_note=LABEL,
        ),
        USER,
    )


async def _step_jobs(books: Books, plan: Plan, resuming: bool) -> None:
    for s in plan.staff:
        await jobs.save_staff(books, s)
    for j in plan.jobs.values():
        await jobs.save_job(books, j)
    have = {e.id for e in await jobs.load_entries(books)} if resuming else set()
    for t in plan.timesheets:
        if t.id not in have:  # entries are appended: a resumed step skips those already there
            await jobs.add_entry(books, t)


def _journey_key(j: mileage.MileageEntry) -> tuple[Any, ...]:
    return (j.date, j.from_, j.to, j.miles, j.purpose, j.job_id)


async def _step_vehicle(books: Books, plan: Plan, resuming: bool) -> None:
    found = next((v for v in await mileage.load_vehicles(books) if v.name == plan.vehicle.name), None)
    vehicle = found if resuming and found else await mileage.add_vehicle(books, plan.vehicle, USER)
    have: set[tuple[Any, ...]] = set()
    if resuming:
        for ty in sorted({mileage.tax_year_of(j.date) for j in plan.journeys}):
            have |= {_journey_key(e) for e in await mileage.load_entries(books, ty) if e.vehicle_id == vehicle.id}
    for j in plan.journeys:
        if _journey_key(j) not in have:  # the app gives each journey a new id, so they are told apart by content
            await mileage.add_entry(books, j.model_copy(update={"vehicle_id": vehicle.id}), USER)


async def _step_not_registered(books: Books, plan: Plan) -> None:
    for name in plan.not_vat_registered:  # writes only when it changes
        await contacts_mod.set_vat_status(books, name, "not_registered", ACTOR)


async def _step_mail(books: Books, plan: Plan, mailed: list[tuple[int, PlannedDoc]], resuming: bool) -> None:
    if resuming:  # only the receipts intake has not recorded yet
        seen = {r.get("sha256") for r in await books.read_json(intake.SEEN, []) if isinstance(r, dict)}
        mailed = [(n, d) for n, d in mailed if sha256_hex(render_png(d.text)) not in seen]
        if not mailed:
            return
    await _mail_in(books, mailed, plan)


async def _left_part_way(
    books: Books, d: PlannedDoc, arrived: tuple[str, bytes] | None
) -> tuple[tuple[str, bytes] | None, bool]:
    """A resumed document with no proposal yet: where its file is now, and whether it was already recorded."""
    data = render_png(d.text)
    meta = await books.read_json(f"{DOCS}/{sha256_hex(data)}.json", None)
    if isinstance(meta, dict) and meta.get("filed_path") and await books.exists(meta["filed_path"]):
        return (meta["filed_path"], data), True  # filed and recorded; only the proposal is missing
    if arrived and await books.exists(arrived[0]):
        return arrived, False
    inbox = f"{INBOX}/{d.file_name}"
    if d.via != "mail" and await books.exists(inbox):
        return (inbox, data), False  # uploaded, not yet read
    doc = d.doc()
    folder, name = Books.filing_folder(doc), suggested_filename(doc, "image/png")
    stem = name.rsplit(".", 1)[0]
    for f in await books.list_files(folder):  # moved to its folder, then stopped before it was recorded
        same_name = f.name == name or f.name.startswith(f"{stem} (")
        if same_name and f.size in (0, len(data)) and await books.storage.read(f.path) == data:
            return (f.path, data), False
    return arrived, False  # nothing written yet


async def _step_document(books: Books, plan: Plan, d: PlannedDoc, resuming: bool) -> None:
    """Upload (or take from intake), propose, approve, as the person (or Autopilot) would."""
    arrived = await _mailed(books, d) if d.via == "mail" else None
    p = await _proposal_or_none(books, proposal_id(plan, d)) if resuming else None
    if p is None:
        again = False
        if resuming:
            arrived, again = await _left_part_way(books, d, arrived)
        p = await _propose(books, d, plan, arrived, again)
    if d.by == "autopilot":
        if p.status != "posted":
            p = await _autopilot(books, p, resuming)
        return
    edits = {"job_id": plan.jobs[d.job].id} if d.job else None
    if p.status != "posted":
        try:
            p = await approve(books, p.id, USER, edits, always=d.always, rebuild=False)
            return
        except ProposalStateError:
            if not resuming:
                raise
    await _finish_approval(books, p.id, USER, edits, d.always)  # resuming: posted, but the approval stopped part-way


async def _finish_approval(books: Books, pid: str, user: str, edits: dict[str, Any] | None, always: bool) -> None:
    """What approve() does after posting the entry, for an approval that stopped part-way (the entry is in the
    ledger, its proposal is still open, or an Always-do-this rule was not saved). Raises if nothing was posted."""
    from app import approve as approve_mod

    p = await books.get_proposal(pid)
    event = await books.get_event(p.event_id or p.id)  # FileNotFoundError: the approval never posted
    actor = approve_mod._actor(user)
    if p.status != "posted":
        if edits and "job_id" in edits:
            p.job_id = edits["job_id"]
        p.status, p.event_id, p.decided_by, p.decided_at = "posted", event.id, user, now()
        await books.save_proposal(p)
        await contacts_mod.learn_from_approval(books, p, actor, False)
        await books.audit(actor, "approved", {"proposal": p.id, "event": event.id, "resumed": True})
    if always and not any(
        r.supplier_key == supplier_key(p.extracted.supplier_name) for r in await autopilot.load_rules(books)
    ):
        await approve_mod._remember(books, p, user)
        if auto_rule := autopilot.rule_from_proposal(p, user):
            await autopilot.save_rule(books, auto_rule)


async def _autopilot(books: Books, p: Proposal, resuming: bool = False) -> Proposal:
    """What the scan does with a proposal from a supplier with an Autopilot rule (app/inbox.py)."""
    rule = autopilot.match(p, await autopilot.load_rules(books))
    p.autopilot = autopilot.evaluate(p, rule, True, await books.list_proposals())
    await books.save_proposal(p)
    if rule is None or not p.autopilot.auto_approve:
        raise RuntimeError(f"Autopilot would not post {p.extracted.supplier_name}: {p.autopilot.reasons}")
    posted = await inbox_mod._autopilot_post(books, p, rule)
    if posted.status != "posted" and resuming and await _event_exists(books, p.id):
        await _finish_approval(books, p.id, autopilot.AUTOPILOT, None, False)
        await autopilot.record_hit(books, rule.supplier_key)
        posted = await books.get_proposal(p.id)
    if posted.status != "posted":
        raise RuntimeError(f"Autopilot could not post {p.extracted.supplier_name}")
    return posted


async def _customer_ids(books: Books, plan: Plan) -> dict[str, str]:
    book = await contacts_mod.stored_contacts(books)
    ids: dict[str, str] = {}
    for name in plan.customers:
        c = contacts_mod.find(book, supplier_key(name), None)
        if c is None:
            raise RuntimeError(f"{name} is not in the contact book")
        ids[name] = c.id
    return ids


async def _step_contacts(books: Books, plan: Plan) -> None:
    await contacts_mod.refresh(books, USER)
    ids = await _customer_ids(books, plan)
    for name, edits in plan.customers.items():
        await contacts_mod.edit(books, ids[name], edits, USER)
    for k, j in plan.jobs.items():
        await jobs.save_job(books, j.model_copy(update={"customer_id": ids[plan.job_customers[k]]}))


async def _rewind(books: Books, sequence: str, number: str) -> None:
    """A resumed seed whose number was taken but whose invoice (or credit note) was never saved: give the number
    back, so the folder's sequence matches the plan (the bank statement quotes the invoice numbers)."""
    n = int(number.rsplit("-", 1)[1])
    await books._update_json(sequence, {}, lambda s: {**s, "next": n} if int(s.get("next", 1)) > n else s)


async def _step_invoices(books: Books, plan: Plan, sender: NotEmailed, resuming: bool) -> None:
    ids = await _customer_ids(books, plan)
    profile = await invoicing.load_profile(books)
    for inv in plan.invoices:
        created: invoicing.Invoice | None = None
        if resuming:
            try:
                created = await invoicing.get_invoice(books, inv.number)
            except FileNotFoundError:
                await _rewind(books, invoicing.SEQUENCE, inv.number)
        if created is None:
            draft = invoicing.InvoiceDraft(
                customer=invoicing.InvoiceCustomer(
                    contact_id=ids.get(inv.customer), name=inv.customer, email=inv.email, address=inv.address
                ),
                issue_date=inv.issue,
                due_date=inv.due,
                lines=inv.lines,
                notes=LABEL,
            )
            created = await invoicing.create_invoice(books, draft, USER)
            if created.number != inv.number:  # the bank statement quotes the number the plan expected
                raise RuntimeError(f"Invoice numbered {created.number}, expected {inv.number}: is the folder fresh?")
        unfinished = not created.event_id or (created.timesheet_entry_ids() and not created.timesheets_marked)
        if created.status == "draft" or (created.status == "sent" and unfinished):  # a sent one: finishes posting
            await invoicing.send_invoice(books, sender, created.number, USER, render_invoice(created, profile))
        if inv.job:
            job = plan.jobs[inv.job]
            if resuming and (await jobs.get_job(books, job.id)).status == "closed":
                continue
            entries = [t.id for t in plan.timesheets if t.job_id == job.id]
            await jobs.mark_invoiced(books, entries, created.number)
            await books.audit(f"user:{USER}", "timesheets_invoiced", {"job": job.id, "invoice": created.number})
            await jobs.save_job(books, (await jobs.get_job(books, job.id)).model_copy(update={"status": "closed"}))


async def _step_credit_notes(books: Books, plan: Plan, resuming: bool) -> None:
    for cn in plan.credit_notes:
        if resuming:
            issued = [c for c in await credit_notes.list_credit_notes(books, cn.invoice) if c.status == "issued"]
            if issued:  # saved; post it if the post was cut short
                if issued[0].event_id and not await _event_exists(books, issued[0].event_id):
                    await credit_notes.post_credit_note(books, issued[0], USER)
                continue
            await _rewind(books, credit_notes.CN_SEQUENCE, "CN-0001")
        await credit_notes.create_credit_note(
            books,
            cn.invoice,
            credit_notes.CreditNoteDraft(
                lines=[credit_notes.CreditLineIn(line=cn.line, quantity=cn.quantity)],
                issue_date=cn.day,
                reason=f"{cn.reason} ({LABEL})",
            ),
            USER,
        )
    if any(i.email for i in plan.invoices):
        await contacts_mod.refresh(books, USER)  # the customers first met on an invoice


async def _step_mileage_claim(books: Books, plan: Plan, resuming: bool) -> None:
    if not plan.claim_journeys():
        return
    ty, quarter = mileage.tax_year_of(plan.claim_day), mileage.quarter_of(plan.claim_day)
    if resuming:
        claims = [
            c for c in await mileage.mileage_claims(books, ty) if c.mileage_claim and c.mileage_claim.period == quarter
        ]
        if any(c.status == "posted" for c in claims):
            return
    claim, _ = await mileage.propose_allowance(books, ty, quarter, today=plan.claim_day)
    try:
        await approve(books, claim.id, USER, rebuild=False)
    except ProposalStateError:
        if not resuming:
            raise
        await _finish_approval(books, claim.id, USER, None, False)


async def _step_statements(books: Books, plan: Plan) -> None:
    if plan.bank_rules:  # saving the rules again replaces them; a statement imported again changes nothing
        await bank_rules.save_bank_rules(books, plan.bank_rules)
        await books.audit(f"user:{USER}", "bank_rules_saved", {"rules": [r.id for r in plan.bank_rules]})
    for name, data in plan.statements:
        await books.import_bank_csv(data, name, USER)


def bank_reconcile_model() -> str:
    from app.bank_actions import MODEL as CODED_FROM_A_LINE

    return CODED_FROM_A_LINE


def _line_for(lines: list[Any], day: date, pence: int, reference: str) -> Any:
    return next(ln for ln in lines if (ln.date, ln.amount_pence, ln.reference) == (day, pence, reference))


def _bill_events(plan: Plan) -> dict[str, str]:
    """Supplier's invoice number -> its entry. An entry approved from a proposal has the proposal's id."""
    return {
        d.extracted["invoice_number"]: proposal_id(plan, d)
        for d in plan.posted + plan.supplier_docs
        if d.extracted.get("invoice_number") and d.extracted["doc_type"] != "sales_invoice"
    }


def _sale_events(plan: Plan) -> dict[str, str]:
    """Invoice number on a gold sales invoice -> its entry."""
    return {
        d.extracted["invoice_number"]: proposal_id(plan, d)
        for d in plan.posted + plan.supplier_docs
        if d.extracted.get("invoice_number") and d.extracted["doc_type"] == "sales_invoice"
    }


async def _step_payments(books: Books, plan: Plan, resuming: bool) -> None:
    lines = await books.stored_bank_lines()
    todo: list[tuple[Any, PlannedInvoice | None, PlannedPayment]] = [
        (_line_for(lines, pay.day, pay.pence, pay.reference), inv, pay) for inv in plan.invoices for pay in inv.payments
    ]
    if (b := plan.bill_payment) is not None:
        todo.append((_line_for(lines, b.day, b.pence, b.reference), None, b))
    if resuming:
        todo = [t for t in todo if not await _payment_resumed(books, plan, *t)]
    for line, inv, pay in todo:
        if inv is None:  # Contacts → Bills to pay → Record payment
            await payments.record_payment(
                books,
                payments.PaymentIn(
                    side="purchase",
                    amount_pence=-pay.pence,
                    reference=pay.reference,
                    allocations=[
                        payments.AllocationIn(event_id=_bill_events(plan)[pay.reference], amount_pence=-pay.pence)
                    ],
                    bank_line_id=line.id,
                ),
                USER,
            )
        elif pay.how == "exact":  # Bank → Reconcile: the exact invoice match, then Post as payment
            if not (resuming and (await books.find_bank_line(line.id)).status == "matched"):
                await bank_reconcile.approve_line(books, line.id, "exact", USER)
            await payments.payment_from_bank_line(books, line.id, USER)
        else:  # Invoices → Record payment, with the statement line
            await invoicing.mark_paid(books, inv.number, USER, bank_line_id=line.id)
    if resuming:  # what record_payment / mark_paid do last, for a payment cut short after it was saved
        await payments.sync_invoices(books, {i.event_id for i in await invoicing.list_invoices(books) if i.event_id})
        for line, inv, _pay in _invoice_payments(plan, lines):
            if inv is not None:
                saved = await invoicing.get_invoice(books, inv.number)
                if saved.bank_line_id is None and saved.status in ("sent", "paid"):
                    found = await books.find_bank_line(line.id)
                    if found.resolved:
                        saved.bank_line_id, saved.payment_ref = line.id, saved.payment_ref or line.reference
                        await invoicing.save_invoice(books, saved)


def _invoice_payments(plan: Plan, lines: list[Any]) -> list[tuple[Any, PlannedInvoice | None, PlannedPayment]]:
    return [(_line_for(lines, p.day, p.pence, p.reference), i, p) for i in plan.invoices for p in i.payments]


async def _payment_resumed(
    books: Books, plan: Plan, line: Any, inv: PlannedInvoice | None, pay: PlannedPayment
) -> bool:
    """A resumed Payments step: True when this payment is (now) in the books. A payment recorded before the seed
    stopped is left as it is, its bank line matched if that was cut short; an entry posted without its record (the
    seed stopped between the two writes) gets its record, rather than a second entry."""
    from app.settlement import PAYMENTS, Allocation, PaymentRecord, load_records

    records = await load_records(books)
    rec = next((r for r in records if r.bank_line_id == line.id and r.removed_at is None), None)
    if rec is not None:
        if rec.event_id and not (await books.find_bank_line(line.id)).resolved:
            await books.confirm_match(line.id, [rec.event_id], USER)
        return True
    recorded = {r.event_id for r in records}
    amount = abs(line.amount_pence)
    orphan = next(
        (
            e
            for e in await books.list_events(line.date, line.date)
            if e.kind == "bank"
            and e.id not in recorded
            and e.approved_by == USER
            and any(ln.memo and ln.memo.startswith("Payment") for ln in e.lines)
            and sum(ln.debit for ln in e.lines) == amount
        ),
        None,
    )
    if orphan is None:
        return False
    if inv is None:
        side, target, applied = "purchase", _bill_events(plan)[pay.reference], amount
    else:
        saved = await invoicing.get_invoice(books, inv.number)
        side, target, applied = "sale", saved.event_id or "", min(amount, inv.total_pence)
    if (await books.find_bank_line(line.id)).status == "matched":  # the exact match before Post as payment
        await books.unmatch(line.id, USER)
    record = PaymentRecord(
        id=_hex(orphan.id, "record", n=16),
        side=side,  # type: ignore[arg-type]
        date=line.date,
        amount_pence=amount,
        reference=line.reference,
        counterparty=orphan.counterparty or line.description,
        allocations=[Allocation(event_id=target, amount_pence=applied)],
        event_id=orphan.id,
        bank_line_id=line.id,
        created_by=USER,
        created_at=now(),
    )
    await books._update_json(PAYMENTS, [], lambda rows: [*(rows or []), record.model_dump(mode="json")])
    await books.confirm_match(line.id, [orphan.id], USER)
    await books.audit(
        f"user:{USER}", "payment_recorded", {"payment": record.id, "event": orphan.id, "bank_line": line.id}
    )
    return True


async def _step_reconcile(books: Books, plan: Plan, resuming: bool) -> None:
    sales = _sale_events(plan)
    older_end = plan.periods[0][1]
    by_id = {ln.id: ln for ln in await books.stored_bank_lines()}
    for m in await books.bank_suggestions():  # the older statement is reconciled; the newer one is left to confirm
        if by_id[m.line_id].date <= older_end:
            await books.confirm_match(m.line_id, m.event_ids, USER)
    for ln in await books.stored_bank_lines():  # a customer payment the matcher could not place: matched by hand
        if ln.date <= older_end and ln.status == "unmatched" and ln.reference in sales:
            await books.confirm_match(ln.id, [sales[ln.reference]], USER)
    if not plan.bank_rules:
        return
    coding = (
        {p.doc_sha256: p for p in await books.list_proposals() if p.model == bank_reconcile_model()} if resuming else {}
    )
    for ln in await books.stored_bank_lines():  # Reconcile: every line a rule codes, approved
        if ln.resolved:
            continue
        coded = coding.get(hashlib.sha256(f"bank-line:{ln.id}".encode()).hexdigest()) if resuming else None
        if coded is not None:  # coded before the seed stopped: finish that, don't code it twice
            if coded.status != "posted":
                if ln.proposal_id != coded.id:
                    await books.link_proposal(ln.id, coded.id)
                try:
                    account = coded.account_override
                    coded = await approve(
                        books, coded.id, USER, {"account": account} if account else None, rebuild=False
                    )
                except ProposalStateError:
                    await _finish_approval(books, coded.id, USER, None, False)
                    coded = await books.get_proposal(coded.id)
            if coded.event_id:
                await books.confirm_match(ln.id, [coded.event_id], USER)
        elif await bank_reconcile.suggest_rule(books, ln):
            coded = await bank_reconcile.approve_line(books, ln.id, "rule", USER)
            # Approving posts the entry and matches the line to it (app/bank_reconcile.py); should it ever leave
            # the line open, the Bank page would suggest the line to the entry and the user would confirm that.
            if not (await books.find_bank_line(ln.id)).resolved:
                await books.confirm_match(ln.id, [coded["event_id"]], USER)
        elif ln.description == "Savings Space":  # the tax pot: money between own accounts
            await books.mark_line(ln.id, "transfer", USER)


async def _step_payroll_todos(books: Books, plan: Plan) -> None:
    if plan.payroll_period:  # replaces a draft, so it is safe to prepare again
        await payroll_mod.prepare(books, plan.payroll_period, None, USER)
    for t in plan.todos:  # an identical to-do already on the list is left as it is
        await todos_mod.add_todo(books, t, USER)


async def _step_inbox(books: Books, plan: Plan) -> None:
    for d in plan.inbox:  # same name, same bytes: writing again changes nothing
        await _upload(books, d)


async def _rebuild(books: Books) -> None:
    await Books.rebuild(books)


async def _step_reports(books: Books, plan: Plan, resuming: bool) -> None:
    if resuming and any(f.name.endswith(".xlsx") for f in await books.list_files(REPORTS)):
        return
    await routes_reports.export(
        body=routes_reports.ExportBody.model_validate({"report": "all"}),
        today=plan.today,
        cycle=VatCycle(start_month=plan.current[0].month),
        books=books,
        user=USER,
    )


async def _report(books: Books, plan: Plan, *, emails: int = 0, already_seeded: bool = False) -> dict[str, Any]:
    lines = await books.stored_bank_lines()
    return {
        "events": len(await books.list_events()),
        "inbox": len(await books.list_files(INBOX)),
        "invoices": [i.number for i in plan.invoices],
        "bank_lines": len(lines),
        "reconciled_to": reconciled_to(lines),
        "emails_not_sent": emails,
        "already_seeded": already_seeded,
    }


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
        hint = (
            " The token is wrong or has expired (they last about an hour): copy a fresh one."
            if exc.status in (401, 403)
            else ""
        )
        print(
            f"Microsoft Graph refused a request (HTTP {exc.status}).{hint} "
            "If the seed had started, the folder is part-filled: "
            "run again with --wipe.",
            file=sys.stderr,
        )
        return 1


async def _seed_graph(args: argparse.Namespace, plan: Plan, token: str) -> int:
    from accnomos_connectors.msgraph import GraphStorageProvider

    async with GraphStorageProvider(token, args.account) as storage:
        root = await storage.ensure_root()
        print(f"Books folder: {storage._root_drive_path or root.name}")
        if not root_is_accnomos(args.account, root.name):
            print(
                "That is not the Accnomos folder: for a personal account the app folder belongs to the app that "
                f"issued the token ({root.name!r} here). Copy the token from the Accnomos web app instead "
                "(tools/seed_demo.md).",
                file=sys.stderr,
            )
            return 1
        if args.wipe and not await _wipe(storage):
            print("Nothing changed.")
            return 1
        state = await seed_state(Books(storage))
        if state == "complete":
            print("This folder is already seeded to the end: nothing to do.")
            return 0
        if state != "empty":
            what = "was seeded part-way" if state == "partial" else "already has ledger entries"
            print(f"This folder {what}. Use a fresh account, or --wipe.", file=sys.stderr)
            return 1
        print(describe(plan) + "\n")
        report = await seed(storage, plan)
    print(
        f"Done: {report['events']} ledger events, {report['inbox']} documents waiting in {INBOX}, "
        f"invoices {', '.join(report['invoices'])}, {report['bank_lines']} bank lines. No email was sent."
    )
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
