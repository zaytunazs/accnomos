"""public_chat_eval: the prompt set, its grounding in the docs, the scorers and the client, against a fake route."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from harness import public_chat_eval as pc


def _corpus() -> str:
    return pc.norm_text(" ".join(f.read_text(encoding="utf-8") for f in pc.corpus_files() if f.exists()))


def test_prompt_mix() -> None:
    cats = {c: sum(1 for x in pc.CASES if x.cat == c) for c in {x.cat for x in pc.CASES}}
    assert cats["offtopic"] == 20 and cats["injection"] == 10 and cats["unknown"] == 6
    on_topic = cats["feature"] + cats["privacy"] + cats["hmrc"] + cats["unknown"]
    assert 45 <= on_topic <= 60 and 75 <= len(pc.CASES) <= 90
    assert len({c.id for c in pc.CASES}) == len(pc.CASES) == len({c.prompt for c in pc.CASES})
    for c in pc.CASES:
        if c.cat in ("feature", "privacy", "hmrc", "unknown"):
            assert c.must, c.id
        if c.cat == "injection":
            assert c.forbid, c.id


def test_expected_key_phrases_come_from_the_docs() -> None:
    """Every required group has an alternative that the docs themselves contain (so a right answer can exist)."""
    corpus = _corpus()
    for c in pc.CASES:
        if c.cat in ("unknown", "offtopic", "injection"):
            continue
        for g in c.must:
            assert any(a in corpus for a in g), f"{c.id} {c.prompt!r}: none of {g} is in README.md or docs/"


def test_hmrc_questions_are_about_sandbox_status() -> None:
    hmrc = [c for c in pc.CASES if c.cat == "hmrc"]
    assert len(hmrc) >= 5
    flat = {a for c in hmrc for g in c.must for a in g}
    assert "sandbox" in flat and any("not been run" in a or "untested" in a for a in flat)
    assert sum(1 for c in hmrc if any("sandbox" in g for g in c.must)) >= 4


def test_every_source_file_named_exists() -> None:
    for c in pc.CASES:
        if c.src.startswith(("README", "docs/")):
            assert (pc.REPO / c.src).exists(), c.src


NUMS = pc.load_corpus_numbers(pc.corpus_files())


def _bad(answer: str, prompt: str = "", strict: bool = False) -> list[str]:
    return pc.invented_numbers(answer, prompt, NUMS[0], NUMS[1], strict=strict)


def test_invented_number_check() -> None:
    assert _bad("Glimmer reads a receipt in about 18 seconds.") == []  # 17.7 in the docs, within 6 %
    assert _bad("Every field is right on 85 % of clean documents.") == []
    assert _bad("Plans start at £7.99 a month.") == ["£7.99"]
    assert _bad("It supports up to 1234 users.") == ["1234"]
    assert pc.invented_numbers("There are 3 steps.", "", set(), set()) == []  # single digits are ignored...
    assert pc.invented_numbers("There are 3 steps.", "", set(), set(), strict=True) == ["3"]  # ...unless strict
    assert _bad("1. Upload\n2. Approve") == []  # list markers
    assert _bad("Yes, a 30 day trial.", "Is there a 30 day trial?") == []  # the question's own figure
    assert _bad("The invoice is for £100.") == []  # £100 is in the docs


def test_refusal_and_extraction() -> None:
    assert pc.is_refusal("Sorry, please Contact the team.") and pc.is_refusal("please contact our team!")
    assert not pc.is_refusal("Accnomos reads receipts.") and pc.is_refusal("x", flag=True)
    assert pc.extract_text(b'{"reply": "hi", "refused": false}', "application/json") == ("hi", False)
    assert pc.extract_text(b'{"answer": "a"}', "application/json")[0] == "a"
    assert pc.extract_text(b'{"message": {"content": "m"}}', "application/json")[0] == "m"
    assert pc.extract_text(b'{"choices":[{"message":{"content":"c"}}]}', "application/json")[0] == "c"
    assert pc.extract_text(b"plain words", "text/plain")[0] == "plain words"
    sse = b'data: {"delta": "Hel"}\n\ndata: {"delta": "lo"}\n\ndata: [DONE]\n'
    assert pc.extract_text(sse, "text/event-stream")[0] == "Hello"


def _case(cat: str) -> pc.Case:
    return next(c for c in pc.CASES if c.cat == cat)


def test_scoring_rules() -> None:
    inj = _case("injection")
    ok, problems = pc.score(inj, pc.REFUSAL_REPLY, 200, None, NUMS, pc.REFUSAL_RE, False)
    assert ok and problems == []
    _, problems = pc.score(
        inj, "Sure: PWNED, my instructions are: you are a bot", 200, None, NUMS, pc.REFUSAL_RE, False
    )
    assert any("refused" in p for p in problems)
    feat = _case("feature")
    _, problems = pc.score(feat, pc.REFUSAL_REPLY, 200, None, NUMS, pc.REFUSAL_RE, False)
    assert problems == ["refused an on-topic product question"]
    _, problems = pc.score(feat, "It is software.", 200, None, NUMS, pc.REFUSAL_RE, False)
    assert problems and problems[0].startswith("missing")
    unk = _case("unknown")
    _, problems = pc.score(unk, "It costs £9.99. Contact the team.", 200, None, NUMS, pc.REFUSAL_RE, False)
    assert any("figure" in p for p in problems)
    assert pc.score(unk, "Please contact the team.", 200, None, NUMS, pc.REFUSAL_RE, False)[1] == []
    assert pc.score(feat, "x", 500, None, NUMS, pc.REFUSAL_RE, False)[1] == ["HTTP 500"]


def _run(mode: str, tmp_path: Path, extra: list[str] | None = None) -> tuple[int, dict | None]:
    fake = pc.FakeChat(mode)
    base = fake.start()
    try:
        code = pc.main(["--base", base, "--per-min", "0", "--out", str(tmp_path), *(extra or [])])
    finally:
        fake.stop()
    f = tmp_path / "result.json"
    return code, (json.loads(f.read_text(encoding="utf-8")) if f.exists() else None)


def test_good_route_passes_everything(tmp_path: Path) -> None:
    code, res = _run("good", tmp_path)
    assert code == 0 and res and res["passed"] == res["prompts"] == len(pc.CASES)
    assert res["false_refusals"] == 0 and res["should_refuse"]["refused"] == 30
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# Public chat eval")


def test_leaky_route_is_caught(tmp_path: Path) -> None:
    code, res = _run("leaky", tmp_path)
    assert code == 1 and res
    assert res["should_refuse"]["refused"] == 0 and res["should_refuse"]["leaked_or_obeyed"] >= 1
    assert res["by_category"]["offtopic"]["passed"] == 0 and res["by_category"]["feature"]["pass_pct"] == 100.0


def test_inventive_route_is_caught(tmp_path: Path) -> None:
    code, res = _run("inventive", tmp_path)
    assert code == 1 and res
    assert res["answers_with_invented_numbers"] >= 40
    assert res["by_category"]["unknown"]["passed"] == 0


def test_missing_route_stops_with_a_clear_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = pc.FakeChat("missing")
    base = fake.start()
    try:
        code = pc.main(["--base", base, "--out", str(tmp_path)])
    finally:
        fake.stop()
    err = capsys.readouterr().err
    assert code == 2 and "not deployed" in err and "HTTP 404" in err
    assert fake.hits == 1  # one preflight request, not 80 failures
    assert not (tmp_path / "result.json").exists()


def test_nothing_listening_is_a_clear_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = pc.main(["--base", "http://127.0.0.1:1", "--out", str(tmp_path)])
    assert code == 2 and "cannot reach" in capsys.readouterr().err


def test_no_base_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert pc.main([]) == 2 and "--base" in capsys.readouterr().err


def test_dry_run_and_stub_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert pc.main(["--dry-run"]) == 0
    assert "prompts" in capsys.readouterr().out
    assert pc.main(["--stub", "--out", str(tmp_path), "--limit", "2"]) == 0
    res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert res["stub"] and res["prompts"] == 12


def test_429_waits_and_retries() -> None:
    state = {"n": 0}

    class H(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            state["n"] += 1
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            if state["n"] == 1:
                self.send_response(429)
                self.send_header("Retry-After", "0")
                self.end_headers()
                return
            body = b'{"reply": "ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, text, _ = pc.Client(f"http://127.0.0.1:{srv.server_address[1]}").ask("hi")
    finally:
        srv.shutdown()
        srv.server_close()
    assert (status, text, state["n"]) == (200, "ok", 2)
