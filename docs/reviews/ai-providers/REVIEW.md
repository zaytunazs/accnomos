# Review: AI provider chain (`claude/ai-providers`)

Goal: no AI call depends on the owner's home server. `AI_PROVIDERS=modal,meta,spark` (recommended for production and
the judges' demo): Muse Glimmer 30B on a hosted GPU, then Muse Spark on the Meta Model API (server key), then our own server's
local model runtime. All three are Meta models.

## What changed

Runtime (`services/runtime/app`)
- `ai/providers.py` (new): builds the chain from the environment. Per provider: base URL, model, auth (the hosted GPU proxy-auth
  `Modal-Key`/`Modal-Secret`; Meta bearer key; none for the Spark), timeouts (connect / first token / whole request,
  `<NAME>_CONNECT_S` etc.; hosted GPU 10/150/240 s for the cold start), capabilities (vision, strict JSON, voice = Meta only).
  An unconfigured provider drops out. Test mode keeps the names and order but points every provider at the stub AI
  (`ACCNOMOS_TEST_AI_DOWN=modal` makes one answer 503).
- `ai/config.py`: `AiConfig` gains `provider`, `extra_headers` (never serialised), timeouts, capabilities, `in_chain`,
  `fallbacks`, plus `chain()`, `auth_headers()`, `http_timeout()`, `with_capability()`. A request with no `X-AI-*`
  headers (or `X-AI-Mode: auto`) gets the chain when `AI_PROVIDERS` is set; anything the user chose is unchanged.
- `ai/chain.py` (new): `run()` / `stream()` failover. Fails over on timeout, connection errors, 5xx, 402/429 and
  401/403/404/408 (provider credentials, model or gateway; a deliberate widening of the brief's list, see below); never
  on other 4xx or on an unparseable reply. Streams fail over only before the first token. Circuit breaker: 3 failures in
  a row skip a provider for 120 s (`AI_BREAKER_*`); if every circuit is open they are all tried anyway. A user's own
  backend has no breaker. Last 50 calls in memory; `take_served()` via a ContextVar.
- Every caller goes through it: extract, verify (the open-weights host first when keyed, then the chain), Ask (streamed and not),
  plan rationale, triage, reminders, chat intents, bank coding, duplicate contacts. The local model server calls now send the
  provider's auth headers. Voice in chain mode uses the chain's Meta provider.
- `ServedBy {provider, model, latency_ms, fell_back_from}` on `Proposal`, `Verification`, `AskAnswer`, `TriageThread`.
  Existing `model` strings are kept (chain proposals read `modal:muse-glimmer:30b`).
- Failure text for the chain names providers, never their URLs ("None of the server's AI providers answered (...)").
- `routes_ai.py` (new): `GET /ai/health` (cheap model-list probes, cached 60 s; the hosted GPU passive unless
  `AI_HEALTH_PROBE_MODAL=1` because a probe starts a paid GPU; no keys or URLs), `GET /ai/calls`, `POST /ai/warm`
  (one hosted-GPU ping per 60 s on top of the per-IP limiter; skipped when the hosted GPU served in the last 4 min).
- `/health` gains `ai: {chain, configured, providers[{name, model, configured}], default, recommended}`.

`tools/modal_glimmer.py`: `MODAL_PROXY_AUTH=1` (`requires_proxy_auth`), `MODAL_KEEP_WARM=08:00-18:00` with
`MODAL_KEEP_WARM_TZ`/`_DAYS` (two cron functions calling `Function.autoscaler.update(min_containers=...)`, the pattern in
the GPU host's scaling guide). Cost stated: cloud GPU $0.000542/s = $1.95/h (the GPU host's pricing page, checked 28 Oct 2026) plus CPU
and memory, about $2.00/h.

Web (`apps/web`)
- Review card line (`data-testid="served-by"`): "Read by Muse Glimmer 30B (hosted GPU) · 14 s · checked by … · the hosted GPU did not
  answer", linking to `/models`. Chain proposals' chip says "Read by Muse Glimmer 30B" instead of the wrong
  "Read by Muse Spark".
- `/models` page: the chain in order with live health and capabilities, the last 50 calls, and eval headlines read from
  `evals/runs/*/summary.json` / `result.json` at build time (`src/lib/evals.ts`), linking to the reports on GitHub.
  Linked from the footer and Settings → AI.
- `POST /ai/warm` from Home and Review when signed in with no AI of one's own.
- Sidebar label for "no AI chosen" now reads "AI: the server's Meta models".

Config/docs: `.env.example`, `deploy/docker-compose.yml` (`AI_PROVIDERS` defaults to `modal,meta,spark`; with no hosted GPU
URL and no `META_API_KEY` that is just the Spark, as before), `docs/PRODUCTION.md` §6, `docs/META_MODELS.md`,
`docs/HONESTY.md`.

## Tests

- `tests/test_ai_providers.py` (new, 33 cases) and one in `tests/test_triage.py`: chain order and config, failover on
  503/500/502/429/402/connect/timeout, fall-through to the Spark, all down, no failover on 400/413/422 or a garbled
  reply, own key single and breaker-free, hosted-GPU proxy headers only to the hosted GPU, breaker open/skip/half-open, all-open still
  tried, verifier/JSON/stream/triage record `served_by`, `/ai/health` (no secrets, cache, hosted GPU passive, open circuit),
  `/ai/calls`, `/ai/warm`, `/health`, test-mode stub chain. All fake transports.
- `apps/web/e2e/models.spec.ts`: `/models` chain, health and eval numbers; the Review card line on the chain and the
  calls list; Settings and footer links. `/models` added to `e2e/pages.ts` (axe, phone, signed-out).

## Things to look at

- 401/403/404/408 fail over: the brief listed timeout, 5xx, connection, 402/429. A hosted-GPU 401 (proxy token wrong) or an
  the local model server 404 (model not pulled) is that provider's problem, and stopping there would end the demo; 400/413/422 do not.
- With the chain, a request without AI headers sends documents to the hosted GPU/Meta (the owner's accounts) before the Spark;
  inbox triage still requires a user choice. Written up in HONESTY.
- The calls log and breaker are per process and shared by all users (no content, no user ids).
- The Glimmer-on-Modal verifier is the same model as the extractor unless `BASETEN_API_KEY` is set.
- Nothing was run against the hosted GPU, Meta or a Spark. `MODAL_KEEP_WARM` is undeployed; the GPU host's SDK version on the deploy
  machine decides between `autoscaler.update` and the older `update_autoscaler` (both handled).
