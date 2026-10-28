# Review: Spark jobs (`claude/spark-jobs`)

Five jobs for the DGX Spark, whose two models (Glimmer 30B on Ollama, Qwen3.8-27B on vLLM) should be kept busy. Neither
model is reachable from the build machine, so **every script was exercised against stubs or fakes only; no real
Glimmer or Qwen call has been made.** Gates: `cd evals && python -m pytest -q tests` 324 passed (66 new),
`ruff check . && ruff format --check .` clean. One commit per job (four), one for the queue, README and `--gold-dir`, one for this file. Nothing pushed.

## What each does

| File | Model | Does |
|---|---|---|
| `evals/harness/bank_ai.py` | Glimmer | Runs all 459 gold bank lines (hand-written statements, six two-month statements, ledger2 pairs with the re-export overlap removed) through the real `app.bank_reconcile.suggest_ai`, wrapping only `call_json_model` to time each call and keep the raw reply. Reports accuracy, refusals split into transport error / empty / invalid JSON / wrong shape / account outside the list / bad VAT code, latency (mean, p50, p95, max), per-set and per-account accuracy, top confusions, misses. Writes `evals/runs/bank_ai/{results.jsonl, summary.json, report.md}`. Resumable. |
| `evals/gold/gen_gold4.py` + `spark_gen.py` | Qwen | 120 price-history receipts: 18 joinery-consumable products, 5 suppliers (each product at 3 or 4 of them, 1 or 2 pack sizes each), Apr-Sep 2026. Same JSON schema as `gold/receipts` plus per-line `item_key`, `sku`, `pack_units`, `unit_net_pence`. `expectations.json`: per product and supplier the observations, latest and mean normalised ex-VAT unit price, cheapest supplier by latest and by mean, and a per-line "cheaper elsewhere" hint using only what was known on that date. PNGs via `harness.render`. |
| `evals/gold/gen_personal.py` | Qwen | Per household (2 by default): 6 months, about 430 rows, 19 recurring series, 22 not-recurring payees, CSV in the Starling, Tide or Barclays layout, `expectations.json`. |
| `evals/harness/public_chat_eval.py` | the chat route | 81 prompts to `POST {base}/public/chat`: 45 product questions from the docs (7 on HMRC sandbox status), 6 unanswerable ones, 20 off-topic, 10 injections. Writes `evals/runs/public_chat/{report.md, result.json}`. |
| `tools/spark_queue.sh` | both | gen_gold4, gen_personal, bank_ai, then `run_extraction` on `gold/ledger{2,3,4}/receipts` folders that exist. |

Also changed: `run_extraction.py` gained `--gold-dir` (default unchanged), `.gitignore` keeps `evals/runs/bank_ai/` and
`evals/runs/public_chat/` (the other run folders stay ignored), `evals/README.md` (new) and `evals/gold/README.md`.

## Why the expectations are right by construction

* **Label.** `LABEL` is written with the real U+2014 in `spark_gen.py`. Every file the generators write goes through
  `write_text`/`write_json`, which refuse content without the exact label and open files as UTF-8. Tests assert the
  label bytes (`E2 80 94`) are in every generated file (receipts, catalogue, expectations, manifest, README, the CSV's first
  line, names.json), that no file contains `???`, that no generator source contains `SAMPLE ?`, and that the guard
  raises on a mangled label.
* **gen_gold4.** Qwen supplies only names and wording. Prices come from a table written by code (base price per unit x supplier factor x bulk
  discount x month-by-month drift with the odd price rise, whole pence per pack) and stored in `catalogue.json`. Receipts
  are built from the table (invoice style: net per pack; till style: shelf price x 1.2 half-up; cash supplier: no VAT, no
  VRN). Expectations are computed from the *finished receipts*, not the plan, then tests recompute them independently
  (latest, mean, cheapest, near-ties, per-line hints) and check every line against the price table. The plan is re-drawn
  (next seed) until every product/supplier pair has 3+ purchases over 2+ months and no cheapest is within 1.5% of the
  runner-up, so no answer is a coin toss. Qwen's wording is checked only for the size words (`38mm`, `18mm`, `ply`...), so identity
  rests on the code-assigned `item_key`, not on Qwen.
* **gen_personal.** Every amount, date and recurrence is code. Direct debits and standing orders move to the next working
  day (2026 bank holidays listed). The opening balance is chosen so the account never goes below 150 GBP, then balances are
  computed. Rule stated in the expectations: a series is one payee with 3+ payments at a fixed cadence; a price rise keeps it one
  series. Lookalikes that must NOT be flagged are in `not_recurring` (cafes and supermarkets with varying amounts, an
  annual policy paid once, a quarterly bill with two payments). Tests parse the CSV with the real importer in all three layouts and
  recompute category totals, series dates, cadence gaps, committed total and running balance from the rows.
* **bank_ai** (the one soft spot). The expectation is derived by code but is a judgement: for the two-month statements from the gold
  document each row pays (`expected_matches.json` -> `gold_case` -> the category table `bank_match` already uses; utility
  with phone/broadband wording -> Telephone & internet), for rows with no document from their statement kind, otherwise
  from an ordered keyword table. Ambiguous merchants accept a set (hardware: Materials or Tools). Money in, HMRC, payroll, drawings,
  transfers and sale-side documents have no expense account on the runtime's list, so they are asked but not scored (174 of 459). A refusal
  counts as wrong in the headline accuracy; "accuracy when answered" is also reported.
* **public_chat_eval.** Required phrases per question are checked in tests to occur in README.md/docs/. The number check
  compares every figure in an answer with the docs corpus (274 distinct figures): money exactly, others exactly or as the rounded
  form of a docs decimal, single digits and list numbers ignored.

## Running on the Spark

```sh
cd <checkout> && . <its venv>/bin/activate        # or SPARK_PYTHON=<interpreter> for the queue
tools/spark_queue.sh --dry-run                    # check
nohup tools/spark_queue.sh >/dev/null 2>&1 &      # log: ~/spark/accnomos/jobs/spark_queue.log
```

Expected wall time (estimates, not measurements): gen_gold4 12 Qwen calls plus about 90 s of PNG rendering; gen_personal 14
calls; bank_ai 459 lines at the Ask-like 5-20 s on Glimmer is roughly 40 to 150 minutes; extraction on ledger4 is 120 documents
at about 24 s. Individual commands are in `evals/README.md`. After a run the lead commits `evals/gold/ledger4`, `evals/gold/personal`
and `evals/runs/{bank_ai,public_chat}`; skim `ledger4/catalogue.json` and `personal/*/names.json` first for a real brand that slipped
past the name filter.

## Risks and things to know

1. **Nothing ran against a live model.** The Qwen request body (`json_object` response format, `enable_thinking: false`) is copied from
   `gen_gold2.py`, the Glimmer call is the app's own. If vLLM rejects a field the generators fail fast (5 attempts per step, then
   a message) and resume from what is saved.
2. **`public_chat_eval` guesses the contract.** The route is being built elsewhere. Assumed: `POST /public/chat`, body
   `{"message": ...}`, reply text under `reply`/`answer`/`message`/`text`/... (JSON, SSE or plain), refusal = "contact the
   team|our team". Flags `--field`, `--refusal-regex` adapt; check the real route first. Expect first-run false failures on
   on-topic prompts where a correct answer paraphrases (my phrase groups are lenient but not psychic): tune `CASES`.
3. **bank_ai accuracy is relative to my expectation table**, so read the misses list before quoting a figure. `suggest_ai` returns
   `None` for every failure, so the failure kind is inferred from the recorded raw reply. The first call includes any cold-load time
   (`keep_alive` is 24h in the app).
4. **gen_gold4 PNGs** are 167-337 KB (median 262 KB); 31 of 120 exceed the 300 KB that `render_gold` enforces for the old set (the
   receipts are longer). They are not committed (`evals/runs/gold4_png/`, ignored). The extraction eval renders its own images anyway.
5. **Personal statements use fictional payees only**, so they cannot test knowledge of real brands, and the Starling layout's
   Spending Category is constant `GENERAL` (not leaking our categories). Bank holidays are 2026 England/Wales only.
6. **Queue.** `ledger2` is skipped on purpose (credit notes and part-paid invoices are not receipt-schema, `run_extraction`
   would mis-score them) and `ledger3` is not in the repo. The GPU is shared with the production runtime: `nice`/`ionice` protect
   CPU and disk only, so a long Qwen or Glimmer request can slow a live user; start it when quiet. Steps resume themselves, but
   `run_extraction` restarts from zero if it dies. A step whose server does not answer is skipped and the queue exits 1.
7. Bugs found by the tests and fixed: a resumed `bank_ai` run glued its first new row onto a half-written line; plan search
   initially could not satisfy the 3-purchase rule at N=60 (now an explicit error asking for about 100+ receipts).
8. `docs/REMAINING.md` still says bank-rule AI codings have only run on the stub; true until the lead runs `bank_ai` and
   updates it from `runs/bank_ai/report.md`.
