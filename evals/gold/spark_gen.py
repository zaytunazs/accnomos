"""Shared pieces for the Spark gold generators (gen_gold4.py, gen_personal.py).

* ``LABEL`` is written with the real em dash (U+2014). Every file the generators write goes through ``write_text`` /
  ``write_json``, which refuse content that does not contain the exact label (a previous script wrote
  question marks in place of the dash through an encoding accident) and always open files as UTF-8.
* ``Qwen`` talks to the local vLLM (OpenAI-compatible); ``StubQwen`` answers the same calls from a table of handlers so
  the generators run offline (``--stub`` / ``--dry-run`` and the tests).
* Name checks (``is_real``) keep real trading names and brands out of the fictional documents.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from gen_gold_v2 import REAL, REAL_PHRASES  # noqa: E402  (the same real-name list the 061-200 set used)

LABEL = "SAMPLE — FICTIONAL COMPANY"  # U+2014 EM DASH between SAMPLE and FICTIONAL
BIZ = "Bramblewood Joinery Ltd"
QWEN_URL = "http://127.0.0.1:8000/v1/chat/completions"
QWEN_MODEL = "qwen3.8-27b"

# Words in the 061-200 real-name list that are ordinary English and would reject innocent names.
_GENERIC = {"power", "water", "united", "yorkshire", "british", "royal", "mail", "gas", "three", "sage", "apple", "jet"}
REAL_BRANDS = [
    *("bostik", "evo-stik", "evostik", "gorilla", "3m", "stanley", "dewalt", "makita", "bosch", "tesa", "scotch"),
    *("rawlplug", "spax", "reisser", "timco", "hilti", "ronseal", "polycell", "unibond", "mirka", "norton"),
    *("festool", "kreg", "uvex", "honeywell", "jsp", "portwest", "mapei", "sika", "everbuild", "toolstation"),
    *("screwfix", "wickes", "jewson", "howdens", "travis"),
]


def is_real(name: str) -> bool:
    low = name.lower()
    words = set(re.findall(r"[a-z0-9&.\-]+", low))
    singles = {w for w in REAL if " " not in w} - _GENERIC
    return any(p in low for p in REAL_PHRASES) or bool(words & singles) or bool(words & set(REAL_BRANDS))


def vrn(rng: random.Random) -> str:
    """Fictional-looking GB VRN: leading 0 block, valid mod-97 checksum (same scheme as gen_gold_v2)."""
    d = [0, rng.randint(0, 9), rng.randint(0, 9)] + [rng.randint(0, 9) for _ in range(4)]
    s = sum(x * w for x, w in zip(d, (8, 7, 6, 5, 4, 3, 2), strict=True))
    chk = 97 - (s % 97)
    digits = "".join(map(str, d)) + f"{chk:02d}"
    return f"GB {digits[:3]} {digits[3:7]} {digits[7:]}"


def vat_ok(v: str) -> bool:
    d = re.sub(r"\D", "", v)
    if len(d) != 9:
        return False
    w = sum(int(c) * k for c, k in zip(d[:7], range(8, 1, -1), strict=False)) + int(d[7:])
    return w % 97 == 0 or (w + 55) % 97 == 0


def m(pence: int | float) -> str:
    return f"{pence / 100:,.2f}"


def vat_pence(net_pence: int, rate: int = 20) -> int:
    """VAT on a net amount in whole pence, half up (integer arithmetic only)."""
    return (net_pence * rate * 2 + 100) // 200


def centre(s: str, w: int = 46) -> str:
    return s.center(w).rstrip()


def lr(left: str, right: str, w: int = 46) -> str:
    left = left[: max(1, w - len(right) - 1)]
    return left + " " * (w - len(left) - len(right)) + right


# ------------------------------------------------------------------------------------------- guarded writing


class LabelError(ValueError):
    """Content that should carry the sample label does not."""


def require_label(text: str, where: str = "") -> None:
    if LABEL not in text:
        raise LabelError(f"{where or 'content'} does not contain the exact label {LABEL!r}")


def write_text(path: Path, text: str, *, label: bool = True) -> None:
    """UTF-8 write. With ``label`` (default) the exact label must be in the text."""
    if label:
        require_label(text, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, obj: Any, *, label: bool = True) -> None:
    write_text(path, json.dumps(obj, indent=1, ensure_ascii=False), label=label)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ the models


class QwenError(RuntimeError):
    pass


class Qwen:
    """Qwen3.8-27B on the Spark's vLLM. ``ask`` returns the parsed JSON object; ``kind``/``hint`` are for the stub."""

    SYSTEM = (
        "You invent entirely fictional UK businesses, products and people for accounting test data. "
        "Never use real company or brand names. Reply with JSON only."
    )

    def __init__(self, url: str = QWEN_URL, model: str = QWEN_MODEL, timeout: int = 300) -> None:
        self.url, self.model, self.timeout = url, model, timeout
        self.calls = 0

    def ask(
        self,
        prompt: str,
        *,
        kind: str = "",
        hint: dict[str, Any] | None = None,
        seed: int | None = None,
        max_tokens: int = 2200,
        temperature: float = 0.9,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": self.SYSTEM}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if seed is not None:
            body["seed"] = seed
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                text = json.load(r)["choices"][0]["message"]["content"]
            obj = json.loads(text)
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, OSError) as exc:
            raise QwenError(f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(obj, dict):
            raise QwenError("reply was not a JSON object")
        return obj


class StubQwen:
    """Offline stand-in: ``handlers[kind](hint)`` returns the object Qwen would. Never touches the network."""

    def __init__(self, handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]) -> None:
        self.handlers = handlers
        self.calls = 0

    def ask(self, prompt: str, *, kind: str = "", hint: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        self.calls += 1
        if kind not in self.handlers:
            raise QwenError(f"stub has no handler for {kind!r}")
        return self.handlers[kind](hint or {})


def ask_validated(
    client: Any,
    prompt: str,
    check: Callable[[dict[str, Any]], str | None],
    *,
    kind: str,
    hint: dict[str, Any] | None = None,
    attempts: int = 5,
    log: Callable[[str], None] = print,
    **kw: Any,
) -> dict[str, Any]:
    """Ask until ``check(reply)`` returns None (valid) or give up. A bad reply is never repaired, only re-asked."""
    last = ""
    base_seed = kw.pop("seed", None)
    for i in range(attempts):
        try:
            seed = None if base_seed is None else base_seed + i
            reply = client.ask(prompt, kind=kind, hint=hint, seed=seed, **kw)
            problem = check(reply)
        except QwenError as exc:
            problem = f"qwen error {exc}"
            time.sleep(min(30, 2**i))
        if problem is None:
            return reply
        last = problem
        log(f"  retry {kind} ({i + 1}/{attempts}): {problem}")
    raise QwenError(f"{kind}: no valid reply after {attempts} attempts; last problem: {last}")
