"""The help centre's articles, and the support assistant's answers from them.

The articles are `help_articles.json`, a copy of the website's source (apps/web/src/content/help/articles.json, copied
by tools/sync_help_articles.py; tests/test_support.py fails when they differ). Each has a stable `id`, which is its
page (`/help/<id>`) and what an answer cites.

Grounding is done in code, not trusted to a model: retrieval is a weighted word match over each article's title,
keywords, summary, steps and troubleshooting, and the answer quotes the matched article's own steps (or its matching
"if this goes wrong" line) word for word, with the link. No model writes steps, so none can be invented. When nothing
matches well enough, or the user reports something broken, the answer says so and offers a support ticket card
instead of guessing.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.public_chat import terms

ARTICLES_PATH = Path(__file__).with_name("help_articles.json")
MIN_SCORE = 2.5  # below this, no article is a confident match
SITE = "https://accnomos.com"

# "How do I…", "where can I…", "I can't…", "… isn't working": a question about using the app, or a problem.
_HOW = re.compile(
    r"^\s*(?:please\s+)?(?:how\s+(?:do|can|should|would)\s+(?:i|we|you)\b|how\s+to\b|where\s+(?:do|can|is|are)\s+(?:i|we|the)\b"
    r"|what\s+do\s+i\s+do\s+(?:if|when|about)\b|can\s+you\s+(?:show|tell|explain)\s+(?:me\s+)?how\b|help\s+me\b|is\s+there\s+a\s+way\s+to\b)",
    re.I,
)
_PROBLEM = re.compile(
    r"\b(?:can'?t|cannot|couldn'?t|won'?t|doesn'?t|didn'?t|isn'?t|aren'?t|not\s+(?:working|loading|showing|appearing|"
    r"syncing|connecting|saving|sending|possible)|broken|bug|error|errors|crash(?:es|ed|ing)?|fail(?:s|ed|ing)?|stuck|"
    r"wrong|missing|disappeared|frozen|keeps?\s+(?:failing|saying|asking))\b",
    re.I,
)
_TICKET = re.compile(
    r"\b(?:support\s+ticket|raise\s+a\s+ticket|open\s+a\s+ticket|create\s+a\s+ticket|contact\s+support|talk\s+to\s+"
    r"(?:a\s+)?(?:human|person|someone)|report\s+(?:a\s+)?(?:bug|problem|issue)|speak\s+to\s+support)\b",
    re.I,
)
_BUG = re.compile(r"\b(?:bug|crash(?:es|ed|ing)?|error|broken|frozen|report\s+(?:a\s+)?(?:bug|problem|issue))\b", re.I)


@dataclass(frozen=True)
class Step:
    title: str
    body: str
    image: str | None = None
    alt: str | None = None


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    summary: str
    category: str
    platforms: tuple[str, ...]
    keywords: tuple[str, ...]
    steps: tuple[Step, ...]
    troubleshooting: tuple[tuple[str, str], ...]
    related: tuple[str, ...] = ()

    @property
    def path(self) -> str:
        return f"/help/{self.id}"

    @property
    def url(self) -> str:
        return f"{SITE}{self.path}"

    def text(self) -> str:
        """Everything a reader sees, for the "never invent steps" check in the tests."""
        parts = [self.title, self.summary]
        parts += [f"{s.title} {s.body}" for s in self.steps]
        parts += [f"{p} {f}" for p, f in self.troubleshooting]
        return "\n".join(parts)


@dataclass
class Match:
    article: Article
    score: float
    trouble: tuple[str, str] | None = None  # the troubleshooting line that matched best, if any


@dataclass
class HelpAnswer:
    answer_md: str
    article: Article | None
    others: list[Article] = field(default_factory=list)
    offer_ticket: bool = False
    is_bug: bool = False


def _article(raw: dict[str, Any]) -> Article:
    return Article(
        id=raw["id"],
        title=raw["title"],
        summary=raw["summary"],
        category=raw["category"],
        platforms=tuple(raw.get("platforms") or ()),
        keywords=tuple(raw.get("keywords") or ()),
        steps=tuple(Step(s["title"], s["body"], s.get("image"), s.get("alt")) for s in raw.get("steps") or ()),
        troubleshooting=tuple((t["problem"], t["fix"]) for t in raw.get("troubleshooting") or ()),
        related=tuple(raw.get("related") or ()),
    )


@lru_cache(maxsize=1)
def articles() -> tuple[Article, ...]:
    data = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    return tuple(_article(a) for a in data["articles"])


def get(article_id: str) -> Article | None:
    return next((a for a in articles() if a.id == article_id), None)


def _bag(text: str) -> set[str]:
    return set(terms(text))


@lru_cache(maxsize=1)
def _index() -> tuple[list[tuple[Article, dict[str, float]]], dict[str, float]]:
    """Per article: term -> weight (title and keywords count most); and each term's inverse document frequency."""
    docs: list[tuple[Article, dict[str, float]]] = []
    df: dict[str, int] = {}
    for a in articles():
        w: dict[str, float] = {}

        def add(text: str, weight: float, w: dict[str, float] = w) -> None:
            for t in _bag(text):
                w[t] = max(w.get(t, 0.0), weight)

        add(" ".join(f"{s.title} {s.body}" for s in a.steps), 1.0)
        add(" ".join(f"{p} {f}" for p, f in a.troubleshooting), 1.0)
        add(a.summary, 1.5)
        add(" ".join(a.keywords), 2.5)
        add(a.title, 3.0)
        docs.append((a, w))
        for t in w:
            df[t] = df.get(t, 0) + 1
    n = len(docs)
    idf = {t: math.log(1 + n / c) for t, c in df.items()}
    return docs, idf


def _phrases(question: str, a: Article) -> float:
    """A keyword phrase said word for word ("bank feed", "sync paypal") is a strong signal."""
    q = f" {question.lower()} "
    return sum(2.0 for k in a.keywords if " " in k and f" {k} " in q or (" " not in k and len(k) > 3 and f" {k} " in q))


def search(question: str, limit: int = 3) -> list[Match]:
    q = _bag(question)
    if not q:
        return []
    docs, idf = _index()
    out: list[Match] = []
    for a, w in docs:
        score = sum(w[t] * idf.get(t, 0.0) for t in q if t in w) + _phrases(question, a)
        if score <= 0:
            continue
        best: tuple[float, tuple[str, str] | None] = (0.0, None)
        for problem, fix in a.troubleshooting:
            hit = len(q & _bag(problem))
            if hit >= 2 and hit > best[0]:
                best = (float(hit), (problem, fix))
        out.append(Match(a, round(score, 3), best[1]))
    out.sort(key=lambda m: m.score, reverse=True)
    # "Get help and raise a ticket" matches every problem sentence ("not working", "error"): it is the fallback, so a
    # real article about the thing that broke goes first unless the user asked for support itself.
    if len(out) > 1 and out[0].article.id == "contact-support" and not wants_ticket(question):
        if out[1].score >= MIN_SCORE:
            out[0], out[1] = out[1], out[0]
    return out[:limit]


def help_intent(question: str) -> bool:
    """A "how do I…" question, a problem report or a request for support: the support assistant answers it."""
    return bool(
        _HOW.search(question) or _TICKET.search(question) or _PROBLEM.search(question) and _mentions_app(question)
    )


def _mentions_app(question: str) -> bool:
    """A problem sentence about the app ("the upload isn't working"), not about the books ("why is my profit wrong")."""
    words = {
        "app",
        "page",
        "button",
        "upload",
        "sign",
        "login",
        "log",
        "sync",
        "connect",
        "link",
        "feed",
        "screen",
        "load",
        "error",
        "bug",
        "crash",
        "android",
        "phone",
        "mic",
        "microphone",
        "voice",
        "paypal",
        "hmrc",
        "onedrive",
        "drive",
        "storage",
        "folder",
        "scan",
        "camera",
        "website",
        "site",
        "email",
        "submit",
        "ticket",
        "support",
    }
    return bool(set(re.findall(r"[a-z]+", question.lower())) & words)


def wants_ticket(question: str) -> bool:
    return bool(_TICKET.search(question))


def is_bug(question: str) -> bool:
    return bool(_BUG.search(question))


def _md_link(a: Article) -> str:
    return f"[{a.title}]({a.path})"


def answer(question: str) -> HelpAnswer:
    """Code's answer: the best article's own steps, quoted, with its link; or an honest "not in the help centre"."""
    found = search(question)
    ticket = wants_ticket(question)
    bug = is_bug(question)
    best = found[0] if found and found[0].score >= MIN_SCORE else None
    floor = max(MIN_SCORE, best.score * 0.5) if best else MIN_SCORE  # "also see" only a close second
    others = [m.article for m in found[1:] if m.score >= floor]
    if best is None:
        text = (
            "I couldn't find that in the help centre, so I won't guess. "
            "You can browse the [help centre](/help), or create a support ticket below and the team will answer."
        )
        return HelpAnswer(text, None, others, offer_ticket=True, is_bug=bug)
    a = best.article
    lines: list[str] = []
    if best.trouble is not None:
        problem, fix = best.trouble
        lines.append(f"From the help article {_md_link(a)}, under *If this goes wrong*:")
        lines.append(f"- **{problem}**: {fix}")
        lines.append("")
        lines.append("The steps in full:")
    else:
        lines.append(f"From the help article {_md_link(a)}:")
    for n, s in enumerate(a.steps, 1):
        lines.append(f"{n}. **{s.title}.** {s.body}")
    if others:
        lines.append("")
        lines.append("Also see " + ", ".join(_md_link(o) for o in others[:2]) + ".")
    if ticket or bug:
        lines.append("")
        lines.append("If that doesn't solve it, create a support ticket below.")
    return HelpAnswer("\n".join(lines), a, others, offer_ticket=ticket or bug, is_bug=bug)


_CATEGORY_BY_ARTICLE = {
    "sign-up-connect-storage": "storage",
    "upload-receipts": "how_to",
    "review-approve": "how_to",
    "bank-feeds": "bank",
    "invoices-paypal-links": "paypal",
    "sync-paypal": "paypal",
    "paypal-disputes": "paypal",
    "bill-pay-paypal": "paypal",
    "paypal-help": "paypal",
    "vat-return": "hmrc_vat",
    "month-end": "how_to",
    "voice-assistant": "how_to",
    "android-app": "mobile",
    "contact-support": "other",
}


def category_for(question: str, article: Article | None) -> str:
    low = question.lower()
    if re.search(r"\b(plan|billing|subscription|trial|price|charged|refund my)\b", low):
        return "billing"
    if "paypal" in low:
        return "paypal"
    if re.search(r"\b(vat|hmrc|mtd)\b", low):
        return "hmrc_vat"
    if is_bug(question):
        return "bug"
    if article is not None:
        return _CATEGORY_BY_ARTICLE.get(article.id, "how_to")
    return "other"


ASK_HOW_SCORE = 6.0  # in the books assistant a "how do I…" goes to the help centre only on a clear match


def route_from_ask(question: str) -> bool:
    """For /books/ask: is this a question for the help centre rather than about the books? "How do I connect my bank
    feed?" is; "how much did I spend on fuel?" and "how can I see my profit?" (no clear article) are not."""
    if wants_ticket(question):
        return True
    found = search(question, limit=1)
    best = found[0].score if found else 0.0
    if _HOW.search(question) and best >= ASK_HOW_SCORE:
        return True
    return bool(_PROBLEM.search(question) and _mentions_app(question) and best >= MIN_SCORE)
