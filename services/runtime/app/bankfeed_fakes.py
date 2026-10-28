"""A stand-in for TrueLayer's Data API, for the unit tests and test mode (`ACCNOMOS_TEST_MODE=1`). Nothing is ever
sent to TrueLayer from here.

`install()` points app/truelayer.TRANSPORT at `handle`, an httpx MockTransport handler that answers the calls
app/truelayer.py makes with the shapes listed in that module's docstring: form-encoded `/connect/token` with the
client id and secret, Bearer-token `GET /data/v1/me`, `/data/v1/accounts` and `/transactions?from=&to=`,
`POST /connections/extend`, `DELETE /api/delete`. A request the fake does not know is a 404, so a wrong path fails a
test instead of passing quietly. Every request is kept in `FAKES.requests`.

In test mode `router` adds the page a browser would see at TrueLayer: a bank picker that has already agreed and
sends the browser straight back to the redirect URI with a code.

The mock bank's account holds six transactions, SAMPLE — FICTIONAL COMPANY. Three are the same payments as three
lines of evals/gold/bank/barclays.csv, worded as a feed words them, so the end-to-end test can show the duplicates
being dropped; three are new.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import truelayer

CLIENT = ("accnomos-fake-truelayer", "accnomos-fake-truelayer-secret")
ACCOUNT_ID = "fake-acc-0001"
BANK = "Mock UK Bank (sandbox)"

#: (date, description, reference, amount in pounds, DEBIT/CREDIT, running balance)
TRANSACTIONS: tuple[tuple[str, str, str | None, str, str, str], ...] = (
    ("2026-10-01", "SCREWFIX DIRECT", None, "-38.47", "DEBIT", "4961.53"),  # Barclays: SCREWFIX DIRECT ON 30 SEP CLP
    ("2026-10-03", "ACME KITCHENS LTD", "INV-0042", "1200.00", "CREDIT", "6161.53"),  # Barclays: … INV-0042 BGC
    ("2026-10-07", "TO SAVINGS 87654321", None, "-500.00", "DEBIT", "5661.53"),  # Barclays: TO SAVINGS … TFR
    ("2026-10-22", "B&Q WARRINGTON", None, "-23.99", "DEBIT", "5637.54"),
    ("2026-10-24", "HARBOUR CAFE LTD", "INV-0043", "480.00", "CREDIT", "6117.54"),
    ("2026-10-26", "COSTA COFFEE 1234", None, "-3.40", "DEBIT", "6114.14"),
)


def _today() -> date:
    from app.books import today  # pinned in test mode

    return today()


@dataclass
class Credential:
    id: str
    created: datetime
    expires: datetime
    refresh: set[str] = field(default_factory=set)


@dataclass
class Fakes:
    requests: list[httpx.Request] = field(default_factory=list)
    codes: dict[str, str] = field(default_factory=dict)  # code -> credentials id
    access: dict[str, str] = field(default_factory=dict)  # access token -> credentials id
    creds: dict[str, Credential] = field(default_factory=dict)
    extend_needs_reauth: bool = False  # the bank wants the user back (extend answers a user_input_link)
    fail_transactions: bool = False  # the bank is down
    deleted: set[str] = field(default_factory=set)

    def new_code(self) -> str:
        cred_id = f"fake-cred-{secrets.token_hex(6)}"
        start = datetime.combine(_today(), time(9, 0), tzinfo=UTC)
        self.creds[cred_id] = Credential(cred_id, start, start + timedelta(days=90))
        code = f"fake-code-{secrets.token_hex(8)}"
        self.codes[code] = cred_id
        return code

    def tokens(self, cred_id: str) -> dict[str, Any]:
        access = f"fake-access-{secrets.token_hex(8)}"
        refresh = f"fake-refresh-{secrets.token_hex(8)}"
        self.access[access] = cred_id
        self.creds[cred_id].refresh.add(refresh)
        scope = truelayer.SCOPES
        return {
            "access_token": access,
            "expires_in": 3600,
            "token_type": "Bearer",
            "refresh_token": refresh,
            "scope": scope,
        }

    def by_refresh(self, token: str) -> Credential | None:
        return next((c for c in self.creds.values() if token in c.refresh and c.id not in self.deleted), None)


FAKES = Fakes()


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def _err(status: int, error: str) -> httpx.Response:
    return _json(status, {"error": error, "error_description": error.replace("_", " ")})


def _cred_from_bearer(request: httpx.Request) -> Credential | None:
    auth = request.headers.get("Authorization", "")
    cred_id = FAKES.access.get(auth.removeprefix("Bearer ").strip())
    return FAKES.creds.get(cred_id) if cred_id and cred_id not in FAKES.deleted else None


def _iso(d: datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


def _transactions(request: httpx.Request) -> httpx.Response:
    q = dict(request.url.params)
    try:
        start, end = date.fromisoformat(q["from"]), date.fromisoformat(q["to"])
    except (KeyError, ValueError):
        return _err(400, "invalid_date_range")
    if FAKES.fail_transactions:
        return _err(503, "provider_error")
    results = [
        {
            "transaction_id": f"fake-tx-{i:03d}",
            "timestamp": f"{d}T00:00:00+00:00",
            "description": desc,
            "amount": float(amount),
            "currency": "GBP",
            "transaction_type": kind,
            "transaction_category": "PURCHASE" if kind == "DEBIT" else "CREDIT",
            "transaction_classification": [],
            "running_balance": {"amount": float(balance), "currency": "GBP"},
            "meta": {"provider_reference": ref} if ref else {},
        }
        for i, (d, desc, ref, amount, kind, balance) in enumerate(TRANSACTIONS, start=1)
        if start <= date.fromisoformat(d) <= end
    ]
    return _json(200, {"results": results, "status": "Succeeded"})


def handle(request: httpx.Request) -> httpx.Response:
    FAKES.requests.append(request)
    path = request.url.path
    if request.method == "POST" and path.endswith("/connect/token"):
        form = dict(parse_qsl(request.content.decode()))
        if (form.get("client_id"), form.get("client_secret")) != CLIENT:
            return _err(401, "invalid_client")
        if form.get("grant_type") == "authorization_code":
            cred_id = FAKES.codes.pop(form.get("code", ""), None)
            if cred_id is None:
                return _err(400, "invalid_grant")
            return _json(200, FAKES.tokens(cred_id))
        if form.get("grant_type") == "refresh_token":
            cred = FAKES.by_refresh(form.get("refresh_token", ""))
            if cred is None or cred.expires.date() < _today():
                return _err(400, "invalid_grant")
            return _json(200, FAKES.tokens(cred.id))
        return _err(400, "unsupported_grant_type")
    if request.method == "POST" and path.endswith("/connections/extend"):
        body = json.loads(request.content or b"{}")
        if (body.get("client_id"), body.get("client_secret")) != CLIENT:
            return _err(401, "invalid_client")
        cred = FAKES.by_refresh(str(body.get("refresh_token") or ""))
        if cred is None or body.get("user_has_reconfirmed_consent") is not True:
            return _err(400, "invalid_request")
        if FAKES.extend_needs_reauth:
            return _json(200, {"user_input_link": f"https://auth.truelayer-sandbox.com/?reauth={cred.id}"})
        cred.expires = datetime.combine(_today(), time(9, 0), tzinfo=UTC) + timedelta(days=90)
        return _json(200, FAKES.tokens(cred.id))
    if request.url.host == "api.truelayer-sandbox.com":
        cred = _cred_from_bearer(request)
        if cred is None:
            return _err(401, "invalid_token")
        if request.method == "DELETE" and path == "/api/delete":
            FAKES.deleted.add(cred.id)
            return _json(200, {"success": True})
        if path == "/data/v1/me":
            return _json(
                200,
                {
                    "results": [
                        {
                            "client_id": CLIENT[0],
                            "credentials_id": cred.id,
                            "consent_status": "Authorised",
                            "consent_created_at": _iso(cred.created),
                            "consent_expires_at": _iso(cred.expires),
                            "provider": {"provider_id": "mock", "display_name": BANK},
                            "scopes": truelayer.SCOPES.split(),
                        }
                    ],
                    "status": "Succeeded",
                },
            )
        if path == "/data/v1/accounts":
            account = {
                "account_id": ACCOUNT_ID,
                "account_type": "TRANSACTION",
                "display_name": "Business Current Account",
                "currency": "GBP",
                "account_number": {"number": "12345678", "sort_code": "20-00-00"},
                "provider": {"provider_id": "mock", "display_name": BANK},
            }
            return _json(200, {"results": [account], "status": "Succeeded"})
        if path == f"/data/v1/accounts/{ACCOUNT_ID}/transactions":
            return _transactions(request)
    return _err(404, f"bankfeed_fakes: no fake for {request.method} {path}")


def install() -> None:
    truelayer.TRANSPORT = httpx.MockTransport(handle)


def reset() -> None:
    FAKES.__dict__.update(Fakes().__dict__)


# --------------------------------------------------------------------------- #
# The browser's side of TrueLayer, in test mode (mounted under /__test by app/testmode.py)
# --------------------------------------------------------------------------- #

router = APIRouter(include_in_schema=False)


@router.get("/truelayer/")
async def truelayer_auth(request: Request) -> RedirectResponse:
    """TrueLayer's bank picker and the bank's consent, already agreed: straight back with `code` and `state`."""
    q = request.query_params
    if (
        q.get("client_id") != CLIENT[0]
        or q.get("response_type") != "code"
        or "offline_access" not in q.get("scope", "")
    ):
        raise HTTPException(400, "bad auth request")
    return RedirectResponse(
        f"{q['redirect_uri']}?{urlencode({'code': FAKES.new_code(), 'state': q.get('state', '')})}", 303
    )
