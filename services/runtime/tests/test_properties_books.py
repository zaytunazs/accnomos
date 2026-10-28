"""Stateful property test (Hypothesis): random sequences of what a user does to their books, run through the real
actions against fake storage, with the books' invariants checked after every step.

Steps: approve purchases (paid or on account), sales and supplier credit notes from Review; send invoices; record
part payments, exact payments and overpayments; Mark paid; credit notes to customers; apply and refund credits;
remove payments; undo approvals; void invoices. A step the app refuses (an InvoiceError or ApprovalError, as a 400
or 409 would) changes nothing and is fine; anything else is a failure.

Invariants, after every step:
- every event balances and the trial balance balances, in integer pence;
- no invoice or bill is settled beyond its total, and every recorded payment is fully accounted for;
- the debtor control account (1100) is the aged debtors total less the customers' unused credits, and the creditor
  control account (2100) the aged creditors total less the suppliers' unused credits;
- VAT control (2200) is exactly box 1 less box 4 over all time, and the 9-box identities hold;
- each invoice file's copy of its status and balance agrees with the ledger.

The Books.xlsx rebuild after each action is switched off: it is a convenience copy with its own tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from accnomos_ledger.vat import compute_vat_return
from app import books as books_
from app import credit_notes as cn_
from app import credits as cr_
from app import invoicing as inv_
from app import payments as pay_
from app.approve import ApprovalError, approve, undo
from app.books import BankMatchError, Books
from app.contacts import aged, documents, load_ledger, merge_ledger
from app.invoicing import PROFILE, InvoiceDraft, InvoiceError, InvoiceProfile
from app.journal import CREDITORS, DEBTORS, VAT_CONTROL, draft_journal
from app.projection import trial_balance
from app.schemas import ExtractedDoc, ExtractedLine, Proposal

USER = "sam@sambuilds.co.uk"
BASE = date(2026, 9, 1)
LATER = BASE + timedelta(days=90)  # after every document: when credits are applied or refunded
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
SUPPLIERS = ["Howdens Joinery", "Screwfix Direct"]
CUSTOMERS = ["Acme Kitchens Ltd", "Bloggs Builders"]
REFUSED = (InvoiceError, ApprovalError, BankMatchError)  # the app's own "can't do that" (400/409): nothing changed


class QuietBooks(Books):
    async def rebuild_safely(self, actor: str) -> None:  # type: ignore[override]
        return None


def _doc(kind: str, who: str, number: str, day: date, net: int, rate: int, method: str | None, credits: str | None):
    vat = round(net * rate / 100)
    return ExtractedDoc(
        doc_type=kind,  # type: ignore[arg-type]
        supplier_name="Sam Builds Ltd" if kind == "sales_invoice" else who,
        supplier_vat_number="GB 123 4567 89",
        customer_name=who if kind == "sales_invoice" else "Sam Builds Ltd",
        invoice_number=number,
        original_invoice_number=credits,
        date=day.isoformat(),
        currency="GBP",
        lines=[
            ExtractedLine(description="Goods", qty=1, unit_price=net / 100, net=net / 100, vat_rate=rate, vat=vat / 100)
        ],
        net_total=net / 100,
        vat_total=vat / 100,
        gross_total=(net + vat) / 100,
        payment_method=method,  # type: ignore[arg-type]
        card_last4=None,
        category_guess="Materials",
        confidence=0.95,
    )


class _Clock(datetime):
    """app.books.now()/today() for one run: a second later on every call, so a failing run replays exactly (events
    posted in the same second are otherwise ordered by their random ids)."""

    ticks = itertools.count(1)

    @classmethod
    def now(cls, tz=None):  # noqa: ANN001, ANN206
        t = NOW + timedelta(seconds=next(cls.ticks))
        return t.astimezone(tz) if tz else t.replace(tzinfo=None)


class BooksMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        ids = itertools.count(1)
        _Clock.ticks = itertools.count(1)
        self.patches = [
            mock.patch.object(books_, "datetime", _Clock),
            mock.patch.object(uuid, "uuid4", lambda: uuid.UUID(bytes=hashlib.sha256(b"%d" % next(ids)).digest()[:16])),
        ]
        for patch in self.patches:
            patch.start()
        self.loop = asyncio.new_event_loop()
        self.books = QuietBooks(FakeStorageProvider())
        self.sender = FakeMailSender()
        self.approved: list[str] = []  # posted ledger events from Review
        self.bills: list[tuple[str, str]] = []  # (bill number, supplier) on account
        self.invoices: list[str] = []  # sent invoice numbers
        self.credit_notes: list[str] = []
        self.payments: list[str] = []
        self.lines: list[str] = []  # bank statement lines imported
        self.n = 0
        profile = InvoiceProfile(name="Sam Builds Ltd", address="1 High Street\nLeeds", vrn="GB 123 4567 89")
        self.run(self.books.write_json(PROFILE, profile.model_dump(mode="json")))

    def run(self, coro):  # noqa: ANN001, ANN201
        return self.loop.run_until_complete(coro)

    def teardown(self) -> None:
        self.loop.close()
        for patch in self.patches:
            patch.stop()

    def _next(self) -> int:
        self.n += 1
        return self.n

    async def _approve(self, doc: ExtractedDoc) -> str | None:
        p = Proposal(
            id=uuid.uuid4().hex,
            doc_sha256=uuid.uuid4().hex * 2,
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
        await self.books.save_proposal(p)
        try:
            return (await approve(self.books, p.id, USER, rebuild=False)).event_id
        except REFUSED:
            return None

    # ----------------------------------------------------------------------- #
    # Review
    # ----------------------------------------------------------------------- #

    @rule(
        who=st.sampled_from(SUPPLIERS),
        day=st.integers(0, 30),
        net=st.integers(1, 200_000),
        rate=st.sampled_from([20, 5, 0]),
        method=st.sampled_from([None, None, "card", "cash"]),
    )
    def approve_purchase(self, who: str, day: int, net: int, rate: int, method: str | None):
        number = f"B-{self._next()}"
        eid = self.run(
            self._approve(_doc("purchase_invoice", who, number, BASE + timedelta(days=day), net, rate, method, None))
        )
        if eid:
            self.approved.append(eid)
            if method is None:
                self.bills.append((number, who))

    @rule(
        who=st.sampled_from(CUSTOMERS),
        day=st.integers(0, 30),
        net=st.integers(0, 200_000),
        rate=st.sampled_from([20, 5, 0]),
    )
    def approve_sale(self, who: str, day: int, net: int, rate: int):
        eid = self.run(
            self._approve(
                _doc("sales_invoice", who, f"S-{self._next()}", BASE + timedelta(days=day), net, rate, None, None)
            )
        )
        if eid:
            self.approved.append(eid)

    @precondition(lambda self: self.bills)
    @rule(data=st.data(), linked=st.booleans(), day=st.integers(30, 60), net=st.integers(1, 300_000))
    def approve_supplier_credit_note(self, data: st.DataObject, linked: bool, day: int, net: int):
        number, who = data.draw(st.sampled_from(self.bills))
        doc = _doc(
            "credit_note",
            who,
            f"C-{self._next()}",
            BASE + timedelta(days=day),
            net,
            20,
            None,
            number if linked else None,
        )
        if eid := self.run(self._approve(doc)):
            self.approved.append(eid)

    @precondition(lambda self: self.approved)
    @rule(data=st.data())
    def undo_an_approval(self, data: st.DataObject):
        eid = data.draw(st.sampled_from(self.approved))
        with contextlib.suppress(REFUSED):
            self.run(undo(self.books, eid, USER))

    # ----------------------------------------------------------------------- #
    # Invoices, payments, credit notes, credits
    # ----------------------------------------------------------------------- #

    @rule(
        who=st.sampled_from(CUSTOMERS),
        day=st.integers(0, 30),
        lines=st.lists(
            st.tuples(st.integers(1, 40), st.integers(1, 50_000), st.sampled_from(["S", "R", "Z", "E", "O"])),
            min_size=1,
            max_size=3,
        ),
    )
    def send_invoice(self, who: str, day: int, lines: list[tuple[int, int, str]]):
        draft = InvoiceDraft.model_validate(
            {
                "customer": {"name": who, "email": "accounts@example.com"},
                "issue_date": (BASE + timedelta(days=day)).isoformat(),
                "lines": [
                    {"description": "Work", "quantity": str(q), "unit_price_pence": u, "vat_code": c}
                    for q, u, c in lines
                ],
            }
        )

        async def go() -> None:
            inv = await inv_.create_invoice(self.books, draft, USER)
            await inv_.send_invoice(self.books, self.sender, inv.number, USER, b"%PDF-1.4 test")
            self.invoices.append(inv.number)

        self.run(go())

    async def _open(self, side: str) -> list[pay_.OpenDocument]:
        return pay_.open_documents(await load_ledger(self.books), side)  # type: ignore[arg-type]

    @rule(data=st.data(), side=st.sampled_from(["sale", "purchase"]), how=st.sampled_from(["part", "exact", "over"]))
    def record_payment(self, data: st.DataObject, side: str, how: str):
        docs = self.run(self._open(side))
        if not docs:
            return
        d = data.draw(st.sampled_from(docs))
        owed = d.outstanding_pence
        amount = {
            "part": data.draw(st.integers(1, owed)),
            "exact": owed,
            "over": owed + data.draw(st.integers(1, 100_000)),
        }[how]
        body = pay_.PaymentIn(
            side=side,  # type: ignore[arg-type]
            date=d.date + timedelta(days=data.draw(st.integers(0, 40))),
            amount_pence=amount,
            allocations=[pay_.AllocationIn(event_id=d.event_id, amount_pence=min(amount, owed))],
        )
        try:
            rec = self.run(pay_.record_payment(self.books, body, USER))
            self.payments.append(rec.id)
        except REFUSED:
            pass

    @precondition(lambda self: self.invoices)
    @rule(data=st.data())
    def mark_paid(self, data: st.DataObject):
        number = data.draw(st.sampled_from(self.invoices))
        with contextlib.suppress(REFUSED):
            self.run(inv_.mark_paid(self.books, number, USER, paid_on=LATER))

    @precondition(lambda self: self.invoices)
    @rule(data=st.data(), whole=st.booleans(), day=st.integers(30, 60))
    def credit_an_invoice(self, data: st.DataObject, whole: bool, day: int):
        number = data.draw(st.sampled_from(self.invoices))
        lines = None if whole else [cn_.CreditLineIn(line=0, quantity=Decimal(1))]
        draft = cn_.CreditNoteDraft(lines=lines, issue_date=BASE + timedelta(days=day), reason="Not done")
        with contextlib.suppress(REFUSED):
            self.credit_notes.append(self.run(cn_.create_credit_note(self.books, number, draft, USER)).number)

    @precondition(lambda self: self.credit_notes)
    @rule(data=st.data())
    def void_a_credit_note(self, data: st.DataObject):
        number = data.draw(st.sampled_from(self.credit_notes))
        with contextlib.suppress(REFUSED):
            self.run(cn_.void_credit_note(self.books, number, USER, "Raised in error"))

    @rule(data=st.data(), refund=st.booleans())
    def use_a_credit(self, data: st.DataObject, refund: bool):
        ledger = self.run(load_ledger(self.books))
        credits = ledger.settlement().credits
        if not credits:
            return
        c = data.draw(st.sampled_from(credits))
        whose = {d.event.id: d.name for d in documents(ledger)}
        amount = data.draw(st.integers(1, c.amount_pence))
        try:
            if refund:
                self.run(
                    cr_.refund_credit(self.books, cr_.RefundIn(credit=c.id, amount_pence=amount, date=LATER), USER)
                )
                return
            docs = [d for d in pay_.open_documents(ledger, c.side) if d.counterparty == whose.get(c.doc_event_id)]
            if docs:
                d = data.draw(st.sampled_from(docs))
                amount = min(amount, d.outstanding_pence)
                body = cr_.ApplyIn(credit=c.id, event_id=d.event_id, amount_pence=amount, date=LATER)
                self.run(cr_.apply_credit(self.books, body, USER))
        except REFUSED:
            pass

    @precondition(lambda self: self.payments)
    @rule(data=st.data())
    def remove_a_payment(self, data: st.DataObject):
        with contextlib.suppress(REFUSED):
            self.run(pay_.remove_payment(self.books, data.draw(st.sampled_from(self.payments)), USER))

    @precondition(lambda self: self.invoices)
    @rule(data=st.data())
    def void_an_invoice(self, data: st.DataObject):
        with contextlib.suppress(REFUSED):
            self.run(inv_.void_invoice(self.books, data.draw(st.sampled_from(self.invoices)), USER, "Raised in error"))

    # ----------------------------------------------------------------------- #
    # Bank statements: lines matched straight to documents, posted as payments, unmatched
    # ----------------------------------------------------------------------- #

    @rule(
        data=st.data(),
        side=st.sampled_from(["sale", "purchase"]),
        how=st.sampled_from(["exact", "penny_short", "penny_over", "half", "double"]),
        later=st.integers(0, 40),
    )
    def match_a_bank_line(self, data: st.DataObject, side: str, how: str, later: int):
        docs = self.run(self._open(side))
        if not docs:
            return
        d = data.draw(st.sampled_from(docs))
        owed = d.outstanding_pence
        amount = {
            "exact": owed,
            "penny_short": owed - 1,
            "penny_over": owed + 1,
            "half": owed // 2,
            "double": owed * 2,
        }[how]
        if amount <= 0:
            return
        signed = amount if side == "sale" else -amount
        n = self._next()
        paid_on = d.date + timedelta(days=later)
        csv = f"Date,Description,Amount\n{paid_on:%d/%m/%Y},FASTER PAYMENT {n},{signed / 100:.2f}\n"

        async def go() -> None:
            await self.books.import_bank_csv(csv.encode(), f"statement-{n}.csv", USER)
            line = next(ln for ln in await self.books.stored_bank_lines() if ln.description == f"FASTER PAYMENT {n}")
            self.lines.append(line.id)
            await self.books.confirm_match(line.id, [d.event_id], USER)

        with contextlib.suppress(REFUSED):
            self.run(go())

    @precondition(lambda self: self.lines)
    @rule(data=st.data(), post=st.booleans())
    def post_or_unmatch_a_bank_line(self, data: st.DataObject, post: bool):
        line_id = data.draw(st.sampled_from(self.lines))
        try:
            if post:
                rec = self.run(pay_.payment_from_bank_line(self.books, line_id, USER))
                self.payments.append(rec.id)
            else:
                self.run(self.books.unmatch(line_id, USER))
        except REFUSED:
            pass

    # ----------------------------------------------------------------------- #
    # Invariants
    # ----------------------------------------------------------------------- #

    @invariant()
    def the_books_hold_together(self):
        self.run(self._check())

    async def _check(self) -> None:
        ledger = await load_ledger(self.books)
        events = ledger.events

        # Every event balances; so does the trial balance; all integer pence
        for e in events:
            assert sum(ln.debit for ln in e.lines) == sum(ln.credit for ln in e.lines)
            assert all(type(ln.debit) is int and type(ln.credit) is int for ln in e.lines)
        tb = trial_balance(events)
        assert sum(dr for _, dr, _ in tb) == sum(cr for _, _, cr in tb)
        bal = {acct: dr - cr for acct, dr, cr in tb}

        # Nothing settled beyond its total; every recorded payment accounted for to the penny
        s = ledger.settlement()
        for eid, gross in s.gross.items():
            assert 0 <= s.paid.get(eid, 0) + s.credited.get(eid, 0) <= gross, eid
        by_bank = {"sale": 0, "purchase": 0}  # what bank lines matched straight to documents settled (nothing posted)
        for pay in s.payments:
            used = s.used.get(f"payment:{pay.id}", 0)
            took = sum(a.amount_pence for a in pay.allocations) + pay.unallocated_pence + used
            if pay.source == "recorded":
                assert took == pay.amount_pence
            else:  # a line within a penny a document pays it in full
                assert abs(took - pay.amount_pence) <= len(pay.allocations)
                by_bank[pay.side] += took

        # Control accounts = aged balances less unused credits
        ages = aged(merge_ledger([], ledger, at=NOW), ledger, LATER + timedelta(days=365))
        credit = {side: sum(c.amount_pence for c in s.credits if c.side == side) for side in ("sale", "purchase")}
        # (a bank line matched straight to an invoice posts nothing until *Post as payment*: the control account
        # still holds what it paid)
        assert bal.get(DEBTORS, 0) == ages.debtors.total_pence - credit["sale"] + by_bank["sale"]
        assert -bal.get(CREDITORS, 0) == ages.creditors.total_pence - credit["purchase"] + by_bank["purchase"]
        assert sum(ages.debtors.buckets.values()) == ages.debtors.total_pence

        # VAT control is box 1 less box 4, over all time; the 9-box identities hold
        ret = compute_vat_return(events, "all", date(2026, 1, 1), date(2027, 12, 31))
        assert ret.total_vat_due == ret.vat_due_sales + ret.vat_due_acquisitions
        assert ret.net_vat_due == abs(ret.total_vat_due - ret.vat_reclaimed)
        assert -bal.get(VAT_CONTROL, 0) == int((ret.vat_due_sales - ret.vat_reclaimed) * 100)

        # Each sent invoice's file agrees with the ledger
        for inv in await inv_.list_invoices(self.books):
            m = pay_.invoice_money(inv, ledger)
            if m is None or pay_.is_marked_paid(inv):
                continue
            assert m.paid_pence + m.credited_pence <= inv.total_pence
            assert inv.status == ("paid" if m.balance_pence == 0 and m.paid_pence + m.credited_pence > 0 else "sent")
            assert (inv.balance_pence, inv.paid_pence) in {(m.balance_pence, m.paid_pence), (None, None)}


BooksMachine.TestCase.settings = settings(max_examples=40, stateful_step_count=25, deadline=None)
TestBooks = BooksMachine.TestCase


class TestBooksDeep(BooksMachine.TestCase):
    settings = settings(max_examples=150, stateful_step_count=40, deadline=None)
    pytestmark = [pytest.mark.slow]
