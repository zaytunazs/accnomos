"""Judge-facing docs stay in step with the repo: one README feature table, cited files exist,
sheet list matches the code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.projection import SHEETS

ROOT = Path(__file__).resolve().parents[3]
DOCS = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/HONESTY.md",
    "docs/DEMO.md",
    "docs/REMAINING.md",
    *(f"docs/submission/{n}.md" for n in ("DESCRIPTION", "META_MODELS", "VIDEO_SCRIPT", "JUDGING", "CHECKLIST")),
)
# A backticked name with a code-ish extension;
# OneDrive paths (`_System/...`, `Books.xlsx`, `*.json`) are not repo files.
CITED = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|ts|tsx|dart|md|yml|yaml|mjs|png))`")


def _what_works_rows() -> list[str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## What works today", 1)[1].split("\n## ", 1)[0]
    lines = section.strip("\n").splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("| Feature"))
    table = []
    for ln in lines[first:]:
        if not ln.startswith("|"):
            break
        table.append(ln)
    assert not any(ln.startswith("|") for ln in lines[first + len(table) :]), (
        "the table is split by a blank or text line"
    )
    return table[2:]


def test_readme_what_works_is_one_table_with_one_row_per_feature():
    rows = _what_works_rows()
    features = [r.split("|")[1].strip() for r in rows]
    assert len(features) >= 15 and len(features) == len(set(features))
    assert all(r.count("|") == 5 for r in rows), "every row has the four columns"


@pytest.mark.parametrize("doc", DOCS)
def test_files_cited_in_docs_exist(doc: str):
    repo = [
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*")
        if p.is_file() and not {"node_modules", ".git", ".venv", ".next", "out"} & set(p.parts)
    ]
    missing = [
        ref
        for ref in sorted(set(CITED.findall((ROOT / doc).read_text(encoding="utf-8"))))
        if not any(f == ref or f.endswith("/" + ref) for f in repo)
    ]
    assert not missing, f"{doc} cites files that do not exist: {missing}"


def test_architecture_lists_the_books_xlsx_sheets_the_code_writes():
    arch = (ROOT / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    row = next(ln for ln in arch.splitlines() if ln.startswith("| `Books.xlsx`"))
    assert re.findall(r"`([\w&]+)`", row.split("sheets", 1)[1])[: len(SHEETS)] == list(SHEETS)
