"""Official look-ups: Companies House (company search and profile) and HMRC's Check a UK VAT number (via the relay).

AI proposes, user approves, code calculates: nothing here writes to the books. A look-up only suggests a legal
name, company number and registered address; the user picks one and saves the contact themselves.

Companies House Public Data API (developer.company-information.service.gov.uk, checked 27 Oct 2026):
  * base `https://api.company-information.service.gov.uk` (COMPANIES_HOUSE_BASE overrides it, for tests only);
  * HTTP Basic auth with the API key as the username and an empty password;
  * 600 requests per 5 minutes per key, then 429. This process asks for at most half of that (`CH_RATE_PER_MIN`);
  * `GET /search/companies?q=&items_per_page=`, `GET /company/{number}` (its `registered_office_address` is the
    registered office, so the separate `/registered-office-address` call is not needed).
No key (COMPANIES_HOUSE_API_KEY unset) -> `NotConfigured`; the routes answer 503 and the web app hides the feature.

HMRC Check a UK VAT number v2.0 is application-restricted, so it needs the HMRC client secret, which only the relay
holds: the runtime calls the relay's `GET /hmrc/vat-check/{vrn}` at HMRC_RELAY_URL. The relay decides sandbox or
production from its own HMRC_BASE and labels every answer (`source`).

Answers are cached in this process for 24 hours (Companies House data changes slowly; a VAT check result is also
kept on the contact). With ACCNOMOS_TEST_MODE=1 both are deterministic fakes (fictional companies labelled
SAMPLE; the gold receipts' fictional suppliers for VAT), so the e2e tests touch no network.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel

from app.ai.config import is_test_mode
from app.autopilot import supplier_key
from app.checks import normalise_vat_number
from app.security import TokenBucket

CH_BASE = "https://api.company-information.service.gov.uk"
CH_RATE_PER_MIN = 60  # 300 per 5 minutes: half of Companies House's 600
CACHE_TTL_S = 24 * 3600
CACHE_MAX = 1024
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
COMPANY_NUMBER_RE = re.compile(r"^[A-Z0-9]{8}$")
SAMPLE = "SAMPLE — FICTIONAL COMPANY"


class LookupFailed(Exception):
    """Base of the look-up errors; the routes turn `status`/`code` into the HTTP answer."""

    status = 502
    code = "lookup_failed"

    def __init__(self, message: str = "", retry_after: int | None = None):
        super().__init__(message or self.code)
        self.retry_after = retry_after


class NotConfigured(LookupFailed):
    status, code = 503, "companies_house_not_configured"


class VatCheckNotConfigured(LookupFailed):
    status, code = 503, "vat_check_not_configured"


class RateLimited(LookupFailed):
    status, code = 429, "rate_limited"


class NotFound(LookupFailed):
    status, code = 404, "not_found"


class BadQuery(LookupFailed):
    status, code = 400, "bad_query"


class Unavailable(LookupFailed):
    status, code = 502, "lookup_unavailable"


class CompanyMatch(BaseModel):
    company_number: str
    name: str
    status: str | None = None  # active, dissolved, liquidation, ...
    type: str | None = None  # ltd, plc, llp, ...
    address: str | None = None  # one line, as contacts store it
    date_of_creation: str | None = None
    source: str = "companies-house"  # "sample" in test mode
    sample: bool = False


class CompanySearch(BaseModel):
    query: str
    items: list[CompanyMatch]


class VatCheck(BaseModel):
    """The relay's answer, as stored on a contact (`Contact.vat_check`)."""

    vrn: str
    registered: bool
    name: str | None = None
    address: str | None = None
    consultation_number: str | None = None
    checked_at: str
    source: str  # "hmrc-sandbox" | "hmrc" | "sample"
    checksum_ok: bool | None = None


# --------------------------------------------------------------------------- #
# Configuration, cache and the polite rate limit (per process)
# --------------------------------------------------------------------------- #


def api_key() -> str:
    return os.getenv("COMPANIES_HOUSE_API_KEY", "").strip()


def configured() -> bool:
    return is_test_mode() or bool(api_key())


def relay_url() -> str:
    return os.getenv("HMRC_RELAY_URL", "").strip().rstrip("/")


def vat_check_configured() -> bool:
    return is_test_mode() or bool(relay_url())


_cache: dict[str, tuple[float, Any]] = {}
_bucket = TokenBucket(CH_RATE_PER_MIN)
_transport: httpx.AsyncBaseTransport | None = None  # tests swap in httpx.MockTransport
_clock: Callable[[], float] = time.monotonic


def reset() -> None:
    """Empty the cache and the rate limit (tests)."""
    _cache.clear()
    _bucket.reset()


def _cached(key: str) -> Any | None:
    hit = _cache.get(key)
    if hit and hit[0] > _clock():
        return hit[1]
    _cache.pop(key, None)
    return None


def _store(key: str, value: Any) -> Any:
    if len(_cache) >= CACHE_MAX:
        now = _clock()
        for k in [k for k, (exp, _) in _cache.items() if exp <= now] or list(_cache)[: CACHE_MAX // 4]:
            _cache.pop(k, None)
    _cache[key] = (_clock() + CACHE_TTL_S, value)
    return value


def normalise_company_number(raw: str) -> str:
    """'sc 123456' -> 'SC123456'; '6' -> '00000006'. BadQuery unless 8 letters/digits result."""
    s = re.sub(r"\s", "", raw.upper())
    if s.isdigit() and 0 < len(s) < 8:
        s = s.zfill(8)
    if not COMPANY_NUMBER_RE.fullmatch(s):
        raise BadQuery("A company number is 8 characters, e.g. 01234567 or SC123456")
    return s


def looks_like_company_number(q: str) -> bool:
    s = re.sub(r"\s", "", q.upper())
    return bool(re.fullmatch(r"\d{6,8}|[A-Z]{2}\d{6}", s))


def one_line(a: dict[str, Any] | None) -> str | None:
    """Companies House address object -> '1 High St, Leeds, LS1 1AA'."""
    if not isinstance(a, dict):
        return None
    first = " ".join(str(a[k]).strip() for k in ("premises", "address_line_1") if a.get(k))
    parts = [first, a.get("address_line_2"), a.get("locality"), a.get("region"), a.get("postal_code")]
    country = a.get("country")
    if country and str(country).strip().lower() not in {"united kingdom", "england", "wales", "scotland", "uk"}:
        parts.append(country)
    text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text or None


# --------------------------------------------------------------------------- #
# Companies House
# --------------------------------------------------------------------------- #


async def _ch_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise NotConfigured()
    if wait := _bucket.take("companies-house"):
        raise RateLimited("Companies House look-ups are paused for a moment", retry_after=max(1, int(wait) + 1))
    base = os.getenv("COMPANIES_HOUSE_BASE", CH_BASE).rstrip("/")
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=TIMEOUT, follow_redirects=False) as http:
            resp = await http.get(f"{base}{path}", params=params, auth=httpx.BasicAuth(key, ""))
    except httpx.HTTPError as e:
        raise Unavailable(f"Couldn't reach Companies House ({type(e).__name__})") from e
    if resp.status_code == 404:
        raise NotFound("Companies House has no company with that number")
    if resp.status_code == 429:
        raise RateLimited("Companies House asked us to slow down", retry_after=60)
    if resp.status_code in (401, 403):
        raise Unavailable("Companies House refused the API key (COMPANIES_HOUSE_API_KEY)")
    if resp.status_code >= 400:
        raise Unavailable(f"Companies House returned {resp.status_code}")
    return resp.json() if resp.content else {}


def _match(item: dict[str, Any]) -> CompanyMatch:
    return CompanyMatch(
        company_number=str(item.get("company_number") or ""),
        name=str(item.get("title") or item.get("company_name") or ""),
        status=item.get("company_status"),
        type=item.get("company_type") or item.get("type"),
        address=one_line(item.get("address") or item.get("registered_office_address")) or item.get("address_snippet"),
        date_of_creation=item.get("date_of_creation"),
    )


async def search(q: str) -> CompanySearch:
    """Up to 10 matches for a company name; a company number goes straight to its profile."""
    q = " ".join(q.split())
    if not 2 <= len(q) <= 160:
        raise BadQuery("Type at least 2 characters")
    if looks_like_company_number(q):
        try:
            return CompanySearch(query=q, items=[await profile(q)])
        except NotFound:
            pass  # not a number after all (e.g. a 6-digit trading name): search by name below
    if is_test_mode():
        return CompanySearch(query=q, items=_fake_search(q))
    if hit := _cached(f"s:{q.lower()}"):
        return hit
    data = await _ch_get("/search/companies", {"q": q, "items_per_page": 10})
    items = [_match(i) for i in data.get("items") or [] if i.get("company_number")]
    return _store(f"s:{q.lower()}", CompanySearch(query=q, items=items))


async def profile(number: str) -> CompanyMatch:
    n = normalise_company_number(number)
    if is_test_mode():
        hit = next((c for c in FAKE_COMPANIES if c.company_number == n), None)
        if hit is None:
            raise NotFound("Companies House has no company with that number")
        return hit
    if hit := _cached(f"p:{n}"):
        return hit
    return _store(f"p:{n}", _match(await _ch_get(f"/company/{n}")))


# --------------------------------------------------------------------------- #
# HMRC VAT check, through the relay
# --------------------------------------------------------------------------- #


def vat_digits(raw: str) -> str:
    n = normalise_vat_number(raw) or ""
    m = re.fullmatch(r"GB(\d{9}|\d{12})", n)
    if not m:
        raise BadQuery("A UK VAT number is GB followed by 9 or 12 digits")
    return m.group(1)


async def check_vat(vrn: str, requester: str | None = None) -> VatCheck:
    digits = vat_digits(vrn)
    own = vat_digits(requester) if requester else None
    if is_test_mode():
        return _fake_vat(digits)
    base = relay_url()
    if not base:
        raise VatCheckNotConfigured("HMRC_RELAY_URL is not set")
    key = f"v:{digits}:{own or ''}"
    if hit := _cached(key):
        return hit
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=TIMEOUT, follow_redirects=False) as http:
            resp = await http.get(f"{base}/hmrc/vat-check/{digits}", params={"requester": own} if own else None)
    except httpx.HTTPError as e:
        raise Unavailable(f"Couldn't reach the HMRC relay ({type(e).__name__})") from e
    if resp.status_code == 503:
        raise VatCheckNotConfigured("The HMRC relay has no HMRC credentials")
    if resp.status_code == 429:
        raise RateLimited("Too many VAT checks; try again in a minute", retry_after=60)
    if resp.status_code == 400:
        raise BadQuery(str((resp.json() if resp.content else {}).get("detail") or "HMRC refused that VAT number"))
    if resp.status_code >= 400:
        raise Unavailable(f"HMRC's VAT check returned {resp.status_code}")
    return _store(key, VatCheck.model_validate(resp.json()))


_NAME_NOISE = {"limited", "ltd", "plc", "llp", "lp", "uk", "co", "company", "and", "the", "group", "services"}


def names_differ(ours: str | None, theirs: str | None) -> bool:
    """True when the supplier name on file and HMRC's registered name clearly differ: neither key contains the
    other and fewer than half the significant words are shared. 'Novex Office Supplies Ltd' vs 'NOVEX OFFICE
    SUPPLIES LIMITED' do not differ; 'Novex' vs 'Bramble Joinery' do. A warning only, never a block."""
    if not ours or not theirs:
        return False
    a, b = supplier_key(ours), supplier_key(theirs)
    if not a or not b or a in b or b in a:
        return False
    wa = {w for w in a.split("-") if w not in _NAME_NOISE}
    wb = {w for w in b.split("-") if w not in _NAME_NOISE}
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) < 0.5


# --------------------------------------------------------------------------- #
# Test mode: fictional companies and the gold receipts' fictional suppliers
# --------------------------------------------------------------------------- #

# "ZZ" is not a Companies House prefix, so these numbers cannot be a real company's.
FAKE_COMPANIES: tuple[CompanyMatch, ...] = tuple(
    CompanyMatch(
        company_number=n,
        name=name,
        status="active",
        type="ltd",
        address=addr,
        date_of_creation=created,
        source="sample",
        sample=True,
    )
    for n, name, addr, created in (
        ("ZZ000001", "NOVEX OFFICE SUPPLIES LIMITED", "14 Industrial Park, Leeds, LS10 1AB", "2014-03-02"),
        ("ZZ000002", "NOVEX OFFICE FURNITURE LTD", "2 Quay Street, Hull, HU1 1AA", "2019-07-15"),
        ("ZZ000003", "JM TRADING LTD", "9 Market Row, Bristol, BS1 4DJ", "2011-11-30"),
        ("ZZ000004", "BRAMBLEWOOD JOINERY LTD", "Unit 3, Mill Lane, Norwich, NR3 2AB", "2020-01-08"),
    )
)


def _fake_search(q: str) -> list[CompanyMatch]:
    words = [w for w in supplier_key(q).split("-") if w]
    return [c for c in FAKE_COMPANIES if words and all(w in supplier_key(c.name).split("-") for w in words)][:10]


def _fake_vat(digits: str) -> VatCheck:
    """Gold receipt suppliers (fictional, SAMPLE-labelled) are registered under their own name and address; the
    test VRN 000000000 is registered to someone else (to show the name warning); any other number is not."""
    from app import testmode

    at = "2026-10-27T09:00:00+00:00"
    if digits == "000000000":
        return VatCheck(
            vrn="GB000000000",
            registered=True,
            name="BRAMBLEWOOD JOINERY LTD",
            address="Unit 3, Mill Lane, Norwich, NR3 2AB",
            checked_at=at,
            source="sample",
            checksum_ok=True,
        )
    for g in testmode.gold_receipts().values():
        s = g.get("supplier") or {}
        if (normalise_vat_number(s.get("vat_number")) or "") == f"GB{digits}":
            return VatCheck(
                vrn=f"GB{digits}",
                registered=True,
                name=str(s.get("name") or "").upper() or None,
                address=s.get("address"),
                checked_at=at,
                source="sample",
            )
    return VatCheck(vrn=f"GB{digits}", registered=False, checked_at=at, source="sample")
