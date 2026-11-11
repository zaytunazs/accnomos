"""The admin API (allow-list, audit), first-party analytics (opt-out, property rules, rate limit), bug reports,
api_error events and the Sentry scrubber (app/billing)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from app.billing import analytics, fakes, middleware, sentry, stripe_api
from app.billing import plans as P
from app.billing import registry as R
from app.billing import routes as billing_routes
from app.billing import service as S
from app.security import TokenBucket

USER = "sam@example.co.uk"
BOSS = "boss@accnomos.example"
H = {"X-Graph-Token": "tok", "X-User": USER}
A = {"X-Graph-Token": "tok", "X-User": BOSS}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch):
    r = R.MemoryRegistry(storage=True)
    R.install(r)
    S.forget()
    fakes.reset()
    fakes.install()
    monkeypatch.setenv("ADMIN_EMAILS", f" {BOSS.upper()} , other@accnomos.example")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_billing_123")
    monkeypatch.setenv("PAYMENTS_PROVIDER", "stripe")

    async def no_books(_request) -> dict:
        return {"bank_feeds": 0, "marketplaces": 0, "autopilot_rules": 0, "users": 1}

    monkeypatch.setattr(billing_routes, "read_gauges", no_books)
    monkeypatch.setattr(analytics, "EVENTS_LIMITER", TokenBucket(100))
    monkeypatch.setattr(analytics, "BUGS_LIMITER", TokenBucket(100))
    yield r
    R.install(None)
    S.forget()
    stripe_api.TRANSPORT = None


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def _user(client: TestClient, reg: R.MemoryRegistry) -> dict:
    client.get("/account", headers=H)
    return next(a for a in reg.accounts.values() if a["email"] == USER)


# --------------------------------------------------------------------------- #
# Admin: who may, and the audit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/metrics"),
        ("GET", "/admin/users"),
        ("GET", "/admin/users/x"),
        ("PATCH", "/admin/users/x"),
        ("POST", "/admin/users/x/actions"),
        ("GET", "/admin/codes"),
        ("POST", "/admin/codes"),
        ("PATCH", "/admin/codes/X"),
        ("GET", "/admin/plans"),
        ("PATCH", "/admin/plans/starter"),
        ("GET", "/admin/audit"),
        ("GET", "/admin/analytics"),
        ("GET", "/admin/bug-reports"),
        ("PATCH", "/admin/bug-reports/x"),
    ],
)
def test_admin_is_for_the_allow_list_only(method: str, path: str, reg: R.MemoryRegistry, client: TestClient):
    assert client.request(method, path, headers=H, json={}).status_code == 403
    assert client.request(method, path, json={}).status_code == 401
    assert reg.audit == []


def test_admin_identity_is_the_verified_one_not_a_header(reg: R.MemoryRegistry, client: TestClient):
    # the stand-in verifier answers X-User; a different, client-written header is never read
    r = client.get("/admin/metrics", headers={**H, "X-Admin-Email": BOSS})
    assert r.status_code == 403
    assert client.get("/admin/metrics", headers=A).status_code == 200


def test_metrics(reg: R.MemoryRegistry, client: TestClient):
    acc = _user(client, reg)
    reg.accounts[acc["id"]]["trial_ends_at"] = datetime.now(UTC) + timedelta(days=3)
    other = {"email": "b@x.example", "auth_kind": "google", "auth_subject": "g1", "status": "active"}
    reg.accounts["b"] = {
        **reg.accounts[acc["id"]],
        **other,
        "id": "b",
        "plan_code": "starter",
        "billing_interval": "year",
    }
    m = client.get("/admin/metrics", headers=A).json()
    assert m["trialing"] == 1 and m["active"] == 1 and m["active_by_plan"]["starter"] == 1
    assert m["mrr_pence"] == round(10000 / 12) and m["trials_ending_7d"] == 1
    assert len(m["signups_by_day"]) == 30 and m["signups_by_day"][-1]["count"] == 2


def test_users_list_detail_patch_and_audit(reg: R.MemoryRegistry, client: TestClient):
    acc = _user(client, reg)
    page = client.get("/admin/users?q=sam&page=1", headers=A).json()
    assert page["total"] == 1 and page["items"][0]["usage"]["docs"] == 0
    assert client.get("/admin/users?status=nonsense", headers=A).status_code == 400
    r = client.patch(f"/admin/users/{acc['id']}", json={"plan_code": "ultimate", "notes": "VIP"}, headers=A)
    assert r.status_code == 200 and r.json()["plan_code"] == "ultimate"
    assert reg.audit[-1]["admin_email"] == BOSS and reg.audit[-1]["action"] == "update_account"
    assert reg.audit[-1]["detail"]["before"]["plan_code"] == "comprehensive"
    detail = client.get(f"/admin/users/{acc['id']}", headers=A).json()
    assert detail["notes"] == "VIP" and detail["audit"][0]["action"] == "update_account"
    assert client.get("/admin/users/nope", headers=A).status_code == 404


def test_actions_are_audited(reg: R.MemoryRegistry, client: TestClient):
    acc = _user(client, reg)
    reg.accounts[acc["id"]].update(status="trial_ended", trial_ends_at=datetime.now(UTC) - timedelta(days=1))
    r = client.post(f"/admin/users/{acc['id']}/actions", json={"action": "extend_trial", "days": 14}, headers=A)
    assert r.status_code == 200 and r.json()["account"]["status"] == "trialing"
    r = client.post(f"/admin/users/{acc['id']}/actions", json={"action": "grant_topup", "docs": 50}, headers=A)
    assert reg.usage[(acc["id"], P.month_start())]["topup_docs_remaining"] == 50
    assert (
        client.post(f"/admin/users/{acc['id']}/actions", json={"action": "cancel_at_period_end"}, headers=A).status_code
        == 409
    )  # no subscription
    reg.accounts[acc["id"]].update(stripe_subscription_id="sub_1", stripe_customer_id="cus_1")
    assert client.post(f"/admin/users/{acc['id']}/actions", json={"action": "cancel_at_period_end"}, headers=A).json()[
        "account"
    ]["cancel_at_period_end"]
    url = client.post(f"/admin/users/{acc['id']}/actions", json={"action": "send_portal_link"}, headers=A).json()["url"]
    assert url.startswith("https://billing.stripe.test/")
    actions = [a["action"] for a in reg.audit]
    assert actions == ["extend_trial", "grant_topup", "cancel_at_period_end", "send_portal_link"]
    assert all(a["account_id"] == acc["id"] and a["admin_email"] == BOSS for a in reg.audit)


def test_codes_create_patch_apply(reg: R.MemoryRegistry, client: TestClient):
    r = client.post("/admin/codes", json={"code": "yearfree", "kind": "free_months", "value": 12}, headers=A)
    assert r.status_code == 201 and r.json()["code"] == "YEARFREE" and r.json()["stripe_coupon_id"] is None
    r = client.post("/admin/codes", json={"code": "LAUNCH20", "kind": "percent", "value": 20}, headers=A)
    assert r.json()["stripe_coupon_id"].startswith("coupon_fake")
    assert (
        client.post("/admin/codes", json={"code": "LAUNCH20", "kind": "percent", "value": 20}, headers=A).status_code
        == 409
    )
    assert (
        client.post("/admin/codes", json={"code": "BIG", "kind": "percent", "value": 150}, headers=A).status_code == 400
    )
    assert (
        client.post("/admin/codes", json={"code": "x y", "kind": "percent", "value": 5}, headers=A).status_code == 400
    )
    r = client.patch("/admin/codes/launch20", json={"active": False}, headers=A)
    assert r.status_code == 200 and r.json()["active"] is False
    assert [c["code"] for c in client.get("/admin/codes", headers=A).json()] == ["LAUNCH20", "YEARFREE"]
    acc = _user(client, reg)
    r = client.post(f"/admin/users/{acc['id']}/actions", json={"action": "apply_code", "code": "YEARFREE"}, headers=A)
    assert r.status_code == 200 and r.json()["account"]["status"] == "comped"
    assert [a["action"] for a in reg.audit] == ["create_code", "create_code", "update_code", "apply_code"]


def test_plans_patch_validates_limits_and_makes_new_prices(reg: R.MemoryRegistry, client: TestClient):
    assert client.patch("/admin/plans/starter", json={"limits": {"docs": -5}}, headers=A).status_code == 400
    r = client.patch("/admin/plans/starter", json={"limits": {"docs": 75}}, headers=A)
    assert r.status_code == 200 and r.json()["limits"]["docs"] == 75 and r.json()["limits"]["ask"] == 100
    assert client.get("/plans").json()[0]["limits"]["docs"] == 75  # live without a deploy
    r = client.patch("/admin/plans/starter", json={"price_month_pence": 1200}, headers=A)
    assert r.json()["stripe_price_month"].startswith("price_fake")
    price = next(f for m, p, f in fakes.CALLS if p == "/v1/prices")
    assert (
        price["unit_amount"] == "1200"
        and price["tax_behavior"] == "exclusive"
        and price["recurring[interval]"] == "month"
    )
    r = client.post("/admin/plans/sync-stripe", headers=A)
    assert set(r.json()["created"]) == {"starter", "comprehensive", "ultimate"}
    assert all(p["stripe_price_month"] and p["stripe_price_year"] for p in reg.plans.values())
    assert [a["action"] for a in reg.audit] == ["update_plan", "update_plan", "sync_prices"]


def test_audit_listing(reg: R.MemoryRegistry, client: TestClient):
    acc = _user(client, reg)
    client.patch(f"/admin/users/{acc['id']}", json={"notes": "n"}, headers=A)
    client.patch("/admin/plans/starter", json={"active": True}, headers=A)
    assert client.get("/admin/audit", headers=A).json()["total"] == 2
    assert client.get(f"/admin/audit?account_id={acc['id']}", headers=A).json()["total"] == 1


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


def test_events_are_stored_with_safe_props(reg: R.MemoryRegistry, client: TestClient):
    r = client.post(
        "/events",
        json={
            "name": "page_view",
            "props": {"page": "/review", "count": 3, "ok": True},
            "app": "web",
            "version": "1.2",
        },
        headers=H,
    )
    assert r.status_code == 202
    ev = reg.events[-1]
    assert ev["name"] == "page_view" and ev["props"] == {"page": "/review", "count": 3, "ok": True}
    assert ev["app"] == "web" and ev["account_id"]


@pytest.mark.parametrize(
    "props",
    [
        {"email": "sam@example.co.uk"},
        {"amount": 1234},
        {"supplier": "acme"},
        {"page": "/contacts/sam@example.co.uk"},
        {"page": "/Review Page"},
        {"feature": "£12.50"},
        {"feature": "Acme Ltd"},
        {"count": 1.5},
        {"count": "3"},
        {"ok": "yes"},
        {"plan": "gold"},
        {f"k{i}": 1 for i in range(11)},
    ],
)
def test_event_props_outside_the_rules_are_refused(props: dict, reg: R.MemoryRegistry, client: TestClient):
    r = client.post("/events", json={"name": "clicked", "props": props}, headers=H)
    assert r.status_code == 422
    assert all(e["name"] != "clicked" for e in reg.events)


def test_server_event_names_cannot_be_sent(reg: R.MemoryRegistry, client: TestClient):
    for name in ("signup", "subscription_active", "api_error", "Bad-Name", "x"):
        assert client.post("/events", json={"name": name}, headers=H).status_code == 422


def test_opt_out_drops_events_silently(reg: R.MemoryRegistry, client: TestClient):
    r = client.patch("/account", json={"analytics_opt_out": True}, headers=H)
    assert r.status_code == 200 and r.json()["analytics_opt_out"] is True
    before = len(reg.events)
    assert client.post("/events", json={"name": "page_view", "props": {"page": "/"}}, headers=H).status_code == 202
    assert len(reg.events) == before
    # server-side events respect it too
    acc = next(iter(reg.accounts.values()))
    S.forget()
    import asyncio

    asyncio.run(S.emit(reg, acc, "proposal_approved", {}))
    assert len(reg.events) == before


def test_events_are_rate_limited(reg: R.MemoryRegistry, client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics, "EVENTS_LIMITER", TokenBucket(2))
    codes = [client.post("/events", json={"name": "page_view"}, headers=H).status_code for _ in range(4)]
    assert codes[:2] == [202, 202] and codes[-1] == 429


def test_events_in_a_batch(reg: R.MemoryRegistry, client: TestClient, monkeypatch: pytest.MonkeyPatch):
    ev = lambda name, **props: {"name": name, "props": props, "app": "web", "version": "1.2"}  # noqa: E731
    batch = [ev("page_view", page="/review"), ev("signup"), ev("upgrade_click", plan="starter", interval="year")]
    r = client.post("/events", json={"events": batch}, headers=H)
    assert r.status_code == 202 and r.json() == {"accepted": 2, "dropped": 1}  # a server-only name is dropped alone
    assert [e["name"] for e in reg.events[-2:]] == ["page_view", "upgrade_click"]
    assert client.post("/events", json={"events": []}, headers=H).status_code == 422
    assert client.post("/events", json={"events": [ev("page_view")] * 21}, headers=H).status_code == 422
    assert client.post("/events", json={"events": batch, "name": "x"}, headers=H).status_code == 422
    # the rate limit counts events, not requests
    monkeypatch.setattr(analytics, "EVENTS_LIMITER", TokenBucket(3))
    assert client.post("/events", json={"events": [ev("page_view")] * 3}, headers=H).status_code == 202
    assert client.post("/events", json={"events": [ev("page_view")]}, headers=H).status_code == 429
    # opted out: taken and dropped
    monkeypatch.setattr(analytics, "EVENTS_LIMITER", TokenBucket(100))
    client.patch("/account", json={"analytics_opt_out": True}, headers=H)
    before = len(reg.events)
    r = client.post("/events", json={"events": [ev("page_view")]}, headers=H)
    assert r.json() == {"accepted": 0, "dropped": 1} and len(reg.events) == before


def test_events_need_a_sign_in(reg: R.MemoryRegistry, client: TestClient):
    assert client.post("/events", json={"name": "page_view"}).status_code == 401


def test_server_events_from_routes(reg: R.MemoryRegistry, client: TestClient):
    from app.main import app
    from app.routes_books import get_books

    assert middleware.match(middleware.EVENTS, "POST", "/books/proposals/p1/approve") == ["proposal_approved"]
    assert middleware.match(middleware.EVENTS, "GET", "/exports/vat-return/file") == ["vat_export"]
    assert middleware.match(middleware.EVENTS, "GET", "/books/self-employment/reports/sa103") == ["itsa_export"]
    assert middleware.match(middleware.EVENTS, "POST", "/books/ebay/sync") == ["ebay_sync"]
    assert middleware.match(middleware.EVENTS, "POST", "/books/bankfeeds/sync") == ["bank_synced"]

    from accnomos_connectors import FakeStorageProvider
    from app.books import Books

    async def over_books() -> Books:
        return Books(FakeStorageProvider())

    app.dependency_overrides[get_books] = over_books
    try:
        assert client.get("/books/self-employment/reports/sa103", headers=H).status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert "itsa_export" in [e["name"] for e in reg.events]


def test_analytics_report(reg: R.MemoryRegistry, client: TestClient):
    acc = _user(client, reg)
    for name in ("document_scanned", "proposal_approved", "ask", "ask"):
        reg.events.append({"id": 0, "at": datetime.now(UTC), "account_id": acc["id"], "name": name, "props": {}})
    reg.events.append(
        {
            "id": 0,
            "at": datetime.now(UTC),
            "account_id": None,
            "name": "api_error",
            "props": {"route": "/x", "method": "GET"},
        }
    )
    out = client.get("/admin/analytics", headers=A).json()
    assert out["funnel"] == {"signed_up": 1, "first_document": 1, "first_approval": 1}
    assert out["features"]["ask"] == 2 and out["features"]["document_scanned"] == 1
    assert out["daily_active"][-1]["count"] == 1 and len(out["daily_active"]) == 30
    assert out["errors_by_route"] == [{"route": "GET /x", "count": 1}]
    assert set(out) >= {"trial_conversion", "churn"}
    assert client.get("/admin/analytics?from=2026-11-10&to=2026-11-01", headers=A).status_code == 400


async def test_api_errors_are_recorded_by_route_template(reg: R.MemoryRegistry):
    async def boom(request):
        raise RuntimeError("secret detail sam@example.co.uk")

    async def bad_gateway(request):
        from starlette.responses import JSONResponse

        return JSONResponse({"detail": "x"}, status_code=502)

    inner = Starlette(routes=[Route("/things/{thing_id}", boom), Route("/up/{x}", bad_gateway)])
    client = TestClient(middleware.BillingMiddleware(inner), raise_server_exceptions=False)
    client.get("/things/INV-123456")
    client.get("/up/1")
    errors = [e for e in reg.events if e["name"] == "api_error"]
    assert [e["props"]["route"] for e in errors] == ["/things/{thing_id}", "/up/{x}"]
    assert errors[0]["account_id"] is None and "sam@" not in str(errors)


# --------------------------------------------------------------------------- #
# Bug reports
# --------------------------------------------------------------------------- #


def test_bug_report_without_and_with_a_screenshot(reg: R.MemoryRegistry, client: TestClient):
    r = client.post(
        "/bug-reports",
        json={"message": "The Review page froze", "page": "/review", "app": "web", "version": "1.2", "ua": "Firefox"},
        headers=H,
    )
    assert r.status_code == 201
    rep = reg.bug_reports[r.json()["id"]]
    assert rep["email"] == USER and rep["status"] == "new" and rep["screenshot_path"] is None
    shot = "data:image/png;base64," + base64.b64encode(PNG).decode()
    r = client.post("/bug-reports", json={"message": "Again", "screenshot_b64": shot}, headers=H)
    rep = reg.bug_reports[r.json()["id"]]
    assert rep["screenshot_path"].endswith(".png") and reg.screenshots[rep["screenshot_path"]] == PNG
    # admin triage
    rows = client.get("/admin/bug-reports?status=new", headers=A).json()
    assert rows["total"] == 2
    r = client.patch(f"/admin/bug-reports/{rep['id']}", json={"status": "fixed", "admin_notes": "done"}, headers=A)
    assert r.json()["status"] == "fixed" and r.json()["closed_at"]
    assert reg.audit[-1]["action"] == "update_bug_report"
    assert client.get(f"/admin/bug-reports/{rep['id']}/screenshot", headers=A).json()["url"].startswith("memory://")


def test_bug_report_screenshot_checks(reg: R.MemoryRegistry, client: TestClient):
    big = base64.b64encode(PNG + b"\x00" * (2 * 1024 * 1024)).decode()
    assert client.post("/bug-reports", json={"message": "m", "screenshot_b64": big}, headers=H).status_code == 413
    gif = base64.b64encode(b"GIF89a" + b"\x00" * 20).decode()
    assert client.post("/bug-reports", json={"message": "m", "screenshot_b64": gif}, headers=H).status_code == 415
    assert client.post("/bug-reports", json={"message": "m", "screenshot_b64": "%%%"}, headers=H).status_code == 422
    reg.storage_configured = False
    r = client.post("/bug-reports", json={"message": "m", "screenshot_b64": base64.b64encode(PNG).decode()}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "screenshots_unavailable"
    assert client.post("/bug-reports", json={"message": "m"}, headers=H).status_code == 201
    assert client.post("/bug-reports", json={"message": ""}, headers=H).status_code == 422


# --------------------------------------------------------------------------- #
# Sentry scrubbing
# --------------------------------------------------------------------------- #


def test_sentry_scrubber_strips_request_and_redacts_patterns():
    event = {
        "request": {
            "url": "https://api.accnomos.com/invoices?customer=acme",
            "method": "POST",
            "headers": {"X-Graph-Token": "eyJabcdefgh.ijklmnop.qrs"},
            "cookies": {"s": "1"},
            "data": {"amount": "£1,234.56"},
            "query_string": "customer=acme",
        },
        "user": {"email": "sam@example.co.uk"},
        "message": "Paid £1,234.56 (GBP 99) to sam@example.co.uk, VAT GB 123 4567 89, Bearer abcdefghijkl, 12.50",
        "exception": {
            "values": [
                {"value": "key " + "sk_" + "live_abcdefghijklmnop", "stacktrace": {"frames": [{"vars": {"x": 1}}]}}
            ]
        },
    }
    out = sentry.scrub_event(event)
    assert out["request"] == {"method": "POST", "url": "https://api.accnomos.com/invoices"}
    assert "user" not in out
    text = str(out)
    for leak in ("1,234.56", "GBP 99", "sam@example", "123 4567 89", "abcdefghijkl", "12.50", "sk_live", "vars"):
        assert leak not in text, leak
    assert "[redacted]" in out["message"]


def test_sentry_off_without_dsn(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert sentry.init() is False
