"""Vehicles, mileage and the approved mileage allowance (app/mileage.py) against FakeStorageProvider."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.events import LedgerEvent, VatCode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mileage as m  # noqa: E402
from app.approve import ApprovalError, approve, undo  # noqa: E402
from app.autopilot import load_rules as load_autopilot_rules  # noqa: E402
from app.books import EVENTS, Books  # noqa: E402
from app.journal import OWNER_LOAN, draft_journal  # noqa: E402
from app.schemas import MILEAGE_CATEGORY, ExtractedDoc, ExtractedLine, Proposal  # noqa: E402

USER = "sam@example.co.uk"


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


def car(**kw: object) -> m.Vehicle:
    return m.Vehicle.model_validate({"name": "Golf", "kind": "car", "owned_by": "personal", **kw})


def trip(vehicle: m.Vehicle, d: str, miles: float, **kw: object) -> m.MileageEntry:
    return m.MileageEntry.model_validate({"vehicle_id": vehicle.id, "date": d, "miles": miles, "purpose": "Site visit", **kw})


def trips(vehicle: m.Vehicle, d: str, total: float) -> list[m.MileageEntry]:
    """`total` miles on one day as journeys of at most 1,000 miles (one journey is capped at 2,000)."""
    out, left, i = [], round(total * 10), 0
    while left:
        chunk = min(left, 10_000)
        out.append(trip(vehicle, d, chunk / 10, id=f"{d.replace('-', '')}{i:024x}"))
        left, i = left - chunk, i + 1
    return out


def _events(fake: FakeStorageProvider) -> list[LedgerEvent]:
    return [LedgerEvent.model_validate_json(d) for p, d in fake.files.items() if p.startswith(f"{EVENTS}/")]


# --------------------------------------------------------------------------- #
# Tax years
# --------------------------------------------------------------------------- #


def test_tax_year_runs_6_april_to_5_april() -> None:
    assert m.tax_year_of(date(2026, 4, 5)) == "2025-26"
    assert m.tax_year_of(date(2026, 4, 6)) == "2026-27"
    assert m.tax_year_of(date(2027, 1, 1)) == "2026-27"
    assert m.tax_year_of(date(1999, 12, 31)) == "1999-00"
    assert m.tax_year_bounds("2026-27") == (date(2026, 4, 6), date(2027, 4, 5))
    for bad in ("2026-28", "2026", "26-27", "../x"):
        with pytest.raises(m.MileageError):
            m.tax_year_bounds(bad)


def test_quarters_of_the_tax_year() -> None:
    assert m.quarter_bounds("2026-27", "Q1") == (date(2026, 4, 6), date(2026, 7, 5))
    assert m.quarter_bounds("2026-27", "Q3") == (date(2026, 10, 6), date(2027, 1, 5))
    assert m.quarter_bounds("2026-27", "Q4") == (date(2027, 1, 6), date(2027, 4, 5))
    assert (m.quarter_of(date(2026, 7, 5)), m.quarter_of(date(2026, 7, 6))) == ("Q1", "Q2")
    assert m.quarter_of(date(2027, 4, 5)) == "Q4"
    with pytest.raises(m.MileageError):
        m.quarter_bounds("2026-27", "Q5")


# --------------------------------------------------------------------------- #
# Rates and the 10,000-mile threshold
# --------------------------------------------------------------------------- #


def test_one_rates_table_with_hmrc_rates() -> None:
    assert {k: (r.first_pence, r.after_pence, r.threshold_miles) for k, r in m.RATES.items()} == {
        "car": (45, 25, 10_000), "van": (45, 25, 10_000), "motorcycle": (24, 24, None), "bicycle": (20, 20, None),
    }


def test_journey_crossing_10000_miles_is_split() -> None:
    golf = car()
    *before, crossing = m.allowances([*trips(golf, "2026-05-01", 9990.0), trip(golf, "2026-06-01", 20.5)], [golf])
    assert sum(a.pence for a in before) == 449_550  # 9,990 × 45p
    assert (crossing.first_tenths, crossing.after_tenths) == (100, 105)
    assert crossing.pence == 713  # 10 × 45p + 10.5 × 25p = 712.5p, rounded half up
    assert m.threshold_crossed_on([*before, crossing]) == date(2026, 6, 1)


def test_exactly_10000_miles_is_all_at_45p_and_the_next_mile_at_25p() -> None:
    golf = car()
    rows = m.allowances([trip(golf, "2026-05-01", 1000.0, id=f"{i:032x}") for i in range(10)] + [trip(golf, "2026-05-02", 1.0)], [golf])
    assert sum(a.pence for a in rows[:10]) == 450_000
    assert m.threshold_crossed_on(rows[:10]) is None
    assert rows[10].pence == 25 and m.threshold_crossed_on(rows) == date(2026, 5, 2)


def test_threshold_is_shared_by_cars_and_vans_only() -> None:
    golf, van = car(), car(name="Transit", kind="van")
    bike, moto = car(name="Bike", kind="bicycle"), car(name="Moto", kind="motorcycle")
    works = car(name="Works van", kind="van", owned_by="business")
    entries = [
        *trips(golf, "2026-05-01", 6000.0), *trips(van, "2026-05-02", 5000.0),
        trip(bike, "2026-05-03", 100.0), trip(moto, "2026-05-04", 100.0), trip(works, "2026-05-05", 500.0),
    ]
    rows = m.allowances(entries, [golf, van, bike, moto, works])

    def total(v: m.Vehicle, attr: str = "pence") -> int:
        return sum(getattr(a, attr) for a in rows if a.entry.vehicle_id == v.id)

    assert total(golf) == 270_000
    assert (total(van, "first_tenths"), total(van, "after_tenths")) == (40_000, 10_000)
    assert total(van) == 4000 * 45 + 1000 * 25
    assert total(bike) == 2000 and total(moto) == 2400
    assert total(works) == 0  # business vehicle: actual costs instead


def test_tenth_of_a_mile_rounds_half_up() -> None:
    golf = car()
    assert m.allowances([trip(golf, "2026-05-01", 0.1)], [golf])[0].pence == 5  # 4.5p


def test_miles_go_in_tenths() -> None:
    golf = car()
    assert trip(golf, "2026-05-01", 12.3).miles == 12.3
    for bad in (1.25, 0, -1, 2000.1):
        with pytest.raises(ValueError):
            trip(golf, "2026-05-01", bad)


def test_entry_round_trips_from_alias() -> None:
    e = m.MileageEntry.model_validate({"vehicle_id": "v", "date": "2026-05-01", "from": "Leeds", "to": "York", "miles": 25, "purpose": "Quote"})
    assert e.from_ == "Leeds" and e.model_dump(by_alias=True)["from"] == "Leeds"
    assert e.job_id is None and e.source == "manual"


# --------------------------------------------------------------------------- #
# Files: the tax-year boundary decides the file, the threshold resets each year
# --------------------------------------------------------------------------- #


async def test_entries_are_filed_by_tax_year_and_threshold_resets(books: Books, fake: FakeStorageProvider) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    for e in [*trips(golf, "2025-04-05", 10_000.0), *trips(golf, "2025-04-06", 10_000.0), trip(golf, "2026-04-05", 2.0)]:
        await m.add_entry(books, e, USER)
    assert {p for p in fake.files if p.startswith("_System/Mileage/")} == {
        "_System/Mileage/2024-25.jsonl", "_System/Mileage/2025-26.jsonl",
    }
    s = await m.summary(books, "2025-26")
    assert s.car_van_miles == 10_002.0
    assert s.allowance_pence == 450_000 + 50  # 6 April starts a new 10,000 miles; 2 miles at 25p
    assert s.threshold_crossed_on == date(2026, 4, 5)
    prev = await m.summary(books, "2024-25")
    assert prev.allowance_pence == 450_000 and prev.threshold_crossed_on is None


async def test_moving_a_journey_across_5_april_moves_it_to_the_other_file(books: Books) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    e = await m.add_entry(books, trip(golf, "2026-04-06", 10.0), USER)
    await m.update_entry(books, e.id, {"date": "2026-04-05"}, USER)
    assert await m.load_entries(books, "2026-27") == []
    assert [x.id for x in await m.load_entries(books, "2025-26")] == [e.id]


async def test_entry_needs_a_known_vehicle_and_a_past_date(books: Books) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    with pytest.raises(m.MileageError):
        await m.add_entry(books, trip(car(), "2026-05-01", 1.0), USER)
    with pytest.raises(m.MileageError):
        await m.add_entry(books, trip(golf, "2099-05-01", 1.0), USER)


# --------------------------------------------------------------------------- #
# Claims
# --------------------------------------------------------------------------- #


async def test_claim_is_a_proposal_and_idempotent_per_period(books: Books, fake: FakeStorageProvider) -> None:
    golf = await m.add_vehicle(books, car(registration=" ab12  cde "), USER)
    await m.add_entry(books, trip(golf, "2025-10-10", 100.0), USER)
    await m.add_entry(books, trip(golf, "2025-12-01", 23.4), USER)
    await m.add_entry(books, trip(golf, "2026-01-10", 50.0), USER)  # Q4, not in this claim

    p, created = await m.propose_allowance(books, "2025-26", "Q3")
    assert created and p.status == "proposed" and p.vehicle_id is None
    assert p.extracted.category_guess == MILEAGE_CATEGORY
    assert p.extracted.gross_total == 55.53  # 123.4 × 45p
    assert p.extracted.date == "2026-01-05"
    assert p.extracted.lines[0].description == "Golf (AB12 CDE), car: 123.4 mi at 45p"
    assert p.mileage_claim and p.mileage_claim.miles == 123.4 and len(p.mileage_claim.entry_ids) == 2
    assert {j.vat_code for j in p.journal_draft} == {"N", None}
    assert [j.account for j in p.journal_draft] == ["7310 Motor — mileage allowance", OWNER_LOAN]

    again, created = await m.propose_allowance(books, "2025-26", "Q3")
    assert not created and again.id == p.id
    assert sum(path.startswith("_System/proposals/") for path in fake.files) == 1

    await m.add_entry(books, trip(golf, "2025-12-02", 10.0), USER)  # refreshes the claim waiting in Review
    refreshed = await books.get_proposal(p.id)
    assert refreshed.extracted.gross_total == 60.03 and refreshed.created_at == p.created_at


async def test_nothing_to_claim(books: Books) -> None:
    works = await m.add_vehicle(books, car(name="Works van", kind="van", owned_by="business"), USER)
    await m.add_entry(books, trip(works, "2025-10-10", 100.0), USER)
    with pytest.raises(m.MileageError, match="No unclaimed"):
        await m.propose_allowance(books, "2025-26", "Q3")
    with pytest.raises(m.MileageError, match="starts on"):
        await m.propose_allowance(books, "2026-27", "Q4", today=date(2026, 10, 27))


async def test_claim_this_quarter_so_far(books: Books) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    await m.add_entry(books, trip(golf, "2025-10-10", 10.0), USER)
    p, _ = await m.propose_allowance(books, "2025-26", "Q3", today=date(2025, 11, 1))
    assert p.extracted.date == "2025-11-01" and p.mileage_claim and p.mileage_claim.covers_to == date(2025, 11, 1)


async def test_approved_claim_posts_no_vat_owed_to_owner_and_never_becomes_a_rule(books: Books, fake: FakeStorageProvider) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    await m.add_entry(books, trip(golf, "2025-10-10", 100.0), USER)
    p, _ = await m.propose_allowance(books, "2025-26", "Q3")
    with pytest.raises(ApprovalError, match="calculated by code"):
        await approve(books, p.id, USER, {"gross_total": 999})
    posted = await approve(books, p.id, USER, always=True)
    assert posted.status == "posted"
    (ev,) = _events(fake)
    assert ev.kind == "purchase" and ev.vat == 0 and ev.net == 4500 and ev.counterparty == "Mileage allowance"
    assert [(ln.account, ln.debit, ln.credit, ln.vat_code) for ln in ev.lines] == [
        ("7310 Motor — mileage allowance", 4500, 0, VatCode.NO_VAT), (OWNER_LOAN, 0, 4500, None),
    ]
    assert await load_autopilot_rules(books) == [] and await books.load_rules() == []


async def test_posted_claim_locks_its_journeys_and_earlier_ones(books: Books) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    e = await m.add_entry(books, trip(golf, "2025-10-10", 100.0), USER)
    p, _ = await m.propose_allowance(books, "2025-26", "Q3", today=date(2025, 11, 1))
    await approve(books, p.id, USER)

    with pytest.raises(m.LockedError):
        await m.update_entry(books, e.id, {"miles": 50}, USER)
    with pytest.raises(m.LockedError):
        await m.delete_entry(books, e.id, USER)
    with pytest.raises(m.LockedError):  # before the claim's date: would change which rate later journeys get
        await m.add_entry(books, trip(golf, "2025-10-31", 1.0), USER)
    with pytest.raises(m.LockedError):
        await m.update_vehicle(books, golf.id, {"owned_by": "business"}, USER)
    await m.update_vehicle(books, golf.id, {"name": "Old Golf"}, USER)  # renaming is fine

    # Journeys on or after the claim's date go into a second claim for the same quarter.
    await m.add_entry(books, trip(golf, "2025-11-01", 10.0), USER)
    top_up, created = await m.propose_allowance(books, "2025-26", "Q3")
    assert created and top_up.id != p.id and top_up.extracted.gross_total == 4.50
    s = await m.summary(books, "2025-26")
    q3 = next(q for q in s.quarters if q.period == "Q3")
    assert (q3.allowance_pence, q3.claimed_pence, q3.unclaimed_pence, q3.waiting_claim_id) == (4950, 4500, 450, top_up.id)
    assert s.locked_until == date(2025, 11, 1)


async def test_claimed_journeys_keep_their_rate_when_a_same_day_journey_is_added(books: Books) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    for e in [*trips(golf, "2025-05-01", 9_999.0), trip(golf, "2025-07-05", 1.0)]:
        await m.add_entry(books, e, USER)
    p, _ = await m.propose_allowance(books, "2025-26", "Q1")
    await approve(books, p.id, USER)
    await m.add_entry(books, trip(golf, "2025-07-05", 5.0), USER)  # same day as the claim's last journey
    s = await m.summary(books, "2025-26")
    q1 = next(q for q in s.quarters if q.period == "Q1")
    assert q1.claimed_pence == 450_000 and q1.unclaimed_pence == 125  # the new 5 miles are past 10,000


async def test_undone_claim_comes_back_and_refreshes_without_losing_its_history(books: Books) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    e = await m.add_entry(books, trip(golf, "2025-10-10", 100.0), USER)
    p, _ = await m.propose_allowance(books, "2025-26", "Q3")
    posted = await approve(books, p.id, USER)
    _, back = await undo(books, posted.event_id or "", USER)
    assert back and back.status == "proposed"
    await m.update_entry(books, e.id, {"miles": 200}, USER)  # unlocked again
    again = await books.get_proposal(p.id)
    assert again.extracted.gross_total == 90.0 and again.undone_events == [posted.event_id]
    reposted = await approve(books, p.id, USER)
    assert reposted.event_id != posted.event_id


async def test_deleting_a_vehicle_in_use_is_refused(books: Books) -> None:
    golf = await m.add_vehicle(books, car(), USER)
    spare = await m.add_vehicle(books, car(name="Spare"), USER)
    await m.add_entry(books, trip(golf, "2025-10-10", 1.0), USER)
    with pytest.raises(m.MileageError, match="inactive"):
        await m.delete_vehicle(books, golf.id, USER)
    await m.delete_vehicle(books, spare.id, USER)
    assert [v.id for v in await m.load_vehicles(books)] == [golf.id]


# --------------------------------------------------------------------------- #
# Receipts tagged to business vehicles
# --------------------------------------------------------------------------- #


def _receipt(category: str = "Motor expenses", supplier: str = "Shell", description: str = "Unleaded") -> ExtractedDoc:
    return ExtractedDoc(
        doc_type="receipt", supplier_name=supplier, supplier_vat_number="GB 232 4567 89", customer_name=None,
        invoice_number=None, date="2025-10-21", currency="GBP",
        lines=[ExtractedLine(description=description, qty=1, unit_price=60, net=50, vat_rate=20, vat=10)],
        net_total=50, vat_total=10, gross_total=60, payment_method="card", card_last4="1234",
        category_guess=category, confidence=0.9,
    )


def _proposal(doc: ExtractedDoc) -> Proposal:
    return Proposal(
        id=uuid.uuid4().hex, doc_sha256="0" * 64, extracted=doc, checks=[], status="proposed", reasons=[],
        suggested_filename="r.jpg", journal_draft=draft_journal(doc), model="stub", elapsed_s=0,
    )


def test_vehicle_costs_are_recognised() -> None:
    assert m.is_vehicle_cost(_receipt())
    assert m.is_vehicle_cost(_receipt("Travel", "NCP", "Car park 2 hrs"))
    assert m.is_vehicle_cost(_receipt("Sundry", "Dartford Crossing", "Dart Charge"))
    assert not m.is_vehicle_cost(_receipt("Travel", "LNER", "Leeds to York"))
    assert not m.is_vehicle_cost(_receipt("Materials", "Screwfix", "Diesel heater"))


def test_only_business_vehicle_is_prefilled() -> None:
    works = car(name="Transit", kind="van", owned_by="business")
    p = _proposal(_receipt())
    m.prefill_vehicle(p, [works, car(), car(name="Old van", kind="van", owned_by="business", active=False)])
    assert p.vehicle_id == works.id and p.checks[-1].code == "VEHICLE" and p.checks[-1].ok

    for vehicles in ([], [car()], [works, car(name="Caddy", kind="van", owned_by="business")]):
        q = _proposal(_receipt())
        m.prefill_vehicle(q, vehicles)
        assert q.vehicle_id is None and q.checks == []
    q = _proposal(_receipt("Materials", "Screwfix", "Screws"))
    m.prefill_vehicle(q, [works])
    assert q.vehicle_id is None


async def test_approve_tags_a_business_vehicle_and_counts_its_costs(books: Books) -> None:
    works = await m.add_vehicle(books, car(name="Transit", kind="van", owned_by="business"), USER)
    golf = await m.add_vehicle(books, car(), USER)
    await m.add_entry(books, trip(works, "2025-10-20", 100.0), USER)
    p, q, r = (_proposal(_receipt()) for _ in range(3))
    for x in (p, q, r):
        await books.save_proposal(x)

    with pytest.raises(ApprovalError, match="personal vehicle"):
        await approve(books, p.id, USER, {"vehicle_id": golf.id})
    with pytest.raises(ApprovalError, match="No such vehicle"):
        await approve(books, p.id, USER, {"vehicle_id": "f" * 32})
    assert (await approve(books, p.id, USER, {"vehicle_id": works.id})).vehicle_id == works.id
    assert (await approve(books, q.id, USER, {"vehicle_id": None})).vehicle_id is None

    s = await m.summary(books, "2025-26")
    van = next(v for v in s.vehicles if v.vehicle_id == works.id)
    assert (van.cost_pence, van.cost_entries, van.allowance_pence, van.pence_per_mile) == (5000, 1, 0, 50)
    assert m.FUEL_SCALE_NOTE in s.notes and "ask your accountant" in m.FUEL_SCALE_NOTE

    for e in await m.load_entries(books, "2025-26"):  # leave the tagged receipt as the only use of the van
        await m.delete_entry(books, e.id, USER)
    with pytest.raises(m.MileageError, match="tagged"):
        await m.delete_vehicle(books, works.id, USER)
