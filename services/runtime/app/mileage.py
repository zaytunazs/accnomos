"""Vehicles, the mileage log and the HMRC approved mileage allowance, all computed by code.

Files (in the user's books folder):

    _System/Vehicles/vehicles.json      [{id, name, registration, kind, owned_by, active}]
    _System/Mileage/{tax-year}.jsonl    one journey per line, e.g. _System/Mileage/2026-27.jsonl

A personal vehicle used for business earns the approved mileage allowance. It is claimed a tax-year
quarter at a time as an ordinary expense proposal that the user approves in Review; nothing here
posts. A business vehicle earns no allowance: its fuel, parking and repair receipts are tagged to it
(`Proposal.vehicle_id`) and its actual costs are summed instead.

Rounding: each journey's allowance is rounded half-up to the penny once (a journey that crosses the
10,000-mile line is split first), so every total is a sum of whole pennies and claims add up exactly.

A posted claim fixes the journeys it paid for. Which rate a journey gets depends on the journeys
before it, so journeys dated before the latest posted claim's `covers_to` cannot be added, changed
or deleted either; undoing the claim in Review unlocks them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.books import SYSTEM, Books, now
from app.books import today as london_today
from app.checks import decide
from app.journal import VAT_CONTROL, draft_journal
from app.schemas import MILEAGE_CATEGORY, Check, ExtractedDoc, ExtractedLine, MileageClaim, Proposal
from app.taxyear import uk_tax_year_start
from app.validation import LENIENT, Day, StrictBody

VEHICLES = f"{SYSTEM}/Vehicles/vehicles.json"
MILEAGE = f"{SYSTEM}/Mileage"
ACTOR = "agent:mileage"
OPEN = ("proposed", "needs_a_look")

VehicleKind = Literal["car", "van", "motorcycle", "bicycle"]
Ownership = Literal["business", "personal"]


@dataclass(frozen=True)
class Rate:
    first_pence: int  # per mile, up to the threshold
    after_pence: int  # per mile, beyond it
    threshold_miles: int | None  # None: one flat rate


# HMRC approved mileage allowance payments (AMAP) by tax year (6 April to 5 April).
# Base table (unchanged since 2011-12):
# https://www.gov.uk/government/publications/rates-and-allowances-travel-mileage-and-fuel-allowances/travel-mileage-and-fuel-rates-and-allowances
# Cars and vans from 2026-27: 55p per mile for the first 10,000 business miles, 25p beyond, per
# https://www.accaglobal.com/gb/en/technical-activities/uk-tech/in-practice-ezine-archive/In-Practice-archive-2026/july-august/Increase-to-Approved-Mileage-Allowance-Payments.html
# (checked 28 Oct 2026). That page states no motorcycle rate (TODO: motorcycle rate) and no
# bicycle rate (TODO: bicycle rate), so those keep their old values.
# The 10,000-mile threshold is shared by all cars and vans in the tax year.
RATES_BY_TAX_YEAR: dict[str, dict[str, Rate]] = {
    "2025-26": {
        "car": Rate(45, 25, 10_000),
        "van": Rate(45, 25, 10_000),
        "motorcycle": Rate(24, 24, None),
        "bicycle": Rate(20, 20, None),
    },
    "2026-27": {
        "car": Rate(55, 25, 10_000),
        "van": Rate(55, 25, 10_000),
        "motorcycle": Rate(24, 24, None),  # TODO: motorcycle rate (not stated on the ACCA page)
        "bicycle": Rate(20, 20, None),  # TODO: bicycle rate (not stated on the ACCA page)
    },
}
THRESHOLD_MILES = 10_000


def rates_for(tax_year: str) -> dict[str, Rate]:
    """The rates table for a tax year like '2026-27': 2025-26 and earlier at the old rates,
    2026-27 onwards at the new ones."""
    start = tax_year_bounds(tax_year)[0].year
    return RATES_BY_TAX_YEAR["2026-27" if start >= 2026 else "2025-26"]


FUEL_SCALE_NOTE = (
    "Business vehicles: Accnomos keeps the VAT code printed on each fuel receipt. If a business vehicle is also used "
    "privately, HMRC may expect a fuel scale charge on your VAT return, or less VAT reclaimed on fuel. Accnomos does "
    "not calculate scale charges: ask your accountant."
)
ALLOWANCE_NOTE = (
    "Personal vehicles: the allowance covers fuel, repairs, insurance and wear, so don't also claim those receipts "
    "for the same vehicle."
)

TAX_YEAR_RE = re.compile(r"(\d{4})-(\d{2})")
QUARTERS = ("Q1", "Q2", "Q3", "Q4")


class MileageError(ValueError):
    """The request can't be done as asked (bad input, nothing to claim)."""


class LockedError(MileageError):
    """The change would alter a mileage claim that has already been posted."""


# --------------------------------------------------------------------------- #
# Tax years (6 April to 5 April) and their quarters
# --------------------------------------------------------------------------- #


def tax_year_of(d: date) -> str:
    """'2026-27' for any day from 6 April 2026 to 5 April 2027."""
    start = uk_tax_year_start(d).year
    return f"{start}-{(start + 1) % 100:02d}"


def tax_year_bounds(tax_year: str) -> tuple[date, date]:
    """(6 April, 5 April) of a tax year like '2026-27'. Raises MileageError for anything else."""
    m = TAX_YEAR_RE.fullmatch(tax_year or "")
    if not m or (int(m[1]) + 1) % 100 != int(m[2]):
        raise MileageError(f"Tax year {tax_year!r} should look like 2026-27")
    start = int(m[1])
    return date(start, 4, 6), date(start + 1, 4, 5)


def quarter_bounds(tax_year: str, period: str) -> tuple[date, date]:
    """Q1 6 Apr–5 Jul, Q2 6 Jul–5 Oct, Q3 6 Oct–5 Jan, Q4 6 Jan–5 Apr."""
    if period not in QUARTERS:
        raise MileageError(f"Period {period!r} should be one of {', '.join(QUARTERS)}")
    y = tax_year_bounds(tax_year)[0].year
    starts = (date(y, 4, 6), date(y, 7, 6), date(y, 10, 6), date(y + 1, 1, 6), date(y + 1, 4, 6))
    i = QUARTERS.index(period)
    return starts[i], date.fromordinal(starts[i + 1].toordinal() - 1)


def quarter_of(d: date) -> str:
    ty = tax_year_of(d)
    return next(q for q in QUARTERS if d <= quarter_bounds(ty, q)[1])


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


def _new_id() -> str:
    return uuid4().hex


class Vehicle(StrictBody):
    id: str = Field(default_factory=_new_id, max_length=32)
    name: str = Field(min_length=1, max_length=60)
    registration: str | None = Field(default=None, max_length=12)  # as the user typed it, upper-cased
    kind: VehicleKind
    owned_by: Ownership
    active: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Give the vehicle a name")
        return v.strip()

    @field_validator("registration")
    @classmethod
    def _reg(cls, v: str | None) -> str | None:
        return re.sub(r"\s+", " ", v).strip().upper() or None if isinstance(v, str) else v

    def label(self) -> str:
        return f"{self.name} ({self.registration})" if self.registration else self.name


class MileageEntry(StrictBody):
    """One business journey. `from` is a Python keyword, so the field is `from_` with the alias "from"."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(default_factory=_new_id, max_length=32)
    vehicle_id: str = Field(max_length=32)
    date: Day
    from_: str = Field(default="", alias="from", max_length=120)
    to: str = Field(default="", max_length=120)
    miles: float = Field(gt=0, le=2000)
    purpose: str = Field(min_length=1, max_length=200)
    job_id: str | None = Field(default=None, max_length=32)  # a job in _System/Jobs/jobs.json, as on purchases
    source: Literal["manual", "proposal"] = "manual"

    @field_validator("miles")
    @classmethod
    def _tenths(cls, v: float) -> float:
        tenths = round(v * 10)
        if abs(v * 10 - tenths) > 1e-6:
            raise ValueError("Miles go in steps of 0.1")
        return tenths / 10

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Say what the journey was for")
        return v.strip()

    @field_validator("job_id")
    @classmethod
    def _job(cls, v: str | None) -> str | None:
        return v.strip() or None if isinstance(v, str) else v

    @property
    def tenths(self) -> int:
        return round(self.miles * 10)


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #


async def load_vehicles(books: Books) -> list[Vehicle]:
    """Raises MileageError when a hand-edited vehicles.json can't be read."""
    raw = await books.read_json(VEHICLES, [])
    try:
        return [Vehicle.model_validate(v, **LENIENT) for v in raw]
    except (ValidationError, TypeError) as exc:
        raise MileageError("The vehicles file could not be read") from exc


async def _change_vehicles(books: Books, change: Callable[[list[Vehicle]], list[Vehicle]]) -> None:
    def apply(raw: list[dict]) -> list[dict]:
        return [v.model_dump(mode="json") for v in change([Vehicle.model_validate(v, **LENIENT) for v in raw])]

    await books._update_json(VEHICLES, [], apply)


def _mileage_path(tax_year: str) -> str:
    tax_year_bounds(tax_year)  # validates; keeps the path inside _System/Mileage
    return f"{MILEAGE}/{tax_year}.jsonl"


def _parse(raw: bytes | None) -> list[MileageEntry]:
    try:
        return [MileageEntry.model_validate_json(x, **LENIENT) for x in (raw or b"").decode().splitlines() if x.strip()]
    except ValidationError as exc:
        raise MileageError("A mileage log file could not be read") from exc


def _dump(entries: Iterable[MileageEntry]) -> bytes:
    ordered = sorted(entries, key=lambda e: (e.date, e.id))
    return "".join(e.model_dump_json(by_alias=True) + "\n" for e in ordered).encode()


async def load_entries(books: Books, tax_year: str) -> list[MileageEntry]:
    """Journeys in a tax year, by date. Raises MileageError for an unreadable file."""
    try:
        raw = await books.storage.read(_mileage_path(tax_year))
    except FileNotFoundError:
        return []
    return sorted(_parse(raw), key=lambda e: (e.date, e.id))


async def _change_entries(
    books: Books, tax_year: str, change: Callable[[list[MileageEntry]], list[MileageEntry]]
) -> None:
    await books._update(_mileage_path(tax_year), lambda raw: _dump(change(_parse(raw))))


async def logged_tax_years(books: Books) -> list[str]:
    names = [f.name.removesuffix(".jsonl") for f in await books.list_files(MILEAGE) if f.name.endswith(".jsonl")]
    return sorted(n for n in names if TAX_YEAR_RE.fullmatch(n))


# --------------------------------------------------------------------------- #
# The allowance
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class JourneyAllowance:
    entry: MileageEntry
    pence: int
    first_tenths: int  # tenths of a mile at the first rate
    after_tenths: int  # tenths of a mile at the rate beyond the threshold


def allowances(
    entries: Iterable[MileageEntry], vehicles: Iterable[Vehicle], claimed: AbstractSet[str] = frozenset()
) -> list[JourneyAllowance]:
    """The allowance for each journey of one tax year, in the order the threshold is counted.

    That order is by date; on the same day, journeys already in a posted claim count first, so a journey
    added later never moves an earlier claim across the threshold. Business (or unknown) vehicles earn 0.
    """
    by_id = {v.id: v for v in vehicles}
    used: dict[str, int] = {}  # tenths of a mile per tax year, all thresholded vehicles together
    out: list[JourneyAllowance] = []
    for e in sorted(entries, key=lambda e: (e.date, e.id not in claimed, e.id)):
        v = by_id.get(e.vehicle_id)
        if v is None or v.owned_by != "personal":
            out.append(JourneyAllowance(e, 0, 0, 0))
            continue
        tax_year = tax_year_of(e.date)
        rate = rates_for(tax_year)[v.kind]
        first = e.tenths
        if rate.threshold_miles is not None:
            first = min(e.tenths, max(0, rate.threshold_miles * 10 - used.get(tax_year, 0)))
            used[tax_year] = used.get(tax_year, 0) + e.tenths
        after = e.tenths - first
        tenth_pence = first * rate.first_pence + after * rate.after_pence
        out.append(JourneyAllowance(e, (tenth_pence + 5) // 10, first, after))
    return out


def threshold_crossed_on(rows: Iterable[JourneyAllowance]) -> date | None:
    """The day car and van miles first went over 10,000 (the first journey paid partly at 25p)."""
    return next((a.entry.date for a in rows if a.after_tenths), None)


# --------------------------------------------------------------------------- #
# Claims: one open proposal per quarter at a time
# --------------------------------------------------------------------------- #


async def mileage_claims(books: Books, tax_year: str | None = None) -> list[Proposal]:
    return [
        p
        for p in await books.list_proposals()
        if p.mileage_claim and (tax_year is None or p.mileage_claim.tax_year == tax_year)
    ]


def _posted(claims: Iterable[Proposal]) -> list[Proposal]:
    return [c for c in claims if c.status == "posted"]


def claimed_ids(claims: Iterable[Proposal]) -> set[str]:
    return {i for c in _posted(claims) for i in c.mileage_claim.entry_ids}  # type: ignore[union-attr]


def locked_until(claims: Iterable[Proposal]) -> date | None:
    """Journeys dated before this day can't change: a posted claim depends on them."""
    return max((c.mileage_claim.covers_to for c in _posted(claims)), default=None)  # type: ignore[union-attr]


def _check_unlocked(entry: MileageEntry, claims: list[Proposal]) -> None:
    if entry.id in claimed_ids(claims):
        raise LockedError("This journey is in a posted mileage claim. Undo that claim in Review to change it")
    lock = locked_until(claims)
    if lock and entry.date < lock:
        raise LockedError(
            f"Mileage up to {lock:%d/%m/%Y} has been claimed, so journeys before then can't be added or changed. "
            "Undo that claim in Review first"
        )


def _claim_id(tax_year: str, period: str, n: int) -> str:
    return hashlib.sha256(f"mileage:{tax_year}:{period}:{n}".encode()).hexdigest()[:32]


def _miles(tenths: int) -> str:
    return f"{tenths / 10:,.1f}"


def _line(v: Vehicle | None, rows: list[JourneyAllowance], tax_year: str) -> ExtractedLine:
    pence = sum(a.pence for a in rows)
    first, after = sum(a.first_tenths for a in rows), sum(a.after_tenths for a in rows)
    if v is None:  # unreachable: only personal vehicles earn an allowance
        return ExtractedLine(
            description="Mileage", qty=1, unit_price=pence / 100, net=pence / 100, vat_rate=None, vat=0
        )
    rate = rates_for(tax_year)[v.kind]
    parts = [f"{_miles(first)} mi at {rate.first_pence}p"] + (
        [f"{_miles(after)} mi at {rate.after_pence}p"] if after else []
    )
    return ExtractedLine(
        description=f"{v.label()}, {v.kind}: {', '.join(parts)}",
        qty=1,
        unit_price=pence / 100,
        net=pence / 100,
        vat_rate=None,
        vat=0,
    )


def claim_proposal(
    proposal_id: str,
    tax_year: str,
    period: str,
    covers_to: date,
    rows: list[JourneyAllowance],
    vehicles: list[Vehicle],
) -> Proposal:
    """An expense proposal for these journeys: category "Motor — mileage allowance", VAT code N
    (no supplier VAT number), credited to the owner who paid for the journeys."""
    by_id = {v.id: v for v in vehicles}
    groups: dict[str, list[JourneyAllowance]] = {}
    for a in rows:
        groups.setdefault(a.entry.vehicle_id, []).append(a)
    lines = [_line(by_id.get(vid), g, tax_year) for vid, g in groups.items()]
    pence = sum(a.pence for a in rows)
    tenths = sum(a.entry.tenths for a in rows)
    doc = ExtractedDoc(
        doc_type="purchase_invoice",
        supplier_name="Mileage allowance",
        supplier_vat_number=None,
        customer_name=None,
        invoice_number=f"MILEAGE-{tax_year}-{period}",
        date=covers_to.isoformat(),
        currency="GBP",
        lines=lines,
        net_total=pence / 100,
        vat_total=0,
        gross_total=pence / 100,
        payment_method=None,
        card_last4=None,
        category_guess=MILEAGE_CATEGORY,
        confidence=1,
    )
    checks = [
        Check(
            code="MILEAGE",
            ok=True,
            severity="warn",
            message=f"Calculated by code: {_miles(tenths)} business miles in personal vehicles, {period} {tax_year} "
            f"to {covers_to:%d/%m/%Y}, at HMRC approved mileage rates",
        )
    ]
    if not rows:
        checks.append(
            Check(
                code="NO_MILES",
                ok=False,
                severity="fail",
                message="No unclaimed miles left in this period; reject this claim",
            )
        )
    status, reasons = decide(checks)
    evidence = json.dumps([[a.entry.id, a.pence] for a in rows]).encode()
    return Proposal(
        id=proposal_id,
        doc_sha256=hashlib.sha256(evidence).hexdigest(),
        extracted=doc,
        checks=checks,
        status=status,
        reasons=reasons,
        suggested_filename=f"Mileage {tax_year} {period}",
        journal_draft=draft_journal(doc),
        model="code:mileage",
        elapsed_s=0,
        mileage_claim=MileageClaim(
            tax_year=tax_year,
            period=period,
            covers_to=covers_to,
            entry_ids=[a.entry.id for a in rows],
            miles=tenths / 10,
        ),
    )


_CALCULATED = ("doc_sha256", "extracted", "checks", "status", "reasons", "journal_draft", "mileage_claim")


async def propose_allowance(
    books: Books, tax_year: str, period: str, today: date | None = None
) -> tuple[Proposal, bool]:
    """Create (or bring up to date) the period's mileage allowance proposal; (proposal, created).

    Idempotent: while a claim for the period is waiting in Review it is the one returned, refreshed
    with any journeys logged since. Once posted, a later call claims only journeys not yet paid.
    """
    start, end = quarter_bounds(tax_year, period)
    today = today or london_today()
    if today < start:
        raise MileageError(f"{period} {tax_year} starts on {start:%d/%m/%Y}")
    covers_to = min(end, today)
    every = await mileage_claims(books, tax_year)
    paid = claimed_ids(every)
    waiting = next((c for c in every if c.mileage_claim.period == period and c.status in OPEN), None)  # type: ignore[union-attr]
    vehicles = await load_vehicles(books)
    rows = [
        a
        for a in allowances(await load_entries(books, tax_year), vehicles, paid)
        if start <= a.entry.date <= covers_to and a.entry.id not in paid and a.pence > 0
    ]
    if not rows and waiting is None:
        raise MileageError(f"No unclaimed business miles in personal vehicles for {period} {tax_year}")
    n = sum(c.mileage_claim.period == period for c in every)  # type: ignore[union-attr]
    fresh = claim_proposal(
        waiting.id if waiting else _claim_id(tax_year, period, n), tax_year, period, covers_to, rows, vehicles
    )
    if waiting is None:
        p = fresh.model_copy(update={"created_at": now()})
    else:  # keep its history (created_at, undone_events, ...): only what code calculated changes
        p = waiting.model_copy(update={k: getattr(fresh, k) for k in _CALCULATED})
        if p.model_dump() == waiting.model_dump():
            return waiting, False
    await books.save_proposal(p)
    await books.audit(
        ACTOR,
        "mileage_proposed" if waiting is None else "mileage_refreshed",
        {
            "proposal": p.id,
            "tax_year": tax_year,
            "period": period,
            "journeys": len(rows),
            "pence": round(p.extracted.gross_total * 100),
        },
    )
    return p, waiting is None


async def refresh_open_claims(books: Books, tax_year: str, today: date | None = None) -> None:
    """Bring claims still waiting in Review up to date after the log or a vehicle changed."""
    for c in await mileage_claims(books, tax_year):
        if c.status in OPEN:
            await propose_allowance(books, tax_year, c.mileage_claim.period, today)  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Changing vehicles and journeys
# --------------------------------------------------------------------------- #


async def _vehicle(books: Books, vehicle_id: str) -> Vehicle:
    v = next((v for v in await load_vehicles(books) if v.id == vehicle_id), None)
    if v is None:
        raise FileNotFoundError(vehicle_id)
    return v


async def add_vehicle(books: Books, v: Vehicle, user: str) -> Vehicle:
    v = v.model_copy(update={"id": _new_id()})
    await _change_vehicles(books, lambda vs: [*vs, v])
    await books.audit(f"user:{user}", "vehicle_added", {"vehicle": v.id, "kind": v.kind, "owned_by": v.owned_by})
    return v


async def update_vehicle(books: Books, vehicle_id: str, changes: dict, user: str) -> Vehicle:
    """Rename, re-register or (de)activate freely; kind and ownership only while no posted claim depends on them."""
    old = await _vehicle(books, vehicle_id)
    try:
        new = Vehicle.model_validate({**old.model_dump(), **changes, "id": old.id})
    except ValidationError as exc:
        raise MileageError(exc.errors()[0]["msg"]) from exc
    if (new.kind, new.owned_by) != (old.kind, old.owned_by):
        for ty in await logged_tax_years(books):
            lock = locked_until(await mileage_claims(books, ty))
            if lock and any(e.vehicle_id == vehicle_id and e.date <= lock for e in await load_entries(books, ty)):
                raise LockedError(
                    f"{old.name} has journeys in a posted mileage claim, so its type and ownership can't change. "
                    "Add it again as a new vehicle instead"
                )
    await _change_vehicles(books, lambda vs: [new if v.id == vehicle_id else v for v in vs])
    await books.audit(f"user:{user}", "vehicle_changed", {"vehicle": vehicle_id, "fields": sorted(changes)})
    if (new.kind, new.owned_by) != (old.kind, old.owned_by):
        for ty in await logged_tax_years(books):
            await refresh_open_claims(books, ty)
    return new


async def delete_vehicle(books: Books, vehicle_id: str, user: str) -> Vehicle:
    """Only a vehicle nothing refers to; otherwise mark it inactive."""
    v = await _vehicle(books, vehicle_id)
    for ty in await logged_tax_years(books):
        if any(e.vehicle_id == vehicle_id for e in await load_entries(books, ty)):
            raise MileageError(f"{v.name} has journeys in the mileage log. Mark it inactive instead")
    if any(p.vehicle_id == vehicle_id for p in await books.list_proposals()):
        raise MileageError(f"{v.name} has receipts tagged to it. Mark it inactive instead")
    await _change_vehicles(books, lambda vs: [x for x in vs if x.id != vehicle_id])
    await books.audit(f"user:{user}", "vehicle_deleted", {"vehicle": vehicle_id})
    return v


async def _known_vehicle(books: Books, vehicle_id: str) -> Vehicle:
    try:
        return await _vehicle(books, vehicle_id)
    except FileNotFoundError as exc:
        raise MileageError(f"No such vehicle {vehicle_id!r}") from exc


def _not_future(d: date) -> None:
    if d > london_today():
        raise MileageError("Log journeys once they have happened")


async def add_entry(books: Books, entry: MileageEntry, user: str) -> MileageEntry:
    entry = entry.model_copy(update={"id": _new_id()})
    await _known_vehicle(books, entry.vehicle_id)
    _not_future(entry.date)
    ty = tax_year_of(entry.date)
    _check_unlocked(entry, await mileage_claims(books, ty))
    await _change_entries(books, ty, lambda es: [*es, entry])
    await books.audit(f"user:{user}", "mileage_added", {"entry": entry.id, "tax_year": ty, "miles": entry.miles})
    await refresh_open_claims(books, ty)
    return entry


async def find_entry(books: Books, entry_id: str) -> tuple[str, MileageEntry]:
    """(tax year, journey). Raises FileNotFoundError."""
    if not re.fullmatch(r"[0-9a-f]{8,64}", entry_id):
        raise FileNotFoundError(entry_id)
    for ty in await logged_tax_years(books):
        if e := next((e for e in await load_entries(books, ty) if e.id == entry_id), None):
            return ty, e
    raise FileNotFoundError(entry_id)


async def update_entry(books: Books, entry_id: str, changes: dict, user: str) -> MileageEntry:
    old_ty, old = await find_entry(books, entry_id)
    try:
        new = MileageEntry.model_validate({**old.model_dump(by_alias=True), **changes, "id": old.id})
    except ValidationError as exc:
        raise MileageError(exc.errors()[0]["msg"]) from exc
    if new.vehicle_id != old.vehicle_id:
        await _known_vehicle(books, new.vehicle_id)
    _not_future(new.date)
    new_ty = tax_year_of(new.date)
    _check_unlocked(old, await mileage_claims(books, old_ty))
    _check_unlocked(new, await mileage_claims(books, new_ty))
    if new_ty == old_ty:
        await _change_entries(books, old_ty, lambda es: [new if e.id == entry_id else e for e in es])
    else:  # moved to another tax year's file: add there first, so a failure never loses the journey
        await _change_entries(books, new_ty, lambda es: [*es, new])
        await _change_entries(books, old_ty, lambda es: [e for e in es if e.id != entry_id])
    await books.audit(f"user:{user}", "mileage_changed", {"entry": entry_id, "fields": sorted(changes)})
    for ty in dict.fromkeys((old_ty, new_ty)):
        await refresh_open_claims(books, ty)
    return new


async def delete_entry(books: Books, entry_id: str, user: str) -> MileageEntry:
    ty, old = await find_entry(books, entry_id)
    _check_unlocked(old, await mileage_claims(books, ty))
    await _change_entries(books, ty, lambda es: [e for e in es if e.id != entry_id])
    await books.audit(f"user:{user}", "mileage_deleted", {"entry": entry_id, "tax_year": ty})
    await refresh_open_claims(books, ty)
    return old


# --------------------------------------------------------------------------- #
# Receipts tagged to business vehicles
# --------------------------------------------------------------------------- #

_VEHICLE_WORDS = re.compile(
    r"\b(fuel|petrol|diesel|unleaded|parking|car park|tolls?|congestion charge|dart charge|ulez|mot|tyres?)\b",
    re.IGNORECASE,
)


def is_vehicle_cost(doc: ExtractedDoc) -> bool:
    """Fuel, parking, tolls or repairs: any "Motor expenses" purchase, or a "Travel"/"Sundry" one that says so."""
    if doc.doc_type == "sales_invoice":
        return False
    if doc.category_guess == "Motor expenses":
        return True
    text = " ".join([doc.supplier_name, *(ln.description for ln in doc.lines)])
    return doc.category_guess in ("Travel", "Sundry") and _VEHICLE_WORDS.search(text) is not None


def prefill_vehicle(p: Proposal, vehicles: Iterable[Vehicle]) -> None:
    """Tag a vehicle cost to the user's only active business vehicle; with none or several, Review asks."""
    business = [v for v in vehicles if v.active and v.owned_by == "business"]
    if p.vehicle_id is None and len(business) == 1 and is_vehicle_cost(p.extracted):
        p.vehicle_id = business[0].id
        p.checks.append(
            Check(
                code="VEHICLE",
                ok=True,
                severity="warn",
                message=f"Tagged to {business[0].label()}, your only business vehicle",
            )
        )


def vehicle_cost_pence(p: Proposal) -> int:
    """What a posted purchase cost the business: its expense debits (reclaimable VAT is not a cost)."""
    return sum(j.debit_pence for j in p.journal_draft if j.account != VAT_CONTROL)


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #


class VehicleSummary(BaseModel):
    vehicle_id: str
    name: str
    registration: str | None
    kind: VehicleKind
    owned_by: Ownership
    active: bool
    miles: float
    journeys: int
    allowance_pence: int  # personal vehicles
    cost_pence: int  # business vehicles: posted receipts tagged to it, dated in the tax year
    cost_entries: int
    pence_per_mile: int | None  # cost (business) or allowance (personal) per business mile


class QuarterSummary(BaseModel):
    period: str
    start: date
    end: date
    miles: float
    allowance_pence: int
    claimed_pence: int  # in posted claims
    unclaimed_pence: int
    waiting_claim_id: str | None  # a claim in Review


class RateRow(BaseModel):
    kind: VehicleKind
    first_pence: int
    after_pence: int
    threshold_miles: int | None


class MileageSummary(BaseModel):
    tax_year: str
    start: date
    end: date
    vehicles: list[VehicleSummary]
    car_van_miles: float  # personal cars and vans: the miles counted towards the threshold
    threshold_miles: int
    threshold_crossed_on: date | None
    allowance_pence: int
    claimed_pence: int
    quarters: list[QuarterSummary]
    locked_until: date | None
    rates: list[RateRow]
    notes: list[str]


async def summary(books: Books, tax_year: str) -> MileageSummary:
    start, end = tax_year_bounds(tax_year)
    vehicles = await load_vehicles(books)
    claims = await mileage_claims(books, tax_year)
    paid = claimed_ids(claims)
    rows = allowances(await load_entries(books, tax_year), vehicles, paid)
    posted = [p for p in await books.list_proposals("posted") if p.vehicle_id]
    by_id = {v.id: v for v in vehicles}

    def in_year(p: Proposal) -> bool:
        try:
            return start <= date.fromisoformat(p.extracted.date) <= end
        except ValueError:
            return False

    per_vehicle = []
    for v in vehicles:
        mine = [a for a in rows if a.entry.vehicle_id == v.id]
        tenths = sum(a.entry.tenths for a in mine)
        costs = [p for p in posted if p.vehicle_id == v.id and in_year(p)]
        cost = sum(vehicle_cost_pence(p) for p in costs)
        allowance = sum(a.pence for a in mine)
        spend = cost if v.owned_by == "business" else allowance
        per_vehicle.append(
            VehicleSummary(
                vehicle_id=v.id,
                name=v.name,
                registration=v.registration,
                kind=v.kind,
                owned_by=v.owned_by,
                active=v.active,
                miles=tenths / 10,
                journeys=len(mine),
                allowance_pence=allowance,
                cost_pence=cost,
                cost_entries=len(costs),
                pence_per_mile=round(spend * 10 / tenths) if tenths else None,
            )
        )
    quarters = []
    for q in QUARTERS:
        qs, qe = quarter_bounds(tax_year, q)
        mine = [a for a in rows if qs <= a.entry.date <= qe]
        mine_claims = [c for c in claims if c.mileage_claim.period == q]  # type: ignore[union-attr]
        quarters.append(
            QuarterSummary(
                period=q,
                start=qs,
                end=qe,
                miles=sum(a.entry.tenths for a in mine) / 10,
                allowance_pence=sum(a.pence for a in mine),
                claimed_pence=sum(round(c.extracted.gross_total * 100) for c in _posted(mine_claims)),
                unclaimed_pence=sum(a.pence for a in mine if a.entry.id not in paid),
                waiting_claim_id=next((c.id for c in mine_claims if c.status in OPEN), None),
            )
        )
    rates = rates_for(tax_year)
    thresholded = [
        a
        for a in rows
        if (v := by_id.get(a.entry.vehicle_id)) and v.owned_by == "personal" and rates[v.kind].threshold_miles
    ]
    return MileageSummary(
        tax_year=tax_year,
        start=start,
        end=end,
        vehicles=per_vehicle,
        car_van_miles=sum(a.entry.tenths for a in thresholded) / 10,
        threshold_miles=THRESHOLD_MILES,
        threshold_crossed_on=threshold_crossed_on(rows),
        allowance_pence=sum(a.pence for a in rows),
        claimed_pence=sum(q.claimed_pence for q in quarters),
        quarters=quarters,
        locked_until=locked_until(claims),
        rates=[
            RateRow(kind=k, first_pence=r.first_pence, after_pence=r.after_pence, threshold_miles=r.threshold_miles)  # type: ignore[arg-type]
            for k, r in rates.items()
        ],
        notes=[ALLOWANCE_NOTE, FUEL_SCALE_NOTE],
    )
