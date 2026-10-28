"""Property-based tests (Hypothesis) for the runtime's money maths, one function at a time.

Inputs are the real request and domain models (LineIn, InvoiceDraft, ExtractedDoc, Proposal, PaymentRecord,
BankLine, CreditUse) and the properties are checked through the real functions: price_lines, sale_event,
credit_note_event, draft_journal, build_event, reversal_of, the repairs, settle, aged, and the VAT period maths.
The books-wide properties (random sequences of approvals, payments, credit notes and undos) are in
tests/test_properties_books.py.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from accnomos_ledger.bank import BankLine
from accnomos_ledger.events import LedgerEvent
from accnomos_ledger.vat import compute_vat_return
from app.approve import build_event, reversal_of
from app.audit_view import months_between
from app.bank_reconcile import _split_gross
from app.books import LONDON
from app.checks import p
from app.contacts import Ledger, aged, documents, merge_ledger
from app.credit_notes import CreditNote, credit_note_event
from app.deadlines import (
    add_months,
    filing_deadline,
    period_containing,
    period_from_id,
    period_id,
    previous_period,
    recent_periods,
    stagger_of,
)
from app.invoicing import (
    RATES,
    InvoiceDraft,
    InvoiceProfile,
    LineIn,
    build_invoice,
    price_lines,
    sale_event,
    send_problems,
)
from app.journal import DEBTORS, VAT_CONTROL, draft_journal, is_balanced
from app.repair import repair_vat_inclusive_totals
from app.schemas import CATEGORIES, ExtractedDoc, ExtractedLine, Proposal
from app.settlement import Allocation, CreditUse, PaymentRecord
from app.vat_cycle import VatCycle

USER = "sam@sambuilds.co.uk"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
PROFILE = InvoiceProfile(name="Sam Builds Ltd", address="1 High Street, Leeds", vrn="GB 123 4567 89")


def half_up(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def balances(events: list[LedgerEvent]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for e in events:
        for ln in e.lines:
            out[ln.account] += ln.debit - ln.credit
    return dict(out)


# --------------------------------------------------------------------------- #
# Invoices: per-line VAT, mixed rates, the sale in the ledger
# --------------------------------------------------------------------------- #

quantities = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000"), places=3)
line_in = st.builds(
    LineIn,
    description=st.just("Work"),
    quantity=quantities,
    unit_price_pence=st.integers(1, 2_000_000),
    vat_code=st.sampled_from(list(RATES)),
)


@given(st.lists(line_in, min_size=1, max_size=12))
def test_mixed_rate_invoices_sum_line_vat_exactly(lines: list[LineIn]):
    priced, summary, net, vat = price_lines(lines)
    for src, ln in zip(lines, priced, strict=True):
        assert ln.net_pence == half_up(src.quantity * src.unit_price_pence)  # rounded half up per line
        assert ln.vat_pence == half_up(Decimal(ln.net_pence) * RATES[src.vat_code] / 100)
        exact = Decimal(ln.net_pence) * ln.vat_rate / 100
        assert abs(ln.vat_pence - exact) <= Decimal("0.5")
    # Totals are the sums of the lines, exactly; the VAT summary splits the same pence by code
    assert net == sum(ln.net_pence for ln in priced) and vat == sum(ln.vat_pence for ln in priced)
    assert sum(r.net_pence for r in summary) == net and sum(r.vat_pence for r in summary) == vat
    assert len({r.vat_code for r in summary}) == len(summary)
    for r in summary:
        assert r.vat_pence == sum(ln.vat_pence for ln in priced if ln.vat_code == r.vat_code)
    # Rounding per line is never more than half a penny a line away from the exact VAT on the whole invoice
    exact_total = sum(Decimal(ln.net_pence) * ln.vat_rate / 100 for ln in priced)
    assert abs(vat - exact_total) <= Decimal(len(priced)) / 2


@given(st.lists(line_in, min_size=1, max_size=8), st.dates(min_value=date(2024, 1, 1), max_value=date(2028, 12, 31)))
def test_a_sent_invoice_posts_a_balanced_sale_that_reaches_the_right_boxes(lines: list[LineIn], day: date):
    draft = InvoiceDraft.model_validate({"customer": {"name": "Acme Kitchens Ltd"}, "issue_date": day, "lines": lines})
    inv = build_invoice("INV-0001", draft, PROFILE, USER)
    assume(not send_problems(inv, PROFILE, "accounts@acme.example"))  # what Send refuses never posts (a £0.00 total)
    ev = sale_event(inv, USER, [])
    assert balances([ev])[DEBTORS] == inv.total_pence == inv.net_pence + inv.vat_pence
    assert -balances([ev]).get(VAT_CONTROL, 0) == inv.vat_pence
    ret = compute_vat_return([ev], "x", day, day)
    on_return = sum(r.net_pence for r in inv.vat_summary if r.vat_code != "O")
    if on_return or inv.vat_pence:
        assert ret.vat_due_sales == Decimal(inv.vat_pence) / 100
        assert ret.total_sales_ex_vat == on_return // 100  # whole pounds, pence dropped
    assert ret.net_vat_due == ret.vat_due_sales

    # Crediting the whole invoice puts Debtors, Sales, VAT control and every box back to nothing
    cn = CreditNote(
        number="CN-0001",
        invoice=inv.number,
        invoice_event_id=ev.id,
        customer=inv.customer,
        issue_date=day,
        lines=inv.lines,
        source_lines=list(range(len(inv.lines))),
        vat_summary=inv.vat_summary,
        net_pence=inv.net_pence,
        vat_pence=inv.vat_pence,
        total_pence=inv.total_pence,
        reason="cancelled",
        created_by=USER,
    )
    both = [ev, credit_note_event(cn, USER)]
    assert set(balances(both).values()) == {0}
    ret = compute_vat_return(both, "x", day, day)
    assert ret.vat_due_sales == ret.net_vat_due == 0 and ret.total_sales_ex_vat == 0


# --------------------------------------------------------------------------- #
# Journals from extracted documents: always balanced, undo returns every account to zero
# --------------------------------------------------------------------------- #

VRNS = st.sampled_from(["GB 123 4567 89", "GB123456789", None, "nonsense"])
RATE = st.sampled_from([20.0, 5.0, 0.0, None])


@st.composite
def extracted(draw: st.DrawFn, doc_type: str | None = None, consistent: bool | None = None) -> ExtractedDoc:
    lines: list[ExtractedLine] = []
    for _ in range(draw(st.integers(0, 6))):
        net = draw(st.integers(0, 500_000))
        rate = draw(RATE)
        vat = round(net * (rate or 0) / 100)
        qty = draw(st.integers(1, 5))
        lines.append(
            ExtractedLine(
                description="item", qty=qty, unit_price=net / 100 / qty, net=net / 100, vat_rate=rate, vat=vat / 100
            )
        )
    net = sum(p(ln.net) for ln in lines) if lines else draw(st.integers(1, 500_000))
    vat = sum(p(ln.vat) for ln in lines) if lines else draw(st.integers(0, 100_000))
    if consistent is False or (consistent is None and draw(st.booleans())):
        net += draw(st.integers(-3, 3))  # printed totals a few pence out from the lines
    net = max(net, 0)
    gross = net + vat + (0 if consistent is not False else draw(st.integers(-2, 2)))
    kind = doc_type or draw(st.sampled_from(["receipt", "purchase_invoice", "sales_invoice", "credit_note"]))
    sign = -1 if kind == "credit_note" and draw(st.booleans()) else 1  # credit notes are often printed negative
    return ExtractedDoc(
        doc_type=kind,  # type: ignore[arg-type]
        supplier_name="Howdens Joinery",
        supplier_vat_number=draw(VRNS),
        customer_name="Sam Builds Ltd",
        invoice_number="H-77",
        date=draw(st.dates(min_value=date(2024, 1, 1), max_value=date(2028, 12, 31))).isoformat(),
        currency="GBP",
        lines=lines,
        net_total=sign * net / 100,
        vat_total=sign * vat / 100,
        gross_total=sign * max(gross, 0) / 100,
        payment_method=draw(
            st.sampled_from(["card", "cash", "bank_transfer", "direct_debit", "cheque", "unknown", None])
        ),
        card_last4=None,
        category_guess=draw(st.sampled_from(CATEGORIES)),
        confidence=0.9,
    )


def proposal(doc: ExtractedDoc) -> Proposal:
    return Proposal(
        id="a" * 32,
        doc_sha256="b" * 64,
        extracted=doc,
        checks=[],
        status="proposed",
        reasons=[],
        suggested_filename="x.pdf",
        journal_draft=draft_journal(doc),
        model="stub",
        elapsed_s=0.0,
        created_at=NOW,
    )


@given(extracted())
def test_every_draft_journal_balances_in_whole_pence_and_posts(doc: ExtractedDoc):
    journal = draft_journal(doc)
    assert is_balanced(journal)
    assert all(type(j.debit_pence) is int and type(j.credit_pence) is int for j in journal)
    assert all(j.debit_pence >= 0 and j.credit_pence >= 0 for j in journal)
    assume(sum(1 for j in journal if j.debit_pence or j.credit_pence) >= 2)
    ev = build_event(proposal(doc), journal, USER)
    assert ev.net is not None and ev.vat is not None and ev.net + ev.vat == sum(ln.debit for ln in ev.lines)
    # The settlement leg moves the whole document: the printed gross when the totals add up
    totals_hold = p(doc.net_total) + p(doc.vat_total) == p(doc.gross_total)
    lines_hold = not doc.lines or abs(sum(p(ln.net) for ln in doc.lines) - p(doc.net_total)) <= 1
    if doc.doc_type != "sales_invoice" and totals_hold and lines_hold:
        assert sum(ln.debit for ln in ev.lines) in {abs(p(doc.gross_total)) + d for d in range(-1, 2)}


@given(extracted())
def test_posting_then_undoing_returns_every_account_and_box_to_zero(doc: ExtractedDoc):
    journal = draft_journal(doc)
    assume(sum(1 for j in journal if j.debit_pence or j.credit_pence) >= 2)
    ev = build_event(proposal(doc), journal, USER)
    undo = reversal_of(ev, USER)
    assert set(balances([ev, undo]).values()) == {0}
    ret = compute_vat_return([ev, undo], "x", ev.date, ev.date)
    assert ret.vat_due_sales == ret.vat_reclaimed == ret.net_vat_due == 0
    assert ret.total_sales_ex_vat == ret.total_purchases_ex_vat == 0
    # Undone in a later (open) period: the original period keeps it, the later one takes it back off
    later = reversal_of(ev, USER, on=ev.date + timedelta(days=95))
    first = compute_vat_return([ev, later], "x", ev.date, ev.date)
    second = compute_vat_return([ev, later], "y", later.date, later.date)
    assert first.vat_due_sales + second.vat_due_sales == 0
    assert first.vat_reclaimed + second.vat_reclaimed == 0


@given(extracted(doc_type="credit_note"))
def test_a_supplier_credit_note_reduces_purchases_by_its_own_figures(doc: ExtractedDoc):
    journal = draft_journal(doc)
    assume(sum(1 for j in journal if j.debit_pence or j.credit_pence) >= 2)
    ev = build_event(proposal(doc), journal, USER)
    assert ev.kind == "reversal" and ev.is_credit_note
    ret = compute_vat_return([ev], "x", ev.date, ev.date)
    assert ret.vat_reclaimed == -Decimal(ev.vat or 0) / 100 and ret.vat_due_sales == 0


# --------------------------------------------------------------------------- #
# VAT-inclusive / exclusive repairs round-trip within a penny
# --------------------------------------------------------------------------- #


@given(st.integers(100, 10_000_000), st.sampled_from([20, 5]), st.integers(1, 4))
def test_a_vat_inclusive_total_read_as_the_net_is_repaired_to_within_a_penny(net: int, rate: int, n: int):
    vat = round(net * rate / 100)
    gross = net + vat
    per = net // n
    nets = [per] * (n - 1) + [net - per * (n - 1)]
    lines = [
        ExtractedLine(
            description="x", qty=1, unit_price=x / 100, net=x / 100, vat_rate=rate, vat=round(x * rate / 100) / 100
        )
        for x in nets
    ]

    def doc(net_p: int, vat_p: int, gross_p: int) -> ExtractedDoc:
        return ExtractedDoc(
            doc_type="receipt",
            supplier_name="Screwfix",
            supplier_vat_number="GB123456789",
            customer_name=None,
            invoice_number=None,
            date="2026-09-01",
            currency="GBP",
            lines=lines,
            net_total=net_p / 100,
            vat_total=vat_p / 100,
            gross_total=gross_p / 100,
            payment_method="card",
            card_last4=None,
            category_guess="Materials",
            confidence=0.9,
        )

    # 1. the VAT-inclusive total copied into net
    d = doc(gross, vat, gross)
    assert repair_vat_inclusive_totals(d) is not None
    assert abs(p(d.net_total) - net) <= 1 and p(d.net_total) + p(d.vat_total) == p(d.gross_total) == gross
    # 2. VAT added on top of a VAT-inclusive total: net + VAT == "gross" but VAT is rate x the inclusive figure
    inclusive = gross
    vat_share = round(inclusive * rate / (100 + rate))
    on_top = round(inclusive * rate / 100)
    assume(abs(on_top - vat_share) > 2 + n)  # otherwise the reading is consistent and nothing needs repair
    d = doc(inclusive, vat_share, inclusive + vat_share)
    assert repair_vat_inclusive_totals(d) is not None
    assert p(d.gross_total) == inclusive and abs(p(d.net_total) - net) <= 1
    assert p(d.net_total) + p(d.vat_total) == p(d.gross_total)
    # 3. A correct reading is left alone
    d = doc(net, vat, gross)
    assert repair_vat_inclusive_totals(d) is None and (p(d.net_total), p(d.vat_total)) == (net, vat)


@given(st.integers(-10_000_000, 10_000_000), st.sampled_from(["S", "R", "Z", "E", None]))
def test_splitting_a_bank_line_gross_into_net_and_vat_loses_no_pence(gross: int, code: str | None):
    net, vat = _split_gross(gross, code)
    assert p(net) + p(vat) == abs(gross)
    rate = {"S": 20, "R": 5}.get(code or "", 0)
    assert abs(p(vat) - Decimal(abs(gross)) * rate / (100 + rate)) <= 1
    # ...and the net it gives back, at that rate, comes back to the same VAT within a penny
    assert abs(round(p(net) * rate / 100) - p(vat)) <= 1


# --------------------------------------------------------------------------- #
# Settlement: part payments, overpayments, credit notes, matched bank lines
# --------------------------------------------------------------------------- #


@st.composite
def money_case(draw: st.DrawFn) -> Ledger:
    """Invoices to two customers, then payments (recorded or by bank line), credit notes and credit uses."""
    events: list[LedgerEvent] = []
    names = ["Acme Kitchens Ltd", "Bloggs Builders"]
    base = date(2026, 9, 1)
    who: dict[str, str] = {}
    for i in range(draw(st.integers(1, 5))):
        lines = [LineIn(description="w", quantity=Decimal(1), unit_price_pence=draw(st.integers(100, 100_000)))]
        name = draw(st.sampled_from(names))
        day = base + timedelta(days=draw(st.integers(0, 20)))
        draft = InvoiceDraft.model_validate({"customer": {"name": name}, "issue_date": day, "lines": lines})
        ev = sale_event(build_invoice(f"INV-{i:04d}", draft, PROFILE, USER), USER, [])
        events.append(ev)
        who[ev.id] = name
    invoices = list(events)
    records: list[PaymentRecord] = []
    bank_lines: list[BankLine] = []
    uses: list[CreditUse] = []
    for j in range(draw(st.integers(0, 8))):
        target = draw(st.sampled_from(invoices))
        gross = target.lines[0].debit
        day = target.date + timedelta(days=draw(st.integers(0, 40)))
        what = draw(st.sampled_from(["part", "exact", "over", "bank", "credit_note", "apply"]))
        if what in ("part", "exact", "over"):
            amount = {
                "part": draw(st.integers(1, gross)),
                "exact": gross,
                "over": gross + draw(st.integers(1, 50_000)),
            }[what]
            records.append(
                PaymentRecord(
                    id=f"p{j}",
                    side="sale",
                    date=day,
                    amount_pence=amount,
                    counterparty=who[target.id],
                    allocations=[Allocation(event_id=target.id, amount_pence=min(amount, gross))],
                    event_id=f"pe{j}",
                    created_by=USER,
                    created_at=NOW,
                )
            )
        elif what == "bank":
            bank_lines.append(
                BankLine(
                    id=f"{j:016x}",
                    date=day,
                    amount_pence=draw(st.sampled_from([gross, gross - 1, gross + 1, gross // 2 or 1, gross * 2])),
                    description="FASTER PAYMENT",
                    source_file="x.csv",
                    status="matched",
                    matched_event_ids=[target.id],
                )
            )
        elif what == "credit_note":
            amount = draw(st.integers(1, gross * 2))
            lines = [LineIn(description="cn", quantity=Decimal(1), unit_price_pence=amount, vat_code="Z")]
            priced, summary, net, vat = price_lines(lines)
            cn = CreditNote(
                number=f"CN-{j:04d}",
                invoice="x",
                invoice_event_id=target.id,
                customer={"name": who[target.id]},  # type: ignore[arg-type]
                issue_date=day,
                lines=priced,
                vat_summary=summary,
                net_pence=net,
                vat_pence=vat,
                total_pence=net + vat,
                reason="r",
                created_by=USER,
            )
            events.append(credit_note_event(cn, USER))
        elif records:
            source = draw(st.sampled_from(records))
            uses.append(
                CreditUse(
                    id=f"u{j}",
                    kind=draw(st.sampled_from(["apply", "refund"])),
                    side="sale",
                    date=day,
                    amount_pence=draw(st.integers(1, 100_000)),
                    credit=f"payment:{source.id}",
                    doc_event_id=target.id,
                    created_by=USER,
                    created_at=NOW,
                )
            )
    return Ledger(events=events, bank_lines=bank_lines, records=records, uses=uses)


@given(money_case())
def test_no_invoice_is_ever_settled_beyond_its_total_and_no_money_goes_missing(ledger: Ledger):
    s = ledger.settlement()
    for eid, gross in s.gross.items():
        settled = s.paid.get(eid, 0) + s.credited.get(eid, 0)
        assert settled >= 0
        # A matched bank line within a penny a document pays it in full, so a penny over is the most there can be
        assert settled <= gross + 1, (eid, gross, settled)
        assert s.outstanding(eid) >= -1
        expected = "open" if settled <= 0 else "part_paid" if s.outstanding(eid) > 0 else None
        assert s.status(eid) == expected if expected else s.status(eid) in ("paid", "overpaid")
    # Every recorded payment is accounted for: what it paid plus what is left as a credit (or later used)
    for pay in s.payments:
        allocated = sum(a.amount_pence for a in pay.allocations)
        used = s.used.get(f"payment:{pay.id}", 0)
        if pay.source == "recorded":
            assert allocated + pay.unallocated_pence + used == pay.amount_pence
        else:  # a matched bank line: all of it, give or take the matcher's penny per document
            assert abs(allocated + pay.unallocated_pence + used - pay.amount_pence) <= len(pay.allocations)
    # Credits never go negative, and uses never take more than their credit had
    assert all(c.amount_pence > 0 for c in s.credits)
    for u in s.uses:
        assert 0 <= u.applied_pence <= u.amount_pence


@given(money_case(), st.dates(min_value=date(2026, 9, 1), max_value=date(2027, 6, 30)))
def test_aged_debtor_buckets_add_up_to_what_is_owed(ledger: Ledger, as_of: date):
    contacts = merge_ledger([], ledger, at=NOW)
    table = aged(contacts, ledger, as_of).debtors
    assert sum(table.buckets.values()) == table.total_pence == sum(r.total_pence for r in table.rows)
    for row in table.rows:
        assert sum(row.buckets.values()) == row.total_pence == sum(d.amount_pence for d in row.documents)
    s = ledger.settlement()
    owed = sum(max(0, s.outstanding(d.event.id)) for d in documents(ledger) if d.event.date <= as_of and not d.undo)
    assert table.total_pence == owed
    # With only recorded payments and credit notes (nothing matched straight from the bank), the debtor control
    # account is the aged total less the customers' unused credits, to the penny
    if not ledger.bank_lines and as_of >= max(e.date for e in ledger.events):
        debtors = sum(ln.debit - ln.credit for e in ledger.events for ln in e.lines if ln.account == DEBTORS)
        payments = sum(r.amount_pence for r in ledger.records)
        refunds = sum(u.applied_pence for u in s.uses if u.kind == "refund")
        credits = sum(c.amount_pence for c in s.credits)
        assert debtors - payments + refunds == table.total_pence - credits


# --------------------------------------------------------------------------- #
# Dates: month ends, leap years, VAT staggers, BST/GMT
# --------------------------------------------------------------------------- #

any_day = st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31))
cycles = st.sampled_from([(1, 3), (2, 3), (3, 3), (1, 1)])  # the three quarterly staggers, and monthly


def _month_end(d: date) -> bool:
    return (d + timedelta(days=1)).day == 1


@given(any_day, cycles)
def test_every_day_falls_in_exactly_one_vat_period_of_whole_months(day: date, cycle: tuple[int, int]):
    start_month, months = cycle
    start, end = period_containing(day, start_month, months)
    assert start <= day <= end and start.day == 1 and _month_end(end)
    assert add_months(start, months) == end + timedelta(days=1)
    assert (start.month - start_month) % months == 0
    if months == 3:  # the stagger's quarters end in its months
        assert stagger_of(start.month) == start_month
        assert end.month in {1: (3, 6, 9, 12), 2: (4, 7, 10, 1), 3: (5, 8, 11, 2)}[start_month]
    # The period before ends the day before; the one after starts the day after
    prev_start, prev_end = previous_period(start, months)
    assert prev_end == start - timedelta(days=1) and period_containing(prev_end, start_month, months)[0] == prev_start
    assert period_containing(end + timedelta(days=1), start_month, months)[0] == end + timedelta(days=1)
    # Its id names it, both ways
    assert period_from_id(period_id(start, months), start_month, months) == (start, end)
    assert VatCycle(start_month, months).current(day) == (start, end)


@given(st.integers(2000, 2099), st.sampled_from([1, 2, 3]))
def test_february_periods_end_on_the_29th_in_leap_years(year: int, stagger: int):
    feb_end = date(year, 3, 1) - timedelta(days=1)
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    assert feb_end.day == (29 if leap else 28)
    _, end = period_containing(date(year, 2, 10), stagger, 3)
    if stagger == 3:  # Dec-Feb
        assert end == feb_end
    _, monthly_end = period_containing(date(year, 2, 10), 1, 1)
    assert monthly_end == feb_end


@given(any_day, cycles)
def test_the_return_is_due_a_month_and_seven_days_after_the_period(day: date, cycle: tuple[int, int]):
    _, end = period_containing(day, *cycle)
    due = filing_deadline(end)
    month_after = due - timedelta(days=7)
    assert _month_end(month_after) and add_months(date(end.year, end.month, 1), 1) == month_after.replace(day=1)
    assert 35 <= (due - end).days <= 38  # 28-31 days, plus 7


@given(any_day, cycles, st.integers(0, 12))
def test_recent_periods_are_back_to_back_newest_first(day: date, cycle: tuple[int, int], previous: int):
    periods = recent_periods(day, cycle[0], cycle[1], previous)
    assert len(periods) == previous + 1 and periods[0][0] <= day <= periods[0][1]
    for (s1, _), (_, e2) in zip(periods, periods[1:], strict=False):
        assert e2 + timedelta(days=1) == s1


@given(
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    st.integers(0, 40),
    st.datetimes(min_value=datetime(2019, 12, 1), max_value=datetime(2031, 2, 1), timezones=st.just(UTC)),
)
def test_a_window_of_london_days_holds_exactly_the_instants_on_those_days(start: date, length: int, t: datetime):
    """The audit log's window (app/audit_view.read): across BST and GMT, an instant is in the window iff its London
    day is, and the UTC-month files it reads include the one that instant was written to."""
    end = start + timedelta(days=length)
    lo = datetime.combine(start, time.min, LONDON).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, LONDON).astimezone(UTC)
    assert (lo <= t < hi) == (start <= t.astimezone(LONDON).date() <= end)
    if lo <= t < hi:
        assert f"{t.year:04d}-{t.month:02d}" in months_between(lo.date(), (hi - timedelta(microseconds=1)).date())


@pytest.mark.parametrize(
    ("utc", "london_day"),
    [
        (datetime(2026, 3, 29, 0, 59, tzinfo=UTC), date(2026, 3, 29)),  # clocks go forward at 01:00 UTC
        (datetime(2026, 3, 31, 23, 30, tzinfo=UTC), date(2026, 4, 1)),  # BST: already the 1st, a new quarter
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), date(2026, 10, 25)),  # clocks go back at 01:00 UTC
        (datetime(2026, 12, 31, 23, 30, tzinfo=UTC), date(2026, 12, 31)),  # GMT: still the 31st
    ],
)
def test_london_days_around_the_clock_changes(utc: datetime, london_day: date):
    assert utc.astimezone(LONDON).date() == london_day
    start, _ = period_containing(london_day, 1, 3)
    assert start == period_containing(utc.astimezone(LONDON).date(), 1, 3)[0]
