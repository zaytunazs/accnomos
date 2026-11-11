"""The billing/admin API's JSON shapes, pinned in docs/billing/api_shapes.json.

Every billing, account, analytics and admin endpoint the web and Android apps read is called here against the
in-memory registry and the Stripe fake, and the keys of each answer (with their JSON types, nested) are compared with
the snapshot. The web unit test `apps/web/tests/unit/api-shapes.test.ts` checks the UI's types and readers against the
same file, so a key renamed on either side fails CI.

After a deliberate change to a response, regenerate the snapshot and commit it with the change:

    UPDATE_API_SHAPES=1 uv run pytest services/runtime/tests/test_billing_contract.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.billing import analytics, fakes, stripe_api
from app.billing import plans as P
from app.billing import registry as R
from app.billing import routes as billing_routes
from app.billing import service as S
from app.security import TokenBucket

SNAPSHOT = Path(__file__).resolve().parents[3] / "docs" / "billing" / "api_shapes.json"
USER = "sam@example.co.uk"
BOSS = "boss@accnomos.example"
H = {"X-Graph-Token": "tok", "X-User": USER}
A = {"X-Graph-Token": "tok", "X-User": BOSS}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def shape(value: Any) -> Any:
    """The keys of `value`, nested, with each leaf's JSON type. A list is described by the union of its items."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [merge([shape(v) for v in value])] if value else []
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return "string"


def merge(shapes: list[Any]) -> Any:
    structured = [s for s in shapes if s != "null"]
    if structured and len(structured) < len(shapes) and not any(isinstance(s, str) for s in structured):
        shapes = structured  # a list or object that is sometimes null: its keys are what matters
    if all(isinstance(s, dict) for s in shapes):
        keys = sorted({k for s in shapes for k in s})
        return {k: merge([s[k] for s in shapes if k in s]) for k in keys}
    if all(isinstance(s, list) for s in shapes):
        inner = [s[0] for s in shapes if s]
        return [merge(inner)] if inner else []
    leaves = sorted({s if isinstance(s, str) else json.dumps(s, sort_keys=True) for s in shapes})
    return "|".join(leaves)


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch):
    r = R.MemoryRegistry(storage=True)
    R.install(r)
    S.forget()
    fakes.reset()
    fakes.install()
    monkeypatch.setenv("ADMIN_EMAILS", BOSS)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_contract_123")
    monkeypatch.setenv("PAYMENTS_PROVIDER", "stripe")
    monkeypatch.setenv("STRIPE_PRICE_STARTER_MONTH", "price_starter_month")
    monkeypatch.setenv("ACCNOMOS_WEB_URL", "https://app.accnomos.example")
    monkeypatch.delenv("BILLING_RETURN_URL", raising=False)

    async def gauges(_request) -> dict:
        return {"bank_feeds": 1, "marketplaces": 0, "autopilot_rules": 2, "users": 1}

    monkeypatch.setattr(billing_routes, "read_gauges", gauges)
    monkeypatch.setattr(analytics, "EVENTS_LIMITER", TokenBucket(1000))
    monkeypatch.setattr(analytics, "BUGS_LIMITER", TokenBucket(1000))
    yield r
    R.install(None)
    S.forget()
    stripe_api.TRANSPORT = None


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def ok(r, status: int = 200) -> Any:
    assert r.status_code == status, (r.request.method, r.request.url.path, r.status_code, r.text)
    return r.json()


def test_api_shapes_match_the_snapshot(reg: R.MemoryRegistry, client: TestClient, monkeypatch: pytest.MonkeyPatch):
    out: dict[str, Any] = {}

    # ---- public and customer -------------------------------------------------------------------------------------
    out["GET /plans"] = ok(client.get("/plans"))
    out["GET /account"] = ok(client.get("/account", headers=H))
    acc_id = out["GET /account"]["id"]
    out["PATCH /account"] = ok(client.patch("/account", json={"analytics_opt_out": False}, headers=H))
    ok(client.post("/admin/codes", json={"code": "YEARFREE", "kind": "free_months", "value": 12}, headers=A), 201)
    ok(client.post("/admin/codes", json={"code": "WELCOME20", "kind": "percent", "value": 20}, headers=A), 201)
    out["POST /billing/redeem"] = ok(client.post("/billing/redeem", json={"code": "WELCOME20"}, headers=H))
    out["POST /billing/checkout"] = ok(
        client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H)
    )
    out["POST /billing/portal"] = ok(client.post("/billing/portal", headers=H))
    out["POST /billing/topup"] = ok(client.post("/billing/topup", headers=H))
    event = {"name": "page_view", "props": {"page": "/review"}, "app": "web", "version": "1.2"}
    single = client.post("/events", json=event, headers=H)
    assert single.status_code == 202 and single.content == b""
    out["POST /events (batch)"] = ok(client.post("/events", json={"events": [event, event]}, headers=H), 202)
    screenshot = base64.b64encode(PNG).decode()
    bug = {
        "message": "It broke",
        "page": "/vat",
        "app": "web",
        "version": "1.2",
        "ua": "UA",
        "screenshot_b64": screenshot,
    }
    out["POST /bug-reports"] = ok(client.post("/bug-reports", json=bug, headers=H), 201)
    bug_id = out["POST /bug-reports"]["id"]

    # ---- 402: a used-up allowance, then a read-only account --------------------------------------------------------
    reg.usage[(acc_id, P.month_start())] = {**R.empty_usage(acc_id, P.month_start()), "ask": 500}
    out["402 plan_limit"] = ok(client.post("/books/ask", json={"question": "What did I spend?"}, headers=H), 402)

    # ---- admin -----------------------------------------------------------------------------------------------------
    reg.accounts[acc_id].update(stripe_subscription_id="sub_fake1", status="active", billing_interval="month")
    S.forget()
    soon = datetime.now(UTC) + timedelta(days=3)
    lee = {"email": "lee@example.co.uk", "auth_kind": "google", "auth_subject": "g-lee"}
    asyncio.run(reg.create_account({**lee, "plan_code": "comprehensive", "status": "trialing", "trial_ends_at": soon}))
    asyncio.run(S.emit(reg, None, "api_error", {"route": "/books/scan", "method": "POST", "status": 500}))
    out["GET /admin/metrics"] = ok(client.get("/admin/metrics", headers=A))
    out["GET /admin/users"] = ok(client.get("/admin/users?q=sam&page=1", headers=A))
    out["PATCH /admin/users/{id}"] = ok(client.patch(f"/admin/users/{acc_id}", json={"notes": "Called"}, headers=A))
    out["POST /admin/users/{id}/actions (extend_trial)"] = ok(
        client.post(f"/admin/users/{acc_id}/actions", json={"action": "extend_trial", "days": 7}, headers=A)
    )
    out["POST /admin/users/{id}/actions (send_portal_link)"] = ok(
        client.post(f"/admin/users/{acc_id}/actions", json={"action": "send_portal_link"}, headers=A)
    )
    reg.accounts[acc_id].update(stripe_subscription_id=None, status="trialing")
    S.forget()
    out["POST /admin/users/{id}/actions (apply_code)"] = ok(
        client.post(f"/admin/users/{acc_id}/actions", json={"action": "apply_code", "code": "YEARFREE"}, headers=A)
    )
    reg.accounts[acc_id].update(stripe_subscription_id="sub_fake1")
    out["GET /admin/users/{id}"] = ok(client.get(f"/admin/users/{acc_id}", headers=A))
    out["POST /admin/codes"] = ok(
        client.post(
            "/admin/codes",
            json={
                "code": "SPRING",
                "kind": "fixed",
                "value": 500,
                "plan_codes": ["starter"],
                "max_redemptions": 10,
                "expires_at": "2027-01-31T23:59:59Z",
                "duration_months": 3,
            },
            headers=A,
        ),
        201,
    )
    out["GET /admin/codes"] = ok(client.get("/admin/codes", headers=A))
    out["PATCH /admin/codes/{code}"] = ok(client.patch("/admin/codes/SPRING", json={"active": False}, headers=A))
    out["GET /admin/plans"] = ok(client.get("/admin/plans", headers=A))
    out["PATCH /admin/plans/{code}"] = ok(
        client.patch("/admin/plans/starter", json={"limits": {"docs": 60}, "active": True}, headers=A)
    )
    out["GET /admin/audit"] = ok(client.get(f"/admin/audit?account_id={acc_id}", headers=A))
    out["GET /admin/analytics"] = ok(client.get("/admin/analytics", headers=A))
    out["GET /admin/bug-reports"] = ok(client.get("/admin/bug-reports", headers=A))
    out["PATCH /admin/bug-reports/{id}"] = ok(
        client.patch(f"/admin/bug-reports/{bug_id}", json={"status": "triaged", "admin_notes": "Seen"}, headers=A)
    )
    out["GET /admin/bug-reports/{id}/screenshot"] = ok(client.get(f"/admin/bug-reports/{bug_id}/screenshot", headers=A))

    # ---- read-only, then billing switched off ------------------------------------------------------------------------
    reg.accounts[acc_id].update(status="trial_ended", stripe_subscription_id=None, comp_until=None)
    S.forget()
    out["402 read_only"] = ok(client.post("/books/ask", json={"question": "What did I spend?"}, headers=H), 402)
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "ACCNOMOS_TEST_MODE"):
        monkeypatch.delenv(k, raising=False)
    R.install(None)
    out["GET /account (billing off)"] = ok(client.get("/account", headers=H))

    shapes = {name: shape(body) for name, body in sorted(out.items())}
    if os.getenv("UPDATE_API_SHAPES") == "1":
        SNAPSHOT.write_text(json.dumps(shapes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert SNAPSHOT.exists(), "docs/billing/api_shapes.json is missing: run with UPDATE_API_SHAPES=1"
    pinned = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for name in sorted(set(pinned) | set(shapes)):
        assert shapes.get(name) == pinned.get(name), (
            f"{name}: the response no longer matches docs/billing/api_shapes.json. If the change is deliberate, "
            "run with UPDATE_API_SHAPES=1, update the web types and readers, and commit both."
        )


def test_shape_of_lists_is_the_union_of_their_items():
    assert shape([{"a": 1}, {"a": None, "b": "x"}]) == [{"a": "null|number", "b": "string"}]
    assert shape({"z": [], "y": True}) == {"y": "boolean", "z": []}
