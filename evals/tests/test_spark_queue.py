"""tools/spark_queue.sh against a fake python in a throwaway copy of the repo layout. No models, no git."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "spark_queue.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "tools" / "spark_queue.sh")
    (repo / "evals").mkdir()
    fake = tmp_path / "fakepy"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$PWD :: $*" >>"$FAKE_CALLS"\n'
        '[ -n "${FAKE_SLEEP:-}" ] && sleep "$FAKE_SLEEP"\n'
        'if [ -n "${FAKE_FAIL:-}" ] && [[ "$*" == *"$FAKE_FAIL"* ]]; then echo "boom"; exit 7; fi\n'
        "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return {"repo": repo, "jobs": tmp_path / "jobs", "fake": fake, "calls": tmp_path / "calls.txt"}


def _run(box: dict[str, Path], *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    e = {
        **os.environ,
        "SPARK_JOBS_DIR": str(box["jobs"]),
        "SPARK_PYTHON": str(box["fake"]),
        "FAKE_CALLS": str(box["calls"]),
        "STEP_TIMEOUT": "1m",
        **(env or {}),
    }
    return subprocess.run(
        ["bash", str(box["repo"] / "tools" / "spark_queue.sh"), *args],
        capture_output=True,
        text=True,
        env=e,
        timeout=60,
    )


def _log(box: dict[str, Path]) -> str:
    return (box["jobs"] / "spark_queue.log").read_text(encoding="utf-8")


def _calls(box: dict[str, Path]) -> list[str]:
    return box["calls"].read_text(encoding="utf-8").splitlines() if box["calls"].exists() else []


def _with_ledger4(box: dict[str, Path]) -> None:
    d = box["repo"] / "evals" / "gold" / "ledger4" / "receipts"
    d.mkdir(parents=True)
    (d / "001_price_history.json").write_text("{}", encoding="utf-8")


def test_runs_every_step_in_order_and_logs(box: dict[str, Path]) -> None:
    _with_ledger4(box)
    r = _run(box, "--no-check")
    assert r.returncode == 0, r.stdout + r.stderr
    log = _log(box)
    order = [m for m in re.findall(r"STEP (\w+): start", log)]
    assert order == ["gen_gold4", "gen_personal", "bank_ai", "extraction_ledger4", "cis_read", "property_docs"]
    assert "STEP extraction_ledger2: skipped" in log and "another schema" in log
    assert "STEP extraction_ledger3: skipped" in log
    assert "nice -n 19" in log  # the politeness prefix is announced
    calls = _calls(box)
    assert [c.split(" :: ")[1].split()[0] for c in calls][:2] == [
        "evals/gold/gen_gold4.py",
        "evals/gold/gen_personal.py",
    ]
    assert calls[2].startswith(str(box["repo"] / "evals")) and "-m harness.bank_ai" in calls[2]
    assert "--gold-dir gold/ledger4/receipts" in calls[3] and "--messy" in calls[3] and "Bramblewood" in calls[3]
    assert "-m harness.cis_read" in calls[4] and "-m harness.property_docs" in calls[5]
    assert sorted(p.name for p in (box["jobs"] / "state").iterdir()) == [
        "bank_ai.done", "cis_read.done", "extraction_ledger4.done", "gen_gold4.done", "gen_personal.done",
        "property_docs.done",
    ]  # fmt: skip


def test_second_run_skips_done_steps(box: dict[str, Path]) -> None:
    _run(box, "--no-check")
    n = len(_calls(box))
    r = _run(box, "--no-check")
    assert r.returncode == 0 and len(_calls(box)) == n
    assert _log(box).count("skipped, already done") == 5
    r = _run(box, "--no-check", "--force", "--only", "bank_ai")
    assert r.returncode == 0 and len(_calls(box)) == n + 1


def test_a_failed_step_is_logged_the_queue_goes_on_and_the_next_run_retries_it(box: dict[str, Path]) -> None:
    r = _run(box, "--no-check", env={"FAKE_FAIL": "gen_personal"})
    assert r.returncode == 1
    log = _log(box)
    assert "STEP gen_personal: FAILED rc=7" in log and "STEP bank_ai: done" in log and "boom" in log
    assert not (box["jobs"] / "state" / "gen_personal.done").exists()
    assert (box["jobs"] / "state" / "gen_gold4.done").exists()
    before = len(_calls(box))
    assert _run(box, "--no-check").returncode == 0
    assert len(_calls(box)) == before + 1  # only gen_personal ran again
    assert (box["jobs"] / "state" / "gen_personal.done").exists()


def test_list_only_and_dry_run(box: dict[str, Path]) -> None:
    r = _run(box, "--dry-run")
    assert r.returncode == 0 and "would run" in r.stdout
    assert "cis_read" in r.stdout and "property_docs" in r.stdout
    assert not box["jobs"].exists() and not _calls(box)  # touches nothing
    _run(box, "--no-check", "--only", "gen_gold4,bank_ai")
    assert [c.split(" :: ")[1].split()[0] for c in _calls(box)][0] == "evals/gold/gen_gold4.py"
    assert len(_calls(box)) == 2
    listing = _run(box, "--list").stdout
    assert "gen_gold4: done" in listing and "gen_personal: pending" in listing and "bank_ai: done" in listing
    assert "cis_read: pending" in listing and "property_docs: pending" in listing
    _run(box, "--no-check", "--only", "cis_read,property_docs")
    listing = _run(box, "--list").stdout
    assert "cis_read: done" in listing and "property_docs: done" in listing


def test_unknown_option_is_an_error(box: dict[str, Path]) -> None:
    r = _run(box, "--nope")
    assert r.returncode == 2 and "unknown option" in r.stderr


@pytest.mark.skipif(shutil.which("curl") is None, reason="needs curl")
def test_a_down_model_server_skips_its_steps(box: dict[str, Path]) -> None:
    dead = "http://127.0.0.1:1/x"
    r = _run(box, env={"QWEN_URL": dead, "OLLAMA_URL": dead})
    assert r.returncode == 1 and not _calls(box)
    assert "the qwen server did not answer" in _log(box) and "the ollama server did not answer" in _log(box)
    assert not list((box["jobs"] / "state").iterdir())


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_only_one_queue_at_a_time(box: dict[str, Path]) -> None:
    env = {
        **os.environ,
        "SPARK_JOBS_DIR": str(box["jobs"]),
        "SPARK_PYTHON": str(box["fake"]),
        "FAKE_CALLS": str(box["calls"]),
        "FAKE_SLEEP": "3",
    }
    first = subprocess.Popen(
        ["bash", str(box["repo"] / "tools" / "spark_queue.sh"), "--no-check", "--only", "gen_gold4"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        for _ in range(50):
            if box["calls"].exists():
                break
            time.sleep(0.1)
        second = _run(box, "--no-check", "--only", "bank_ai")
        assert second.returncode == 3 and "already running" in second.stderr
    finally:
        first.wait(timeout=30)


def test_the_script_never_touches_git_or_installs() -> None:
    code = [ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
    text = "\n".join(code)
    assert not re.search(r"\bgit\b", text)
    assert not re.search(r"pip install|uv sync|uv pip|npm |pnpm ", text)
    assert "ionice -c3" in text and "nice -n 19" in text
    assert os.access(SCRIPT, os.X_OK)
