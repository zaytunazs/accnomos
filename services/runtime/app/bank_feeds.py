"""Bank feeds through TrueLayer's Data API (Open Banking), into the same bank lines a statement CSV makes.

Why TrueLayer, and what was compared: docs/research/BANK_FEEDS.md. No database (docs/ARCHITECTURE.md), so:

* **The server holds only the platform's credentials**, from env vars that are empty by default (the feature is
  then off, with a sentence saying so): `TRUELAYER_CLIENT_ID`, `TRUELAYER_CLIENT_SECRET`, `BANKFEEDS_REDIRECT_URI`
  (this runtime's `/books/bankfeeds/callback`, registered with TrueLayer) and `BANKFEEDS_TOKEN_KEY` (32 random
  bytes, base64). Sandbox only by default: `TRUELAYER_ENV=live` is refused unless `BANKFEEDS_LIVE=1`.
* **What the user's books keep**, `_System/bankfeeds.json`: per connection the bank's name, the accounts (name,
  type, last four digits), when the consent was given and when it expires, when it was last synced, and the
  **refresh token encrypted with the server's key** (AES-256-GCM, the connection id as associated data). TrueLayer
  gives a 1-hour access token and a 90-day refresh token; without the refresh token the user would have to sign in
  at their bank on every visit, so it is unavoidable. Encrypted, the file alone is useless (no key) and the key
  alone is useless (no file, which only the user's own Graph token can read). Changing the key makes every stored
  token unreadable: the connection then shows "connect again". Access tokens are never stored.
* **Consent lasts 90 days** (UK). Since FCA PS21/19 (in force 26 Mar 2022) the user reconfirms with us, not the
  bank, at least every 90 days, and we must stop reading when they don't. From RECONFIRM_DAYS before expiry the
  app asks; reconfirming calls TrueLayer's extend. After expiry the only way back is connecting again at the bank.
* **Connecting** is OAuth-shaped like Settings' payment links: a signed short-lived `state` binds the code to the
  browser that started it (`binding`) and to the user. TrueLayer sends the browser to the runtime's callback, which
  forwards code and state in the URL fragment to the Bank page; the page posts them back with the Graph token.
* **Transactions are fetched when the user opens the app** (no webhook: it would arrive without a Graph token).
  New lines go through the same pipeline as a CSV: filed as `04 Bank statements/{last date}_feed.csv`, stored in
  `_System/bank/{sha256}.json`, matched by the same code. A line already imported from a statement CSV is dropped
  (`accnomos_ledger.bank.pair_duplicates`: same amount, dates within 2 days, same reference or a word in common) is
  kept out of the bank lines and every total, but not thrown away: it is flagged in `_System/bankfeed_duplicates.json`
  with the statement line it paired with, listed after the fetch, and the user can add it back ("not a duplicate")
  when the fuzzy pairing was wrong. A feed line seen before (TrueLayer's `transaction_id`) is dropped. CSV import stays
  as the fallback.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field

from accnomos_ledger.bank import BankLine, pair_duplicates
from app.ai.config import is_test_mode
from app.books import BANK, BANK_LINES, SYSTEM, Books, now, today
from app.truelayer import (
    LIVE_API,
    LIVE_AUTH,
    LIVE_PROVIDERS,
    TrueLayerApi,
    TrueLayerConfig,
    TrueLayerError,
    auth_url,
    client,
    pence_from_amount,
)

FEEDS = f"{SYSTEM}/bankfeeds.json"
CONSENT_DAYS = 90  # UK AIS consent (FCA PS21/19; TrueLayer's refresh token lasts as long)
RECONFIRM_DAYS = 14  # ask the user to reconfirm from this many days before the consent ends
FIRST_SYNC_DAYS = 89  # how far back the first sync reads (banks give at least 90 days; some more)
OVERLAP_DAYS = 7  # later syncs re-read this far back: late-posted lines are caught, seen ones dropped by id
STATE_TTL_S = 900
TEST_TOKEN_KEY = base64.b64encode(b"accnomos-test-mode-bankfeed-key!").decode()  # 32 bytes, test mode only
ID_RE = re.compile(r"^[A-Za-z0-9_:-][A-Za-z0-9._:-]{0,127}$")  # ids put in a path or a file; never "." or ".."
OFF_SENTENCE = "Bank feeds are not set up on this server yet. Upload a statement CSV instead."

RECONNECT = "Reconnect your bank to keep it going."

# --- The demo sandbox (app/demo.py; docs/BANK_FEED_SANDBOX_DEMO.md) ---
#: What a demo's feed card and its connection say, everywhere.
DEMO_LABEL = "Bank sandbox (TrueLayer test bank) — no real bank data"
#: In a demo, TrueLayer's picker offers only its sandbox mock bank ("Mock"), never a real bank's own sandbox.
DEMO_PROVIDERS = "uk-cs-mock"
#: TrueLayer's public test login for that mock bank (https://docs.truelayer.com/docs/mock-users): `john` / `doe` signs
#: in and has example data. Published by TrueLayer for anyone's sandbox; not a secret, and not ours.
DEMO_TEST_LOGIN = {"username": "john", "password": "doe"}
DEMO_TEST_LOGIN_SOURCE = "https://docs.truelayer.com/docs/mock-users"
DEMO_OFF = (
    "Bank sandbox is not set up on this server, so the demo cannot connect a test bank. "
    "Upload a statement CSV instead: it is matched the same way."
)
DEMO_NOT_SANDBOX = (
    "This server's bank feeds point at live banks, and the demo only ever uses TrueLayer's test bank, so connecting "
    "a bank is switched off in the demo sandbox. Upload a statement CSV instead."
)
ConnectionState = Literal["ok", "reconfirm", "reconnect", "expired", "key_changed"]


class BankFeedError(ValueError):
    """Cannot do this with bank feeds (a 400)."""


class NotConfigured(BankFeedError):
    """The server has no TrueLayer credentials (a 503)."""


# --------------------------------------------------------------------------- #
# Server configuration (env only; nothing here is per user)
# --------------------------------------------------------------------------- #


def public_base() -> str:
    """This runtime as the browser reaches it (test mode only: the fake TrueLayer consent page)."""
    return os.getenv("RUNTIME_PUBLIC_URL", "").rstrip("/") or f"http://127.0.0.1:{os.getenv('PORT', '8780')}"


def _token_key_bytes(raw: str) -> bytes | None:
    try:  # standard or URL-safe base64, padded or not
        key = base64.urlsafe_b64decode(raw.replace("+", "-").replace("/", "_") + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == 32 else None


def config() -> tuple[TrueLayerConfig | None, bytes | None, str | None]:
    """(TrueLayer config, token key, None) when bank feeds can be used, else (None, None, why not, in a sentence)."""
    if is_test_mode():
        base = public_base()
        cfg = TrueLayerConfig(
            client_id="accnomos-fake-truelayer",
            client_secret="accnomos-fake-truelayer-secret",
            redirect_uri=f"{base}/books/bankfeeds/callback",
            auth_base=f"{base}/__test/truelayer",
        )
        return cfg, _token_key_bytes(TEST_TOKEN_KEY), None
    env = {
        k: os.getenv(k, "").strip()
        for k in ("TRUELAYER_CLIENT_ID", "TRUELAYER_CLIENT_SECRET", "BANKFEEDS_REDIRECT_URI", "BANKFEEDS_TOKEN_KEY")
    }
    if not all(env.values()):
        return None, None, OFF_SENTENCE
    key = _token_key_bytes(env["BANKFEEDS_TOKEN_KEY"])
    if key is None:
        return None, None, "Bank feeds are switched off: the server's token key is not 32 bytes of base64."
    live = os.getenv("TRUELAYER_ENV", "sandbox").strip().lower() == "live"
    if live and os.getenv("BANKFEEDS_LIVE", "").strip() != "1":
        return None, None, "This server points bank feeds at live banks, but they only run in the sandbox here."
    cfg = TrueLayerConfig(
        client_id=env["TRUELAYER_CLIENT_ID"],
        client_secret=env["TRUELAYER_CLIENT_SECRET"],
        redirect_uri=env["BANKFEEDS_REDIRECT_URI"],
        **({"auth_base": LIVE_AUTH, "api_base": LIVE_API, "providers": LIVE_PROVIDERS} if live else {}),
    )
    return cfg, key, None


def _need() -> tuple[TrueLayerConfig, bytes]:
    cfg, key, why = config()
    if cfg is None or key is None:
        raise NotConfigured(why or OFF_SENTENCE)
    return cfg, key


def demo_refusal() -> str | None:
    """Why a demo session cannot use bank feeds here, in a sentence; None when the server is on TrueLayer's sandbox."""
    cfg, key, _ = config()
    if cfg is None or key is None:
        return DEMO_OFF
    if not cfg.sandbox:
        return DEMO_NOT_SANDBOX
    return None


def demo_hash(session_id: str) -> str:
    """Names a demo session inside the signed state without carrying its id (the id is the visitor's bearer secret)."""
    return hashlib.sha256(b"accnomos-bankfeed-demo:" + session_id.encode()).hexdigest()[:32]


def key_id(key: bytes) -> str:
    """Names the key a token was sealed with, so a changed key reads as "connect again", not as an error."""
    return hashlib.sha256(b"accnomos-bankfeed-key-id:" + key).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# The refresh token, sealed with the server's key
# --------------------------------------------------------------------------- #


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def seal(token: str, key: bytes, connection_id: str) -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, token.encode(), f"accnomos-bankfeed:{connection_id}".encode())
    return f"v1.{_b64(nonce)}.{_b64(ct)}"


def unseal(sealed: str, key: bytes, connection_id: str) -> str | None:
    """The token, or None when the key or the connection id is not the one it was sealed with (or it is damaged)."""
    try:
        version, nonce, ct = sealed.split(".")
        if version != "v1":
            return None
        plain = AESGCM(key).decrypt(_unb64(nonce), _unb64(ct), f"accnomos-bankfeed:{connection_id}".encode())
    except (ValueError, InvalidTag, binascii.Error):
        return None
    return plain.decode()


# --------------------------------------------------------------------------- #
# Signed state (no session store; one use per step, kept in memory until it would expire)
# --------------------------------------------------------------------------- #


class StateError(ValueError):
    pass


_spent: dict[tuple[str, str], float] = {}


def _state_key() -> bytes:
    _, key = _need()
    return hashlib.sha256(b"accnomos-bankfeed-state:" + key).digest()


def user_hash(user: str) -> str:
    return hashlib.sha256(user.strip().lower().encode()).hexdigest()[:16]


def binding_hash(binding: str) -> str:
    return hashlib.sha256(binding.encode()).hexdigest()


def make_state(redirect_to: str, binding_hash_: str, user: str, demo_session: str | None = None) -> str:
    """Signed, short-lived; with `demo_session`, bound to that demo session (by a hash, `d`), so the code it brings
    back can only be connected in the same demo's books, and never in a signed-in user's."""
    body = {
        "r": redirect_to,
        "b": binding_hash_,
        "u": user_hash(user),
        "e": int(time.time()) + STATE_TTL_S,
        "n": secrets.token_urlsafe(12),
    }
    if demo_session is not None:
        body["d"] = demo_hash(demo_session)
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_state_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_state(state: str, use: str | None = None) -> dict[str, Any]:
    """Check the signature and the expiry; with `use`, spend the state for that step."""
    try:
        payload, sig = state.split(".")
        expected = _b64(hmac.new(_state_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig.encode(), expected.encode()):
            raise StateError("bad signature")
        data = json.loads(_unb64(payload))
        expires, nonce = float(data["e"]), str(data["n"])
        out = {
            "redirect_to": str(data["r"]),
            "binding_hash": str(data["b"]),
            "user_hash": str(data["u"]),
            "demo": str(data["d"]) if data.get("d") is not None else "",
        }
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


def allowed_origins() -> list[str]:
    return [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]


def check_redirect(url: str) -> str:
    """Only back to the Bank page on one of this server's web origins; the fragment is ours to set."""
    parts = urlsplit(url)
    if f"{parts.scheme}://{parts.netloc}" not in allowed_origins() or not parts.path.startswith("/bank"):
        raise BankFeedError("A bank feed can only come back to the Bank page in this app")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


# --------------------------------------------------------------------------- #
# The user's connections (in their books)
# --------------------------------------------------------------------------- #


class FeedAccount(BaseModel):
    id: str = Field(pattern=ID_RE.pattern)
    name: str = Field(max_length=200)
    type: str | None = Field(default=None, max_length=40)
    last4: str | None = Field(default=None, pattern=r"^[0-9]{1,4}$")
    currency: str = "GBP"


class FeedConnection(BaseModel):
    id: str = Field(pattern=ID_RE.pattern)  # TrueLayer's credentials_id
    provider: Literal["truelayer"] = "truelayer"
    sandbox: bool = True
    bank: str = Field(max_length=200)
    accounts: list[FeedAccount] = []
    consent_created_at: datetime | None = None
    consent_expires_at: datetime
    connected_at: datetime
    connected_by: str
    reconfirmed_at: datetime | None = None
    last_synced_at: datetime | None = None
    synced_to: date | None = None
    token: str  # the refresh token, sealed (see seal); never the access token
    key_id: str
    # TrueLayer said the user has to go back through the bank (extend answered authentication_needed, or the refresh
    # token was refused): nothing is read until they connect again.
    needs_reauth: bool = False


class FeedsFile(BaseModel):
    version: int = 1
    connections: list[FeedConnection] = []


async def load_feeds(books: Books) -> FeedsFile:
    raw = await books.read_json(FEEDS, {})
    out = FeedsFile()
    if isinstance(raw, dict):  # a hand-edited file loses only the connections that do not read
        for c in raw.get("connections") or []:
            with contextlib.suppress(ValueError, TypeError):
                out.connections.append(FeedConnection.model_validate(c))
    return out


async def _save(books: Books, change: Any) -> None:
    """Apply `change(FeedsFile) -> FeedsFile` to the stored file (read, change, write; ETag-checked by Books)."""

    def apply(old: Any) -> dict[str, Any]:
        cur = FeedsFile()
        if isinstance(old, dict):
            for c in old.get("connections") or []:
                with contextlib.suppress(ValueError, TypeError):
                    cur.connections.append(FeedConnection.model_validate(c))
        return change(cur).model_dump(mode="json")

    await books._update_json(FEEDS, {}, apply)


def _put(conn: FeedConnection) -> Any:
    def change(f: FeedsFile) -> FeedsFile:
        f.connections = [c for c in f.connections if c.id != conn.id] + [conn]
        return f

    return change


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


class ConnectionView(BaseModel):
    id: str
    bank: str
    sandbox: bool
    accounts: list[FeedAccount]
    consent_expires_at: datetime
    reconfirm_by: date  # the last day the user can reconfirm in the app
    days_left: int
    state: ConnectionState
    message: str
    connected_at: datetime
    last_synced_at: datetime | None
    synced_to: date | None


class TestLogin(BaseModel):
    """TrueLayer's public sandbox login for its mock bank, shown on a demo's card for the visitor to type."""

    username: str
    password: str
    source_url: str = DEMO_TEST_LOGIN_SOURCE


class FeedStatus(BaseModel):
    available: bool
    reason: str | None = None  # why not, in a sentence
    provider: str = "TrueLayer"
    sandbox: bool = True
    reconfirm_days: int = RECONFIRM_DAYS
    connections: list[ConnectionView] = []
    demo: bool = False  # a demo session: TrueLayer's sandbox test bank only, in the demo's own books
    label: str | None = None  # DEMO_LABEL in a demo
    test_login: TestLogin | None = None  # in a demo on the sandbox


def _london_day(ts: datetime) -> date:
    from app.books import LONDON

    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(LONDON).date()


def uk_date(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def view(conn: FeedConnection, key: bytes | None, on: date) -> ConnectionView:
    last_day = _london_day(conn.consent_expires_at)
    days = (last_day - on).days
    state: ConnectionState
    if key is not None and conn.key_id != key_id(key):
        state, msg = "key_changed", "This connection can't be read any more (the server's key changed). Connect again."
    elif days < 0:
        state, msg = "expired", f"Your consent ended on {uk_date(last_day)}. Connect again to keep the feed going."
    elif conn.needs_reauth:
        state, msg = "reconnect", f"{conn.bank} wants you to sign in at the bank again. {RECONNECT}"
    elif days <= RECONFIRM_DAYS:
        when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        state, msg = "reconfirm", f"Your 90-day consent ends {when} ({uk_date(last_day)}). Reconfirm to keep it going."
    else:
        state, msg = "ok", f"Consent runs to {uk_date(last_day)}."
    return ConnectionView(
        id=conn.id,
        bank=conn.bank,
        sandbox=conn.sandbox,
        accounts=conn.accounts,
        consent_expires_at=conn.consent_expires_at,
        reconfirm_by=last_day,
        days_left=days,
        state=state,
        message=msg,
        connected_at=conn.connected_at,
        last_synced_at=conn.last_synced_at,
        synced_to=conn.synced_to,
    )


async def status(books: Books, demo: bool = False) -> FeedStatus:
    cfg, key, why = config()
    feeds = await load_feeds(books)
    on = today()
    if demo:
        refusal = demo_refusal()
        return FeedStatus(
            available=refusal is None,
            reason=refusal,
            sandbox=True,
            connections=[view(c, key, on) for c in feeds.connections] if refusal is None else [],
            demo=True,
            label=DEMO_LABEL,
            test_login=TestLogin(**DEMO_TEST_LOGIN) if refusal is None else None,
        )
    return FeedStatus(
        available=cfg is not None,
        reason=why,
        sandbox=cfg.sandbox if cfg else True,
        connections=[view(c, key, on) for c in feeds.connections],
    )


# --------------------------------------------------------------------------- #
# Connect, reconfirm, disconnect
# --------------------------------------------------------------------------- #


def start(redirect_to: str, binding_hash_: str, user: str, demo_session: str | None = None) -> str:
    """TrueLayer's consent URL. For a demo session: only on the sandbox, only its mock bank, state bound to the demo."""
    cfg, _ = _need()
    if demo_session is not None:
        if (refusal := demo_refusal()) is not None:
            raise BankFeedError(refusal)
        cfg = replace(cfg, providers=DEMO_PROVIDERS)
    return auth_url(cfg, make_state(check_redirect(redirect_to), binding_hash_, user, demo_session))


def _finish(state: str, binding: str, user: str, demo_session: str | None = None) -> None:
    try:
        st = read_state(state, use="connect")
    except StateError as exc:
        raise BankFeedError("The bank sign-in has expired; connect again") from exc
    if not hmac.compare_digest(st["binding_hash"], binding_hash(binding)):
        raise BankFeedError("This bank sign-in was started in another browser")
    if st["user_hash"] != user_hash(user):
        raise BankFeedError("This bank sign-in was started by someone else")
    want = demo_hash(demo_session) if demo_session is not None else ""
    if not hmac.compare_digest(st["demo"], want):
        raise BankFeedError("This bank sign-in was started in another demo session; connect again")


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        got = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=UTC)


def _account(raw: dict[str, Any]) -> FeedAccount | None:
    acc_id = str(raw.get("account_id") or "")
    if not ID_RE.match(acc_id):
        return None
    number = raw.get("account_number") if isinstance(raw.get("account_number"), dict) else {}
    digits = re.sub(r"\D", "", str((number or {}).get("number") or ""))
    return FeedAccount(
        id=acc_id,
        name=str(raw.get("display_name") or "Account")[:200],
        type=str(raw.get("account_type") or "")[:40] or None,
        last4=digits[-4:] or None,
        currency=str(raw.get("currency") or "GBP")[:3],
    )


async def _describe(api: TrueLayerApi, access: str) -> tuple[str, str, datetime | None, datetime | None, list[Any]]:
    """(credentials id, bank name, consent created, consent expires, accounts) for a fresh access token."""
    me = await api.me(access)
    cred = str(me.get("credentials_id") or "")
    if not ID_RE.match(cred):
        raise BankFeedError("TrueLayer did not say which connection this is; connect again")
    provider = me.get("provider") if isinstance(me.get("provider"), dict) else {}
    bank = str((provider or {}).get("display_name") or "Your bank")[:200]
    accounts = [a for a in (_account(r) for r in await api.accounts(access)) if a is not None]
    return cred, bank, _ts(me.get("consent_created_at")), _ts(me.get("consent_expires_at")), accounts


async def connect(
    books: Books, code: str, state: str, binding: str, user: str, demo_session: str | None = None
) -> FeedConnection:
    """Exchange the code and save the connection in `books` (a demo's own in-memory books for a demo session)."""
    cfg, key = _need()
    if demo_session is not None and (refusal := demo_refusal()) is not None:
        raise BankFeedError(refusal)
    _finish(state, binding, user, demo_session)
    async with client() as http:
        api = TrueLayerApi(cfg, http)
        try:
            tokens = await api.exchange_code(code)
            refresh = str(tokens.get("refresh_token") or "")
            if not refresh:
                raise BankFeedError("TrueLayer gave no long-lived access (offline_access); connect again")
            cred, bank, created, expires, accounts = await _describe(api, str(tokens["access_token"]))
        except TrueLayerError as exc:
            raise BankFeedError(f"The bank feed was not connected: {exc.message}") from exc
    stamp = now()
    conn = FeedConnection(
        id=cred,
        sandbox=cfg.sandbox,
        bank=bank,
        accounts=accounts,
        consent_created_at=created or stamp,
        consent_expires_at=expires or (created or stamp) + timedelta(days=CONSENT_DAYS),
        connected_at=stamp,
        connected_by=user,
        token=seal(refresh, key, cred),
        key_id=key_id(key),
    )

    def put_replacing(f: FeedsFile) -> FeedsFile:
        # Reconnecting a bank that asked for a new sign-in replaces the stale connection rather than listing both.
        f.connections = [c for c in f.connections if not (c.needs_reauth and c.bank == conn.bank and c.id != conn.id)]
        return _put(conn)(f)

    await _save(books, put_replacing)
    await books.audit(
        f"user:{user}",
        "bank_feed_connected",
        {
            "connection": cred,
            "bank": bank,
            "accounts": len(accounts),
            "expires": conn.consent_expires_at.isoformat(),
            "sandbox": cfg.sandbox,
            **({"demo": True} if demo_session is not None else {}),
        },
    )
    return conn


async def _find(books: Books, connection_id: str) -> FeedConnection:
    for c in (await load_feeds(books)).connections:
        if c.id == connection_id:
            return c
    raise FileNotFoundError(connection_id)


def _refresh_token(conn: FeedConnection, key: bytes) -> str:
    token = unseal(conn.token, key, conn.id) if conn.key_id == key_id(key) else None
    if token is None:
        raise BankFeedError(
            f"The {conn.bank} connection can't be read any more (the server's key changed). Connect again."
        )
    return token


class ReconfirmResult(BaseModel):
    connection: ConnectionView | None = None
    reauthorise: bool = False  # the bank wants the user back: start Connect again
    message: str


REAUTH_ACTIONS = {"authentication_needed", "reconfirmation_of_consent_needed"}


def end_user(user: str, name: str | None) -> dict[str, str]:
    """The `user` object extend requires of an unregulated client: an id, a name and an email. The id is a hash of
    the email (no raw identifier as an id); the name is Microsoft's display name, else the email's local part."""
    email = user.strip()
    return {"id": user_hash(email), "name": (name or "").strip() or email.split("@", 1)[0], "email": email}


async def _mark_reauth(books: Books, connection_id: str) -> None:
    def change(f: FeedsFile) -> FeedsFile:
        for c in f.connections:
            if c.id == connection_id:
                c.needs_reauth = True
        return f

    await _save(books, change)


async def reconfirm(books: Books, connection_id: str, user: str, name: str | None = None) -> ReconfirmResult:
    """The user ticked "keep sharing" in the app: extend the consent at TrueLayer for another 90 days."""
    cfg, key = _need()
    conn = await _find(books, connection_id)
    if view(conn, key, today()).state == "expired":
        raise BankFeedError(f"The {conn.bank} consent has already ended; connect again")
    token = _refresh_token(conn, key)
    async with client() as http:
        api = TrueLayerApi(cfg, http)
        try:
            got = await api.extend(token, end_user(user, name))
            action = str(got.get("action_needed") or "")
            if action in REAUTH_ACTIONS or (got.get("user_input_link") and not got.get("access_token")):
                await _mark_reauth(books, conn.id)
                detail = {"connection": conn.id, "bank": conn.bank, "via": "extend"}
                await books.audit(f"user:{user}", "bank_feed_reauth_needed", detail)
                return ReconfirmResult(
                    reauthorise=True, message=f"{conn.bank} wants you to sign in at the bank again. {RECONNECT}"
                )
            if not got.get("access_token"):  # extend gave no tokens back: refresh to read the new expiry
                got = await api.refresh(token)
            _, _, _, expires, _ = await _describe(api, str(got["access_token"]))
        except TrueLayerError as exc:
            raise BankFeedError(f"{conn.bank} did not extend the consent: {exc.message}") from exc
    stamp = now()
    conn.reconfirmed_at = stamp
    conn.consent_expires_at = expires or stamp + timedelta(days=CONSENT_DAYS)
    if got.get("refresh_token"):
        conn.token = seal(str(got["refresh_token"]), key, conn.id)
    await _save(books, _put(conn))
    await books.audit(
        f"user:{user}",
        "bank_feed_reconfirmed",
        {"connection": conn.id, "bank": conn.bank, "expires": conn.consent_expires_at.isoformat()},
    )
    v = view(conn, key, today())
    return ReconfirmResult(connection=v, message=f"{conn.bank}: consent reconfirmed. {v.message}")


async def disconnect(books: Books, connection_id: str, user: str) -> str | None:
    """Forget the connection in the user's books and end it at TrueLayer. Lines already imported stay.
    Returns a warning when TrueLayer could not be told."""
    conn = await _find(books, connection_id)
    warning = None
    cfg, key, _ = config()
    if cfg is not None and key is not None:
        token = unseal(conn.token, key, conn.id) if conn.key_id == key_id(key) else None
        if token is not None:
            async with client() as http:
                api = TrueLayerApi(cfg, http)
                try:
                    await api.delete(str((await api.refresh(token))["access_token"]))
                except TrueLayerError as exc:
                    warning = f"TrueLayer did not confirm ({exc.message}); you can also stop sharing in your bank's app"
    await _save(books, lambda f: FeedsFile(connections=[c for c in f.connections if c.id != connection_id]))
    await books.audit(f"user:{user}", "bank_feed_disconnected", {"connection": conn.id, "bank": conn.bank})
    return warning


# --------------------------------------------------------------------------- #
# Sync: transactions into bank lines
# --------------------------------------------------------------------------- #


def feed_line_id(connection_id: str, account_id: str, transaction_id: str) -> str:
    return hashlib.sha256(f"feed|{connection_id}|{account_id}|{transaction_id}".encode()).hexdigest()[:16]


def to_line(raw: dict[str, Any], connection_id: str, account_id: str) -> BankLine | None:
    """One TrueLayer transaction as a bank line; None for another currency, no id, no date or an odd amount."""
    tx_id = str(raw.get("transaction_id") or "")
    when = _ts(raw.get("timestamp"))
    pence = pence_from_amount(raw.get("amount"))
    if not tx_id or when is None or pence is None or str(raw.get("currency") or "GBP").upper() != "GBP":
        return None
    kind = str(raw.get("transaction_type") or "").upper()
    if kind == "DEBIT":  # the sign is taken from the type, whichever way the bank signed the amount
        pence = -abs(pence)
    elif kind == "CREDIT":
        pence = abs(pence)
    balance = raw.get("running_balance") if isinstance(raw.get("running_balance"), dict) else None
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    ref = str((meta or {}).get("provider_reference") or "").strip() or None
    desc = re.sub(r"\s+", " ", str(raw.get("description") or raw.get("merchant_name") or "")).strip()
    return BankLine(
        id=feed_line_id(connection_id, account_id, tx_id),
        date=when.date(),
        amount_pence=pence,
        description=desc[:300] or "(no description)",
        reference=ref[:120] if ref else None,
        balance_pence=pence_from_amount((balance or {}).get("amount")) if balance else None,
        source_file="",
        feed_id=tx_id[:128],
    )


def feed_csv(lines: list[BankLine]) -> bytes:
    """The fetched lines as a statement CSV (the evidence filed in 04 Bank statements; parse_bank_csv reads it)."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Date", "Description", "Reference", "Amount", "Balance", "Transaction ID"])
    for ln in sorted(lines, key=lambda x: (x.date, x.id)):
        bal = "" if ln.balance_pence is None else f"{ln.balance_pence / 100:.2f}"
        w.writerow(
            [
                ln.date.strftime("%d/%m/%Y"),
                ln.description,
                ln.reference or "",
                f"{ln.amount_pence / 100:.2f}",
                bal,
                ln.feed_id,
            ]
        )
    return out.getvalue().encode("utf-8")


class ConnectionSync(BaseModel):
    id: str
    bank: str
    fetched: int = 0
    error: str | None = None  # in a sentence; the other connections still sync
    reauth: bool = False  # the bank wants the user to sign in again: show "Reconnect your bank"


class FlaggedDuplicate(BaseModel):
    """A feed line paired with a line a statement CSV already brought in: kept here, out of the bank lines and every
    total, until the user says it is a different payment ("not a duplicate")."""

    line_id: str
    date: date
    amount_pence: int
    description: str
    duplicate_of: str  # the statement line's id
    duplicate_of_date: date | None = None
    duplicate_of_description: str | None = None
    flagged_at: datetime


class SyncResult(BaseModel):
    new_lines: int
    already_imported: int  # lines a statement CSV had already brought in (flagged in `duplicates`, not in totals)
    already_fetched: int  # lines an earlier sync had already brought in (dropped)
    skipped: int  # not GBP, or no id / date / amount
    filed_path: str | None
    connections: list[ConnectionSync]
    duplicates: list[FlaggedDuplicate] = []  # flagged by this fetch; restore one with restore_duplicate


async def _fetch(
    api: TrueLayerApi, conn: FeedConnection, key: bytes, on: date
) -> tuple[list[BankLine], int, str | None]:
    """(lines, skipped, new refresh token or None) for one connection."""
    tokens = await api.refresh(_refresh_token(conn, key))
    access = str(tokens["access_token"])
    start = (conn.synced_to - timedelta(days=OVERLAP_DAYS)) if conn.synced_to else on - timedelta(days=FIRST_SYNC_DAYS)
    lines: list[BankLine] = []
    skipped = 0
    for acc in conn.accounts:
        for raw in await api.transactions(access, acc.id, start, on):
            ln = to_line(raw, conn.id, acc.id)
            if ln is None:
                skipped += 1
            else:
                lines.append(ln)
    return lines, skipped, (str(tokens["refresh_token"]) if tokens.get("refresh_token") else None)


async def sync(books: Books, user: str) -> SyncResult:
    """Fetch every live connection's transactions and add the lines not already in the books."""
    cfg, key = _need()
    feeds = await load_feeds(books)
    on = today()
    fetched: list[BankLine] = []
    skipped = 0
    per: list[ConnectionSync] = []
    updated: list[FeedConnection] = []
    reauth: list[str] = []
    async with client() as http:
        api = TrueLayerApi(cfg, http)
        for conn in feeds.connections:
            v = view(conn, key, on)
            row = ConnectionSync(id=conn.id, bank=conn.bank)
            per.append(row)
            if v.state in ("expired", "key_changed", "reconnect"):
                row.error = v.message  # consent over, or the bank wants a new sign-in: we must not read (PS21/19)
                row.reauth = v.state == "reconnect"
                continue
            try:
                lines, bad, rotated = await _fetch(api, conn, key, on)
            except TrueLayerError as exc:
                # A refused refresh token: the consent was withdrawn at the bank, or has lapsed there early.
                if exc.status in (400, 401):
                    row.error = f"{conn.bank}: {exc.message}. {RECONNECT}"
                    row.reauth = True
                    reauth.append(conn.id)
                else:
                    row.error = f"{conn.bank}: {exc.message}."
                continue
            except BankFeedError as exc:
                row.error = str(exc)
                continue
            row.fetched = len(lines)
            fetched += lines
            skipped += bad
            conn.last_synced_at, conn.synced_to = now(), on
            if rotated:
                conn.token = seal(rotated, key, conn.id)
            updated.append(conn)

    stored = await books.stored_bank_lines()
    flagged_before = await load_duplicates(books)
    # A line flagged before is "already fetched" too: the overlap re-reads it and it must not be flagged twice.
    seen_ids = {ln.feed_id for ln in stored if ln.feed_id}
    seen_ids |= {d.line.feed_id for d in flagged_before if d.line.feed_id}
    unique: dict[str, BankLine] = {}
    for ln in fetched:
        unique.setdefault(ln.id, ln)
    candidates = [ln for ln in unique.values() if ln.feed_id not in seen_ids]
    already_fetched = len(fetched) - len(candidates)
    statement_lines = {ln.id: ln for ln in stored if not ln.feed_id}
    dupes = pair_duplicates(candidates, list(statement_lines.values()))
    fresh = [ln for ln in candidates if ln.id not in dupes]
    stamp = now()
    flagged = [_Flagged(line=ln, duplicate_of=dupes[ln.id], flagged_at=stamp) for ln in candidates if ln.id in dupes]

    filed = await _file_lines(books, fresh) if fresh else None
    if flagged:
        await _save_duplicates(
            books, lambda cur: cur + [f for f in flagged if f.line.id not in {c.line.id for c in cur}]
        )

    if updated or reauth:
        by_id = {c.id: c for c in updated}

        def change(f: FeedsFile) -> FeedsFile:
            f.connections = [by_id.get(c.id, c) for c in f.connections]
            for c in f.connections:
                if c.id in reauth:
                    c.needs_reauth = True
            return f

        await _save(books, change)
    if updated or fresh:
        await books.audit(
            f"user:{user}",
            "bank_feed_synced",
            {
                "new": len(fresh),
                "duplicates": len(dupes),
                "connections": len(updated),
                **({"path": filed} if filed else {}),
            },
        )
    if fresh:
        await books.rebuild_safely(f"user:{user}")
    return SyncResult(
        new_lines=len(fresh),
        already_imported=len(dupes),
        already_fetched=already_fetched,
        skipped=skipped,
        filed_path=filed,
        connections=per,
        duplicates=[f.view(statement_lines) for f in flagged],
    )


# --------------------------------------------------------------------------- #
# Feed lines flagged as duplicates of statement lines (kept, never in totals, restorable)
# --------------------------------------------------------------------------- #

DUPLICATES = f"{SYSTEM}/bankfeed_duplicates.json"


class _Flagged(BaseModel):
    line: BankLine
    duplicate_of: str
    flagged_at: datetime

    def view(self, statement_lines: dict[str, BankLine]) -> FlaggedDuplicate:
        other = statement_lines.get(self.duplicate_of)
        return FlaggedDuplicate(
            line_id=self.line.id,
            date=self.line.date,
            amount_pence=self.line.amount_pence,
            description=self.line.description,
            duplicate_of=self.duplicate_of,
            duplicate_of_date=other.date if other else None,
            duplicate_of_description=other.description if other else None,
            flagged_at=self.flagged_at,
        )


async def load_duplicates(books: Books) -> list[_Flagged]:
    raw = await books.read_json(DUPLICATES, [])
    out: list[_Flagged] = []
    for item in raw if isinstance(raw, list) else []:
        with contextlib.suppress(ValueError, TypeError):
            out.append(_Flagged.model_validate(item))
    return out


async def _save_duplicates(books: Books, change: Any) -> None:
    def apply(old: Any) -> list[dict[str, Any]]:
        cur: list[_Flagged] = []
        for item in old if isinstance(old, list) else []:
            with contextlib.suppress(ValueError, TypeError):
                cur.append(_Flagged.model_validate(item))
        return [f.model_dump(mode="json") for f in change(cur)]

    await books._update_json(DUPLICATES, [], apply)


async def _file_lines(books: Books, lines: list[BankLine]) -> str:
    """File feed lines as the evidence CSV in 04 Bank statements and store them as bank lines; the CSV's path."""
    data = feed_csv(lines)
    sha = hashlib.sha256(data).hexdigest()
    filed = await books.free_path(BANK, f"{max(ln.date for ln in lines).isoformat()}_feed.csv")
    await books.storage.write(filed, data)
    for ln in lines:
        ln.source_file = filed
    await books.write_json(f"{BANK_LINES}/{sha}.json", [ln.model_dump(mode="json") for ln in lines])
    return filed


async def list_duplicates(books: Books) -> list[FlaggedDuplicate]:
    statement_lines = {ln.id: ln for ln in await books.stored_bank_lines() if not ln.feed_id}
    return [f.view(statement_lines) for f in sorted(await load_duplicates(books), key=lambda f: f.line.date)]


async def restore_duplicate(books: Books, line_id: str, user: str) -> list[FlaggedDuplicate]:
    """The user said a flagged feed line is a different payment: add it to the bank lines. FileNotFoundError when no
    such flagged line."""
    item = next((f for f in await load_duplicates(books) if f.line.id == line_id), None)
    if item is None:
        raise FileNotFoundError(line_id)
    if any(ln.id == line_id for ln in await books.stored_bank_lines()):  # restored already (a second tab)
        await _save_duplicates(books, lambda cur: [f for f in cur if f.line.id != line_id])
        return await list_duplicates(books)
    filed = await _file_lines(books, [item.line.model_copy()])
    await _save_duplicates(books, lambda cur: [f for f in cur if f.line.id != line_id])
    await books.audit(
        f"user:{user}",
        "bank_feed_duplicate_restored",
        {"line": line_id, "was_paired_with": item.duplicate_of, "path": filed},
    )
    await books.rebuild_safely(f"user:{user}")
    return await list_duplicates(books)
