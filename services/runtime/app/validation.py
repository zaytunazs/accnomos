"""Input validation shared by the routes: strict request bodies and file names.

(VRNs are checked where they are accepted: contacts.edit here, the `Vrn` path type in the HMRC relay;
period keys by the route patterns, `^[A-Za-z0-9#]{4}$`.)

File names arrive from users (uploads) and from third parties (mail attachments, model output) and end up as
path segments inside the user's own cloud folder, so a name must never be able to climb out of it.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, BeforeValidator, ConfigDict

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_NAME = 200


def _day(v: Any) -> Any:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, str) and _ISO_DAY.fullmatch(v):
        return v  # pydantic then checks it is a real day
    raise ValueError("dates are written YYYY-MM-DD")


def _pence(v: Any) -> Any:
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    raise ValueError("money is a whole number of pence")


#: A calendar date in a request body: "YYYY-MM-DD" only (lax pydantic also takes 1700000000 or "2026-10-27T00:00").
Day = Annotated[date, BeforeValidator(_day)]
#: Money in a request body: a whole number of pence as an integer (not 12.0, "12" or true).
Pence = Annotated[int, BeforeValidator(_pence)]


class StrictBody(BaseModel):
    """Base for every JSON request body: unknown fields are an error, not silently ignored.

    A model that is also read back from the user's files is loaded with `**LENIENT` (extra="ignore"), so a
    hand-edited file with an extra key still opens."""

    model_config = ConfigDict(extra="forbid")


class _Lenient(TypedDict):
    extra: Literal["ignore"]


LENIENT: _Lenient = {"extra": "ignore"}  # Model.model_validate(raw, **LENIENT) for files in the user's folder


class UnsafeName(ValueError):
    pass


def check_name(name: str) -> str:
    """Return `name` if it is a plain file name; raise UnsafeName for anything that is a path or could act as
    one: '.', '..', separators, absolute or drive paths, control characters, empty or over-long names."""
    if not name or len(name) > MAX_NAME:
        raise UnsafeName("file name is empty or too long")
    if _CONTROL.search(name):
        raise UnsafeName("file name contains control characters")
    if "/" in name or "\\" in name or re.match(r"[A-Za-z]:", name):
        raise UnsafeName("file name must not contain a path")
    if name.strip(" .") == "":  # '.', '..', '...', ' . '
        raise UnsafeName("file name must not be '.' or '..'")
    return name
