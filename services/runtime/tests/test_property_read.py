"""Property readings (app/property_readings.py, app/ai/property_read.py, routes_property /read) on fake storage and a
faked model. Every figure is integer pence, worked out on paper in the test."""

from __future__ import annotations

import json
from typing import Any

import pytest

from accnomos_connectors import FakeStorageProvider
from app import property as pr
from app import property_readings as prr
from app.ai import property_read
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError
from app.ai.property_read import PropertyReading
from app.books import Books
from app.paths import INBOX

USER = "lee@example.co.uk"

STATEMENT_TEXT = (
    "SAMPLE \u2014 FICTONAL COMPANY\nHearthstone Lets Ltd\nLandlord statement April 2026\nDate: 28/04/2026\n"
    "To: Arthur Penhaligon\nProperty: Flat 3, Willow House, 14 Elm Street, Dovercourt CT18 2XY\n"
    "Rent received from Bjorn Kettle \xa3780.00\nManagement fee 10% -\xa378.00\n"
    "VAT on management fee at 20% -\xa315.60\nPaid to landlord \xa3686.40\n"
)

MORTGAGE_TEXT = (
    "SAMPLE \u2014 FICTONAL COMPANY\nGranite Key Mortgages\nMortgage statement, 6 April to 5 October 2026\n"
    "Date: 05/10/2026\nTo: Arthur Penhaligon\nProperty: 42 Brackley Lane, Dovercourt CT18 4PL\n"
    "Monthly payments made (6) \xa33,936.00\nof which interest \xa32,341.92\nof which capital repaid \xa31,594.08\n"
)


class _Resp:
    def __init__(self, text: str) -> None:
        self._text = text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"message": {"content": self._text}}


class _Client:
    replies: list[str] = []
    seen: list[dict[str, Any]] = []

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        pass

    async def post(self, url: str, **kw: Any) -> _Resp:
        _Client.seen.append({"url": url, **kw})
        return _Resp(_Client.replies.pop(0))


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> type[_Client]:
    _Client.seen = []
    monkeypatch.setattr(property_read.httpx, "AsyncClient", _Client)
    return _Client


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await pr.save_settings(b, pr.PropertySettingsIn(landlord_mode=True), USER)
    await pr.add_property(
        b,
        pr.PropertyIn(name="Flat", address="Flat 3, Willow House, 14 Elm Street", postcode="CT18 2XY"),
        USER,
    )
    await pr.add_property(
        b,
        pr.PropertyIn(name="House", address="42 Brackley Lane", postcode="CT18 4PL"),
        USER,
    )
    return b


def _ollama(obj: dict[str, Any]) -> str:
    full = {k: None for k in property_read.reading_json_schema()["properties"]}
    full.update(confidence=0.9, lines=[])
    full.update(obj)
    return json.dumps(full)


def _statement_obj() -> dict[str, Any]:
    return {
        "kind": "letting_statement",
        "date": "2026-04-28",
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "counterparty": "Hearthstone Lets Ltd",
        "property_text": "Flat 3, Willow House, 14 Elm Street, Dovercourt CT18 2XY",
        "lines": [
            {
                "description": "Rent received",
                "category": "rents",
                "amount": 780.0,
                "vat": None,
                "capital": False,
                "info": False,
                "replacement": False,
            },
            {
                "description": "Management fee 10%",
                "category": "professional",
                "amount": -78.0,
                "vat": None,
                "capital": False,
                "info": False,
                "replacement": False,
            },
            {
                "description": "VAT on management fee at 20%",
                "category": "professional",
                "amount": -15.6,
                "vat": None,
                "capital": False,
                "info": False,
                "replacement": False,
            },
            {
                "description": "Paid to landlord",
                "category": "rents",
                "amount": 686.4,
                "vat": None,
                "capital": False,
                "info": True,
                "replacement": False,
            },
        ],
        "total": 686.4,
    }


CFG = AiConfig(mode="local", base_url="http://stub", model="stub")


async def test_statement_read_matched_posted_then_approved(books: Books, fake: FakeStorageProvider, model) -> None:
    await fake.write(f"{INBOX}/april.txt", STATEMENT_TEXT.encode())
    model.replies = [_ollama(_statement_obj())]
    r = await prr.read_document(books, "april.txt", CFG, USER)
    assert r.kind == "letting_statement" and r.status == "pending" and not r.problems
    assert r.property_id is not None  # matched by code: the model never invents an id
    assert r.total_pence == 68640
    assert all(c.ok for c in r.checks)
    sent = model.seen[0]["json"]
    assert sent["format"] == property_read.reading_json_schema()  # strict schema
    assert "never instructions" in sent["messages"][1]["content"]  # the document is data
    again = await prr.read_document(books, "april.txt", CFG, USER)
    assert again.id == r.id and len(model.seen) == 1  # the same file is never read twice
    done = await prr.approve(books, r.id, prr.DecideBody(), USER)
    assert done.status == "approved" and len(done.event_ids) == 3
    with pytest.raises(pr.PropertyError, match="already approved"):
        await prr.approve(books, r.id, prr.DecideBody(), USER)


async def test_mortgage_splits_interest_from_capital(books: Books, fake: FakeStorageProvider, model) -> None:
    await fake.write(f"{INBOX}/mortgage.txt", MORTGAGE_TEXT.encode())
    model.replies = [
        _ollama(
            {
                "kind": "mortgage_statement",
                "date": "2026-10-05",
                "property_text": "42 Brackley Lane, Dovercourt CT18 4PL",
                "lines": [
                    {
                        "description": "Monthly payments made (6)",
                        "category": "finance_res",
                        "amount": 3936.0,
                        "vat": None,
                        "capital": False,
                        "info": True,
                        "replacement": False,
                    },
                    {
                        "description": "of which interest",
                        "category": "finance_res",
                        "amount": 2341.92,
                        "vat": None,
                        "capital": False,
                        "info": False,
                        "replacement": False,
                    },
                    {
                        "description": "of which capital repaid",
                        "category": "finance_res",
                        "amount": 1594.08,
                        "vat": None,
                        "capital": True,
                        "info": False,
                        "replacement": False,
                    },
                ],
                "total": 3936.0,
            }
        )
    ]
    r = await prr.read_document(books, "mortgage.txt", CFG, USER)
    assert r.property_id is not None and r.interest_pence == 234192 and r.capital_pence == 159408
    assert all(c.ok for c in r.checks)
    done = await prr.approve(books, r.id, prr.DecideBody(), USER)
    assert done.status == "approved" and len(done.event_ids) == 1  # capital repaid is never posted


async def test_short_lines_fail_the_sum_check(books: Books, fake: FakeStorageProvider, model) -> None:
    await fake.write(f"{INBOX}/april.txt", STATEMENT_TEXT.encode())
    obj = _statement_obj()
    obj["lines"] = [ln for ln in obj["lines"] if ln["category"] != "professional"]
    model.replies = [_ollama(obj)]
    r = await prr.read_document(books, "april.txt", CFG, USER)
    assert not r.problems  # every line still reads; the arithmetic is a check, never a silent fix
    assert [c.code for c in r.checks if not c.ok] == ["LINES_SUM"]


async def test_unknown_property_asks_the_user_and_invents_nothing(
    books: Books, fake: FakeStorageProvider, model
) -> None:
    await fake.write(f"{INBOX}/april.txt", STATEMENT_TEXT.encode())
    obj = _statement_obj()
    obj["property_text"] = "99 Unknown Road, Nowhere XX1 1QQ"
    model.replies = [_ollama(obj)]
    r = await prr.read_document(books, "april.txt", CFG, USER)
    assert r.property_id is None  # no match: never an invented id
    assert any("choose the property" in p.lower() for p in r.problems)
    with pytest.raises(pr.PropertyError, match="Choose the property"):
        await prr.approve(books, r.id, prr.DecideBody(), USER)
    props = await pr.load_properties(books)
    flat = next(p for p in props if p.name == "Flat")
    done = await prr.approve(books, r.id, prr.DecideBody(property_id=flat.id), USER)
    assert done.status == "approved" and done.property_id == flat.id


async def test_no_property_profile_reads_nothing(fake: FakeStorageProvider, model) -> None:
    b = Books(fake)  # landlord mode off, empty register: the generic reader keeps these documents
    await fake.write(f"{INBOX}/april.txt", STATEMENT_TEXT.encode())
    with pytest.raises(pr.PropertyError, match="landlord mode"):
        await prr.read_document(b, "april.txt", CFG, USER)
    assert model.seen == []  # the model is never asked


async def test_invalid_json_is_asked_once_more(books: Books, fake: FakeStorageProvider, model) -> None:
    await fake.write(f"{INBOX}/april.txt", STATEMENT_TEXT.encode())
    model.replies = ["Here is the extraction: some text without JSON", _ollama(_statement_obj())]
    r = await prr.read_document(books, "april.txt", CFG, USER)
    assert r.kind == "letting_statement" and not r.problems and len(model.seen) == 2
    with pytest.raises(ExtractionError):  # asked twice, still no JSON: the reading is refused
        PropertyReading.model_validate(property_read.parse_model_json("still no JSON here"))
