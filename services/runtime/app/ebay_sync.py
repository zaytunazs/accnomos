"""Connect eBay: the seller signs in at eBay and agrees, and Accnomos fetches their sales, refunds, fees, postage
labels and payouts (eBay's Finances API, app/ebay.py) as **proposals the user approves on Review**. Nothing is
posted on its own. Same shape as bank feeds (app/bank_feeds.py), no database (docs/ARCHITECTURE.md):

* **The server holds only the platform's keyset**, from env vars empty by default (the feature is then off and the
  web card hidden): `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_RUNAME` (the RuName whose "Auth Accepted URL" is
  this runtime's `/books/ebay/callback`), `EBAY_ENV=sandbox|production` (sandbox by default) and the token key,
  `EBAY_TOKEN_KEY` or else the bank feeds' `BANKFEEDS_TOKEN_KEY` (32 random bytes, base64). docs/EBAY_SETUP.md.
* **What the user's books keep**, `_System/eBay/connection.json`: when it was connected and last synced, eBay's
  payouts seen (for matching the bank line), the optional VAT number from eBay's fee invoices, and the **refresh
  token sealed with the server's key** (AES-256-GCM; associated data binds it to these books' root folder id and
  a hash of who connected, so a copy of the file in other books cannot be used: "Reconnect eBay"). eBay's
  refresh token lasts about 18 months; access tokens (2 hours) are never stored. `_System/eBay/imported.json`
  lists every eBay transaction and payout already turned into proposals ("SALE:<transactionId>", "PAYOUT:<id>").
  The real guard against proposing one twice (two tabs, two devices, a retry, a sync cut short) is the proposal id:
  derived from the books, the type and the transaction id, and written create-only, so a second write of the same
  part fails instead of making a twin, even after the first was rejected. One sync runs at a time per books here.
* **Connecting** is OAuth-shaped like bank feeds: a signed, short-lived `state` binds the code to the browser that
  started it (`binding`) and to the user; eBay sends the browser to the runtime's callback, which forwards code and
  state in the URL fragment to the Bank page, which posts them back with the user's own token.
* **The mapping** (all amounts integer pence; eBay pays a UK seller in GBP; other currencies are skipped):
  - SALE: the sale itself, gross = `amount` + `totalFeeAmount` (what the seller earned before eBay's fees; eBay's
    spec: a line's feeBasisAmount "includes transactions.amount, totalFeeAmount, eBayCollectedTaxAmount, and
    shipping"), into 1250 eBay clearing (Dr clearing / Cr 4000 Sales / Cr 2200 VAT). VAT from the business's VAT
    settings: VAT-registered (Settings › Business) → 20% standard rate included in the gross, with the business's
    own VAT number; not registered → no VAT. An order on which eBay collected tax (`eBayCollectedTaxAmount`, a
    sale abroad) is proposed zero-rated and flagged. The fees deducted from it (`totalFeeAmount`) are split by
    `orderLineItems[].marketplaceFees[].feeType` into selling fees (Dr 5400 Marketplace fees) and advertising fees
    (AD_FEE, PREMIUM_AD_FEES: Dr 6210 Marketplace advertising), one proposal each, one line per fee type, Cr 1250
    eBay clearing. 1250, 5400 and 6210 move to a free fallback code if a saved chart uses the code (app/chart.py).
  - REFUND: the sale turned round for `amount` + `totalFeeAmount` (the fee credit eBay gives back), and the fee
    credit as a credit note from eBay. (UNVERIFIED in the sandbox: that a REFUND's `amount` is net of the fee
    credit, by symmetry with SALE.)
  - NON_SALE_CHARGE (and FEE, which eBay's enum does not list): a selling fee (5400), or an advertising fee
    (6210) when its `feeType` is AD_FEE / PREMIUM_AD_FEES or its memo names promoted or offsite ads; a CREDIT
    booking entry is a credit note from eBay. The same fee VAT rule applies to both.
  - SHIPPING_LABEL: postage, Dr 7520 Postage / Cr clearing, with the VAT eBay reports in `taxes` (VAT), if any.
  - Payouts (SUCCEEDED): recorded here, not posted. When the payout reaches the bank, the Bank page offers "Payout
    from eBay" on that line, which posts Dr 1200 Bank / Cr 1250 eBay clearing (app/online_payments.match_payout),
    so the bank line matches and eBay's money is counted once.
  - CREDIT, ADJUSTMENT, DISPUTE, TRANSFER, WITHDRAWAL, LOAN_REPAYMENT, PURCHASE: listed as skipped, to book by hand.
* **VAT on eBay's fees.** eBay's announcement of 1 Aug 2017: business sellers with a UK address contract with eBay
  (UK) Limited, which is "required by HMRC to add UK VAT to all fees billed to business sellers, at the standard
  rate of 20%"; VAT-registered sellers can reclaim it
  (https://community.ebay.co.uk/t5/Announcements/Changes-to-VAT-on-eBay-fees-for-business-sellers-with-a-UK/ba-p/6241551,
  read 9 Nov 2026). UNVERIFIED: that the Finances API's fee amounts include that VAT, and eBay (UK) Limited's VAT
  number. So a fee is proposed with 20% VAT reclaimable only when the user has entered the VAT number printed on
  eBay's VAT invoice (`fee_vat_number`); without it the VAT stays in the cost (code N), and every fee card says so.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import weakref
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field

from accnomos_connectors.base import ConflictError
from app.ai.config import is_test_mode
from app.books import SYSTEM, Books, now, today
from app.checks import normalise_vat_number
from app.ebay import PRODUCTION, SANDBOX, EbayApi, EbayConfig, EbayError, Hosts, auth_url, client, currency, pence
from app.journal import EBAY_CLEARING, MARKETPLACE_ADS, MARKETPLACE_FEES
from app.paths import PROPOSALS
from app.schemas import Check, ExtractedDoc, ExtractedLine, Proposal

FOLDER = f"{SYSTEM}/eBay"
CONNECTION = f"{FOLDER}/connection.json"
IMPORTED = f"{FOLDER}/imported.json"
CONNECTION_ID = "ebay"  # one eBay account per set of books (no user id comes back without another scope)
DEFAULT_DAYS = 90
MAX_DAYS = 730  # well inside eBay's 36-month filter limit and getOrders' two years
STATE_TTL_S = 900
TEST_TOKEN_KEY = base64.b64encode(b"accnomos-test-mode-ebay-tokenkey").decode()  # 32 bytes, test mode only
MODEL = "ebay-import"  # in place of a reading model's name: code built it from eBay's data
EBAY_SUPPLIER = "eBay (UK) Limited"
UK_STANDARD = 20
OFF_SENTENCE = "Connecting eBay is not set up on this server yet."
DEMO_OFF = "Connecting eBay is switched off in the demo sandbox."
FEE_SOURCE = (
    "https://community.ebay.co.uk/t5/Announcements/Changes-to-VAT-on-eBay-fees-for-business-sellers-with-a-UK/"
    "ba-p/6241551"
)
SKIPPED_TYPES = {"CREDIT", "ADJUSTMENT", "DISPUTE", "TRANSFER", "WITHDRAWAL", "LOAN_REPAYMENT", "PURCHASE"}
FEE_TYPES = {"NON_SALE_CHARGE", "FEE"}


class EbaySyncError(ValueError):
    """Cannot do this with eBay (a 400)."""


class NotConfigured(EbaySyncError):
    """The server has no eBay keyset (a 503)."""


# --------------------------------------------------------------------------- #
# Server configuration (env only)
# --------------------------------------------------------------------------- #


def public_base() -> str:
    return os.getenv("RUNTIME_PUBLIC_URL", "").rstrip("/") or f"http://127.0.0.1:{os.getenv('PORT', '8780')}"


def _key_bytes(raw: str) -> bytes | None:
    try:
        key = base64.urlsafe_b64decode(raw.replace("+", "-").replace("/", "_") + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == 32 else None


def config() -> tuple[EbayConfig | None, bytes | None, str | None]:
    """(eBay config, token key, None) when Connect eBay can be used, else (None, None, why not)."""
    if is_test_mode():
        base = public_base()
        cfg = EbayConfig(
            client_id="accnomos-fake-ebay",
            client_secret="accnomos-fake-ebay-secret",
            runame="Accnomos-FakeRuName",
            hosts=Hosts(f"{base}/__test/ebay", SANDBOX.api, SANDBOX.apiz),
        )
        return cfg, _key_bytes(TEST_TOKEN_KEY), None
    env = {k: os.getenv(k, "").strip() for k in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_RUNAME")}
    raw_key = os.getenv("EBAY_TOKEN_KEY", "").strip() or os.getenv("BANKFEEDS_TOKEN_KEY", "").strip()
    if not all(env.values()) or not raw_key:
        return None, None, OFF_SENTENCE
    key = _key_bytes(raw_key)
    if key is None:
        return None, None, "Connecting eBay is switched off: the server's token key is not 32 bytes of base64."
    which = os.getenv("EBAY_ENV", "sandbox").strip().lower()
    if which not in ("sandbox", "production"):
        return None, None, "Connecting eBay is switched off: EBAY_ENV is sandbox or production."
    hosts = PRODUCTION if which == "production" else SANDBOX
    return EbayConfig(env["EBAY_CLIENT_ID"], env["EBAY_CLIENT_SECRET"], env["EBAY_RUNAME"], hosts), key, None


def _need() -> tuple[EbayConfig, bytes]:
    cfg, key, why = config()
    if cfg is None or key is None:
        raise NotConfigured(why or OFF_SENTENCE)
    return cfg, key


def key_id(key: bytes) -> str:
    return hashlib.sha256(b"accnomos-ebay-key-id:" + key).hexdigest()[:12]


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


async def books_id(books: Books) -> str:
    """A stable id for these books: a hash of their root folder's id at the storage provider (a OneDrive item id or
    a Google Drive file id). Copying _System/eBay/connection.json into other books changes it."""
    root = await books.storage.ensure_root()
    return hashlib.sha256(f"accnomos-ebay-books:{root.id}".encode()).hexdigest()[:32]


def _aad(books_ref: str, connected_by: str) -> bytes:
    """What the sealed token is bound to: these books and the person who connected eBay (by a hash)."""
    return f"accnomos-ebay:v2:{books_ref}:{user_hash(connected_by)}".encode()


def seal(token: str, key: bytes, books_ref: str, connected_by: str) -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, token.encode(), _aad(books_ref, connected_by))
    return f"v2.{_b64(nonce)}.{_b64(ct)}"


def unseal(sealed: str, key: bytes, books_ref: str, connected_by: str) -> str | None:
    """The token, or None for another key, other books, another `connected_by`, or a damaged value."""
    try:
        version, nonce, ct = sealed.split(".")
        if version != "v2":
            return None
        plain = AESGCM(key).decrypt(_unb64(nonce), _unb64(ct), _aad(books_ref, connected_by))
    except (ValueError, InvalidTag, binascii.Error):
        return None
    return plain.decode()


KEY_CHANGED = "This connection can't be read any more (the server's key changed). Connect eBay again."
MOVED = (
    "This eBay connection was made in other books, or was changed by hand, so it can't be used here. Reconnect eBay."
)


# --------------------------------------------------------------------------- #
# Signed state (one use per step, kept in memory until it would expire)
# --------------------------------------------------------------------------- #


class StateError(ValueError):
    pass


_spent: dict[tuple[str, str], float] = {}


def _state_key() -> bytes:
    _, key = _need()
    return hashlib.sha256(b"accnomos-ebay-state:" + key).digest()


def user_hash(user: str) -> str:
    return hashlib.sha256(user.strip().lower().encode()).hexdigest()[:16]


def binding_hash(binding: str) -> str:
    return hashlib.sha256(binding.encode()).hexdigest()


def make_state(redirect_to: str, binding_hash_: str, user: str) -> str:
    body = {
        "r": redirect_to,
        "b": binding_hash_,
        "u": user_hash(user),
        "e": int(time.time()) + STATE_TTL_S,
        "n": secrets.token_urlsafe(12),
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_b64(hmac.new(_state_key(), payload.encode(), hashlib.sha256).digest())}"


def read_state(state: str, use: str | None = None) -> dict[str, str]:
    try:
        payload, sig = state.split(".")
        expected = _b64(hmac.new(_state_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig.encode(), expected.encode()):
            raise StateError("bad signature")
        data = json.loads(_unb64(payload))
        expires, nonce = float(data["e"]), str(data["n"])
        out = {"redirect_to": str(data["r"]), "binding_hash": str(data["b"]), "user_hash": str(data["u"])}
    except StateError:
        raise
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise StateError("malformed state") from exc
    now_s = time.time()
    if expires < now_s:
        raise StateError("state expired")
    if use:
        for k in [k for k, exp in _spent.items() if exp < now_s]:
            del _spent[k]
        if (use, nonce) in _spent:
            raise StateError("state already used")
        _spent[(use, nonce)] = expires
    return out


def check_redirect(url: str) -> str:
    """Only back to the Bank page on one of this server's web origins."""
    origins = [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o]
    parts = urlsplit(url)
    if f"{parts.scheme}://{parts.netloc}" not in origins or not parts.path.startswith("/bank"):
        raise EbaySyncError("Connecting eBay can only come back to the Bank page in this app")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


# --------------------------------------------------------------------------- #
# What the user's books keep
# --------------------------------------------------------------------------- #


class EbayPayout(BaseModel):
    payout_id: str = Field(max_length=128)
    date: date
    amount_pence: int
    last4: str | None = Field(default=None, max_length=8)
    bank_reference: str | None = Field(default=None, max_length=200)


class SyncSummary(BaseModel):
    sales: int = 0
    refunds: int = 0
    fees: int = 0  # selling fees (final value, per order, international, regulatory, store, insertion ...)
    ad_fees: int = 0  # advertising fees (Promoted Listings)
    postage: int = 0
    payouts: int = 0
    already_imported: int = 0
    skipped: int = 0
    skipped_types: dict[str, int] = {}  # eBay transaction type -> how many were left to book by hand


class EbayConnection(BaseModel):
    id: str = CONNECTION_ID
    sandbox: bool = True
    connected_at: datetime
    connected_by: str
    token: str  # the refresh token, sealed; never the access token
    key_id: str
    refresh_expires_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_summary: SyncSummary | None = None
    payouts: list[EbayPayout] = []


class EbayFile(BaseModel):
    version: int = 1
    connection: EbayConnection | None = None
    #: The VAT number printed on eBay's VAT invoice for its fees; with it, fee VAT is proposed as reclaimable.
    fee_vat_number: str | None = None


async def load(books: Books) -> EbayFile:
    raw = await books.read_json(CONNECTION, {})
    try:
        return EbayFile.model_validate(raw if isinstance(raw, dict) else {})
    except ValueError:
        return EbayFile()  # a hand-broken file reads as "not connected"


async def _save(books: Books, change: Any) -> EbayFile:
    out: dict[str, EbayFile] = {}

    def apply(old: Any) -> dict[str, Any]:
        try:
            cur = EbayFile.model_validate(old if isinstance(old, dict) else {})
        except ValueError:
            cur = EbayFile()
        out["f"] = change(cur)
        return out["f"].model_dump(mode="json")

    await books._update_json(CONNECTION, {}, apply)
    return out["f"]


async def load_imported(books: Books) -> dict[str, list[str]]:
    """ "<TYPE>:<eBay id>" -> the proposal ids made from it (empty for a payout)."""
    raw = await books.read_json(IMPORTED, {})
    ids = raw.get("ids") if isinstance(raw, dict) else None
    return {str(k): [str(x) for x in v] for k, v in (ids or {}).items() if isinstance(v, list)}


async def _add_imported(books: Books, new: dict[str, list[str]]) -> None:
    def apply(old: Any) -> dict[str, Any]:
        ids = dict((old or {}).get("ids") or {}) if isinstance(old, dict) else {}
        ids.update(new)
        return {"version": 1, "ids": ids}

    await books._update_json(IMPORTED, {}, apply)


# --------------------------------------------------------------------------- #
# Status, settings, connect, disconnect
# --------------------------------------------------------------------------- #


class PayoutView(BaseModel):
    payout_id: str
    date: date
    amount_pence: int
    last4: str | None
    matched: bool  # a bank line has been matched as this eBay payout


class EbayStatus(BaseModel):
    configured: bool  # the server has an eBay keyset: the web shows the card only then
    reason: str | None = None
    sandbox: bool = True
    connected: bool = False
    state: Literal["ok", "key_changed", "reconnect"] | None = None
    message: str | None = None
    connected_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_summary: SyncSummary | None = None
    fee_vat_number: str | None = None
    payouts: list[PayoutView] = []


async def _matched_payouts(books: Books) -> list[tuple[date, int]]:
    from app.online_payments import _payouts

    with contextlib.suppress(ValueError, TypeError):
        return [
            (p.date, p.amount_pence) for p in await _payouts(books) if p.provider == "ebay" and not p.reversal_event_id
        ]
    return []


async def status(books: Books, demo: bool = False) -> EbayStatus:
    if demo:
        return EbayStatus(configured=False, reason=DEMO_OFF)
    cfg, key, why = config()
    if cfg is None or key is None:
        return EbayStatus(configured=False, reason=why)
    f = await load(books)
    c = f.connection
    if c is None:
        return EbayStatus(configured=True, sandbox=cfg.sandbox, fee_vat_number=f.fee_vat_number)
    ref = await books_id(books)
    state: Literal["ok", "key_changed", "reconnect"] = (
        "key_changed"
        if c.key_id != key_id(key)
        else "ok"
        if unseal(c.token, key, ref, c.connected_by) is not None
        else "reconnect"
    )
    matched = await _matched_payouts(books)
    views = []
    for p in sorted(c.payouts, key=lambda p: p.date, reverse=True)[:20]:
        hit = next((m for m in matched if m[1] == p.amount_pence and abs((m[0] - p.date).days) <= 7), None)
        if hit is not None:
            matched.remove(hit)
        views.append(PayoutView(**p.model_dump(exclude={"bank_reference"}), matched=hit is not None))
    return EbayStatus(
        configured=True,
        sandbox=c.sandbox,
        connected=True,
        state=state,
        message={"ok": None, "key_changed": KEY_CHANGED, "reconnect": MOVED}[state],
        connected_at=c.connected_at,
        last_synced_at=c.last_synced_at,
        last_summary=c.last_summary,
        fee_vat_number=f.fee_vat_number,
        payouts=views,
    )


def start(redirect_to: str, binding_hash_: str, user: str) -> str:
    cfg, _ = _need()
    return auth_url(cfg, make_state(check_redirect(redirect_to), binding_hash_, user))


async def connect(books: Books, code: str, state: str, binding: str, user: str) -> EbayConnection:
    cfg, key = _need()
    try:
        st = read_state(state, use="connect")
    except StateError as exc:
        raise EbaySyncError("The eBay sign-in has expired; connect again") from exc
    if not hmac.compare_digest(st["binding_hash"], binding_hash(binding)):
        raise EbaySyncError("This eBay sign-in was started in another browser")
    if st["user_hash"] != user_hash(user):
        raise EbaySyncError("This eBay sign-in was started by someone else")
    async with client() as http:
        try:
            tokens = await EbayApi(cfg, http).exchange_code(code)
        except EbayError as exc:
            raise EbaySyncError(f"eBay was not connected: {exc.message}") from exc
    refresh = str(tokens.get("refresh_token") or "")
    if not refresh:
        raise EbaySyncError("eBay gave no long-lived access; connect again")
    stamp = now()
    lasts = tokens.get("refresh_token_expires_in")
    conn = EbayConnection(
        sandbox=cfg.sandbox,
        connected_at=stamp,
        connected_by=user,
        token=seal(refresh, key, await books_id(books), user),
        key_id=key_id(key),
        refresh_expires_at=stamp + timedelta(seconds=lasts) if isinstance(lasts, int) and lasts > 0 else None,
    )

    def put(f: EbayFile) -> EbayFile:
        if f.connection is not None:  # reconnecting keeps the payouts seen
            conn.payouts = f.connection.payouts
        f.connection = conn
        return f

    await _save(books, put)
    await books.audit(f"user:{user}", "ebay_connected", {"sandbox": cfg.sandbox})
    return conn


async def disconnect(books: Books, user: str) -> str:
    """Forget the connection (and its sealed token). Proposals and postings already made stay."""
    if (await load(books)).connection is None:
        raise FileNotFoundError(CONNECTION_ID)

    def drop(f: EbayFile) -> EbayFile:
        f.connection = None
        return f

    await _save(books, drop)
    await books.audit(f"user:{user}", "ebay_disconnected", {})
    return (
        "eBay disconnected: nothing more is fetched, and what was fetched stays. To withdraw the access at eBay too, "
        "remove Accnomos from the third-party apps in your eBay account settings."
    )


async def set_fee_vat_number(books: Books, vat_number: str | None, user: str) -> EbayFile:
    n = normalise_vat_number(vat_number) if vat_number else None
    if vat_number and (n is None or not n.startswith("GB")):
        raise EbaySyncError("Enter the UK VAT number shown on eBay's VAT invoice, e.g. GB 123 4567 89")

    def put(f: EbayFile) -> EbayFile:
        f.fee_vat_number = n
        return f

    out = await _save(books, put)
    await books.audit(f"user:{user}", "ebay_fee_vat_number_set", {"set": n is not None})
    return out


# --------------------------------------------------------------------------- #
# Mapping eBay's transactions to proposals
# --------------------------------------------------------------------------- #


class VatSettings(BaseModel):
    registered: bool
    own_vrn: str | None  # the business's own VAT number (Settings › Business)
    fee_vrn: str | None  # eBay's, as the user typed it from eBay's VAT invoice


def _vat_of(gross: int, rate: int) -> int:
    """VAT included in `gross` pence at `rate` %, rounded half up to the penny."""
    return (gross * rate * 2 + (100 + rate)) // (2 * (100 + rate)) if gross >= 0 else -_vat_of(-gross, rate)


def _pounds(p: int) -> float:
    return round(p / 100, 2)


def _day(raw: Any) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        got = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return got.date()


def _doc(
    kind: Literal["sales_invoice", "receipt", "credit_note"],
    *,
    when: date,
    gross: int,
    vat: int,
    rate: int | None,
    supplier: str,
    supplier_vrn: str | None,
    customer: str | None,
    ref: str | None,
    category: str,
    description: str,
    parts: list[tuple[str, int]] | None = None,
) -> ExtractedDoc:
    """With `parts` ((description, gross pence), e.g. a fee per eBay feeType): one line each, VAT worked out per
    line at `rate` and the totals summed from the lines, so lines and totals always agree."""
    if parts and len(parts) > 1:
        rows = [(d, g, _vat_of(g, rate) if rate else 0) for d, g in parts]
        gross, vat = sum(g for _, g, _ in rows), sum(v for _, _, v in rows)
        lines = [
            ExtractedLine(
                description=d[:200],
                qty=1,
                unit_price=_pounds(g - v),
                net=_pounds(g - v),
                vat_rate=rate if rate is not None else 0,
                vat=_pounds(v),
            )
            for d, g, v in rows
        ]
        if rate is None:  # no VAT shown: the journal codes it from the document (code N), not from 0% lines
            lines = []
    else:
        lines = (
            [
                ExtractedLine(
                    description=description[:200],
                    qty=1,
                    unit_price=_pounds(gross - vat),
                    net=_pounds(gross - vat),
                    vat_rate=rate,
                    vat=_pounds(vat),
                )
            ]
            if rate is not None
            else []
        )
    return ExtractedDoc(
        doc_type=kind,
        supplier_name=supplier,
        supplier_vat_number=supplier_vrn,
        customer_name=customer,
        invoice_number=ref,
        date=when.isoformat(),
        currency="GBP",
        lines=lines,
        net_total=_pounds(gross - vat),
        vat_total=_pounds(vat),
        gross_total=_pounds(gross),
        payment_method="unknown",
        card_last4=None,
        category_guess=category,
        confidence=1.0,
    )


def proposal_id(books_ref: str, key: str, part: str) -> str:
    """The same eBay transaction part in the same books always gets the same proposal id, so a second sync (another
    tab, another device, a retry) collides on the file instead of proposing it twice."""
    return hashlib.sha256(f"accnomos-ebay-proposal:{books_ref}:{key}:{part}".encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Accounts:
    """Where eBay's money and fees post in these books (app/chart.resolve_label)."""

    clearing: str = EBAY_CLEARING
    fees: str = MARKETPLACE_FEES
    ads: str = MARKETPLACE_ADS


def _proposal(
    key: str,
    part: str,
    doc: ExtractedDoc,
    notes: list[str],
    ctx: tuple[str, Accounts],
    *,
    expense: Literal["fees", "ads"] | None = None,
    refund: bool = False,
) -> Proposal:
    books_ref, accounts = ctx
    checks = [Check(code="ebay_import", ok=False, severity="fail", message=m) for m in notes]
    p = Proposal(
        id=proposal_id(books_ref, key, part),
        doc_sha256=hashlib.sha256(f"ebay:{key}:{part}".encode()).hexdigest(),
        extracted=doc,
        checks=checks,
        status="needs_a_look",  # imported by code: a person always looks before it posts
        reasons=[f"{c.code}: {c.message}" for c in checks],
        suggested_filename=f"{doc.date} eBay {part} {doc.invoice_number or ''}".strip()[:120],
        journal_draft=[],
        model=MODEL,
        elapsed_s=0.0,
        source_name=f"eBay {key.replace(':', ' ')}",
        created_at=now(),
        account_override={"fees": accounts.fees, "ads": accounts.ads, None: None}[expense],
        settlement_account=accounts.clearing,
        sale_refund=refund,
        source_ref=f"eBay {key.replace(':', ' ')}"[:200],
    )
    return p


def _sale_vat(gross: int, vs: VatSettings, collected_abroad: bool) -> tuple[int, int | None, str | None, list[str]]:
    """(VAT pence, rate for the line or None, the business's VRN for the journal, notes) for a sale or refund."""
    if not vs.registered:
        return 0, None, None, ["Your business isn't VAT-registered (Settings › Business), so no VAT is charged."]
    if collected_abroad:
        return (
            0,
            0,
            vs.own_vrn,
            [
                "eBay collected tax from the buyer on this order (usually a sale abroad), so it is proposed zero-rated "
                "as an export. Check where it was sent before approving."
            ],
        )
    notes = [
        f"VAT at the standard {UK_STANDARD}% is taken as included in the price (your VAT settings). Change the VAT "
        "if this item is zero-rated or reduced-rate."
    ]
    if vs.own_vrn is None:
        notes.append(
            "VAT is due on this sale because your business is VAT-registered, so it is included here. Add your VAT "
            "number in Settings › Business so eBay sales are coded as standard-rated."
        )
    return _vat_of(gross, UK_STANDARD), UK_STANDARD, vs.own_vrn, notes


def _fee_vat(gross: int, vs: VatSettings) -> tuple[int, int | None, str | None, list[str]]:
    if not vs.registered:
        return 0, None, None, []
    vat = _vat_of(gross, UK_STANDARD)
    if vs.fee_vrn:
        return (
            vat,
            UK_STANDARD,
            vs.fee_vrn,
            [
                f"eBay (UK) Limited adds 20% UK VAT to fees billed to UK business sellers ({FEE_SOURCE}). Check the "
                "amount against eBay's monthly VAT invoice before reclaiming it."
            ],
        )
    return (
        vat,
        UK_STANDARD,
        None,
        [
            f"eBay (UK) Limited adds 20% UK VAT to fees billed to UK business sellers ({FEE_SOURCE}), but no eBay VAT "
            "number is saved, so this VAT is not reclaimed. Enter the VAT number from eBay's VAT invoice on the Bank "
            "page's eBay card to reclaim it on later imports."
        ],
    )


def _titles(order: dict[str, Any] | None) -> str:
    items = [li for li in (order or {}).get("lineItems") or [] if isinstance(li, dict)]
    out = [f"{li.get('quantity') or 1} × {str(li.get('title') or '').strip()}" for li in items if li.get("title")]
    return "; ".join(out)[:300]


class Skipped(BaseModel):
    type: str
    id: str
    date: date | None
    amount_pence: int | None
    reason: str


#: eBay's FeeTypeEnum values for advertising (Promoted Listings); offsite ads arrive as a NON_SALE_CHARGE whose memo
#: names them ("Promoted Offsite Fee", eBay's transactionMemo description). Everything else is a selling fee.
AD_FEE_TYPES = {"AD_FEE", "PREMIUM_AD_FEES"}
AD_WORDS = re.compile(r"\b(promoted|offsite|advert)", re.IGNORECASE)


def is_ad_fee(fee_type: str | None, memo: str | None = None) -> bool:
    return str(fee_type or "").upper() in AD_FEE_TYPES or bool(AD_WORDS.search(memo or ""))


def fee_label(fee_type: str) -> str:
    """FINAL_VALUE_FEE_FIXED_PER_ORDER -> "Final value fee fixed per order"."""
    return fee_type.replace("_", " ").strip().capitalize() or "Fee"


def fee_breakdown(tx: dict[str, Any], total: int) -> dict[str, int]:
    """eBay's fees on one order by feeType (pence, positive), from orderLineItems[].marketplaceFees; whatever the
    breakdown does not cover of `total` (totalFeeAmount) is "OTHER_FEES". No breakdown: all of it is OTHER_FEES."""
    out: dict[str, int] = {}
    for li in tx.get("orderLineItems") or []:
        for f in (li.get("marketplaceFees") or []) if isinstance(li, dict) else []:
            if isinstance(f, dict) and (p := pence(f.get("amount"))) is not None and p:
                t = str(f.get("feeType") or "OTHER_FEES").upper()
                out[t] = out.get(t, 0) + abs(p)
    covered = sum(out.values())
    if covered > total:  # a breakdown that disagrees with the total: trust the total, say so in the notes
        return {"OTHER_FEES": total}
    if total - covered:
        out["OTHER_FEES"] = out.get("OTHER_FEES", 0) + total - covered
    return out


def map_transaction(
    tx: dict[str, Any],
    vs: VatSettings,
    orders: dict[str, dict[str, Any]],
    books_ref: str = "",
    accounts: Accounts = Accounts(),  # noqa: B008 - frozen dataclass
) -> tuple[str, list[Proposal], dict[str, int], Skipped | None]:
    """(dedupe key, proposals, counts by kind, skipped) for one eBay transaction. Pure: no I/O."""
    ctx = (books_ref, accounts)
    kind = str(tx.get("transactionType") or "").upper()
    tx_id = str(tx.get("transactionId") or "").strip()[:128]
    key = f"{kind}:{tx_id}"
    when = _day(tx.get("transactionDate"))
    amount = pence(tx.get("amount"))
    credit = str(tx.get("bookingEntry") or "").upper() == "CREDIT"

    def skip(reason: str) -> tuple[str, list[Proposal], dict[str, int], Skipped]:
        return key, [], {}, Skipped(type=kind or "?", id=tx_id, date=when, amount_pence=amount, reason=reason)

    if not tx_id or when is None or amount is None:
        return skip("no id, date or amount")
    if currency(tx.get("amount")) not in ("", "GBP"):
        return skip(f"in {currency(tx.get('amount'))}, not GBP: book it by hand")
    amount = abs(amount)
    fee = abs(pence(tx.get("totalFeeAmount")) or 0)
    order_id = str(tx.get("orderId") or "").strip() or None
    what = _titles(orders.get(order_id or ""))
    memo = str(tx.get("transactionMemo") or tx.get("feeType") or "").strip()

    if kind in ("SALE", "REFUND"):
        refund = kind == "REFUND"
        gross = amount + fee
        collected = (pence(tx.get("eBayCollectedTaxAmount")) or 0) > 0
        vat, rate, vrn, notes = _sale_vat(gross, vs, collected)
        basis = pence(tx.get("totalFeeBasisAmount"))
        tax = pence(tx.get("eBayCollectedTaxAmount")) or 0
        if not refund and basis is not None and basis - tax != gross:
            notes.append(
                f"eBay's order total less tax it collected ({basis - tax}p) differs from the payout before fees "
                f"({gross}p); check the order in Seller Hub."
            )
        label = "Refund to eBay buyer" if refund else "eBay sale"
        desc = f"{label} {order_id or tx_id}" + (f": {what}" if what else "")
        notes.insert(0, f"Imported from eBay ({'refund' if refund else 'sale'} {order_id or tx_id}). {desc}"[:600])
        doc = _doc(
            "sales_invoice",
            when=when,
            gross=gross,
            vat=vat,
            rate=rate,
            supplier=label,
            supplier_vrn=vrn,
            customer="eBay buyer",
            ref=order_id or tx_id,
            category="Sales",
            description=desc,
        )
        out = [_proposal(key, "refund" if refund else "sale", doc, notes, ctx, refund=refund)]
        counts = {"refunds" if refund else "sales": 1}
        breakdown = fee_breakdown(tx, fee) if fee else {}
        buckets = {
            "ads": {t: v for t, v in breakdown.items() if is_ad_fee(t)},
            "fees": {t: v for t, v in breakdown.items() if not is_ad_fee(t)},
        }
        for bucket, by_type in buckets.items():
            total = sum(by_type.values())
            if not total:
                continue
            fvat, frate, fvrn, fnotes = _fee_vat(total, vs)
            what_fee = "advertising fees" if bucket == "ads" else "selling fees"
            fdesc = f"eBay {what_fee} {'credited back on refund' if refund else 'on order'} {order_id or tx_id}"
            split = "; ".join(f"{fee_label(t)} £{v / 100:.2f}" for t, v in sorted(by_type.items()))
            fdoc = _doc(
                "credit_note" if refund else "receipt",
                when=when,
                gross=total,
                vat=fvat,
                rate=frate,
                supplier=EBAY_SUPPLIER,
                supplier_vrn=fvrn,
                customer=None,
                ref=order_id or tx_id,
                category="Advertising" if bucket == "ads" else "Sundry",
                description=fdesc,
                parts=[(f"{fee_label(t)} ({order_id or tx_id})", v) for t, v in sorted(by_type.items())],
            )
            notes_f = [f"Imported from eBay: {fdesc}.", f"By eBay fee type: {split}.", *fnotes]
            part = "fees" if bucket == "fees" else "adfees"
            out.append(_proposal(key, part, fdoc, notes_f, ctx, expense="ads" if bucket == "ads" else "fees"))
            counts["ad_fees" if bucket == "ads" else "fees"] = 1
        return key, out, counts, None

    if kind in FEE_TYPES or kind == "SHIPPING_LABEL":
        postage = kind == "SHIPPING_LABEL"
        if postage:
            taxes = [t for t in tx.get("taxes") or [] if isinstance(t, dict) and str(t.get("taxType")).upper() == "VAT"]
            label_vat = sum(abs(pence(t.get("amount")) or 0) for t in taxes)
            vat, rate = (label_vat, UK_STANDARD) if vs.registered and label_vat else (0, None)
            vrn = vs.fee_vrn if vat else None
            notes = (
                [f"eBay reports £{label_vat / 100:.2f} VAT on this label."]
                + ([] if vrn else ["No eBay VAT number is saved, so the VAT stays in the cost."])
                if label_vat
                else ["eBay reports no VAT on this label; check eBay's invoice if you expected some."]
            )
        else:
            vat, rate, vrn, notes = _fee_vat(amount, vs)
        ad = not postage and is_ad_fee(str(tx.get("feeType") or ""), str(tx.get("transactionMemo") or ""))
        if not postage and tx.get("feeType"):
            notes.insert(0, f"eBay fee type: {fee_label(str(tx.get('feeType')).upper())}.")
        noun = "eBay postage label" if postage else "eBay advertising fee" if ad else "eBay selling fee"
        desc = noun + (f": {memo}" if memo else "") + f" ({tx_id})"
        doc = _doc(
            "credit_note" if credit else "receipt",
            when=when,
            gross=amount,
            vat=vat,
            rate=rate,
            supplier=EBAY_SUPPLIER,
            supplier_vrn=vrn,
            customer=None,
            ref=order_id or tx_id,
            category="Postage" if postage else "Advertising" if ad else "Sundry",
            description=desc,
        )
        part = "postage" if postage else "adfee" if ad else "fee"
        p = _proposal(
            key,
            part,
            doc,
            [f"Imported from eBay: {desc}" + (" (a credit)." if credit else "."), *notes],
            ctx,
            expense=None if postage else "ads" if ad else "fees",
        )
        return key, [p], {"postage" if postage else "ad_fees" if ad else "fees": 1}, None

    if kind in SKIPPED_TYPES:
        return skip(f"eBay {kind.lower().replace('_', ' ')}: not imported, book it by hand if it matters")
    return skip(f"unknown eBay transaction type {kind or '(none)'}")


def map_payout(raw: dict[str, Any]) -> EbayPayout | None:
    """A SUCCEEDED GBP payout, or None (pending, failed, reversed or odd: read again on the next sync)."""
    pid = str(raw.get("payoutId") or "").strip()[:128]
    when = _day(raw.get("payoutDate"))
    amount = pence(raw.get("amount"))
    if not pid or when is None or amount is None or str(raw.get("payoutStatus") or "").upper() != "SUCCEEDED":
        return None
    if currency(raw.get("amount")) not in ("", "GBP"):
        return None
    inst = raw.get("payoutInstrument") if isinstance(raw.get("payoutInstrument"), dict) else {}
    last4 = str((inst or {}).get("accountLastFourDigits") or "")[-4:] or None
    ref = str(raw.get("bankReference") or "").strip()[:200] or None
    return EbayPayout(payout_id=pid, date=when, amount_pence=abs(amount), last4=last4, bank_reference=ref)


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #


class SyncResult(SyncSummary):
    start: date
    end: date
    proposals: list[str] = []  # the new proposals' ids (all on Review)
    skipped_items: list[Skipped] = []
    warning: str | None = None  # a part that failed (order titles) while the rest went through


async def vat_settings(books: Books, fee_vrn: str | None) -> VatSettings:
    from app.invoicing import load_profile

    prof = await load_profile(books)
    return VatSettings(registered=prof.is_vat_registered, own_vrn=prof.vrn, fee_vrn=fee_vrn)


#: One sync at a time per books in this process (a double click, two tabs). Across processes and devices the
#: create-only proposal files (deterministic ids, proposal_id) are the guard; imported.json is only an index.
_SYNC_LOCKS: weakref.WeakValueDictionary[tuple[int, str], asyncio.Lock] = weakref.WeakValueDictionary()


def _sync_lock(books: Books) -> asyncio.Lock:
    storage = getattr(books.storage, "inner", books.storage)  # past the per-request memo (app/cache.py)
    k = (id(asyncio.get_running_loop()), books.cache_key or f"storage:{id(storage)}")
    lock = _SYNC_LOCKS.get(k)
    if lock is None:
        lock = _SYNC_LOCKS[k] = asyncio.Lock()
    return lock


def _kind(p: Proposal, accounts: Accounts) -> str:
    if p.sale_refund:
        return "refunds"
    if p.extracted.doc_type == "sales_invoice":
        return "sales"
    if p.account_override == accounts.ads:
        return "ad_fees"
    return "postage" if p.extracted.category_guess == "Postage" else "fees"


async def _create_proposal(books: Books, p: Proposal) -> bool:
    """Write the proposal only if no file has its id yet; False when one has (already imported, even if rejected)."""
    data = json.dumps(p.model_dump(mode="json"), indent=2, ensure_ascii=False).encode()
    try:
        await books.storage.write(f"{PROPOSALS}/{p.id}.json", data, create_only=True)
    except (FileExistsError, ConflictError):
        return False
    return True


async def sync(books: Books, user: str, days: int = DEFAULT_DAYS) -> SyncResult:
    """Fetch the last `days` days of eBay transactions and payouts; propose what is new. Posts nothing."""
    async with _sync_lock(books):
        return await _sync(books, user, days)


async def _sync(books: Books, user: str, days: int) -> SyncResult:
    cfg, key = _need()
    f = await load(books)
    conn = f.connection
    if conn is None:
        raise EbaySyncError("Connect eBay first")
    if conn.key_id != key_id(key):
        raise EbaySyncError(KEY_CHANGED)
    ref = await books_id(books)
    token = unseal(conn.token, key, ref, conn.connected_by)
    if token is None:
        raise EbaySyncError(MOVED)
    days = max(1, min(days, MAX_DAYS))
    end_day = today()
    start_day = end_day - timedelta(days=days)
    start = datetime.combine(start_day, dtime(0, 0), tzinfo=UTC)
    end = now().astimezone(UTC)
    warning = None
    async with client() as http:
        api = EbayApi(cfg, http)
        try:
            tokens = await api.refresh(token)
            access = str(tokens["access_token"])
            txs = await api.transactions(access, start, end)
            raw_payouts = await api.payouts(access, start, end)
        except EbayError as exc:
            again = " Connect eBay again." if exc.status in (400, 401) else ""
            raise EbaySyncError(f"eBay did not answer the sync: {exc.message}.{again}") from exc
        seen = await load_imported(books)
        wanted = sorted(
            {
                str(t.get("orderId"))
                for t in txs
                if t.get("orderId")
                and f"{str(t.get('transactionType') or '').upper()}:{t.get('transactionId')}" not in seen
            }
        )
        orders: dict[str, dict[str, Any]] = {}
        if wanted:
            try:
                orders = {str(o.get("orderId")): o for o in await api.orders(access, wanted)}
            except EbayError as exc:
                warning = f"Item titles could not be read from eBay ({exc.message}); the amounts are complete."
    from app.approve import final_journal  # local: approve imports much of the app
    from app.chart import ebay_accounts

    vs = await vat_settings(books, f.fee_vat_number)
    clearing, fees, ads = await ebay_accounts(books)
    accounts = Accounts(clearing=clearing, fees=fees, ads=ads)
    result = SyncResult(start=start_day, end=end_day, warning=warning)
    new_ids: dict[str, list[str]] = {}
    batch_seen: set[str] = set()
    for tx in txs:
        k, props, _, skipped = map_transaction(tx, vs, orders, ref, accounts)
        if k in seen or k in batch_seen:
            result.already_imported += 1
            continue
        batch_seen.add(k)
        if skipped is not None:
            result.skipped += 1
            result.skipped_items.append(skipped)
            result.skipped_types[skipped.type] = result.skipped_types.get(skipped.type, 0) + 1
            continue
        made = []
        for p in props:
            p.journal_draft = await final_journal(books, p)
            if await _create_proposal(books, p):
                made.append(p)
        new_ids[k] = [p.id for p in props]
        if not made:  # every part already on file: another sync proposed it, or this one was cut short before
            result.already_imported += 1
            continue
        for p in made:
            result.proposals.append(p.id)
            setattr(result, _kind(p, accounts), getattr(result, _kind(p, accounts)) + 1)
    payouts: list[EbayPayout] = []
    for raw in raw_payouts:
        po = map_payout(raw)
        if po is None:
            continue
        k = f"PAYOUT:{po.payout_id}"
        if k in seen or k in batch_seen:
            result.already_imported += 1
            continue
        batch_seen.add(k)
        payouts.append(po)
        new_ids[k] = []
    result.payouts = len(payouts)
    if new_ids:
        await _add_imported(books, new_ids)
    stamp = now()
    rotated = str(tokens.get("refresh_token") or "")

    def put(cur: EbayFile) -> EbayFile:
        if cur.connection is not None:
            cur.connection.last_synced_at = stamp
            cur.connection.last_summary = SyncSummary(**result.model_dump(include=set(SyncSummary.model_fields)))
            known = {p.payout_id for p in cur.connection.payouts}
            cur.connection.payouts = (cur.connection.payouts + [p for p in payouts if p.payout_id not in known])[-200:]
            if rotated:
                cur.connection.token = seal(rotated, key, ref, cur.connection.connected_by)
        return cur

    await _save(books, put)
    await books.audit(
        f"user:{user}",
        "ebay_synced",
        {**result.model_dump(include=set(SyncSummary.model_fields)), "days": days},
    )
    if result.proposals:
        await books.rebuild_safely(f"user:{user}")
    return result
