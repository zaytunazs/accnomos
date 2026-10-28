"""TrueLayer's Data API over HTTP, for bank feeds (app/bank_feeds.py). No SDK: each call is the documented request,
so the fakes in app/bankfeed_fakes.py can check it field by field.

Sources (searched 28 Oct 2026; this session's network could not open docs.truelayer.com itself, so the shapes below
are from TrueLayer's documentation as quoted in search results and from the public API reference as we know it.
**UNVERIFIED until the owner runs it against the sandbox**; docs/bank-feeds/RESEARCH.md lists what to check):

  * https://docs.truelayer.com/docs/general-data-api-concepts: an `access_token` lasts 1 hour; a `refresh_token` is
    only issued with the `offline_access` scope and lasts 90 days (UK), the same as the consent; `GET /data/v1/me`
    gives the connection's `consent_expires_at`.
  * https://docs.truelayer.com/docs/create-a-connection: the auth link
    `https://auth.truelayer[-sandbox].com/?response_type=code&client_id=&redirect_uri=&scope=&providers=&state=`;
    the sandbox's mock bank is the `uk-cs-mock` provider.
  * `POST {auth}/connect/token` (form: `grant_type=authorization_code|refresh_token`, `client_id`,
    `client_secret`, `redirect_uri`, `code` | `refresh_token`) answers `access_token`, `expires_in`,
    `refresh_token`, `token_type`, `scope`.
  * `GET {api}/data/v1/accounts`, `GET {api}/data/v1/accounts/{id}/transactions?from=&to=`: `{"results": [...],
    "status": "Succeeded"}`; a transaction has `transaction_id`, `timestamp`, `description`, `amount`, `currency`,
    `transaction_type` (DEBIT | CREDIT), `running_balance.amount`, `meta.provider_reference`.
  * https://support.truelayer.com/hc/en-us/articles/360017594238 (re-authentication): `POST {auth}/connections/extend`
    with the `refresh_token` and `user_has_reconfirmed_consent: true` extends the consent after the user reconfirmed
    it in our app (FCA PS21/19); when the bank itself wants the user back, the answer carries a `user_input_link`.
  * `DELETE {api}/api/delete` with the access token ends the connection at TrueLayer.

Every amount leaves this module as integer pence (`pence_from_amount`); only GBP is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
# Set by app/bankfeed_fakes.py in test mode and by the unit tests: every TrueLayer call goes to the fakes instead.
TRANSPORT: httpx.AsyncBaseTransport | None = None

SANDBOX_AUTH = "https://auth.truelayer-sandbox.com"
SANDBOX_API = "https://api.truelayer-sandbox.com"
LIVE_AUTH = "https://auth.truelayer.com"
LIVE_API = "https://api.truelayer.com"
SCOPES = "info accounts balance transactions offline_access"
SANDBOX_PROVIDERS = "uk-cs-mock uk-ob-all uk-oauth-all"  # the mock bank plus the real banks' sandboxes
LIVE_PROVIDERS = "uk-ob-all uk-oauth-all"


class TrueLayerError(RuntimeError):
    """TrueLayer refused or could not be reached. `status` is the HTTP status (0: no answer)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"TrueLayer: {message}" + (f" (HTTP {status})" if status else ""))
        self.status, self.message = status, message


@dataclass(frozen=True)
class TrueLayerConfig:
    client_id: str
    client_secret: str
    redirect_uri: str  # the runtime's /books/bankfeeds/callback, registered in TrueLayer's console
    auth_base: str = SANDBOX_AUTH
    api_base: str = SANDBOX_API
    providers: str = SANDBOX_PROVIDERS

    @property
    def sandbox(self) -> bool:
        return self.auth_base != LIVE_AUTH


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False)


def pence_from_amount(amount: Any) -> int | None:
    """TrueLayer's decimal `amount` (a JSON number) as pence; None for a third decimal place or no number."""
    if isinstance(amount, bool) or amount is None:
        return None
    try:
        p = Decimal(str(amount)) * 100
    except InvalidOperation:
        return None
    return int(p) if p == p.to_integral_value() else None


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200] or "error"
    if isinstance(body, dict):
        return str(body.get("error_description") or body.get("error") or body.get("title") or "error")[:300]
    return "error"


def auth_url(cfg: TrueLayerConfig, state: str) -> str:
    """Where the browser goes to pick a bank and give consent; TrueLayer comes back to `redirect_uri`."""
    q = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": SCOPES,
        "providers": cfg.providers,
        "state": state,
    }
    return f"{cfg.auth_base}/?{urlencode(q)}"


class TrueLayerApi:
    def __init__(self, cfg: TrueLayerConfig, http: httpx.AsyncClient) -> None:
        self.cfg, self.http = cfg, http

    async def _json(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise TrueLayerError(resp.status_code, _error_text(resp))
        try:
            body = resp.json()
        except ValueError as exc:
            raise TrueLayerError(resp.status_code, "answer was not JSON") from exc
        if not isinstance(body, dict):
            raise TrueLayerError(resp.status_code, "answer was not a JSON object")
        return body

    async def _send(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        try:
            resp = await self.http.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise TrueLayerError(0, f"could not reach TrueLayer ({type(exc).__name__})") from exc
        return await self._json(resp)

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        body = {"client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret, **form}
        got = await self._send("POST", f"{self.cfg.auth_base}/connect/token", data=body)
        if not got.get("access_token"):
            raise TrueLayerError(0, "no access token in the answer")
        return got

    async def exchange_code(self, code: str) -> dict[str, Any]:
        return await self._token(
            {"grant_type": "authorization_code", "redirect_uri": self.cfg.redirect_uri, "code": code}
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def extend(self, refresh_token: str) -> dict[str, Any]:
        """Extend the consent after the user reconfirmed it in the app. UNVERIFIED request and answer shape."""
        body = {
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "refresh_token": refresh_token,
            "redirect_uri": self.cfg.redirect_uri,
            "user_has_reconfirmed_consent": True,
        }
        return await self._send("POST", f"{self.cfg.auth_base}/connections/extend", json=body)

    def _bearer(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    async def _results(self, access_token: str, path: str, params: dict[str, str] | None = None) -> list[Any]:
        got = await self._send("GET", f"{self.cfg.api_base}{path}", headers=self._bearer(access_token), params=params)
        results = got.get("results")
        if not isinstance(results, list):
            raise TrueLayerError(0, f"no results list from {path}")
        return results

    async def me(self, access_token: str) -> dict[str, Any]:
        results = await self._results(access_token, "/data/v1/me")
        if not results or not isinstance(results[0], dict):
            raise TrueLayerError(0, "no connection details from /data/v1/me")
        return results[0]

    async def accounts(self, access_token: str) -> list[dict[str, Any]]:
        return [a for a in await self._results(access_token, "/data/v1/accounts") if isinstance(a, dict)]

    async def transactions(self, access_token: str, account_id: str, start: date, end: date) -> list[dict[str, Any]]:
        path = f"/data/v1/accounts/{account_id}/transactions"
        params = {"from": start.isoformat(), "to": end.isoformat()}
        return [t for t in await self._results(access_token, path, params) if isinstance(t, dict)]

    async def delete(self, access_token: str) -> None:
        await self._send("DELETE", f"{self.cfg.api_base}/api/delete", headers=self._bearer(access_token))
