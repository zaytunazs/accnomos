"""tools/hmrc/fph_validate.py: the owner's evidence run against HMRC's Test Fraud Prevention Headers API (sandbox).
HMRC is faked; the tool must reach the right endpoints, keep secrets out of the saved files and count problems."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx

TOOL = Path(__file__).resolve().parents[3] / "tools" / "hmrc" / "fph_validate.py"
spec = importlib.util.spec_from_file_location("fph_validate", TOOL)
assert spec and spec.loader
fph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fph)

FEEDBACK = {
    "requests": [
        {
            "path": "/organisations/vat/123456789/returns",
            "method": "POST",
            "code": "POTENTIALLY_INVALID_HEADERS",
            "warnings": [{"code": "POTENTIALLY_INVALID_HEADER", "message": "x", "headers": ["gov-client-screens"]}],
        }
    ]
}


def test_relay_mode_saves_report_without_secrets(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def relay(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.headers["x-hmrc-environment"] == "sandbox"
        if req.url.path == "/hmrc/validate-headers":
            return httpx.Response(200, json={"hmrc": {"code": "VALID_HEADERS"}, "sent_headers": {"Authorization": "x"}})
        assert req.url.path == "/hmrc/validation-feedback" and req.url.params["method"] == "WEB_APP_VIA_SERVER"
        return httpx.Response(200, json=FEEDBACK)

    code = fph.main(["--relay", "https://relay.example", "--out", str(tmp_path)], transport=httpx.MockTransport(relay))
    assert code == 0 and len(seen) == 2
    (j,) = tmp_path.glob("fph-validation-*.json")
    data = json.loads(j.read_text())
    assert data["validate"]["body"]["sent_headers"]["Authorization"] == "<removed>"
    assert data["errors"] == [] and len(data["warnings"]) == 1 and "gov-client-screens" in data["warnings"][0]
    assert "Warnings: 1" in next(tmp_path.glob("*.md")).read_text()


def test_direct_mode_uses_sandbox_and_reports_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HMRC_CLIENT_ID", "cid")
    monkeypatch.setenv("HMRC_CLIENT_SECRET", "secret")

    def hmrc(req: httpx.Request) -> httpx.Response:
        assert str(req.url).startswith("https://test-api.service.hmrc.gov.uk/")
        if req.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "APP", "expires_in": 14400})
        assert req.url.path == "/test/fraud-prevention-headers/vat-mtd/validation-feedback"
        assert req.headers["authorization"] == "Bearer APP"
        return httpx.Response(200, json={"requests": [{"path": "/x", "errors": [{"code": "MISSING_HEADER"}]}]})

    assert fph.main(["--direct", "--out", str(tmp_path)], transport=httpx.MockTransport(hmrc)) == 1
    text = next(tmp_path.glob("*.json")).read_text()
    assert "secret" not in text and "APP" not in text and "MISSING_HEADER" in text


def test_direct_mode_needs_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HMRC_CLIENT_ID", raising=False)
    monkeypatch.delenv("HMRC_CLIENT_SECRET", raising=False)
    assert fph.main(["--direct", "--out", str(tmp_path)]) == 2
