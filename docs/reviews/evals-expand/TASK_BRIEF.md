# Task: Expand the evaluation set with Qwen (local vLLM) and re-run the Glimmer extraction eval

Accnomos monorepo (public; UK English). Read first: `evals/gold/receipts/{README.md,manifest.json}`, `evals/gold/receipts/gen_gold.py`
(or `~/spark/accnomos/jobs/gen_gold.py` — same generator), `evals/harness/{render.py,run_extraction.py,judge.py}`, `evals/REPORT_*.md`.
A local OpenAI-compatible server is running at `http://127.0.0.1:8000/v1` (model id `qwen3.8-27b`, no key) — use it for **bulk
synthetic data only**; it is not a product model. Glimmer runs on Ollama at `http://127.0.0.1:11434` (`muse-glimmer:30b`).

## Deliverables
1. Generate **140 more gold documents** with Qwen (seeded, deterministic manifest): 40 purchase receipts (fuel, trade counters, cafés,
   parking), 30 purchase invoices (builders' merchants, subcontractors, software subscriptions), 30 sales invoices from the sample
   business "Bramblewood Joinery Ltd" (so the side-orientation logic is exercised), 15 utility/telecoms bills, 10 credit notes, 15 mixed
   edge cases (multi-rate VAT, zero-rated, reverse charge note, foreign currency with GBP total, handwritten-style totals, torn/faded).
   Every document carries the words "SAMPLE — FICTIONAL COMPANY"; all businesses, VAT numbers (valid checksum format but fictional),
   addresses and people are invented. Extend `manifest.json` with full gold fields (supplier, date, net/VAT/gross in pence, VAT code,
   side, VRN, line items) and render them with the existing renderer into messy variants.
2. Generate **6 bank statement CSVs** (3 formats: Barclays-, Starling- and Tide-style headers) that reconcile against ~70 % of the
   new documents, with realistic noise (card refs, rounding, split payments). Store under `evals/gold/bank/`.
3. Generate **20 mailbox fixtures** (`evals/gold/mail/*.json`): message metadata + attachment list referencing gold PDFs/PNGs, including
   decoys (newsletters with images, calendar invites, signatures) for the Outlook intake tests.
4. Re-run the extraction eval on the **full 200-doc** set with Glimmer (`run_extraction.py`), then the Claude judge if
   `ANTHROPIC_API_KEY` is present in the environment (it is: `~/.anthropic_key` + workspace header, see `judge.py`), and commit
   `evals/REPORT_glimmer_messy_200_<date>.md` with per-field accuracy, side accuracy, check-status distribution and the 10 worst cases
   with a one-line diagnosis each. Do not change the extraction code in this task; file findings in the report's "Suggested fixes".
5. Keep generated binaries small (PNG ≤ 300 KB each); do not commit anything over 2 MB. Update `evals/gold/receipts/README.md`.

Commit in small steps; do not push. Finish with `git log --oneline -8` and the headline numbers from the new report.
