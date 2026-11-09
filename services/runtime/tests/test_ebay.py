"""Connect eBay (app/ebay_sync.py, app/ebay.py, app/routes_ebay.py) against the fake in app/ebay_fakes.py, which answers
with the request and response shapes app/ebay.py documents. Nothing here talks to eBay."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.vat import compute_vat_return
from app import books as books_mod
from app import ebay, ebay_fakes, ebay_sync
from app.approve import approve
from app.books import Books
from app.ebay_fakes import FAKES
from app.ebay_sync import CONNECTION, IMPORTED, VatSettings, binding_hash, key_id, map_transaction, seal, unseal
from app.invoicing import PROFILE as INVOICE_PROFILE
from app.journal import EBAY_CLEARING, MARKETPLACE_FEES, SALES, VAT_CONTROL

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
WEB = "http://localhost:3000"
BANK_PAGE = f"{WEB}/bank"
BINDING = "browser-only-secret-0123456789"
KEY = base64.b64encode(bytes(range(32))).decode()
TODAY = date(2026, 10, 27)
VRN = "GB123456789"
ENV = ("ACCNOMOS_TEST_MODE", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_RUNAME", "EBAY_ENV", "EBAY_TOKEN_KEY")


def _env(monkeypatch: pytest.MonkeyPatch, *, on: bool = True) -> None:
    for k in (*ENV, "BANKFEEDS_TOKEN_KEY", "EBAY_DELETION_TOKEN", "EBAY_DELETION_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CORS_ORIGINS", WEB)
    if on:
        monkeypatch.setenv("EBAY_CLIENT_ID", ebay_fakes.CLIENT[0])
        monkeypatch.setenv("EBAY_CLIENT_SECRET", ebay_fakes.CLIENT[1])
        monkeypatch.setenv("EBAY_RUNAME", ebay_fakes.RUNAME)
        monkeypatch.setenv("EBAY_TOKEN_KEY", KEY)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch):
    _env(monkeypatch)
    ebay_fakes.reset()
    ebay_fakes.install()
    ebay_sync._spent.clear()
    monkeypatch.setattr(books_mod, "today", lambda tz=None: TODAY)
    monkeypatch.setattr(ebay_sync, "today", lambda tz=None: TODAY)
    yield
    ebay.TRANSPORT = None


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def over_books() -> Books:
        return books

    app.dependency_overrides[get_books] = over_books
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _vat_registered(books: Books, vrn: str | None = VRN, registered: bool = True) -> None:
    await books.write_json(INVOICE_PROFILE, {"name": "Sam Builds", "vrn": vrn, "vat_registered": registered})


def _ok(r: httpx.Response) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _start(client: TestClient) -> str:
    body = {"redirect_to": BANK_PAGE, "binding_hash": binding_hash(BINDING)}
    return _ok(client.post("/books/ebay/connect", json=body, headers=H))["url"]


def _callback(client: TestClient, url: str) -> dict[str, str]:
    """Play eBay: the fake's consent page answers a code; the runtime's callback forwards it in the fragment."""
    q = parse_qs(urlsplit(url).query)
    back = client.get(
        "/books/ebay/callback",
        params={"code": FAKES.new_code(), "state": q["state"][0], "expires_in": "299"},
        follow_redirects=False,
    )
    assert back.status_code == 303, back.text
    assert back.headers["location"].startswith(f"{BANK_PAGE}#")
    return dict(parse_qsl(urlsplit(back.headers["location"]).fragment))


def _connect(client: TestClient) -> dict:
    frag = _callback(client, _start(client))
    assert frag["feed"] == "ebay"
    body = {"code": frag["code"], "state": frag["state"], "binding": BINDING}
    return _ok(client.post("/books/ebay/complete", json=body, headers=H))


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_off_without_env_hides_the_card_and_refuses(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    _env(monkeypatch, on=False)
    got = _ok(client.get("/books/ebay", headers=H))
    assert got["configured"] is False and got["reason"] == ebay_sync.OFF_SENTENCE
    body = {"redirect_to": BANK_PAGE, "binding_hash": binding_hash(BINDING)}
    assert client.post("/books/ebay/connect", json=body, headers=H).status_code == 503
    assert client.post("/books/ebay/sync", headers=H).status_code == 503


def test_sandbox_by_default_production_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, key, why = ebay_sync.config()
    assert why is None and key is not None and cfg is not None and cfg.hosts == ebay.SANDBOX and cfg.sandbox
    monkeypatch.setenv("EBAY_ENV", "production")
    cfg, _, _ = ebay_sync.config()
    assert cfg is not None and cfg.hosts == ebay.PRODUCTION and not cfg.sandbox
    monkeypatch.setenv("EBAY_ENV", "live")
    assert ebay_sync.config()[0] is None
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.delenv("EBAY_TOKEN_KEY")
    monkeypatch.setenv("BANKFEEDS_TOKEN_KEY", KEY)  # the bank feeds' key serves when eBay has none of its own
    assert ebay_sync.config()[1] == bytes(range(32))


def test_demo_session_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import demo

    monkeypatch.setattr(demo, "is_demo_request", lambda request: True)
    assert _ok(client.get("/books/ebay", headers=H))["configured"] is False
    r = client.post("/books/ebay/sync", headers=H)
    assert r.status_code == 403 and "demo" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# OAuth: consent URL, callback, code exchange, sealed refresh token
# --------------------------------------------------------------------------- #


def test_seal_round_trip() -> None:
    key = bytes(range(32))
    sealed = seal("v^1.1#refresh", key)
    assert "refresh" not in sealed and unseal(sealed, key) == "v^1.1#refresh"
    assert unseal(sealed, bytes(32)) is None and unseal(sealed, key, "other") is None


async def test_connect_exchanges_the_code_and_keeps_only_a_sealed_refresh_token(
    client: TestClient, fake: FakeStorageProvider
) -> None:
    url = _start(client)
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://auth.sandbox.ebay.com/oauth2/authorize"
    assert q["client_id"] == [ebay_fakes.CLIENT[0]] and q["redirect_uri"] == [ebay_fakes.RUNAME]
    assert q["response_type"] == ["code"] and q["scope"] == [" ".join(ebay.SCOPES)]

    got = _connect(client)
    assert got["connected"] is True and got["state"] == "ok" and got["sandbox"] is True

    [token_req] = [r for r in FAKES.requests if r.url.path == "/identity/v1/oauth2/token"]
    assert str(token_req.url) == "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    basic = base64.b64encode(f"{ebay_fakes.CLIENT[0]}:{ebay_fakes.CLIENT[1]}".encode()).decode()
    assert token_req.headers["Authorization"] == f"Basic {basic}"
    form = dict(parse_qsl(token_req.content.decode()))
    assert form["grant_type"] == "authorization_code" and form["redirect_uri"] == ebay_fakes.RUNAME
    assert form["code"].startswith("v^1.1#")  # encoded once by the form, not twice

    raw = (await fake.read(CONNECTION)).decode()
    for t in FAKES.refresh | FAKES.access:
        assert t not in raw
    stored = json.loads(raw)["connection"]
    assert stored["token"].startswith("v1.") and stored["key_id"] == key_id(bytes(range(32)))


def test_state_is_single_use_and_bound_to_the_browser(client: TestClient) -> None:
    frag = _callback(client, _start(client))
    wrong = {"code": frag["code"], "state": frag["state"], "binding": "another-browser-secret-xyz"}
    r = client.post("/books/ebay/complete", json=wrong, headers=H)
    assert r.status_code == 400 and "another browser" in r.json()["detail"]
    right = {"code": frag["code"], "state": frag["state"], "binding": BINDING}
    assert client.post("/books/ebay/complete", json=right, headers=H).status_code == 400  # state spent
    assert client.get("/books/ebay/callback", params={"state": "forged.state"}).status_code == 400


def test_redirect_must_be_the_bank_page(client: TestClient) -> None:
    body = {"redirect_to": "https://evil.example/bank", "binding_hash": binding_hash(BINDING)}
    assert client.post("/books/ebay/connect", json=body, headers=H).status_code == 400


def test_decline_comes_back_as_an_error(client: TestClient) -> None:
    q = parse_qs(urlsplit(_start(client)).query)
    back = client.get(
        "/books/ebay/callback", params={"state": q["state"][0], "error": "access_denied"}, follow_redirects=False
    )
    frag = dict(parse_qsl(urlsplit(back.headers["location"]).fragment))
    assert frag["error"] == "access_denied" and "code" not in frag


async def test_changed_server_key_reads_as_connect_again(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _connect(client)
    monkeypatch.setenv("EBAY_TOKEN_KEY", base64.b64encode(bytes(32)).decode())
    got = _ok(client.get("/books/ebay", headers=H))
    assert got["state"] == "key_changed" and "Connect again" in got["message"]
    r = client.post("/books/ebay/sync", headers=H)
    assert r.status_code == 400 and "key changed" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Sync: requests, pagination, mapping, dedupe
# --------------------------------------------------------------------------- #


async def test_sync_proposes_sales_fees_refund_postage_and_records_the_payout(client: TestClient, books: Books) -> None:
    await _vat_registered(books)
    _connect(client)
    got = _ok(client.post("/books/ebay/sync", headers=H))
    assert (got["sales"], got["refunds"], got["fees"], got["postage"], got["payouts"]) == (2, 1, 4, 1, 1)
    assert got["already_imported"] == 0 and got["skipped"] == 1
    assert got["skipped_items"][0]["type"] == "ADJUSTMENT"
    assert got["start"] == "2026-07-29" and got["end"] == "2026-10-27"  # 90 days by default
    assert len(got["proposals"]) == 8

    tx = [r for r in FAKES.requests if r.url.path == "/sell/finances/v1/transaction"][0]
    assert tx.url.host == "apiz.sandbox.ebay.com"
    assert tx.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_GB"
    assert tx.url.params["filter"].startswith("transactionDate:[2026-07-29T00:00:00.000Z..")
    orders = [r for r in FAKES.requests if r.url.path == "/sell/fulfillment/v1/order"]
    assert len(orders) == 1 and set(orders[0].url.params["orderIds"].split(",")) == {
        ebay_fakes.ORDER_1,
        ebay_fakes.ORDER_2,
    }

    props = [await books.get_proposal(pid) for pid in got["proposals"]]
    assert all(p.status == "needs_a_look" and p.settlement_account == EBAY_CLEARING for p in props)
    assert await books.list_events() == []  # nothing posted without approval

    sale = next(
        p for p in props if p.extracted.invoice_number == ebay_fakes.ORDER_1 and p.extracted.doc_type == "sales_invoice"
    )
    j = {(x.account, x.debit_pence, x.credit_pence) for x in sale.journal_draft}
    assert j == {(EBAY_CLEARING, 2400, 0), (SALES, 0, 2000), (VAT_CONTROL, 0, 400)}
    assert "Blue mug" in sale.reasons[0]

    refund = next(p for p in props if p.sale_refund)
    j = {(x.account, x.debit_pence, x.credit_pence) for x in refund.journal_draft}
    assert j == {(SALES, 2500, 0), (VAT_CONTROL, 500, 0), (EBAY_CLEARING, 0, 3000)}

    fee = next(p for p in props if p.extracted.invoice_number == ebay_fakes.ORDER_1 and p.account_override)
    j = {(x.account, x.debit_pence, x.credit_pence) for x in fee.journal_draft}
    assert j == {(MARKETPLACE_FEES, 280, 0), (EBAY_CLEARING, 0, 280)}  # no eBay VAT number saved: VAT in the cost
    assert any("no eBay VAT number" in r for r in fee.reasons)

    status = _ok(client.get("/books/ebay", headers=H))
    assert status["last_summary"]["sales"] == 2 and status["last_synced_at"]
    assert status["payouts"] == [
        {"payout_id": "fake-payout-1", "date": "2026-10-26", "amount_pence": 4003, "last4": "5678", "matched": False}
    ]


async def test_second_sync_proposes_nothing_twice(client: TestClient, books: Books, fake: FakeStorageProvider) -> None:
    _connect(client)
    first = _ok(client.post("/books/ebay/sync", headers=H))
    again = _ok(client.post("/books/ebay/sync", headers=H))
    assert again["proposals"] == [] and again["payouts"] == 0
    assert again["already_imported"] == 6  # five transactions and the payout; the adjustment is skipped again
    ids = json.loads((await fake.read(IMPORTED)).decode())["ids"]
    assert set(ids) == {
        "SALE:fake-tx-001",
        "SALE:fake-tx-002",
        "REFUND:fake-tx-003",
        "NON_SALE_CHARGE:fake-tx-004",
        "SHIPPING_LABEL:fake-tx-005",
        "PAYOUT:fake-payout-1",
    }
    assert sorted(sum(ids.values(), [])) == sorted(first["proposals"])


async def test_pagination_reads_every_page(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ebay, "PAGE", 2)
    _connect(client)
    got = _ok(client.post("/books/ebay/sync", headers=H))
    offsets = [r.url.params["offset"] for r in FAKES.requests if r.url.path == "/sell/finances/v1/transaction"]
    assert offsets == ["0", "2", "4"]
    assert all(r.url.params["limit"] == "2" for r in FAKES.requests if r.url.path.startswith("/sell/finances"))
    assert got["sales"] == 2 and got["skipped"] == 1


async def test_nothing_in_range_is_a_204(client: TestClient) -> None:
    _connect(client)
    got = _ok(client.post("/books/ebay/sync", json={"days": 1}, headers=H))
    # No transaction in the last day: the fake answers 204 No Content, as eBay does; yesterday's payout is still read.
    assert got["proposals"] == [] and got["skipped"] == 0 and got["payouts"] == 1


async def test_titles_failing_still_proposes_with_a_warning(client: TestClient) -> None:
    FAKES.fail_orders = True
    _connect(client)
    got = _ok(client.post("/books/ebay/sync", headers=H))
    assert got["sales"] == 2 and "titles could not be read" in got["warning"]


async def test_withdrawn_access_says_connect_again(client: TestClient) -> None:
    _connect(client)
    FAKES.revoke_refresh = True
    r = client.post("/books/ebay/sync", headers=H)
    assert r.status_code == 400 and "Connect eBay again" in r.json()["detail"]


async def test_approved_imports_net_to_the_payout_and_reach_the_vat_return(client: TestClient, books: Books) -> None:
    from app.online_payments import clearing_balance

    await _vat_registered(books)
    _connect(client)
    got = _ok(client.post("/books/ebay/sync", headers=H))
    for pid in got["proposals"]:
        await approve(books, pid, USER)
    assert await clearing_balance(books, "ebay") == 4003  # exactly eBay's payout: the bank line matches it
    ret = compute_vat_return(await books.list_events(), "26A1", date(2026, 7, 1), TODAY)
    assert str(ret.vat_due_sales) == "9.00"  # 4.00 + 10.00 - 5.00 (the refund)
    assert ret.total_sales_ex_vat == 45  # 20 + 50 - 25


async def test_disconnect_needs_confirming_and_keeps_proposals(client: TestClient, books: Books) -> None:
    _connect(client)
    got = _ok(client.post("/books/ebay/sync", headers=H))
    assert client.post("/books/ebay/disconnect", json={}, headers=H).status_code == 400
    out = _ok(client.post("/books/ebay/disconnect", json={"confirm": True}, headers=H))
    assert out["status"]["connected"] is False and "eBay account settings" in out["message"]
    assert (await books.get_proposal(got["proposals"][0])).status == "needs_a_look"
    assert client.post("/books/ebay/disconnect", json={"confirm": True}, headers=H).status_code == 404


# --------------------------------------------------------------------------- #
# Mapping rules (pure)
# --------------------------------------------------------------------------- #

SALE = {
    "transactionId": "t1",
    "transactionType": "SALE",
    "transactionDate": "2026-10-01T09:00:00.000Z",
    "orderId": "o1",
    "amount": {"value": "108.00", "currency": "GBP"},
    "bookingEntry": "CREDIT",
    "totalFeeAmount": {"value": "12.00", "currency": "GBP"},
    "totalFeeBasisAmount": {"value": "120.00", "currency": "GBP"},
}


def test_not_vat_registered_sales_carry_no_vat() -> None:
    _, props, counts, _ = map_transaction(SALE, VatSettings(registered=False, own_vrn=None, fee_vrn=None), {})
    sale = props[0].extracted
    assert counts == {"sales": 1, "fees": 1} and sale.vat_total == 0 and sale.gross_total == 120


def test_tax_collected_by_ebay_is_proposed_zero_rated() -> None:
    tx = SALE | {"eBayCollectedTaxAmount": {"value": "24.00", "currency": "GBP"}}
    tx["totalFeeBasisAmount"] = {"value": "144.00", "currency": "GBP"}
    _, props, _, _ = map_transaction(tx, VatSettings(registered=True, own_vrn=VRN, fee_vrn=None), {})
    sale = props[0]
    assert sale.extracted.vat_total == 0 and sale.extracted.lines[0].vat_rate == 0
    assert any("zero-rated" in r for r in sale.reasons)
    assert not any("differs" in r for r in sale.reasons)


def test_with_ebays_vat_number_fee_vat_is_reclaimable() -> None:
    _, props, _, _ = map_transaction(SALE, VatSettings(registered=True, own_vrn=VRN, fee_vrn="GB999999973"), {})
    fee = props[1].extracted
    assert fee.supplier_vat_number == "GB999999973" and fee.vat_total == 2.0 and fee.net_total == 10.0


def test_odd_currency_and_unknown_types_are_skipped() -> None:
    vs = VatSettings(registered=True, own_vrn=VRN, fee_vrn=None)
    _, props, _, skipped = map_transaction(SALE | {"amount": {"value": "10.00", "currency": "EUR"}}, vs, {})
    assert props == [] and skipped is not None and "EUR" in skipped.reason
    _, props, _, skipped = map_transaction(SALE | {"transactionType": "DISPUTE"}, vs, {})
    assert props == [] and skipped is not None and "dispute" in skipped.reason


def test_vat_number_setting_is_checked(client: TestClient) -> None:
    assert client.put("/books/ebay/settings", json={"fee_vat_number": "nonsense"}, headers=H).status_code == 400
    got = _ok(client.put("/books/ebay/settings", json={"fee_vat_number": "GB 999 9999 73"}, headers=H))
    assert got["fee_vat_number"] == "GB999999973"


def test_account_deletion_challenge(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/ebay/account-deletion", params={"challenge_code": "abc"}).status_code == 404
    token, endpoint = "t" * 40, "https://api.example/ebay/account-deletion"
    monkeypatch.setenv("EBAY_DELETION_TOKEN", token)
    monkeypatch.setenv("EBAY_DELETION_ENDPOINT", endpoint)
    got = _ok(client.get("/ebay/account-deletion", params={"challenge_code": "abc"}))
    assert got == {"challengeResponse": hashlib.sha256(("abc" + token + endpoint).encode()).hexdigest()}
    assert client.post("/ebay/account-deletion", json={"metadata": {}}).status_code == 204
