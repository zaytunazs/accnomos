"""CIS documents read by the user's AI, waiting for the user: payment and deduction statements from contractors, and
subcontractors' reverse-charge invoices (AI proposes, user approves, code calculates).

A document in `00 Inbox` (uploaded, or copied there by Outlook intake) is read by app/ai/cis_read.py. Code turns the
printed pounds into pence, checks them (app/cis.py: the tax month, the deduction against 0/20/30% of the amount
liable; for a reverse-charge invoice, the VAT against the net at the printed rate and HMRC's wording), and saves a
reading in `_System/CIS/readings/<id>.json`. Nothing is kept or posted until the user approves, with the figures
as read or as corrected on the card:

* a statement is added to `_System/CIS/statements.json` (app/cis.add_statement), posting nothing: the deductions
  are posted when the payment is recorded (app/payments.py) and the statement is the evidence the year totals use;
* a reverse-charge bill posts Dr 5300 Subcontractors (net) / Cr 2100 Creditors with `reverse_charge_vat` worked out
  by code from the net and the rate (boxes 1 and 4, accnomos_ledger.vat), so it shows in Contacts as a bill to pay.

Rejecting keeps the reading, marked rejected. The document stays where it is.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app import cis, paths
from app.ai.cis_read import CisReading, read_cis_document, to_date, to_pence
from app.ai.config import AiConfig
from app.books import Books, now
from app.checks import normalise_vat_number
from app.formats import prepare
from app.journal import CREDITORS
from app.validation import LENIENT, Day, Pence, StrictBody, check_name

ReadingStatus = Literal["pending", "approved", "rejected"]


class ReverseChargeBillIn(StrictBody):
    """A subcontractor's invoice under the VAT domestic reverse charge (no VAT charged; we account for it)."""

    supplier_name: str = Field(min_length=1, max_length=200)
    supplier_vat_number: str | None = Field(None, max_length=20)
    invoice_number: str | None = Field(None, max_length=60)
    invoice_date: Day
    net_pence: Pence = Field(gt=0, le=10_000_000_000)
    vat_rate: Literal[20, 5] = 20
    account: Literal["5300 Subcontractors", "5000 Materials"] = cis.SUBCONTRACTORS_ACCOUNT
    document: str | None = Field(None, max_length=400)

    @model_validator(mode="after")
    def _vrn(self) -> ReverseChargeBillIn:
        self.supplier_vat_number = normalise_vat_number(self.supplier_vat_number)
        return self

    @property
    def reverse_charge_vat_pence(self) -> int:
        return (self.net_pence * self.vat_rate + 50) // 100


def bill_checks(b: ReverseChargeBillIn, printed_vat: int | None, wording: bool) -> list[cis.Check]:
    out = [
        cis.Check(
            code="RC_WORDING",
            ok=wording,
            message="Says the reverse charge applies"
            if wording
            else "No reverse charge wording found: if VAT was simply left off, ask the supplier for a proper invoice",
        ),
        cis.Check(
            code="SUPPLIER_VRN",
            ok=bool(b.supplier_vat_number and re.fullmatch(r"GB\d{9}(\d{3})?", b.supplier_vat_number)),
            message="Supplier's VAT number is printed"
            if b.supplier_vat_number
            else "No supplier VAT number: the reverse charge only applies between VAT-registered businesses",
        ),
    ]
    if printed_vat is not None:
        ok = abs(printed_vat - b.reverse_charge_vat_pence) <= cis.PENNY
        out.append(
            cis.Check(
                code="RC_VAT",
                ok=ok,
                message=f"VAT to account for is {b.vat_rate}% of the net"
                if ok
                else f"Printed VAT {cis.money(printed_vat)} is not {b.vat_rate}% of {cis.money(b.net_pence)} "
                f"({cis.money(b.reverse_charge_vat_pence)}); code uses {cis.money(b.reverse_charge_vat_pence)}",
            )
        )
    return out


class Reading(BaseModel):
    id: str
    path: str  # the document in the books
    sha256: str
    kind: Literal["cis_statement", "reverse_charge_invoice", "other"]
    statement: cis.StatementIn | None = None
    bill: ReverseChargeBillIn | None = None
    problems: list[str] = []  # what stopped code filling a field
    checks: list[cis.Check] = []
    confidence: float = 0
    model: str = ""
    status: ReadingStatus = "pending"
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    statement_id: str | None = None  # after approval
    event_id: str | None = None  # after approval of a bill


def _path(reading_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{16}", reading_id):
        raise FileNotFoundError(reading_id)
    return f"{cis.READINGS}/{reading_id}.json"


async def get_reading(books: Books, reading_id: str) -> Reading:
    return Reading.model_validate_json(await books.storage.read(_path(reading_id)), **LENIENT)


async def save_reading(books: Books, r: Reading) -> None:
    await books.write_json(_path(r.id), r.model_dump(mode="json"))


async def list_readings(books: Books, status: ReadingStatus | None = None) -> list[Reading]:
    files = [f for f in await books.list_files(cis.READINGS) if re.fullmatch(r"[0-9a-f]{16}\.json", f.name)]

    async def one(path: str) -> Reading:
        return Reading.model_validate_json(await books.storage.read(path), **LENIENT)

    out = [r for r in await asyncio.gather(*(one(f.path) for f in files)) if status is None or r.status == status]
    return sorted(out, key=lambda r: r.created_at, reverse=True)


def _why(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    found: Any = errors() if callable(errors) else None
    return str(found[0]["msg"]) if found else str(exc)


def from_reading(read: CisReading, path: str, settings: cis.CisSettings) -> tuple[Reading, list[str]]:
    """Code's half: pounds to pence, dates parsed, the model's figures fitted into the request bodies and checked."""
    problems: list[str] = []
    statement = bill = None
    checks: list[cis.Check] = []
    if read.kind == "cis_statement":
        end = to_date(read.tax_month_end)
        gross, materials, cut = to_pence(read.gross_amount), to_pence(read.materials) or 0, to_pence(read.deduction)
        if end is None:
            problems.append("No tax month end date read")
        if gross is None or cut is None:
            problems.append("The gross amount or the deduction was not read")
        if not read.contractor_name:
            problems.append("No contractor name read")
        if not problems and end and gross is not None and cut is not None:
            try:
                statement = cis.StatementIn(
                    contractor_name=read.contractor_name or "",
                    contractor_ref=(read.contractor_ref or "")[:20] or None,
                    tax_month_end=end,
                    gross_pence=gross,
                    materials_pence=materials,
                    deduction_pence=cut,
                    subcontractor_utr=read.subcontractor_utr,
                    verification_number=(read.verification_number or "")[:20] or None,
                    document=path,
                )
            except ValueError as exc:
                problems.append(f"The figures do not fit together: {_why(exc)}")
        if statement:
            checks = cis.statement_checks(statement, settings)
            liable = to_pence(read.amount_liable)
            if liable is not None and liable != statement.gross_pence - statement.materials_pence:
                checks.append(
                    cis.Check(code="LIABLE", ok=False, message="The printed amount liable is not gross less materials")
                )
            paid = to_pence(read.net_paid)
            if paid is not None and paid != statement.gross_pence - statement.deduction_pence:
                checks.append(
                    cis.Check(
                        code="NET_PAID", ok=False, message="The printed net payment is not gross less the deduction"
                    )
                )
    elif read.kind == "reverse_charge_invoice":
        day, net = to_date(read.invoice_date), to_pence(read.net)
        rate = int(read.vat_rate) if read.vat_rate in (20, 5) else None
        if day is None:
            problems.append("No invoice date read")
        if net is None or net <= 0:
            problems.append("No net amount read")
        if rate is None:
            problems.append("The VAT rate was not 20% or 5%")
        if not read.supplier_name:
            problems.append("No supplier name read")
        if not problems and day and net and rate:
            try:
                bill = ReverseChargeBillIn(
                    supplier_name=read.supplier_name or "",
                    supplier_vat_number=read.supplier_vat_number,
                    invoice_number=(read.invoice_number or "")[:60] or None,
                    invoice_date=day,
                    net_pence=net,
                    vat_rate=rate,  # type: ignore[arg-type]
                    document=path,
                )
            except ValueError as exc:
                problems.append(f"The figures do not fit together: {_why(exc)}")
        if bill:
            checks = bill_checks(bill, to_pence(read.reverse_charge_vat), read.reverse_charge_wording)
    else:
        problems.append("This does not look like a CIS statement or a reverse-charge invoice")
    reading = Reading(
        id=uuid.uuid4().hex[:16],
        path=path,
        sha256="",
        kind=read.kind,
        statement=statement,
        bill=bill,
        problems=problems,
        checks=checks,
        confidence=read.confidence,
        created_at=now(),
    )
    return reading, problems


async def read_document(books: Books, name: str, cfg: AiConfig, user: str) -> Reading:
    """Read `00 Inbox/<name>` with the user's AI and save what code made of it, waiting for the user."""
    check_name(name)
    path = f"{paths.INBOX}/{name}"
    data = await books.storage.read(path)
    digest = hashlib.sha256(data).hexdigest()
    for r in await list_readings(books):
        if r.sha256 == digest and r.status != "rejected":
            return r  # read already: never twice
    hint = "text/plain" if name.lower().endswith(".txt") else name
    prepared = await asyncio.to_thread(prepare, data, hint)
    text = prepared.text if prepared.kind != "image" else None
    read, meta = await read_cis_document(prepared.image, prepared.mime, cfg, text=text)
    reading, _ = from_reading(read, path, await cis.load_settings(books))
    reading.sha256, reading.model = digest, str(meta.get("model", ""))
    await save_reading(books, reading)
    await books.audit(
        "agent:cis-reader",
        "cis_document_read",
        {"reading": reading.id, "file": path, "kind": reading.kind, "requested_by": user},
    )
    return reading


def bill_event_id(key: str) -> str:
    return hashlib.sha256(f"rc-bill:{key}".encode()).hexdigest()[:32]


def bill_event(b: ReverseChargeBillIn, user: str, key: str, evidence: list[str]) -> LedgerEvent:
    memo = f"Reverse charge (s55A) bill {b.invoice_number or ''}".strip()
    code = VatCode.REDUCED if b.vat_rate == 5 else VatCode.STANDARD
    return LedgerEvent(
        id=bill_event_id(key),
        kind="purchase",
        date=b.invoice_date,
        lines=[
            Line(account=b.account, debit=b.net_pence, vat_code=code, memo=memo),
            Line(account=CREDITORS, credit=b.net_pence, memo=memo),
        ],
        evidence=evidence,
        approved_by=user,
        approved_at=now(),
        net=b.net_pence,
        vat=0,
        reverse_charge_vat=b.reverse_charge_vat_pence,
        counterparty=b.supplier_name,
    )


async def post_bill(books: Books, b: ReverseChargeBillIn, user: str, key: str, evidence: list[str]) -> str:
    """Post a reverse-charge bill once (the id comes from `key`: the reading, or a typed bill's own id)."""
    settings = await cis.load_settings(books)
    if not (settings.contractor or settings.subcontractor):
        raise cis.CisError("Turn on CIS in Settings › CIS first")
    event = bill_event(b, user, key, evidence)
    try:
        path = await books.post_event(event)
    except FileExistsError:
        path = None
    await books.audit(
        f"user:{user}",
        "reverse_charge_bill_posted",
        {
            "event": event.id,
            "event_path": path,
            "supplier": b.supplier_name,
            "rc_vat_pence": b.reverse_charge_vat_pence,
        },
    )
    await books.rebuild_safely(f"user:{user}")
    return event.id


class DecideBody(StrictBody):
    statement: cis.StatementIn | None = None  # the figures as corrected on the card (default: as read)
    bill: ReverseChargeBillIn | None = None


async def approve(books: Books, reading_id: str, body: DecideBody, user: str) -> Reading:
    r = await get_reading(books, reading_id)
    if r.status != "pending":
        raise cis.CisError(f"This reading was already {r.status}")
    if r.kind == "cis_statement":
        st_in = body.statement or r.statement
        if st_in is None:
            raise cis.CisError("Fill in the statement's figures first")
        st = await cis.add_statement(books, st_in, user, source="read", reading_id=r.id)
        r.statement, r.statement_id = st_in, st.id
    elif r.kind == "reverse_charge_invoice":
        b = body.bill or r.bill
        if b is None:
            raise cis.CisError("Fill in the invoice's figures first")
        r.event_id = await post_bill(books, b, user, r.id, [r.sha256] if r.sha256 else [])
        r.bill = b
    else:
        raise cis.CisError("Nothing to approve: reject it instead")
    r.status, r.decided_by, r.decided_at = "approved", user, now()
    await save_reading(books, r)
    await books.audit(f"user:{user}", "cis_reading_approved", {"reading": r.id, "kind": r.kind})
    return r


async def reject(books: Books, reading_id: str, user: str) -> Reading:
    r = await get_reading(books, reading_id)
    if r.status != "pending":
        raise cis.CisError(f"This reading was already {r.status}")
    r.status, r.decided_by, r.decided_at = "rejected", user, now()
    await save_reading(books, r)
    await books.audit(f"user:{user}", "cis_reading_rejected", {"reading": r.id, "kind": r.kind})
    return r


def typed_bill_key(b: ReverseChargeBillIn) -> str:
    """A typed bill's idempotency key: the same supplier, number, date and net post once."""
    return f"typed:{b.supplier_name.strip().lower()}:{b.invoice_number or ''}:{b.invoice_date}:{b.net_pence}"
