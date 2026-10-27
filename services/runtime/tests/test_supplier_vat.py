"""The books remember whether each supplier should show a VAT number: scan -> question -> tick -> remembered.

Extraction is stubbed (fake storage, no model). The rules themselves are tested one by one in test_checks_journal.py.
"""

from __future__ import annotations

import json

import pytest
from accnomos_connectors import FakeStorageProvider
from fastapi.testclient import TestClient

from app import contacts as cb
from app import invoicing, pipeline
from app.ai.config import AiConfig
from app.approve import NOT_VAT_REGISTERED, ApprovalError, approve
from app.books import AUDIT, Books
from app.checks import SUPPLIER_VAT_UNKNOWN
from app.contacts import CONTACTS
from app.inbox import scan_inbox
from app.schemas import ExtractedDoc, ExtractedLine

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")
USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}


def _doc(supplier: str, gross: float, vat: float = 0.0, vrn: str | None = None, day: str = "2026-10-21") -> ExtractedDoc:
    net = round(gross - vat, 2)
    return ExtractedDoc(
        doc_type="receipt", supplier_name=supplier, supplier_vat_number=vrn, customer_name=None, invoice_number=None,
        date=day, currency="GBP",
        lines=[ExtractedLine(description="Goods", qty=1, unit_price=net, net=net, vat_rate=20 if vat else None, vat=vat)],
        net_total=net, vat_total=vat, gross_total=gross, payment_method="card", card_last4="9304",
        category_guess="Materials", confidence=0.95,
    )


IRONMONGER = "Hargreaves & Sons Ironmongery"
DOCS = {
    b"iron-1": _doc(IRONMONGER, 368.50),  # gold 005: over £250, no VAT, no VAT number
    b"iron-2": _doc("HARGREAVES & SONS IRONMONGERY LTD", 412.00, day="2026-10-24"),  # same supplier, other spelling
    b"iron-3": _doc(IRONMONGER, 120.00, vat=20.00, day="2026-10-25"),  # charges VAT, still no number
    b"screwfix-1": _doc("Screwfix", 38.47, vat=6.41, vrn="GB 232 4567 89"),
    b"screwfix-2": _doc("SCREWFIX LTD", 57.60, vat=9.60, day="2026-10-23"),  # VAT number missed this time
    b"screwfix-3": _doc("Screwfix", 300.00, day="2026-10-26"),  # zero-rated, over £250
    b"other": _doc("Harrow & Finch Trading Ltd", 291.00),  # gold 016
}


@pytest.fixture(autouse=True)
def stub_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_extract(data: bytes, mime: str, cfg: AiConfig) -> tuple[ExtractedDoc, dict[str, str]]:
        return DOCS[data].model_copy(deep=True), {"backend": "stub", "model": cfg.model}

    async def no_verifier(*_a: object, **_kw: object) -> None:
        return None

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    monkeypatch.setattr(pipeline, "verify", no_verifier)


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


async def _scan(fake: FakeStorageProvider, books: Books, *names: bytes):  # noqa: ANN202
    for n in names:
        fake.files[f"00 Inbox/{n.decode()}.jpg"] = n
    return await scan_inbox(books, CFG)


def _stored(fake: FakeStorageProvider) -> dict[str, dict]:
    return {c["name"]: c for c in json.loads(fake.files[CONTACTS])}


def _audit(fake: FakeStorageProvider) -> list[dict]:
    return [json.loads(x) for p, d in sorted(fake.files.items()) if p.startswith(f"{AUDIT}/") for x in d.decode().splitlines()]


def _question(p) -> str | None:  # noqa: ANN001
    return next((c.message for c in p.checks if c.code == SUPPLIER_VAT_UNKNOWN and not c.ok), None)


async def test_unknown_supplier_is_asked_once_then_remembered(fake: FakeStorageProvider, books: Books) -> None:
    (p,) = await _scan(fake, books, b"iron-1")
    assert p.status == "needs_a_look"
    assert _question(p) == f"Is {IRONMONGER} VAT-registered? Over £250 they should give a VAT invoice"

    await approve(books, p.id, USER, {NOT_VAT_REGISTERED: True})
    c = _stored(fake)[IRONMONGER]
    assert (c["vat_status"], c["vrn"], c["kind"]) == ("not_registered", None, "supplier")
    assert {"action": "contact_vat_status", "actor": f"user:{USER}"}.items() <= _audit(fake)[-2].items()

    (again,) = await _scan(fake, books, b"iron-2")  # found by normalised name: decided without asking
    assert again.status == "proposed" and _question(again) is None
    assert any("isn't VAT-registered" in c.message for c in again.checks if c.code == "VAT_NUMBER_REQUIRED")

    (vat,) = await _scan(fake, books, b"iron-3")  # charging VAT with no number is still a fail
    assert vat.status == "needs_a_look" and any(c.code == "VAT_NUMBER_REQUIRED" and not c.ok for c in vat.checks)

    book, _, _ = await cb.contact_book(books)  # the ledger refresh keeps what was learnt
    assert [c.vat_status for c in book if c.name == IRONMONGER] == ["not_registered"]


async def test_approving_without_the_tick_teaches_nothing(fake: FakeStorageProvider, books: Books) -> None:
    (p,) = await _scan(fake, books, b"iron-1")
    await approve(books, p.id, USER)
    assert CONTACTS not in fake.files
    (again,) = await _scan(fake, books, b"iron-2")
    assert again.status == "needs_a_look" and _question(again)


async def test_a_vat_number_teaches_registered(fake: FakeStorageProvider, books: Books) -> None:
    (p,) = await _scan(fake, books, b"screwfix-1")
    await approve(books, p.id, USER)
    c = _stored(fake)["Screwfix"]
    assert (c["vat_status"], c["vrn"]) == ("registered", "GB232456789")

    (missed,) = await _scan(fake, books, b"screwfix-2")
    msg = next(c.message for c in missed.checks if c.code == "VAT_NUMBER_REQUIRED")
    assert missed.status == "needs_a_look"
    assert msg == "VAT charged but no VAT number shown; their VAT number is usually GB232456789; the VAT can't be reclaimed without it"

    (zero,) = await _scan(fake, books, b"screwfix-3")  # a known registered supplier with nothing to reclaim: not asked
    assert zero.status == "proposed" and _question(zero) is None

    before = fake.files[CONTACTS]
    await approve(books, zero.id, USER)  # already known as registered: nothing new learnt, nothing written
    assert fake.files[CONTACTS] == before


async def test_tick_is_refused_where_it_makes_no_sense(fake: FakeStorageProvider, books: Books) -> None:
    vat, vrn = await _scan(fake, books, b"iron-3", b"screwfix-1")
    with pytest.raises(ApprovalError, match="charges VAT"):
        await approve(books, vat.id, USER, {NOT_VAT_REGISTERED: True})
    with pytest.raises(ApprovalError, match="shows a VAT number"):
        await approve(books, vrn.id, USER, {NOT_VAT_REGISTERED: True})
    with pytest.raises(ApprovalError, match="true or false"):
        await approve(books, vat.id, USER, {NOT_VAT_REGISTERED: "yes"})
    # Correcting the VAT to nil in the same approval makes the tick valid
    await approve(books, vat.id, USER, {"vat_total": 0.0, "net_total": 120.0, NOT_VAT_REGISTERED: True})
    assert _stored(fake)[IRONMONGER]["vat_status"] == "not_registered"


async def test_business_not_vat_registered_never_asks(fake: FakeStorageProvider, books: Books) -> None:
    await invoicing.save_profile(books, invoicing.InvoiceProfile(name="Sam's Joinery", vat_registered=False), USER)
    first, vat = await _scan(fake, books, b"iron-1", b"iron-3")
    assert (first.status, vat.status) == ("proposed", "proposed")
    assert all("isn't VAT-registered" in c.message for c in (first.checks + vat.checks) if c.code == "VAT_NUMBER_REQUIRED")


def test_a_vat_number_in_the_profile_means_registered() -> None:
    assert invoicing.InvoiceProfile().is_vat_registered  # the default: today's behaviour
    assert not invoicing.InvoiceProfile(vat_registered=False).is_vat_registered
    assert invoicing.InvoiceProfile(vat_registered=False, vrn="GB 123 4567 89").is_vat_registered


async def test_broken_contacts_file_neither_blocks_a_scan_nor_an_approval(fake: FakeStorageProvider, books: Books) -> None:
    fake.files[CONTACTS] = b"{not json"
    (p,) = await _scan(fake, books, b"iron-1")
    assert p.status == "needs_a_look" and _question(p)
    posted = await approve(books, p.id, USER, {NOT_VAT_REGISTERED: True})
    assert posted.status == "posted" and fake.files[CONTACTS] == b"{not json"


async def test_seen_vat_number_finds_the_contact_whatever_the_name(fake: FakeStorageProvider, books: Books) -> None:
    await cb.set_vat_status(books, "Screwfix", "registered", "agent:test", "GB232456789")
    doc = _doc("SFX Trade Counter", 38.47, vat=6.41, vrn="GB232456789")
    k = cb.supplier_knowledge(await cb.stored_contacts(books), doc)
    assert (k.vat_status, k.vrn) == ("registered", "GB232456789")
    sale = doc.model_copy(update={"doc_type": "sales_invoice"})  # the user's own invoice: no supplier to know
    assert cb.supplier_knowledge(await cb.stored_contacts(books), sale).vat_status == "unknown"


def test_a_contact_with_a_vat_number_counts_as_registered() -> None:
    old = cb.Contact(id="0" * 16, kind="supplier", name="Howdens", normalised_key="howdens", vrn="GB123456789")
    assert cb.supplier_knowledge([old], _doc("Howdens", 300.0)).vat_status == "registered"
    told = old.model_copy(update={"vat_status": "not_registered"})  # what the user said wins
    assert cb.supplier_knowledge([told], _doc("Howdens", 300.0)).vat_status == "not_registered"


# --------------------------------------------------------------------------- #
# Contacts page: show and edit vat_status
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(books: Books):  # noqa: ANN201
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_contacts_route_shows_and_edits_vat_status(client: TestClient, fake: FakeStorageProvider, books: Books) -> None:
    (p,) = await _scan(fake, books, b"other")
    await approve(books, p.id, USER, {NOT_VAT_REGISTERED: True})
    rows = client.get("/contacts", headers=H).json()["contacts"]
    (row,) = [r for r in rows if r["name"] == "Harrow & Finch Trading Ltd"]
    assert row["vat_status"] == "not_registered"

    r = client.put(f"/contacts/{row['id']}", json={"vat_status": "unknown"}, headers=H)
    assert r.status_code == 200 and r.json()["vat_status"] == "unknown" and "vat_status" in r.json()["edited"]
    assert client.put(f"/contacts/{row['id']}", json={"vat_status": "maybe"}, headers=H).status_code == 422
    assert client.put(f"/contacts/{row['id']}", json={"vat_status": None}, headers=H).json()["vat_status"] == "unknown"

    fake.files.pop("00 Inbox/other.jpg", None)
    (asked,) = await _scan(fake, books, b"other")  # unknown again, so the scan asks again (as a duplicate too)
    assert _question(asked)

    r = client.put(f"/contacts/{row['id']}", json={"vat_status": "registered"}, headers=H)
    assert r.json()["vat_status"] == "registered"
