from datetime import UTC, datetime

import pytest

from relay.fraud_headers import REQUIRED, ClientFacts, RequestMeta, build_headers, enc, missing, request_meta

from .conftest import make_settings, mobile_facts, web_facts

META = RequestMeta(
    public_ip="198.51.100.7", public_port=50123, received_at=datetime(2026, 10, 27, 9, 30, 1, 234000, tzinfo=UTC)
)


@pytest.mark.parametrize("method,facts", [("WEB_APP_VIA_SERVER", web_facts), ("MOBILE_APP_VIA_SERVER", mobile_facts)])
def test_complete_per_method(method, facts):
    h = build_headers(method, ClientFacts(**facts()), META, make_settings())
    assert missing(h, method) == []
    assert set(REQUIRED[method]) <= set(h)
    assert all(v != "null" for v in h.values())


def test_web_has_15_required_and_no_mobile_headers():
    h = build_headers("WEB_APP_VIA_SERVER", ClientFacts(**web_facts()), META, make_settings())
    assert len(REQUIRED["WEB_APP_VIA_SERVER"]) == 15
    assert not {"Gov-Client-User-Agent", "Gov-Client-Local-IPs", "Gov-Client-Local-IPs-Timestamp"} & set(h)
    assert "Gov-Vendor-License-IDs" not in h  # only when configured


def test_values_and_percent_encoding():
    s = make_settings(relay_licence_hash="ab/cd=", relay_public_ip="2001:db8::6")
    h = build_headers("MOBILE_APP_VIA_SERVER", ClientFacts(**mobile_facts()), META, s)
    assert h["Gov-Client-Connection-Method"] == "MOBILE_APP_VIA_SERVER"
    assert h["Gov-Client-Public-IP"] == "198.51.100.7"
    assert h["Gov-Client-Public-IP-Timestamp"] == "2026-10-27T09:30:01.234Z"
    assert h["Gov-Client-Public-Port"] == "50123"
    assert h["Gov-Client-Local-IPs"] == "10.0.0.12,fe80%3A%3A1"
    assert h["Gov-Client-User-Agent"] == (
        "os-family=Android&os-version=15&device-manufacturer=Google&device-model=Pixel%209"
    )
    assert h["Gov-Client-Screens"] == "width=1080&height=2400&scaling-factor=2.75&colour-depth=24"
    assert h["Gov-Client-Multi-Factor"] == "type=TOTP&timestamp=2026-10-27T09%3A00Z&unique-reference=c6f1e2"
    assert h["Gov-Vendor-Forwarded"] == "by=2001%3Adb8%3A%3A6&for=198.51.100.7"
    assert h["Gov-Vendor-Public-IP"] == "2001:db8::6"
    assert h["Gov-Vendor-Product-Name"] == "Accnomos%20Books"
    assert h["Gov-Vendor-Version"] == "accnomos-android=1.4.0&accnomos-books-relay=0.1.0"
    assert h["Gov-Vendor-License-IDs"] == "accnomos-books=ab%2Fcd%3D"


def test_web_user_ids_and_empty_mfa():
    h = build_headers("WEB_APP_VIA_SERVER", ClientFacts(**web_facts()), META, make_settings())
    assert h["Gov-Client-User-IDs"] == "accnomos=user%2042"
    assert h["Gov-Client-Multi-Factor"] == ""
    assert h["Gov-Client-Window-Size"] == "width=1256&height=803"
    assert h["Gov-Client-Screens"] == "width=1920&height=1080&scaling-factor=1&colour-depth=24"


def test_unavailable_are_omitted_and_reported(caplog):
    facts = web_facts() | {"window_size": None}
    meta = RequestMeta(public_ip="198.51.100.7", public_port=None, received_at=META.received_at)
    h = build_headers("WEB_APP_VIA_SERVER", ClientFacts(**facts), meta, make_settings())
    assert "Gov-Client-Public-Port" not in h and "Gov-Client-Window-Size" not in h
    assert missing(h, "WEB_APP_VIA_SERVER") == ["Gov-Client-Public-Port", "Gov-Client-Window-Size"]
    assert "Gov-Client-Public-Port" in caplog.text


def test_mobile_vendor_version_needs_two_pairs():
    facts = mobile_facts() | {"vendor_versions": None}
    h = build_headers("MOBILE_APP_VIA_SERVER", ClientFacts(**facts), META, make_settings())
    assert missing(h, "MOBILE_APP_VIA_SERVER") == ["Gov-Vendor-Version"]


def test_enc():
    assert enc("a b&c=d,é") == "a%20b%26c%3Dd%2C%C3%A9"


@pytest.mark.parametrize(
    "headers,peer,expected",
    [
        ({}, ("198.51.100.7", 50123), ("198.51.100.7", 50123)),
        # the last hop is the one the proxy appended; hops to its left came from the client
        ({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}, ("10.0.0.1", 4000), ("203.0.113.9", None)),
        ({"X-Forwarded-For": "203.0.113.9 ,"}, ("10.0.0.1", 4000), (None, None)),
        ({"X-Forwarded-For": "203.0.113.9:6000", "X-Client-Port": "6000"}, ("10.0.0.1", 4000), ("203.0.113.9", 6000)),
        ({"X-Forwarded-For": "[2001:db8::1]:443"}, ("10.0.0.1", 4000), ("2001:db8::1", None)),
        # CF-Connecting-IP is never trusted, with or without X-Forwarded-For
        ({"CF-Connecting-IP": "2001:db8::2", "X-Forwarded-For": "203.0.113.9"}, ("10.0.0.1", 1), ("203.0.113.9", None)),
        ({"CF-Connecting-IP": "2001:db8::2"}, ("198.51.100.7", 50123), ("198.51.100.7", 50123)),
        ({"X-Forwarded-For": "garbage"}, ("10.0.0.1", 4000), (None, None)),
    ],
)
def test_request_meta(headers, peer, expected):
    m = request_meta(headers, *peer)
    assert (m.public_ip, m.public_port) == expected
