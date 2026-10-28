"""Spending, cheaper options and the shopping list, all from the user's own purchase history.

GET  /books/spending            the spending summary for a period (default: this calendar month); code's figures,
                                the model's words, checked (app/spending.py, app/ai/spending.py)
GET  /books/prices              item price history and savings (app/prices.py); code only
POST /books/prices/suggest      the same, with the model's same-product suggestions where code's rules agree
POST /books/prices/matches      the user's answer for one possible match (_System/item_matches.json)
GET  /shopping                  the shopping list (_System/shopping_list.json, app/shopping.py)
POST /shopping/lookup           what the history (then a live price search, when on) has for the words typed
POST /shopping                  add an item (the user's own tap on the page); 201
POST /shopping/propose          a signed card for Ask (kind add_to_shopping_list), from typed specs; no model
PATCH /shopping/{id}            tick off / untick;  DELETE /shopping/{id} remove
Same headers as /books/*; changes also need X-User.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from app import actions, price_search, prices, shopping, spending
from app.ai import spending as spending_ai
from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books, today
from app.routes_actions import graph_token
from app.routes_books import business_name, get_books, require_user
from app.schemas import AskPeriod, ProposedAction
from app.validation import StrictBody

router = APIRouter(tags=["spending"])


def this_month(day: date) -> AskPeriod:
    """The whole calendar month `day` is in (so the previous period is the whole month before)."""
    nxt = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return AskPeriod(start=day.replace(day=1), end=nxt - timedelta(days=1))


@router.get("/books/spending", response_model=spending.SpendingSummary)
async def get_spending(
    start: date | None = Query(None, description="first day; with no start or end: this calendar month"),
    end: date | None = Query(None),
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
    business: str | None = Depends(business_name),
) -> spending.SpendingSummary:
    if (start is None) != (end is None):
        raise HTTPException(422, "give both start and end, or neither")
    if start and end and end < start:
        raise HTTPException(422, "end is before start")
    if start and end and (end - start).days > 400:
        raise HTTPException(422, "a period can be at most about a year (400 days)")
    period = AskPeriod(start=start, end=end) if start and end else this_month(today())
    facts = await spending.build(books, period, business)
    text, by, why = await spending_ai.summarise(facts, cfg)
    return spending.SpendingSummary(
        period=period,
        previous=spending.previous_period(period),
        facts=facts,
        summary_md=text,
        summary_by=by,
        fallback_reason=why,
        model=cfg.model if by == "model" else "code",
    )


@router.get("/books/prices", response_model=prices.PriceReport)
async def get_prices(books: Books = Depends(get_books)) -> prices.PriceReport:
    return await prices.price_report(books, today(), price_search.provider_from_env())


@router.post("/books/prices/suggest", response_model=prices.PriceReport)
async def suggest_matches(
    books: Books = Depends(get_books), cfg: AiConfig = Depends(ai_config_from_request)
) -> prices.PriceReport:
    return await prices.suggest(books, today(), cfg, price_search.provider_from_env())


@router.post("/books/prices/matches", response_model=prices.MatchDecision)
async def decide_match(
    body: prices.MatchIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> prices.MatchDecision:
    try:
        return await prices.save_match(books, body, user)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/shopping", response_model=shopping.ShoppingList)
async def shopping_list(books: Books = Depends(get_books)) -> shopping.ShoppingList:
    try:
        items = await shopping.list_items(books)
    except shopping.ShoppingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return shopping.ShoppingList(items=items, web_search=price_search.status(price_search.provider_from_env()))


class LookupBody(StrictBody):
    text: str = Field(min_length=1, max_length=120)


@router.post("/shopping/lookup", response_model=shopping.Lookup)
async def shopping_lookup(body: LookupBody, books: Books = Depends(get_books)) -> shopping.Lookup:
    if not body.text.strip():
        raise HTTPException(422, "say what to look for")
    return await shopping.lookup(books, body.text, today())


@router.post("/shopping", response_model=shopping.ShoppingItem, status_code=201)
async def shopping_add(
    body: shopping.ShoppingIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> shopping.ShoppingItem:
    try:
        return await shopping.add_item(books, body, user, today())
    except shopping.ShoppingError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/shopping/propose", response_model=ProposedAction)
async def shopping_propose(
    body: shopping.ShoppingIn, books: Books = Depends(get_books), token: str = Depends(graph_token)
) -> ProposedAction:
    """The card Ask shows after the user filled in the specs: approve it with POST /actions/approve."""
    return actions.new_action(await actions.shopping_draft(books, body, today()), token)


class DoneBody(StrictBody):
    done: bool


@router.patch("/shopping/{item_id}", response_model=shopping.ShoppingItem)
async def shopping_tick(
    item_id: str, body: DoneBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> shopping.ShoppingItem:
    try:
        return await shopping.set_done(books, item_id, body.done, user)
    except KeyError as exc:
        raise HTTPException(404, "No such item") from exc
    except shopping.ShoppingError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/shopping/{item_id}", response_model=shopping.ShoppingItem)
async def shopping_remove(
    item_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> shopping.ShoppingItem:
    try:
        return await shopping.remove_item(books, item_id, user)
    except KeyError as exc:
        raise HTTPException(404, "No such item") from exc
    except shopping.ShoppingError as exc:
        raise HTTPException(409, str(exc)) from exc
