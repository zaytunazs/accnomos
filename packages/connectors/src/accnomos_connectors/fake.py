"""In-memory StorageProvider used by contract tests and by the runtime's own tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from accnomos_connectors.base import ConflictError, FileRef, StorageProvider


class FakeStorageProvider(StorageProvider):
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.folders: set[str] = {""}
        self._log: list[tuple[str, str]] = []

    def _ref(self, path: str, is_folder: bool = False) -> FileRef:
        data = self.files.get(path, b"")
        etag = hashlib.sha1(data).hexdigest()[:12] if not is_folder else None
        return FileRef(
            id=f"fake:{path}", path=path, name=path.rsplit("/", 1)[-1], size=len(data), etag=etag,
            modified=datetime.now(UTC), is_folder=is_folder,
        )

    async def ensure_root(self) -> FileRef:
        return self._ref("", True)

    async def ensure_folder(self, path: str) -> FileRef:
        parts = path.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            self.folders.add("/".join(parts[:i]))
        return self._ref(path.strip("/"), True)

    async def list(self, path: str) -> list[FileRef]:
        prefix = path.strip("/")
        prefix = prefix + "/" if prefix else ""
        out: list[FileRef] = []
        for f in sorted(self.folders):
            if f and f.startswith(prefix) and "/" not in f[len(prefix):]:
                out.append(self._ref(f, True))
        for p in sorted(self.files):
            if p.startswith(prefix) and "/" not in p[len(prefix):]:
                out.append(self._ref(p))
        return out

    async def read(self, path: str) -> bytes:
        return self.files[path.strip("/")]

    async def write(self, path: str, data: bytes, *, if_match: str | None = None) -> FileRef:
        path = path.strip("/")
        if if_match is not None and path in self.files and self._ref(path).etag != if_match:
            raise ConflictError(path)
        if "/" in path:
            await self.ensure_folder(path.rsplit("/", 1)[0])
        self.files[path] = data
        self._log.append(("write", path))
        return self._ref(path)

    async def move(self, path: str, new_path: str) -> FileRef:
        path, new_path = path.strip("/"), new_path.strip("/")
        self.files[new_path] = self.files.pop(path)
        self._log.append(("move", f"{path} -> {new_path}"))
        return self._ref(new_path)

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        start = int(cursor or 0)
        changed = [self._ref(p.split(" -> ")[-1]) for _, p in self._log[start:] if p.split(" -> ")[-1] in self.files]
        return changed, str(len(self._log))
