"""Construction Industry Scheme (CIS): the subcontractor side first, then the contractor's monthly return (CIS300).

Every rule below was checked on GOV.UK on 28 Oct 2026 (through a page reader; www.gov.uk itself is blocked from the
build container), and is written in one place:

* Deduction rates: 20% for registered subcontractors ("net payment status"), 30% for unregistered or unverified
  ones, 0% with gross payment status.
  https://www.gov.uk/what-you-must-do-as-a-cis-contractor/print (section 5) and
  https://www.gov.uk/what-you-must-do-as-a-cis-subcontractor/print (section 3).
* What is deducted from: the gross invoice less VAT, consumable stores, fuel (except for travelling), plant hire,
  manufacturing or prefabricating materials and materials the subcontractor paid for directly; travel and
  subsistence stay in. CIS 340 paragraphs 2.17, 3.11-3.14,
  https://www.gov.uk/government/publications/construction-industry-scheme-cis-340/construction-industry-scheme-a-guide-for-contractors-and-subcontractors-cis-340.
  Here a line ticked "materials" is the excluded part; every other line is labour.
* Rounding: neither page says how to round a deduction that is not a whole number of pence. We round DOWN to the
  penny (`deduction`), so we never withhold more than the rate; the contractor's statement is the figure that
  counts and a difference of a penny is shown, not refused.
* Tax months run from the 6th of one month to the 5th of the next. Payment and deduction statements are due within
  14 days of the end of the tax month (the 19th); the monthly return (CIS300) must reach HMRC by the 19th; the
  deductions are paid to HMRC by the 22nd (19th by post). Contractor guide sections 5-7 (URL above).
* The CIS300 holds, per subcontractor paid in the month: name, UTR, the verification number (only needed where the
  higher rate was deducted), total payments excluding VAT and CITB levy, the cost of materials, and the amount
  deducted; a nil return when nothing was paid; and a declaration that the subcontractors are not employees. No
  negative values when filed by software (put 0). HMRC manual CISR61190-CISR61230,
  https://www.gov.uk/hmrc-internal-manuals/construction-industry-scheme-reform/cisr61220.
* Year end, sole trader or partner: turnover before CIS deductions, and the total deductions in the CIS box:
  SA103S boxes 9 and 38, SA103F boxes 15 and 81 (2026 notes,
  https://assets.publishing.service.gov.uk/media/69ce15395cf899414a0bc69f/SA103S_Notes_2026.pdf and
  https://assets.publishing.service.gov.uk/media/69c26565cfa346b9d4704b35/SA103F_Notes_2026.pdf); a contractor's
  payments to subcontractors are SA103F box 18. Limited company: the year-to-date CIS deductions go on the
  Employer Payment Summary (EPS) beside the FPS and are set against PAYE; "Do not use your Corporation Tax return to
  pay tax with your deductions" (subcontractor guide section 4).

Direct online submission of the CIS300 is out of scope: Accnomos prepares the figures and a file, and the user
files through HMRC's CIS online service or commercial CIS software. Verification of subcontractors is also done
there; the verification number is typed in here.

Postings, by code, all integer pence:

    subcontractor, paid net of a deduction:  Dr 1200 Bank (net) + Dr 1150 CIS suffered (deduction) / Cr 1100 Debtors
                                             (app/payments.py, `cis_deduction_pence`)
    contractor, paying a subcontractor:      Dr 5300 Subcontractors (gross, ex VAT) [+ Dr 2200 VAT]
                                             / Cr 1200 Bank (paid) + Cr 2220 CIS deductions owed (deduction)
                                             or, against a bill already in the books, Dr 2100 Creditors instead
    reverse-charge bill from a subcontractor: Dr 5300 Subcontractors (net) / Cr 2100 Creditors, with
                                             `reverse_charge_vat` (boxes 1 and 4, accnomos_ledger.vat)

Files, all in the user's own folder:

    _System/CIS/settings.json          CIS registration (status, UTRs, references)
    _System/CIS/statements.json        payment and deduction statements received from contractors, approved
    _System/CIS/readings/<id>.json     documents the user's AI read (statements, reverse-charge bills), waiting for
                                       the user (app/ai/cis_read.py proposes; the user approves)
    _System/CIS/subcontractors.json    the contractor's subcontractors (names, UTRs, verification numbers)
    _System/CIS/payments.json          the contractor's payments to subcontractors
    07 Reports/CIS/CIS300 <yyyy-mm-dd>.csv / .json   a prepared monthly return (the tax month's end date)
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app import paths
from app.books import SYSTEM, Books, now
from app.journal import BANK, CASH, CREDITORS, DEBTORS, VAT_CONTROL
from app.taxyear import uk_tax_year_start
from app.validation import LENIENT, Day, Pence, StrictBody

CIS_DIR = f"{SYSTEM}/CIS"
SETTINGS = f"{CIS_DIR}/settings.json"
STATEMENTS = f"{CIS_DIR}/statements.json"
READINGS = f"{CIS_DIR}/readings"
SUBCONTRACTORS = f"{CIS_DIR}/subcontractors.json"
CONTRACTOR_PAYMENTS = f"{CIS_DIR}/payments.json"
RETURNS_FOLDER = f"{paths.REPORTS}/CIS"

CIS_SUFFERED = "1150 CIS suffered"  # an asset: tax paid on account, set against the year's tax (or PAYE, for a company)
CIS_OWED = "2220 CIS deductions owed"  # a liability: deductions the contractor must pay HMRC by the 22nd
SUBCONTRACTORS_ACCOUNT = "5300 Subcontractors"

Status = Literal["gross", "net", "unverified"]
Entity = Literal["sole_trader", "partnership", "company"]
RATES: dict[str, int] = {"gross": 0, "net": 20, "unverified": 30}
STATUS_LABELS = {
    "gross": "Gross payment status (0%)",
    "net": "Registered, net payment status (20%)",
    "unverified": "Not registered or not verified (30%)",
}
SOURCE_URL = "https://www.gov.uk/what-you-must-do-as-a-cis-contractor/print"
CHECKED = "28 Oct 2026"
NOT_SUBMITTED = (
    "Accnomos does not submit CIS returns. File this return through HMRC's CIS online service or commercial CIS "
    "software by the 19th; pay the deductions to HMRC by the 22nd."
)
DECLARATION = (
    "On the return you must declare that the subcontractors listed are not employees, and that you verified any "
    "subcontractor who needed verifying."
)
UTR_RE = re.compile(r"\d{10}")
VERIFICATION_RE = re.compile(r"V\d{10}[A-Z]{0,2}", re.I)  # HMRC prints e.g. V1234567890 (higher rate adds letters)
PENNY = 1


class CisError(ValueError):
    """The CIS action cannot be done as asked (a 400)."""


def _digits(v: str | None) -> str | None:
    d = re.sub(r"\D", "", v or "")
    return d or None


def _utr(v: str | None) -> str | None:
    d = _digits(v)
    if d and not UTR_RE.fullmatch(d):
        raise ValueError("A UTR has 10 digits")
    return d


def money(p: int) -> str:
    sign = "-" if p < 0 else ""
    pounds, pennies = divmod(abs(p), 100)
    return f"{sign}£{pounds:,}.{pennies:02d}"


# --------------------------------------------------------------------------- #
# Rules: rates, deductions, tax months
# --------------------------------------------------------------------------- #


def rate_for(status: Status) -> int:
    return RATES[status]


def deduction(liable_pence: int, rate: int) -> int:
    """The deduction on the part of a payment that is not materials, rounded down to the penny (see the docstring)."""
    if liable_pence <= 0 or rate <= 0:
        return 0
    return liable_pence * rate // 100


def tax_month(day: date) -> tuple[date, date]:
    """(6th, 5th) of the tax month `day` falls in."""
    start = date(day.year, day.month, 6) if day.day >= 6 else _month_back(date(day.year, day.month, 6))
    end = _month_on(start) - timedelta(days=1)
    return start, end


def _month_on(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, d.day)


def _month_back(d: date) -> date:
    return date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, d.day)


def tax_month_of_end(end: date) -> tuple[date, date]:
    """The tax month ending on `end` (which must be a 5th)."""
    if end.day != 5:
        raise CisError("A tax month ends on the 5th, e.g. 2026-11-05")
    return tax_month(end)


def return_due(end: date) -> date:
    """The CIS300 and the statements are due on the 19th of the month the tax month ends in."""
    return date(end.year, end.month, 19)


def payment_due(end: date) -> date:
    """Deductions reach HMRC by the 22nd (electronic; the 19th by post)."""
    return date(end.year, end.month, 22)


def tax_year_label(day: date) -> str:
    start = uk_tax_year_start(day)
    return f"{start.year}-{(start.year + 1) % 100:02d}"


def tax_year_bounds(label: str) -> tuple[date, date]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", label)
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise CisError("A tax year is written like 2026-27")
    y = int(m.group(1))
    return date(y, 4, 6), date(y + 1, 4, 5)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


class CisSettings(StrictBody):
    """Settings › CIS. Stored in _System/CIS/settings.json."""

    subcontractor: bool = False  # the business works for contractors under CIS
    status: Status = "net"  # its payment status, as HMRC told its contractors on verification
    utr: str | None = Field(None, max_length=20)  # the business's own UTR (as on statements)
    entity: Entity = "sole_trader"
    contractor: bool = False  # the business pays subcontractors and files CIS300 returns
    contractor_utr: str | None = Field(None, max_length=20)
    accounts_office_ref: str | None = Field(None, max_length=20)  # e.g. 123PA00045678
    employer_ref: str | None = Field(None, max_length=20)  # e.g. 123/AB45678
    reverse_charge_default: bool = False  # new invoices to VAT- and CIS-registered customers start reverse-charged

    @field_validator("utr", "contractor_utr")
    @classmethod
    def _check_utr(cls, v: str | None) -> str | None:
        return _utr(v)

    @field_validator("accounts_office_ref", "employer_ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper()
        if v and not re.fullmatch(r"[0-9A-Z/ ]{3,20}", v):
            raise ValueError("Use letters, digits and / only, as on HMRC's letter")
        return v or None

    @property
    def rate(self) -> int:
        return rate_for(self.status)


async def load_settings(books: Books) -> CisSettings:
    return CisSettings.model_validate(await books.read_json(SETTINGS, {}), **LENIENT)


async def save_settings(books: Books, settings: CisSettings, user: str) -> CisSettings:
    payload = settings.model_dump(mode="json")
    await books._update_json(SETTINGS, {}, lambda _old: payload)
    await books.audit(f"user:{user}", "cis_settings_saved", {"path": SETTINGS, "status": settings.status})
    return settings


# --------------------------------------------------------------------------- #
# On an invoice or quote: the deduction on labour only
# --------------------------------------------------------------------------- #


class CisOnInvoice(BaseModel):
    """The CIS part of an invoice or quote, worked out by code from its lines (net, before VAT)."""

    status: Status
    rate: int
    labour_pence: int  # every line not ticked materials (travel and subsistence count as labour)
    materials_pence: int
    deduction_pence: int  # deducted by the contractor and paid to HMRC on the business's behalf
    payable_pence: int  # the invoice total less the deduction: what the contractor should pay


def cis_on_invoice(lines: list[tuple[int, bool]], total_pence: int, status: Status) -> CisOnInvoice:
    """`lines` are (net pence, is materials). VAT never enters the deduction (CIS 340 3.12)."""
    labour = sum(net for net, materials in lines if not materials)
    materials = sum(net for net, materials in lines if materials)
    rate = rate_for(status)
    cut = deduction(labour, rate)
    return CisOnInvoice(
        status=status,
        rate=rate,
        labour_pence=labour,
        materials_pence=materials,
        deduction_pence=cut,
        payable_pence=total_pence - cut,
    )


def max_deduction(cis: CisOnInvoice) -> int:
    """The most a contractor can rightly deduct from this invoice: the higher rate on its labour."""
    return deduction(cis.labour_pence, RATES["unverified"])


# --------------------------------------------------------------------------- #
# Subcontractor side: statements received from contractors
# --------------------------------------------------------------------------- #


class StatementIn(StrictBody):
    """A monthly payment and deduction statement, typed in or read by the user's AI."""

    contractor_name: str = Field(min_length=1, max_length=200)
    contractor_ref: str | None = Field(None, max_length=20)  # the contractor's employer (PAYE) reference
    tax_month_end: Day  # the 5th that ends the tax month
    gross_pence: Pence = Field(ge=0, le=10_000_000_000)  # gross amount paid, excluding VAT
    materials_pence: Pence = Field(0, ge=0, le=10_000_000_000)
    deduction_pence: Pence = Field(ge=0, le=10_000_000_000)
    subcontractor_utr: str | None = Field(None, max_length=20)
    verification_number: str | None = Field(None, max_length=20)
    document: str | None = Field(None, max_length=400)  # the file in the books the figures came from

    @field_validator("subcontractor_utr")
    @classmethod
    def _check_utr(cls, v: str | None) -> str | None:
        return _utr(v)

    @model_validator(mode="after")
    def _sums(self) -> StatementIn:
        if self.materials_pence > self.gross_pence:
            raise ValueError("Materials cannot be more than the gross amount paid")
        if self.deduction_pence > self.gross_pence - self.materials_pence:
            raise ValueError("The deduction cannot be more than the amount liable to deduction")
        return self


class Check(BaseModel):
    code: str
    ok: bool
    message: str


class Statement(StatementIn):
    id: str
    source: Literal["typed", "read"] = "typed"
    reading_id: str | None = None
    approved_by: str
    approved_at: datetime

    @property
    def liable_pence(self) -> int:
        return self.gross_pence - self.materials_pence

    @property
    def net_paid_pence(self) -> int:
        return self.gross_pence - self.deduction_pence


def statement_checks(s: StatementIn, settings: CisSettings) -> list[Check]:
    """Code checks on a statement's figures. A failed check is a warning on the card, never a silent fix."""
    out: list[Check] = []
    out.append(
        Check(
            code="TAX_MONTH",
            ok=s.tax_month_end.day == 5,
            message="Tax month ends on the 5th"
            if s.tax_month_end.day == 5
            else f"A tax month ends on the 5th; the statement says {s.tax_month_end:%d/%m/%Y}",
        )
    )
    liable = s.gross_pence - s.materials_pence
    fits = [r for r in (0, 20, 30) if abs(deduction(liable, r) - s.deduction_pence) <= PENNY]
    expected = deduction(liable, settings.rate)
    if settings.rate in fits:
        out.append(Check(code="RATE", ok=True, message=f"Deduction is {settings.rate}% of {money(liable)}"))
    elif fits:
        out.append(
            Check(
                code="RATE",
                ok=False,
                message=f"Deduction matches {fits[0]}%, not your {settings.rate}% ({STATUS_LABELS[settings.status]}); "
                "check your status with the contractor",
            )
        )
    else:
        out.append(
            Check(
                code="RATE",
                ok=False,
                message=f"Deduction {money(s.deduction_pence)} is not 0%, 20% or 30% of {money(liable)} "
                f"(at your rate it would be {money(expected)})",
            )
        )
    if settings.utr and s.subcontractor_utr and s.subcontractor_utr != settings.utr:
        out.append(Check(code="UTR", ok=False, message="The UTR on the statement is not yours"))
    return out


async def statements(books: Books) -> list[Statement]:
    rows = await books.read_json(STATEMENTS, [])
    out = [Statement.model_validate(r, **LENIENT) for r in rows if isinstance(r, dict)]
    return sorted(out, key=lambda s: (s.tax_month_end, s.contractor_name.lower()))


def _same_statement(a: StatementIn, b: StatementIn) -> bool:
    return (
        a.contractor_name.strip().lower() == b.contractor_name.strip().lower()
        and a.tax_month_end == b.tax_month_end
        and a.gross_pence == b.gross_pence
        and a.deduction_pence == b.deduction_pence
    )


async def add_statement(
    books: Books,
    body: StatementIn,
    user: str,
    *,
    source: Literal["typed", "read"] = "typed",
    reading_id: str | None = None,
) -> Statement:
    """Keep an approved statement. The same statement twice (contractor, month, gross, deduction) is refused."""
    existing = await statements(books)
    if any(_same_statement(s, body) for s in existing):
        raise CisError(
            f"{body.contractor_name}'s statement for the month to {body.tax_month_end:%d/%m/%Y} is already in"
        )
    st = Statement(
        **body.model_dump(),
        id=uuid.uuid4().hex[:16],
        source=source,
        reading_id=reading_id,
        approved_by=user,
        approved_at=now(),
    )
    await books._update_json(STATEMENTS, [], lambda rows: [*(rows or []), st.model_dump(mode="json")])
    await books.audit(
        f"user:{user}",
        "cis_statement_added",
        {"statement": st.id, "contractor": st.contractor_name, "deduction_pence": st.deduction_pence, "source": source},
    )
    return st


async def remove_statement(books: Books, statement_id: str, user: str) -> None:
    rows = await books.read_json(STATEMENTS, [])
    if not any(isinstance(r, dict) and r.get("id") == statement_id for r in rows):
        raise FileNotFoundError(statement_id)
    await books._update_json(
        STATEMENTS,
        [],
        lambda rows: [r for r in rows or [] if not (isinstance(r, dict) and r.get("id") == statement_id)],
    )
    await books.audit(f"user:{user}", "cis_statement_removed", {"statement": statement_id})


def _name_key(name: str | None) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = re.sub(r"\b(ltd|limited|plc|llp|the|and|co)\b", " ", s)
    return " ".join(s.split())


def suffered_in(events: list[LedgerEvent], start: date, end: date) -> dict[str, int]:
    """CIS deductions posted to 1150 between `start` and `end`, by counterparty (reversals net off)."""
    out: dict[str, int] = defaultdict(int)
    for ev in events:
        if not start <= ev.date <= end:
            continue
        for ln in ev.lines:
            if ln.account == CIS_SUFFERED:
                out[ev.counterparty or "?"] += ln.debit - ln.credit
    return dict(out)


class StatementView(BaseModel):
    statement: Statement
    liable_pence: int
    net_paid_pence: int
    checks: list[Check]
    recorded_pence: int  # deductions recorded on payments from this contractor in the same tax month
    difference_pence: int  # statement minus recorded: what the books are missing (negative: recorded too much)


def statement_views(sts: list[Statement], events: list[LedgerEvent], settings: CisSettings) -> list[StatementView]:
    out = []
    for s in sts:
        start, end = tax_month(s.tax_month_end)
        recorded = sum(
            v for k, v in suffered_in(events, start, end).items() if _name_key(k) == _name_key(s.contractor_name)
        )
        out.append(
            StatementView(
                statement=s,
                liable_pence=s.liable_pence,
                net_paid_pence=s.net_paid_pence,
                checks=statement_checks(s, settings),
                recorded_pence=recorded,
                difference_pence=s.deduction_pence - recorded,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Year totals for the tax return
# --------------------------------------------------------------------------- #


class ContractorYear(BaseModel):
    contractor_name: str
    statements: int
    gross_pence: int
    materials_pence: int
    deduction_pence: int


class YearTotals(BaseModel):
    tax_year: str
    start: date
    end: date
    entity: Entity
    status: Status
    gross_pence: int  # from the statements: income before CIS deductions
    materials_pence: int
    deduction_pence: int  # from the statements: the CIS box
    recorded_pence: int  # deductions in the books (1150 CIS suffered) dated in the year
    difference_pence: int
    by_contractor: list[ContractorYear]
    months_missing: list[str]  # tax months (ending dates) with recorded deductions but no statement
    where_it_goes: list[str]
    paid_to_subcontractors_pence: int = 0  # contractor side: SA103F box 18
    deducted_from_subcontractors_pence: int = 0
    source_urls: list[str]


def year_totals(
    label: str,
    sts: list[Statement],
    events: list[LedgerEvent],
    settings: CisSettings,
    payments: list[ContractorPayment],
) -> YearTotals:
    start, end = tax_year_bounds(label)
    mine = [s for s in sts if start <= s.tax_month_end <= end]
    groups: dict[str, list[Statement]] = defaultdict(list)
    for s in mine:
        groups[s.contractor_name.strip()].append(s)
    by = [
        ContractorYear(
            contractor_name=name,
            statements=len(g),
            gross_pence=sum(s.gross_pence for s in g),
            materials_pence=sum(s.materials_pence for s in g),
            deduction_pence=sum(s.deduction_pence for s in g),
        )
        for name, g in sorted(groups.items(), key=lambda kv: kv[0].lower())
    ]
    recorded = sum(suffered_in(events, start, end).values())
    covered = {s.tax_month_end for s in mine}
    missing = sorted(
        {
            tax_month(ev.date)[1]
            for ev in events
            if start <= ev.date <= end and any(ln.account == CIS_SUFFERED and ln.debit for ln in ev.lines)
        }
        - covered
    )
    gross = sum(c.gross_pence for c in by)
    cut = sum(c.deduction_pence for c in by)
    if settings.entity == "company":
        where = [
            f"Limited company: put the year-to-date CIS deductions suffered ({money(cut)}) on your Employer Payment "
            "Summary (EPS), sent with your FPS; HMRC sets them against your PAYE bill. Do not use the Corporation "
            "Tax return to claim them.",
            f"Your turnover in the company accounts is the full amount before deductions ({money(gross)} on these "
            "statements).",
        ]
    else:
        where = [
            f"Self Assessment, short pages (SA103S): turnover in box 9 includes the full {money(gross)} before "
            f"deductions; box 38 is {money(cut)}.",
            f"Full pages (SA103F): box 15 turnover before deductions; box 81 is {money(cut)}.",
            "Keep the contractors' statements; do not send them with the return.",
        ]
    paid = [p for p in payments if not p.removed_at and start <= p.date <= end]
    return YearTotals(
        tax_year=label,
        start=start,
        end=end,
        entity=settings.entity,
        status=settings.status,
        gross_pence=gross,
        materials_pence=sum(c.materials_pence for c in by),
        deduction_pence=cut,
        recorded_pence=recorded,
        difference_pence=cut - recorded,
        by_contractor=by,
        months_missing=[d.isoformat() for d in missing],
        where_it_goes=where,
        paid_to_subcontractors_pence=sum(p.gross_pence for p in paid),
        deducted_from_subcontractors_pence=sum(p.deduction_pence for p in paid),
        source_urls=[
            "https://www.gov.uk/what-you-must-do-as-a-cis-subcontractor/print",
            "https://assets.publishing.service.gov.uk/media/69ce15395cf899414a0bc69f/SA103S_Notes_2026.pdf",
            "https://assets.publishing.service.gov.uk/media/69c26565cfa346b9d4704b35/SA103F_Notes_2026.pdf",
        ],
    )


# --------------------------------------------------------------------------- #
# Contractor side: subcontractors, payments, the monthly return
# --------------------------------------------------------------------------- #


class SubcontractorIn(StrictBody):
    name: str = Field(min_length=1, max_length=200)  # exactly as registered with HMRC
    trading_name: str | None = Field(None, max_length=200)
    kind: Entity = "sole_trader"
    utr: str = Field(max_length=20)
    status: Status = "net"  # what HMRC said on verification
    verification_number: str | None = Field(None, max_length=20)
    verified_on: Day | None = None
    vat_registered: bool = False

    @field_validator("utr")
    @classmethod
    def _check_utr(cls, v: str) -> str:
        return _utr(v) or ""

    @field_validator("verification_number")
    @classmethod
    def _vn(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper().replace(" ", "")
        if v and not VERIFICATION_RE.fullmatch(v):
            raise ValueError("A verification number looks like V1234567890 (letters after it at the higher rate)")
        return v or None

    @model_validator(mode="after")
    def _needs(self) -> SubcontractorIn:
        if not self.utr:
            raise ValueError("Add the subcontractor's UTR (10 digits)")
        return self


class Subcontractor(SubcontractorIn):
    id: str
    created_by: str
    created_at: datetime


async def subcontractors(books: Books) -> list[Subcontractor]:
    rows = await books.read_json(SUBCONTRACTORS, [])
    return [Subcontractor.model_validate(r, **LENIENT) for r in rows if isinstance(r, dict)]


async def save_subcontractor(
    books: Books, body: SubcontractorIn, user: str, sub_id: str | None = None
) -> Subcontractor:
    existing = await subcontractors(books)
    if any(s.utr == body.utr and s.id != sub_id for s in existing):
        raise CisError("A subcontractor with this UTR is already on the list")
    old = next((s for s in existing if s.id == sub_id), None) if sub_id else None
    if sub_id and old is None:
        raise FileNotFoundError(sub_id)
    sub = Subcontractor(
        **body.model_dump(),
        id=old.id if old else uuid.uuid4().hex[:12],
        created_by=old.created_by if old else user,
        created_at=old.created_at if old else now(),
    )
    row = sub.model_dump(mode="json")

    def change(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept = [r for r in rows or [] if not (isinstance(r, dict) and r.get("id") == sub.id)]
        return [*kept, row]

    await books._update_json(SUBCONTRACTORS, [], change)
    await books.audit(f"user:{user}", "cis_subcontractor_saved", {"subcontractor": sub.id, "status": sub.status})
    return sub


VatTreatment = Literal["reverse_charge", "standard", "none"]


class ContractorPaymentIn(StrictBody):
    """One payment to a subcontractor. Code works out the deduction from the subcontractor's status."""

    subcontractor_id: str = Field(max_length=12)
    date: Day
    gross_pence: Pence = Field(gt=0, le=10_000_000_000)  # the subcontractor's invoice excluding VAT
    materials_pence: Pence = Field(0, ge=0, le=10_000_000_000)  # materials they paid for directly, excluding VAT
    vat_treatment: VatTreatment = "reverse_charge"
    vat_rate: Literal[20, 5] = 20
    account: Literal["1200 Bank", "1210 Cash"] = "1200 Bank"
    bill_event_id: str | None = Field(None, pattern=r"^[0-9a-f]{8,64}$", max_length=64)  # the bill, if already posted
    reference: str | None = Field(None, max_length=120)

    @model_validator(mode="after")
    def _sums(self) -> ContractorPaymentIn:
        if self.materials_pence > self.gross_pence:
            raise ValueError("Materials cannot be more than the gross amount")
        return self


class ContractorPayment(BaseModel):
    id: str
    subcontractor_id: str
    subcontractor_name: str
    utr: str
    status: Status
    verification_number: str | None = None
    date: date
    gross_pence: int
    materials_pence: int
    rate: int
    deduction_pence: int
    vat_treatment: VatTreatment
    vat_rate: int = 20
    vat_pence: int  # VAT paid to the subcontractor (standard), or accounted for by us (reverse charge, not paid)
    paid_pence: int  # what left the bank
    account: str = BANK
    bill_event_id: str | None = None
    reference: str | None = None
    event_id: str | None = None
    payment_record_id: str | None = None  # app/payments.py's record, for a payment against a bill
    created_by: str
    created_at: datetime
    removed_at: datetime | None = None
    removed_by: str | None = None
    reversal_event_id: str | None = None


def contractor_payment_event(p: ContractorPayment, user: str) -> LedgerEvent:
    """The posting for a payment to a subcontractor with no bill in the books (see the module docstring): the cost,
    its VAT, the money paid and the deduction owed to HMRC, balanced by construction. A payment against a bill goes
    through app/payments.py instead, so the bill shows paid."""
    memo = f"CIS payment to {p.subcontractor_name}" + (f" ({p.reference})" if p.reference else "")
    code = VatCode.NO_VAT if p.vat_treatment == "none" else VatCode.REDUCED if p.vat_rate == 5 else VatCode.STANDARD
    lines = [Line(account=SUBCONTRACTORS_ACCOUNT, debit=p.gross_pence, vat_code=code, memo=memo)]
    if p.vat_treatment == "standard" and p.vat_pence:
        lines.append(Line(account=VAT_CONTROL, debit=p.vat_pence, vat_code=code, memo=memo))
    if p.paid_pence:
        lines.append(Line(account=p.account, credit=p.paid_pence, memo=memo))
    if p.deduction_pence:
        lines.append(Line(account=CIS_OWED, credit=p.deduction_pence, memo=memo))
    return LedgerEvent(
        id=_event_id(p.id),
        kind="purchase",
        date=p.date,
        lines=lines,
        approved_by=user,
        approved_at=now(),
        net=p.gross_pence if p.vat_treatment != "none" else 0,
        vat=p.vat_pence if p.vat_treatment == "standard" else 0,
        reverse_charge_vat=p.vat_pence if p.vat_treatment == "reverse_charge" else None,
        counterparty=p.subcontractor_name,
    )


def _event_id(payment_id: str) -> str:
    return hashlib.sha256(f"cis-payment:{payment_id}".encode()).hexdigest()[:32]


async def contractor_payments(books: Books) -> list[ContractorPayment]:
    rows = await books.read_json(CONTRACTOR_PAYMENTS, [])
    out = [ContractorPayment.model_validate(r, **LENIENT) for r in rows if isinstance(r, dict)]
    return sorted(out, key=lambda p: (p.date, p.created_at))


async def record_contractor_payment(books: Books, body: ContractorPaymentIn, user: str) -> ContractorPayment:
    settings = await load_settings(books)
    if not settings.contractor:
        raise CisError("Turn on 'We pay subcontractors (CIS contractor)' in Settings › CIS first")
    sub = next((s for s in await subcontractors(books) if s.id == body.subcontractor_id), None)
    if sub is None:
        raise CisError("No such subcontractor; add them first")
    if sub.status == "unverified" and not sub.verification_number:
        raise CisError("Deducting at 30% needs the verification number HMRC gave you for this subcontractor")
    rate = rate_for(sub.status)
    cut = deduction(body.gross_pence - body.materials_pence, rate)
    vat = 0
    if body.vat_treatment != "none":
        if not sub.vat_registered:
            raise CisError(f"{sub.name} is not VAT-registered on your list: choose 'No VAT'")
        vat = (body.gross_pence * body.vat_rate + 50) // 100  # half up to the penny, as invoices are priced
    bill_total = None
    if body.bill_event_id:
        try:
            bill = await books.get_event(body.bill_event_id)
        except FileNotFoundError as exc:
            raise CisError("No such bill in the books") from exc
        bill_total = sum(ln.credit for ln in bill.lines if ln.account == CREDITORS)
        if bill_total <= 0:
            raise CisError("That entry is not a bill on account (nothing owed in 2100 Creditors)")
        vat = bill.vat or bill.reverse_charge_vat or 0  # the bill's own VAT is already in the books
        paid = bill_total - cut
    else:
        paid = body.gross_pence + (vat if body.vat_treatment == "standard" else 0) - cut
    if paid <= 0:
        raise CisError("The deduction is as much as the payment; check the figures")
    p = ContractorPayment(
        id=uuid.uuid4().hex[:16],
        subcontractor_id=sub.id,
        subcontractor_name=sub.name,
        utr=sub.utr,
        status=sub.status,
        verification_number=sub.verification_number,
        date=body.date,
        gross_pence=body.gross_pence,
        materials_pence=body.materials_pence,
        rate=rate,
        deduction_pence=cut,
        vat_treatment=body.vat_treatment,
        vat_rate=body.vat_rate,
        vat_pence=vat,
        paid_pence=paid,
        account=body.account,
        bill_event_id=body.bill_event_id,
        reference=(body.reference or "").strip() or None,
        created_by=user,
        created_at=now(),
    )
    if bill_total is not None:
        from app import payments  # late: app.payments imports this module

        try:
            record = await payments.record_payment(
                books,
                payments.PaymentIn(
                    side="purchase",
                    date=p.date,
                    amount_pence=paid,
                    account=body.account,
                    reference=p.reference,
                    allocations=[payments.AllocationIn(event_id=body.bill_event_id or "", amount_pence=bill_total)],
                    bank_line_id=None,
                    cis_deduction_pence=cut,
                ),
                user,
            )
        except payments.InvoiceError as exc:
            raise CisError(str(exc)) from exc
        p.event_id, p.payment_record_id, path = record.event_id, record.id, None
    else:
        event = contractor_payment_event(p, user)
        p.event_id = event.id
        path = await books.post_event(event)
    await books._update_json(CONTRACTOR_PAYMENTS, [], lambda rows: [*(rows or []), p.model_dump(mode="json")])
    await books.audit(
        f"user:{user}",
        "cis_payment_recorded",
        {"payment": p.id, "event": p.event_id, "event_path": path, "deduction_pence": cut, "subcontractor": sub.id},
    )
    await books.rebuild_safely(f"user:{user}")
    return p


async def remove_contractor_payment(books: Books, payment_id: str, user: str) -> ContractorPayment:
    from app.approve import reversal_of  # late: app.approve is heavy and imports much of the app

    p = next((x for x in await contractor_payments(books) if x.id == payment_id), None)
    if p is None:
        raise FileNotFoundError(payment_id)
    if p.removed_at:
        raise CisError("This payment was already removed")
    if p.payment_record_id:
        from app import payments  # late: app.payments imports this module

        await payments.remove_payment(books, p.payment_record_id, user)
        rev_id = next(
            (r.reversal_event_id for r in await payments._records(books) if r.id == p.payment_record_id), None
        )
    else:
        rev = reversal_of(await books.get_event(p.event_id or ""), user)
        await books.post_event(rev)
        rev_id = rev.id
    stamp = now()

    def change(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for r in rows or []:
            if isinstance(r, dict) and r.get("id") == payment_id:
                r.update(removed_at=stamp.isoformat(), removed_by=user, reversal_event_id=rev_id)
        return rows

    await books._update_json(CONTRACTOR_PAYMENTS, [], change)
    await books.audit(f"user:{user}", "cis_payment_removed", {"payment": payment_id, "event": rev_id})
    await books.rebuild_safely(f"user:{user}")
    p.removed_at, p.removed_by, p.reversal_event_id = stamp, user, rev_id
    return p


class ReturnLine(BaseModel):
    subcontractor_name: str
    utr: str
    verification_number: str | None  # only where the higher rate was deducted (CISR61220)
    total_payments_pence: int  # excluding VAT
    materials_pence: int
    deduction_pence: int
    rate: int


class MonthlyReturn(BaseModel):
    """CIS300 data for one tax month."""

    tax_month_start: date
    tax_month_end: date
    return_due: date
    payment_due: date
    contractor_utr: str | None
    accounts_office_ref: str | None
    employer_ref: str | None
    nil_return: bool
    lines: list[ReturnLine]
    total_payments_pence: int
    total_materials_pence: int
    total_deductions_pence: int
    declaration: str = DECLARATION
    not_submitted: str = NOT_SUBMITTED
    problems: list[str]
    source_url: str = "https://www.gov.uk/hmrc-internal-manuals/construction-industry-scheme-reform/cisr61220"


def monthly_return(end: date, settings: CisSettings, payments: list[ContractorPayment]) -> MonthlyReturn:
    start, end = tax_month_of_end(end)
    live = [p for p in payments if not p.removed_at and start <= p.date <= end]
    by: dict[str, list[ContractorPayment]] = defaultdict(list)
    for p in live:
        by[p.utr].append(p)
    lines = []
    for utr, ps in sorted(by.items(), key=lambda kv: kv[1][0].subcontractor_name.lower()):
        last = ps[-1]
        higher = any(p.rate == RATES["unverified"] for p in ps)
        lines.append(
            ReturnLine(
                subcontractor_name=last.subcontractor_name,
                utr=utr,
                verification_number=last.verification_number if higher else None,
                total_payments_pence=max(0, sum(p.gross_pence for p in ps)),  # software returns: never negative
                materials_pence=max(0, sum(p.materials_pence for p in ps)),
                deduction_pence=max(0, sum(p.deduction_pence for p in ps)),
                rate=last.rate,
            )
        )
    problems = []
    if not settings.contractor_utr:
        problems.append("Add your contractor UTR in Settings › CIS")
    if not settings.accounts_office_ref:
        problems.append("Add your Accounts Office reference in Settings › CIS")
    for ln in lines:
        if ln.rate == RATES["unverified"] and not ln.verification_number:
            problems.append(f"{ln.subcontractor_name}: a 30% deduction needs its verification number")
    return MonthlyReturn(
        tax_month_start=start,
        tax_month_end=end,
        return_due=return_due(end),
        payment_due=payment_due(end),
        contractor_utr=settings.contractor_utr,
        accounts_office_ref=settings.accounts_office_ref,
        employer_ref=settings.employer_ref,
        nil_return=not lines,
        lines=lines,
        total_payments_pence=sum(ln.total_payments_pence for ln in lines),
        total_materials_pence=sum(ln.materials_pence for ln in lines),
        total_deductions_pence=sum(ln.deduction_pence for ln in lines),
        problems=problems,
    )


def _pounds(p: int) -> str:
    return f"{p // 100}.{p % 100:02d}"


def return_csv(ret: MonthlyReturn, sample: bool = False) -> str:
    """The return as a CSV a person can type into HMRC's CIS online service (or import into CIS software)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if sample:
        w.writerow(["SAMPLE — FICTIONAL COMPANY"])
    w.writerow(["CIS300 monthly return (prepared by Accnomos; NOT submitted to HMRC)"])
    w.writerow(["Tax month", f"{ret.tax_month_start:%d/%m/%Y} to {ret.tax_month_end:%d/%m/%Y}"])
    w.writerow(["Return due", f"{ret.return_due:%d/%m/%Y}", "Deductions payable by", f"{ret.payment_due:%d/%m/%Y}"])
    w.writerow(["Contractor UTR", ret.contractor_utr or "", "Accounts Office reference", ret.accounts_office_ref or ""])
    w.writerow(["Employer reference", ret.employer_ref or ""])
    w.writerow(["Nil return", "yes" if ret.nil_return else "no"])
    w.writerow([])
    w.writerow(
        [
            "Subcontractor name",
            "UTR",
            "Verification number",
            "Total payments (excl VAT) £",
            "Cost of materials £",
            "Amount deducted £",
            "Rate %",
        ]
    )
    for ln in ret.lines:
        w.writerow(
            [
                _inert(ln.subcontractor_name),
                ln.utr,
                ln.verification_number or "",
                _pounds(ln.total_payments_pence),
                _pounds(ln.materials_pence),
                _pounds(ln.deduction_pence),
                ln.rate,
            ]
        )
    w.writerow(
        [
            "Totals",
            "",
            "",
            _pounds(ret.total_payments_pence),
            _pounds(ret.total_materials_pence),
            _pounds(ret.total_deductions_pence),
            "",
        ]
    )
    w.writerow([])
    w.writerow([ret.declaration])
    w.writerow([ret.not_submitted])
    return buf.getvalue()


def _inert(s: str) -> str:
    """Typed text that a spreadsheet must not run as a formula."""
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


async def export_return(books: Books, ret: MonthlyReturn, user: str, sample: bool = False) -> list[str]:
    """Save the return as CSV and JSON in 07 Reports/CIS (a second save the same month replaces the file: it is a
    prepared copy for the user to file, never a submission). Returns the two paths."""
    stem = f"{RETURNS_FOLDER}/CIS300 {ret.tax_month_end.isoformat()}"
    csv_path, json_path = f"{stem}.csv", f"{stem}.json"
    await books.storage.ensure_folder(RETURNS_FOLDER)
    await books.storage.write(csv_path, return_csv(ret, sample).encode("utf-8-sig"))
    await books.write_json(json_path, {"sample": sample, **ret.model_dump(mode="json")})
    await books.audit(
        f"user:{user}",
        "cis_return_prepared",
        {
            "tax_month_end": ret.tax_month_end.isoformat(),
            "path": csv_path,
            "deductions_pence": ret.total_deductions_pence,
        },
    )
    return [csv_path, json_path]


def owed_to_hmrc(events: list[LedgerEvent], end: date) -> int:
    """What 2220 CIS deductions owed stands at on `end` (deductions made less payments to HMRC posted against it)."""
    return sum(ln.credit - ln.debit for ev in events if ev.date <= end for ln in ev.lines if ln.account == CIS_OWED)


assert BANK == "1200 Bank" and CASH == "1210 Cash" and DEBTORS == "1100 Debtors"
