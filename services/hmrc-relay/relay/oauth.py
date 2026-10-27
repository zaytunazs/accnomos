"""HMRC OAuth 2.0: user-restricted (authorisation code + refresh) and application-restricted (client_credentials).

The relay holds the client secret because HMRC requires it at code exchange and at refresh. Tokens are returned
to the caller and never persisted; the only in-memory copies are the app-restricted token cache and a
seconds-long cache of a refresh result, so a duplicate concurrent refresh gets the same answer instead of
burning the single-use refresh token twice.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .hmrc_client import HmrcError, HmrcUnavailable
from .settings import Settings

SCOPES = "read:vat write:vat"
STATE_TTL_S = 600  # matches HMRC's 10-minute authorisation code lifetime
REFRESH_RESULT_TTL_S = 30
APP_TOKEN_MARGIN_S = 60


class StateError(ValueError):
    pass


@dataclass(frozen=True)
class AuthState:
    redirect_to: str
    pkce: bool


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class OAuth:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http
        self._refresh_locks: dict[str, tuple[asyncio.Lock, int]] = {}  # sha256(refresh token) -> (lock, users)
        self._refresh_results: dict[str, tuple[float, dict]] = {}
        self._app_token: tuple[float, str] | None = None
        self._app_lock = asyncio.Lock()

    # --- state: signed, self-contained, so the relay needs no session store -------------------------------

    def _state_key(self) -> bytes:
        return hashlib.sha256(b"hmrc-relay-state:" + self.settings.hmrc_client_secret.get_secret_value().encode()).digest()

    def make_state(self, redirect_to: str, pkce: bool) -> str:
        payload = _b64(json.dumps(
            {"r": redirect_to, "p": pkce, "e": int(time.time()) + STATE_TTL_S, "n": secrets.token_urlsafe(12)},
            separators=(",", ":"),
        ).encode())
        sig = _b64(hmac.new(self._state_key(), payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{sig}"

    def read_state(self, state: str) -> AuthState:
        try:
            payload, sig = state.split(".")
            expected = _b64(hmac.new(self._state_key(), payload.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(sig, expected):
                raise StateError("bad signature")
            data = json.loads(_unb64(payload))
        except StateError:
            raise
        except (ValueError, KeyError) as e:
            raise StateError("malformed state") from e
        if data["e"] < time.time():
            raise StateError("state expired")
        return AuthState(redirect_to=data["r"], pkce=bool(data["p"]))

    def authorize_url(self, redirect_to: str, code_challenge: str | None = None) -> tuple[str, str]:
        state = self.make_state(redirect_to, pkce=bool(code_challenge))
        q = {
            "response_type": "code",
            "client_id": self.settings.hmrc_client_id,
            "scope": SCOPES,
            "redirect_uri": self.settings.hmrc_redirect_uri,
            "state": state,
        }
        if code_challenge:
            q |= {"code_challenge": code_challenge, "code_challenge_method": "S256"}
        return f"{self.settings.authorize_url}?{urlencode(q)}", state

    # --- token endpoint ------------------------------------------------------------------------------------

    async def _token(self, form: dict[str, str]) -> dict:
        form = {"client_id": self.settings.hmrc_client_id,
                "client_secret": self.settings.hmrc_client_secret.get_secret_value(), **form}
        try:
            resp = await self.http.post(self.settings.token_url, data=form, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise HmrcUnavailable(type(e).__name__) from e
        if resp.status_code >= 400:
            raise HmrcError.from_response(resp)
        return resp.json()

    async def exchange_code(self, code: str, code_verifier: str | None = None) -> dict:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.settings.hmrc_redirect_uri}
        if code_verifier:
            form["code_verifier"] = code_verifier
        return await self._token(form)

    async def refresh(self, refresh_token: str) -> dict:
        """Refresh, serialised per refresh token. HMRC refresh tokens are single-use and HMRC rejects a second
        concurrent refresh, so callers racing on the same token share one HMRC call and its result."""
        key = hashlib.sha256(refresh_token.encode()).hexdigest()
        lock, users = self._refresh_locks.get(key, (asyncio.Lock(), 0))
        self._refresh_locks[key] = (lock, users + 1)
        try:
            async with lock:
                now = time.monotonic()
                self._refresh_results = {k: v for k, v in self._refresh_results.items() if v[0] > now}
                if hit := self._refresh_results.get(key):
                    return hit[1]
                tokens = await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
                self._refresh_results[key] = (time.monotonic() + REFRESH_RESULT_TTL_S, tokens)
                return tokens
        finally:
            lock, users = self._refresh_locks[key]
            if users == 1:
                del self._refresh_locks[key]
            else:
                self._refresh_locks[key] = (lock, users - 1)

    async def app_token(self) -> str:
        """Application-restricted bearer (client_credentials), cached in memory until shortly before expiry."""
        async with self._app_lock:
            if self._app_token and self._app_token[0] > time.monotonic():
                return self._app_token[1]
            tok = await self._token({"grant_type": "client_credentials"})
            ttl = max(int(tok.get("expires_in", 0)) - APP_TOKEN_MARGIN_S, 0)
            self._app_token = (time.monotonic() + ttl, tok["access_token"])
            return tok["access_token"]
