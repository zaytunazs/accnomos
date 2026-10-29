"""Launch check: what is new or changed since the books last saw the folders.

When the app opens it compares 01 Bulk upload and 00 Inbox against what the books
already know (hashes and paths in _System/docs). Listing only: folder listings
carry the name, size, modification date and the provider's content hash, so no
document is ever downloaded here. A file counts as:

    new      no filed document shares its content hash or its name;
    changed  a filed document shares its name but the content hash or the size
             differs, or (when the provider gives no hash) the file was modified
             after the books filed that name;
    known    anything else: already filed, so the check stays quiet about it.

The page runs this after first paint, shows a thin progress bar while it runs
and a small badge ("N new, M changed - Review"), and never blocks rendering.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.books import DOCS, Books
from app.paths import BULK, INBOX

WATCHED = (BULK, INBOX)
MODIFIED_SKEW = timedelta(seconds=60)  # copies land with a fresh mtime; only clearly newer counts


class ChangedFile(BaseModel):
    path: str
    reason: str  # "different content than the filed copy" or "different size ..." or "modified since ..."


class LaunchCheck(BaseModel):
    new: list[str] = []  # paths in the bulk folder or Inbox the books have not filed
    changed: list[ChangedFile] = []
    checked: int = 0  # files listed


def _hex(content_hash: str | None) -> str | None:
    """'sha256:abc...' (Graph, the fake) -> 'abc...'; unhashable providers give None."""
    if not content_hash or ":" not in content_hash:
        return None
    algo, _, hexpart = content_hash.partition(":")
    return hexpart if algo == "sha256" and len(hexpart) == 64 else None


def _modified_after(modified: datetime | None, candidates: list[dict[str, object]]) -> bool:
    """The file's modification date is clearly newer than every filing of this name."""
    if modified is None:
        return False
    try:
        saved = [datetime.fromisoformat(str(m.get("saved_at") or "")) for m in candidates]
    except ValueError:
        return False
    if not saved:
        return False
    latest = max(saved)
    if modified.tzinfo is None and latest.tzinfo is not None:
        return modified.date() > latest.date()  # naive file date against aware filings: dates alone
    if modified.tzinfo is not None and latest.tzinfo is None:
        return modified.replace(tzinfo=None) > latest + MODIFIED_SKEW
    return modified > latest + MODIFIED_SKEW


async def launch_check(books: Books) -> LaunchCheck:
    """List-only diff of the bulk folder and Inbox against the filed documents.

    Reads folder listings and the small _System/docs records only; document
    contents are never downloaded, so this stays fast enough to run on launch.
    """
    listed: list[tuple[str, str | None, int, datetime | None]] = []  # (path, sha256 hex, size, modified)
    for folder in WATCHED:
        for ref in await books.list_files(folder):
            listed.append((ref.path, _hex(ref.content_hash), ref.size, ref.modified))
    known_hashes = await books.known_hashes()
    by_name: dict[str, list[dict[str, object]]] = {}
    for name in known_hashes:
        try:
            raw = await books.storage.read(f"{DOCS}/{name}.json")
        except FileNotFoundError:
            continue
        try:
            meta = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(meta, dict):
            continue
        key = str(meta.get("source_name") or "").casefold()
        if key:
            by_name.setdefault(key, []).append(meta)
        filed = str(meta.get("filed_path") or "").rsplit("/", 1)[-1].casefold()
        if filed and filed != key:
            by_name.setdefault(filed, []).append(meta)
    out = LaunchCheck(checked=len(listed))
    for path, sha, size, modified in listed:
        if sha and sha in known_hashes:
            continue  # byte-identical to a filed document: the scan will say duplicate
        name = path.rsplit("/", 1)[-1].casefold()
        candidates = by_name.get(name, [])
        if not candidates:
            out.new.append(path)
            continue
        same_content = any(sha and m.get("sha256") == sha for m in candidates)
        same_size = any(m.get("size") == size for m in candidates)
        if same_content:
            continue  # the filed copy under the same name
        if sha and any(m.get("sha256") for m in candidates):
            out.changed.append(ChangedFile(path=path, reason="different content than the filed copy under this name"))
        elif not same_size:
            out.changed.append(ChangedFile(path=path, reason="different size than the filed copy under this name"))
        elif _modified_after(modified, candidates):
            out.changed.append(ChangedFile(path=path, reason="modified since the books filed this name"))
        # else: same name and size, no hash from the provider and not clearly newer: the filed copy
    return out
