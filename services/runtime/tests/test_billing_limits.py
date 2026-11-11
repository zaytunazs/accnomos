"""Plans, the account registry fake, registration and limits (app/billing): each counter, the 402 shape, own AI,
trial / comped / read-only accounts, and billing switched off."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app.billing import gauges, middleware
from app.billing import plans as P
from app.billing import registry as R
from app.billing import routes as billing_routes
from app.billing import service as S
from app.books import Books

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch):
    r = R.MemoryRegistry(storage=True)
    R.install(r)
    S.forget()
    monkeypatch.setenv("ACCNOMOS_WEB_URL", "https://app.accnomos.example")
    monkeypatch.delenv("BILLING_RETURN_URL", raising=False)

    async def no_books(_request) -> dict:
        return {"bank_feeds": 0, "marketplaces": 0, "autopilot_rules": 0, "users": 1}

    monkeypatch.setattr(billing_routes, "read_gauges", no_books)
    yield r
    R.install(None)
    S.forget()


@pytest.fixture
def client():
    from app.main import app

    yield TestClient(app)
    app.dependency_overrides.clear()


async def _account(reg: R.MemoryRegistry, **patch) -> dict:
    acc = await S.ensure_account(reg, S.Who(email=USER, name="Sam", kind="personal", subject=f"email:{USER}"))
    if patch:
        acc = await reg.update_account(acc["id"], patch)
        S.forget()
    assert acc is not None
    return acc


def _meter(reg: R.MemoryRegistry, acc: dict, own: bool = False) -> S.Meter:
    plans = {p["code"]: p for p in reg.plans.values()}
    return S.Meter(reg=reg, account=acc, limits=S.limits_for(acc, plans), own_ai=own)


# --------------------------------------------------------------------------- #
# The in-memory registry
# --------------------------------------------------------------------------- #


async def test_registry_creates_one_account_per_identity():
    reg = R.MemoryRegistry()
    row = {"email": "a@x.example", "auth_kind": "google", "auth_subject": "123"}
    a = await reg.create_account(row)
    b = await reg.create_account({**row, "email": "changed@x.example"})
    assert a["id"] == b["id"] and len(reg.accounts) == 1
    assert await reg.find_account("personal", "123") is None


async def test_registry_counts_docs_then_top_up_then_refuses():
    reg = R.MemoryRegistry()
    acc = await reg.create_account({"email": "a@x.example", "auth_kind": "personal", "auth_subject": "s"})
    month = P.month_start()
    assert (await reg.bump_usage(acc["id"], month, "docs", 1, 1))[0]
    ok, row = await reg.bump_usage(acc["id"], month, "docs", 1, 1)
    assert not ok and row["docs"] == 1
    await reg.add_topup(acc["id"], month, 2)
    ok, row = await reg.bump_usage(acc["id"], month, "docs", 1, 1)
    assert ok and row["docs"] == 2 and row["topup_docs_remaining"] == 1
    # the top-up carries into next month, after that month's allowance
    nxt = (month + timedelta(days=32)).replace(day=1)
    usage = await reg.get_usage(acc["id"], nxt)
    assert usage["docs"] == 0 and usage["topup_docs_remaining"] == 1
    assert (await reg.bump_usage(acc["id"], nxt, "ask", 5, None))[0]
    ok, _ = await reg.bump_usage(acc["id"], nxt, "ask", 1, 5)
    assert not ok


async def test_registry_expired_top_up_is_gone():
    reg = R.MemoryRegistry()
    acc = await reg.create_account({"email": "a@x.example", "auth_kind": "personal", "auth_subject": "s"})
    month = P.month_start()
    await reg.add_topup(acc["id"], month, 100)
    reg.usage[(acc["id"], month)]["topup_expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    ok, _ = await reg.bump_usage(acc["id"], month, "docs", 1, 0)
    assert not ok


# --------------------------------------------------------------------------- #
# Registration and GET /account
# --------------------------------------------------------------------------- #


def test_first_call_registers_a_90_day_comprehensive_trial(reg: R.MemoryRegistry, client: TestClient):
    r = client.get("/account", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] and body["status"] == "trialing" and body["plan_code"] == "comprehensive"
    assert body["email"] == USER and body["own_ai"] is False and body["read_only"] is False
    ends = datetime.fromisoformat(body["trial_ends_at"])
    assert timedelta(days=89) < ends - datetime.now(UTC) <= timedelta(days=90)
    assert body["limits"]["docs"] == 300 and body["usage"]["docs"] == 0
    assert set(body["usage"]) >= {
        "docs",
        "ask",
        "invoices",
        "bank_feeds",
        "users",
        "marketplaces",
        "topup_docs_remaining",
    }
    assert client.get("/account", headers=H).json()["id"] == body["id"]
    assert len(reg.accounts) == 1
    assert [e["name"] for e in reg.events] == ["signup"]
    acc = next(iter(reg.accounts.values()))
    assert acc["auth_kind"] == "personal" and acc["auth_subject"] == f"email:{USER}"


def test_account_needs_a_sign_in(reg: R.MemoryRegistry, client: TestClient):
    assert client.get("/account").status_code == 401


def test_google_and_microsoft_with_one_email_are_two_accounts(reg: R.MemoryRegistry, client: TestClient):
    a = client.get("/account", headers=H).json()["id"]
    b = client.get("/account", headers={**H, "X-Account-Kind": "google"}).json()["id"]
    assert a != b


async def test_last_seen_is_written_at_most_hourly(reg: R.MemoryRegistry, monkeypatch: pytest.MonkeyPatch):
    who = S.Who(email=USER, name="", kind="work", subject="graph-id-1")
    acc = await S.ensure_account(reg, who)
    writes: list[dict] = []
    real = reg.update_account

    async def counting(account_id: str, patch: dict):
        writes.append(patch)
        return await real(account_id, patch)

    monkeypatch.setattr(reg, "update_account", counting)
    S.forget()
    await S.ensure_account(reg, who)
    assert writes == []  # seen a moment ago
    reg.accounts[acc["id"]]["last_seen_at"] = datetime.now(UTC) - timedelta(hours=2)
    S.forget()
    await S.ensure_account(reg, who)
    assert len(writes) == 1 and "last_seen_at" in writes[0]


def test_billing_off_leaves_everything_unlimited(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "ACCNOMOS_TEST_MODE"):
        monkeypatch.delenv(k, raising=False)
    R.install(None)
    assert R.registry() is None
    r = client.get("/account", headers=H)
    assert r.status_code == 200 and r.json()["configured"] is False
    assert client.get("/plans").json()[0]["code"] == "starter"
    assert (
        client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H).status_code
        == 503
    )
    # a metered route is not refused: no meter at all
    r = client.post("/extract", headers=H)
    assert r.status_code != 402


def test_public_plans(reg: R.MemoryRegistry, client: TestClient):
    plans = client.get("/plans").json()
    assert [p["code"] for p in plans] == ["starter", "comprehensive", "ultimate"]
    assert plans[0]["price_month_pence"] == 1000 and plans[0]["price_year_pence"] == 10000
    assert plans[0]["limits"]["invoices"] == 20 and plans[1]["limits"]["invoices"] is None


# --------------------------------------------------------------------------- #
# Limits: each counter
# --------------------------------------------------------------------------- #


async def test_documents_are_charged_and_refused_at_the_limit(reg: R.MemoryRegistry):
    acc = await _account(reg, plan_code="starter", status="active")
    m = _meter(reg, acc)
    assert m.limit("docs") == 50
    reg.usage[(acc["id"], P.month_start())] = {**R.empty_usage(acc["id"], P.month_start()), "docs": 49}
    await m.charge_document()
    with pytest.raises(S.PlanLimit) as exc:
        await m.charge_document()
    body = exc.value.body()
    assert body["code"] == "plan_limit" and body["counter"] == "docs"
    assert body["limit"] == 50 and body["used"] == 50
    assert body["upgrade_url"] == "https://app.accnomos.example/settings/billing"
    assert "top-up" not in body["detail"] and "own AI" in body["detail"]  # payments off by default: nothing to buy
    # a top-up is used after the allowance
    await reg.add_topup(acc["id"], P.month_start(), 100)
    await m.charge_document()
    assert (await reg.get_usage(acc["id"], P.month_start()))["topup_docs_remaining"] == 99
    assert sum(e["name"] == "document_scanned" for e in reg.events) == 2


async def test_own_ai_documents_and_questions_are_not_counted(reg: R.MemoryRegistry):
    acc = await _account(reg, plan_code="starter", status="active")
    reg.usage[(acc["id"], P.month_start())] = {**R.empty_usage(acc["id"], P.month_start()), "docs": 50, "ask": 100}
    m = _meter(reg, acc, own=True)
    await m.charge_document()
    await m.precheck("docs")
    await m.precheck("ask")
    await m.record("ask")
    usage = await reg.get_usage(acc["id"], P.month_start())
    assert usage["docs"] == 50 and usage["ask"] == 100
    with pytest.raises(S.PlanLimit):
        await _meter(reg, acc).precheck("ask")


@pytest.mark.parametrize(
    ("headers", "own"),
    [
        ({}, False),
        ({"X-AI-Mode": "auto"}, False),
        ({"X-AI-Mode": "key", "X-Meta-Api-Key": "mk-user"}, True),
        ({"X-AI-Mode": "key"}, False),  # no key of their own: the server's
        ({"X-AI-Mode": "key", "X-Meta-Api-Key": "mk-user", "X-AI-Route": "local_first"}, False),
        ({"X-AI-Mode": "local", "X-AI-Base-Url": "https://glimmer.home.example"}, True),
        ({"X-AI-Mode": "local", "X-AI-Base-Url": "https://glimmer.home.example", "X-AI-Route": "meta_first"}, False),
        ({"X-AI-Mode": "local"}, False),  # the server's own local model
        ({"X-AI-Mode": "local", "X-AI-Base-Url": "http://spark.internal:11434"}, False),  # = OLLAMA_BASE
    ],
)
def test_own_ai_is_the_users_key_or_their_own_model(headers, own, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_BASE", "http://spark.internal:11434/")
    assert S.own_ai(headers) is own


def test_ask_refused_at_the_monthly_limit_with_402(reg: R.MemoryRegistry, client: TestClient):
    acc = client.get("/account", headers=H).json()
    reg.usage[(acc["id"], P.month_start())] = {**R.empty_usage(acc["id"], P.month_start()), "ask": 500}
    r = client.post("/books/ask", json={"question": "What did I spend?"}, headers=H)
    assert r.status_code == 402
    body = r.json()
    assert body == {**body, "code": "plan_limit", "counter": "ask", "limit": 500, "used": 500}
    assert body["upgrade_url"].endswith("/settings/billing")
    own = {**H, "X-AI-Mode": "key", "X-Meta-Api-Key": "mk-user-key-123"}
    assert client.post("/books/ask", json={"question": "What did I spend?"}, headers=own).status_code != 402


def test_document_routes_refused_before_reading_when_used_up(reg: R.MemoryRegistry, client: TestClient):
    acc = client.get("/account", headers=H).json()
    reg.usage[(acc["id"], P.month_start())] = {**R.empty_usage(acc["id"], P.month_start()), "docs": 300}
    for path in ("/extract", "/books/scan", "/books/scan/jobs", "/mail/scan"):
        r = client.post(path, headers=H)
        assert r.status_code == 402 and r.json()["counter"] == "docs", path


async def test_the_document_reader_charges_before_any_model_call(reg: R.MemoryRegistry):
    from app.formats import Prepared
    from app.pipeline import process_document

    acc = await _account(reg)
    reg.usage[(acc["id"], P.month_start())] = {**R.empty_usage(acc["id"], P.month_start()), "docs": 300}
    prep = Prepared(kind="image", image=b"x", mime="image/png")
    with S.metering(_meter(reg, acc)), pytest.raises(S.PlanLimit):
        await process_document(prep, cfg=None, digest="0" * 64)  # type: ignore[arg-type]


@pytest.fixture
def invoice_client(client: TestClient, reg: R.MemoryRegistry):
    from app.invoicing import PROFILE, InvoiceProfile
    from app.main import app
    from app.routes_books import get_books

    books = Books(FakeStorageProvider())
    profile = {
        "name": "Sam Builds Ltd",
        "address": "1 High Street\nLeeds LS1 1AA",
        "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
    }

    async def over_books() -> Books:
        await books.write_json(PROFILE, InvoiceProfile.model_validate(profile).model_dump(mode="json"))
        return books

    app.dependency_overrides[get_books] = over_books
    return client


DRAFT = {
    "customer": {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example", "address": "2 Low Road"},
    "issue_date": "2026-10-27",
    "lines": [{"description": "Labour", "quantity": "1", "unit": "hours", "unit_price_pence": 4500}],
}


def test_invoices_are_counted_after_success_and_refused_at_the_limit(reg: R.MemoryRegistry, invoice_client: TestClient):
    acc = invoice_client.get("/account", headers=H).json()
    reg.accounts[acc["id"]].update(plan_code="starter", status="active")
    S.forget()
    r = invoice_client.post("/invoices", json=DRAFT, headers=H)
    assert r.status_code in (200, 201), r.text
    assert reg.usage[(acc["id"], P.month_start())]["invoices"] == 1
    bad = invoice_client.post("/invoices", json={"customer": {}}, headers=H)
    assert bad.status_code == 422 and reg.usage[(acc["id"], P.month_start())]["invoices"] == 1  # failures not counted
    reg.usage[(acc["id"], P.month_start())]["invoices"] = 20
    r = invoice_client.post("/invoices", json=DRAFT, headers=H)
    assert r.status_code == 402 and r.json()["counter"] == "invoices" and r.json()["limit"] == 20
    # unlimited on a trial (Comprehensive's limits)
    reg.accounts[acc["id"]].update(status="trialing")
    S.forget()
    assert invoice_client.post("/invoices", json=DRAFT, headers=H).status_code in (200, 201)


async def test_bank_feeds_are_limited_by_what_is_connected(reg: R.MemoryRegistry, monkeypatch: pytest.MonkeyPatch):
    acc = await _account(reg, plan_code="starter", status="active")
    counts = {"all": 1, "reauth": 0}

    async def n_feeds(_books) -> int:
        return counts["all"]

    async def n_reauth(_books) -> int:
        return counts["reauth"]

    monkeypatch.setattr(gauges, "bank_feeds", n_feeds)
    monkeypatch.setattr(gauges, "bank_feeds_needing_reauth", n_reauth)
    books = Books(FakeStorageProvider())
    await gauges.bank_feed_room(books)  # no meter: never limited
    with S.metering(_meter(reg, acc)):
        with pytest.raises(S.PlanLimit) as exc:
            await gauges.bank_feed_room(books)
        assert exc.value.body()["counter"] == "bank_feeds" and exc.value.limit == 1
        counts["reauth"] = 1  # the one there needs reconnecting: reconnecting is allowed
        await gauges.bank_feed_room(books)


async def test_marketplaces_starter_has_none_and_reconnecting_is_allowed(reg: R.MemoryRegistry, monkeypatch):
    acc = await _account(reg, plan_code="starter", status="active")
    connected = {"n": 0}

    async def n_markets(_books) -> int:
        return connected["n"]

    monkeypatch.setattr(gauges, "marketplaces", n_markets)
    books = Books(FakeStorageProvider())
    with S.metering(_meter(reg, acc)):
        with pytest.raises(S.PlanLimit) as exc:
            await gauges.marketplace_room(books)
        assert exc.value.limit == 0 and "doesn't include" in exc.value.body()["detail"]
        connected["n"] = 1
        await gauges.marketplace_room(books)
    comp = await _account(reg, plan_code="comprehensive", status="active")
    connected["n"] = 0
    with S.metering(_meter(reg, comp)):
        await gauges.marketplace_room(books)


async def test_autopilot_rules_capped_without_blocking_approval(reg: R.MemoryRegistry, monkeypatch):
    from app import approve as approve_mod

    acc = await _account(reg, plan_code="starter", status="active")
    rules = [type("Rule", (), {"supplier_key": f"s{i}"})() for i in range(5)]

    async def load(_books):
        return rules

    monkeypatch.setattr(approve_mod, "load_rules", load)
    books = Books(FakeStorageProvider())
    m = _meter(reg, acc)
    with S.metering(m):
        assert await approve_mod._rule_room(books, "s0")  # replacing a supplier's rule is fine
        assert not await approve_mod._rule_room(books, "new-supplier")
    assert m.notices == ["autopilot_rules"]
    assert await approve_mod._rule_room(books, "new-supplier")  # no billing: no cap


def test_users_limit_is_reported(reg: R.MemoryRegistry, client: TestClient):
    body = client.get("/account", headers=H).json()
    assert body["usage"]["users"] == 1 and body["limits"]["users"] == 3


# --------------------------------------------------------------------------- #
# Trial, comped, read-only
# --------------------------------------------------------------------------- #


async def test_trial_gets_comprehensive_limits_whatever_plan_it_picked(reg: R.MemoryRegistry):
    acc = await _account(reg, plan_code="starter", status="trialing", stripe_subscription_id="sub_1")
    assert _meter(reg, acc).limit("docs") == 300
    acc = await _account(reg, plan_code="starter", status="active")
    assert _meter(reg, acc).limit("docs") == 50


async def test_trial_end_without_a_subscription_is_read_only(reg: R.MemoryRegistry, client: TestClient):
    acc = await _account(reg, trial_ends_at=datetime.now(UTC) - timedelta(minutes=1))
    r = client.post("/invoices", json=DRAFT, headers=H)
    assert r.status_code == 402
    assert r.json()["code"] == "read_only" and r.json()["status"] == "trial_ended"
    assert reg.accounts[acc["id"]]["status"] == "trial_ended"
    assert "trial_ended" in [e["name"] for e in reg.events]
    # billing still works (no customer yet: 409, not read-only)
    assert client.post("/billing/portal", headers=H).status_code in (409, 503)
    body = client.get("/account", headers=H).json()
    assert body["read_only"] is True


async def test_trialing_with_a_subscription_is_left_to_stripe(reg: R.MemoryRegistry):
    acc = await _account(reg, trial_ends_at=datetime.now(UTC) - timedelta(minutes=1), stripe_subscription_id="sub_1")
    assert S.effective_status(acc, datetime.now(UTC)) == "trialing"


async def test_comp_expires_into_read_only(reg: R.MemoryRegistry):
    acc = await _account(reg, status="comped", comp_until=datetime.now(UTC) + timedelta(days=1))
    assert S.effective_status(acc, datetime.now(UTC)) == "comped"
    assert S.effective_status(acc, datetime.now(UTC) + timedelta(days=2)) == "trial_ended"


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("/profile", True),
        ("/setup-wizard/step/business", True),
        ("/exports/vat-return/save", True),
        ("/books/export", True),
        ("/reports/export", True),
        ("/invoices/INV-0001/pdf", True),
        ("/invoices/profile", True),
        ("/books/bankfeeds/abc/disconnect", True),
        ("/books/ebay/disconnect", True),
        ("/accountant/invitations/i1/revoke", True),
        ("/books/rules/acme", True),
        ("/invoices", False),
        ("/books/proposals/p1/approve", False),
        ("/books/scan", False),
        ("/books/ask", False),
    ],
)
def test_read_only_still_allows_settings_exports_and_disconnecting(path: str, ok: bool):
    assert bool(middleware.WRITE_OK.search(path)) is ok


def test_accountant_in_a_clients_books_and_demo_are_not_metered(reg: R.MemoryRegistry, client: TestClient):
    acc = client.get("/account", headers=H).json()
    reg.usage[(acc["id"], P.month_start())] = {**R.empty_usage(acc["id"], P.month_start()), "docs": 300}
    shared = {**H, "X-Books-Drive-Id": "d1", "X-Books-Item-Id": "i1"}
    assert client.post("/extract", headers=shared).status_code != 402


def test_plan_limit_body_for_a_monthly_counter():
    body = S.PlanLimit("invoices", 20, 20).body()
    assert body["code"] == "plan_limit" and "1st" in body["detail"]


@pytest.mark.parametrize(("provider", "buying"), [("none", False), ("stripe", True)])
def test_refusals_mention_buying_only_when_payments_are_on(provider: str, buying: bool, monkeypatch):
    monkeypatch.setenv("PAYMENTS_PROVIDER", provider)
    docs = S.PlanLimit("docs", 50, 50).body()["detail"]
    feeds = S.PlanLimit("bank_feeds", 1, 1).body()["detail"]
    ended = S.ReadOnly("trial_ended").body()["detail"]
    assert ("top-up" in docs) is buying and ("Upgrade" in feeds) is buying
    assert ("Choose a plan" in ended) is buying and ("promo code" in ended) is not buying


def test_limits_validation():
    assert P.validate_limits({"docs": 10, "invoices": None, "projects": True}) == {
        "docs": 10,
        "invoices": None,
        "projects": True,
    }
    for bad in ({"docs": -1}, {"docs": "lots"}, {"projects": 1}, {"nope": 1}, {"docs": True}):
        with pytest.raises(ValueError):
            P.validate_limits(bad)


async def test_test_mode_uses_the_in_memory_registry_and_reset_clears_usage(monkeypatch: pytest.MonkeyPatch):
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    R.install(None)
    try:
        reg = R.registry()
        assert isinstance(reg, R.MemoryRegistry) and R.registry() is reg
        acc = await reg.create_account({"email": USER, "auth_kind": "personal", "auth_subject": "x"})
        await reg.bump_usage(acc["id"], P.month_start(), "docs", 3, None)
        R.reset_test_mode()
        assert (await reg.get_usage(acc["id"], P.month_start()))["docs"] == 0
        assert await reg.get_account(acc["id"]) is not None
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
        assert isinstance(R.registry(), R.SupabaseRegistry)
    finally:
        R.install(None)


async def test_supabase_registry_speaks_postgrest(monkeypatch: pytest.MonkeyPatch):
    import json as _json

    import httpx

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/rest/v1/accounts" and request.method == "GET":
            return httpx.Response(200, json=[{"id": "a1", "email": USER, "created_at": "2026-11-11T10:00:00+00:00"}])
        if path == "/rest/v1/accounts" and request.method == "POST":
            return httpx.Response(201, json=[])  # a duplicate: ignored, then found
        if path == "/rest/v1/rpc/bump_usage":
            body = _json.loads(request.content)
            row = {"account_id": body["p_account"], "month": body["p_month"], "docs": 7, "ask": 0, "invoices": 0}
            return httpx.Response(200, json={"ok": False, "usage": {**row, "topup_docs_remaining": 0}})
        if path == "/rest/v1/admin_audit":
            return httpx.Response(200, json=[], headers={"content-range": "0-0/42"})
        if path.startswith("/storage/v1/object/bug-screenshots/"):
            return httpx.Response(400, json={"message": "no bucket"})
        return httpx.Response(404, json={"message": "nope"})

    monkeypatch.setattr(R, "TRANSPORT", httpx.MockTransport(handle))
    reg = R.SupabaseRegistry("https://proj.supabase.co/", "service-key")
    acc = await reg.find_account("google", "sub-1")
    assert acc is not None and acc["created_at"] == datetime(2026, 11, 11, 10, tzinfo=UTC)
    first = seen[0]
    assert first.headers["apikey"] == "service-key" and first.headers["authorization"] == "Bearer service-key"
    assert first.headers["accept-profile"] == "accnomos"
    assert first.url.params["auth_kind"] == "eq.google" and first.url.params["auth_subject"] == "eq.sub-1"
    created = await reg.create_account({"email": USER, "auth_kind": "google", "auth_subject": "sub-1"})
    assert created["id"] == "a1"
    post = next(r for r in seen if r.method == "POST" and r.url.path == "/rest/v1/accounts")
    assert post.headers["content-profile"] == "accnomos" and "ignore-duplicates" in post.headers["prefer"]
    assert post.url.params["on_conflict"] == "auth_kind,auth_subject"
    ok, row = await reg.bump_usage("a1", P.month_start(), "docs", 1, 50)
    assert ok is False and row["docs"] == 7 and row["month"] == P.month_start()
    _, total = await reg.list_audit(None, 1, 25)
    assert total == 42 and "count=exact" in seen[-1].headers["prefer"]
    with pytest.raises(R.StorageUnavailable):
        await reg.upload_screenshot("a1/x.png", b"png", "image/png")
    assert await reg.get_account("not-a-uuid") is None
