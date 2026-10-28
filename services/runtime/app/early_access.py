"""Early-adopter list: people who sign up before the public launch get 3 months free and one email at launch.

The one thing the runtime keeps. It is the operator's marketing list (controller: Zaytuna Business Services Ltd),
not anyone's books, and it is off unless EARLY_ACCESS_ENABLED=1 (docs/SECURITY.md, docs/PRODUCTION.md).

Storage: JSON lines in EARLY_ACCESS_FILE (default /data/early-access.jsonl, the runtime's data volume), one line
per sign-up, appended. A second sign-up with the same email appends a newer line; the newest line wins and the
first sign-up time is kept. Erasure is the one rewrite: `delete --email` drops every line for that address.

Owner tools (no web admin):
    python -m app.early_access count
    python -m app.early_access export --csv out.csv     (`--csv -` writes to stdout)
    python -m app.early_access delete --email someone@example.co.uk
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TextIO

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.security import TokenBucket

try:  # serialises the server's appends with the owner's `delete` (POSIX only; the server runs in Linux Docker)
    import fcntl
except ImportError:  # pragma: no cover  Windows dev box: the in-process lock still covers the server itself
    fcntl = None

# Shown next to the unticked checkbox (apps/web/src/lib/early-access.ts) and stored with every record, so each
# record says what the person agreed to. The route refuses any other wording.
CONSENT_TEXT = "Email me once Accnomos launches, with my 3 months free. I can unsubscribe any time."
BusinessType = Literal["company", "sole_trader", "personal", "accountant"]
BUSINESS_TYPES: tuple[str, ...] = ("company", "sole_trader", "personal", "accountant")
DEFAULT_FILE = "/data/early-access.jsonl"
FIELDS = ("email", "name", "business_type", "heard", "source", "consent", "consent_text", "first_at", "at")

# Practical address check (no DNS): one @, a dotted domain, no spaces or angle brackets. 254 is the SMTP path limit.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?"
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@" + _LABEL + r"(?:\." + _LABEL + r")+")
_SOURCE = re.compile(r"/[A-Za-z0-9/_-]{0,99}")
_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("EARLY_ACCESS_ENABLED", "0").strip() == "1"


def data_file() -> Path:
    return Path(os.getenv("EARLY_ACCESS_FILE", "").strip() or DEFAULT_FILE)


def normalise_email(raw: str) -> str | None:
    """Trimmed and lower-cased, or None if it does not look like an address."""
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL.fullmatch(email) or ".." in email:
        return None
    return email


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path.with_name(path.name + ".lock"), "a") as lock:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_EX)
            yield


def _lines(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                with contextlib.suppress(json.JSONDecodeError):  # a torn last line (power cut) must not lose the rest
                    yield json.loads(line)


def records(path: Path | None = None) -> list[dict[str, Any]]:
    """The current list: one record per email, the newest line's details with the first sign-up time."""
    out: dict[str, dict[str, Any]] = {}
    for line in _lines(path or data_file()):
        email = line.get("email")
        if not isinstance(email, str):
            continue
        first = out.get(email, {}).get("first_at", line.get("at"))
        out[email] = {**line, "first_at": first}
    return sorted(out.values(), key=lambda r: str(r.get("first_at")))


def add(record: dict[str, Any], path: Path | None = None) -> None:
    """Append one sign-up line. The file is created owner-only (0600)."""
    path = path or data_file()
    with _locked(path):
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())


def delete(email: str, path: Path | None = None) -> int:
    """Right to erasure: rewrite the file without any line for `email`. Returns how many lines were removed."""
    path = path or data_file()
    target = email.strip().lower()
    with _locked(path):
        if not path.exists():
            return 0
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        keep = [ln for ln in lines if _line_email(ln) != target]
        removed = len(lines) - len(keep)
        if removed:
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".early-access-")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(keep)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        return removed


def _line_email(line: str) -> str | None:
    try:
        value = json.loads(line).get("email")
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def export_csv(out: TextIO, path: Path | None = None) -> int:
    rows = records(path)
    writer = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # A leading = + - @ makes spreadsheets run the cell as a formula: quote it as text.
        writer.writerow({k: _cell(row.get(k)) for k in FIELDS})
    return len(rows)


def _cell(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


# --------------------------------------------------------------------------- #
# POST /public/early-access
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/public", tags=["public"])
# Its own per-IP bucket on top of the runtime's 60 a minute: a sign-up form needs a handful, not sixty.
_RATE = int(os.getenv("EARLY_ACCESS_PER_MIN", "5"))
LIMITER: TokenBucket | None = TokenBucket(_RATE) if _RATE > 0 else None


class EarlyAccessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    name: str | None = Field(default=None, max_length=100)
    business_type: BusinessType
    heard: str | None = Field(default=None, max_length=200)  # "How did you hear about us?" (optional)
    consent: bool
    consent_text: str = Field(max_length=200)  # the wording the page showed; must be CONSENT_TEXT
    source: str = Field(default="/", max_length=100)  # the page the form was on, e.g. "/" or "/judges"
    website: str | None = Field(default=None, max_length=200)  # honeypot: hidden from people, filled by bots


class EarlyAccessOut(BaseModel):
    ok: bool
    message: str


DONE = EarlyAccessOut(ok=True, message="You're on the list — we'll email you once at launch")


def _text(value: str | None) -> str | None:
    value = " ".join((value or "").split())  # collapse newlines and tabs: one line per record in the CSV too
    return value or None


@router.post("/early-access", response_model=EarlyAccessOut)
async def early_access(body: EarlyAccessIn, request: Request) -> EarlyAccessOut | JSONResponse:
    """Join the early-adopter list. No sign-in. New and repeat sign-ups get the same answer, so the form never
    says whether an address is already on the list."""
    if not enabled():
        raise HTTPException(503, "Early-access sign-ups are not open on this server")
    if LIMITER:
        wait = LIMITER.take(request.client.host if request.client else "unknown")
        if wait:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many sign-ups from here; try again in a minute"},
                headers={"Retry-After": str(max(1, int(wait) + 1))},
            )
    if body.website:  # a bot filled the hidden field: look successful, keep nothing
        return DONE
    email = normalise_email(body.email)
    if not email:
        raise HTTPException(400, "Enter a valid email address")
    if not body.consent:
        raise HTTPException(400, "Tick the box to agree to the launch email")
    if body.consent_text.strip() != CONSENT_TEXT:
        raise HTTPException(400, "The consent wording has changed; reload the page and try again")
    source = body.source.strip() or "/"
    if not _SOURCE.fullmatch(source):
        raise HTTPException(400, "Bad source page")
    add(
        {
            "email": email,
            "name": _text(body.name),
            "business_type": body.business_type,
            "heard": _text(body.heard),
            "source": source,
            "consent": True,
            "consent_text": CONSENT_TEXT,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    return DONE


# --------------------------------------------------------------------------- #
# Owner CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.early_access", description="Early-adopter list owner tools")
    parser.add_argument("--file", type=Path, help="list file (default: EARLY_ACCESS_FILE, else " + DEFAULT_FILE + ")")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("count", help="how many people are on the list")
    exp = sub.add_parser("export", help="write the current list as CSV")
    exp.add_argument("--csv", required=True, help="output file, or - for stdout")
    rm = sub.add_parser("delete", help="erase every record for one email (right to erasure, unsubscribe)")
    rm.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    path: Path = args.file or data_file()

    if args.cmd == "count":
        print(len(records(path)))
    elif args.cmd == "export":
        if args.csv == "-":
            n = export_csv(sys.stdout, path)
        else:
            fd = os.open(args.csv, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # personal data: owner-only
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                n = export_csv(f, path)
        print(f"exported {n} record(s)", file=sys.stderr)
    else:
        n = delete(args.email, path)
        print(f"deleted {n} line(s) for {args.email.strip().lower()}" if n else "no record for that email")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
