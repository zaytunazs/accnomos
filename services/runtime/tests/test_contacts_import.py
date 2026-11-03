"""Importing contacts, all or a chosen few, from Outlook, the people the user emails, and the phone
(app/contacts_import.py, routes under /contacts/import)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeContactsProvider, FakeMailProvider, FakeStorageProvider
from accnomos_connectors.base import AddressBookContact, MailMessage
from app import contacts as cb
from app import contacts_import as ci
from app.books import AUDIT, Books

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def contact(name: str, kind: str = "customer", email: str | None = None, phone: str | None = None) -> cb.Contact:
    key = ci.supplier_key(name)
    return cb.Contact(id=cb.contact_id(key, None), kind=kind, name=name, normalised_key=key, email=email, phone=phone)  # type: ignore[arg-type]


BOOK = [
    contact("Sterling & Co. Architects", email="accounts@sterling-architects.example"),
    contact("Hargreaves Hardware Ltd", "supplier", phone="020 7946 0001"),
]


def test_marks_existing_by_name_email_and_phone() -> None:
    rows = ci.from_rows(
        [
            ci.Row(name="Sterling & Co Architects Ltd"),  # same name, once Ltd and punctuation go
            ci.Row(name="Tom Bradley", email="ACCOUNTS@sterling-architects.example"),  # same email
            ci.Row(name="Hargreaves shop", phone="+44 20 7946 0001"),  # same phone, +44 for 0
            ci.Row(name="Lucy Bennett", email="lucy@bennett.example"),
            ci.Row(name="  "),  # no usable name: dropped
        ]
    )
    p = ci._mark(rows, ci._Index(BOOK))
    by = {c.name: c for c in p.candidates}
    assert p.new == 1 and p.existing == 3 and len(p.candidates) == 4
    assert by["Sterling & Co Architects Ltd"].match == "same name"
    assert by["Tom Bradley"].match == "same email" and by["Tom Bradley"].existing_name == "Sterling & Co. Architects"
    assert by["Hargreaves shop"].match == "same phone" and by["Hargreaves shop"].kind == "supplier"
    assert by["Lucy Bennett"].existing_id is None
    assert p.candidates[0].name == "Lucy Bennett"  # new ones first


def test_address_book_uses_company_then_person() -> None:
    cands = ci.from_address_book(
        [
            AddressBookContact(
                id="1", display_name="Emily Clarke", company_name="Clarke Interiors Ltd", emails=["e@c.example"]
            ),
            AddressBookContact(id="2", display_name="George Palmer", business_phones=["07700 900303"]),
            AddressBookContact(id="3"),
        ]
    )
    assert [(c.name, c.person) for c in cands] == [("Clarke Interiors Ltd", "Emily Clarke"), ("George Palmer", None)]


def test_email_senders_skip_robots_and_own_address_and_count_messages() -> None:
    def m(i: int, addr: str, name: str) -> MailMessage:
        return MailMessage(id=str(i), received_at=NOW, from_address=addr, from_name=name)

    msgs = [
        m(1, "accounts@sterling-architects.example", "Sterling & Co. Architects"),
        m(2, "Accounts@Sterling-Architects.example", "Sterling & Co. Architects"),
        m(3, "no-reply@bank.example", "Bank"),
        m(4, "newsletter@shop.example", "Shop"),
        m(5, USER, "Sam"),
        m(6, "jo@plumbing.example", ""),
    ]
    cands = ci.from_messages(msgs, [USER])
    assert [(c.name, c.messages) for c in cands] == [("Sterling & Co. Architects", 2), ("jo", 1)]


def test_merge_adds_new_with_kind_skips_existing_fills_blanks_and_is_idempotent() -> None:
    rows = [
        ci.Row(name="Lucy Bennett", email="lucy@bennett.example", kind="both"),
        ci.Row(name="Hargreaves Hardware", email="shop@hargreaves.example"),  # existing: gains an email
        ci.Row(name="Northfield Timber Supplies", kind="supplier"),
        ci.Row(name="Northfield Timber Supplies", kind="supplier"),  # twice in one go: once
        ci.Row(name="Bad email", email="not-an-email"),
    ]
    book, s = ci.merge_rows(BOOK, rows, "outlook")
    assert (s.added, s.already, s.filled, s.invalid) == (2, 2, 1, 1)
    assert s.message == "Imported 2, skipped 2 already in your books, 1 without a usable name or email."
    by = {c.name: c for c in book}
    assert by["Lucy Bennett"].kind == "both" and by["Lucy Bennett"].source == "outlook"
    assert by["Northfield Timber Supplies"].kind == "supplier"
    assert by["Hargreaves Hardware Ltd"].email == "shop@hargreaves.example"  # filled, kind and name unchanged
    again, s2 = ci.merge_rows(book, rows, "outlook")
    assert s2.added == 0 and len(again) == len(book)


# Routes ------------------------------------------------------------------------------------------------------- #


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.write_json(cb.CONTACTS, cb._dump(BOOK))
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books, require_user
    from app.routes_contacts import get_address_book
    from app.routes_mail import get_mail

    book = FakeContactsProvider(
        [
            AddressBookContact(id="1", display_name="Tom Bradley", company_name="Sterling & Co. Architects"),
            AddressBookContact(id="2", display_name="Lucy Bennett", company_name="Bennett Kitchens Ltd"),
            AddressBookContact(id="3", display_name="George Palmer", emails=["george@example.co.uk"]),
        ]
    )
    mail = FakeMailProvider()
    mail.add(
        MailMessage(
            id="m1",
            received_at=datetime.now(UTC) - timedelta(days=2),
            from_address="jo@plumb.example",
            from_name="Jo Plumb",
        ),
        body="hi",
    )

    async def over_books() -> Books:
        return books

    async def over_book():
        yield book

    async def over_mail():
        yield mail

    app.dependency_overrides[get_books] = over_books
    app.dependency_overrides[require_user] = lambda: USER
    app.dependency_overrides[get_address_book] = over_book
    app.dependency_overrides[get_mail] = over_mail
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_routes_preview_import_selected_audit_and_repeat(client: TestClient, books: Books) -> None:
    p = client.get("/contacts/import/outlook", headers=H).json()
    assert p["source"] == "outlook" and p["new"] == 2 and p["existing"] == 1
    assert {c["name"]: c["existing_id"] is not None for c in p["candidates"]} == {
        "Bennett Kitchens Ltd": False,
        "George Palmer": False,
        "Sterling & Co. Architects": True,
    }
    e = client.get("/contacts/import/email", headers=H).json()
    assert [(c["name"], c["email"]) for c in e["candidates"]] == [("Jo Plumb", "jo@plumb.example")]
    chk = client.post("/contacts/import/check", headers=H, json={"contacts": [{"name": "Hargreaves Hardware"}]}).json()
    assert chk["source"] == "phone" and chk["candidates"][0]["match"] == "same name"

    pick = [{"name": "Bennett Kitchens Ltd", "person": "Lucy Bennett", "kind": "supplier"}]
    r = client.post("/contacts/import", headers=H, json={"source": "outlook", "contacts": pick})
    assert r.status_code == 200 and r.json()["added"] == 1 and r.json()["message"] == "Imported 1."
    again = client.post("/contacts/import", headers=H, json={"source": "outlook", "contacts": pick}).json()
    assert again["added"] == 0 and again["already"] == 1
    assert client.post("/contacts/import", headers=H, json={"source": "outlook", "contacts": []}).status_code == 422

    saved = {c["name"]: c for c in await books.read_json(cb.CONTACTS, [])}
    assert saved["Bennett Kitchens Ltd"]["kind"] == "supplier"
    from app.dashboard import read_audit

    imported = [a for a in await read_audit(books, AUDIT) if a["action"] == "contacts_imported"]
    assert [(a["refs"]["source"], a["refs"]["added"], a["refs"]["already"]) for a in imported][-2:] in (
        [("outlook", 1, 0), ("outlook", 0, 1)],
        [("outlook", 0, 1), ("outlook", 1, 0)],
    )
