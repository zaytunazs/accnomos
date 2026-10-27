# Review: `claude/ask-speed`

Second-agent review of the Ask speed and grounding work (brief: `TASK_BRIEF.md`): routed facts pack under a token
budget, period-aware grounding, `POST /books/ask?stream=1` (SSE) used by the web, Glimmer re-run of the 40-prompt eval.

## What was checked

- `services/runtime`: `pytest -q`: 692 passed, 1 skipped before the review; 695 passed, 1 skipped after it.
- `evals`: `pytest -q`: 158 passed.
- `apps/web`: `pnpm run build` succeeded; `pnpm run e2e:build` + `playwright test e2e/ask.spec.ts`: 2 passed (the Ask spec
  asserts the browser uses `?stream=1` and does not fall back to the plain call).
- `packages/*` and `services/hmrc-relay` are not touched by the branch; not re-run.
- Read the whole diff: `app/ask_router.py`, `app/ai/ask.py`, `app/routes_ask.py`, `app/facts.py`, `app/schemas.py`,
  `app/testmode.py`, the web stream client and cards, the eval harness and report, README Ask row. Android is untouched
  (it keeps the plain call, as the brief asks).
- Product rules: numbers and citations come from code and the model writes only the words; nothing is stored server-side;
  no secrets or internal URLs in the eval outputs; the eval books are the seeded "SAMPLE — FICTIONAL COMPANY" demo.
- Report and README figures checked against the per-question tables in `evals/runs/ask_40/report.md`.

## What I fixed

- `12abd5e`: a garbled streamed chunk from Ollama or an OpenAI-style server (`json.loads` on a bad line) escaped
  `answer()`/`answer_stream()` as a 500, or cut the stream off with no `answer` event, even though both say they never raise
  for model trouble. Such a chunk is now an `httpx.DecodingError` ("sent a reply that could not be read") and gets the code
  fallback. The same commit fixes a regression: `app/ai/plan.py` uses `ask_ai._call_model`, which now streams and can raise
  `AiStalled`, and the day-plan rationale did not catch it (a 500 instead of the code rationale). New tests: both wire
  formats through `httpx.MockTransport` (Ollama NDJSON with `num_predict`, OpenAI SSE with `max_tokens`), a garbled
  chunk → fallback in both plain and streamed modes, and a stalled model → code rationale for the day plan.
- `73a1c23`: a sentence naming the other period as "Apr-Jun 2026" (hyphen, not en dash) was treated as not naming it,
  so a correct answer was replaced by the fallback. Hyphens and em dashes now match the label; test extended.
- `76c0c94`: `docs/HONESTY.md` still said 4/35 Glimmer timeouts and that grounding cannot catch a wrong-period figure.
  It now matches the re-run and says what the period check still can't do.

## What remains

- On Glimmer the streamed explanation arrives in one piece (Ollama 0.40 holds back a schema-constrained reply), so
  only the first `start` event is early there, and the 90 s first-chunk wait is in effect a whole-reply timeout. The
  per-chunk timeout only helps on servers that stream token by token (Qwen/vLLM).
- Glimmer's raw "no invented figure" is 34/35 against 31/31 before. The before run never scored its 4 timed-out replies,
  and in both runs no invented figure reached the user (`corp_tax`'s "600" was replaced by the fallback). Strictly, that is
  not "unchanged or better" on the raw row.
- The eval was not re-run after this review's fixes; it needs Glimmer and Qwen. The fixes only touch error paths
  and accept one more way of writing a period label, so they can only reduce fallbacks.
- Web: if the stream breaks after it starts, or is refused (4xx/5xx), the web falls back to `POST /books/ask`,
  which asks the model again: a second wait, or a repeat of the same error. A non-model exception after the `start` event
  (a bug in grounding, say) ends the stream with no `answer` or `error` event; the web then falls back to the plain call.
- Period grounding is a per-sentence phrase/label match. A figure that exists in both periods cannot be told apart.
  A follow-up like "why?" is routed on its own words, so it is treated as being about the current period.
- The router is keywords only. Bank, payroll, jobs, deadlines and corporation tax are not in the facts pack (the model
  is told so). Glimmer's instruction prompts still give 3/5 action cards, but that code path was not changed here.
- The pack budget is 1,500 tokens (`PACK_TOKENS`), not the brief's example of 3k. The measured routed prompt is
  median 813 and max 1,792 real tokens, system prompt included.
- `TASK_BRIEF.md` is committed at the repo root (`a19eaca`, "wip: checkpoint"). Drop it, or squash that commit, before merging if
  briefs should not live in `main`.

## How to verify by hand

Start the runtime in test mode (`ACCNOMOS_TEST_MODE=1`, as the web e2e config does) and the web app, open `/vat`, then
*Ask about Jul–Sep 2026*, and ask "How much VAT do I owe this quarter?". The key numbers table (Net VAT (Box 5), 26A3)
should appear at once with "…is writing the explanation", then the words, then the checked answer. In dev tools,
check that one request went to `/books/ask?stream=1` and that it returned `event: start`, `token` events and `event: answer`.
With Glimmer on Ollama :11434, ask "How much VAT did I reclaim last quarter?". The answer should quote the Apr–Jun
Box 4 figure and cite the 2026-04…06 ledger folders. If the model quotes this quarter's figure without saying so, the
answer shows the warning band and code's figures for the asked period. To check speed and timeouts, run
`cd evals && python -m harness.ask_40` and compare with `evals/runs/ask_40/report.md`.
