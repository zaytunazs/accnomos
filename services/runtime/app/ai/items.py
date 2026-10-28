"""Which differently-named items are the same product? The model may only suggest; code decides (app/prices.py).

The model sees item names only (no prices, suppliers or dates) as numbered pairs code picked as possible matches,
and answers same / not same for each. app/prices.py counts a "same" only where its own rules agree (same kind of
measure, widths within tolerance, enough name words in common); everything else stays a possible match for the
user to confirm or reject.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.schemas import strict_json_schema

PAIRS_MAX = 30

SYSTEM_PROMPT = (
    "You help a UK small business owner tidy their purchase history. You get numbered pairs of item names from "
    "their receipts. For each pair, say whether both names are the same product or an equivalent one a buyer "
    "would happily swap (same thing, same size; a different brand is fine). Different sizes, grades or kinds are "
    "not the same. Answer every pair, by its number. Never mention prices."
)


class PairVerdict(BaseModel):
    pair: int
    same: bool


class PairVerdicts(BaseModel):
    verdicts: list[PairVerdict]


def prompt(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f'{i}. "{a}" | "{b}"' for i, (a, b) in enumerate(pairs, start=1))


async def same_product(pairs: list[tuple[str, str]], cfg: AiConfig) -> tuple[list[bool | None], str | None]:
    """One verdict per pair (None where the model gave none), and a note when the model could not be used."""
    pairs = pairs[:PAIRS_MAX]
    if not pairs:
        return [], None
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt(pairs)}]
    try:
        raw = await ask_ai.call_json_model(messages, cfg, strict_json_schema(PairVerdicts), "item_matches")
        out = PairVerdicts.model_validate(parse_model_json(raw))
    except (ExtractionError, ValidationError):
        return [None] * len(pairs), "The model's reply was not in the expected format."
    except Exception as exc:  # noqa: BLE001  model trouble: the possible matches stay for the user
        return [None] * len(pairs), ask_ai._trouble(exc, cfg)
    got: dict[int, bool] = {v.pair: v.same for v in out.verdicts}
    return [got.get(i) for i in range(1, len(pairs) + 1)], None
