"""Thin async wrapper over the HMRC REST APIs: Accept versioning, bearer auth, sandbox scenarios, typed errors."""

from __future__ import annotations

from typing import Any

import httpx

from .settings import Settings


class HmrcError(Exception):
    """An HMRC error response, normalised from `{code, message, errors[]}` or OAuth `{error, error_description}`."""

    def __init__(self, status: int, code: str, message: str, errors: list[dict] | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.errors = errors or []

    @classmethod
    def from_response(cls, resp: httpx.Response) -> HmrcError:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        code = body.get("code") or body.get("error") or f"HTTP_{resp.status_code}"
        message = body.get("message") or body.get("error_description") or resp.reason_phrase
        return cls(resp.status_code, code, message, body.get("errors"))

    def to_json(self) -> dict:
        return {"code": self.code, "message": self.message, "errors": self.errors, "hmrc_status": self.status}


class HmrcUnavailable(Exception):
    """Transport-level failure talking to HMRC (DNS, TLS, timeout)."""


class HmrcClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str,
        version: str = "1.0",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        gov_test_scenario: str | None = None,
    ) -> httpx.Response:
        """Call `{HMRC_BASE}{path}`; raise HmrcError on any 4xx/5xx."""
        h = {"Accept": f"application/vnd.hmrc.{version}+json", "Authorization": f"Bearer {bearer}", **(headers or {})}
        if gov_test_scenario and self.settings.sandbox:
            h["Gov-Test-Scenario"] = gov_test_scenario
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await self.http.request(
                method, f"{self.settings.hmrc_base.rstrip('/')}{path}", headers=h, params=params, json=json
            )
        except httpx.HTTPError as e:
            raise HmrcUnavailable(type(e).__name__) from e
        if resp.status_code >= 400:
            raise HmrcError.from_response(resp)
        return resp
