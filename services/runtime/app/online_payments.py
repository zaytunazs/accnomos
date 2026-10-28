"""Payment links on invoices, paid into the user's own Stripe or PayPal account, and matched back into the books.

No database (docs/ARCHITECTURE.md), so:

* **The server holds only the platform's credentials**, from env vars that are empty by default (each feature is then
  off, with a sentence saying so): `STRIPE_SECRET_KEY` + `STRIPE_CONNECT_CLIENT_ID` + `STRIPE_REDIRECT_URI`, and
  `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` + `PAYPAL_PARTNER_MERCHANT_ID` + `PAYPAL_PARTNER_ATTRIBUTION_ID` +
  `PAYPAL_RETURN_URL`. Test mode only: a live Stripe key or PayPal's live API is refused unless `PAYMENTS_LIVE=1`.
* **The user's link to their own account lives in their books**, `_System/Payments/providers.json`: the connected
  Stripe account id (`acct_…`) or PayPal merchant id and when it was linked. Never a secret, never a token: Stripe
  calls are made with the platform key plus `Stripe-Account`, PayPal calls with the platform token plus
  `PayPal-Auth-Assertion` naming the merchant, so neither provider hands us anything worth storing.
* **Connecting** is OAuth-shaped, like the HMRC relay: a signed, short-lived `state` (HMAC, one use per step) carries
  where to come back to and a hash of a secret only the user's browser holds (`binding`), so a code started in
  someone else's browser cannot link their account to this user's books. The provider sends the browser to the
  runtime's callback, which checks the state and forwards code and state in the URL fragment to Settings; Settings
  posts them back with the user's Graph token, and only then is anything exchanged or written.
* **Payments are found when the user opens the app**, not by webhook: a webhook arrives with no Graph token, so the
  runtime could not write the payment to the user's OneDrive, and there is nowhere else to keep it. Opening Invoices
  calls `GET /payments/online/check`, which asks the provider about each sent invoice that has a link. Each payment
  found is a proposal: the user approves it, and code posts the money received into the provider's clearing account
  (Dr 1230 Stripe clearing or 1240 PayPal clearing / Cr 1100 Debtors, via app/payments.py) and the provider's fee as
  its own expense (Dr 7900 Bank charges, VAT exempt / Cr the clearing account). Nothing is ever posted on its own.
* **Payouts.** The money reaches the bank later, as one payout per batch, net of fees. That statement line is
  matched as a payout (`match_payout`): Dr 1200 Bank / Cr the clearing account, so the receipt is counted once
  (in the clearing account), the bank only when the money arrives, and the clearing account's balance is what the
  provider still holds. Before clearing accounts, receipts went straight to 1200 Bank and the payout line was a
  second receipt of the same money.
* **PayPal.me** needs no API at all: a `paypal.me/<name>/<amount>GBP` link. PayPal cannot tell us about those
  payments, so they are recorded by hand like a bank transfer.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app.ai.config import is_test_mode
from app.books import SYSTEM, Books, now
from app.invoicing import (
    Invoice,
    InvoiceError,
    InvoiceStateError,
    PaymentLink,
    get_invoice,
    list_invoices,
    money,
    save_invoice,
)
from app.journal import BANK, CATEGORY_ACCOUNTS, CLEARING
from app.payment_providers import (
    PAYPAL_SANDBOX,
    PayPalApi,
    PayPalConfig,
    ProviderError,
    StripeApi,
    StripeConfig,
    client,
    paypal_value,
    pence_from_paypal,
    recipient_view_url,
)

PROVIDERS = f"{SYSTEM}/Payments/providers.json"  # beside payments.json; OneDrive ignores case
STATE_TTL_S = 900  # Stripe's authorisation code lasts 5 minutes; PayPal sign-up can take longer
FEES = CATEGORY_ACCOUNTS["Bank charges"]  # 7900 Bank charges
LONDON = ZoneInfo("Europe/London")
Provider = Literal["stripe", "paypal", "paypalme"]
MAX_CHECKED = 50  # invoices asked about per check; the oldest due first
PAYPALME_RE = re.compile(r"[A-Za-z0-9]{1,30}")  # UNVERIFIED: PayPal publishes no exact rule for PayPal.me names


class OnlinePaymentError(InvoiceError):
    """Cannot do this with online payments (a 400)."""


class NotConfigured(OnlinePaymentError):
    """The server has no platform credentials for this provider (a 503)."""


# --------------------------------------------------------------------------- #
# Server configuration (env only; nothing here is per user)
# --------------------------------------------------------------------------- #


def live_allowed() -> bool:
    return os.getenv("PAYMENTS_LIVE", "").strip() == "1"


def public_base() -> str:
    """This runtime as the browser reaches it (test mode only: the fakes' pages and the fake consent screens)."""
    return os.getenv("RUNTIME_PUBLIC_URL", "").rstrip("/") or f"http://127.0.0.1:{os.getenv('PORT', '8780')}"


def stripe_config() -> tuple[StripeConfig | None, str | None]:
    """(config, None) when Stripe payment links can be used, else (None, why not, in a sentence)."""
    if is_test_mode():
        base = public_base()
        return (
            StripeConfig(
                secret_key="sk_test_accnomos_fake",
                client_id="ca_accnomos_fake",
                redirect_uri=f"{base}/payments/online/stripe/callback",
                authorize_url=f"{base}/__test/stripe/oauth/authorize",
            ),
            None,
        )
    key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    cid = os.getenv("STRIPE_CONNECT_CLIENT_ID", "").strip()
    redirect = os.getenv("STRIPE_REDIRECT_URI", "").strip()
    if not (key and cid and redirect):
        return None, "Stripe payment links are not set up on this server yet."
    cfg = StripeConfig(secret_key=key, client_id=cid, redirect_uri=redirect)
    if not cfg.test_mode and not live_allowed():
        return None, "This server has a live Stripe key, but payment links only run in test mode here."
    return cfg, None


def paypal_config() -> tuple[PayPalConfig | None, str | None]:
    if is_test_mode():
        return (
            PayPalConfig(
                client_id="accnomos-fake-client",
                client_secret="accnomos-fake-secret",
                partner_merchant_id="FAKEPARTNER1",
                attribution_id="ACCNOMOS_FAKE_BN",
                return_url=f"{public_base()}/payments/online/paypal/callback",
            ),
            None,
        )
    env = {
        k: os.getenv(k, "").strip()
        for k in (
            "PAYPAL_CLIENT_ID",
            "PAYPAL_CLIENT_SECRET",
            "PAYPAL_PARTNER_MERCHANT_ID",
            "PAYPAL_PARTNER_ATTRIBUTION_ID",
            "PAYPAL_RETURN_URL",
        )
    }
    if not all(env.values()):
        return None, "PayPal payment links are not set up on this server yet."
    cfg = PayPalConfig(
        client_id=env["PAYPAL_CLIENT_ID"],
        client_secret=env["PAYPAL_CLIENT_SECRET"],
        partner_merchant_id=env["PAYPAL_PARTNER_MERCHANT_ID"],
        attribution_id=env["PAYPAL_PARTNER_ATTRIBUTION_ID"],
        return_url=env["PAYPAL_RETURN_URL"],
        base=os.getenv("PAYPAL_BASE", "").strip().rstrip("/") or PAYPAL_SANDBOX,
    )
    if not cfg.test_mode and not live_allowed():
        return None, "This server points at PayPal's live API, but payment links only run in the sandbox here."
    return cfg, None


def _need_stripe() -> StripeConfig:
    cfg, why = stripe_config()
    if cfg is None:
        raise NotConfigured(why or "Stripe is not set up")
    return cfg


def _need_paypal() -> PayPalConfig:
    cfg, why = paypal_config()
    if cfg is None:
        raise NotConfigured(why or "PayPal is not set up")
    return cfg


# --------------------------------------------------------------------------- #
# Signed state (no session store; one use per step, kept in memory until it would expire)
# --------------------------------------------------------------------------- #


class StateError(ValueError):
    pass


@dataclass(frozen=True)
class AuthState:
    provider: str
    redirect_to: str
    binding_hash: str
    user_hash: str
    nonce: str


_spent: dict[tuple[str, str], float] = {}


def _b64(b: bytes) -> str:
    return urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _state_key(provider: str) -> bytes:
    secret = os.getenv("PAYMENTS_STATE_KEY", "").strip()
    if not secret:
        cfg: StripeConfig | PayPalConfig | None = stripe_config()[0] if provider == "stripe" else paypal_config()[0]
        if cfg is None:
            raise NotConfigured(f"{provider} is not set up on this server")
        secret = cfg.secret_key if isinstance(cfg, StripeConfig) else cfg.client_secret
    return hashlib.sha256(f"accnomos-payments-state:{provider}:{secret}".encode()).digest()


def user_hash(user: str) -> str:
    return hashlib.sha256(user.strip().lower().encode()).hexdigest()[:16]


def make_state(provider: str, redirect_to: str, binding_hash: str, user: str) -> str:
    nonce = secrets.token_urlsafe(12)
    payload = _b64(
        json.dumps(
            {
                "p": provider,
                "r": redirect_to,
                "b": binding_hash,
                "u": user_hash(user),
                "e": int(time.time()) + STATE_TTL_S,
                "n": nonce,
            },
            separators=(",", ":"),
        ).encode()
    )
    sig = _b64(hmac.new(_state_key(provider), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_state(state: str, provider: str, use: str | None = None) -> AuthState:
    """Check the signature, the provider and the expiry; with `use`, spend the state for that step."""
    try:
        payload, sig = state.split(".")
        expected = _b64(hmac.new(_state_key(provider), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig.encode(), expected.encode()):
            raise StateError("bad signature")
        data = json.loads(_unb64(payload))
        got = AuthState(
            provider=str(data["p"]),
            redirect_to=str(data["r"]),
            binding_hash=str(data["b"]),
            user_hash=str(data["u"]),
            nonce=str(data["n"]),
        )
        expires = float(data["e"])
    except StateError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise StateError("malformed state") from exc
    if got.provider != provider:
        raise StateError("state is for another provider")
    now_s = time.time()
    if expires < now_s:
        raise StateError("state expired")
    if use:
        for k in [k for k, exp in _spent.items() if exp < now_s]:
            del _spent[k]
        if (use, got.nonce) in _spent:
            raise StateError("state already used")
        _spent[(use, got.nonce)] = expires
    return got


def binding_hash(binding: str) -> str:
    return hashlib.sha256(binding.encode()).hexdigest()


def allowed_origins() -> list[str]:
    return [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]


def check_redirect(url: str) -> str:
    """Only back to Settings on one of this server's web origins; the fragment is ours to set."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in allowed_origins() or not parts.path.startswith("/settings"):
        raise OnlinePaymentError("Payments can only come back to Settings in this app")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _finish(state: str, provider: str, binding: str, user: str) -> AuthState:
    try:
        st = read_state(state, provider, use="connect")
    except StateError as exc:
        raise OnlinePaymentError(f"The {provider_label(provider)} sign-in has expired; connect again") from exc
    if not hmac.compare_digest(st.binding_hash, binding_hash(binding)):
        raise OnlinePaymentError(f"This {provider_label(provider)} sign-in was started in another browser")
    if st.user_hash != user_hash(user):
        raise OnlinePaymentError(f"This {provider_label(provider)} sign-in was started by someone else")
    return st


def provider_label(provider: str) -> str:
    return {"stripe": "Stripe", "paypal": "PayPal", "paypalme": "PayPal.me"}.get(provider, provider)


# --------------------------------------------------------------------------- #
# The user's connections (in their books)
# --------------------------------------------------------------------------- #


class StripeConnection(BaseModel):
    account_id: str = Field(pattern=r"^acct_[A-Za-z0-9]{1,64}$")
    livemode: bool = False
    connected_at: datetime
    connected_by: str


class PayPalConnection(BaseModel):
    merchant_id: str = Field(pattern=r"^[A-Za-z0-9]{5,32}$")
    sandbox: bool = True
    connected_at: datetime
    connected_by: str


class PayPalMe(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9]{1,30}$")
    set_at: datetime
    set_by: str


class Connections(BaseModel):
    stripe: StripeConnection | None = None
    paypal: PayPalConnection | None = None
    paypalme: PayPalMe | None = None


async def load_connections(books: Books) -> Connections:
    raw = await books.read_json(PROVIDERS, {})
    out = Connections()
    if isinstance(raw, dict):  # a hand-edited file loses only the part that does not read
        for name, model in (("stripe", StripeConnection), ("paypal", PayPalConnection), ("paypalme", PayPalMe)):
            with contextlib.suppress(ValueError, TypeError):
                if raw.get(name):
                    setattr(out, name, model.model_validate(raw[name]))
    return out


async def _save_connection(books: Books, name: str, value: BaseModel | None) -> None:
    payload = value.model_dump(mode="json") if value is not None else None

    def change(old: Any) -> dict[str, Any]:
        cur = dict(old) if isinstance(old, dict) else {}
        if payload is None:
            cur.pop(name, None)
        else:
            cur[name] = payload
        return cur

    await books._update_json(PROVIDERS, {}, change)


class ProviderStatus(BaseModel):
    provider: Provider
    label: str
    available: bool  # this server can do it
    reason: str | None = None  # why not, in a sentence
    test_mode: bool
    connected: bool
    account: str | None = None  # acct_…, the merchant id, or the PayPal.me name
    connected_at: datetime | None = None
    can_match: bool  # payments through it are found by code (not PayPal.me)


async def status(books: Books) -> list[ProviderStatus]:
    c = await load_connections(books)
    s_cfg, s_why = stripe_config()
    p_cfg, p_why = paypal_config()
    return [
        ProviderStatus(
            provider="stripe",
            label="Stripe",
            available=s_cfg is not None,
            reason=s_why,
            test_mode=s_cfg.test_mode if s_cfg else True,
            connected=c.stripe is not None,
            account=c.stripe.account_id if c.stripe else None,
            connected_at=c.stripe.connected_at if c.stripe else None,
            can_match=True,
        ),
        ProviderStatus(
            provider="paypal",
            label="PayPal",
            available=p_cfg is not None,
            reason=p_why,
            test_mode=p_cfg.test_mode if p_cfg else True,
            connected=c.paypal is not None,
            account=c.paypal.merchant_id if c.paypal else None,
            connected_at=c.paypal.connected_at if c.paypal else None,
            can_match=True,
        ),
        ProviderStatus(
            provider="paypalme",
            label="PayPal.me",
            available=True,
            test_mode=False,
            connected=c.paypalme is not None,
            account=c.paypalme.username if c.paypalme else None,
            connected_at=c.paypalme.set_at if c.paypalme else None,
            can_match=False,
        ),
    ]


# --- Stripe: connect ------------------------------------------------------------------------------------------


def stripe_authorize_url(redirect_to: str, binding_hash_: str, user: str) -> str:
    from urllib.parse import urlencode

    cfg = _need_stripe()
    state = make_state("stripe", check_redirect(redirect_to), binding_hash_, user)
    q = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "scope": "read_write",
        "redirect_uri": cfg.redirect_uri,
        "state": state,
    }
    return f"{cfg.authorize_url}?{urlencode(q)}"


async def connect_stripe(books: Books, code: str, state: str, binding: str, user: str) -> StripeConnection:
    cfg = _need_stripe()
    _finish(state, "stripe", binding, user)
    async with client() as http:
        api = StripeApi(cfg, http)
        try:
            got = await api.exchange_code(code)
        except ProviderError as exc:
            raise OnlinePaymentError(f"Stripe did not link the account: {exc.message}") from exc
        account = str(got.get("stripe_user_id") or "")
        livemode = bool(got.get("livemode"))
        if livemode and not live_allowed():
            with contextlib.suppress(ProviderError):
                await api.deauthorize(account)
            raise OnlinePaymentError("That Stripe account was linked in live mode; this server only uses test mode")
    conn = StripeConnection(account_id=account, livemode=livemode, connected_at=now(), connected_by=user)
    await _save_connection(books, "stripe", conn)
    await books.audit(
        f"user:{user}", "payment_provider_connected", {"provider": "stripe", "account": account, "test": not livemode}
    )
    return conn


# --- PayPal: connect ------------------------------------------------------------------------------------------


async def paypal_signup_url(redirect_to: str, binding_hash_: str, user: str) -> str:
    from urllib.parse import urlencode

    cfg = _need_paypal()
    state = make_state("paypal", check_redirect(redirect_to), binding_hash_, user)
    nonce = read_state(state, "paypal").nonce
    sep = "&" if "?" in cfg.return_url else "?"
    async with client() as http:
        try:
            return await PayPalApi(cfg, http).partner_referral(
                tracking_id=nonce, return_url=f"{cfg.return_url}{sep}{urlencode({'state': state})}"
            )
        except ProviderError as exc:
            raise OnlinePaymentError(f"PayPal did not start the sign-up: {exc.message}") from exc


async def connect_paypal(books: Books, merchant_id: str, state: str, binding: str, user: str) -> PayPalConnection:
    """Link the merchant PayPal sent back, once PayPal itself says it finished onboarding with this sign-up."""
    cfg = _need_paypal()
    st = _finish(state, "paypal", binding, user)
    if not re.fullmatch(r"[A-Za-z0-9]{5,32}", merchant_id):
        raise OnlinePaymentError("PayPal sent back a merchant id that does not look right")
    async with client() as http:
        try:
            info = await PayPalApi(cfg, http).merchant_status(merchant_id)
        except ProviderError as exc:
            raise OnlinePaymentError(f"PayPal could not confirm the account: {exc.message}") from exc
    if str(info.get("tracking_id") or "") != st.nonce:  # the merchant onboarded through this sign-up, not another
        raise OnlinePaymentError("That PayPal account was not linked through this sign-up; connect again")
    if not info.get("payments_receivable"):
        raise OnlinePaymentError("PayPal says this account cannot receive payments yet; finish setting it up in PayPal")
    if not info.get("primary_email_confirmed"):
        raise OnlinePaymentError("Confirm your email address with PayPal first, then connect again")
    if not info.get("oauth_integrations"):
        raise OnlinePaymentError("PayPal did not give Accnomos permission to make invoices; connect again")
    conn = PayPalConnection(merchant_id=merchant_id, sandbox=cfg.test_mode, connected_at=now(), connected_by=user)
    await _save_connection(books, "paypal", conn)
    await books.audit(
        f"user:{user}",
        "payment_provider_connected",
        {"provider": "paypal", "account": merchant_id, "test": cfg.test_mode},
    )
    return conn


async def set_paypalme(books: Books, username: str, user: str) -> PayPalMe:
    name = username.strip().removeprefix("https://").removeprefix("www.").removeprefix("paypal.me/").strip("/")
    if not PAYPALME_RE.fullmatch(name):
        raise OnlinePaymentError("A PayPal.me name is letters and numbers only, e.g. SamBuilds")
    me = PayPalMe(username=name, set_at=now(), set_by=user)
    await _save_connection(books, "paypalme", me)
    await books.audit(f"user:{user}", "payment_provider_connected", {"provider": "paypalme", "account": name})
    return me


async def disconnect(books: Books, provider: Provider, user: str) -> str | None:
    """Forget the link in the user's books (and, for Stripe, tell Stripe). Returns a warning, if any."""
    c = await load_connections(books)
    warning = None
    if provider == "stripe" and c.stripe:
        cfg, _ = stripe_config()
        if cfg is not None:
            async with client() as http:
                try:
                    await StripeApi(cfg, http).deauthorize(c.stripe.account_id)
                except ProviderError as exc:
                    warning = f"Stripe did not confirm the disconnect ({exc.message}); check Connected apps in Stripe"
    elif provider == "paypal" and c.paypal:
        warning = "To stop Accnomos acting for you in PayPal too, remove it under Account settings in PayPal"
    if getattr(c, provider) is None:
        raise OnlinePaymentError(f"{provider_label(provider)} is not connected")
    await _save_connection(books, provider, None)
    await books.audit(f"user:{user}", "payment_provider_disconnected", {"provider": provider})
    return warning


# --------------------------------------------------------------------------- #
# Links on invoices
# --------------------------------------------------------------------------- #


async def outstanding(books: Books, inv: Invoice) -> int:
    """What the link is for: the total of a draft, the balance of a sent invoice (after part payments and credits)."""
    if inv.status == "draft":
        return inv.total_pence
    if inv.status != "sent" or not inv.event_id:
        raise InvoiceStateError(f"Invoice {inv.number} is {inv.status}; only a draft or an unpaid invoice takes a link")
    from app import payments

    m = payments.invoice_money(inv, await payments.load_ledger(books))
    return m.balance_pence if m else inv.total_pence


def paypalme_url(username: str, pence: int) -> str:
    """https://paypal.me/<name>/<amount><currency> (PayPal Help Centre, 'What is PayPal.Me?', checked 28 Oct 2026:
    'PayPal.Me/DiaRusso/25AUD'; the decimal form '10.50GBP' redirected with its path kept on the same day)."""
    return f"https://paypal.me/{username}/{paypal_value(pence)}GBP"


async def _switch_off(link: PaymentLink, c: Connections) -> str | None:
    """Stop the old link taking money. Returns a warning when the provider could not be told."""
    try:
        if link.provider == "stripe" and link.provider_ref:
            cfg = _need_stripe()
            if not c.stripe or c.stripe.account_id != link.account_ref:
                return "The old Stripe link is on an account that is no longer connected; switch it off in Stripe"
            async with client() as http:
                await StripeApi(cfg, http).deactivate_link(c.stripe.account_id, link.provider_ref)
        elif link.provider == "paypal" and link.provider_ref:
            cfg = _need_paypal()
            if not c.paypal or c.paypal.merchant_id != link.account_ref:
                return "The old PayPal invoice is on an account that is no longer connected; cancel it in PayPal"
            async with client() as http:
                await PayPalApi(cfg, http).cancel_invoice(c.paypal.merchant_id, link.provider_ref)
    except (ProviderError, NotConfigured) as exc:
        return f"The old {provider_label(link.provider)} link could not be switched off ({exc}); do it there"
    return None


async def add_link(books: Books, number: str, provider: Provider, user: str) -> tuple[Invoice, str | None]:
    """Make a payment link for what is owed on the invoice and keep it on the invoice (replacing an old one, which
    is switched off first). Returns the invoice and a warning when the old link could not be switched off."""
    inv = await get_invoice(books, number)
    amount = await outstanding(books, inv)
    if amount <= 0:
        raise InvoiceStateError(f"Invoice {number} has nothing left to pay")
    c = await load_connections(books)
    ref = secrets.token_hex(8)
    if provider == "stripe":
        cfg = _need_stripe()
        if not c.stripe:
            raise OnlinePaymentError("Connect Stripe in Settings › Online payments first")
        async with client() as http:
            try:
                made = await StripeApi(cfg, http).create_link(
                    c.stripe.account_id,
                    amount_pence=amount,
                    invoice_number=number,
                    ref=ref,
                    idempotency_key=f"accnomos-{ref}",
                )
            except ProviderError as exc:
                raise OnlinePaymentError(f"Stripe did not make the link: {exc.message}") from exc
        link = PaymentLink(
            provider="stripe",
            url=str(made["url"]),
            amount_pence=amount,
            test_mode=not c.stripe.livemode,
            provider_ref=str(made["id"]),
            account_ref=c.stripe.account_id,
            ref=ref,
            created_by=user,
        )
    elif provider == "paypal":
        cfg = _need_paypal()
        if not c.paypal:
            raise OnlinePaymentError("Connect PayPal in Settings › Online payments first")
        async with client() as http:
            try:
                made = await PayPalApi(cfg, http).create_invoice(
                    c.paypal.merchant_id,
                    number=number,
                    amount_pence=amount,
                    ref=ref,
                    customer_name=inv.customer.name,
                    customer_email=inv.customer.email,
                    request_id=f"accnomos-{ref}",
                )
            except ProviderError as exc:
                raise OnlinePaymentError(f"PayPal did not make the invoice: {exc.message}") from exc
        url = recipient_view_url(made)
        if not url:
            raise OnlinePaymentError("PayPal made the invoice but gave no link to pay it; try again")
        link = PaymentLink(
            provider="paypal",
            url=url,
            amount_pence=amount,
            test_mode=c.paypal.sandbox,
            provider_ref=str(made["id"]),
            account_ref=c.paypal.merchant_id,
            ref=ref,
            created_by=user,
        )
    else:
        if not c.paypalme:
            raise OnlinePaymentError("Add your PayPal.me name in Settings › Online payments first")
        link = PaymentLink(
            provider="paypalme",
            url=paypalme_url(c.paypalme.username, amount),
            amount_pence=amount,
            test_mode=False,
            provider_ref=None,
            account_ref=c.paypalme.username,
            ref=ref,
            created_by=user,
        )
    warning = await _switch_off(inv.payment_link, c) if inv.payment_link else None
    inv = await get_invoice(books, number)
    inv.payment_link = link
    await save_invoice(books, inv)
    await books.audit(
        f"user:{user}",
        "payment_link_created",
        {"invoice": number, "provider": provider, "amount_pence": amount, "test": link.test_mode},
    )
    return inv, warning


async def remove_link(books: Books, number: str, user: str) -> tuple[Invoice, str | None]:
    inv = await get_invoice(books, number)
    if inv.payment_link is None:
        raise OnlinePaymentError(f"Invoice {number} has no payment link")
    old = inv.payment_link
    warning = await _switch_off(old, await load_connections(books))
    inv.payment_link = None
    await save_invoice(books, inv)
    await books.audit(f"user:{user}", "payment_link_removed", {"invoice": number, "provider": old.provider})
    return inv, warning


# --------------------------------------------------------------------------- #
# Payments received through a link: found by asking the provider, approved by the user
# --------------------------------------------------------------------------- #


class JournalPreview(BaseModel):
    account: str
    debit_pence: int = 0
    credit_pence: int = 0
    vat_code: str | None = None


class FoundPayment(BaseModel):
    invoice: str
    customer: str
    provider: Provider
    payment_id: str  # a Stripe Checkout Session (cs_…) or a PayPal transaction id
    date: date
    gross_pence: int
    fee_pence: int | None  # None: the provider has not said yet (approve with the fee typed in, or check later)
    net_pence: int | None
    balance_pence: int  # still owed on the invoice before this payment
    test_mode: bool
    journal: list[JournalPreview]  # what approving posts, worked out by code


class CheckProblem(BaseModel):
    invoice: str
    provider: Provider
    message: str


class CheckResult(BaseModel):
    checked: int  # invoices asked about
    found: list[FoundPayment]
    problems: list[CheckProblem]


@dataclass
class _Raw:
    payment_id: str
    when: date
    gross_pence: int
    fee_pence: int | None


def _london_day(ts: Any) -> date | None:
    try:
        return datetime.fromtimestamp(int(ts), UTC).astimezone(LONDON).date()
    except (TypeError, ValueError, OverflowError):
        return None


def stripe_payments(sessions: list[dict[str, Any]], ref: str) -> list[_Raw]:
    """Paid Checkout Sessions of the link that carry our reference, in GBP, with the fee when Stripe has it."""
    out = []
    for s in sessions:
        if s.get("status") != "complete" or s.get("payment_status") != "paid":
            continue
        if (s.get("metadata") or {}).get("accnomos_ref") != ref or str(s.get("currency", "")).lower() != "gbp":
            continue
        gross = s.get("amount_total")
        if not isinstance(gross, int) or gross <= 0:
            continue
        pi = s.get("payment_intent")
        charge = pi.get("latest_charge") if isinstance(pi, dict) else None
        bt = charge.get("balance_transaction") if isinstance(charge, dict) else None
        fee = (
            bt["fee"]
            if isinstance(bt, dict) and isinstance(bt.get("fee"), int) and str(bt.get("currency")).lower() == "gbp"
            else None
        )
        when = _london_day(charge.get("created") if isinstance(charge, dict) else None) or _london_day(s.get("created"))
        out.append(_Raw(str(s["id"]), when or now().date(), gross, fee))
    return out


def _paypal_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


async def paypal_payments(api: PayPalApi, merchant: str, invoice: dict[str, Any], ref: str) -> list[_Raw]:
    """PayPal payments on the PayPal invoice (not payments the merchant marked by hand there), with the fee."""
    if (invoice.get("detail") or {}).get("reference") != ref:
        return []
    out = []
    for t in ((invoice.get("payments") or {}).get("transactions")) or []:
        if not isinstance(t, dict) or t.get("type", "PAYPAL") != "PAYPAL" or not t.get("payment_id"):
            continue
        gross = pence_from_paypal(t.get("amount"))
        if not gross or gross <= 0:
            continue
        fee = None
        with contextlib.suppress(ProviderError):
            cap = await api.capture(merchant, str(t["payment_id"]))
            fee = pence_from_paypal((cap.get("seller_receivable_breakdown") or {}).get("paypal_fee"))
        when = _paypal_day(t.get("payment_date") or t.get("payment_date_time")) or now().date()
        out.append(_Raw(str(t["payment_id"]), when, gross, fee))
    return out


def journal_for(provider: str, gross: int, fee: int | None) -> list[JournalPreview]:
    """What approving posts: the receipt and the fee, both through the provider's clearing account."""
    clearing = CLEARING[provider]
    lines = [
        JournalPreview(account=clearing, debit_pence=gross),
        JournalPreview(account="1100 Debtors", credit_pence=gross),
    ]
    if fee:
        lines += [
            JournalPreview(account=FEES, debit_pence=fee, vat_code="E"),
            JournalPreview(account=clearing, credit_pence=fee),
        ]
    return lines


async def _provider_payments(inv: Invoice, c: Connections) -> list[_Raw]:
    link = inv.payment_link
    if link is None or not link.provider_ref:
        return []
    if link.provider == "stripe":
        cfg = _need_stripe()
        if not c.stripe or c.stripe.account_id != link.account_ref:
            raise OnlinePaymentError("the Stripe account this link is on is not connected any more")
        async with client() as http:
            sessions = await StripeApi(cfg, http).completed_sessions(c.stripe.account_id, link.provider_ref)
        return stripe_payments(sessions, link.ref)
    if link.provider == "paypal":
        cfg = _need_paypal()
        if not c.paypal or c.paypal.merchant_id != link.account_ref:
            raise OnlinePaymentError("the PayPal account this link is on is not connected any more")
        async with client() as http:
            api = PayPalApi(cfg, http)
            return await paypal_payments(
                api, c.paypal.merchant_id, await api.invoice(c.paypal.merchant_id, link.provider_ref), link.ref
            )
    return []


async def check(books: Books) -> CheckResult:
    """Ask Stripe/PayPal about every sent invoice with a link (oldest due first, at most MAX_CHECKED). Reads only."""
    from app import payments

    invoices = sorted(
        (
            i
            for i in await list_invoices(books, "sent")
            if i.payment_link and i.payment_link.provider in ("stripe", "paypal") and i.event_id
        ),
        key=lambda i: i.due_date,
    )[:MAX_CHECKED]
    if not invoices:
        return CheckResult(checked=0, found=[], problems=[])
    c = await load_connections(books)
    ledger = await payments.load_ledger(books)
    settled = ledger.settlement()
    gate = asyncio.Semaphore(4)

    async def one(inv: Invoice) -> tuple[list[FoundPayment], CheckProblem | None]:
        link = inv.payment_link
        assert link is not None and inv.event_id
        try:
            async with gate:
                raws = await _provider_payments(inv, c)
        except (ProviderError, OnlinePaymentError) as exc:
            msg = exc.message if isinstance(exc, ProviderError) else str(exc)
            return [], CheckProblem(invoice=inv.number, provider=link.provider, message=msg)
        balance = max(0, settled.outstanding(inv.event_id))
        found = [
            FoundPayment(
                invoice=inv.number,
                customer=inv.customer.name,
                provider=link.provider,
                payment_id=r.payment_id,
                date=r.when,
                gross_pence=r.gross_pence,
                fee_pence=r.fee_pence,
                net_pence=r.gross_pence - r.fee_pence if r.fee_pence is not None else None,
                balance_pence=balance,
                test_mode=link.test_mode,
                journal=journal_for(link.provider, r.gross_pence, r.fee_pence),
            )
            for r in raws
            if r.payment_id not in inv.online_payments
        ]
        return found, None

    results = await asyncio.gather(*(one(i) for i in invoices))
    return CheckResult(
        checked=len(invoices),
        found=[f for fs, _ in results for f in fs],
        problems=[p for _, p in results if p is not None],
    )


def fee_event_id(provider: str, payment_id: str) -> str:
    return hashlib.sha256(f"online-fee:{provider}:{payment_id}".encode()).hexdigest()[:32]


def fee_event(provider: str, payment_id: str, number: str, when: date, fee: int, user: str) -> LedgerEvent:
    """The provider's fee as an expense of its own: Dr 7900 Bank charges (VAT exempt) / Cr its clearing account."""
    memo = f"{provider_label(provider)} fee for invoice {number}"
    return LedgerEvent(
        id=fee_event_id(provider, payment_id),
        kind="purchase",
        date=when,
        lines=[
            Line(account=FEES, debit=fee, vat_code=VatCode.EXEMPT, memo=memo),
            Line(account=CLEARING[provider], credit=fee, memo=memo),
        ],
        approved_by=user,
        approved_at=now(),
        net=fee,
        vat=0,
        counterparty=provider_label(provider),
    )


async def approve(
    books: Books, number: str, payment_id: str, user: str, *, fee_pence: int | None = None
) -> tuple[Invoice, FoundPayment]:
    """The user's yes to one payment found through the invoice's link. The amount and fee are read again from the
    provider (never from the app); a fee is typed in only when the provider has not said it. Posts the payment
    (app/payments.record_payment) and the fee, and remembers the payment id on the invoice so it is proposed once."""
    from app import payments

    inv = await get_invoice(books, number)
    link = inv.payment_link
    if link is None or link.provider not in ("stripe", "paypal"):
        raise OnlinePaymentError(f"Invoice {number} has no Stripe or PayPal link to take payments from")
    if payment_id in inv.online_payments:
        raise InvoiceStateError("This online payment is already in your books")
    reference = f"{provider_label(link.provider)} {payment_id}"[:120]
    # A retry after a failure part way: the money is in (so the invoice may be paid now); finish the rest.
    already = [r for r in await payments._records(books) if r.reference == reference and r.removed_at is None]
    if not inv.event_id or (inv.status != "sent" and not (already and inv.status == "paid")):
        raise InvoiceStateError(f"Invoice {number} is {inv.status}; a payment can only go against a sent invoice")
    try:
        raws = await _provider_payments(inv, await load_connections(books))
    except ProviderError as exc:
        raise OnlinePaymentError(f"{provider_label(link.provider)} could not be asked: {exc.message}") from exc
    raw = next((r for r in raws if r.payment_id == payment_id), None)
    if raw is None:
        raise OnlinePaymentError(f"{provider_label(link.provider)} has no such paid payment on this link")
    fee = raw.fee_pence
    if fee is None:
        if fee_pence is None:
            raise OnlinePaymentError(
                f"{provider_label(link.provider)} has not said its fee yet; "
                "type it in from your statement, or check later"
            )
        if not 0 <= fee_pence < raw.gross_pence:
            raise OnlinePaymentError("The fee must be at least £0.00 and less than the payment")
        fee = fee_pence
    elif fee_pence is not None and fee_pence != fee:
        raise OnlinePaymentError(f"{provider_label(link.provider)} says the fee is {money(fee)}")
    record_id = already[0].id if already else None
    if not already:
        ledger = await payments.load_ledger(books)
        owed = max(0, ledger.settlement().outstanding(inv.event_id))
        if owed <= 0:
            raise InvoiceStateError(
                f"Invoice {number} is already paid; this {money(raw.gross_pence)} would be an overpayment. "
                "Record it by hand as a credit for the customer, or refund it"
            )
        body = payments.PaymentIn(
            side="sale",
            date=max(raw.when, inv.issue_date),
            amount_pence=raw.gross_pence,
            account=cast(payments.PaymentAccount, CLEARING[link.provider]),  # the bank sees it in a payout
            reference=reference,
            allocations=[payments.AllocationIn(event_id=inv.event_id, amount_pence=min(raw.gross_pence, owed))],
            bank_line_id=None,
        )
        record_id = (await payments.record_payment(books, body, user)).id
    fee_id = None
    if fee:
        ev = fee_event(link.provider, payment_id, number, max(raw.when, inv.issue_date), fee, user)
        with contextlib.suppress(FileExistsError):
            await books.post_event(ev)
        fee_id = ev.id
    inv = await get_invoice(books, number)  # record_payment refreshed its status
    inv.online_payments = [*inv.online_payments, payment_id]
    await save_invoice(books, inv)
    await books.audit(
        f"user:{user}",
        "online_payment_approved",
        {
            "invoice": number,
            "provider": link.provider,
            "provider_payment": payment_id,
            "payment": record_id,
            "amount_pence": raw.gross_pence,
            "fee_pence": fee,
            "fee_event": fee_id,
        },
    )
    await books.rebuild_safely(f"user:{user}")
    found = FoundPayment(
        invoice=number,
        customer=inv.customer.name,
        provider=link.provider,
        payment_id=payment_id,
        date=raw.when,
        gross_pence=raw.gross_pence,
        fee_pence=fee,
        net_pence=raw.gross_pence - fee,
        balance_pence=inv.balance_pence or 0,
        test_mode=link.test_mode,
        journal=journal_for(link.provider, raw.gross_pence, fee),
    )
    return inv, found


# --------------------------------------------------------------------------- #
# Payouts: the provider's transfer to the bank, matched to a statement line
# --------------------------------------------------------------------------- #

PAYOUTS = f"{SYSTEM}/Payments/payouts.json"
PAYOUT_WORDS = {
    "stripe": re.compile(r"\bstripe\b", re.IGNORECASE),
    "paypal": re.compile(r"\bpaypal\b|\bpp\s?\*", re.IGNORECASE),
}


class Payout(BaseModel):
    """One statement line matched as a payout (`_System/Payments/payouts.json`)."""

    line_id: str
    provider: Literal["stripe", "paypal"]
    date: date
    amount_pence: int
    event_id: str
    matched_by: str
    matched_at: datetime
    reversal_event_id: str | None = None  # posted when the line is unmatched


def payout_provider(description: str) -> Literal["stripe", "paypal"] | None:
    """Which provider a statement line's words name, for the hint on an unmatched line; None when neither."""
    for name, words in PAYOUT_WORDS.items():
        if words.search(description):
            return name  # type: ignore[return-value]
    return None


async def _payouts(books: Books) -> list[Payout]:
    return [Payout.model_validate(r) for r in await books.read_json(PAYOUTS, [])]


async def clearing_balance(books: Books, provider: str) -> int:
    """What the provider still holds for the user, by the books: receipts less fees less payouts (pence)."""
    account = CLEARING[provider]
    return sum(ln.debit - ln.credit for e in await books.list_events() for ln in e.lines if ln.account == account)


async def match_payout(books: Books, line_id: str, provider: Literal["stripe", "paypal"], user: str) -> Any:
    """The user's yes: this money-in line is a payout from `provider`. Posts Dr 1200 Bank / Cr the clearing account for
    the line's amount and matches the line to it. Refused (BankMatchError) when the clearing account holds less: the
    payments it pays out are not approved yet, and posting it would leave the provider owing the user a negative
    amount."""
    from app.books import BankMatchError

    line = await books.find_bank_line(line_id)
    if line.resolved:
        raise BankMatchError("This bank line is already settled; undo that first")
    if line.amount_pence <= 0:
        raise BankMatchError("A payout is money in; this line is money out")
    held = await clearing_balance(books, provider)
    if line.amount_pence > held:
        raise BankMatchError(
            f"{CLEARING[provider]} holds {money(max(held, 0))}, less than this {money(line.amount_pence)} payout. "
            f"Approve the {provider_label(provider)} payments it pays out on the Invoices page first"
        )
    memo = f"{provider_label(provider)} payout"
    event = LedgerEvent(
        kind="bank",
        date=line.date,
        lines=[
            Line(account=BANK, debit=line.amount_pence, memo=memo),
            Line(account=CLEARING[provider], credit=line.amount_pence, memo=memo),
        ],
        approved_by=user,
        approved_at=now(),
        counterparty=provider_label(provider),
    )
    await books.post_event(event)
    record = Payout(
        line_id=line_id,
        provider=provider,
        date=line.date,
        amount_pence=line.amount_pence,
        event_id=event.id,
        matched_by=user,
        matched_at=now(),
    )
    await books._update_json(PAYOUTS, [], lambda rows: [*(rows or []), record.model_dump(mode="json")])
    await books.audit(
        f"user:{user}",
        "payout_matched",
        {"line": line_id, "provider": provider, "amount_pence": line.amount_pence, "event": event.id},
    )
    return await books.confirm_match(line_id, [event.id], user)


async def on_unmatched(books: Books, line_id: str, event_ids: list[str], user: str) -> None:
    """A payout line was unmatched: reverse its transfer, so the money is back in the clearing account."""
    payouts = await _payouts(books)
    hit = next(
        (p for p in payouts if p.line_id == line_id and p.event_id in event_ids and not p.reversal_event_id), None
    )
    if hit is None:
        return
    original = next((e for e in await books.list_events() if e.id == hit.event_id), None)
    if original is None:
        return
    reversal = LedgerEvent(
        kind="reversal",
        date=original.date,
        lines=[Line(account=ln.account, debit=ln.credit, credit=ln.debit, memo=ln.memo) for ln in original.lines],
        approved_by=user,
        approved_at=now(),
        counterparty=original.counterparty,
        reverses=original.id,
    )
    await books.post_event(reversal)

    def change(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "reversal_event_id": reversal.id} if r.get("event_id") == hit.event_id else r for r in rows or []]

    await books._update_json(PAYOUTS, [], change)
    await books.audit(
        f"user:{user}", "payout_unmatched", {"line": line_id, "provider": hit.provider, "event": hit.event_id}
    )
