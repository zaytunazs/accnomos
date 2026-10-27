# Autopilot L2 safety eval: false posts

## Headline

- **Verifier on: 21 false posts in 67 documents = 31.3 %** (clean documents: 0/15 = 0.0 %); 38 posted, 5 of 22 expected posts missed.

A false post is a document Autopilot posted where a field differs from gold, gold says it needs a look, or the same document is already in the books. Rates are per document fed.

## Overall

| | verifier on |
|---|---:|
| Documents | 67 |
| Would post (Autopilot posted) | 38 |
| Proposed (left in Review) | 12 |
| Needs a look | 17 |
| Extraction errors | 0 |
| **False posts** | **21 (31.3 %)** |
| False posts as a share of posts | 55.3 % |
| Correct posts | 17 |
| Missed posts (of expected) | 5 of 22 |
| Seeded-history rules only: false posts | 21 of 21 posts |

## False-post rate by document class

| Class | docs | posted | false | rate (verifier on) |
|---|---:|---:|---:|---:|
| clean | 15 | 8 | 0 | 0.0 % |
| messy | 0 | 0 | 0 | — |
| handwritten | 0 | 0 | 0 | — |
| duplicate | 42 | 21 | 21 | 50.0 % |
| no_vrn | 10 | 9 | 0 | 0.0 % |

Duplicates by kind:

| Duplicate | docs | posted | false (verifier on) |
|---|---:|---:|---:|
| posted receipt, new photo, same date | 32 | 21 | 21 |
| posted receipt, identical file | 10 | 0 | 0 |
| gold document the seed posted re-dated, fed with its own date | 0 | 0 | 0 |

## By pass

| Pass | docs | posted | false | missed (verifier on) |
|---|---:|---:|---:|---:|
| inbox | 25 | 17 | 0 | 5/22 |
| dupes | 42 | 21 | 21 | 0/0 |

## The ≤2× typical total rule

| | verifier on |
|---|---:|
| Refusals naming the 2× rule | 1 |
| Refused by the 2× rule alone | 0 |
| … which would have been false posts | 0 |
| … which would have been correct posts | 0 |

## Time per document (one scan of one document, seconds)

| | verifier on |
|---|---:|
| mean | 26.1 |
| median | 26.2 |
| p95 | 34.1 |
| max | 34.9 |
| Verifier reading, mean | 7.3 |

## Why Autopilot left rule matches in Review

- verifier on: CONFIDENCE warned 9, DUPLICATE failed 9, ARITH_LINES warned 7, ARITH_TOTALS warned 6, VAT treatment differs 4, ARITH_TOTALS failed 3, VAT number differs 2, VERIFIER_AGREES failed 2, over 2x 1, VAT_NUMBER_FORMAT failed 1, DATE_IN_PERIOD warned 1

## Every false post

### Verifier on

- `dupes/photo/003_reduced.json@2026-04-08` (duplicate, history rule): duplicate
- `dupes/photo/036_reduced.json@2026-04-11` (duplicate, history rule): duplicate
- `dupes/photo/002_mixed.json@2026-04-12` (duplicate, history rule): duplicate
- `dupes/photo/014_reduced.json@2026-05-09` (duplicate, history rule): duplicate
- `dupes/photo/007_full_invoice.json@2026-05-12` (duplicate, history rule): duplicate
- `dupes/photo/047_reduced.json@2026-05-12` (duplicate, history rule): duplicate
- `dupes/photo/009_exempt.json@2026-05-28` (duplicate, history rule): duplicate
- `dupes/photo/011_standard.json@2026-06-04` (duplicate, history rule): duplicate
- `dupes/photo/012_standard.json@2026-06-12` (duplicate, history rule): duplicate
- `dupes/photo/058_reduced.json@2026-06-13` (duplicate, history rule): duplicate
- `dupes/photo/016_no_vat_number.json@2026-07-05` (duplicate, history rule): duplicate
- `dupes/photo/003_reduced.json@2026-07-08` (duplicate, history rule): duplicate
- `dupes/photo/017_cash_no_vat.json@2026-07-12` (duplicate, history rule): duplicate
- `dupes/photo/018_full_invoice.json@2026-07-20` (duplicate, history rule): duplicate
- `dupes/photo/020_exempt.json@2026-08-04` (duplicate, history rule): duplicate
- `dupes/photo/014_reduced.json@2026-08-09` (duplicate, history rule): duplicate
- `dupes/photo/022_standard.json@2026-08-12` (duplicate, history rule): duplicate
- `dupes/photo/023_standard.json@2026-08-20` (duplicate, history rule): duplicate
- `dupes/photo/026_zero.json@2026-09-04` (duplicate, history rule): duplicate
- `dupes/photo/027_no_vat_number.json@2026-09-11` (duplicate, history rule): duplicate
- `dupes/photo/058_reduced.json@2026-09-13` (duplicate, history rule): duplicate

## Set-up

Model: muse-glimmer:30b (local); verifier on = the same model with the verifier prompt (ollama:muse-glimmer:30b). Books: `tools/seed_demo.py` plan for Bramblewood Joinery Ltd, today 2026-10-27. Rules: {'history': 26, 'regular': 123}. Passes: inbox, dupes.

Reproduce: `cd evals && python -m harness.autopilot_sim --verifier on && python -m harness.autopilot_sim --verifier off && python -m harness.autopilot_sim --report`.
