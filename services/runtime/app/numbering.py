"""Document numbers: PREFIX-0001, PREFIX-0002 ... one sequence file per kind of document, in the user's folder.

Used by quotes (QU-), purchase orders (PO-) and repeating templates (RI-/RB-). Invoices and credit notes keep their
own copies of the same logic (app/invoicing.py, app/credit_notes.py), which were written first.

A number is written back to the sequence before it is used, so two drafts never share one, and it is never reused:
unwanted drafts are cancelled or voided, not deleted, which keeps the sequence unbroken.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.books import Books

PREFIX_RE = re.compile(r"[A-Z0-9-]{0,10}")
NUMBER_RE = re.compile(r"[A-Z0-9][A-Z0-9-]{0,23}")


class NumberingError(ValueError):
    """No free number could be found (a sequence file edited backwards beside many existing documents)."""


async def allocate(books: Books, sequence_path: str, default_prefix: str, path_for: Callable[[str], str]) -> str:
    """The next number, e.g. 'QU-0007'. `path_for(number)` is where that document would be stored, so a sequence
    that was reset or hand-edited backwards skips numbers whose documents already exist."""
    default = {"prefix": default_prefix, "next": 1}
    for _ in range(50):
        got: dict[str, Any] = {}

        def bump(seq: dict[str, Any], got: dict[str, Any] = got) -> dict[str, Any]:
            prefix = str(seq.get("prefix", default_prefix)).upper()
            if not PREFIX_RE.fullmatch(prefix):
                prefix = default_prefix
            n = max(1, int(seq.get("next", 1)))
            got["number"] = f"{prefix}{n:04d}"
            return {**seq, "prefix": prefix, "next": n + 1}

        await books._update_json(sequence_path, dict(default), bump)
        if not await books.exists(path_for(got["number"])):
            return got["number"]
    raise NumberingError(f"Could not find a free number; check {sequence_path}")


def safe_number(number: str) -> str:
    """The number if it can only name a file in its own folder; FileNotFoundError otherwise (404 in the routes)."""
    if not NUMBER_RE.fullmatch(number):
        raise FileNotFoundError(number)
    return number
