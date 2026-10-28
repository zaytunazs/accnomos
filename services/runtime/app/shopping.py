"""The shopping list, kept in the user's books as `_System/shopping_list.json`.

Adding "packing tape": code looks the words up in the user's price history (app/prices.py) and offers what they
bought before, each with its last price and supplier ("Tesa 50mm x 66m brown, £2.10 each from A; or 48mm clear
from B, £1.65"). Nothing matches: code asks for the specs as fields (width, length, colour, quantity), not as free
chat. The item is stored with the chosen spec, the quantity, and the cheapest supplier for it in the history, which
code works out again when the item is saved (never taken from the client). With a live price search switched on
(app/price_search.py) the lookup also shows live offers after the history, each labelled with source and time.

Ticking an item off keeps it on the list as done. Turning the list into a purchase order or a draft email to the
supplier is a future step and is switched off (FUTURE_STEPS). Every change is an audit line.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app import price_search
from app.books import SYSTEM, Books, now
from app.prices import (
    COLOURS,
    MEASURE_WORDS,
    ItemSpec,
    LiveOffer,
    Observation,
    PriceGroup,
    build_report,
    history,
    live_offer,
    load_matches,
    normalise,
    pounds,
    uk_day,
)
from app.validation import StrictBody

SHOPPING_LIST = f"{SYSTEM}/shopping_list.json"
ITEMS_MAX = 300
OPTIONS_MAX = 5
FUTURE_STEPS = {
    "purchase_order": "Turn into a purchase order: coming later, switched off in this version.",
    "email_supplier": "Draft an email to the supplier: coming later, switched off in this version.",
}


class ShoppingError(ValueError):
    """The list cannot take this change (it is full, or the file is not a shopping list)."""


class ShoppingSpec(StrictBody):
    width_mm: Decimal | None = Field(default=None, gt=0, le=100_000)
    length_m: Decimal | None = Field(default=None, gt=0, le=100_000)
    weight_kg: Decimal | None = Field(default=None, gt=0, le=100_000)
    volume_l: Decimal | None = Field(default=None, gt=0, le=100_000)
    colour: str | None = Field(default=None, max_length=30)
    pack: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("colour")
    @classmethod
    def _colour(cls, v: str | None) -> str | None:
        v = (v or "").strip().lower()
        return v or None


class ShoppingIn(StrictBody):
    text: str = Field(min_length=1, max_length=120)  # what the user typed or said: "packing tape"
    option_key: str | None = Field(default=None, max_length=300)  # an item from the lookup (ItemSpec.key)
    spec: ShoppingSpec | None = None  # when nothing in the history matched
    quantity: Decimal = Field(default=Decimal(1), gt=0, le=100_000)
    note: str = Field(default="", max_length=200)

    @field_validator("text")
    @classmethod
    def _one_line(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("text is empty")
        return v


class Suggested(BaseModel):
    """The cheapest place to buy it, from the user's own books (code's choice)."""

    supplier: str
    description: str
    unit_price: str  # pounds, one unit as bought
    per_measure: str  # pounds per metre / kg / litre / item
    measure_word: str
    date: date
    source: str
    basis: str  # plain words: why this one


class ShoppingItem(BaseModel):
    id: str
    text: str
    description: str  # the spec in words: the item chosen, or the text plus the specs given
    quantity: Decimal
    spec: dict[str, Any]
    item_key: str | None
    suggested: Suggested | None
    live_offer: LiveOffer | None = None  # the cheapest comparable live offer when the item was added (search on)
    note: str = ""
    added_at: datetime
    added_by: str
    done: bool = False
    done_at: datetime | None = None


class SpecField(BaseModel):
    name: Literal["width_mm", "length_m", "colour", "quantity"]
    label: str
    kind: Literal["number", "choice"]
    unit: str | None = None
    options: list[str] = []
    required: bool = False


SPEC_FIELDS = [
    SpecField(name="width_mm", label="Width", kind="number", unit="mm"),
    SpecField(name="length_m", label="Length", kind="number", unit="m"),
    SpecField(name="colour", label="Colour", kind="choice", options=["any", *COLOURS[:14]]),
    SpecField(name="quantity", label="Quantity", kind="number", required=True),
]


class LookupOption(BaseModel):
    key: str
    description: str
    supplier: str  # where it was bought last
    unit_price: str
    per_measure: str
    measure_word: str
    date: date
    source: str
    cheapest: Suggested | None  # the lowest price for this product (or an equivalent) in the books
    label: str  # "Tesa 50mm x 66m Brown Packing Tape, £2.10 each from Parcelworks Supplies Ltd (8 Oct 2026)"


class Lookup(BaseModel):
    text: str
    read_as: dict[str, Any]  # the sizes code read from the words
    options: list[LookupOption]
    fields: list[SpecField]  # asked for when there are no options
    question_md: str
    live_offers: list[LiveOffer] = []
    web_search: price_search.SearchStatus


class ShoppingList(BaseModel):
    items: list[ShoppingItem]
    web_search: price_search.SearchStatus
    future_steps: dict[str, str] = FUTURE_STEPS


# --------------------------------------------------------------------------- #
# Matching the words against the history
# --------------------------------------------------------------------------- #


def _close(a: Decimal | None, b: Decimal | None, tolerance: Decimal = Decimal(0)) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= max(a, b) * tolerance


def fits(query: ItemSpec, item: ItemSpec) -> bool:
    """Every word the user gave is in the item's name, and every size or colour they gave is the item's (a size they
    typed is meant exactly; WIDTH_TOLERANCE is for joining equivalent items in the price history)."""
    if not query.name_words or not set(query.name_words) <= set(item.name_words):
        return False
    if query.colour and item.colour and query.colour != item.colour:
        return False
    return (
        _close(query.width_mm, item.width_mm)
        and _close(query.length_m, item.length_m)
        and _close(query.weight_kg, item.weight_kg)
        and _close(query.volume_l, item.volume_l)
    )


def _suggested(g: PriceGroup | None) -> Suggested | None:
    if g is None:
        return None
    c = g.cheapest
    many = g.observations > 1
    return Suggested(
        supplier=c.supplier,
        description=c.description,
        unit_price=c.unit_price,
        per_measure=c.per_measure,
        measure_word=g.measure_word,
        date=c.date,
        source=c.source,
        basis=("the lowest price per " + g.measure_word + " in your books" if many else "the only time you bought it"),
    )


def _options(text: str, obs: list[Observation], groups: list[PriceGroup]) -> tuple[ItemSpec, list[LookupOption]]:
    query = normalise(text)
    by_key = {k: g for g in groups for k in g.keys}
    latest: dict[str, Observation] = {}
    for o in sorted(obs, key=lambda o: o.date):
        latest[o.spec.key] = o
    exact = [k for k in latest if k == query.key]
    keys = exact or [k for k, o in latest.items() if fits(query, o.spec)]
    keys.sort(key=lambda k: (latest[k].date, k), reverse=True)
    out = []
    for k in keys[:OPTIONS_MAX]:
        o = latest[k]
        word = MEASURE_WORDS[o.spec.measure]
        each = "each" if o.spec.pack == 1 else f"for {o.spec.pack}"
        out.append(
            LookupOption(
                key=k,
                description=o.description,
                supplier=o.supplier,
                unit_price=pounds(o.unit_price_pence),
                per_measure=pounds(o.per_measure, 4),
                measure_word=word,
                date=o.date,
                source=o.source,
                cheapest=_suggested(by_key.get(k)),
                label=f"{o.description}, £{pounds(o.unit_price_pence)} {each} from {o.supplier} ({uk_day(o.date)})",
            )
        )
    return query, out


def _question(text: str, options: list[LookupOption]) -> str:
    if not options:
        return (
            f"I can't find “{text}” in your receipts. Tell me the width, length, colour and how many, and I'll add it."
        )
    if len(options) == 1:
        o = options[0]
        return f"Last time: {o.label}."
    first, *rest = options
    others = "; or ".join(o.label for o in rest)
    return f"Which one? Last time: {first.label}; or {others}."


async def _live(text: str, query: ItemSpec) -> tuple[list[LiveOffer], price_search.SearchStatus]:
    provider = price_search.provider_from_env()
    if provider is None:
        return [], price_search.status(None)
    offers, why = await price_search.search(provider, text, query.as_dict())
    priced = [live_offer(o, query if query.name_words else None) for o in offers]
    priced.sort(key=lambda x: (x[1] is None, x[1] or 0))
    return [lo for lo, _pm in priced], price_search.status(provider, why)


async def lookup(books: Books, text: str, today: date) -> Lookup:
    """History first (code), then live offers when a price search is switched on."""
    text = " ".join(text.split())[:120]
    obs, since = await history(books, today)
    report = build_report(obs, await load_matches(books), since, today)
    query, options = _options(text, obs, report.groups)
    live, search = await _live(text, query)
    return Lookup(
        text=text,
        read_as=query.as_dict(),
        options=options,
        fields=[] if options else SPEC_FIELDS,
        question_md=_question(text, options),
        live_offers=live,
        web_search=search,
    )


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #


def _rows(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ShoppingError(f"{SHOPPING_LIST} is not a list; fix or remove it in your OneDrive")
    return raw


async def list_items(books: Books) -> list[ShoppingItem]:
    rows = _rows(await books.read_json(SHOPPING_LIST, []))
    items = [ShoppingItem.model_validate(r) for r in rows]
    return sorted(items, key=lambda i: (i.done, -i.added_at.timestamp()))


def describe(text: str, spec: ShoppingSpec | None) -> str:
    """'packing tape' + 48 mm, 66 m, clear -> 'packing tape 48mm x 66m clear'."""
    if spec is None:
        return text
    sizes = [f"{_n(spec.width_mm)}mm" if spec.width_mm else "", f"{_n(spec.length_m)}m" if spec.length_m else ""]
    parts = [text, " x ".join(s for s in sizes if s)]
    parts += [f"{_n(spec.weight_kg)}kg" if spec.weight_kg else "", f"{_n(spec.volume_l)}L" if spec.volume_l else ""]
    parts.append(spec.colour if spec.colour and spec.colour != "any" else "")
    parts.append(f"pack of {spec.pack}" if spec.pack and spec.pack > 1 else "")
    return " ".join(p for p in parts if p)


def _n(d: Decimal | None) -> str:
    return format(d.normalize(), "f") if d is not None else ""


async def resolve(books: Books, body: ShoppingIn, today: date) -> dict[str, Any]:
    """What would be stored for `body`, worked out by code: the item, its spec and the cheapest supplier."""
    obs, since = await history(books, today)
    report = build_report(obs, await load_matches(books), since, today)
    by_key = {k: g for g in report.groups for k in g.keys}
    latest: dict[str, Observation] = {}
    for o in sorted(obs, key=lambda o: o.date):
        latest[o.spec.key] = o
    warnings: list[str] = []
    key = body.option_key if body.option_key in latest else None
    if body.option_key and key is None:
        warnings.append("That item is no longer in your price history; it was added as you typed it.")
    if key is not None:
        description = latest[key].description
        spec = latest[key].spec
    else:
        description = describe(body.text, body.spec)
        spec = normalise(description)
        found = spec.key if spec.key in latest else None
        key = found
    group = by_key.get(key) if key else None
    live, _search = await _live(description, spec)
    best_live = next((lo for lo in live if lo.comparable), None)
    return {
        "text": body.text,
        "description": description,
        "quantity": format(body.quantity.normalize(), "f"),
        "spec": spec.as_dict(),
        "item_key": key,
        "suggested": _suggested(group).model_dump(mode="json") if group else None,  # type: ignore[union-attr]
        "live_offer": best_live.model_dump(mode="json") if best_live else None,
        "note": body.note,
        "warnings": warnings,
    }


async def add_item(books: Books, body: ShoppingIn, user: str, today: date) -> ShoppingItem:
    resolved = await resolve(books, body, today)
    item = ShoppingItem.model_validate(
        {
            **{k: v for k, v in resolved.items() if k != "warnings"},
            "id": uuid.uuid4().hex[:12],
            "added_at": now(),
            "added_by": user,
        }
    )

    def change(rows: Any) -> Any:
        rows = _rows(rows)
        if len(rows) >= ITEMS_MAX:
            raise ShoppingError(f"The shopping list is full ({ITEMS_MAX} items); tick some off and remove them first.")
        return [*rows, item.model_dump(mode="json")]

    await books._update_json(SHOPPING_LIST, [], change)
    await books.audit(f"user:{user}", "shopping_added", {"item": item.id, "description": item.description})
    return item


async def _change_one(books: Books, item_id: str, update: Any) -> ShoppingItem:
    found: list[ShoppingItem] = []

    def change(rows: Any) -> Any:
        found.clear()  # run again on a write conflict
        rows = _rows(rows)
        out = []
        for r in rows:
            if r.get("id") == item_id:
                new = update(ShoppingItem.model_validate(r))
                found.append(new or ShoppingItem.model_validate(r))
                if new is None:
                    continue  # removed
                out.append(new.model_dump(mode="json"))
            else:
                out.append(r)
        if not found:
            raise KeyError(item_id)
        return out

    await books._update_json(SHOPPING_LIST, [], change)
    return found[0]


async def set_done(books: Books, item_id: str, done: bool, user: str) -> ShoppingItem:
    item = await _change_one(
        books, item_id, lambda i: i.model_copy(update={"done": done, "done_at": now() if done else None})
    )
    await books.audit(f"user:{user}", "shopping_ticked" if done else "shopping_unticked", {"item": item_id})
    return item


async def remove_item(books: Books, item_id: str, user: str) -> ShoppingItem:
    item = await _change_one(books, item_id, lambda _i: None)
    await books.audit(f"user:{user}", "shopping_removed", {"item": item_id})
    return item
