"""Input validation shared by the routes: strict request bodies and file names.

(VRNs are checked where they are accepted: contacts.edit here, the `Vrn` path type in the HMRC relay;
period keys by the route patterns, `^[A-Za-z0-9#]{4}$`.)

File names arrive from users (uploads) and from third parties (mail attachments, model output) and end up as
path segments inside the user's own cloud folder, so a name must never be able to climb out of it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_NAME = 200


class StrictBody(BaseModel):
    """Base for every JSON request body: unknown fields are an error, not silently ignored."""

    model_config = ConfigDict(extra="forbid")


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
