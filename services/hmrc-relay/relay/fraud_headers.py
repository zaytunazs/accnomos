"""HMRC fraud-prevention headers, spec v3.3.

`build_headers` is pure: client-collected facts + what the relay observed about the request + settings in,
header dict out. A header is omitted only when its source data is genuinely unavailable; that is logged and
reported by `missing` — never filled with a placeholder.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from .settings import Settings

log = logging.getLogger("hmrc_relay.fraud_headers")

Method = Literal["WEB_APP_VIA_SERVER", "MOBILE_APP_VIA_SERVER"]

_COMMON = [
    "Gov-Client-Connection-Method",
    "Gov-Client-Device-ID",
    "Gov-Client-Multi-Factor",
    "Gov-Client-Public-IP",
    "Gov-Client-Public-IP-Timestamp",
    "Gov-Client-Public-Port",
    "Gov-Client-Screens",
    "Gov-Client-Timezone",
    "Gov-Client-User-IDs",
    "Gov-Client-Window-Size",
    "Gov-Vendor-Forwarded",
    "Gov-Vendor-Product-Name",
    "Gov-Vendor-Public-IP",
    "Gov-Vendor-Version",
]
REQUIRED: dict[str, list[str]] = {
    "WEB_APP_VIA_SERVER": _COMMON + ["Gov-Client-Browser-JS-User-Agent"],
    "MOBILE_APP_VIA_SERVER": _COMMON
    + ["Gov-Client-User-Agent", "Gov-Client-Local-IPs", "Gov-Client-Local-IPs-Timestamp"],
}
# Gov-Vendor-License-IDs is sent when RELAY_LICENCE_HASH is configured; it is not required otherwise.

_TS = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"


def enc(value: object) -> str:
    """Percent-encode a header value component (RFC 3986, nothing reserved left unescaped)."""
    return quote(str(value), safe="")


def _pairs(d: Mapping[str, object]) -> str:
    return "&".join(f"{enc(k)}={enc(v)}" for k, v in d.items())


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an unknown fact is a client bug, not something to drop quietly


class MultiFactor(_Strict):
    type: Literal["TOTP", "AUTH_CODE", "OTHER"]
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")
    unique_reference: str = Field(min_length=1, description="Hash identifying the factor, never the factor itself")


class Screen(_Strict):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    scaling_factor: float = Field(gt=0)
    colour_depth: int = Field(gt=0)


class WindowSize(_Strict):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class DeviceUserAgent(_Strict):
    os_family: str
    os_version: str
    device_manufacturer: str
    device_model: str


class ClientFacts(_Strict):
    """What the browser / app collected on the device. Field absent = genuinely unavailable."""

    device_id: str | None = None
    multi_factor: list[MultiFactor] | None = None  # [] = no MFA used (sent as an empty header)
    screens: list[Screen] | None = None
    timezone: str | None = Field(None, pattern=r"^UTC[+-]\d{2}:\d{2}$")
    user_ids: dict[str, str] | None = None  # e.g. {"accnomos": "<user id>"}
    window_size: WindowSize | None = None
    vendor_versions: dict[str, str] | None = None  # client software, e.g. {"accnomos-android": "1.4.0"}
    # web only
    browser_js_user_agent: str | None = None
    # mobile only
    user_agent: DeviceUserAgent | None = None
    local_ips: list[str] | None = None
    local_ips_timestamp: str | None = Field(None, pattern=_TS)


@dataclass(frozen=True)
class RequestMeta:
    """What the relay itself observed about the inbound client request."""

    public_ip: str | None
    public_port: int | None
    received_at: datetime


# Proxies that know the client's source port should forward it in one of these (e.g. nginx `$remote_port`).
_PORT_HEADERS = ("x-client-port", "x-real-port")


def request_meta(
    headers: Mapping[str, str], peer_host: str | None, peer_port: int | None, received_at: datetime | None = None
) -> RequestMeta:
    """Work out the client's public IP/port: the last X-Forwarded-For hop, else the socket.

    The proxy in front appends the peer it saw, so the last hop is the one a client cannot forge; anything to its
    left was sent by the client. CF-Connecting-IP is never read, for the same reason (deploy/nginx.conf applies
    the same rule and strips it, but the relay does not rely on that).
    Behind a proxy the socket port belongs to the proxy, so the port is only trusted from the socket when no
    forwarding header was used, or from an explicit client-port header set by the proxy.
    """
    received_at = received_at or datetime.now(UTC)
    h = {k.lower(): v for k, v in headers.items()}
    forwarded = (h.get("x-forwarded-for") or "").strip()
    if forwarded:  # behind a proxy: the socket peer is the proxy, never fall back to it
        ip = _clean_ip(forwarded.split(",")[-1])
        port = next((int(h[k]) for k in _PORT_HEADERS if h.get(k, "").strip().isdigit()), None)
    else:
        ip, port = _clean_ip(peer_host or ""), peer_port
    return RequestMeta(public_ip=ip, public_port=port, received_at=received_at)


def _clean_ip(raw: str) -> str | None:
    raw = raw.strip()
    if raw.startswith("[") and "]" in raw:  # [v6]:port
        raw = raw[1 : raw.index("]")]
    elif raw.count(":") == 1:  # v4:port
        raw = raw.split(":")[0]
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def build_headers(method: Method, client_facts: ClientFacts, meta: RequestMeta, settings: Settings) -> dict[str, str]:
    cf = client_facts
    h: dict[str, str] = {"Gov-Client-Connection-Method": method}

    if cf.device_id:
        h["Gov-Client-Device-ID"] = cf.device_id
    if cf.multi_factor is not None:
        h["Gov-Client-Multi-Factor"] = ",".join(
            _pairs({"type": m.type, "timestamp": m.timestamp, "unique-reference": m.unique_reference})
            for m in cf.multi_factor
        )
    if cf.screens:
        h["Gov-Client-Screens"] = ",".join(
            _pairs(
                {
                    "width": s.width,
                    "height": s.height,
                    "scaling-factor": f"{s.scaling_factor:g}",
                    "colour-depth": s.colour_depth,
                }
            )
            for s in cf.screens
        )
    if cf.timezone:
        h["Gov-Client-Timezone"] = cf.timezone
    if cf.user_ids:
        h["Gov-Client-User-IDs"] = _pairs(cf.user_ids)
    if cf.window_size:
        h["Gov-Client-Window-Size"] = _pairs({"width": cf.window_size.width, "height": cf.window_size.height})

    if method == "WEB_APP_VIA_SERVER":
        if cf.browser_js_user_agent:
            h["Gov-Client-Browser-JS-User-Agent"] = cf.browser_js_user_agent
    else:
        if cf.user_agent:
            ua = cf.user_agent
            h["Gov-Client-User-Agent"] = _pairs(
                {
                    "os-family": ua.os_family,
                    "os-version": ua.os_version,
                    "device-manufacturer": ua.device_manufacturer,
                    "device-model": ua.device_model,
                }
            )
        if cf.local_ips:
            h["Gov-Client-Local-IPs"] = ",".join(enc(ip) for ip in cf.local_ips)
        if cf.local_ips_timestamp:
            h["Gov-Client-Local-IPs-Timestamp"] = cf.local_ips_timestamp

    if meta.public_ip:
        h["Gov-Client-Public-IP"] = meta.public_ip
        h["Gov-Client-Public-IP-Timestamp"] = _ts(meta.received_at)
    if meta.public_port:
        h["Gov-Client-Public-Port"] = str(meta.public_port)
    if settings.relay_public_ip:
        h["Gov-Vendor-Public-IP"] = settings.relay_public_ip
        if meta.public_ip:
            h["Gov-Vendor-Forwarded"] = _pairs({"by": settings.relay_public_ip, "for": meta.public_ip})

    product = settings.vendor_product_key
    h["Gov-Vendor-Product-Name"] = enc(settings.hmrc_vendor_product_name)
    h["Gov-Vendor-Version"] = _pairs({**(cf.vendor_versions or {}), f"{product}-relay": settings.hmrc_vendor_version})
    if settings.relay_licence_hash:
        h["Gov-Vendor-License-IDs"] = _pairs({product: settings.relay_licence_hash})

    if gaps := missing(h, method):
        log.warning("fraud-prevention headers unavailable for %s: %s", method, ", ".join(gaps))
    return h


def missing(headers: Mapping[str, str], method: Method) -> list[str]:
    """Required headers absent for `method`. An empty Gov-Client-Multi-Factor counts as present (no MFA used).

    For mobile, Gov-Vendor-Version is also reported if it lacks the app *and* server pairs the spec requires.
    """
    gaps = [name for name in REQUIRED[method] if name not in headers]
    if method == "MOBILE_APP_VIA_SERVER" and "Gov-Vendor-Version" in headers:
        if headers["Gov-Vendor-Version"].count("=") < 2:
            gaps.append("Gov-Vendor-Version")
    return gaps
