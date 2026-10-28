"""Products and services: the catalogue behind the Item picker on invoices, quotes and purchase orders.

One file in the user's folder, `_System/Items/items.json`, a list of items (money in integer pence):

    code, name, description, unit, sale_price_pence, purchase_price_pence, vat_code,
    income_account, expense_account, archived

Picking an item fills a line (`fill_line`): its description (or name), unit, the price for the side of the
business the document is on (sale price on invoices and quotes, purchase price on purchase orders and bills), its VAT
code, and the catalogue code it came from. Nothing else follows the item afterwards: a line keeps what it was filled
with, so changing an item never rewrites a document already written, and archiving one never breaks one.

Accounts. `expense_account` is used: a purchase order converted to a bill proposes that account (it is posted only
when the user approves the bill in Review). `income_account` is kept and shown, but invoices still post every sale to
4000 Sales (docs/HONESTY.md): the VAT return finds sales by that word in the account name, so it must be an account
named "... Sales ..." for now.

CSV: `export_csv` writes our own columns; `import_csv` reads those and Xero's inventory export (`*ItemCode`,
`ItemName`, `SalesUnitPrice`, ...), matching items by code. Rows with a problem are skipped and listed.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.books import Books, now
from app.invoicing import SalesVatCode
from app.paths import SYSTEM
from app.validation import LENIENT, Pence, StrictBody

ITEMS = f"{SYSTEM}/Items/items.json"
CODE_RE = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,29}")
INCOME_RE = re.compile(r"4\d{3} \S.*Sales.*|4\d{3} Sales")
EXPENSE_RE = re.compile(r"[5-8]\d{3} \S.*")
DEFAULT_INCOME = "4000 Sales"
DEFAULT_EXPENSE = "7999 Sundry expenses"
MAX_PRICE = 100_000_000  # £1m: anything bigger is a typing slip
MAX_ITEMS = 5000
MAX_CSV_BYTES = 1_000_000
Side = Literal["sale", "purchase"]


class ItemError(ValueError):
    """The item cannot be saved as asked (a bad code, a duplicate, a bad CSV)."""


class ItemNotFound(ItemError):
    pass


class ItemIn(StrictBody):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(None, max_length=300)  # the line's description; the name when blank
    unit: str | None = Field(None, max_length=20)  # "hours", "each"
    sale_price_pence: Pence | None = Field(None, ge=0, le=MAX_PRICE)  # None: not sold
    purchase_price_pence: Pence | None = Field(None, ge=0, le=MAX_PRICE)  # None: not bought
    vat_code: SalesVatCode = "S"
    income_account: str = Field(DEFAULT_INCOME, max_length=60)
    expense_account: str = Field(DEFAULT_EXPENSE, max_length=60)
    archived: bool = False

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not CODE_RE.fullmatch(v):
            raise ValueError("The code is letters, digits, dots, dashes and underscores, up to 30 characters")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("The name cannot be blank")
        return v

    @field_validator("description", "unit")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("income_account")
    @classmethod
    def _income(cls, v: str) -> str:
        v = v.strip()
        if not INCOME_RE.fullmatch(v):
            raise ValueError('The income account is a 4000-4999 Sales account, e.g. "4000 Sales"')
        return v

    @field_validator("expense_account")
    @classmethod
    def _expense(cls, v: str) -> str:
        v = v.strip()
        if not EXPENSE_RE.fullmatch(v):
            raise ValueError('The expense account is a 5000-8999 account, e.g. "7999 Sundry expenses"')
        return v


class Item(ItemIn):
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class ItemFill(BaseModel):
    """What picking an item puts on a line. The price is None when the item has none for this side."""

    item_code: str
    description: str
    unit: str | None
    quantity: str
    unit_price_pence: int | None
    vat_code: SalesVatCode
    account: str  # the expense account on the purchase side, the income account on the sale side


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


async def load_items(books: Books, include_archived: bool = True) -> list[Item]:
    raw = await books.read_json(ITEMS, [])
    items = [Item.model_validate(r, **LENIENT) for r in raw if isinstance(r, dict)]
    items = [i for i in items if include_archived or not i.archived]
    return sorted(items, key=lambda i: i.code)


async def get_item(books: Books, code: str) -> Item:
    code = code.strip().upper()
    for i in await load_items(books):
        if i.code == code:
            return i
    raise ItemNotFound(f"No item with the code {code}")


def _dump(items: list[Item]) -> list[dict]:
    return [i.model_dump(mode="json") for i in sorted(items, key=lambda i: i.code)]


async def create_item(books: Books, body: ItemIn, user: str) -> Item:
    item = Item(**body.model_dump())

    def add(rows: list[dict]) -> list[dict]:
        if any(r.get("code") == item.code for r in rows):
            raise ItemError(f"There is already an item with the code {item.code}")
        if len(rows) >= MAX_ITEMS:
            raise ItemError(f"The catalogue is limited to {MAX_ITEMS} items")
        return _dump([*(Item.model_validate(r, **LENIENT) for r in rows), item])

    await books._update_json(ITEMS, [], add)
    await books.audit(f"user:{user}", "item_created", {"item": item.code})
    return item


async def update_item(books: Books, code: str, body: ItemIn, user: str) -> Item:
    code = code.strip().upper()
    if body.code != code:
        raise ItemError("An item's code cannot change: archive it and add a new one")
    done: dict[str, Item] = {}

    def change(rows: list[dict]) -> list[dict]:
        items = [Item.model_validate(r, **LENIENT) for r in rows]
        old = next((i for i in items if i.code == code), None)
        if old is None:
            raise ItemNotFound(f"No item with the code {code}")
        new = Item(**body.model_dump(), created_at=old.created_at)
        done["item"] = new
        return _dump([new if i.code == code else i for i in items])

    await books._update_json(ITEMS, [], change)
    await books.audit(f"user:{user}", "item_edited", {"item": code})
    return done["item"]


async def archive_item(books: Books, code: str, user: str, archived: bool = True) -> Item:
    item = await get_item(books, code)
    return await update_item(
        books,
        item.code,
        ItemIn(**{**item.model_dump(exclude={"created_at", "updated_at"}), "archived": archived}),
        user,
    )


# --------------------------------------------------------------------------- #
# Filling a line
# --------------------------------------------------------------------------- #


def fill_line(item: Item, side: Side, quantity: Decimal | str = "1") -> ItemFill:
    """The line an item makes: sale price on the sale side, purchase price on the purchase side."""
    price = item.sale_price_pence if side == "sale" else item.purchase_price_pence
    return ItemFill(
        item_code=item.code,
        description=item.description or item.name,
        unit=item.unit,
        quantity=str(quantity),
        unit_price_pence=price,
        vat_code=item.vat_code,
        account=item.income_account if side == "sale" else item.expense_account,
    )


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #

COLUMNS = (
    "code",
    "name",
    "description",
    "unit",
    "sale_price",
    "purchase_price",
    "vat_code",
    "income_account",
    "expense_account",
    "archived",
)


def pounds(p: int | None) -> str:
    """'45.00' from pence, exactly; blank for None."""
    if p is None:
        return ""
    return f"{p // 100}.{p % 100:02d}"


def _cell(s: str) -> str:
    """A text cell Excel will not run as a formula (leading = + - @ gets an apostrophe)."""
    return f"'{s}" if s[:1] in ("=", "+", "-", "@") else s


def export_csv(items: list[Item]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(COLUMNS)
    for i in sorted(items, key=lambda i: i.code):
        w.writerow(
            [
                _cell(i.code),
                _cell(i.name),
                _cell(i.description or ""),
                _cell(i.unit or ""),
                pounds(i.sale_price_pence),
                pounds(i.purchase_price_pence),
                i.vat_code,
                i.income_account,
                i.expense_account,
                "yes" if i.archived else "",
            ]
        )
    return out.getvalue()


#: Xero's inventory export columns, and ours, by the name a header is matched on (lower case, no spaces or stars).
_ALIASES = {
    "itemcode": "code",
    "code": "code",
    "itemname": "name",
    "name": "name",
    "salesdescription": "description",
    "description": "description",
    "unit": "unit",
    "salesunitprice": "sale_price",
    "saleprice": "sale_price",
    "purchasesunitprice": "purchase_price",
    "purchaseprice": "purchase_price",
    "vatcode": "vat_code",
    "salestaxrate": "vat_code",
    "salesaccount": "income_account",
    "incomeaccount": "income_account",
    "purchasesaccount": "expense_account",
    "expenseaccount": "expense_account",
    "archived": "archived",
}


def _header(h: str) -> str | None:
    return _ALIASES.get(re.sub(r"[\s*_-]", "", h.lstrip("﻿")).lower())


def _price(raw: str) -> int | None:
    s = raw.strip().replace("£", "").replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"{raw!r} is not a price") from exc
    if d < 0 or d != d.quantize(Decimal("0.01")):
        raise ValueError(f"{raw!r} is not pounds and pence")
    return int(d * 100)


def _vat(raw: str) -> str:
    s = raw.strip()
    if not s:
        return "S"
    if s.upper() in ("S", "R", "Z", "E", "O"):
        return s.upper()
    low = s.lower()
    if low.startswith("20"):
        return "S"
    if low.startswith("5%") or low.startswith("5 "):
        return "R"
    if "exempt" in low:
        return "E"
    if "out of scope" in low or "outside" in low or "no tax" in low:
        return "O"
    if low.startswith("0") or "zero" in low or "no vat" in low:
        return "Z"
    raise ValueError(f"VAT rate {raw!r} is not one of S, R, Z, E, O or a named rate such as '20% (VAT on Income)'")


class ImportRowError(BaseModel):
    line: int  # the CSV line, counting the header as 1
    code: str | None
    message: str


class ImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[ImportRowError]


def parse_csv(text: str) -> list[tuple[int, ItemIn | ImportRowError]]:
    """Every data row as an ItemIn or the reason it cannot be one. ItemError: not an item CSV at all."""
    if len(text.encode()) > MAX_CSV_BYTES:
        raise ItemError("The file is over 1 MB")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ItemError("The file is empty")
    cols = [_header(h) for h in rows[0]]
    if "code" not in cols or "name" not in cols:
        raise ItemError("The first row must name the columns, including a code and a name (code, name, ...)")
    out: list[tuple[int, ItemIn | ImportRowError]] = []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        cells = {c: row[i].strip() for i, c in enumerate(cols) if c and i < len(row)}
        code = cells.get("code", "")
        try:
            out.append(
                (
                    n,
                    ItemIn(
                        code=code,
                        name=cells.get("name", ""),
                        description=cells.get("description") or None,
                        unit=cells.get("unit") or None,
                        sale_price_pence=_price(cells.get("sale_price", "")),
                        purchase_price_pence=_price(cells.get("purchase_price", "")),
                        vat_code=_vat(cells.get("vat_code", "")),  # type: ignore[arg-type]
                        income_account=cells.get("income_account") or DEFAULT_INCOME,
                        expense_account=cells.get("expense_account") or DEFAULT_EXPENSE,
                        archived=cells.get("archived", "").lower() in ("yes", "true", "1", "y"),
                    ),
                )
            )
        except ValueError as exc:  # pydantic's ValidationError is one
            msg = "; ".join(
                e["msg"].removeprefix("Value error, ") for e in getattr(exc, "errors", lambda: [])()
            ) or str(exc)
            out.append((n, ImportRowError(line=n, code=code or None, message=msg)))
    return out


async def import_csv(books: Books, text: str, user: str, *, update_existing: bool = True) -> ImportResult:
    """Add the items in `text`; with `update_existing`, rows whose code is already in the catalogue replace it,
    otherwise they are skipped. A code twice in the file takes its last row."""
    parsed = parse_csv(text)
    errors = [r for _n, r in parsed if isinstance(r, ImportRowError)]
    good: dict[str, ItemIn] = {}
    for _n, r in parsed:
        if isinstance(r, ItemIn):
            good[r.code] = r
    counts = {"created": 0, "updated": 0, "skipped": 0}

    def merge(rows: list[dict]) -> list[dict]:
        existing = {i.code: i for i in (Item.model_validate(r, **LENIENT) for r in rows)}
        counts.update(created=0, updated=0, skipped=0)
        for code, body in good.items():
            old = existing.get(code)
            if old is None:
                if len(existing) >= MAX_ITEMS:
                    raise ItemError(f"The catalogue is limited to {MAX_ITEMS} items")
                existing[code] = Item(**body.model_dump())
                counts["created"] += 1
            elif update_existing:
                existing[code] = Item(**body.model_dump(), created_at=old.created_at)
                counts["updated"] += 1
            else:
                counts["skipped"] += 1
        return _dump(list(existing.values()))

    await books._update_json(ITEMS, [], merge)
    result = ImportResult(
        skipped=counts["skipped"] + len(errors), errors=errors, **{k: counts[k] for k in ("created", "updated")}
    )
    await books.audit(
        f"user:{user}",
        "items_imported",
        {"created": result.created, "updated": result.updated, "skipped": result.skipped},
    )
    return result
