"""Early-adopter list (app/early_access.py): POST /public/early-access, its neutral alias /public/sign-up, and the
owner CLI."""

from __future__ import annotations

import csv
import io
import json
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import early_access as ea
from app.main import app
from app.security import TokenBucket

URL = "/public/early-access"


def body(**over: object) -> dict[str, object]:
    return {
        "email": "Priya@Example.co.uk",
        "name": "Priya Shah",
        "business_type": "sole_trader",
        "heard": "A friend",
        "consent": True,
        "consent_text": ea.CONSENT_TEXT,
        "source": "/",
        **over,
    }


@pytest.fixture
def file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data" / "early-access.jsonl"
    monkeypatch.setenv("EARLY_ACCESS_FILE", str(path))
    monkeypatch.setenv("EARLY_ACCESS_ENABLED", "1")
    monkeypatch.setattr(ea, "LIMITER", TokenBucket(5))
    return path


@pytest.fixture
def client(file: Path) -> Iterator[TestClient]:
    yield TestClient(app)


def lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_sign_up_stores_one_record_with_the_consent_text(client: TestClient, file: Path) -> None:
    r = client.post(URL, json=body())
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "message": "You're on the list — we'll email you once at launch"}
    [rec] = lines(file)
    assert rec["email"] == "priya@example.co.uk"  # trimmed and lower-cased
    assert rec["name"] == "Priya Shah" and rec["business_type"] == "sole_trader" and rec["heard"] == "A friend"
    assert rec["consent"] is True and rec["consent_text"] == ea.CONSENT_TEXT
    assert rec["source"] == "/" and rec["at"].endswith("+00:00")
    assert "ip" not in rec  # the rate limit is in memory only
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_optional_fields_may_be_left_out(client: TestClient, file: Path) -> None:
    r = client.post(URL, json={k: v for k, v in body().items() if k not in ("name", "heard", "source")})
    assert r.status_code == 200, r.text
    [rec] = lines(file)
    assert rec["name"] is None and rec["heard"] is None and rec["source"] == "/"


@pytest.mark.parametrize(
    "email",
    ["", "priya", "priya@", "@example.co.uk", "priya@example", "pri ya@example.co.uk", "priya@@example.co.uk",
     "priya..shah@example.co.uk", "<priya@example.co.uk>", "a" * 65 + "@example.co.uk"],
)  # fmt: skip
def test_bad_email_is_refused(client: TestClient, file: Path, email: str) -> None:
    r = client.post(URL, json=body(email=email))
    assert r.status_code in (400, 422), r.text
    assert not file.exists()


@pytest.mark.parametrize(
    "over",
    [
        {"business_type": "charity"},
        {"name": "x" * 101},
        {"heard": "x" * 201},
        {"source": "https://evil.example/"},
        {"source": "/<script>"},
        {"unexpected": "field"},
    ],
)
def test_other_validation(client: TestClient, file: Path, over: dict) -> None:
    assert client.post(URL, json=body(**over)).status_code in (400, 422)
    assert not file.exists()


def test_every_business_type_is_accepted(client: TestClient, file: Path) -> None:
    for i, kind in enumerate(ea.BUSINESS_TYPES):
        assert client.post(URL, json=body(email=f"p{i}@example.co.uk", business_type=kind)).status_code == 200
    assert [r["business_type"] for r in ea.records(file)] == list(ea.BUSINESS_TYPES)


def test_consent_is_required(client: TestClient, file: Path) -> None:
    r = client.post(URL, json=body(consent=False))
    assert r.status_code == 400 and "Tick the box" in r.json()["detail"]
    assert client.post(URL, json={k: v for k, v in body().items() if k != "consent"}).status_code == 422
    assert not file.exists()


def test_consent_text_must_match_what_is_stored(client: TestClient, file: Path) -> None:
    r = client.post(URL, json=body(consent_text="Send me anything you like."))
    assert r.status_code == 400
    assert not file.exists()


def test_neutral_sign_up_route_feeds_the_same_list(client: TestClient, file: Path) -> None:
    """POST /public/sign-up (the submission build's "Get 3 months free" form) is the same list under a neutral name,
    with its own launch-free consent wording stored as agreed."""
    r = client.post("/public/sign-up", json=body(consent_text=ea.SIGNUP_CONSENT_TEXT, source="/join"))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "message": "Thanks — we'll email you to set up your 3 months free"}
    assert client.post(URL, json=body(email="other@example.co.uk")).status_code == 200
    first, second = lines(file)
    assert first["consent_text"] == ea.SIGNUP_CONSENT_TEXT and first["source"] == "/join"
    assert second["consent_text"] == ea.CONSENT_TEXT
    assert [r["email"] for r in ea.records(file)] == ["priya@example.co.uk", "other@example.co.uk"]
    for word in ("launch", "early", "beta", "coming soon", "waiting"):
        assert word not in ea.SIGNUP_CONSENT_TEXT.lower()


def test_neutral_sign_up_route_has_the_same_checks(client: TestClient, file: Path) -> None:
    assert client.post("/public/sign-up", json=body(consent_text="Send me anything you like.")).status_code == 400
    assert (
        client.post("/public/sign-up", json=body(consent=False, consent_text=ea.SIGNUP_CONSENT_TEXT)).status_code == 400
    )
    r = client.post("/public/sign-up", json=body(consent_text=ea.SIGNUP_CONSENT_TEXT, website="https://spam.example"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not file.exists()


def test_neutral_sign_up_route_is_off_with_the_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EARLY_ACCESS_FILE", str(tmp_path / "x.jsonl"))
    monkeypatch.setenv("EARLY_ACCESS_ENABLED", "0")
    r = TestClient(app).post("/public/sign-up", json=body(consent_text=ea.SIGNUP_CONSENT_TEXT))
    assert r.status_code == 503
    assert not (tmp_path / "x.jsonl").exists()


def test_honeypot_looks_successful_but_keeps_nothing(client: TestClient, file: Path) -> None:
    r = client.post(URL, json=body(website="https://spam.example"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not file.exists()


def test_rate_limit_per_ip(client: TestClient, file: Path) -> None:
    codes = [client.post(URL, json=body(email=f"p{i}@example.co.uk")).status_code for i in range(7)]
    assert codes == [200] * 5 + [429, 429]
    r = client.post(URL, json=body(email="later@example.co.uk"))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert len(lines(file)) == 5


def test_duplicate_email_updates_the_record(client: TestClient, file: Path) -> None:
    assert client.post(URL, json=body()).status_code == 200
    first_at = lines(file)[0]["at"]
    r = client.post(URL, json=body(email="  PRIYA@example.co.uk ", name="Priya S", business_type="company"))
    assert r.status_code == 200
    assert r.json() == client.post(URL, json=body(email="new@example.co.uk")).json()  # same answer: no enumeration
    assert len(lines(file)) == 3  # appended, never rewritten
    current = {r["email"]: r for r in ea.records(file)}
    assert len(current) == 2
    assert current["priya@example.co.uk"]["name"] == "Priya S"
    assert current["priya@example.co.uk"]["business_type"] == "company"
    assert current["priya@example.co.uk"]["first_at"] == first_at


def test_newlines_in_free_text_are_collapsed(client: TestClient, file: Path) -> None:
    assert client.post(URL, json=body(name="Priya\nShah", heard="a\r\n\tpodcast")).status_code == 200
    [rec] = lines(file)
    assert rec["name"] == "Priya Shah" and rec["heard"] == "a podcast"


@pytest.mark.parametrize("flag", [None, "0", "true", ""])
def test_disabled_never_writes_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str | None) -> None:
    path = tmp_path / "early-access.jsonl"
    monkeypatch.setenv("EARLY_ACCESS_FILE", str(path))
    if flag is None:
        monkeypatch.delenv("EARLY_ACCESS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("EARLY_ACCESS_ENABLED", flag)
    r = TestClient(app).post(URL, json=body())
    assert r.status_code == 503
    assert not path.exists() and not list(tmp_path.iterdir())


def test_no_sign_in_needed_and_cors_preflight_allowed(client: TestClient) -> None:
    r = client.options(
        URL,
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )  # fmt: skip
    assert r.status_code == 200
    assert client.post(URL, json=body()).status_code == 200  # no X-Graph-Token


def test_default_file_is_on_the_data_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EARLY_ACCESS_FILE", raising=False)
    assert ea.data_file() == Path("/data/early-access.jsonl")


def test_torn_last_line_is_skipped(file: Path) -> None:
    file.parent.mkdir(parents=True)
    file.write_text(
        json.dumps({"email": "a@example.co.uk", "at": "2026-10-01T00:00:00+00:00"}) + '\n{"email": "b@', "utf-8"
    )
    assert [r["email"] for r in ea.records(file)] == ["a@example.co.uk"]


# --- owner CLI -------------------------------------------------------------------------------------------------


@pytest.fixture
def three(client: TestClient, file: Path) -> Path:
    for email, name in [("a@example.co.uk", "=HYPERLINK(1)"), ("b@example.co.uk", "Bea"), ("a@example.co.uk", "Al")]:
        assert client.post(URL, json=body(email=email, name=name)).status_code == 200
    assert client.post(URL, json=body(email="c@example.co.uk", name="=cmd")).status_code == 200
    return file


def test_cli_count(three: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ea.main(["count"]) == 0
    assert capsys.readouterr().out.strip() == "3"


def test_cli_export_csv(three: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out.csv"
    assert ea.main(["export", "--csv", str(out)]) == 0
    assert "exported 3 record(s)" in capsys.readouterr().err
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["email"] for r in rows] == ["a@example.co.uk", "b@example.co.uk", "c@example.co.uk"]
    assert rows[0]["name"] == "Al" and rows[2]["name"] == "'=cmd"  # formula cells defused
    assert rows[0]["consent_text"] == ea.CONSENT_TEXT and rows[0]["first_at"]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_cli_export_to_stdout(three: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ea.main(["export", "--csv", "-"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 3


def test_cli_delete_erases_every_line_for_that_email(three: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ea.main(["delete", "--email", " A@Example.co.uk "]) == 0
    assert "deleted 2 line(s)" in capsys.readouterr().out
    assert "a@example.co.uk" not in three.read_text(encoding="utf-8")
    assert [r["email"] for r in ea.records(three)] == ["b@example.co.uk", "c@example.co.uk"]
    assert stat.S_IMODE(three.stat().st_mode) == 0o600
    assert ea.main(["delete", "--email", "a@example.co.uk"]) == 0
    assert "no record" in capsys.readouterr().out
    assert not [p for p in three.parent.iterdir() if p.name.startswith(".early-access-")]  # no temp file left


def test_cli_file_option_and_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "none.jsonl"
    assert ea.main(["--file", str(missing), "count"]) == 0
    assert capsys.readouterr().out.strip() == "0"
    assert ea.main(["--file", str(missing), "delete", "--email", "x@example.co.uk"]) == 0
    assert not missing.exists()


def test_cli_module_entry_point(three: Path) -> None:
    import os
    import subprocess
    import sys

    runtime = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(runtime), *sys.path])}
    r = subprocess.run(
        [sys.executable, "-m", "app.early_access", "count"], cwd=runtime, env=env, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "3"
