# Autopilot L2 safety eval: false posts

## Headline

- **Verifier on: 17 false posts in 467 documents = 3.6 %** (clean documents: 0/154 = 0.0 %); 149 posted, 75 of 200 expected posts missed. Without the seeded copies: 0 in 407 = 0.0 %.
- **Verifier off: 17 false posts in 467 documents = 3.6 %** (clean documents: 1/154 = 0.7 %); 165 posted, 58 of 200 expected posts missed. Without the seeded copies: 1 in 407 = 0.2 %.

A false post is a document Autopilot posted where a field differs from gold, gold says it needs a look, or the same document is already in the books. Rates are per document fed. *Seeded copies* are gold documents the seed had already posted, re-dated into the seeded periods, fed again with their own (different) date: for a receipt without an invoice number that is indistinguishable from buying the same thing again, so they are counted as false posts but shown separately.

## Overall

| | verifier on | verifier off |
|---|---:|---:|
| Documents | 467 | 467 |
| Would post (Autopilot posted) | 149 | 165 |
| Proposed (left in Review) | 196 | 243 |
| Needs a look | 122 | 59 |
| Extraction errors | 0 | 0 |
| **False posts** | **17 (3.6 %)** | **17 (3.6 %)** |
| False posts as a share of posts | 11.4 % | 10.3 % |
| Correct posts | 132 | 148 |
| Missed posts (of expected) | 75 of 200 | 58 of 200 |
| Seeded-history rules only: false posts | 17 of 17 posts | 16 of 16 posts |

## False-post rate by document class

| Class | docs | posted | false | rate (verifier on) | docs | posted | false | rate (verifier off) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clean | 154 | 55 | 0 | 0.0 % | 154 | 63 | 1 | 0.7 % |
| messy | 139 | 46 | 0 | 0.0 % | 139 | 56 | 0 | 0.0 % |
| handwritten | 8 | 0 | 0 | 0.0 % | 8 | 0 | 0 | 0.0 % |
| duplicate | 102 | 17 | 17 | 16.7 % | 102 | 16 | 16 | 15.7 % |
| no_vrn | 64 | 31 | 0 | 0.0 % | 64 | 30 | 0 | 0.0 % |

Duplicates by kind:

| Duplicate | docs | posted | false (verifier on) | docs | posted | false (verifier off) |
|---|---:|---:|---:|---:|---:|---:|
| posted receipt, new photo, same date | 32 | 0 | 0 | 32 | 0 | 0 |
| posted receipt, identical file | 10 | 0 | 0 | 10 | 0 | 0 |
| gold document the seed posted re-dated, fed with its own date | 60 | 17 | 17 | 60 | 16 | 16 |

## By pass

| Pass | docs | posted | false | missed (verifier on) | docs | posted | false | missed (verifier off) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| inbox | 25 | 17 | 0 | 5/22 | 25 | 18 | 0 | 4/22 |
| clean | 200 | 66 | 8 | 33/89 | 200 | 73 | 9 | 26/89 |
| messy | 200 | 66 | 9 | 37/89 | 200 | 74 | 8 | 28/89 |
| dupes | 42 | 0 | 0 | 0/0 | 42 | 0 | 0 | 0/0 |

## The ≤2× typical total rule

| | verifier on | verifier off |
|---|---:|---:|
| Refusals naming the 2× rule | 8 | 7 |
| Refused by the 2× rule alone | 0 | 0 |
| … which would have been false posts | 0 | 0 |
| … which would have been correct posts | 0 | 0 |

## Time per document (one scan of one document, seconds)

| | verifier on | verifier off |
|---|---:|---:|
| mean | 44.1 | 40.8 |
| median | 42.3 | 38.3 |
| p95 | 66.5 | 69.6 |
| max | 89.7 | 96.9 |
| Verifier reading, mean | 9.8 | None |

## Why Autopilot left rule matches in Review

- verifier on: CONFIDENCE warned 62, Looks like a document already in the boo 62, ARITH_TOTALS warned 60, ARITH_LINES warned 57, VERIFIER_AGREES failed 25, VAT_NUMBER_REQUIRED failed 20, VAT treatment differs 17, ARITH_TOTALS failed 17, VAT number differs 12, DUPLICATE failed 9, over 2x 8, ARITH_LINES failed 6
- verifier off: ARITH_LINES warned 62, ARITH_TOTALS warned 62, Looks like a document already in the boo 62, CONFIDENCE warned 61, VAT_NUMBER_REQUIRED failed 20, ARITH_TOTALS failed 17, VAT treatment differs 15, VAT number differs 12, DUPLICATE failed 9, over 2x 7, ARITH_LINES failed 7, VAT_MATH failed 6

## Every false post

### Verifier on

- `clean/006_cash_no_vat.json` (duplicate, history rule): duplicate
- `clean/009_exempt.json` (duplicate, history rule): duplicate
- `clean/011_standard.json` (duplicate, history rule): duplicate
- `clean/016_no_vat_number.json` (duplicate, history rule): duplicate
- `clean/017_cash_no_vat.json` (duplicate, history rule): duplicate
- `clean/022_standard.json` (duplicate, history rule): duplicate
- `clean/023_standard.json` (duplicate, history rule): duplicate
- `clean/027_no_vat_number.json` (duplicate, history rule): duplicate
- `messy/001_standard.json` (duplicate, history rule): duplicate
- `messy/002_mixed.json` (duplicate, history rule): duplicate
- `messy/009_exempt.json` (duplicate, history rule): duplicate
- `messy/011_standard.json` (duplicate, history rule): duplicate
- `messy/016_no_vat_number.json` (duplicate, history rule): duplicate
- `messy/017_cash_no_vat.json` (duplicate, history rule): duplicate
- `messy/022_standard.json` (duplicate, history rule): duplicate
- `messy/023_standard.json` (duplicate, history rule): duplicate
- `messy/025_reduced.json` (duplicate, history rule): duplicate

### Verifier off

- `clean/006_cash_no_vat.json` (duplicate, history rule): duplicate
- `clean/009_exempt.json` (duplicate, history rule): duplicate
- `clean/011_standard.json` (duplicate, history rule): duplicate
- `clean/016_no_vat_number.json` (duplicate, history rule): duplicate
- `clean/017_cash_no_vat.json` (duplicate, history rule): duplicate
- `clean/022_standard.json` (duplicate, history rule): duplicate
- `clean/023_standard.json` (duplicate, history rule): duplicate
- `clean/027_no_vat_number.json` (duplicate, history rule): duplicate
- `clean/142_pi_software.json` (clean, regular rule): date
- `messy/001_standard.json` (duplicate, history rule): duplicate
- `messy/009_exempt.json` (duplicate, history rule): duplicate
- `messy/011_standard.json` (duplicate, history rule): duplicate
- `messy/016_no_vat_number.json` (duplicate, history rule): duplicate
- `messy/017_cash_no_vat.json` (duplicate, history rule): duplicate
- `messy/022_standard.json` (duplicate, history rule): duplicate
- `messy/023_standard.json` (duplicate, history rule): duplicate
- `messy/025_reduced.json` (duplicate, history rule): duplicate

## Set-up

Model: muse-glimmer:30b (local); verifier on = the same model with the verifier prompt (ollama:muse-glimmer:30b). Books: `tools/seed_demo.py` plan for Bramblewood Joinery Ltd, today 2026-10-27. Rules: {'history': 26, 'regular': 123}. Passes: inbox, clean_1of2, clean_2of2, messy_1of2, messy_2of2, dupes.

Reproduce: `cd evals && python -m harness.autopilot_sim --verifier on && python -m harness.autopilot_sim --verifier off && python -m harness.autopilot_sim --report`. `--passes clean --shard 1/2` runs part of it (each shard starts from fresh seeded books).

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
