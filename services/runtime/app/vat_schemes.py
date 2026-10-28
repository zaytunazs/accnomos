"""The business's VAT schemes, as saved in its own books, and the VAT boxes worked out under them. By code, no model.

Stored in `_System/vat/schemes.json` (one file per set of books, so per business; no Accnomos database):

    {"registered_on": "2025-02-01",                     VAT registration date (the flat rate's first-year 1%)
     "schemes": [{"from": "2025-02-01", "scheme": "standard"},
                 {"from": "2026-04-01", "scheme": "flat_rate",
                  "flat_rate": {"sector": "Photography", "turnover_method": "basic", "limited_cost": "auto"}}],
     "annual": {"start": "2026-01-01", "instalments": "monthly", "basis_pence": 1000000} | null,
     "capital_purchases": ["<event id>", ...],           flat rate: single purchases of capital goods of £2,000+
     "relevant_goods_accounts": ["5000", "7200", "7500"] | null,
     "estimates": {"taxable_turnover_pence": ..., "total_income_pence": ...},
     "updated_at": ..., "updated_by": ...}

Each entry of `schemes` runs from its `from` date to the day before the next one. The rules (thresholds, when a scheme
may start or stop, how the boxes are filled) live in accnomos_ledger.vat_schemes with their gov.uk sources; this module
checks a saved timeline against them, works out the eligibility tests from the books, and feeds the engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from accnomos_ledger import LedgerEvent, VatCode, compute_scheme_return
from accnomos_ledger.vat_schemes import (
    ANNUAL_JOIN_LIMIT,
    ANNUAL_LEAVE_LIMIT,
    CAPITAL_GOODS_MIN_GROSS,
    CASH_JOIN_LIMIT,
    CASH_LEAVE_LIMIT,
    FLAT_RATE_SECTORS,
    FRS_JOIN_LIMIT,
    FRS_LEAVE_LIMIT,
    AnnualAccounting,
    DocPayment,
    FlatRate,
    SchemeBooks,
    SchemeReturn,
    SchemeSpan,
    annual_period_containing,
    annual_periods,
    annual_return_due,
    first_anniversary,
    instalment_schedule,
    months_later,
    sector_rate,
    segments_of,
    span_at,
    validate_spans,
)
from app.books import SYSTEM, Books
from app.cash_basis import document_money
from app.contacts import Ledger, load_ledger
from app.deadlines import add_months, filing_deadline, period_containing, period_from_id, period_id
from app.validation import LENIENT
from app.vat_cycle import VatCycle

log = logging.getLogger(__name__)
SCHEMES_PATH = f"{SYSTEM}/vat/schemes.json"
SOURCES = {
    "flat_rate": "https://www.gov.uk/guidance/flat-rate-scheme-for-small-businesses-vat-notice-733--2",
    "flat_rates": "https://www.gov.uk/vat-flat-rate-scheme/how-much-you-pay",
    "cash": "https://www.gov.uk/guidance/vat-cash-accounting-scheme-notice-731",
    "annual": "https://www.gov.uk/guidance/vat-annual-accounting-notice-732",
    "boxes": "https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012",
}
CHECKED = "28 Oct 2026"
NAMES = {"standard": "Standard accounting", "cash": "Cash Accounting Scheme", "flat_rate": "Flat Rate Scheme"}


# --- what is saved ------------------------------------------------------------------------------------------------


class FlatRateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sector: str = Field(max_length=120)
    turnover_method: Literal["basic", "cash"] = "basic"
    limited_cost: Literal["auto", "yes", "no"] = "auto"

    @field_validator("sector")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in FLAT_RATE_SECTORS:
            raise ValueError("pick one of HMRC's business types (GET /books/vat/schemes lists them)")
        return v


class SchemeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    start: date = Field(alias="from")
    scheme: Literal["standard", "cash", "flat_rate"]
    flat_rate: FlatRateIn | None = None
    cash_exit: Literal["immediate", "six_months"] = "immediate"


class AnnualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    first_year_end: date | None = None
    instalments: Literal["monthly", "quarterly"] = "monthly"
    basis_pence: int | None = Field(default=None, ge=0)  # the figure in HMRC's letter: last year's VAT, or its estimate
    end: date | None = None


class Estimates(BaseModel):
    """What the business expects for the next 12 months, for the joining tests; empty = the last 12 months' books."""

    model_config = ConfigDict(extra="forbid")

    taxable_turnover_pence: int | None = Field(default=None, ge=0)  # excluding VAT: standard, reduced and zero-rated
    total_income_pence: int | None = Field(
        default=None, ge=0
    )  # including VAT, taxable and exempt (flat rate leaving test)


class VatSchemeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    registered_on: date | None = None
    schemes: list[SchemeEntry] = Field(default_factory=list, max_length=50)
    annual: AnnualIn | None = None
    capital_purchases: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        default_factory=list, max_length=500
    )
    relevant_goods_accounts: list[str] | None = Field(default=None, max_length=50)
    estimates: Estimates = Field(default_factory=lambda: Estimates())
    updated_at: datetime | None = None
    updated_by: str | None = Field(default=None, max_length=320)  # set by the runtime on save

    @field_validator("relevant_goods_accounts")
    @classmethod
    def _codes(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and not all(len(c) == 4 and c.isdigit() for c in v):
            raise ValueError("account codes are 4 digits, e.g. 5000")
        return v

    @property
    def in_use(self) -> bool:
        """Anything other than standard accounting with quarterly or monthly returns."""
        return self.annual is not None or any(e.scheme != "standard" for e in self.schemes)


def spans_of(s: VatSchemeSettings) -> list[SchemeSpan]:
    entries = sorted(s.schemes, key=lambda e: e.start)
    out = []
    for i, e in enumerate(entries):
        end = entries[i + 1].start - timedelta(days=1) if i + 1 < len(entries) else None
        fr = (
            FlatRate(e.flat_rate.sector, e.flat_rate.turnover_method, e.flat_rate.limited_cost) if e.flat_rate else None
        )
        out.append(SchemeSpan(e.start, end, e.scheme, fr, e.cash_exit))
    return out


def annual_of(s: VatSchemeSettings) -> AnnualAccounting | None:
    a = s.annual
    return AnnualAccounting(a.start, a.first_year_end, a.instalments, a.basis_pence, a.end) if a else None


async def load_settings(books: Books) -> VatSchemeSettings:
    """schemes.json as saved; missing = standard accounting. A file that does not read (hand-edited) is logged and
    treated as standard accounting, never a 500."""
    try:
        raw = await books.read_json(SCHEMES_PATH, None)
    except ValueError:
        raw = None
        log.warning("%s does not read as JSON; standard accounting assumed", SCHEMES_PATH)
    if not isinstance(raw, dict):
        return VatSchemeSettings()
    try:
        return VatSchemeSettings.model_validate(raw, **LENIENT)
    except ValidationError:
        log.warning("%s does not match the expected shape; standard accounting assumed", SCHEMES_PATH)
        return VatSchemeSettings()


# --- VAT periods when annual accounting is in use -----------------------------------------------------------------


@dataclass(frozen=True)
class SchemeContext:
    """The saved schemes for one request, and the VAT periods they make with the business's VAT cycle."""

    settings: VatSchemeSettings = field(default_factory=lambda: VatSchemeSettings())
    cycle: VatCycle = field(default_factory=VatCycle)

    @property
    def spans(self) -> list[SchemeSpan]:
        return spans_of(self.settings)

    @property
    def annual(self) -> AnnualAccounting | None:
        return annual_of(self.settings)

    @property
    def needs_ledger(self) -> bool:
        """Cash basis needs every payment (and documents from before the period), so the whole ledger."""
        return any(s.cash_basis for s in self.spans)

    def is_annual(self, start: date, end: date) -> bool:
        a = self.annual
        return a is not None and annual_period_containing(a, start) == (start, end)

    def period_at(self, day: date) -> tuple[date, date]:
        """The VAT period containing `day`: an annual one while annual accounting is in use, else the cycle's."""
        a = self.annual
        if a is not None and (p := annual_period_containing(a, day)) is not None:
            return p
        return period_containing(day, self.cycle.start_month, self.cycle.months)

    def current(self, today: date) -> tuple[date, date]:
        return self.period_at(today)

    def previous(self, start: date) -> tuple[date, date]:
        return self.period_at(start - timedelta(days=1))

    def recent(self, today: date, previous: int = 8) -> list[tuple[date, date]]:
        out = [self.current(today)]
        for _ in range(previous):
            out.append(self.previous(out[-1][0]))
        return out

    def period_id(self, start: date, end: date) -> str:
        """'2026-Y01' for an annual period starting January 2026; else '2026-Q4' or '2026-11' as before."""
        if self.is_annual(start, end):
            return f"{start.year}-Y{start.month:02d}"
        return period_id(start, self.cycle.months)

    def period_from_id(self, pid: str) -> tuple[date, date]:
        """Raises ValueError."""
        year, _, rest = pid.partition("-")
        if rest.startswith("Y"):
            a = self.annual
            if a is None or not (year.isdigit() and rest[1:].isdigit() and 1 <= int(rest[1:]) <= 12):
                raise ValueError(f"period {pid!r} is an annual period, and annual accounting is not set up")
            day = date(int(year), int(rest[1:]), 1)
            p = annual_period_containing(a, day)
            if p is None or p[0] != day:
                raise ValueError(f"no annual VAT period starts in {day:%B %Y}")
            return p
        return period_from_id(pid, self.cycle.start_month, self.cycle.months)

    def deadline(self, start: date, end: date) -> date:
        """Annual: 2 months after the period (1 under 4 months, Notice 732 §3.6); else 1 month and 7 days."""
        return annual_return_due(start, end) if self.is_annual(start, end) else filing_deadline(end)

    def period_starts(self, day: date) -> bool:
        return self.period_at(day)[0] == day


async def scheme_context(books: Books, cycle: VatCycle) -> SchemeContext:
    return SchemeContext(await load_settings(books), cycle)


# --- feeding the engine -------------------------------------------------------------------------------------------


def _extras(ctx: SchemeContext) -> dict[str, Any]:
    s = ctx.settings
    return {
        "capital": set(s.capital_purchases),
        "relevant_goods_accounts": tuple(s.relevant_goods_accounts) if s.relevant_goods_accounts is not None else None,
        "registered_on": s.registered_on,
    }


def books_from_events(ctx: SchemeContext, events: list[LedgerEvent]) -> SchemeBooks:
    """Invoice basis only: the events dated in the periods are all the engine needs."""
    return SchemeBooks(events, **_extras(ctx))


def books_from_ledger(ctx: SchemeContext, ledger: Ledger) -> SchemeBooks:
    """Every event, and the money that settled each document: the payments, matched bank lines and overpayments
    applied that the income tax cash basis counts (app/cash_basis.py `document_money`), so the two never disagree."""
    settled = ledger.settlement()
    pays = [DocPayment(doc_id, day, pence) for doc_id, day, pence in document_money(settled)]
    return SchemeBooks(ledger.events, pays, on_account=set(settled.gross), due=dict(ledger.dues), **_extras(ctx))


async def scheme_books(books: Books, ctx: SchemeContext, start: date, end: date) -> SchemeBooks:
    """The events (and, for cash basis, the payments) the engine needs for periods within [start, end]."""
    if not ctx.needs_ledger:
        return books_from_events(ctx, await books.list_events(start, end))
    return books_from_ledger(ctx, await load_ledger(books))


def scheme_return(sb: SchemeBooks, ctx: SchemeContext, key: str, start: date, end: date) -> SchemeReturn:
    return compute_scheme_return(sb, ctx.spans, key, start, end)


# --- what is shown ------------------------------------------------------------------------------------------------


def _day(d: date) -> str:
    """'1 Apr 2026' (no %-d: it is not portable to Windows)."""
    return f"{d.day} {d:%b %Y}"


def pounds(pence: int) -> str:
    return f"{Decimal(pence) / 100:.2f}"


class FlatCalcView(BaseModel):
    start: date
    end: date
    percent: str  # "11", "15.5"
    turnover: str  # pounds, VAT inclusive
    tax: str
    first_year: bool


class SegmentView(BaseModel):
    start: date
    end: date
    scheme: Literal["standard", "cash", "flat_rate"]
    label: str  # "Flat Rate Scheme: Photography, basic turnover"
    cash_basis: bool
    payments: int  # cash basis: payments counted in this part
    unpaid_brought_in_vat: str  # pounds: VAT on unpaid documents brought in on leaving a cash basis
    turnover: str | None = None  # flat rate: VAT inclusive turnover (box 6)
    relevant_goods: str | None = None
    limited_cost_cap: str | None = None
    limited_cost: bool | None = None
    limited_cost_source: Literal["auto", "yes", "no"] | None = None
    capital_vat: str | None = None
    calcs: list[FlatCalcView] = []


class InstalmentView(BaseModel):
    number: int
    due: date
    amount: str  # pounds


class AnnualView(BaseModel):
    start: date
    end: date
    return_due: date
    instalments: list[InstalmentView]
    instalments_total: str
    basis_known: bool  # HMRC's figure for the instalments is saved in Settings
    balancing: str  # pounds, absolute: box 5 less the instalments
    balancing_direction: Literal["pay", "refund", "nil"]


class SchemeView(BaseModel):
    summary: str  # one sentence for the VAT page
    segments: list[SegmentView]
    annual: AnnualView | None = None
    sources: dict[str, str] = SOURCES
    checked: str = CHECKED


def segment_label(seg_scheme: str, span: SchemeSpan) -> str:
    if span.scheme == "flat_rate" and span.flat_rate is not None:
        method = "cash based turnover" if span.flat_rate.turnover_method == "cash" else "basic turnover"
        return f"Flat Rate Scheme: {span.flat_rate.sector}, {method}"
    return NAMES[seg_scheme]


def scheme_summary(ctx: SchemeContext, start: date, end: date) -> str | None:
    """'Flat Rate Scheme: Photography, basic turnover, with annual accounting' for the schemes used in [start, end]."""
    if not ctx.settings.in_use:
        return None
    names = list(dict.fromkeys(segment_label(sp.scheme, sp) for _a, _b, sp in segments_of(ctx.spans, start, end)))
    a = ctx.annual
    annual = a is not None and any(annual_period_containing(a, d) for d in (start, end))
    return " then ".join(names) + (", with annual accounting" if annual else "")


def annual_view(ctx: SchemeContext, start: date, end: date, box5_signed_pence: int) -> AnnualView | None:
    a = ctx.annual
    if a is None or not ctx.is_annual(start, end):
        return None
    plan = instalment_schedule(start, end, a.basis_pence, a.instalments)
    total = sum(i.amount_pence for i in plan)
    bal = box5_signed_pence - total
    return AnnualView(
        start=start,
        end=end,
        return_due=annual_return_due(start, end),
        instalments=[InstalmentView(number=i.number, due=i.due, amount=pounds(i.amount_pence)) for i in plan],
        instalments_total=pounds(total),
        basis_known=a.basis_pence is not None,
        balancing=pounds(abs(bal)),
        balancing_direction="pay" if bal > 0 else "refund" if bal < 0 else "nil",
    )


def scheme_view(ctx: SchemeContext, out: SchemeReturn, start: date, end: date) -> SchemeView:
    segs = []
    for seg in out.segments:
        span = span_at(ctx.spans, seg.start)
        view = SegmentView(
            start=seg.start,
            end=seg.end,
            scheme=seg.scheme,
            label=segment_label(seg.scheme, span),
            cash_basis=seg.cash_basis,
            payments=seg.payments,
            unpaid_brought_in_vat=pounds(seg.exit_vat),
        )
        if seg.scheme == "flat_rate":
            view.turnover = pounds(seg.turnover_pence)
            view.relevant_goods = pounds(seg.relevant_goods_pence)
            view.limited_cost_cap = pounds(seg.limited_cost_cap_pence)
            view.limited_cost = seg.limited_cost
            view.limited_cost_source = seg.limited_cost_source
            view.capital_vat = pounds(seg.capital_vat)
            view.calcs = [
                FlatCalcView(
                    start=c.start,
                    end=c.end,
                    percent=f"{c.percent.normalize():f}",
                    turnover=pounds(c.turnover_pence),
                    tax=pounds(c.tax_pence),
                    first_year=c.first_year,
                )
                for c in seg.calcs
            ]
        segs.append(view)
    names = list(dict.fromkeys(s.label for s in segs))
    signed = int((out.ret.total_vat_due - out.ret.vat_reclaimed) * 100)
    annual = annual_view(ctx, start, end, signed)
    summary = " then ".join(names) + (", with annual accounting" if annual else "") + "."
    return SchemeView(summary=summary, segments=segs, annual=annual)


# --- eligibility --------------------------------------------------------------------------------------------------


class Check(BaseModel):
    scheme: Literal["flat_rate", "cash", "annual"]
    status: Literal["ok", "warn", "stop"]  # stop: you cannot (or must no longer) use the scheme
    message: str
    figure: str | None = None  # pounds
    limit: str | None = None
    basis: Literal["estimate", "books"] | None = None
    source: str


TAXABLE = {VatCode.STANDARD, VatCode.REDUCED, VatCode.ZERO}


def last_12_months(events: list[LedgerEvent], end: date) -> tuple[int, int]:
    """(taxable sales excluding VAT, total income including VAT with exempt) for the 12 months to `end`, from the
    sales in the books on invoice basis. Capital asset sales are not told apart here."""
    start = add_months(date(end.year, end.month, 1), -11)
    taxable = income = 0
    for ev in events:
        if not (start <= ev.date <= end) or ev.net is None:
            continue
        sign = 1 if ev.kind == "sale" else -1 if ev.kind == "reversal" and ev.lines and _sales_reversal(ev) else 0
        if not sign:
            continue
        codes = {ln.vat_code for ln in ev.lines if ln.vat_code is not None}
        if codes & TAXABLE:
            taxable += sign * ev.net
        if codes & (TAXABLE | {VatCode.EXEMPT, VatCode.NO_VAT}):
            income += sign * (ev.net + (ev.vat or 0))
    return taxable, income


def _sales_reversal(ev: LedgerEvent) -> bool:
    return any(ln.debit and "Sales" in ln.account for ln in ev.lines)


def eligibility(ctx: SchemeContext, events: list[LedgerEvent], today: date) -> list[Check]:
    """The joining and leaving tests for the schemes in use now (Notice 733 §3, §12.2; 731 §2.1, §2.5; 732 §2.1,
    §2.4), on the business's own estimate when it gave one, else on the last 12 months of its books."""
    s = ctx.settings
    span = span_at(ctx.spans, today)
    taxable, income = last_12_months(events, today)
    est_taxable = s.estimates.taxable_turnover_pence
    out: list[Check] = []

    def join(scheme: Literal["flat_rate", "cash", "annual"], limit: int, what: str, src: str) -> None:
        figure, basis = (est_taxable, "estimate") if est_taxable is not None else (taxable, "books")
        ok = figure <= limit
        out.append(
            Check(
                scheme=scheme,
                status="ok" if ok else "warn",
                message=(
                    f"{what}: taxable turnover (excluding VAT) for the next 12 months must be £{limit // 100:,} or "
                    f"less to join. {'Your estimate' if basis == 'estimate' else 'The last 12 months in your books'}: "
                    f"£{pounds(figure)}." + ("" if ok else " Check with HMRC before relying on the scheme.")
                ),
                figure=pounds(figure),
                limit=pounds(limit),
                basis=basis,  # type: ignore[arg-type]
                source=src,
            )
        )

    if span.scheme == "flat_rate":
        join("flat_rate", FRS_JOIN_LIMIT, "Flat Rate Scheme", SOURCES["flat_rate"] + "#who-can-join")
        joined = span.start
        anniversary = joined
        while (nxt := first_anniversary(anniversary)) <= today:
            anniversary = nxt
        if anniversary > joined:
            _, year_income = last_12_months(events, anniversary - timedelta(days=1))
            over = year_income > FRS_LEAVE_LIMIT
            leave_by = ctx.period_at(anniversary)[1]
            out.append(
                Check(
                    scheme="flat_rate",
                    status="stop" if over else "ok",
                    message=(
                        f"At your Flat Rate Scheme anniversary ({_day(anniversary)}) your income including VAT "
                        f"for the year was £{pounds(year_income)}"
                        + (
                            f", over £{FRS_LEAVE_LIMIT // 100:,}: you must leave the scheme from the end of the VAT "
                            f"period containing the anniversary ({_day(leave_by)}), unless HMRC agrees the next "
                            "12 months will be £191,500 or less."
                            if over
                            else f" (the limit is £{FRS_LEAVE_LIMIT // 100:,})."
                        )
                    ),
                    figure=pounds(year_income),
                    limit=pounds(FRS_LEAVE_LIMIT),
                    basis="books",
                    source=SOURCES["flat_rate"] + "#when-you-must-leave-the-scheme",
                )
            )
        out.append(
            Check(
                scheme="flat_rate",
                status="ok",
                message=(
                    "If your income for the next 30 days alone could be over £230,000 you must leave the scheme from "
                    "the start of those 30 days (Notice 733 §12.2(b)); Accnomos cannot see future sales."
                ),
                source=SOURCES["flat_rate"] + "#when-you-must-leave-the-scheme",
            )
        )
    if span.scheme == "cash":
        join("cash", CASH_JOIN_LIMIT, "Cash Accounting Scheme", SOURCES["cash"] + "#eligibility")
        over = taxable > CASH_LEAVE_LIMIT
        if over:
            out.append(
                Check(
                    scheme="cash",
                    status="stop",
                    message=(
                        f"Taxable supplies in the last 12 months were £{pounds(taxable)}, over £1,600,000: you must "
                        f"leave cash accounting at the end of this VAT period ({_day(ctx.current(today)[1])}) and "
                        "bring the VAT on unpaid invoices and bills to account (Notice 731 §2.5, §6.4)."
                    ),
                    figure=pounds(taxable),
                    limit=pounds(CASH_LEAVE_LIMIT),
                    basis="books",
                    source=SOURCES["cash"] + "#if-the-value-of-your-taxable-supplies-go-over-135-million",
                )
            )
    a = ctx.annual
    if a is not None and annual_period_containing(a, today) is not None:
        join("annual", ANNUAL_JOIN_LIMIT, "Annual Accounting Scheme", SOURCES["annual"] + "#eligibility")
        if taxable > ANNUAL_LEAVE_LIMIT:
            out.append(
                Check(
                    scheme="annual",
                    status="stop",
                    message=(
                        f"Taxable supplies in the last 12 months were £{pounds(taxable)}, over £1,600,000: tell HMRC; "
                        "you will usually be taken off annual accounting at the end of this annual period "
                        "(Notice 732 §2.4, §4.7)."
                    ),
                    figure=pounds(taxable),
                    limit=pounds(ANNUAL_LEAVE_LIMIT),
                    basis="books",
                    source=SOURCES["annual"],
                )
            )
        if a.basis_pence is None:
            out.append(
                Check(
                    scheme="annual",
                    status="warn",
                    message=(
                        "Add the instalment figure from HMRC's letter (last year's VAT, or HMRC's estimate) so the "
                        "interim payments and the balancing payment can be worked out."
                    ),
                    source=SOURCES["annual"] + "#when-payments-are-due",
                )
            )
    return out


# --- checking a timeline before it is saved -----------------------------------------------------------------------


class SchemeRuleError(ValueError):
    """A timeline HMRC's rules do not allow; the message says which rule."""


def check_timeline(new: VatSchemeSettings, cycle: VatCycle, today: date) -> list[str]:
    """Raise SchemeRuleError for a timeline the rules do not allow; return warnings for ones worth a second look."""
    warnings: list[str] = []
    try:
        spans = validate_spans(spans_of(new))
    except ValueError as exc:
        raise SchemeRuleError(str(exc)) from exc
    starts = [e.start for e in new.schemes]
    if len(set(starts)) != len(starts):
        raise SchemeRuleError("two schemes start on the same day")
    ctx = SchemeContext(new, cycle)
    a = ctx.annual
    if a is not None:
        if not SchemeContext(VatSchemeSettings(), cycle).period_starts(a.start):
            raise SchemeRuleError(
                "annual accounting starts on the first day of a VAT period (Notice 732 §3.2); "
                f"{_day(a.start)} is not the start of one of your VAT periods"
            )
        try:
            annual_periods(a, a.start)
        except ValueError as exc:
            raise SchemeRuleError(str(exc)) from exc
        for d in (a.first_year_end, a.end):
            if d is not None and (d + timedelta(days=1)).day != 1:
                raise SchemeRuleError("annual accounting periods end on the last day of a month (Notice 732 §3.3)")
        if a.end is not None:
            if a.end < a.start:
                raise SchemeRuleError("annual accounting ends before it starts")
            if not SchemeContext(VatSchemeSettings(), cycle).period_starts(a.end + timedelta(days=1)):
                raise SchemeRuleError(
                    "after annual accounting the next VAT period starts the day after it ends; set your VAT periods "
                    "in Settings to the ones HMRC gave you so that day starts a period"
                )
    for prev, span in zip(spans, spans[1:], strict=False):
        day = span.start
        cash_change = (prev.scheme == "cash" or span.scheme == "cash") and prev.scheme != span.scheme
        if cash_change and not ctx.period_starts(day):
            raise SchemeRuleError(
                "cash accounting starts at the beginning of a VAT period and can only be left at the end of one "
                f"(Notice 731 §3.1, §6.1); {_day(day)} is not the first day of one of your VAT periods"
            )
        if prev.scheme == "flat_rate" and span.scheme != "flat_rate":
            again = next((s for s in spans if s.scheme == "flat_rate" and s.start > day), None)
            if again is not None and again.start < months_later(day, 12):
                raise SchemeRuleError(
                    "you cannot rejoin the Flat Rate Scheme within 12 months of leaving it (Notice 733 §3.6, §12.6)"
                )
            warnings.append(
                "Leaving the Flat Rate Scheme: you may be able to claim VAT on stock on hand (Notice 733 §12.8-12.9). "
                "Accnomos does not work that out; add it as a journal if it applies."
            )
    if spans and spans[0].scheme == "cash" and not ctx.period_starts(spans[0].start):
        raise SchemeRuleError("cash accounting starts at the beginning of a VAT period (Notice 731 §3.1)")
    for span in spans:
        if span.scheme in ("cash", "flat_rate") and span.start < ctx.current(today)[0]:
            warnings.append(
                f"{NAMES[span.scheme]} from {_day(span.start)} is in the past. Only record a past date if you "
                "were already on the scheme then: cash accounting cannot be applied retrospectively (Notice 731 §1.2), "
                "and HMRC confirms flat rate start dates in writing."
            )
    if new.registered_on is None and any(s.scheme == "flat_rate" for s in spans):
        warnings.append("Add your VAT registration date so the first-year 1% reduction is applied when it is due.")
    return warnings


def sectors(today: date) -> list[dict[str, str]]:
    return [{"name": n, "percent": f"{sector_rate(n, today).normalize():f}"} for n in FLAT_RATE_SECTORS]


def capital_candidates(events: list[LedgerEvent], capital: set[str]) -> list[dict[str, Any]]:
    """Purchases of £2,000 or more including VAT, which may be capital expenditure goods (Notice 733 §15)."""
    out = []
    for ev in events:
        if ev.kind == "purchase" and ev.net is not None and ev.net + (ev.vat or 0) >= CAPITAL_GOODS_MIN_GROSS:
            out.append(
                {
                    "event_id": ev.id,
                    "date": ev.date.isoformat(),
                    "counterparty": ev.counterparty,
                    "gross": pounds(ev.net + (ev.vat or 0)),
                    "vat": pounds(ev.vat or 0),
                    "marked": ev.id in capital,
                }
            )
    return out[-20:]
