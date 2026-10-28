# Handover: claude/spend-ai

**Done**: spending summary (`/books/spending`, Home card, `/spending`), cheaper options from own history
(`/books/prices`, `/prices`; provider-based live price search, off by default via `PRICE_SEARCH_PROVIDER`), shopping
list (`/shopping`, `_System/shopping_list.json`), Ask action `add_to_shopping_list` incl. the owner's voice sentence
"Remember to order 2-inch bolts for the Hendon job" (job linked), docs (HONESTY, ARCHITECTURE, PRODUCTION 3a),
REVIEW.md with details and risks.

**Left**:
1. A complete green pytest run: the last full runs were OOM-killed at ~67%; one failure there is unidentified
   (`cd services/runtime && python -m pytest -q -rf`).
2. The full e2e suite on the agreed ports:
   `CI=1 E2E_WEB_PORT=3140 E2E_RUNTIME_PORT=8794 E2E_RELAY_PORT=8802 pnpm run e2e:build && CI=1 E2E_WEB_PORT=3140 E2E_RUNTIME_PORT=8794 E2E_RELAY_PORT=8802 pnpm run e2e:test`
   (venv active). Only `e2e/spending.spec.ts` was seen green (6/6). The new pages are in `e2e/pages.ts`, so the
   signed-out, a11y and phone sweeps now cover them: check those.
3. No e2e for the job-linked voice flow (unit tests through `/books/ask/voice` only).

**Test by hand**: test-mode runtime, `POST /__test/reset?seed=purchases`, then `/spending`, `/prices`, `/shopping`, and
in Ask "add packing tape to my shopping list" / "Remember to order 2-inch bolts for the Hendon job" (add a job first).
