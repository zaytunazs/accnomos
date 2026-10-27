# Autopilot L2 safety eval: false posts

## Headline

- **Verifier on: 17 false posts in 467 documents = 3.6 %** (clean documents: 0/154 = 0.0 %); 149 posted, 75 of 200 expected posts missed.
- **Verifier off: 17 false posts in 367 documents = 4.6 %** (clean documents: 1/154 = 0.7 %); 126 posted, 42 of 148 expected posts missed.

A false post is a document Autopilot posted where a field differs from gold, gold says it needs a look, or the same document is already in the books. Rates are per document fed.

## Overall

| | verifier on | verifier off |
|---|---:|---:|
| Documents | 467 | 367 |
| Would post (Autopilot posted) | 149 | 126 |
| Proposed (left in Review) | 196 | 196 |
| Needs a look | 122 | 45 |
| Extraction errors | 0 | 0 |
| **False posts** | **17 (3.6 %)** | **17 (4.6 %)** |
| False posts as a share of posts | 11.4 % | 13.5 % |
| Correct posts | 132 | 109 |
| Missed posts (of expected) | 75 of 200 | 42 of 148 |
| Seeded-history rules only: false posts | 17 of 17 posts | 16 of 16 posts |

## False-post rate by document class

| Class | docs | posted | false | rate (verifier on) | docs | posted | false | rate (verifier off) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clean | 154 | 55 | 0 | 0.0 % | 154 | 63 | 1 | 0.7 % |
| messy | 139 | 46 | 0 | 0.0 % | 55 | 18 | 0 | 0.0 % |
| handwritten | 8 | 0 | 0 | 0.0 % | 5 | 0 | 0 | 0.0 % |
| duplicate | 102 | 17 | 17 | 16.7 % | 102 | 16 | 16 | 15.7 % |
| no_vrn | 64 | 31 | 0 | 0.0 % | 51 | 29 | 0 | 0.0 % |

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
| messy | 200 | 66 | 9 | 37/89 | 100 | 35 | 8 | 12/37 |
| dupes | 42 | 0 | 0 | 0/0 | 42 | 0 | 0 | 0/0 |

## The ≤2× typical total rule

| | verifier on | verifier off |
|---|---:|---:|
| Refusals naming the 2× rule | 8 | 5 |
| Refused by the 2× rule alone | 0 | 0 |
| … which would have been false posts | 0 | 0 |
| … which would have been correct posts | 0 | 0 |

## Time per document (one scan of one document, seconds)

| | verifier on | verifier off |
|---|---:|---:|
| mean | 44.1 | 38.9 |
| median | 42.3 | 36.7 |
| p95 | 66.5 | 59.2 |
| max | 89.7 | 87.5 |
| Verifier reading, mean | 9.8 | None |

## Why Autopilot left rule matches in Review

- verifier on: CONFIDENCE warned 62, Looks like a document already in the boo 62, ARITH_TOTALS warned 60, ARITH_LINES warned 57, VERIFIER_AGREES failed 25, VAT_NUMBER_REQUIRED failed 20, VAT treatment differs 17, ARITH_TOTALS failed 17, VAT number differs 12, DUPLICATE failed 9, over 2x 8, ARITH_LINES failed 6
- verifier off: Looks like a document already in the boo 62, ARITH_LINES warned 51, ARITH_TOTALS warned 48, CONFIDENCE warned 40, ARITH_TOTALS failed 12, VAT_NUMBER_REQUIRED failed 12, VAT treatment differs 11, VAT number differs 10, DUPLICATE failed 9, over 2x 5, ARITH_LINES failed 4, VAT_NUMBER_FORMAT failed 3

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

Reproduce: `cd evals && python -m harness.autopilot_sim --verifier on && python -m harness.autopilot_sim --verifier off && python -m harness.autopilot_sim --report`.
