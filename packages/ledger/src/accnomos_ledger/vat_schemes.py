"""VAT accounting schemes, by code: Flat Rate, Cash Accounting and Annual Accounting. No model, no I/O.

Sources (all read on gov.uk on 28 Oct 2026):
- Flat Rate Scheme for small businesses (VAT Notice 733), last updated 18 Dec 2025:
  https://www.gov.uk/guidance/flat-rate-scheme-for-small-businesses-vat-notice-733--2
- VAT Flat Rate Scheme: flat rates for types of business:
  https://www.gov.uk/vat-flat-rate-scheme/how-much-you-pay
- Cash Accounting Scheme (VAT Notice 731), last updated 18 Dec 2023:
  https://www.gov.uk/guidance/vat-cash-accounting-scheme-notice-731
- Annual Accounting Scheme (VAT Notice 732), last updated 22 Nov 2024:
  https://www.gov.uk/guidance/vat-annual-accounting-notice-732
- VAT Annual Accounting Scheme: return and payment deadlines:
  https://www.gov.uk/vat-annual-accounting-scheme/return-and-payment-deadlines
- HMRC internal manual VATAAS4100 (interim payments rounded down to the nearest £5):
  https://www.gov.uk/hmrc-internal-manuals/vat-annual-accounting-system/vataas4100
- How to fill in and submit your VAT Return (VAT Notice 700/12), sections 4.1-4.3 (boxes under each scheme):
  https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012

How the pieces fit:
- A business's schemes are a timeline of `SchemeSpan`s (standard, cash accounting, or flat rate with the basic or
  the cash-based turnover method). Days no span covers use standard (invoice) accounting.
- Every sale, purchase and credit note becomes one or more *tax moments*: a dated share of its net and VAT.
  On invoice basis that is the document's own date. On cash basis it is each payment's date, as a proportion of
  the gross (Notice 731 §5.7 and the worked examples in §8), with cumulative rounding so the parts add up to the
  whole. Which basis a document uses is decided by the scheme on its date; where its moments land decides how
  they count (normal boxes, or flat rate turnover).
- A VAT period is cut into segments where the scheme changes (Notice 733 §12.7 and Notice 732 §9.8: "do 2
  calculations ... add these together"), each segment is worked out under its own rules, and the boxes are summed.
- Annual Accounting changes the length of the period and adds interim payments; the boxes are filled in the
  normal way for the whole year (Notice 700/12 §4.3), so it needs no tax-moment rules of its own.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

from accnomos_ledger.events import LedgerEvent
from accnomos_ledger.vat import ON_RETURN, VatReturn, vat_side

Scheme = Literal["standard", "cash", "flat_rate"]
TurnoverMethod = Literal["basic", "cash"]
LimitedCost = Literal["auto", "yes", "no"]
CashExit = Literal["immediate", "six_months"]
Side = Literal["sales", "purchases"]

# --- thresholds (pence) -------------------------------------------------------------------------------------------
#: Notice 733 §3.1: join if taxable turnover (excluding VAT) in the next year will be £150,000 or less.
FRS_JOIN_LIMIT = 150_000_00
#: Notice 733 §3.5 / §12.2(a): leave if total income (including VAT, taxable and exempt) for the year is over £230,000.
FRS_LEAVE_LIMIT = 230_000_00
#: Notice 733 §3.5: HMRC may let you stay if the next 12 months will not exceed £191,500.
FRS_STAY_LIMIT = 191_500_00
#: Notice 731 §2.1 and Notice 732 §2.1: join if taxable supplies (excluding VAT) next year will be £1.35m or less.
CASH_JOIN_LIMIT = ANNUAL_JOIN_LIMIT = 1_350_000_00
#: Notice 731 §2.5 and Notice 732 §2.4: leave once taxable supplies for a year go over £1.6m.
CASH_LEAVE_LIMIT = ANNUAL_LEAVE_LIMIT = 1_600_000_00

# --- flat rate scheme ---------------------------------------------------------------------------------------------
#: Notice 733 §4.4: limited cost businesses use 16.5% from 1 April 2017.
LIMITED_COST_RATE = Decimal("16.5")
LIMITED_COST_FROM = date(2017, 4, 1)
#: Notice 733 §4.4: relevant goods under 2% of flat rate turnover, or over 2% but under £1,000 a year (pro rata).
LIMITED_COST_SHARE = Decimal("0.02")
LIMITED_COST_ANNUAL = 1_000_00
#: Notice 733 §15.2: VAT on a single purchase of capital expenditure goods of £2,000 or more including VAT is claimed.
CAPITAL_GOODS_MIN_GROSS = 2_000_00
#: Notice 733 §4.7: 1% off the flat rate until the day before the first anniversary of VAT registration.
FIRST_YEAR_DISCOUNT = Decimal("1")

#: VAT flat rates by type of business, with the dates a rate starts (gov.uk/vat-flat-rate-scheme/how-much-you-pay,
#: read 28 Oct 2026). Each value is ((from, percent), ...) oldest first; `date.min` = before any change we hold.
FLAT_RATE_SECTORS: dict[str, tuple[tuple[date, Decimal], ...]] = {
    name: tuple((start, Decimal(pct)) for start, pct in history)
    for name, history in {
        "Accountancy or book-keeping": [(date.min, "14.5")],
        "Advertising": [(date.min, "11")],
        "Agricultural services": [(date.min, "11")],
        "Any other activity not listed elsewhere": [(date.min, "12")],
        "Architect, civil and structural engineer or surveyor": [(date.min, "14.5")],
        "Boarding or care of animals": [(date.min, "12")],
        "Business services not listed elsewhere": [(date.min, "12")],
        "Catering services including restaurants and takeaways": [
            (date.min, "12.5"),
            (date(2020, 7, 15), "4.5"),
            (date(2021, 10, 1), "8.5"),
            (date(2022, 4, 1), "12.5"),
        ],
        "Computer and IT consultancy or data processing": [(date.min, "14.5")],
        "Computer repair services": [(date.min, "10.5")],
        "Entertainment or journalism": [(date.min, "12.5")],
        "Estate agency or property management services": [(date.min, "12")],
        "Farming or agriculture not listed elsewhere": [(date.min, "6.5")],
        "Film, radio, television or video production": [(date.min, "13")],
        "Financial services": [(date.min, "13.5")],
        "Forestry or fishing": [(date.min, "10.5")],
        "General building or construction services": [(date.min, "9.5")],
        "Hairdressing or other beauty treatment services": [(date.min, "13")],
        "Hiring or renting goods": [(date.min, "9.5")],
        "Hotel or accommodation": [
            (date.min, "10.5"),
            (date(2020, 7, 15), "0"),
            (date(2021, 10, 1), "5.5"),
            (date(2022, 4, 1), "10.5"),
        ],
        "Investigation or security": [(date.min, "12")],
        "Labour-only building or construction services": [(date.min, "14.5")],
        "Laundry or dry-cleaning services": [(date.min, "12")],
        "Lawyer or legal services": [(date.min, "14.5")],
        "Library, archive, museum or other cultural activity": [(date.min, "9.5")],
        "Management consultancy": [(date.min, "14")],
        "Manufacturing fabricated metal products": [(date.min, "10.5")],
        "Manufacturing food": [(date.min, "9")],
        "Manufacturing not listed elsewhere": [(date.min, "9.5")],
        "Manufacturing yarn, textiles or clothing": [(date.min, "9")],
        "Membership organisation": [(date.min, "8")],
        "Mining or quarrying": [(date.min, "10")],
        "Packaging": [(date.min, "9")],
        "Photography": [(date.min, "11")],
        "Post offices": [(date.min, "5")],
        "Printing": [(date.min, "8.5")],
        "Publishing": [(date.min, "11")],
        "Pubs": [(date.min, "6.5"), (date(2020, 7, 15), "1"), (date(2021, 10, 1), "4"), (date(2022, 4, 1), "6.5")],
        "Real estate activity not listed elsewhere": [(date.min, "14")],
        "Repairing personal or household goods": [(date.min, "10")],
        "Repairing vehicles": [(date.min, "8.5")],
        "Retailing food, confectionery, tobacco, newspapers or children's clothing": [(date.min, "4")],
        "Retailing pharmaceuticals, medical goods, cosmetics or toiletries": [(date.min, "8")],
        "Retailing not listed elsewhere": [(date.min, "7.5")],
        "Retailing vehicles or fuel": [(date.min, "6.5")],
        "Secretarial services": [(date.min, "13")],
        "Social work": [(date.min, "11")],
        "Sport or recreation": [(date.min, "8.5")],
        "Transport or storage, including couriers, freight, removals and taxis": [(date.min, "10")],
        "Travel agency": [(date.min, "10.5")],
        "Veterinary medicine": [(date.min, "11")],
        "Wholesaling agricultural products": [(date.min, "8")],
        "Wholesaling food": [(date.min, "7.5")],
        "Wholesaling not listed elsewhere": [(date.min, "8.5")],
    }.items()
}

#: Purchases on these accounts count as "relevant goods" for the limited cost test (Notice 733 §4.6) unless the
#: business says otherwise: goods used in the business. Services (rent, software, phone, insurance, fees,
#: advertising, postage, bank charges, travel), food and drink for you or staff, and vehicle costs and fuel are not.
DEFAULT_RELEVANT_GOODS = ("5000", "7200", "7500")
#: Vehicle costs and fuel count as relevant goods only in the transport sector (Notice 733 §4.6).
MOTOR_ACCOUNTS = ("7300",)
TRANSPORT_SECTOR = "Transport or storage, including couriers, freight, removals and taxis"


def sector_rate(sector: str, day: date) -> Decimal:
    """The flat rate for `sector` on `day`. Raises KeyError for a sector not in HMRC's list."""
    rate = FLAT_RATE_SECTORS[sector][0][1]
    for start, pct in FLAT_RATE_SECTORS[sector]:
        if start <= day:
            rate = pct
    return rate


def first_anniversary(registered_on: date) -> date:
    """The first anniversary of VAT registration (29 Feb registrations: 1 Mar the next year)."""
    try:
        return registered_on.replace(year=registered_on.year + 1)
    except ValueError:
        return date(registered_on.year + 1, 3, 1)


@dataclass(frozen=True)
class FlatRate:
    sector: str
    turnover_method: TurnoverMethod = "basic"  # Notice 733 §6.1: basic, or cash based (§9); retailer's is not offered
    limited_cost: LimitedCost = "auto"  # auto: the §4.4 test each period from the books; yes/no: the business decides


@dataclass(frozen=True)
class SchemeSpan:
    """One scheme from `start` to `end` (inclusive; None = still in use)."""

    start: date
    end: date | None
    scheme: Scheme
    flat_rate: FlatRate | None = None
    cash_exit: CashExit = "immediate"  # cash accounting only: Notice 731 §6.4's two ways to bring unpaid VAT to account

    @property
    def cash_basis(self) -> bool:
        """Sales are taxed when paid: cash accounting, or the flat rate scheme's cash based turnover method."""
        return self.scheme == "cash" or (self.flat_rate is not None and self.flat_rate.turnover_method == "cash")

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)

    def cash_basis_for(self, side: Side) -> bool:
        """Purchases are on cash basis only under cash accounting; the flat rate's cash method is about turnover."""
        return self.scheme == "cash" if side == "purchases" else self.cash_basis


STANDARD = SchemeSpan(date.min, None, "standard")


@dataclass(frozen=True)
class DocPayment:
    """Money that settled part of a document: a payment, a matched bank line or a credit applied to it."""

    doc_id: str
    date: date
    amount_pence: int


@dataclass
class SchemeBooks:
    """What the scheme engine needs from the books. `events` is every event, any date."""

    events: Sequence[LedgerEvent]
    payments: Sequence[DocPayment] = ()
    on_account: set[str] | None = None  # documents waiting for payment; None = every sale and purchase on account
    due: dict[str, date] = field(default_factory=dict)  # sales invoice due dates
    capital: set[str] = field(default_factory=set)  # purchases the business marked as capital expenditure goods
    relevant_goods_accounts: tuple[str, ...] | None = None  # account code prefixes; None = DEFAULT_RELEVANT_GOODS
    registered_on: date | None = None  # VAT registration date, for the flat rate's first-year 1% off


@dataclass(frozen=True)
class Moment:
    """A dated share of a document's net and VAT that reaches the return."""

    date: date
    side: Side
    net: int  # pence, signed
    vat: int
    event_id: str
    kind: Literal["invoice", "payment", "scheme_exit"] = "invoice"
    capital: bool = False  # flat rate: capital expenditure goods of £2,000 or more, dealt with outside the scheme
    relevant_share: Decimal = Decimal(0)  # share of the gross that is relevant goods (limited cost test)

    @property
    def gross(self) -> int:
        return self.net + self.vat


@dataclass
class FlatCalc:
    """One flat rate calculation: a stretch of a segment with one percentage (Notice 733 §4.12)."""

    start: date
    end: date
    percent: Decimal
    turnover_pence: int
    tax_pence: int
    first_year: bool


@dataclass
class Segment:
    """The part of a VAT period under one scheme."""

    start: date
    end: date
    scheme: Scheme
    cash_basis: bool
    sales_net: int = 0
    sales_vat: int = 0
    purchases_net: int = 0
    purchases_vat: int = 0
    payments: int = 0  # cash basis: payment moments counted here
    exit_net: int = 0  # unpaid amounts brought to account on leaving a cash basis (Notice 731 §6.4, 733 §9.6)
    exit_vat: int = 0
    # flat rate only
    sector: str | None = None
    turnover_pence: int = 0  # VAT inclusive flat rate turnover (box 6)
    relevant_goods_pence: int = 0
    limited_cost_cap_pence: int = 0  # the pro rata £1,000
    limited_cost: bool | None = None
    limited_cost_source: LimitedCost | None = None
    capital_net: int = 0  # boxes 7 and 4
    capital_vat: int = 0
    calcs: list[FlatCalc] = field(default_factory=list)

    @property
    def box1(self) -> int:
        return sum(c.tax_pence for c in self.calcs) if self.scheme == "flat_rate" else self.sales_vat

    @property
    def box4(self) -> int:
        return self.capital_vat if self.scheme == "flat_rate" else self.purchases_vat

    @property
    def box6(self) -> int:
        return self.turnover_pence if self.scheme == "flat_rate" else self.sales_net

    @property
    def box7(self) -> int:
        return self.capital_net if self.scheme == "flat_rate" else self.purchases_net


@dataclass
class SchemeReturn:
    ret: VatReturn
    segments: list[Segment]
    warnings: list[str] = field(default_factory=list)


# --- helpers ------------------------------------------------------------------------------------------------------


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _pounds(pence: int) -> Decimal:
    return (Decimal(pence) / 100).quantize(Decimal("0.01"))


def _whole_pounds(pence: int) -> int:
    return int((Decimal(pence) / 100).quantize(Decimal("1"), rounding=ROUND_DOWN))


def add_months(first: date, n: int) -> date:
    """The first day of the month `n` months after the month of `first`."""
    index = first.year * 12 + first.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def months_later(day: date, n: int) -> date:
    """The same day `n` months later (the month's last day when it is shorter)."""
    first = add_months(date(day.year, day.month, 1), n)
    last = add_months(first, 1) - timedelta(days=1)
    return first.replace(day=min(day.day, last.day))


def _whole_months(start: date, end: date) -> int | None:
    """Months from `start` (a 1st) to `end` (a month end), or None when the span is not whole months."""
    if start.day != 1 or (end + timedelta(days=1)).day != 1:
        return None
    return (end.year - start.year) * 12 + end.month - start.month + 1


def span_at(spans: Sequence[SchemeSpan], day: date) -> SchemeSpan:
    return next((s for s in spans if s.covers(day)), STANDARD)


def validate_spans(spans: Sequence[SchemeSpan]) -> list[SchemeSpan]:
    """Spans sorted by start; raises ValueError when two overlap or a flat rate span has no (known) sector."""
    out = sorted(spans, key=lambda s: s.start)
    for a, b in zip(out, out[1:], strict=False):
        if a.end is None or a.end >= b.start:
            raise ValueError(f"schemes from {a.start} and {b.start} overlap")
    for s in out:
        if s.end is not None and s.end < s.start:
            raise ValueError(f"the scheme from {s.start} ends before it starts")
        if s.scheme == "flat_rate":
            if s.flat_rate is None or s.flat_rate.sector not in FLAT_RATE_SECTORS:
                raise ValueError("a flat rate scheme needs one of HMRC's business types")
        elif s.flat_rate is not None:
            raise ValueError(f"only the flat rate scheme takes flat rate settings (the scheme from {s.start})")
    return out


def _cash_run_end(spans: Sequence[SchemeSpan], day: date, side: Side) -> tuple[date | None, SchemeSpan]:
    """(last day of the unbroken run of cash basis spans containing `day`, the last span of that run)."""
    cur = span_at(spans, day)
    while cur.end is not None:
        nxt = span_at(spans, cur.end + timedelta(days=1))
        if nxt is STANDARD or not nxt.cash_basis_for(side) or nxt.start != cur.end + timedelta(days=1):
            break
        cur = nxt
    return cur.end, cur


def _relevant_share(ev: LedgerEvent, prefixes: tuple[str, ...]) -> Decimal:
    """The share of a purchase's cost lines that are on relevant goods accounts."""
    cost = [ln for ln in ev.lines if ln.debit and ln.vat_code is not None and not ln.account.startswith("2200")]
    total = sum(ln.debit for ln in cost)
    if not total:
        return Decimal(0)
    relevant = sum(ln.debit for ln in cost if ln.account[:4] in prefixes)
    return Decimal(relevant) / Decimal(total)


# --- tax moments --------------------------------------------------------------------------------------------------


def tax_moments(books: SchemeBooks, spans: Sequence[SchemeSpan]) -> tuple[list[Moment], list[tuple[str, str]]]:
    """Every dated share of net and VAT, under the scheme in force on each document's date; and (event id, warning)
    for documents that need a word."""
    spans = validate_spans(spans)
    warnings: list[tuple[str, str]] = []
    reversed_ids = {e.reverses for e in books.events if e.kind == "reversal" and e.reverses}
    pays: dict[str, list[DocPayment]] = defaultdict(list)
    for p in sorted(books.payments, key=lambda p: p.date):
        pays[p.doc_id].append(p)
    prefixes = books.relevant_goods_accounts or DEFAULT_RELEVANT_GOODS
    if any(s.flat_rate and s.flat_rate.sector == TRANSPORT_SECTOR for s in spans):
        prefixes = (*prefixes, *MOTOR_ACCOUNTS)

    def on_return(ev: LedgerEvent) -> bool:
        return bool({ln.vat_code for ln in ev.lines if ln.vat_code is not None} & ON_RETURN)

    def cash_doc(ev: LedgerEvent) -> bool:
        """Sales and purchases taxed when paid (not undone; not excluded by Notice 731 §2.7)."""
        if ev.kind not in ("sale", "purchase") or ev.id in reversed_ids or ev.net is None or not on_return(ev):
            return False
        side: Side = "sales" if ev.kind == "sale" else "purchases"
        span = span_at(spans, ev.date)
        if not span.cash_basis_for(side):
            return False
        due = books.due.get(ev.id)
        if span.scheme == "cash" and due is not None and due > months_later(ev.date, 6):
            warnings.append(
                (
                    ev.id,
                    f"event {ev.id}: payment is not due within 6 months of the invoice, so it is outside cash "
                    "accounting (Notice 731 §2.7) and counts on its invoice date",
                )
            )
            return False
        return True

    cash_ids = {e.id for e in books.events if cash_doc(e)}
    folded: dict[str, list[LedgerEvent]] = defaultdict(list)  # cash document -> its credit notes
    for e in books.events:
        if e.is_credit_note and e.credits in cash_ids and e.id not in reversed_ids and e.net is not None:
            folded[e.credits].append(e)  # type: ignore[index]
    folded_ids = {cn.id for cns in folded.values() for cn in cns}

    moments: list[Moment] = []
    for ev in books.events:
        if ev.kind not in {"sale", "purchase", "reversal"} or ev.id in folded_ids:
            continue
        if ev.net is None:
            warnings.append((ev.id, f"event {ev.id}: no net amount recorded; excluded"))
            continue
        if not on_return(ev):
            continue
        if ev.kind == "reversal" and ev.reverses and (ev.reverses in cash_ids or ev.reverses in folded_ids):
            continue  # undoing a cash basis document (or a credit note folded into one): neither ever counted
        side, sign = vat_side(ev) or ("purchases", -1)
        capital = side == "purchases" and ev.id in books.capital and (ev.net + (ev.vat or 0)) >= CAPITAL_GOODS_MIN_GROSS
        share = _relevant_share(ev, prefixes) if side == "purchases" and not capital else Decimal(0)
        if ev.id not in cash_ids:
            moments.append(Moment(ev.date, side, sign * ev.net, sign * (ev.vat or 0), ev.id, "invoice", capital, share))
            continue
        net, vat = ev.net, ev.vat or 0
        for cn in folded[ev.id]:
            net -= cn.net or 0
            vat -= cn.vat or 0
        gross = net + vat
        if gross <= 0:
            continue
        paid = pays.get(ev.id, [])
        if books.on_account is not None and ev.id not in books.on_account:
            paid = [DocPayment(ev.id, ev.date, gross)]  # paid at the time
        run_end, last = _cash_run_end(spans, ev.date, side)
        cutoff = run_end
        if run_end is not None and last.scheme == "cash" and last.cash_exit == "six_months":
            cutoff = add_months(run_end + timedelta(days=1), 6) - timedelta(days=1)
        cum = done_net = done_vat = 0
        for p in paid:
            if cutoff is not None and p.date > cutoff:
                break
            cum = min(gross, cum + p.amount_pence)
            to_net = _round(Decimal(net) * cum / gross)
            to_vat = _round(Decimal(vat) * cum / gross)
            if (to_net, to_vat) != (done_net, done_vat):
                moments.append(
                    Moment(p.date, side, to_net - done_net, to_vat - done_vat, ev.id, "payment", capital, share)
                )
            done_net, done_vat = to_net, to_vat
            if cum >= gross:
                break
        if cutoff is not None and cum < gross:
            moments.append(Moment(cutoff, side, net - done_net, vat - done_vat, ev.id, "scheme_exit", capital, share))
    return moments, warnings


# --- the return ---------------------------------------------------------------------------------------------------


def segments_of(spans: Sequence[SchemeSpan], start: date, end: date) -> list[tuple[date, date, SchemeSpan]]:
    """[start, end] cut where the scheme changes; gaps between spans are standard accounting."""
    cuts = {start}
    for s in spans:
        if start < s.start <= end:
            cuts.add(s.start)
        if s.end is not None and start <= s.end < end:
            cuts.add(s.end + timedelta(days=1))
    days = sorted(cuts)
    out = []
    for i, a in enumerate(days):
        b = days[i + 1] - timedelta(days=1) if i + 1 < len(days) else end
        out.append((a, b, span_at(spans, a)))
    return out


def limited_cost_cap(start: date, end: date) -> int:
    """The pro rata £1,000 for a stretch: twelfths for whole months (£250 a quarter, £83 for a month, £166 for
    two, as Notice 733 §4.5 rounds), else by days of a 365-day year; truncated to whole pounds."""
    months = _whole_months(start, end)
    if months is not None:
        pounds = Decimal(LIMITED_COST_ANNUAL) * months / 12 / 100
    else:
        pounds = Decimal(LIMITED_COST_ANNUAL) * ((end - start).days + 1) / 365 / 100
    return int(pounds.quantize(Decimal(1), rounding=ROUND_DOWN)) * 100


def is_limited_cost(relevant_pence: int, turnover_pence: int, cap_pence: int) -> bool:
    """Notice 733 §4.4: relevant goods less than 2% of flat rate turnover, or more than 2% but less than the cap."""
    two_pct = Decimal(turnover_pence) * LIMITED_COST_SHARE
    return relevant_pence < two_pct or (relevant_pence > two_pct and relevant_pence < cap_pence)


def _flat_segment(seg: Segment, fr: FlatRate, moments: list[Moment], registered_on: date | None) -> None:
    sales = [m for m in moments if m.side == "sales"]
    purchases = [m for m in moments if m.side == "purchases"]
    seg.sector = fr.sector
    seg.turnover_pence = sum(m.gross for m in sales)
    seg.capital_net = sum(m.net for m in purchases if m.capital)
    seg.capital_vat = sum(m.vat for m in purchases if m.capital)
    seg.relevant_goods_pence = _round(sum((m.relevant_share * m.gross for m in purchases if not m.capital), Decimal(0)))
    seg.limited_cost_cap_pence = limited_cost_cap(seg.start, seg.end)
    seg.limited_cost_source = fr.limited_cost
    if seg.end < LIMITED_COST_FROM:
        seg.limited_cost = False
    elif fr.limited_cost == "auto":
        seg.limited_cost = is_limited_cost(seg.relevant_goods_pence, seg.turnover_pence, seg.limited_cost_cap_pence)
    else:
        seg.limited_cost = fr.limited_cost == "yes"
    cuts = {seg.start}
    for start, _ in FLAT_RATE_SECTORS[fr.sector]:
        if seg.start < start <= seg.end:
            cuts.add(start)
    anniversary = first_anniversary(registered_on) if registered_on else None
    if anniversary and seg.start < anniversary <= seg.end:
        cuts.add(anniversary)
    if seg.start < LIMITED_COST_FROM <= seg.end:
        cuts.add(LIMITED_COST_FROM)
    days = sorted(cuts)
    for i, a in enumerate(days):
        b = days[i + 1] - timedelta(days=1) if i + 1 < len(days) else seg.end
        pct = LIMITED_COST_RATE if seg.limited_cost and a >= LIMITED_COST_FROM else sector_rate(fr.sector, a)
        first_year = bool(registered_on and anniversary and registered_on <= a < anniversary)
        if first_year:
            pct = max(Decimal(0), pct - FIRST_YEAR_DISCOUNT)
        turnover = sum(m.gross for m in sales if a <= m.date <= b)
        seg.calcs.append(FlatCalc(a, b, pct, turnover, _round(Decimal(turnover) * pct / 100), first_year))


def compute_scheme_return(
    books: SchemeBooks, spans: Sequence[SchemeSpan], period_key: str, start: date, end: date
) -> SchemeReturn:
    """The 9 boxes for [start, end] under the schemes in `spans` (none: the same as `compute_vat_return`)."""
    spans = validate_spans(spans)
    moments, warnings = tax_moments(books, spans)
    ret = VatReturn(period_key=period_key, start=start, end=end)
    dated = {e.id for e in books.events if start <= e.date <= end}
    ret.warnings = [w for eid, w in warnings if eid in dated and eid not in {m.event_id for m in moments}]
    segments: list[Segment] = []
    ids: list[str] = []
    for a, b, span in segments_of(spans, start, end):
        seg = Segment(a, b, span.scheme, span.cash_basis)
        here = [m for m in moments if a <= m.date <= b]
        for m in here:
            if m.kind == "payment":
                seg.payments += 1
            if m.kind == "scheme_exit":
                seg.exit_net += m.net
                seg.exit_vat += m.vat
            if m.side == "sales":
                seg.sales_net += m.net
                seg.sales_vat += m.vat
            else:
                seg.purchases_net += m.net
                seg.purchases_vat += m.vat
            if m.event_id not in ids:
                ids.append(m.event_id)
        if span.scheme == "flat_rate" and span.flat_rate is not None:
            _flat_segment(seg, span.flat_rate, here, books.registered_on)
        segments.append(seg)
    ret.event_ids = ids
    ret.vat_due_sales = _pounds(sum(s.box1 for s in segments))
    ret.vat_reclaimed = _pounds(sum(s.box4 for s in segments))
    ret.total_sales_ex_vat = _whole_pounds(sum(s.box6 for s in segments))
    ret.total_purchases_ex_vat = _whole_pounds(sum(s.box7 for s in segments))
    out = SchemeReturn(ret, segments)
    out.warnings = [w for eid, w in warnings if eid in ids]
    if any(s.scheme == "flat_rate" for s in segments) and any(s.scheme != "flat_rate" for s in segments):
        out.warnings.append("The scheme changes during this period: the boxes add up one calculation per scheme.")
    return out


# --- annual accounting --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AnnualAccounting:
    """Notice 732: one return a year with interim payments. `start` is the first day of the first annual period
    (the first day of the VAT period in which you joined, §3.2); `first_year_end` its last day when you asked for
    a year end that suits you (no period over 12 months, §3.4); `end` the last day on the scheme, if you left."""

    start: date
    first_year_end: date | None = None
    instalments: Literal["monthly", "quarterly"] = "monthly"
    basis_pence: int | None = None  # last year's net VAT (or HMRC's estimate for a new business), from its letter
    end: date | None = None


@dataclass(frozen=True)
class Instalment:
    number: int
    due: date
    amount_pence: int


def annual_periods(aas: AnnualAccounting, until: date) -> list[tuple[date, date]]:
    """Annual periods from `aas.start` up to the one containing `until` (or the scheme's end), oldest first."""
    first_end = aas.first_year_end or add_months(aas.start, 12) - timedelta(days=1)
    if first_end < aas.start or first_end > add_months(aas.start, 12) - timedelta(days=1):
        raise ValueError("the first annual period must end within 12 months of its start (Notice 732 §3.4)")
    out = [(aas.start, first_end)]
    while out[-1][1] < until and (aas.end is None or out[-1][1] < aas.end):
        s = out[-1][1] + timedelta(days=1)
        out.append((s, add_months(s, 12) - timedelta(days=1)))
    if aas.end is not None:
        out = [(s, min(e, aas.end)) for s, e in out if s <= aas.end]
    return out


def annual_period_containing(aas: AnnualAccounting, day: date) -> tuple[date, date] | None:
    if day < aas.start or (aas.end is not None and day > aas.end):
        return None
    return next((p for p in annual_periods(aas, day) if p[0] <= day <= p[1]), None)


def period_months(start: date, end: date) -> int:
    """Whole months in a period that starts on a 1st and ends on a month end (part months count as one)."""
    return (end.year - start.year) * 12 + end.month - start.month + 1


def annual_return_due(start: date, end: date) -> date:
    """Return and balancing payment: 2 months after the period ends, or 1 month for a period under 4 months
    (Notice 732 §3.6). Periods end on a month end, so this is the end of the month 2 (or 1) months later."""
    months = 1 if period_months(start, end) < 4 else 2
    return add_months(date(end.year, end.month, 1), months + 1) - timedelta(days=1)


def instalment_amount(basis_pence: int, pattern: Literal["monthly", "quarterly"]) -> int:
    """10% (monthly) or 25% (quarterly) of the basis, rounded down to the nearest £5 (VATAAS4100)."""
    share = Decimal("0.10") if pattern == "monthly" else Decimal("0.25")
    pounds = Decimal(max(0, basis_pence)) * share / 100
    return int((pounds / 5).quantize(Decimal(1), rounding=ROUND_DOWN)) * 5 * 100


def instalment_schedule(
    start: date, end: date, basis_pence: int | None, pattern: Literal["monthly", "quarterly"]
) -> list[Instalment]:
    """Interim payments due at the end of months 4-12 (monthly) or 4, 7 and 10 (quarterly) of the period; none for a
    period under 4 months, or with no basis yet (HMRC's letter gives it) (Notice 732 §4.1-4.5)."""
    months = period_months(start, end)
    if basis_pence is None or months < 4:
        return []
    amount = instalment_amount(basis_pence, pattern)
    if not amount:
        return []  # a repayment trader makes no interim payments (Notice 732 §7.1)
    wanted = range(4, 13) if pattern == "monthly" else (4, 7, 10)
    due = [add_months(start, m) - timedelta(days=1) for m in wanted if m <= months]
    return [Instalment(i + 1, d, amount) for i, d in enumerate(due)]


def balancing_payment(box5_signed_pence: int, instalments: Iterable[Instalment]) -> int:
    """Box 5 (VAT owed for the year, signed: negative = HMRC owes you) minus the interim payments made (Notice 732
    §6.2). Positive: still to pay with the return; negative: HMRC refunds it."""
    return box5_signed_pence - sum(i.amount_pence for i in instalments)
