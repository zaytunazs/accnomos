"""One source of truth for the books folder names (app/paths.py).

* no other Python source spells a numbered folder name as a string literal;
* no source, spec or current doc still uses an old name (they are listed in paths.RENAMED);
* folders.json, apps/web/src/lib/folders.ts and the block in apps/mobile/lib/services/graph.dart are exactly what
  tools/gen_folders.py writes, and carry the same list byte for byte.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app import paths

ROOT = Path(__file__).resolve().parents[3]
PATHS_PY = ROOT / "services/runtime/app/paths.py"
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", "tests", "out", ".next", "build", "apps"}
NUMBERED = re.compile(r"(^|/)0\d [A-Za-z]")
# A known name anywhere in a string ("saved in 06 VAT returns after ..."), current or old.
NAMED = re.compile("|".join(re.escape(n) for n in [*(f.name for f in paths.TOP), *paths.RENAMED]), re.I)


def _hit(value: str) -> bool:
    return bool(NUMBERED.search(value) or NAMED.search(value))


OLD = re.compile("|".join(re.escape(old) for old in paths.RENAMED))
# Current docs and code outside Python; docs/reviews/* are a record of what was true at the time.
DOCS_AND_WEB = [
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/DEMO.md",
    "docs/HMRC.md",
    "docs/HONESTY.md",
    "docs/REMAINING.md",
    "tools/seed_demo.md",
    "apps/web/src",
    "apps/web/e2e",
]


def _gen():
    spec = importlib.util.spec_from_file_location("gen_folders", ROOT / "tools/gen_folders.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def python_sources() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if SKIP_DIRS.intersection(rel.parts[:-1]) or p.name.startswith("test_") or p.name == "conftest.py":
            continue
        if p != PATHS_PY:
            out.append(p)
    return out


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_the_scan_sees_the_modules_that_use_folders() -> None:
    found = {p.relative_to(ROOT).as_posix() for p in python_sources()}
    assert {
        "services/runtime/app/books.py",
        "services/runtime/app/invoicing.py",
        "services/runtime/app/payroll.py",
        "tools/seed_demo.py",
        "packages/connectors/src/accnomos_connectors/msgraph.py",
    } <= found


def test_no_folder_name_literal_outside_paths_py() -> None:
    bad = []
    for p in python_sources():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
                and _hit(node.value)
            ):
                bad.append(f"{p.relative_to(ROOT)}:{node.lineno}: {node.value[:60]!r}")
    assert not bad, "import the name from app/paths.py instead:\n" + "\n".join(bad)


def test_the_literal_check_catches_one() -> None:
    tree = ast.parse(
        '"""Doc: 04 Bank statements."""\nX = "04 Bank statements"\nY = f"{A}/03 Sales/x"\n'
        'Z = "saved in 06 VAT returns after"\nD = "paid on 05 Oct"\n'
    )
    docs = _docstrings(tree)
    hits = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and _hit(n.value)
    ]
    assert sorted(hits) == ["/03 Sales/x", "04 Bank statements", "saved in 06 VAT returns after"]


def _text_files() -> list[Path]:
    out = [p for p in python_sources()]
    for entry in DOCS_AND_WEB:
        path = ROOT / entry
        out += [path] if path.is_file() else [p for p in path.rglob("*") if p.suffix in {".ts", ".tsx", ".mjs"}]
    return [p for p in out if p != _gen().TS_FILE]


def test_no_old_folder_names_left() -> None:
    bad = []
    for p in _text_files():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if OLD.search(line) and "old name" not in line.lower():
                bad.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert not bad, "old folder names (app/paths.py RENAMED):\n" + "\n".join(bad)


def test_generated_files_are_up_to_date() -> None:
    gen = _gen()
    stale = [
        str(path.relative_to(ROOT)) for path, text in gen.render().items() if path.read_text(encoding="utf-8") != text
    ]
    assert not stale, f"run `python tools/gen_folders.py`; out of date: {stale}"


def test_runtime_web_and_android_lists_are_byte_for_byte_equal() -> None:
    gen = _gen()
    fixture = json.loads(gen.JSON_FILE.read_text(encoding="utf-8"))
    canonical = json.dumps(fixture["tree"], ensure_ascii=False).encode()
    ts = re.search(rb"export const FOLDERS: readonly string\[\] = (\[.*?\]);", gen.TS_FILE.read_bytes())
    dart = re.search(rb"const List<String> kBooksFolders = (\[.*?\]);", gen.DART_FILE.read_bytes())
    assert ts and dart
    assert ts.group(1) == canonical == dart.group(1)
    assert fixture["tree"] == list(paths.TREE)
    assert fixture["renamed"] == paths.RENAMED
    assert fixture["readme"] == paths.readme_text()


def test_tree_shape() -> None:
    assert [f.name for f in paths.TOP] == [
        "00 Inbox",
        "01 Receipts",
        "02 Needs a look",
        "03 Sales",
        "04 Bank statements",
        "05 Payroll",
        "06 VAT returns",
        "07 Reports",
    ]
    assert paths.INVOICES == "03 Sales/invoices" and paths.SENT == "03 Sales/invoices/sent"
    assert {paths.INVOICES, paths.SENT, "_System/audit", "_System/Ledger/events"} <= set(paths.TREE)
    assert len(set(paths.TREE)) == len(paths.TREE)
    current = {f.name.casefold() for f in paths.TOP}
    assert not current & {old.casefold() for old in paths.RENAMED}  # no name is both old and current
    assert set(paths.RENAMED.values()) <= {f.name for f in paths.TOP}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("04 Needs a look/a.pdf", "02 Needs a look/a.pdf"),
        ("03 bank statements/2026-09-30_starling.csv", "04 Bank statements/2026-09-30_starling.csv"),
        ("05 VAT returns", "06 VAT returns"),
        ("04 Bank statements/a.csv", "04 Bank statements/a.csv"),
        ("_System/docs/x.json", "_System/docs/x.json"),
        ("05 VAT returnsX/a", "05 VAT returnsX/a"),
    ],
)
def test_upgrade(old: str, new: str) -> None:
    assert paths.upgrade(old) == new


def test_readme_lists_every_top_folder() -> None:
    text = paths.readme_text()
    assert all(f"- {f.name}: " in text for f in paths.TOP)
    assert "SAMPLE — FICTIONAL COMPANY" in text and not OLD.search(text)
