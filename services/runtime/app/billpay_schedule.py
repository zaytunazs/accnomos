"""Upcoming PayPal payments: "Approve now, pay on due date", the schedule of what leaves PayPal, and the calendar.

**PayPal cannot hold a payment for a future date.** The Payouts API sends at once; PayPal's "scheduled payouts" are a
limited-release automatic withdrawal to the merchant's own bank, not a future-dated payment to a supplier (checked 11
Nov 2026). And Accnomos has no background writer with access to the books (writing needs the user's sign-in). So an
approval in advance is kept in the books (`_System/Payments/billpay-scheduled.json`, `billpay.Approval`) and acted on
by `POST /billpay/run`, which the app calls when it opens: the bill is paid **the next time Accnomos is open on or after
its due date**, and only if the amount owed, the supplier's saved PayPal email and the bill's own entry are exactly
what the owner approved. Anything else moves it to Due today with the reason (`needs_you`), and nothing is sent. The
payout itself is `billpay.pay` (same idempotent `sender_batch_id`, same posting on SUCCESS). Autopilot is separate.

The schedule (`upcoming`) lists every approved-in-advance and planned PayPal bill payment with its status, the books'
1240 PayPal clearing balance, what is due to leave PayPal in the next 7 and 30 days, and a shortfall warning (a books
figure, not the live PayPal balance: Accnomos does not read the PayPal balance).

The calendar: an RFC 5545 `.ics` (`ics`) with one all-day VEVENT per payment and a UID stable per bill, so importing
again updates the event; or, on the user's tap, an event in the calendar they signed in with (Google or Outlook through
`CalendarProvider`), tagged `billpay:<bill id>` so it is found, updated and removed again, never duplicated.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from accnomos_connectors import CalendarEvent, CalendarProvider, NewCalendarEvent
from app import billpay as bp
from app.books import Books, now
from app.books import today as london_today
from app.invoicing import InvoiceError, InvoiceStateError, money

ACTOR = "agent:billpay-scheduled"
UID_DOMAIN = "accnomos.com"
LONDON = ZoneInfo("Europe/London")
KEY_PREFIX = "billpay:"
SHOW_PAID_DAYS = 30  # a payment approved in advance stays on the schedule this long after it is paid
CAL_BACK, CAL_AHEAD = 60, 400  # days of calendar searched for our own events

NOTE = "PayPal cannot hold a payment for a future date."


def pays_line(d: date) -> str:
    return f"Accnomos pays this the next time it is open on or after {day_label(d)} — {NOTE}"


def day_label(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


# --------------------------------------------------------------------------- #
# Approve in advance, cancel
# --------------------------------------------------------------------------- #


def _find(ov: bp.Overview, event_id: str) -> bp.Bill | None:
    return next((b for b in [*ov.due, *ov.upcoming] if b.event_id == event_id), None)


async def approve(
    books: Books,
    event_id: str,
    amount_pence: int,
    payee_email: str,
    user: str,
    *,
    acknowledge_changed_details: bool = False,
    today: date | None = None,
) -> bp.Approval:
    """The owner's yes, now, to paying this bill through PayPal on its due date. `amount_pence` and `payee_email` are
    what the card showed: anything else means the bill or the payee changed while they looked."""
    today = today or london_today()
    ov = await bp.bills(books, today=today, read_documents=False)
    bill = _find(ov, event_id)
    if bill is None:
        raise InvoiceStateError("No unpaid bill on account with that id (it may be paid or undone)")
    if bill.due_now:
        raise InvoiceStateError("This bill is due already: pay it from Due today")
    if amount_pence != bill.owed_pence:
        raise InvoiceStateError(
            f"{money(bill.owed_pence)} is owed on this bill now, not {money(amount_pence)}; look again before approving"
        )
    if bill.payee_email is None:
        raise bp.BillPayError(f"Add {bill.supplier}'s PayPal email first (you type it; it is never read from a bill)")
    if bp.normalise_email(payee_email) != bill.payee_email:
        raise InvoiceStateError(
            f"{bill.supplier}'s saved PayPal email is {bill.payee_email} now, not {payee_email}; look again"
        )
    if bill.blocks:
        raise InvoiceStateError(bill.blocks[0])
    if bill.plan == "not_paypal":
        raise bp.BillPayError("You marked this bill not to be paid through PayPal; tick Pay with PayPal first")
    if bill.changed_details and not acknowledge_changed_details:
        raise bp.BillPayError(
            "The payment details on this bill differ from the ones you saved. Check with the supplier, then confirm"
        )
    at = now()
    made: list[bp.Approval] = []

    def change(st: bp.Scheduled) -> None:
        cur = st.approvals.get(event_id)
        if cur is not None and cur.status in ("scheduled", "paying"):
            raise InvoiceStateError("This payment is already approved; cancel it first to change it")
        a = bp.Approval(
            event_id=event_id,
            contact_id=bill.contact_id,
            supplier=bill.supplier,
            reference=bill.reference,
            amount_pence=amount_pence,
            payee_email=bill.payee_email or "",
            due_date=bill.due_date,
            bill_version=bill.version,
            approved_by=user,
            approved_at=at,
            updated_at=at,
        )
        st.approvals[event_id] = a
        made.append(a)

    await bp.update_scheduled(books, change)
    if bill.plan != "paypal":
        await bp.set_plan(books, event_id, "paypal", user)
    a = made[-1]
    await books.audit(
        f"user:{user}",
        "billpay_scheduled_approved",
        {
            "bill": event_id,
            "supplier": a.supplier,
            "amount_pence": a.amount_pence,
            "receiver": a.payee_email,
            "due_date": a.due_date.isoformat(),
            "bill_version": a.bill_version,
            "acknowledged_changed_details": bool(bill.changed_details and acknowledge_changed_details),
        },
    )
    return a


async def cancel(books: Books, event_id: str, user: str) -> bp.Approval:
    """Withdraw an approval in advance. Refused once a payout was sent for it (PayPal has it then)."""
    done: list[bp.Approval] = []

    def change(st: bp.Scheduled) -> None:
        a = st.approvals.get(event_id)
        if a is None or a.status == "cancelled":
            raise FileNotFoundError(event_id)
        if a.payout_id is not None or a.status == "paying":
            raise InvoiceStateError("This payment was already sent to PayPal, so it cannot be cancelled here")
        a.status = "cancelled"
        a.cancelled_at = a.updated_at = now()
        a.cancelled_by = user
        done.append(a)

    await bp.update_scheduled(books, change)
    a = done[-1]
    await books.audit(
        f"user:{user}",
        "billpay_scheduled_cancelled",
        {"bill": event_id, "supplier": a.supplier, "amount_pence": a.amount_pence, "due_date": a.due_date.isoformat()},
    )
    return a


# --------------------------------------------------------------------------- #
# Paying on or after the due date (from billpay.run, when the app opens)
# --------------------------------------------------------------------------- #


def held_reasons(a: bp.Approval, bill: bp.Bill | None, payee: bp.Payee | None) -> list[str]:
    """Why an approval in advance must not be paid now (empty: it may)."""
    if bill is None:
        return ["This bill is no longer open in your books (paid another way, or undone), so nothing was sent"]
    out: list[str] = []
    if bill.version != a.bill_version:
        out.append("The bill was changed after you approved the payment")
    if bill.owed_pence != a.amount_pence:
        out.append(f"{money(bill.owed_pence)} is owed now, not the {money(a.amount_pence)} you approved")
    if payee is None:
        out.append(f"No PayPal email is saved for {a.supplier} any more")
    elif bp.normalise_email(payee.paypal_email) != a.payee_email:
        out.append(f"{a.supplier}'s saved PayPal email is now {payee.paypal_email}, not {a.payee_email} as approved")
    if bill.plan == "not_paypal":
        out.append("You marked this bill not to be paid through PayPal")
    if bill.changed_details:
        out.append("Payment details on this bill differ from the ones you saved")
    out += [b for b in bill.blocks if b not in out]
    return out


async def _hold(books: Books, event_id: str, reasons: list[str]) -> None:
    def change(st: bp.Scheduled) -> None:
        a = st.approvals.get(event_id)
        if a is not None and a.status == "scheduled":
            a.status, a.reason, a.updated_at = "needs_you", "; ".join(reasons), now()

    st = await bp.update_scheduled(books, change)
    a = st.approvals[event_id]
    await books.audit(
        ACTOR,
        "billpay_scheduled_held",
        {"bill": event_id, "supplier": a.supplier, "amount_pence": a.amount_pence, "reasons": reasons},
    )

    def note(s: bp.Ledgerish) -> None:
        bp._notice(
            s,
            "asked",
            f"Accnomos did not pay {a.supplier} {money(a.amount_pence)} as you approved in advance: {reasons[0]}. It "
            "is waiting for you in Due today.",
        )

    await bp._update_state(books, note)


async def run_scheduled(books: Books, out: bp.RunResult, *, today: date | None = None) -> None:
    """Pay each approval in advance whose due date has come, if nothing changed since; else hold it for the owner."""
    today = today or london_today()
    sched = await bp.load_scheduled(books)
    due = [a for a in sched.approvals.values() if a.status == "scheduled" and a.due_date <= today]
    if not due:
        return
    ap = (await bp.load_settings(books)).autopilot
    if bp.server_kill_switch() or (ap.stopped_at is not None and not ap.enabled):
        # The kill switch stops every payment Accnomos sends by itself, approvals in advance included; they stay
        # approved and go out on the first visit after the switch is lifted (or the owner pays them by hand).
        out.problems.append(
            f"{len(due)} payment(s) you approved in advance were not sent: bill pay is stopped with the kill switch."
        )
        return
    ov = await bp.bills(books, today=today, read_documents=False)
    payees = await bp.load_payees(books)
    for a in sorted(due, key=lambda x: (x.due_date, x.supplier.lower())):
        reasons = held_reasons(a, _find(ov, a.event_id), payees.get(a.contact_id))
        if reasons:
            await _hold(books, a.event_id, reasons)
            out.scheduled_held.append(
                {"bill": a.event_id, "supplier": a.supplier, "amount_pence": a.amount_pence, "reasons": reasons}
            )
            continue
        claimed: list[bool] = []

        def claim(st: bp.Scheduled, eid: str = a.event_id, claimed: list[bool] = claimed) -> None:
            cur = st.approvals.get(eid)
            if cur is not None and cur.status == "scheduled":  # another tab may have taken it a moment ago
                cur.status, cur.updated_at = "paying", now()
                claimed.append(True)

        await bp.update_scheduled(books, claim)
        if not claimed:
            continue
        try:
            p = await bp.pay(books, a.event_id, a.amount_pence, a.approved_by, via="owner", today=today)
        except InvoiceError as exc:

            def back(st: bp.Scheduled, eid: str = a.event_id) -> None:
                st.approvals[eid].status = "scheduled"

            await bp.update_scheduled(books, back)
            await _hold(books, a.event_id, [str(exc)])
            out.scheduled_held.append(
                {"bill": a.event_id, "supplier": a.supplier, "amount_pence": a.amount_pence, "reasons": [str(exc)]}
            )
            continue

        def sent(st: bp.Scheduled, eid: str = a.event_id, pid: str = p.id) -> None:
            st.approvals[eid].payout_id, st.approvals[eid].updated_at = pid, now()

        await bp.update_scheduled(books, sent)
        await books.audit(
            ACTOR,
            "billpay_scheduled_sent",
            {
                "bill": a.event_id,
                "payout": p.id,
                "supplier": a.supplier,
                "amount_pence": a.amount_pence,
                "receiver": a.payee_email,
                "approved_by": a.approved_by,
                "approved_at": a.approved_at.isoformat(),
                "status": p.status,
            },
        )
        out.scheduled_paid.append(p)


# --------------------------------------------------------------------------- #
# The schedule
# --------------------------------------------------------------------------- #

ItemStatus = Literal["scheduled", "planned", "due_today", "paying", "paid", "needs_you"]
UNPAID: tuple[ItemStatus, ...] = ("scheduled", "planned", "due_today", "paying", "needs_you")
#: Statuses a calendar event is offered for (money still to be sent).
CALENDAR_OK: tuple[ItemStatus, ...] = ("scheduled", "planned", "due_today", "needs_you")


class UpcomingItem(BaseModel):
    event_id: str
    contact_id: str
    supplier: str
    reference: str | None = None
    date: date  # the due date: paid the next time Accnomos is open on or after it
    amount_pence: int
    payee_email: str | None = None
    status: ItemStatus
    approved: bool  # approved in advance (else planned: the owner approves on the day, or Autopilot pays)
    approved_by: str | None = None
    approved_at: datetime | None = None
    reason: str | None = None  # needs_you: why; paying/paid: PayPal's word
    payout_id: str | None = None
    calendar_uid: str
    in_calendar: bool  # an event Accnomos put in the connected calendar
    calendar_outdated: bool = False  # that event shows another date or amount: add again to update it
    title: str
    description: str


class UpcomingView(BaseModel):
    today: date
    clearing_pence: int
    clearing_label: str
    next_7_pence: int
    next_30_pence: int
    shortfall_7_pence: int
    shortfall_30_pence: int
    warning: str | None = None
    items: list[UpcomingItem]
    calendar_stale: list[str]  # bills whose calendar event is for a payment cancelled, paid or no longer planned
    note: str


CLEARING_LABEL = "1240 PayPal clearing by your books (not your live PayPal balance)"


def title_for(supplier: str, amount_pence: int) -> str:
    return f"PayPal payment: {supplier} {money(amount_pence)}"


def description_for(item_status: ItemStatus, approved: bool, d: date, email: str | None, reference: str | None) -> str:
    what = f"Bill {reference}" if reference else "A bill"
    to = f" to {email}" if email else ""
    if approved:
        head = (
            f"{what}, paid through PayPal{to}. {pays_line(d)} You approved it in advance; it is paid only if the "
            "amount, the supplier's PayPal email and the bill are unchanged."
        )
    else:
        head = (
            f"{what}, to pay through PayPal{to}. Not approved yet: approve it in Accnomos (Purchases). Approved in "
            f"advance, Accnomos pays it the next time it is open on or after {day_label(d)} — {NOTE}"
        )
    if item_status == "needs_you":
        head += " It needs you in Accnomos: something changed since you approved it."
    return head


def uid(event_id: str) -> str:
    return f"billpay-{event_id}@{UID_DOMAIN}"


async def upcoming(books: Books, *, today: date | None = None) -> UpcomingView:
    """Every approved-in-advance and planned PayPal bill payment, with totals and the shortfall warning. Pays nothing,
    writes nothing (bill files are not read here)."""
    today = today or london_today()
    ov = await bp.bills(books, today=today, read_documents=False)
    sched = await bp.load_scheduled(books)
    st = await bp.load_state(books)
    by_payout = {p.id: p for p in st.payouts}
    items: list[UpcomingItem] = []
    seen: set[str] = set()

    def item(
        *,
        event_id: str,
        contact_id: str,
        supplier: str,
        reference: str | None,
        d: date,
        amount: int,
        email: str | None,
        status: ItemStatus,
        approval: bp.Approval | None,
        reason: str | None,
        payout_id: str | None,
    ) -> UpcomingItem:
        cal = sched.calendar.get(event_id)
        title = title_for(supplier, amount)
        return UpcomingItem(
            event_id=event_id,
            contact_id=contact_id,
            supplier=supplier,
            reference=reference,
            date=d,
            amount_pence=amount,
            payee_email=email,
            status=status,
            approved=approval is not None,
            approved_by=approval.approved_by if approval else None,
            approved_at=approval.approved_at if approval else None,
            reason=reason,
            payout_id=payout_id,
            calendar_uid=uid(event_id),
            in_calendar=cal is not None,
            calendar_outdated=cal is not None and (cal.day != d or cal.title != title),
            title=title,
            description=description_for(status, approval is not None, d, email, reference),
        )

    for b in [*ov.due, *ov.upcoming]:
        a = b.approval
        if b.plan == "not_paypal" and a is None:
            continue
        planned = b.plan == "paypal" or (b.plan is None and b.payee_email is not None)
        if a is None and not planned:
            continue
        p = b.payout
        reason: str | None = None
        status: ItemStatus
        if p is not None and p.status in bp.WAITING:
            status, reason = "paying", p.detail
        elif a is not None and a.status == "needs_you":
            status, reason = "needs_you", a.reason
        elif p is not None and p.status == "failed" and (a is None or a.payout_id == p.id):
            status, reason = "needs_you", p.detail
        elif a is not None:
            status = "due_today" if a.due_date <= today else "scheduled"
        else:
            status = "due_today" if b.due_now else "planned"
        d = a.due_date if a is not None else b.due_date
        items.append(
            item(
                event_id=b.event_id,
                contact_id=b.contact_id,
                supplier=b.supplier,
                reference=b.reference,
                d=d,
                amount=a.amount_pence if a is not None else b.owed_pence,
                email=a.payee_email if a is not None else b.payee_email,
                status=status,
                approval=a,
                reason=reason,
                payout_id=p.id if p is not None else None,
            )
        )
        seen.add(b.event_id)
    # Approvals whose bill is no longer open: paid (shown for a while), or gone another way (needs you).
    for a in sched.approvals.values():
        if a.event_id in seen or a.status == "cancelled":
            continue
        p = by_payout.get(a.payout_id or "")
        if p is not None and p.status == "paid":
            if (today - p.updated_at.date()).days > SHOW_PAID_DAYS:
                continue
            status, reason = "paid", None
        elif a.status == "needs_you":
            status, reason = "needs_you", a.reason
        elif a.status == "scheduled":  # the bill went (paid another way or undone): the next run holds it
            status, reason = "needs_you", held_reasons(a, None, None)[0]
        else:
            continue
        items.append(
            item(
                event_id=a.event_id,
                contact_id=a.contact_id,
                supplier=a.supplier,
                reference=a.reference,
                d=a.due_date,
                amount=a.amount_pence,
                email=a.payee_email,
                status=status,
                approval=a,
                reason=reason,
                payout_id=a.payout_id,
            )
        )
    items.sort(key=lambda i: (i.date, i.supplier.lower(), i.event_id))
    unpaid = [i for i in items if i.status in UNPAID]
    n7 = sum(i.amount_pence for i in unpaid if i.date <= today + timedelta(days=7))
    n30 = sum(i.amount_pence for i in unpaid if i.date <= today + timedelta(days=30))
    clearing = ov.clearing_pence
    s7, s30 = max(0, n7 - clearing), max(0, n30 - clearing)
    warning = None
    if s30:
        when = "7" if s7 else "30"
        total = n7 if s7 else n30
        warning = (
            f"By your books, 1240 PayPal clearing holds {money(max(clearing, 0))}: {money(total - clearing)} less "
            f"than the {money(total)} due to leave PayPal in the next {when} days. This is a books figure, not your "
            "live PayPal balance (Accnomos does not read it): check PayPal has the money, or a linked funding source."
        )
    live = {i.event_id for i in items if i.status in CALENDAR_OK}
    return UpcomingView(
        today=today,
        clearing_pence=clearing,
        clearing_label=CLEARING_LABEL,
        next_7_pence=n7,
        next_30_pence=n30,
        shortfall_7_pence=s7,
        shortfall_30_pence=s30,
        warning=warning,
        items=items,
        calendar_stale=sorted(k for k in sched.calendar if k not in live),
        note=f"Accnomos pays an approved bill the next time it is open on or after its due date — {NOTE}",
    )


# --------------------------------------------------------------------------- #
# Calendar: an .ics file, or the connected calendar on the user's tap
# --------------------------------------------------------------------------- #


def ics_escape(text: str) -> str:
    """RFC 5545 3.3.11 TEXT: backslash, semicolon, comma and newlines escaped."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def ics_fold(line: str) -> str:
    """RFC 5545 3.1: lines over 75 octets are folded (CRLF then a space), never inside a UTF-8 character."""
    out: list[str] = []
    cur = b""
    limit = 75
    for ch in line:
        enc = ch.encode()
        if len(cur) + len(enc) > limit:
            out.append(cur.decode())
            cur = b""
            limit = 74  # continuation lines start with a space
        cur += enc
    out.append(cur.decode())
    return "\r\n ".join(out)


def ics(items: list[UpcomingItem], *, stamp: datetime | None = None) -> str:
    """One VCALENDAR with an all-day VEVENT per payment. The UID is stable per bill, and SEQUENCE grows with time,
    so importing the file again updates the event rather than adding a second."""
    stamp = (stamp or now()).astimezone(UTC)
    seq = max(0, int((stamp - datetime(2026, 1, 1, tzinfo=UTC)).total_seconds() // 60))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Accnomos//Upcoming PayPal payments//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for i in items:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{i.calendar_uid}",
            f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}",
            f"SEQUENCE:{seq}",
            f"DTSTART;VALUE=DATE:{i.date:%Y%m%d}",
            f"DTEND;VALUE=DATE:{i.date + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{ics_escape(i.title)}",
            f"DESCRIPTION:{ics_escape(i.description)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(x) for x in lines) + "\r\n"


def calendar_items(view: UpcomingView, event_ids: list[str] | None) -> list[UpcomingItem]:
    """The payments a calendar entry is offered for (still to be sent), all or the ones asked for."""
    ok = [i for i in view.items if i.status in CALENDAR_OK]
    if event_ids is None:
        return ok
    by = {i.event_id: i for i in ok}
    missing = [e for e in event_ids if e not in by]
    if missing:
        raise FileNotFoundError(missing[0])
    return [by[e] for e in event_ids]


def _new_event(i: UpcomingItem) -> NewCalendarEvent:
    start = datetime.combine(i.date, datetime.min.time(), LONDON)
    return NewCalendarEvent(
        subject=i.title,
        start=start,
        end=start + timedelta(days=1),
        is_all_day=True,
        body=i.description,
        reminder_minutes=15 * 60,  # 09:00 the day before
        key=KEY_PREFIX + i.event_id,
    )


async def _ours(calendar: CalendarProvider, today: date) -> dict[str, CalendarEvent]:
    window = await calendar.list_range(today - timedelta(days=CAL_BACK), today + timedelta(days=CAL_AHEAD))
    out: dict[str, CalendarEvent] = {}
    for e in window:
        if e.key and e.key.startswith(KEY_PREFIX):
            out.setdefault(e.key.removeprefix(KEY_PREFIX), e)
    return out


class CalendarResult(BaseModel):
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    not_found: int = 0  # already gone from the calendar (removed by the user)


async def add_to_calendar(
    books: Books, calendar: CalendarProvider, event_ids: list[str] | None, user: str, *, today: date | None = None
) -> CalendarResult:
    """Put each payment in the connected calendar as an all-day event (the user tapped Add). Re-adding updates."""
    today = today or london_today()
    view = await upcoming(books, today=today)
    items = calendar_items(view, event_ids)
    ours = await _ours(calendar, today)
    res = CalendarResult()
    kept: dict[str, bp.CalendarEntry] = {}
    for i in items:
        have = ours.get(i.event_id)
        if have is None:
            made = await calendar.add_event(_new_event(i))
            res.added += 1
        elif have.subject != i.title or have.start.astimezone(LONDON).date() != i.date:
            made = await calendar.update_event(have.id, _new_event(i))
            res.updated += 1
        else:
            made = have
            res.unchanged += 1
        kept[i.event_id] = bp.CalendarEntry(
            calendar_event_id=made.id, day=i.date, title=i.title, added_at=now(), added_by=user
        )

    def change(st: bp.Scheduled) -> None:
        st.calendar.update(kept)

    await bp.update_scheduled(books, change)
    await books.audit(
        f"user:{user}",
        "billpay_calendar_added",
        {"bills": sorted(kept), "added": res.added, "updated": res.updated, "unchanged": res.unchanged},
    )
    return res


async def remove_from_calendar(
    books: Books, calendar: CalendarProvider, event_ids: list[str] | None, user: str, *, today: date | None = None
) -> CalendarResult:
    """Take payments' events out of the connected calendar: the ones asked for, or (None) every one for a payment
    cancelled, paid or no longer planned. Only events Accnomos tagged `billpay:` are touched."""
    today = today or london_today()
    sched = await bp.load_scheduled(books)
    if event_ids is None:
        event_ids = (await upcoming(books, today=today)).calendar_stale
    ours = await _ours(calendar, today)
    res = CalendarResult()
    done: list[str] = []
    for eid in event_ids:
        target = ours.get(eid)
        saved = sched.calendar.get(eid)
        cal_id = target.id if target is not None else saved.calendar_event_id if saved is not None else None
        if cal_id is None:
            res.not_found += 1
            done.append(eid)
            continue
        try:
            await calendar.delete_event(cal_id)
            res.removed += 1
        except FileNotFoundError:
            res.not_found += 1
        done.append(eid)

    def change(st: bp.Scheduled) -> None:
        for eid in done:
            st.calendar.pop(eid, None)

    await bp.update_scheduled(books, change)
    await books.audit(
        f"user:{user}", "billpay_calendar_removed", {"bills": done, "removed": res.removed, "not_found": res.not_found}
    )
    return res
