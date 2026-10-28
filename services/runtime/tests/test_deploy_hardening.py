"""Static checks on deploy/ and the static site's .htaccess (deploy/README.md lists what each one guards)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy"
HEADERS = ("Strict-Transport-Security", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy")


def test_edge_nginx_sends_security_headers_everywhere():
    conf = (DEPLOY / "nginx.conf").read_text()
    for h in HEADERS:
        assert re.search(rf'^\s*add_header {h} "[^"]+" always;', conf, re.M), h
    # add_header inside a location would drop every server-level header for that location
    for block in re.findall(r"location[^{]*\{([^}]*)\}", conf):
        assert "add_header" not in block
    assert "server_tokens off;" in conf


def test_edge_nginx_body_caps_and_client_ip():
    conf = (DEPLOY / "nginx.conf").read_text()
    assert "client_max_body_size 256k;" in conf and "client_max_body_size 25m;" in conf
    assert "$http_x_forwarded_for;" not in conf  # never forward the client-supplied chain as-is
    assert "$http_cf_connecting_ip" not in conf  # a client can send CF-Connecting-IP on the Plesk path
    assert 'proxy_set_header CF-Connecting-IP "";' in conf


def _nginx_cap(conf: str, path: str) -> int:
    """client_max_body_size (bytes) nginx applies to `path`: an exact location, else a regex one, else the server's."""
    size = {"k": 1024, "m": 1024 * 1024}
    blocks = re.findall(r"location\s+(=|~)\s+(\S+)\s*\{([^}]*)\}", conf)
    for kind, pattern, body in sorted(blocks, key=lambda b: b[0] != "="):  # exact matches win, as in nginx
        if (path == pattern) if kind == "=" else re.search(pattern, path):
            m = re.search(r"client_max_body_size (\d+)([km]);", body)
            if m:
                return int(m.group(1)) * size[m.group(2)]
            break
    m = re.search(r"^\s{4}client_max_body_size (\d+)([km]);", conf, re.M)
    assert m
    return int(m.group(1)) * size[m.group(2)]


def test_edge_nginx_lets_every_upload_route_through_at_the_runtimes_cap():
    """A route the runtime takes more than 256 KB on needs its own nginx location, or uploads die at the edge."""
    from app.security import JSON_LIMIT, SMALL_UPLOADS, UPLOAD_PATHS, body_limit

    conf = (DEPLOY / "nginx.conf").read_text()
    for path in (*UPLOAD_PATHS, *SMALL_UPLOADS):
        assert _nginx_cap(conf, path) >= body_limit(path) > JSON_LIMIT, path
    assert _nginx_cap(conf, "/invoices/INV-0001/send") == JSON_LIMIT  # and nothing else gets more


def test_static_site_sends_security_headers():
    htaccess = (ROOT / "apps/web/public/.htaccess").read_text()
    for h in HEADERS:
        assert re.search(rf"^\s*Header always set {h} ", htaccess, re.M), h


def test_static_site_has_a_full_csp_in_report_only_mode():
    """The enforced CSP stays frame/object/base only; the report-only one says where tokens may go (connect-src)."""
    htaccess = (ROOT / "apps/web/public/.htaccess").read_text()
    m = re.search(r'^\s*Header always set Content-Security-Policy-Report-Only "([^"]+)"$', htaccess, re.M)
    assert m
    policy = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in m.group(1).split(";")) if d}
    assert policy["default-src"] == ["'self'"] and policy["object-src"] == ["'none'"]
    connect = policy["connect-src"]
    deploy = (ROOT / ".github/workflows/deploy-web.yml").read_text()
    for var in ("NEXT_PUBLIC_RUNTIME_URL", "NEXT_PUBLIC_RELAY_URL"):  # the published build's own services
        url = re.search(rf"{var}: (\S+)", deploy)
        assert url and url.group(1) in connect, var
    assert "https://graph.microsoft.com" in connect and "https://login.microsoftonline.com" in connect
    assert not any(src in ("*", "https:", "http:") for srcs in policy.values() for src in srcs)


def test_static_site_caches_hashed_assets_only():
    htaccess = (ROOT / "apps/web/public/.htaccess").read_text()
    # HTML and everything unhashed: revalidate. Only /_next/static/ (content-hashed names) is kept for a year.
    assert re.search(r'^\s*Header set Cache-Control "no-cache"$', htaccess, re.M)
    hashed = re.search(r'<If "%\{REQUEST_URI\} =~ m#\^/_next/static/#">\s*Header set Cache-Control "([^"]+)"', htaccess)
    assert hashed and hashed.group(1) == "public, max-age=31536000, immutable"
    assert htaccess.count("immutable") == 1


@pytest.mark.parametrize("name", ["Dockerfile.runtime", "Dockerfile.relay"])
def test_dockerfiles_are_pinned_non_root_with_healthcheck(name):
    text = (DEPLOY / name).read_text()
    bases = re.findall(r"^FROM (\S+)", text, re.M)
    assert len(bases) == 1, f"one stage expected, got {bases}"  # a second FROM silently replaces the pinned base
    assert re.fullmatch(r"[\w./-]+:\d+\.\d+\.\d+[\w.-]*(@sha256:[0-9a-f]{64})?", bases[0]), f"unpinned base {bases[0]}"
    assert re.search(r"^USER (?!root|0\b)\S+", text, re.M)
    assert re.search(r"^HEALTHCHECK ", text, re.M)


def test_compose_services_are_hardened():
    yaml = pytest.importorskip("yaml")  # PyYAML is not a runtime dependency
    services = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())["services"]
    assert set(services) == {"runtime", "relay", "edge"}
    for name, svc in services.items():
        assert svc["read_only"] is True and svc["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in svc["security_opt"], name
        assert all(p.startswith("127.0.0.1:") for p in svc["ports"]), name  # only the tunnel/host reaches them
        if "image" in svc and "build" not in svc:
            assert re.search(r":\d+\.\d+\.\d+", svc["image"]), f"{name} image not pinned"
    assert "healthcheck" in services["edge"]


def test_android_manifest_asks_for_little_and_is_not_backed_up():
    """The Android app (apps/mobile): only the permissions its features use, and no cloud backup of its settings."""
    manifest = (ROOT / "apps/mobile/android/app/src/main/AndroidManifest.xml").read_text()
    code = re.sub(r"<!--.*?-->", "", manifest, flags=re.S)
    perms = set(re.findall(r'<uses-permission android:name="android\.permission\.([A-Z_]+)"', code))
    assert perms == {"CAMERA", "RECORD_AUDIO", "INTERNET", "ACCESS_NETWORK_STATE"}
    assert 'android:allowBackup="false"' in code
    assert "android:debuggable" not in code
    assert code.count('android:exported="true"') == 1  # the launcher activity; MSAL's own is declared by the library
