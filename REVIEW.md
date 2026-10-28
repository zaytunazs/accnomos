# Review: spending summary, cheaper options, shopping list (branch `claude/spend-ai`)

All three features work from the user's own purchase history: approved ledger events on the purchases side, plus the
line items of the proposal each one was approved from. Code does every figure; the model writes words (the summary)
or makes one narrow suggestion (two item names are the same product), and code checks or limits both.

## What changed

Runtime (`services/runtime/app`):
- `purchases.py`: loads approved purchases with the VAT return's sign rule (a supplier credit note or an undo counts
  against spend), category from the cost account, line items from the proposal. An undone purchase's lines are dropped.
- `spending.py`, `ai/spending.py`, `GET /books/spending`: spend by category, supplier and item; change on the previous
  period of the same length; recurring costs (3+ months, or 2+ for subscriptions, utilities, rent, insurance); unusual
  one-offs (≥ £100 and ≥ 3× the median earlier purchase, not a regular supplier). The model's summary goes through
  Ask's own checks (`KnownNumbers.unknown`, `wrong_period` in `ai/ask.py`); any failure or model trouble shows code's
  summary with the reason. "Summarise my spending" in Ask (`routes_ask.spending_answer`) answers the same way, with an
  `open_spending` button.
- `prices.py`, `ai/items.py`, `GET /books/prices`, `POST /books/prices/suggest`, `POST /books/prices/matches`:
  `normalise()` reads width, length, weight, volume, colour and pack from a description; prices per metre / kg / litre /
  item; groups identical name + size + colour; savings = (volume-weighted average paid − lowest paid) × usual monthly
  volume. Different names join only by the user (`_System/item_matches.json`) or by the model where code's rules allow
  (same measure, width within 10 %, half the name words shared); the model sees names only and its view is not stored.
- `price_search.py` (after the owner's update): `PriceSearchProvider` interface, chosen by `PRICE_SEARCH_PROVIDER`
  (empty/`none` = off by default; `fake` only in test mode; unknown = off with a log warning). Offers carry supplier,
  title, unit price, pack, URL, `retrieved_at`, `source`; code prices them with the same `normalise()`, keeps them apart
  from the history, labels each, and computes a separate `live_saving`. A failing or slow (8 s) provider loses only its
  offers. No real provider is wired.
- `shopping.py`, `/shopping` routes: `_System/shopping_list.json`; lookup (history first, every typed word in the name,
  typed sizes exact; then live offers when on), spec fields when nothing matches, the cheapest supplier recomputed by code
  when the item is saved, tick/untick/remove, all audited. Purchase order / supplier email: `FUTURE_STEPS`, disabled.
- `actions.py`: new kind `add_to_shopping_list` (intent fields `item_text`, `quantity_text`; quantity must be a number
  the user said). Several matches → a clarification with the candidates; none → a clarification with `spec_fields`, and
  `POST /shopping/propose` turns the filled fields into a signed card. Executes once on Approve, like the other kinds.
- Owner's voice example: "Remember to order 2-inch bolts for the Hendon job." parses to item `2-inch bolts` (code reads
  `in=2` as a size, priced per bolt), `job_ref` "Hendon" matched to an open job by `actions.pick`; history matches are
  offered (2-inch only), or spec fields when there are none; the job id rides in `Clarification.extra` and the card,
  and the item is stored with `job_id`/`job_name`. Intent words `order`/`remember` were added to the action gate.
- `schemas.py`: `ActionKind` + `add_to_shopping_list`, `AskActionKind` + `open_spending`, `Clarification.spec_fields`.
- `testmode.py`: stub replies for the spending and item-match prompts, the shopping intent pattern, and a `purchases`
  seed (`sample_purchases.py`, fictional, Jun–Oct 2026). `audit_view.py`: sentences for the new audit kinds.
- `deploy/docker-compose.yml`, `.env.example`: `PRICE_SEARCH_PROVIDER` passed through, empty.

Web (`apps/web`): pages `/spending`, `/prices`, `/shopping` (new "Buying" sidebar group), Home *Spending* card, Ask card
and spec form for the shopping action, "Summarise my spending" suggestion, `lib/spending.ts` formatting (no maths: every
figure is the runtime's string). "Live price search is off" is shown on Cheaper options and the Shopping list.

Docs: `docs/ARCHITECTURE.md` (new section, two `_System` rows, model call sites), `docs/HONESTY.md` (new section),
`docs/PRODUCTION.md` (§3a, the env switch and how a provider would be added).

## Tests

- New unit tests: `tests/test_prices.py` 29 (normalisation ×14, unit-price and savings maths, rules, report, user and
  model matches, undone lines, provider switch, live offer maths and labels, failing/slow provider, routes),
  `tests/test_spending.py` 17 (facts, recurring/unusual, credit notes, empty books, the number check ×6, fallbacks,
  route, Ask entry), `tests/test_shopping.py` 18 (the owner's sentence through `/books/ask/voice` with stub voice + test-mode intent stub,
  with and without history, and an unknown job; lookup, spec fields, live offers, list, supplier from code,
  action parse/clarify/card/approve-once, routes). Guard tests updated: `test_integration.py` layout,
  `test_security_routes.py` (three no-X-User routes with reasons).
- Runtime suite: see "Gate results" below.
- `ruff check . && ruff format --check .`: clean. `pyright services/runtime/app`: 0 errors.
- Web: `pnpm install --frozen-lockfile`, `pnpm exec eslint .` clean; `e2e:build` OK. New `e2e/spending.spec.ts`
  (6 tests: Home card + Spending page, Cheaper options incl. AI-suggest and user confirm, Shopping list incl. specs and
  tick-off, Ask which-one → card → Approve, Ask spec form → card, Ask summary). The three pages were added to
  `e2e/pages.ts` and the phone nav list, so the signed-out, a11y and phone sweeps cover them.

## Gate results

- ruff check/format: clean. pyright services/runtime/app: 0 errors. eslint: clean. e2e:build: OK.
- pytest: a full run before the voice/job change gave 1282 passed, 4 failed (guard tests, all fixed; those suites then
  234 passed). Later full runs were OOM-killed at ~67% on the shared machine (one F at ~66%, not identified). New and
  touched suites after the last change: 47 + 170 passed.
- e2e: `e2e/spending.spec.ts` 6/6 passed (own runtime on ports 3391/8913, one worker). The full e2e suite was NOT
  run green, and the coordinator's `CI=1 E2E_WEB_PORT=3140 E2E_RUNTIME_PORT=8794 E2E_RELAY_PORT=8802` run was not done.

## Risks and what a human should check

1. **Only the stub model has run.** The spending summary prompt and the same-product prompt have not been tried on
   Glimmer or Spark. The spending facts pack is ~3 KB for the sample month and bounded by TOP_N=6 lists, but it is not
   trimmed to Ask's PACK_TOKENS like Ask's own pack.
2. **Normalisation is regexes.** Check real receipt lines: "6 pack" vs "x6" vs "(6)" (the last is not read as a pack),
   inches/feet, "dozen", brand names left in the name words (they keep "Tesa" tape apart from unbranded tape until
   someone joins them). A missed pack size makes a per-item price wrong by that factor.
3. **Savings are hindsight**: average paid vs the lowest price ever seen in 12 months, ignoring delivery, minimums and
   price changes since. Worth a product decision on the wording "Could save £x a year".
4. **Live price search**: only the interface and a test fake exist. When a real provider is added, check its terms
   allow display, add egress for its host, and review `price_search.search` timeouts (8 s per group, up to 8 groups
   searched sequentially on `/books/prices`: a slow provider could make that page take a minute).
5. **Spending recurring/unusual rules** are fixed thresholds; an annual bill or a quarterly utility shows as unusual or
   not recurring.
6. The Ask card's supplier price is computed when the card is made and again on Approve; if the books change between
   the two, the stored suggestion is the newer one (not what the card showed).
7. Android has no screens for any of this.

Check by hand: `POST /__test/reset?seed=purchases` in test mode, then `/spending`, `/prices`, `/shopping` and Ask
"add packing tape to my shopping list".
