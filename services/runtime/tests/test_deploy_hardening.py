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


def test_static_site_sends_security_headers():
    htaccess = (ROOT / "apps/web/public/.htaccess").read_text()
    for h in HEADERS:
        assert re.search(rf"^\s*Header always set {h} ", htaccess, re.M), h


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
