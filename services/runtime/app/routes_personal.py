"""/personal/*: basic personal finances (app/personal.py). Same headers as /books/*; writes also need `X-User`.

GET    /categories            household categories (the defaults until you edit them)
PUT    /categories            replace the list (ids kept so budgets and rules follow a rename)
GET    /budgets               {category id: pence a month}
PUT    /budgets               replace the budgets
GET    /rules                 personal categorisation rules, in order (first match wins)
POST   /rules                 add one;  DELETE /rules/{id};  POST /rules/starter adds common UK merchants
POST   /lines/{id}/category   put one bank line in a category by hand (null hands it back to the rules)
GET    /summary?month=        income, spend by category against budget, uncategorised
GET    /recurring             bills and subscriptions found in the statements (estimates)
GET    /goals                 goals with the monthly amount code works out;  POST, PATCH /{id}, DELETE /{id}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import personal as p
from app.books import Books, today
from app.routes_books import get_books, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/personal", tags=["personal"])

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


def _refused(exc: p.PersonalError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/categories", response_model=list[p.Category])
async def categories(books: Books = Depends(get_books)) -> list[p.Category]:
    return await p.load_categories(books)


@router.put("/categories", response_model=list[p.Category])
async def put_categories(
    body: p.CategoriesIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> list[p.Category]:
    try:
        return await p.save_categories(books, body, user)
    except p.PersonalError as exc:
        raise _refused(exc) from exc


@router.get("/budgets", response_model=dict[str, int])
async def budgets(books: Books = Depends(get_books)) -> dict[str, int]:
    return await p.load_budgets(books)


@router.put("/budgets", response_model=dict[str, int])
async def put_budgets(
    body: p.BudgetsIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, int]:
    try:
        return await p.save_budgets(books, body, user)
    except p.PersonalError as exc:
        raise _refused(exc) from exc


@router.get("/rules", response_model=list[p.PersonalRule])
async def rules(books: Books = Depends(get_books)) -> list[p.PersonalRule]:
    return await p.load_rules(books)


@router.post("/rules", response_model=p.PersonalRule, status_code=201)
async def post_rule(
    body: p.PersonalRuleIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> p.PersonalRule:
    try:
        return await p.add_rule(books, body, user)
    except p.PersonalError as exc:
        raise _refused(exc) from exc


@router.post("/rules/starter", response_model=list[p.PersonalRule])
async def post_starter_rules(
    books: Books = Depends(get_books), user: str = Depends(require_user)
) -> list[p.PersonalRule]:
    return await p.add_starter_rules(books, user)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    try:
        await p.delete_rule(books, rule_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such rule") from exc


class LineCategory(StrictBody):
    category_id: str | None = Field(max_length=40)


@router.post("/lines/{line_id}/category", status_code=204)
async def line_category(
    line_id: str, body: LineCategory, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> None:
    try:
        await p.set_override(books, line_id, body.category_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank line") from exc
    except p.PersonalError as exc:
        raise _refused(exc) from exc


@router.get("/summary", response_model=p.MonthlySummary)
async def summary(
    month: str | None = Query(default=None, pattern=MONTH), books: Books = Depends(get_books)
) -> p.MonthlySummary:
    m = month or today().strftime("%Y-%m")
    return p.summarise_month(
        m,
        await books.list_bank_lines(),
        await p.load_categories(books),
        await p.load_budgets(books),
        await p.load_rules(books),
        await p.load_overrides(books),
    )


class RecurringList(BaseModel):
    items: list[p.RecurringItem]
    monthly_total_pence: int  # estimate: every item not stopped, as a monthly equivalent
    note: str


@router.get("/recurring", response_model=RecurringList)
async def recurring(books: Books = Depends(get_books)) -> RecurringList:
    items = p.detect_recurring(
        await books.list_bank_lines(),
        await p.load_categories(books),
        await p.load_rules(books),
        await p.load_overrides(books),
        today(),
    )
    return RecurringList(
        items=items,
        monthly_total_pence=sum(i.monthly_equivalent_pence for i in items if i.status != "stopped"),
        note=(
            "Estimates from your imported statements: same payee, a regular gap, a similar amount. "
            "Next due is the last payment plus one cycle, not a date from the provider."
        ),
    )


@router.get("/goals", response_model=list[p.GoalPlan])
async def goals(books: Books = Depends(get_books)) -> list[p.GoalPlan]:
    t = today()
    return [p.plan_goal(g, t) for g in await p.load_goals(books)]


@router.post("/goals", response_model=p.GoalPlan, status_code=201)
async def post_goal(body: p.GoalIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> p.GoalPlan:
    try:
        return p.plan_goal(await p.add_goal(books, body, user), today())
    except p.PersonalError as exc:
        raise _refused(exc) from exc


@router.patch("/goals/{goal_id}", response_model=p.GoalPlan)
async def patch_goal(
    goal_id: str, body: p.GoalPatch, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> p.GoalPlan:
    try:
        return p.plan_goal(await p.patch_goal(books, goal_id, body, user), today())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such goal") from exc
    except p.PersonalError as exc:
        raise _refused(exc) from exc


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    try:
        await p.delete_goal(books, goal_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such goal") from exc
