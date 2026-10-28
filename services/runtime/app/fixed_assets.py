"""Fixed asset register, depreciation runs and disposals. The maths is accnomos_ledger.depreciation; this module keeps
the register and turns runs and disposals into manual journal drafts (app/manual_journals.py) for the user to approve.

`_System/Accounting/assets.json` holds the register (what was bought, when, for how much, on which accounts, and how
it is depreciated). What has been depreciated and whether an asset is disposed are **not** stored on the asset: they
are worked out from the posted journals (`asset_charges`, `disposal`), so voiding a journal undoes its effect.

- Registering an asset posts nothing: the purchase is already in the books (a bill coded to the asset's cost
  account, e.g. 0030 Office equipment; Find and recode moves one coded to an expense).
- *Run depreciation* to a month end proposes one journal: for each asset, the charges for every period ending by
  then that is not yet posted (Dr 8000 Depreciation / Cr the asset's accumulated depreciation account). One run may
  wait for approval at a time.
- *Dispose* proposes one journal: depreciation for any full periods up to the disposal date, then the asset out at
  cost and its accumulated depreciation, the proceeds to the bank (with output VAT if charged), and the difference to
  8010 Profit or loss on disposal (a gain credits it).
- This is book depreciation. **Capital allowances are separate**: they are claimed on the tax return, and an asset's
  tax written-down value is not its book value here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from accnomos_ledger.depreciation import Policy, disposal, month_end, schedule
from accnomos_ledger.events import LedgerEvent
from app.books import Books, now
from app.chart import ACCOUNTING, DEPRECIATION, DISPOSALS, ChartError, active_account, load_chart
from app.invoicing import money
from app.journal import BANK, VAT_CONTROL
from app.manual_journals import (
    AssetCharge,
    AssetDisposal,
    JournalError,
    JournalLineIn,
    ManualJournal,
    ManualJournalIn,
    create_draft,
    list_journals,
)
from app.validation import LENIENT, Day, Pence, StrictBody

ASSETS = f"{ACCOUNTING}/assets.json"
CAPITAL_ALLOWANCES_NOTE = (
    "Book depreciation only. Capital allowances (AIA, writing-down allowances) are worked out separately for tax "
    "and are not shown here."
)
AssetType = Literal["plant", "office", "motor", "computer", "other"]
TYPE_ACCOUNTS: dict[str, tuple[str, str]] = {
    "plant": ("0020 Plant and machinery", "0021 Plant and machinery depreciation"),
    "office": ("0030 Office equipment", "0031 Office equipment depreciation"),
    "motor": ("0040 Motor vehicles", "0041 Motor vehicles depreciation"),
    "computer": ("0050 Computer equipment", "0051 Computer equipment depreciation"),
}
MethodIn = Literal["none", "straight_line", "reducing_balance"]
MAX_PENCE = 10_000_000_000


class AssetError(ValueError):
    """The asset cannot be registered, changed, depreciated or disposed of as asked."""


class AssetIn(StrictBody):
    name: str = Field(min_length=1, max_length=120)
    asset_type: AssetType
    purchase_date: Day
    cost_pence: Pence = Field(gt=0, le=MAX_PENCE)
    residual_pence: Pence = Field(0, ge=0, le=MAX_PENCE)
    method: MethodIn = "straight_line"
    rate_percent: Decimal | None = Field(None, gt=0, le=100, decimal_places=2)
    life_years: int | None = Field(None, ge=1, le=100)
    frequency: Literal["monthly", "yearly"] = "monthly"
    cost_account: str | None = Field(None, max_length=90)  # default by type
    accumulated_account: str | None = Field(None, max_length=90)
    expense_account: str | None = Field(None, max_length=90)  # default 8000 Depreciation
    serial: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=500)


class Asset(BaseModel):
    id: str
    number: str
    name: str
    asset_type: AssetType
    purchase_date: date
    cost_pence: int
    residual_pence: int = 0
    method: MethodIn
    rate_percent: Decimal | None = None
    life_years: int | None = None
    frequency: Literal["monthly", "yearly"] = "monthly"
    cost_account: str
    accumulated_account: str
    expense_account: str
    serial: str | None = None
    notes: str | None = None
    created_by: str
    created_at: datetime

    def policy(self) -> Policy | None:
        if self.method == "none":
            return None
        return Policy(
            self.method,
            self.frequency,
            rate_percent=self.rate_percent,
            life_years=self.life_years,
            residual_pence=self.residual_pence,
        )


class AssetState(BaseModel):
    """What the posted journals say about one asset."""

    accumulated_pence: int = 0
    depreciated_to: date | None = None
    disposed_on: date | None = None
    disposal_journal: str | None = None
    proceeds_pence: int | None = None
    gain_pence: int | None = None
    pending_journal: str | None = None  # a draft that would depreciate or dispose of it


class AssetRow(Asset):
    state: AssetState
    book_value_pence: int
    status: Literal["registered", "disposed"]


async def list_assets(books: Books) -> list[Asset]:
    raw = await books.read_json(ASSETS, [])
    try:
        return [Asset.model_validate(r, **LENIENT) for r in raw]
    except (TypeError, ValidationError) as exc:
        raise AssetError("The fixed asset register could not be read; fix _System/Accounting/assets.json") from exc


async def _save_all(books: Books, assets: list[Asset]) -> None:
    payload = [a.model_dump(mode="json") for a in assets]
    await books._update_json(ASSETS, [], lambda _old: payload)


def states(assets: Iterable[Asset], journals: Iterable[ManualJournal]) -> dict[str, AssetState]:
    out = {a.id: AssetState() for a in assets}
    for j in journals:
        involved = [c.asset_id for c in j.asset_charges] + ([j.disposal.asset_id] if j.disposal else [])
        if j.status == "draft":
            for aid in involved:
                if aid in out:
                    out[aid].pending_journal = j.number
            continue
        if j.status != "posted":
            continue
        charges = list(j.asset_charges) + ([j.disposal.catch_up] if j.disposal and j.disposal.catch_up else [])
        for c in charges:
            if c.asset_id in out:
                s = out[c.asset_id]
                s.accumulated_pence += c.amount_pence
                s.depreciated_to = max(filter(None, (s.depreciated_to, c.end)))
        if j.disposal and j.disposal.asset_id in out:
            s = out[j.disposal.asset_id]
            s.disposed_on, s.disposal_journal = j.disposal.date, j.number
            s.proceeds_pence, s.gain_pence = j.disposal.proceeds_pence, j.disposal.gain_pence
    return out


def rows(assets: Sequence[Asset], journals: Sequence[ManualJournal]) -> list[AssetRow]:
    st = states(assets, journals)
    return [
        AssetRow(
            **a.model_dump(),
            state=st[a.id],
            book_value_pence=0 if st[a.id].disposed_on else a.cost_pence - st[a.id].accumulated_pence,
            status="disposed" if st[a.id].disposed_on else "registered",
        )
        for a in sorted(assets, key=lambda a: a.number)
    ]


async def register(books: Books, body: AssetIn, user: str) -> Asset:
    """Add an asset to the register. Posts nothing."""
    default_cost, default_acc = TYPE_ACCOUNTS.get(body.asset_type, (None, None))
    try:
        chart, _ = await load_chart(books)
        cost = active_account(chart, body.cost_account or default_cost or "")
        accum = active_account(chart, body.accumulated_account or default_acc or "")
        expense = active_account(chart, body.expense_account or DEPRECIATION)
    except ChartError as exc:
        if body.asset_type == "other" and not (body.cost_account and body.accumulated_account):
            raise AssetError("For an asset of type Other, choose its cost and depreciation accounts") from exc
        raise AssetError(str(exc)) from exc
    if cost.type != "fixed_asset" or accum.type != "fixed_asset":
        raise AssetError("The cost and accumulated depreciation accounts must be fixed asset accounts (0000–0999)")
    if cost.code == accum.code:
        raise AssetError("The cost and accumulated depreciation accounts must be different")
    if expense.type not in ("overhead", "direct_costs"):
        raise AssetError("The depreciation expense account must be an overhead or direct cost account")
    if body.method != "none":
        try:
            Policy(
                body.method,
                body.frequency,
                rate_percent=body.rate_percent,
                life_years=body.life_years if body.method == "straight_line" else None,
                residual_pence=body.residual_pence,
            )
        except ValueError as exc:
            raise AssetError(str(exc)) from exc
        if body.method == "reducing_balance" and body.life_years:
            raise AssetError("Reducing balance uses a rate, not a life")
    if body.residual_pence > body.cost_pence:
        raise AssetError("The residual value is more than the cost")
    assets = await list_assets(books)
    n = max((int(a.number.removeprefix("FA-")) for a in assets if a.number.removeprefix("FA-").isdigit()), default=0)
    asset = Asset(
        id=uuid.uuid4().hex[:16],
        number=f"FA-{n + 1:04d}",
        name=" ".join(body.name.split()),
        asset_type=body.asset_type,
        purchase_date=body.purchase_date,
        cost_pence=body.cost_pence,
        residual_pence=body.residual_pence,
        method=body.method,
        rate_percent=body.rate_percent,
        life_years=body.life_years,
        frequency=body.frequency,
        cost_account=cost.label,
        accumulated_account=accum.label,
        expense_account=expense.label,
        serial=(body.serial or "").strip() or None,
        notes=(body.notes or "").strip() or None,
        created_by=user,
        created_at=now(),
    )
    await _save_all(books, [*assets, asset])
    await books.audit(
        f"user:{user}", "asset_registered", {"asset": asset.id, "number": asset.number, "cost_pence": asset.cost_pence}
    )
    return asset


async def remove(books: Books, asset_id: str, user: str) -> Asset:
    """Take an asset off the register: only while no journal (posted or waiting) mentions it."""
    assets = await list_assets(books)
    asset = next((a for a in assets if a.id == asset_id), None)
    if asset is None:
        raise FileNotFoundError("No such asset")
    for j in await list_journals(books):
        if j.status in ("draft", "posted") and (
            any(c.asset_id == asset_id for c in j.asset_charges) or (j.disposal and j.disposal.asset_id == asset_id)
        ):
            raise AssetError(f"{asset.number} is in journal {j.number}; void or discard that first")
    await _save_all(books, [a for a in assets if a.id != asset_id])
    await books.audit(f"user:{user}", "asset_removed", {"asset": asset.id, "number": asset.number})
    return asset


def due_charge(asset: Asset, state: AssetState, upto: date) -> AssetCharge | None:
    """The asset's charges for the periods ending by `upto` that are not posted yet, as one charge."""
    policy = asset.policy()
    if policy is None or state.disposed_on:
        return None
    periods = [
        p
        for p in schedule(asset.cost_pence, asset.purchase_date, policy, upto=upto)
        if state.depreciated_to is None or p.end > state.depreciated_to
    ]
    if not periods:
        return None
    return AssetCharge(
        asset_id=asset.id,
        start=periods[0].start,
        end=periods[-1].end,
        amount_pence=sum(p.charge_pence for p in periods),
        periods=len(periods),
    )


def _span(c: AssetCharge) -> str:
    return (
        f"{c.start:%b %Y}–{c.end:%b %Y}"
        if (c.start.year, c.start.month) != (c.end.year, c.end.month)
        else f"{c.end:%b %Y}"
    )


async def run_depreciation(books: Books, upto: date, user: str) -> ManualJournal | None:
    """Propose the depreciation journal to the month end of `upto`. None when nothing is due."""
    upto = month_end(upto)
    assets = await list_assets(books)
    journals = await list_journals(books)
    if waiting := next((j for j in journals if j.status == "draft" and j.source == "depreciation"), None):
        raise AssetError(f"Depreciation journal {waiting.number} is waiting for approval; approve or discard it first")
    st = states(assets, journals)
    charges: list[tuple[Asset, AssetCharge]] = []
    for a in sorted(assets, key=lambda a: a.number):
        if st[a.id].pending_journal:
            continue  # a disposal is waiting for it
        if c := due_charge(a, st[a.id], upto):
            charges.append((a, c))
    if not charges:
        return None
    lines: list[JournalLineIn] = []
    for a, c in charges:
        what = f"{a.number} {a.name}: {_span(c)}"
        lines.append(JournalLineIn(account=a.expense_account, debit_pence=c.amount_pence, description=what))
        lines.append(JournalLineIn(account=a.accumulated_account, credit_pence=c.amount_pence, description=what))
    body = ManualJournalIn(date=upto, narration=f"Depreciation to {upto:%d %B %Y}", lines=lines)
    return await create_draft(books, body, user, source="depreciation", asset_charges=[c for _, c in charges])


class DisposeIn(StrictBody):
    date: Day
    proceeds_pence: Pence = Field(0, ge=0, le=MAX_PENCE)
    vat_pence: Pence = Field(0, ge=0, le=MAX_PENCE)  # output VAT charged on the sale, if any
    proceeds_account: str = Field(BANK, max_length=90)


async def dispose(books: Books, asset_id: str, body: DisposeIn, user: str) -> ManualJournal:
    """Propose the disposal journal (with catch-up depreciation for full periods to the disposal date)."""
    assets = await list_assets(books)
    asset = next((a for a in assets if a.id == asset_id), None)
    if asset is None:
        raise FileNotFoundError("No such asset")
    journals = await list_journals(books)
    state = states(assets, journals)[asset_id]
    if state.disposed_on:
        raise AssetError(f"{asset.number} was disposed of on {state.disposed_on:%d/%m/%Y}")
    if state.pending_journal:
        raise AssetError(f"Journal {state.pending_journal} for {asset.number} is waiting; approve or discard it first")
    if body.date < asset.purchase_date:
        raise AssetError("The disposal date is before the purchase date")
    if body.vat_pence and not body.proceeds_pence:
        raise AssetError("VAT is charged on proceeds: enter the proceeds too")
    catch_up = due_charge(asset, state, body.date)
    accumulated = state.accumulated_pence + (catch_up.amount_pence if catch_up else 0)
    result = disposal(asset.cost_pence, accumulated, body.proceeds_pence)
    what = f"{asset.number} {asset.name}: disposal"
    lines: list[JournalLineIn] = []
    if catch_up:
        dep = f"{asset.number} {asset.name}: {_span(catch_up)}"
        lines += [
            JournalLineIn(account=asset.expense_account, debit_pence=catch_up.amount_pence, description=dep),
            JournalLineIn(account=asset.accumulated_account, credit_pence=catch_up.amount_pence, description=dep),
        ]
    if accumulated:
        lines.append(JournalLineIn(account=asset.accumulated_account, debit_pence=accumulated, description=what))
    if body.proceeds_pence:
        lines.append(
            JournalLineIn(
                account=body.proceeds_account,
                debit_pence=body.proceeds_pence + body.vat_pence,
                vat_code="S" if body.vat_pence else None,
                description=f"{what}: proceeds",
            )
        )
    if body.vat_pence:
        lines.append(JournalLineIn(account=VAT_CONTROL, credit_pence=body.vat_pence, description=f"{what}: output VAT"))
    lines.append(JournalLineIn(account=asset.cost_account, credit_pence=asset.cost_pence, description=what))
    if result.gain_pence > 0:
        lines.append(JournalLineIn(account=DISPOSALS, credit_pence=result.gain_pence, description=f"{what}: gain"))
    elif result.gain_pence < 0:
        lines.append(JournalLineIn(account=DISPOSALS, debit_pence=-result.gain_pence, description=f"{what}: loss"))
    verb = "Sale" if body.proceeds_pence else "Disposal"
    narration = f"{verb} of {asset.number} {asset.name}" + (
        f" for {money(body.proceeds_pence)}" if body.proceeds_pence else ""
    )
    journal_body = ManualJournalIn(
        date=body.date, narration=narration[:300], lines=lines, vat_box="sales" if body.vat_pence else None
    )
    try:
        return await create_draft(
            books,
            journal_body,
            user,
            source="disposal",
            disposal=AssetDisposal(
                asset_id=asset.id,
                date=body.date,
                proceeds_pence=body.proceeds_pence,
                gain_pence=result.gain_pence,
                catch_up=catch_up,
            ),
            net_vat=(body.proceeds_pence, body.vat_pence) if body.vat_pence else None,
        )
    except JournalError as exc:
        raise AssetError(str(exc)) from exc


async def check_journal_still_fits(books: Books, j: ManualJournal) -> None:
    """Before a depreciation or disposal journal posts: the register and the posted journals have not moved on
    since it was drafted (no overlap, no gap, asset still there and not disposed)."""
    assets = {a.id: a for a in await list_assets(books)}
    others = [x for x in await list_journals(books) if x.id != j.id]
    st = states(assets.values(), others)
    charges = list(j.asset_charges) + ([j.disposal.catch_up] if j.disposal and j.disposal.catch_up else [])
    ids = {c.asset_id for c in charges} | ({j.disposal.asset_id} if j.disposal else set())
    for aid in ids:
        if aid not in assets:
            raise JournalError(f"An asset in {j.number} is no longer on the register; discard the journal")
        if st[aid].disposed_on:
            raise JournalError(f"{assets[aid].number} has been disposed of since {j.number} was drafted; discard it")
    for c in charges:
        due = due_charge(assets[c.asset_id], st[c.asset_id], c.end)
        if due is None or (due.start, due.end, due.amount_pence) != (c.start, c.end, c.amount_pence):
            raise JournalError(
                f"The depreciation of {assets[c.asset_id].number} has changed since {j.number} was drafted; "
                "discard it and run depreciation again"
            )
    if (
        j.disposal
        and not j.disposal.catch_up
        and due_charge(assets[j.disposal.asset_id], st[j.disposal.asset_id], j.disposal.date)
    ):
        raise JournalError(f"{assets[j.disposal.asset_id].number} has depreciation due; discard and dispose again")


async def check_void_allowed(books: Books, j: ManualJournal) -> None:
    """A depreciation journal can be voided only while it is the latest one for each of its assets and none of them
    has been disposed of since."""
    later = [x for x in await list_journals(books) if x.status == "posted" and x.id != j.id and x.date >= j.date]
    mine = {c.asset_id for c in j.asset_charges}
    for x in later:
        hit = mine & ({c.asset_id for c in x.asset_charges} | ({x.disposal.asset_id} if x.disposal else set()))
        if hit and (x.date > j.date or x.created_at > j.created_at):
            raise JournalError(f"Journal {x.number} depreciates or disposes of the same assets later; void that first")


def schedule_rows(asset: Asset, state: AssetState, limit: int = 600) -> list[dict]:
    policy = asset.policy()
    if policy is None:
        return []
    return [
        {
            "index": p.index,
            "start": p.start,
            "end": p.end,
            "charge_pence": p.charge_pence,
            "accumulated_pence": p.accumulated_pence,
            "book_value_pence": p.book_value_pence,
            "posted": state.depreciated_to is not None and p.end <= state.depreciated_to,
        }
        for p in schedule(asset.cost_pence, asset.purchase_date, policy)[:limit]
    ]


class ReconRow(BaseModel):
    account: str
    kind: Literal["cost", "accumulated_depreciation"]
    register_pence: int  # what the register says (cost of assets held; their accumulated depreciation, as a credit)
    ledger_pence: int  # the account's balance in the ledger (debit − credit for cost; credit − debit for depreciation)
    difference_pence: int  # ledger − register


def reconciliation(
    assets: Sequence[Asset], journals: Sequence[ManualJournal], events: Iterable[LedgerEvent]
) -> list[ReconRow]:
    """Register against ledger, per cost and accumulated depreciation account."""
    st = states(assets, journals)
    balance: dict[str, int] = {}
    for e in events:
        for ln in e.lines:
            balance[ln.account] = balance.get(ln.account, 0) + ln.debit - ln.credit
    reg: dict[tuple[str, str], int] = {}
    for a in assets:
        held = st[a.id].disposed_on is None
        reg[(a.cost_account, "cost")] = reg.get((a.cost_account, "cost"), 0) + (a.cost_pence if held else 0)
        key = (a.accumulated_account, "accumulated_depreciation")
        reg[key] = reg.get(key, 0) + (st[a.id].accumulated_pence if held else 0)
    out = []
    for (account, kind), register_pence in sorted(reg.items()):
        ledger = balance.get(account, 0) * (1 if kind == "cost" else -1)
        out.append(
            ReconRow(
                account=account,
                kind=kind,  # type: ignore[arg-type]
                register_pence=register_pence,
                ledger_pence=ledger,
                difference_pence=ledger - register_pence,
            )
        )
    return out
