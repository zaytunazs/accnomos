# Review: `claude/verifier`

Brief: `TASK_BRIEF.md` (Verifier agent: independent second reading, compared per field in code).
Reviewed 27 Oct 2026 by the second agent on the branch.

## What was checked

- `pytest -q` in `services/runtime` (114 passed after fixes), `services/hmrc-relay` (39 passed),
  `packages/ledger` (15 passed), `packages/connectors` (17 passed).
- `cd apps/web && pnpm run build`: compiles, all routes prerender.
- Read the full diff: `app/ai/verify.py`, the pipeline routing, schemas, the web chip and diff table, the `--verify`
  harness, the eval report, README and `.env.example`.
- Checked the committed report against the run artefact `evals/runs/verifier-20/summary.json` (git-ignored). The
  numbers match: 94% all-field agreement, 16/1/0/1 doc outcomes, 95% → 90% decision accuracy.
- Product rules: the model never merges values (the code compares, and the extracted document is untouched); local mode
  never leaves the machine even when a Baseten key is set; the user's Meta key is never sent to Baseten; `.env.example`
  has empty values only; nothing is written server-side; the sample chip is labelled "(sample)".

## What I fixed

- `6d0ee1b`: added `services/runtime/conftest.py`. The shared `.venv` has `accnomos-runtime` installed editable from
  another lane, so plain `pytest -q` imported that lane's `app` and failed to collect `test_verify.py`.
- `90049f0`: `verify()` promised never to raise, but a 200 response with a non-JSON body or no `choices` raised
  `KeyError`/`ValueError` and failed the whole upload. Those responses now count as a verifier error (a warning,
  never agreement). Name normalisation dropped "uk"/"co"/"company" anywhere in a name, so "UK Fuels" agreed with
  "Fuels". Legal suffixes are now dropped only at the end. Added fake-transport tests: the Baseten request goes to the
  right URL with the owner's key, the user's key is never in it, the first reading is never in the prompt, and
  malformed or 401 responses give an error rather than a crash.
- `8e915c5`: the web label claimed "Glimmer 30B" for any local verifier model; it now shows the real model. The README
  and the card said "you choose" between readings, but the card only offers Approve or Reject. Reworded so it does not
  promise more than that.
- `aaf4012`: the privacy page's third-party list left out Baseten, which receives document images in key mode when the
  owner sets `BASETEN_API_KEY`. Added it.

## What remains

- The Baseten model slug `meta-models/muse-spark-open` is still unconfirmed against Baseten's docs (the code says so).
  No real Baseten or Meta API verifier call has been made; both paths are unit-tested with fakes only.
- The eval covers 20 messy synthetic receipts with Glimmer verifying Glimmer: 0 extra catches and 1 false alarm on a
  mixed-rate receipt (the verifier reads the standard-rated subtotal as net). The catch rate is not yet measured; run
  the full 60 and real photos. The verifier prompt needs a mixed-rate hint.
- The card cannot adopt the second reading. On disagreement the user can only approve the first reading or reject the
  proposal; there is no Edit in the live review.
- All six fields are decisive (the brief listed supplier, date, total and VAT). Net and VAT number disagreements also
  go to *Needs a look*. This is stricter than the brief and left as is.
- The local venv points `accnomos-ledger`/`accnomos-connectors` at another lane's checkout. This branch does not touch
  those packages, so runtime tests are unaffected, but reinstall editable from this checkout before merging other work.
- Harness rule issues noted in the report (`015_zero` gold VAT number not printed; `016_no_vat_number` with £0 VAT
  expected to need a look) are unrelated to the verifier and not fixed here.

## How to verify by hand

Run `cd services/runtime && pytest -q`. Start the runtime in local mode with Ollama serving `muse-glimmer:30b` and the
web app (`cd apps/web && pnpm dev`). Connect a OneDrive and drop a clear receipt into `00 Inbox`. On `/review` the card
should say *Verifier agrees · all 6 fields match — muse-glimmer:30b*. Then drop a mixed-rate receipt (or any receipt
where you expect a misread). If the readings differ, the proposal should sit in *Needs a look* with an amber table
showing both readings, and the extracted values should be unchanged. With `VERIFIER=off` set on the runtime, the card
should say *Second reading not run*. Optionally run
`cd evals && python -m harness.run_extraction --mode local --limit 20 --messy --verify` and compare with
`evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md`.
