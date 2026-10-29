"""/setup-wizard: the new-user set-up wizard (app/setup_wizard.py), saved as you go into `_System/profile.json`.

One question per step; the web asks `/lookup/*` first for the company and VAT checks and posts what the user
confirmed. Same headers as /books/*; writing needs `X-User`. Confirming applies the profile (kind, name and
settings) and records the summary; it files nothing anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app import profile as profile_mod
from app import setup_wizard as wiz
from app.books import Books
from app.company_lookup import COMPANY_NUMBER_RE
from app.routes_books import business_name, get_books, require_user
from app.validation import StrictBody

router = APIRouter(tags=["setup-wizard"])

StepName = Literal["business_type", "company", "vat", "income_tax", "cis", "payroll", "property", "summary"]


class StepBody(StrictBody):
    answers: dict[str, Any] = Field(default_factory=dict, max_length=30)


async def _load_raw(books: Books) -> dict[str, Any]:
    raw = await books.read_json(profile_mod.PROFILE, None)
    return raw if isinstance(raw, dict) else {}


async def _save_setup(books: Books, raw: dict[str, Any], setup: dict[str, Any], user: str) -> None:
    raw[wiz.SETUP_KEY] = setup
    await books.write_json(profile_mod.PROFILE, raw)
    await books.audit(f"user:{user}", "setup_wizard_saved", {"confirmed": bool(setup.get("confirmed_at"))})


def _check_step(step: str, setup: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Check one step's answers; raises 400 with a plain-words sentence. Returns the step's stored dict."""
    state = wiz.SetupState.model_validate(setup)
    if step == "business_type":
        bt = answers.get("business_type")
        if bt not in wiz.KIND_FOR:
            options = ", ".join(k for k, _, _ in wiz.BUSINESS_TYPES)
            raise HTTPException(status_code=400, detail=f"Pick what you are: {options}.")
        name = " ".join(str(answers.get("business_name") or "").split())
        if not name:
            raise HTTPException(status_code=400, detail="Give the business (or your) name.")
        state.business_type = bt  # type: ignore[assignment]
        state.business_name = name[:80]
    elif step == "company":
        number = "".join(str(answers.get("company_number") or "").split()).upper()
        if not COMPANY_NUMBER_RE.fullmatch(number):
            raise HTTPException(
                status_code=400,
                detail="A Companies House number is 8 characters, e.g. 01234567 or SC123456.",
            )
        for field in ("name", "address"):
            if not str(answers.get(field) or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"Confirm the {field} from the Companies House look-up first.",
                )
        state.company = {
            "number": number,
            "name": " ".join(str(answers.get("name")).split())[:120],
            "address": " ".join(str(answers.get("address")).split())[:240],
            "incorporation_date": str(answers.get("incorporation_date") or "")[:10],
            "sic": str(answers.get("sic") or "")[:120],
            "confirmed": True,
        }
    elif step == "vat":
        registered = answers.get("registered")
        if registered not in (True, False):
            raise HTTPException(status_code=400, detail="Say whether the business is VAT-registered.")
        if not registered:
            state.vat = {"asked": True, "registered": False}
        else:
            number = "".join(str(answers.get("vat_number") or "").split()).upper()
            if not profile_mod.VAT_NUMBER_RE.fullmatch(number):
                raise HTTPException(
                    status_code=400,
                    detail="A UK VAT number is 9 digits, optionally after GB (e.g. GB123456789).",
                )
            scheme = answers.get("scheme")
            if scheme not in ("standard", "flat_rate", "cash", "annual"):
                raise HTTPException(status_code=400, detail="Pick a VAT scheme: standard, flat rate, cash or annual.")
            check = answers.get("vat_check") or {}
            if check and check.get("registered") not in (True, False, None):
                raise HTTPException(status_code=400, detail="The VAT check answer is not one I understand.")
            schemes = ("standard", "flat_rate", "cash", "annual")
            picked = [s for s in (answers.get("schemes") or [scheme]) if s in schemes] or [scheme]
            stagger = answers.get("stagger")
            vat: dict[str, Any] = {
                "asked": True,
                "registered": True,
                "vat_number": number,
                "scheme": scheme,
                "schemes": picked,
                "stagger": stagger if stagger in ("monthly", "quarterly", "annual") else "quarterly",
                "period_start": str(answers.get("period_start") or "")[:10],
                "mismatch_acknowledged": bool(answers.get("mismatch_acknowledged")),
            }
            if check:
                vat["vat_check"] = {
                    "registered": check.get("registered"),
                    "name": str(check.get("name") or "")[:120],
                    "address": str(check.get("address") or "")[:240],
                    "consultation_number": str(check.get("consultation_number") or "")[:40],
                    "checked_at": str(check.get("checked_at") or "")[:30],
                }
            if scheme == "flat_rate":
                fr = answers.get("flat_rate") or {}
                if not str(fr.get("sector") or "").strip():
                    raise HTTPException(
                        status_code=400, detail="Pick the flat-rate sector; the percentage follows the sector."
                    )
                vat["flat_rate"] = {
                    "sector": str(fr.get("sector"))[:80],
                    "percentage": fr.get("percentage"),
                    "first_year_discount_from": str(fr.get("first_year_discount_from") or "")[:10],
                    "relevant_goods_share_pct": fr.get("relevant_goods_share_pct"),
                    "relevant_goods_pence": fr.get("relevant_goods_pence"),
                    "limited_cost": bool(fr.get("limited_cost")),
                }
            state.vat = vat
    elif step == "income_tax":
        utr = "".join(str(answers.get("utr") or "").split())
        if utr and not profile_mod.UTR_RE.fullmatch(utr):
            raise HTTPException(status_code=400, detail="A Unique Taxpayer Reference is 10 digits.")
        basis = answers.get("accounting_basis") or ("cash" if state.business_type == "sole_trader" else "traditional")
        if basis not in ("cash", "traditional"):
            raise HTTPException(status_code=400, detail="The accounting basis is cash or traditional.")
        start = str(answers.get("accounting_period_start") or "04-06").strip()
        if not profile_mod.MONTH_DAY_RE.fullmatch(start):
            raise HTTPException(status_code=400, detail="The accounting period start is MM-DD, e.g. 04-06 for 6 April.")
        turnover = answers.get("turnover_pence", 0) or 0
        if not isinstance(turnover, int) or turnover < 0:
            raise HTTPException(status_code=400, detail="Turnover is a whole number of pence, 0 or more.")
        state.income_tax = {
            "asked": True,
            "utr": utr or None,
            "accounting_basis": basis,
            "accounting_period_start": start,
            "turnover_pence": turnover,
        }
    elif step == "cis":
        for field in ("is_subcontractor", "is_contractor"):
            if answers.get(field) not in (True, False, None):
                raise HTTPException(status_code=400, detail=f"{field} is yes or no.")
        state.cis = {
            "asked": True,
            "is_subcontractor": bool(answers.get("is_subcontractor")),
            "is_contractor": bool(answers.get("is_contractor")),
            "verification_number": str(answers.get("verification_number") or "")[:40] or None,
        }
    elif step == "payroll":
        has = answers.get("has_employees")
        if has not in (True, False):
            raise HTTPException(status_code=400, detail="Say whether the business has employees.")
        paye = " ".join(str(answers.get("paye_reference") or "").split()).upper()[:14] or None
        ao = " ".join(str(answers.get("accounts_office_reference") or "").split()).upper()[:13] or None
        state.payroll = {
            "asked": True,
            "has_employees": has,
            "paye_reference": paye,
            "accounts_office_reference": ao,
        }
    elif step == "property":
        lets = answers.get("number_of_lets", 0) or 0
        if not isinstance(lets, int) or lets < 0 or lets > 1000:
            raise HTTPException(status_code=400, detail="The number of lets is a whole number, 0 or more.")
        state.property = {
            "asked": True,
            "number_of_lets": lets,
            "joint_ownership": bool(answers.get("joint_ownership")),
        }
    elif step == "summary":
        return state.model_dump()
    else:
        raise HTTPException(status_code=404, detail=f"There is no wizard step called {step!r}.")
    return state.model_dump()


@router.get("/setup-wizard")
async def wizard_status(
    books: Books = Depends(get_books), business: str | None = Depends(business_name)
) -> dict[str, Any]:
    """Where this account's wizard is: the steps for this business, the first unanswered one, the answers so
    far, and the summary (blocking issues stop `can_continue`)."""
    raw = await _load_raw(books)
    setup = wiz.get_setup(raw)
    steps = wiz.steps_for(setup.get("business_type"))
    current = wiz.first_incomplete(setup)
    report = wiz.summary(setup)
    return {
        "business": business,
        "steps": steps,
        "current_step": current,
        "setup": setup,
        "business_types": [
            {"value": value, "label": label, "explains": explains} for value, label, explains in wiz.BUSINESS_TYPES
        ],
        **report,
    }


@router.put("/setup-wizard/step/{step}")
async def wizard_answer(
    step: StepName,
    body: StepBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> dict[str, Any]:
    """Save one step's answers (checked, in plain words). Saving never files anything."""
    raw = await _load_raw(books)
    setup = wiz.get_setup(raw)
    updated = _check_step(step, setup, body.answers or {})
    await _save_setup(books, raw, updated, user)
    report = wiz.summary(updated)
    return {
        "setup": updated,
        "current_step": wiz.first_incomplete(updated),
        "steps": wiz.steps_for(updated.get("business_type")),
        **report,
    }


@router.post("/setup-wizard/confirm")
async def wizard_confirm(books: Books = Depends(get_books), user: str = Depends(require_user)) -> dict[str, Any]:
    """Confirm the summary: applies the profile (kind, name, settings) and records the confirmation. A
    blocking issue answers 400 naming it; nothing is filed with HMRC or Companies House."""
    raw = await _load_raw(books)
    setup = wiz.get_setup(raw)
    report = wiz.summary(setup)
    if not setup.get("business_type"):
        raise HTTPException(status_code=400, detail="Answer the first question (what you are) before confirming.")
    if report["blocking"]:
        first = report["blocking"][0]
        raise HTTPException(
            status_code=400,
            detail=f"Sort this out first ({first['fix_step']} step): {first['message']}",
        )
    state = wiz.SetupState.model_validate(setup)
    kind = wiz.KIND_FOR[state.business_type or "personal"]
    settings = wiz.profile_settings_for(setup)
    validated = profile_mod.validate_settings(kind, {**(raw.get("settings") or {}), **settings})
    before = await profile_mod.load(books)
    saved = profile_mod.Profile(
        name=state.business_name or before.name,
        kind=kind,
        settings=validated,
        linked=before.linked if before.exists else [],
        updated_at=datetime.now(UTC),
        features=profile_mod.features_for(kind, validated),
    )
    raw.update(profile_mod.to_file(saved))
    confirmed = dict(setup)
    confirmed["confirmed_at"] = datetime.now(UTC).isoformat()
    raw[wiz.SETUP_KEY] = confirmed
    await books.write_json(profile_mod.PROFILE, raw)
    await books.audit(f"user:{user}", "setup_wizard_confirmed", {"kind": kind, "blocking": 0})
    return {
        "profile": saved.model_dump(),
        "setup": confirmed,
        "filed": [],
        "filing_note": wiz.confirm_note(),
        **wiz.summary(confirmed),
    }
