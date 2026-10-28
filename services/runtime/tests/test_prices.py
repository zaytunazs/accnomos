"""Cheaper options: item normalisation, unit prices, savings maths, grouping (code, model + rules, the user), the
history window, and the live price search provider switch (off by default; the test fake; failures)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import price_search, prices
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.books import Books
from app.prices import ItemSpec, MatchIn, normalise, per_measure_pence, rules_allow, saving_pence
from app.sample_purchases import TAPE_BROWN, TAPE_BROWN_6, TAPE_CLEAR, seed_purchases

TODAY = date(2026, 10, 27)
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
BROWN = "packing tape tesa|w=50|l=66|c=brown"
CLEAR = "packing tape|w=48|l=66|c=clear"


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await seed_purchases(b)
    return b


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "key", "measure", "per_unit", "pack"),
    [
        (TAPE_BROWN, BROWN, "m", "66", 1),
        (TAPE_BROWN_6, BROWN, "m", "396", 6),  # the same product as a 6-pack: same key, six rolls per unit
        ("tesa packing tape, brown, 50 mm × 66 m", BROWN, "m", "66", 1),
        (TAPE_CLEAR, CLEAR, "m", "66", 1),
        ("Packing tape transparent 48mm x 66m", CLEAR, "m", "66", 1),  # transparent = clear
        ("Mineral Water 6x1.5L", "mineral water|vol=1.5", "l", "9.0", 6),
        ("Wood Glue 500ml", "glue wood|vol=0.5", "l", "0.5", 1),
        ("Bananas 1kg", "banana|kg=1", "kg", "1", 1),
        ("Sugar 500g", "sugar|kg=0.5", "kg", "0.5", 1),
        ("Gel Pens Black (10pk)", "gel pen|c=black", "item", "10", 10),
        ("Stainless Steel Hinges (Pair)", "hinge stainless steel", "item", "2", 2),
        ("Double wall cardboard boxes (pack of 25)", "box cardboard double wall", "item", "25", 25),
        ("Bubble wrap 1,000mm x 100m", "bubble wrap|w=1000|l=100", "m", "100", 1),
        ("Accounting software", "accounting software", "item", "1", 1),
    ],
)
def test_normalise(text: str, key: str, measure: str, per_unit: str, pack: int):
    spec = normalise(text)
    assert spec.key == key
    assert spec.measure == measure and spec.per_unit == Decimal(per_unit) and spec.pack == pack


def test_cm_is_read_as_mm_and_order_and_case_do_not_matter():
    assert normalise("TAPE 5cm X 66M brown tesa packing").key == BROWN


def test_unit_price_per_measure_and_saving_maths():
    roll = normalise(TAPE_BROWN)
    six = normalise(TAPE_BROWN_6)
    assert per_measure_pence(210, roll) == Decimal("3.1818")  # £2.10 / 66 m
    assert per_measure_pence(1140, six) == Decimal("2.8788")  # £11.40 / 396 m
    assert per_measure_pence(165, normalise(TAPE_CLEAR)) == Decimal("2.5000")
    # 396 m a month at 3.1061p instead of 2.8788p: 0.2273p x 396 = 90.0108p -> 90p
    assert saving_pence(Decimal("3.1061"), Decimal("2.8788"), Decimal(396)) == 90
    assert saving_pence(Decimal("2.5"), Decimal("2.8788"), Decimal(396)) == 0  # never negative
    assert saving_pence(Decimal("1.00005"), Decimal(1), Decimal(10_000)) == 1  # half up: 0.5p -> 1p


def test_rules_for_equivalent_items():
    brown, clear = normalise(TAPE_BROWN), normalise(TAPE_CLEAR)
    ok, note = rules_allow(brown, clear)
    assert ok and "different colour" in note  # 48 mm and 50 mm are within 10 %
    assert not rules_allow(brown, normalise("Packing tape 25mm x 66m"))[0]  # half the width
    assert not rules_allow(brown, normalise("Packing tape (6 pack)"))[0]  # per item vs per metre
    assert not rules_allow(brown, normalise("Duct tape silver 50mm x 50m"))[0]  # too few words in common
    assert not rules_allow(normalise("Mitre saw 254mm"), normalise("Wood glue 500ml"))[0]


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


async def test_price_report_from_the_books(books: Books):
    r = await prices.price_report(books, TODAY)
    assert r.since == date(2025, 11, 1) and r.until == TODAY
    tape = next(g for g in r.groups if g.keys == [BROWN])
    assert tape.observations == 4 and tape.suppliers == ["Parcelworks Supplies Ltd"]
    assert tape.cheapest.description == TAPE_BROWN_6 and tape.cheapest.per_measure == "0.0288"
    assert tape.latest.unit_price == "2.10" and tape.average_paid == "0.0311"
    # 1,584 m over Jul-Oct (4 months) = 396 m a month; (3.1061 - 2.8788) x 396 = 90p a month, £10.80 a year
    assert tape.saving is not None
    assert (tape.saving.per_month, tape.saving.per_year, tape.saving.monthly_items) == ("0.90", "10.80", "6")
    assert r.total_saving_per_year == "10.80"
    # Brown 50 mm and clear 48 mm are different names: a possible match until someone says so
    assert [(m.a, m.b, m.rules_ok) for m in r.possible_matches] == [(BROWN, CLEAR, True)]
    assert r.web_search.enabled is False and "off" in r.web_search.note
    assert "only from receipts and bills" in r.coverage_note


async def test_user_confirms_a_match_and_the_cheaper_supplier_shows(books: Books):
    await prices.save_match(books, MatchIn(a=BROWN, b=CLEAR, same=True), USER)
    r = await prices.price_report(books, TODAY)
    tape = next(g for g in r.groups if BROWN in g.keys)
    assert tape.keys == sorted([BROWN, CLEAR]) and tape.match == "equivalent" and tape.joined_by == ["user"]
    assert tape.cheapest.supplier == "Boxmart Ltd" and tape.cheapest.per_measure == "0.0250"
    assert tape.saving is not None and Decimal(tape.saving.per_year) > Decimal("10.80")
    assert r.possible_matches == []
    # A later "no" replaces the yes
    await prices.save_match(books, MatchIn(a=CLEAR, b=BROWN, same=False), USER)
    r = await prices.price_report(books, TODAY)
    assert all(len(g.keys) == 1 for g in r.groups) and r.possible_matches == []
    stored = await prices.load_matches(books)
    assert len(stored) == 1 and stored[0].same is False and stored[0].by == f"user:{USER}"


async def test_model_suggestions_count_only_where_code_rules_agree(books: Books, monkeypatch: pytest.MonkeyPatch):
    seen: list = []

    async def fake(messages, cfg, schema, name):  # noqa: ANN001, ANN202
        seen.append(messages[-1]["content"])
        return '{"verdicts":[{"pair":1,"same":true}]}'

    monkeypatch.setattr(ask_ai, "call_json_model", fake)
    r = await prices.suggest(books, TODAY, CFG)
    assert r.ai_used and "code kept only those its rules allow" in (r.ai_note or "")
    tape = next(g for g in r.groups if BROWN in g.keys)
    assert tape.joined_by == ["ai+rules"] and tape.cheapest.supplier == "Boxmart Ltd"
    assert "£" not in seen[0] and "2.10" not in seen[0]  # names only: no prices reach the model
    assert await prices.load_matches(books) == []  # nothing stored without the user


async def test_model_says_same_but_rules_refuse():
    obs = prices.observations(
        [
            prices.Purchase(
                event_id="e1",
                date=date(2026, 10, 1),
                supplier="A",
                category="Materials",
                net_pence=100,
                vat_pence=0,
                source="x",
                lines=(prices_line("Packing tape 50mm x 66m", 210),),
            ),
            prices.Purchase(
                event_id="e2",
                date=date(2026, 10, 2),
                supplier="B",
                category="Materials",
                net_pence=100,
                vat_pence=0,
                source="y",
                lines=(prices_line("Packing tape 25mm x 66m", 120),),
            ),
        ]
    )
    a, b = sorted({o.spec.key for o in obs})
    r = prices.build_report(obs, [], date(2026, 1, 1), TODAY, {(a, b): True})
    assert len(r.groups) == 2  # 25 mm is not 50 mm, whatever the model said
    assert r.possible_matches[0].ai_says_same is True and not r.possible_matches[0].rules_ok


def prices_line(description: str, unit_pence: int):  # noqa: ANN201
    from app.purchases import ItemLine

    return ItemLine(description=description, qty=1, unit_price_pence=unit_pence, net_pence=unit_pence)


async def test_model_trouble_leaves_possible_matches(books: Books, monkeypatch: pytest.MonkeyPatch):
    async def down(messages, cfg, schema, name):  # noqa: ANN001, ANN202
        import httpx

        raise httpx.ConnectError("no")

    monkeypatch.setattr(ask_ai, "call_json_model", down)
    r = await prices.suggest(books, TODAY, CFG)
    assert len(r.possible_matches) == 1 and "could not be reached" in (r.ai_note or "")


async def test_undone_purchase_lines_are_not_prices(books: Books):
    from accnomos_ledger import LedgerEvent, Line

    ev = next(e for e in await books.list_events() if e.date == date(2026, 9, 8))
    await books.post_event(
        LedgerEvent(
            kind="reversal",
            date=ev.date,
            lines=[Line(account=ln.account, debit=ln.credit, credit=ln.debit, vat_code=ln.vat_code) for ln in ev.lines],
            approved_by=USER,
            approved_at=datetime(2026, 10, 20, tzinfo=UTC),
            reverses=ev.id,
            net=ev.net,
            vat=ev.vat,
            counterparty=ev.counterparty,
        )
    )
    tape = next(g for g in (await prices.price_report(books, TODAY)).groups if g.keys == [BROWN])
    assert tape.observations == 3 and tape.saving is None  # the cheap 6-pack was undone


# --------------------------------------------------------------------------- #
# Live price search provider
# --------------------------------------------------------------------------- #


def test_provider_is_off_by_default_and_fake_is_test_mode_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(price_search.ENV, raising=False)
    assert price_search.provider_from_env() is None
    for off in ("", "none", "off", "NONE"):
        monkeypatch.setenv(price_search.ENV, off)
        assert price_search.provider_from_env() is None
    monkeypatch.setenv(price_search.ENV, "some-paid-api")
    assert price_search.provider_from_env() is None  # unknown: off
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    monkeypatch.setenv(price_search.ENV, "fake")
    assert price_search.provider_from_env() is None  # the fake never runs on real books
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    assert isinstance(price_search.provider_from_env(), price_search.FakePriceSearch)
    assert price_search.status(None).note.startswith("Live price search is off")


async def test_live_offers_are_priced_by_code_and_labelled(books: Books):
    r = await prices.price_report(books, TODAY, price_search.FakePriceSearch())
    assert r.web_search.enabled and r.web_search.provider == "Test fake"
    tape = next(g for g in r.groups if g.keys == [BROWN])
    assert [o.supplier for o in tape.live_offers] == ["Example Packaging (test fake)", "Example Wholesale (test fake)"]
    pack36 = tape.live_offers[0]
    # £41.40 for 36 x 66 m = 2,376 m -> 1.7424p per metre
    assert pack36.pack == 36 and pack36.per_measure == "0.0174" and pack36.comparable
    assert (
        pack36.source == "Test fake"
        and pack36.retrieved_at.year == 2026
        and pack36.url.endswith(".invalid/tape-48-66-x36")
    )
    assert tape.cheapest.supplier == "Parcelworks Supplies Ltd"  # live offers never replace the history
    assert tape.live_saving is not None and "found by Test fake" in tape.live_saving.explanation
    # (3.1061 - 1.7424) x 396 = 540.0252p -> £5.40 a month
    assert tape.live_saving.per_month == "5.40"
    water = next(g for g in r.groups if g.name == "Water supply")
    assert water.live_offers == [] and water.live_saving is None


async def test_live_offer_not_comparable_is_shown_but_not_used():
    lo, pm = prices.live_offer(
        price_search.Offer(
            supplier="X",
            title="Packing tape 25mm x 66m",
            unit_price_pence=50,
            url="https://x.invalid",
            retrieved_at=datetime(2026, 10, 27, tzinfo=UTC),
            source="Test fake",
        ),
        normalise(TAPE_BROWN),
    )
    assert pm is None and not lo.comparable and lo.per_measure is None and lo.note.startswith("Not compared")


async def test_a_failing_or_slow_provider_costs_only_its_offers(books: Books, monkeypatch: pytest.MonkeyPatch):
    class Broken:
        name = "Broken"

        async def search(self, query: str, specs: dict[str, object]) -> list[price_search.Offer]:
            raise RuntimeError("boom")

    class Slow:
        name = "Slow"

        async def search(self, query: str, specs: dict[str, object]) -> list[price_search.Offer]:
            await asyncio.sleep(5)
            return []

    r = await prices.price_report(books, TODAY, Broken())
    assert r.groups and all(g.live_offers == [] for g in r.groups) and "could not be searched" in r.web_search.note
    monkeypatch.setattr(price_search, "TIMEOUT_S", 0.01)
    r = await prices.price_report(books, TODAY, Slow())
    assert "did not answer" in r.web_search.note


def test_item_spec_dict_round_trip():
    s = ItemSpec(name_words=("tape",), width_mm=Decimal(48), length_m=Decimal(66), colour="clear", pack=6)
    assert s.as_dict() == {
        "width_mm": "48",
        "length_m": "66",
        "weight_kg": None,
        "volume_l": None,
        "colour": "clear",
        "pack": 6,
        "size_in": None,
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def test_price_routes(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    monkeypatch.delenv(price_search.ENV, raising=False)
    app.dependency_overrides[get_books] = override
    try:
        client = TestClient(app)
        got = client.get("/books/prices", headers=H)
        bad = client.post("/books/prices/matches", json={"a": BROWN, "b": BROWN, "same": True}, headers=H)
        ok = client.post("/books/prices/matches", json={"a": BROWN, "b": CLEAR, "same": True}, headers=H)
        after = client.get("/books/prices", headers=H)
    finally:
        app.dependency_overrides.clear()
    assert got.status_code == 200, got.text
    assert got.json()["web_search"] == {"enabled": False, "provider": None, "note": price_search.OFF_NOTE}
    assert bad.status_code == 422 and ok.status_code == 200
    assert any(len(g["keys"]) == 2 for g in after.json()["groups"])
