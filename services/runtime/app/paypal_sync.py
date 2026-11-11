"""Sync PayPal: one tap reads the user's PayPal history and proposes each transaction for the books.

The house rule holds: the AI (and code) proposes, code calculates in pence, the user approves. Nothing here posts on
its own; `sync` only reads PayPal and writes proposals to `_System/Payments/paypal-sync.json` in the user's books.

* **Where the history comes from.** PayPal's Transaction Search (`PayPalApi.transactions`, `GET
  /v1/reporting/transactions`): at most 31 days per request, so a sync is cut into 31-day windows, each read page by
  page (500 a page). Transactions can appear up to three hours late, so each sync starts three hours before the last
  one ended; ids already synced are skipped, so the overlap never proposes anything twice. The first sync reads 90
  days (up to three years, PayPal's limit, when asked). Direct mode (`PAYPAL_DIRECT=1`) reads the server's own
  sandbox account; partner mode names the user's merchant with `PayPal-Auth-Assertion`. A demo session with no PayPal
  connected reads a sample history (app/online_fakes.sample_transactions), labelled as such.
* **What each transaction becomes** (`classify`), GBP and completed (`S`) only:
    - money in naming one of the user's sent invoices (its PayPal payment link, or the invoice number in PayPal's
      invoice id, custom field or subject): the invoice's payment, posted exactly as an online payment found on the
      Invoices page (app/online_payments.approve, or the same entries when it was not paid through the link):
      Dr 1240 PayPal clearing / Cr 1100 Debtors, and the fee Dr 7900 Bank charges (exempt) / Cr 1240;
    - other money in: a sale, Dr 1240 gross / Cr 4000 Sales net / Cr 2200 VAT (20% included when the books are VAT
      registered, else outside the scope), and the fee as above;
    - money out: a purchase from 1240, coded like a bank line (the user's supplier rules, then their bank rules and
      the built-in ones, then their own AI model, then a few names code knows), with the VAT code proposed and a
      flag when no receipt in the books matches it (amount, and date or supplier);
    - PayPal's own fees: bank charges, exempt;
    - withdrawals to the bank, money added from the bank, refunds, reversals, currency conversions and anything not
      in pounds: shown, never posted (a withdrawal is matched on the Bank page as a PayPal payout, `match_payout`).
  A pending transaction is not kept, so a later sync picks it up once PayPal completes it.
* **Never twice.** A transaction already in the books (an invoice's `online_payments`, a payment recorded with
  reference `PayPal <id>`) is shown as already there; every entry this module posts has an id made from the PayPal
  transaction id, and the fee's id is the one app/online_payments uses, so a ledger event can only be claimed once.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app import online_payments as op
from app.ai.config import AiConfig
from app.books import SYSTEM, Books, now
from app.invoicing import Invoice, InvoiceError, InvoiceStateError, get_invoice, list_invoices, money, save_invoice
from app.journal import CATEGORY_ACCOUNTS, PAYPAL_CLEARING, SALES, SUNDRY, VAT_CONTROL
from app.payment_providers import (
    PayPalApi,
    ProviderError,
    client,
    paypal_parse_time,
    pence_from_paypal,
)

SYNC = f"{SYSTEM}/Payments/paypal-sync.json"
WINDOW = timedelta(days=31)  # Transaction Search's longest range per request
LATE = timedelta(hours=3)  # transactions can take up to three hours to be listed
DEFAULT_DAYS = 90
MAX_DAYS = 3 * 365  # PayPal keeps three years of history
PAGE_SIZE = 500
MAX_PAGES = 20  # 10,000 rows per request at most (PayPal's own cap)
MAX_AI = 12  # model calls per sync, for purchases nothing else could code
FEES = op.FEES  # 7900 Bank charges
DEBTORS = "1100 Debtors"
NO_RECEIPT = "No receipt in your books yet: photograph it or forward the email"
MODEL = "paypal-sync"

Kind = Literal["invoice", "sale", "expense", "fee", "withdrawal", "deposit", "refund", "other"]
Status = Literal["proposed", "approved", "rejected", "info", "already"]
Source = Literal["paypal", "sample"]
EXPENSE_VAT = ("S", "R", "Z", "E", "N")

#: Names code recognises when no rule matched and the user's AI was not asked (or did not answer): account only,
#: never a VAT code. Lower-case words in the payee or the item names.
HINTS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\b(adobe|microsoft|google|apple|dropbox|canva|xero|zoom|slack|notion|github|openai|software)\b"),
        "Software & subscriptions",
    ),
    (
        re.compile(r"\b(screwfix|toolstation|wickes|b&q|travis perkins|jewson|selco|howdens|timber|hardware)\b"),
        "Materials",
    ),
    (re.compile(r"\b(royal mail|parcelforce|evri|hermes|dpd|ups|fedex|yodel|parcel2go)\b"), "Postage"),
    (re.compile(r"\b(ebay|amazon)\b"), "Office supplies"),
    (re.compile(r"\b(facebook|meta platforms|instagram|google ads|linkedin)\b"), "Advertising"),
]


class SyncError(InvoiceError):
    """Cannot sync or post this (a 400; NotReady is a 503)."""


class NotReady(SyncError):
    """PayPal is not set up on this server or not connected in these books."""


class Journal(BaseModel):
    account: str
    debit_pence: int = 0
    credit_pence: int = 0
    vat_code: str | None = None


class ReceiptMatch(BaseModel):
    proposal_id: str
    status: str  # the proposal's: proposed, needs_a_look, posted, rejected
    supplier: str
    date: str
    gross_pence: int


class SyncItem(BaseModel):
    transaction_id: str
    date: date
    kind: Kind
    status: Status
    event_code: str
    name: str  # the other party (payer or payee), else PayPal's subject
    items: list[str] = Field(default_factory=list)  # cart item names
    currency: str = "GBP"
    gross_pence: int  # signed: money in is positive
    fee_pence: int = 0  # what PayPal charged (positive)
    net_pence: int  # gross less the fee, signed
    invoice: str | None = None  # the user's invoice this pays
    via_link: bool = False  # paid through the invoice's PayPal payment link
    account: str | None = None  # proposed income or cost account
    vat_code: str | None = None
    coded_by: str | None = None  # in words: which rule, the AI, or code
    receipt: ReceiptMatch | None = None
    notes: list[str] = Field(default_factory=list)
    journal: list[Journal] = Field(default_factory=list)  # what approving posts, worked out by code
    event_ids: list[str] = Field(default_factory=list)
    found_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    reject_reason: str | None = None


class SyncState(BaseModel):
    version: int = 1
    source: Source | None = None
    last_end: datetime | None = None  # the end of the last window read
    last_synced_at: datetime | None = None
    last_synced_by: str | None = None
    items: dict[str, SyncItem] = Field(default_factory=dict)


class SyncResult(BaseModel):
    source: Source
    sample: bool  # not the user's PayPal: the demo's sample history
    start: datetime
    end: datetime
    requests: int  # Transaction Search calls made
    read: int  # rows PayPal listed
    new: int  # rows kept for the first time
    pending: int  # still pending at PayPal: not kept, picked up by a later sync
    items: list[SyncItem]  # every kept row, newest first


class SyncView(BaseModel):
    available: bool
    reason: str | None = None
    source: Source | None = None
    sample: bool = False
    last_synced_at: datetime | None = None
    items: list[SyncItem]


class FeeSummary(BaseModel):
    start: date
    end: date
    fees_pence: int  # PayPal's fees in the synced history, whether approved or not
    transactions: int  # synced transactions that carried a fee
    received_pence: int  # money in on those
    fees_in_books_pence: int  # PayPal fees posted to 7900 Bank charges in the ledger for the dates
    by_month: dict[str, int]  # yyyy-mm -> fees (pence), from the synced history
    synced_through: datetime | None  # the history is only as complete as the last sync


Fetch = Callable[[datetime, datetime], Awaitable[tuple[list[dict[str, Any]], int]]]


# --------------------------------------------------------------------------- #
# Reading PayPal
# --------------------------------------------------------------------------- #


def windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """[start, end) cut into consecutive windows no longer than 31 days, oldest first."""
    out = []
    cur = start
    while cur < end:
        nxt = min(cur + WINDOW, end)
        out.append((cur, nxt))
        cur = nxt
    return out


async def _read_window(api: PayPalApi, merchant: str | None, start: datetime, end: datetime) -> tuple[list, int]:
    rows: list[dict[str, Any]] = []
    calls = 0
    page = 1
    while True:
        got = await api.transactions(merchant, start=start, end=end, page=page, page_size=PAGE_SIZE)
        calls += 1
        rows += [r for r in got.get("transaction_details") or [] if isinstance(r, dict)]
        try:
            total = int(got.get("total_pages") or 1)
        except (TypeError, ValueError):
            total = 1
        if page >= min(total, MAX_PAGES):
            return rows, calls
        page += 1


def paypal_fetch(merchant: str | None) -> Fetch:
    cfg = op._need_paypal()

    async def fetch(start: datetime, end: datetime) -> tuple[list[dict[str, Any]], int]:
        async with client() as http:
            return await _read_window(PayPalApi(cfg, http), merchant, start, end)

    return fetch


def sample_fetch(day: date, invoice: tuple[str, int, str] | None) -> Fetch:
    """The demo's sample history (app/online_fakes.sample_transactions), dated back from `day`."""
    from app import online_fakes

    rows = online_fakes.sample_transactions(day, invoice)

    async def fetch(start: datetime, end: datetime) -> tuple[list[dict[str, Any]], int]:
        out = []
        for row in rows:
            when = paypal_parse_time(row["transaction_info"]["transaction_initiation_date"])
            if when is not None and start <= when <= end:
                out.append(row)
        return out, 1

    return fetch


async def source_for(books: Books, demo: bool) -> tuple[Source | None, str | None, str | None]:
    """(source, the merchant to read, why not). PayPal when the server can reach it and these books are connected;
    the sample history in a demo session without that; otherwise None and a sentence."""
    cfg, why = op.paypal_config()
    conn = (await op.load_connections(books)).paypal
    if cfg is not None and conn is not None:
        return "paypal", conn.merchant_id, None
    if demo:
        return "sample", None, None
    if cfg is None:
        return None, None, why or "PayPal is not set up on this server yet."
    return None, None, "Connect PayPal in Settings › Online payments first."


# --------------------------------------------------------------------------- #
# What a row is (pure)
# --------------------------------------------------------------------------- #


def _name(row: dict[str, Any]) -> str:
    info = row.get("transaction_info") or {}
    payer = row.get("payer_info") or {}
    pn = payer.get("payer_name") or {}
    full = pn.get("alternate_full_name") or " ".join(
        x for x in (pn.get("given_name"), pn.get("surname")) if isinstance(x, str) and x
    )
    for cand in (
        full,
        (row.get("shipping_info") or {}).get("name"),
        payer.get("email_address"),
        info.get("transaction_subject"),
        info.get("transaction_note"),
    ):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()[:120]
    return "PayPal"


def _items(row: dict[str, Any]) -> list[str]:
    out = []
    for it in (row.get("cart_info") or {}).get("item_details") or []:
        if isinstance(it, dict) and isinstance(it.get("item_name"), str) and it["item_name"].strip():
            out.append(it["item_name"].strip()[:120])
    return out[:10]


def _haystack(info: dict[str, Any]) -> str:
    return " ".join(
        str(info.get(k) or "") for k in ("invoice_id", "custom_field", "transaction_subject", "transaction_note")
    )


def parse(row: dict[str, Any]) -> dict[str, Any] | None:
    """The fields code uses from one row, or None when it has no id or amount."""
    info = row.get("transaction_info") or {}
    tid = str(info.get("transaction_id") or "").strip()
    amount = info.get("transaction_amount") or {}
    if not tid or not isinstance(amount, dict):
        return None
    currency = str(amount.get("currency_code") or "")
    when = paypal_parse_time(info.get("transaction_initiation_date"))
    gbp = pence_from_paypal(amount) if currency == "GBP" else None
    fee = pence_from_paypal(info.get("fee_amount")) if currency == "GBP" else None
    return {
        "tid": tid[:64],
        "code": str(info.get("transaction_event_code") or "")[:8],
        "status": str(info.get("transaction_status") or ""),
        "currency": currency,
        "gross": gbp,
        "fee": abs(fee or 0),
        "when": when,
        "name": _name(row),
        "items": _items(row),
        "hay": _haystack(info),
        "invoice_id": str(info.get("invoice_id") or ""),
    }


def kind_of(code: str, gross: int) -> Kind:
    """By PayPal's event code family (T04 withdrawals, T03 bank deposits, T11 reversals and refunds, T01 fees, T02
    currency conversion; T00 payments), then the sign."""
    fam = code[:3].upper()
    if fam == "T04":
        return "withdrawal"
    if fam == "T03":
        return "deposit"
    if fam == "T11":
        return "refund"
    if fam == "T01" and gross < 0:
        return "fee"
    if fam not in ("T00", "T01") or gross == 0:
        return "other"
    return "sale" if gross > 0 else "expense"


INFO_NOTES: dict[str, str] = {
    "withdrawal": "Money moved from PayPal to your bank: not income or a cost. Match the bank line on the Bank page "
    "as a PayPal payout.",
    "deposit": "Money added to PayPal from your bank: not income. Nothing to post.",
    "refund": "A refund or reversal: not posted. Record it from Contacts if it changes what you are owed or owe.",
    "other": "Not a payment for goods or services (a currency conversion, hold or adjustment): not posted.",
}


def invoice_for(p: dict[str, Any], invoices: list[Invoice]) -> tuple[Invoice, bool] | None:
    """The sent invoice this money in pays: first one whose PayPal payment link it came through, then one whose
    number PayPal's invoice id, custom field or subject names."""
    hay = p["hay"]
    for inv in invoices:
        link = inv.payment_link
        if link is None or link.provider != "paypal" or not inv.event_id:
            continue
        if (link.provider_ref and p["invoice_id"] == link.provider_ref) or (
            link.ref and (p["invoice_id"] == f"{inv.number}-{link.ref[:6]}" or link.ref in hay)
        ):
            return inv, True
    for inv in invoices:
        if inv.event_id and re.search(rf"(?<![A-Za-z0-9]){re.escape(inv.number)}(?![0-9])", hay, re.IGNORECASE):
            return inv, False
    return None


def split_vat(gross: int, code: str | None) -> tuple[int, int]:
    """(net, VAT) in pence with the VAT included in the gross, half up to the penny."""
    rate = {"S": 20, "R": 5}.get((code or "").upper())
    if not rate:
        return gross, 0
    vat = (gross * rate * 2 + (100 + rate)) // (2 * (100 + rate))
    return gross - vat, vat


def main_journal(item: SyncItem) -> list[Journal]:
    """The entry for the money itself (pence), by code; empty for what is never posted. The fee is its own entry."""
    gross = abs(item.gross_pence)
    if item.kind == "invoice":
        return [Journal(account=PAYPAL_CLEARING, debit_pence=gross), Journal(account=DEBTORS, credit_pence=gross)]
    if item.kind == "sale":
        net, vat = split_vat(gross, item.vat_code)
        lines = [
            Journal(account=PAYPAL_CLEARING, debit_pence=gross),
            Journal(account=item.account or SALES, credit_pence=net, vat_code=item.vat_code),
        ]
        if vat:
            lines.append(Journal(account=VAT_CONTROL, credit_pence=vat, vat_code=item.vat_code))
        return lines
    if item.kind in ("expense", "fee"):
        code = item.vat_code or "N"
        net, vat = split_vat(gross, code)
        lines = [Journal(account=item.account or SUNDRY, debit_pence=net, vat_code=code)]
        if vat:
            lines.append(Journal(account=VAT_CONTROL, debit_pence=vat, vat_code=code))
        lines.append(Journal(account=PAYPAL_CLEARING, credit_pence=gross))
        return lines
    return []


def journal_for(item: SyncItem) -> list[Journal]:
    """What approving the item posts: its entry, then PayPal's fee on it (Dr 7900 Bank charges, exempt / Cr 1240),
    as app/online_payments.journal_for lays out a payment found through a link."""
    lines = main_journal(item)
    if lines and item.fee_pence and item.kind != "fee":
        lines += [
            Journal(account=FEES, debit_pence=item.fee_pence, vat_code="E"),
            Journal(account=PAYPAL_CLEARING, credit_pence=item.fee_pence),
        ]
    return lines


# --------------------------------------------------------------------------- #
# Coding purchases and finding their receipts
# --------------------------------------------------------------------------- #


def accounts() -> list[str]:
    return sorted(set(CATEGORY_ACCOUNTS.values()) | {SUNDRY})


async def code_purchase(
    books: Books, name: str, items: list[str], gross: int, when: date, cfg: AiConfig | None, ai_budget: list[int]
) -> tuple[str, str | None, str]:
    """(account, VAT code or None, in words who coded it). The user's own supplier rules first (Approve's 'always'),
    then bank rules (theirs, then the built-in ones), then their AI model, then names code knows, else Sundry."""
    from app.bank_reconcile import suggest_ai, suggest_rule

    valid = accounts()
    for rule in reversed(await books.load_rules()):
        with contextlib.suppress(re.error):
            if re.search(rule.match.supplier_regex, name, re.IGNORECASE) and rule.account in valid:
                return rule.account, rule.vat_code, "your rule for this supplier"
    text = " ".join([name, *items])
    line = SimpleNamespace(date=when, description=text, reference=None, amount_pence=-gross)
    rule = await suggest_rule(books, line)
    if rule is not None and rule.account in valid:
        return rule.account, rule.vat_code, rule.rule_name or "a bank rule"
    if cfg is not None and ai_budget[0] > 0:
        ai_budget[0] -= 1
        ai = await suggest_ai(line, cfg, valid)
        if ai is not None:
            return ai.account, ai.vat_code, f"{ai.by}: {ai.reason}" if ai.reason else ai.by
    low = text.lower()
    for pattern, category in HINTS:
        if pattern.search(low):
            return CATEGORY_ACCOUNTS[category], None, f"code: the name looks like {category.lower()}"
    return SUNDRY, None, "code: nothing matched, so Sundry; choose the account"


def _words(text: str) -> set[str]:
    stop = {"ltd", "limited", "plc", "the", "and", "uk", "direct", "co", "inc", "llc", "systems", "software"}
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in stop}


async def find_receipt(books: Books, name: str, gross: int, when: date, proposals: list[Any]) -> ReceiptMatch | None:
    """A document in the books for this purchase: a receipt or bill (not one made from a bank line or this sync) of
    the same amount to the penny, dated within 7 days or from a supplier with a word in common."""
    from app.bank_actions import MODEL as BANK_MODEL

    who = _words(name)
    best = None
    for p in proposals:
        doc = p.extracted
        if p.model in (BANK_MODEL, MODEL) or doc.doc_type not in ("receipt", "purchase_invoice"):
            continue
        if round(abs(doc.gross_total) * 100) != gross:
            continue
        try:
            d = date.fromisoformat(doc.date)
        except ValueError:
            continue
        if abs((d - when).days) > 7 and not (who & _words(doc.supplier_name or "")):
            continue
        hit = ReceiptMatch(
            proposal_id=p.id, status=p.status, supplier=doc.supplier_name, date=doc.date, gross_pence=gross
        )
        if p.status != "rejected" and (best is None or best.status == "rejected"):
            best = hit
    return best


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #


async def load_state(books: Books) -> SyncState:
    raw = await books.read_json(SYNC, {})
    try:
        return SyncState.model_validate(raw if isinstance(raw, dict) else {})
    except ValueError:  # a hand-broken file: start again (ids already posted are still refused by the ledger)
        return SyncState()


async def already_in_books(books: Books) -> set[str]:
    """PayPal transaction ids the books already hold: on invoices (payments found through links) and as payment
    references `PayPal <id>` (app/online_payments.approve)."""
    from app import payments

    ids = {pid for inv in await list_invoices(books) for pid in inv.online_payments}
    for r in await payments._records(books):
        ref = r.reference or ""
        if r.removed_at is None and ref.startswith("PayPal "):
            ids.add(ref.removeprefix("PayPal ").strip())
    return ids


async def _propose(
    books: Books,
    p: dict[str, Any],
    *,
    invoices: list[Invoice],
    known: set[str],
    vat_registered: bool,
    proposals: list[Any],
    cfg: AiConfig | None,
    ai_budget: list[int],
) -> SyncItem:
    gross: int = p["gross"]
    when: date = p["when"].date()
    kind = kind_of(p["code"], gross)
    item = SyncItem(
        transaction_id=p["tid"],
        date=when,
        kind=kind,
        status="proposed",
        event_code=p["code"],
        name=p["name"],
        items=p["items"],
        currency="GBP",
        gross_pence=gross,
        fee_pence=p["fee"],
        net_pence=gross - p["fee"],
        found_at=now(),
    )
    if p["status"] == "V":
        item.status, item.notes = "info", ["Reversed at PayPal: nothing to post."]
        return item
    if kind in INFO_NOTES:
        item.status, item.notes = "info", [INFO_NOTES[kind]]
        return item
    if p["tid"] in known:
        item.status = "already"
        item.notes = ["Already in your books (approved as an online payment on Invoices)."]
        return item
    if kind == "sale":
        hit = invoice_for(p, invoices)
        if hit is not None:
            inv, via_link = hit
            item.kind, item.invoice, item.via_link = "invoice", inv.number, via_link
            item.account = DEBTORS
            item.notes = [
                f"Pays invoice {inv.number} ({inv.customer.name})"
                + (", through its PayPal payment link." if via_link else "; PayPal names the invoice number.")
            ]
        else:
            item.account = SALES
            # VAT is never assumed on a sale with no invoice: standard, zero-rated, exempt and outside-the-scope
            # receipts all reach PayPal, and output VAT goes to HMRC. A VAT-registered owner chooses it first.
            item.vat_code = None if vat_registered else "O"
            item.coded_by = "code: money in with no invoice of yours named, so a sale"
            item.notes = [
                "A sale with no invoice in your books: "
                + (
                    "choose its VAT before you approve it (no VAT is assumed)."
                    if vat_registered
                    else "no VAT (the books are not VAT registered)."
                )
                + " Reject it if it was not a sale (a refund, a loan, money from yourself)."
            ]
    elif kind == "fee":
        item.account, item.vat_code, item.coded_by = FEES, "E", "code: a PayPal fee"
    else:
        account, vat, by = await code_purchase(books, p["name"], p["items"], -gross, when, cfg, ai_budget)
        item.account, item.coded_by = account, by
        item.vat_code = (vat if vat in EXPENSE_VAT else None) or "N"
        if not vat_registered:
            item.vat_code = "N"
        receipt = await find_receipt(books, p["name"], -gross, when, proposals)
        item.receipt = receipt
        if receipt is None:
            item.notes.append(NO_RECEIPT + ".")
            if item.vat_code in ("S", "R"):
                item.notes.append("VAT can only be reclaimed with a VAT receipt.")
        elif receipt.status == "posted":
            item.notes.append(
                f"Already in your books from its receipt ({receipt.supplier}, {receipt.date}): reject this unless it "
                "is a different purchase, or it is counted twice."
            )
        elif receipt.status != "rejected":
            item.notes.append(
                f"Its receipt is waiting on Review ({receipt.supplier}, {receipt.date}): approve one of the two, "
                "not both."
            )
    item.journal = journal_for(item)
    return item


async def sync(
    books: Books,
    user: str,
    fetch: Fetch,
    source: Source,
    *,
    days: int | None = None,
    cfg: AiConfig | None = None,
    end: datetime | None = None,
) -> SyncResult:
    """Read PayPal from the last sync (less three hours) or `days` back, to now, and keep a proposal per new
    transaction. Posts nothing. Raises SyncError when PayPal cannot be read (nothing is saved then)."""
    from app.invoicing import load_profile

    state = await load_state(books)
    end = end or now()
    if days is not None:
        start = end - timedelta(days=max(1, min(days, MAX_DAYS)))
    elif state.last_end is not None and state.source == source:
        start = min(state.last_end - LATE, end - LATE)
    else:
        start = end - timedelta(days=DEFAULT_DAYS)
    start = max(start, end - timedelta(days=MAX_DAYS))
    rows: list[dict[str, Any]] = []
    calls = 0
    try:
        for a, b in windows(start, end):
            got, n = await fetch(a, b)
            rows += got
            calls += n
    except ProviderError as exc:
        raise SyncError(f"PayPal did not answer: {exc.message}") from exc

    invoices = sorted(
        (i for i in await list_invoices(books, "sent") if i.event_id), key=lambda i: (i.due_date, i.number)
    )
    known = await already_in_books(books)
    vat_registered = (await load_profile(books)).is_vat_registered
    proposals = await books.list_proposals()
    ai_budget = [MAX_AI]
    pending = 0
    fresh: list[SyncItem] = []
    seen: set[str] = set()
    parsed = [p for p in (parse(r) for r in rows) if p is not None]
    todo = []
    for p in parsed:
        if p["tid"] in seen or p["tid"] in state.items:
            continue
        seen.add(p["tid"])
        if p["status"] == "P":
            pending += 1
            continue
        if p["status"] not in ("S", "V") or p["when"] is None:
            continue  # denied, or unreadable: nothing happened
        if p["currency"] != "GBP" or p["gross"] is None:
            fresh.append(
                SyncItem(
                    transaction_id=p["tid"],
                    date=p["when"].date(),
                    kind="other",
                    status="info",
                    event_code=p["code"],
                    name=p["name"],
                    items=p["items"],
                    currency=p["currency"] or "?",
                    gross_pence=0,
                    net_pence=0,
                    notes=[
                        f"In {p['currency'] or 'another currency'}, not pounds: not proposed. Record it by hand "
                        "at the pounds your bank or PayPal converted it to."
                    ],
                    found_at=now(),
                )
            )
            continue
        todo.append(p)
    gate = asyncio.Semaphore(4)

    async def one(p: dict[str, Any]) -> SyncItem:
        async with gate:
            return await _propose(
                books,
                p,
                invoices=invoices,
                known=known,
                vat_registered=vat_registered,
                proposals=proposals,
                cfg=cfg,
                ai_budget=ai_budget,
            )

    fresh += await asyncio.gather(*(one(p) for p in todo))
    stamp = now()

    def change(raw: Any) -> dict[str, Any]:
        try:
            cur = SyncState.model_validate(raw if isinstance(raw, dict) else {})
        except ValueError:
            cur = SyncState()
        for it in fresh:
            cur.items.setdefault(it.transaction_id, it)  # one already kept (by a sync running alongside) stays
        cur.source = source
        cur.last_end = end if cur.last_end is None or cur.source != source else max(cur.last_end, end)
        cur.last_synced_at, cur.last_synced_by = stamp, user
        return cur.model_dump(mode="json")

    await books._update_json(SYNC, {}, change)
    await books.audit(
        f"user:{user}",
        "paypal_synced",
        {
            "source": source,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "read": len(rows),
            "new": len(fresh),
            "proposed": sum(1 for i in fresh if i.status == "proposed"),
            "pending": pending,
        },
    )
    state = await load_state(books)
    return SyncResult(
        source=source,
        sample=source == "sample",
        start=start,
        end=end,
        requests=calls,
        read=len(rows),
        new=len(fresh),
        pending=pending,
        items=_newest_first(state),
    )


def _newest_first(state: SyncState) -> list[SyncItem]:
    return sorted(state.items.values(), key=lambda i: (i.date, i.transaction_id), reverse=True)


async def view(books: Books, demo: bool) -> SyncView:
    source, _merchant, why = await source_for(books, demo)
    state = await load_state(books)
    known = await already_in_books(books) if state.items else set()
    items = _newest_first(state)
    for it in items:  # approved meanwhile on the Invoices page: show it as already there
        if it.status == "proposed" and it.transaction_id in known:
            it.status = "already"
            it.notes = ["Already in your books (approved as an online payment on Invoices)."]
    return SyncView(
        available=source is not None,
        reason=why,
        source=source,
        sample=source == "sample",
        last_synced_at=state.last_synced_at,
        items=items,
    )


# --------------------------------------------------------------------------- #
# The user's decision
# --------------------------------------------------------------------------- #


def sync_event_id(tid: str) -> str:
    return hashlib.sha256(f"paypal-sync:{tid}".encode()).hexdigest()[:32]


def _evidence(tid: str) -> str:
    return hashlib.sha256(f"paypal-transaction:{tid}".encode()).hexdigest()


async def _save_item(books: Books, item: SyncItem) -> None:
    def change(raw: Any) -> dict[str, Any]:
        cur = SyncState.model_validate(raw if isinstance(raw, dict) else {})
        cur.items[item.transaction_id] = item
        return cur.model_dump(mode="json")

    await books._update_json(SYNC, {}, change)


async def _item(books: Books, tid: str) -> SyncItem:
    state = await load_state(books)
    item = state.items.get(tid)
    if item is None:
        raise FileNotFoundError(tid)
    return item


def _fee_event(tid: str, when: date, fee: int, who: str, user: str) -> LedgerEvent:
    memo = f"PayPal fee on {who}"[:200]
    return LedgerEvent(
        id=op.fee_event_id("paypal", tid),  # the id app/online_payments gives the same transaction's fee
        kind="purchase",
        date=when,
        lines=[
            Line(account=FEES, debit=fee, vat_code=VatCode.EXEMPT, memo=memo),
            Line(account=PAYPAL_CLEARING, credit=fee, memo=memo),
        ],
        evidence=[_evidence(tid)],
        approved_by=user,
        approved_at=now(),
        net=fee,
        vat=0,
        counterparty="PayPal",
    )


async def _post_invoice(books: Books, item: SyncItem, user: str) -> list[str]:
    """The invoice's payment: through app/online_payments.approve when it came through the invoice's link (the amount
    and fee read again from PayPal); otherwise the same entries from the synced amounts."""
    from app import payments

    assert item.invoice
    tid = item.transaction_id
    inv = await get_invoice(books, item.invoice)
    if inv.payment_link and inv.payment_link.provider == "paypal" and item.via_link:
        try:
            _inv, found = await op.approve(books, inv.number, tid, user)
        except op.OnlinePaymentError as exc:
            if "fee" not in str(exc):
                raise SyncError(str(exc)) from exc
            _inv, found = await op.approve(books, inv.number, tid, user, fee_pence=item.fee_pence)
        events = [op.fee_event_id("paypal", tid)] if found.fee_pence else []
        return events
    reference = f"PayPal {tid}"
    if not inv.event_id or inv.status != "sent":
        raise InvoiceStateError(f"Invoice {inv.number} is {inv.status}; a payment can only go against a sent invoice")
    ledger = await payments.load_ledger(books)
    owed = max(0, ledger.settlement().outstanding(inv.event_id))
    if owed <= 0:
        raise InvoiceStateError(
            f"Invoice {inv.number} is already paid; this {money(abs(item.gross_pence))} would be an overpayment. "
            "Reject it here and refund it or record it as a credit"
        )
    gross = abs(item.gross_pence)
    when = max(item.date, inv.issue_date)
    body = payments.PaymentIn(
        side="sale",
        date=when,
        amount_pence=gross,
        account=cast(payments.PaymentAccount, PAYPAL_CLEARING),
        reference=reference,
        allocations=[payments.AllocationIn(event_id=inv.event_id, amount_pence=min(gross, owed))],
        bank_line_id=None,
    )
    record = await payments.record_payment(books, body, user)
    events = [record.event_id] if record.event_id else []
    if item.fee_pence:
        ev = op.fee_event("paypal", tid, inv.number, when, item.fee_pence, user)
        with contextlib.suppress(FileExistsError):
            await books.post_event(ev)
        events.append(ev.id)
    inv = await get_invoice(books, inv.number)
    if tid not in inv.online_payments:
        inv.online_payments = [*inv.online_payments, tid]
        await save_invoice(books, inv)
    await books.audit(
        f"user:{user}",
        "online_payment_approved",
        {
            "invoice": inv.number,
            "provider": "paypal",
            "provider_payment": tid,
            "payment": record.id,
            "amount_pence": gross,
            "fee_pence": item.fee_pence,
            "fee_event": op.fee_event_id("paypal", tid) if item.fee_pence else None,
        },
    )
    return events


async def _post_entry(books: Books, item: SyncItem, user: str) -> list[str]:
    """A sale, a purchase or a PayPal fee, as the item's journal says, with its fee on its own."""
    lines = [
        Line(
            account=j.account,
            debit=j.debit_pence,
            credit=j.credit_pence,
            vat_code=VatCode(j.vat_code) if j.vat_code else None,
            memo=f"PayPal {item.transaction_id}",
        )
        for j in main_journal(item)
    ]
    sale = item.kind == "sale"
    vat = sum(ln.credit if sale else ln.debit for ln in lines if ln.account == VAT_CONTROL)
    gross = abs(item.gross_pence)
    event = LedgerEvent(
        id=sync_event_id(item.transaction_id),
        kind="sale" if sale else "purchase",
        date=item.date,
        lines=lines,
        evidence=[_evidence(item.transaction_id)],
        approved_by=user,
        approved_at=now(),
        net=gross - vat,
        vat=vat,
        counterparty=item.name,
    )
    try:
        await books.post_event(event)
    except FileExistsError as exc:
        raise InvoiceStateError("This PayPal transaction is already in your books") from exc
    events = [event.id]
    if item.fee_pence and item.kind != "fee":
        fee = _fee_event(item.transaction_id, item.date, item.fee_pence, item.name, user)
        with contextlib.suppress(FileExistsError):
            await books.post_event(fee)
        events.append(fee.id)
    return events


async def approve(
    books: Books,
    tid: str,
    user: str,
    *,
    account: str | None = None,
    vat_code: str | None = None,
) -> SyncItem:
    """The user's yes to one synced transaction. For a purchase or a sale the account and VAT code may be changed
    first (from the chart's cost or sales accounts and the usual codes); code works out the entries again."""
    item = await _item(books, tid)
    if item.status != "proposed":
        raise InvoiceStateError(
            {
                "approved": "This PayPal transaction is already approved",
                "rejected": "This PayPal transaction was rejected",
                "already": "This PayPal transaction is already in your books",
                "info": "This PayPal transaction is not something to post",
            }[item.status]
        )
    if tid in await already_in_books(books):
        item.status = "already"
        item.notes = ["Already in your books (approved as an online payment on Invoices)."]
        await _save_item(books, item)
        raise InvoiceStateError("This PayPal transaction is already in your books")
    if account is not None or vat_code is not None:
        if item.kind not in ("expense", "sale"):
            raise SyncError("Only a purchase's or a sale's account and VAT can be changed here")
        if account is not None:
            ok = accounts() if item.kind == "expense" else [SALES]
            if account not in ok:
                raise SyncError(f"Choose one of: {', '.join(ok)}")
            item.account = account
        if vat_code is not None:
            ok_vat = EXPENSE_VAT if item.kind == "expense" else ("S", "R", "Z", "E", "O")
            if vat_code not in ok_vat:
                raise SyncError(f"VAT code is one of {', '.join(ok_vat)}")
            item.vat_code = vat_code
        item.journal = journal_for(item)
    if item.kind == "sale" and item.vat_code is None:
        raise SyncError(
            "Choose the VAT for this sale first (standard, reduced, zero-rated, exempt or outside the scope)"
        )
    if item.kind == "invoice":
        events = await _post_invoice(books, item, user)
    elif item.kind in ("sale", "expense", "fee"):
        events = await _post_entry(books, item, user)
    else:
        raise SyncError("This PayPal transaction is not something to post")
    item.status, item.event_ids = "approved", events
    item.decided_by, item.decided_at = user, now()
    await _save_item(books, item)
    await books.audit(
        f"user:{user}",
        "paypal_transaction_approved",
        {
            "transaction": tid,
            "kind": item.kind,
            "invoice": item.invoice,
            "amount_pence": abs(item.gross_pence),
            "fee_pence": item.fee_pence,
            "account": item.account,
            "vat_code": item.vat_code,
            "events": events,
        },
    )
    await books.rebuild_safely(f"user:{user}")
    return item


async def reject(books: Books, tid: str, user: str, reason: str | None = None) -> SyncItem:
    item = await _item(books, tid)
    if item.status != "proposed":
        raise InvoiceStateError("Only a transaction waiting for your approval can be rejected")
    item.status, item.reject_reason = "rejected", (reason or "").strip()[:300] or None
    item.decided_by, item.decided_at = user, now()
    await _save_item(books, item)
    await books.audit(
        f"user:{user}",
        "paypal_transaction_rejected",
        {"transaction": tid, "kind": item.kind, "reason": item.reject_reason},
    )
    return item


# --------------------------------------------------------------------------- #
# Fees, for the assistant and the page
# --------------------------------------------------------------------------- #


async def fee_summary(books: Books, start: date, end: date) -> FeeSummary:
    """PayPal's fees for the dates: what the synced history says PayPal charged (approved or not), and what the
    ledger holds as PayPal fees in 7900 Bank charges. Code adds them up; nothing is estimated."""
    if end < start:
        raise SyncError("The end date is before the start date")
    state = await load_state(books)
    fees = received = n = 0
    by_month: dict[str, int] = {}
    for it in state.items.values():
        if not start <= it.date <= end or not it.fee_pence:
            continue
        fees += it.fee_pence
        n += 1
        if it.gross_pence > 0:
            received += it.gross_pence
        key = f"{it.date:%Y-%m}"
        by_month[key] = by_month.get(key, 0) + it.fee_pence
    in_books = 0
    for e in await books.list_events(start, end):
        if (e.counterparty or "") != "PayPal":
            continue
        in_books += sum(ln.debit - ln.credit for ln in e.lines if ln.account == FEES)
    return FeeSummary(
        start=start,
        end=end,
        fees_pence=fees,
        transactions=n,
        received_pence=received,
        fees_in_books_pence=in_books,
        by_month=dict(sorted(by_month.items())),
        synced_through=state.last_end,
    )


__all__ = [
    "SYNC",
    "FeeSummary",
    "NotReady",
    "SyncError",
    "SyncItem",
    "SyncResult",
    "SyncView",
    "approve",
    "fee_summary",
    "journal_for",
    "kind_of",
    "paypal_fetch",
    "reject",
    "sample_fetch",
    "source_for",
    "sync",
    "view",
    "windows",
]


# --------------------------------------------------------------------------- #
# Tie-out: the books' PayPal clearing account against PayPal's own balance
# --------------------------------------------------------------------------- #


class TieOut(BaseModel):
    """What PayPal says it holds against what the books say (1240 PayPal clearing), with the gap explained by what
    the sync has seen but not posted. Read-only; posts nothing."""

    available: bool
    reason: str | None = None
    paypal_pence: int | None = None  # PayPal's total GBP balance
    paypal_as_of: datetime | None = None  # PayPal refreshes this in batches: shown beside the figure
    books_pence: int = 0  # 1240 PayPal clearing in the ledger
    difference_pence: int | None = None  # paypal - books
    waiting_pence: int = 0  # synced, proposed, not yet approved (net of fees)
    not_posted_pence: int = 0  # synced, never posted by design (withdrawals, refunds, conversions, holds…)
    unexplained_pence: int | None = None  # difference - waiting - not_posted
    notes: list[str] = Field(default_factory=list)


async def tie_out(books: Books, demo: bool) -> TieOut:
    source, merchant, why = await source_for(books, demo)
    books_pence = await op.clearing_balance(books, "paypal")
    if source != "paypal":
        return TieOut(
            available=False,
            reason=why or "A tie-out needs your real PayPal account connected (the demo shows sample history).",
            books_pence=books_pence,
        )
    cfg, _ = op.paypal_config()
    assert cfg is not None
    try:
        async with client() as http:
            got = await PayPalApi(cfg, http).balances(merchant)
    except ProviderError as exc:
        return TieOut(available=False, reason=f"PayPal did not answer: {exc.message}", books_pence=books_pence)
    gbp = next((b for b in got.get("balances") or [] if isinstance(b, dict) and b.get("currency") == "GBP"), None)
    paypal = pence_from_paypal((gbp or {}).get("total_balance")) if gbp else 0
    as_of = paypal_parse_time(got.get("last_refresh_time") or got.get("as_of_time"))
    state = await load_state(books)
    waiting = sum(i.net_pence for i in state.items.values() if i.status == "proposed")
    not_posted = sum(i.gross_pence for i in state.items.values() if i.status == "info")
    diff = None if paypal is None else paypal - books_pence
    unexplained = None if diff is None else diff - waiting - not_posted
    notes = [
        "PayPal lists payments up to 3 hours late, and refreshes this balance in batches: compare at the time shown.",
        "Your sandbox or account's opening balance is never posted by Accnomos; it shows as not posted.",
    ]
    if unexplained == 0:
        notes.insert(0, "Your books match PayPal to the penny once the items waiting are approved.")
    return TieOut(
        available=True,
        paypal_pence=paypal,
        paypal_as_of=as_of,
        books_pence=books_pence,
        difference_pence=diff,
        waiting_pence=waiting,
        not_posted_pence=not_posted,
        unexplained_pence=unexplained,
        notes=notes,
    )
