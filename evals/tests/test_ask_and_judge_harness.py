"""Offline checks for the Ask eval scoring (seeded books, a fake model) and the judge's reply cap."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from harness import ask_40, judge


def test_has_gold_matches_by_value_words_and_name() -> None:
    assert ask_40.has_gold("2803.33", "You owe **£2,803.33** this quarter.")
    assert ask_40.has_gold("-620.00", "down £620.00 on last quarter")  # sign does not matter
    assert not ask_40.has_gold("2803.33", "You owe £2,803.34.")
    assert ask_40.has_gold("3", "There were three sales.") and not ask_40.has_gold("3", "There were thirty sales.")
    assert ask_40.has_gold("Oakhurst Timber & Tools", "your biggest supplier was oakhurst timber & tools")


@pytest.fixture(scope="module")
def seeded() -> tuple:
    async def build() -> tuple:
        books = await ask_40.seeded_books()
        return books, await ask_40.build_facts(books, ask_40.PERIOD, ask_40.BUSINESS)

    return asyncio.run(build())


def _reply(answer: str, value: str, source: str) -> str:
    return json.dumps(
        {
            "answer_md": answer,
            "key_numbers": [{"label": "Box 5", "value": value, "source": source}],
            "citations": [source],
            "suggested_actions": [],
            "confidence": "high",
        }
    )


def test_ask_scoring_through_the_app_path_with_a_fake_model(seeded: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    books, facts = seeded
    box5 = Decimal(facts["this_period"]["vat"]["box5"])
    source = facts["sources"][0]
    replies = iter(
        [
            _reply(f"You owe £{box5:,.2f}.", f"£{box5:,.2f}", source),
            _reply(f"You owe £{box5 + 1000:,.2f}.", f"£{box5 + 1000:,.2f}", source),
        ]
    )

    async def fake_call(messages, cfg, *args, **kwargs):  # type: ignore[no-untyped-def]
        return next(replies)

    monkeypatch.setattr(ask_40.ask_ai, "_call_model", fake_call)
    ask_40.capture_raw_replies()  # wraps the fake, as it wraps the real call in a run
    qid, prompt, gold, cite = ask_40.QUESTIONS[0]

    async def one() -> dict:
        raw: list[str] = []
        ask_40._RAW.set(raw)
        a = await ask_40.ask_one(books, ask_40.MODELS["glimmer"], prompt, raw)
        return ask_40.score_question(qid, prompt, gold, cite, facts, a, raw)

    right = asyncio.run(one())
    assert (
        right["numbers_exact"]
        and right["citation_present"]
        and right["no_invented_figure"]
        and right["fallback"] is None
    )
    # An invented figure: counted against the raw reply, replaced by grounding, so nothing invented reaches the user.
    wrong = asyncio.run(one())
    assert (
        not wrong["no_invented_figure"]
        and wrong["raw_invented"]
        and wrong["fallback"]
        and wrong["shipped_invented"] == []
    )


def test_judge_sends_the_raised_cap_and_records_stop_reason() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"field_errors": [], "sev'}],
                "stop_reason": "max_tokens",
                "usage": {"output_tokens": 4000},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        verdict = judge.judge_one(client, "claude-haiku-5-5", {"supplier": {"name": "A"}}, {"supplier_name": "A"})
    assert seen["max_tokens"] == judge.MAX_TOKENS == 4000
    assert verdict["severity"] == "unparsed" and verdict["stop_reason"] == "max_tokens"
