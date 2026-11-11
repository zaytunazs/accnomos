"""PayPal disputes on payments Accnomos knows about: the evidence comes from the books, the owner sends it.

When a customer opens a PayPal dispute (or chargeback) on a payment made through an invoice's PayPal link
(app/online_payments.py), Accnomos:

1. **Finds it and matches it** (`list_disputes`). PayPal's dispute names the disputed transaction
   (`disputed_transactions[].seller_transaction_id`) and the PayPal invoice number. It is one of ours when that
   transaction is a payment recorded from an invoice's link (`Invoice.online_payments`) or the PayPal invoice
   number is the one `PayPalApi.create_invoice` gave the invoice's current link (`{number}-{ref[:6]}`, or `-1` after
   the single-line fall-back). Anything else is listed as not one of ours and is never touched.
2. **Builds the evidence** (`build_evidence`), only when the owner asks. Code gathers the facts from the books: the
   invoice and its lines, when and to whom it was emailed (and the SHA-256 of the exact PDF), the payment and when
   it came in, reminders, the invoice's audit trail, the customer's other invoices (a short statement) and, for an
   invoice written from a job's hours, the timesheet entries it billed. Nothing about delivery exists in the books
   (no carrier or tracking data), so nothing about it is claimed. The model (the user's own AI settings, as for
   reminders in app/ai/remind.py) drafts a short factual response for PayPal from those facts as strict JSON; code
   then checks it: every figure must be a figure in the facts, every date must be a date in the facts, the invoice
   number must be in it, no links, at most 2,000 characters (PayPal's `notes` limit). Anything else, or any model
   trouble, and code writes the response itself from the facts. One evidence PDF is made: a summary page with the
   facts and the response, then the invoice exactly as it was emailed.
3. **Sends nothing on its own.** The proposal (response + PDF) is saved; the owner previews it and taps *Send to
   PayPal* (`send_evidence`, `confirm: true`), which re-reads the dispute from PayPal, checks it still waits for the
   seller and that the PDF is the one previewed (SHA-256), and only then calls provide-evidence.
4. **When the dispute is lost** (`dispute_outcome.outcome_code` RESOLVED_BUYER_FAVOUR, or the owner accepted the
   claim) and PayPal refunded the whole payment, the reversing entry is proposed: the recorded PayPal payment is
   taken back (app/payments.remove_payment: Dr 1100 Debtors / Cr 1240 PayPal clearing), so the invoice is open again
   and the owner decides between a credit note and chasing. It is posted only on the owner's yes. A partial refund
   is shown, never posted: a credit note for that amount is the owner's call. PayPal's fee is left as it was.

Every build, send and reversal is audit-logged. Files: `_System/Payments/disputes.json` (one record per dispute
built) and `03 Sales/disputes/{dispute id}.pdf` (the evidence PDF that was previewed and sent).

**Demo sandbox.** A demo session shows one SAMPLE dispute on its most recent PayPal-linked invoice (or, with none,
its most recent paid invoice), shaped by app/online_fakes.dispute_shape. Building evidence for it is the same code;
"sending" it calls nothing and is recorded as "Demo: not sent to PayPal". In test mode (`ACCNOMOS_TEST_MODE=1`)
the PayPal fake in app/online_fakes.py holds disputes (`FAKES.open_dispute`, `/__test/paypal/dispute/{invoice}`).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ValidationError

from app import paths
from app.ai import chain
from app.ai.ask import KnownNumbers, call_json_model
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.books import SYSTEM, Books, now
from app.books import today as london_today
from app.invoicing import Invoice, InvoiceError, InvoiceProfile, list_invoices, load_profile, money, uk_date
from app.online_payments import (
    JournalPreview,
    OnlinePaymentError,
    load_connections,
    paypal_config,
)
from app.payment_providers import PayPalApi, ProviderError, client, pence_from_paypal
from app.schemas import strict_json_schema

DISPUTES = f"{SYSTEM}/Payments/disputes.json"
EVIDENCE_DIR = f"{paths.SALES}/disputes"
NOTES_MAX = 2000  # PayPal's `evidence.notes` maxLength (Disputes v1 schema 1.12)
DETAILS_MAX = 20  # disputes read in full per list
SAMPLE_PREFIX = "PP-D-SAMPLE-"
LINK = re.compile(r"https?://|www\.", re.IGNORECASE)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTH_WORD = rf"(?:{MONTHS}|{'|'.join(m[:3] for m in MONTHS.split('|'))})"
_DATE_PATTERNS = (
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_WORD})\.?,?\s+(\d{{4}})\b", re.IGNORECASE),
    re.compile(rf"\b({_MONTH_WORD})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
)
REASONS = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "says the goods or service were not received",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "says the goods or service were not as described",
    "UNAUTHORISED": "says they did not authorise the payment",
    "CREDIT_NOT_PROCESSED": "says a refund or credit was not processed",
    "DUPLICATE_TRANSACTION": "says they were charged twice",
    "INCORRECT_AMOUNT": "says the amount was wrong",
    "PAYMENT_BY_OTHER_MEANS": "says they paid another way",
    "CANCELED_RECURRING_BILLING": "says a cancelled subscription was charged",
    "PROBLEM_WITH_REMITTANCE": "reports a problem with the payment",
    "OTHER": "has opened a dispute",
}

SYSTEM_PROMPT = (
    "You write a short, factual response to a PayPal dispute for a UK small business, to be read by PayPal's "
    "dispute team. Plain UK English, polite, no more than 180 words, plain text (no markdown). "
    "You are given FACTS as JSON, worked out by code from the business's books. Rules: "
    "1) State only what FACTS say: what was invoiced, when and to whom it was emailed, when it was paid, the work "
    "logged, the customer's history. Never claim delivery, tracking, signatures or conversations that are not "
    "in FACTS. "
    "2) Quote every amount, date, invoice number and transaction id exactly as FACTS has it; never calculate. "
    "3) Answer FACTS.dispute_reason directly. Do not accuse the customer, threaten, or mention fees or legal action. "
    "4) No links. Say the attached PDF has the invoice as emailed and the record from the books. "
    "Return JSON with `notes`."
)


class DisputeError(OnlinePaymentError):
    """Cannot do this with the dispute (a 400)."""


class EvidenceModelOutput(BaseModel):
    notes: str


class EvidenceProposal(BaseModel):
    """What the owner previews and, with a yes, sends (one record per dispute in `DISPUTES`)."""

    dispute_id: str
    invoice: str
    evidence_type: str = "OTHER"
    notes: str
    model: str
    fallback_reason: str | None = None  # the model's words were replaced by a response written by code
    facts: dict[str, Any]
    pdf_path: str
    pdf_sha256: str
    built_at: datetime
    built_by: str
    status: Literal["proposed", "sent"] = "proposed"
    sent_at: datetime | None = None
    sent_by: str | None = None
    demo: bool = False  # a demo's sample dispute: "sent" without calling PayPal
    reversal_payment: str | None = None  # the payment record taken back after the dispute was lost
    reversal_at: datetime | None = None


class ReversalProposal(BaseModel):
    payment_record: str
    amount_pence: int
    refunded_pence: int | None
    can_post: bool
    reason: str | None = None  # why it cannot be posted by code
    journal: list[JournalPreview]


class DisputeRow(BaseModel):
    dispute_id: str
    sample: bool = False
    reason: str
    reason_text: str
    status: str
    state: str | None = None
    stage: str | None = None
    amount_pence: int | None
    respond_by: date | None = None
    opened: date | None = None
    invoice: str | None = None  # the Accnomos invoice it matched, None: not one of ours
    customer: str | None = None
    transaction_id: str | None = None
    can_send_evidence: bool
    outcome: str | None = None
    lost: bool = False
    proposal: EvidenceProposal | None = None
    reversal: ReversalProposal | None = None


class DisputeList(BaseModel):
    connected: bool
    disputes: list[DisputeRow]
    problem: str | None = None  # PayPal could not be asked, in a sentence


# --------------------------------------------------------------------------- #
# Reading disputes and matching them to invoices
# --------------------------------------------------------------------------- #


def _day(raw: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def paypal_numbers(inv: Invoice) -> set[str]:
    link = inv.payment_link
    if link is None or link.provider != "paypal":
        return set()
    base = f"{inv.number}-{link.ref[:6]}"
    return {base, f"{base}-1"}


def match(dispute: dict[str, Any], invoices: list[Invoice]) -> tuple[Invoice | None, str | None]:
    """(the invoice, the disputed transaction id) for a dispute, or (None, id) when it is not one of ours."""
    txs = [t for t in dispute.get("disputed_transactions") or [] if isinstance(t, dict)]
    tid = next((str(t["seller_transaction_id"]) for t in txs if t.get("seller_transaction_id")), None)
    for t in txs:
        sid, num = t.get("seller_transaction_id"), t.get("invoice_number")
        for inv in invoices:
            if (sid and str(sid) in inv.online_payments) or (num and str(num) in paypal_numbers(inv)):
                return inv, str(sid) if sid else tid
    return None, tid


async def _paypal_invoices(books: Books) -> list[Invoice]:
    return [i for i in await list_invoices(books) if i.payment_link and i.payment_link.provider == "paypal"]


def _sample_for(invoices: list[Invoice]) -> tuple[dict[str, Any], Invoice] | None:
    """The demo's SAMPLE dispute: on the latest PayPal-linked sent or paid invoice, else the latest paid one."""
    from app.online_fakes import dispute_shape

    live = [i for i in invoices if i.status in ("sent", "paid")]
    linked = [i for i in live if i.payment_link and i.payment_link.provider == "paypal"]
    pool = linked or [i for i in live if i.status == "paid"]
    if not pool:
        return None
    inv = max(pool, key=lambda i: (i.issue_date, i.number))
    numbers = sorted(paypal_numbers(inv)) or [inv.number]
    tid = (
        inv.online_payments[0]
        if inv.online_payments
        else f"SAMPLE{hashlib.sha256(inv.number.encode()).hexdigest()[:11].upper()}"
    )
    opened = max(inv.issue_date, london_today() - timedelta(days=2))
    d = dispute_shape(
        f"{SAMPLE_PREFIX}{inv.number}",
        paypal_invoice_number=numbers[0],
        transaction_id=tid,
        amount_pence=inv.total_pence,
        reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        created=f"{opened.isoformat()}T10:00:00.000Z",
        due=f"{(opened + timedelta(days=10)).isoformat()}T10:00:00.000Z",
    )
    d["disputed_transactions"][0]["buyer"] = {"name": f"{inv.customer.name} (sample)"}
    return d, inv


async def _records(books: Books) -> dict[str, EvidenceProposal]:
    raw = await books.read_json(DISPUTES, {})
    out: dict[str, EvidenceProposal] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            with contextlib.suppress(ValidationError, TypeError):
                out[k] = EvidenceProposal.model_validate(v)
    return out


async def _save_record(books: Books, rec: EvidenceProposal) -> None:
    payload = rec.model_dump(mode="json")

    def change(old: Any) -> dict[str, Any]:
        cur = dict(old) if isinstance(old, dict) else {}
        cur[rec.dispute_id] = payload
        return cur

    await books._update_json(DISPUTES, {}, change)


def _can_send(d: dict[str, Any]) -> bool:
    if d.get("status") != "WAITING_FOR_SELLER_RESPONSE":
        return False
    links = d.get("links")
    if not isinstance(links, list) or not any(isinstance(x, dict) and "rel" in x for x in links):
        return True  # a list summary carries only `self`; the full dispute is read again before sending
    return any(isinstance(x, dict) and x.get("rel") == "provide_evidence" for x in links)


def _lost(d: dict[str, Any]) -> bool:
    code = ((d.get("dispute_outcome") or {}).get("outcome_code")) or ""
    return d.get("status") == "RESOLVED" and code in ("RESOLVED_BUYER_FAVOUR", "ACCEPTED")


async def _payment_record(books: Books, tid: str | None) -> Any:
    if not tid:
        return None
    from app import payments

    reference = f"PayPal {tid}"[:120]
    return next((r for r in await payments._records(books) if r.reference == reference and r.removed_at is None), None)


async def _reversal(books: Books, d: dict[str, Any], tid: str | None) -> ReversalProposal | None:
    if not _lost(d):
        return None
    rec = await _payment_record(books, tid)
    if rec is None:
        return None
    refunded = pence_from_paypal((d.get("dispute_outcome") or {}).get("amount_refunded"))
    full = refunded is not None and refunded >= rec.amount_pence
    return ReversalProposal(
        payment_record=rec.id,
        amount_pence=rec.amount_pence,
        refunded_pence=refunded,
        can_post=full,
        reason=None
        if full
        else (
            f"PayPal refunded {money(refunded)} of the {money(rec.amount_pence)} payment; record a credit note for "
            "that amount instead"
            if refunded
            else "PayPal has not said how much it refunded; check the dispute in PayPal"
        ),
        journal=[
            JournalPreview(account="1100 Debtors", debit_pence=rec.amount_pence),
            JournalPreview(account="1240 PayPal clearing", credit_pence=rec.amount_pence),
        ],
    )


def _row(d: dict[str, Any], inv: Invoice | None, tid: str | None, sample: bool) -> DisputeRow:
    reason = str(d.get("reason") or "OTHER")
    return DisputeRow(
        dispute_id=str(d["dispute_id"]),
        sample=sample,
        reason=reason,
        reason_text=REASONS.get(reason, REASONS["OTHER"]),
        status=str(d.get("status") or "OTHER"),
        state=d.get("dispute_state"),
        stage=d.get("dispute_life_cycle_stage"),
        amount_pence=pence_from_paypal(d.get("dispute_amount")),
        respond_by=_day(d.get("seller_response_due_date")),
        opened=_day(d.get("create_time")),
        invoice=inv.number if inv else None,
        customer=inv.customer.name if inv else None,
        transaction_id=tid,
        can_send_evidence=inv is not None and _can_send(d),
        outcome=((d.get("dispute_outcome") or {}).get("outcome_code")),
        lost=_lost(d),
    )


async def _api() -> tuple[PayPalApi, httpx.AsyncClient] | None:
    cfg, _why = paypal_config()
    if cfg is None:
        return None
    http = client()
    return PayPalApi(cfg, http), http


async def list_disputes(books: Books, *, sample: bool = False) -> DisputeList:
    """PayPal's disputes on the connected account, matched to invoices, newest first, with any saved proposal and,
    for a lost one, the reversing entry proposed. Reads only. `sample`: a demo session (adds its SAMPLE dispute)."""
    c = await load_connections(books)
    invoices = await list_invoices(books)
    records = await _records(books)
    found: list[tuple[dict[str, Any], bool]] = []
    problem = None
    got = await _api() if c.paypal else None
    if c.paypal and got is None:
        problem = paypal_config()[1]
    if got is not None and c.paypal:
        api, http = got
        merchant = c.paypal.merchant_id
        async with http:
            try:
                summaries = await api.list_disputes(merchant)
                gate = asyncio.Semaphore(4)

                async def full(s: dict[str, Any]) -> dict[str, Any]:
                    async with gate:
                        try:
                            return await api.dispute(merchant, str(s["dispute_id"]))
                        except ProviderError:
                            return s  # the summary still lists it; it just cannot be matched

                found += [(d, False) for d in await asyncio.gather(*(full(s) for s in summaries[:DETAILS_MAX]))]
            except ProviderError as exc:
                problem = f"PayPal could not be asked about disputes: {exc.message}"
    demo = _sample_for(invoices) if sample else None
    if demo is not None:
        found.append((demo[0], True))
    rows = []
    for d, is_sample in found:
        if not d.get("dispute_id"):
            continue
        inv, tid = match(d, invoices)
        if is_sample and inv is None and demo is not None:
            inv = demo[1]
        row = _row(d, inv, tid, is_sample)
        row.proposal = records.get(row.dispute_id)
        if inv is not None and not is_sample:
            row.reversal = await _reversal(books, d, tid)
            if row.reversal and row.proposal and row.proposal.reversal_payment:
                row.reversal = None  # already posted
        rows.append(row)
    rows.sort(key=lambda r: (r.opened or date.min, r.dispute_id), reverse=True)
    return DisputeList(connected=c.paypal is not None or sample, disputes=rows, problem=problem)


async def _dispute(books: Books, dispute_id: str, *, sample: bool) -> tuple[dict[str, Any], Invoice, str | None]:
    """The dispute read again (from PayPal, or the demo's sample) and its invoice; DisputeError when not ours."""
    invoices = await list_invoices(books)
    if dispute_id.startswith(SAMPLE_PREFIX):
        s = _sample_for(invoices) if sample else None
        if s is None or s[0]["dispute_id"] != dispute_id:
            raise DisputeError("No such dispute")
        return s[0], s[1], s[0]["disputed_transactions"][0]["seller_transaction_id"]
    if not re.fullmatch(r"[A-Za-z0-9-]{1,255}", dispute_id):
        raise DisputeError("No such dispute")
    c = await load_connections(books)
    got = await _api() if c.paypal else None
    if got is None or c.paypal is None:
        raise DisputeError("Connect PayPal in Settings › Online payments first")
    api, http = got
    async with http:
        try:
            d = await api.dispute(c.paypal.merchant_id, dispute_id)
        except ProviderError as exc:
            raise DisputeError(f"PayPal could not show the dispute: {exc.message}") from exc
    inv, tid = match(d, invoices)
    if inv is None:
        raise DisputeError("This dispute is not on a payment Accnomos knows about; answer it in PayPal")
    return d, inv, tid


# --------------------------------------------------------------------------- #
# Facts from the books
# --------------------------------------------------------------------------- #


async def _audit_trail(books: Books, inv: Invoice) -> list[dict[str, str]]:
    from app import audit_view

    start = inv.created_at.date() - timedelta(days=1) if inv.created_at else inv.issue_date
    page = await audit_view.read(books, min(start, inv.issue_date), london_today(), limit=500)
    rows = [e for e in page.entries if e.refs.invoice == inv.number]
    rows.sort(key=lambda e: e.ts)
    return [{"date": uk_date(e.ts.date()), "what": e.summary} for e in rows[:15]]


async def _timesheets(books: Books, inv: Invoice) -> list[dict[str, Any]]:
    ids = set(inv.timesheet_entry_ids())
    if not ids:
        return []
    from app import jobs

    with contextlib.suppress(Exception):
        entries = [e for e in await jobs.load_entries(books) if e.id in ids]
        entries.sort(key=lambda e: e.date)
        return [{"date": uk_date(e.date), "hours": e.hours, "note": e.note} for e in entries[:30]]
    return []


async def _statement(books: Books, inv: Invoice) -> dict[str, Any]:
    """The customer's other invoices, briefly: how many were paid and for how much."""
    same = [
        i
        for i in await list_invoices(books)
        if i.number != inv.number
        and i.status in ("sent", "paid")
        and (
            (inv.customer.contact_id and i.customer.contact_id == inv.customer.contact_id)
            or i.customer.name.strip().lower() == inv.customer.name.strip().lower()
        )
    ]
    paid = [i for i in same if i.status == "paid"]
    return {
        "other_invoices": len(same),
        "other_invoices_paid": len(paid),
        "other_paid_total": money(sum(i.total_pence for i in paid)),
        "first_invoice_date": uk_date(min(i.issue_date for i in same)) if same else None,
    }


def _dates_in(node: Any) -> set[date]:
    out: set[date] = set()
    if isinstance(node, dict):
        for v in node.values():
            out |= _dates_in(v)
    elif isinstance(node, list):
        for v in node:
            out |= _dates_in(v)
    elif isinstance(node, str):
        out |= found_dates(node)
    return out


def _month(name: str) -> int:
    return next(i for i, m in enumerate(MONTHS.split("|"), 1) if m.lower().startswith(name.lower()[:3]))


def found_dates(text: str) -> set[date]:
    """Every date written in the text (6 November 2026, November 6, 2026, 06/11/2026, 2026-11-06)."""
    out: set[date] = set()
    for i, pat in enumerate(_DATE_PATTERNS):
        for m in pat.finditer(text):
            with contextlib.suppress(ValueError, StopIteration):
                g = m.groups()
                if i == 0:
                    out.add(date(int(g[2]), _month(g[1]), int(g[0])))
                elif i == 1:
                    out.add(date(int(g[2]), _month(g[0]), int(g[1])))
                elif i == 2:
                    out.add(date(int(g[2]), int(g[1]), int(g[0])))
                else:
                    out.add(date(int(g[0]), int(g[1]), int(g[2])))
    return out


async def gather_facts(books: Books, d: dict[str, Any], inv: Invoice, tid: str | None) -> dict[str, Any]:
    profile = await load_profile(books)
    rec = await _payment_record(books, tid)
    lines = [
        {
            "description": ln.description,
            "quantity": format(ln.quantity.normalize(), "f"),
            "unit": ln.unit,
            "amount_ex_vat": money(ln.net_pence),
        }
        for ln in inv.lines[:20]
    ]
    reason = str(d.get("reason") or "OTHER")
    return {
        "business_name": profile.name.strip() or None,
        "customer_name": inv.customer.name,
        "invoice_number": inv.number,
        "invoice_date": uk_date(inv.issue_date),
        "due_date": uk_date(inv.due_date),
        "invoice_total": money(inv.total_pence),
        "invoice_vat": money(inv.vat_pence),
        "reference": inv.reference,
        "lines": lines,
        "dispute_id": str(d.get("dispute_id")),
        "dispute_reason": REASONS.get(reason, REASONS["OTHER"]),
        "amount_disputed": money(pence_from_paypal(d.get("dispute_amount")) or 0),
        "dispute_opened": uk_date(o) if (o := _day(d.get("create_time"))) else None,
        "emailed": (
            {"date": uk_date(inv.sent_at.date()), "to": inv.sent_to, "pdf_sha256": inv.pdf_sha256}
            if inv.sent_at
            else None
        ),
        "reminders": [uk_date(r.sent_at.date()) for r in inv.reminders],
        "payment": (
            {"date": uk_date(rec.date), "amount": money(rec.amount_pence), "paypal_transaction": tid}
            if rec is not None
            else ({"paypal_transaction": tid} if tid else None)
        ),
        "invoice_status": inv.status,
        "timesheets": await _timesheets(books, inv),
        "customer_history": await _statement(books, inv),
        "audit_trail": await _audit_trail(books, inv),
    }


# --------------------------------------------------------------------------- #
# The response: model words checked by code, or code's own
# --------------------------------------------------------------------------- #


def fallback_notes(f: dict[str, Any]) -> str:
    n = f["invoice_number"]
    parts = [
        f"Invoice {n} for {f['invoice_total']} was issued to {f['customer_name']} on {f['invoice_date']}"
        + (f" for: {'; '.join(ln['description'] for ln in f['lines'][:6])}." if f["lines"] else ".")
    ]
    if e := f["emailed"]:
        parts.append(f"It was emailed to {e['to']} on {e['date']}.")
    if ts := f["timesheets"]:
        hours = sum((Decimal(str(t["hours"])) for t in ts), Decimal(0))
        parts.append(
            f"The work was logged on {len(ts)} timesheet entr{'y' if len(ts) == 1 else 'ies'} "
            f"from {ts[0]['date']} to {ts[-1]['date']}, {format(hours.normalize(), 'f')} hours in all."
        )
    if (p := f["payment"]) and p.get("date"):
        parts.append(
            f"The customer paid {p['amount']} through PayPal on {p['date']} (transaction {p['paypal_transaction']})."
        )
    h = f["customer_history"]
    if k := h["other_invoices_paid"]:
        parts.append(
            f"The customer has paid {k} other invoice{'s' if k != 1 else ''} from us, {h['other_paid_total']} in all."
        )
    parts.append(
        f"The customer {f['dispute_reason']}. The attached PDF has invoice {n} exactly as it was emailed and the "
        "record of it from our books. We ask PayPal to resolve this dispute in our favour."
    )
    return " ".join(parts)[:NOTES_MAX]


def ground(out: EvidenceModelOutput, facts: dict[str, Any]) -> str:
    """The model's notes when every check passes; raises ValueError with the reason otherwise."""
    notes = out.notes.strip()
    if not notes:
        raise ValueError("The model returned an empty response.")
    if len(notes) > NOTES_MAX:
        raise ValueError("The model's response was longer than PayPal takes.")
    if LINK.search(notes):
        raise ValueError("The model's response contained a link.")
    if facts["invoice_number"] not in notes:
        raise ValueError("The model's response did not mention the invoice number.")
    if invented := KnownNumbers(facts).unknown(notes, all_tokens=False):
        raise ValueError(
            f"The model quoted figures that are not in the books ({', '.join(dict.fromkeys(invented[:3]))})."
        )
    if extra := found_dates(notes) - _dates_in(facts):
        raise ValueError(
            f"The model quoted dates that are not in the books ({', '.join(uk_date(x) for x in sorted(extra)[:3])})."
        )
    return notes


async def _call_model(messages: list[dict[str, str]], cfg: AiConfig) -> str:
    return await call_json_model(messages, cfg, strict_json_schema(EvidenceModelOutput), "dispute_evidence")


async def draft_notes(facts: dict[str, Any], cfg: AiConfig | None) -> tuple[str, str, str | None]:
    """(notes, model, fallback reason). Never raises for model trouble: code's response stands in, with the reason."""
    if cfg is None:
        return fallback_notes(facts), "code", "No AI is set up, so code wrote the response."
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}"},
    ]
    try:
        out = EvidenceModelOutput.model_validate(parse_model_json(await _call_model(messages, cfg)))
        return ground(out, facts), cfg.model, None
    except httpx.HTTPStatusError as exc:
        reason = chain.trouble(cfg, f"returned HTTP {exc.response.status_code}")
    except httpx.HTTPError:
        reason = chain.trouble(cfg, f"could not be reached at {cfg.base_url}")
    except (ExtractionError, ValidationError):
        reason = "The model's reply was not in the expected format."
    except ValueError as exc:
        reason = str(exc)
    return fallback_notes(facts), cfg.model, reason


# --------------------------------------------------------------------------- #
# The evidence PDF
# --------------------------------------------------------------------------- #


def render_evidence(facts: dict[str, Any], notes: str, invoice_pdf: bytes | None, sample: bool) -> bytes:
    """One PDF: the summary from the books and the response, then the invoice exactly as it was emailed."""
    from fpdf.enums import XPos, YPos

    from app.pdf import INK, LEFT, MUTED, _DocPdf, text

    title = f"Dispute {facts['dispute_id']}: evidence for invoice {facts['invoice_number']}"
    footer = " · ".join(
        p for p in (facts["business_name"] or "", "Prepared with Accnomos from the business's books") if p
    )
    pdf = _DocPdf(text(footer), False)
    pdf.set_title(text(title))
    pdf.set_creator("Accnomos")
    pdf.add_page()
    width = pdf._right - LEFT

    def para(s: str, size: int = 10, bold: bool = False, colour: tuple[int, int, int] = INK) -> None:
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.set_text_color(*colour)
        pdf.multi_cell(width, size * 0.5, text(s), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if sample:
        para("SAMPLE: a demo dispute on fictional books. Nothing here was sent to PayPal.", 9, True)
        pdf.ln(1)
    para(title, 14, True)
    para(f"Customer: {facts['customer_name']}. The customer {facts['dispute_reason']}.", 9, colour=MUTED)
    pdf.ln(2)
    para("Response", 11, True)
    para(notes)
    pdf.ln(2)
    para("From the books", 11, True)
    rows = [
        ("Invoice", f"{facts['invoice_number']}, dated {facts['invoice_date']}, due {facts['due_date']}"),
        ("Total", f"{facts['invoice_total']} (VAT {facts['invoice_vat']})"),
    ]
    if facts.get("reference"):
        rows.append(("Customer reference", str(facts["reference"])))
    if e := facts["emailed"]:
        rows.append(("Emailed", f"{e['date']} to {e['to']}"))
        if e.get("pdf_sha256"):
            rows.append(("PDF emailed (SHA-256)", str(e["pdf_sha256"])))
    if facts["reminders"]:
        rows.append(("Reminders", ", ".join(facts["reminders"])))
    if p := facts["payment"]:
        rows.append(
            (
                "PayPal payment",
                " ".join(
                    x
                    for x in (
                        p.get("amount"),
                        f"on {p['date']}" if p.get("date") else None,
                        f"(transaction {p.get('paypal_transaction')})",
                    )
                    if x
                ),
            )
        )
    h = facts["customer_history"]
    rows.append(
        (
            "Customer history",
            f"{h['other_invoices']} other invoice(s) since {h['first_invoice_date']}, {h['other_invoices_paid']} paid "
            f"({h['other_paid_total']})"
            if h["other_invoices"]
            else "No other invoices",
        )
    )
    for k, v in rows:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        pdf.cell(width * 0.3, 5, text(k))
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(width * 0.7, 5, text(v), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if facts["lines"]:
        pdf.ln(2)
        para("Invoice lines", 11, True)
        for ln in facts["lines"]:
            para(f"{ln['description']}: {ln['quantity']} {ln['unit'] or ''} = {ln['amount_ex_vat']} before VAT", 9)
    if facts["timesheets"]:
        pdf.ln(2)
        para("Work logged (timesheets billed on this invoice)", 11, True)
        for t in facts["timesheets"]:
            para(f"{t['date']}: {t['hours']} h{(' - ' + t['note']) if t['note'] else ''}", 9)
    if facts["audit_trail"]:
        pdf.ln(2)
        para("Audit trail", 11, True)
        for a in facts["audit_trail"]:
            para(f"{a['date']}: {a['what']}", 9)
    summary = bytes(pdf.output())
    if not invoice_pdf:
        return summary
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(summary)
        doc.import_pages(pdfium.PdfDocument(invoice_pdf))
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001  a PDF that will not merge: the summary still stands, with the sha above
        return summary


async def _invoice_pdf(books: Books, inv: Invoice, profile: InvoiceProfile) -> bytes | None:
    from app.invoicing import load_logo, sent_pdf
    from app.pdf import render_invoice

    sent = await sent_pdf(books, inv.number)
    if sent:
        return sent
    with contextlib.suppress(Exception):
        return render_invoice(inv, profile, await load_logo(books, profile))
    return None


# --------------------------------------------------------------------------- #
# Build, send, reverse
# --------------------------------------------------------------------------- #


async def build_evidence(
    books: Books, dispute_id: str, cfg: AiConfig | None, user: str, *, sample: bool = False
) -> EvidenceProposal:
    """Gather the facts, draft the response (checked), render the PDF and save it all as a proposal. Sends nothing."""
    d, inv, tid = await _dispute(books, dispute_id, sample=sample)
    old = (await _records(books)).get(dispute_id)
    if old is not None and old.status == "sent":
        raise DisputeError("The evidence for this dispute was already sent")
    is_sample = dispute_id.startswith(SAMPLE_PREFIX)
    if not is_sample and not _can_send(d):
        raise DisputeError("PayPal is not waiting for evidence from you on this dispute")
    facts = await gather_facts(books, d, inv, tid)
    notes, model, reason = await draft_notes(facts, cfg)
    pdf = render_evidence(facts, notes, await _invoice_pdf(books, inv, await load_profile(books)), is_sample)
    path = f"{EVIDENCE_DIR}/{dispute_id}.pdf"
    await books.storage.write(path, pdf)
    rec = EvidenceProposal(
        dispute_id=dispute_id,
        invoice=inv.number,
        notes=notes,
        model=model,
        fallback_reason=reason,
        facts=facts,
        pdf_path=path,
        pdf_sha256=hashlib.sha256(pdf).hexdigest(),
        built_at=now(),
        built_by=user,
        demo=is_sample,
    )
    await _save_record(books, rec)
    await books.audit(
        f"user:{user}",
        "dispute_evidence_built",
        {"dispute": dispute_id, "invoice": inv.number, "model": model, "fallback": bool(reason), "file": path},
    )
    return rec


async def evidence_pdf(books: Books, dispute_id: str) -> bytes:
    rec = (await _records(books)).get(dispute_id)
    if rec is None:
        raise DisputeError("Build the evidence first")
    return await books.storage.read(rec.pdf_path)


async def send_evidence(books: Books, dispute_id: str, user: str, *, sample: bool = False) -> EvidenceProposal:
    """The owner's yes: send the previewed response and PDF to PayPal (provide-evidence). Never called by code alone."""
    rec = (await _records(books)).get(dispute_id)
    if rec is None:
        raise DisputeError("Build the evidence first")
    if rec.status == "sent":
        raise DisputeError("The evidence for this dispute was already sent")
    pdf = await books.storage.read(rec.pdf_path)
    if hashlib.sha256(pdf).hexdigest() != rec.pdf_sha256:
        raise DisputeError("The evidence PDF changed after it was built; build it again")
    d, inv, _tid = await _dispute(books, dispute_id, sample=sample)
    if inv.number != rec.invoice:
        raise DisputeError("This dispute now matches another invoice; build the evidence again")
    if rec.demo:
        pass  # a demo's sample dispute: nothing leaves the server
    else:
        if not _can_send(d):
            raise DisputeError("PayPal is no longer waiting for evidence from you on this dispute")
        c = await load_connections(books)
        got = await _api()
        if got is None or c.paypal is None:
            raise DisputeError("Connect PayPal in Settings › Online payments first")
        api, http = got
        evidence = [{"evidence_type": rec.evidence_type, "notes": rec.notes[:NOTES_MAX]}]
        async with http:
            try:
                await api.provide_evidence(
                    c.paypal.merchant_id, dispute_id, evidence, [(f"evidence-{rec.invoice}.pdf", pdf)]
                )
            except ProviderError as exc:
                raise DisputeError(f"PayPal did not take the evidence: {exc.message}") from exc
    rec.status, rec.sent_at, rec.sent_by = "sent", now(), user
    await _save_record(books, rec)
    await books.audit(
        f"user:{user}",
        "dispute_evidence_sent",
        {
            "dispute": dispute_id,
            "invoice": rec.invoice,
            "file": rec.pdf_path,
            "sha256": rec.pdf_sha256,
            "demo": rec.demo,
        },
    )
    return rec


async def post_reversal(books: Books, dispute_id: str, user: str) -> ReversalProposal:
    """The owner's yes to the reversing entry for a lost dispute: the PayPal payment is taken back (Dr 1100 Debtors /
    Cr 1240 PayPal clearing) and the invoice is open again. Only for a full refund PayPal itself reports."""
    from app import payments

    d, inv, tid = await _dispute(books, dispute_id, sample=False)
    rev = await _reversal(books, d, tid)
    if rev is None:
        raise DisputeError("PayPal does not say this dispute was lost, or the payment is not in your books")
    if not rev.can_post:
        raise DisputeError(rev.reason or "This cannot be posted by code")
    try:
        await payments.remove_payment(books, rev.payment_record, user)
    except InvoiceError as exc:
        raise DisputeError(str(exc)) from exc
    rec = (await _records(books)).get(dispute_id)
    if rec is not None:
        rec.reversal_payment, rec.reversal_at = rev.payment_record, now()
        await _save_record(books, rec)
    await books.audit(
        f"user:{user}",
        "dispute_reversal_posted",
        {"dispute": dispute_id, "invoice": inv.number, "payment": rev.payment_record, "amount_pence": rev.amount_pence},
    )
    return rev
