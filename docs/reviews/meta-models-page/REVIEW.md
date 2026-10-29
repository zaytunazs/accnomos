# Review: one public page saying which Meta model does what (`claude/meta-models-page`)

Branch from `origin/main` (`c353bd4`) with `origin/claude/muse-transcribe` merged in (clean merge; it adds Muse Voice
Transcribe, which is not on main yet). No push to main, no PR. Meta's API, Baseten and Modal were not called.

Owner's request: "one page that says which Meta model is used for what work and what they do in the app."

## Sources (all in this repository, read 29 Oct 2026)

| What | Where |
|---|---|
| Every runtime model call | `git grep` for `call_json_model`, `extract_document`, `verify`, `read_cis_document`, `read_property_document`, `app.ai.*` imports: `app/ai/{extract,verify,ask,cis_read,property_read,home_summary,close_summary,spending,triage,remind,plan,items,duplicates,stt,voice,crop}.py`, `app/actions.py` (chat/voice intents), `app/bank_reconcile.py` (`suggest_ai`), `app/cashflow.py` (`explain`), `app/public_chat.py` |
| Backends and order | `app/ai/config.py` (local = Ollama/Glimmer, key = Meta Model API/`muse-spark-1.3`), `app/ai/providers.py` (`AI_PROVIDERS`, recommended `modal,meta,spark`), `app/ai/chain.py` (failover, breaker), `app/ai/verify.py` (Spark Open first for the Verifier), `app/ai/stt.py` (Muse first, local fallback second), `app/ai/crop.py` (`SAM_CROP=1`, key mode) |
| Screens | the web callers: `components/review`, `cis`, `property`, `ask`, `home/OverviewCards.tsx`, `home/InboxTriage.tsx`, `home/PlanToday.tsx`, `month-end/MonthEnd.tsx`, `spending/LiveSpending.tsx`, `accounting/CashFlow.tsx` (`/reports/cashflow`), `bank/BankReconcile.tsx`, `contacts/LiveContacts.tsx`, `spending/LivePrices.tsx` (`/prices`), invoices reminder draft |
| Muse Image | `tools/brand_muse.py`, `tools/teaser/build.py` (thumbnail and title art use the brand art) |
| Figures | `evals/runs/{glimmer_200_v2,glimmer_messy_200_v2,spark_open_200,spark_open_messy_200,cis_read,property_docs}/summary.json`, `ask_40/result.json`, `autopilot_l2/summary.json`, `mail_intake/result.json`; `evals/REPORT_crop_code_20_2026-10-27.md` |

## Design

- **`/meta-models`** (`apps/web/src/app/meta-models/page.tsx`): a public path (`PUBLIC_PATHS`), so signed out it gets
  the marketing shell and signed in the app shell. An overview (Model, What it does, How it is called, Measured) as a
  `<table>` from 768 px and the same rows as stacked cards below that, then one section per model: what it is, jobs with
  the screen, how it is called, what code checks after it, and measured results with run date, sample size and a link
  to the committed report.
- **Data** (`apps/web/src/lib/meta-models-page.ts`): the words are typed from the code; the numbers are read from the
  run files at build time (as `/models` already does via `lib/evals.ts`, whose reader is now exported as `readRun`).
  Runs that carry no date of their own use their commit date, typed in and commented. Bank coding and speech-to-text
  read `evals/runs/bank_ai/` and `evals/runs/stt/` if present (stub runs ignored) and say "Not measured yet" until then.
- **Wording**: only Meta's models and the Meta Model API are named. No hardware, no other company's engine; the voice
  fallback is "a local fallback model". **Modal is named** in the chain order because the owner's brief used it as the
  example ("Modal first, Meta API second"); Baseten is not (Spark Open is "hosted open weights the server owner sets
  up"); the owner's own server is "our own server". If Modal should go too, it is two strings in
  `meta-models-page.ts` and one row in the spec. No launch, "coming soon", "beta" or "early access" words.
- **Links**: public footer (Help › Meta models used), app footer (About › Meta models used), `/judges` ("What is real"),
  the Home summary card under its who-wrote-it line, and README (next to the models table).
- **`docs/submission/META_MODELS.md`**: a new first section with the same facts as the page; the earlier engineering
  table and notes (which do name hosts and engines) stay below it, unchanged.
- **"Muse Spark 1.x / Contributor"** from the brief: the code calls `muse-spark-1.3` only; no "Contributor" model id
  exists anywhere in the repository, so the page lists Muse Spark and says no other Meta model is called.
- **Bank categoriser**: `bank_matching` is code-only matching (not a model), so it is not on the page; the model part
  (`suggest_ai`) has a harness but no committed run, so it shows "Not measured yet".

## Tests

- `apps/web/e2e/meta-models-page.spec.ts` (4 tests): the table lists all six models, every row link lands on its
  section with the four sub-headings, the CIS 92.5 % / property 89.8 % / Ask 32/32 / Spark Open 91 % figures come
  through, every report link is a file that exists in the checkout, every in-page anchor lands, and the page text has
  none of DGX, Ollama, vLLM, Whisper, Kokoro, Qwen, ComfyUI, Baseten, L40S or launch words (signed out and signed in);
  the public footer, `/judges`, the Home summary card and the app footer reach it; at 360 px the cards show, the table
  is hidden and nothing scrolls sideways.
- `/meta-models` added to `e2e/pages.ts` (axe signed out and signed in, phone smoke) and to the public set in
  `e2e/signed-out.spec.ts` (CTA wording, live links and buttons at 390 and 1280 px).
- `e2e/site-layout.spec.ts`: its copy of the public set gains `/meta-models` (the one failure of the first full run).
- Gate totals (29 Oct 2026): runtime `pytest -q` 2390 passed, 2 skipped; `ruff check` and `ruff format --check` clean;
  `pyright app` 0 errors; web `eslint .` clean; `e2e:build` ok; full `e2e:test` (CI=1) 485 passed, 94 skipped, 1 failed
  (`site-layout.spec.ts`, the public-set copy above), then that spec re-run after the fix: 6 passed. No Flutter change.

## Follow-up: no non-Meta names on any public or judge-facing page (owner's rule, 29 Oct 2026)

`origin/main` merged (muse-transcribe had landed there). Reworded, with a non-Meta fallback always "a local fallback
model":

- **Public chat KB** (`services/runtime/app/public_kb.md`): voice fallback, Glimmer "run by the team", Spark Open
  "hosted open weights", "the team's own server"; Baseten/DGX/Ollama dropped from the retrieval keywords and
  `meta models` added.
- **Labels the runtime sends to the UI**: the STT fallback's label is now "a local fallback model" (`app/ai/stt.py`,
  shown as "Transcribed by …" on web and Android) and the chain's `spark` provider is "our own server"
  (`app/ai/providers.py`). Code comments and env names keep the real names.
- **Web**: `/how-it-works` (voice gap, Verifier gap, local-mode FAQ, "not tested" FAQ, the models list), the landing
  page's models table, the Ask help text, `/privacy` (Glimmer example; Baseten listed as "a hosted inference provider
  chosen by the server owner"), the Settings label "Local agent address", and the provider labels on `/models` and the
  Review card line (`lib/meta-models.ts`, `lib/evals.ts`: "our own server", "hosted open weights", "Modal" without
  the GPU name). Two `/how-it-works` lines were also out of date (Spark Open "unit-tested only, model name
  unconfirmed"); they now give the measured figures, as `/meta-models` does. `/judges` and `/meta-models` had no such
  names.
- **Checks**: `e2e/submission-mode.spec.ts` now also fails on Whisper, Kokoro, Ollama, vLLM, Qwen, ComfyUI, DGX or
  Baseten in any rendered page's text, title, meta description or accessible-name attributes, signed out, signed in
  and with the phone menu open (list `THIRD_PARTY_NAMES` in `scripts/prelaunch-words.mjs`; not applied to the export's
  JS files, which keep provider ids like `baseten:` to map them to Meta names).
  `tests/test_public_chat.py::test_notes_name_no_non_meta_tool_engine_or_hardware` checks the KB in both build modes.
- **Not changed**: repository docs (`docs/submission/*.md`, README, `docs/META_MODELS.md`, HONESTY) still use the full
  names where they explain the engineering; tell me if the judge-facing submission docs should follow the same rule.
  The privacy page now names a category rather than Baseten (UK GDPR art. 13(1)(e) asks for "the recipients or categories
  of recipients", from knowledge: **not re-checked**, legislation.gov.uk is not reachable from this sandbox, 29 Oct
  2026; the owner or their adviser should confirm a category is enough); Modal, which the server chain also sends documents to, was already not listed there, which is a gap
  for the owner to decide on.

- Gate totals after the follow-up (29 Oct 2026): runtime `pytest -q` 2392 passed, 2 skipped; `ruff check`,
  `ruff format --check` clean and `pyright app` 0 errors (after wrapping one over-long line in `app/ai/stt.py`);
  web `eslint .` clean; `e2e:build` ok; full `e2e:test` (CI=1) 486 passed, 94 skipped, 0 failed. The Flutter
  test fixture's label string changed (`apps/mobile/test/voice_provider_test.dart`); Flutter is not installed here,
  so `flutter test` was not run.

## Follow-up: the live order and Contributor mode (owner's decision, 29 Oct 2026)

- The live server runs `AI_PROVIDERS=meta,spark`. `/meta-models` now lists **Muse Spark first** (it carries the job
  list) and Muse Glimmer 30B second as "a local fallback model ... on our own server", plus local mode. The chain
  sentence reads "1st Muse Spark on the Meta Model API; last, a local fallback model"; Modal appears once, as "an
  optional extra provider" the code supports, "not what runs live". A highlighted line under the intro says the same
  and: "Your data goes only to standard Muse Spark, never to Contributor mode, which lets Meta train on the content
  sent to it." The Muse Spark section repeats it.
- `docs/submission/META_MODELS.md`: Spark row first with the live order and the Contributor sentence; Glimmer row
  "last on the live server", Modal optional and not deployed; a note on what backs the Contributor claim.
- What backs it in code: the app's key mode always sends `muse-spark-1.3` (`lib/ai-config.ts` `DEFAULT_KEY`; Settings
  has no model field for key mode) and the chain's `meta` provider uses `MODEL_API_MODEL`, default `muse-spark-1.3`.
  Not checked: how Contributor mode is selected at Meta (dev.meta.ai is not reachable from here), and a direct API
  caller with their own key can still send another `X-AI-Model`. Both in `docs/HONESTY.md`.
- Consequence recorded in HONESTY: the model answering first live (Muse Spark) has no measured figure; every number on
  the page is Glimmer's or Spark Open's.
- `e2e/meta-models-page.spec.ts` now checks the live-order line, the Contributor sentence, Muse Spark as the first row,
  the chain sentence, and that every line naming Modal calls it an optional extra provider.

## Follow-up: Contributor mode on the live server (owner's correction, 29 Oct 2026)

- The earlier "standard Muse Spark only" sentence was wrong for the live server and is gone. `/meta-models` now names
  the model **Muse Spark 1.3**, shows `muse-spark-1.3-contributor (live, demo and testing) · muse-spark-1.3 (your own
  key)`, and the highlighted line and the Muse Spark section say: the live server uses Contributor mode for the demo and
  testing; in Contributor mode Meta may use the content sent to it to improve its models; the demo uses only fictional
  sample data; testers who connect their own books are served the same way, so they should test with documents they
  are happy to share; before real customers the server switches to standard mode; with your own Meta key the app asks
  for standard Muse Spark 1.3.
- The tester sentence is mine, not in the owner's wording: a signed-in tester's own documents go through the same
  server chain, so "the demo uses only fictional sample data" alone would leave them out.
- `docs/submission/META_MODELS.md` and `docs/HONESTY.md` say the same. HONESTY also records that the switch to standard
  mode is a server setting nothing in the code enforces, and that `/privacy` and the public chat notes do not mention
  Contributor mode yet.
- The earlier full e2e run on `70ef62d`: 485 passed, 94 skipped, 1 flaky (`property.spec.ts` landlord mode, passed on
  retry; not touched by this branch).

## Risks

- The page's words are a hand summary of the code: a new AI call site will not appear until someone adds it
  (`docs/HONESTY.md`, Models).
- The playwright browser in this sandbox is build 1243 while the lockfile's Playwright wants 1248; the e2e run here
  used a symlink outside the repository. CI installs its own.
