"""The export registry: what can be downloaded, in which formats, and the document every report is built as.

A report is an `ExportSpec` whose `build(ctx)` returns a `ReportDoc`: a title, a period line, notes and one or more
tables (`Section`). The writers in app/exports/writers.py turn any ReportDoc into CSV, XLSX or PDF, so a feature only
writes the figures once. Vendor import files are ReportDocs too, with one section whose columns are the vendor's
template headings and whose cells are already formatted as the template wants (`ImportFile` says how the CSV is
written: header row or not, byte-order mark or not).

Registering a report from another feature (payroll, Income Tax):

    from app.exports.registry import ExportSpec, register

    async def build_p32(ctx: ExportContext) -> ReportDoc: ...

    register(ExportSpec(id="payroll-p32", group="payroll", title="P32 employer payment record", ...))

and add the module name to OPTIONAL_PLUGINS below, so GET /exports imports it. Ids are unique; registering one
twice raises.
Ids in RESERVED are kept for the feature named there. Groups shown on the web page are GROUPS; another feature may
add its own (the page lists unknown groups last). Favourites (starred reports) live in _System/exports/favourites.json
(app/routes_exports.py).
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from accnomos_ledger import LedgerEvent
    from app.books import Books
    from app.contacts import Contact, Ledger
    from app.exports.mapping import Mappings
    from app.vat_cycle import VatCycle

Format = Literal["csv", "xlsx", "pdf", "zip", "json"]
CellKind = Literal["text", "money", "pounds", "date", "int"]
RowStyle = Literal["normal", "heading", "subtotal", "total"]
Param = Literal["period", "as_of", "mode"]

#: The groups the Reports & exports page shows, in order: (id, heading). The first five follow Xero's "All reports"
#: list, so an accountant finds each report where they expect it.
GROUPS: tuple[tuple[str, str], ...] = (
    ("financial", "Financial statements"),
    ("payables", "Payables and receivables"),
    ("reconciliations", "Reconciliations"),
    ("taxes", "Taxes and balances"),
    ("transactions", "Transactions"),
    ("pack", "For your accountant"),
    ("export", "Export to another package"),
)
#: Modules that register reports (imported once, by catalogue()). Ours first; then other features' modules, which
#: may not exist yet in this checkout: a missing one is skipped, never fatal.
PLUGINS: list[str] = [
    "app.exports.accounts",
    "app.exports.statements",
    "app.exports.receivables",
    "app.exports.reconciliation",
    "app.exports.vat_reports",
    "app.exports.vendors",
    "app.exports.pack",
]
OPTIONAL_PLUGINS: list[str] = [
    "app.accounting_tools.reports",  # fixed-asset schedules, budgets, tracking, cash-flow forecast
    "app.sales_purchases.reports",  # sales by item
    "app.payroll_reports",  # PAYE/RTI and pensions
    "app.income_tax.reports",  # MTD Income Tax (self-employment)
]
#: Ids kept for reports other features build: (group, title, owner). Only the owner registers these ids (with
#: `owner=` set to the same name); the catalogue lists one only once it is registered.
RESERVED: dict[str, tuple[str, str, str]] = {
    "fixed-asset-schedule": ("financial", "Fixed asset schedule", "accounting-tools"),
    "depreciation-schedule": ("financial", "Depreciation schedule", "accounting-tools"),
    "budget-variance": ("financial", "Budget variance", "accounting-tools"),
    "budget-summary": ("financial", "Budget summary", "accounting-tools"),
    "tracking-summary": ("transactions", "Tracking summary", "accounting-tools"),
    "cash-flow-forecast": ("financial", "Cash-flow forecast", "accounting-tools"),
    "sales-by-item": ("payables", "Sales by item", "sales-purchases"),
}

MEDIA: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "json": "application/json",
}


class Column(BaseModel):
    key: str
    label: str
    kind: CellKind = "text"  # money: integer pence; pounds: whole pounds (VAT boxes 6-9); date: ISO yyyy-mm-dd


class Row(BaseModel):
    cells: dict[str, str | int | None]
    style: RowStyle = "normal"


class Section(BaseModel):
    title: str
    columns: list[Column]
    rows: list[Row] = []
    note: str | None = None


class ImportFile(BaseModel):
    """How a vendor import file's CSV is written. Cells are already strings in the vendor's date and number format."""

    package: str  # "Xero", "QuickBooks Online", "Sage 50", "Sage Accounting", "FreeAgent"
    template: str  # the vendor's own name for the template
    header: bool = True  # FreeAgent's bank CSV has no header row
    bom: bool = False
    source: str  # where the headings were checked, with the date: shown in the preview and the pack README
    instructions: str  # one line: where to import it in the package


class ReportDoc(BaseModel):
    id: str
    title: str
    period: str  # "1 Jul 2026 to 30 Sep 2026", "at 30 Sep 2026"
    basis: list[str] = []  # how the figures are worked out, one line each
    sections: list[Section]
    warnings: list[str] = []  # unmapped accounts, events left out of the VAT boxes, and the like
    sample: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    import_file: ImportFile | None = None  # set on vendor import files


@dataclass
class ExportContext:
    """One request's inputs. The ledger and contacts are read once, on first use, and shared by every report built."""

    books: Books
    today: date
    start: date
    end: date
    as_of: date
    cycle: VatCycle
    mode: str | None = None
    _ledger: Ledger | None = field(default=None, repr=False)
    _contacts: list[Contact] | None = field(default=None, repr=False)
    _paths: dict[str, str] | None = field(default=None, repr=False)
    _mappings: Mappings | None = field(default=None, repr=False)

    async def ledger(self) -> Ledger:
        if self._ledger is None:
            from app.contacts import load_ledger

            self._ledger = await load_ledger(self.books)
        return self._ledger

    async def events(self) -> list[LedgerEvent]:
        return (await self.ledger()).events

    async def contacts(self) -> list[Contact]:
        if self._contacts is None:
            from app.contacts import contact_book

            self._contacts, _, _ = await contact_book(self.books, await self.ledger())
        return self._contacts

    async def event_paths(self) -> dict[str, str]:
        """Event id -> its file under _System/Ledger/events (the digital link to the stored entry)."""
        if self._paths is None:
            self._paths = {ev.id: path for path, ev in await self.books.list_event_entries()}
        return self._paths

    async def mappings(self) -> Mappings:
        if self._mappings is None:
            from app.exports.mapping import load_mappings

            self._mappings = await load_mappings(self.books)
        return self._mappings

    @property
    def previous(self) -> tuple[date, date]:
        return previous_span(self.start, self.end)

    @property
    def last_year(self) -> tuple[date, date]:
        return year_earlier(self.start, self.end)


Builder = Callable[[ExportContext], Awaitable[ReportDoc]]


@dataclass(frozen=True)
class ExportSpec:
    id: str  # url-safe: "trial-balance", "xero-manual-journals"
    group: str  # one of GROUPS, or a feature's own
    title: str
    description: str
    build: Builder
    formats: tuple[Format, ...] = ("csv", "xlsx", "pdf")
    params: tuple[Param, ...] = ("period",)
    modes: tuple[tuple[str, str], ...] = ()  # (value, label); the first is the default
    package: str | None = None  # vendor exports: "xero", "qbo", "sage50", "sage-accounting", "freeagent"
    #: For formats a ReportDoc cannot express (the Accountant pack zip, the ledger JSON): format -> bytes.
    raw: Callable[[ExportContext], Awaitable[bytes]] | None = None
    slug: str = ""  # file name part; defaults to id
    owner: str = "exports"  # the feature that builds it; a RESERVED id must be registered by its owner

    @property
    def name(self) -> str:
        return self.slug or self.id


_REGISTRY: dict[str, ExportSpec] = {}


def register(spec: ExportSpec) -> ExportSpec:
    if spec.id in _REGISTRY:
        raise ValueError(f"export {spec.id!r} is registered twice")
    if spec.id in RESERVED and RESERVED[spec.id][2] != spec.owner:
        raise ValueError(f"export {spec.id!r} is kept for {RESERVED[spec.id][2]}")
    if not spec.formats:
        raise ValueError(f"export {spec.id!r} has no formats")
    _REGISTRY[spec.id] = spec
    return spec


_loaded = False


def catalogue() -> dict[str, ExportSpec]:
    """Every registered export, by id, after importing PLUGINS once."""
    global _loaded
    if not _loaded:
        for module in PLUGINS:
            importlib.import_module(module)
        for module in OPTIONAL_PLUGINS:
            try:
                importlib.import_module(module)
            except ModuleNotFoundError as e:
                if e.name is None or not module.startswith(e.name):
                    raise  # the module exists but imports something missing: a real error
        _loaded = True
    return dict(_REGISTRY)


def get(export_id: str) -> ExportSpec | None:
    return catalogue().get(export_id)


# --------------------------------------------------------------------------- #
# Small helpers every builder uses
# --------------------------------------------------------------------------- #


def uk_day(d: date) -> str:
    """1 Jul 2026."""
    return f"{d.day} {d:%b %Y}"


def span_label(start: date, end: date) -> str:
    return f"{uk_day(start)} to {uk_day(end)}"


def previous_span(start: date, end: date) -> tuple[date, date]:
    """The period before: whole calendar months shift by the same number of months (Jul–Sep -> Apr–Jun); any other
    span is the same number of days ending the day before `start`."""
    from app.deadlines import add_months

    prev_end = start - timedelta(days=1)
    if start.day == 1 and (end + timedelta(days=1)).day == 1:
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        return add_months(start, -months), prev_end
    return prev_end - timedelta(days=(end - start).days), prev_end


def year_earlier(start: date, end: date) -> tuple[date, date]:
    """The same dates a year earlier (29 Feb becomes 28 Feb)."""

    def back(d: date) -> date:
        try:
            return d.replace(year=d.year - 1)
        except ValueError:
            return d.replace(year=d.year - 1, day=28)

    return back(start), back(end)


def money_row(style: RowStyle = "normal", **cells: Any) -> Row:
    return Row(cells=cells, style=style)


def columns(*spec: tuple[str, str] | tuple[str, str, CellKind]) -> list[Column]:
    return [Column(key=s[0], label=s[1], kind=s[2] if len(s) > 2 else "text") for s in spec]  # type: ignore[misc]


def doc_from(
    spec_id: str,
    title: str,
    period: str,
    sections: Sequence[Section],
    *,
    basis: Sequence[str] = (),
    warnings: Sequence[str] = (),
    sample: bool = False,
    import_file: ImportFile | None = None,
) -> ReportDoc:
    return ReportDoc(
        id=spec_id,
        title=title,
        period=period,
        basis=list(basis),
        sections=list(sections),
        warnings=list(warnings),
        sample=sample,
        import_file=import_file,
    )
