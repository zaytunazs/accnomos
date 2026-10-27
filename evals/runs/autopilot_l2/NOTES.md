## How this run was made, and what the numbers do not show

- **Code:** the numbers above are with the same-document condition in `app/autopilot.py` (commit 316618e). Before it,
  the dupes pass with the verifier on gave **21 false posts in 42 documents**: 21 of 32 posted receipts photographed
  again were posted a second time (a new photo has a new file hash, so the DUPLICATE check passed); the 10 identical
  files were caught by hash. The inbox pass was the same before and after (17 posted, 0 false). Those runs are in
  `before_tightening/`. The clean pass on the old code was stopped at a two-hour limit before it wrote its records
  (70 of 184 posted by then; not graded), so there is no before figure for clean.
- **Rules:** the seeded books share no supplier with the 25 inbox documents, so with only the rules from the posted
  history nothing in the inbox is posted (row *Seeded-history rules only*). The *regular* rules (one earlier bill per
  other supplier, approved with "Always do this") are what put documents within reach of Autopilot. 12 suppliers got
  no rule: 5 EUR invoices (approve refuses them) and 7 credit notes, where `approve()` fails with a pydantic
  `ValidationError` (negative debit) instead of an `ApprovalError`: a runtime bug, not fixed here.
- **Expected posts missed** come from misreadings that a check or the verifier catches, line detail that does not add
  up (ARITH_LINES / ARITH_TOTALS warnings), low model confidence, and fictional suppliers whose names normalise to the
  same key with different VAT numbers (e.g. "Northgate Timber & Hardware" and "… Supplies"; Autopilot refuses on the
  VAT number). A missed post only means the document waits in Review.
- **Verifier off:** with `VERIFIER=off` the pipeline adds no VERIFIER_AGREES check at all, so Autopilot can post on a
  single reading. `docs/AUTOPILOT.md` said the proposal then waits; that is true only when the verifier is on but
  cannot run (a warning). The docs now say what the code does; whether L2 should require a second reading is a product
  decision (in this run it removed no false post and cost expected posts).
- **Shards and timing:** the clean and messy passes were run as two shards of 100 (`--shard k/2`), each on fresh
  seeded books, so a document in the second half never sees a proposal from the first half (gold documents are
  distinct, so only the same-document condition could notice). Other work on the same machine used Ollama during
  the day, and from the verifier-on clean pass onwards two of these runs shared the GPU, so the times in the table
  above are inflated. The least disturbed measurement is the verifier-on inbox and dupes run on the old code
  (`before_tightening/on_inbox_dupes.log`, 67 documents): **26.1 s mean, 26.2 s median, 34.9 s max per document**,
  one scan of one document including the verifier's reading (the same-document condition adds no model call).
- **Grading:** a 001-060 `no_vat_number` receipt charging no VAT is expected to be proposed (the seller is not VAT
  registered; `run_extraction.expected_status` says needs a look, which docs/reviews/verifier/REVIEW.md flags).
- **Handwritten:** only 4 gold documents are handwritten, torn or faded (8 renders per mode); too few for a rate.
