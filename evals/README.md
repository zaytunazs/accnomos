# Evals

Synthetic gold sets (`gold/`), the harness that grades the product against them (`harness/`), offline tests (`tests/`)
and the committed reports (`runs/`, `REPORT_*.md`). Every document in a gold set is fictional and labelled
`SAMPLE — FICTIONAL COMPANY` (em dash, U+2014). The gold generators call **Qwen3.8-27B** (vLLM, `127.0.0.1:8000`) as a
test-data generator only; the product models are **Muse Glimmer 30B** (Ollama, `127.0.0.1:11434`) and Muse Spark.

```sh
cd evals && python -m pytest -q tests      # offline, no model; needs the repo's Python environment
cd evals && ruff check . && ruff format --check .
```

Existing evals are described in `docs/META_MODELS.md` and `gold/README.md` (`run_extraction`, `bank_match`, `ask_40`,
`mail_intake`, `bench_runtime`). The jobs below were added for the DGX Spark, which has both models running all the time.
Each has a way to try it without a model, and each was tested here only against stubs: **no real Glimmer or Qwen call
has been made by this code yet**.

## The Spark jobs

| Job | Model | What it produces | Offline try-out |
|---|---|---|---|
| `harness/bank_ai.py` | Glimmer | accuracy, refusals, invalid JSON and latency of the bank-rule AI coding (`suggest_ai`) over every gold bank line | `--dry-run`, `--stub` |
| `harness/cis_read.py` | Glimmer | per-field accuracy, check codes, latency and misses of the CIS reader (`read_cis_document` + code checks) over every gold CIS statement and reverse-charge invoice | `--dry-run`, `--stub` |
| `harness/property_docs.py` | Glimmer | category, property, amount and date accuracy of the generic extraction reader over the gold landlord statements and bills (no property-specific reader exists yet) | `--dry-run`, `--stub` |
| `gold/gen_gold4.py` | Qwen | `gold/ledger4/`: about 120 price-history receipts, five suppliers, six months, `expectations.json` | `--dry-run`, `--stub` |
| `gold/gen_personal.py` | Qwen | `gold/personal/NN_name/`: six months of a household's bank statement and `expectations.json` | `--dry-run`, `--stub` |
| `harness/public_chat_eval.py` | the chat route's model | pass rates for `POST /public/chat`: product facts, refusals, injections | `--dry-run`, `--stub` |
| `tools/spark_queue.sh` | both | runs the first three, then the extraction eval, one after another | `--dry-run` |

### `bank_ai`: does Glimmer code bank lines?

```sh
cd evals && python -m harness.bank_ai --dry-run            # 459 lines, expectations printed, nothing called
cd evals && python -m harness.bank_ai --stub               # the whole pipeline against a fake model
cd evals && python -m harness.bank_ai                      # Glimmer at http://localhost:11434, model muse-glimmer:30b
cd evals && python -m harness.bank_ai --base http://127.0.0.1:11434 --model muse-glimmer:30b --limit 40
```

Runs the real `app.bank_reconcile.suggest_ai` (its prompt, JSON schema, parsing and account / VAT-code validation) on
the hand-written and six two-month statements in `gold/bank/` and the ledger2 bank pairs (overlap removed). Writes
`runs/bank_ai/{results.jsonl, summary.json, report.md}`. One request at a time. Resumable (`results.jsonl`; `--fresh`
starts again). How the expected account is derived is in the module docstring: the gold document's category, the
statement kind, or an ordered keyword table, with sets of defensible accounts; lines with no expense account (money in,
HMRC, payroll, drawings, transfers) are asked but not scored.

### `gen_gold4`: price history across suppliers

```sh
python evals/gold/gen_gold4.py --dry-run                   # stub Qwen, plan checked, nothing written
python evals/gold/gen_gold4.py                             # 120 receipts, then PNGs to evals/runs/gold4_png/
python evals/gold/gen_gold4.py 150 --no-render             # more receipts, skip the PNGs
python evals/gold/gen_gold4.py --fresh                     # throw away the saved catalogue and start over
```

Qwen names the suppliers and products and writes each supplier's wording; code sets stock, pack sizes, prices, VAT,
dates and totals, and `expectations.json` (normalised ex-VAT unit price per supplier, cheapest supplier by latest price
and by mean, and a per-line "cheaper elsewhere" hint) is computed from the finished receipts. The catalogue is saved
after each Qwen step, so a stopped run resumes; receipts already on disk are kept. Feed the receipts to the extraction
eval with `python -m harness.run_extraction --mode local --messy --gold-dir gold/ledger4/receipts`.
The PNGs are not committed (`evals/runs/*` is ignored); the longest receipts are a little over the 300 KB that
`render_gold` allows for the older set.

### `gen_personal`: household statements

```sh
python evals/gold/gen_personal.py --dry-run
python evals/gold/gen_personal.py                          # 2 households, Starling layout
python evals/gold/gen_personal.py --households 4 --layout tide
```

Qwen names the payees; code fixes every amount, date and recurrence. `statement.csv` starts with the label on its own
line (the importer skips lines above the header) and reads through `accnomos_ledger.bank.parse_bank_csv`. 
`expectations.json` lists the recurring series (monthly, weekly, four-weekly; price rises; one cancelled, one started
late), the lookalikes that must not be flagged, the monthly committed total, category totals per month, and the
category of every row. Resumable per household and per Qwen batch.

### `public_chat_eval`: the public chat route

```sh
cd evals && python -m harness.public_chat_eval --dry-run
cd evals && python -m harness.public_chat_eval --stub                       # shows the report format
cd evals && python -m harness.public_chat_eval --base http://127.0.0.1:8780
```

81 prompts: 45 product questions answered in README.md / docs/ (each with the phrases a right answer needs, and the
HMRC ones must say *sandbox*), 6 the docs cannot answer (a good reply admits it and states no figure), 20 off-topic and
10 injection attempts that must get the "contact the team" reply. Any figure in an answer must be in the docs. The
route is being built elsewhere: the request/response shape assumed is at the top of the module (flags change the key
and refusal pattern). With no route (404/405) or nothing listening it stops with a clear message and exit code 2.
Writes `runs/public_chat/{report.md, result.json}`. Paced at 30 requests a minute (`--per-min`) because the runtime
rate-limits per IP.

### `tools/spark_queue.sh`: all of it, overnight

```sh
tools/spark_queue.sh --dry-run          # what would run
nohup tools/spark_queue.sh >/dev/null 2>&1 &     # on the Spark; follow with: tail -f ~/spark/accnomos/jobs/spark_queue.log
tools/spark_queue.sh --list             # which steps are done
tools/spark_queue.sh --only bank_ai     # one step;  --force runs a done step again;  --no-check skips the server probe
```

Order: `gen_gold4`, `gen_personal`, `bank_ai`, then `run_extraction` (Glimmer, messy) on each
`gold/ledger{2,3,4}/receipts` folder that exists, then `cis_read` and `property_docs` (both Glimmer).
`ledger2` has none (its credit notes and part-paid invoices use another schema that `run_extraction` does not score)
and `ledger3` is not in this repository, so both are skipped with a note; `ledger4` is picked up once `gen_gold4`
has run. Log: `~/spark/accnomos/jobs/spark_queue.log`; markers in `~/spark/accnomos/jobs/state/` (delete one to
re-run that step). Everything runs under `nice -n 19` and `ionice -c3`, one job at a time, and a step whose model
server does not answer is skipped (and tried again next run). The script never runs git, installs nothing, and writes
only under `evals/` (gold and runs) and the jobs folder. Set `SPARK_PYTHON` to the environment's interpreter if
`.venv/bin/python` in the checkout is not the one to use. The GPU is shared with the production runtime:
`nice` does not stop a long Qwen or Glimmer request from slowing a live user, so start it when the site is quiet.
