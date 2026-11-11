#!/usr/bin/env python3
"""Evidence for HMRC's production-credentials request: run HMRC's Test Fraud Prevention Headers API against the
SANDBOX application and save what it says in docs/hmrc/.

HMRC asks every MTD VAT / Income Tax product to "check submissions using the Test Fraud Prevention Headers API before
submitting live header data" (Developer Hub terms of use, "Fraud prevention data"). The API has two endpoints, both
application-restricted (client_credentials) and sandbox only:

    GET /test/fraud-prevention-headers/validate
        checks the Gov-* headers sent WITH THIS REQUEST (immediate feedback for one request)
    GET /test/fraud-prevention-headers/{api}/validation-feedback?connectionMethod=WEB_APP_VIA_SERVER
        HMRC's feedback on the LAST request this application made to each endpoint of {api} (vat-mtd here)

Two ways to run it (the owner runs it; no credentials are in the repository):

1. Through the relay (recommended: it is the relay that builds the headers HMRC will see):

       python tools/hmrc/fph_validate.py --relay https://api.accnomos.com

   calls the relay's sandbox-only POST /hmrc/validate-headers (with the browser facts in --facts, or a typical
   desktop browser) and GET /hmrc/validation-feedback?method=WEB_APP_VIA_SERVER. Make a sandbox VAT submission from
   the web app first (the demo does one: /demo → VAT → Submit), so the feedback has requests to report on.

2. Straight to HMRC's sandbox with the sandbox application's own credentials (feedback only; validating headers
   needs the relay to build them):

       HMRC_CLIENT_ID=… HMRC_CLIENT_SECRET=… python tools/hmrc/fph_validate.py --direct

Writes docs/hmrc/fph-validation-YYYY-MM-DD.json (everything HMRC answered, the headers sent, never a token or a
secret) and docs/hmrc/fph-validation-YYYY-MM-DD.md (a short summary: errors, warnings, per endpoint). Exit code 0
when HMRC reports no errors, 1 when it reports errors, 2 when the run itself failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SANDBOX = "https://test-api.service.hmrc.gov.uk"
FEEDBACK_API = "vat-mtd"
METHOD = "WEB_APP_VIA_SERVER"
OUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "hmrc"
#: A typical desktop browser, the facts the web app collects (apps/web/src/lib/hmrc.ts clientFacts). Override with
#: --facts file.json holding what a real browser sent (copy it from the browser's network tab).
DEFAULT_FACTS: dict[str, Any] = {
    "device_id": "beec798b-b366-47fa-b1f8-92cede14a1ce",
    "multi_factor": [],
    "screens": [{"width": 1920, "height": 1080, "scaling_factor": 1, "colour_depth": 24}],
    "timezone": "UTC+00:00",
    "user_ids": {"accnomos": "4f1c0e2b9a7d4c5e8f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2"},
    "window_size": {"width": 1256, "height": 803},
    "browser_js_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "vendor_versions": {"accnomos-web": "0.4.0"},
}
SECRET_KEYS = {"authorization", "access_token", "refresh_token", "client_secret", "x-hmrc-access-token"}


def scrub(value: Any) -> Any:
    """Drop anything that looks like a credential before it is written to the repository."""
    if isinstance(value, dict):
        return {k: ("<removed>" if str(k).lower() in SECRET_KEYS else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def via_relay(http: httpx.Client, relay: str, facts: dict[str, Any]) -> dict[str, Any]:
    base = relay.rstrip("/")
    head = {"X-HMRC-Environment": "sandbox"}  # the sandbox application, whatever the relay's HMRC_ENV is
    v = http.post(f"{base}/hmrc/validate-headers", json={"client_facts": facts, "method": METHOD}, headers=head)
    f = http.get(f"{base}/hmrc/validation-feedback", params={"method": METHOD}, headers=head)
    return {
        "mode": "relay",
        "relay": base,
        "validate": {"status": v.status_code, "body": _json(v)},
        "feedback": {"status": f.status_code, "body": _json(f)},
    }


def direct(http: httpx.Client, client_id: str, client_secret: str, base: str = SANDBOX) -> dict[str, Any]:
    tok = http.post(
        f"{base}/oauth/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        headers={"Accept": "application/json"},
    )
    tok.raise_for_status()
    bearer = tok.json()["access_token"]
    f = http.get(
        f"{base}/test/fraud-prevention-headers/{FEEDBACK_API}/validation-feedback",
        params={"connectionMethod": METHOD},
        headers={"Accept": "application/vnd.hmrc.1.0+json", "Authorization": f"Bearer {bearer}"},
    )
    return {"mode": "direct", "base": base, "feedback": {"status": f.status_code, "body": _json(f)}}


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:2000]


def problems(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(errors, warnings) as short lines, from both answers. HMRC's shapes: validate returns {code, message, errors,
    warnings}; feedback returns {requests: [{path, method, requestTimestamp, code, errors, warnings, ...}], ...}."""
    errors: list[str] = []
    warnings: list[str] = []

    def take(where: str, body: Any) -> None:
        if not isinstance(body, dict):
            return
        for e in body.get("errors") or []:
            errors.append(f"{where}: {_item(e)}")
        for w in body.get("warnings") or []:
            warnings.append(f"{where}: {_item(w)}")

    for step in ("validate", "feedback"):
        part = result.get(step)
        if not part:
            continue
        body = part.get("body")
        if part.get("status", 200) >= 400:
            errors.append(f"{step}: HTTP {part.get('status')} {_item(body)}")
            continue
        if step == "validate":
            # The relay wraps HMRC's answer: {"hmrc": {...}, "sent_headers": {...}, ...}
            take("validate", body.get("hmrc") if isinstance(body, dict) and "hmrc" in body else body)
        else:
            take("feedback", body)
            for req in (body.get("requests") or []) if isinstance(body, dict) else []:
                take(f"feedback {req.get('method', '')} {req.get('path', '')}".strip(), req)
    return errors, warnings


def _item(x: Any) -> str:
    if isinstance(x, dict):
        head = x.get("code") or x.get("header") or ""
        msg = x.get("message") or ""
        headers = x.get("headers")
        extra = f" ({', '.join(headers)})" if isinstance(headers, list) else ""
        return f"{head} {msg}{extra}".strip()
    return str(x)[:300]


def summary(result: dict[str, Any], errors: list[str], warnings: list[str], when: datetime) -> str:
    lines = [
        f"# HMRC fraud-prevention headers: sandbox validation, {when:%d %b %Y %H:%M} UTC",
        "",
        f"Made by `tools/hmrc/fph_validate.py` ({result['mode']}), against HMRC's sandbox application, connection "
        f"method `{METHOD}`, feedback API `{FEEDBACK_API}`. Full answers: the JSON file of the same name.",
        "",
        f"**Errors: {len(errors)}. Warnings: {len(warnings)}.**",
        "",
    ]
    if errors:
        lines += ["## Errors", "", *[f"- {e}" for e in errors], ""]
    if warnings:
        lines += ["## Warnings", "", *[f"- {w}" for w in warnings], ""]
    if not errors and not warnings:
        lines += ["HMRC reported nothing to fix.", ""]
    return "\n".join(lines)


def save(result: dict[str, Any], out_dir: Path, when: datetime) -> tuple[Path, Path, int]:
    errors, warnings = problems(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"fph-validation-{when:%Y-%m-%d}"
    j, m = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    record = {"run_at": when.isoformat(timespec="seconds"), **scrub(result), "errors": errors, "warnings": warnings}
    j.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m.write_text(summary(result, errors, warnings, when), encoding="utf-8")
    return j, m, 1 if errors else 0


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    how = p.add_mutually_exclusive_group(required=True)
    how.add_argument("--relay", help="the relay's base URL, e.g. https://api.accnomos.com")
    how.add_argument("--direct", action="store_true", help="call HMRC's sandbox with HMRC_CLIENT_ID/SECRET")
    p.add_argument("--facts", type=Path, help="JSON file of browser facts (ClientFacts) for --relay")
    p.add_argument("--out", type=Path, default=OUT_DIR, help=f"where to save (default {OUT_DIR})")
    a = p.parse_args(argv)
    when = datetime.now(UTC)
    try:
        with httpx.Client(timeout=30, transport=transport) as http:
            if a.relay:
                facts = json.loads(a.facts.read_text(encoding="utf-8")) if a.facts else DEFAULT_FACTS
                result = via_relay(http, a.relay, facts)
            else:
                cid, secret = os.environ.get("HMRC_CLIENT_ID", ""), os.environ.get("HMRC_CLIENT_SECRET", "")
                if not cid or not secret:
                    print("Set HMRC_CLIENT_ID and HMRC_CLIENT_SECRET (the SANDBOX application's).", file=sys.stderr)
                    return 2
                result = direct(http, cid, secret)
    except (httpx.HTTPError, ValueError, OSError) as e:
        print(f"The run failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    j, m, code = save(result, a.out, when)
    print(f"Saved {j} and {m}")
    print(m.read_text(encoding="utf-8"))
    return code


if __name__ == "__main__":
    sys.exit(main())
