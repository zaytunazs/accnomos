from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from relay.main import create_app
from relay.settings import Settings

Handler = Callable[[httpx.Request], httpx.Response]


def make_settings(**kw) -> Settings:
    base = dict(
        hmrc_client_id="cid",
        hmrc_client_secret="csecret",
        hmrc_base="https://test-api.service.hmrc.gov.uk",
        hmrc_auth_base="https://test-www.tax.service.gov.uk",
        hmrc_redirect_uri="https://relay.example/hmrc/callback",
        hmrc_vendor_product_name="Accnomos Books",
        hmrc_vendor_version="0.1.0",
        relay_public_ip="203.0.113.6",
        relay_allowed_redirects="https://app.accnomos.example",
    )
    return Settings(_env_file=None, **(base | kw))


def web_facts() -> dict:
    return {
        "device_id": "beec798b-b366-47fa-b1f8-92cede14a1ce",
        "multi_factor": [],
        "screens": [{"width": 1920, "height": 1080, "scaling_factor": 1, "colour_depth": 24}],
        "timezone": "UTC+00:00",
        "user_ids": {"accnomos": "user 42"},
        "window_size": {"width": 1256, "height": 803},
        "browser_js_user_agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
        "vendor_versions": {"accnomos-pwa": "0.4.0"},
    }


def mobile_facts() -> dict:
    return {
        "device_id": "a1b2c3d4-0000-4000-8000-000000000001",
        "multi_factor": [{"type": "TOTP", "timestamp": "2026-10-27T09:00Z", "unique_reference": "c6f1e2"}],
        "screens": [{"width": 1080, "height": 2400, "scaling_factor": 2.75, "colour_depth": 24}],
        "timezone": "UTC+01:00",
        "user_ids": {"accnomos": "user-42"},
        "window_size": {"width": 1080, "height": 2200},
        "user_agent": {
            "os_family": "Android",
            "os_version": "15",
            "device_manufacturer": "Google",
            "device_model": "Pixel 9",
        },
        "local_ips": ["10.0.0.12", "fe80::1"],
        "local_ips_timestamp": "2026-10-27T09:01:02.345Z",
        "vendor_versions": {"accnomos-android": "1.4.0"},
    }


@pytest.fixture
def client_for():
    """Return an AsyncClient bound to a relay whose HMRC traffic goes to `handler`."""

    def _make(handler: Handler, **settings_kw) -> httpx.AsyncClient:
        app = create_app(make_settings(**settings_kw), transport=httpx.MockTransport(handler))
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("198.51.100.7", 50123)), base_url="http://relay"
        )

    return _make
