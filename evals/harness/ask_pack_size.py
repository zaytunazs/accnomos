"""Facts pack size per Ask question, in real prompt tokens: the whole pack against the routed one (app/ask_router.py).

    cd evals && python -m harness.ask_pack_size        # writes runs/ask_40/pack_size.json

Same books and period as harness.ask_40. Each prompt is sent to Glimmer with a one-token reply, so Ollama's
`prompt_eval_count` is the exact number of tokens the model reads (system prompt + facts + question).
"""

from __future__ import annotations

import asyncio
import json
import statistics
from typing import Any

import httpx

from app.ai import ask as ask_ai  # noqa: E402  (harness.ask_40 puts the runtime on sys.path)
from app.ask_router import approx_tokens, pack, route  # noqa: E402
from app.facts import build_facts  # noqa: E402
from harness.ask_40 import BUSINESS, MODELS, PERIOD, QUESTIONS, REPO, seeded_books

OUT = REPO / "evals" / "runs" / "ask_40" / "pack_size.json"


async def prompt_tokens(client: httpx.AsyncClient, facts: dict[str, Any], question: str) -> int:
    cfg = MODELS["glimmer"]
    body = {
        "model": cfg.model,
        "messages": ask_ai._messages(question, facts, []),
        "think": False,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 1},
        "keep_alive": "24h",
    }
    r = await client.post(f"{cfg.base_url}/api/chat", json=body)
    r.raise_for_status()
    return int(r.json()["prompt_eval_count"])


async def main() -> None:
    books = await seeded_books()
    facts = await build_facts(books, PERIOD, BUSINESS)
    rows = []
    async with httpx.AsyncClient(timeout=120) as client:
        for qid, question, _gold, _cite in QUESTIONS:
            routed = pack(facts, route(question, facts))
            rows.append(
                {
                    "id": qid,
                    "whole_pack": await prompt_tokens(client, facts, question),
                    "routed_pack": await prompt_tokens(client, routed, question),
                    "routed_estimate": approx_tokens(routed),
                    "whole_estimate": approx_tokens(facts),
                }
            )
            print(rows[-1], flush=True)
    summary = {
        k: {"median": statistics.median(r[k] for r in rows), "max": max(r[k] for r in rows)}
        for k in ("whole_pack", "routed_pack")
    }
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
