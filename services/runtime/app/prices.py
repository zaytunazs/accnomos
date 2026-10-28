"""Item price history from the user's own receipts and bills, and where they paid less for the same thing.

Who decides what:
  code       normalises every line item (name words, width, length, weight, volume, colour, pack size), works out a
             unit price per metre, kilogram, litre or item, groups lines with the same name and size (the same
             product), and does all the money: cheapest price, the usual monthly volume and the potential saving.
  the model  may only suggest that two *different* item names are the same product (app/ai/items.py). A suggestion
             counts only when code's rules agree too (same kind of measure, widths within WIDTH_TOLERANCE, both
             names sharing most of their words); otherwise it is shown as a possible match for the user.
  the user   confirms or rejects a possible match; the answer is kept in `_System/item_matches.json`.

History covers only suppliers already in the user's books. A live price search (app/price_search.py, chosen by
PRICE_SEARCH_PROVIDER, off by default) can add offers from elsewhere: code reads each offer's title with the same
normalise() and does the unit-price maths, and every live offer keeps its source and retrieval time, apart from the
history. With it off, the report says so and is history-only.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

from app import price_search
from app.books import SYSTEM, Books, now
from app.purchases import Purchase, load_purchases
from app.validation import StrictBody

ITEM_MATCHES = f"{SYSTEM}/item_matches.json"
HISTORY_MONTHS = 12  # how far back the price history (and the usual volume) looks
WIDTH_TOLERANCE = Decimal("0.10")  # 48 mm and 50 mm tape are equivalent; 25 mm and 50 mm are not
NAME_OVERLAP = 0.5  # share of name words two items must have in common to be a possible match
MATCHES_MAX = 500
COVERAGE_NOTE = (
    "Your price history comes only from receipts and bills already in your books, so it compares only suppliers you "
    "have bought from."
)

Measure = Literal["m", "kg", "l", "item"]
MEASURE_WORDS: dict[str, str] = {"m": "metre", "kg": "kg", "l": "litre", "item": "item"}

COLOURS = (
    "black",
    "white",
    "brown",
    "buff",
    "clear",
    "transparent",
    "red",
    "blue",
    "green",
    "yellow",
    "orange",
    "grey",
    "gray",
    "silver",
    "gold",
    "pink",
    "purple",
)
_COLOUR_ALIASES = {"transparent": "clear", "gray": "grey"}
_STOP = {"the", "of", "and", "with", "for", "a", "an", "in", "on", "x", "each", "per", "roll", "rolls", "pack"}
_STOP |= {"pk", "pcs", "pc", "pieces", "piece", "assorted", "length", "item", "items", "unit", "units", "size"}

_NUM = r"(\d+(?:\.\d+)?)"
_LENGTH = re.compile(rf"{_NUM}\s*(mm|cm|metres?|meters?|m)\b")
_WEIGHT = re.compile(rf"{_NUM}\s*(kg|g)\b")
_VOLUME = re.compile(rf"{_NUM}\s*(ml|litres?|liters?|ltr|l)\b")
_INCH = re.compile(rf"{_NUM}(?:\s*-?\s*inch(?:es)?\b|in\b|\s*\")")  # 2-inch, 2 inch, 2in, 2" (not "2 in stock")
_MULTI = re.compile(rf"\b(\d+)\s*x\s*(?={_NUM}\s*(?:mm|cm|m|kg|g|ml|l|ltr|litres?)\b)")
_PACKS = (
    re.compile(r"\b(?:pack|box|bag|case|set|tub|carton) of (\d+)\b"),
    re.compile(r"\b(\d+)\s*-?\s*(?:pk|pack|pcs|pieces|pc|count|ct)\b"),
    re.compile(r"\bx\s*(\d+)\s*$"),
)
_PAIR = re.compile(r"\bpair\b")


def _dec(text: str) -> Decimal:
    return Decimal(text)


def _plain(d: Decimal | None) -> str | None:
    """Decimal('66.000') -> '66'; None stays None."""
    if d is None:
        return None
    s = format(d.normalize(), "f")
    return s


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith(("xes", "ches", "shes", "sses")):
        return word[:-2]
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


@dataclass(frozen=True)
class ItemSpec:
    """What code reads from an item's description. Sizes are per item as sold (one roll, one tub)."""

    name_words: tuple[str, ...]  # sorted, singular, no sizes, packs or colours
    width_mm: Decimal | None = None
    length_m: Decimal | None = None
    weight_kg: Decimal | None = None
    volume_l: Decimal | None = None
    colour: str | None = None
    pack: int = 1  # items per purchased unit ("pack of 6" -> 6)
    size_in: Decimal | None = None  # a size in inches ("2-inch bolts"); part of what the item is, not its measure

    @property
    def measure(self) -> Measure:
        if self.length_m:
            return "m"
        if self.weight_kg:
            return "kg"
        if self.volume_l:
            return "l"
        return "item"

    @property
    def per_unit(self) -> Decimal:
        """How much of the measure one purchased unit holds: 6 rolls of 66 m -> 396 (metres)."""
        size = {"m": self.length_m, "kg": self.weight_kg, "l": self.volume_l, "item": Decimal(1)}[self.measure]
        return (size or Decimal(1)) * self.pack

    @property
    def key(self) -> str:
        """The same product: the same name words, size and colour. The pack size is left out (it changes the
        price per item, not what the item is)."""
        parts = [" ".join(self.name_words)]
        sizes = (("w", self.width_mm), ("l", self.length_m), ("kg", self.weight_kg), ("vol", self.volume_l))
        for label, v in (*sizes, ("in", self.size_in)):
            if v is not None:
                parts.append(f"{label}={_plain(v)}")
        if self.colour:
            parts.append(f"c={self.colour}")
        return "|".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "width_mm": _plain(self.width_mm),
            "length_m": _plain(self.length_m),
            "weight_kg": _plain(self.weight_kg),
            "volume_l": _plain(self.volume_l),
            "colour": self.colour,
            "pack": self.pack,
            "size_in": _plain(self.size_in),
        }


def normalise(description: str) -> ItemSpec:
    """Read sizes, pack and colour out of an item's description; what is left is its name."""
    text = description.lower().replace("×", "x").replace("*", "x")
    text = re.sub(r"(\d),(\d{3})(?!\d)", r"\1\2", text)  # 1,000 -> 1000
    rest = text
    pack = 1
    if m := _MULTI.search(rest):  # "6x1.5l": six of 1.5 l
        pack = int(m.group(1))
        rest = rest[: m.start()] + " " + rest[m.end() :]
    for rx in _PACKS:
        if pack == 1 and (m := rx.search(rest)):
            pack = int(m.group(1))
            rest = rest[: m.start()] + " " + rest[m.end() :]
    if pack == 1 and _PAIR.search(rest):
        pack = 2
        rest = _PAIR.sub(" ", rest)

    inches = None
    if m := _INCH.search(rest):  # a size, not what it is sold by: 2-inch bolts are still priced per bolt
        inches = _dec(m.group(1))
        rest = _INCH.sub(" ", rest)
    width = length = weight = volume = None
    for m in _LENGTH.finditer(rest):
        value, unit = _dec(m.group(1)), m.group(2)
        if unit in ("mm", "cm"):
            width = width if width is not None else value * (10 if unit == "cm" else 1)
        else:
            length = length if length is not None else value
    for m in _WEIGHT.finditer(rest):
        if weight is None:
            weight = _dec(m.group(1)) / (1000 if m.group(2) == "g" else 1)
    for m in _VOLUME.finditer(rest):
        if volume is None:
            volume = _dec(m.group(1)) / (1000 if m.group(2) == "ml" else 1)
    rest = _LENGTH.sub(" ", rest)
    rest = _WEIGHT.sub(" ", rest)
    rest = _VOLUME.sub(" ", rest)

    colour = None
    for c in COLOURS:
        if re.search(rf"\b{c}\b", rest):
            colour = colour or _COLOUR_ALIASES.get(c, c)
            rest = re.sub(rf"\b{c}\b", " ", rest)
    words = sorted(
        {
            _singular(w)
            for w in re.findall(r"[a-z][a-z'&-]*", rest)
            if len(w) >= 2 and _singular(w.strip("'-&")) not in _STOP and w.strip("'-&")
        }
    )
    return ItemSpec(
        name_words=tuple(w.strip("'-&") for w in words if w.strip("'-&")),
        width_mm=width.normalize() if width is not None else None,
        length_m=length.normalize() if length is not None else None,
        weight_kg=weight.normalize() if weight is not None else None,
        volume_l=volume.normalize() if volume is not None else None,
        colour=colour,
        pack=max(pack, 1),
        size_in=inches.normalize() if inches is not None else None,
    )


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def half_up(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def per_measure_pence(unit_price_pence: int, spec: ItemSpec) -> Decimal:
    """Price per metre / kg / litre / item, in pence to 4 dp: £11.40 for 6 × 66 m -> 2.8788p per metre."""
    return (Decimal(unit_price_pence) / spec.per_unit).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def saving_pence(paid_per_measure: Decimal, cheapest_per_measure: Decimal, volume: Decimal) -> int:
    """What buying `volume` (in the measure) at the cheapest price would have saved; never negative."""
    return max(0, half_up((paid_per_measure - cheapest_per_measure) * volume))


def pounds(pence: int | Decimal, dp: int = 2) -> str:
    q = Decimal(1).scaleb(-dp)
    return f"{(Decimal(pence) / 100).quantize(q, rounding=ROUND_HALF_UP)}"


# --------------------------------------------------------------------------- #
# Matching: same product (code), equivalent (model + code rules, or the user)
# --------------------------------------------------------------------------- #


def name_overlap(a: ItemSpec, b: ItemSpec) -> float:
    sa, sb = set(a.name_words), set(b.name_words)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def rules_allow(a: ItemSpec, b: ItemSpec) -> tuple[bool, str]:
    """Can two different item names be the same product? Code's rules, whatever the model said."""
    if a.measure != b.measure:
        return False, f"one is priced per {MEASURE_WORDS[a.measure]}, the other per {MEASURE_WORDS[b.measure]}"
    if a.size_in and b.size_in and a.size_in != b.size_in:
        return False, f"sizes differ ({_plain(a.size_in)} in and {_plain(b.size_in)} in)"
    if a.width_mm and b.width_mm:
        wide = max(a.width_mm, b.width_mm)
        if abs(a.width_mm - b.width_mm) / wide > WIDTH_TOLERANCE:
            return False, f"widths differ ({_plain(a.width_mm)} mm and {_plain(b.width_mm)} mm)"
    if name_overlap(a, b) < NAME_OVERLAP:
        return False, "the names have too few words in common"
    return True, "same kind of measure and size" + (
        "; different colour" if a.colour and b.colour and a.colour != b.colour else ""
    )


class MatchDecision(BaseModel):
    a: str  # item keys (ItemSpec.key), stored in sorted order
    b: str
    same: bool
    by: str  # "user:<email>"
    at: str


class MatchIn(StrictBody):
    a: str = Field(min_length=1, max_length=300)
    b: str = Field(min_length=1, max_length=300)
    same: bool


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


async def load_matches(books: Books) -> list[MatchDecision]:
    raw = await books.read_json(ITEM_MATCHES, [])
    out = []
    for row in raw if isinstance(raw, list) else []:
        try:
            out.append(MatchDecision.model_validate(row))
        except ValueError:
            continue  # a hand-edited row that no longer parses: ignored, not fatal
    return out


async def save_match(books: Books, body: MatchIn, user: str) -> MatchDecision:
    """The user's answer for one possible match; a later answer for the same pair replaces the earlier one."""
    a, b = _pair(body.a, body.b)
    if a == b:
        raise ValueError("an item always matches itself")
    row = MatchDecision(a=a, b=b, same=body.same, by=f"user:{user}", at=now().isoformat())

    def change(rows: Any) -> Any:
        kept = [r for r in (rows if isinstance(rows, list) else []) if _pair(r.get("a", ""), r.get("b", "")) != (a, b)]
        return [*kept, row.model_dump()][-MATCHES_MAX:]

    await books._update_json(ITEM_MATCHES, [], change)
    await books.audit(f"user:{user}", "item_match", {"a": a, "b": b, "same": body.same})
    return row


# --------------------------------------------------------------------------- #
# Price history
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Observation:
    """One line item bought: what, from whom, when, and its prices."""

    description: str
    spec: ItemSpec
    supplier: str
    date: date
    qty: Decimal
    unit_price_pence: int
    per_measure: Decimal  # pence per metre / kg / litre / item
    source: str
    approved: bool = True


def observations(purchases: list[Purchase]) -> list[Observation]:
    out = []
    for p in purchases:
        for ln in p.lines:
            if ln.qty <= 0 or ln.unit_price_pence <= 0:
                continue  # discounts, deposits and free lines say nothing about a price
            spec = normalise(ln.description)
            if not spec.name_words:
                continue
            out.append(
                Observation(
                    description=ln.description,
                    spec=spec,
                    supplier=p.supplier,
                    date=p.date,
                    qty=Decimal(str(ln.qty)),
                    unit_price_pence=ln.unit_price_pence,
                    per_measure=per_measure_pence(ln.unit_price_pence, spec),
                    source=p.source,
                )
            )
    return out


class _Union:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {k: k for k in keys}

    def find(self, k: str) -> str:
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def join(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


class Paid(BaseModel):
    supplier: str
    description: str
    date: date
    unit_price: str  # pounds, as on the receipt
    per_measure: str  # pounds per metre / kg / litre / item, 4 dp
    pack: int
    source: str


class Saving(BaseModel):
    per_month: str  # pounds
    per_year: str
    monthly_volume: str  # in the measure (metres, kg, litres or items)
    monthly_items: str  # the same volume in the items last bought (rolls, tubs)
    explanation: str


class PriceGroup(BaseModel):
    id: str  # the group's first item key
    name: str
    measure: Measure
    measure_word: str
    keys: list[str]
    match: Literal["same", "equivalent"]  # equivalent: different names joined by the user, or by the model + rules
    joined_by: list[str] = []  # "user", "ai+rules"
    observations: int
    suppliers: list[str]
    latest: Paid
    cheapest: Paid
    by_supplier: list[Paid]  # each supplier's latest price, cheapest first
    saving: Saving | None = None  # None when the latest price is already the cheapest
    monthly_volume: str = "0"  # your usual amount a month, in the measure
    average_paid: str = "0"  # pounds per measure, weighted by what you bought
    _average_pence: Decimal = PrivateAttr(default=Decimal(0))
    _cheapest_pence: Decimal = PrivateAttr(default=Decimal(0))
    live_offers: list[LiveOffer] = []  # only with a live price search on; never mixed into `cheapest`
    live_saving: Saving | None = None  # the latest price against the cheapest comparable live offer


class PossibleMatch(BaseModel):
    a: str
    b: str
    a_name: str
    b_name: str
    rules_ok: bool
    rules_note: str
    ai_says_same: bool | None = None  # only after POST /books/prices/suggest


class LiveOffer(BaseModel):
    """A live price search result, with code's unit-price maths. Always labelled with where and when it was found."""

    source: str  # the provider
    retrieved_at: datetime
    supplier: str
    title: str
    url: str
    unit_price: str  # pounds, one unit as sold
    pack: int
    per_measure: str | None  # pounds per metre / kg / litre / item, 4 dp; None when not comparable
    measure_word: str
    comparable: bool  # code's rules: same kind of measure and size as the item it was searched for
    note: str


class PriceReport(BaseModel):
    since: date
    until: date
    lines_read: int
    groups: list[PriceGroup]
    possible_matches: list[PossibleMatch]
    total_saving_per_year: str
    coverage_note: str = COVERAGE_NOTE
    web_search: price_search.SearchStatus
    ai_used: bool = False
    ai_note: str | None = None


def _paid(o: Observation) -> Paid:
    return Paid(
        supplier=o.supplier,
        description=o.description,
        date=o.date,
        unit_price=pounds(o.unit_price_pence),
        per_measure=pounds(o.per_measure, 4),
        pack=o.spec.pack,
        source=o.source,
    )


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def uk_day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _plural(word: str, n: Decimal) -> str:
    return word if n == 1 or word == "kg" else f"{word}s"


def _saving(paid: Decimal, best: Decimal, monthly: Decimal, spec: ItemSpec, why: str) -> Saving | None:
    """The saving at the usual monthly volume if every unit had cost `best` instead of `paid` (pence per measure)."""
    per_month = saving_pence(paid, best, monthly)
    if per_month <= 0:
        return None
    items = (monthly / spec.per_unit).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    word = MEASURE_WORDS[spec.measure]
    return Saving(
        per_month=pounds(per_month),
        per_year=pounds(per_month * 12),
        monthly_volume=_plain(monthly) or "0",
        monthly_items=_plain(items) or "0",
        explanation=f"{why} At your usual {_plain(monthly)} {_plural(word, monthly)} a month, that is "
        f"£{pounds(per_month)} a month.",
    )


def _display(o: Observation) -> str:
    return o.description.strip()


def candidate_pairs(obs: list[Observation], decided: set[tuple[str, str]]) -> list[tuple[ItemSpec, ItemSpec]]:
    """Different item keys whose names overlap enough to ask about, not yet decided by the user."""
    specs: dict[str, ItemSpec] = {}
    for o in obs:
        specs.setdefault(o.spec.key, o.spec)
    keys = sorted(specs)
    out = []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if _pair(a, b) in decided:
                continue
            if name_overlap(specs[a], specs[b]) >= NAME_OVERLAP and specs[a].measure == specs[b].measure:
                out.append((specs[a], specs[b]))
    return out


def build_report(
    obs: list[Observation],
    decisions: list[MatchDecision],
    since: date,
    until: date,
    ai_links: dict[tuple[str, str], bool] | None = None,
) -> PriceReport:
    """Group the observations into products and work out every price and saving. `ai_links`: the model's verdicts
    on candidate pairs (POST /books/prices/suggest); a "same" counts only where code's rules allow it."""
    specs: dict[str, ItemSpec] = {}
    names: dict[str, str] = {}
    for o in sorted(obs, key=lambda o: o.date):
        specs.setdefault(o.spec.key, o.spec)
        names[o.spec.key] = _display(o)  # the latest description wins
    union = _Union(sorted(specs))
    joined: dict[str, set[str]] = defaultdict(set)
    decided = {(d.a, d.b): d.same for d in decisions}
    for (a, b), same in decided.items():
        if same and a in specs and b in specs:
            union.join(a, b)
            joined[a].add("user")
    possible: list[PossibleMatch] = []
    for sa, sb in candidate_pairs(obs, set(decided)):
        ok, note = rules_allow(sa, sb)
        ai = (ai_links or {}).get(_pair(sa.key, sb.key))
        if ai and ok:
            union.join(sa.key, sb.key)
            joined[sa.key].add("ai+rules")
            continue
        possible.append(
            PossibleMatch(
                a=sa.key,
                b=sb.key,
                a_name=names[sa.key],
                b_name=names[sb.key],
                rules_ok=ok,
                rules_note=note,
                ai_says_same=ai,
            )
        )

    members: dict[str, list[Observation]] = defaultdict(list)
    for o in obs:
        members[union.find(o.spec.key)].append(o)
    groups: list[PriceGroup] = []
    for root, group_obs in members.items():
        group_obs.sort(key=lambda o: (o.date, o.per_measure))
        keys = sorted({o.spec.key for o in group_obs})
        latest = group_obs[-1]
        cheapest = min(group_obs, key=lambda o: (o.per_measure, -o.date.toordinal()))
        per_supplier: dict[str, Observation] = {}
        for o in group_obs:
            per_supplier[o.supplier] = o  # the latest per supplier
        volume = sum((o.qty * o.spec.per_unit for o in group_obs), Decimal(0))
        months = max(1, min(HISTORY_MONTHS, _months(group_obs[0].date, until)))
        monthly = (volume / months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        spent = sum((o.qty * o.unit_price_pence for o in group_obs), Decimal(0))
        average = (spent / volume).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if volume else Decimal(0)
        saving = _saving(
            average,
            cheapest.per_measure,
            monthly,
            latest.spec,
            f"On average you paid £{pounds(average, 4)} per {MEASURE_WORDS[latest.spec.measure]}; the lowest in "
            f"your books is £{pounds(cheapest.per_measure, 4)} ({cheapest.supplier}, {uk_day(cheapest.date)}).",
        )
        by = sorted(per_supplier.values(), key=lambda o: o.per_measure)
        groups.append(
            PriceGroup(
                id=root,
                name=names[latest.spec.key],
                measure=latest.spec.measure,
                measure_word=MEASURE_WORDS[latest.spec.measure],
                keys=keys,
                match="equivalent" if len(keys) > 1 else "same",
                joined_by=sorted({w for k in keys for w in joined.get(k, set())}),
                observations=len(group_obs),
                suppliers=sorted(per_supplier),
                latest=_paid(latest),
                cheapest=_paid(cheapest),
                by_supplier=[_paid(o) for o in by],
                saving=saving,
                monthly_volume=_plain(monthly) or "0",
                average_paid=pounds(average, 4),
            )
        )
        groups[-1]._average_pence = average
        groups[-1]._cheapest_pence = cheapest.per_measure
    groups.sort(key=lambda g: (-(Decimal(g.saving.per_year) if g.saving else Decimal(0)), g.name.lower()))
    total = sum((Decimal(g.saving.per_year) for g in groups if g.saving), Decimal(0))
    return PriceReport(
        since=since,
        until=until,
        lines_read=len(obs),
        groups=groups,
        possible_matches=possible,
        total_saving_per_year=f"{total:.2f}",
        web_search=price_search.status(None),
    )


async def history(books: Books, until: date) -> tuple[list[Observation], date]:
    since = (until.replace(day=1) - timedelta(days=1)).replace(day=1)
    for _ in range(HISTORY_MONTHS - 2):
        since = (since - timedelta(days=1)).replace(day=1)
    return observations(await load_purchases(books, since, until)), since


def offer_spec(offer: price_search.Offer) -> ItemSpec:
    """The offer's title read like a receipt line; a pack size the provider states wins over one in the title."""
    spec = normalise(offer.title)
    return ItemSpec(**{**spec.__dict__, "pack": offer.pack if offer.pack > 1 else spec.pack})


def live_offer(offer: price_search.Offer, wanted: ItemSpec | None) -> tuple[LiveOffer, Decimal | None]:
    """Code's maths on one live offer, and its price per measure when it is comparable with `wanted`."""
    spec = offer_spec(offer)
    pm = per_measure_pence(offer.unit_price_pence, spec)
    ok, note = rules_allow(wanted, spec) if wanted is not None else (True, "")
    word = MEASURE_WORDS[spec.measure]
    return (
        LiveOffer(
            source=offer.source,
            retrieved_at=offer.retrieved_at,
            supplier=offer.supplier,
            title=offer.title,
            url=offer.url,
            unit_price=pounds(offer.unit_price_pence),
            pack=spec.pack,
            per_measure=pounds(pm, 4) if ok else None,
            measure_word=word,
            comparable=ok,
            note=(
                f"£{pounds(pm, 4)} per {word}" + (f" ({note})" if note.endswith("colour") else "")
                if ok
                else f"Not compared: {note}."
            ),
        ),
        pm if ok else None,
    )


async def add_live_offers(report: PriceReport, provider: price_search.PriceSearchProvider | None) -> PriceReport:
    """Search the groups people spend most on (at most SEARCHES_MAX) and attach labelled offers. Off: unchanged,
    and the report says live search is off."""
    if provider is None:
        return report
    trouble: str | None = None
    for g in sorted(report.groups, key=lambda g: -g.observations)[: price_search.SEARCHES_MAX]:
        wanted = normalise(g.latest.description)
        offers, why = await price_search.search(provider, g.name, wanted.as_dict())
        trouble = trouble or why
        priced = [live_offer(o, wanted) for o in offers]
        g.live_offers = [lo for lo, _pm in sorted(priced, key=lambda x: (x[1] is None, x[1] or 0))]
        best = min((pm for _lo, pm in priced if pm is not None), default=None)
        if best is not None and best < g._cheapest_pence:
            top = next(lo for lo, pm in priced if pm == best)
            g.live_saving = _saving(
                g._average_pence,
                best,
                Decimal(g.monthly_volume),
                wanted,
                f"{top.supplier} lists £{pounds(best, 4)} per {g.measure_word} (found by {top.source}, "
                f"{top.retrieved_at:%d %b %Y %H:%M} UTC; check it before you buy).",
            )
    report.web_search = price_search.status(provider, trouble)
    return report


async def price_report(
    books: Books,
    until: date,
    provider: price_search.PriceSearchProvider | None = None,
) -> PriceReport:
    obs, since = await history(books, until)
    report = build_report(obs, await load_matches(books), since, until)
    return await add_live_offers(report, provider)


def median_pence(values: list[int]) -> int:
    return half_up(Decimal(str(statistics.median(values)))) if values else 0


async def suggest(
    books: Books,
    until: date,
    cfg: Any,
    provider: price_search.PriceSearchProvider | None = None,
) -> PriceReport:
    """The report with the model's same-product suggestions applied where code's rules agree (nothing is stored:
    the user confirms a match to keep it)."""
    from app.ai import items as items_ai  # the only part of this module that talks to a model

    obs, since = await history(books, until)
    decisions = await load_matches(books)
    pairs = candidate_pairs(obs, {(d.a, d.b) for d in decisions})[: items_ai.PAIRS_MAX]
    names: dict[str, str] = {}
    for o in sorted(obs, key=lambda o: o.date):
        names[o.spec.key] = o.description
    verdicts, note = await items_ai.same_product([(names[a.key], names[b.key]) for a, b in pairs], cfg)
    links = {_pair(a.key, b.key): v for (a, b), v in zip(pairs, verdicts, strict=True) if v is not None}
    report = build_report(obs, decisions, since, until, links)
    report.ai_used = True
    report.ai_note = note or (
        f"Your AI looked at {len(pairs)} possible matches; code kept only those its rules allow."
        if pairs
        else "No possible matches to look at."
    )
    return await add_live_offers(report, provider)
