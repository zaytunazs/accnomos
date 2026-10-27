"""Merging duplicate contacts by code: combining fields, re-pointing references, exact undo."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from accnomos_connectors import FakeStorageProvider
from app import contacts as cb
from app.autopilot import supplier_key
from app.bank_rules import BANK_RULES
from app.books import AUDIT, AUTOPILOT_RULES, Books
from app.invoicing import InvoiceDraft

USER = "sam@example.co.uk"


def _contact(cid: str, name: str, **kw) -> cb.Contact:
    base = {"kind": "supplier", "name": name, "normalised_key": supplier_key(name)}
    base.update(kw)
    return cb.Contact(id=cid, **base)


def test_merge_combines_everything_and_drops_nothing() -> None:
    keep = _contact(
        "a" * 16,
        "Screwfix",
        email="trade@screwfix.com",
        vat_status="unknown",
        kind="supplier",
        default_category="Materials",
        edited=["email"],
    )
    old = _contact(
        "b" * 16,
        "SCREWFIX DIRECT LTD",
        phone="0117 496 0123",
        address="1 Trade Park",
        vat_status="registered",
        kind="customer",
        terms_days=14,
        edited=["phone"],
    )
    old.normalised_key = "screwfix-direct"
    old.aliases = ["screwfix-direct-ltd"]
    book, kept, removed = cb.merge_contacts([keep, old], "a" * 16, ["b" * 16])
    assert [c.id for c in book] == ["a" * 16]
    assert removed[0].id == "b" * 16
    assert kept.email == "trade@screwfix.com" and kept.phone == "0117 496 0123"
    assert kept.address == "1 Trade Park"
    assert kept.vat_status == "registered"  # the stricter status wins
    assert kept.kind == "both"
    assert kept.terms_days == 14 and kept.default_category == "Materials"
    assert kept.edited == ["email", "phone"]
    assert kept.normalised_key == "screwfix"
    assert kept.aliases == ["screwfix-direct", "screwfix-direct-ltd"]  # future documents still match


def test_merge_combines_addresses_line_by_line() -> None:
    keep = _contact("a" * 16, "Screwfix", address="1 Trade Park")
    old = _contact("b" * 16, "Screwfix Direct", address="1 Trade Park\nBristol")
    _, kept, _ = cb.merge_contacts([keep, old], "a" * 16, ["b" * 16])
    assert kept.address == "1 Trade Park\nBristol"


def test_merge_takes_the_vrn_and_keeps_the_stricter_status() -> None:
    keep = _contact("a" * 16, "Screwfix", vat_status="not_registered")
    old = _contact("b" * 16, "Screwfix Direct", vrn="GB123456789", vat_status="unknown")
    _, kept, _ = cb.merge_contacts([keep, old], "a" * 16, ["b" * 16])
    assert kept.vrn == "GB123456789" and kept.vat_status == "not_registered"  # stricter than unknown
    fresh = _contact("c" * 16, "Screwfix Trade", vat_status="unknown")
    _, kept2, _ = cb.merge_contacts([fresh, old], "c" * 16, ["b" * 16])
    assert kept2.vrn == "GB123456789" and kept2.vat_status == "registered"  # a VAT number means registered


def test_merge_refuses_bad_requests() -> None:
    keep = _contact("a" * 16, "Screwfix")
    old = _contact("b" * 16, "Screwfix Direct", vrn="GB111111111")
    other_vrn = _contact("c" * 16, "Screwfix Trade", vrn="GB222222222")
    with pytest.raises(cb.MergeError, match="empty"):
        cb.merge_contacts([keep, old], "a" * 16, [])
    with pytest.raises(cb.MergeError, match="No such contact to keep"):
        cb.merge_contacts([keep, old], "0" * 16, ["b" * 16])
    with pytest.raises(cb.MergeError, match="cannot also be merged"):
        cb.merge_contacts([keep, old], "a" * 16, ["a" * 16])
    with pytest.raises(cb.MergeError, match="No such contact"):
        cb.merge_contacts([keep, old], "a" * 16, ["0" * 16])
    with pytest.raises(cb.MergeError, match="Different VAT numbers"):
        cb.merge_contacts([keep, old, other_vrn], "a" * 16, ["b" * 16, "c" * 16])
    with pytest.raises(cb.MergeError, match="empty"):
        cb.merge_contacts([keep, old], "a" * 16, ["b" * 16], name="  ")


def test_renaming_on_merge_keeps_the_old_name_as_an_alias() -> None:
    keep = _contact("a" * 16, "Screwfix")
    old = _contact("b" * 16, "Screwfix Direct")
    _, kept, _ = cb.merge_contacts([keep, old], "a" * 16, ["b" * 16], name="Screwfix Trade")
    assert kept.name == "Screwfix Trade" and kept.normalised_key == "screwfix-trade"
    assert "screwfix" in kept.aliases and "screwfix-direct" in kept.aliases


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


async def _seed(books: Books) -> tuple[cb.Contact, cb.Contact, str]:
    keep = _contact("a" * 16, "Screwfix", email="trade@screwfix.com")
    old = _contact("b" * 16, "SCREWFIX DIRECT LTD", phone="0117 496 0123", kind="customer")
    old.normalised_key = "screwfix-direct"
    await cb.save_contacts(books, [keep, old])
    draft = InvoiceDraft.model_validate(
        {
            "customer": {"contact_id": "b" * 16, "name": "SCREWFIX DIRECT LTD"},
            "issue_date": date(2026, 10, 1).isoformat(),
            "lines": [{"description": "Bits", "quantity": "1", "unit": "each", "unit_price_pence": 1000}],
        }
    )
    from app import invoicing as inv

    invoice = await inv.create_invoice(books, draft, USER)
    await books.write_json(
        BANK_RULES,
        [
            {
                "id": "r1",
                "match": {"op": "contains", "value": "SCREWFIX"},
                "action": {"account": "5000 Materials", "contact": "SCREWFIX DIRECT LTD"},
            }
        ],
    )
    await books.write_json(
        AUTOPILOT_RULES,
        [
            {
                "supplier_key": "screwfix-direct",
                "supplier_name": "SCREWFIX DIRECT LTD",
                "category": "Materials",
                "side": "purchase",
                "typical_gross_pence": 1200,
            }
        ],
    )
    return keep, old, invoice.number


async def test_merge_repoints_everything_and_undo_restores_exactly(books: Books, fake: FakeStorageProvider) -> None:
    from app import invoicing as inv

    keep, old, number = await _seed(books)
    contacts_before = json.loads(fake.files[cb.CONTACTS])
    invoice_before = json.loads(fake.files[f"03 Sales/invoices/{number}.json"])
    bank_before = json.loads(fake.files[BANK_RULES])
    auto_before = json.loads(fake.files[AUTOPILOT_RULES])

    kept, merge_id = await cb.merge(books, keep.id, [old.id], "Screwfix Ltd", USER)
    assert kept.name == "Screwfix Ltd" and kept.phone == "0117 496 0123"
    stored = {c["id"]: c for c in json.loads(fake.files[cb.CONTACTS])}
    assert set(stored) == {keep.id}  # the merged contact is gone
    assert "screwfix-direct" in stored[keep.id]["aliases"]
    assert (await inv.get_invoice(books, number)).customer.contact_id == keep.id
    assert json.loads(fake.files[BANK_RULES])[0]["action"]["contact"] == "Screwfix Ltd"
    auto = json.loads(fake.files[AUTOPILOT_RULES])[0]
    assert auto["supplier_key"] == "screwfix" and auto["supplier_name"] == "Screwfix Ltd"
    assert fake.files[cb._merge_path(merge_id)]  # the undo record
    actions = [
        json.loads(line)["action"]
        for path in sorted(fake.files)
        if path.startswith(f"{AUDIT}/")
        for line in fake.files[path].decode().splitlines()
    ]
    assert "contacts_merged" in actions

    restored = await cb.undo_merge(books, merge_id, USER)
    assert {c.id for c in restored} == {keep.id, old.id}
    assert json.loads(fake.files[cb.CONTACTS]) == contacts_before  # byte-exact entries
    assert json.loads(fake.files[f"03 Sales/invoices/{number}.json"]) == invoice_before
    assert json.loads(fake.files[BANK_RULES]) == bank_before
    assert json.loads(fake.files[AUTOPILOT_RULES]) == auto_before
    undone_actions = [
        json.loads(x)["action"]
        for p in fake.files
        if p.startswith(f"{AUDIT}/")
        for x in fake.files[p].decode().splitlines()
    ]
    assert "contacts_merge_undone" in undone_actions
    with pytest.raises(FileNotFoundError):
        await cb.undo_merge(books, merge_id, USER)  # already undone
    with pytest.raises(FileNotFoundError):
        await cb.undo_merge(books, "0" * 16, USER)
    with pytest.raises(FileNotFoundError):
        await cb.undo_merge(books, "not-an-id", USER)


async def test_merge_without_references_still_audits(books: Books, fake: FakeStorageProvider) -> None:
    keep = _contact("a" * 16, "Screwfix", email="trade@screwfix.com")
    old = _contact("b" * 16, "Screwfix Direct", email="trade@screwfix.com")
    await cb.save_contacts(books, [keep, old])
    kept, merge_id = await cb.merge(books, keep.id, [old.id], None, USER)
    assert kept.email == "trade@screwfix.com"
    record = cb.MergeRecord.model_validate_json(fake.files[cb._merge_path(merge_id)])
    assert record.references == [] and record.contacts_before


async def test_merged_documents_still_belong_to_the_keeper() -> None:
    """Payments and credits belong to ledger documents, not contact ids: the kept aliases still find them."""
    from accnomos_ledger import LedgerEvent, Line, VatCode

    ids = iter(["1" * 32, "2" * 32])

    def event(who: str) -> LedgerEvent:
        return LedgerEvent(
            id=next(ids),
            kind="purchase",
            date=date(2026, 9, 1),
            lines=[
                Line(account="5000 Materials", debit=1000, vat_code=VatCode.STANDARD),
                Line(account="2100 Creditors", credit=1000),
            ],
            counterparty=who,
            approved_by=USER,
            approved_at=datetime(2026, 10, 25, tzinfo=UTC),
        )

    keep = _contact("a" * 16, "Screwfix")
    old = _contact("b" * 16, "SCREWFIX DIRECT LTD")
    old.normalised_key = "screwfix-direct"
    book, kept, _ = cb.merge_contacts([keep, old], "a" * 16, ["b" * 16])
    ledger = cb.Ledger(events=[event("Screwfix"), event("SCREWFIX DIRECT LTD")])
    by_contact = cb.assign(book, cb.documents(ledger))
    assert len(by_contact[kept.id]) == 2
