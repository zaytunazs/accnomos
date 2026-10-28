"""Tracking categories (up to two, e.g. Department and Project) and the Tracking Summary report.

`_System/Accounting/tracking.json` holds the categories and their options, each with a stable id. A ledger line
carries `tracking` as {category id: option id}, so renaming an option renames it everywhere; options in use are
archived, never deleted. Lines get tags from invoice lines (app/invoicing.py), from a bill's approval
(app/approve.py, edit `tracking`) and from manual journal lines (app/manual_journals.py).

The Tracking Summary is the profit and loss of the events dated in a period (app/reports.py's accounts and signs),
split by the option each line carries for one category; untagged lines are "Unassigned". Code only.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from accnomos_ledger.events import LedgerEvent
from app.books import Books, now
from app.chart import ACCOUNTING
from app.reports import account_code, section_of
from app.validation import LENIENT, StrictBody, Tags  # noqa: F401  (Tags re-exported)

TRACKING = f"{ACCOUNTING}/tracking.json"
MAX_CATEGORIES = 2
MAX_OPTIONS = 100
UNASSIGNED = "unassigned"


class TrackingError(ValueError):
    """The tracking categories cannot be changed, or a line tagged, as asked."""


class TrackingOption(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=60)
    archived: bool = False


class TrackingCategory(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=40)
    options: list[TrackingOption] = []

    def option(self, option_id: str) -> TrackingOption | None:
        return next((o for o in self.options if o.id == option_id), None)


class TrackingConfig(BaseModel):
    categories: list[TrackingCategory] = []

    def category(self, category_id: str) -> TrackingCategory | None:
        return next((c for c in self.categories if c.id == category_id), None)


async def load_tracking(books: Books) -> TrackingConfig:
    raw = await books.read_json(TRACKING, None)
    if raw is None:
        return TrackingConfig()
    try:
        return TrackingConfig.model_validate(raw, **LENIENT)
    except ValidationError as exc:
        raise TrackingError(
            "The tracking file could not be read; fix or remove _System/Accounting/tracking.json"
        ) from exc


async def save_tracking(books: Books, cfg: TrackingConfig, user: str, action: str, refs: dict) -> None:
    payload = {**cfg.model_dump(mode="json"), "updated_by": user, "updated_at": now().isoformat()}
    await books._update_json(TRACKING, None, lambda _old: payload)
    await books.audit(f"user:{user}", action, refs)


def _name(raw: str, what: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise TrackingError(f"Give the {what} a name")
    return name


def add_category(cfg: TrackingConfig, name: str) -> TrackingCategory:
    if len(cfg.categories) >= MAX_CATEGORIES:
        raise TrackingError(f"You can have {MAX_CATEGORIES} tracking categories; rename one instead")
    name = _name(name, "category")
    if any(c.name.casefold() == name.casefold() for c in cfg.categories):
        raise TrackingError(f"There is already a category called {name}")
    cat = TrackingCategory(id=uuid.uuid4().hex[:12], name=name)
    cfg.categories.append(cat)
    return cat


def rename_category(cfg: TrackingConfig, category_id: str, name: str) -> TrackingCategory:
    cat = cfg.category(category_id)
    if cat is None:
        raise FileNotFoundError("No such tracking category")
    name = _name(name, "category")
    if any(c is not cat and c.name.casefold() == name.casefold() for c in cfg.categories):
        raise TrackingError(f"There is already a category called {name}")
    cat.name = name
    return cat


def used_tags(events: Iterable[LedgerEvent]) -> set[tuple[str, str]]:
    return {(c, o) for e in events for ln in e.lines for c, o in (ln.tracking or {}).items()}


def delete_category(cfg: TrackingConfig, category_id: str, used: set[tuple[str, str]]) -> TrackingCategory:
    cat = cfg.category(category_id)
    if cat is None:
        raise FileNotFoundError("No such tracking category")
    if any(c == category_id for c, _ in used):
        raise TrackingError(
            f"Lines in your books are tagged with {cat.name}, so it can't be deleted; archive its options"
        )
    cfg.categories.remove(cat)
    return cat


def add_option(cfg: TrackingConfig, category_id: str, name: str) -> TrackingOption:
    cat = cfg.category(category_id)
    if cat is None:
        raise FileNotFoundError("No such tracking category")
    if len(cat.options) >= MAX_OPTIONS:
        raise TrackingError(f"{cat.name} already has {MAX_OPTIONS} options")
    name = _name(name, "option")
    if any(o.name.casefold() == name.casefold() for o in cat.options):
        raise TrackingError(f"{cat.name} already has an option called {name}")
    opt = TrackingOption(id=uuid.uuid4().hex[:12], name=name)
    cat.options.append(opt)
    return opt


def edit_option(
    cfg: TrackingConfig, category_id: str, option_id: str, name: str | None, archived: bool | None
) -> TrackingOption:
    cat = cfg.category(category_id)
    opt = cat.option(option_id) if cat else None
    if cat is None or opt is None:
        raise FileNotFoundError("No such tracking option")
    if name is not None:
        new = _name(name, "option")
        if any(o is not opt and o.name.casefold() == new.casefold() for o in cat.options):
            raise TrackingError(f"{cat.name} already has an option called {new}")
        opt.name = new
    if archived is not None:
        opt.archived = archived
    return opt


def check_tags(cfg: TrackingConfig, tags: dict[str, str] | None) -> dict[str, str] | None:
    """The tags for one line, checked against the categories: known category, active option. None when empty."""
    if not tags:
        return None
    out: dict[str, str] = {}
    for cid, oid in tags.items():
        if not oid:
            continue
        cat = cfg.category(cid)
        if cat is None:
            raise TrackingError("A line is tagged with a tracking category that no longer exists")
        opt = cat.option(oid)
        if opt is None:
            raise TrackingError(f"A line is tagged with an option {cat.name} does not have")
        if opt.archived:
            raise TrackingError(f"{cat.name}: {opt.name} is archived; restore it to tag new lines with it")
        out[cid] = oid
    return out or None


class TrackingIn(StrictBody):
    name: str = Field(min_length=1, max_length=60)


class OptionEdit(StrictBody):
    name: str | None = Field(None, min_length=1, max_length=60)
    archived: bool | None = None


# --------------------------------------------------------------------------- #
# Tracking Summary
# --------------------------------------------------------------------------- #


class TrackingRow(BaseModel):
    account: str
    section: str  # sales | cost_of_sales | overheads
    by_option: dict[str, int]  # option id (or "unassigned") -> pence, sales as income and costs as spending
    total_pence: int


class TrackingColumn(BaseModel):
    id: str
    name: str
    archived: bool = False


class TrackingSummary(BaseModel):
    start: date
    end: date
    category: TrackingColumn
    columns: list[TrackingColumn]  # the category's options, then Unassigned
    rows: list[TrackingRow]
    totals: dict[str, dict[str, int]]  # section -> option -> pence; plus "net_profit"
    net_profit_total_pence: int
    basis: str = "As approved, from the ledger lines dated in the period; worked out by code."


def tracking_summary(
    events: Sequence[LedgerEvent], cfg: TrackingConfig, category_id: str, start: date, end: date
) -> TrackingSummary:
    cat = cfg.category(category_id)
    if cat is None:
        raise FileNotFoundError("No such tracking category")
    ids = [o.id for o in cat.options] + [UNASSIGNED]
    amounts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(ids, 0))
    for e in events:
        if not (start <= e.date <= end):
            continue
        for ln in e.lines:
            sec = section_of(ln.account)
            if sec is None:
                continue
            opt = (ln.tracking or {}).get(category_id)
            key = opt if opt in amounts[ln.account] else UNASSIGNED
            amounts[ln.account][key] += (ln.credit - ln.debit) if sec == "sales" else (ln.debit - ln.credit)
    rows = [
        TrackingRow(account=a, section=section_of(a) or "", by_option=v, total_pence=sum(v.values()))
        for a, v in sorted(amounts.items(), key=lambda kv: (account_code(kv[0]) or 0, kv[0]))
        if any(v.values())
    ]
    totals: dict[str, dict[str, int]] = {}
    for sec in ("sales", "cost_of_sales", "overheads"):
        totals[sec] = {i: sum(r.by_option[i] for r in rows if r.section == sec) for i in ids}
    totals["net_profit"] = {i: totals["sales"][i] - totals["cost_of_sales"][i] - totals["overheads"][i] for i in ids}
    columns = [TrackingColumn(id=o.id, name=o.name, archived=o.archived) for o in cat.options]
    columns.append(TrackingColumn(id=UNASSIGNED, name="Unassigned"))
    return TrackingSummary(
        start=start,
        end=end,
        category=TrackingColumn(id=cat.id, name=cat.name),
        columns=columns,
        rows=rows,
        totals=totals,
        net_profit_total_pence=sum(totals["net_profit"].values()),
    )
