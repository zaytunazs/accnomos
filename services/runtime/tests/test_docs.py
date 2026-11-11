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


# Owner's rule (4 Nov 2026): the public docs name Meta's models only; anything else is generic ("a local open-weight
# model", "a hosted GPU", "other AI tools"). Prose only: code spans keep env names and ids (`BASETEN_API_KEY`,
# `spark,anthropic`), and `claude/...` branch names are git refs. The same list guards the public chat
# (tests/test_public_chat.py) and every rendered web page (apps/web/scripts/prelaunch-words.mjs).
# Since 11 Nov 2026 Anthropic is the server's backup AI provider and a processor of customer documents, which the
# privacy text must name: "Anthropic" is allowed. Its model names ("Claude ...") stay out of public prose: customers
# are not told which models read their documents.
NON_META_NAMES = re.compile(
    r"whisper|kokoro|ollama|vllm|qwen|comfyui|\bdgx\b|\bnvidia\b|\bl40s\b|baseten|\bmodal\b|\bllama\b|\bclaude\b(?!/)"
    r"|openai|\bchatgpt\b|\bgpt-\d|\bgemini\b|\bmistral\b|deepseek|hugging ?face|systran|speaches",
    re.IGNORECASE,
)
PUBLIC_DOCS = sorted(
    {
        "README.md",
        "evals/README.md",
        "services/runtime/app/public_kb.md",
        *(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").glob("*.md")),
        *(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs/submission").rglob("*.md")),
    }
)


def _prose(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_public_docs_name_no_non_meta_model_or_vendor(doc: str):
    hits = [
        m.group(0) + ": " + line.strip()[:120]
        for line in _prose((ROOT / doc).read_text(encoding="utf-8")).splitlines()
        for m in NON_META_NAMES.finditer(line)
    ]
    assert hits == [], f"{doc} names a non-Meta model, tool, host or vendor in its prose"
