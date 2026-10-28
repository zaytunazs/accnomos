"""Find and recode: search posted lines, then move chosen lines to another account or VAT code.

History is never edited. A recode appends one `adjustment` per original entry, dated like it, that takes each line
off its current coding and puts it on the new one (so the trial balance stays balanced and every report for that
period reads the corrected coding). The adjustment lists what it did in `recodes` (event, line, new account, new
VAT code, new amount), so the current coding of a line is the original, then each recode in order.

- **Account recode**: Dr new / Cr old for a debit line (the other way round for a credit), same amount and VAT code.
  The VAT return is untouched. Income moves only between revenue accounts; spending between cost, fixed asset and
  current asset accounts (so a purchase can be capitalised as a fixed asset).
- **VAT recode** (a sale or purchase whose VAT sits on one line): the gross stays what was paid or invoiced; code
  works out the VAT at the new rate (20% → gross × 20/120, 5% → × 5/105, zero, exempt, outside scope or no VAT
  invoice → none reclaimed or charged), and the adjustment carries the change in net and VAT on the right side of
  the return (`vat_box`).
- Refused, with a plain sentence: lines on control and bank accounts (debtors, creditors, VAT control, payroll,
  bank, cash: their detail lives in invoices, bills, the VAT return and bank lines); entries dated in a VAT period
  already submitted; undone entries.

Recoding is the user's action: `confirm: true` on the request, after the preview of the same request.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

from accnomos_ledger.events import LedgerEvent, Line, Recode, VatCode
from app.approve import submitted_spans
from app.books import Books, now
from app.chart import CONTROL_ACCOUNTS, Account, ChartError, active_account, find, load_chart
from app.deadlines import period_label
from app.journal import BANK, CASH, VAT_CONTROL
from app.validation import StrictBody

VatLetter = Literal["S", "R", "Z", "E", "O", "N"]
RATES = {"S": 20, "R": 5}
SALES_CODES = {"S", "R", "Z", "E", "O"}
MAX_RESULTS = 500


class RecodeError(ValueError):
    """The lines cannot be recoded as asked."""


class LineState(BaseModel):
    account: str
    vat_code: str | None
    amount: int
    side: Literal["debit", "credit"]


def _recode_events(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    return sorted((e for e in events if e.recodes), key=lambda e: (e.approved_at, e.id))


def current_state(events: Sequence[LedgerEvent]) -> tuple[dict[tuple[str, int], LineState], dict[str, int]]:
    """Each line's coding now ((event id, index) -> state), and each recoded entry's VAT now (event id -> pence)."""
    lines: dict[tuple[str, int], LineState] = {}
    for e in events:
        for i, ln in enumerate(e.lines):
            lines[(e.id, i)] = LineState(
                account=ln.account,
                vat_code=ln.vat_code.value if ln.vat_code else None,
                amount=ln.debit or ln.credit,
                side="debit" if ln.debit else "credit",
            )
    vat: dict[str, int] = {}
    for r in (r for e in _recode_events(events) for r in e.recodes):
        if (key := (r.event_id, r.line)) in lines:
            st = lines[key]
            lines[key] = st.model_copy(
                update={"account": r.account, "vat_code": r.vat_code.value if r.vat_code else None, "amount": r.amount}
            )
            if r.vat is not None:
                vat[r.event_id] = r.vat
    return lines, vat


class FoundLine(BaseModel):
    event_id: str
    line: int
    date: date
    kind: str
    counterparty: str | None
    memo: str | None
    account: str  # as it is coded now
    vat_code: str | None
    debit_pence: int
    credit_pence: int
    recoded: bool  # changed by an earlier recode
    recodable: bool
    vat_recodable: bool
    reason: str | None = None  # why it can't be recoded


class SearchResult(BaseModel):
    lines: list[FoundLine]
    truncated: bool


def _bank_like(label: str, chart: Sequence[Account]) -> bool:
    a = find(chart, label)
    return label in (BANK, CASH) or (a is not None and a.type == "bank")


def _vat_line_index(e: LedgerEvent) -> int | None:
    """The one line of a sale or purchase that its VAT belongs to, or None (no VAT side, or VAT over several lines)."""
    if e.kind not in ("sale", "purchase"):
        return None
    coded = [i for i, ln in enumerate(e.lines) if ln.vat_code is not None and ln.account != VAT_CONTROL]
    return coded[0] if len(coded) == 1 else None


def _blocked(
    e: LedgerEvent, state: LineState, chart: Sequence[Account], submitted: dict[tuple[date, date], str]
) -> str | None:
    if state.account in CONTROL_ACCOUNTS or _bank_like(state.account, chart):
        return f"{state.account} is kept by invoices, bills, the VAT return or bank lines, so it can't be recoded"
    if find(chart, state.account) is None:
        return f"{state.account} is not in your chart of accounts"
    if span := next((s for s in submitted if s[0] <= e.date <= s[1]), None):
        return f"The VAT return for {period_label(*span)} has been submitted, so entries dated in it can't be recoded"
    return None


async def _context(books: Books):
    events = await books.list_events()
    try:
        chart, _ = await load_chart(books)
    except ChartError as exc:
        raise RecodeError(str(exc)) from exc
    return events, chart, await submitted_spans(books)


def _candidates(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    """Entries whose lines can be found: not reversals or mirrors (an undo, a voided journal, an unwound recode), not
    undone or voided, not recodes themselves."""
    gone = {e.reverses for e in events if e.reverses}
    return [e for e in events if e.kind != "reversal" and not e.reverses and e.id not in gone and not e.recodes]


async def search(
    books: Books,
    *,
    account: str | None = None,
    contact: str | None = None,
    start: date | None = None,
    end: date | None = None,
    min_pence: int | None = None,
    max_pence: int | None = None,
    vat_code: str | None = None,
) -> SearchResult:
    events, chart, submitted = await _context(books)
    lines, _ = current_state(events)
    out: list[FoundLine] = []
    for e in _candidates(events):
        if (start and e.date < start) or (end and e.date > end):
            continue
        if contact and contact.strip().casefold() not in (e.counterparty or "").casefold():
            continue
        vat_idx = _vat_line_index(e)
        for i, ln in enumerate(e.lines):
            st = lines[(e.id, i)]
            if account and not st.account.startswith(account.strip()[:4]):
                continue
            if vat_code and st.vat_code != vat_code:
                continue
            if (min_pence is not None and st.amount < min_pence) or (max_pence is not None and st.amount > max_pence):
                continue
            reason = _blocked(e, st, chart, submitted)
            out.append(
                FoundLine(
                    event_id=e.id,
                    line=i,
                    date=e.date,
                    kind=e.kind,
                    counterparty=e.counterparty,
                    memo=ln.memo,
                    account=st.account,
                    vat_code=st.vat_code,
                    debit_pence=st.amount if st.side == "debit" else 0,
                    credit_pence=st.amount if st.side == "credit" else 0,
                    recoded=(st.account, st.vat_code, st.amount)
                    != (ln.account, ln.vat_code.value if ln.vat_code else None, ln.debit or ln.credit),
                    recodable=reason is None,
                    vat_recodable=reason is None and vat_idx == i,
                    reason=reason,
                )
            )
    out.sort(key=lambda f: (f.date, f.event_id, f.line), reverse=True)
    return SearchResult(lines=out[:MAX_RESULTS], truncated=len(out) > MAX_RESULTS)


class LineRef(StrictBody):
    event_id: str = Field(pattern=r"^[0-9a-f]{8,64}$", max_length=64)
    line: int = Field(ge=0, le=500)


class RecodeIn(StrictBody):
    lines: list[LineRef] = Field(min_length=1, max_length=200)
    account: str | None = Field(None, max_length=90)  # the new account; None keeps each line's account
    vat_code: VatLetter | None = None  # the new VAT code; None keeps it
    confirm: bool = False  # false: preview only


class ProposedLine(BaseModel):
    account: str
    debit_pence: int
    credit_pence: int
    vat_code: str | None


class ProposedEvent(BaseModel):
    original_event_id: str
    date: date
    counterparty: str | None
    lines: list[ProposedLine]
    vat_box: str | None
    net_change_pence: int | None
    vat_change_pence: int | None
    event_id: str


class RecodeResult(BaseModel):
    posted: bool
    events: list[ProposedEvent]
    lines_recoded: int


def _round(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _group(account: Account) -> str:
    return "income" if account.type == "revenue" else "spend"


def _on_return(code: str | None, amount: int) -> int:
    return amount if code and code != "O" else 0


def build_recodes(
    events: Sequence[LedgerEvent],
    chart: Sequence[Account],
    submitted: dict[tuple[date, date], str],
    body: RecodeIn,
    user: str,
) -> list[LedgerEvent]:
    if body.account is None and body.vat_code is None:
        raise RecodeError("Choose the account or the VAT code to recode to")
    target: Account | None = None
    if body.account:
        try:
            target = active_account(chart, body.account)
        except ChartError as exc:
            raise RecodeError(str(exc)) from exc
        if target.label in CONTROL_ACCOUNTS or _bank_like(target.label, chart):
            raise RecodeError(
                f"{target.label} is kept by invoices, bills, the VAT return or bank lines; choose another"
            )
    lines, vat_now = current_state(events)
    by_id = {e.id: e for e in _candidates(events)}
    picked: dict[str, list[int]] = {}
    for ref in body.lines:
        if ref.event_id not in by_id:
            raise RecodeError("A chosen line is not in the books any more (it may have been undone or recoded)")
        e = by_id[ref.event_id]
        if ref.line >= len(e.lines):
            raise RecodeError("A chosen line is not in the books any more")
        picked.setdefault(ref.event_id, [])
        if ref.line not in picked[ref.event_id]:
            picked[ref.event_id].append(ref.line)
    out: list[LedgerEvent] = []
    for eid, idxs in picked.items():
        e = by_id[eid]
        new_lines: list[Line] = []
        refs: list[Recode] = []
        net_change = vat_change = 0
        vat_box: Literal["sales", "purchases"] | None = None
        for i in sorted(idxs):
            st = lines[(eid, i)]
            if reason := _blocked(e, st, chart, submitted):
                raise RecodeError(reason)
            orig = e.lines[i]
            source = find(chart, st.account)
            assert source is not None  # _blocked checked it
            dest = target or source
            if _group(dest) != _group(source):
                raise RecodeError(
                    f"{st.account} is {'income' if _group(source) == 'income' else 'spending'}, so it can't move to "
                    f"{dest.label}"
                )
            memo = f"Recode of {eid[:8]} line {i + 1}"
            if body.vat_code is None or body.vat_code == st.vat_code:
                if dest.label == st.account:
                    raise RecodeError(f"Line {i + 1} of that entry is already on {dest.label}")
                debit = st.side == "debit"
                new_lines += [
                    Line(
                        account=dest.label,
                        debit=st.amount if debit else 0,
                        credit=0 if debit else st.amount,
                        vat_code=None if st.vat_code is None else VatCode(st.vat_code),
                        memo=memo,
                        tracking=orig.tracking,
                    ),
                    Line(
                        account=st.account,
                        debit=0 if debit else st.amount,
                        credit=st.amount if debit else 0,
                        vat_code=None if st.vat_code is None else VatCode(st.vat_code),
                        memo=memo,
                        tracking=orig.tracking,
                    ),
                ]
                refs.append(
                    Recode(
                        event_id=eid,
                        line=i,
                        account=dest.label,
                        vat_code=None if st.vat_code is None else VatCode(st.vat_code),
                        amount=st.amount,
                    )
                )
                continue
            # VAT recode: keep the gross, work out the VAT again at the new rate.
            if _vat_line_index(e) != i:
                raise RecodeError(
                    "Only a sale or purchase whose VAT is on one line can have its VAT code changed here; "
                    "undo the entry and post it again instead"
                )
            sale = e.kind == "sale"
            if sale and body.vat_code not in SALES_CODES:
                raise RecodeError("A sale can't be coded as having no VAT invoice (N); choose another code")
            vat_box = "sales" if sale else "purchases"
            old_vat = vat_now.get(eid, e.vat or 0)
            gross = st.amount + old_vat
            rate = RATES.get(body.vat_code or "", 0)
            new_vat = _round(Decimal(gross) * rate / (100 + rate)) if rate else 0
            new_net = gross - new_vat
            # Sales lines are credits and purchase lines debits: take the old coding off, put the new one on.
            off, on = ("debit", "credit") if sale else ("credit", "debit")
            new_code = VatCode(body.vat_code)  # type: ignore[arg-type]
            old_code = VatCode(st.vat_code) if st.vat_code else None

            def line(
                account: str, amount: int, side: str, code: VatCode | None, memo: str = memo, src: Line = orig
            ) -> Line:
                return Line(
                    account=account,
                    debit=amount if side == "debit" else 0,
                    credit=amount if side == "credit" else 0,
                    vat_code=code,
                    memo=memo,
                    tracking=src.tracking,
                )

            new_lines.append(line(st.account, st.amount, off, old_code))
            if old_vat:
                new_lines.append(line(VAT_CONTROL, old_vat, off, old_code))
            new_lines.append(line(dest.label, new_net, on, new_code))
            if new_vat:
                new_lines.append(line(VAT_CONTROL, new_vat, on, new_code))
            net_change += _on_return(new_code.value, new_net) - _on_return(st.vat_code, st.amount)
            vat_change += new_vat - old_vat
            refs.append(
                Recode(event_id=eid, line=i, account=dest.label, vat_code=new_code, amount=new_net, vat=new_vat)
            )
        state_key = "|".join(f"{r.line}:{lines[(eid, r.line)].account}:{lines[(eid, r.line)].vat_code}" for r in refs)
        target_key = f"{body.account or ''}:{body.vat_code or ''}"
        out.append(
            LedgerEvent(
                id=hashlib.sha256(f"recode:{eid}:{state_key}:{target_key}".encode()).hexdigest()[:32],
                kind="adjustment",
                date=e.date,
                lines=new_lines,
                evidence=e.evidence,
                approved_by=user,
                approved_at=now(),
                counterparty=e.counterparty,
                recodes=refs,
                vat_box=vat_box,
                net=net_change if vat_box else None,
                vat=vat_change if vat_box else None,
            )
        )
    return out


def _proposed(original: str, e: LedgerEvent) -> ProposedEvent:
    return ProposedEvent(
        original_event_id=original,
        date=e.date,
        counterparty=e.counterparty,
        lines=[
            ProposedLine(
                account=ln.account,
                debit_pence=ln.debit,
                credit_pence=ln.credit,
                vat_code=ln.vat_code.value if ln.vat_code else None,
            )
            for ln in e.lines
        ],
        vat_box=e.vat_box,
        net_change_pence=e.net,
        vat_change_pence=e.vat,
        event_id=e.id,
    )


async def recode(books: Books, body: RecodeIn, user: str) -> RecodeResult:
    """Preview (confirm false) or post the adjusting entries."""
    events, chart, submitted = await _context(books)
    built = build_recodes(events, chart, submitted, body, user)
    result = RecodeResult(
        posted=False,
        events=[_proposed(e.recodes[0].event_id, e) for e in built],
        lines_recoded=sum(len(e.recodes) for e in built),
    )
    if not body.confirm:
        return result
    for e in built:
        try:
            await books.post_event(e)
        except FileExistsError:
            continue  # a retried request: that entry is already recoded
    await books.audit(
        f"user:{user}",
        "lines_recoded",
        {
            "events": [e.id for e in built],
            "originals": [e.recodes[0].event_id for e in built],
            "lines": result.lines_recoded,
            "account": body.account,
            "vat_code": body.vat_code,
        },
    )
    await books.rebuild_safely(f"user:{user}")
    return result.model_copy(update={"posted": True})


async def unwind_recodes(books: Books, original: LedgerEvent, user: str, on: date) -> list[str]:
    """When an entry is undone, cancel the recodes of its lines too (each by its mirror adjustment, dated `on`), so
    no recoded amount is left on an account once the entry itself is gone. Returns the ids posted."""
    events = await books.list_events()
    posted = []
    for e in _recode_events(events):
        if not any(r.event_id == original.id for r in e.recodes):
            continue
        mirror = LedgerEvent(
            id=hashlib.sha256(f"{e.id}:unwind".encode()).hexdigest()[:32],
            kind="adjustment",
            date=on,
            lines=[
                ln.model_copy(update={"debit": ln.credit, "credit": ln.debit, "memo": f"Undo of recode {e.id[:8]}"})
                for ln in e.lines
            ],
            evidence=e.evidence,
            approved_by=user,
            approved_at=now(),
            counterparty=e.counterparty,
            reverses=e.id,
            vat_box=e.vat_box,
            net=None if e.net is None else -e.net,
            vat=None if e.vat is None else -e.vat,
        )
        try:
            await books.post_event(mirror)
        except FileExistsError:
            continue
        posted.append(mirror.id)
    return posted
