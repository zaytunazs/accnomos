"""The plain-English rationale for a day plan. Ordering and times come from code (app/planner.py).

The model sees the computed plan as JSON and returns `{"rationale_md": ...}`. Code then checks it: every
clock time it quotes must be a time in the plan, and every other figure must be in the facts. Anything else
(or no AI configured, or the model failing) and the rationale is written by code instead.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.planner import ADMIN_MIN, HHMM_RE, LUNCH_MIN, TRAVEL_OTHER_MIN, TRAVEL_SAME_MIN, Plan, hhmm, uk_day

RATIONALE_MAX = 900

SYSTEM_PROMPT = (
    "You explain a proposed working day to a UK tradesperson in plain UK English: short, friendly, as 2 to 5 "
    f"markdown '-' bullets, under {RATIONALE_MAX} characters. You are given PLAN as JSON, worked out by code "
    "from their calendar, open jobs and VAT deadlines. Say why it is ordered this way (visits grouped by "
    "postcode district to cut driving), mention lunch and any admin, and repeat any warnings simply. "
    "Rules: quote clock times only exactly as they appear in PLAN (HH:MM); never change the order or times, "
    "never add visits, never estimate distances or miles. Return JSON {\"rationale_md\": \"...\"}."
)


class PlanModelOutput(BaseModel):
    rationale_md: str


def facts(plan: Plan) -> dict[str, Any]:
    """What the model is shown: the plan in local times, nothing else from the books."""
    return {
        "day": uk_day(plan.date),
        "working_hours": [hhmm(plan.window[0]), hhmm(plan.window[1])],
        "items": [
            {"kind": i.kind, "start": hhmm(i.start), "end": hhmm(i.end), "title": i.title}
            for i in plan.items
        ],
        "visit_districts_in_order": plan.districts,
        "rules": {
            "travel_minutes_same_district": TRAVEL_SAME_MIN, "travel_minutes_new_district": TRAVEL_OTHER_MIN,
            "lunch_minutes": LUNCH_MIN, "admin_minutes": ADMIN_MIN,
        },
        "warnings": plan.warnings,
    }


def code_rationale(plan: Plan) -> str:
    """The rationale written by code: used without AI and whenever the model's words fail the checks."""
    visits = [i for i in plan.items if i.kind == "visit"]
    lines: list[str] = []
    if visits:
        where = ", then ".join(plan.districts)
        lines.append(
            f"- {len(visits)} visit{'s' if len(visits) != 1 else ''}, grouped by postcode district ({where}) so you "
            f"drive between areas as little as possible; the first starts at {hhmm(visits[0].start)}."
        )
        lines.append(
            f"- Travel time is a rule of thumb, not a map: {TRAVEL_SAME_MIN} min within a district, "
            f"{TRAVEL_OTHER_MIN} min when you change district."
        )
    else:
        lines.append("- No visits planned: no open jobs with a postcode fitted around your calendar.")
    existing = sum(1 for i in plan.items if i.kind == "existing")
    if existing:
        lines.append(f"- Planned around {existing} event{'s' if existing != 1 else ''} already in your calendar.")
    for i in plan.items:
        if i.kind == "lunch":
            lines.append(f"- Lunch {hhmm(i.start)}–{hhmm(i.end)}.")
        elif i.kind == "admin":
            lines.append(f"- Admin {hhmm(i.start)}–{hhmm(i.end)}: {i.title}.")
    lines += [f"- {w}" for w in plan.warnings]
    return "\n".join(lines)


def check(text: str, plan: Plan) -> str | None:
    """Why the model's rationale cannot be used, or None when it only quotes the plan."""
    text = text.strip()
    if not text:
        return "The model returned an empty rationale."
    f = facts(plan)
    times = {f["working_hours"][0], f["working_hours"][1]} | {t for i in f["items"] for t in (i["start"], i["end"])}
    bad_times = [t for t in HHMM_RE.findall(text) if t not in times]
    if bad_times:
        return f"The model quoted times that are not in the plan ({', '.join(dict.fromkeys(bad_times[:3]))})."
    known = ask_ai.KnownNumbers(f)
    invented = known.unknown(HHMM_RE.sub(" ", text), all_tokens=False)
    if invented:
        return f"The model quoted figures that are not in the plan ({', '.join(dict.fromkeys(invented[:3]))})."
    return None


async def rationale(plan: Plan, cfg: AiConfig | None) -> tuple[str, str | None, str | None]:
    """(rationale_md, model, fallback_reason). Never raises for model trouble."""
    if cfg is None:
        return code_rationale(plan), None, "No AI is set up, so the rationale was written by code."
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "PLAN:\n" + json.dumps(facts(plan), separators=(",", ":"), ensure_ascii=False)},
    ]
    try:
        raw = await ask_ai._call_model(messages, cfg, PlanModelOutput, "plan_rationale")
        out = PlanModelOutput.model_validate(parse_model_json(raw))
    except httpx.HTTPStatusError as exc:
        return code_rationale(plan), cfg.model, f"Your AI ({cfg.mode}) returned HTTP {exc.response.status_code}."
    except httpx.HTTPError:
        return code_rationale(plan), cfg.model, f"Your AI ({cfg.mode}) could not be reached at {cfg.base_url}."
    except (ExtractionError, ValidationError):
        return code_rationale(plan), cfg.model, "The model's reply was not in the expected format."
    if reason := check(out.rationale_md, plan):
        return code_rationale(plan), cfg.model, reason
    return ask_ai._clip(out.rationale_md, RATIONALE_MAX), cfg.model, None
