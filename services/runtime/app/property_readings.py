"""Property documents read by the user's AI, waiting for the user: letting agent statements, bills for work on a
let property, landlord insurance schedules and mortgage statements (AI proposes, user approves, code calculates).

A document in `00 Inbox` (uploaded, or copied there by Outlook intake) is read by app/ai/property_read.py, but only
for a business with a property profile (landlord mode on, or properties on the register). Code turns the printed
pounds into pence, matches the property by code (address tokens against the register; never invented), checks that
the lines add up to the printed totals (a mortgage statement's interest and capital split is worked out here, and
capital repaid is kept as information, never an expense), and saves a reading in `_System/Property/readings/<id>.json`.
Nothing is kept or posted until the user approves, with the figures as read or as corrected on the card: each
income or cost line becomes a property entry (app/property.add_entry) tagged to the property. Rejecting keeps the
reading, marked rejected. The document stays where it is.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import cis, paths
from app import property as pr
from app.ai.config import AiConfig
from app.ai.property_read import PropertyReading, read_property_document, to_date, to_pence
from app.books import Books, now
from app.formats import prepare
from app.validation import LENIENT, Day, StrictBody, check_name

READINGS = f"{pr.PROPERTY}/readings"

ReadingStatus = Literal["pending", "approved", "rejected"]

_GAP = re.compile(r"[^a-z0-9]+")
_STOP = {"the", "flat", "house", "and", "of", "at", "no", "number"}


def _tokens(text: str) -> set[str]:
    return {t for t in _GAP.split(text.lower()) if len(t) > 2 and t not in _STOP}


def match_property(properties: list[pr.Property], text: str | None) -> pr.Property | None:
    """The register entry whose address the printed `text` names, or None: code matches, the model never invents.

    A squashed-postcode hit wins outright; otherwise the property sharing the most address tokens wins, but only
    when it shares at least two and strictly more than any other. Anything else (nothing printed, a tie, too
    little to go on) is None: the user picks the property when approving.
    """
    text = text or ""
    if not text.strip():
        return None
    squashed = _GAP.sub("", text.lower())
    if squashed:
        hits = [p for p in properties if p.postcode and _GAP.sub("", p.postcode.lower()) in squashed]
        if len(hits) == 1:
            return hits[0]
    scored = sorted(((len(_tokens(text) & _tokens(f"{p.address or ''} {p.postcode or ''}"))), p) for p in properties)
    if len(scored) >= 1 and scored[-1][0] >= 2 and (len(scored) == 1 or scored[-1][0] > scored[-2][0]):
        return scored[-1][1]
    return None


class ReadLine(BaseModel):
    """One money line as read, in integer pence (signed as printed)."""

    description: str = ""
    category: pr.CategoryKey = "other"  # type: ignore[assignment]
    amount_pence: int = 0
    vat_pence: int | None = None
    capital: bool = False  # repays capital (mortgage capital): kept as information, never an expense
    info: bool = False  # already included in another line's amount (payout, an `of which` line)
    replacement: bool = False  # a replacement of an item already in the let property (like for like)


class Reading(BaseModel):
    id: str
    path: str  # the document in the books
    sha256: str
    kind: str
    date: Day | None = None
    period_start: Day | None = None
    period_end: Day | None = None
    counterparty: str | None = None
    property_id: str | None = None  # matched by code; None asks the user to pick it when approving
    property_text: str | None = None  # the address as printed
    lines: list[ReadLine] = Field(default_factory=list)
    total_pence: int | None = None  # the headline total as printed (payout, Total, payments made, premium)
    interest_pence: int = 0  # mortgage interest: the finance cost (a tax credit, not an expense)
    capital_pence: int = 0  # mortgage capital repaid: information, never posted
    problems: list[str] = []  # what stopped code filling a field
    checks: list[cis.Check] = []
    confidence: float = 0
    model: str = ""
    status: ReadingStatus = "pending"
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    event_ids: list[str] = []  # after approval


def _why(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    found: Any = errors() if callable(errors) else None
    return str(found[0]["msg"]) if found else str(exc)


def expense_lines(reading: Reading) -> list[ReadLine]:
    """Lines approval posts: money that moved, each once (no `of which` lines, no capital repaid, no nil lines)."""
    return [ln for ln in reading.lines if not ln.info and not ln.capital and ln.amount_pence != 0]


def from_reading(read: PropertyReading, properties: list[pr.Property], path: str) -> tuple[Reading, list[str]]:
    """Code's half: pounds to pence, dates parsed, the property matched, the lines checked against the totals."""
    problems: list[str] = []
    day = to_date(read.date)
    if day is None:
        problems.append("No document date read")
    if read.kind == "other":
        problems.append(
            "This does not look like a letting statement, a bill, an insurance schedule or a mortgage statement"
        )
    if not read.lines:
        problems.append("No money lines read")
    total = to_pence(read.total)
    if total is None:
        problems.append("No headline total read")
    lines: list[ReadLine] = []
    for ln in read.lines:
        amount = to_pence(ln.amount)
        if ln.category not in pr.BY_KEY:
            problems.append(f"Unknown category read: {ln.category or '(blank)'}")
            continue
        if amount is None:
            problems.append(f"No amount read for: {(ln.description or 'a line')[:60]}")
            continue
        lines.append(
            ReadLine(
                description=(ln.description or "")[:140],
                category=ln.category,  # type: ignore[arg-type]
                amount_pence=amount,
                vat_pence=to_pence(ln.vat),
                capital=ln.capital,
                info=ln.info,
                replacement=ln.replacement,
            )
        )
    prop = match_property(properties, read.property_text)
    if read.property_text and prop is None:
        problems.append("No let property matches the address printed; choose the property when approving")
    if not read.property_text:
        problems.append("No property address read; choose the property when approving")
    checks: list[cis.Check] = []
    if total is not None and lines:
        s = sum(ln.amount_pence for ln in lines if not ln.info)
        checks.append(
            cis.Check(
                code="LINES_SUM",
                ok=abs(s - total) <= 1,
                message=f"Lines add up to the printed total of {cis.money(total)}"
                if abs(s - total) <= 1
                else f"Lines add up to {cis.money(s)}, not the printed total of {cis.money(total)}",
            )
        )
    interest = sum(ln.amount_pence for ln in lines if ln.category == "finance_res" and not ln.capital and not ln.info)
    capital = sum(ln.amount_pence for ln in lines if ln.capital)
    if read.kind == "mortgage_statement" and total is not None and lines:
        ok = interest > 0 and capital >= 0 and abs(interest + capital - total) <= 1
        checks.append(
            cis.Check(
                code="MORTGAGE_SPLIT",
                ok=ok,
                message=f"Interest of {cis.money(interest)} is the finance cost; capital of {cis.money(capital)} "
                "repaid is not an expense"
                if ok
                else "The interest and capital split does not add up to the payments made",
            )
        )
    reading = Reading(
        id=uuid.uuid4().hex[:16],
        path=path,
        sha256="",
        kind=read.kind,
        date=day,
        period_start=to_date(read.period_start),
        period_end=to_date(read.period_end),
        counterparty=(read.counterparty or "")[:200] or None,
        property_id=prop.id if prop else None,
        property_text=(read.property_text or "")[:200] or None,
        lines=lines,
        total_pence=total,
        interest_pence=interest,
        capital_pence=capital,
        problems=problems,
        checks=checks,
        confidence=read.confidence,
        created_at=now(),
    )
    return reading, problems


def _path(reading_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{16}", reading_id):
        raise FileNotFoundError(reading_id)
    return f"{READINGS}/{reading_id}.json"


async def get_reading(books: Books, reading_id: str) -> Reading:
    return Reading.model_validate_json(await books.storage.read(_path(reading_id)), **LENIENT)


async def save_reading(books: Books, r: Reading) -> None:
    await books.write_json(_path(r.id), r.model_dump(mode="json"))


async def list_readings(books: Books, status: ReadingStatus | None = None) -> list[Reading]:
    files = [f for f in await books.list_files(READINGS) if re.fullmatch(r"[0-9a-f]{16}\.json", f.name)]

    async def one(path: str) -> Reading:
        return Reading.model_validate_json(await books.storage.read(path), **LENIENT)

    out = [r for r in await asyncio.gather(*(one(f.path) for f in files)) if status is None or r.status == status]
    return sorted(out, key=lambda r: r.created_at, reverse=True)


async def has_property_profile(books: Books) -> bool:
    """Landlord mode is on, or the register holds properties: property documents have a reader to go to."""
    settings = await pr.load_settings(books)
    if settings.landlord_mode:
        return True
    return bool(await pr.load_properties(books))


async def read_document(books: Books, name: str, cfg: AiConfig, user: str) -> Reading:
    """Read `00 Inbox/<name>` with the user's AI and save what code made of it, waiting for the user."""
    if not await has_property_profile(books):
        raise pr.PropertyError("Turn on landlord mode in Settings › Business › I let property first")
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
    read, meta = await read_property_document(prepared.image, prepared.mime, cfg, text=text)
    reading, _ = from_reading(read, await pr.load_properties(books), path)
    reading.sha256, reading.model = digest, str(meta.get("model", ""))
    await save_reading(books, reading)
    await books.audit(
        "agent:property-reader",
        "property_document_read",
        {"reading": reading.id, "file": path, "kind": reading.kind, "requested_by": user},
    )
    return reading


class DecideBody(StrictBody):
    property_id: str | None = Field(None, max_length=40)  # the property, when the address did not match one


def _entry_bodies(reading: Reading, property_id: str, prop: pr.Property) -> list[pr.EntryIn]:
    out: list[pr.EntryIn] = []
    if reading.date is None:
        raise pr.PropertyError("Fill in the document's date first")
    for ln in expense_lines(reading):
        cat = pr._for_use(pr.BY_KEY[ln.category], prop.use)
        if cat.key == "rent_a_room" and prop.use != "rent_a_room":
            raise pr.PropertyError("Rent a Room rents are only for a room let in your own home")
        if cat.key == "domestic_items":
            if prop.use != "residential":
                raise pr.PropertyError("replacement of domestic items relief is for residential lets only")
            if not ln.replacement:
                raise pr.PropertyError(
                    "replacement of domestic items covers like-for-like replacements, not first purchases"
                )
        try:
            kind: pr.EntryIn = pr.EntryIn(
                property_id=property_id,
                date=reading.date,
                category=cat.key,  # type: ignore[arg-type]
                amount_pence=abs(ln.amount_pence),
                description=ln.description or cat.label,
                replacing_existing_item=bool(ln.replacement),
            )
        except ValueError as exc:
            raise pr.PropertyError(f"Fill in the line's figures first: {_why(exc)}") from exc
        out.append(kind)
    return out


async def approve(books: Books, reading_id: str, body: DecideBody, user: str) -> Reading:
    r = await get_reading(books, reading_id)
    if r.status != "pending":
        raise pr.PropertyError(f"This reading was already {r.status}")
    if r.kind == "other" or not expense_lines(r):
        raise pr.PropertyError("Nothing to approve: reject it instead")
    property_id = body.property_id or r.property_id
    if property_id is None:
        raise pr.PropertyError("Choose the property this document belongs to first")
    prop = next((p for p in await pr.load_properties(books) if p.id == property_id), None)
    if prop is None:
        raise pr.PropertyError("no such property")
    if r.problems and not (len(r.problems) == 1 and r.property_id is None and body.property_id):
        raise pr.PropertyError(f"Fill in the figures first: {r.problems[0]}")
    bodies = _entry_bodies(r, property_id, prop)
    if not bodies:
        raise pr.PropertyError("Nothing to approve: reject it instead")
    r.event_ids = [(await pr.add_entry(books, b, user))[0].id for b in bodies]
    r.property_id = property_id
    r.status, r.decided_by, r.decided_at = "approved", user, now()
    await save_reading(books, r)
    await books.audit(f"user:{user}", "property_reading_approved", {"reading": r.id, "kind": r.kind})
    return r


async def reject(books: Books, reading_id: str, user: str) -> Reading:
    r = await get_reading(books, reading_id)
    if r.status != "pending":
        raise pr.PropertyError(f"This reading was already {r.status}")
    r.status, r.decided_by, r.decided_at = "rejected", user, now()
    await save_reading(books, r)
    await books.audit(f"user:{user}", "property_reading_rejected", {"reading": r.id, "kind": r.kind})
    return r
