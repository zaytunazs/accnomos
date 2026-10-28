"""Second security pass (docs/SECURITY.md): invariants over every registered route, so a new router cannot skip them.

* every JSON body forbids unknown fields, and every free-text string in it has a length cap;
* dates in bodies are YYYY-MM-DD only, money is whole pence as an integer.
"""

from __future__ import annotations

import typing
from collections.abc import Iterator
from typing import Any

import pytest
from annotated_types import MaxLen
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from accnomos_connectors import FakeStorageProvider
from app import security
from app.books import Books
from app.invoicing import InvoiceDraft
from app.main import app
from app.routes_books import get_books
from app.validation import Day, Pence

H = {"X-Graph-Token": "graph-token-" + "t" * 20, "X-User": "sam@example.co.uk"}


@pytest.fixture
def books() -> Books:
    return Books(FakeStorageProvider())


@pytest.fixture
def client(books: Books) -> Iterator[TestClient]:
    """The real app over in-memory storage: nothing here reaches Graph."""

    async def fake_books() -> Any:
        yield books

    app.dependency_overrides[get_books] = fake_books
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def routes() -> Iterator[APIRoute]:
    def walk(items: list[Any]) -> Iterator[APIRoute]:
        for r in items:
            if hasattr(r, "original_router"):  # FastAPI keeps included routers as a wrapper
                yield from walk(r.original_router.routes)
            elif isinstance(r, APIRoute):
                yield r

    return walk(app.routes)


def body_models(tp: Any, seen: set[type] | None = None) -> Iterator[type[BaseModel]]:
    seen = set() if seen is None else seen
    if typing.get_origin(tp) is not None:
        for a in typing.get_args(tp):
            yield from body_models(a, seen)
        return
    if isinstance(tp, type) and issubclass(tp, BaseModel) and tp not in seen:
        seen.add(tp)
        yield tp
        for f in tp.model_fields.values():
            yield from body_models(f.annotation, seen)


def all_body_models() -> dict[type[BaseModel], set[str]]:
    out: dict[type[BaseModel], set[str]] = {}
    for r in routes():
        for p in r.dependant.body_params:
            for m in body_models(p.field_info.annotation):
                out.setdefault(m, set()).add(f"{'/'.join(sorted(r.methods))} {r.path}")
    return out


def test_the_walk_sees_the_new_routers():
    paths = {r.path for r in routes()}
    assert {
        "/invoices",
        "/actions/approve",
        "/plan/day/apply",
        "/mail/draft-reply",
        "/todos",
        "/payroll/runs/prepare",
        "/vehicles",
        "/mileage",
        "/jobs",
        "/contacts/{contact_id}",
        "/books/dashboard",
        "/audit",
    } <= paths


def test_every_request_body_forbids_unknown_fields():
    loose = {
        f"{m.__module__}.{m.__qualname__}": sorted(where)
        for m, where in all_body_models().items()
        if m.model_config.get("extra") != "forbid"
    }
    assert loose == {}


def _unbounded_str(tp: Any) -> bool:
    """A `str` somewhere in `tp` without a MaxLen on its own Annotated wrapper (dict keys and Literals excepted)."""
    if tp is str:
        return True
    origin = typing.get_origin(tp)
    if origin is typing.Literal:
        return False
    if origin is typing.Annotated:
        inner, *meta = typing.get_args(tp)
        capped = any(
            isinstance(x, MaxLen) or any(isinstance(y, MaxLen) for y in getattr(x, "metadata", [])) for x in meta
        )
        return False if capped else _unbounded_str(inner)
    if origin is dict:
        return _unbounded_str(typing.get_args(tp)[1])
    return any(_unbounded_str(a) for a in typing.get_args(tp))


def test_every_free_text_field_in_a_body_has_a_length_cap():
    missing = sorted(
        f"{m.__module__}.{m.__qualname__}.{name}"
        for m in all_body_models()
        for name, f in m.model_fields.items()
        if _unbounded_str(f.annotation) and not any(isinstance(x, MaxLen) for x in f.metadata)
    )
    assert missing == []


class _Money(BaseModel):
    day: Day
    pence: Pence


@pytest.mark.parametrize(
    "raw",
    [
        '{"day": 1793059200, "pence": 1}',  # a Unix timestamp
        '{"day": "2026-10-27T00:00:00", "pence": 1}',  # a datetime
        '{"day": "27/10/2026", "pence": 1}',
        '{"day": "2026-02-30", "pence": 1}',  # not a real day
        '{"day": "2026-10-27", "pence": 12.0}',  # float pence
        '{"day": "2026-10-27", "pence": "12"}',
        '{"day": "2026-10-27", "pence": true}',
    ],
)
def test_dates_and_money_are_parsed_strictly(raw: str):
    with pytest.raises(ValidationError):
        _Money.model_validate_json(raw)


def test_strict_dates_and_pence_still_take_the_normal_forms():
    from datetime import date

    assert _Money.model_validate_json('{"day": "2026-10-27", "pence": -5}').day == date(2026, 10, 27)
    assert _Money.model_validate({"day": date(2026, 10, 27), "pence": 0}).pence == 0


@pytest.mark.parametrize(
    "change",
    [
        {"issue_date": 1793059200},
        {"lines": [{"description": "x", "quantity": 1, "unit_price_pence": 1000.5}]},
        {"lines": [{"description": "x", "quantity": 1, "unit_price_pence": "1000"}]},
        {"lines": [{"description": "x" * 301, "quantity": 1, "unit_price_pence": 1000}]},
        {"notes": "x" * 1001},
        {"customer": {"name": "JM Trading", "address": "x" * 1001}},
    ],
)
def test_invoice_drafts_refuse_loose_dates_money_and_long_text(change: dict[str, Any]):
    ok = {
        "customer": {"name": "JM Trading"},
        "lines": [{"description": "Work", "quantity": 1, "unit_price_pence": 1000}],
    }
    InvoiceDraft.model_validate(ok)
    with pytest.raises(ValidationError):
        InvoiceDraft.model_validate({**ok, **change})


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/actions/approve", {"action": {}, "extra": 1}),
        ("post", "/invoices/INV-0001/send", {"confirm": True, "bcc": "x@example.com"}),
        ("post", "/invoices/INV-0001/mark-paid", {"paid_on": "2026-10-27", "amount": 1}),
        ("post", "/plan/day/apply", {"date": "2026-10-27", "plan": [], "force": True}),
        ("put", "/payroll/runs/2026-10", {"lines": [{"staff_id": "a", "hours": 1, "rate_pence": 1, "bonus": 1}]}),
    ],
)
def test_unknown_fields_on_the_new_routes_are_a_422(client: TestClient, method: str, path: str, body: dict[str, Any]):
    r = getattr(client, method)(path, json=body, headers=H)
    assert r.status_code == 422
    assert any(e["type"] == "extra_forbidden" for e in r.json()["detail"])


# --------------------------------------------------------------------------- #
# Outbound: Graph (the connector), allow-listed AI base URLs, Baseten. No URL from a document, email or to-do.
# --------------------------------------------------------------------------- #

APP = __import__("pathlib").Path(__file__).resolve().parents[1] / "app"
NET_MODULES = {"httpx", "requests", "urllib.request", "aiohttp", "socket", "http.client", "urllib3"}
#: The only runtime modules that may import an HTTP library, and what they call.
TALKS_HTTP = {
    "main.py": "/ai/test: the allow-listed AI base URL",
    "ai/ask.py": "cfg.base_url",
    "ai/extract.py": "cfg.base_url",
    "ai/duplicates.py": "cfg.base_url",
    "ai/cis_read.py": "cfg.base_url",
    "ai/crop.py": "cfg.base_url (SAM, key mode)",
    "ai/voice.py": "cfg.base_url",
    "ai/verify.py": "cfg.base_url or BASETEN_BASE",
    "ai/remind.py": "httpx errors only",
    "ai/plan.py": "httpx errors only",
    "ai/triage.py": "httpx errors only",
    "company_lookup.py": "Companies House (CH_BASE constant) and the relay (HMRC_RELAY_URL): server env only",
    "payment_providers.py": "Stripe and PayPal: the bases in StripeConfig/PayPalConfig, from server env only",
    "online_fakes.py": "test fakes: builds httpx.Response objects, sends nothing",
}


def _modules_importing_http() -> set[str]:
    import ast

    found = set()
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(n in NET_MODULES or n.split(".")[0] in {"httpx", "requests", "aiohttp", "urllib3"} for n in names):
                found.add(path.relative_to(APP).as_posix())
    return found


def test_only_known_modules_can_make_http_calls():
    assert _modules_importing_http() == set(TALKS_HTTP)


def test_payment_provider_calls_go_only_to_the_configured_provider_bases():
    """app/payment_providers.py: every request URL starts with a base from StripeConfig/PayPalConfig (server env or
    the documented constants); never a URL a provider, the app or a user sent. Its one client follows no redirect."""
    import ast

    from app.payment_providers import PAYPAL_SANDBOX, PayPalConfig, StripeConfig

    src = (APP / "payment_providers.py").read_text()
    bases = {"self.cfg.connect_base", "self.cfg.api_base", "self.cfg.base"}
    seen = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.FormattedValue):
            head = ast.unparse(node.values[0].value)
            if head.startswith("self.cfg."):
                assert head in bases, head
                seen += 1
        if isinstance(node, ast.Call) and ast.unparse(node.func) in ("httpx.AsyncClient", "httpx.Client"):
            assert any(k.arg == "follow_redirects" and ast.unparse(k.value) == "False" for k in node.keywords)
    assert seen >= 8
    cfg = StripeConfig(secret_key="sk_test_x", client_id="ca_x", redirect_uri="https://x/cb")
    assert (cfg.api_base, cfg.connect_base) == ("https://api.stripe.com", "https://connect.stripe.com")
    assert PayPalConfig("a", "b", "c", "d", "https://x/cb").base == PAYPAL_SANDBOX == "https://api-m.sandbox.paypal.com"


def test_every_runtime_http_call_goes_to_an_allow_listed_base_and_follows_no_redirects():
    """Request URLs are f"{<base_url>}/..." where the base is the AI config (allow-listed in app/ai/config.py),
    the verifier backend (that config, or the BASETEN_BASE constant) or /ai/test's checked `base`; never a URL
    read from a document, an email, a to-do or a model reply. And no client follows a redirect off that host."""
    import ast

    calls = 0
    for rel in TALKS_HTTP:
        for node in ast.walk(ast.parse((APP / rel).read_text())):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in ("httpx.AsyncClient", "httpx.Client"):
                assert not any(
                    k.arg == "follow_redirects" and ast.unparse(k.value) != "False" for k in node.keywords
                ), rel
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "post")
                and ast.unparse(node.func.value) in ("client", "http")
            ):
                calls += 1
                url = node.args[0]
                assert isinstance(url, ast.JoinedStr) and isinstance(url.values[0], ast.FormattedValue), (
                    f"{rel}:{node.lineno}"
                )
                assert ast.unparse(url.values[0].value) in (
                    "cfg.base_url",
                    "be.base_url",
                    "base",
                    "cfg.base_url.rstrip('/')",
                ), f"{rel}:{node.lineno} {ast.unparse(url)}"
    assert calls >= 9


def test_the_verifier_only_leaves_for_baseten_or_the_users_own_ai():
    from app.ai.config import AiConfig
    from app.ai.verify import BASETEN_BASE, select_backend

    assert BASETEN_BASE.startswith("https://inference.baseten.co")
    local = AiConfig(mode="local", base_url="http://127.0.0.1:11434", model="m")
    assert select_backend(local, {"BASETEN_API_KEY": "k"}).base_url == local.base_url  # type: ignore[union-attr]
    key = AiConfig(mode="key", base_url="https://api.meta.ai/v1", model="m", api_key="k")
    assert select_backend(key, {"BASETEN_API_KEY": "b"}).base_url == BASETEN_BASE  # type: ignore[union-attr]
    assert select_backend(key, {}).base_url == key.base_url  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Test mode is inert unless ACCNOMOS_TEST_MODE=1
# --------------------------------------------------------------------------- #

_PROBE = r"""
import json
from fastapi.testclient import TestClient
from app.main import app
from app import security

def walk(items):
    for r in items:
        if hasattr(r, "original_router"):
            yield from walk(r.original_router.routes)
        else:
            yield r

c = TestClient(app)
pre = c.options("/books/summary", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
                                           "Access-Control-Request-Headers": "x-test-tenant"})
print(json.dumps({
    "test_paths": sorted(p for r in walk(app.routes) if (p := getattr(r, "path", "")).startswith("/__test")),
    "middleware": [m.cls.__name__ for m in app.user_middleware],
    "state": c.get("/__test/state").status_code,
    "reset": c.post("/__test/reset").status_code,
    "graph": c.get("/__test/graph/v1.0/me/drive/special/approot").status_code,
    "tenant_header_allowed": "x-test-tenant" in pre.headers.get("access-control-allow-headers", "").lower(),
    "health_test_mode": "test_mode" in c.get("/health").json(),
    "unlimited": list(security.UNLIMITED_PREFIXES),
}))
"""


@pytest.mark.parametrize("flag", [None, "0", "true", ""])
def test_without_the_flag_no_test_route_header_or_middleware_exists(flag: str | None):
    """Imported fresh, the way the Docker image starts it (ACCNOMOS_TEST_MODE=0) and with the variable unset."""
    import json
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.startswith("ACCNOMOS_")}
    env.update({"CORS_ORIGINS": "http://localhost:3000", **({"ACCNOMOS_TEST_MODE": flag} if flag is not None else {})})
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=APP.parent, env=env, capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == {
        "test_paths": [],
        "middleware": got["middleware"],
        "state": 404,
        "reset": 404,
        "graph": 404,
        "tenant_header_allowed": False,
        "health_test_mode": False,
        "unlimited": [],
    }
    assert "TenantMiddleware" not in got["middleware"]


def test_cors_allows_every_method_a_route_uses_and_no_other():
    """The web app edits vehicles and mileage with PATCH; a method missing here fails only in the browser."""
    used = {m for r in routes() for m in r.methods} - {"HEAD", "OPTIONS"}
    c = TestClient(app)
    for method in sorted(used | {"TRACE", "CONNECT"}):
        r = c.options(
            "/vehicles/abc", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method}
        )
        assert (r.status_code == 200) == (method in used), method


def test_the_test_mode_web_build_is_never_published():
    root = APP.parents[2] / ".github/workflows"
    deploy, e2e = (root / "deploy-web.yml").read_text(), (root / "ci.yml").read_text()
    assert 'NEXT_PUBLIC_TEST_MODE: ""' in deploy and "publish_dir: apps/web/out\n" in deploy
    guard, publish = deploy.index("Refuse to publish a test-mode build"), deploy.index("publish_dir:")
    assert guard < publish and "__test/(graph|ai)" in deploy[guard:publish]
    assert "permissions:\n  contents: read" in e2e and "pnpm run e2e:build" in e2e
    assert not any(word in e2e for word in ("secrets.", "gh-pages", "publish_dir", "contents: write", "docker push"))
    build = (APP.parents[2] / "apps/web/e2e/build.mjs").read_text()
    assert "out-e2e" in build and 'NEXT_PUBLIC_TEST_MODE: "1"' in build


# --------------------------------------------------------------------------- #
# Upload caps and rate limits on the logo route
# --------------------------------------------------------------------------- #


def test_logo_route_has_its_own_small_body_cap():
    from app.security import JSON_LIMIT, SMALL_UPLOADS, body_limit

    assert body_limit("/invoices/profile/logo") == SMALL_UPLOADS["/invoices/profile/logo"] == 2 * 1024 * 1024
    assert body_limit("/invoices/profile") == JSON_LIMIT


def test_logo_upload_over_the_cap_is_refused_before_the_route_reads_it(client: TestClient, books: Books):
    big = {"file": ("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * (3 * 1024 * 1024), "image/png")}
    r = client.post("/invoices/profile/logo", files=big, headers=H)
    assert r.status_code == 413 and "2 MB" in r.json()["detail"]
    assert not books.storage.files


def test_logo_upload_counts_against_the_rate_limit():
    from fastapi import FastAPI

    from app.security import SecurityMiddleware, TokenBucket

    tiny = FastAPI()
    tiny.add_middleware(SecurityMiddleware, limiter=TokenBucket(2))

    @tiny.post("/invoices/profile/logo")
    async def logo() -> dict:
        return {}

    c = TestClient(tiny)
    codes = [c.post("/invoices/profile/logo", content=b"x").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# --------------------------------------------------------------------------- #
# Identity: writes need X-User; audit lines say who (user:) or what (agent:)
# --------------------------------------------------------------------------- #

#: Write-method routes that do not take X-User, and why. Anything else that writes must depend on require_user.
NO_USER_NEEDED = {
    "POST /ai/test": "pings the AI the caller names (allow-listed); writes nothing",
    "POST /extract": "reads one document; writes nothing",
    "POST /books/scan": "the extractor agent files the inbox; audited as agent:extractor / agent:autopilot",
    "POST /books/rebuild": "rebuilds Books.xlsx from the files already there; no new facts",
    "POST /books/ask": "answers, or proposes a signed action that only /actions/approve (X-User) runs",
    "POST /books/ask/voice": "as /books/ask",
    "POST /mail/scan": (
        "the intake agent copies receipts to 00 Inbox; audited as agent:intake (user: when X-User is sent)"
    ),
    "POST /mail/triage": "reads previews; one counts-only audit line as agent:triage (user: when X-User is sent)",
    "POST /jobs/{job_id}/invoice-lines": "proposes lines; marks nothing",
    "POST /invoices/{number}/pdf": "renders the PDF of an invoice the user already wrote; no new facts",
    "POST /credit-notes/{number}/pdf": "renders the PDF of a credit note the user already made; no new facts",
    "POST /invoices/{number}/reminder-draft": "drafts text for the user to read; sends and writes nothing",
    "POST /plan/day": "proposes a day; writes nothing (apply needs X-User)",
    "POST /files/archive/preview": "lists what archiving would move; writes nothing (archive needs X-User)",
    "POST /backups/restore/preview": "compares a backup with the books; writes nothing (restore needs X-User)",
    "POST /public/early-access": "public sign-up to the operator's launch list (off unless EARLY_ACCESS_ENABLED=1)",
}


def _depends_on(route: APIRoute, call: Any) -> bool:
    def calls(d: Any) -> Iterator[Any]:
        for sub in d.dependencies:
            yield sub.call
            yield from calls(sub)

    return call in set(calls(route.dependant))


def test_every_write_route_needs_x_user_or_is_listed_with_a_reason():
    from app.routes_books import require_user

    unlisted, stale = [], set(NO_USER_NEEDED)
    for r in routes():
        for method in sorted(r.methods & {"POST", "PUT", "PATCH", "DELETE"}):
            key = f"{method} {r.path}"
            if _depends_on(r, require_user):
                assert key not in NO_USER_NEEDED, f"{key} takes X-User now; drop it from NO_USER_NEEDED"
            elif key in NO_USER_NEEDED:
                stale.discard(key)
            else:
                unlisted.append(key)
    assert unlisted == []
    assert stale == set(), "NO_USER_NEEDED lists routes that no longer exist"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/actions/approve", {"action": {}}),
        (
            "post",
            "/invoices",
            {"customer": {"name": "x"}, "lines": [{"description": "x", "quantity": 1, "unit_price_pence": 1}]},
        ),
        ("post", "/invoices/INV-0001/send", {"confirm": True}),
        ("post", "/plan/day/apply", {"date": "2026-10-27", "plan": []}),
        ("post", "/mail/draft-reply", {"message_id": "AAMk", "body": "Thanks"}),
        ("post", "/todos", {"text": "Ring Hartley"}),
        ("post", "/payroll/runs/prepare", {"period": "2026-10"}),
        ("post", "/vehicles", {"name": "Van", "kind": "van", "owned_by": "business"}),
    ],
)
def test_writes_without_x_user_are_refused(client: TestClient, method: str, path: str, body: dict[str, Any]):
    r = getattr(client, method)(path, json=body, headers={"X-Graph-Token": H["X-Graph-Token"]})
    assert r.status_code in (400, 422)
    assert "x-user" in r.text.lower()


_ACTOR_PREFIXES = ('f"user:', "f'user:", 'f"agent:', "f'agent:", '"agent:', "'agent:")


def _actor_ok(node: Any) -> bool:
    import ast

    if isinstance(node, ast.IfExp):
        return _actor_ok(node.body) and _actor_ok(node.orelse)
    src = ast.unparse(node)
    return src.startswith(_ACTOR_PREFIXES) or src.endswith("ACTOR") or src.startswith("_actor(") or src == "actor"


def test_every_audit_actor_is_user_or_agent():
    """`books.audit(actor, ...)` and `rebuild_safely(actor)`: an f"user:..." / "agent:..." string, an ...ACTOR
    constant (all "agent:..."), `_actor(user)` or a parameter named `actor`; never a bare e-mail address."""
    import ast
    from pathlib import Path

    bad = []
    for path in sorted((Path(__file__).resolve().parents[1] / "app").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.args
                and node.func.attr in ("audit", "audit_autopilot", "rebuild_safely")
                and not _actor_ok(node.args[0])
            ):
                bad.append(f"{path.name}:{node.lineno} {node.func.attr}({ast.unparse(node.args[0])})")
    assert bad == []


# Routes that answer without a Graph token, each with its reason. Every other route reaches the user's books, mail or
# the server's look-up keys only through `X-Graph-Token` (get_books and its siblings) and must answer 401 without it.
PUBLIC_ROUTES = {
    "GET /health": "liveness for the container healthcheck; no user data",
    "POST /ai/test": "Settings' Test connection, with the caller's own key or local agent (docs/SECURITY.md)",
    "POST /extract": "Android reads a receipt before sign-in; returns a proposal, touches no books",
    "GET /lookup/status": "says only whether look-ups are configured",
    "GET /books/bank/coding-options": "the fixed chart of accounts and VAT codes; nothing from the user's books",
    "POST /public/early-access": "the operator's launch list sign-up, before anyone has an account",
    "GET /cis/reverse-charge": "fixed text from HMRC's reverse charge guidance; nothing from the user's books",
    "GET /payments/online/stripe/callback": (
        "Stripe's browser redirect; only checks the signed one-time state and hands back to Settings, touches no books"
    ),
    "GET /payments/online/paypal/callback": (
        "PayPal's browser redirect; only checks the signed one-time state and hands back to Settings, touches no books"
    ),
}


def test_every_route_but_the_public_ones_needs_a_graph_token() -> None:
    """No header at all, and an empty one: 401 before any body or path validation, on every non-public route. The
    real dependencies (no overrides), so nothing reaches Graph: a request without a token never gets that far."""
    client = TestClient(app)
    seen: set[str] = set()
    for r in routes():
        for method in sorted(r.methods):
            key = f"{method} {r.path}"
            seen.add(key)
            if key in PUBLIC_ROUTES:
                continue
            path = r.path
            for name in r.param_convertors:
                path = path.replace("{" + name + "}", "0" * 32)
            if security.LIMITER:  # ~280 requests from one address: not what this test is about
                security.LIMITER.reset()
            for headers in ({}, {"X-Graph-Token": ""}):
                resp = client.request(method, path, headers={**headers, "X-User": H["X-User"]}, json={})
                assert resp.status_code == 401, (key, headers, resp.status_code, resp.text)
    assert set(PUBLIC_ROUTES) <= seen  # the list names real routes
