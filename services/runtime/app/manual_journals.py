"""Manual journals: a balanced journal the user writes, saved as a draft and posted only when they approve it.

Stored in `_System/Accounting/journals.json` (one record per journal, rewritten whole; a record is never removed:
a discarded draft or a voided journal stays, marked so). Approving posts one `adjustment` event (integer pence,
Σ debits = Σ credits, enforced here with a plain sentence and again by the ledger), with an id derived from the
journal's, so a retried approval cannot post twice.

- **VAT.** A journal may carry a VAT line on 2200 VAT control. It then says which side of the return it is on
  (`vat_box`: sales or purchases) and the lines the VAT is on carry a VAT code; its net is those lines (credit − debit
  for sales, debit − credit for purchases) and its VAT the VAT control line, both signed. The VAT return counts it
  as it is (accnomos_ledger.vat). A journal with VAT can't be dated in a VAT period already submitted.
- **Reversing journals.** With `auto_reverse_on`, approving also posts the mirror entry (every line on the other
  side) dated that day — accruals and prepayments undone next month. The user approves both at once.
- **Void.** A posted journal is cancelled by appending its mirror (dated like it, or today if its VAT period was
  submitted); nothing is edited or deleted.
- **Documents.** A journal may name a file already in the books folder; its sha256 becomes the event's evidence.
- Debtors, creditors and payroll liabilities are kept off journals: invoices, bills and pay runs carry their
  detail. Depreciation and disposals (app/fixed_assets.py) arrive here as drafts with `source` set.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app.approve import submitted_spans
from app.books import Books, now
from app.chart import ACCOUNTING, CONTROL_ACCOUNTS, ChartError, active_account, load_chart
from app.deadlines import period_label
from app.invoicing import money
from app.journal import VAT_CONTROL
from app.tracking import TrackingError, check_tags, load_tracking
from app.validation import LENIENT, Day, Pence, StrictBody, Tags, check_name

JOURNALS = f"{ACCOUNTING}/journals.json"
MAX_PENCE = 10_000_000_000
RATES = {"S": 20, "R": 5}
JournalStatus = Literal["draft", "posted", "voided", "discarded"]
JournalSource = Literal["manual", "depreciation", "disposal"]
VatLetter = Literal["S", "R", "Z", "E", "O", "N"]


class JournalError(ValueError):
    """The journal cannot be saved, approved or voided as asked."""


class JournalStateError(JournalError):
    """The journal's status does not allow this."""


class JournalLineIn(StrictBody):
    account: str = Field(min_length=4, max_length=90)  # "7500 Office supplies" or just "7500"
    debit_pence: Annotated[Pence, Field(ge=0, le=MAX_PENCE)] = 0
    credit_pence: Annotated[Pence, Field(ge=0, le=MAX_PENCE)] = 0
    vat_code: VatLetter | None = None
    description: Annotated[str | None, Field(max_length=200)] = None
    tracking: Annotated[Tags | None, Field(max_length=2)] = None


class ManualJournalIn(StrictBody):
    date: Day
    narration: str = Field(min_length=1, max_length=300)
    lines: list[JournalLineIn] = Field(min_length=2, max_length=100)
    vat_box: Literal["sales", "purchases"] | None = None
    auto_reverse_on: Day | None = None
    document_path: Annotated[str | None, Field(max_length=400)] = None


class JournalLine(BaseModel):
    account: str
    debit_pence: int = 0
    credit_pence: int = 0
    vat_code: VatLetter | None = None
    description: str | None = None
    tracking: dict[str, str] | None = None


class AssetCharge(BaseModel):
    """One asset's depreciation in a depreciation journal (app/fixed_assets.py)."""

    asset_id: str
    start: date
    end: date
    amount_pence: int
    periods: int


class AssetDisposal(BaseModel):
    asset_id: str
    date: date
    proceeds_pence: int
    gain_pence: int  # positive gain, negative loss
    catch_up: AssetCharge | None = None


class ManualJournal(BaseModel):
    id: str
    number: str
    status: JournalStatus = "draft"
    source: JournalSource = "manual"
    date: date
    narration: str
    lines: list[JournalLine]
    vat_box: Literal["sales", "purchases"] | None = None
    net_pence: int | None = None
    vat_pence: int | None = None
    auto_reverse_on: date | None = None
    document_path: str | None = None
    document_sha256: str | None = None
    warnings: list[str] = []
    asset_charges: list[AssetCharge] = []
    disposal: AssetDisposal | None = None
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    event_id: str | None = None
    reversal_event_id: str | None = None  # the auto-reversal
    voided_by: str | None = None
    voided_at: datetime | None = None
    void_event_ids: list[str] = []
    discarded_by: str | None = None

    @model_validator(mode="after")
    def _balanced(self) -> ManualJournal:
        if sum(ln.debit_pence for ln in self.lines) != sum(ln.credit_pence for ln in self.lines):
            raise ValueError("unbalanced journal")
        return self

    @property
    def total_pence(self) -> int:
        return sum(ln.debit_pence for ln in self.lines)


def event_id_for(journal_id: str, part: str = "") -> str:
    return hashlib.sha256(f"journal:{journal_id}{part}".encode()).hexdigest()[:32]


async def list_journals(books: Books) -> list[ManualJournal]:
    raw = await books.read_json(JOURNALS, [])
    try:
        return [ManualJournal.model_validate(r, **LENIENT) for r in raw]
    except (TypeError, ValidationError) as exc:
        raise JournalError("The journals file could not be read; fix _System/Accounting/journals.json") from exc


async def get_journal(books: Books, journal_id: str) -> ManualJournal:
    j = next((j for j in await list_journals(books) if j.id == journal_id), None)
    if j is None:
        raise FileNotFoundError(f"No journal {journal_id}")
    return j


async def journal_for_event(books: Books, event_id: str) -> ManualJournal | None:
    """The journal that posted `event_id` (its entry, auto-reversal or void), if any."""
    try:
        journals = await list_journals(books)
    except JournalError:
        return None
    return next((j for j in journals if event_id in (j.event_id, j.reversal_event_id, *j.void_event_ids)), None)


async def _save(books: Books, j: ManualJournal) -> None:
    row = j.model_dump(mode="json")

    def change(rows: list[dict]) -> list[dict]:
        rows = list(rows or [])
        for i, r in enumerate(rows):
            if r.get("id") == j.id:
                rows[i] = row
                return rows
        return [*rows, row]

    await books._update_json(JOURNALS, [], change)


def _pence(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def vat_figures(lines: list[JournalLine], vat_box: str | None) -> tuple[int | None, int | None, list[str]]:
    """(net, vat, warnings) for a journal: None, None when it has no VAT side. Raises JournalError when the VAT is
    half-described (a VAT control line with no side, or a side with no VAT-coded lines)."""
    on_control = [ln for ln in lines if ln.account == VAT_CONTROL]
    coded = [ln for ln in lines if ln.account != VAT_CONTROL and ln.vat_code]
    if on_control and not vat_box:
        raise JournalError("This journal has a VAT line: say whether the VAT is on sales or on purchases")
    if not vat_box:
        return None, None, []
    if not coded:
        raise JournalError("Give the lines the VAT is on a VAT code, so the return knows what it is on")
    sign = 1 if vat_box == "purchases" else -1
    net = sum(sign * (ln.debit_pence - ln.credit_pence) for ln in coded if ln.vat_code != "O")
    vat = sum(sign * (ln.debit_pence - ln.credit_pence) for ln in on_control)
    expected = sum(
        _pence(Decimal(sign * (ln.debit_pence - ln.credit_pence)) * RATES[ln.vat_code] / 100)
        for ln in coded
        if ln.vat_code in RATES
    )
    warnings = []
    if abs(expected - vat) > len(coded):
        warnings.append(
            f"The VAT line is {money(vat)}, but the coded lines at their rates come to {money(expected)} of VAT. "
            "Check it before approving."
        )
    return net, vat, warnings


async def check_lines(books: Books, lines: list[JournalLineIn], vat_box: str | None) -> list[JournalLine]:
    """Lines as the chart and the tracking categories name them; JournalError with a plain sentence otherwise."""
    try:
        chart, _ = await load_chart(books)
        tracking = await load_tracking(books)
    except (ChartError, TrackingError) as exc:
        raise JournalError(str(exc)) from exc
    out: list[JournalLine] = []
    for n, ln in enumerate(lines, start=1):
        if (ln.debit_pence > 0) == (ln.credit_pence > 0):
            raise JournalError(f"Line {n}: put an amount in debit or in credit, not both or neither")
        try:
            acc = active_account(chart, ln.account)
            tags = check_tags(tracking, ln.tracking)
        except (ChartError, TrackingError) as exc:
            raise JournalError(f"Line {n}: {exc}") from exc
        if acc.label in CONTROL_ACCOUNTS - {VAT_CONTROL}:
            raise JournalError(
                f"Line {n}: {acc.label} is kept by invoices, bills and pay runs; use those instead of a journal"
            )
        if acc.label == VAT_CONTROL and not vat_box:
            raise JournalError(f"Line {n}: say whether the VAT is on sales or on purchases")
        out.append(
            JournalLine(
                account=acc.label,
                debit_pence=ln.debit_pence,
                credit_pence=ln.credit_pence,
                vat_code=None if acc.label == VAT_CONTROL else ln.vat_code,
                description=(ln.description or "").strip() or None,
                tracking=tags,
            )
        )
    debits, credits = sum(ln.debit_pence for ln in out), sum(ln.credit_pence for ln in out)
    if debits != credits:
        gap = abs(debits - credits)
        raise JournalError(
            f"Debits are {money(debits)} and credits are {money(credits)}: they must be equal, "
            f"and are {money(gap)} apart"
        )
    if debits == 0:
        raise JournalError("The journal has no amounts")
    return out


async def _document(books: Books, path: str | None) -> tuple[str | None, str | None]:
    if not path or not path.strip():
        return None, None
    path = path.strip().strip("/")
    for part in path.split("/"):
        check_name(part)
    if not await books.exists(path):
        raise JournalError(f"There is no file {path} in your books folder")
    return path, hashlib.sha256(await books.storage.read(path)).hexdigest()


def _next_number(journals: Iterable[ManualJournal]) -> str:
    n = max((int(j.number.removeprefix("MJ-")) for j in journals if j.number.removeprefix("MJ-").isdigit()), default=0)
    return f"MJ-{n + 1:04d}"


async def create_draft(
    books: Books,
    body: ManualJournalIn,
    user: str,
    *,
    source: JournalSource = "manual",
    asset_charges: list[AssetCharge] | None = None,
    disposal: AssetDisposal | None = None,
    net_vat: tuple[int, int] | None = None,
) -> ManualJournal:
    """Save a draft. Posts nothing."""
    lines = await check_lines(books, body.lines, body.vat_box)
    if body.auto_reverse_on is not None and body.auto_reverse_on <= body.date:
        raise JournalError("The reversal date must be after the journal's date")
    if net_vat is not None:  # a disposal: code worked out the VAT-able net and the VAT itself
        if not body.vat_box:
            raise JournalError("A journal with VAT figures needs its VAT side")
        (net, vat), warnings = net_vat, []
    else:
        net, vat, warnings = vat_figures(lines, body.vat_box)
    doc_path, doc_sha = await _document(books, body.document_path)
    journal = ManualJournal(
        id=uuid.uuid4().hex[:16],
        number=_next_number(await list_journals(books)),
        source=source,
        date=body.date,
        narration=body.narration.strip(),
        lines=lines,
        vat_box=body.vat_box,
        net_pence=net,
        vat_pence=vat,
        auto_reverse_on=body.auto_reverse_on,
        document_path=doc_path,
        document_sha256=doc_sha,
        warnings=warnings,
        asset_charges=asset_charges or [],
        disposal=disposal,
        created_by=user,
        created_at=now(),
    )
    await _save(books, journal)
    await books.audit(
        f"user:{user}",
        "journal_drafted",
        {"journal": journal.id, "number": journal.number, "source": source, "total_pence": journal.total_pence},
    )
    return journal


def _lines(j: ManualJournal, mirror: bool = False, memo: str | None = None) -> list[Line]:
    return [
        Line(
            account=ln.account,
            debit=ln.credit_pence if mirror else ln.debit_pence,
            credit=ln.debit_pence if mirror else ln.credit_pence,
            vat_code=VatCode(ln.vat_code)
            if ln.vat_code
            else (VatCode(_box_code(j)) if ln.account == VAT_CONTROL else None),
            memo=memo or ln.description or j.narration,
            tracking=ln.tracking,
        )
        for ln in j.lines
    ]


def _box_code(j: ManualJournal) -> str:
    codes = [ln.vat_code for ln in j.lines if ln.vat_code and ln.account != VAT_CONTROL]
    return max(codes, key=codes.count) if codes else "S"


def journal_event(
    j: ManualJournal,
    user: str,
    *,
    part: str = "",
    on: date | None = None,
    mirror: bool = False,
    memo: str | None = None,
    reverses: str | None = None,
) -> LedgerEvent:
    sign = -1 if mirror else 1
    return LedgerEvent(
        id=event_id_for(j.id, part),
        kind="adjustment",
        date=on or j.date,
        lines=_lines(j, mirror, memo),
        evidence=[j.document_sha256] if j.document_sha256 else [],
        approved_by=user,
        approved_at=now(),
        counterparty=f"Journal {j.number}",
        reverses=reverses,  # a void names the entry it cancels (kind stays `adjustment`, so VAT counts it as signed)
        vat_box=j.vat_box,
        net=None if j.net_pence is None else sign * j.net_pence,
        vat=None if j.vat_pence is None else sign * j.vat_pence,
    )


async def submitted_label(books: Books, day: date) -> str | None:
    """'Jul–Sep 2026' when `day` is in a VAT period whose return was submitted, else None."""
    span = next((s for s in await submitted_spans(books) if s[0] <= day <= s[1]), None)
    return period_label(*span) if span else None


async def approve_journal(books: Books, journal_id: str, user: str) -> ManualJournal:
    """Post a draft (and its auto-reversal). The user's action: `user` tapped Approve."""
    j = await get_journal(books, journal_id)
    if j.status != "draft":
        raise JournalStateError(f"Journal {j.number} is {j.status}")
    # The chart or the tracking options may have changed since the draft was saved: check the lines again.
    await check_lines(
        books,
        [JournalLineIn.model_validate(ln.model_dump()) for ln in j.lines],
        j.vat_box,
    )
    if j.vat_box:
        for day in filter(None, (j.date, j.auto_reverse_on)):
            if label := await submitted_label(books, day):
                raise JournalError(
                    f"The VAT return for {label} has been submitted, so a journal with VAT can't be dated "
                    f"{day:%d/%m/%Y}. Date it in the current VAT period instead."
                )
    if j.source != "manual":
        from app.fixed_assets import check_journal_still_fits  # fixed_assets imports this module

        await check_journal_still_fits(books, j)
    event = journal_event(j, user)
    try:
        await books.post_event(event)
    except FileExistsError as exc:
        raise JournalStateError("Already posted to the ledger") from exc
    j.status, j.event_id, j.approved_by, j.approved_at = "posted", event.id, user, now()
    if j.auto_reverse_on:
        rev = journal_event(j, user, part=":reverse", on=j.auto_reverse_on, mirror=True, memo=f"Reversal of {j.number}")
        await books.post_event(rev)
        j.reversal_event_id = rev.id
    await _save(books, j)
    await books.audit(
        f"user:{user}",
        "journal_approved",
        {"journal": j.id, "number": j.number, "event": event.id, "reversal": j.reversal_event_id, "source": j.source},
    )
    await books.rebuild_safely(f"user:{user}")
    return j


async def discard_draft(books: Books, journal_id: str, user: str) -> ManualJournal:
    j = await get_journal(books, journal_id)
    if j.status != "draft":
        raise JournalStateError(f"Journal {j.number} is {j.status}; only a draft can be discarded")
    j.status, j.discarded_by = "discarded", user
    await _save(books, j)
    await books.audit(f"user:{user}", "journal_discarded", {"journal": j.id, "number": j.number})
    return j


async def void_journal(books: Books, journal_id: str, user: str, today: date) -> ManualJournal:
    """Cancel a posted journal by appending its mirror (and the mirror of its auto-reversal)."""
    j = await get_journal(books, journal_id)
    if j.status != "posted" or not j.event_id:
        raise JournalStateError(f"Journal {j.number} is {j.status}; only a posted journal can be voided")
    ids = [i for i in (j.event_id, j.reversal_event_id) if i]
    if any(i in ln.event_ids() for ln in await books.stored_bank_lines() if ln.status == "matched" for i in ids):
        raise JournalError("A bank line is matched to this journal; unmatch it on the Bank page first")
    if j.source != "manual":
        from app.fixed_assets import check_void_allowed

        await check_void_allowed(books, j)
    parts = [("", j.date, False, j.event_id)] + (
        [(":reverse", j.auto_reverse_on, True, j.reversal_event_id)] if j.reversal_event_id else []
    )
    posted: list[str] = []
    for part, day, was_mirror, cancels in parts:
        assert day is not None
        on = today if j.vat_box and await submitted_label(books, day) else day
        ev = journal_event(
            j, user, part=f"{part}:void", on=on, mirror=not was_mirror, memo=f"Void of {j.number}", reverses=cancels
        )
        with contextlib.suppress(FileExistsError):  # a retried void: already there
            await books.post_event(ev)
        posted.append(ev.id)
    j.status, j.voided_by, j.voided_at, j.void_event_ids = "voided", user, now(), posted
    await _save(books, j)
    await books.audit(f"user:{user}", "journal_voided", {"journal": j.id, "number": j.number, "events": posted})
    await books.rebuild_safely(f"user:{user}")
    return j


def matches(
    j: ManualJournal,
    *,
    status: str | None = None,
    source: str | None = None,
    start: date | None = None,
    end: date | None = None,
    account: str | None = None,
    q: str | None = None,
) -> bool:
    if status and j.status != status:
        return False
    if source and j.source != source:
        return False
    if start and j.date < start:
        return False
    if end and j.date > end:
        return False
    if account and not any(ln.account.startswith(account.strip()[:4]) for ln in j.lines):
        return False
    if q:
        text = " ".join([j.number, j.narration, *(ln.description or "" for ln in j.lines)]).casefold()
        if q.strip().casefold() not in text:
            return False
    return True
